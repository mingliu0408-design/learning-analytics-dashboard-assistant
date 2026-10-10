"""Read-only identity gates for RQ2-C1 inputs, history, and local runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

from . import (
    C0_EMBEDDINGS_RELATIVE,
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_RELATIVE,
    C0_INDEX_SHA256,
    EXPECTED_CHECKSUM_MANIFESTS,
    EXPECTED_FIXTURE_COUNT,
    EXPECTED_FIXTURE_SHA256,
    EXPECTED_FIXTURE_SIZE,
    GOLD_BUNDLE_SHA256,
    EXPECTED_HISTORY,
    EXPECTED_P1_POLICY_SHA256,
    EXPECTED_PROTECTED_COUNT,
    EXPECTED_PROTECTED_SHA256,
    EXPECTED_R5_REVIEW_ZIP_SHA256,
    FIXTURE_RELATIVE,
    GOLD_INPUTS,
    LOCAL_LEDGER_INPUTS,
    MODEL_RELATIVE,
    MODEL_REPO_ID,
    MODEL_REVISION,
    P1_POLICY_ID,
    P1_POLICY_RELATIVE,
    PRIMARY_PERSISTENT_POLICY,
    R5_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    RQ2C1Error,
    STARTING_BRANCH,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_bytes,
    sha256_file,
)


class StartingStateError(RQ2C1Error):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _parse_manifest(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH") from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
        values[relative] = digest
    return values


def verify_output_checksums(stage: str) -> dict[str, Any]:
    relative, expected_count, manifest_sha = EXPECTED_CHECKSUM_MANIFESTS[stage]
    path = ROOT / relative
    if sha256_file(path) != manifest_sha:
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    values = _parse_manifest(path)
    failed = [
        relative_path
        for relative_path, digest in values.items()
        if not (ROOT / relative_path).is_file()
        or (ROOT / relative_path).is_symlink()
        or sha256_file(ROOT / relative_path) != digest
    ]
    if len(values) != expected_count or failed:
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "checksum_count": len(values),
        "failure_count": 0,
        "manifest_sha256": manifest_sha,
    }


def _aggregate(paths: Iterable[str]) -> tuple[int, str]:
    ordered = sorted(set(paths))
    digest = hashlib.sha256()
    for relative in ordered:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise StartingStateError("BLOCKED_RQ2_C1_PROTECTED_SOURCE_MUTATED")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return len(ordered), digest.hexdigest()


def _git_files(*pathspecs: str) -> list[str]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *pathspecs], cwd=ROOT
    )
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


HISTORY_PATHS = {
    "RQ2B": "evaluation/capability_routing_rq2b_v1",
    "R2": "evaluation/capability_routing_rq2c0_r2_v1",
    "R3": "evaluation/capability_routing_rq2c0_r3_v1",
    "R4": "evaluation/capability_routing_rq2c0_r4_v1",
    "R5": "evaluation/capability_routing_rq2c0_r5_v1",
}


def verify_historical_sources() -> dict[str, Any]:
    report: dict[str, Any] = {}
    for stage, relative in HISTORY_PATHS.items():
        count, manifest_sha = _aggregate(_git_files(relative))
        expected_count, expected_sha = EXPECTED_HISTORY[stage]
        if count != expected_count or manifest_sha != expected_sha:
            raise StartingStateError("BLOCKED_RQ2_C1_PROTECTED_SOURCE_MUTATED")
        report[stage] = {
            "tracked_file_count": count,
            "tracked_manifest_sha256": manifest_sha,
            "status": "PASS",
        }
    return report


PROTECTED_PATHS = (
    "Home.py",
    "pages",
    "utils",
    "tests",
    "semantic_runtime",
    "evaluation/learned_intent_ranking",
    "evaluation/capability_routing_v1",
    "evaluation/capability_routing_v1_r1",
    "evaluation/capability_routing_v1_r1b",
    "evaluation/capability_routing_v1_r1c",
    "evaluation/capability_routing_v1_r2a",
    "evaluation/capability_routing_v1_r2b",
    "evaluation/capability_routing_rq2b_v1",
    "evaluation/capability_routing_rq2c0_v1",
    "evaluation/capability_routing_rq2c0_r1_v1",
    "evaluation/capability_routing_rq2c0_r2_v1",
    "evaluation/capability_routing_rq2c0_r3_v1",
    "evaluation/capability_routing_rq2c0_r4_v1",
    "evaluation/capability_routing_rq2c0_r5_v1",
    "docs/thesis_mainline/rq1",
    ":(glob)docs/thesis_mainline/rq2/RQ2A_*",
    ":(glob)docs/thesis_mainline/rq2/RQ2B_*",
    ":(glob)docs/thesis_mainline/rq2/RQ2C0_*",
)


def protected_manifest() -> dict[str, Any]:
    count, manifest_sha = _aggregate(_git_files(*PROTECTED_PATHS))
    if count != EXPECTED_PROTECTED_COUNT or manifest_sha != EXPECTED_PROTECTED_SHA256:
        raise StartingStateError("BLOCKED_RQ2_C1_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "protected_file_count": count,
        "protected_manifest_sha256": manifest_sha,
    }


def _verified_local(path: Path, expected_sha: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise StartingStateError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    value = path.read_bytes()
    if sha256_bytes(value) != expected_sha:
        raise StartingStateError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    return value


def verify_local_inputs() -> dict[str, Any]:
    gold: dict[str, Any] = {}
    for name, (relative, expected_sha, expected_count) in GOLD_INPUTS.items():
        value = _verified_local(ROOT / relative, expected_sha)
        count = len(value.splitlines())
        if count != expected_count:
            raise StartingStateError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
        gold[name] = {
            "sha256": expected_sha,
            "record_count": count,
            "status": "PASS",
        }
    ledgers: dict[str, Any] = {}
    for name, (relative, expected_sha) in LOCAL_LEDGER_INPUTS.items():
        value = _verified_local(ROOT / relative, expected_sha)
        ledgers[name] = {
            "sha256": expected_sha,
            "size_bytes": len(value),
            "status": "PASS",
        }
    fixture = _verified_local(ROOT / FIXTURE_RELATIVE, EXPECTED_FIXTURE_SHA256)
    if len(fixture) != EXPECTED_FIXTURE_SIZE or len(fixture.splitlines()) != EXPECTED_FIXTURE_COUNT:
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "gold": gold,
        "local_ledgers": ledgers,
        "fixture": {
            "sha256": EXPECTED_FIXTURE_SHA256,
            "size_bytes": len(fixture),
            "record_count": len(fixture.splitlines()),
        },
    }


def verify_c0_and_policy_identity() -> dict[str, Any]:
    if sha256_file(ROOT / P1_POLICY_RELATIVE) != EXPECTED_P1_POLICY_SHA256:
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    policy = json.loads((ROOT / P1_POLICY_RELATIVE).read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (ROOT / C0_INDEX_RELATIVE).read_text(encoding="utf-8").splitlines()
    ]
    labels = {str(row["final_semantic_label"]) for row in rows}
    config = json.loads(
        (ROOT / "semantic_runtime/config/semantic_routing_config.json").read_text(
            encoding="utf-8"
        )
    )
    model = config.get("model") or {}
    if (
        policy.get("selected_policy_id") != P1_POLICY_ID
        or sha256_file(ROOT / C0_INDEX_RELATIVE) != C0_INDEX_SHA256
        or sha256_file(ROOT / C0_EMBEDDINGS_RELATIVE) != C0_EMBEDDINGS_SHA256
        or len(rows) != 62
        or len(labels) != 16
        or model.get("repo_id") != MODEL_REPO_ID
        or model.get("revision") != MODEL_REVISION
        or model.get("local_files_only") is not True
        or model.get("device") != "cpu"
        or not (ROOT / MODEL_RELATIVE).is_dir()
        or (ROOT / MODEL_RELATIVE).is_symlink()
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "rq1_router": "C0_COSINE",
        "p1_policy_id": P1_POLICY_ID,
        "p1_policy_sha256": EXPECTED_P1_POLICY_SHA256,
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "candidate_index_sha256": C0_INDEX_SHA256,
        "candidate_record_count": len(rows),
        "candidate_label_count": len(labels),
        "candidate_embeddings_sha256": C0_EMBEDDINGS_SHA256,
        "model_repo_id": MODEL_REPO_ID,
        "model_revision": MODEL_REVISION,
        "model_device": "cpu",
        "model_local_files_only": True,
        "primary_persistent_policy": PRIMARY_PERSISTENT_POLICY,
        "effective_retrieval": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "effective_payload_binding": "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3",
        "effective_validated_bundle": "PERSISTENT_MEMORY_VALIDATED_BUNDLE_V1_4",
        "effective_retrieval_plan": "VALIDATED_RETRIEVAL_PLAN_V1_2",
    }


def verify_starting_state() -> dict[str, Any]:
    if (
        _git("branch", "--show-current") != RESULT_BRANCH
        or _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT
        or _git("merge-base", STARTING_HEAD, "HEAD") != STARTING_HEAD
        or int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) not in (0, 1)
        or _git("remote")
        or _git("tag", "--list")
        or not R5_REVIEW_ZIP.is_file()
        or R5_REVIEW_ZIP.is_symlink()
        or sha256_file(R5_REVIEW_ZIP) != EXPECTED_R5_REVIEW_ZIP_SHA256
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_STARTING_STATE_MISMATCH")
    checksums = {
        stage: verify_output_checksums(stage)
        for stage in ("RQ2B", "R2", "R3", "R4", "R5")
    }
    return {
        "status": "PASS",
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "result_branch": RESULT_BRANCH,
        "r5_review_zip_sha256": EXPECTED_R5_REVIEW_ZIP_SHA256,
        "output_checksums": checksums,
        "local_inputs": verify_local_inputs(),
        "frozen_runtime": verify_c0_and_policy_identity(),
        "historical_sources": verify_historical_sources(),
        "protected_sources": protected_manifest(),
        "remote_count": 0,
        "tag_count": 0,
    }


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")
