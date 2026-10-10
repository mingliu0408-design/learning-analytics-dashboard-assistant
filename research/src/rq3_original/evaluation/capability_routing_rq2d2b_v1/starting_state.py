"""Fail-closed verification of the frozen D2A and D1 starting authority."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from typing import Any

from . import (
    D1_CHECKSUM_COUNT,
    D1_CHECKSUM_RELATIVE,
    D1_GLOBAL_LOCK_RELATIVE,
    D1_GLOBAL_LOCK_SHA256,
    D1_REVIEW_ZIP_NAME,
    D1_REVIEW_ZIP_SHA256,
    D1_VALIDATION_RELATIVE,
    D2A_BLANK_ADJUDICATION_RELATIVE,
    D2A_BLANK_ADJUDICATION_SHA256,
    D2A_BLANK_ADJUDICATION_SIZE,
    D2A_CANONICAL_A_RELATIVE,
    D2A_CANONICAL_A_SHA256,
    D2A_CANONICAL_A_SIZE,
    D2A_CANONICAL_B_RELATIVE,
    D2A_CANONICAL_B_SHA256,
    D2A_CANONICAL_B_SIZE,
    D2A_CHECKSUM_COUNT,
    D2A_CHECKSUM_RELATIVE,
    D2A_DISAGREEMENT_RELATIVE,
    D2A_REVIEW_ZIP_NAME,
    D2A_REVIEW_ZIP_SHA256,
    ROOT,
    START_HEAD,
    START_PARENT,
    START_TREE_SHA256,
    TARGET_BRANCH,
    downloads_path,
    id_set_sha256,
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


def _validate_checksum_manifest(relative: Path, expected_count: int) -> int:
    lines = [
        line
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(lines) != expected_count:
        raise StartingStateError("historical output checksum count mismatch")
    for line in lines:
        digest, member = line.split("  ", 1)
        if sha256_file(ROOT / member) != digest:
            raise StartingStateError(f"historical output checksum mismatch: {member}")
    return len(lines)


def _validate_local_identity(
    relative: Path, expected_sha256: str, expected_size: int
) -> dict[str, Any]:
    path = ROOT / relative
    if (
        not _regular_non_symlink(path)
        or sha256_file(path) != expected_sha256
        or path.stat().st_size != expected_size
    ):
        raise StartingStateError("frozen D2A local identity mismatch")
    if git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
        raise StartingStateError("frozen D2A local input is not ignored")
    if not git("ls-files", "--error-unmatch", relative.as_posix(), check=False).returncode:
        raise StartingStateError("frozen D2A local input is tracked")
    return {
        "relative_local_path": relative.as_posix(),
        "sha256": expected_sha256,
        "size_bytes": expected_size,
        "regular_non_symlink": True,
        "ignored": True,
        "tracked": False,
    }


def validate_starting_state() -> dict[str, Any]:
    if git("rev-parse", f"{START_HEAD}^").stdout.decode().strip() != START_PARENT:
        raise StartingStateError("BLOCKED_RQ2_D2B_STARTING_STATE_MISMATCH")
    tree_sha = sha256_bytes(git("ls-tree", "-r", START_HEAD).stdout)
    if tree_sha != START_TREE_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D2B_STARTING_STATE_MISMATCH")
    if git("branch", "--show-current").stdout.decode().strip() != TARGET_BRANCH:
        raise StartingStateError("D2B target branch mismatch")
    if git("merge-base", "--is-ancestor", START_HEAD, "HEAD", check=False).returncode:
        raise StartingStateError("approved D2A HEAD is not an ancestor")
    relative_commits = int(
        git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative_commits not in {0, 1}:
        raise StartingStateError("unexpected relative commit count")
    if relative_commits == 1 and git("rev-parse", "HEAD^").stdout.decode().strip() != START_HEAD:
        raise StartingStateError("D2B commit does not directly follow D2A")
    if git("remote").stdout.strip() or git("tag", "--list").stdout.strip():
        raise StartingStateError("remote/tag count mismatch")

    for name, digest in (
        (D2A_REVIEW_ZIP_NAME, D2A_REVIEW_ZIP_SHA256),
        (D1_REVIEW_ZIP_NAME, D1_REVIEW_ZIP_SHA256),
    ):
        path = downloads_path(name)
        if not _regular_non_symlink(path) or sha256_file(path) != digest:
            raise StartingStateError("frozen review ZIP mismatch")
    d2a_checksums = _validate_checksum_manifest(D2A_CHECKSUM_RELATIVE, D2A_CHECKSUM_COUNT)
    d1_checksums = _validate_checksum_manifest(D1_CHECKSUM_RELATIVE, D1_CHECKSUM_COUNT)

    lock_path = ROOT / D1_GLOBAL_LOCK_RELATIVE
    if not _regular_non_symlink(lock_path) or sha256_file(lock_path) != D1_GLOBAL_LOCK_SHA256:
        raise StartingStateError("D1 global lock identity mismatch")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_required = {
        "state": "COMPLETED",
        "raw_open_count": 1,
        "raw_read_count": 1,
        "retry_permitted": False,
        "global_access_consumed": True,
    }
    if any(lock.get(key) != value for key, value in lock_required.items()):
        raise StartingStateError("D1 global lock lifecycle mismatch")
    d1_validation = json.loads((ROOT / D1_VALIDATION_RELATIVE).read_text(encoding="utf-8"))
    if d1_validation.get("escrow", {}).get("access_guard_after_completed") != "DENIED":
        raise StartingStateError("hidden legacy access guard is not DENIED")

    canonical_a = _validate_local_identity(
        D2A_CANONICAL_A_RELATIVE, D2A_CANONICAL_A_SHA256, D2A_CANONICAL_A_SIZE
    )
    canonical_b = _validate_local_identity(
        D2A_CANONICAL_B_RELATIVE, D2A_CANONICAL_B_SHA256, D2A_CANONICAL_B_SIZE
    )
    blank = _validate_local_identity(
        D2A_BLANK_ADJUDICATION_RELATIVE,
        D2A_BLANK_ADJUDICATION_SHA256,
        D2A_BLANK_ADJUDICATION_SIZE,
    )
    disagreement = json.loads((ROOT / D2A_DISAGREEMENT_RELATIVE).read_text(encoding="utf-8"))
    ids = [case["review_case_id"] for case in disagreement.get("cases", [])]
    if (
        disagreement.get("unique_disagreement_case_count") != 23
        or len(ids) != 23
        or len(set(ids)) != 23
    ):
        raise StartingStateError("D2A disagreement identity mismatch")
    return {
        "schema_version": "rq2d2b-starting-state-v1",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-d2a-track-b-review-agreement",
        "approved_starting_head": START_HEAD,
        "approved_starting_parent": START_PARENT,
        "starting_tree_sha256": START_TREE_SHA256,
        "target_branch": TARGET_BRANCH,
        "relative_commit_count": relative_commits,
        "remote_count": 0,
        "tag_count": 0,
        "d2a_review_zip_sha256": D2A_REVIEW_ZIP_SHA256,
        "d2a_output_checksums": f"{d2a_checksums}/{D2A_CHECKSUM_COUNT} PASS",
        "d1_review_zip_sha256": D1_REVIEW_ZIP_SHA256,
        "d1_output_checksums": f"{d1_checksums}/{D1_CHECKSUM_COUNT} PASS",
        "d1_global_lock": {
            "relative_local_path": D1_GLOBAL_LOCK_RELATIVE.as_posix(),
            "sha256": D1_GLOBAL_LOCK_SHA256,
            **lock_required,
            "modified": False,
        },
        "d2a_local_inputs": {
            "canonical_reviewer_a": canonical_a,
            "canonical_reviewer_b": canonical_b,
            "blank_adjudication": blank,
        },
        "d2a_disagreement_case_count": 23,
        "d2a_disagreement_case_id_set_sha256": id_set_sha256(ids),
        "hidden_legacy_access_guard": "DENIED",
    }
