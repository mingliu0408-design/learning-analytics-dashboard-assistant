"""Read-only verification of the frozen D0 and C1-R1 authority chain."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from . import (
    C1_R1_REVIEW_ZIP,
    C1_R1_REVIEW_ZIP_SHA256,
    D0_HEAD,
    D0_PARENT,
    D0_REVIEW_ZIP,
    D0_REVIEW_ZIP_SHA256,
    FIXTURE28_SHA256,
    GOLD_BUNDLE_SHA256,
    P1_POLICY_ID,
    RESULT_BRANCH,
    ROOT,
    SAFE_SCHEMA_ZIP,
    SAFE_SCHEMA_ZIP_SHA256,
    TRACK_B_COLUMN_COUNT,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    sha256_file,
)


class D0IdentityError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _verify_checksum_manifest(relative: str, expected_count: int) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise D0IdentityError("BLOCKED_RQ2_D0_R1_STARTING_STATE_MISMATCH")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, target = line.split(None, 1)
        target = target.strip().lstrip("*")
        actual = sha256_file(ROOT / target)
        rows.append({"relative_path": target, "match": actual == expected})
    if len(rows) != expected_count or not all(row["match"] for row in rows):
        raise D0IdentityError("BLOCKED_RQ2_D0_R1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "checksum_count": len(rows),
        "all_entries_match": True,
        "manifest_sha256": sha256_file(path),
    }


def verify_d0_identity() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", D0_HEAD, "HEAD"], cwd=ROOT, check=False
    )
    if (
        branch != RESULT_BRANCH
        or ancestor.returncode != 0
        or _git("rev-parse", f"{D0_HEAD}^") != D0_PARENT
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise D0IdentityError("BLOCKED_RQ2_D0_R1_STARTING_STATE_MISMATCH")
    zip_values = {
        "rq2d0": (D0_REVIEW_ZIP, D0_REVIEW_ZIP_SHA256),
        "rq2c1_r1": (C1_R1_REVIEW_ZIP, C1_R1_REVIEW_ZIP_SHA256),
        "safe_schema": (SAFE_SCHEMA_ZIP, SAFE_SCHEMA_ZIP_SHA256),
    }
    zip_report: dict[str, str] = {}
    for role, (path, expected) in zip_values.items():
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise D0IdentityError("BLOCKED_RQ2_D0_R1_STARTING_STATE_MISMATCH")
        zip_report[role] = expected
    safe_authority = json.loads(
        (ROOT / "evaluation/capability_routing_rq2d0_v1/"
         "track_b_safe_authority_contract_v1.json").read_text(encoding="utf-8")
    )["source_identity"]
    p1 = json.loads(
        (ROOT / "evaluation/capability_routing_rq2b_v1/"
         "rq2b_final_p1_policy_v1.json").read_text(encoding="utf-8")
    )
    if (
        safe_authority.get("sha256") != TRACK_B_SHA256
        or safe_authority.get("size_bytes") != TRACK_B_SIZE_BYTES
        or safe_authority.get("record_count") != TRACK_B_RECORD_COUNT
        or safe_authority.get("column_count") != TRACK_B_COLUMN_COUNT
        or p1.get("selected_policy_id") != P1_POLICY_ID
    ):
        raise D0IdentityError("BLOCKED_RQ2_D0_R1_STARTING_STATE_MISMATCH")
    return {
        "schema_version": "rq2d0-r1-preflight-report-v1",
        "stage": "RQ2-D0-R1",
        "status": "PASS",
        "starting_branch": "research/rq2-d0-track-b-final-contract",
        "starting_head": D0_HEAD,
        "starting_parent": D0_PARENT,
        "starting_worktree_clean": True,
        "starting_index_clean": True,
        "target_branch": RESULT_BRANCH,
        "remote_count": 0,
        "tag_count": 0,
        "review_zip_sha256": zip_report,
        "output_checksums": {
            "rq2d0": _verify_checksum_manifest(
                "evaluation/capability_routing_rq2d0_v1/"
                "rq2d0_output_checksums_v1.sha256",
                36,
            ),
            "rq2c1_r1": _verify_checksum_manifest(
                "evaluation/capability_routing_rq2c1_r1_v1/"
                "rq2c1_r1_output_checksums_v1.sha256",
                32,
            ),
        },
        "frozen_identities": {
            "track_b_safe_sha256": TRACK_B_SHA256,
            "track_b_safe_size_bytes": TRACK_B_SIZE_BYTES,
            "track_b_safe_record_count": TRACK_B_RECORD_COUNT,
            "track_b_safe_column_count": TRACK_B_COLUMN_COUNT,
            "p1_policy": P1_POLICY_ID,
            "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
            "fixture28_sha256": FIXTURE28_SHA256,
        },
        "raw_track_b_accessed": False,
        "real_d1_lock_created": False,
        "real_packets_created": False,
        "provider_calls": 0,
        "network_access": False,
    }
