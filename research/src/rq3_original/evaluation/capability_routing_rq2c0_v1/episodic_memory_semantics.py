"""Frozen terminology and mechanism classification for RQ2-C0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MECHANISM_LABELS = (
    "SATISFIED_BY_WORKING_CONTEXT",
    "REQUIRES_ADDITIONAL_EPISODIC_RETRIEVAL",
    "MISSING_CONTEXT_REQUIRES_CLARIFICATION",
    "UNRESOLVED_MECHANISM_LABEL",
)


@dataclass(frozen=True)
class MechanismObservations:
    visible_history_present: bool
    working_state_object_present: bool
    context_missing: bool
    explicit_additional_retrieval_target: bool = False


def classify_mechanism(observation: MechanismObservations) -> str:
    """Classify evidence reachability without inspecting query text or case IDs."""

    if observation.visible_history_present and observation.working_state_object_present:
        return "SATISFIED_BY_WORKING_CONTEXT"
    if observation.explicit_additional_retrieval_target:
        return "REQUIRES_ADDITIONAL_EPISODIC_RETRIEVAL"
    if observation.context_missing and not observation.working_state_object_present:
        return "MISSING_CONTEXT_REQUIRES_CLARIFICATION"
    return "UNRESOLVED_MECHANISM_LABEL"


def semantics_contract() -> dict[str, Any]:
    return {
        "schema_version": "episodic-memory-semantics-contract-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "terms": {
            "WORKING_CONTEXT_AVAILABLE": {
                "definition": "Recent relevant turns or active structured state already entered ContextEnvelopeV1.",
                "predicted_capability": False,
                "persistent_retrieval_claim_allowed": False,
            },
            "EPISODIC_STATE_USE_REQUIRED": {
                "definition": "The answer must use a prior goal, plan, constraint, preference, completion, correction, or referenced item.",
                "current_gold_field": "episodic_memory",
            },
            "EPISODIC_RETRIEVAL_REQUIRED": {
                "definition": "Required state is absent from ContextEnvelopeV1 and must be fetched from additional earlier or persistent storage.",
                "current_gold_guarantees_label": False,
            },
            "MISSING_CONTEXT_CLARIFICATION_REQUIRED": {
                "definition": "The current turn depends on unavailable or unreliable prior state, so execution must stop for clarification.",
            },
        },
        "mechanism_labels": list(MECHANISM_LABELS),
        "prohibitions": [
            "DO_NOT_EQUATE_EPISODIC_MEMORY_GOLD_WITH_PERSISTENT_RETRIEVAL",
            "DO_NOT_COUNT_WORKING_CONTEXT_AS_PERSISTENT_RETRIEVAL_SUCCESS",
            "DO_NOT_INFER_LONG_TERM_MEMORY_PERFORMANCE",
            "DO_NOT_USE_QUERY_SPECIFIC_RULES",
        ],
    }
