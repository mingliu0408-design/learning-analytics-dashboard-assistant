"""Versioned future-D1 state machine with exact authority receipt binding.

The real and synthetic APIs are intentionally separate.  This module defines
future execution behaviour but performs no work on import.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from evaluation.capability_routing_rq2d0_v1.track_b_schema_contract import (
    parse_track_b_csv_bytes,
)
from evaluation.capability_routing_rq2d0_r1_v1 import (
    TRACK_B_FILE_NAME,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
)
from evaluation.capability_routing_rq2d0_r1_v1.blinding_key_governance import (
    KEY_FILE_NAME,
    generate_fresh_key,
    persist_key,
)
from evaluation.capability_routing_rq2d0_r1_v1.durable_atomic_persistence import (
    atomic_write_durable,
)
from evaluation.capability_routing_rq2d0_r1_v1.durable_contamination_receipt import (
    payload_receipt,
    verify_payload_receipt,
)
from evaluation.capability_routing_rq2d0_r1_v1.legacy_escrow_contract import (
    ESCROW_FILE_NAME,
    build_legacy_escrow_rows,
    escrow_jsonl_bytes,
)
from evaluation.capability_routing_rq2d0_r1_v1.packet_generation_state_machine_v1_1 import (
    _build_packets,
    _jsonl_bytes,
    _raw_source_rows,
)
from evaluation.capability_routing_rq2d0_r1_v1.prearm_output_guard import (
    assert_output_root_empty,
)

from . import ROOT, canonical_json_bytes, sha256_bytes
from .contamination_policy_v1_2 import (
    audit_hash_identities_v1_2,
    require_final_independence_v1_2,
    target_identity,
)
from .frozen_reference_authority import (
    FrozenContaminationReferenceAuthorityV1_1,
    load_frozen_contamination_reference_authority_v1_1,
)
from .track_b_grouping_identity import (
    grouping_hash_from_track_b_record,
    validate_track_b_contrast_groups,
)


STATE_ORDER = (
    "PREARM_VALIDATED",
    "KEY_PERSISTED",
    "ARMED",
    "OPENED",
    "CASE_BANK_PERSISTED",
    "LEGACY_ESCROW_PERSISTED",
    "CONTAMINATION_AUDIT_PERSISTED",
    "REVIEW_PACKETS_PERSISTED",
    "COMPLETED",
)
LOCK_NAME = "TRACK_B_PACKET_GENERATION_ACCESS_CONSUMED_V1_2.json"
AUTHORITY_RECEIPT_NAME = "track_b_reference_authority_receipt_v1_1.json"


class StateMachineV1_2Error(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _source_record_identity_hash(raw_id: str) -> str:
    return hashlib.sha256(
        b"RQ2_SOURCE_RECORD_IDENTITY_V1\x00" + raw_id.encode("utf-8")
    ).hexdigest()


def _advance(lock: dict[str, Any], state: str) -> None:
    index = len(lock["state_history"])
    if index >= len(STATE_ORDER) or STATE_ORDER[index] != state:
        raise StateMachineV1_2Error("illegal packet-generation state transition")
    lock["state"] = state
    lock["state_history"].append(state)


def _replace_lock(path: Path, lock: Mapping[str, Any]) -> None:
    atomic_write_durable(
        path, canonical_json_bytes(dict(lock)), mode=0o600, replace=path.exists()
    )


def _verify_schema_authority(schema_authority_sha256: str) -> None:
    authority_path = (
        ROOT
        / "evaluation/capability_routing_rq2d0_v1/track_b_schema_authority_v1.json"
    )
    if (
        not authority_path.is_file()
        or authority_path.is_symlink()
        or sha256_bytes(authority_path.read_bytes()) != schema_authority_sha256
    ):
        raise StateMachineV1_2Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")


def _verify_real_prearm_before_authority(
    source_path: Path,
    output_root: Path,
    *,
    approved_head: str,
    schema_authority_sha256: str,
) -> dict[str, Any]:
    if (
        os.environ.get("RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED") != "YES"
        or source_path.name != TRACK_B_FILE_NAME
        or _git("rev-parse", "HEAD") != approved_head
        or _git("status", "--porcelain=v1", "--untracked-files=all")
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise StateMachineV1_2Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")
    output_gate = assert_output_root_empty(output_root)
    _verify_schema_authority(schema_authority_sha256)
    return output_gate


def _receipt_matches(
    receipt: Mapping[str, Any],
    authority: FrozenContaminationReferenceAuthorityV1_1,
) -> bool:
    expected = authority.safe_receipt()
    return all(receipt.get(key) == value for key, value in expected.items())


def require_authority_receipt_match(
    receipt: Mapping[str, Any],
    authority: FrozenContaminationReferenceAuthorityV1_1,
) -> None:
    if not _receipt_matches(receipt, authority):
        raise StateMachineV1_2Error(
            "BLOCKED_RQ2_D0_R2_EXACT_REFERENCE_AUTHORITY"
        )


def _initial_lock(
    *,
    execution_mode: str,
    approved_head: str,
    schema_authority_sha256: str,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    output_root: Path,
    authority: FrozenContaminationReferenceAuthorityV1_1,
    output_gate: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "track-b-packet-generation-lock-v1.2",
        "state": "PREARM_VALIDATED",
        "state_history": ["PREARM_VALIDATED"],
        "raw_asset_open_count": 0,
        "raw_asset_read_count": 0,
        "retry_permitted": False,
        "persisted": False,
        "failure_lock_preserved": False,
        "post_completed_writes_permitted": False,
        "execution_mode": execution_mode,
        "approved_head": approved_head,
        "schema_authority_sha256": schema_authority_sha256,
        "expected_raw_sha256": expected_source_sha256,
        "expected_raw_size_bytes": expected_source_size_bytes,
        "expected_raw_record_count": 48,
        "output_root_identity": sha256_bytes(
            (execution_mode + "\x00" + output_root.name).encode("utf-8")
        ),
        "prearm_output_gate": output_gate["status"],
        **authority.safe_receipt(),
    }


def _execute_core(
    source_path: Path,
    output_root: Path,
    *,
    execution_mode: str,
    approved_head: str,
    schema_authority_sha256: str,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    authority: FrozenContaminationReferenceAuthorityV1_1,
    authority_reloader: Callable[[], FrozenContaminationReferenceAuthorityV1_1],
    output_gate: Mapping[str, Any],
    key: bytes,
) -> dict[str, Any]:
    lock = _initial_lock(
        execution_mode=execution_mode,
        approved_head=approved_head,
        schema_authority_sha256=schema_authority_sha256,
        expected_source_sha256=expected_source_sha256,
        expected_source_size_bytes=expected_source_size_bytes,
        output_root=output_root,
        authority=authority,
        output_gate=output_gate,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    key_receipt = persist_key(output_root / KEY_FILE_NAME, key)
    _advance(lock, "KEY_PERSISTED")
    lock["key_commitment"] = key_receipt["key_commitment"]
    lock["key_size_bytes"] = key_receipt["key_length_bytes"]
    lock["key_file_mode"] = key_receipt["file_mode_octal"]
    _advance(lock, "ARMED")
    lock_path = output_root / LOCK_NAME
    _replace_lock(lock_path, lock)

    try:
        with source_path.open("rb") as handle:
            lock["raw_asset_open_count"] = 1
            raw = handle.read()
            lock["raw_asset_read_count"] = 1
        if (
            sha256_bytes(raw) != expected_source_sha256
            or len(raw) != expected_source_size_bytes
        ):
            raise StateMachineV1_2Error("raw source identity mismatch")
        _advance(lock, "OPENED")
        lock["raw_asset_sha256"] = sha256_bytes(raw)
        lock["raw_asset_size_bytes"] = len(raw)
        _replace_lock(lock_path, lock)

        parser_mode = (
            "D1_AUTHORISED_RAW"
            if execution_mode == "D1_AUTHORISED_REAL_V1_2"
            else "SYNTHETIC_D0"
        )
        records, schema_report = parse_track_b_csv_bytes(
            raw,
            mode=parser_mode,
            expected_synthetic_sha256=(
                expected_source_sha256 if parser_mode == "SYNTHETIC_D0" else None
            ),
        )
        source_rows = _raw_source_rows(raw)
        if len(records) != 48 or len(source_rows) != 48:
            raise StateMachineV1_2Error("Track-B-shaped source count mismatch")
        grouping_report = validate_track_b_contrast_groups(records)

        payloads: dict[str, tuple[Path, bytes, int]] = {}
        authority_payload = canonical_json_bytes(
            {
                "schema_version": "track-b-reference-authority-receipt-v1.1",
                "status": "PASS",
                **authority.safe_receipt(),
                "reference_text_emitted": False,
            }
        )
        authority_path = output_root / AUTHORITY_RECEIPT_NAME
        atomic_write_durable(authority_path, authority_payload)
        payloads["contamination_reference_authority_receipt"] = (
            authority_path,
            authority_payload,
            authority.bundle_record_count,
        )

        case_bank = _jsonl_bytes(records)
        case_path = output_root / "track_b_canonical_case_bank_v1.jsonl"
        atomic_write_durable(case_path, case_bank)
        payloads["canonical_case_bank"] = (case_path, case_bank, 48)
        _advance(lock, "CASE_BANK_PERSISTED")
        _replace_lock(lock_path, lock)

        escrow = escrow_jsonl_bytes(build_legacy_escrow_rows(source_rows))
        escrow_path = output_root / ESCROW_FILE_NAME
        atomic_write_durable(escrow_path, escrow)
        payloads["hidden_legacy_escrow"] = (escrow_path, escrow, 48)
        _advance(lock, "LEGACY_ESCROW_PERSISTED")
        _replace_lock(lock_path, lock)

        track_identities = [
            target_identity(
                query=str(record["effective_current_query"]),
                history=record["effective_conversation_history"],
                source_record_identity_hash=_source_record_identity_hash(
                    str(record["raw_case_id"])
                ),
                family_or_group_hash=grouping_hash_from_track_b_record(record),
            )
            for record in records
        ]
        audit = audit_hash_identities_v1_2(
            track_identities, authority.reference_rows
        )
        audit.update(
            {
                "reference_authority_contract_id": authority.reference_contract_id,
                "reference_authority_commitment": authority.authority_commitment,
                "normaliser_contract_id": authority.normaliser_contract_id,
                "grouping_validation": grouping_report,
            }
        )
        audit_payload = canonical_json_bytes(audit)
        audit_path = output_root / "track_b_contamination_audit_summary_v1_2.json"
        atomic_write_durable(audit_path, audit_payload)
        payloads["contamination_audit_summary"] = (
            audit_path,
            audit_payload,
            48,
        )
        _advance(lock, "CONTAMINATION_AUDIT_PERSISTED")
        lock["hard_conflict_count"] = audit["hard_conflict_count"]
        lock["sensitivity_overlap_count"] = audit["sensitivity_overlap_count"]
        lock["contamination_status"] = audit["status"]
        _replace_lock(lock_path, lock)
        require_final_independence_v1_2(audit)

        packet_a, packet_b, packet_manifest_seed, mapping = _build_packets(
            records, key
        )
        packet_manifest = json.loads(packet_manifest_seed)
        packet_manifest.update(
            {
                "schema_version": "track-b-packet-manifest-v1.2",
                "key_commitment": lock["key_commitment"],
                "legacy_escrow_sha256": sha256_bytes(escrow),
                "contamination_audit_sha256": sha256_bytes(audit_payload),
                "reference_authority_receipt": authority.safe_receipt(),
            }
        )
        packet_manifest_payload = canonical_json_bytes(packet_manifest)
        packet_values = {
            "reviewer_a_packet": (
                output_root / "reviewer_a_track_b_capability_review_v1.csv",
                packet_a,
                48,
            ),
            "reviewer_b_packet": (
                output_root / "reviewer_b_track_b_capability_review_v1.csv",
                packet_b,
                48,
            ),
            "packet_manifest": (
                output_root / "track_b_packet_manifest_v1_2.json",
                packet_manifest_payload,
                48,
            ),
            "raw_to_blinded_mapping": (
                output_root / "track_b_opaque_mapping_v1.jsonl",
                mapping,
                48,
            ),
        }
        for role, (path, payload, _) in packet_values.items():
            atomic_write_durable(path, payload)
            payloads[role] = packet_values[role]
        _advance(lock, "REVIEW_PACKETS_PERSISTED")
        _replace_lock(lock_path, lock)

        receipts = {
            role: payload_receipt(payload, record_count=count)
            for role, (_, payload, count) in sorted(payloads.items())
        }
        for role, (path, _, _) in payloads.items():
            verify_payload_receipt(path, receipts[role])
        current_authority = authority_reloader()
        require_authority_receipt_match(lock, current_authority)
        require_authority_receipt_match(
            packet_manifest["reference_authority_receipt"], current_authority
        )

        _advance(lock, "COMPLETED")
        lock["persisted"] = True
        lock["schema_validation_status"] = schema_report["status"]
        lock["outputs"] = receipts
        lock["human_labels_formed"] = False
        _replace_lock(lock_path, lock)
        return dict(lock)
    except Exception as exc:
        lock["failure_lock_preserved"] = True
        lock["failure_type"] = type(exc).__name__
        lock["retry_permitted"] = False
        _replace_lock(lock_path, lock)
        raise


def execute_real_d1_one_shot_v1_2(
    source_path: Path,
    output_root: Path,
    *,
    approved_head: str,
    schema_authority_sha256: str,
) -> dict[str, Any]:
    """Future real D1 entry point; exact authority is always loaded internally."""

    output_gate = _verify_real_prearm_before_authority(
        source_path,
        output_root,
        approved_head=approved_head,
        schema_authority_sha256=schema_authority_sha256,
    )
    authority = load_frozen_contamination_reference_authority_v1_1()
    lock_path = output_root / LOCK_NAME
    if lock_path.exists() or lock_path.is_symlink():
        raise StateMachineV1_2Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")
    # Only after exact authority verification may a key be generated or persisted.
    key = generate_fresh_key()
    return _execute_core(
        source_path,
        output_root,
        execution_mode="D1_AUTHORISED_REAL_V1_2",
        approved_head=approved_head,
        schema_authority_sha256=schema_authority_sha256,
        expected_source_sha256=TRACK_B_SHA256,
        expected_source_size_bytes=TRACK_B_SIZE_BYTES,
        authority=authority,
        authority_reloader=load_frozen_contamination_reference_authority_v1_1,
        output_gate=output_gate,
        key=key,
    )


def execute_synthetic_d1_harness_v1_2(
    source_path: Path,
    output_root: Path,
    *,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    synthetic_reference_authority: FrozenContaminationReferenceAuthorityV1_1,
    synthetic_key: bytes,
    synthetic_authority_reloader: Callable[
        [], FrozenContaminationReferenceAuthorityV1_1
    ]
    | None = None,
) -> dict[str, Any]:
    """Wholly synthetic API; it cannot select or call the real D1 entry point."""

    output_gate = assert_output_root_empty(output_root)
    reloader = synthetic_authority_reloader or (lambda: synthetic_reference_authority)
    return _execute_core(
        source_path,
        output_root,
        execution_mode="SYNTHETIC_D0_R2_ONLY",
        approved_head="SYNTHETIC_ONLY",
        schema_authority_sha256="SYNTHETIC_ONLY",
        expected_source_sha256=expected_source_sha256,
        expected_source_size_bytes=expected_source_size_bytes,
        authority=synthetic_reference_authority,
        authority_reloader=reloader,
        output_gate=output_gate,
        key=synthetic_key,
    )


def verify_synthetic_completed_authority_receipt_v1_2(
    output_root: Path,
    synthetic_reference_authority: FrozenContaminationReferenceAuthorityV1_1,
) -> dict[str, Any]:
    lock = json.loads((output_root / LOCK_NAME).read_text(encoding="utf-8"))
    packet = json.loads(
        (output_root / "track_b_packet_manifest_v1_2.json").read_text(
            encoding="utf-8"
        )
    )
    if lock.get("state") != "COMPLETED":
        raise StateMachineV1_2Error("completed lock required")
    require_authority_receipt_match(lock, synthetic_reference_authority)
    require_authority_receipt_match(
        packet.get("reference_authority_receipt", {}),
        synthetic_reference_authority,
    )
    return {"status": "PASS", "authority_receipt_match": True}


def verify_real_completed_authority_receipt_v1_2(
    output_root: Path,
) -> dict[str, Any]:
    """Revalidate a completed real receipt against the fixed authority bytes."""

    lock = json.loads((output_root / LOCK_NAME).read_text(encoding="utf-8"))
    packet = json.loads(
        (output_root / "track_b_packet_manifest_v1_2.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        lock.get("state") != "COMPLETED"
        or lock.get("execution_mode") != "D1_AUTHORISED_REAL_V1_2"
    ):
        raise StateMachineV1_2Error("completed real D1 lock required")
    authority = load_frozen_contamination_reference_authority_v1_1()
    require_authority_receipt_match(lock, authority)
    require_authority_receipt_match(
        packet.get("reference_authority_receipt", {}), authority
    )
    return {"status": "PASS", "authority_receipt_match": True}


def state_machine_contract_document_v1_2() -> dict[str, Any]:
    return {
        "schema_version": "track-b-packet-generation-state-machine-v1.2",
        "status": "FROZEN_SYNTHETICALLY_VALIDATED_BEFORE_D1",
        "state_order": list(STATE_ORDER),
        "real_entry_point": "execute_real_d1_one_shot_v1_2",
        "real_entry_point_reference_injection_parameters": [],
        "synthetic_entry_point": "execute_synthetic_d1_harness_v1_2",
        "real_completed_receipt_verifier": (
            "verify_real_completed_authority_receipt_v1_2"
        ),
        "real_and_synthetic_api_separated": True,
        "unified_mode_switch_permitted": False,
        "prearm_order": [
            "approved HEAD, clean Git, explicit environment authority",
            "output root new-or-empty validation",
            "safe schema authority verification",
            "exact frozen contamination authority loading and verification",
            "authority commitment calculation",
            "no pre-existing real lock verification",
            "fresh 32-byte key generation",
            "key durable persistence",
            "KEY_PERSISTED",
            "ARMED lock",
            "raw Track B open",
        ],
        "authority_failure_key_generation_count": 0,
        "authority_failure_key_file_creation_count": 0,
        "authority_failure_real_lock_creation_count": 0,
        "authority_failure_raw_open_count": 0,
        "authority_failure_raw_read_count": 0,
        "armed_receipt_binds_exact_authority": True,
        "packet_manifest_repeats_exact_authority_receipt": True,
        "completed_lock_repeats_exact_authority_receipt": True,
        "authority_reverified_before_completed": True,
        "post_completed_authority_mutation_rejected": True,
        "retry_permitted": False,
        "d0_r2_raw_track_b_accessed": False,
        "d0_r2_real_key_created": False,
        "d0_r2_real_lock_created": False,
        "d0_r2_real_packets_created": False,
    }
