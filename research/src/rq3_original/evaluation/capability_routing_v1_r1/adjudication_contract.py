"""Adjudication triggers, final disposition, and calibration coverage gates."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Mapping, Sequence

from . import PREDICTED_CAPABILITIES
from .human_review_schema import validate_forbidden_capabilities


ADJUDICATION_TRIGGERS = (
    "CASE_VALIDITY_DISAGREEMENT",
    "EITHER_REVIEWER_EXCLUDES",
    "NATURALNESS_DIFFERENCE_AT_LEAST_TWO",
    "CONTEXT_SUFFICIENT_DISAGREEMENT",
    "CAPABILITY_UNAMBIGUOUS_DISAGREEMENT",
    "CONTEXT_RESOLUTION_DISAGREEMENT",
    "ANY_CAPABILITY_DISAGREEMENT",
    "FORBIDDEN_CAPABILITY_DISAGREEMENT",
    "EITHER_REVIEWER_UNCERTAIN",
)
FORBIDDEN_ADJUDICATION_KEYS = {
    "query",
    "current_query",
    "original_query",
    "normalised_query",
    "resolved_query",
    "conversation_history",
    "rewritten_query",
}


class AdjudicationContractError(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def adjudication_reasons(
    reviewer_a: Mapping[str, Any], reviewer_b: Mapping[str, Any]
) -> tuple[str, ...]:
    reasons: list[str] = []
    validity_a, validity_b = _text(reviewer_a, "case_validity"), _text(
        reviewer_b, "case_validity"
    )
    if validity_a != validity_b:
        reasons.append("CASE_VALIDITY_DISAGREEMENT")
    if "EXCLUDE_INVALID_CASE" in {validity_a, validity_b}:
        reasons.append("EITHER_REVIEWER_EXCLUDES")
    try:
        naturalness_difference = abs(
            int(_text(reviewer_a, "query_naturalness_1_to_5"))
            - int(_text(reviewer_b, "query_naturalness_1_to_5"))
        )
    except ValueError as exc:
        raise AdjudicationContractError("naturalness values are incomplete") from exc
    if naturalness_difference >= 2:
        reasons.append("NATURALNESS_DIFFERENCE_AT_LEAST_TWO")
    if _text(reviewer_a, "context_sufficient") != _text(
        reviewer_b, "context_sufficient"
    ):
        reasons.append("CONTEXT_SUFFICIENT_DISAGREEMENT")
    if _text(reviewer_a, "capability_unambiguous") != _text(
        reviewer_b, "capability_unambiguous"
    ):
        reasons.append("CAPABILITY_UNAMBIGUOUS_DISAGREEMENT")
    if _text(reviewer_a, "context_resolution_required") != _text(
        reviewer_b, "context_resolution_required"
    ):
        reasons.append("CONTEXT_RESOLUTION_DISAGREEMENT")
    if any(
        _text(reviewer_a, capability) != _text(reviewer_b, capability)
        for capability in PREDICTED_CAPABILITIES
    ):
        reasons.append("ANY_CAPABILITY_DISAGREEMENT")
    if set(validate_forbidden_capabilities(_text(reviewer_a, "forbidden_capabilities"))) != set(
        validate_forbidden_capabilities(_text(reviewer_b, "forbidden_capabilities"))
    ):
        reasons.append("FORBIDDEN_CAPABILITY_DISAGREEMENT")
    uncertain_fields = (
        "case_validity",
        "context_sufficient",
        "capability_unambiguous",
    )
    if any(
        _text(row, field) == "UNCERTAIN"
        for row in (reviewer_a, reviewer_b)
        for field in uncertain_fields
    ):
        reasons.append("EITHER_REVIEWER_UNCERTAIN")
    return tuple(dict.fromkeys(reasons))


def adjudication_required(
    reviewer_a: Mapping[str, Any], reviewer_b: Mapping[str, Any]
) -> bool:
    return bool(adjudication_reasons(reviewer_a, reviewer_b))


def validate_adjudication_record(
    record: Mapping[str, Any], *, expected_case_id: str
) -> None:
    if set(record) & FORBIDDEN_ADJUDICATION_KEYS:
        raise AdjudicationContractError("query text or rewrite field is forbidden")
    if _text(record, "case_id") != expected_case_id:
        raise AdjudicationContractError("adjudication cannot change case_id")
    if record.get("query_rewrite_performed") is not False:
        raise AdjudicationContractError("adjudication cannot rewrite query")
    if not record.get("disagreement_reasons"):
        raise AdjudicationContractError("disagreement reasons are required")
    if not _text(record, "adjudicator_id"):
        raise AdjudicationContractError("adjudicator ID is required")
    try:
        date.fromisoformat(_text(record, "adjudication_date"))
    except ValueError as exc:
        raise AdjudicationContractError("adjudication date must be ISO-8601") from exc


def final_gold_disposition(record: Mapping[str, Any]) -> str:
    validity = _text(record, "case_validity")
    context = _text(record, "context_sufficient")
    unambiguous = _text(record, "capability_unambiguous")
    if "UNCERTAIN" in {validity, context, unambiguous}:
        raise AdjudicationContractError("final adjudication must resolve uncertainty")
    if validity != "INCLUDE_VALID_CASE" or context == "NO" or unambiguous == "NO":
        return "EXCLUDE_FROM_SYNTHETIC_CALIBRATION_GOLD"
    if context not in {"YES", "NOT_APPLICABLE"} or unambiguous != "YES":
        raise AdjudicationContractError("final quality disposition is invalid")
    return "INCLUDE_IN_SYNTHETIC_CALIBRATION_GOLD"


def evaluate_coverage(included_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    capability_counts = Counter()
    context_positive = 0
    multi_capability = 0
    for row in included_rows:
        active = {
            capability
            for capability in PREDICTED_CAPABILITIES
            if _text(row, capability) == "YES"
        }
        capability_counts.update(active)
        context_positive += _text(row, "context_resolution_required") == "YES"
        multi_capability += len(active) >= 2
    deficits: dict[str, Any] = {}
    if len(included_rows) < 20:
        deficits["included_cases"] = {"observed": len(included_rows), "required": 20}
    for capability in PREDICTED_CAPABILITIES:
        if capability_counts[capability] < 2:
            deficits[f"capability:{capability}"] = {
                "observed": capability_counts[capability],
                "required": 2,
            }
    if context_positive < 4:
        deficits["context_resolution_required"] = {
            "observed": context_positive,
            "required": 4,
        }
    if multi_capability < 4:
        deficits["multi_capability_cases"] = {
            "observed": multi_capability,
            "required": 4,
        }
    return {
        "status": (
            "PASS" if not deficits else "BLOCKED_RQ2_A_R2_CALIBRATION_COVERAGE"
        ),
        "included_case_count": len(included_rows),
        "capability_positive_counts": {
            capability: capability_counts[capability]
            for capability in PREDICTED_CAPABILITIES
        },
        "context_resolution_positive_count": context_positive,
        "multi_capability_case_count": multi_capability,
        "deficits": deficits,
        "threshold_change_authorised": False,
        "automatic_supplemental_case_generation_authorised": False,
    }


def human_adjudication_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "human-adjudication-contract-v1",
        "stage": "RQ2-A-R1",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "adjudication_before_both_packets_frozen": False,
        "adjudication_triggers": list(ADJUDICATION_TRIGGERS),
        "required_adjudication_metadata": [
            "CASE_ID",
            "FINAL_DECISION_PER_ITEM",
            "DISAGREEMENT_REASONS",
            "ADJUDICATOR_ID",
            "ADJUDICATION_DATE",
        ],
        "hidden_proposal_visible_during_adjudication": False,
        "hidden_proposal_use_after_gold_freeze": "ERROR_ANALYSIS_ONLY",
        "query_rewrite_during_adjudication": False,
        "rewrite_required_policy": {
            "current_case_disposition": "EXCLUDE",
            "new_case_id_required": True,
            "new_independent_two_reviewer_round_required": True,
            "direct_addition_to_current_gold": False,
        },
        "final_gold_include_rule": {
            "case_validity": "INCLUDE_VALID_CASE",
            "context_sufficient_not": "NO",
            "capability_unambiguous_not": "NO",
            "uncertainty_must_be_resolved": True,
        },
        "final_gold_exclude_rule": [
            "ADJUDICATED_INVALID",
            "ADJUDICATED_CONTEXT_INSUFFICIENT",
            "ADJUDICATED_CAPABILITY_NOT_UNAMBIGUOUS",
            "UNRESOLVED_UNCERTAINTY",
        ],
        "rq2_a_r2_coverage_gates": {
            "included_cases_minimum": 20,
            "each_capability_positive_minimum": 2,
            "context_resolution_positive_minimum": 4,
            "multi_capability_cases_minimum": 4,
            "clarification_positive_minimum": 2,
            "safe_direct_response_positive_minimum": 2,
            "failure_status": "BLOCKED_RQ2_A_R2_CALIBRATION_COVERAGE",
        },
        "coverage_failure_threshold_change_authorised": False,
        "supplemental_cases_require_new_two_reviewer_round": True,
    }
