"""Read-only R2/R3/R4, fixture, policy, Gold, and protected-source gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from . import (
    EXPECTED_EFFECTIVE_ADMISSION,
    EXPECTED_EFFECTIVE_RETRIEVAL,
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_OUTPUT_CHECKSUMS,
    EXPECTED_P1_POLICY,
    EXPECTED_PAYLOAD_SCOPE,
    EXPECTED_PRIMARY_POLICY_ID,
    EXPECTED_PROTECTED_FILE_COUNT,
    EXPECTED_PROTECTED_MANIFEST_SHA256,
    EXPECTED_R4_PAYLOAD_BINDING,
    EXPECTED_R4_REVIEW_ZIP_SHA256,
    EXPECTED_TRACKED_HISTORY,
    FIXTURE_BANK_PATH,
    R2_OUTPUT_CHECKSUM_RELATIVE,
    R3_OUTPUT_CHECKSUM_RELATIVE,
    R4_OUTPUT_CHECKSUM_RELATIVE,
    R4_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)


class R4IdentityError(RuntimeError):
    """Fail-closed R4 authority or history failure."""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def parse_checksum_manifest(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED") from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
        values[relative] = digest
    return values


def _verify_output_checksums(stage: str, relative: Path) -> dict[str, Any]:
    expected_count, expected_manifest_sha = EXPECTED_OUTPUT_CHECKSUMS[stage]
    manifest = ROOT / relative
    if sha256_file(manifest) != expected_manifest_sha:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    values = parse_checksum_manifest(manifest)
    failures = [
        item
        for item, digest in values.items()
        if not (ROOT / item).is_file()
        or (ROOT / item).is_symlink()
        or sha256_file(ROOT / item) != digest
    ]
    if len(values) != expected_count or failures:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    return {
        "status": "PASS",
        "checksum_count": len(values),
        "failure_count": 0,
        "manifest_sha256": expected_manifest_sha,
    }


def verify_r2_output_checksums() -> dict[str, Any]:
    return _verify_output_checksums("R2", R2_OUTPUT_CHECKSUM_RELATIVE)


def verify_r3_output_checksums() -> dict[str, Any]:
    return _verify_output_checksums("R3", R3_OUTPUT_CHECKSUM_RELATIVE)


def verify_r4_output_checksums() -> dict[str, Any]:
    return _verify_output_checksums("R4", R4_OUTPUT_CHECKSUM_RELATIVE)


def _aggregate_file_manifest(relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _tracked_history(stage: str) -> dict[str, Any]:
    expected_count, expected_manifest_sha = EXPECTED_TRACKED_HISTORY[stage]
    relative = f"evaluation/capability_routing_rq2c0_{stage.lower()}_v1"
    paths = [
        item.decode("utf-8")
        for item in subprocess.check_output(
            ["git", "ls-files", "-z", relative], cwd=ROOT
        ).split(b"\0")
        if item
    ]
    observed = _aggregate_file_manifest(paths)
    if len(paths) != expected_count or observed != expected_manifest_sha:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    return {
        "status": "PASS",
        "tracked_file_count": len(paths),
        "tracked_manifest_sha256": observed,
    }


def verify_r2_tracked_history() -> dict[str, Any]:
    return _tracked_history("R2")


def verify_r3_tracked_history() -> dict[str, Any]:
    return _tracked_history("R3")


def verify_r4_tracked_history() -> dict[str, Any]:
    return _tracked_history("R4")


def _protected_path(relative: str) -> bool:
    prefixes = (
        "pages/",
        "utils/",
        "tests/",
        "semantic_runtime/",
        "evaluation/learned_intent_ranking/",
        "evaluation/capability_routing_v1/",
        "evaluation/capability_routing_v1_r1/",
        "evaluation/capability_routing_v1_r1b/",
        "evaluation/capability_routing_v1_r1c/",
        "evaluation/capability_routing_v1_r2a/",
        "evaluation/capability_routing_v1_r2b/",
        "evaluation/capability_routing_rq2b_v1/",
        "evaluation/capability_routing_rq2c0_v1/",
        "evaluation/capability_routing_rq2c0_r1_v1/",
        "evaluation/capability_routing_rq2c0_r2_v1/",
        "evaluation/capability_routing_rq2c0_r3_v1/",
        "evaluation/capability_routing_rq2c0_r4_v1/",
        "docs/thesis_mainline/rq1/",
    )
    if relative == "Home.py" or relative.startswith(prefixes):
        return True
    base = "docs/thesis_mainline/rq2/"
    names = (
        "RQ2A_",
        "RQ2B_",
        "RQ2C0_R1_",
        "RQ2C0_R2_",
        "RQ2C0_R3_",
        "RQ2C0_R4_",
    )
    return relative.startswith(base) and relative[len(base) :].startswith(names)


def protected_manifest() -> dict[str, Any]:
    tracked = [
        item.decode("utf-8")
        for item in subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT
        ).split(b"\0")
        if item
    ]
    paths = [relative for relative in tracked if _protected_path(relative)]
    observed = _aggregate_file_manifest(paths)
    if (
        len(paths) != EXPECTED_PROTECTED_FILE_COUNT
        or observed != EXPECTED_PROTECTED_MANIFEST_SHA256
    ):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "protected_file_count": len(paths),
        "protected_manifest_sha256": observed,
    }


def verify_fixture_identity() -> dict[str, Any]:
    if not FIXTURE_BANK_PATH.is_file() or FIXTURE_BANK_PATH.is_symlink():
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    payload = FIXTURE_BANK_PATH.read_bytes()
    if (
        hashlib.sha256(payload).hexdigest() != EXPECTED_FIXTURE_BANK_SHA256
        or len(payload) != EXPECTED_FIXTURE_BANK_SIZE
        or len(payload.splitlines()) != EXPECTED_FIXTURE_RECORD_COUNT
    ):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "sha256": EXPECTED_FIXTURE_BANK_SHA256,
        "size_bytes": len(payload),
        "record_count": len(payload.splitlines()),
    }


def verify_starting_authority() -> dict[str, Any]:
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    if _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    if _git("merge-base", STARTING_HEAD, "HEAD") != STARTING_HEAD:
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) not in (0, 1):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    if (
        not R4_REVIEW_ZIP.is_file()
        or R4_REVIEW_ZIP.is_symlink()
        or sha256_file(R4_REVIEW_ZIP) != EXPECTED_R4_REVIEW_ZIP_SHA256
    ):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")

    effective = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2c0_r4_v1/"
            "effective_persistent_memory_contract_v1_3.json"
        ).read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2c0_r4_v1/"
            "rq2c0_r4_preflight_report_v1.json"
        ).read_text(encoding="utf-8")
    )
    authority = preflight["starting_authority"]
    if (
        authority["p1_policy"] != EXPECTED_P1_POLICY
        or authority["gold_bundle_sha256"] != EXPECTED_GOLD_BUNDLE_SHA256
        or preflight["effective_primary_policy_id"] != EXPECTED_PRIMARY_POLICY_ID
        or effective["effective_retrieval"] != EXPECTED_EFFECTIVE_RETRIEVAL
        or effective["effective_admission"] != EXPECTED_EFFECTIVE_ADMISSION
        or effective["effective_payload_scope"] != EXPECTED_PAYLOAD_SCOPE
        or effective["effective_payload_binding"] != EXPECTED_R4_PAYLOAD_BINDING
    ):
        raise R4IdentityError("BLOCKED_RQ2_C0_R5_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "starting_branch": "research/rq2-c0-r4-payload-integrity-repair",
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "result_branch": RESULT_BRANCH,
        "r4_review_zip_sha256": EXPECTED_R4_REVIEW_ZIP_SHA256,
        "r2_output_checksums": verify_r2_output_checksums(),
        "r3_output_checksums": verify_r3_output_checksums(),
        "r4_output_checksums": verify_r4_output_checksums(),
        "r2_tracked_history": verify_r2_tracked_history(),
        "r3_tracked_history": verify_r3_tracked_history(),
        "r4_tracked_history": verify_r4_tracked_history(),
        "fixture_bank": verify_fixture_identity(),
        "p1_policy": EXPECTED_P1_POLICY,
        "gold_bundle_sha256": EXPECTED_GOLD_BUNDLE_SHA256,
        "primary_policy_id": EXPECTED_PRIMARY_POLICY_ID,
        "effective_retrieval": EXPECTED_EFFECTIVE_RETRIEVAL,
        "effective_admission": EXPECTED_EFFECTIVE_ADMISSION,
        "payload_scope": EXPECTED_PAYLOAD_SCOPE,
        "r4_payload_binding": EXPECTED_R4_PAYLOAD_BINDING,
        "protected_sources": protected_manifest(),
    }
