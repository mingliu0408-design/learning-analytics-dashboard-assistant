"""Temporal and state hard guards before any effective admission support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
    temporal_validity,
)


MAX_ADMITTED_MEMORIES_V1_1 = 3


@dataclass(frozen=True)
class AdmissionItemDecisionV1_1:
    memory_id: str
    pre_guard_relevance_signals: tuple[str, ...]
    guard_eligible: bool
    guard_failure_reason: str | None
    relevance_supported_after_guards: bool
    admission_support_basis: tuple[str, ...]
    admitted: bool
    failure_reason: str | None


@dataclass(frozen=True)
class AdmissionOutcomeV1_1:
    decisions: tuple[AdmissionItemDecisionV1_1, ...]
    admitted_memory_ids: tuple[str, ...]
    admitted_memory_count: int
    clarification: bool
    continue_without_memory: bool
    automatic_top1_admission: bool = False


def pre_guard_relevance_signals_v1_1(
    candidate: RankedMemoryCandidateV1_1,
) -> tuple[str, ...]:
    record = candidate.record
    signals: list[str] = []
    if record.explicit_state_link:
        signals.append("DIRECT_RELEVANCE_SIGNAL")
    if record.entity_overlap_count > 0 and candidate.type_compatible:
        signals.append("STRUCTURED_RELEVANCE_SIGNAL")
    if (
        record.dense_rank is not None
        and record.dense_rank <= 3
        and candidate.type_compatible
    ):
        signals.append("DENSE_RELEVANCE_SIGNAL")
    return tuple(signals)


def admission_guard_failure_v1_1(
    candidate: RankedMemoryCandidateV1_1, plan: RetrievalPlanV1_1
) -> str | None:
    record = candidate.record
    if record.student_scope_id != plan.student_scope_id:
        return "CROSS_STUDENT_SCOPE"
    if record.status == "DELETED":
        return "DELETED_MEMORY"
    if not candidate.temporal_validity or not temporal_validity(
        record, plan.query_time
    ):
        return "TEMPORALLY_INVALID"
    if record.status in {"STALE", "SUPERSEDED", "CANCELLED"}:
        return record.status
    if record.status == "COMPLETED" and "COMPLETION" not in set(
        plan.target_memory_types
    ):
        return "COMPLETED_NOT_REQUESTED"
    if record.status not in {"ACTIVE", "COMPLETED"}:
        return "INACTIVE_STATUS"
    return None


def effective_admission_support_v1_1(
    candidate: RankedMemoryCandidateV1_1,
) -> tuple[str, ...]:
    if not candidate.temporal_validity:
        return ()
    record = candidate.record
    basis: list[str] = []
    if record.explicit_state_link:
        basis.append("DIRECT_SUPPORT")
    if record.entity_overlap_count > 0 and candidate.type_compatible:
        basis.append("STRUCTURED_SUPPORT")
    if (
        record.dense_rank is not None
        and record.dense_rank <= 3
        and candidate.type_compatible
    ):
        basis.append("DENSE_SUPPORT")
    return tuple(basis)


def admit_ranked_candidates_v1_1(
    candidates: Iterable[RankedMemoryCandidateV1_1],
    plan: RetrievalPlanV1_1,
) -> AdmissionOutcomeV1_1:
    decisions: list[AdmissionItemDecisionV1_1] = []
    admitted: list[str] = []
    for candidate in candidates:
        signals = pre_guard_relevance_signals_v1_1(candidate)
        guard_failure = admission_guard_failure_v1_1(candidate, plan)
        guard_eligible = guard_failure is None
        support = effective_admission_support_v1_1(candidate) if guard_eligible else ()
        relevance_supported = bool(support) and guard_eligible
        failure = guard_failure or (
            None if relevance_supported else "RELEVANCE_UNSUPPORTED"
        )
        is_admitted = (
            failure is None and len(admitted) < MAX_ADMITTED_MEMORIES_V1_1
        )
        if failure is None and not is_admitted:
            failure = "ADMISSION_LIMIT_REACHED"
        if is_admitted:
            admitted.append(candidate.record.memory_id)
        decisions.append(
            AdmissionItemDecisionV1_1(
                memory_id=candidate.record.memory_id,
                pre_guard_relevance_signals=signals,
                guard_eligible=guard_eligible,
                guard_failure_reason=guard_failure,
                relevance_supported_after_guards=relevance_supported,
                admission_support_basis=support,
                admitted=is_admitted,
                failure_reason=failure,
            )
        )
    clarification = not admitted and plan.memory_required
    return AdmissionOutcomeV1_1(
        decisions=tuple(decisions),
        admitted_memory_ids=tuple(admitted),
        admitted_memory_count=len(admitted),
        clarification=clarification,
        continue_without_memory=not admitted and not plan.memory_required,
    )


def temporal_admission_contract() -> dict[str, Any]:
    return {
        "algorithm_id": "MEMORY_ADMISSION_V1_1",
        "stage": "RQ2-C0-R3",
        "maximum_admitted_memories": MAX_ADMITTED_MEMORIES_V1_1,
        "processing_order": [
            "PRE_GUARD_RELEVANCE_SIGNALS",
            "MANDATORY_HARD_GUARDS",
            "EFFECTIVE_ADMISSION_SUPPORT",
            "FINAL_ADMISSION",
        ],
        "mandatory_guard_failure_codes": [
            "CROSS_STUDENT_SCOPE",
            "DELETED_MEMORY",
            "TEMPORALLY_INVALID",
            "STALE",
            "SUPERSEDED",
            "CANCELLED",
            "COMPLETED_NOT_REQUESTED",
            "INACTIVE_STATUS",
        ],
        "pre_guard_relevance_signals": [
            "DIRECT_RELEVANCE_SIGNAL",
            "STRUCTURED_RELEVANCE_SIGNAL",
            "DENSE_RELEVANCE_SIGNAL",
        ],
        "effective_support_bases": [
            "DIRECT_SUPPORT",
            "STRUCTURED_SUPPORT",
            "DENSE_SUPPORT",
        ],
        "temporal_validity_required_for_every_effective_basis": True,
        "explicit_link_overrides_hard_guard": False,
        "automatic_top1_admission": False,
        "admission_executed": False,
        "p2_implemented": False,
    }
