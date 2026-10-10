"""Atomic mutable state receipt locked by the immutable reservation sentinel."""

from __future__ import annotations

from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable, Mapping, Sequence

from . import STATE_SCHEMA, RQ2D3R4Error, canonical_json_bytes, sha256_bytes, utc_timestamp
from .durable_no_replace_artifact_v1_2 import (
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .immutable_reservation_sentinel_v1_2 import read_reservation_sentinel_v1_2
from .terminal_state_machine_v1_2 import (
    COMPLETED,
    FAILED,
    TERMINAL_STATES,
    require_transition_v1_2,
    validate_transition_chain_v1_2,
)


class AtomicStateError(RQ2D3R4Error):
    pass


StateMutation = Callable[[dict[str, Any]], None]
BeforeReplaceHook = Callable[[Path, Path], None]


def _bundle_commitment(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "cumulative_bundle_commitment"}
    return sha256_bytes(canonical_json_bytes(payload))


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise AtomicStateError("short atomic state write")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_file_nofollow(path: Path, *, expected_mode: int = 0o600) -> bytes:
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != expected_mode
    ):
        raise AtomicStateError("BLOCKED_RQ2_D4_ATOMIC_STATE_UNSAFE")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise AtomicStateError("BLOCKED_RQ2_D4_ATOMIC_STATE_UNSAFE")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def verify_execution_state_document_v1_2(document: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "state_version",
        "previous_state_sha256",
        "previous_state",
        "current_state",
        "transition_index",
        "transition_timestamp",
        "execution_id",
        "approved_head",
        "effective_contract_id",
        "sentinel_sha256",
        "parent_receipt_sha256",
        "transitions",
        "state_file_chain",
        "state_file_chain_commitment",
        "stage_receipts",
        "worker_roles",
        "open_read_counters",
        "firewall_evidence",
        "hard_failure_evidence",
        "cumulative_bundle_commitment",
        "root_failure_code",
        "root_failure_stage",
        "root_failure_timestamp",
        "last_successful_state",
        "root_failure_receipt",
        "retry_permitted",
        "synthetic",
    }
    if (
        not required <= set(document)
        or document.get("schema_version") != STATE_SCHEMA
        or document.get("retry_permitted") is not False
        or document.get("state_file_chain_commitment")
        != sha256_bytes(canonical_json_bytes(document.get("state_file_chain")))
        or document.get("cumulative_bundle_commitment") != _bundle_commitment(document)
    ):
        raise AtomicStateError("BLOCKED_RQ2_D4_ATOMIC_STATE_MISMATCH")
    validate_transition_chain_v1_2(
        document["transitions"], current_state=str(document["current_state"])
    )
    if document.get("current_state") == FAILED:
        if not all(
            document.get(name)
            for name in (
                "root_failure_code",
                "root_failure_stage",
                "root_failure_timestamp",
                "last_successful_state",
                "root_failure_receipt",
            )
        ):
            raise AtomicStateError("FAILED state root failure incomplete")
    elif any(
        document.get(name) is not None
        for name in (
            "root_failure_code",
            "root_failure_stage",
            "root_failure_timestamp",
            "root_failure_receipt",
        )
    ):
        raise AtomicStateError("non-FAILED state carries root failure")


def read_execution_state_v1_2(path: Path) -> tuple[dict[str, Any], bytes]:
    value = _read_file_nofollow(path)
    try:
        document = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AtomicStateError("BLOCKED_RQ2_D4_ATOMIC_STATE_MISMATCH") from error
    verify_execution_state_document_v1_2(document)
    return document, value


def initial_execution_state_document_v1_2(
    *,
    execution_id: str,
    approved_head: str,
    effective_contract_id: str,
    sentinel_sha256: str,
    synthetic: bool,
    transition_timestamp: str | None = None,
) -> dict[str, Any]:
    timestamp = transition_timestamp or utc_timestamp()
    transition = {
        "previous_state": None,
        "current_state": "GLOBAL_RESERVED",
        "transition_index": 0,
        "transition_timestamp": timestamp,
        "stage_receipts": [],
        "evidence_summary": {"reservation": "PERSISTED"},
    }
    document: dict[str, Any] = {
        "schema_version": STATE_SCHEMA,
        "state_version": 1,
        "previous_state_sha256": None,
        "previous_state": None,
        "current_state": "GLOBAL_RESERVED",
        "transition_index": 0,
        "transition_timestamp": timestamp,
        "execution_id": execution_id,
        "approved_head": approved_head,
        "effective_contract_id": effective_contract_id,
        "sentinel_sha256": sentinel_sha256,
        "parent_receipt_sha256": None,
        "transitions": [transition],
        "state_file_chain": [],
        "state_file_chain_commitment": sha256_bytes(canonical_json_bytes([])),
        "stage_receipts": [],
        "worker_roles": {},
        "open_read_counters": {},
        "firewall_evidence": [],
        "hard_failure_evidence": [],
        "administrative_events": [],
        "root_failure_code": None,
        "root_failure_stage": None,
        "root_failure_timestamp": None,
        "last_successful_state": "GLOBAL_RESERVED",
        "root_failure_receipt": None,
        "retry_permitted": False,
        "synthetic": bool(synthetic),
    }
    document["cumulative_bundle_commitment"] = _bundle_commitment(document)
    return document


def initialise_execution_state_v1_2(
    state_path: Path,
    sentinel_path: Path,
    document: Mapping[str, Any],
    *,
    state_relative_path: str,
) -> dict[str, Any]:
    sentinel, sentinel_value = read_reservation_sentinel_v1_2(sentinel_path)
    if document.get("sentinel_sha256") != sha256_bytes(sentinel_value):
        raise AtomicStateError("state sentinel identity mismatch")
    verify_execution_state_document_v1_2(document)
    receipt = publish_no_replace_artifact_v1_2(
        state_path,
        canonical_json_bytes(dict(document)),
        relative_path=state_relative_path,
        stage="GLOBAL_RESERVED",
        worker_role="RQ2_D4_PARENT_V1_2",
        worker_credential_commitment=None,
        artifact_role="ATOMIC_MUTABLE_EXECUTION_STATE_RECEIPT",
        schema_id=STATE_SCHEMA,
        record_count=1,
        approved_head=str(document["approved_head"]),
        execution_id=str(document["execution_id"]),
        effective_contract_id=str(document["effective_contract_id"]),
        code_identity=str(sentinel.get("d3_r4_code_bundle_identity", "SYNTHETIC")),
        parent_state="IMMUTABLE_SENTINEL_PERSISTED",
        schema_validator=json_object_validator(STATE_SCHEMA),
    )
    read_execution_state_v1_2(state_path)
    return receipt


def atomic_mutate_execution_state_v1_2(
    state_path: Path,
    sentinel_path: Path,
    mutation: StateMutation,
    *,
    new_state: str | None = None,
    stage_receipts: Sequence[Mapping[str, Any]] = (),
    evidence_summary: Mapping[str, Any] | None = None,
    before_replace: BeforeReplaceHook | None = None,
) -> dict[str, Any]:
    sentinel_document, sentinel_value = read_reservation_sentinel_v1_2(sentinel_path)
    sentinel_before = os.lstat(sentinel_path)
    sentinel_descriptor = os.open(
        sentinel_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    )
    temporary: Path | None = None
    try:
        sentinel_after = os.fstat(sentinel_descriptor)
        if (
            not stat.S_ISREG(sentinel_after.st_mode)
            or (sentinel_before.st_dev, sentinel_before.st_ino)
            != (sentinel_after.st_dev, sentinel_after.st_ino)
            or stat.S_IMODE(sentinel_after.st_mode) != 0o600
        ):
            raise AtomicStateError("state sentinel inode mismatch")
        fcntl.flock(sentinel_descriptor, fcntl.LOCK_EX)
        os.lseek(sentinel_descriptor, 0, os.SEEK_SET)
        locked_sentinel = b""
        while True:
            chunk = os.read(sentinel_descriptor, 1024 * 1024)
            if not chunk:
                break
            locked_sentinel += chunk
        if locked_sentinel != sentinel_value:
            raise AtomicStateError("state sentinel bytes changed before lock")
        current, current_value = read_execution_state_v1_2(state_path)
        if current.get("current_state") == FAILED:
            raise AtomicStateError("ALREADY_TERMINAL_FAILED")
        if current.get("current_state") == COMPLETED:
            raise AtomicStateError("ALREADY_TERMINAL_COMPLETED")
        current_sha = sha256_bytes(current_value)
        if current.get("sentinel_sha256") != sha256_bytes(sentinel_value):
            raise AtomicStateError("state/sentinel identity mismatch")
        updated = deepcopy(current)
        if new_state is not None:
            previous_state = str(current["current_state"])
            require_transition_v1_2(previous_state, new_state)
            if new_state == COMPLETED:
                completion = dict((evidence_summary or {}).get("completion_evidence") or {})
                completion_requirements = (
                    completion.get("completion_eligible") is True,
                    completion.get("hard_failure_count") == 0,
                    completion.get("hard_failure_count")
                    == len(completion.get("hard_failure_events") or []),
                    completion.get("required_workers_consumed_success") is True,
                    completion.get("required_stage_receipts_valid") is True,
                    completion.get("expected_open_read_counts_exact") is True,
                    completion.get("artifacts_bound") is True,
                    completion.get("state_chain_valid") is True,
                    completion.get("feature_prediction_binding_valid") is True,
                    completion.get("method_metric_complete") is True,
                    completion.get("statistical_complete") is True,
                )
                if not all(completion_requirements):
                    raise AtomicStateError("BLOCKED_RQ2_D4_COMPLETION_EVIDENCE")
            timestamp = utc_timestamp()
            transition_index = int(current["transition_index"]) + 1
            transition = {
                "previous_state": previous_state,
                "current_state": new_state,
                "transition_index": transition_index,
                "transition_timestamp": timestamp,
                "stage_receipts": [dict(row) for row in stage_receipts],
                "evidence_summary": dict(evidence_summary or {}),
            }
            updated["previous_state"] = previous_state
            updated["current_state"] = new_state
            updated["transition_index"] = transition_index
            updated["transition_timestamp"] = timestamp
            updated["transitions"].append(transition)
            updated["stage_receipts"].extend(dict(row) for row in stage_receipts)
            if new_state == FAILED:
                details = dict(evidence_summary or {})
                updated["root_failure_code"] = str(details.get("root_failure_code") or "UNSPECIFIED_FAILURE")
                updated["root_failure_stage"] = str(details.get("root_failure_stage") or previous_state)
                updated["root_failure_timestamp"] = timestamp
                updated["last_successful_state"] = previous_state
                updated["root_failure_receipt"] = dict(
                    details.get("root_failure_receipt")
                    or {
                        "artifact_role": "ROOT_FAILURE_RECEIPT",
                        "sha256": sha256_bytes(
                            canonical_json_bytes(
                                {
                                    "previous_state": previous_state,
                                    "failure_code": updated["root_failure_code"],
                                    "failure_stage": updated["root_failure_stage"],
                                    "timestamp": timestamp,
                                }
                            )
                        ),
                    }
                )
            elif new_state != COMPLETED:
                updated["last_successful_state"] = new_state
        mutation(updated)
        updated["state_version"] = int(current["state_version"]) + 1
        updated["previous_state_sha256"] = current_sha
        updated["state_file_chain"].append(current_sha)
        updated["state_file_chain_commitment"] = sha256_bytes(
            canonical_json_bytes(updated["state_file_chain"])
        )
        updated["cumulative_bundle_commitment"] = _bundle_commitment(updated)
        verify_execution_state_document_v1_2(updated)
        value = canonical_json_bytes(updated)
        temporary = state_path.parent / f".{state_path.name}.tmp.{secrets.token_hex(16)}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            _write_all(descriptor, value)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if before_replace is not None:
            before_replace(temporary, state_path)
        os.replace(temporary, state_path)
        temporary = None
        _fsync_directory(state_path.parent)
        reread, reread_value = read_execution_state_v1_2(state_path)
        if reread != updated or reread_value != value:
            raise AtomicStateError("atomic state reread mismatch")
        return reread
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
                _fsync_directory(state_path.parent)
            except FileNotFoundError:
                pass
        try:
            fcntl.flock(sentinel_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(sentinel_descriptor)


def transition_execution_state_v1_2(
    state_path: Path,
    sentinel_path: Path,
    new_state: str,
    *,
    stage_receipts: Sequence[Mapping[str, Any]] = (),
    evidence_summary: Mapping[str, Any] | None = None,
    mutation: StateMutation | None = None,
) -> dict[str, Any]:
    return atomic_mutate_execution_state_v1_2(
        state_path,
        sentinel_path,
        mutation or (lambda document: None),
        new_state=new_state,
        stage_receipts=stage_receipts,
        evidence_summary=evidence_summary,
    )


def fail_execution_state_v1_2(
    state_path: Path,
    sentinel_path: Path,
    *,
    failure_code: str,
    failure_stage: str,
    failure_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current, _ = read_execution_state_v1_2(state_path)
    if current.get("current_state") == FAILED:
        raise AtomicStateError("ALREADY_TERMINAL_FAILED")
    if current.get("current_state") == COMPLETED:
        raise AtomicStateError("ALREADY_TERMINAL_COMPLETED")
    return transition_execution_state_v1_2(
        state_path,
        sentinel_path,
        FAILED,
        evidence_summary={
            "root_failure_code": failure_code,
            "root_failure_stage": failure_stage,
            "root_failure_receipt": dict(failure_receipt or {}),
        },
    )


def atomic_execution_state_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-atomic-execution-state-contract-v1-2",
        "status": "FROZEN",
        "role": "ATOMIC_MUTABLE_EXECUTION_STATE_RECEIPT",
        "separate_from_immutable_sentinel": True,
        "initial_publication": "ATOMIC_NO_REPLACE",
        "later_publication": "SAME_DIRECTORY_TEMP_AND_OS_REPLACE",
        "temporary_mode": "0600",
        "temporary_file_fsync": True,
        "immutable_sentinel_flock_exclusive": True,
        "current_state_reread_under_lock": True,
        "full_chain_verified_before_replace": True,
        "control_directory_fsync": True,
        "reread_verified": True,
        "in_place_truncate": False,
        "crash_before_replace_preserves_old_state": True,
        "sentinel_modified_by_state_update": False,
    }
