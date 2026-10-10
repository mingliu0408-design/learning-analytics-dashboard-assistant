"""Frozen v1.1 human-review schema and closure validation."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Iterable, Mapping, Sequence

from . import PREDICTED_CAPABILITIES


VISIBLE_FIELDS = (
    "case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "turn_index",
    "source_dataset",
    "capability_definition_reference",
)
HUMAN_FIELDS = (
    "case_validity",
    "query_naturalness_1_to_5",
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
CONTEXT_SUFFICIENT_VALUES = ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN")
CAPABILITY_UNAMBIGUOUS_VALUES = ("YES", "NO", "UNCERTAIN")
BINARY_ANNOTATION_VALUES = ("YES", "NO")
NATURALNESS_VALUES = ("1", "2", "3", "4", "5")
REMOVED_REVIEW_DECISION = "ACCEPT_AS_PRESENTED"
DEFINITION_REFERENCE = (
    "docs/thesis_mainline/rq2/"
    "RQ2A_R1_HUMAN_REVIEW_AND_ADJUDICATION_PROTOCOL.md"
)


class HumanReviewSchemaError(ValueError):
    pass


def _value(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def validate_naturalness(value: Any, *, allow_blank: bool = False) -> int | None:
    text = str(value or "").strip()
    if not text and allow_blank:
        return None
    if text not in NATURALNESS_VALUES:
        raise HumanReviewSchemaError("query naturalness must be an integer from 1 to 5")
    return int(text)


def validate_forbidden_capabilities(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    values = tuple(item.strip() for item in text.split(";") if item.strip())
    if len(values) != len(set(values)) or not set(values) <= set(PREDICTED_CAPABILITIES):
        raise HumanReviewSchemaError("forbidden capabilities are invalid")
    return values


def validate_blank_packet(rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        if any(_value(row, field) for field in HUMAN_FIELDS):
            raise HumanReviewSchemaError("new reviewer packet contains a filled human field")
        if "review_decision" in row or any(
            _value(row, field) == REMOVED_REVIEW_DECISION for field in row
        ):
            raise HumanReviewSchemaError("obsolete ACCEPT_AS_PRESENTED contract is present")


def validate_annotation_row(
    row: Mapping[str, Any], *, allow_all_blank: bool = False
) -> None:
    if allow_all_blank and not any(_value(row, field) for field in HUMAN_FIELDS):
        return
    validity = _value(row, "case_validity")
    if validity not in CASE_VALIDITY_VALUES:
        raise HumanReviewSchemaError("case_validity is invalid")
    validate_naturalness(_value(row, "query_naturalness_1_to_5"))
    if _value(row, "context_sufficient") not in CONTEXT_SUFFICIENT_VALUES:
        raise HumanReviewSchemaError("context_sufficient is invalid")
    if _value(row, "capability_unambiguous") not in CAPABILITY_UNAMBIGUOUS_VALUES:
        raise HumanReviewSchemaError("capability_unambiguous is invalid")

    annotation_fields = ("context_resolution_required", *PREDICTED_CAPABILITIES)
    annotations = [_value(row, field) for field in annotation_fields]
    if validity == "INCLUDE_VALID_CASE":
        if any(value not in BINARY_ANNOTATION_VALUES for value in annotations):
            raise HumanReviewSchemaError("valid cases require every binary annotation")
        active = {
            capability
            for capability in PREDICTED_CAPABILITIES
            if _value(row, capability) == "YES"
        }
        if not active:
            raise HumanReviewSchemaError("valid cases require at least one capability")
        if "clarification" in active and active != {"clarification"}:
            raise HumanReviewSchemaError("clarification must be exclusive")
        if "safe_direct_response" in active and active != {"safe_direct_response"}:
            raise HumanReviewSchemaError("safe direct response must be exclusive")
    else:
        if any(value and value not in BINARY_ANNOTATION_VALUES for value in annotations):
            raise HumanReviewSchemaError("optional binary annotation is invalid")
    forbidden = set(validate_forbidden_capabilities(_value(row, "forbidden_capabilities")))
    if validity == "INCLUDE_VALID_CASE" and active & forbidden:
        raise HumanReviewSchemaError("required and forbidden capabilities overlap")
    if not _value(row, "reviewer_rationale"):
        raise HumanReviewSchemaError("reviewer rationale is required at closure")
    reviewer_id = _value(row, "reviewer_id")
    if not reviewer_id or re.search(r"\b(?:llm|codex|model|bot)\b", reviewer_id, re.I):
        raise HumanReviewSchemaError("reviewer_id must identify a human reviewer")
    try:
        date.fromisoformat(_value(row, "review_date"))
    except ValueError as exc:
        raise HumanReviewSchemaError("review_date must be ISO-8601") from exc


def validate_completed_packet(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        raise HumanReviewSchemaError("completed reviewer packet is empty")
    for row in rows:
        validate_annotation_row(row)
    reviewer_ids = {_value(row, "reviewer_id") for row in rows}
    if len(reviewer_ids) != 1:
        raise HumanReviewSchemaError("one packet must have exactly one reviewer_id")
    return next(iter(reviewer_ids))


def validate_independent_reviewer_ids(
    reviewer_a_rows: Sequence[Mapping[str, Any]],
    reviewer_b_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    reviewer_a = validate_completed_packet(reviewer_a_rows)
    reviewer_b = validate_completed_packet(reviewer_b_rows)
    if reviewer_a == reviewer_b:
        raise HumanReviewSchemaError("Reviewer A and Reviewer B must be different humans")
    return reviewer_a, reviewer_b


def human_review_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "human-review-schema-v1.1",
        "stage": "RQ2-A-R1",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "visible_fields": list(VISIBLE_FIELDS),
        "human_fields": list(HUMAN_FIELDS),
        "case_validity_values": list(CASE_VALIDITY_VALUES),
        "query_naturalness_values": [1, 2, 3, 4, 5],
        "context_sufficient_values": list(CONTEXT_SUFFICIENT_VALUES),
        "capability_unambiguous_values": list(CAPABILITY_UNAMBIGUOUS_VALUES),
        "binary_annotation_values": list(BINARY_ANNOTATION_VALUES),
        "capabilities": list(PREDICTED_CAPABILITIES),
        "forbidden_capabilities_delimiter": ";",
        "accept_as_presented_removed": True,
        "reviewers_independently_assign_capabilities": True,
        "required_human_reviewer_count": 2,
        "reviewer_ids_must_differ": True,
        "llm_may_substitute_required_human_reviewer": False,
        "discussion_before_both_packets_frozen": False,
        "other_reviewer_visible_during_round_one": False,
        "hidden_proposal_visible": False,
        "legacy_output_visible": False,
        "c0_scores_visible": False,
        "old_packet_answers_visible": False,
        "invalid_case_capability_fields_required": False,
        "invalid_case_rationale_required": True,
        "review_order": [
            "CASE_VALIDITY",
            "QUERY_NATURALNESS",
            "CONTEXT_SUFFICIENT",
            "CAPABILITY_UNAMBIGUOUS",
            "CONTEXT_RESOLUTION_REQUIRED",
            "SIX_CAPABILITIES",
            "FORBIDDEN_CAPABILITIES",
            "RATIONALE",
        ],
        "all_human_fields_initially_blank": True,
        "no_human_labels_filled_by_codex": True,
    }
