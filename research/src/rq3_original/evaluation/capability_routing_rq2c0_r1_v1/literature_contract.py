"""Task-supplied literature synthesis invariants for PersistentLearnerMemoryV1."""

from __future__ import annotations

from typing import Any


MEMORY_LAYERS = (
    "WORKING_CONTEXT",
    "SESSION_STATE",
    "PERSISTENT_EPISODE",
    "PROFILE_PREFERENCE",
    "PLAN_PROGRESS",
)

ARCHITECTURE_INVARIANTS = (
    "LAYER_WORKING_SESSION_PERSISTENT_PROFILE_PLAN_STATE",
    "RAW_EPISODES_APPEND_ONLY",
    "ACTIVE_STATE_FROM_VERSIONED_PROJECTION",
    "KEYWORD_SIGNAL_NOT_SOLE_RETRIEVAL_BASIS",
    "DENSE_SIMILARITY_NOT_SOLE_RETRIEVAL_BASIS",
    "RETRIEVAL_COMBINES_SEMANTIC_ENTITY_TYPE_TIME_AND_STATUS",
    "LLM_SUMMARY_NOT_SOLE_FACT_SOURCE",
    "WRITE_REQUIRES_EXPLICIT_STATEMENT_OR_VERIFIED_EVENT",
    "NO_UNCONFIRMED_SENSITIVE_PERSONALITY_OR_ABILITY_INFERENCE",
    "LATEST_EXPLICIT_CORRECTION_WINS",
    "REJECT_STALE_SUPERSEDED_CANCELLED_DELETED_AND_CROSS_SCOPE",
)


def architecture_contract() -> dict[str, Any]:
    """Return the frozen synthesis without adding external claims or citations."""

    return {
        "schema_version": "persistent-memory-literature-contract-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "evidence_basis": "USER_SUPPLIED_LITERATURE_IDENTITIES_AND_SUMMARIES_ONLY",
        "network_literature_lookup": False,
        "external_claims_added": False,
        "layers": list(MEMORY_LAYERS),
        "layer_roles": {
            "WORKING_CONTEXT": "VISIBLE_RECENT_TURN_CONTEXT",
            "SESSION_STATE": "CURRENT_SESSION_GOAL_PLAN_CONSTRAINT_AND_REFERENCE_STATE",
            "PERSISTENT_EPISODE": "APPEND_ONLY_CROSS_SESSION_SOURCE_EPISODES",
            "PROFILE_PREFERENCE": "EXPLICIT_PREFERENCE_AND_CONSTRAINT_PROJECTION_ONLY",
            "PLAN_PROGRESS": "VERIFIED_PLAN_AND_COMPLETION_PROJECTION",
        },
        "invariants": list(ARCHITECTURE_INVARIANTS),
        "persistent_memory_is_complete_student_model": False,
        "educational_effectiveness_evaluated": False,
        "production_integration": False,
    }
