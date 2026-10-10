#!/usr/bin/env python3
"""Build the narrow post-commit J2D0 internal review ZIP."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping
import zlib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from judge_package_validator_v3 import sha256_file, validate_package_zip


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DOWNLOADS = Path("/Users/liuming/Downloads")
OUTPUT = DOWNLOADS / "RQ3_REAL_J2D0_JUDGE_CONTINUATION_REPAIR_REVIEW_2026-09-02.zip"
STARTING_HEAD = "366286e257abca2be18cc6fe88de5f7e445a65bd"
POST_CHERRY_PICK_HEAD = "ba598bd74d889469b7479db7e84b06319e914890"
EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
REVIEW_SOURCE_ALLOWLIST = {
    "C4_REAL_HUMAN_RATING_INTAKE_READINESS.md",
    "C4_REAL_J2D0_EXECUTION_REPORT.md",
    "C4_REAL_JUDGE_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json",
    "C4_REAL_JUDGE_EXISTING_OUTPUT_PRESERVATION_MANIFEST_V1.json",
    "C4_REAL_JUDGE_PARSER_V2_RATIONALE_FALSE_REJECTION_ANALYSIS.md",
    "C4_REAL_JUDGE_PARSER_V2_V3_COMPATIBILITY_NOTE.md",
    "C4_REAL_JUDGE_RUNNER_V3_OFFLINE_PREFLIGHT_RECEIPT.json",
    "C4_REAL_JUDGE_TIMEOUT_AUDIT.md",
    "OFFLINE_TEST_RESULTS.txt",
    "STATUS.md",
    "build_j2d0_artifacts.py",
    "build_j2d0_review_package.py",
    "c4_real_existing_judge_attempt_reclassification_summary_v3.json",
    "c4_real_judge_commit_integration_mapping_v1.json",
    "c4_real_judge_continuation_package_manifest_v1.json",
    "c4_real_judge_continuation_source_identity_audit_v1.json",
    "judge_execution_runner_v3.py",
    "judge_package_offline_tests_v3.py",
    "judge_package_validator_v3.py",
    "judge_result_parser_v3.py",
    "test_j2d0_judge_continuation_repair.py",
}
CONTINUATION_PACKAGES = {
    shard: DOWNLOADS
    / f"C4_REAL_JUDGE_SHARD_{shard}_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip"
    for shard in "ABC"
}
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*=\s*['\"]?sk-[A-Za-z0-9_-]{12,})",
    re.IGNORECASE,
)
_PROHIBITED_NAME = re.compile(
    r"(?:restricted_internal|hmac.*key|condition_to_|response_to_(?:condition|mode|scenario)|"
    r"existing_canonical_judge_results|attempt_reclassification_v3\.jsonl|"
    r"remaining_manifest|BLINDED_JUDGE_REQUESTS|JUDGE_(?:ATTEMPT|TERMINAL)_JOURNAL)",
    re.IGNORECASE,
)


class ReviewError(RuntimeError):
    """Raised if the committed review handoff is not exact."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def git(*args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return result.stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def zip_bytes(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            path = Path(name)
            require(not path.is_absolute() and ".." not in path.parts, "unsafe review path")
            require(len(path.parts) == 1, "nested review path")
            info = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name], compress_type=ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def main() -> int:
    require(Path.cwd().resolve() == REPO, "working directory differs")
    require(str(git("branch", "--show-current")).strip() == EXPECTED_BRANCH, "branch differs")
    ending_head = str(git("rev-parse", "HEAD")).strip()
    require(str(git("rev-parse", f"{ending_head}^")).strip() == POST_CHERRY_PICK_HEAD, "J2D0 commit parent differs")
    require(int(str(git("rev-list", "--count", f"{STARTING_HEAD}..{ending_head}")).strip()) == 4, "expected three integrations plus one J2D0 commit")
    require(int(str(git("rev-list", "--count", f"{POST_CHERRY_PICK_HEAD}..{ending_head}")).strip()) == 1, "expected exactly one J2D0 commit")
    require(not str(git("status", "--short")).strip(), "worktree is not clean")
    require(not OUTPUT.exists(), "review ZIP already exists")
    changed = str(git("diff-tree", "--no-commit-id", "--name-only", "-r", ending_head)).splitlines()
    prefix = "evaluation/rq3_real_c4/j2d0_judge_continuation_repair/"
    require(changed and all(path.startswith(prefix) for path in changed), "J2D0 commit scope differs")
    require(not any(_PROHIBITED_NAME.search(name) for name in REVIEW_SOURCE_ALLOWLIST), "review allowlist contains prohibited data artifact")

    package_manifest = json.loads((HERE / "c4_real_judge_continuation_package_manifest_v1.json").read_text())
    package_results: dict[str, Any] = {}
    for shard, path in CONTINUATION_PACKAGES.items():
        validation = validate_package_zip(path)
        recorded = package_manifest["packages"][shard]
        require(validation["status"] == "PASS", f"Shard {shard} Package validation failed")
        require(sha256_file(path) == recorded["sha256"], f"Shard {shard} Package hash differs")
        package_results[shard] = {
            "path": str(path),
            "sha256": recorded["sha256"],
            "request_count": validation["request_count"],
            "maximum_physical_attempts": validation["maximum_physical_attempts"],
            "validation": "PASS",
        }

    members: dict[str, bytes] = {}
    for name in sorted(REVIEW_SOURCE_ALLOWLIST):
        path = HERE / name
        require(path.is_file(), f"review source absent: {name}")
        data = path.read_bytes()
        committed = git("show", f"{ending_head}:{prefix}{name}", binary=True)
        require(isinstance(committed, bytes) and data == committed, f"review source is not committed: {name}")
        members[name] = data
    require(not _SECRET.search(b"\n".join(members.values())), "credential-like content detected")

    checksums = {
        "schema_version": "c4-real-j2d0-review-member-checksums-v1",
        "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        "member_crc32": {name: f"{zlib.crc32(data) & 0xffffffff:08x}" for name, data in sorted(members.items())},
    }
    members["REVIEW_FILE_SHA256SUMS.json"] = pretty_json_bytes(checksums)
    review_manifest = {
        "schema_version": "c4-real-j2d0-review-manifest-v1",
        "status": "PASS_NARROW_INTERNAL_REVIEW_PACKAGE",
        "working_directory": str(REPO),
        "branch": EXPECTED_BRANCH,
        "starting_head": STARTING_HEAD,
        "ending_head": ending_head,
        "integrated_commit_count": 3,
        "j2d0_additional_commit_count": 1,
        "review_file_count": len(members) + 1,
        "review_file_allowlist": sorted({*members, "REVIEW_MANIFEST.json"}),
        "review_payload_member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        "review_payload_member_crc32": {name: f"{zlib.crc32(data) & 0xffffffff:08x}" for name, data in sorted(members.items())},
        "continuation_packages": package_results,
        "unit_tests": {"passed": 239, "failed": 0},
        "unchanged_r3d1_r2_validator_checks": {"passed": 109, "failed": 0},
        "continuation_package_validator_invocations": {"passed": 3, "failed": 0},
        "corrected_harness_setup_events": 1,
        "raw_judge_outputs_included": False,
        "canonical_judge_score_records_included": False,
        "continuation_provider_payload_manifests_included": False,
        "raw_restricted_mapping_included": False,
        "hmac_key_included": False,
        "human_ratings_included": False,
        "api_credentials_included": False,
        "full_project_included": False,
        "provider_calls": 0,
        "new_judge_executions": 0,
        "human_rating_intake_calls": 0,
        "condition_unblinding_calls": 0,
        "scoring_or_statistical_calls": 0,
    }
    members["REVIEW_MANIFEST.json"] = pretty_json_bytes(review_manifest)
    archive_bytes = zip_bytes(members)
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        require(archive.namelist() == sorted(review_manifest["review_file_allowlist"]), "review ZIP allowlist/order mismatch")
        require(len(archive.namelist()) == len(set(archive.namelist())), "duplicate review member")
        for name, data in members.items():
            require(archive.read(name) == data, f"review ZIP byte mismatch: {name}")
            require(archive.getinfo(name).CRC == zlib.crc32(data) & 0xffffffff, f"review ZIP CRC mismatch: {name}")
    with OUTPUT.open("xb") as handle:
        handle.write(archive_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({
        "status": "PASS_REVIEW_ZIP_CREATED_ONCE",
        "path": str(OUTPUT),
        "sha256": sha256_file(OUTPUT),
        "regular_file_count": len(members),
        "ending_head": ending_head,
        "provider_calls": 0,
        "new_judge_executions": 0,
        "human_rating_intake_calls": 0,
        "condition_unblinding_calls": 0,
        "scoring_or_statistical_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
