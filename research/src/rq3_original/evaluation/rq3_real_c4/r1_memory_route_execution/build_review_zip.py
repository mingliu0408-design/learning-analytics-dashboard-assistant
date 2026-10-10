#!/usr/bin/env python3
"""Build the clean-commit, review-only RQ3-REAL-R1B evidence ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.rq3_real_c4.r1_memory_route_execution.validate_memory_route_execution_v1 import (  # noqa: E402
    validate_all,
)


STARTING_HEAD = "246e6ff64003caa4787716e00f050a2451dfca01"
EXPECTED_BRANCH = "research/rq3-real-r1-memory-route"
ALLOWED_PREFIX = "evaluation/rq3_real_c4/r1_memory_route_execution/"
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_R1B_P3_MEMORY_ROUTE_EXECUTION_REVIEW_2026-09-01.zip"
)
REQUIRED_RELATIVE_FILES = {
    ALLOWED_PREFIX + "MEMORY_ROUTE_EXECUTION_REPORT.md",
    ALLOWED_PREFIX + "STATUS.md",
    ALLOWED_PREFIX + "build_review_zip.py",
    ALLOWED_PREFIX + "execution_output_v1/ROUTE_EXECUTION_REPORT.md",
    ALLOWED_PREFIX + "execution_output_v1/route_attempt_records_v1.jsonl",
    ALLOWED_PREFIX + "execution_output_v1/route_error_registry_v1.jsonl",
    ALLOWED_PREFIX + "execution_output_v1/route_execution_preflight_receipt_v1.json",
    ALLOWED_PREFIX + "execution_output_v1/route_execution_status_v1.json",
    ALLOWED_PREFIX + "execution_output_v1/route_terminal_results_v1.jsonl",
    ALLOWED_PREFIX + "execution_output_v1/route_usage_and_cost_v1.json",
    ALLOWED_PREFIX + "memory_route_execution_audit_v1.json",
    ALLOWED_PREFIX + "memory_route_execution_source_manifest_v1.json",
    ALLOWED_PREFIX + "route_execution_authorization_v1.json",
    ALLOWED_PREFIX + "tests/__init__.py",
    ALLOWED_PREFIX + "tests/test_memory_route_execution.py",
    ALLOWED_PREFIX + "validate_memory_route_execution_v1.py",
}
SECRET_VALUE = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})",
    re.IGNORECASE,
)


def command(*args: str) -> str:
    return subprocess.run(
        list(args), cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=(2026, 9, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((stat.S_IFREG | 0o644) & 0xFFFF) << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def publish_exclusive(path: Path, data: bytes) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite review ZIP: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            handle.write(data)
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def build(output: Path) -> dict[str, Any]:
    if command("git", "status", "--porcelain=v1"):
        raise RuntimeError("Review ZIP requires a clean committed worktree")
    branch = command("git", "branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Branch mismatch: {branch}")
    head = command("git", "rev-parse", "HEAD")
    commit_count = int(
        command("git", "rev-list", "--count", f"{STARTING_HEAD}..{head}")
    )
    if commit_count != 1:
        raise RuntimeError(
            f"Expected exactly one RQ3-REAL-R1B commit, observed {commit_count}"
        )
    names = {
        line
        for line in command(
            "git", "diff", "--name-only", f"{STARTING_HEAD}..{head}"
        ).splitlines()
        if line
    }
    if names != REQUIRED_RELATIVE_FILES:
        raise RuntimeError(
            "Review diff allowlist mismatch: "
            + repr(sorted(names ^ REQUIRED_RELATIVE_FILES))
        )
    if any(not name.startswith(ALLOWED_PREFIX) for name in names):
        raise RuntimeError("Review diff escaped the authorized directory")

    validation = validate_all()
    if validation["status"] != "PASS_RQ3_REAL_R1B_MEMORY_ROUTE_EXECUTION":
        raise RuntimeError("Offline execution validation did not pass")

    files: dict[str, bytes] = {}
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Review member is not a regular file: {name}")
        data = path.read_bytes()
        if SECRET_VALUE.search(data):
            raise RuntimeError(f"Potential credential value in review member: {name}")
        files[name] = data

    audit = json.loads(
        (HERE / "memory_route_execution_audit_v1.json").read_text(encoding="utf-8")
    )
    review_manifest = {
        "schema_version": "rq3-real-r1b-memory-route-review-manifest-v1",
        "status": "REVIEW_ONLY_NOT_EXECUTION_OR_INTEGRATION_AUTHORITY",
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "result_commit": head,
        "result_commit_count": commit_count,
        "strict_allowlist": sorted([*files, "REVIEW_MANIFEST.json"]),
        "member_sha256_excluding_self": {
            name: sha256(data) for name, data in sorted(files.items())
        },
        "execution_summary": {
            "state": audit["execution"]["state"],
            "component": "MEMORY",
            "logical_calls": audit["execution"]["logical_call_count"],
            "physical_attempts": audit["execution"]["physical_attempt_count"],
            "retries": audit["execution"]["retry_count"],
            "valid_terminal_results": audit["execution"]["valid_terminal_result_count"],
            "memory_yes_count": audit["memory_route_counts"]["memory_yes_count"],
            "memory_no_count": audit["memory_route_counts"]["memory_no_count"],
            "terminal_results_sha256": audit["execution"]["terminal_results_sha256"],
        },
        "contains_full_project": False,
        "contains_credentials": False,
        "contains_gold": False,
        "contains_scoring_outputs": False,
        "contains_memory_database_contents": False,
        "contains_generated_answers": False,
        "contains_judge_outputs": False,
        "contains_unscored_memory_route_results": True,
        "contains_authorization_record_as_historical_evidence": True,
        "authorizes_additional_provider_calls": False,
        "authorizes_route_integration": False,
        "p3_route_assembly_executed": False,
        "review_zip_build_provider_calls": 0,
    }
    files["REVIEW_MANIFEST.json"] = (
        json.dumps(review_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    archive_data = zip_bytes(files)
    publish_exclusive(output.resolve(), archive_data)
    return {
        "path": str(output.resolve()),
        "sha256": sha256(archive_data),
        "member_count": len(files),
        "result_commit": head,
        "status": review_manifest["status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
