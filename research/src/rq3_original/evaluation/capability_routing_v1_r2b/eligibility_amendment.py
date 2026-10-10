"""Versioned synthetic-only clarification eligibility amendment."""

from __future__ import annotations

from typing import Any, Mapping


SYNTHETIC_EXCEPTION_CONDITIONS = {
    "source_role": "synthetic",
    "case_validity": "INCLUDE_VALID_CASE",
    "capability_unambiguous": "YES",
    "context_sufficient": "NO",
    "context_resolution_required": "YES",
    "clarification": "YES",
    "dashboard_evidence": "NO",
    "course_retrieval": "NO",
    "episodic_memory": "NO",
    "planning": "NO",
    "safe_direct_response": "NO",
    "query_rewrite_performed": False,
    "assistant_context_attached": False,
}


def synthetic_clarification_exception_applies(row: Mapping[str, Any]) -> bool:
    return all(row.get(field) == value for field, value in SYNTHETIC_EXCEPTION_CONDITIONS.items())


def synthetic_clarification_eligibility_amendment() -> dict[str, Any]:
    return {
        "schema_version": "synthetic-clarification-eligibility-amendment-v1",
        "stage": "RQ2-A-R2B",
        "status": "AUTHORISED_PRE_GOLD_CONTRACT_AMENDMENT",
        "authority_basis": "USER_EXPLICIT_AUTHORISATION",
        "authorisation_date": "2026-08-26",
        "supersedes": {
            "contract": "human-adjudication-contract-v1.3",
            "field": "context_insufficient_capability_exact_set_gold_eligible",
            "scope": "FOR_SYNTHETIC_CLARIFICATION_CASES_ONLY",
        },
        "authentic_rule_changed": False,
        "synthetic_rule_changed": True,
        "synthetic_exception_required_conditions": dict(SYNTHETIC_EXCEPTION_CONDITIONS),
        "human_annotation_changed": False,
        "adjudication_changed": False,
        "capability_definition_changed": False,
        "coverage_threshold_changed": False,
        "model_output_used": False,
        "production_behavior_changed": False,
    }


def validate_eligibility_amendment(value: dict[str, Any]) -> None:
    if value != synthetic_clarification_eligibility_amendment():
        raise ValueError("BLOCKED_RQ2_A_R2B_ELIGIBILITY_AMENDMENT")
