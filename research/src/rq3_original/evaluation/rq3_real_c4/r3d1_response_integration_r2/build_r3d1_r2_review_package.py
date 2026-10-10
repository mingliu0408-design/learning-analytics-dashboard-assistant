#!/usr/bin/env python3
"""Build the narrow post-commit R3D1-R2 internal review ZIP."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

try:
    from build_r3d1_r2_artifacts import (
        DOWNLOADS,
        EXPECTED_BRANCH,
        REPO,
        R1_PACKAGE_HASHES,
        START_HEAD,
        sha256_bytes,
        sha256_file,
    )
    from judge_package_validator_v2 import read_package_zip, validate_package_zip
    from validate_r3d1_r2_artifacts import validate
except ImportError:  # pragma: no cover - repository package import
    from .build_r3d1_r2_artifacts import (
        DOWNLOADS,
        EXPECTED_BRANCH,
        REPO,
        R1_PACKAGE_HASHES,
        START_HEAD,
        sha256_bytes,
        sha256_file,
    )
    from .judge_package_validator_v2 import read_package_zip, validate_package_zip
    from .validate_r3d1_r2_artifacts import validate


HERE = Path(__file__).resolve().parent
OUTPUT = DOWNLOADS / "RQ3_REAL_R3D1_R2_JUDGE_HUMAN_PREEXECUTION_REPAIR_REVIEW_2026-09-02.zip"
R2_JUDGE_PACKAGES = {
    shard: DOWNLOADS / f"C4_REAL_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R2_2026-09-02.zip"
    for shard in "ABC"
}
R2_HUMAN_PACKAGES = {
    role: DOWNLOADS / f"C4_REAL_HUMAN_RATER_{role}_PACKET_R2_2026-09-02.zip"
    for role in "AB"
}
REVIEW_SOURCE_ALLOWLIST = {
    "C4_REAL_R3D1_R2_PREEXECUTION_AUDIT.md",
    "c4_real_r3d1_r2_preexecution_audit_v1.json",
    "C4_REAL_JUDGE_PROVIDER_CONTRACT_R1_R2_COMPATIBILITY_NOTE.md",
    "c4_real_judge_prompt_r2_provider_compatible.txt",
    "c4_real_judge_schema_r2_provider_compatible.json",
    "judge_result_parser_v2.py",
    "judge_execution_runner_v2.py",
    "judge_package_validator_v2.py",
    "judge_package_offline_tests_v2.py",
    "c4_real_judge_configuration_set_frozen_r2.json",
    "c4_real_judge_execution_contract_set_r2.json",
    "c4_real_judge_package_manifest_r2_v1.json",
    "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT_R2.json",
    "HUMAN_RATER_GUIDE_R2.md",
    "C4_REAL_HUMAN_VISIBLE_ITEM_DEDUPLICATION_METHOD.md",
    "c4_real_human_packet_manifest_r2_v1.json",
    "c4_real_human_restricted_mapping_metadata_r2_v1.json",
    "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT_R2.json",
    "c4_real_r3d1_r1_package_supersession_r2_v1.json",
    "c4_real_r3d1_r2_source_preservation_manifest_v1.json",
    "c4_real_r3d1_r2_build_summary_v1.json",
    "validate_r3d1_r2_artifacts.py",
    "test_r3d1_r2_preexecution_repair.py",
    "build_r3d1_r2_artifacts.py",
    "build_r3d1_r2_review_package.py",
    "STATUS.md",
}


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
        capture_output=True,
        text=not binary,
    )
    return result.stdout


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
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def run_tests(command: list[str], cwd: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    require(result.returncode == 0, f"offline tests failed: {' '.join(command)}\n{output}")
    match = re.search(r"Ran (\d+) tests?", output)
    if match is None:
        raise ReviewError("unittest count absent")
    return {"passed": int(match.group(1)), "failed": 0}


def run_package_tests(package_path: Path) -> dict[str, Any]:
    validation = validate_package_zip(package_path)
    members = read_package_zip(package_path)
    with tempfile.TemporaryDirectory(prefix="c4-r3d1-r2-review-package-test-") as tmp:
        root = Path(tmp)
        for name, data in members.items():
            (root / name).write_bytes(data)
        result = run_tests(
            ["/opt/anaconda3/bin/python3", "-B", "test_package.py"], root
        )
    return {**result, "validation": validation["status"]}


def main() -> int:
    require(Path.cwd().resolve() == REPO.resolve(), "working directory differs")
    require(str(git("branch", "--show-current")).strip() == EXPECTED_BRANCH, "branch differs")
    ending_head = str(git("rev-parse", "HEAD")).strip()
    require(ending_head != START_HEAD, "R3D1-R2 commit is absent")
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", START_HEAD, ending_head], cwd=REPO
        ).returncode
        == 0,
        "starting HEAD is not an ancestor",
    )
    commit_count = int(str(git("rev-list", "--count", f"{START_HEAD}..{ending_head}")).strip())
    require(commit_count == 1, "R3D1-R2 must contain exactly one additional commit")
    require(not str(git("status", "--short")).strip(), "worktree is not clean")
    require(not OUTPUT.exists(), "review ZIP already exists")

    validation = validate()
    require(validation["status"] == "PASS" and validation["checks_failed"] == 0, "R2 validation failed")
    repository_tests = run_tests(
        [
            "/opt/anaconda3/bin/python3",
            "-B",
            "-m",
            "unittest",
            "evaluation.rq3_real_c4.r3d1_response_integration_r2.test_r3d1_r2_preexecution_repair",
            "-v",
        ],
        REPO,
    )
    unchanged_r1_tests = run_tests(
        [
            "/opt/anaconda3/bin/python3",
            "-B",
            "-m",
            "unittest",
            "evaluation.rq3_real_c4.r3d1_response_integration.test_r3d1_response_integration",
            "-v",
        ],
        REPO,
    )
    package_tests = {
        shard: run_package_tests(path) for shard, path in R2_JUDGE_PACKAGES.items()
    }

    for name, digest in R1_PACKAGE_HASHES.items():
        require(sha256_file(DOWNLOADS / name) == digest, f"R1 Package changed: {name}")
    judge_hashes = {shard: sha256_file(path) for shard, path in R2_JUDGE_PACKAGES.items()}
    human_hashes = {role: sha256_file(path) for role, path in R2_HUMAN_PACKAGES.items()}

    members: dict[str, bytes] = {}
    prefix = str(HERE.relative_to(REPO))
    for name in sorted(REVIEW_SOURCE_ALLOWLIST):
        path = HERE / name
        require(path.is_file(), f"review source absent: {name}")
        data = path.read_bytes()
        committed = git("show", f"{ending_head}:{prefix}/{name}", binary=True)
        require(isinstance(committed, bytes) and data == committed, f"review source not committed: {name}")
        members[name] = data
    checksums = {
        "schema_version": "c4-real-r3d1-r2-review-member-checksums-v1",
        "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
    }
    checksum_bytes = pretty_json_bytes(checksums)
    members["REVIEW_FILE_SHA256SUMS.json"] = checksum_bytes
    review_manifest = {
        "schema_version": "c4-real-r3d1-r2-review-manifest-v1",
        "status": "PASS_NARROW_INTERNAL_REVIEW_PACKAGE",
        "starting_head": START_HEAD,
        "ending_head": ending_head,
        "additional_commit_count": commit_count,
        "branch": EXPECTED_BRANCH,
        "review_file_count": len(members) + 1,
        "review_file_allowlist": sorted({*members, "REVIEW_MANIFEST.json"}),
        "review_payload_member_sha256": {
            name: sha256_bytes(data) for name, data in sorted(members.items())
        },
        "artifact_validation": {
            "passed": validation["checks_passed"],
            "failed": validation["checks_failed"],
        },
        "repository_r2_tests": repository_tests,
        "unchanged_r3d1_r1_tests": unchanged_r1_tests,
        "judge_package_tests": package_tests,
        "r1_package_sha256": R1_PACKAGE_HASHES,
        "r2_judge_package_sha256": judge_hashes,
        "r2_human_package_sha256": human_hashes,
        "raw_restricted_mapping_included": False,
        "hmac_key_included": False,
        "api_credentials_included": False,
        "full_project_included": False,
        "provider_calls": 0,
        "judge_calls": 0,
        "response_quality_scores": 0,
        "human_ratings": 0,
        "streamlit_launches": 0,
    }
    members["REVIEW_MANIFEST.json"] = pretty_json_bytes(review_manifest)
    archive = zip_bytes(members)
    with ZipFile(io.BytesIO(archive)) as built:
        require(set(built.namelist()) == set(review_manifest["review_file_allowlist"]), "review allowlist mismatch")
        require(len(built.namelist()) == len(set(built.namelist())), "duplicate review member")
        for name, data in members.items():
            require(built.read(name) == data, f"review member byte mismatch: {name}")
            built.getinfo(name)  # forces central-directory/CRC lookup
    forbidden_names = (
        "c4_real_i1_blinding_hmac_key.bin",
        "c4_real_human_rating_item_to_condition_mapping_frozen_r2.csv",
    )
    require(not any(name in members for name in forbidden_names), "restricted material selected")
    with OUTPUT.open("xb") as handle:
        handle.write(archive)
        handle.flush()
        os.fsync(handle.fileno())
    result = {
        "status": "PASS_REVIEW_ZIP_CREATED_ONCE",
        "path": str(OUTPUT),
        "sha256": sha256_file(OUTPUT),
        "regular_file_count": len(members),
        "ending_head": ending_head,
        "validation_checks_passed": validation["checks_passed"],
        "repository_r2_tests_passed": repository_tests["passed"],
        "unchanged_r3d1_r1_tests_passed": unchanged_r1_tests["passed"],
        "package_tests_passed": {
            shard: package_tests[shard]["passed"] for shard in "ABC"
        },
        "provider_calls": 0,
        "judge_calls": 0,
        "human_ratings": 0,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
