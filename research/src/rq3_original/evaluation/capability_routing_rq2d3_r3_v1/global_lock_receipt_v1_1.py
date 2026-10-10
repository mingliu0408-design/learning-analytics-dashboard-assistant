"""Repository-global lock with cumulative, durable transition receipts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping, Sequence

from . import GLOBAL_LOCK_SCHEMA, RQ2D3R3Error, canonical_json_bytes, sha256_bytes
from .rq2d4_state_machine_v1_1 import FAILURE_STATE, require_successor


class GlobalLockError(RQ2D3R3Error):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normal_parent(path: Path) -> None:
    value = os.lstat(path.parent)
    if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
        raise GlobalLockError("unsafe global-lock parent")


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise GlobalLockError("short global-lock write")
        view = view[written:]


def _bundle_commitment(document: Mapping[str, Any]) -> str:
    payload = {
        "state": document.get("state"),
        "fixed_identity_bundle": document.get("fixed_identity_bundle"),
        "prearm_runtime_smoke_receipt": document.get("prearm_runtime_smoke_receipt"),
        "worker_roles": document.get("worker_roles"),
        "failure": document.get("failure"),
        "transitions": [
            {
                "transition_index": row.get("transition_index"),
                "new_state": row.get("new_state"),
                "worker_role": row.get("authorised_worker_role"),
                "credential_commitment": row.get("worker_credential_commitment"),
                "stage_receipts": row.get("stage_receipt_identities"),
                "open_read_counts": row.get("actual_open_read_counts"),
            }
            for row in document.get("transitions", [])
        ],
    }
    return sha256_bytes(canonical_json_bytes(payload))


def reserve_global_lock_v1_1(
    path: Path,
    *,
    approved_head: str,
    execution_id: str,
    effective_contract_id: str,
    lock_identity: str,
    fixed_identity_bundle: Mapping[str, Any],
    prearm_runtime_smoke_receipt: Mapping[str, Any],
    synthetic: bool,
) -> dict[str, Any]:
    _normal_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    document = {
        "schema_version": GLOBAL_LOCK_SCHEMA,
        "state": "GLOBAL_RESERVED",
        "retry_permitted": False,
        "approved_head": approved_head,
        "execution_id": execution_id,
        "effective_contract_id": effective_contract_id,
        "global_lock_identity": lock_identity,
        "synthetic": bool(synthetic),
        "fixed_identity_bundle": dict(fixed_identity_bundle),
        "prearm_runtime_smoke_receipt": dict(prearm_runtime_smoke_receipt),
        "worker_roles": {},
        "transitions": [
            {
                "previous_state": None,
                "new_state": "GLOBAL_RESERVED",
                "transition_index": 0,
                "transition_timestamp": _timestamp(),
                "authorised_worker_role": None,
                "worker_credential_commitment": None,
                "stage_receipt_identities": [dict(prearm_runtime_smoke_receipt)],
                "actual_open_read_counts": {},
            }
        ],
        "failure": None,
    }
    document["cumulative_artifact_bundle_commitment"] = _bundle_commitment(document)
    try:
        _write_all(descriptor, canonical_json_bytes(document))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return read_global_lock_v1_1(path)


def _safe_lock_stat(path: Path) -> None:
    value = os.lstat(path)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise GlobalLockError("unsafe global lock")


def read_global_lock_v1_1(path: Path) -> dict[str, Any]:
    _safe_lock_stat(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        value = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            value += chunk
    finally:
        os.close(descriptor)
    document = json.loads(value)
    if document.get("schema_version") != GLOBAL_LOCK_SCHEMA:
        raise GlobalLockError("global-lock schema mismatch")
    if document.get("cumulative_artifact_bundle_commitment") != _bundle_commitment(document):
        raise GlobalLockError("global-lock cumulative commitment mismatch")
    return document


Mutator = Callable[[dict[str, Any]], None]


def locked_update_v1_1(path: Path, mutator: Mutator) -> dict[str, Any]:
    raise RuntimeError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    _safe_lock_stat(path)
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.lseek(descriptor, 0, os.SEEK_SET)
        current = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            current += chunk
        document = json.loads(current)
        if document.get("cumulative_artifact_bundle_commitment") != _bundle_commitment(document):
            raise GlobalLockError("global-lock cumulative commitment mismatch")
        mutator(document)
        document["cumulative_artifact_bundle_commitment"] = _bundle_commitment(document)
        value = canonical_json_bytes(document)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        _write_all(descriptor, value)
        os.fsync(descriptor)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return read_global_lock_v1_1(path)


def append_transition_v1_1(
    path: Path,
    *,
    new_state: str,
    worker_role: str | None,
    credential_commitment: str | None,
    stage_receipt_identities: Sequence[Mapping[str, Any]] = (),
    open_read_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> None:
        previous = str(document["state"])
        require_successor(previous, new_state)
        document["state"] = new_state
        document["transitions"].append(
            {
                "previous_state": previous,
                "new_state": new_state,
                "transition_index": len(document["transitions"]),
                "transition_timestamp": _timestamp(),
                "authorised_worker_role": worker_role,
                "worker_credential_commitment": credential_commitment,
                "stage_receipt_identities": [dict(row) for row in stage_receipt_identities],
                "actual_open_read_counts": dict(open_read_counts or {}),
            }
        )

    return locked_update_v1_1(path, mutate)


def commit_worker_credential_v1_1(
    path: Path, *, descriptor: Mapping[str, Any], commitment: str, commit_state: str
) -> dict[str, Any]:
    role = str(descriptor["worker_role"])

    def mutate(document: dict[str, Any]) -> None:
        if document["state"] == FAILURE_STATE or role in document["worker_roles"]:
            raise GlobalLockError("worker role already issued or global lock failed")
        previous = str(document["state"])
        require_successor(previous, commit_state)
        if descriptor.get("required_predecessor_state") != commit_state:
            raise GlobalLockError("worker predecessor descriptor mismatch")
        document["worker_roles"][role] = {
            "status": "ISSUED",
            "descriptor": dict(descriptor),
            "credential_commitment": commitment,
            "stage_receipt_identities": [],
            "process_report_receipt": None,
            "actual_open_read_counts": {},
            "runtime_firewall_summary": {},
        }
        document["state"] = commit_state
        document["transitions"].append(
            {
                "previous_state": previous,
                "new_state": commit_state,
                "transition_index": len(document["transitions"]),
                "transition_timestamp": _timestamp(),
                "authorised_worker_role": role,
                "worker_credential_commitment": commitment,
                "stage_receipt_identities": [
                    {
                        "artifact_role": "WORKER_CREDENTIAL_COMMITMENT",
                        "sha256": commitment,
                        "worker_role": role,
                    }
                ],
                "actual_open_read_counts": {},
            }
        )

    return locked_update_v1_1(path, mutate)


def mark_worker_claimed_v1_1(
    path: Path, *, descriptor: Mapping[str, Any], commitment: str
) -> dict[str, Any]:
    role = str(descriptor["worker_role"])

    def mutate(document: dict[str, Any]) -> None:
        entry = document.get("worker_roles", {}).get(role)
        if (
            document.get("approved_head") != descriptor.get("approved_head")
            or document.get("execution_id") != descriptor.get("execution_id")
            or document.get("effective_contract_id") != descriptor.get("effective_contract_id")
            or document.get("global_lock_identity") != descriptor.get("global_lock_identity")
            or document.get("state") != descriptor.get("required_predecessor_state")
            or not entry
            or entry.get("status") != "ISSUED"
            or entry.get("descriptor") != dict(descriptor)
            or entry.get("credential_commitment") != commitment
        ):
            raise GlobalLockError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
        entry["status"] = "CLAIMED"
        entry["claimed_at"] = _timestamp()

    return locked_update_v1_1(path, mutate)


def mark_worker_consumed_v1_1(
    path: Path,
    *,
    role: str,
    commitment: str,
    stage_receipt_identities: Sequence[Mapping[str, Any]],
    process_report_receipt: Mapping[str, Any],
    open_read_counts: Mapping[str, Any],
    runtime_firewall_summary: Mapping[str, Any],
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> None:
        entry = document.get("worker_roles", {}).get(role)
        if not entry or entry.get("status") != "CLAIMED" or entry.get("credential_commitment") != commitment:
            raise GlobalLockError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
        entry["status"] = "CONSUMED"
        entry["consumed_at"] = _timestamp()
        entry["stage_receipt_identities"] = [dict(row) for row in stage_receipt_identities]
        entry["process_report_receipt"] = dict(process_report_receipt)
        entry["actual_open_read_counts"] = dict(open_read_counts)
        entry["runtime_firewall_summary"] = dict(runtime_firewall_summary)

    return locked_update_v1_1(path, mutate)


def fail_global_lock_v1_1(path: Path, *, reason: str, worker_role: str | None = None) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> None:
        previous = str(document["state"])
        if previous == "COMPLETED":
            raise GlobalLockError("completed lock cannot fail")
        document["state"] = FAILURE_STATE
        document["retry_permitted"] = False
        if worker_role and worker_role in document.get("worker_roles", {}):
            document["worker_roles"][worker_role]["status"] = "CONSUMED_FAILED"
        timestamp = _timestamp()
        document["failure"] = {"reason": reason, "timestamp": timestamp}
        failure_receipt = {
            "artifact_role": "FAILURE_RECEIPT",
            "sha256": sha256_bytes(
                canonical_json_bytes(
                    {
                        "previous_state": previous,
                        "reason": reason,
                        "worker_role": worker_role,
                        "timestamp": timestamp,
                    }
                )
            ),
            "worker_role": worker_role,
        }
        document["transitions"].append(
            {
                "previous_state": previous,
                "new_state": FAILURE_STATE,
                "transition_index": len(document["transitions"]),
                "transition_timestamp": timestamp,
                "authorised_worker_role": worker_role,
                "worker_credential_commitment": None,
                "stage_receipt_identities": [failure_receipt],
                "actual_open_read_counts": {},
            }
        )

    return locked_update_v1_1(path, mutate)


def verify_global_lock_chain_v1_1(document: Mapping[str, Any]) -> None:
    transitions = document.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        raise GlobalLockError("global-lock transition history absent")
    for index, transition in enumerate(transitions):
        required = {
            "previous_state",
            "new_state",
            "transition_index",
            "transition_timestamp",
            "authorised_worker_role",
            "worker_credential_commitment",
            "stage_receipt_identities",
            "actual_open_read_counts",
        }
        if not required <= set(transition) or not transition.get("stage_receipt_identities"):
            raise GlobalLockError("global-lock transition receipt incomplete")
        if transition.get("transition_index") != index:
            raise GlobalLockError("global-lock transition index mismatch")
        if index and transition.get("previous_state") != transitions[index - 1].get("new_state"):
            raise GlobalLockError("global-lock parent-state chain mismatch")
        if index:
            try:
                require_successor(
                    str(transition.get("previous_state")),
                    str(transition.get("new_state")),
                )
            except ValueError as error:
                raise GlobalLockError("global-lock successor-state mismatch") from error
    if document.get("state") != transitions[-1].get("new_state"):
        raise GlobalLockError("global-lock terminal state mismatch")
    if document.get("cumulative_artifact_bundle_commitment") != _bundle_commitment(document):
        raise GlobalLockError("global-lock cumulative commitment mismatch")


def global_lock_receipt_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-global-lock-receipt-contract-v1-1",
        "status": "FROZEN",
        "global_lock_schema": GLOBAL_LOCK_SCHEMA,
        "initial_creation": ["O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
        "mode": "0600",
        "flock_for_claim_and_transition": True,
        "file_fsync": True,
        "directory_fsync": True,
        "each_transition_carries_receipts": True,
        "cumulative_bundle_commitment": True,
        "cumulative_bundle_binds_worker_consumption": True,
        "failure_transition_carries_receipt": True,
        "exit_code_trusted_without_receipt": False,
        "retry_permitted": False,
    }
