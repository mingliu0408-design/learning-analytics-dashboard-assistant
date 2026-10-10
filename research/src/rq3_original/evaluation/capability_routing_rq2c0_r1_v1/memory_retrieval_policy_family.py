"""Frozen research-only persistent-memory candidate policy family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


POLICY_IDS = (
    "PMR_KW_LEGACY",
    "PMR_DENSE_ONLY",
    "PMR_HYBRID_TYPE_TEMPORAL",
    "PMR_HYBRID_STATE_AWARE",
)


@dataclass(frozen=True)
class RetrievalPolicySpec:
    policy_id: str
    keyword_signal: bool
    dense_signal: bool
    lexical_entity_signal: bool
    explicit_state_link: bool
    type_compatibility: bool
    temporal_validity: bool
    recency: bool
    active_status_filter: bool
    conflict_resolution: bool


POLICIES = (
    RetrievalPolicySpec("PMR_KW_LEGACY", True, False, False, False, False, False, False, False, False),
    RetrievalPolicySpec("PMR_DENSE_ONLY", False, True, False, False, False, False, False, False, False),
    RetrievalPolicySpec("PMR_HYBRID_TYPE_TEMPORAL", True, True, True, True, True, True, True, False, False),
    RetrievalPolicySpec("PMR_HYBRID_STATE_AWARE", True, True, True, True, True, True, True, True, True),
)


def policy_family_contract() -> dict[str, Any]:
    return {
        "schema_version": "persistent-memory-retrieval-policy-family-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN_NOT_SELECTED",
        "policy_ids": list(POLICY_IDS),
        "policies": {
            spec.policy_id: {
                key: value
                for key, value in spec.__dict__.items()
                if key != "policy_id"
            }
            for spec in POLICIES
        },
        "hybrid_candidate_union": [
            "DENSE_TOP_K",
            "LEXICAL_OR_ENTITY_MATCH",
            "EXPLICIT_GOAL_PLAN_OR_REFERENCE_LINK",
        ],
        "hybrid_rerank_signals": [
            "MEMORY_TYPE_COMPATIBILITY",
            "TEMPORAL_VALIDITY",
            "RECENCY",
        ],
        "state_aware_rejections": [
            "STALE",
            "SUPERSEDED",
            "CANCELLED",
            "DELETED",
            "CROSS_STUDENT_SCOPE",
        ],
        "latest_explicit_correction_wins": True,
        "keyword_only_is_baseline": True,
        "keyword_only_is_sufficient_architecture": False,
        "dense_only_is_sufficient_architecture": False,
        "future_dense_encoder": {
            "model": "sentence-transformers/all-mpnet-base-v2",
            "revision": "e8c3b32edf5434bc2275fc9bab85f82640a19130",
            "local_only": True,
            "download_authorised": False,
        },
        "local_mpnet_identity_frozen_for_future_dense_condition": True,
        "policy_selected": False,
        "policy_executed": False,
        "learned_retriever": False,
        "cross_encoder_training": False,
        "llm_memory_router": False,
        "case_specific_keywords": False,
        "gold_label_as_feature": False,
        "source_role_as_feature": False,
    }
