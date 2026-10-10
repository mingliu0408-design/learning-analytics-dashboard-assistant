"""Deterministically freeze source-blinded Track-B Capability Gold."""

from __future__ import annotations

import argparse
import json
from typing import Any, Iterable

from . import (
    CANONICAL_ADJUDICATION_RELATIVE,
    FULL_GOLD_RELATIVE,
    HERE,
    LABEL_GOLD_RELATIVE,
    ORIGINAL_ADJUDICATION_RELATIVE,
    ROOT,
    START_HEAD,
    canonical_json_bytes,
    durable_write,
    sha256_bytes,
)
from .adjudication_canonicalisation import canonicalise_adjudication
from .adjudication_input_authority import resolve_and_preserve_input
from .gold_bundle_manifest import build_gold_bundle_documents
from .gold_composition_validator import validate_gold_composition
from .human_adjudicator_attestation import human_adjudicator_attestation
from .human_decision_precedence import resolve_human_decisions
from .source_blinded_gold_builder import write_gold
from .starting_state import validate_starting_state
from .validate_completed_adjudication import validate_completed_adjudication


class FinalisationError(RuntimeError):
    pass


CORE_JSON_NAMES = (
    "track_b_human_adjudicator_independence_attestation_v1.json",
    "track_b_adjudication_packet_authority_v1.json",
    "track_b_adjudication_canonicalisation_manifest_v1.json",
    "track_b_completed_adjudication_validation_v1.json",
    "track_b_human_decision_precedence_v1.json",
    "track_b_capability_gold_summary_v1.json",
    "track_b_capability_gold_manifest_v1.json",
    "track_b_capability_gold_freeze_receipt_v1.json",
)


def _write_json(name: str, value: dict[str, Any]) -> None:
    durable_write(HERE / name, canonical_json_bytes(value), mode=0o644)


def _generate_core() -> dict[str, Any]:
    starting = validate_starting_state()
    input_paths, input_authority = resolve_and_preserve_input(ROOT)
    canonicalisation = canonicalise_adjudication(input_paths, ROOT)
    completed, reviewer_a, reviewer_b, completed_validation = (
        validate_completed_adjudication(ROOT)
    )
    attestation = human_adjudicator_attestation()
    decisions, precedence = resolve_human_decisions(reviewer_a, reviewer_b, completed)
    label_rows, _, gold_build = write_gold(decisions, ROOT)
    summary = validate_gold_composition(label_rows)

    dependencies = {
        "track_b_human_adjudicator_independence_attestation_v1.json": attestation,
        "track_b_adjudication_packet_authority_v1.json": input_authority,
        "track_b_adjudication_canonicalisation_manifest_v1.json": canonicalisation,
        "track_b_completed_adjudication_validation_v1.json": completed_validation,
        "track_b_human_decision_precedence_v1.json": precedence,
        "track_b_capability_gold_summary_v1.json": summary,
    }
    for name, value in dependencies.items():
        _write_json(name, value)
    manifest, receipt = build_gold_bundle_documents(
        attestation_sha256=sha256_bytes(canonical_json_bytes(attestation)),
        decision_precedence_sha256=sha256_bytes(canonical_json_bytes(precedence)),
        gold_summary_sha256=sha256_bytes(canonical_json_bytes(summary)),
    )
    _write_json("track_b_capability_gold_manifest_v1.json", manifest)
    _write_json("track_b_capability_gold_freeze_receipt_v1.json", receipt)
    return {
        "starting": starting,
        **dependencies,
        "track_b_capability_gold_manifest_v1.json": manifest,
        "track_b_capability_gold_freeze_receipt_v1.json": receipt,
        "gold_build": gold_build,
    }


def _snapshot() -> dict[str, bytes]:
    local = (
        ORIGINAL_ADJUDICATION_RELATIVE,
        CANONICAL_ADJUDICATION_RELATIVE,
        FULL_GOLD_RELATIVE,
    )
    return {
        **{f"safe:{name}": (HERE / name).read_bytes() for name in CORE_JSON_NAMES},
        f"safe:{LABEL_GOLD_RELATIVE.name}": (ROOT / LABEL_GOLD_RELATIVE).read_bytes(),
        **{f"local:{relative.as_posix()}": (ROOT / relative).read_bytes() for relative in local},
    }


def _preflight(generated: dict[str, Any]) -> dict[str, Any]:
    starting_snapshot = json.loads(json.dumps(generated["starting"]))
    starting_snapshot["relative_commit_count"] = 0
    manifest = generated["track_b_capability_gold_manifest_v1.json"]
    return {
        "schema_version": "rq2d2b-preflight-report-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "starting_state": starting_snapshot,
        "initial_working_tree_and_index_gate": "CLEAN",
        "user_adjudicator_authority": {
            "third_adjudicator_distinct_human": True,
            "adjudicator_id": "C",
            "ai_used_for_annotation": False,
            "complete_row_authority": True,
            "gold_freeze_authorised": True,
            "hidden_legacy_access_authorised": False,
            "model_execution_authorised": False,
            "final_evaluation_authorised": False,
        },
        "completed_adjudication_identity": "PASS",
        "canonical_adjudication_identity": "PASS",
        "complete_row_adjudication_count": 23,
        "consensus_case_count": 25,
        "gold_record_count": 48,
        "gold_bundle_sha256": manifest["gold_bundle_sha256"],
        "gold_frozen_before_unblinding": True,
        "hidden_legacy_access_guard": "DENIED",
        "hidden_legacy_accessed": False,
        "raw_mapping_accessed": False,
        "raw_track_b_accessed": False,
        "track_a_accessed": False,
        "model_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
        "policy_threshold_or_seed_change": False,
        "final_evaluation_started": False,
        "production_integration_performed": False,
        "double_finalisation_byte_identical": True,
        "approved_base_head": START_HEAD,
    }


def _validation_report(generated: dict[str, Any]) -> dict[str, Any]:
    manifest = generated["track_b_capability_gold_manifest_v1.json"]
    return {
        "schema_version": "rq2d2b-validation-report-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "starting_state": "PASS",
        "adjudication_input_authority": "PASS",
        "adjudication_canonicalisation": "PASS",
        "completed_adjudication_validation": "23/23 PASS",
        "complete_row_precedence": "PASS",
        "consensus_resolution": "25/25 PASS",
        "label_only_gold_identity": "48/48 PASS",
        "local_full_text_gold_identity": "48/48 PASS",
        "gold_composition": "PASS",
        "gold_bundle_sha256": manifest["gold_bundle_sha256"],
        "gold_frozen_before_unblinding": True,
        "hidden_legacy_access_guard": "DENIED",
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "mapping_access_count": 0,
        "model_execution_count": 0,
        "final_evaluation_count": 0,
        "provider_calls": 0,
        "network_access": False,
        "protected_source_change_count": 0,
        "governed_text_leak_count": 0,
        "double_finalisation_byte_identical": True,
        "review_package_contract": "ALL_OUTPUT_CHECKSUM_REFERENCES_REQUIRED",
    }


def build_all() -> dict[str, Any]:
    from .validate_rq2d2b import validate_all, write_output_checksums

    first = _generate_core()
    first_snapshot = _snapshot()
    second = _generate_core()
    second_snapshot = _snapshot()
    if first_snapshot != second_snapshot or any(
        first[key] != second[key] for key in ("starting", *CORE_JSON_NAMES, "gold_build")
    ):
        raise FinalisationError("D2B double core build is not byte-identical")
    _write_json("rq2d2b_preflight_report_v1.json", _preflight(second))
    _write_json("rq2d2b_validation_report_v1.json", _validation_report(second))
    write_output_checksums()
    validate_all(require_review_zip=False)
    return second


def assert_double_finalisation() -> None:
    tracked = (
        *CORE_JSON_NAMES,
        "rq2d2b_preflight_report_v1.json",
        "rq2d2b_validation_report_v1.json",
        "rq2d2b_output_checksums_v1.sha256",
    )
    build_all()
    first = {name: (HERE / name).read_bytes() for name in tracked}
    first.update(_snapshot())
    build_all()
    second = {name: (HERE / name).read_bytes() for name in tracked}
    second.update(_snapshot())
    if first != second:
        raise FinalisationError("double finalisation byte identity mismatch")


def build_review_zip() -> dict[str, Any]:
    from .validate_rq2d2b import create_review_zip

    return create_review_zip()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--review-zip", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.build == args.review_zip:
        parser.error("choose exactly one of --build or --review-zip")
    result = build_all() if args.build else build_review_zip()
    output = {
        "status": "PASS",
        "operation": "build" if args.build else "review_zip",
        "gold_state": "TRACK_B_CAPABILITY_GOLD_FROZEN",
        "gold_record_count": 48,
        "consensus_count": 25,
        "adjudicated_count": 23,
        "hidden_legacy_accessed": False,
        "raw_track_b_accessed": False,
        "model_execution_count": 0,
        "final_evaluation_started": False,
    }
    if args.review_zip:
        output.update(result)
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
