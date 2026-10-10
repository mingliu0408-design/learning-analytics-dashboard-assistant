"""Read-only D3-R1 starting-state and safe-authority verification."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from typing import Any
import zipfile

from . import (
    BASE_CONTRACT_RELATIVE,
    BASE_CONTRACT_SHA256,
    BASE_CONTRACT_SIZE,
    BLOCKER_ZIP_NAME,
    BLOCKER_ZIP_SHA256,
    BLOCKER_ZIP_SIZE,
    D2B_CHECKSUM_RELATIVE,
    D2B_GOLD_BUNDLE_SHA256,
    D2B_MANIFEST_RELATIVE,
    D2B_VALIDATION_RELATIVE,
    D2B_ZIP_NAME,
    D2B_ZIP_SHA256,
    METRIC_IMPLEMENTATION_RELATIVE,
    METRIC_IMPLEMENTATION_SHA256,
    ROOT,
    START_BRANCH,
    START_HEAD,
    START_PARENT,
    TARGET_BRANCH,
    downloads_path,
    sha256_file,
)


class StartingStateError(RuntimeError):
    pass


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False
    )
    if check and result.returncode:
        raise StartingStateError(f"git command failed: {' '.join(args)}")
    return result


def _regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def validate_starting_state() -> dict[str, Any]:
    if git("rev-parse", f"{START_HEAD}^").stdout.decode().strip() != START_PARENT:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    branch = git("branch", "--show-current").stdout.decode().strip()
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    relative = int(
        git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode().strip()
    )
    if branch != TARGET_BRANCH or relative not in {0, 1}:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    if relative == 0 and head != START_HEAD:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    if relative == 1 and git("rev-parse", "HEAD^").stdout.decode().strip() != START_HEAD:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    if git("remote").stdout.strip() or git("tag", "--list").stdout.strip():
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")

    blocker = downloads_path(BLOCKER_ZIP_NAME)
    if (
        not _regular_non_symlink(blocker)
        or blocker.stat().st_size != BLOCKER_ZIP_SIZE
        or sha256_file(blocker) != BLOCKER_ZIP_SHA256
    ):
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    with zipfile.ZipFile(blocker) as archive:
        if len(archive.namelist()) != 2 or archive.testzip() is not None:
            raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    d2b_zip = downloads_path(D2B_ZIP_NAME)
    if not _regular_non_symlink(d2b_zip) or sha256_file(d2b_zip) != D2B_ZIP_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")

    checksum_lines = [
        line
        for line in (ROOT / D2B_CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines()
        if line
    ]
    d2b_validation = json.loads(
        (ROOT / D2B_VALIDATION_RELATIVE).read_text(encoding="utf-8")
    )
    d2b_manifest = json.loads(
        (ROOT / D2B_MANIFEST_RELATIVE).read_text(encoding="utf-8")
    )
    if (
        len(checksum_lines) != 28
        or d2b_validation.get("status") != "PASS"
        or d2b_manifest.get("gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256
    ):
        raise StartingStateError("BLOCKED_RQ2_D3_R1_STARTING_STATE_MISMATCH")
    base = ROOT / BASE_CONTRACT_RELATIVE
    if sha256_file(base) != BASE_CONTRACT_SHA256 or base.stat().st_size != BASE_CONTRACT_SIZE:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_ORIGINAL_CONTRACT_IDENTITY")
    if sha256_file(ROOT / METRIC_IMPLEMENTATION_RELATIVE) != METRIC_IMPLEMENTATION_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D3_R1_METRIC_CONTRACT")
    return {
        "schema_version": "rq2d3-r1-starting-state-v1",
        "status": "PASS",
        "approved_starting_branch": START_BRANCH,
        "approved_starting_head": START_HEAD,
        "approved_starting_parent": START_PARENT,
        "target_branch": TARGET_BRANCH,
        "relative_commits_from_d2b": relative,
        "initial_worktree_and_index_gate": "CLEAN",
        "remote_count": 0,
        "tag_count": 0,
        "blocker_review_zip_sha256": BLOCKER_ZIP_SHA256,
        "blocker_review_zip_size_bytes": BLOCKER_ZIP_SIZE,
        "blocker_review_zip_member_count": 2,
        "d2b_review_zip_sha256": D2B_ZIP_SHA256,
        "d2b_output_checksum_manifest": "28/28 PASS",
        "d2b_gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
        "original_statistical_contract_sha256": BASE_CONTRACT_SHA256,
        "original_statistical_contract_size_bytes": BASE_CONTRACT_SIZE,
        "frozen_metric_implementation_sha256": METRIC_IMPLEMENTATION_SHA256,
        "restricted_asset_access_count": 0,
        "label_record_access_count": 0,
    }
