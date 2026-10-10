"""Validate RQ1-B aggregate outputs, privacy boundaries, and Git scope."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from . import DOC_FILENAMES, HERE, ROOT, SAFE_JSON_FILENAMES, STARTING_HEAD
from .finalise_rq1b_results import (
    CHECKSUM_PATH,
    DOC_ROOT,
    RUN_BUNDLE_PATH,
    build_artifacts,
    check_byte_identical,
)
from .governed_data_loader import (
    authorised_path,
    governed_source_texts,
    load_governed_bundle,
    reject_final_gold_path,
    sha256_file,
    verify_protected_sources_unchanged,
)


class ValidationError(RuntimeError):
    pass


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def verify_output_checksums() -> dict[str, Any]:
    if not CHECKSUM_PATH.is_file():
        raise ValidationError("RQ1-B output checksum manifest is missing")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        CHECKSUM_PATH.read_text(encoding="utf-8").splitlines(), 1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValidationError(f"checksum syntax failed at line {line_number}")
        expected, relative = match.groups()
        if relative in seen:
            raise ValidationError("duplicate checksum member")
        seen.add(relative)
        path = authorised_path(reject_final_gold_path(relative))
        if not path.is_file() or path.is_symlink():
            raise ValidationError("checksum member missing or not regular")
        actual = sha256_file(path)
        if actual != expected:
            raise ValidationError("output checksum mismatch")
        results.append(
            {
                "relative_path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": True,
            }
        )
    required = {
        *(f"evaluation/learned_intent_ranking/lr4b_dev/{name}" for name in SAFE_JSON_FILENAMES),
        *(f"docs/thesis_mainline/rq1/{name}" for name in DOC_FILENAMES),
    }
    if not required <= seen:
        raise ValidationError("required deliverable absent from checksum manifest")
    return {"entry_count": len(results), "all_match": True, "entries": results}


def verify_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"python_file_count": len(paths), "all_ast_valid": True}


def _tracked_deliverable_paths() -> list[Path]:
    return [
        *(HERE / name for name in SAFE_JSON_FILENAMES),
        CHECKSUM_PATH,
        *sorted(HERE.glob("*.py")),
        *(DOC_ROOT / name for name in DOC_FILENAMES),
    ]


def scan_for_governed_text(bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    governed = bundle or load_governed_bundle()
    source_strings = {
        value
        for value in governed_source_texts(governed)
        if len(value.encode("utf-8")) >= 24
    }
    paths = _tracked_deliverable_paths()
    leaks: list[str] = []
    for path in paths:
        content = path.read_bytes() if path.is_file() else b""
        if any(value.encode("utf-8") in content for value in source_strings):
            leaks.append(str(path.relative_to(ROOT)))
    if leaks:
        raise ValidationError("governed natural-language representation leaked")
    return {
        "source_string_count_checked": len(source_strings),
        "deliverable_file_count_checked": len(paths),
        "governed_text_leak_count": 0,
    }


def verify_local_artifact_boundaries() -> dict[str, Any]:
    paths = [
        "evaluation/learned_intent_ranking/lr4b_dev/local_artifacts/embeddings/",
        "evaluation/learned_intent_ranking/lr4b_dev/local_artifacts/pair_ledgers/",
        "evaluation/learned_intent_ranking/lr4b_dev/local_artifacts/prediction_ledgers/",
        "evaluation/learned_intent_ranking/lr4b_dev/local_artifacts/training_histories/",
        "evaluation/learned_intent_ranking/lr4b_dev/checkpoints/",
        "evaluation/learned_intent_ranking/lr4b_dev/results/",
        "evaluation/learned_intent_ranking/lr4b_dev/tmp/",
    ]
    for relative in paths:
        ignored = _git("check-ignore", "-q", relative)
        if ignored.returncode != 0:
            raise ValidationError("required local artifact path is not ignored")
        tracked = _git("ls-files", "--", relative)
        if tracked.returncode != 0 or tracked.stdout.strip():
            raise ValidationError("local artifact path is tracked")
    return {"path_count": len(paths), "all_ignored": True, "tracked_file_count": 0}


def verify_staged_scope() -> dict[str, Any]:
    result = _git("diff", "--cached", "--name-only", "-z")
    if result.returncode != 0:
        raise ValidationError("cannot inspect staged content")
    names = [value.decode("utf-8") for value in result.stdout.split(b"\0") if value]
    allowed = []
    forbidden = []
    for name in names:
        in_scope = (
            name == ".gitignore"
            or name.startswith("docs/thesis_mainline/rq1/RQ1B_")
            or name.startswith("evaluation/learned_intent_ranking/lr4b_dev/")
        )
        local = any(
            segment in name
            for segment in (
                "/local_artifacts/",
                "/checkpoints/",
                "/results/",
                "/tmp/",
            )
        )
        (allowed if in_scope and not local else forbidden).append(name)
    if forbidden:
        raise ValidationError("staged path is outside the RQ1-B allowlist")
    return {
        "staged_file_count": len(names),
        "staged_scope_pass": True,
        "staged_scan_performed": bool(names),
        "paths": allowed,
    }


def validate(run_bundle_path: Path = RUN_BUNDLE_PATH) -> dict[str, Any]:
    if not run_bundle_path.is_file():
        raise ValidationError("local run bundle is missing")
    run_bundle = json.loads(run_bundle_path.read_text(encoding="utf-8"))
    if run_bundle.get("run_count") != 20:
        raise ValidationError("20-run matrix is incomplete")
    safe_outputs = {name: json.loads((HERE / name).read_text()) for name in SAFE_JSON_FILENAMES}
    if any(value.get("final_gold_accessed") is not False for value in safe_outputs.values()):
        raise ValidationError("safe output final-gold invariant failed")
    if safe_outputs["rq1b_validation_report_v1.json"].get("overall_status") != "PASS":
        raise ValidationError("validation report is not PASS")
    if safe_outputs["rq1b_scenario_selection_v1.json"].get("selected_scenario") not in {
        "V0",
        "V1",
        "V2",
        "V3",
    }:
        raise ValidationError("scenario selection is invalid")
    artifacts = build_artifacts(run_bundle)
    check_byte_identical(artifacts)
    result = {
        "schema_version": "rq1b-validator-execution-v1",
        "status": "PASS",
        "output_checksums": verify_output_checksums(),
        "python_ast": verify_python_ast(),
        "governed_text_scan": scan_for_governed_text(),
        "local_artifact_boundary": verify_local_artifact_boundaries(),
        "staged_content": verify_staged_scope(),
        "protected_sources": verify_protected_sources_unchanged(),
        "deterministic_finalisation": True,
        "experiment_run_count": 20,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-bundle", type=Path, default=RUN_BUNDLE_PATH)
    args = parser.parse_args(argv)
    try:
        result = validate(args.run_bundle)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValidationError, ValueError, OSError, json.JSONDecodeError):
        print(
            json.dumps(
                {
                    "status": "BLOCKED_RQ1_B_TEST_FAILURE",
                    "raw_text_emitted": False,
                    "final_gold_accessed": False,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
