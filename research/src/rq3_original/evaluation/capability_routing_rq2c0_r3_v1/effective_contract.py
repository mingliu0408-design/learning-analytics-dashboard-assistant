"""Safe authority, amendments, and effective RQ2-C1 import contract."""

from __future__ import annotations

from typing import Any, Iterable

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    DENSE_TOP_K,
    POLICY_IDS,
    PRIMARY_POLICY_ID,
    RETRIEVAL_MAX_RESULTS,
    MemoryIndexRecordV1_1,
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
    rank_dense_only,
    rank_hybrid_type_temporal,
    rank_kw_legacy,
)
from evaluation.capability_routing_rq2c0_r2_v1.text_normalisation import (
    FROZEN_DENSE_ENCODER,
)

from . import AUTHORISATION_DATE, AUTHORITY_TYPE
from .admission_v1_1 import MAX_ADMITTED_MEMORIES_V1_1
from .payload_scope_v1_1 import PAYLOAD_SCOPE_ID, text_only_payload_contract
from .state_aware_eligibility import eligibility_contract
from .state_aware_retrieval_v1_1 import (
    rank_hybrid_state_aware_v1_1,
    state_aware_retrieval_contract,
)
from .admission_v1_1 import temporal_admission_contract


AUTHORISED_CORRECTIONS = (
    "STATE_AND_TEMPORAL_ELIGIBILITY_BEFORE_DENSE_TOP_K",
    "TEMPORAL_INVALIDITY_BLOCKS_ALL_ADMISSION_SUPPORT_BASES",
    "RQ2_C1_TEXT_ONLY_PRIVATE_PAYLOAD_SCOPE",
)


def _unchanged_false_fields() -> dict[str, bool]:
    return {
        "fixture_text_change_authorised": False,
        "fixture_membership_change_authorised": False,
        "fixture_expected_decision_change_authorised": False,
        "fixture_hash_change_authorised": False,
        "coverage_change_authorised": False,
        "P1_change_authorised": False,
        "Capability_Gold_change_authorised": False,
        "human_annotation_change_authorised": False,
        "retrieval_threshold_change_authorised": False,
        "primary_policy_identity_change_authorised": False,
        "model_output_change_authorised": False,
        "production_behaviour_change_authorised": False,
    }


def memory_safety_repair_authority() -> dict[str, Any]:
    return {
        "schema_version": "memory-safety-repair-authority-v1",
        "stage": "RQ2-C0-R3",
        "status": "FROZEN",
        "authority_type": AUTHORITY_TYPE,
        "authorisation_date": AUTHORISATION_DATE,
        "authorised_corrections": list(AUTHORISED_CORRECTIONS),
        **_unchanged_false_fields(),
    }


def _amendment(amendment_id: str, correction: str, supersedes: str) -> dict[str, Any]:
    return {
        "schema_version": amendment_id.lower().replace("_", "-") + "-v1",
        "stage": "RQ2-C0-R3",
        "status": "FROZEN",
        "amendment_id": amendment_id,
        "authority_basis": "USER_EXPLICIT_AUTHORISATION",
        "authorisation_date": AUTHORISATION_DATE,
        "authorised_correction": correction,
        "supersedes": supersedes,
        "human_annotation_changed": False,
        "Capability_Gold_changed": False,
        "fixture_changed": False,
        "fixture_hash_changed": False,
        "P1_changed": False,
        "primary_policy_identity_changed": False,
        "retrieval_threshold_changed": False,
        "model_output_used": False,
        "production_behaviour_changed": False,
    }


def candidate_ordering_amendment() -> dict[str, Any]:
    return {
        **_amendment(
            "STATE_AWARE_CANDIDATE_ORDERING_AMENDMENT",
            AUTHORISED_CORRECTIONS[0],
            "RQ2_C0_R2_STATE_AWARE_CANDIDATE_ORDERING",
        ),
        "effective_algorithm": "PMR_HYBRID_STATE_AWARE_V1_1",
        "eligibility_before_dense_top_k": True,
        "eligibility": eligibility_contract(),
        "retrieval": state_aware_retrieval_contract(),
    }


def temporal_admission_amendment() -> dict[str, Any]:
    return {
        **_amendment(
            "TEMPORAL_ADMISSION_SAFETY_AMENDMENT",
            AUTHORISED_CORRECTIONS[1],
            "RQ2_C0_R2_ADMISSION_TEMPORAL_GUARD_ORDERING",
        ),
        "effective_algorithm": "MEMORY_ADMISSION_V1_1",
        "admission": temporal_admission_contract(),
    }


def payload_scope_amendment() -> dict[str, Any]:
    return {
        **_amendment(
            "TEXT_ONLY_PAYLOAD_SCOPE_AMENDMENT",
            AUTHORISED_CORRECTIONS[2],
            "RQ2_C0_R2_AMBIGUOUS_STRUCTURED_VALUE_SCOPE",
        ),
        "effective_payload_scope": PAYLOAD_SCOPE_ID,
        "payload": text_only_payload_contract(),
    }


def effective_persistent_memory_contract() -> dict[str, Any]:
    return {
        "schema_version": "effective-persistent-memory-contract-v1.2",
        "stage": "RQ2-C0-R3",
        "status": "FROZEN_FOR_FUTURE_RQ2_C1",
        "historical_contract": "RQ2-C0-R2 executable persistent-memory contract",
        "effective_primary_policy_id": PRIMARY_POLICY_ID,
        "effective_state_aware_algorithm": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission_algorithm": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": PAYLOAD_SCOPE_ID,
        "supersedes": [
            "R2_STATE_AWARE_CANDIDATE_ORDERING",
            "R2_ADMISSION_TEMPORAL_GUARD_ORDERING",
            "R2_AMBIGUOUS_STRUCTURED_VALUE_SCOPE",
        ],
        "unchanged": {
            "policy_family_ids": list(POLICY_IDS),
            "primary_policy_identity": PRIMARY_POLICY_ID,
            "dense_encoder": dict(FROZEN_DENSE_ENCODER),
            "dense_top_k": DENSE_TOP_K,
            "maximum_retrieval_results": RETRIEVAL_MAX_RESULTS,
            "maximum_admitted_memories": MAX_ADMITTED_MEMORIES_V1_1,
            "ranking_tuple_after_eligibility": state_aware_retrieval_contract()[
                "ranking_tuple"
            ],
            "direct_structured_dense_relevance_definitions": True,
            "fixture_bank": True,
            "P1": True,
            "Capability_Gold": True,
            "production_code": True,
        },
        "rq2c1_import_contract": {
            "state_aware_retrieval": (
                "evaluation.capability_routing_rq2c0_r3_v1."
                "state_aware_retrieval_v1_1.rank_hybrid_state_aware_v1_1"
            ),
            "admission": (
                "evaluation.capability_routing_rq2c0_r3_v1."
                "admission_v1_1.admit_ranked_candidates_v1_1"
            ),
            "payload_scope": (
                "evaluation.capability_routing_rq2c0_r3_v1."
                "payload_scope_v1_1.validate_text_only_payload_scope_v1_1"
            ),
            "superseded_r2_state_aware_import_allowed": False,
            "superseded_r2_admission_import_allowed": False,
        },
        "only_state_aware_effective_algorithm_superseded": True,
        "primary_policy_selected_from_data": False,
        "p2_implemented": False,
        "persistent_store_implemented": False,
        "actual_retrieval_executed": False,
        "production_behaviour_changed": False,
    }


def rank_effective_policy_v1_2(
    policy_id: str,
    plan: RetrievalPlanV1_1,
    records: Iterable[MemoryIndexRecordV1_1],
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    frozen_records = tuple(records)
    if policy_id == "PMR_KW_LEGACY":
        return rank_kw_legacy(plan, frozen_records)
    if policy_id == "PMR_DENSE_ONLY":
        return rank_dense_only(plan, frozen_records)
    if policy_id == "PMR_HYBRID_TYPE_TEMPORAL":
        return rank_hybrid_type_temporal(plan, frozen_records)
    if policy_id == PRIMARY_POLICY_ID:
        return rank_hybrid_state_aware_v1_1(plan, frozen_records)
    raise ValueError("BLOCKED_RQ2_C0_R3_EFFECTIVE_CONTRACT: unknown policy")
