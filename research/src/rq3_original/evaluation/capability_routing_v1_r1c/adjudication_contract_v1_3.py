"""v1.3 missing-context adjudication and immutable query boundaries."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from evaluation.capability_routing_v1_r1.adjudication_contract import (
    ADJUDICATION_TRIGGERS as V11_TRIGGERS,
    adjudication_reasons as v11_adjudication_reasons,
)


ADJUDICATION_TRIGGERS = (
    *V11_TRIGGERS,
    "SYNTHETIC_CONTEXT_LINK_VALID_DISAGREEMENT",
    "SYNTHETIC_REVIEWER_REJECTS_CONTEXT_LINK",
    "AUTHENTIC_CONTEXT_INSUFFICIENT",
)
AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS = (
    "EXCLUDE_FROM_CAPABILITY_GOLD_BUT_RETAIN_AS_CONTEXT_MISSING_CASE",
    "INCLUDE_AS_STANDALONE_IF_QUERY_IS_SELF_CONTAINED",
)
FORBIDDEN_RECORD_KEYS = {
    "query",
    "current_query",
    "original_query",
    "normalised_query",
    "resolved_query",
    "rewritten_query",
    "conversation_history",
    "assistant_context",
    "guessed_context",
    "spliced_context",
}


class AdjudicationV13Error(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def adjudication_reasons(
    reviewer_a: Mapping[str, Any],
    reviewer_b: Mapping[str, Any],
    *,
    source_bank: str,
) -> tuple[str, ...]:
    if source_bank not in {"authentic", "synthetic"}:
        raise AdjudicationV13Error("unknown source bank")
    reasons = list(v11_adjudication_reasons(reviewer_a, reviewer_b))
    if source_bank == "authentic":
        if "NO" in {
            _text(reviewer_a, "context_sufficient"),
            _text(reviewer_b, "context_sufficient"),
        }:
            reasons.append("AUTHENTIC_CONTEXT_INSUFFICIENT")
    else:
        link_a = _text(reviewer_a, "context_link_valid")
        link_b = _text(reviewer_b, "context_link_valid")
        if link_a != link_b:
            reasons.append("SYNTHETIC_CONTEXT_LINK_VALID_DISAGREEMENT")
        if "NO" in {link_a, link_b}:
            reasons.append("SYNTHETIC_REVIEWER_REJECTS_CONTEXT_LINK")
    return tuple(dict.fromkeys(reasons))


def validate_adjudication_record(
    record: Mapping[str, Any],
    *,
    expected_review_case_id: str,
    source_bank: str,
) -> None:
    if set(record) & FORBIDDEN_RECORD_KEYS:
        raise AdjudicationV13Error("query/context reconstruction fields are forbidden")
    if _text(record, "review_case_id") != expected_review_case_id:
        raise AdjudicationV13Error("adjudication cannot change review_case_id")
    if record.get("query_rewrite_performed") is not False:
        raise AdjudicationV13Error("adjudication cannot rewrite query")
    if record.get("assistant_context_attached") is not False:
        raise AdjudicationV13Error("adjudication cannot attach assistant context")
    if not record.get("disagreement_reasons"):
        raise AdjudicationV13Error("disagreement reasons are required")
    if not _text(record, "adjudicator_id"):
        raise AdjudicationV13Error("adjudicator ID is required")
    try:
        date.fromisoformat(_text(record, "adjudication_date"))
    except ValueError as exc:
        raise AdjudicationV13Error("adjudication date must be ISO-8601") from exc
    if source_bank == "authentic" and _text(record, "context_sufficient") == "NO":
        if _text(record, "missing_context_disposition") not in (
            AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS
        ):
            raise AdjudicationV13Error("authentic missing context requires disposition")


def authentic_gold_disposition(record: Mapping[str, Any]) -> str:
    if _text(record, "context_sufficient") == "NO":
        disposition = _text(record, "missing_context_disposition")
        if disposition not in AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS:
            raise AdjudicationV13Error("missing-context disposition unresolved")
        return disposition
    if _text(record, "case_validity") != "INCLUDE_VALID_CASE" or _text(
        record, "capability_unambiguous"
    ) == "NO":
        return "EXCLUDE_FROM_AUTHENTIC_CODEBOOK_CALIBRATION_GOLD"
    return "INCLUDE_IN_AUTHENTIC_CODEBOOK_CALIBRATION_GOLD"


def human_adjudication_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "human-adjudication-contract-v1.3",
        "stage": "RQ2-A-R1C",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "adjudication_before_both_packets_frozen": False,
        "adjudication_triggers": list(ADJUDICATION_TRIGGERS),
        "authentic_context_sufficient_no_requires_adjudication": True,
        "authentic_missing_context_dispositions": list(
            AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS
        ),
        "assistant_context_attachment_authorised": False,
        "query_rewrite_authorised": False,
        "real_prior_context_guessing_authorised": False,
        "cross_case_context_splicing_authorised": False,
        "context_insufficient_capability_exact_set_gold_eligible": False,
        "context_missing_qualitative_retention_allowed": True,
        "new_complete_query_policy": {
            "new_case_id_required": True,
            "new_independent_two_reviewer_round_required": True,
            "direct_addition_to_current_gold": False,
        },
        "hidden_proposal_visible_before_final_human_decision": False,
        "threshold_selection_from_authentic_cases_authorised": False,
    }
