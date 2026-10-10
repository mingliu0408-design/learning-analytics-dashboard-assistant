#!/usr/bin/env python3
"""Build the strict, review-only G2D0 handoff ZIP after the repair commit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping
import zipfile


ROOT = Path(__file__).resolve().parents[3]
REPAIR = Path(__file__).resolve().parent
I1 = ROOT / "evaluation/rq3_real_c4/i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
TARGET = Path(
    "/Users/liuming/Downloads/RQ3_REAL_G2D0_PREJUDGE_FORMAT_REPAIR_REVIEW_2026-09-01.zip"
)
BRANCH = "research/rq3-real-c4-i1-route-integration"
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)

SOURCE_MEMBERS: Mapping[str, Path] = {
    "STATUS.md": REPAIR / "STATUS.md",
    "c4_real_g2d0_status_v1.json": REPAIR / "c4_real_g2d0_status_v1.json",
    "C4_REAL_G2D0_TEST_REPORT.md": REPAIR / "C4_REAL_G2D0_TEST_REPORT.md",
    "c4_real_g2d0_test_report_v1.json": REPAIR / "c4_real_g2d0_test_report_v1.json",
    "c4_real_g2_response_source_manifest_v1.json": REPAIR
    / "c4_real_g2_response_source_manifest_v1.json",
    "c4_real_student_facing_response_format_contract_v1.json": REPAIR
    / "c4_real_student_facing_response_format_contract_v1.json",
    "c4_real_g2_prejudge_format_audit_v1.csv": REPAIR
    / "c4_real_g2_prejudge_format_audit_v1.csv",
    "c4_real_g2_prejudge_format_audit_v1.json": REPAIR
    / "c4_real_g2_prejudge_format_audit_v1.json",
    "C4_REAL_G2_PREJUDGE_FORMAT_AUDIT.md": REPAIR / "C4_REAL_G2_PREJUDGE_FORMAT_AUDIT.md",
    "c4_real_g2_blind_format_audit_freeze_receipt_v1.json": REPAIR
    / "c4_real_g2_blind_format_audit_freeze_receipt_v1.json",
    "c4_real_g2_restricted_aggregate_format_bias_audit_v1.json": REPAIR
    / "c4_real_g2_restricted_aggregate_format_bias_audit_v1.json",
    "C4_REAL_G2_RESTRICTED_AGGREGATE_FORMAT_BIAS_AUDIT.md": REPAIR
    / "C4_REAL_G2_RESTRICTED_AGGREGATE_FORMAT_BIAS_AUDIT.md",
    "C4_REAL_G2_PREJUDGE_EXCLUSION_AND_REGENERATION_DISCLOSURE.md": REPAIR
    / "C4_REAL_G2_PREJUDGE_EXCLUSION_AND_REGENERATION_DISCLOSURE.md",
    "c4_real_generation_prompt_frozen_v3.txt": REPAIR / "c4_real_generation_prompt_frozen_v3.txt",
    "c4_real_generation_request_renderer_v3.py": REPAIR
    / "c4_real_generation_request_renderer_v3.py",
    "c4_real_generation_renderer_v2_v3_diff_audit.json": REPAIR
    / "c4_real_generation_renderer_v2_v3_diff_audit.json",
    "c4_real_student_facing_response_validator_v1.py": REPAIR
    / "c4_real_student_facing_response_validator_v1.py",
    "generation_execution_runner_v3.py": REPAIR / "generation_execution_runner_v3.py",
    "generation_package_validator_v3.py": REPAIR / "generation_package_validator_v3.py",
    "generation_package_offline_tests_v3.py": REPAIR / "generation_package_offline_tests_v3.py",
    "test_g2d0_response_format_repair.py": REPAIR / "test_g2d0_response_format_repair.py",
    "c4_real_generation_configuration_frozen_v3.json": I1
    / "c4_real_generation_configuration_frozen_v3.json",
    "c4_real_generation_request_deduplication_summary_v3.json": I1
    / "c4_real_generation_request_deduplication_summary_v3.json",
    "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT_V3.md": I1
    / "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT_V3.md",
    "c4_real_generation_shard_summary_v3.json": I1 / "c4_real_generation_shard_summary_v3.json",
    "c4_real_condition_payload_rebuild_summary_v3.json": I1
    / "c4_real_condition_payload_rebuild_summary_v3.json",
    "c4_real_restricted_mapping_metadata_v3.json": I1
    / "c4_real_restricted_mapping_metadata_v3.json",
    "c4_real_generation_package_manifest_v3.json": I1
    / "c4_real_generation_package_manifest_v3.json",
}

ALLOWED_MEMBERS = frozenset({*SOURCE_MEMBERS, "REVIEW_MANIFEST.json"})
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def verify_preconditions() -> str:
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("review builder must run from repository root")
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("review builder branch mismatch")
    if git("status", "--short"):
        raise RuntimeError("review builder requires a clean tracked worktree after commit")
    if TARGET.exists():
        raise FileExistsError(f"refusing to overwrite review ZIP: {TARGET}")
    head = git("rev-parse", "HEAD")
    subject = git("show", "-s", "--format=%s", "HEAD")
    if subject != "RQ3-REAL-G2D0: audit generated responses and freeze uniform regeneration":
        raise RuntimeError("review builder HEAD is not the single G2D0 repair commit")
    tracked = set(git("ls-files").splitlines())
    for path in SOURCE_MEMBERS.values():
        relative = str(path.relative_to(ROOT))
        if relative not in tracked:
            raise RuntimeError(f"review source is not tracked: {relative}")
    return head


def build_members(head: str) -> dict[str, bytes]:
    members = {name: path.read_bytes() for name, path in SOURCE_MEMBERS.items()}
    key = (RESTRICTED / "c4_real_i1_blinding_hmac_key.bin").read_bytes()
    if any(key in content for content in members.values()):
        raise RuntimeError("raw HMAC key appears in review content")
    if _SECRET.search(b"\n".join(members.values())):
        raise RuntimeError("credential-like value appears in review content")
    if any(path.name.endswith((".sqlite", ".sqlite3", ".db")) for path in SOURCE_MEMBERS.values()):
        raise RuntimeError("database selected for review ZIP")
    if any("restricted_internal" in name for name in SOURCE_MEMBERS):
        raise RuntimeError("restricted mapping selected for review ZIP")
    package_manifest = json.loads(
        (I1 / "c4_real_generation_package_manifest_v3.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "c4-real-g2d0-review-manifest-v1",
        "status": "REVIEW_ONLY_G2D0_COMPLETE_R3_PACKAGES_DORMANT",
        "source_commit": head,
        "member_sha256_excluding_self": {
            name: sha256_bytes(content) for name, content in sorted(members.items())
        },
        "member_count_including_self": len(members) + 1,
        "r3_package_sha256": {
            row["shard"]: row["sha256"] for row in package_manifest["packages"]
        },
        "raw_hmac_key_included": False,
        "restricted_mapping_content_included": False,
        "raw_scenario_or_mode_mapping_included": False,
        "api_credentials_included": False,
        "judge_outputs_included": False,
        "response_quality_scores_included": False,
        "course_documents_included": False,
        "memory_databases_included": False,
        "g2_answer_text_included": False,
        "provider_calls": 0,
        "response_regeneration_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }
    members["REVIEW_MANIFEST.json"] = json_bytes(manifest)
    if set(members) != ALLOWED_MEMBERS:
        raise RuntimeError("review member allowlist mismatch")
    return members


def write_zip(path: Path, members: Mapping[str, bytes]) -> None:
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[name], compresslevel=9)


def validate_zip(path: Path, members: Mapping[str, bytes]) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != ALLOWED_MEMBERS:
            raise RuntimeError("review ZIP allowlist mismatch")
        if any(name.endswith("/") or Path(name).name != name for name in names):
            raise RuntimeError("review ZIP contains a nested path")
        for name, expected in members.items():
            if archive.read(name) != expected:
                raise RuntimeError(f"review ZIP member changed: {name}")


def main() -> int:
    head = verify_preconditions()
    members = build_members(head)
    with tempfile.TemporaryDirectory(prefix=".g2d0-review-", dir=TARGET.parent) as temporary:
        staged = Path(temporary) / TARGET.name
        write_zip(staged, members)
        validate_zip(staged, members)
        os.link(staged, TARGET)
        os.chmod(TARGET, 0o644)
    print(
        json.dumps(
            {
                "status": "REVIEW_ZIP_FROZEN",
                "path": str(TARGET),
                "sha256": sha256_file(TARGET),
                "byte_count": TARGET.stat().st_size,
                "member_count": len(members),
                "source_commit": head,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
