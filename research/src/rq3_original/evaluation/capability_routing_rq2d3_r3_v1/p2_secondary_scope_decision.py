"""Freeze P2 as explicitly deferred, not a zero-execution performance result."""

from __future__ import annotations


def p2_secondary_scope_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-p2-secondary-scope-decision-v1",
        "status": "DEFERRED_NOT_EXECUTED",
        "state_name": "SECONDARY_SCOPE_METADATA_PERSISTED",
        "superseded_state_name": "SECONDARY_DIAGNOSTICS_PERSISTED",
        "execution_count": 0,
        "performance_claims": False,
        "persistent_memory_executed": False,
        "rag_executed": False,
        "session_state_tool_use_executed": False,
        "persistent_retrieval_metric_present": False,
        "rag_sufficiency_metric_present": False,
        "reason": (
            "RQ2-D4 is the confirmatory B0/B1/P1 capability-routing evaluation; "
            "Track B lacks persistent-memory targets and chunk-level sufficiency truth."
        ),
        "deferred_stage": "RQ3_END_TO_END",
    }
