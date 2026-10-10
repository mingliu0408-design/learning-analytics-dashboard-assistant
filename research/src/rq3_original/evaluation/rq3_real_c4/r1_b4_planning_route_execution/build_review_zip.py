#!/usr/bin/env python3
"""Build the clean-commit, review-only RQ3-REAL-R1C handoff ZIP."""

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
import tempfile
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STARTING_HEAD = "246e6ff64003caa4787716e00f050a2451dfca01"
EXPECTED_BRANCH = "research/rq3-real-r1-b4-planning-route"
ALLOWED_PREFIX = "evaluation/rq3_real_c4/r1_b4_planning_route_execution/"
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_R1C_P3_B4_PLANNING_ROUTE_EXECUTION_REVIEW_2026-09-01.zip"
)
REQUIRED_RELATIVE_FILES = {
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/B4_PLANNING_ROUTE_EXECUTION_REPORT.md",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/STATUS.md",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/b4_planning_route_execution_audit_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/b4_planning_route_execution_source_manifest_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/build_review_zip.py",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/ROUTE_EXECUTION_REPORT.md",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_attempt_records_v1.jsonl",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_error_registry_v1.jsonl",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_execution_preflight_receipt_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_execution_status_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_terminal_results_v1.jsonl",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/execution_output_v1/route_usage_and_cost_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/route_execution_authorization_v1.json",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/tests/__init__.py",
    "evaluation/rq3_real_c4/r1_b4_planning_route_execution/tests/test_b4_planning_route_execution.py",
}
SECRET_VALUE = re.compile(
    rb"(?:s[k]-(?:proj-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})",
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
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"Refusing to overwrite review ZIP: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
    if command("git", "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("Review ZIP requires a clean committed worktree")
    branch = command("git", "branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Branch mismatch: {branch}")
    head = command("git", "rev-parse", "HEAD")
    commit_count = int(command("git", "rev-list", "--count", f"{STARTING_HEAD}..{head}"))
    if commit_count != 1:
        raise RuntimeError(f"Expected exactly one R1C commit, observed {commit_count}")
    names = {
        line
        for line in command("git", "diff", "--name-only", f"{STARTING_HEAD}..{head}").splitlines()
        if line
    }
    if names != REQUIRED_RELATIVE_FILES:
        raise RuntimeError(
            f"R1C review diff allowlist mismatch: {sorted(names ^ REQUIRED_RELATIVE_FILES)}"
        )
    if any(not name.startswith(ALLOWED_PREFIX) for name in names):
        raise RuntimeError("R1C diff escaped the authorized execution directory")

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
        (HERE / "b4_planning_route_execution_audit_v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = {
        "schema_version": "rq3-real-r1c-b4-planning-route-review-manifest-v1",
        "status": "REVIEW_ONLY_NOT_ROUTE_INTEGRATION_AUTHORITY",
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "execution_commit": head,
        "execution_commit_count": commit_count,
        "strict_allowlist": sorted([*files, "REVIEW_MANIFEST.json"]),
        "member_sha256_excluding_self": {
            name: sha256(data) for name, data in sorted(files.items())
        },
        "authoritative_package_not_embedded": {
            "path": "/Users/liuming/Downloads/C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip",
            "sha256": "56acb70b6ff16f346f5f0b14b18c22b7eeb7853b0bff11db546841aba03b7de0",
        },
        "execution_state": audit["execution"]["state"],
        "logical_calls": audit["execution"]["logical_requests"],
        "physical_attempts": audit["execution"]["physical_attempts"],
        "retries": audit["execution"]["retry_count"],
        "valid_terminal_results": audit["coverage"]["valid_terminal_results"],
        "terminal_results_sha256": audit["terminal_results_sha256"],
        "contains_full_project": False,
        "contains_credentials": False,
        "contains_gold": False,
        "contains_accuracy_or_route_scoring": False,
        "contains_rag_specialist_results": False,
        "contains_memory_specialist_results": False,
        "contains_generated_answers": False,
        "contains_judge_outputs": False,
        "route_integration_executed": False,
        "review_zip_grants_execution_authority": False,
    }
    files["REVIEW_MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    data = zip_bytes(files)
    publish_exclusive(output.resolve(), data)
    return {
        "path": str(output.resolve()),
        "sha256": sha256(data),
        "member_count": len(files),
        "execution_commit": head,
        "status": manifest["status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
