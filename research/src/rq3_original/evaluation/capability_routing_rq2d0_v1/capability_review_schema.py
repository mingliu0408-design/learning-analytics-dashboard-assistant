"""Frozen blank Track-B Capability-review schema using RQ2 v1.3 semantics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import CAPABILITIES


VISIBLE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "capability_definition_reference",
)
HUMAN_FIELDS = (
    "case_validity",
    "query_naturalness_1_to_5",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
    "reviewer_rationale",
    "reviewer_id",
    "review_date",
)
CASE_VALIDITY_VALUES = (
    "INCLUDE_VALID_CASE",
    "EXCLUDE_INVALID_CASE",
    "UNCERTAIN",
)
CONTEXT_LINK_VALUES = ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN")
CONTEXT_SUFFICIENT_VALUES = ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN")
CAPABILITY_UNAMBIGUOUS_VALUES = ("YES", "NO", "UNCERTAIN")
BINARY_VALUES = ("YES", "NO")
DEFINITION_REFERENCE = "docs/thesis_mainline/rq2/RQ2D0_TRACK_B_CAPABILITY_MAPPING_PROTOCOL.md"


class CapabilityReviewSchemaError(ValueError):
    pass


def validate_blank_packet(rows: Iterable[Mapping[str, Any]]) -> None:
    prohibited = {
        "scenario_id",
        "raw_case_id",
        "normalised_current_query",
        "human_final_label",
        "final_effective_task_intent",
        "source_scope",
        "scenario_family_id",
        "contrast_set_id",
        "difficulty",
        "legacy_prediction",
        "c0_score",
        "capability_proposal",
        "model_output",
    }
    expected = (*VISIBLE_FIELDS, *HUMAN_FIELDS)
    for row in rows:
        if tuple(row) != expected:
            raise CapabilityReviewSchemaError("review packet field order mismatch")
        if prohibited & set(row):
            raise CapabilityReviewSchemaError("review packet leaks hidden metadata")
        if any(str(row.get(field) or "").strip() for field in HUMAN_FIELDS):
            raise CapabilityReviewSchemaError("human field is not blank")
        if not str(row.get("review_case_id") or "").startswith("TBV1-"):
            raise CapabilityReviewSchemaError("review ID is not opaque")
        if not str(row.get("current_query") or "").strip():
            raise CapabilityReviewSchemaError("effective query is blank")
        if not str(row.get("necessary_conversation_history") or "").strip():
            raise CapabilityReviewSchemaError("effective history is blank")


def capability_review_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-capability-review-schema-v1",
        "inherits_annotation_semantics": "RQ2_HUMAN_REVIEW_SCHEMA_V1_3",
        "status": "FROZEN_BEFORE_TRACK_B_HUMAN_REVIEW",
        "visible_fields": list(VISIBLE_FIELDS),
        "human_fields": list(HUMAN_FIELDS),
        "case_validity_values": list(CASE_VALIDITY_VALUES),
        "query_naturalness_values": [1, 2, 3, 4, 5],
        "context_link_valid_values": list(CONTEXT_LINK_VALUES),
        "context_sufficient_values": list(CONTEXT_SUFFICIENT_VALUES),
        "capability_unambiguous_values": list(CAPABILITY_UNAMBIGUOUS_VALUES),
        "binary_values": list(BINARY_VALUES),
        "capabilities": list(CAPABILITIES),
        "required_human_reviewer_count": 2,
        "reviewer_ids_must_differ": True,
        "first_round_independent": True,
        "reviewers_must_not_view_each_other": True,
        "reviewers_must_not_view_intent_or_model_outputs": True,
        "reviewers_must_not_use_ai": True,
        "llm_may_substitute_required_reviewer": False,
        "third_human_adjudicator_required_for_all_disagreements": True,
        "all_48_cases_reviewed": True,
        "sampling_permitted": False,
        "all_human_fields_initially_blank": True,
        "existing_intent_labels_role": "DESCRIPTIVE_LEGACY_ANNOTATIONS_ONLY",
        "capability_labels_role": "NEW_MULTILABEL_EXECUTABLE_REQUIREMENTS",
        "intent_to_capability_map_may_form_gold": False,
        "intent_vs_capability_diagnostic_allowed_only_after_gold_freeze": True,
        "review_sequence": [
            "case_validity",
            "query_naturalness_1_to_5",
            "context_link_valid",
            "context_sufficient",
            "capability_unambiguous",
            "context_resolution_required",
            "six_capabilities",
            "forbidden_capabilities",
            "reviewer_rationale",
        ],
        "packet_generation_does_not_form_labels": True,
    }
