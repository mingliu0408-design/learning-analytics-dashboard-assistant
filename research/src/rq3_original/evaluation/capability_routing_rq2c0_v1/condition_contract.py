"""Frozen P2 condition matrix and mechanism metric contract."""

from __future__ import annotations

from typing import Any, Mapping


CONDITION_IDS = ("P1_BASE", "P2_RAG_ONLY", "P2_MEMORY_ONLY", "P2_FULL")


def condition_matrix() -> dict[str, Any]:
    return {
        "schema_version": "p2-condition-contract-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "conditions": {
            "P1_BASE": {"dual_gated_rag": False, "selective_memory_gate": False},
            "P2_RAG_ONLY": {"dual_gated_rag": True, "selective_memory_gate": False},
            "P2_MEMORY_ONLY": {"dual_gated_rag": False, "selective_memory_gate": True},
            "P2_FULL": {"dual_gated_rag": True, "selective_memory_gate": True},
        },
        "frozen_across_conditions": [
            "C0_COSINE",
            "P1_D05_SIGNAL_UNION",
            "CAPABILITY_GOLD",
            "CASE_SET",
            "CONTEXT_ENVELOPE_V1",
            "PRODUCTION_GUARDS",
        ],
        "p1_plan_immutable": True,
        "p1_vs_p2_full_only_comparison_permitted": False,
        "authentic_used_for_mechanism_selection": False,
        "track_b_used": False,
        "production_integration": False,
    }


def validate_condition_isolation(matrix: Mapping[str, Any]) -> bool:
    conditions = matrix.get("conditions") or {}
    return (
        set(conditions) == set(CONDITION_IDS)
        and conditions["P1_BASE"]
        == {"dual_gated_rag": False, "selective_memory_gate": False}
        and conditions["P2_RAG_ONLY"]
        == {"dual_gated_rag": True, "selective_memory_gate": False}
        and conditions["P2_MEMORY_ONLY"]
        == {"dual_gated_rag": False, "selective_memory_gate": True}
        and conditions["P2_FULL"]
        == {"dual_gated_rag": True, "selective_memory_gate": True}
    )


def metric_contract() -> dict[str, Any]:
    return {
        "schema_version": "p2-mechanism-metric-contract-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "capability_level": [
            "six_capability_macro_f1",
            "exact_set_accuracy",
            "required_capability_recall",
            "unnecessary_capability_rate",
            "set_jaccard",
        ],
        "rag_gate": [
            "retrieval_candidate_precision",
            "retrieval_candidate_recall",
            "retrieval_attempt_precision",
            "retrieval_attempt_recall",
            "unnecessary_retrieval_rate",
            "supported_evidence_admission_rate",
            "unsupported_evidence_admission_rate",
            "ambiguous_evidence_clarification_rate",
        ],
        "memory_gate": [
            "episodic_state_dependency_precision",
            "episodic_state_dependency_recall",
            "working_context_satisfaction_rate",
            "additional_retrieval_needed_recall",
            "unnecessary_state_use_rate",
            "stale_state_admission_rate",
            "superseded_state_admission_rate",
            "missing_context_unsafe_execution_rate",
        ],
        "safety": [
            "clarification_precision",
            "clarification_recall",
            "execution_capability_false_positives",
            "empty_plan_count",
            "source_restriction_violations",
            "forbidden_capability_violations",
        ],
        "working_context_counted_as_persistent_retrieval_success": False,
        "persistent_retrieval_claim_requires_explicit_target": True,
    }
