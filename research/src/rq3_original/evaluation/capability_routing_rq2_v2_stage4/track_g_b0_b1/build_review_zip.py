"""Build the single deterministic Stage 4G review-only ZIP after commit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from . import PACKAGE_ROOT, PROJECT_ROOT


STARTING_HEAD = "1838a5d85db2dcaeba481c7404c36cbfbc94215e"
EXPECTED_BRANCH = "research/rq2-v2-stage4-g-b0-b1"
OUTPUT_PATH = Path("/Users/liuming/Downloads/RQ2_V2_STAGE_4G_B0_B1_DEV_REVIEW_2026-08-31.zip")
ZIP_PREFIX = "track_g_b0_b1"
FIXED_ZIP_TIME = (2026, 8, 31, 0, 0, 0)


class ReviewZipError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def build() -> dict[str, object]:
    if Path.cwd().resolve() != PROJECT_ROOT.resolve():
        raise ReviewZipError("review ZIP builder must run from the authorized worktree root")
    if git("branch", "--show-current") != EXPECTED_BRANCH:
        raise ReviewZipError("unexpected branch")
    ending_head = git("rev-parse", "HEAD")
    if git("status", "--short"):
        raise ReviewZipError("worktree must be clean before review packaging")
    if git("rev-list", "--count", f"{STARTING_HEAD}..{ending_head}") != "1":
        raise ReviewZipError("Stage 4G must be exactly one commit beyond the authorized start")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, ending_head],
        cwd=PROJECT_ROOT,
        check=True,
    )
    if OUTPUT_PATH.exists():
        raise ReviewZipError(f"refusing to overwrite existing review ZIP: {OUTPUT_PATH}")
    relative_root = PACKAGE_ROOT.relative_to(PROJECT_ROOT).as_posix()
    tracked = git("ls-tree", "-r", "--name-only", "HEAD", "--", relative_root).splitlines()
    if not tracked or any(not name.startswith(relative_root + "/") for name in tracked):
        raise ReviewZipError("tracked review allowlist is empty or escapes the Track 4G directory")
    members: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    for relative_name in sorted(tracked):
        source = PROJECT_ROOT / relative_name
        if not source.is_file() or source.suffix == ".pyc" or "__pycache__" in source.parts:
            raise ReviewZipError(f"invalid tracked review member: {relative_name}")
        data = source.read_bytes()
        archive_name = f"{ZIP_PREFIX}/{source.relative_to(PACKAGE_ROOT).as_posix()}"
        members.append(
            {"name": archive_name, "sha256": sha256_bytes(data), "size_bytes": len(data)}
        )
        payloads.append((archive_name, data))
    manifest = {
        "schema_version": "rq2-v2-stage4g-review-zip-manifest-v1",
        "starting_head": STARTING_HEAD,
        "ending_head": ending_head,
        "branch": EXPECTED_BRANCH,
        "review_scope": relative_root,
        "members": members,
        "full_project_included": False,
        "dev_source_gold_included": False,
        "c0_index_or_embeddings_included": False,
        "model_weights_included": False,
        "test_escrow_included": False,
        "provider_calls": 0,
    }
    manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with zipfile.ZipFile(OUTPUT_PATH, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads:
            archive.writestr(_zip_info(name), data)
        archive.writestr(_zip_info(f"{ZIP_PREFIX}/REVIEW_ZIP_MANIFEST.json"), manifest_data)
    result = {
        "status": "PASS",
        "path": str(OUTPUT_PATH),
        "sha256": hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest(),
        "size_bytes": OUTPUT_PATH.stat().st_size,
        "tracked_member_count": len(members),
        "manifest_member_count": len(members) + 1,
        "ending_head": ending_head,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    build()
