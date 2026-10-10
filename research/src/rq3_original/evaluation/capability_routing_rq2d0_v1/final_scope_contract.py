"""Frozen RQ2 Track-B primary and P2 secondary evaluation scope."""

from __future__ import annotations

from typing import Any

from . import (
    GOLD_BUNDLE_SHA256,
    P1_POLICY_ID,
    P1_POLICY_SHA256,
    ROOT,
    RQ1_ROUTER,
    sha256_file,
)


PRIMARY_PREDICTORS = (
    "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
    "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE",
    P1_POLICY_ID,
)
P2_CONDITIONS = (
    "P1_BASE",
    "P2_RAG_ONLY",
    "P2_SESSION_STATE_ONLY",
    "P2_PERSISTENT_MEMORY_ONLY",
    "P2_FULL_NO_PERSISTENT_TARGET",
)


def final_scope_contract_document() -> dict[str, Any]:
    implementation_paths = {
        "B0": "evaluation/capability_routing_rq2b_v1/b0_original_query_adapter.py",
        "B1": "evaluation/capability_routing_rq2b_v1/b1_reproduction_adapter.py",
        "C0_FULL_VECTOR": "evaluation/capability_routing_rq2b_v1/c0_full_score_vector.py",
        "P1": "evaluation/capability_routing_rq2b_v1/p1_capability_router.py",
        "DUAL_GATED_RAG": "evaluation/capability_routing_rq2c1_v1/offline_dual_gated_rag.py",
        "SESSION_STATE_GATE": "evaluation/capability_routing_rq2c1_v1/offline_session_state_gate.py",
        "CORRECTED_CONDITION_RUNNER": (
            "evaluation/capability_routing_rq2c1_r1_v1/p2_condition_runner_v1_1.py"
        ),
    }
    return {
        "schema_version": "rq2-final-scope-contract-v1",
        "status": "FROZEN_BEFORE_TRACK_B_GOLD_OR_MODEL_RESULTS",
        "source_alias": "TRACK_B_CONTEXTUAL_CAPABILITY_FINAL_SOURCE_V1",
        "capability_gold_required_before_evaluation": True,
        "existing_intent_labels_are_capability_gold": False,
        "all_48_cases_require_independent_human_mapping": True,
        "primary_capability_predictors": list(PRIMARY_PREDICTORS),
        "primary_comparisons": {
            "B1_MINUS_B0": "CURRENT_CONTEXT_RESOLUTION_CONTRIBUTION",
            "P1_MINUS_B1": "MULTILABEL_CAPABILITY_AGGREGATION_CONTRIBUTION",
            "P1_MINUS_B0": "COMPLETE_PROPOSED_ROUTING_CONTRIBUTION",
        },
        "primary_metric": "SIX_CAPABILITY_MACRO_F1",
        "secondary_metrics": [
            "Exact-Set Accuracy",
            "Micro Precision",
            "Micro Recall",
            "Micro F1",
            "Required-Capability Recall",
            "Unnecessary-Capability Rate",
            "Mean Set Jaccard",
            "Per-Capability Precision/Recall/F1",
            "Forbidden-Capability Violation Rate",
            "Context-Resolution Accuracy",
            "Context-Resolution Positive Recall",
            "Clarification Precision/Recall",
            "Unnecessary-Clarification Rate",
        ],
        "p2_is_capability_predictor": False,
        "p2_role": "SECONDARY_EXECUTION_DIAGNOSTIC_ONLY",
        "p2_conditions": list(P2_CONDITIONS),
        "p2_rag_diagnostics_after_gold": [
            "RAG candidate precision/recall",
            "actual retrieval-attempt precision/recall",
            "unnecessary retrieval rate",
            "clarification-blocked retrieval count",
        ],
        "p2_session_state_diagnostics_after_gold": [
            "session-state candidate precision/recall",
            "state-admission precision/recall",
            "unnecessary state-use rate",
            "missing-context unsafe-execution rate",
        ],
        "track_b_rag_sufficiency_accuracy_evaluable": False,
        "forbidden_rag_claims": [
            "RAG evidence-sufficiency accuracy",
            "supported-chunk precision/recall",
        ],
        "track_b_persistent_retrieval_evaluable": False,
        "persistent_execution_rule": "STRICT_NO_OP",
        "P2_PERSISTENT_MEMORY_ONLY": "NOT_APPLICABLE_NO_GOVERNED_PERSISTENT_TARGET",
        "P2_FULL_NO_PERSISTENT_TARGET": "RAG_PLUS_SESSION_STATE_PERSISTENT_COMPONENT_NO_OP",
        "persistent_results_remain_from": "CONTROLLED_MECHANISM_FIXTURE28_ONLY",
        "frozen_runtime": {
            "rq1_router": RQ1_ROUTER,
            "c0_candidate_index_sha256": (
                "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
            ),
            "c0_candidate_embeddings_sha256": (
                "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
            ),
            "c0_candidate_record_count": 62,
            "c0_label_count": 16,
            "c0_aggregation": "MAX_PER_INTENT",
            "c0_model": "sentence-transformers/all-mpnet-base-v2",
            "c0_model_revision": "e8c3b32edf5434bc2275fc9bab85f82640a19130",
            "p1_policy_id": P1_POLICY_ID,
            "p1_policy_sha256": P1_POLICY_SHA256,
            "session_policy": "M0_P1_ONLY",
            "dual_gated_rag": "RQ2_C1_R1_CORRECTED_CONDITION_ISOLATION",
            "rag_top_k": 5,
            "rag_candidate_gate": "FROZEN_DETERMINISTIC_CAPABILITY_AND_SOURCE_GATE",
            "rag_sufficiency_gate": "FROZEN_EXISTING_STATUS_INTERFACE",
            "implementation_sha256": {
                role: sha256_file(ROOT / relative)
                for role, relative in implementation_paths.items()
            },
            "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
            "threshold_change_after_track_b_visible": False,
            "policy_change_after_track_b_visible": False,
        },
        "track_b_used_for_threshold_or_policy_selection": False,
        "negative_result_is_valid": True,
        "production_selection_gate_registered": False,
        "production_integration": False,
    }
