"""Local-only hidden legacy metadata escrow contract and extractor."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import canonical_json_bytes


ESCROW_FILE_NAME = "track_b_hidden_legacy_metadata_v1.jsonl"
HIDDEN_LEGACY_FIELDS = (
    "scenario_id",
    "normalised_current_query",
    "history_turn_count",
    "history_required",
    "final_effective_task_intent",
    "final_semantic_label",
    "human_final_label",
    "final_expected_legacy_query_type",
    "final_expected_source_scope",
    "final_expected_authority_flags",
    "final_expected_hard_guard_triggered",
    "final_expected_source_scope_locked",
    "final_expected_hybrid_policy_class",
    "expected_hybrid_policy_class_scored",
    "expected_production_action",
    "scenario_category",
    "scenario_family_id",
    "contrast_set_id",
    "difficulty",
    "semantic_accuracy_denominator_eligible",
    "hybrid_evaluation_eligible",
    "threshold_selection_eligible",
    "primary_heldout_eligible",
    "review_decision",
    "review_method",
    "reviewed_dataset_version",
    "scenario_schema_version",
    "authoring_provenance",
    "authoring_notes_safe",
    "human_decision",
    "human_rationale",
    "human_final_source_scope",
    "human_final_context_requirement",
    "human_final_page_context",
    "human_naturalness",
    "human_unambiguity",
    "human_difficulty_confirmed",
    "human_independence_confirmed",
    "human_privacy_check",
    "human_revised_query",
    "human_revised_history",
    "human_revised_expected_fields",
    "reviewer_id",
    "review_timestamp",
    "review_status",
)


def build_legacy_escrow_rows(source_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        if not source.get("scenario_id"):
            raise ValueError("legacy escrow source lacks scenario identity")
        rows.append({field: source.get(field, "") for field in HIDDEN_LEGACY_FIELDS})
    if len(rows) != 48:
        raise ValueError("legacy escrow must contain 48 records")
    return rows


def escrow_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row), pretty=False) for row in rows)


def legacy_escrow_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-legacy-escrow-contract-v1",
        "status": "FROZEN_BEFORE_D1",
        "record_count": 48,
        "hidden_field_count": len(HIDDEN_LEGACY_FIELDS),
        "hidden_fields": list(HIDDEN_LEGACY_FIELDS),
        "local_only": True,
        "git_tracked": False,
        "review_zip_member": False,
        "immutable_after_d1_completed": True,
        "reviewer_packet_visibility": False,
        "pre_gold_access": {
            "codex": False,
            "reviewer": False,
            "adjudicator": False,
            "model": False,
        },
        "future_access_gate": "TRACK_B_CAPABILITY_GOLD_FROZEN=true",
        "post_gold_role": "LEGACY_DIAGNOSTIC_ONLY",
        "lock_binding": ["sha256", "size_bytes", "record_count"],
    }
