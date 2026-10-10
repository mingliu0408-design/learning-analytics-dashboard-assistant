"""Read-only starting-state checks that never touch restricted Track-B rows."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from typing import Any
import zipfile

from . import (
    D2B_REVIEW_ZIP_NAME,
    D2B_REVIEW_ZIP_SHA256,
    EFFECTIVE_STATISTICAL_CONTRACT_RELATIVE,
    EFFECTIVE_STATISTICAL_CONTRACT_SHA256,
    EMPTY_D3_BRANCH,
    FULL_TEXT_GOLD_SHA256,
    FULL_TEXT_GOLD_SIZE,
    GOLD_BUNDLE_SHA256,
    LABEL_ONLY_GOLD_SHA256,
    METRIC_IMPLEMENTATION_RELATIVE,
    METRIC_IMPLEMENTATION_SHA256,
    ORIGINAL_STATISTICAL_CONTRACT_RELATIVE,
    ORIGINAL_STATISTICAL_CONTRACT_SHA256,
    R1_REVIEW_ZIP_MEMBERS,
    R1_REVIEW_ZIP_NAMES,
    R1_REVIEW_ZIP_SHA256,
    R1_REVIEW_ZIP_SIZE,
    ROOT,
    START_HEAD,
    START_PARENT,
    TARGET_BRANCH,
    downloads_path,
    sha256_file,
)


class StartingStateError(RuntimeError):
    pass


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False,
        env={**__import__("os").environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    return result


def _regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def _find_authorised_r1_zip() -> Path:
    for name in R1_REVIEW_ZIP_NAMES:
        path = downloads_path(name)
        if not _regular_non_symlink(path):
            continue
        if path.stat().st_size != R1_REVIEW_ZIP_SIZE or sha256_file(path) != R1_REVIEW_ZIP_SHA256:
            continue
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) == R1_REVIEW_ZIP_MEMBERS and archive.testzip() is None:
                return path
    raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")


def validate_starting_state_v1() -> dict[str, Any]:
    branch = _git("branch", "--show-current").stdout.decode().strip()
    head = _git("rev-parse", "HEAD").stdout.decode().strip()
    relative = int(_git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode())
    if branch != TARGET_BRANCH or relative not in {0, 1}:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    if relative == 0 and head != START_HEAD:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    if relative == 1 and _git("rev-parse", "HEAD^").stdout.decode().strip() != START_HEAD:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    if _git("rev-parse", f"{START_HEAD}^").stdout.decode().strip() != START_PARENT:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    empty_head = _git("rev-parse", EMPTY_D3_BRANCH).stdout.decode().strip()
    if empty_head != START_PARENT or _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")

    r1_zip = _find_authorised_r1_zip()
    r1_manifest = ROOT / "evaluation/capability_routing_rq2d3_r1_v1/rq2d3_r1_output_checksums_v1.sha256"
    r1_lines = [line for line in r1_manifest.read_text(encoding="utf-8").splitlines() if line]
    if len(r1_lines) != 20:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    for line in r1_lines:
        expected, relative_path = line.split("  ", 1)
        if sha256_file(ROOT / relative_path) != expected:
            raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")

    d2b_zip = downloads_path(D2B_REVIEW_ZIP_NAME)
    if not _regular_non_symlink(d2b_zip) or sha256_file(d2b_zip) != D2B_REVIEW_ZIP_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    d2b_checks = [
        line for line in (ROOT / "evaluation/capability_routing_rq2d2b_v1/rq2d2b_output_checksums_v1.sha256").read_text(encoding="utf-8").splitlines() if line
    ]
    d2b_validation = json.loads((ROOT / "evaluation/capability_routing_rq2d2b_v1/rq2d2b_validation_report_v1.json").read_text(encoding="utf-8"))
    gold = json.loads((ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json").read_text(encoding="utf-8"))
    if len(d2b_checks) != 28 or d2b_validation.get("status") != "PASS":
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    if (
        gold.get("gold_bundle_sha256") != GOLD_BUNDLE_SHA256
        or gold.get("record_count") != 48
        or gold["label_only_gold"].get("sha256") != LABEL_ONLY_GOLD_SHA256
        or gold["label_only_gold"].get("record_count") != 48
        or gold["full_text_gold"].get("sha256") != FULL_TEXT_GOLD_SHA256
        or gold["full_text_gold"].get("size_bytes") != FULL_TEXT_GOLD_SIZE
        or gold["full_text_gold"].get("record_count") != 48
    ):
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    fixed = {
        EFFECTIVE_STATISTICAL_CONTRACT_RELATIVE: EFFECTIVE_STATISTICAL_CONTRACT_SHA256,
        ORIGINAL_STATISTICAL_CONTRACT_RELATIVE: ORIGINAL_STATISTICAL_CONTRACT_SHA256,
        METRIC_IMPLEMENTATION_RELATIVE: METRIC_IMPLEMENTATION_SHA256,
    }
    if any(sha256_file(ROOT / relative_path) != expected for relative_path, expected in fixed.items()):
        raise StartingStateError("BLOCKED_RQ2_D3_R2_STARTING_STATE_MISMATCH")
    return {
        "schema_version": "rq2d3-r2-starting-state-v1",
        "status": "PASS",
        "starting_branch": "research/rq2-d3-r1-statistical-contract-completion",
        "starting_head": START_HEAD,
        "starting_parent": START_PARENT,
        "target_branch": TARGET_BRANCH,
        "relative_commits_from_r1": relative,
        "original_empty_d3_branch_head": empty_head,
        "initial_worktree_and_index": "CLEAN",
        "remote_count": 0,
        "tag_count": 0,
        "r1_review_zip_name": r1_zip.name,
        "r1_review_zip_sha256": R1_REVIEW_ZIP_SHA256,
        "r1_review_zip_size_bytes": R1_REVIEW_ZIP_SIZE,
        "r1_review_zip_member_count": R1_REVIEW_ZIP_MEMBERS,
        "r1_output_checksums": "20/20 PASS",
        "d2b_review_zip_sha256": D2B_REVIEW_ZIP_SHA256,
        "d2b_output_checksums": "28/28 PASS",
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "label_only_gold_metadata_sha256": LABEL_ONLY_GOLD_SHA256,
        "full_text_gold_metadata_sha256": FULL_TEXT_GOLD_SHA256,
        "full_text_gold_metadata_size_bytes": FULL_TEXT_GOLD_SIZE,
        "full_text_gold_content_open_count": 0,
        "label_row_open_count": 0,
    }
