"""Capability Gold Policy v1.1 and deterministic inclusion decisions."""

from __future__ import annotations

from typing import Any, Mapping

from . import GOLD_RELEVANT_FIELDS
from .eligibility_amendment import synthetic_clarification_exception_applies


AUTHENTIC_GOLD = "AUTHENTIC_CODEBOOK_CALIBRATION_GOLD"
AUTHENTIC_REGISTRY = "AUTHENTIC_CONTEXT_MISSING_QUALITATIVE_REGISTRY"
SYNTHETIC_GOLD = "SYNTHETIC_COVERAGE_STRESS_GOLD"
EXCLUDED = "EXCLUDED_FROM_CAPABILITY_DEVELOPMENT_GOLD"


def authentic_destination(row: Mapping[str, Any]) -> str:
    if row.get("context_sufficient") == "NO":
        return AUTHENTIC_REGISTRY
    if (
        row.get("case_validity") == "INCLUDE_VALID_CASE"
        and row.get("capability_unambiguous") == "YES"
    ):
        return AUTHENTIC_GOLD
    return EXCLUDED


def synthetic_destination(row: Mapping[str, Any]) -> str:
    default_eligible = (
        row.get("case_validity") == "INCLUDE_VALID_CASE"
        and row.get("capability_unambiguous") == "YES"
        and row.get("context_sufficient") != "NO"
    )
    if default_eligible or synthetic_clarification_exception_applies(row):
        return SYNTHETIC_GOLD
    return EXCLUDED


def capability_gold_policy_document() -> dict[str, Any]:
    return {
        "schema_version": "capability-gold-policy-v1.1",
        "stage": "RQ2-A-R2B",
        "status": "FROZEN_BEFORE_GOLD_BUILD",
        "human_decision_precedence": {
            "canonical_adjudication_present": "USE_ADJUDICATED_FINAL_FIELDS",
            "otherwise": "REQUIRE_REVIEWER_A_B_CONSENSUS",
            "gold_relevant_fields": list(GOLD_RELEVANT_FIELDS),
            "unresolved_disagreement_action": (
                "BLOCKED_RQ2_A_R2B_UNRESOLVED_HUMAN_DISAGREEMENT"
            ),
        },
        "naturalness_role": "HUMAN_REVIEW_QUALITY_DIAGNOSTIC_ONLY",
        "authentic_inclusion_rule": {
            "destination": AUTHENTIC_GOLD,
            "case_validity": "INCLUDE_VALID_CASE",
            "capability_unambiguous": "YES",
            "context_sufficient": "NOT_NO",
        },
        "authentic_context_missing_rule": {
            "when_context_sufficient": "NO",
            "destination": AUTHENTIC_REGISTRY,
            "eligible_for_capability_gold": False,
        },
        "synthetic_default_inclusion_rule": {
            "destination": SYNTHETIC_GOLD,
            "case_validity": "INCLUDE_VALID_CASE",
            "capability_unambiguous": "YES",
            "context_sufficient": "NOT_NO",
        },
        "synthetic_clarification_exception": {
            "authority": "synthetic-clarification-eligibility-amendment-v1",
            "applies_to_authentic": False,
            "destination": SYNTHETIC_GOLD,
        },
        "query_rewrite_authorised": False,
        "assistant_context_attachment_authorised": False,
        "model_output_may_form_gold": False,
        "coverage_threshold_changed": False,
        "capability_definition_changed": False,
    }
