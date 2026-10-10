"""Read-only R2, fixture, P1, Gold, and protected-source identity gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from . import (
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_PRIMARY_POLICY_ID,
    EXPECTED_PROTECTED_FILE_COUNT,
    EXPECTED_PROTECTED_MANIFEST_SHA256,
    EXPECTED_R2_OUTPUT_CHECKSUM_COUNT,
    EXPECTED_R2_OUTPUT_CHECKSUM_SHA256,
    EXPECTED_R2_REVIEW_ZIP_SHA256,
    EXPECTED_R2_TRACKED_FILE_COUNT,
    EXPECTED_R2_TRACKED_MANIFEST_SHA256,
    FIXTURE_BANK_PATH,
    R2_OUTPUT_CHECKSUM_RELATIVE,
    R2_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)


class R2IdentityError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def parse_checksum_manifest(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_IDENTITY")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_IDENTITY") from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_IDENTITY")
        values[relative] = digest
    return values


def verify_r2_output_checksums() -> dict[str, Any]:
    manifest = ROOT / R2_OUTPUT_CHECKSUM_RELATIVE
    if sha256_file(manifest) != EXPECTED_R2_OUTPUT_CHECKSUM_SHA256:
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_HISTORY_MUTATED")
    values = parse_checksum_manifest(manifest)
    failures = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if len(values) != EXPECTED_R2_OUTPUT_CHECKSUM_COUNT or failures:
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_HISTORY_MUTATED")
    return {
        "status": "PASS",
        "checksum_count": len(values),
        "failure_count": 0,
        "manifest_sha256": sha256_file(manifest),
    }


def _aggregate_file_manifest(relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_HISTORY_MUTATED")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_r2_tracked_history() -> dict[str, Any]:
    paths = _git(
        "ls-tree",
        "-r",
        "--name-only",
        STARTING_HEAD,
        "evaluation/capability_routing_rq2c0_r2_v1",
    ).splitlines()
    observed = _aggregate_file_manifest(paths)
    if (
        len(paths) != EXPECTED_R2_TRACKED_FILE_COUNT
        or observed != EXPECTED_R2_TRACKED_MANIFEST_SHA256
    ):
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_R2_HISTORY_MUTATED")
    return {
        "status": "PASS",
        "tracked_file_count": len(paths),
        "tracked_manifest_sha256": observed,
    }


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
        "docs/thesis_mainline/rq1/",
    )
    if relative == "Home.py" or relative.startswith(prefixes):
        return True
    if relative.startswith(
        ("docs/thesis_mainline/rq2/RQ2A_", "docs/thesis_mainline/rq2/RQ2B_")
    ):
        return True
    return relative.startswith("docs/thesis_mainline/rq2/RQ2C0_") and not relative.startswith(
        "docs/thesis_mainline/rq2/RQ2C0_R3_"
    )


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
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "protected_file_count": len(paths),
        "protected_manifest_sha256": observed,
    }


def verify_fixture_identity() -> dict[str, Any]:
    if not FIXTURE_BANK_PATH.is_file() or FIXTURE_BANK_PATH.is_symlink():
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    payload = FIXTURE_BANK_PATH.read_bytes()
    records = payload.splitlines()
    if (
        hashlib.sha256(payload).hexdigest() != EXPECTED_FIXTURE_BANK_SHA256
        or len(payload) != EXPECTED_FIXTURE_BANK_SIZE
        or len(records) != EXPECTED_FIXTURE_RECORD_COUNT
    ):
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "sha256": EXPECTED_FIXTURE_BANK_SHA256,
        "size_bytes": len(payload),
        "record_count": len(records),
    }


def verify_starting_authority() -> dict[str, Any]:
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_GIT_FAILURE")
    if _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT:
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode != 0:
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    if (
        not R2_REVIEW_ZIP.is_file()
        or R2_REVIEW_ZIP.is_symlink()
        or sha256_file(R2_REVIEW_ZIP) != EXPECTED_R2_REVIEW_ZIP_SHA256
    ):
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")

    preflight = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2c0_r2_v1/"
            "rq2c0_r2_preflight_report_v1.json"
        ).read_text(encoding="utf-8")
    )
    retrieval = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2c0_r2_v1/"
            "executable_persistent_retrieval_contract_v1.json"
        ).read_text(encoding="utf-8")
    )
    authority = preflight["starting_authority"]
    if (
        authority["p1_policy"] != EXPECTED_P1_POLICY
        or authority["p1_policy_immutable"] is not True
        or authority["gold_bundle_sha256"] != EXPECTED_GOLD_BUNDLE_SHA256
        or retrieval["primary_policy_id"] != EXPECTED_PRIMARY_POLICY_ID
    ):
        raise R2IdentityError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")

    return {
        "status": "PASS",
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "r2_review_zip_sha256": EXPECTED_R2_REVIEW_ZIP_SHA256,
        "r2_output_checksums": verify_r2_output_checksums(),
        "r2_tracked_history": verify_r2_tracked_history(),
        "fixture_bank": verify_fixture_identity(),
        "p1_policy": EXPECTED_P1_POLICY,
        "p1_immutable": True,
        "gold_bundle_sha256": EXPECTED_GOLD_BUNDLE_SHA256,
        "primary_policy_id": EXPECTED_PRIMARY_POLICY_ID,
        "protected_sources": protected_manifest(),
    }
