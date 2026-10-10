"""Durable repository-global D4 one-shot state machine primitives."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


GLOBAL_STATE_ORDER = (
    "GLOBAL_RESERVED",
    "INPUT_IDENTITIES_VERIFIED",
    "COMBINED_CASE_SOURCE_OPENED",
    "FEATURE_VIEW_PERSISTED",
    "FEATURE_FIREWALL_VERIFIED",
    "B0_PREDICTIONS_PERSISTED",
    "B1_PREDICTIONS_PERSISTED",
    "P1_PREDICTIONS_PERSISTED",
    "PREDICTION_FIREWALL_VERIFIED",
    "LABEL_GOLD_OPENED",
    "GROUPING_OPENED",
    "PRIMARY_METRICS_PERSISTED",
    "SECONDARY_DIAGNOSTICS_PERSISTED",
    "RESULT_PERSISTED",
    "COMPLETED",
)
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED"})


class GlobalOneShotConsumedError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_global_lock_v1(lock_path: Path, *, execution_id: str, synthetic: bool) -> dict[str, Any]:
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(lock_path.parent, 0o700)
    payload = {
        "schema_version": "rq2d4-global-one-shot-lock-v1",
        "contract_id": "RQ2_TRACK_B_B0_B1_P1_FINAL_EVALUATION_GLOBAL_ONE_SHOT_V1" if not synthetic else "SYNTHETIC_TEST_ONLY_RQ2D4_GLOBAL_ONE_SHOT_V1",
        "execution_id": execution_id,
        "state": "GLOBAL_RESERVED",
        "state_history": ["GLOBAL_RESERVED"],
        "last_successful_state": "GLOBAL_RESERVED",
        "retry_permitted": False,
        "synthetic_test_only": synthetic,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise GlobalOneShotConsumedError("repository-global D4 one-shot already consumed") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical(payload))
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(lock_path, 0o600)
    _fsync_directory(lock_path.parent)
    observed = json.loads(lock_path.read_text(encoding="utf-8"))
    if observed != payload:
        raise RuntimeError("global reservation reread mismatch")
    return payload


def read_global_lock_v1(lock_path: Path) -> dict[str, Any]:
    if not lock_path.is_file() or lock_path.is_symlink():
        raise GlobalOneShotConsumedError("global lock absent or unsafe")
    return json.loads(lock_path.read_text(encoding="utf-8"))


def _replace_lock(lock_path: Path, payload: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".rq2d4-lock-", dir=lock_path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, lock_path)
        _fsync_directory(lock_path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def transition_global_lock_v1(lock_path: Path, next_state: str) -> dict[str, Any]:
    payload = read_global_lock_v1(lock_path)
    current = str(payload["state"])
    if current in TERMINAL_STATES:
        raise GlobalOneShotConsumedError("terminal D4 lock cannot transition")
    if next_state == "FAILED":
        payload["state"] = "FAILED"
        payload["state_history"].append("FAILED")
        payload["retry_permitted"] = False
    else:
        expected_index = GLOBAL_STATE_ORDER.index(current) + 1
        if expected_index >= len(GLOBAL_STATE_ORDER) or GLOBAL_STATE_ORDER[expected_index] != next_state:
            raise ValueError("illegal D4 state transition")
        payload["state"] = next_state
        payload["state_history"].append(next_state)
        payload["last_successful_state"] = next_state
    _replace_lock(lock_path, payload)
    if read_global_lock_v1(lock_path) != payload:
        raise RuntimeError("D4 lock transition reread mismatch")
    return payload


def state_machine_contract_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-d4-state-machine-v1",
        "status": "FROZEN",
        "states": list(GLOBAL_STATE_ORDER),
        "failure_state": "FAILED",
        "retry_permitted_after_reservation": False,
        "failure_lock_persistent": True,
        "completion_lock_persistent": True,
        "fixed_read_counts": {
            "combined_case_source_open_read": "1/1",
            "label_only_gold_open_read": "1/1",
            "grouping_ledger_open_read": "1/1",
        },
    }
