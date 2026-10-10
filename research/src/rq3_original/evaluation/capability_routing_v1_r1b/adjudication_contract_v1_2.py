"""Source-aware v1.2 adjudication and gold-role contracts."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_v1_r1.adjudication_contract import (
    ADJUDICATION_TRIGGERS as V11_TRIGGERS,
    adjudication_reasons as v11_adjudication_reasons,
    evaluate_coverage as evaluate_synthetic_coverage,
)

from . import PREDICTED_CAPABILITIES


ADJUDICATION_TRIGGERS = (
    *V11_TRIGGERS,
    "CONTEXT_LINK_VALID_DISAGREEMENT",
    "EITHER_REVIEWER_REJECTS_CONTEXT_LINK",
)
FORBIDDEN_RECORD_KEYS = {
    "query",
    "current_query",
    "original_query",
    "normalised_query",
    "resolved_query",
    "conversation_history",
    "rewritten_query",
}
CONTEXT_LINK_DISPOSITIONS = (
    "CONTINUE_AS_STANDALONE_QUERY",
    "EXCLUDE_CONTEXT_INSUFFICIENT",
)


class AdjudicationV12Error(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def adjudication_reasons(
    reviewer_a: Mapping[str, Any], reviewer_b: Mapping[str, Any]
) -> tuple[str, ...]:
    reasons = list(v11_adjudication_reasons(reviewer_a, reviewer_b))
    link_a = _text(reviewer_a, "context_link_valid")
    link_b = _text(reviewer_b, "context_link_valid")
    if link_a != link_b:
        reasons.append("CONTEXT_LINK_VALID_DISAGREEMENT")
    if "NO" in {link_a, link_b}:
        reasons.append("EITHER_REVIEWER_REJECTS_CONTEXT_LINK")
    if "UNCERTAIN" in {link_a, link_b} and "EITHER_REVIEWER_UNCERTAIN" not in reasons:
        reasons.append("EITHER_REVIEWER_UNCERTAIN")
    return tuple(dict.fromkeys(reasons))


def adjudication_required(
    reviewer_a: Mapping[str, Any], reviewer_b: Mapping[str, Any]
) -> bool:
    return bool(adjudication_reasons(reviewer_a, reviewer_b))


def validate_adjudication_record(
    record: Mapping[str, Any], *, expected_review_case_id: str
) -> None:
    if set(record) & FORBIDDEN_RECORD_KEYS:
        raise AdjudicationV12Error("query text or rewrite field is forbidden")
    if _text(record, "review_case_id") != expected_review_case_id:
        raise AdjudicationV12Error("adjudication cannot change review_case_id")
    if record.get("query_rewrite_performed") is not False:
        raise AdjudicationV12Error("adjudication cannot rewrite query")
    if not record.get("disagreement_reasons"):
        raise AdjudicationV12Error("disagreement reasons are required")
    if not _text(record, "adjudicator_id"):
        raise AdjudicationV12Error("adjudicator ID is required")
    try:
        date.fromisoformat(_text(record, "adjudication_date"))
    except ValueError as exc:
        raise AdjudicationV12Error("adjudication date must be ISO-8601") from exc
    if _text(record, "context_link_valid") == "NO" and _text(
        record, "context_link_disposition"
    ) not in CONTEXT_LINK_DISPOSITIONS:
        raise AdjudicationV12Error("rejected context link requires a disposition")


def final_gold_disposition(record: Mapping[str, Any], *, source_bank: str) -> str:
    if source_bank not in {"authentic", "synthetic"}:
        raise AdjudicationV12Error("unknown source bank")
    validity = _text(record, "case_validity")
    context = _text(record, "context_sufficient")
    unambiguous = _text(record, "capability_unambiguous")
    if "UNCERTAIN" in {validity, context, unambiguous, _text(record, "context_link_valid")}:
        raise AdjudicationV12Error("final adjudication must resolve uncertainty")
    if validity != "INCLUDE_VALID_CASE" or context == "NO" or unambiguous == "NO":
        return f"EXCLUDE_FROM_{source_bank.upper()}_GOLD"
    if _text(record, "context_link_valid") == "NO" and _text(
        record, "context_link_disposition"
    ) != "CONTINUE_AS_STANDALONE_QUERY":
        return f"EXCLUDE_FROM_{source_bank.upper()}_GOLD"
    return (
        "INCLUDE_IN_AUTHENTIC_CODEBOOK_CALIBRATION_GOLD"
        if source_bank == "authentic"
        else "INCLUDE_IN_SYNTHETIC_COVERAGE_STRESS_GOLD"
    )


def authentic_reporting_summary(
    included_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    capability_counts = Counter(
        capability
        for row in included_rows
        for capability in PREDICTED_CAPABILITIES
        if _text(row, capability) == "YES"
    )
    pages = Counter(_text(row, "current_page") for row in included_rows)
    return {
        "included_authentic_count": len(included_rows),
        "capability_positive_counts": {
            capability: capability_counts[capability]
            for capability in PREDICTED_CAPABILITIES
        },
        "context_link_confirmed_count": sum(
            _text(row, "context_link_valid") == "YES" for row in included_rows
        ),
        "multi_capability_count": sum(
            sum(_text(row, capability) == "YES" for capability in PREDICTED_CAPABILITIES)
            >= 2
            for row in included_rows
        ),
        "page_distribution": dict(sorted(pages.items())),
        "hard_coverage_gate": False,
    }


def human_adjudication_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "human-adjudication-contract-v1.2",
        "stage": "RQ2-A-R1B",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "adjudication_before_both_packets_frozen": False,
        "adjudication_triggers": list(ADJUDICATION_TRIGGERS),
        "context_link_no_dispositions": list(CONTEXT_LINK_DISPOSITIONS),
        "invalid_assistant_context_may_remain_in_capability_gold": False,
        "hidden_proposal_visible_before_final_human_decision": False,
        "hidden_proposal_use_after_gold_freeze": "ERROR_ANALYSIS_ONLY",
        "query_rewrite_during_adjudication": False,
        "rewrite_or_recombination_policy": {
            "current_case_disposition": "EXCLUDE",
            "new_case_id_required": True,
            "new_independent_two_reviewer_round_required": True,
            "direct_addition_to_current_gold": False,
        },
        "gold_roles": {
            "authentic": "AUTHENTIC_CODEBOOK_CALIBRATION_GOLD",
            "synthetic": "SYNTHETIC_COVERAGE_STRESS_GOLD",
            "merged_source_erasing_gold_allowed": False,
        },
        "threshold_rules": {
            "authentic_threshold_selection_eligible": False,
            "synthetic_controlled_threshold_development_eligible": True,
            "track_b_only_contextual_final_heldout": True,
        },
        "synthetic_coverage_gate": {
            "included_synthetic_cases_minimum": 20,
            "each_capability_positive_minimum": 2,
            "context_resolution_positive_minimum": 4,
            "multi_capability_cases_minimum": 4,
            "clarification_positive_minimum": 2,
            "safe_direct_response_positive_minimum": 2,
            "failure_status": "BLOCKED_RQ2_A_R2_CALIBRATION_COVERAGE",
        },
        "authentic_reporting_requirements": [
            "INCLUDED_AUTHENTIC_COUNT",
            "EACH_CAPABILITY_POSITIVE_COUNT",
            "CONTEXT_LINK_CONFIRMED_COUNT",
            "MULTI_CAPABILITY_COUNT",
            "PAGE_DISTRIBUTION",
        ],
        "authentic_hard_coverage_gate": False,
        "authentic_query_rewrite_for_coverage": False,
        "synthetic_coverage_calculator": evaluate_synthetic_coverage.__name__,
    }
