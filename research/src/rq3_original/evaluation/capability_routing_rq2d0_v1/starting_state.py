"""Fail-closed RQ2-D0 starting-state and frozen-identity checks."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from . import (
    C1_CHECKSUM_RELATIVE,
    C1_REVIEW_ZIP,
    C1_REVIEW_ZIP_SHA256,
    C1_R1_CHECKSUM_RELATIVE,
    C1_R1_REVIEW_ZIP,
    C1_R1_REVIEW_ZIP_SHA256,
    EXPECTED_CHECKSUM_COUNTS,
    FIXTURE_RELATIVE,
    FIXTURE_SHA256,
    GOLD_BUNDLE_SHA256,
    P1_POLICY_ID,
    P1_POLICY_RELATIVE,
    P1_POLICY_SHA256,
    R5_CHECKSUM_RELATIVE,
    R5_REVIEW_ZIP,
    R5_REVIEW_ZIP_SHA256,
    RESULT_BRANCH,
    ROOT,
    RQ1_ROUTER,
    STARTING_BRANCH,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)


class StartingStateError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _verify_checksum_manifest(relative: Path, expected_count: int) -> dict[str, Any]:
    path = ROOT / relative
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, member = line.split(None, 1)
        member = member.strip().lstrip("*")
        entries.append((digest, member))
    failed = [
        member
        for digest, member in entries
        if not (ROOT / member).is_file()
        or (ROOT / member).is_symlink()
        or sha256_file(ROOT / member) != digest
    ]
    if len(entries) != expected_count or failed:
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "checksum_count": len(entries),
        "failure_count": 0,
        "manifest_sha256": sha256_file(path),
    }


def _frozen_result_identities() -> dict[str, Any]:
    p1 = json.loads((ROOT / P1_POLICY_RELATIVE).read_text(encoding="utf-8"))
    selected = p1.get("policy_id") or p1.get("selected_policy_id") or p1.get("final_policy")
    if selected != P1_POLICY_ID or sha256_file(ROOT / P1_POLICY_RELATIVE) != P1_POLICY_SHA256:
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    router = json.loads(
        (
            ROOT
            / "evaluation/learned_intent_ranking/rq1c_final/"
            "rq1c1_router_selection_manifest_v1.json"
        ).read_text(encoding="utf-8")
    )
    if router.get("selected_router") != RQ1_ROUTER:
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    c1 = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2c1_r1_v1/"
            "rq2c1_r1_starting_preflight_v1.json"
        ).read_text(encoding="utf-8")
    )
    if (
        c1.get("gold_bundle_sha256") != GOLD_BUNDLE_SHA256
        or c1.get("p1_policy") != P1_POLICY_ID
        or c1.get("fixture", {}).get("sha256") != FIXTURE_SHA256
        or sha256_file(ROOT / FIXTURE_RELATIVE) != FIXTURE_SHA256
    ):
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    candidate_index = ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
    candidate_embeddings = (
        ROOT / "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"
    )
    expected_index = "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
    expected_embeddings = (
        "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
    )
    if (
        sha256_file(candidate_index) != expected_index
        or sha256_file(candidate_embeddings) != expected_embeddings
    ):
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    return {
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
        "fixture_record_count": 28,
        "p1_policy_id": P1_POLICY_ID,
        "p1_policy_sha256": P1_POLICY_SHA256,
        "rq1_router": RQ1_ROUTER,
        "c0_candidate_index_sha256": expected_index,
        "c0_candidate_embeddings_sha256": expected_embeddings,
        "c0_candidate_record_count": 62,
        "c0_label_count": 16,
    }


def verify_starting_state(*, require_pristine: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", STARTING_HEAD + "^")
    if parent != STARTING_PARENT:
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    if branch == STARTING_BRANCH:
        valid_checkout = head == STARTING_HEAD
    elif branch == RESULT_BRANCH:
        relative_count = int(_git("rev-list", "--count", f"{STARTING_HEAD}..{head}"))
        valid_checkout = relative_count in {0, 1} and (
            relative_count == 0 or _git("rev-parse", head + "^") == STARTING_HEAD
        )
    else:
        valid_checkout = False
    if not valid_checkout:
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    if require_pristine and _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    zip_identities = (
        (C1_R1_REVIEW_ZIP, C1_R1_REVIEW_ZIP_SHA256),
        (C1_REVIEW_ZIP, C1_REVIEW_ZIP_SHA256),
        (R5_REVIEW_ZIP, R5_REVIEW_ZIP_SHA256),
    )
    for path, expected in zip_identities:
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise StartingStateError("BLOCKED_RQ2_D0_STARTING_STATE_MISMATCH")
    checksum_results = {
        relative.as_posix(): _verify_checksum_manifest(relative, count)
        for relative, count in EXPECTED_CHECKSUM_COUNTS.items()
    }
    return {
        "schema_version": "rq2d0-preflight-report-v1",
        "status": "PASS",
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "result_branch": RESULT_BRANCH,
        "current_branch": branch,
        "current_head": head,
        "remote_count": 0,
        "tag_count": 0,
        "review_zip_sha256": {
            "rq2c1_r1": C1_R1_REVIEW_ZIP_SHA256,
            "rq2c1": C1_REVIEW_ZIP_SHA256,
            "rq2c0_r5": R5_REVIEW_ZIP_SHA256,
        },
        "output_checksums": checksum_results,
        "frozen_identities": _frozen_result_identities(),
        "track_a_raw_access_count": 0,
        "track_b_raw_access_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def assert_d0_partition_allowed(value: str | Path) -> None:
    text = str(value).replace("\\", "/").casefold()
    if "track_a" in text or "track_b" in text or "primary_v3_hybrid_context" in text:
        raise PermissionError("D0 raw Track A/Track B access is prohibited")
