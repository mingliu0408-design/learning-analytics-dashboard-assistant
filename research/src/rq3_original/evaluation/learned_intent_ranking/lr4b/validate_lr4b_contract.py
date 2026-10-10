"""Validate the on-disk RQ1-A contract without model, network, or gold access."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
        LR4B_RELATIVE_ROOT,
        OUTPUT_CHECKSUM_PATH,
        analyse_contract,
        compute_protected_source_fingerprint,
        safe_output_bundle_fingerprint,
    )
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        DOC_PATHS,
        LEDGER_FIELDS,
        LOCAL_LEDGER_PATH,
        SAFE_JSON_FILENAMES,
        authorised_project_path,
        canonical_json_bytes,
        sha256_file,
    )
else:
    from .build_lr4b_contract import (
        LR4B_RELATIVE_ROOT,
        OUTPUT_CHECKSUM_PATH,
        analyse_contract,
        compute_protected_source_fingerprint,
        safe_output_bundle_fingerprint,
    )
    from .contract_schema import (
        BASELINE,
        DOC_PATHS,
        LEDGER_FIELDS,
        LOCAL_LEDGER_PATH,
        SAFE_JSON_FILENAMES,
        authorised_project_path,
        canonical_json_bytes,
        sha256_file,
    )


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _expected_checksum_paths() -> set[str]:
    return {
        *DOC_PATHS,
        str(LR4B_RELATIVE_ROOT / "__init__.py"),
        str(LR4B_RELATIVE_ROOT / "contract_schema.py"),
        str(LR4B_RELATIVE_ROOT / "context_representation.py"),
        str(LR4B_RELATIVE_ROOT / "build_lr4b_contract.py"),
        str(LR4B_RELATIVE_ROOT / "validate_lr4b_contract.py"),
        str(LR4B_RELATIVE_ROOT / "test_lr4b_contract_unittest.py"),
        *(str(LR4B_RELATIVE_ROOT / name) for name in SAFE_JSON_FILENAMES),
    }


def validate(project_root: Path) -> dict[str, object]:
    outputs, expected_ledger = analyse_contract(project_root)
    mismatched_outputs = 0
    for name in SAFE_JSON_FILENAMES:
        path = authorised_project_path(project_root, LR4B_RELATIVE_ROOT / name)
        if not path.is_file() or path.is_symlink():
            mismatched_outputs += 1
            continue
        if path.read_bytes() != canonical_json_bytes(outputs[name]):
            mismatched_outputs += 1

    checksum_path = authorised_project_path(project_root, OUTPUT_CHECKSUM_PATH)
    checksum_entries: dict[str, str] = {}
    checksum_mismatches = 0
    if checksum_path.is_file() and not checksum_path.is_symlink():
        for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                raise ValueError(f"invalid output checksum syntax at line {line_number}")
            expected_hash, relative_path = match.groups()
            if relative_path in checksum_entries:
                raise ValueError("duplicate output checksum path")
            path = authorised_project_path(project_root, relative_path)
            if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_hash:
                checksum_mismatches += 1
            checksum_entries[relative_path] = expected_hash
    else:
        checksum_mismatches += 1
    checksum_path_set_matches = set(checksum_entries) == _expected_checksum_paths()

    ignore_rule = "evaluation/learned_intent_ranking/lr4b/local_artifacts/"
    ignore_lines = (project_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    ledger_path = authorised_project_path(project_root, LOCAL_LEDGER_PATH)
    check_ignore = _git(project_root, "check-ignore", "-q", str(LOCAL_LEDGER_PATH))
    ledger_ignored = ignore_rule in ignore_lines and check_ignore.returncode == 0
    ledger_tracked = _git(project_root, "ls-files", "--error-unmatch", str(LOCAL_LEDGER_PATH)).returncode == 0
    ledger_mismatch_count = 0
    ledger_record_count = 0
    if ledger_path.is_file() and not ledger_path.is_symlink():
        actual_ledger = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        ledger_record_count = len(actual_ledger)
        if actual_ledger != expected_ledger:
            ledger_mismatch_count += 1
        if any(set(row) != set(LEDGER_FIELDS) for row in actual_ledger):
            ledger_mismatch_count += 1
    else:
        ledger_mismatch_count += 1

    current_branch = _git(project_root, "branch", "--show-current").stdout.strip()
    remote_count = len([line for line in _git(project_root, "remote").stdout.splitlines() if line])
    tag_count = len([line for line in _git(project_root, "tag").stdout.splitlines() if line])
    protected = compute_protected_source_fingerprint(project_root)

    new_relative_paths = sorted(_expected_checksum_paths() | {str(OUTPUT_CHECKSUM_PATH)})
    absolute_path_findings = 0
    macos_user_prefix = "/" + "Users" + "/"
    windows_user_prefix = "C:" + "\\" + "Users" + "\\"
    for relative_path in new_relative_paths:
        text = authorised_project_path(project_root, relative_path).read_text(encoding="utf-8")
        absolute_path_findings += text.count(macos_user_prefix)
        absolute_path_findings += text.count(windows_user_prefix)

    failures = {
        "safe_output_mismatch_count": mismatched_outputs,
        "checksum_mismatch_count": checksum_mismatches,
        "checksum_path_set_mismatch": not checksum_path_set_matches,
        "ledger_not_ignored": not ledger_ignored,
        "ledger_tracked": ledger_tracked,
        "ledger_mismatch_count": ledger_mismatch_count,
        "wrong_branch": current_branch != "research/rq1-a-lr4b-contract",
        "remote_count_nonzero": remote_count != 0,
        "tag_count_nonzero": tag_count != 0,
        "protected_source_mismatch": protected["manifest_fingerprint"] != BASELINE["protected_source_manifest_fingerprint"],
        "absolute_path_finding_count": absolute_path_findings,
    }
    status = "PASS" if not any(bool(value) for value in failures.values()) else "FAIL"
    return {
        "schema_version": "lr4b-validator-result-v1",
        "status": status,
        "failures": failures,
        "safe_output_bundle_sha256": safe_output_bundle_fingerprint(outputs),
        "safe_output_count": len(outputs),
        "checksum_entry_count": len(checksum_entries),
        "ledger_record_count": ledger_record_count,
        "ledger_ignored": ledger_ignored,
        "ledger_tracked": ledger_tracked,
        "branch": current_branch,
        "remote_count": remote_count,
        "tag_count": tag_count,
        "protected_source_entry_count": protected["entry_count"],
        "protected_source_manifest_fingerprint": protected["manifest_fingerprint"],
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "model_training": False,
        "checkpoint_loaded": False,
        "embedding_executed": False,
        "network_access": False,
        "raw_text_emitted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(argv)
    project_root = Path(os.path.abspath(args.project_root))
    try:
        result = validate(project_root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result = {
            "status": "FAIL",
            "error": "RQ1_A_CONTRACT_VALIDATION_FAILED",
            "raw_text_emitted": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
