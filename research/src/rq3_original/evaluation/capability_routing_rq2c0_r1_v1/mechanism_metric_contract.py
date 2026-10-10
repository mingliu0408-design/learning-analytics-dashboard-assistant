"""Frozen mechanism-level metrics for future controlled P2 evaluation."""

from __future__ import annotations

from typing import Any


def metric_contract() -> dict[str, Any]:
    return {
        "schema_version": "persistent-memory-metric-contract-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN_NOT_MEASURED",
        "memory_write": [
            "write_precision",
            "write_recall",
            "unsafe_write_rate",
            "sensitive_inference_write_count",
        ],
        "retrieval": [
            "recall_at_1",
            "recall_at_3",
            "mrr",
            "multi_hop_complete_retrieval_rate",
            "no_memory_abstention_accuracy",
        ],
        "admission": [
            "admission_precision",
            "admission_recall",
            "irrelevant_memory_admission_rate",
            "stale_admission_rate",
            "superseded_admission_rate",
            "cancelled_or_completed_admission_rate",
            "cross_student_violation_rate",
            "deleted_memory_violation_rate",
        ],
        "conflict_update": [
            "latest_correction_accuracy",
            "supersession_accuracy",
            "deletion_compliance",
            "state_projection_consistency",
        ],
        "end_to_end": [
            "episodic_memory_capability_precision",
            "episodic_memory_capability_recall",
            "safe_clarification_accuracy",
            "personalisation_evidence_coverage",
            "memory_token_overhead",
        ],
        "fixture_result_is_student_outcome_evidence": False,
        "educational_effectiveness_claim_authorised": False,
        "authentic_generalisation_claim_authorised": False,
    }
