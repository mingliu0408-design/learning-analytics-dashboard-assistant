"""Wholly synthetic global-lock harness, separate from the real D1 API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import canonical_json_bytes, sha256_bytes
from .global_one_shot_lock import (
    GLOBAL_RECEIPT_FIELDS,
    mark_global_failed_v1_3,
    read_global_lock_v1_3,
    reserve_synthetic_test_access_v1_3,
    update_global_state_v1_3,
)
from .output_root_identity import (
    compute_global_lock_identity_v1_3,
    compute_output_root_identity_v1_3,
)


SYNTHETIC_EXECUTION_CONTRACT_ID = (
    "RQ2_SYNTHETIC_GLOBAL_ONE_SHOT_HARNESS_V1_3"
)
SYNTHETIC_OUTPUT_RELATIVE = "synthetic-output-v1-3"
SYNTHETIC_CONTROL_RELATIVE = "synthetic-control-v1-3"
SYNTHETIC_LOCK_RELATIVE = (
    "synthetic-control-v1-3/SYNTHETIC_GLOBAL_ACCESS_V1_3.json"
)
SYNTHETIC_LOCK_NAME = "SYNTHETIC_GLOBAL_ACCESS_V1_3.json"
FIXED_SYNTHETIC_TIMESTAMP = "2026-08-28T00:00:00+00:00"


class SyntheticHarnessError(RuntimeError):
    pass


def synthetic_paths(synthetic_root: Path) -> tuple[Path, Path, Path]:
    return (
        synthetic_root / SYNTHETIC_OUTPUT_RELATIVE,
        synthetic_root / SYNTHETIC_CONTROL_RELATIVE,
        synthetic_root / SYNTHETIC_LOCK_RELATIVE,
    )


def build_synthetic_reservation_payload(
    *, synthetic_authority: Mapping[str, Any]
) -> dict[str, Any]:
    authority_commitment = str(
        synthetic_authority.get("reference_authority_commitment") or ""
    )
    if len(authority_commitment) != 64:
        raise SyntheticHarnessError("synthetic authority commitment required")
    return {
        "schema_version": "track-b-global-access-lock-v1.3",
        "execution_contract_id": SYNTHETIC_EXECUTION_CONTRACT_ID,
        "state": "GLOBAL_RESERVED",
        "state_history": ["GLOBAL_RESERVED"],
        "last_successful_state": "GLOBAL_RESERVED",
        "global_access_consumed": True,
        "retry_permitted": False,
        "approved_head": "SYNTHETIC_ONLY",
        "fixed_output_root_relative": SYNTHETIC_OUTPUT_RELATIVE,
        "fixed_global_lock_relative": SYNTHETIC_LOCK_RELATIVE,
        "output_root_identity": compute_output_root_identity_v1_3(
            SYNTHETIC_EXECUTION_CONTRACT_ID, SYNTHETIC_OUTPUT_RELATIVE
        ),
        "global_lock_identity": compute_global_lock_identity_v1_3(
            SYNTHETIC_EXECUTION_CONTRACT_ID, SYNTHETIC_LOCK_RELATIVE
        ),
        "safe_schema_authority_sha256": "a" * 64,
        "reference_authority_commitment": authority_commitment,
        "expected_raw_sha256": "b" * 64,
        "expected_raw_size": 1,
        "expected_raw_records": 1,
        "reservation_created_at": FIXED_SYNTHETIC_TIMESTAMP,
        "raw_open_count": 0,
        "raw_read_count": 0,
        "post_completed_writes_permitted": False,
    }


def _write_safe_output(path: Path, value: Mapping[str, Any]) -> None:
    raw = canonical_json_bytes(dict(value))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _receipt(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {field: lock[field] for field in GLOBAL_RECEIPT_FIELDS}


def execute_synthetic_global_one_shot_harness_v1_3(
    synthetic_root: Path,
    synthetic_records: Sequence[Mapping[str, Any]],
    synthetic_authority: Mapping[str, Any],
    *,
    simulate_failure_after_state: str | None = None,
) -> dict[str, Any]:
    """Exercise global lifecycle without real constants, paths, or raw data."""

    synthetic_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_root, control_root, lock_path = synthetic_paths(synthetic_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise SyntheticHarnessError("synthetic output root must be new or empty")
    payload = build_synthetic_reservation_payload(
        synthetic_authority=synthetic_authority
    )
    reserve_synthetic_test_access_v1_3(
        control_root=control_root,
        lock_path=lock_path,
        reservation_payload=payload,
    )
    key_generation_count = 0
    synthetic_open_count = 0
    synthetic_read_count = 0
    try:
        if simulate_failure_after_state == "GLOBAL_RESERVED":
            raise SyntheticHarnessError("simulated post-reservation failure")
        if not output_root.exists():
            os.mkdir(output_root, 0o700)
        key_generation_count = 1
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="GLOBAL_RESERVED",
            next_state="KEY_PERSISTED",
            updates={"synthetic_key_persisted": True},
        )
        if simulate_failure_after_state == "KEY_PERSISTED":
            raise SyntheticHarnessError("simulated key-persisted failure")
        lock = update_global_state_v1_3(
            lock_path, expected_state="KEY_PERSISTED", next_state="ARMED"
        )
        if simulate_failure_after_state == "ARMED":
            raise SyntheticHarnessError("simulated armed failure")
        synthetic_open_count = 1
        synthetic_read_count = 1
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="ARMED",
            next_state="OPENED",
            updates={
                "raw_open_count": synthetic_open_count,
                "raw_read_count": synthetic_read_count,
            },
        )
        receipt = _receipt(lock)
        case_manifest = {
            "schema_version": "synthetic-case-bank-manifest-v1.3",
            "record_count": len(synthetic_records),
            "global_receipt": receipt,
        }
        _write_safe_output(output_root / "synthetic_case_bank_manifest.json", case_manifest)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="OPENED",
            next_state="CASE_BANK_PERSISTED",
        )
        escrow_manifest = {
            "schema_version": "synthetic-escrow-manifest-v1.3",
            "record_count": len(synthetic_records),
            "global_receipt": receipt,
        }
        _write_safe_output(output_root / "synthetic_escrow_manifest.json", escrow_manifest)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="CASE_BANK_PERSISTED",
            next_state="LEGACY_ESCROW_PERSISTED",
        )
        audit = {
            "schema_version": "synthetic-contamination-audit-v1.3",
            "status": "PASS",
            "global_receipt": receipt,
        }
        _write_safe_output(output_root / "synthetic_contamination_audit.json", audit)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="LEGACY_ESCROW_PERSISTED",
            next_state="CONTAMINATION_AUDIT_PERSISTED",
        )
        for reviewer in ("a", "b"):
            _write_safe_output(
                output_root / f"synthetic_reviewer_{reviewer}_manifest.json",
                {
                    "schema_version": "synthetic-reviewer-packet-manifest-v1.3",
                    "reviewer": reviewer.upper(),
                    "global_receipt": receipt,
                },
            )
        packet_manifest = {
            "schema_version": "synthetic-packet-manifest-v1.3",
            "record_count": len(synthetic_records),
            "global_receipt": receipt,
        }
        _write_safe_output(output_root / "synthetic_packet_manifest.json", packet_manifest)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="CONTAMINATION_AUDIT_PERSISTED",
            next_state="REVIEW_PACKETS_PERSISTED",
        )
        if simulate_failure_after_state == "REVIEW_PACKETS_PERSISTED":
            raise SyntheticHarnessError("simulated packet failure")
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="REVIEW_PACKETS_PERSISTED",
            next_state="COMPLETED",
            updates={"completed_global_receipt": receipt},
        )
        return {
            "status": "COMPLETED",
            "lock": lock,
            "lock_sha256": sha256_bytes(lock_path.read_bytes()),
            "key_generation_count": key_generation_count,
            "synthetic_open_count": synthetic_open_count,
            "synthetic_read_count": synthetic_read_count,
            "real_raw_open_count": 0,
            "real_global_lock_created": False,
            "real_key_created": False,
            "real_packets_created": False,
            "synthetic_lock_path": lock_path,
            "synthetic_output_root": output_root,
        }
    except Exception as exc:
        failed = mark_global_failed_v1_3(
            lock_path,
            failure_stage=str(read_global_lock_v1_3(lock_path).get("state")),
            failure_code=type(exc).__name__,
            failure_timestamp=FIXED_SYNTHETIC_TIMESTAMP,
            raw_open_count=synthetic_open_count,
            raw_read_count=synthetic_read_count,
        )
        setattr(exc, "synthetic_failure_lock", failed)
        raise
