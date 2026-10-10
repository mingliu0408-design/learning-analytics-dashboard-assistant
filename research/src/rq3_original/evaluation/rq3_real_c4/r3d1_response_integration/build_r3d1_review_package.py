#!/usr/bin/env python3
"""Build and byte-verify the narrow R3D1-R1 internal review ZIP."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RESTRICTED = REPO / "evaluation/rq3_real_c4/i1_route_integration/restricted_internal"
START_HEAD = "ebac41e4dfd1b3a54fd229cc92863b6ea5280673"
EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
OUTPUT = Path("/Users/liuming/Downloads/RQ3_REAL_R3D1_R1_RESPONSE_INTEGRATION_EVALUATION_PACKET_FREEZE_REVIEW_2026-09-02.zip")


TRACKED_ALLOWLIST = (
    "C4_REAL_IDENTICAL_ANSWER_TEXT_POLICY.md",
    "c4_real_identical_answer_text_policy_v1.json",
    "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl",
    "c4_real_r3_canonical_unique_responses_frozen_v1.csv",
    "c4_real_r3_response_source_registry_v1.jsonl",
    "c4_real_r3_duplicate_text_identity_audit_v1.json",
    "c4_real_r3_final_response_format_audit_v1.json",
    "C4_REAL_R3_FINAL_RESPONSE_FREEZE_REPORT.md",
    "c4_real_r3_generation_usage_frozen_v1.json",
    "c4_real_r3_source_preservation_manifest_v1.json",
    "c4_real_r3_response_mapping_metadata_v1.json",
    "c4_real_r3_applicability_integrity_audit_v1.json",
    "c4_real_unique_judge_request_manifest_frozen_v1.jsonl",
    "C4_REAL_JUDGE_REQUEST_DEDUPLICATION_REPORT.md",
    "c4_real_judge_request_deduplication_audit_v1.json",
    "c4_real_judge_restricted_mapping_metadata_v1.json",
    "c4_real_judge_configuration_frozen_r1.json",
    "c4_real_judge_execution_contract_v1.json",
    "c4_real_judge_package_manifest_r1_v1.json",
    "judge_execution_runner_v1.py",
    "judge_result_parser_v1.py",
    "judge_package_validator_v1.py",
    "judge_package_offline_tests_v1.py",
    "c4_real_human_validation_sample_metadata_v1.json",
    "c4_real_human_packet_manifest_v1.json",
    "c4_real_human_restricted_mapping_metadata_v1.json",
    "HUMAN_RATER_GUIDE.md",
    "human_rater_attestation_A.md",
    "human_rater_attestation_B.md",
    "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json",
    "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT.json",
    "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT.json",
    "build_r3d1_artifacts.py",
    "build_r3d1_review_package.py",
    "validate_r3d1_artifacts.py",
    "test_r3d1_response_integration.py",
    "STATUS.md",
)

PROTOCOL_MEMBERS = {
    "judge/JUDGE_PROMPT.txt": REPO / "evaluation/rq3_real_c4/i1_route_integration/c4_real_judge_prompt_v2_provider_compatible.txt",
    "judge/JUDGE_SCHEMA.json": REPO / "evaluation/rq3_real_c4/i1_route_integration/c4_real_judge_schema_v2_provider_compatible.json",
    "judge/PRIMARY_RUBRIC.json": REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_primary_eight_criterion_rubric_v1.json",
    "judge/APPLICABILITY_CONTRACT.json": REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_dimension_applicability_v1.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout


def main() -> int:
    require(Path.cwd().resolve() == REPO.resolve(), "working directory mismatch")
    require(git("branch", "--show-current").strip() == EXPECTED_BRANCH, "branch mismatch")
    head = git("rev-parse", "HEAD").strip()
    require(head != START_HEAD, "R3D1-R1 commit has not been created")
    require(int(git("rev-list", "--count", f"{START_HEAD}..HEAD").strip()) == 1, "expected exactly one R3D1-R1 commit")
    require(git("rev-parse", "HEAD^").strip() == START_HEAD, "R3D1-R1 commit parent mismatch")
    require(not git("status", "--short"), "tracked worktree must be clean before review packaging")
    require(not OUTPUT.exists(), "review ZIP already exists; overwrite prohibited")

    members: dict[str, bytes] = {}
    for name in TRACKED_ALLOWLIST:
        path = HERE / name
        require(path.is_file(), f"review member missing: {name}")
        relative = path.relative_to(REPO).as_posix()
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=REPO, check=True, capture_output=True
        ).stdout
        current = path.read_bytes()
        require(current == committed, f"review source differs from committed bytes: {name}")
        members[f"r3d1_response_integration/{name}"] = current
    for archive_name, path in PROTOCOL_MEMBERS.items():
        require(path.is_file(), f"protocol member missing: {archive_name}")
        members[archive_name] = path.read_bytes()

    raw_key = (RESTRICTED / "c4_real_i1_blinding_hmac_key.bin").read_bytes()
    require(len(raw_key) == 32, "HMAC key length mismatch")
    require(all(raw_key not in data for data in members.values()), "raw HMAC key leaked into review members")
    forbidden_names = (
        "restricted_internal",
        "condition_to_unique_judge_request_mapping",
        "condition_response_records_frozen",
        "rating_item_to_condition_mapping",
        "OPENAI_API_KEY",
        ".db",
        ".sqlite",
    )
    require(
        all(not any(token.casefold() in name.casefold() for token in forbidden_names) for name in members),
        "review allowlist contains a prohibited filename",
    )
    review_manifest: dict[str, Any] = {
        "schema_version": "c4-real-r3d1-r1-review-package-manifest-v1",
        "status": "PASS_NARROW_REVIEW_ONLY_ALLOWLIST",
        "source_commit": head,
        "starting_head": START_HEAD,
        "regular_file_count_excluding_manifest": len(members),
        "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        "restricted_mapping_included": False,
        "raw_hmac_key_included": False,
        "api_credentials_included": False,
        "completed_judge_results_included": False,
        "completed_human_ratings_included": False,
        "course_documents_or_memory_databases_included": False,
    }
    members["REVIEW_MANIFEST.json"] = (
        json.dumps(review_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")

    with OUTPUT.open("xb") as output_handle:
        with ZipFile(output_handle, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(members):
                info = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, members[name])
        output_handle.flush()
        os.fsync(output_handle.fileno())
    OUTPUT.chmod(0o644)

    with ZipFile(OUTPUT) as archive:
        require(archive.testzip() is None, "review ZIP CRC failure")
        require(set(archive.namelist()) == set(members), "review ZIP member-set mismatch")
        for name, expected in members.items():
            require(archive.read(name) == expected, f"review ZIP byte mismatch: {name}")
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": str(OUTPUT),
                "sha256": sha256_bytes(OUTPUT.read_bytes()),
                "regular_file_count": len(members),
                "source_commit": head,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

