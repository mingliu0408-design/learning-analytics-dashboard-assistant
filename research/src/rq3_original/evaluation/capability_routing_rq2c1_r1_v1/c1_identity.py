"""Read-only identity gates and original-C1 preservation audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

from evaluation.capability_routing_rq2b_v1.gold_preflight import (
    load_and_validate_gold,
)

from . import (
    C1_CHECKSUM_RELATIVE,
    C1_REVIEW_ZIP,
    C1_REVIEW_ZIP_SHA256,
    EXPECTED_C1_CHECKSUM_COUNT,
    EXPECTED_FIXTURE_COUNT,
    EXPECTED_FIXTURE_SHA256,
    EXPECTED_FIXTURE_SIZE,
    EXPECTED_P1_POLICY_SHA256,
    EXPECTED_R5_CHECKSUM_COUNT,
    EXPECTED_R5_CHECKSUM_SHA256,
    FIXTURE_RELATIVE,
    GOLD_BUNDLE_SHA256,
    ORIGINAL_C1_DOCS,
    ORIGINAL_C1_TRACKED_FILE_COUNT,
    ORIGINAL_C1_TRACKED_MANIFEST_SHA256,
    P1_POLICY_ID,
    P1_POLICY_RELATIVE,
    R5_CHECKSUM_RELATIVE,
    R5_REVIEW_ZIP,
    R5_REVIEW_ZIP_SHA256,
    RESULT_BRANCH,
    ROOT,
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


def _parse_checksum_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH") from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
        values[relative] = digest
    return values


def verify_checksum_manifest(
    relative: Path, expected_count: int, expected_manifest_sha: str | None = None
) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    if expected_manifest_sha is not None and sha256_file(path) != expected_manifest_sha:
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    values = _parse_checksum_manifest(path)
    failed = [
        name
        for name, digest in values.items()
        if not (ROOT / name).is_file()
        or (ROOT / name).is_symlink()
        or sha256_file(ROOT / name) != digest
    ]
    if len(values) != expected_count or failed:
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "checksum_count": len(values),
        "failure_count": 0,
        "manifest_sha256": sha256_file(path),
    }


def _original_c1_paths() -> list[str]:
    raw = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "evaluation/capability_routing_rq2c1_v1",
            *ORIGINAL_C1_DOCS,
        ],
        cwd=ROOT,
    )
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def _aggregate(paths: Iterable[str]) -> tuple[int, str]:
    values = sorted(set(paths))
    digest = hashlib.sha256()
    for relative in values:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise StartingStateError("BLOCKED_RQ2_C1_R1_PROTECTED_SOURCE_MUTATED")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return len(values), digest.hexdigest()


def verify_original_c1_identity() -> dict[str, Any]:
    count, digest = _aggregate(_original_c1_paths())
    diff = subprocess.run(
        ["git", "diff", "--quiet", STARTING_HEAD, "--", "evaluation/capability_routing_rq2c1_v1", *ORIGINAL_C1_DOCS],
        cwd=ROOT,
        check=False,
    )
    if (
        count != ORIGINAL_C1_TRACKED_FILE_COUNT
        or digest != ORIGINAL_C1_TRACKED_MANIFEST_SHA256
        or diff.returncode != 0
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_R1_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "tracked_file_count": count,
        "tracked_manifest_sha256": digest,
        "byte_identical_to_original_head": True,
    }


def _validate_worktree_scope() -> None:
    # Preserve porcelain's leading index/worktree status column.  `_git()`
    # deliberately strips scalar outputs and is therefore unsuitable here.
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    invalid: list[str] = []
    for line in status:
        path = line[3:]
        if path.startswith("evaluation/capability_routing_rq2c1_r1_v1/"):
            continue
        if path.startswith("docs/thesis_mainline/rq2/RQ2C1_R1_"):
            continue
        if path == ".gitignore":
            continue
        invalid.append(path)
    if invalid:
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")


def verify_starting_preflight() -> dict[str, Any]:
    if (
        _git("branch", "--show-current") != RESULT_BRANCH
        or _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT
        or _git("remote")
        or _git("tag", "--list")
        or int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) not in {0, 1}
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    _validate_worktree_scope()
    if (
        sha256_file(C1_REVIEW_ZIP) != C1_REVIEW_ZIP_SHA256
        or sha256_file(R5_REVIEW_ZIP) != R5_REVIEW_ZIP_SHA256
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    c1_checks = verify_checksum_manifest(
        C1_CHECKSUM_RELATIVE, EXPECTED_C1_CHECKSUM_COUNT
    )
    r5_checks = verify_checksum_manifest(
        R5_CHECKSUM_RELATIVE,
        EXPECTED_R5_CHECKSUM_COUNT,
        EXPECTED_R5_CHECKSUM_SHA256,
    )
    fixture = ROOT / FIXTURE_RELATIVE
    rows = [line for line in fixture.read_text(encoding="utf-8").splitlines() if line]
    if (
        sha256_file(fixture) != EXPECTED_FIXTURE_SHA256
        or fixture.stat().st_size != EXPECTED_FIXTURE_SIZE
        or len(rows) != EXPECTED_FIXTURE_COUNT
    ):
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    p1_path = ROOT / P1_POLICY_RELATIVE
    p1 = json.loads(p1_path.read_text(encoding="utf-8"))
    observed_policy = (
        p1.get("selected_policy_id") or p1.get("final_policy_id") or p1.get("policy_id")
    )
    if sha256_file(p1_path) != EXPECTED_P1_POLICY_SHA256 or observed_policy != P1_POLICY_ID:
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    gold = load_and_validate_gold(ROOT)
    if gold.identity.get("gold_bundle_sha256") != GOLD_BUNDLE_SHA256:
        raise StartingStateError("BLOCKED_RQ2_C1_R1_STARTING_STATE_MISMATCH")
    original = verify_original_c1_identity()
    return {
        "schema_version": "rq2c1-r1-starting-preflight-v1",
        "status": "PASS",
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "result_branch": RESULT_BRANCH,
        "current_head": _git("rev-parse", "HEAD"),
        "relative_commit_count": int(
            _git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")
        ),
        "remote_count": 0,
        "tag_count": 0,
        "c1_review_zip_sha256": C1_REVIEW_ZIP_SHA256,
        "r5_review_zip_sha256": R5_REVIEW_ZIP_SHA256,
        "output_checksums": {"C1": c1_checks, "R5": r5_checks},
        "fixture": {
            "sha256": EXPECTED_FIXTURE_SHA256,
            "size_bytes": EXPECTED_FIXTURE_SIZE,
            "record_count": EXPECTED_FIXTURE_COUNT,
        },
        "p1_policy": P1_POLICY_ID,
        "p1_policy_sha256": EXPECTED_P1_POLICY_SHA256,
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "gold_counts": {
            "synthetic": len(gold.synthetic_gold),
            "authentic": len(gold.authentic_gold),
            "context_missing": len(gold.authentic_context_missing_registry),
        },
        "original_c1": original,
        "track_a_access_count": 0,
        "track_b_access_count": 0,
    }


def assert_partition_access_allowed(partition: str) -> None:
    if partition in {"TRACK_A", "TRACK_B"}:
        raise PermissionError(f"{partition}_SEALED")
