#!/usr/bin/env python3
"""Build the narrow R3D0 review-only ZIP with a strict safe allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
OUTPUT = Path(
    "/Users/liuming/Downloads/RQ3_REAL_R3D0_VALIDATOR_REPAIR_CONTINUATION_FREEZE_REVIEW_2026-09-02.zip"
)
ALLOWLIST = (
    "C4_REAL_R3D0_TEST_REPORT.md",
    "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json",
    "C4_REAL_STUDENT_FACING_VALIDATOR_FALSE_POSITIVE_ANALYSIS.md",
    "C4_REAL_VALIDATOR_V1_V2_COMPATIBILITY_NOTE.md",
    "STATUS.md",
    "build_r3c_continuation_package.py",
    "build_r3d0_artifacts.py",
    "c4_real_r3_canonical_attempt_selection_audit_v1.json",
    "c4_real_r3_commit_integration_mapping_v1.json",
    "c4_real_r3_primary_response_completion_boundary_v1.json",
    "c4_real_r3_source_preservation_manifest_after_v1.json",
    "c4_real_r3_source_preservation_manifest_before_v1.json",
    "c4_real_r3c_continuation_package_freeze_audit_v1.json",
    "c4_real_r3c_continuation_source_audit_v1.json",
    "c4_real_r3d0_status_v1.json",
    "c4_real_r3d0_test_report_v1.json",
    "c4_real_r3d0_validation_report_v1.json",
    "c4_real_student_facing_response_format_contract_v2.json",
    "c4_real_student_facing_response_validator_v2.py",
    "continuation_package_offline_tests_v1.py",
    "continuation_package_validator_v1.py",
    "generation_execution_runner_v3_1.py",
    "r3_existing_attempt_format_reclassification_summary_v2.json",
    "test_r3d0_validator_false_positive_repair.py",
    "validate_r3d0_artifacts.py",
)
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)
_PROHIBITED_NAME = re.compile(
    r"(?:HMAC_KEY\.bin|restricted_internal|condition_to_|response_to_(?:condition|mode|scenario)|"
    r"GENERATION_(?:ATTEMPT|TERMINAL)_JOURNAL|answer.*\.jsonl|course_corpus|memory.*\.(?:db|sqlite))",
    re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build(output: Path, *, replace: bool) -> dict[str, object]:
    if output.exists() and not replace:
        raise FileExistsError(f"refusing to overwrite existing review package: {output}")
    if len(ALLOWLIST) != len(set(ALLOWLIST)):
        raise ValueError("review allowlist contains duplicates")
    if any(_PROHIBITED_NAME.search(name) for name in ALLOWLIST):
        raise ValueError("review allowlist contains a prohibited filename")
    missing = [name for name in ALLOWLIST if not (HERE / name).is_file()]
    if missing:
        raise FileNotFoundError(f"review allowlist source missing: {missing}")
    contents = {name: (HERE / name).read_bytes() for name in ALLOWLIST}
    if _SECRET.search(b"\n".join(contents[name] for name in ALLOWLIST)):
        raise ValueError("review package contains a credential-like value")
    temporary = output.with_name(f".{output.name}.building-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True
    ) as archive:
        for name in sorted(ALLOWLIST):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(
                info,
                contents[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    with zipfile.ZipFile(temporary) as archive:
        names = archive.namelist()
        if names != sorted(ALLOWLIST) or len(names) != len(set(names)):
            raise ValueError("review ZIP member allowlist mismatch")
        for name, content in contents.items():
            if archive.read(name) != content:
                raise ValueError(f"review ZIP byte mismatch: {name}")
    if output.exists():
        output.unlink()
    os.replace(temporary, output)
    audit = {
        "schema_version": "c4-real-r3d0-review-package-audit-v1",
        "status": "PASS_REVIEW_ONLY_SAFE_ALLOWLIST",
        "review_package_path": str(output),
        "review_package_sha256": sha256_file(output),
        "member_count": len(ALLOWLIST),
        "member_allowlist": sorted(ALLOWLIST),
        "member_sha256": {name: sha256_bytes(contents[name]) for name in sorted(ALLOWLIST)},
        "raw_hmac_key_included": False,
        "restricted_mapping_included": False,
        "scenario_mode_condition_mapping_included": False,
        "api_credentials_included": False,
        "judge_outputs_included": False,
        "scores_included": False,
        "course_corpus_included": False,
        "memory_database_included": False,
        "existing_answer_text_artifact_included": False,
        "continuation_provider_payload_manifest_included": False,
    }
    (HERE / "c4_real_r3d0_review_package_audit_v1.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--replace-owned-output", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), replace=args.replace_owned_output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
