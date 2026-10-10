"""Executable synthetic proof of the repaired future-D1 durable lifecycle."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d0_v1.blinded_packet_builder import (
    REVIEWER_A_ORDER_SEED,
    REVIEWER_B_ORDER_SEED,
)
from evaluation.capability_routing_rq2d0_v1.capability_review_schema import (
    DEFINITION_REFERENCE,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_blank_packet,
)
from evaluation.capability_routing_rq2d0_v1.track_b_schema_contract import (
    parse_track_b_csv_bytes,
)

from . import (
    D0_HEAD,
    NORMALISER_CONTRACT_ID,
    ROOT,
    TRACK_B_FILE_NAME,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    canonical_json_bytes,
    sha256_bytes,
)
from .blinding_key_governance import (
    KEY_FILE_NAME,
    assert_real_mode_key_input,
    build_opaque_ids,
    generate_fresh_key,
    key_commitment,
    persist_key,
)
from .contamination_policy_v1_1 import (
    audit_hash_identities,
    require_final_independence,
    target_identity,
)
from .contamination_reference_builder import parse_bundle_bytes
from .contamination_reference_validator import validate_reference_bundle
from .durable_atomic_persistence import atomic_write_durable
from .durable_contamination_receipt import (
    payload_receipt,
    verify_payload_receipt,
)
from .legacy_escrow_contract import (
    ESCROW_FILE_NAME,
    build_legacy_escrow_rows,
    escrow_jsonl_bytes,
)
from .prearm_output_guard import assert_output_root_empty


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
LOCK_NAME = "TRACK_B_PACKET_GENERATION_ACCESS_CONSUMED_V1.json"


class StateMachineError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _verify_real_prearm(
    *, approved_head: str, schema_authority_sha256: str, expected_source_size_bytes: int
) -> None:
    authority_path = (
        ROOT
        / "evaluation/capability_routing_rq2d0_v1/track_b_schema_authority_v1.json"
    )
    if (
        _git("rev-parse", "HEAD") != approved_head
        or _git("status", "--porcelain=v1", "--untracked-files=all")
        or _git("remote")
        or _git("tag", "--list")
        or not authority_path.is_file()
        or authority_path.is_symlink()
        or sha256_bytes(authority_path.read_bytes()) != schema_authority_sha256
        or expected_source_size_bytes != TRACK_B_SIZE_BYTES
    ):
        raise StateMachineError("BLOCKED_RQ2_D1_PREARM_VALIDATION")


def _advance(lock: dict[str, Any], state: str) -> None:
    expected_index = len(lock["state_history"])
    if expected_index >= len(STATE_ORDER) or STATE_ORDER[expected_index] != state:
        raise StateMachineError("illegal packet-generation state transition")
    lock["state"] = state
    lock["state_history"].append(state)


def _replace_lock(path: Path, lock: Mapping[str, Any]) -> None:
    atomic_write_durable(
        path, canonical_json_bytes(dict(lock)), mode=0o600, replace=path.exists()
    )


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row), pretty=False) for row in rows)


def _raw_source_rows(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _packet_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[*VISIBLE_FIELDS, *HUMAN_FIELDS],
        extrasaction="raise",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def _build_packets(
    records: Sequence[Mapping[str, Any]], key: bytes
) -> tuple[bytes, bytes, bytes, bytes]:
    raw_ids = [str(row["raw_case_id"]) for row in records]
    review_ids = build_opaque_ids(raw_ids, key)
    source_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, str]] = []
    for record, review_id in zip(records, review_ids):
        history = json.dumps(
            record["effective_conversation_history"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        source_rows.append(
            {
                "review_case_id": review_id,
                "current_query": str(record["effective_current_query"]),
                "current_page": str(record["current_page"]),
                "necessary_conversation_history": history,
                "capability_definition_reference": DEFINITION_REFERENCE,
                **{field: "" for field in HUMAN_FIELDS},
            }
        )
        mapping_rows.append(
            {"review_case_id": review_id, "raw_scenario_id": str(record["raw_case_id"])}
        )
    rows_a = [dict(row) for row in source_rows]
    rows_b = [dict(row) for row in source_rows]
    random.Random(REVIEWER_A_ORDER_SEED).shuffle(rows_a)
    random.Random(REVIEWER_B_ORDER_SEED).shuffle(rows_b)
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    packet_a = _packet_csv(rows_a)
    packet_b = _packet_csv(rows_b)
    mapping = _jsonl_bytes(mapping_rows)
    manifest = canonical_json_bytes(
        {
            "schema_version": "track-b-packet-manifest-v1.1",
            "status": "PASS",
            "record_count": len(records),
            "reviewer_a_seed": REVIEWER_A_ORDER_SEED,
            "reviewer_b_seed": REVIEWER_B_ORDER_SEED,
            "reviewer_a_packet_sha256": sha256_bytes(packet_a),
            "reviewer_b_packet_sha256": sha256_bytes(packet_b),
            "mapping_sha256": sha256_bytes(mapping),
            "same_case_set": True,
            "different_order": [r["review_case_id"] for r in rows_a]
            != [r["review_case_id"] for r in rows_b],
            "all_human_fields_blank": True,
            "legacy_metadata_visible": False,
            "labels_formed": False,
        }
    )
    return packet_a, packet_b, manifest, mapping


def _source_identity_hash(raw_id: str) -> str:
    return hashlib.sha256(
        b"RQ2_SOURCE_RECORD_IDENTITY_V1\x00" + raw_id.encode("utf-8")
    ).hexdigest()


def _family_hash(value: str) -> str:
    return hashlib.sha256(
        b"RQ2_FAMILY_OR_GROUP_IDENTITY_V1\x00" + value.encode("utf-8")
    ).hexdigest()


def execute_one_shot_v1_1(
    source_path: Path,
    output_root: Path,
    *,
    mode: str,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    reference_bundle: bytes,
    reference_manifest: Mapping[str, Any],
    approved_head: str = D0_HEAD,
    schema_authority_sha256: str = "SYNTHETIC_SCHEMA_AUTHORITY",
    synthetic_key: bytes | None = None,
) -> dict[str, Any]:
    """Run only on synthetic input in D0-R1; real mode remains future-D1 gated."""

    validate_reference_bundle(reference_bundle, reference_manifest)
    output_gate = assert_output_root_empty(output_root)
    if mode == "D1_AUTHORISED":
        assert_real_mode_key_input(supplied_key=synthetic_key)
        if os.environ.get("RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED") != "YES":
            raise StateMachineError("explicit D1 authority is absent")
        if source_path.name != TRACK_B_FILE_NAME or expected_source_sha256 != TRACK_B_SHA256:
            raise StateMachineError("D1 raw identity mismatch")
        _verify_real_prearm(
            approved_head=approved_head,
            schema_authority_sha256=schema_authority_sha256,
            expected_source_size_bytes=expected_source_size_bytes,
        )
        key = generate_fresh_key()
    elif mode == "SYNTHETIC_D0_R1":
        key = synthetic_key if synthetic_key is not None else generate_fresh_key()
    else:
        raise StateMachineError("unknown packet-generation mode")
    lock: dict[str, Any] = {
        "schema_version": "track-b-packet-generation-lock-v1.1",
        "state": "PREARM_VALIDATED",
        "state_history": ["PREARM_VALIDATED"],
        "raw_asset_open_count": 0,
        "raw_asset_read_count": 0,
        "retry_permitted": False,
        "persisted": False,
        "failure_lock_preserved": False,
        "post_completed_writes_permitted": False,
        "execution_mode": mode,
        "approved_head": approved_head,
        "schema_authority_sha256": schema_authority_sha256,
        "expected_raw_sha256": expected_source_sha256,
        "expected_raw_size_bytes": expected_source_size_bytes,
        "expected_raw_record_count": 48,
        "reference_manifest_sha256": sha256_bytes(canonical_json_bytes(reference_manifest)),
        "reference_bundle_sha256": sha256_bytes(reference_bundle),
        "packet_seeds": [REVIEWER_A_ORDER_SEED, REVIEWER_B_ORDER_SEED],
        "output_root_identity": sha256_bytes(
            (
                str(output_root.absolute())
                if mode == "D1_AUTHORISED"
                else output_root.name
            ).encode("utf-8")
        ),
        "code_identity": sha256_bytes(Path(__file__).read_bytes()),
        "prearm_output_gate": output_gate["status"],
    }
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
            raise StateMachineError("raw source hash mismatch")
        _advance(lock, "OPENED")
        lock["raw_asset_sha256"] = sha256_bytes(raw)
        lock["raw_asset_size_bytes"] = len(raw)
        _replace_lock(lock_path, lock)
        parser_mode = "SYNTHETIC_D0" if mode == "SYNTHETIC_D0_R1" else "D1_AUTHORISED_RAW"
        records, schema_report = parse_track_b_csv_bytes(
            raw,
            mode=parser_mode,
            expected_synthetic_sha256=(
                expected_source_sha256 if parser_mode == "SYNTHETIC_D0" else None
            ),
        )
        source_rows = _raw_source_rows(raw)
        if len(records) != 48 or len(source_rows) != 48:
            raise StateMachineError("Track-B-shaped source count mismatch")

        payloads: dict[str, tuple[Path, bytes, int]] = {}
        reference_manifest_payload = canonical_json_bytes(reference_manifest)
        reference_manifest_path = (
            output_root / "track_b_contamination_reference_manifest_v1.json"
        )
        atomic_write_durable(reference_manifest_path, reference_manifest_payload)
        payloads["contamination_reference_manifest"] = (
            reference_manifest_path,
            reference_manifest_payload,
            int(reference_manifest["total_reference_records"]),
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
                source_record_identity_hash=_source_identity_hash(str(record["raw_case_id"])),
                family_or_group_hash=_family_hash(str(record["scenario_family_id"])),
            )
            for record in records
        ]
        audit = audit_hash_identities(track_identities, parse_bundle_bytes(reference_bundle))
        audit.update(
            {
                "reference_manifest_sha256": lock["reference_manifest_sha256"],
                "reference_bundle_sha256": lock["reference_bundle_sha256"],
                "normaliser_contract_id": NORMALISER_CONTRACT_ID,
            }
        )
        audit_payload = canonical_json_bytes(audit)
        audit_path = output_root / "track_b_contamination_audit_summary_v1.json"
        atomic_write_durable(audit_path, audit_payload)
        payloads["contamination_audit_summary"] = (audit_path, audit_payload, 48)
        _advance(lock, "CONTAMINATION_AUDIT_PERSISTED")
        audit_receipt = payload_receipt(audit_payload, record_count=48)
        lock["audit_summary_sha256"] = audit_receipt["sha256"]
        lock["audit_summary_size_bytes"] = audit_receipt["size_bytes"]
        lock["hard_conflict_count"] = audit["hard_conflict_count"]
        lock["sensitivity_overlap_count"] = audit["sensitivity_overlap_count"]
        lock["contamination_status"] = audit["status"]
        _replace_lock(lock_path, lock)
        require_final_independence(audit)

        packet_a, packet_b, packet_manifest_seed, mapping = _build_packets(records, key)
        seed_manifest = json.loads(packet_manifest_seed)
        seed_manifest.update(
            {
                "key_commitment": lock["key_commitment"],
                "legacy_escrow_sha256": sha256_bytes(escrow),
                "legacy_escrow_size_bytes": len(escrow),
                "legacy_escrow_record_count": 48,
                "contamination_audit_sha256": sha256_bytes(audit_payload),
                "contamination_audit_size_bytes": len(audit_payload),
                "reference_manifest_sha256": lock["reference_manifest_sha256"],
                "reference_bundle_sha256": lock["reference_bundle_sha256"],
            }
        )
        packet_manifest = canonical_json_bytes(seed_manifest)
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
                output_root / "track_b_packet_manifest_v1.json",
                packet_manifest,
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
        _advance(lock, "COMPLETED")
        lock["persisted"] = True
        lock["schema_validation_status"] = schema_report["status"]
        lock["outputs"] = receipts
        lock["audit_summary_sha256"] = receipts["contamination_audit_summary"]["sha256"]
        lock["audit_summary_size_bytes"] = receipts["contamination_audit_summary"][
            "size_bytes"
        ]
        lock["hard_conflict_count"] = audit["hard_conflict_count"]
        lock["sensitivity_overlap_count"] = audit["sensitivity_overlap_count"]
        lock["contamination_status"] = audit["status"]
        lock["human_labels_formed"] = False
        _replace_lock(lock_path, lock)
        return dict(lock)
    except Exception as exc:
        lock["failure_lock_preserved"] = True
        lock["failure_type"] = type(exc).__name__
        lock["retry_permitted"] = False
        _replace_lock(lock_path, lock)
        raise


def state_machine_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-packet-generation-state-machine-v1.1",
        "status": "FROZEN_SYNTHETICALLY_VALIDATED_BEFORE_D1",
        "state_order": list(STATE_ORDER),
        "prearm_requirements": [
            "approved HEAD",
            "clean worktree and index",
            "explicit D1 environment authority",
            "schema authority verified",
            "output directory absent or completely empty",
            "eight-partition reference bundle complete",
            "reference manifest verified",
            "no real lock exists",
        ],
        "key_persisted_before_armed": True,
        "raw_open_count_required": 1,
        "raw_read_count_required": 1,
        "escrow_persisted_before_packets": True,
        "contamination_audit_persisted_before_packets": True,
        "all_outputs_reverified_before_completed": True,
        "completed_lock_binds_sha_size_record_count": True,
        "retry_permitted": False,
        "failure_lock_preserved": True,
        "post_completed_write_permitted": False,
        "d0_r1_raw_track_b_accessed": False,
        "d0_r1_real_lock_created": False,
        "d0_r1_real_packets_created": False,
    }
