"""Corrected state-aware candidate generation over eligible metadata records."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    DENSE_TOP_K,
    RETRIEVAL_MAX_RESULTS,
    MemoryIndexRecordV1_1,
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
    _dense_ranked_records as _r2_dense_ranked_records,
    _hybrid_rank_key as _r2_hybrid_rank_key,
    temporal_validity,
    type_compatibility,
)

from .state_aware_eligibility import (
    StateAwareEligibilityOutcomeV1_1,
    state_aware_eligible_records_v1_1,
)


@dataclass(frozen=True)
class StateAwareRetrievalOutcomeV1_1:
    candidates: tuple[RankedMemoryCandidateV1_1, ...]
    eligibility: StateAwareEligibilityOutcomeV1_1
    dense_rank_by_id: Mapping[str, int]
    candidate_union_ids: tuple[str, ...]


def _ranked(
    record: MemoryIndexRecordV1_1, plan: RetrievalPlanV1_1
) -> RankedMemoryCandidateV1_1:
    compatible, unspecified = type_compatibility(record, plan.target_memory_types)
    return RankedMemoryCandidateV1_1(
        record=record,
        type_compatible=compatible,
        target_type_unspecified=unspecified,
        temporal_validity=temporal_validity(record, plan.query_time),
    )


def rank_hybrid_state_aware_v1_1_with_trace(
    plan: RetrievalPlanV1_1,
    records: Iterable[MemoryIndexRecordV1_1],
) -> StateAwareRetrievalOutcomeV1_1:
    eligibility = state_aware_eligible_records_v1_1(plan, tuple(records))
    eligible = tuple(replace(record, dense_rank=None) for record in eligibility.eligible_records)
    dense = _r2_dense_ranked_records(eligible, DENSE_TOP_K)
    dense_by_id = {record.memory_id: record for record in dense}

    candidate_union: dict[str, MemoryIndexRecordV1_1] = dict(dense_by_id)
    for record in eligible:
        if (
            record.explicit_state_link
            or record.exact_lexical_match
            or record.entity_overlap_count > 0
        ):
            candidate_union[record.memory_id] = dense_by_id.get(record.memory_id) or record

    ranked = tuple(_ranked(record, plan) for record in candidate_union.values())
    if any(not candidate.temporal_validity for candidate in ranked):
        raise ValueError("BLOCKED_RQ2_C0_R3_STATE_AWARE_ORDERING")
    candidates = tuple(
        sorted(ranked, key=_r2_hybrid_rank_key)[:RETRIEVAL_MAX_RESULTS]
    )
    return StateAwareRetrievalOutcomeV1_1(
        candidates=candidates,
        eligibility=eligibility,
        dense_rank_by_id={
            record.memory_id: int(record.dense_rank)
            for record in dense
            if record.dense_rank is not None
        },
        candidate_union_ids=tuple(candidate_union),
    )


def rank_hybrid_state_aware_v1_1(
    plan: RetrievalPlanV1_1,
    records: Iterable[MemoryIndexRecordV1_1],
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    return rank_hybrid_state_aware_v1_1_with_trace(plan, records).candidates


def state_aware_retrieval_contract() -> dict[str, Any]:
    return {
        "algorithm_id": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_policy_id": "PMR_HYBRID_STATE_AWARE",
        "stage": "RQ2-C0-R3",
        "candidate_order": [
            "STATE_AND_TEMPORAL_ELIGIBILITY",
            "DENSE_TOP_5_OVER_ELIGIBLE_ONLY",
            "ELIGIBLE_DENSE_LEXICAL_ENTITY_EXPLICIT_LINK_UNION",
            "DEDUPLICATE_BY_MEMORY_ID",
            "UNCHANGED_R2_HYBRID_LEXICOGRAPHIC_RANKING",
            "FINAL_TOP_5",
        ],
        "dense_top_k": DENSE_TOP_K,
        "maximum_results": RETRIEVAL_MAX_RESULTS,
        "ranking_tuple": [
            "EXPLICIT_STATE_LINK_DESC",
            "TYPE_COMPATIBLE_DESC",
            "ENTITY_OVERLAP_COUNT_DESC",
            "TEMPORAL_VALIDITY_DESC",
            "DENSE_SCORE_DESC",
            "EVENT_TIME_DESC",
            "MEMORY_ID_ASC",
        ],
        "all_returned_candidates_temporally_valid": True,
        "invalid_records_consume_dense_rank": False,
        "invalid_records_consume_candidate_union_slot": False,
        "invalid_records_consume_final_slot": False,
        "other_policy_algorithms_changed": False,
        "persistent_retrieval_executed": False,
    }
