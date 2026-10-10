"""Deterministic metadata-only retrieval algorithms; no store or encoder is executed."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Any, Iterable, Sequence

from .text_normalisation import FROZEN_DENSE_ENCODER, representation_contract


POLICY_IDS = (
    "PMR_KW_LEGACY",
    "PMR_DENSE_ONLY",
    "PMR_HYBRID_TYPE_TEMPORAL",
    "PMR_HYBRID_STATE_AWARE",
)
PRIMARY_POLICY_ID = "PMR_HYBRID_STATE_AWARE"
DENSE_TOP_K = 5
RETRIEVAL_MAX_RESULTS = 5


@dataclass(frozen=True)
class RetrievalPlanV1_1:
    student_scope_id: str
    query_time: str
    target_memory_types: tuple[str, ...]
    original_query: str = ""
    resolved_query: str = ""
    resolver_authorised: bool = False
    memory_required: bool = False


@dataclass(frozen=True)
class MemoryIndexRecordV1_1:
    memory_id: str
    student_scope_id: str
    memory_type: str
    status: str
    event_time: str
    valid_from: str
    valid_until: str | None
    governed_entity_set: tuple[str, ...] = ()
    supersession_chain_id: str = ""
    supersedes_memory_id: str | None = None
    explicit_state_link: bool = False
    production_memory_trigger: bool = False
    exact_lexical_match: bool = False
    entity_overlap_count: int = 0
    dense_score: float = 0.0
    dense_rank: int | None = None
    explicitness: str = ""


@dataclass(frozen=True)
class RankedMemoryCandidateV1_1:
    record: MemoryIndexRecordV1_1
    type_compatible: bool
    target_type_unspecified: bool
    temporal_validity: bool


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("vectors must have equal non-zero dimensions")
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("zero-norm vector is not a valid dense representation")
    return numerator / (left_norm * right_norm)


def temporal_validity(record: MemoryIndexRecordV1_1, query_time: str) -> bool:
    query = _timestamp(query_time)
    starts = _timestamp(record.valid_from)
    ends = _timestamp(record.valid_until) if record.valid_until is not None else None
    return starts <= query and (ends is None or query < ends)


def type_compatibility(
    record: MemoryIndexRecordV1_1, target_memory_types: Sequence[str]
) -> tuple[bool, bool]:
    targets = tuple(dict.fromkeys(target_memory_types))
    if not targets:
        return True, True
    return record.memory_type in targets, False


def hard_safety_filter(
    records: Iterable[MemoryIndexRecordV1_1], plan: RetrievalPlanV1_1
) -> tuple[tuple[MemoryIndexRecordV1_1, ...], dict[str, str]]:
    eligible: list[MemoryIndexRecordV1_1] = []
    rejected: dict[str, str] = {}
    for record in records:
        if record.student_scope_id != plan.student_scope_id:
            rejected[record.memory_id] = "CROSS_STUDENT_SCOPE"
        elif record.status == "DELETED":
            rejected[record.memory_id] = "DELETED_MEMORY"
        else:
            eligible.append(record)
    return tuple(eligible), rejected


def _ranked(record: MemoryIndexRecordV1_1, plan: RetrievalPlanV1_1) -> RankedMemoryCandidateV1_1:
    compatible, unspecified = type_compatibility(record, plan.target_memory_types)
    return RankedMemoryCandidateV1_1(
        record=record,
        type_compatible=compatible,
        target_type_unspecified=unspecified,
        temporal_validity=temporal_validity(record, plan.query_time),
    )


def _dense_ranked_records(
    records: Iterable[MemoryIndexRecordV1_1], limit: int = DENSE_TOP_K
) -> tuple[MemoryIndexRecordV1_1, ...]:
    ordered = sorted(
        records,
        key=lambda item: (-item.dense_score, -_timestamp(item.event_time), item.memory_id),
    )[:limit]
    return tuple(replace(item, dense_rank=index) for index, item in enumerate(ordered, 1))


def rank_kw_legacy(
    plan: RetrievalPlanV1_1, records: Iterable[MemoryIndexRecordV1_1]
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    eligible, _ = hard_safety_filter(records, plan)
    candidates = [
        item
        for item in eligible
        if item.production_memory_trigger
        or item.explicit_state_link
        or item.exact_lexical_match
        or item.entity_overlap_count > 0
    ]
    candidates.sort(
        key=lambda item: (
            -int(item.explicit_state_link),
            -item.entity_overlap_count,
            -_timestamp(item.event_time),
            item.memory_id,
        )
    )
    return tuple(_ranked(item, plan) for item in candidates[:RETRIEVAL_MAX_RESULTS])


def rank_dense_only(
    plan: RetrievalPlanV1_1, records: Iterable[MemoryIndexRecordV1_1]
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    eligible, _ = hard_safety_filter(records, plan)
    return tuple(_ranked(item, plan) for item in _dense_ranked_records(eligible))


def _hybrid_union(
    plan: RetrievalPlanV1_1, records: Iterable[MemoryIndexRecordV1_1]
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    eligible, _ = hard_safety_filter(records, plan)
    dense = _dense_ranked_records(eligible)
    dense_by_id = {item.memory_id: item for item in dense}
    union: dict[str, MemoryIndexRecordV1_1] = dict(dense_by_id)
    for item in eligible:
        if item.explicit_state_link or item.exact_lexical_match or item.entity_overlap_count > 0:
            union[item.memory_id] = replace(
                item,
                dense_rank=(dense_by_id.get(item.memory_id) or item).dense_rank,
            )
    return tuple(_ranked(item, plan) for item in union.values())


def _hybrid_rank_key(item: RankedMemoryCandidateV1_1) -> tuple[Any, ...]:
    record = item.record
    return (
        -int(record.explicit_state_link),
        -int(item.type_compatible),
        -record.entity_overlap_count,
        -int(item.temporal_validity),
        -record.dense_score,
        -_timestamp(record.event_time),
        record.memory_id,
    )


def rank_hybrid_type_temporal(
    plan: RetrievalPlanV1_1, records: Iterable[MemoryIndexRecordV1_1]
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    return tuple(sorted(_hybrid_union(plan, records), key=_hybrid_rank_key)[:RETRIEVAL_MAX_RESULTS])


def _conflict_group_key(record: MemoryIndexRecordV1_1) -> tuple[Any, ...]:
    entities = tuple(sorted(set(record.governed_entity_set)))
    if not entities and not record.supersession_chain_id:
        return (record.student_scope_id, record.memory_type, record.memory_id)
    return (
        record.student_scope_id,
        record.memory_type,
        entities,
        record.supersession_chain_id,
    )


def rank_hybrid_state_aware(
    plan: RetrievalPlanV1_1, records: Iterable[MemoryIndexRecordV1_1]
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    union = list(_hybrid_union(plan, records))
    completion_requested = "COMPLETION" in set(plan.target_memory_types)
    allowed: list[RankedMemoryCandidateV1_1] = []
    for candidate in union:
        status = candidate.record.status
        if status in {"STALE", "SUPERSEDED", "CANCELLED"}:
            continue
        if status == "COMPLETED" and not completion_requested:
            continue
        if status not in {"ACTIVE", "COMPLETED"}:
            continue
        allowed.append(candidate)

    active_corrections = [
        item
        for item in allowed
        if item.record.memory_type == "CORRECTION"
        and item.record.status == "ACTIVE"
        and item.record.explicitness == "EXPLICIT_STUDENT"
    ]
    superseded_ids = {
        item.record.supersedes_memory_id
        for item in active_corrections
        if item.record.supersedes_memory_id
    }
    allowed = [item for item in allowed if item.record.memory_id not in superseded_ids]

    latest_by_group: dict[tuple[Any, ...], RankedMemoryCandidateV1_1] = {}
    for item in allowed:
        key = _conflict_group_key(item.record)
        incumbent = latest_by_group.get(key)
        if incumbent is None or (
            _timestamp(item.record.event_time), item.record.memory_id
        ) > (
            _timestamp(incumbent.record.event_time), incumbent.record.memory_id
        ):
            latest_by_group[key] = item
    return tuple(
        sorted(latest_by_group.values(), key=_hybrid_rank_key)[:RETRIEVAL_MAX_RESULTS]
    )


def rank_candidates(
    policy_id: str,
    plan: RetrievalPlanV1_1,
    records: Iterable[MemoryIndexRecordV1_1],
) -> tuple[RankedMemoryCandidateV1_1, ...]:
    if policy_id == "PMR_KW_LEGACY":
        return rank_kw_legacy(plan, records)
    if policy_id == "PMR_DENSE_ONLY":
        return rank_dense_only(plan, records)
    if policy_id == "PMR_HYBRID_TYPE_TEMPORAL":
        return rank_hybrid_type_temporal(plan, records)
    if policy_id == "PMR_HYBRID_STATE_AWARE":
        return rank_hybrid_state_aware(plan, records)
    raise ValueError("BLOCKED_RQ2_C0_R2_RETRIEVAL_CONTRACT: unknown policy")


def executable_retrieval_contract() -> dict[str, Any]:
    return {
        "schema_version": "executable-persistent-retrieval-contract-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN_EXECUTABLE_NOT_RUN",
        "policy_ids": list(POLICY_IDS),
        "primary_policy_id": PRIMARY_POLICY_ID,
        "primary_policy_selection_basis": "PREDESIGNATED_BY_CONTRACT_NOT_FIXTURE_SELECTION",
        "common_hard_guards_before_candidate_generation": [
            "STUDENT_SCOPE_ID_EXACT_MATCH",
            "STATUS_NOT_DELETED",
        ],
        "hard_guard_rejection_codes": ["CROSS_STUDENT_SCOPE", "DELETED_MEMORY"],
        "dense_encoder": dict(FROZEN_DENSE_ENCODER),
        "dense_score": "COSINE_QUERY_EMBEDDING_MEMORY_EMBEDDING",
        "dense_tie_break": ["DENSE_SCORE_DESC", "EVENT_TIME_DESC", "MEMORY_ID_ASC"],
        "dense_top_k": DENSE_TOP_K,
        "maximum_policy_results": RETRIEVAL_MAX_RESULTS,
        "PMR_KW_LEGACY": {
            "signals": [
                "EXISTING_PRODUCTION_MEMORY_TRIGGER",
                "EXPLICIT_PLAN_GOAL_REFERENCE_LINK",
                "EXACT_LEXICAL_OR_ENTITY_OVERLAP",
            ],
            "ranking": [
                "EXPLICIT_LINK_DESC",
                "ENTITY_OVERLAP_COUNT_DESC",
                "EVENT_TIME_DESC",
                "MEMORY_ID_ASC",
            ],
            "p2_full_policy": False,
        },
        "PMR_DENSE_ONLY": {
            "candidate_pool": "DENSE_TOP_5",
            "ranking_uses_keyword_entity_type_time_active_status_or_gold": False,
            "admission_still_validates_type_and_time": True,
            "p2_full_policy": False,
        },
        "PMR_HYBRID_TYPE_TEMPORAL": {
            "candidate_union": [
                "DENSE_TOP_5",
                "EXACT_LEXICAL_OR_ENTITY_MATCH",
                "EXPLICIT_GOAL_PLAN_OR_REFERENCE_LINK",
            ],
            "deduplicate_by": "MEMORY_ID",
            "ranking": [
                "EXPLICIT_STATE_LINK_DESC",
                "TYPE_COMPATIBLE_DESC",
                "ENTITY_OVERLAP_COUNT_DESC",
                "TEMPORAL_VALIDITY_DESC",
                "DENSE_SCORE_DESC",
                "EVENT_TIME_DESC",
                "MEMORY_ID_ASC",
            ],
            "target_type_unspecified_is_neutral_true_and_audited": True,
        },
        "PMR_HYBRID_STATE_AWARE": {
            "starts_from": "PMR_HYBRID_TYPE_TEMPORAL_CANDIDATE_UNION",
            "pre_ranking_rejections": [
                "STALE",
                "SUPERSEDED",
                "CANCELLED",
                "COMPLETED_UNLESS_COMPLETION_TARGETED",
            ],
            "conflict_group_fields": [
                "STUDENT_SCOPE",
                "MEMORY_TYPE",
                "GOVERNED_ENTITY_SET",
                "SUPERSESSION_CHAIN",
            ],
            "latest_active_episode_only": True,
            "latest_explicit_correction_wins": True,
            "p2_full_policy": True,
        },
        "case_specific_keywords": False,
        "gold_feature": False,
        "encoder_executed": False,
        "retrieval_executed": False,
        "persistent_store_implemented": False,
        "representation": representation_contract(),
    }
