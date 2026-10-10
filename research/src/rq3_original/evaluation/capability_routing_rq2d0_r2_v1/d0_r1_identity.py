"""Read-only verification of the frozen RQ2-D0/R1 starting lineage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from . import (
    C1_R1_REVIEW_ZIP_NAME,
    C1_R1_REVIEW_ZIP_SHA256,
    D0_REVIEW_ZIP_NAME,
    D0_REVIEW_ZIP_SHA256,
    R1_REVIEW_ZIP_NAME,
    R1_REVIEW_ZIP_SHA256,
    RESULT_BRANCH,
    ROOT,
    SAFE_SCHEMA_ZIP_NAME,
    SAFE_SCHEMA_ZIP_SHA256,
    START_HEAD,
    START_PARENT,
    sha256_file,
)


class D0R1IdentityError(RuntimeError):
    pass


CHECKSUM_MANIFESTS = (
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
    relative: str, expected_sha256: str, expected_count: int
) -> dict[str, Any]:
    path = ROOT / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or sha256_file(path) != expected_sha256
    ):
        raise D0R1IdentityError("BLOCKED_RQ2_D0_R2_STARTING_STATE_MISMATCH")
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, member = line.split(None, 1)
        entries.append((digest, member.strip().lstrip("*")))
    if len(entries) != expected_count or any(
        not (ROOT / member).is_file()
        or (ROOT / member).is_symlink()
        or sha256_file(ROOT / member) != digest
        for digest, member in entries
    ):
        raise D0R1IdentityError("BLOCKED_RQ2_D0_R2_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "checksum_count": expected_count,
        "manifest_sha256": expected_sha256,
    }


def verify_frozen_d0_r1_identity() -> dict[str, Any]:
    if (
        _git("rev-parse", START_HEAD) != START_HEAD
        or _git("rev-parse", f"{START_HEAD}^") != START_PARENT
        or _git("branch", "--show-current") != RESULT_BRANCH
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise D0R1IdentityError("BLOCKED_RQ2_D0_R2_STARTING_STATE_MISMATCH")

    reviews = (
        (R1_REVIEW_ZIP_NAME, R1_REVIEW_ZIP_SHA256),
        (D0_REVIEW_ZIP_NAME, D0_REVIEW_ZIP_SHA256),
        (C1_R1_REVIEW_ZIP_NAME, C1_R1_REVIEW_ZIP_SHA256),
        (SAFE_SCHEMA_ZIP_NAME, SAFE_SCHEMA_ZIP_SHA256),
    )
    review_results: dict[str, str] = {}
    for name, expected in reviews:
        path = ROOT.parent / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise D0R1IdentityError(
                "BLOCKED_RQ2_D0_R2_STARTING_STATE_MISMATCH"
            )
        review_results[name] = expected

    checksums = {
        relative: _verify_checksum_manifest(relative, digest, count)
        for relative, digest, count in CHECKSUM_MANIFESTS
    }
    frozen_report_path = (
        ROOT
        / "evaluation/capability_routing_rq2d0_r1_v1/"
        "rq2d0_r1_preflight_report_v1.json"
    )
    frozen_report = json.loads(frozen_report_path.read_text(encoding="utf-8"))
    identities = frozen_report.get("frozen_identities", {})
    if (
        identities.get("p1_policy") != "P1_D05_SIGNAL_UNION"
        or identities.get("gold_bundle_sha256")
        != "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
        or identities.get("fixture28_sha256")
        != "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
        or identities.get("track_b_safe_sha256")
        != "52c14dbc9e79b3c211e47ffd72697ec6ed87eec0478353066eb5d2f1ab45f351"
        or identities.get("track_b_safe_size_bytes") != 65_095
        or identities.get("track_b_safe_record_count") != 48
        or identities.get("track_b_safe_column_count") != 47
    ):
        raise D0R1IdentityError("BLOCKED_RQ2_D0_R2_STARTING_STATE_MISMATCH")

    historical_changes = _git(
        "diff",
        "--name-only",
        START_HEAD,
        "--",
        "evaluation/capability_routing_rq2d0_v1",
        "evaluation/capability_routing_rq2d0_r1_v1",
    )
    if historical_changes:
        raise D0R1IdentityError("BLOCKED_RQ2_D0_R2_PROTECTED_SOURCE_MUTATED")
    return {
        "schema_version": "rq2d0-r2-preflight-report-v1",
        "status": "PASS",
        "starting_branch": "research/rq2-d0-r1-d1-prearm-repair",
        "starting_head": START_HEAD,
        "starting_parent": START_PARENT,
        "target_branch": RESULT_BRANCH,
        "starting_worktree_clean": True,
        "starting_index_clean": True,
        "remote_count": 0,
        "tag_count": 0,
        "review_zip_sha256": review_results,
        "output_checksums": checksums,
        "frozen_identities": identities,
        "d0_and_d0_r1_historical_files_unchanged": True,
        "raw_track_b_accessed": False,
        "real_blinding_key_created": False,
        "real_d1_lock_created": False,
        "real_packets_created": False,
        "provider_calls": 0,
        "network_access": False,
    }
