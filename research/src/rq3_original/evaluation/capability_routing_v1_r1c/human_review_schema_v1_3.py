"""Frozen source-blinded v1.3 human-review schema."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Iterable, Mapping, Sequence

from . import PREDICTED_CAPABILITIES


VISIBLE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "turn_index",
    "capability_definition_reference",
)
HUMAN_FIELDS = (
    "case_validity",
    "query_naturalness_1_to_5",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
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
NATURALNESS_VALUES = ("1", "2", "3", "4", "5")
DEFINITION_REFERENCE = (
    "docs/thesis_mainline/rq2/RQ2A_R1C_HUMAN_REVIEW_PROTOCOL_V1_3.md"
)


class HumanReviewSchemaV13Error(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def has_displayed_history(row: Mapping[str, Any]) -> bool:
    return _text(row, "necessary_conversation_history") not in {"", "[]"}


def validate_naturalness(value: Any, *, allow_blank: bool = False) -> int | None:
    text = str(value or "").strip()
    if not text and allow_blank:
        return None
    if text not in NATURALNESS_VALUES:
        raise HumanReviewSchemaV13Error("naturalness must be an integer from 1 to 5")
    return int(text)


def validate_forbidden_capabilities(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    values = tuple(item.strip() for item in text.split(";") if item.strip())
    if len(values) != len(set(values)) or not set(values) <= set(PREDICTED_CAPABILITIES):
        raise HumanReviewSchemaV13Error("forbidden capabilities are invalid")
    return values


def validate_blank_packet(rows: Iterable[Mapping[str, Any]]) -> None:
    forbidden_visible = {
        "source_dataset",
        "source_bank",
        "canonical_case_id",
        "authentic_student_origin",
        "overlap_status",
        "legacy_prediction",
        "c0_score",
        "intent_proposal",
        "capability_proposal",
    }
    for row in rows:
        if tuple(row.keys()) != (*VISIBLE_FIELDS, *HUMAN_FIELDS):
            raise HumanReviewSchemaV13Error("review packet field order mismatch")
        if any(_text(row, field) for field in HUMAN_FIELDS):
            raise HumanReviewSchemaV13Error("review packet contains a filled human field")
        if forbidden_visible & set(row):
            raise HumanReviewSchemaV13Error("packet leaks hidden source/model data")


def validate_annotation_row(
    row: Mapping[str, Any], *, allow_all_blank: bool = False
) -> None:
    if allow_all_blank and not any(_text(row, field) for field in HUMAN_FIELDS):
        return
    validity = _text(row, "case_validity")
    if validity not in CASE_VALIDITY_VALUES:
        raise HumanReviewSchemaV13Error("case_validity is invalid")
    validate_naturalness(row.get("query_naturalness_1_to_5"))
    link = _text(row, "context_link_valid")
    sufficient = _text(row, "context_sufficient")
    resolution = _text(row, "context_resolution_required")
    if link not in CONTEXT_LINK_VALUES:
        raise HumanReviewSchemaV13Error("context_link_valid is invalid")
    if sufficient not in CONTEXT_SUFFICIENT_VALUES:
        raise HumanReviewSchemaV13Error("context_sufficient is invalid")
    if has_displayed_history(row):
        if link == "NOT_APPLICABLE":
            raise HumanReviewSchemaV13Error("displayed history requires link judgement")
    else:
        if link != "NOT_APPLICABLE":
            raise HumanReviewSchemaV13Error("no-history case requires NOT_APPLICABLE link")
        if sufficient not in {"NOT_APPLICABLE", "NO"}:
            raise HumanReviewSchemaV13Error(
                "no-history context sufficiency must be NOT_APPLICABLE or NO"
            )
        if sufficient == "NO" and resolution != "YES":
            raise HumanReviewSchemaV13Error(
                "missing-context case requires context resolution"
            )
    if _text(row, "capability_unambiguous") not in CAPABILITY_UNAMBIGUOUS_VALUES:
        raise HumanReviewSchemaV13Error("capability_unambiguous is invalid")
    binary_fields = ("context_resolution_required", *PREDICTED_CAPABILITIES)
    values = [_text(row, field) for field in binary_fields]
    active: set[str] = set()
    if validity == "INCLUDE_VALID_CASE":
        if any(value not in BINARY_VALUES for value in values):
            raise HumanReviewSchemaV13Error("included cases require binary annotations")
        active = {
            capability
            for capability in PREDICTED_CAPABILITIES
            if _text(row, capability) == "YES"
        }
        if not active:
            raise HumanReviewSchemaV13Error("included case requires a capability")
        if "clarification" in active and active != {"clarification"}:
            raise HumanReviewSchemaV13Error("clarification must be exclusive")
        if "safe_direct_response" in active and active != {"safe_direct_response"}:
            raise HumanReviewSchemaV13Error("safe direct response must be exclusive")
    elif any(value and value not in BINARY_VALUES for value in values):
        raise HumanReviewSchemaV13Error("optional binary annotation is invalid")
    forbidden = set(validate_forbidden_capabilities(row.get("forbidden_capabilities")))
    if active & forbidden:
        raise HumanReviewSchemaV13Error("required and forbidden capabilities overlap")
    if not _text(row, "reviewer_rationale"):
        raise HumanReviewSchemaV13Error("reviewer rationale is required")
    reviewer_id = _text(row, "reviewer_id")
    if not reviewer_id or re.search(r"\b(?:llm|codex|model|bot)\b", reviewer_id, re.I):
        raise HumanReviewSchemaV13Error("reviewer_id must identify a human")
    try:
        date.fromisoformat(_text(row, "review_date"))
    except ValueError as exc:
        raise HumanReviewSchemaV13Error("review_date must be ISO-8601") from exc


def validate_completed_packet(rows: Sequence[Mapping[str, Any]]) -> str:
    if len(rows) != 60:
        raise HumanReviewSchemaV13Error("completed packet must contain 60 cases")
    for row in rows:
        validate_annotation_row(row)
    reviewer_ids = {_text(row, "reviewer_id") for row in rows}
    if len(reviewer_ids) != 1:
        raise HumanReviewSchemaV13Error("one packet must have one reviewer_id")
    return next(iter(reviewer_ids))


def validate_independent_reviewer_ids(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> tuple[str, str]:
    reviewer_a = validate_completed_packet(rows_a)
    reviewer_b = validate_completed_packet(rows_b)
    if reviewer_a == reviewer_b:
        raise HumanReviewSchemaV13Error("Reviewer A and Reviewer B must differ")
    return reviewer_a, reviewer_b


def human_review_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "human-review-schema-v1.3",
        "stage": "RQ2-A-R1C",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "visible_fields": list(VISIBLE_FIELDS),
        "human_fields": list(HUMAN_FIELDS),
        "case_validity_values": list(CASE_VALIDITY_VALUES),
        "query_naturalness_values": [1, 2, 3, 4, 5],
        "context_link_valid_values": list(CONTEXT_LINK_VALUES),
        "context_sufficient_values": list(CONTEXT_SUFFICIENT_VALUES),
        "capability_unambiguous_values": list(CAPABILITY_UNAMBIGUOUS_VALUES),
        "binary_annotation_values": list(BINARY_VALUES),
        "capabilities": list(PREDICTED_CAPABILITIES),
        "required_human_reviewer_count": 2,
        "reviewer_ids_must_differ": True,
        "llm_may_substitute_required_human_reviewer": False,
        "source_identity_visible": False,
        "canonical_case_id_visible": False,
        "model_or_proposal_output_visible": False,
        "all_human_fields_initially_blank": True,
        "no_displayed_history_rule": {
            "self_contained_query": {
                "context_link_valid": "NOT_APPLICABLE",
                "context_sufficient": "NOT_APPLICABLE",
            },
            "missing_prior_context": {
                "context_link_valid": "NOT_APPLICABLE",
                "context_sufficient": "NO",
                "context_resolution_required": "YES",
            },
        },
        "displayed_history_link_values": ["YES", "NO", "UNCERTAIN"],
        "authentic_assistant_history_displayed": False,
    }
