"""Five frozen P2 mechanism-isolation conditions for future offline work."""

from __future__ import annotations

from typing import Any, Mapping


CONDITION_IDS = (
    "P1_BASE",
    "P2_RAG_ONLY",
    "P2_SESSION_STATE_ONLY",
    "P2_PERSISTENT_MEMORY_ONLY",
    "P2_FULL",
)


def condition_contract() -> dict[str, Any]:
    return {
        "schema_version": "p2-condition-contract-v2",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN_NOT_EVALUATED",
        "conditions": {
            "P1_BASE": {
                "dual_gated_rag": False,
                "session_state_use": False,
                "persistent_memory_retrieval": False,
            },
            "P2_RAG_ONLY": {
                "dual_gated_rag": True,
                "session_state_use": False,
                "persistent_memory_retrieval": False,
            },
            "P2_SESSION_STATE_ONLY": {
                "dual_gated_rag": False,
                "session_state_use": True,
                "persistent_memory_retrieval": False,
            },
            "P2_PERSISTENT_MEMORY_ONLY": {
                "dual_gated_rag": False,
                "session_state_use": False,
                "persistent_memory_retrieval": True,
            },
            "P2_FULL": {
                "dual_gated_rag": True,
                "session_state_use": True,
                "persistent_memory_retrieval": True,
            },
        },
        "frozen_across_conditions": [
            "C0_COSINE",
            "P1_D05_SIGNAL_UNION",
            "PRODUCTION_GUARDS",
            "RQ2_P2_CONTROLLED_MECHANISM_FIXTURE_BANK_V1",
            "CAPABILITY_GOLD",
            "CONTEXT_ENVELOPE_V1",
        ],
        "condition_evaluation_executed": False,
        "production_integration": False,
    }


def validate_condition_isolation(value: Mapping[str, Any]) -> bool:
    conditions = value.get("conditions") or {}
    expected = condition_contract()["conditions"]
    return set(conditions) == set(CONDITION_IDS) and all(
        conditions[condition_id] == expected[condition_id]
        for condition_id in CONDITION_IDS
    )
