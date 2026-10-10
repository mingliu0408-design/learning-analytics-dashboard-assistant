"""Build the strict review-only ZIP after the single Stage 4-0 commit."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence
import unittest
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from . import (
    DEV_RELEASE_SHA256,
    EXPECTED_BRANCH,
    EXPECTED_COMMIT_SUBJECT,
    PACKAGE_ROOT,
    READY_STATUS,
    STAGE3C_RELEASE_SHA256,
    STARTING_HEAD,
)
from .build_dev_protocol import REVIEW_ARCHIVE_FILES, sha256_bytes, sha256_file
from .validate_dev_protocol import validate_protocol


PROJECT_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_4_0_DEV_PROTOCOL_REVIEW_2026-08-31.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_4_0_DEV_PROTOCOL_REVIEW_2026-08-31"
REVIEW_MANIFEST_NAME = "REVIEW_ZIP_MANIFEST.json"
FIXED_ZIP_TIMESTAMP = (2026, 8, 31, 0, 0, 0)


class ReviewZipError(RuntimeError):
    """Raised when repository state or review archive scope differs."""


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def verify_git_state() -> dict[str, Any]:
    branch = _git("branch", "--show-current").strip()
    head = _git("rev-parse", "HEAD").strip()
    status = _git("status", "--short")
    subject = _git("show", "-s", "--format=%s", "HEAD").strip()
    parent = _git("rev-parse", "HEAD^").strip()
    commit_count = int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD").strip())
    if branch != EXPECTED_BRANCH:
        raise ReviewZipError(f"branch differs: {branch}")
    if status:
        raise ReviewZipError("review ZIP requires a clean working tree")
    if parent != STARTING_HEAD or commit_count != 1:
        raise ReviewZipError("Stage 4-0 must be exactly one commit beyond the authorized start")
    if subject != EXPECTED_COMMIT_SUBJECT:
        raise ReviewZipError(f"commit subject differs: {subject}")

    package_relative = PACKAGE_ROOT.relative_to(PROJECT_ROOT)
    expected_paths = {
        (package_relative / name).as_posix() for name in REVIEW_ARCHIVE_FILES
    }
    changed_paths = {
        line
        for line in _git("diff", "--name-only", f"{STARTING_HEAD}..HEAD").splitlines()
        if line
    }
    if changed_paths != expected_paths:
        raise ReviewZipError("committed path allowlist differs from the protocol review files")
    statuses = [
        line.split("\t", 1)
        for line in _git("diff", "--name-status", f"{STARTING_HEAD}..HEAD").splitlines()
        if line
    ]
    if any(status_code != "A" for status_code, _path in statuses):
        raise ReviewZipError("Stage 4-0 commit must add files only")
    subprocess.run(
        ["git", "diff", "--check", f"{STARTING_HEAD}..HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "working_directory": str(PROJECT_ROOT),
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "ending_head": head,
        "commit_subject": subject,
        "commit_count": commit_count,
        "clean_tree": True,
        "changed_file_count": len(changed_paths),
    }


def run_tests() -> tuple[int, str]:
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "evaluation.capability_routing_rq2_v2_stage4.dev_protocol.test_dev_protocol"
    )
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise ReviewZipError("unit tests failed before review ZIP creation:\n" + stream.getvalue())
    return result.testsRun, stream.getvalue()


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, FIXED_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _review_manifest(
    git_state: dict[str, Any], validation_count: int, test_count: int
) -> bytes:
    value = {
        "schema_version": "rq2-v2-stage4-dev-review-zip-manifest-v1",
        "status": READY_STATUS,
        "git": git_state,
        "source_hashes": {
            "dev_release_sha256": DEV_RELEASE_SHA256,
            "stage3c_grouping_source_sha256": STAGE3C_RELEASE_SHA256,
        },
        "verification": {
            "validator_checks_passed": validation_count,
            "unit_tests_passed": test_count,
            "test_rows_retained": 0,
            "test_identifiers_retained": 0,
            "writer_identity_retained": False,
            "full_restricted_split_retained": False,
            "model_training": False,
            "router_execution": False,
            "provider_calls": False,
            "model_performance_calculation": False,
            "rq3_execution": False,
        },
        "files": [
            {
                "name": name,
                "sha256": sha256_file(PACKAGE_ROOT / name),
                "size_bytes": (PACKAGE_ROOT / name).stat().st_size,
            }
            for name in REVIEW_ARCHIVE_FILES
        ],
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_review_zip(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = Path(output)
    if output.exists():
        raise ReviewZipError(f"refusing to overwrite existing review ZIP: {output}")
    if output.parent != Path("/Users/liuming/Downloads"):
        raise ReviewZipError("review ZIP output must be the authorized Downloads path")

    checks = validate_protocol(PACKAGE_ROOT, verify_source_zips=True)
    test_count, _test_output = run_tests()
    git_state = verify_git_state()
    manifest_payload = _review_manifest(git_state, len(checks), test_count)

    member_payloads = {
        f"{ARCHIVE_ROOT}/{name}": (PACKAGE_ROOT / name).read_bytes()
        for name in REVIEW_ARCHIVE_FILES
    }
    member_payloads[f"{ARCHIVE_ROOT}/{REVIEW_MANIFEST_NAME}"] = manifest_payload
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(member_payloads):
            archive.writestr(_zip_info(name), member_payloads[name])

    with ZipFile(output) as archive:
        names = archive.namelist()
        if names != sorted(member_payloads) or len(names) != len(set(names)):
            raise ReviewZipError("review ZIP member allowlist differs")
        for name, payload in member_payloads.items():
            if archive.read(name) != payload:
                raise ReviewZipError(f"review ZIP payload differs: {name}")

    return {
        "path": str(output),
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
        "member_count": len(member_payloads),
        "payload_digest": sha256_bytes(
            b"".join(member_payloads[name] for name in sorted(member_payloads))
        ),
        "validator_checks_passed": len(checks),
        "unit_tests_passed": test_count,
        "git": git_state,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = build_review_zip(args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
