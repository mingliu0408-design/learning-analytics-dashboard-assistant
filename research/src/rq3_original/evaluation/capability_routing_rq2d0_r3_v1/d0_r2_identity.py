"""Read-only verification of the frozen D0, D0-R1, and D0-R2 lineage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from evaluation.capability_routing_rq2d0_r2_v1.frozen_reference_authority import (
    load_frozen_contamination_reference_authority_v1_1,
)

from . import (
    FIXTURE28_SHA256,
    GOLD_BUNDLE_SHA256,
    P1_POLICY_ID,
    R1_REVIEW_ZIP_NAME,
    R1_REVIEW_ZIP_SHA256,
    R2_REVIEW_ZIP_NAME,
    R2_REVIEW_ZIP_SHA256,
    REFERENCE_AUTHORITY_COMMITMENT,
    RESULT_BRANCH,
    ROOT,
    SAFE_SCHEMA_ZIP_NAME,
    SAFE_SCHEMA_ZIP_SHA256,
    START_HEAD,
    START_PARENT,
    TRACK_B_COLUMN_COUNT,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    sha256_file,
)


class D0R2IdentityError(RuntimeError):
    pass


CHECKSUM_MANIFESTS = (
    (
        "evaluation/capability_routing_rq2d0_r2_v1/"
        "rq2d0_r2_output_checksums_v1.sha256",
        "cda0b09c8f3e46f760d907c9d6f4f6a49bacbef27afd3b8aa91a21db47aeebef",
        21,
    ),
    (
        "evaluation/capability_routing_rq2d0_r1_v1/"
        "rq2d0_r1_output_checksums_v1.sha256",
        "9b7d61e365e5ba912e93463f5678ec79d87e10513ba0470273084a862f258b96",
        30,
    ),
    (
        "evaluation/capability_routing_rq2d0_v1/rq2d0_output_checksums_v1.sha256",
        "e56422d1498143e5a2cfcd82fa0c54e9ce8864a1ca4ae91c6508a3c06c729c07",
        36,
    ),
    (
        "evaluation/capability_routing_rq2c1_r1_v1/"
        "rq2c1_r1_output_checksums_v1.sha256",
        "9e819215a980cb10ec0d76e08b6ab34016c8ff51a260517db3799215adc78fec",
        32,
    ),
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _verify_checksum_manifest(
    relative: str, expected_sha: str, expected_count: int
) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_sha:
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_STARTING_STATE_MISMATCH")
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, member = line.split(None, 1)
            entries.append((digest, member.strip().lstrip("*")))
    if len(entries) != expected_count or any(
        not (ROOT / member).is_file()
        or (ROOT / member).is_symlink()
        or sha256_file(ROOT / member) != digest
        for digest, member in entries
    ):
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_HISTORY_MUTATED")
    return {
        "status": "PASS",
        "checksum_count": expected_count,
        "manifest_sha256": expected_sha,
    }


def verify_frozen_d0_r2_identity() -> dict[str, Any]:
    if (
        _git("rev-parse", START_HEAD) != START_HEAD
        or _git("rev-parse", f"{START_HEAD}^") != START_PARENT
        or _git("branch", "--show-current") != RESULT_BRANCH
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_STARTING_STATE_MISMATCH")
    for name, expected in (
        (R2_REVIEW_ZIP_NAME, R2_REVIEW_ZIP_SHA256),
        (R1_REVIEW_ZIP_NAME, R1_REVIEW_ZIP_SHA256),
        (SAFE_SCHEMA_ZIP_NAME, SAFE_SCHEMA_ZIP_SHA256),
    ):
        path = ROOT.parent / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise D0R2IdentityError(
                "BLOCKED_RQ2_D0_R3_STARTING_STATE_MISMATCH"
            )
    checksums = {
        relative: _verify_checksum_manifest(relative, digest, count)
        for relative, digest, count in CHECKSUM_MANIFESTS
    }
    authority = load_frozen_contamination_reference_authority_v1_1()
    if authority.authority_commitment != REFERENCE_AUTHORITY_COMMITMENT:
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_STARTING_STATE_MISMATCH")
    preflight = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2d0_r2_v1/"
            "rq2d0_r2_preflight_report_v1.json"
        ).read_text(encoding="utf-8")
    )
    identities = preflight.get("frozen_identities", {})
    if (
        identities.get("p1_policy") != P1_POLICY_ID
        or identities.get("gold_bundle_sha256") != GOLD_BUNDLE_SHA256
        or identities.get("fixture28_sha256") != FIXTURE28_SHA256
        or identities.get("track_b_safe_sha256") != TRACK_B_SHA256
        or identities.get("track_b_safe_size_bytes") != TRACK_B_SIZE_BYTES
        or identities.get("track_b_safe_record_count") != TRACK_B_RECORD_COUNT
        or identities.get("track_b_safe_column_count") != TRACK_B_COLUMN_COUNT
    ):
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_STARTING_STATE_MISMATCH")
    changed_history = _git(
        "diff",
        "--name-only",
        START_HEAD,
        "--",
        "evaluation/capability_routing_rq2d0_v1",
        "evaluation/capability_routing_rq2d0_r1_v1",
        "evaluation/capability_routing_rq2d0_r2_v1",
    )
    if changed_history:
        raise D0R2IdentityError("BLOCKED_RQ2_D0_R3_HISTORY_MUTATED")
    return {
        "schema_version": "rq2d0-r3-preflight-report-v1",
        "status": "PASS",
        "starting_branch": "research/rq2-d0-r2-exact-reference-policy-repair",
        "starting_head": START_HEAD,
        "starting_parent": START_PARENT,
        "target_branch": RESULT_BRANCH,
        "starting_worktree_clean": True,
        "starting_index_clean": True,
        "remote_count": 0,
        "tag_count": 0,
        "review_zip_sha256": {
            "rq2d0_r2": R2_REVIEW_ZIP_SHA256,
            "rq2d0_r1": R1_REVIEW_ZIP_SHA256,
            "safe_schema": SAFE_SCHEMA_ZIP_SHA256,
        },
        "output_checksums": checksums,
        "frozen_identities": identities,
        "reference_authority_commitment": authority.authority_commitment,
        "d0_d0_r1_d0_r2_historical_files_unchanged": True,
        "raw_track_b_accessed": False,
        "real_blinding_key_created": False,
        "real_global_lock_created": False,
        "real_d1_lock_created": False,
        "real_packets_created": False,
        "provider_calls": 0,
        "network_access": False,
    }
