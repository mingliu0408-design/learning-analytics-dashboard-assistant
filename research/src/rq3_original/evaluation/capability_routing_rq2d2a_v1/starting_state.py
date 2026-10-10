"""Fail-closed verification of the frozen RQ2-D1 starting authority."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from typing import Any

from . import (
    BLANK_A_RELATIVE,
    BLANK_A_SHA256,
    BLANK_B_RELATIVE,
    BLANK_B_SHA256,
    D1_CHECKSUM_COUNT,
    D1_CHECKSUM_RELATIVE,
    D1_GLOBAL_LOCK_RELATIVE,
    D1_GLOBAL_LOCK_SHA256,
    D1_REVIEW_ZIP_NAME,
    D1_REVIEW_ZIP_SHA256,
    D1_VALIDATION_RELATIVE,
    PACKET_FIELDS,
    ROOT,
    START_HEAD,
    START_PARENT,
    START_TREE_SHA256,
    TARGET_BRANCH,
    csv_rows,
    downloads_path,
    sha256_bytes,
    sha256_file,
)


class StartingStateError(RuntimeError):
    pass


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if check and result.returncode:
        raise StartingStateError(f"git command failed: {' '.join(args)}")
    return result


def _regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def starting_tree_sha256() -> str:
    return sha256_bytes(git("ls-tree", "-r", START_HEAD).stdout)


def _validate_d1_checksums() -> int:
    manifest = ROOT / D1_CHECKSUM_RELATIVE
    lines = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    if len(lines) != D1_CHECKSUM_COUNT:
        raise StartingStateError("D1 checksum count mismatch")
    for line in lines:
        digest, relative = line.split("  ", 1)
        if sha256_file(ROOT / relative) != digest:
            raise StartingStateError(f"D1 checksum mismatch: {relative}")
    return len(lines)


def _validate_blank_packet(relative: Path, expected_sha256: str) -> dict[str, Any]:
    path = ROOT / relative
    if not _regular_non_symlink(path) or sha256_file(path) != expected_sha256:
        raise StartingStateError("BLOCKED_RQ2_D2A_BLANK_PACKET_IDENTITY")
    value = path.read_bytes()
    rows = csv_rows(path)
    if (
        len(rows) != 48
        or not rows
        or tuple(rows[0]) != PACKET_FIELDS
        or not value.startswith(b"\xef\xbb\xbf")
        or value.count(b"\r\n") != 49
        or value.count(b"\n") != 49
        or not value.endswith(b"\r\n")
    ):
        raise StartingStateError("BLOCKED_RQ2_D2A_BLANK_PACKET_IDENTITY")
    if git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
        raise StartingStateError("blank packet is not ignored")
    if not git("ls-files", "--error-unmatch", relative.as_posix(), check=False).returncode:
        raise StartingStateError("blank packet must be untracked")
    return {
        "relative_local_path": relative.as_posix(),
        "sha256": expected_sha256,
        "size_bytes": len(value),
        "record_count": 48,
        "column_count": 21,
        "utf8_bom": True,
        "crlf_only": True,
        "ignored": True,
        "tracked": False,
    }


def validate_starting_state() -> dict[str, Any]:
    if git("rev-parse", f"{START_HEAD}^").stdout.decode().strip() != START_PARENT:
        raise StartingStateError("BLOCKED_RQ2_D2A_STARTING_STATE_MISMATCH")
    if starting_tree_sha256() != START_TREE_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D2A_STARTING_STATE_MISMATCH")
    branch = git("branch", "--show-current").stdout.decode().strip()
    if branch != TARGET_BRANCH:
        raise StartingStateError("target branch mismatch")
    if git("merge-base", "--is-ancestor", START_HEAD, "HEAD", check=False).returncode:
        raise StartingStateError("approved D1 HEAD is not an ancestor")
    relative_commits = int(
        git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative_commits not in {0, 1}:
        raise StartingStateError("unexpected relative commit count")
    if relative_commits == 1 and git("rev-parse", "HEAD^").stdout.decode().strip() != START_HEAD:
        raise StartingStateError("D2A commit does not directly follow D1")
    if git("remote").stdout.strip() or git("tag", "--list").stdout.strip():
        raise StartingStateError("remote/tag count mismatch")

    review_zip = downloads_path(D1_REVIEW_ZIP_NAME)
    if not _regular_non_symlink(review_zip) or sha256_file(review_zip) != D1_REVIEW_ZIP_SHA256:
        raise StartingStateError("D1 review ZIP mismatch")
    checksum_count = _validate_d1_checksums()

    lock_path = ROOT / D1_GLOBAL_LOCK_RELATIVE
    if not _regular_non_symlink(lock_path) or sha256_file(lock_path) != D1_GLOBAL_LOCK_SHA256:
        raise StartingStateError("D1 global lock identity mismatch")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    required = {
        "state": "COMPLETED",
        "raw_open_count": 1,
        "raw_read_count": 1,
        "retry_permitted": False,
        "global_access_consumed": True,
    }
    if any(lock.get(key) != value for key, value in required.items()):
        raise StartingStateError("D1 global lock lifecycle mismatch")
    d1_validation = json.loads((ROOT / D1_VALIDATION_RELATIVE).read_text(encoding="utf-8"))
    if d1_validation.get("escrow", {}).get("access_guard_after_completed") != "DENIED":
        raise StartingStateError("hidden legacy access guard is not DENIED")

    blank_a = _validate_blank_packet(BLANK_A_RELATIVE, BLANK_A_SHA256)
    blank_b = _validate_blank_packet(BLANK_B_RELATIVE, BLANK_B_SHA256)
    return {
        "schema_version": "rq2d2a-starting-state-v1",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-d1-track-b-mapping-packets",
        "approved_starting_head": START_HEAD,
        "approved_starting_parent": START_PARENT,
        "starting_tree_sha256": START_TREE_SHA256,
        "target_branch": TARGET_BRANCH,
        "relative_commit_count": relative_commits,
        "remote_count": 0,
        "tag_count": 0,
        "d1_review_zip_sha256": D1_REVIEW_ZIP_SHA256,
        "d1_output_checksums": f"{checksum_count}/{D1_CHECKSUM_COUNT} PASS",
        "global_lock": {
            "relative_local_path": D1_GLOBAL_LOCK_RELATIVE.as_posix(),
            "sha256": D1_GLOBAL_LOCK_SHA256,
            **required,
            "modified": False,
        },
        "blank_packets": {"reviewer_a_template": blank_a, "reviewer_b_template": blank_b},
        "hidden_legacy_access_guard": "DENIED",
    }
