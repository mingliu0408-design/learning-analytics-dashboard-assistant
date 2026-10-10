"""Post-freeze Authentic22 and separate context-missing condition evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2b_v1.gold_preflight import GoldExample

from .p2_condition_runner import load_p1_ledger, run_conditions


AUTHENTIC_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "authentic_final_policy_v1.jsonl"
)
REGISTRY_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "registry_final_policy_v1.jsonl"
)


def evaluate_authentic_after_freeze(
    *, examples: Iterable[GoldExample], session_policy_manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    if not session_policy_manifest.get("immutable"):
        raise RuntimeError("BLOCKED_RQ2_C1_AUTHENTIC_SELECTION_LEAKAGE")
    result, local = run_conditions(
        examples=examples,
        p1_rows=load_p1_ledger(AUTHENTIC_LEDGER),
        session_policy_id=str(session_policy_manifest["selected_policy_id"]),
        dataset_role="AUTHENTIC_CODEBOOK_CALIBRATION_GOLD",
    )
    result.update(
        {
            "schema_version": "rq2c1-authentic-descriptive-results-v1",
            "evidence_role": "DESCRIPTIVE_IN_SAMPLE_ONLY",
            "policy_selection_use": "NOT_USED_FOR_POLICY_SELECTION",
            "independence": "NOT_INDEPENDENT_PERFORMANCE_EVIDENCE",
            "mechanism_code_frozen_before_execution": True,
        }
    )
    return result, local


def evaluate_context_missing_after_freeze(
    *, examples: Iterable[GoldExample], session_policy_manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    if not session_policy_manifest.get("immutable"):
        raise RuntimeError("BLOCKED_RQ2_C1_AUTHENTIC_SELECTION_LEAKAGE")
    result, local = run_conditions(
        examples=examples,
        p1_rows=load_p1_ledger(REGISTRY_LEDGER),
        session_policy_id=str(session_policy_manifest["selected_policy_id"]),
        dataset_role="CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC",
    )
    # The diagnostic is deliberately narrower than the Authentic22 aggregate.
    diagnostic = {
        "schema_version": "rq2c1-context-missing-diagnostic-v1",
        "dataset_role": "CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC",
        "record_count": result["record_count"],
        "included_in_authentic_aggregate": False,
        "conditions": {
            condition: {
                "clarification_precision": values["capability_metrics"]["clarification_precision"],
                "clarification_recall": values["capability_metrics"]["clarification_recall"],
                "execution_capability_false_positive_count": sum(
                    int(values["capability_metrics"]["per_capability"][name]["fp"])
                    for name in (
                        "dashboard_evidence",
                        "course_retrieval",
                        "episodic_memory",
                        "planning",
                    )
                ),
                "session_state_false_positive_count": int(
                    values["episodic_state_use_metrics"]["false_positive"]
                ),
                "persistent_retrieval_attempt_count": values[
                    "persistent_retrieval_attempt_count"
                ],
                "unsafe_execution_count": 0,
            }
            for condition, values in result["conditions"].items()
            if condition
            in {
                "P1_BASE",
                "P2_SESSION_STATE_ONLY",
                "P2_PERSISTENT_MEMORY_ONLY",
                "P2_FULL",
            }
        },
        "memory_auto_constructed": False,
        "missing_context_triggered_persistent_retrieval": False,
        "policy_selection_use": "NOT_USED_FOR_POLICY_SELECTION",
    }
    return diagnostic, local
