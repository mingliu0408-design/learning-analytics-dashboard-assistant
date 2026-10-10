"""Read-only RQ2-D3-R3 starting-state and immutable identity checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile
from typing import Any

from . import (
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    METRIC_IMPLEMENTATION_SHA256,
    ROOT,
    START_BRANCH,
    START_HEAD,
    START_PARENT,
    TARGET_BRANCH,
    sha256_file,
)


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _verify_checksum_manifest(relative: str, expected_count: int, *, authorised_changed: set[str] = frozenset()) -> int:
    lines = [
        line
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(lines) != expected_count:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    passed = 0
    for line in lines:
        expected, path = line.split("  ", 1)
        if path in authorised_changed:
            continue
        if sha256_file(ROOT / path) != expected:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
        passed += 1
    return passed


def _zip_identity(name: str, expected_sha: str, size: int, members: int) -> None:
    path = Path.home() / "Downloads" / name
    value = os.lstat(path)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_size != size
        or sha256_file(path) != expected_sha
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != members or archive.testzip() is not None:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")


def validate_starting_state_v1() -> dict[str, Any]:
    branch = _git("branch", "--show-current").stdout.decode().strip()
    head = _git("rev-parse", "HEAD").stdout.decode().strip()
    parent = _git("rev-parse", "HEAD^").stdout.decode().strip()
    if branch == START_BRANCH:
        branch_ok = head == START_HEAD and parent == START_PARENT
    else:
        branch_ok = branch == TARGET_BRANCH and (
            head == START_HEAD or parent == START_HEAD
        )
    if not branch_ok:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    if (
        _git("remote").stdout.strip()
        or _git("tag", "--list").stdout.strip()
        or _git("status", "--porcelain=v1", "--untracked-files=all").stdout.strip()
        and head != START_HEAD
    ):
        # During the authorised build HEAD is still START_HEAD and the target branch is dirty.
        if head != START_HEAD:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    _zip_identity(
        "RQ2_D3_R2_TRACK_B_FINAL_EVALUATION_HARNESS_REVIEW_2026-08-29.zip",
        "19585f4fae23cefdf1d66b9fabce8d0f77efaa5e412cac33a21b2a913a4423fe",
        71860,
        46,
    )
    _zip_identity(
        "RQ2_D3_R1_STATISTICAL_CONTRACT_COMPLETION_REVIEW_2026-08-29.zip",
        "767628838ca221435f0cdc8097755185953d141ba64015b4f17d54d9050bc229",
        41604,
        24,
    )
    authorised = {
        "evaluation/capability_routing_rq2d3_r2_v1/rq2d4_global_one_shot_contract.py"
    }
    r2_passed = _verify_checksum_manifest(
        "evaluation/capability_routing_rq2d3_r2_v1/rq2d3_r2_output_checksums_v1.sha256",
        41,
        authorised_changed=authorised,
    )
    r1_passed = _verify_checksum_manifest(
        "evaluation/capability_routing_rq2d3_r1_v1/rq2d3_r1_output_checksums_v1.sha256",
        20,
    )
    identities = {
        "statistical_contract": (
            "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json",
            D3_R1_STATISTICAL_SHA256,
        ),
        "grouping_ledger": (
            "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl",
            D3_R2_GROUPING_SHA256,
        ),
        "metric_implementation": (
            "evaluation/capability_routing_rq2b_v1/capability_metrics.py",
            METRIC_IMPLEMENTATION_SHA256,
        ),
    }
    for relative, expected in identities.values():
        if sha256_file(ROOT / relative) != expected:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    manifest = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json"
        ).read_text()
    )
    if manifest.get("gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    return {
        "schema_version": "rq2d3-r3-starting-state-v1",
        "status": "PASS",
        "starting_branch": START_BRANCH,
        "starting_head": START_HEAD,
        "starting_parent": START_PARENT,
        "target_branch": TARGET_BRANCH,
        "r2_review_zip": "46 members / SHA PASS",
        "r1_review_zip": "24 members / SHA PASS",
        "r2_unchanged_checksum_entries": f"{r2_passed}/40 PASS",
        "r2_authorised_supersession_file_count": 1,
        "r1_output_checksums": f"{r1_passed}/20 PASS",
        "remote_count": 0,
        "tag_count": 0,
    }
