"""Validate the RQ1-A-R1 supplement without model or final-gold access."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
        compute_protected_source_fingerprint,
    )
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        authorised_project_path,
        canonical_json_bytes,
        sha256_file,
    )
    from evaluation.learned_intent_ranking.lr4b_r1.build_rq1a_r1_supplement import (
        CODE_FILENAMES,
        DOC_PATHS,
        OUTPUT_CHECKSUM_PATH,
        R1_ROOT,
        SAFE_JSON_FILENAMES,
        STARTING_HEAD,
        TARGET_BRANCH,
        build_supplement,
        expected_checksum_paths,
        supplement_bundle_fingerprint,
    )
else:
    from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
        compute_protected_source_fingerprint,
    )
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        authorised_project_path,
        canonical_json_bytes,
        sha256_file,
    )
    from .build_rq1a_r1_supplement import (
        CODE_FILENAMES,
        DOC_PATHS,
        OUTPUT_CHECKSUM_PATH,
        R1_ROOT,
        SAFE_JSON_FILENAMES,
        STARTING_HEAD,
        TARGET_BRANCH,
        build_supplement,
        expected_checksum_paths,
        supplement_bundle_fingerprint,
    )


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _allowed_new_path(relative_path: str) -> bool:
    return (
        relative_path.startswith("docs/thesis_mainline/rq1/RQ1A_R1_")
        or relative_path.startswith(str(R1_ROOT) + "/")
    )


def _status_paths(project_root: Path) -> tuple[str, ...]:
    result = _git(project_root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise ValueError("Git status failed")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            raise ValueError("Git status syntax failed")
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value.startswith('"'):
            raise ValueError("quoted Git status path is not authorised")
        paths.append(value)
    return tuple(paths)


def _validate_checksum_manifest(project_root: Path) -> dict[str, object]:
    checksum_path = authorised_project_path(project_root, OUTPUT_CHECKSUM_PATH)
    entries: dict[str, str] = {}
    mismatch_count = 0
    if not checksum_path.is_file() or checksum_path.is_symlink():
        raise ValueError("RQ1-A-R1 checksum manifest missing")
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"checksum syntax failed at line {line_number}")
        expected, relative_path = match.groups()
        if relative_path in entries:
            raise ValueError("duplicate checksum member")
        path = authorised_project_path(project_root, relative_path)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            mismatch_count += 1
        entries[relative_path] = expected
    expected_paths = set(expected_checksum_paths())
    return {
        "entry_count": len(entries),
        "mismatch_count": mismatch_count,
        "path_set_matches": set(entries) == expected_paths,
        "manifest_sha256": sha256_file(checksum_path),
    }


def _validate_python_ast(project_root: Path) -> int:
    count = 0
    for name in CODE_FILENAMES:
        if not name.endswith(".py"):
            continue
        path = authorised_project_path(project_root, R1_ROOT / name)
        ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        count += 1
    return count


def validate(project_root: Path) -> dict[str, object]:
    project_root = Path(os.path.abspath(project_root))
    expected_outputs = build_supplement(project_root)
    safe_output_mismatch_count = 0
    for name in SAFE_JSON_FILENAMES:
        path = authorised_project_path(project_root, R1_ROOT / name)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.read_bytes() != canonical_json_bytes(expected_outputs[name])
        ):
            safe_output_mismatch_count += 1

    checksum = _validate_checksum_manifest(project_root)
    ast_file_count = _validate_python_ast(project_root)
    protected = compute_protected_source_fingerprint(project_root)

    branch_result = _git(project_root, "branch", "--show-current")
    remote_result = _git(project_root, "remote")
    tag_result = _git(project_root, "tag", "--list")
    relative_result = _git(project_root, "rev-list", "--count", f"{STARTING_HEAD}..HEAD")
    ancestry_result = _git(project_root, "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD")
    diff_result = _git(project_root, "diff", "--name-only", STARTING_HEAD, "--")
    if any(result.returncode != 0 for result in (
        branch_result,
        remote_result,
        tag_result,
        relative_result,
        diff_result,
    )):
        raise ValueError("Git validation command failed")
    branch = branch_result.stdout.strip()
    remote_count = len([line for line in remote_result.stdout.splitlines() if line])
    tag_count = len([line for line in tag_result.stdout.splitlines() if line])
    relative_commit_count = int(relative_result.stdout.strip())
    changed_paths = tuple(line for line in diff_result.stdout.splitlines() if line)
    status_paths = _status_paths(project_root)
    unauthorised_paths = sorted({
        path for path in (*changed_paths, *status_paths)
        if not _allowed_new_path(path)
    })

    absolute_path_findings = 0
    macos_prefix = "/" + "Users" + "/"
    windows_prefix = "C:" + "\\" + "Users" + "\\"
    review_paths = [
        *DOC_PATHS,
        *(str(R1_ROOT / name) for name in CODE_FILENAMES),
        *(str(R1_ROOT / name) for name in SAFE_JSON_FILENAMES),
        str(OUTPUT_CHECKSUM_PATH),
    ]
    for relative_path in review_paths:
        text = authorised_project_path(project_root, relative_path).read_text(encoding="utf-8")
        absolute_path_findings += text.count(macos_prefix)
        absolute_path_findings += text.count(windows_prefix)

    parity = expected_outputs["rq1a_r1_keyword_parity_v1.json"]
    scenario = expected_outputs["rq1a_r1_scenario_composition_v1.json"]
    duplicate = expected_outputs["rq1a_r1_duplicate_representation_audit_v1.json"]
    statistical = expected_outputs["rq1a_r1_statistical_decision_contract_v1.json"]
    failures = {
        "safe_output_mismatch_count": safe_output_mismatch_count,
        "checksum_mismatch_count": checksum["mismatch_count"],
        "checksum_path_set_mismatch": not checksum["path_set_matches"],
        "wrong_branch": branch != TARGET_BRANCH,
        "remote_count_nonzero": remote_count != 0,
        "tag_count_nonzero": tag_count != 0,
        "starting_head_not_ancestor": ancestry_result.returncode != 0,
        "relative_commit_count_invalid": relative_commit_count not in (0, 1),
        "unauthorised_changed_path_count": len(unauthorised_paths),
        "protected_source_mismatch": (
            protected["manifest_fingerprint"]
            != BASELINE["protected_source_manifest_fingerprint"]
        ),
        "keyword_parity_mismatch_count": parity["mismatch_count"],
        "semantic_loader_call_count": parity["semantic_loader_call_count"],
        "scenario_method_flag_invalid": scenario["pure_data_volume_causal_interpretation"] is not False,
        "cross_label_duplicate_group_count": duplicate["cross_label_duplicate_group_count"],
        "statistical_contract_not_frozen": statistical["status"] != "FROZEN",
        "absolute_path_finding_count": absolute_path_findings,
    }
    status = "PASS" if not any(bool(value) for value in failures.values()) else "FAIL"
    return {
        "schema_version": "rq1a-r1-validator-result-v1",
        "status": status,
        "failures": failures,
        "supplement_bundle_sha256": supplement_bundle_fingerprint(expected_outputs),
        "safe_output_count": len(expected_outputs),
        "checksum_entry_count": checksum["entry_count"],
        "checksum_manifest_sha256": checksum["manifest_sha256"],
        "python_ast_file_count": ast_file_count,
        "branch": branch,
        "relative_commit_count": relative_commit_count,
        "remote_count": remote_count,
        "tag_count": tag_count,
        "changed_path_count": len(changed_paths),
        "working_status_path_count": len(status_paths),
        "unauthorised_changed_paths": unauthorised_paths,
        "keyword_parity_records": parity["record_count"],
        "keyword_parity_matches": parity["match_count"],
        "semantic_loader_call_count": parity["semantic_loader_call_count"],
        "protected_source_entry_count": protected["entry_count"],
        "protected_source_manifest_fingerprint": protected["manifest_fingerprint"],
        "model_training": False,
        "checkpoint_created": False,
        "checkpoint_loaded": False,
        "embedding_executed": False,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "provider_calls": False,
        "network_access": False,
        "production_code_modified": False,
        "rq1b_started": False,
        "raw_text_emitted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(Path(args.project_root))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result = {
            "status": "FAIL",
            "error": "RQ1_A_R1_SUPPLEMENT_VALIDATION_FAILED",
            "raw_text_emitted": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
