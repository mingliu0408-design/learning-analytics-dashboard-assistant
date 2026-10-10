"""Frozen Stage 4-0 scientific and model-visibility contracts.

The helpers in this module only project already-authorized fields.  They do
not instantiate or execute any routing method.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import (
    B1_HISTORICAL_FIELDS,
    FEATURE_PROFILE,
    MODEL_IDS,
    PRIMARY_SEMANTIC_FIELDS,
)


CLARIFICATION_BOUNDARY = {
    "architecture": "SHARED_UPSTREAM_CLARIFICATION_GATE_V1",
    "applies_to_model_ids": list(MODEL_IDS),
    "separately_evaluated": True,
    "predicted_clarify_behavior": {
        "execute_core_capability_router": False,
        "rag_output": "NOT_APPLICABLE",
        "memory_output": "NOT_APPLICABLE",
        "planning_output": "NOT_APPLICABLE",
    },
    "core_conditional_evaluation": {
        "population": "FINAL_HUMAN_GOLD_ANSWER_CASES_ONLY",
        "clarification_gate_invoked": False,
        "purpose": (
            "Compare core Capability Routers without clarification-gate "
            "implementation differences."
        ),
    },
    "end_to_end_evaluation": {
        "population": "ALL_DEV_CASES",
        "clarification_gate_invoked_first": True,
        "false_clarify_on_gold_answer": "END_TO_END_ROUTE_ERROR",
    },
}

MODEL_FEATURE_CONTRACT = {
    "profile": FEATURE_PROFILE,
    "primary_router_model_ids": [model_id for model_id in MODEL_IDS if "B1" not in model_id],
    "primary_semantic_fields": list(PRIMARY_SEMANTIC_FIELDS),
    "historical_b1": {
        "model_id": "R2V2-B1_LEGACY_INTENT",
        "profile": "HISTORICAL_B1_C0_QUERY_PAGE_INTERFACE",
        "semantic_fields": list(B1_HISTORICAL_FIELDS),
    },
    "forbidden_model_features": [
        "annotation_case_id",
        "scenario_family_id",
        "dev_atomic_component_id",
        "dev_contrast_group_id",
        "dev_contrast_axis",
        "fold_id",
        "fold_role",
        "partition",
        "final_dialogue_action",
        "final_routing_signature",
        "final_rag_required",
        "final_memory_required",
        "final_planning_required",
        "final_naturalness",
        "writer_id",
    ],
}

METRIC_CONTRACT = {
    "primary_core_capability_metric": {
        "name": "macro_f1",
        "population": "FINAL_HUMAN_GOLD_ANSWER_CASES_ONLY",
        "labels": ["RAG", "Memory", "Planning"],
        "definition": "Unweighted mean of per-label binary F1.",
    },
    "secondary_core_capability_metrics": [
        {
            "name": "micro_f1",
            "definition": "F1 after pooling TP, FP, and FN over all three labels.",
        },
        {
            "name": "per_label_precision_recall_f1",
            "definition": "Precision, Recall, and F1 separately for RAG, Memory, and Planning.",
        },
        {
            "name": "exact_capability_set_match",
            "definition": "Fraction of ANSWER cases with all three capability bits correct.",
        },
        {
            "name": "example_based_f1",
            "definition": "Mean per-case set F1; two empty sets score 1.",
        },
        {
            "name": "jaccard",
            "definition": "Mean per-case set intersection over union; two empty sets score 1.",
        },
        {
            "name": "hamming_loss",
            "definition": "Incorrect capability bits divided by ANSWER cases times three.",
        },
        {
            "name": "under_routing_rate",
            "definition": "Fraction of ANSWER cases with one or more false-negative capability bits.",
        },
        {
            "name": "over_routing_rate",
            "definition": "Fraction of ANSWER cases with one or more false-positive capability bits.",
        },
        {
            "name": "family_both_utterances_correct_rate",
            "definition": "Fraction of ANSWER families for which both utterance capability sets are exact.",
        },
        {
            "name": "contrast_consistency",
            "definition": (
                "Fraction of eligible DEV contrast groups whose predicted capability change agrees "
                "with the frozen human route change; grouping metadata is audit-only."
            ),
        },
        {
            "name": "page_stratified_metrics",
            "definition": "The primary and secondary core metrics reported separately for each LAD page.",
        },
        {
            "name": "writer_a_vs_writer_b_performance",
            "definition": (
                "The primary and secondary core metrics stratified by writer using a separately "
                "authorized audit-only join; writer identity is absent from this freeze and is never a feature."
            ),
        },
    ],
    "shared_clarification_metrics": [
        {
            "name": "clarification_accuracy",
            "definition": "Binary CLARIFY-versus-ANSWER accuracy over all DEV cases.",
        },
        {
            "name": "clarify_precision_recall_f1",
            "definition": "Precision, Recall, and F1 with CLARIFY as the positive class.",
        },
        {
            "name": "full_dialogue_action_exact_match",
            "definition": "Exact ANSWER/CLARIFY action match over all DEV cases.",
        },
    ],
    "end_to_end_metrics": [
        {
            "name": "full_route_signature_exact_match",
            "definition": (
                "Exact CLARIFY or ANSWER-plus-three-capability signature match over all DEV cases."
            ),
        },
        {
            "name": "family_level_full_route_consistency",
            "definition": "Fraction of families whose two utterances both have an exact full route.",
        },
    ],
    "performance_calculated_in_stage4_0": False,
}

TIE_BREAK_CONTRACT = {
    "scope": "CORE_ROUTER_CONFIGURATION_SELECTION_WITHIN_EACH_MODEL_TRACK",
    "ordered_rules": [
        {"rank": 1, "metric": "macro_f1", "direction": "HIGHER"},
        {
            "rank": 2,
            "metric": "exact_capability_set_match",
            "direction": "HIGHER",
        },
        {"rank": 3, "metric": "jaccard", "direction": "HIGHER"},
        {"rank": 4, "metric": "under_routing_rate", "direction": "LOWER"},
        {"rank": 5, "metric": "over_routing_rate", "direction": "LOWER"},
        {
            "rank": 6,
            "metric": "predeclared_simplicity_key",
            "direction": "LOWER",
            "requirement": (
                "Each model track must declare its deterministic complexity ordering before CV scoring."
            ),
        },
        {
            "rank": 7,
            "metric": "config_id",
            "direction": "UTF8_BYTEWISE_ASCENDING",
        },
    ],
    "test_performance_used": False,
}


def project_model_features(row: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    """Return only the frozen model-visible semantic fields for ``model_id``."""

    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown RQ2-V2 model_id: {model_id}")
    fields = (
        B1_HISTORICAL_FIELDS
        if model_id == "R2V2-B1_LEGACY_INTENT"
        else PRIMARY_SEMANTIC_FIELDS
    )
    missing = [field for field in fields if field not in row]
    if missing:
        raise ValueError(f"missing model-visible fields: {missing}")
    projected = {field: row[field] for field in fields}
    if "visible_conversation_history" in projected:
        history = projected["visible_conversation_history"]
        if isinstance(history, str):
            try:
                history = json.loads(history)
            except json.JSONDecodeError as exc:
                raise ValueError("visible_conversation_history is not valid JSON") from exc
        if not isinstance(history, list):
            raise ValueError("visible_conversation_history must be a list")
        projected["visible_conversation_history"] = history
    return projected
