"""Fail-closed single-use access state machine reserved for RQ1-C1."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Mapping

from . import (
    AUTHORITY_CONTRACT_RELATIVE,
    FINAL_RESULT_RELATIVE,
    FINAL_RESULT_TEMP_FILE_NAME,
    LOCAL_ARTIFACTS_RELATIVE,
    LOCK_FILE_NAME,
    ROOT,
    TRACK_A_RELATIVE_PATH,
)
from .authority_contract import canonical_json_bytes, validate_authority_contract
from .contamination_audit import (
    audit_contamination,
    require_contamination_clear,
)
from .final_input_schema import parse_final_csv_bytes
from .final_model_runner import FinalRuntimeBundle, prepare_final_runtime_bundle


class SealedAccessError(RuntimeError):
    """Raised without deleting or resetting an already-created lock."""


@dataclass(frozen=True)
class FinalResultTarget:
    path: Path
    temporary_path: Path
    relative_path: str


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def validate_execution_authority(
    *,
    execute_final: bool,
    expected_harness_head: str,
    authority_contract_argument: str,
    environment: Mapping[str, str],
    root: Path = ROOT,
) -> Path:
    """Validate the three explicit gates before reading even safe contract bytes."""

    if execute_final is not True:
        raise SealedAccessError("--execute-final is required")
    if environment.get("RQ1C_FINAL_ACCESS_AUTHORISED") != "YES":
        raise SealedAccessError("RQ1C final-access environment authority is absent")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_harness_head):
        raise SealedAccessError("expected harness HEAD must be a full Git object ID")
    expected_relative = AUTHORITY_CONTRACT_RELATIVE.as_posix()
    supplied = str(authority_contract_argument).replace("\\", "/")
    expected_absolute = root.joinpath(*AUTHORITY_CONTRACT_RELATIVE.parts).as_posix()
    if supplied not in {expected_relative, expected_absolute}:
        raise SealedAccessError("authority-contract path is not the tracked frozen contract")
    return root.joinpath(*AUTHORITY_CONTRACT_RELATIVE.parts)


def verify_harness_state(root: Path, expected_harness_head: str) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD")
    tracked = _git(root, "diff", "--quiet")
    staged = _git(root, "diff", "--cached", "--quiet")
    remote = _git(root, "remote")
    tags = _git(root, "tag", "--list")
    if head.returncode or tracked.returncode or staged.returncode or remote.returncode or tags.returncode:
        raise SealedAccessError("approved harness Git state is not clean")
    actual_head = head.stdout.decode("ascii").strip()
    if actual_head != expected_harness_head:
        raise SealedAccessError("current HEAD is not the approved harness HEAD")
    if remote.stdout.splitlines() or tags.stdout.splitlines():
        raise SealedAccessError("remote or tag appeared after harness approval")
    return {
        "approved_harness_head": expected_harness_head,
        "current_head": actual_head,
        "tracked_worktree_clean": True,
        "index_clean": True,
        "remote_count": 0,
        "tag_count": 0,
    }


def _write_lock_state(lock_path: Path, payload: Mapping[str, Any]) -> None:
    temporary = lock_path.with_name(lock_path.name + ".update")
    with temporary.open("wb") as handle:
        handle.write(canonical_json_bytes(dict(payload)))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, lock_path)


def preflight_final_result_path(root: Path = ROOT) -> FinalResultTarget:
    """Prove the ignored result destination is safe before a lock can exist."""

    relative = FINAL_RESULT_RELATIVE.as_posix()
    ignored = _git(root, "check-ignore", "-q", relative)
    if ignored.returncode != 0:
        raise SealedAccessError("final result path is not covered by Git ignore policy")
    path = root.joinpath(*FINAL_RESULT_RELATIVE.parts)
    parent = path.parent
    temporary = parent / FINAL_RESULT_TEMP_FILE_NAME
    if path.exists() or path.is_symlink():
        raise SealedAccessError("BLOCKED_RQ1_C0_R2_RESULT_PATH_ALREADY_EXISTS")
    if temporary.exists() or temporary.is_symlink():
        raise SealedAccessError("final result temporary path already exists")
    if parent.is_symlink():
        raise SealedAccessError("final result parent must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink():
        raise SealedAccessError("final result parent is unavailable")

    probe = parent / ".rq1c-r2-atomic-write-preflight"
    if probe.exists() or probe.is_symlink():
        raise SealedAccessError("atomic-write preflight path already exists")
    descriptor = -1
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(b"rq1c-r2-atomic-write-preflight\n")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink()
    except BaseException as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise SealedAccessError("final result atomic-write preflight failed") from exc
    return FinalResultTarget(
        path=path,
        temporary_path=temporary,
        relative_path=relative,
    )


def persist_result_atomically(
    result: Mapping[str, Any],
    target: FinalResultTarget,
) -> dict[str, Any]:
    """Durably persist canonical bytes to an absent target and verify them."""

    payload = canonical_json_bytes(dict(result))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target.temporary_path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if target.path.exists() or target.path.is_symlink():
        raise SealedAccessError("final result target appeared after preflight")
    os.replace(target.temporary_path, target.path)
    persisted = target.path.read_bytes()
    if persisted != payload:
        raise SealedAccessError("persisted final result bytes differ")
    digest = hashlib.sha256(persisted).hexdigest()
    if digest != hashlib.sha256(payload).hexdigest() or len(persisted) != len(payload):
        raise SealedAccessError("persisted final result identity mismatch")
    directory_descriptor = os.open(target.path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return {
        "result_relative_path": target.relative_path,
        "result_sha256": digest,
        "result_size_bytes": len(persisted),
        "persisted": True,
    }


def _create_armed_lock(lock_path: Path, expected_head: str) -> dict[str, Any]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "rq1c-final-gold-access-lock-v1",
        "state": "ARMED",
        "expected_harness_head": expected_head,
        "raw_asset_open_count": 0,
        "persisted": False,
        "retry_permitted": False,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise SealedAccessError("final-gold access has already been consumed") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_json_bytes(payload))
        handle.flush()
        os.fsync(handle.fileno())
    return payload


def consume_one_shot_asset(
    *,
    asset_path: Path,
    lock_path: Path,
    expected_sha256: str,
    expected_size: int,
    expected_head: str,
    parser: Callable[[bytes], Any],
    evaluator: Callable[[Any], Mapping[str, Any]],
    result_persister: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    opener: Callable[..., BinaryIO] = open,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """Open one path once, read once, and preserve the lock on every outcome."""

    lock = _create_armed_lock(lock_path, expected_head)
    try:
        with opener(os.fspath(asset_path), "rb") as handle:
            raw_bytes = handle.read()
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        lock = {
            **lock,
            "state": "OPENED",
            "raw_asset_open_count": 1,
            "raw_asset_size_bytes": len(raw_bytes),
            "raw_asset_sha256": actual_sha256,
        }
        _write_lock_state(lock_path, lock)
        if len(raw_bytes) != expected_size or actual_sha256 != expected_sha256:
            raise SealedAccessError("opened final asset identity mismatch")
        parsed = parser(raw_bytes)
        result = evaluator(parsed)
        try:
            persisted = dict(result_persister(result))
            required = {
                "result_relative_path",
                "result_sha256",
                "result_size_bytes",
                "persisted",
            }
            if (
                not required <= set(persisted)
                or persisted["persisted"] is not True
                or not re.fullmatch(r"[0-9a-f]{64}", str(persisted["result_sha256"]))
                or int(persisted["result_size_bytes"]) <= 0
            ):
                raise SealedAccessError("result persister metadata contract mismatch")
        except BaseException:
            failed = {
                **lock,
                "state": "FAILED_RESULT_PERSISTENCE",
                "persisted": False,
                "retry_permitted": False,
            }
            _write_lock_state(lock_path, failed)
            raise
        lock = {
            **lock,
            **persisted,
            "state": "RESULT_PERSISTED",
            "retry_permitted": False,
        }
        _write_lock_state(lock_path, lock)
        lock = {
            **lock,
            "state": "COMPLETED",
            "persisted": True,
            "retry_permitted": False,
        }
        _write_lock_state(lock_path, lock)
        return lock, result
    except BaseException:
        # The ARMED or OPENED lock is intentionally retained.  No cleanup or
        # retry path exists here.
        raise


def run_authorised_one_shot(
    *,
    execute_final: bool,
    expected_harness_head: str,
    authority_contract_argument: str,
    environment: Mapping[str, str],
    evaluator: Callable[
        [list[Mapping[str, Any]], FinalRuntimeBundle], Mapping[str, Any]
    ],
    root: Path = ROOT,
    runtime_preparer: Callable[[Path, str], FinalRuntimeBundle] = (
        prepare_final_runtime_bundle
    ),
    result_preflighter: Callable[[Path], FinalResultTarget] = (
        preflight_final_result_path
    ),
    opener: Callable[..., BinaryIO] = open,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """The sole real-asset entry point; invocation is RQ1-C1 work."""

    contract_path = validate_execution_authority(
        execute_final=execute_final,
        expected_harness_head=expected_harness_head,
        authority_contract_argument=authority_contract_argument,
        environment=environment,
        root=root,
    )
    runtime_bundle = runtime_preparer(root, expected_harness_head)
    contract = runtime_bundle.authority_contract
    validate_authority_contract(contract)
    if contract_path != root.joinpath(*AUTHORITY_CONTRACT_RELATIVE.parts):
        raise SealedAccessError("authority contract location changed during pre-arm")
    result_target = result_preflighter(root)
    track_a = contract["track_a"]
    raw_relative = PurePosixPath(str(track_a["expected_local_relative_path"]))
    if raw_relative != TRACK_A_RELATIVE_PATH or raw_relative.is_absolute() or ".." in raw_relative.parts:
        raise SealedAccessError("authority contract raw path mismatch")
    # Do not call exists/stat/hash/resolve/readlink on asset_path.  The first
    # filesystem operation on it is the single opener call below.
    asset_path = root.joinpath(*raw_relative.parts)
    lock_path = root.joinpath(*LOCAL_ARTIFACTS_RELATIVE.parts) / LOCK_FILE_NAME

    def parse_and_audit(raw_bytes: bytes) -> dict[str, Any]:
        records, schema_report = parse_final_csv_bytes(raw_bytes, contract)
        contamination = audit_contamination(
            records, runtime_bundle.reference_identity_sets
        )
        require_contamination_clear(contamination)
        return {
            "records": records,
            "schema_validation": schema_report,
            "contamination_audit": contamination,
        }

    def evaluate_with_audit(parsed: Mapping[str, Any]) -> Mapping[str, Any]:
        result = dict(evaluator(parsed["records"], runtime_bundle))
        result["input_schema_validation"] = parsed["schema_validation"]
        result["contamination_audit"] = parsed["contamination_audit"]
        return result

    return consume_one_shot_asset(
        asset_path=asset_path,
        lock_path=lock_path,
        expected_sha256=str(track_a["sha256"]),
        expected_size=int(track_a["size_bytes"]),
        expected_head=expected_harness_head,
        parser=parse_and_audit,
        evaluator=evaluate_with_audit,
        result_persister=lambda result: persist_result_atomically(
            result, result_target
        ),
        opener=opener,
    )
