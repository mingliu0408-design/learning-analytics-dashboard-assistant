"""Provider-free RQ2-D0 contract build and synthetic harness validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from .blinded_packet_builder import build_blinded_packets, parse_packet_bytes
from .contamination_contract import ContaminationError, audit_contamination
from .packet_generation_state_machine import (
    LOCK_NAME,
    PacketGenerationError,
    execute_one_shot_packet_generation,
)
from .starting_state import verify_starting_state
from .synthetic_track_b_fixture import (
    build_synthetic_track_b_csv,
    synthetic_fixture_identity,
)
from .track_b_safe_authority import (
    install_governed_authority_copies,
    verify_safe_schema_package,
)
from .track_b_schema_contract import parse_track_b_csv_bytes


SYNTHETIC_BLIND_KEY = b"RQ2D0-SYNTHETIC-BLIND-KEY-V1"


@dataclass(frozen=True)
class RQ2D0Result:
    preflight: dict[str, Any]
    safe_authority: dict[str, Any]
    authority_copy: dict[str, Any]
    synthetic_validation: dict[str, Any]


def run_synthetic_validation() -> dict[str, Any]:
    raw_one = build_synthetic_track_b_csv()
    raw_two = build_synthetic_track_b_csv()
    if raw_one != raw_two:
        raise RuntimeError("BLOCKED_RQ2_D0_ONE_SHOT_HARNESS")
    fixture = synthetic_fixture_identity(raw_one)
    records, schema = parse_track_b_csv_bytes(
        raw_one,
        mode="SYNTHETIC_D0",
        expected_synthetic_sha256=fixture["sha256"],
    )
    packet_a_1, packet_b_1, manifest_1, mapping_1 = build_blinded_packets(
        records, blind_key=SYNTHETIC_BLIND_KEY
    )
    packet_a_2, packet_b_2, manifest_2, mapping_2 = build_blinded_packets(
        records, blind_key=SYNTHETIC_BLIND_KEY
    )
    if (packet_a_1, packet_b_1, manifest_1, mapping_1) != (
        packet_a_2,
        packet_b_2,
        manifest_2,
        mapping_2,
    ):
        raise RuntimeError("BLOCKED_RQ2_D0_ONE_SHOT_HARNESS")
    rows_a = parse_packet_bytes(packet_a_1)
    rows_b = parse_packet_bytes(packet_b_1)
    contamination_blocked = False
    try:
        audit_contamination(
            records,
            {
                "RQ1_TRAIN": [
                    {
                        "query": records[0]["effective_current_query"],
                        "history": records[0]["effective_conversation_history"],
                    }
                ]
            },
        )
    except ContaminationError:
        contamination_blocked = True
    if not contamination_blocked:
        raise RuntimeError("BLOCKED_RQ2_D0_ONE_SHOT_HARNESS")
    with tempfile.TemporaryDirectory(prefix="rq2d0-synthetic-") as temporary:
        root = Path(temporary)
        source = root / "synthetic_48.csv"
        output = root / "one_shot_outputs"
        source.write_bytes(raw_one)
        lock = execute_one_shot_packet_generation(
            source,
            output,
            execution_stage="RQ2-D0",
            expected_source_sha256=fixture["sha256"],
            blind_key=SYNTHETIC_BLIND_KEY,
        )
        lock_path = output / LOCK_NAME
        completed_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        retry_blocked = False
        try:
            execute_one_shot_packet_generation(
                source,
                output,
                execution_stage="RQ2-D0",
                expected_source_sha256=fixture["sha256"],
                blind_key=SYNTHETIC_BLIND_KEY,
            )
        except PacketGenerationError:
            retry_blocked = True
        no_post_completed_write = (
            completed_hash == hashlib.sha256(lock_path.read_bytes()).hexdigest()
        )
        persisted_names = sorted(path.name for path in output.iterdir())
        persisted_count = len(persisted_names)
    with tempfile.TemporaryDirectory(prefix="rq2d0-failure-") as temporary:
        root = Path(temporary)
        source = root / "synthetic_corrupt.csv"
        output = root / "failed_outputs"
        source.write_bytes(raw_one[:-2] + b"\n")
        failure_observed = False
        try:
            execute_one_shot_packet_generation(
                source,
                output,
                execution_stage="RQ2-D0",
                expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                blind_key=SYNTHETIC_BLIND_KEY,
            )
        except Exception:
            failure_observed = True
        failure_lock = json.loads((output / LOCK_NAME).read_text(encoding="utf-8"))
    hidden_keys = {
        "scenario_id",
        "raw_case_id",
        "normalised_current_query",
        "human_final_label",
        "scenario_family_id",
        "contrast_set_id",
        "model_output",
    }
    packet_keys = set(rows_a[0])
    if (
        lock["state"] != "COMPLETED"
        or lock["state_history"]
        != [
            "ARMED",
            "OPENED",
            "CASE_BANK_PERSISTED",
            "REVIEW_PACKETS_PERSISTED",
            "COMPLETED",
        ]
        or lock["raw_asset_open_count"] != 1
        or lock["raw_asset_read_count"] != 1
        or not retry_blocked
        or not no_post_completed_write
        or not failure_observed
        or not failure_lock.get("failure_lock_preserved")
        or hidden_keys & packet_keys
    ):
        raise RuntimeError("BLOCKED_RQ2_D0_ONE_SHOT_HARNESS")
    return {
        "schema_version": "rq2d0-synthetic-validation-v1",
        "status": "PASS",
        "fixture_identity": fixture,
        "schema_validation": {
            key: schema[key]
            for key in (
                "status",
                "record_count",
                "column_count",
                "encoding",
                "bom_hex",
                "newline",
                "final_crlf_present",
                "index_column_present",
                "ordered_id_commitment",
                "scenario_family_unique_count",
                "contrast_set_count",
                "session_id_present",
                "human_revised_query_override_count",
                "human_revised_history_override_count",
            )
        },
        "source_blinding": {
            "same_case_set": manifest_1["same_case_set"],
            "different_order": manifest_1["different_order"],
            "human_field_blank_count_per_packet": manifest_1[
                "human_field_blank_count_per_packet"
            ],
            "raw_scenario_id_visible": False,
            "existing_intent_visible": False,
            "model_outputs_visible": False,
            "automatic_proposal_visible": False,
        },
        "one_shot": {
            "state": lock["state"],
            "state_history": lock["state_history"],
            "raw_open_count": lock["raw_asset_open_count"],
            "raw_read_count": lock["raw_asset_read_count"],
            "outputs_persisted_and_reverified": lock["persisted"],
            "persisted_member_count": persisted_count,
            "retry_blocked": retry_blocked,
            "failure_lock_preserved": bool(failure_lock.get("failure_lock_preserved")),
            "no_post_completed_write": no_post_completed_write,
        },
        "contamination_conflict_blocked": contamination_blocked,
        "double_fixture_build_byte_identical": True,
        "double_packet_build_byte_identical": True,
        "real_track_b_access_count": 0,
        "real_lock_created": False,
        "real_packets_generated": False,
        "human_labels_formed": False,
    }


def run_rq2d0() -> RQ2D0Result:
    preflight = verify_starting_state()
    safe_authority, payloads = verify_safe_schema_package()
    authority_copy = install_governed_authority_copies(payloads)
    synthetic = run_synthetic_validation()
    return RQ2D0Result(
        preflight=preflight,
        safe_authority=safe_authority,
        authority_copy=authority_copy,
        synthetic_validation=synthetic,
    )


if __name__ == "__main__":
    result = run_rq2d0()
    print(
        json.dumps(
            {
                "status": result.synthetic_validation["status"],
                "safe_authority": result.safe_authority["status"],
                "real_track_b_access_count": 0,
            },
            sort_keys=True,
        )
    )
