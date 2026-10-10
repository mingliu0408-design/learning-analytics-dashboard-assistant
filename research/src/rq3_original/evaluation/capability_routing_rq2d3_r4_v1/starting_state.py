"""Read-only RQ2-D3-R4 starting-state and frozen-identity gates."""

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
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_SHA256,
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    D3_R3_CHECKSUM_MANIFEST_SHA256,
    METRIC_IMPLEMENTATION_SHA256,
    P1_POLICY_SHA256,
    ROOT,
    START_BRANCH,
    START_HEAD,
    START_PARENT,
    TARGET_BRANCH,
    sha256_file,
)


START_BLOCKER = "BLOCKED_RQ2_D3_R4_STARTING_STATE_MISMATCH"
R3_ZIP = "RQ2_D3_R3_D4_EXECUTION_INTEGRITY_REPAIR_REVIEW_2026-08-29.zip"
R2_ZIP = "RQ2_D3_R2_TRACK_B_FINAL_EVALUATION_HARNESS_REVIEW_2026-08-29.zip"


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_identity(
    name: str, expected_sha: str, expected_size: int, expected_members: int
) -> None:
    path = Path.home() / "Downloads" / name
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_size != expected_size
        or sha256_file(path) != expected_sha
    ):
        raise RuntimeError(START_BLOCKER)
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != expected_members or archive.testzip() is not None:
            raise RuntimeError(START_BLOCKER)


def _manifest_at_commit(commit: str, relative: str, expected_count: int) -> int:
    manifest_process = _git("show", f"{commit}:{relative}")
    if manifest_process.returncode:
        raise RuntimeError(START_BLOCKER)
    lines = [line for line in manifest_process.stdout.decode().splitlines() if line]
    if len(lines) != expected_count:
        raise RuntimeError(START_BLOCKER)
    passed = 0
    for line in lines:
        expected, target = line.split("  ", 1)
        process = _git("show", f"{commit}:{target}")
        if process.returncode or _sha(process.stdout) != expected:
            raise RuntimeError(START_BLOCKER)
        passed += 1
    return passed


def _grouping_shape() -> tuple[int, int, set[int]]:
    path = ROOT / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    groups: dict[str, int] = {}
    for row in rows:
        key = str(row["contrast_group_id"])
        groups[key] = groups.get(key, 0) + 1
    return len(rows), len(groups), set(groups.values())


def validate_starting_state_v1() -> dict[str, Any]:
    branch = _git("branch", "--show-current").stdout.decode().strip()
    head = _git("rev-parse", "HEAD").stdout.decode().strip()
    parent = _git("rev-parse", "HEAD^").stdout.decode().strip()
    branch_ok = (branch == START_BRANCH and head == START_HEAD and parent == START_PARENT) or (
        branch == TARGET_BRANCH and (head == START_HEAD or parent == START_HEAD)
    )
    if not branch_ok or _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise RuntimeError(START_BLOCKER)
    _zip_identity(
        R3_ZIP,
        "93bf350393e938d91cf13cdc82e28c9bf41f954927ebbd39831a0e64201ed6b9",
        99900,
        58,
    )
    _zip_identity(
        R2_ZIP,
        "19585f4fae23cefdf1d66b9fabce8d0f77efaa5e412cac33a21b2a913a4423fe",
        71860,
        46,
    )
    r3_manifest = ROOT / "evaluation/capability_routing_rq2d3_r3_v1/rq2d3_r3_output_checksums_v1.sha256"
    if sha256_file(r3_manifest) != D3_R3_CHECKSUM_MANIFEST_SHA256:
        raise RuntimeError(START_BLOCKER)
    r3_pass = _manifest_at_commit(
        START_HEAD,
        "evaluation/capability_routing_rq2d3_r3_v1/rq2d3_r3_output_checksums_v1.sha256",
        53,
    )
    r2_pass = _manifest_at_commit(
        START_PARENT,
        "evaluation/capability_routing_rq2d3_r2_v1/rq2d3_r2_output_checksums_v1.sha256",
        41,
    )
    identities = {
        "d3_r1_statistical_contract": (
            "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json",
            D3_R1_STATISTICAL_SHA256,
        ),
        "d3_r2_grouping": (
            "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl",
            D3_R2_GROUPING_SHA256,
        ),
        "metric": (
            "evaluation/capability_routing_rq2b_v1/capability_metrics.py",
            METRIC_IMPLEMENTATION_SHA256,
        ),
        "c0_index": (
            "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
            C0_INDEX_SHA256,
        ),
        "c0_embeddings": (
            "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz",
            C0_EMBEDDINGS_SHA256,
        ),
        "p1_policy": (
            "evaluation/capability_routing_rq2b_v1/rq2b_final_p1_policy_v1.json",
            P1_POLICY_SHA256,
        ),
    }
    for relative, expected in identities.values():
        if sha256_file(ROOT / relative) != expected:
            raise RuntimeError(START_BLOCKER)
    grouping = ROOT / identities["d3_r2_grouping"][0]
    rows, groups, sizes = _grouping_shape()
    if grouping.stat().st_size != 4176 or (rows, groups, sizes) != (48, 24, {2}):
        raise RuntimeError(START_BLOCKER)
    manifest = json.loads(
        (ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json").read_text()
    )
    if (
        manifest.get("gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256
        or manifest.get("full_text_gold", {}).get("sha256")
        != "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
        or manifest.get("label_only_gold", {}).get("sha256")
        != "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
    ):
        raise RuntimeError(START_BLOCKER)
    # The two governed files are lstat-only in R4 preflight; their bytes are never opened.
    governed_metadata = []
    for member in (manifest["full_text_gold"], manifest["label_only_gold"]):
        target = ROOT / member["relative_path"]
        observed = os.lstat(target)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_size != member["size_bytes"]
        ):
            raise RuntimeError(START_BLOCKER)
        governed_metadata.append(
            {
                "role": "COMBINED" if member.get("local_only") else "LABEL_ONLY",
                "size_bytes": observed.st_size,
                "content_read_count": 0,
                "lstat_count": 1,
            }
        )
    return {
        "schema_version": "rq2d3-r4-starting-state-v1",
        "status": "PASS",
        "starting_branch": START_BRANCH,
        "starting_head": START_HEAD,
        "starting_parent": START_PARENT,
        "target_branch": TARGET_BRANCH,
        "r3_review_zip": "58 members / SHA and size PASS",
        "r3_output_checksums_at_frozen_head": f"{r3_pass}/53 PASS",
        "r2_review_zip": "46 members / SHA and size PASS",
        "r2_output_checksums_at_frozen_head": f"{r2_pass}/41 PASS",
        "grouping": "48 records / 24 groups / size 2 / SHA PASS",
        "governed_input_preflight": governed_metadata,
        "remote_count": 0,
        "tag_count": 0,
    }
