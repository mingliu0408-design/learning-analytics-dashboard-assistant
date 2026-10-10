"""Frozen non-predictor P2 scope for Track-B final evaluation."""

from __future__ import annotations

from typing import Any


def p2_secondary_scope_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-p2-secondary-scope-v1",
        "status": "FROZEN",
        "p2_is_capability_predictor": False,
        "p2_modifies_p1_predictions": False,
        "allowed_diagnostics": [
            "RAG_CANDIDATE_AND_ATTEMPT",
            "SESSION_STATE_CANDIDATE_AND_USE",
            "CLARIFICATION_SAFETY",
            "EXECUTION_FALSE_POSITIVES",
        ],
        "TRACK_B_PERSISTENT_RETRIEVAL_EVALUABLE": False,
        "TRACK_B_RAG_SUFFICIENCY_ACCURACY_EVALUABLE": False,
        "session_policy": "M0_P1_ONLY",
        "persistent_component": "STRICT_NO_OP",
        "persistent_read_count": 0,
        "persistent_write_count": 0,
    }
