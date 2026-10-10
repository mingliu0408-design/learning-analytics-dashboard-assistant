"""RQ2-C1 AST, governance, output, isolation, and review-package validators."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable
import zipfile

from . import (
    DOC_FILENAMES,
    DOC_ROOT,
    EXPECTED_PROTECTED_COUNT,
    EXPECTED_PROTECTED_SHA256,
    HERE,
    LOCAL_ROOT,
    RESULT_BRANCH,
    ROOT,
    SAFE_JSON_FILENAMES,
    STARTING_HEAD,
    sha256_file,
)
from .finalise_rq2c1 import (
    CHECKSUM_NAME,
    expected_review_members,
    parse_output_checksums,
)
from .starting_state import assert_partition_access_allowed, protected_manifest


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(paths)}


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failed = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if failed:
        raise RuntimeError("BLOCKED_RQ2_C1_TEST_FAILURE")
    return {"status": "PASS", "checksum_count": len(values), "failure_count": 0}


def validate_safe_outputs() -> dict[str, Any]:
    missing = [name for name in SAFE_JSON_FILENAMES if not (HERE / name).is_file()]
    missing.extend(name for name in DOC_FILENAMES if not (DOC_ROOT / name).is_file())
    if missing:
        raise RuntimeError("BLOCKED_RQ2_C1_TEST_FAILURE")
    safety = json.loads((HERE / "rq2c1_hard_safety_validation_v1.json").read_text())
    validation = json.loads((HERE / "rq2c1_validation_report_v1.json").read_text())
    if safety["status"] != "PASS" or safety["hard_failure_count"] != 0 or validation["status"] != "PASS":
        raise RuntimeError("BLOCKED_RQ2_C1_HARD_SAFETY_VIOLATION")
    return {"status": "PASS", "safe_json_count": len(SAFE_JSON_FILENAMES), "doc_count": len(DOC_FILENAMES)}


def _governed_strings() -> tuple[str, ...]:
    strings: set[str] = set()
    fixture = ROOT / (
        "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
        "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
    )
    for line in fixture.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        value = row.get("input_event_or_query") or {}
        if isinstance(value.get("text"), str):
            strings.add(value["text"])
        for item in row.get("initial_store_state") or ():
            if isinstance(item.get("raw_content"), str):
                strings.add(item["raw_content"])
    gold_paths = (
        "evaluation/capability_routing_v1_r2b/local_gold/authentic_codebook_calibration_gold_v1.jsonl",
        "evaluation/capability_routing_v1_r2b/local_gold/synthetic_coverage_stress_gold_v1.jsonl",
        "evaluation/capability_routing_v1_r2b/local_gold/authentic_context_missing_qualitative_registry_v1.jsonl",
    )
    for relative in gold_paths:
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for key in ("current_query",):
                if isinstance(row.get(key), str):
                    strings.add(row[key])
            for turn in row.get("necessary_conversation_history") or ():
                if isinstance(turn, dict) and isinstance(turn.get("content"), str):
                    strings.add(turn["content"])
    return tuple(sorted(value for value in strings if len(value) >= 12))


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    if paths is None:
        values = [ROOT / relative for relative in parse_output_checksums()]
        values.append(HERE / CHECKSUM_NAME)
    else:
        values = list(paths)
    governed = _governed_strings()
    leaks: list[str] = []
    for path in values:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value in text for value in governed):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RuntimeError("BLOCKED_RQ2_C1_EXPECTED_FIELD_LEAKAGE")
    return {"status": "PASS", "governed_string_count": len(governed), "leak_count": 0}


def protected_source_comparison() -> dict[str, Any]:
    result = protected_manifest()
    if result["protected_file_count"] != EXPECTED_PROTECTED_COUNT or result["protected_manifest_sha256"] != EXPECTED_PROTECTED_SHA256:
        raise RuntimeError("BLOCKED_RQ2_C1_PROTECTED_SOURCE_MUTATED")
    return result


def validate_local_artifacts_ignored() -> dict[str, Any]:
    command = subprocess.run(
        ["git", "check-ignore", "-q", str(LOCAL_ROOT.relative_to(ROOT)) + "/probe"],
        cwd=ROOT,
        check=False,
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", str(LOCAL_ROOT.relative_to(ROOT))], cwd=ROOT, text=True
    ).strip()
    if command.returncode != 0 or tracked:
        raise RuntimeError("BLOCKED_RQ2_C1_TEST_FAILURE")
    return {"status": "PASS", "ignored": True, "tracked_file_count": 0}


def staged_allowlist() -> dict[str, Any]:
    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True
    ).splitlines()
    invalid = [
        value
        for value in staged
        if value != ".gitignore"
        and not value.startswith("evaluation/capability_routing_rq2c1_v1/")
        and not value.startswith("docs/thesis_mainline/rq2/RQ2C1_")
    ]
    if invalid or any("local_artifacts/" in value for value in staged):
        raise RuntimeError("BLOCKED_RQ2_C1_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    branch = git("branch", "--show-current")
    count = int(git("rev-list", "--count", f"{STARTING_HEAD}..HEAD"))
    if branch != RESULT_BRANCH or count not in ({1} if require_commit else {0, 1}) or git("remote") or git("tag", "--list"):
        raise RuntimeError("BLOCKED_RQ2_C1_GIT_FAILURE")
    return {"status": "PASS", "branch": branch, "relative_commit_count": count, "remote_count": 0, "tag_count": 0}


def validate_review_zip(path: Path) -> dict[str, Any]:
    expected = set(expected_review_members())
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if archive.testzip() is not None or names != expected:
            raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
        referenced = set(parse_output_checksums())
        if not referenced <= names:
            raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
        review_manifest = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode("utf-8")
        checks = dict(line.split("  ", 1) for line in review_manifest.splitlines())
        for name, digest in checks.items():
            if __import__("hashlib").sha256(archive.read(digest)).hexdigest() != name:
                raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
    return {"status": "PASS", "member_count": len(expected), "referenced_output_count": len(parse_output_checksums())}


def validate_all() -> dict[str, Any]:
    return {
        "python_ast": validate_python_ast(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "local_artifacts": validate_local_artifacts_ignored(),
        "staged_allowlist": staged_allowlist(),
        "git": validate_git_state(),
        "track_a_rejected": _partition_rejected("TRACK_A"),
        "track_b_rejected": _partition_rejected("TRACK_B"),
        "status": "PASS",
    }


def _partition_rejected(partition: str) -> bool:
    try:
        assert_partition_access_allowed(partition)
    except PermissionError:
        return True
    return False


if __name__ == "__main__":
    print(json.dumps(validate_all(), indent=2, sort_keys=True))
