#!/usr/bin/env python3
"""Build the deterministic, integration-only I0 review ZIP after commit."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import subprocess
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_COMMIT = "7eda7aabc6f11071906898d124e5d1eed180df6a"
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ3_REAL_I0_C4_INTEGRATION_ROUTE_HARNESS_REVIEW_2026-09-01.zip"
)
EXACT_ALLOWED = {
    "C4_REAL_EVIDENCE_SYNTHESIS_BINDING.md",
    "C4_REAL_INTEGRATION_ARCHITECTURE.md",
    "C4_REAL_MEMORY_EXPERIMENT_SCOPE.md",
    "evaluation/rq3_real_c4/mock_providers.py",
    "evaluation/rq3_real_c4/run_c4_real_replay.py",
    "tests/test_c4_real_service.py",
    "utils/c4_real_adapters.py",
    "utils/c4_real_contracts.py",
    "utils/c4_real_factory.py",
    "utils/c4_real_service.py",
}
ALLOWED_PREFIX = "evaluation/rq3_real_c4/i0_integration/"
SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{16,}|(?:api[_-]?key|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_./+-]{16,})",
    re.IGNORECASE,
)


def command(*args: str) -> str:
    return subprocess.run(
        list(args), cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=(2026, 9, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((stat.S_IFREG | 0o644) & 0xFFFF) << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def build(output: Path, base_commit: str) -> dict[str, Any]:
    if command("git", "status", "--porcelain=v1"):
        raise RuntimeError("Review ZIP requires a clean committed worktree")
    head = command("git", "rev-parse", "HEAD")
    branch = command("git", "branch", "--show-current")
    names = [
        value
        for value in command("git", "diff", "--name-only", f"{base_commit}..{head}").splitlines()
        if value
    ]
    if not names:
        raise RuntimeError("No integration commit content found")
    unexpected = [
        name for name in names if name not in EXACT_ALLOWED and not name.startswith(ALLOWED_PREFIX)
    ]
    if unexpected:
        raise RuntimeError(f"Review allowlist rejected paths: {unexpected}")
    files: dict[str, bytes] = {}
    for name in names:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Review member is not a regular file: {name}")
        data = path.read_bytes()
        if SECRET.search(data):
            raise RuntimeError(f"Potential credential value in review member: {name}")
        files[name] = data
    route_plan = json.loads(
        (HERE / "c4_real_route_execution_plan_v1.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "rq3-real-i0-review-manifest-v1",
        "status": "REVIEW_ONLY_NOT_EXECUTION_AUTHORITY",
        "branch": branch,
        "base_after_authorized_cherry_picks": base_commit,
        "integration_commit": head,
        "strict_allowlist": sorted([*files, "REVIEW_MANIFEST.json"]),
        "member_sha256_excluding_self": {
            name: sha(data) for name, data in sorted(files.items())
        },
        "route_packages_external_not_embedded": route_plan["packages"],
        "contains_full_project": False,
        "contains_credentials": False,
        "contains_provider_outputs": False,
        "contains_p3_routes": False,
        "contains_generated_responses": False,
        "contains_judge_scores": False,
        "provider_calls_in_i0": 0,
    }
    files["REVIEW_MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output.write_bytes(zip_bytes(files))
    return {
        "path": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "member_count": len(files),
        "integration_commit": head,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-commit", default=BASE_COMMIT)
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), args.base_commit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
