#!/usr/bin/env python3
"""Build the clean-commit, integration-only I0-R1 internal review ZIP."""

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
BASE_COMMIT = "23c1a016b0d797b9e975baa65994321eb3d2fd67"
EXPECTED_BRANCH = "research/rq3-real-c4-i0-integration"
ALLOWED_PREFIX = "evaluation/rq3_real_c4/i0_integration/"
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_I0_R1_ROUTE_PACKAGE_CONFIG_INTEGRITY_REVIEW_2026-09-01.zip"
)
REQUIRED_RELATIVE_FILES = {
    "evaluation/rq3_real_c4/i0_integration/C4_REAL_P3_ROUTE_PACKAGE_CONFIGURATION_REPAIR.md",
    "evaluation/rq3_real_c4/i0_integration/STATUS.md",
    "evaluation/rq3_real_c4/i0_integration/build_r1_route_packages.py",
    "evaluation/rq3_real_c4/i0_integration/build_r1_review_zip.py",
    "evaluation/rq3_real_c4/i0_integration/route_execution_runner_v2.py",
    "evaluation/rq3_real_c4/i0_integration/route_package_validator_v1.py",
    "evaluation/rq3_real_c4/i0_integration/validate_r1_route_packages.py",
    "evaluation/rq3_real_c4/i0_integration/c4_real_frozen_component_configuration_verification_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_original_route_packages_supersession_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_r1_old_new_identity_audit_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_r1_execution_contract_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_r1_route_package_summaries_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_i0_r1_build_report_v1.json",
    "evaluation/rq3_real_c4/i0_integration/tests/test_i0_r1_route_package_repair.py",
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
    if command("git", "status", "--porcelain=v1"):
        raise RuntimeError("Review ZIP requires a clean committed worktree")
    branch = command("git", "branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Branch mismatch: {branch}")
    head = command("git", "rev-parse", "HEAD")
    commit_count = int(command("git", "rev-list", "--count", f"{BASE_COMMIT}..{head}"))
    if commit_count != 1:
        raise RuntimeError(f"Expected exactly one I0-R1 commit, observed {commit_count}")
    names = [
        line
        for line in command("git", "diff", "--name-only", f"{BASE_COMMIT}..{head}").splitlines()
        if line
    ]
    if set(names) != REQUIRED_RELATIVE_FILES:
        raise RuntimeError(
            f"I0-R1 review diff allowlist mismatch: {sorted(set(names) ^ REQUIRED_RELATIVE_FILES)}"
        )
    if any(not name.startswith(ALLOWED_PREFIX) for name in names):
        raise RuntimeError("I0-R1 diff escaped the integration directory")

    files: dict[str, bytes] = {}
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Review member is not a regular file: {name}")
        data = path.read_bytes()
        if SECRET_VALUE.search(data):
            raise RuntimeError(f"Potential credential value in review member: {name}")
        files[name] = data

    summaries = json.loads(
        (HERE / "c4_real_r1_route_package_summaries_v1.json").read_text(
            encoding="utf-8"
        )
    )
    supersession = json.loads(
        (HERE / "c4_real_original_route_packages_supersession_v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = {
        "schema_version": "rq3-real-i0-r1-review-manifest-v1",
        "status": "REVIEW_ONLY_NOT_EXECUTION_AUTHORITY",
        "branch": branch,
        "starting_head": BASE_COMMIT,
        "integration_commit": head,
        "integration_commit_count": commit_count,
        "strict_allowlist": sorted([*files, "REVIEW_MANIFEST.json"]),
        "member_sha256_excluding_self": {
            name: sha256(data) for name, data in sorted(files.items())
        },
        "external_r1_packages_not_embedded": summaries["packages"],
        "original_packages_not_embedded": supersession["packages"],
        "contains_full_project": False,
        "contains_credentials": False,
        "contains_course_source_documents": False,
        "contains_memory_database_contents": False,
        "contains_generated_routes": False,
        "contains_generated_answers": False,
        "contains_judge_outputs": False,
        "provider_calls_in_i0_r1": 0,
        "route_executions_in_i0_r1": 0,
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
        "integration_commit": head,
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
