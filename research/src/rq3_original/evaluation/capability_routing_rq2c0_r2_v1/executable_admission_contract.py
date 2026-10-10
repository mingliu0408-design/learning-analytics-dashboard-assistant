"""Separate deterministic admission algorithm with a maximum of three memories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .executable_retrieval_contract import (
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
)


MAX_ADMITTED_MEMORIES = 3


@dataclass(frozen=True)
class AdmissionItemDecisionV1:
    memory_id: str
    admitted: bool
    relevance_supported: bool
    support_basis: tuple[str, ...]
    failure_reason: str | None


@dataclass(frozen=True)
class AdmissionOutcomeV1:
    decisions: tuple[AdmissionItemDecisionV1, ...]
    admitted_memory_ids: tuple[str, ...]
    admitted_memory_count: int
    clarification: bool
    continue_without_memory: bool
    automatic_top1_admission: bool = False


def _status_failure(
    candidate: RankedMemoryCandidateV1_1, plan: RetrievalPlanV1_1
) -> str | None:
    record = candidate.record
    if record.student_scope_id != plan.student_scope_id:
        return "CROSS_STUDENT_SCOPE"
    if record.status == "DELETED":
        return "DELETED_MEMORY"
    if record.status in {"STALE", "SUPERSEDED", "CANCELLED"}:
        return record.status
    if record.status == "COMPLETED" and "COMPLETION" not in set(plan.target_memory_types):
        return "COMPLETED_NOT_REQUESTED"
    if record.status not in {"ACTIVE", "COMPLETED"}:
        return "INACTIVE_STATUS"
    return None


def evaluate_relevance_support(
    candidate: RankedMemoryCandidateV1_1,
) -> tuple[bool, tuple[str, ...]]:
    record = candidate.record
    basis: list[str] = []
    if record.explicit_state_link:
        basis.append("DIRECT_SUPPORT")
    if (
        record.entity_overlap_count > 0
        and candidate.type_compatible
        and candidate.temporal_validity
    ):
        basis.append("STRUCTURED_SUPPORT")
    if (
        record.dense_rank is not None
        and record.dense_rank <= 3
        and candidate.type_compatible
        and candidate.temporal_validity
    ):
        basis.append("DENSE_SUPPORT")
    return bool(basis), tuple(basis)


def admit_ranked_candidates(
    candidates: Iterable[RankedMemoryCandidateV1_1],
    plan: RetrievalPlanV1_1,
) -> AdmissionOutcomeV1:
    decisions: list[AdmissionItemDecisionV1] = []
    admitted: list[str] = []
    for candidate in candidates:
        status_failure = _status_failure(candidate, plan)
        supported, basis = evaluate_relevance_support(candidate)
        failure_reason = status_failure or (None if supported else "RELEVANCE_UNSUPPORTED")
        is_admitted = failure_reason is None and len(admitted) < MAX_ADMITTED_MEMORIES
        if failure_reason is None and not is_admitted:
            failure_reason = "ADMISSION_LIMIT_REACHED"
        if is_admitted:
            admitted.append(candidate.record.memory_id)
        decisions.append(
            AdmissionItemDecisionV1(
                memory_id=candidate.record.memory_id,
                admitted=is_admitted,
                relevance_supported=supported,
                support_basis=basis,
                failure_reason=failure_reason,
            )
        )
    clarification = not admitted and plan.memory_required
    return AdmissionOutcomeV1(
        decisions=tuple(decisions),
        admitted_memory_ids=tuple(admitted),
        admitted_memory_count=len(admitted),
        clarification=clarification,
        continue_without_memory=not admitted and not plan.memory_required,
    )


def admission_contract() -> dict[str, Any]:
    return {
        "schema_version": "memory-admission-contract-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN_EXECUTABLE_NOT_RUN",
        "retrieval_separate_from_admission": True,
        "maximum_admitted_memories": MAX_ADMITTED_MEMORIES,
        "direct_support": "EXPLICIT_STATE_LINK_TRUE",
        "structured_support": [
            "ENTITY_OVERLAP_COUNT_GT_0",
            "TYPE_COMPATIBLE_TRUE",
            "TEMPORAL_VALIDITY_TRUE",
        ],
        "dense_support": [
            "DENSE_RANK_LE_3",
            "TYPE_COMPATIBLE_TRUE",
            "TEMPORAL_VALIDITY_TRUE",
        ],
        "dense_only_ranking_ignores_type_and_time": True,
        "dense_only_admission_validates_type_and_time": True,
        "automatic_top1_admission": False,
        "no_admitted_candidate_when_memory_required": "CLARIFICATION_TRUE",
        "no_admitted_candidate_when_memory_not_required": "CONTINUE_WITHOUT_MEMORY",
        "admission_executed": False,
        "p2_implemented": False,
    }
