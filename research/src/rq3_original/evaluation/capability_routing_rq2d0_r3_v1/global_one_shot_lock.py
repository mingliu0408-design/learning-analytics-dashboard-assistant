"""Durable repository-global singleton reservation for future real D1."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
    REFERENCE_AUTHORITY_COMMITMENT,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    canonical_json_bytes,
    sha256_bytes,
)
from .fixed_d1_paths import ResolvedRealD1FixedPathsV1_3
from .output_root_identity import (
    fixed_global_lock_identity_v1_3,
    fixed_output_root_identity_v1_3,
)


GLOBAL_STATE_ORDER = (
    "GLOBAL_RESERVED",
    "KEY_PERSISTED",
    "ARMED",
    "OPENED",
    "CASE_BANK_PERSISTED",
    "LEGACY_ESCROW_PERSISTED",
    "CONTAMINATION_AUDIT_PERSISTED",
    "REVIEW_PACKETS_PERSISTED",
    "COMPLETED",
)
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED"})
GLOBAL_RECEIPT_FIELDS = (
    "execution_contract_id",
    "fixed_output_root_relative",
    "fixed_global_lock_relative",
    "output_root_identity",
    "global_lock_identity",
    "reference_authority_commitment",
    "approved_head",
)


class GlobalReservationError(RuntimeError):
    pass


class GlobalAccessAlreadyReserved(GlobalReservationError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_real_global_reservation_payload_v1_3(
    *,
    approved_head: str,
    safe_schema_authority_sha256: str,
    reference_authority_commitment: str,
    reservation_created_at: str,
) -> dict[str, Any]:
    if not reservation_created_at:
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    return {
        "schema_version": "track-b-global-access-lock-v1.3",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "state": "GLOBAL_RESERVED",
        "state_history": ["GLOBAL_RESERVED"],
        "last_successful_state": "GLOBAL_RESERVED",
        "global_access_consumed": True,
        "retry_permitted": False,
        "approved_head": approved_head,
        "fixed_output_root_relative": REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
        "fixed_global_lock_relative": REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
        "output_root_identity": fixed_output_root_identity_v1_3(),
        "global_lock_identity": fixed_global_lock_identity_v1_3(),
        "safe_schema_authority_sha256": safe_schema_authority_sha256,
        "reference_authority_commitment": reference_authority_commitment,
        "expected_raw_sha256": TRACK_B_SHA256,
        "expected_raw_size": TRACK_B_SIZE_BYTES,
        "expected_raw_records": TRACK_B_RECORD_COUNT,
        "reservation_created_at": reservation_created_at,
        "raw_open_count": 0,
        "raw_read_count": 0,
        "post_completed_writes_permitted": False,
    }


def global_receipt_from_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return {field: lock[field] for field in GLOBAL_RECEIPT_FIELDS}
    except KeyError as exc:
        raise GlobalReservationError(
            "BLOCKED_RQ2_D1_GLOBAL_RECEIPT_MISMATCH"
        ) from exc


def require_global_receipt_match(
    candidate: Mapping[str, Any], authoritative_lock: Mapping[str, Any]
) -> None:
    expected = global_receipt_from_lock(authoritative_lock)
    if any(candidate.get(field) != value for field, value in expected.items()):
        raise GlobalReservationError("BLOCKED_RQ2_D1_GLOBAL_RECEIPT_MISMATCH")


def _validate_reservation_payload(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != "track-b-global-access-lock-v1.3"
        or payload.get("state") != "GLOBAL_RESERVED"
        or payload.get("state_history") != ["GLOBAL_RESERVED"]
        or payload.get("global_access_consumed") is not True
        or payload.get("retry_permitted") is not False
        or not payload.get("reservation_created_at")
        or int(payload.get("raw_open_count", -1)) != 0
        or int(payload.get("raw_read_count", -1)) != 0
        or any(field not in payload for field in GLOBAL_RECEIPT_FIELDS)
    ):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")


def _assert_real_paths(paths: ResolvedRealD1FixedPathsV1_3) -> None:
    if (
        paths.output_root
        != paths.repo_root / REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3
        or paths.global_control_root
        != paths.repo_root / REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3
        or paths.global_lock_path
        != paths.repo_root / REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3
    ):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")


def _assert_normal_directory(path: Path, *, required_mode: int | None = None) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    if required_mode is not None and stat.S_IMODE(mode) != required_mode:
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")


def _ensure_private_control_root(control_root: Path) -> None:
    _assert_normal_directory(control_root.parent)
    try:
        os.mkdir(control_root, 0o700)
    except FileExistsError:
        pass
    _assert_normal_directory(control_root, required_mode=0o700)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_regular_no_follow(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise GlobalReservationError(
            "BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION"
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _exclusive_reserve(
    *, control_root: Path, lock_path: Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_reservation_payload(payload)
    _ensure_private_control_root(control_root)
    try:
        lock_path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        )
    raw = canonical_json_bytes(dict(payload))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        ) from exc
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise GlobalReservationError(
                    "BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION"
                )
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(control_root)
    observed = _read_regular_no_follow(lock_path)
    mode = stat.S_IMODE(lock_path.lstat().st_mode)
    if (
        observed != raw
        or sha256_bytes(observed) != sha256_bytes(raw)
        or len(observed) != len(raw)
        or mode != 0o600
        or json.loads(observed) != dict(payload)
    ):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    return {
        "status": "GLOBAL_RESERVED",
        "sha256": sha256_bytes(raw),
        "size_bytes": len(raw),
        "file_mode_octal": "0600",
        "control_directory_mode_octal": "0700",
        "durably_reverified": True,
    }


def reserve_global_track_b_access_v1_3(
    paths: ResolvedRealD1FixedPathsV1_3,
    reservation_payload: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_real_paths(paths)
    fixed_values = {
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "fixed_output_root_relative": REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
        "fixed_global_lock_relative": (
            REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3
        ),
        "output_root_identity": fixed_output_root_identity_v1_3(),
        "global_lock_identity": fixed_global_lock_identity_v1_3(),
        "reference_authority_commitment": REFERENCE_AUTHORITY_COMMITMENT,
        "expected_raw_sha256": TRACK_B_SHA256,
        "expected_raw_size": TRACK_B_SIZE_BYTES,
        "expected_raw_records": TRACK_B_RECORD_COUNT,
    }
    if (
        any(
            reservation_payload.get(field) != expected
            for field, expected in fixed_values.items()
        )
        or len(str(reservation_payload.get("approved_head") or "")) != 40
        or len(
            str(
                reservation_payload.get("safe_schema_authority_sha256")
                or ""
            )
        )
        != 64
    ):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    return _exclusive_reserve(
        control_root=paths.global_control_root,
        lock_path=paths.global_lock_path,
        payload=reservation_payload,
    )


def reserve_synthetic_test_access_v1_3(
    *, control_root: Path, lock_path: Path, reservation_payload: Mapping[str, Any]
) -> dict[str, Any]:
    if reservation_payload.get("execution_contract_id") == EXECUTION_CONTRACT_ID:
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_SYNTHETIC_REAL_BOUNDARY")
    return _exclusive_reserve(
        control_root=control_root, lock_path=lock_path, payload=reservation_payload
    )


def read_global_lock_v1_3(lock_path: Path) -> dict[str, Any]:
    raw = _read_regular_no_follow(lock_path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        ) from exc
    if not isinstance(value, dict):
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        )
    return value


def assert_global_access_unreserved_v1_3(lock_path: Path) -> None:
    try:
        lock_path.lstat()
    except FileNotFoundError:
        return
    raise GlobalAccessAlreadyReserved(
        "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
    )


def _replace_durable(lock_path: Path, payload: Mapping[str, Any]) -> None:
    try:
        mode = lock_path.lstat().st_mode
    except FileNotFoundError as exc:
        raise GlobalReservationError(
            "BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION"
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")
    raw = canonical_json_bytes(dict(payload))
    temporary = lock_path.with_name(
        f".{lock_path.name}.state-update-{os.getpid()}"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise GlobalReservationError(
                    "BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION"
                )
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, lock_path)
    _fsync_directory(lock_path.parent)
    if _read_regular_no_follow(lock_path) != raw:
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_GLOBAL_RESERVATION")


def update_global_state_v1_3(
    lock_path: Path,
    *,
    expected_state: str,
    next_state: str,
    updates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lock = read_global_lock_v1_3(lock_path)
    state = str(lock.get("state") or "")
    if state in TERMINAL_STATES:
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        )
    try:
        expected_index = GLOBAL_STATE_ORDER.index(expected_state)
    except ValueError as exc:
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_STATE_MACHINE") from exc
    if (
        state != expected_state
        or expected_index + 1 >= len(GLOBAL_STATE_ORDER)
        or GLOBAL_STATE_ORDER[expected_index + 1] != next_state
    ):
        raise GlobalReservationError("BLOCKED_RQ2_D0_R3_STATE_MACHINE")
    lock.update(dict(updates or {}))
    lock["state"] = next_state
    lock["last_successful_state"] = next_state
    lock.setdefault("state_history", []).append(next_state)
    lock["retry_permitted"] = False
    _replace_durable(lock_path, lock)
    return lock


def mark_global_failed_v1_3(
    lock_path: Path,
    *,
    failure_stage: str,
    failure_code: str,
    failure_timestamp: str,
    raw_open_count: int,
    raw_read_count: int,
) -> dict[str, Any]:
    lock = read_global_lock_v1_3(lock_path)
    if lock.get("state") in TERMINAL_STATES:
        raise GlobalAccessAlreadyReserved(
            "BLOCKED_RQ2_D1_GLOBAL_ACCESS_ALREADY_RESERVED"
        )
    last = str(lock.get("state") or "UNKNOWN_BUT_PRESENT")
    lock.update(
        {
            "state": "FAILED",
            "last_successful_state": last,
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "failure_timestamp": failure_timestamp,
            "raw_open_count": raw_open_count,
            "raw_read_count": raw_read_count,
            "retry_permitted": False,
            "global_access_consumed": True,
        }
    )
    lock.setdefault("state_history", []).append("FAILED")
    _replace_durable(lock_path, lock)
    return lock


def global_reservation_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-global-reservation-contract-v1.3",
        "status": "FROZEN_BEFORE_REAL_D1",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "global_state_order": list(GLOBAL_STATE_ORDER),
        "first_consuming_state": "GLOBAL_RESERVED",
        "exclusive_creation_flags": ["O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
        "reservation_file_mode": "0600",
        "global_control_directory_mode": "0700",
        "durability_sequence": [
            "write",
            "flush_by_complete_os_write",
            "fsync_file",
            "close",
            "fsync_parent_directory",
            "reread_no_follow",
            "schema_sha_size_verification",
        ],
        "reservation_before_key_generation": True,
        "reservation_before_raw_open": True,
        "existing_any_state_blocks": True,
        "unknown_but_present_blocks": True,
        "failed_lock_retry_permitted": False,
        "completed_lock_retry_permitted": False,
        "global_lock_permanently_retained": True,
        "per_output_consumed_lock_permitted": False,
        "alternative_global_lock_permitted": False,
        "real_global_lock_created_in_rq2_d0_r3": False,
    }
