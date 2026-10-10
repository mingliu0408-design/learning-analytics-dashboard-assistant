"""Unambiguous P1/session-state/persistent-memory P2 condition semantics."""

from __future__ import annotations

from typing import Any, Mapping


CONDITION_IDS = (
    "P1_BASE",
    "P2_RAG_ONLY",
    "P2_SESSION_STATE_ONLY",
    "P2_PERSISTENT_MEMORY_ONLY",
    "P2_FULL",
)


def condition_semantics_contract() -> dict[str, Any]:
    return {
        "schema_version": "p2-condition-semantics-v2-1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN_NOT_EVALUATED",
        "conditions": {
            "P1_BASE": {
                "context_envelope_for_capability_routing": True,
                "new_session_state_evidence_admission": False,
                "persistent_store_search": False,
                "dual_gated_rag": False,
            },
            "P2_RAG_ONLY": {
                "context_envelope_for_capability_routing": True,
                "new_session_state_evidence_admission": False,
                "persistent_store_search": False,
                "dual_gated_rag": True,
            },
            "P2_SESSION_STATE_ONLY": {
                "context_envelope_for_capability_routing": True,
                "new_session_state_evidence_admission": True,
                "session_state_relevance_and_freshness_gate": True,
                "persistent_store_search": False,
                "dual_gated_rag": False,
            },
            "P2_PERSISTENT_MEMORY_ONLY": {
                "context_envelope_for_capability_routing": True,
                "new_session_state_evidence_admission": False,
                "persistent_store_search": True,
                "persistent_policy": "PMR_HYBRID_STATE_AWARE",
                "dual_gated_rag": False,
            },
            "P2_FULL": {
                "context_envelope_for_capability_routing": True,
                "new_session_state_evidence_admission": True,
                "session_state_relevance_and_freshness_gate": True,
                "persistent_store_search": True,
                "persistent_policy": "PMR_HYBRID_STATE_AWARE",
                "dual_gated_rag": True,
            },
        },
        "mechanism_switches_independent": True,
        "same_c0": True,
        "same_p1_d05": True,
        "same_production_guards": True,
        "condition_evaluation_executed": False,
        "p2_implemented": False,
    }


def validate_condition_semantics(value: Mapping[str, Any]) -> bool:
    conditions = value.get("conditions") or {}
    expected = condition_semantics_contract()["conditions"]
    return set(conditions) == set(CONDITION_IDS) and all(
        conditions[condition_id] == expected[condition_id]
        for condition_id in CONDITION_IDS
    )
