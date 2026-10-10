"""One-shot raw-to-case-bank-to-blinded-packet persistence harness."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import TRACK_B_FILE_NAME, TRACK_B_SHA256, canonical_json_bytes, sha256_bytes
from .blinded_packet_builder import build_blinded_packets
from .contamination_contract import REFERENCE_PARTITIONS, audit_contamination
from .starting_state import assert_d0_partition_allowed
from .track_b_schema_contract import parse_track_b_csv_bytes


STATE_ORDER = (
    "ARMED",
    "OPENED",
    "CASE_BANK_PERSISTED",
    "REVIEW_PACKETS_PERSISTED",
    "COMPLETED",
)
LOCK_NAME = "TRACK_B_PACKET_GENERATION_ACCESS_CONSUMED_V1.json"


class PacketGenerationError(RuntimeError):
    pass


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_lock(path: Path, lock: Mapping[str, Any], *, exclusive: bool = False) -> None:
    payload = canonical_json_bytes(lock)
    if exclusive:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        temporary = path.with_name("." + path.name + ".tmp")
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def _case_bank_bytes(records: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row), pretty=False) for row in records)


def _safe_error_name(exc: Exception) -> str:
    return type(exc).__name__


def execute_one_shot_packet_generation(
    source_path: Path,
    output_dir: Path,
    *,
    execution_stage: str,
    expected_source_sha256: str,
    blind_key: bytes,
    contamination_references: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute once; D0 invokes this only on a temporary synthetic source."""

    if execution_stage == "RQ2-D0":
        # String-only rejection precedes every filesystem operation on the source.
        assert_d0_partition_allowed(source_path)
    elif execution_stage != "RQ2-D1_AUTHORISED":
        raise PacketGenerationError("unknown packet-generation stage")
    if execution_stage == "RQ2-D1_AUTHORISED":
        if os.environ.get("RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED") != "YES":
            raise PacketGenerationError("D1 access authority is absent")
        if source_path.name != TRACK_B_FILE_NAME:
            raise PacketGenerationError("authorised D1 source filename mismatch")
        if expected_source_sha256 != TRACK_B_SHA256:
            raise PacketGenerationError("authorised D1 source commitment mismatch")
        if contamination_references is None or set(contamination_references) != set(
            REFERENCE_PARTITIONS
        ):
            raise PacketGenerationError("complete D1 contamination references are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / LOCK_NAME
    if lock_path.exists():
        raise PacketGenerationError("one-shot packet generation already consumed; no retry")
    lock: dict[str, Any] = {
        "schema_version": "track-b-packet-generation-lock-v1",
        "state": "ARMED",
        "state_history": ["ARMED"],
        "raw_asset_open_count": 0,
        "raw_asset_read_count": 0,
        "retry_permitted": False,
        "persisted": False,
        "failure_lock_preserved": False,
        "post_completed_writes_permitted": False,
        "execution_stage": execution_stage,
    }
    _write_lock(lock_path, lock, exclusive=True)
    try:
        with source_path.open("rb") as handle:
            lock["raw_asset_open_count"] = 1
            raw = handle.read()
            lock["raw_asset_read_count"] = 1
        lock["state"] = "OPENED"
        lock["state_history"].append("OPENED")
        lock["raw_asset_sha256"] = sha256_bytes(raw)
        lock["raw_asset_size_bytes"] = len(raw)
        _write_lock(lock_path, lock)
        mode = "SYNTHETIC_D0" if execution_stage == "RQ2-D0" else "D1_AUTHORISED_RAW"
        records, schema_report = parse_track_b_csv_bytes(
            raw,
            mode=mode,
            expected_synthetic_sha256=(
                expected_source_sha256 if mode == "SYNTHETIC_D0" else None
            ),
        )
        contamination = audit_contamination(records, contamination_references or {})
        case_bank = _case_bank_bytes(records)
        case_bank_path = output_dir / "track_b_canonical_case_bank_v1.jsonl"
        _atomic_write(case_bank_path, case_bank)
        if sha256_bytes(case_bank_path.read_bytes()) != sha256_bytes(case_bank):
            raise PacketGenerationError("case bank persistence verification failed")
        lock["state"] = "CASE_BANK_PERSISTED"
        lock["state_history"].append("CASE_BANK_PERSISTED")
        lock["case_bank_sha256"] = sha256_bytes(case_bank)
        lock["case_bank_record_count"] = len(records)
        _write_lock(lock_path, lock)
        packet_a, packet_b, manifest, mapping = build_blinded_packets(
            records, blind_key=blind_key
        )
        paths = {
            "reviewer_a": output_dir / "reviewer_a_track_b_capability_review_v1.csv",
            "reviewer_b": output_dir / "reviewer_b_track_b_capability_review_v1.csv",
            "packet_manifest": output_dir / "track_b_packet_manifest_v1.json",
            "opaque_mapping": output_dir / "track_b_opaque_mapping_v1.json",
        }
        payloads = {
            "reviewer_a": packet_a,
            "reviewer_b": packet_b,
            "packet_manifest": canonical_json_bytes(manifest),
            "opaque_mapping": canonical_json_bytes(mapping),
        }
        for role, path in paths.items():
            _atomic_write(path, payloads[role])
            if sha256_bytes(path.read_bytes()) != sha256_bytes(payloads[role]):
                raise PacketGenerationError("review packet persistence verification failed")
        lock["state"] = "REVIEW_PACKETS_PERSISTED"
        lock["state_history"].append("REVIEW_PACKETS_PERSISTED")
        lock["outputs"] = {
            role: {"sha256": sha256_bytes(payloads[role]), "size_bytes": len(payloads[role])}
            for role in sorted(payloads)
        }
        _write_lock(lock_path, lock)
        lock["state"] = "COMPLETED"
        lock["state_history"].append("COMPLETED")
        lock["persisted"] = True
        lock["schema_validation_status"] = schema_report["status"]
        lock["contamination_status"] = contamination["status"]
        lock["human_labels_formed"] = False
        _write_lock(lock_path, lock)
        return dict(lock)
    except Exception as exc:
        lock["failure_lock_preserved"] = True
        lock["failure_type"] = _safe_error_name(exc)
        lock["retry_permitted"] = False
        _write_lock(lock_path, lock)
        raise


def state_machine_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-packet-generation-state-machine-v1",
        "status": "FROZEN_SYNTHETICALLY_VALIDATED_BEFORE_D1",
        "state_order": list(STATE_ORDER),
        "completed_written_only_after_output_reverification": True,
        "raw_asset_open_count_required": 1,
        "raw_asset_read_count_required": 1,
        "retry_permitted": False,
        "failure_lock_preserved": True,
        "post_completed_writes_permitted": False,
        "d1_lock_distinct_from_future_evaluation_lock": True,
        "d1_explicit_environment_authority_required": (
            "RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED=YES"
        ),
        "d1_complete_contamination_reference_set_required_prearm": True,
        "d0_real_lock_created": False,
        "d0_real_packets_generated": False,
        "d1_outputs_local_only": [
            "canonical case bank",
            "Reviewer A packet",
            "Reviewer B packet",
            "packet manifest",
            "opaque ID mapping",
            "consumed-access lock",
        ],
    }
