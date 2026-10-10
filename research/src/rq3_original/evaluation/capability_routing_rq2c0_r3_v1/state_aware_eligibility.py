"""Pre-candidate state and temporal eligibility for the R3 primary policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    MemoryIndexRecordV1_1,
    RetrievalPlanV1_1,
    _conflict_group_key as _r2_conflict_group_key,
    _timestamp as _r2_timestamp,
    temporal_validity,
)


@dataclass(frozen=True)
class EligibilityTraceItemV1_1:
    memory_id: str
    outcome: str
    reason: str | None


@dataclass(frozen=True)
class StateAwareEligibilityOutcomeV1_1:
    eligible_records: tuple[MemoryIndexRecordV1_1, ...]
    rejected_record_reasons: Mapping[str, str]
    suppressed_record_reasons: Mapping[str, str]
    eligibility_trace: tuple[EligibilityTraceItemV1_1, ...]


def _initial_guard_failure(
    plan: RetrievalPlanV1_1, record: MemoryIndexRecordV1_1
) -> str | None:
    if record.student_scope_id != plan.student_scope_id:
        return "CROSS_STUDENT_SCOPE"
    if record.status == "DELETED":
        return "DELETED_MEMORY"
    if not temporal_validity(record, plan.query_time):
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


def state_aware_eligible_records_v1_1(
    plan: RetrievalPlanV1_1,
    records: Iterable[MemoryIndexRecordV1_1],
) -> StateAwareEligibilityOutcomeV1_1:
    """Apply all primary-policy eligibility and projection before dense Top-k."""

    ordered = tuple(records)
    identifiers = [record.memory_id for record in ordered]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("BLOCKED_RQ2_C0_R3_STATE_AWARE_ORDERING: duplicate memory_id")

    rejected: dict[str, str] = {}
    initially_eligible: list[MemoryIndexRecordV1_1] = []
    for record in ordered:
        failure = _initial_guard_failure(plan, record)
        if failure is None:
            initially_eligible.append(record)
        else:
            rejected[record.memory_id] = failure

    active_corrections = [
        record
        for record in initially_eligible
        if record.memory_type == "CORRECTION"
        and record.status == "ACTIVE"
        and record.explicitness == "EXPLICIT_STUDENT"
        and record.supersedes_memory_id
    ]
    correction_suppressed = {
        str(record.supersedes_memory_id)
        for record in active_corrections
        if record.supersedes_memory_id
    }
    suppressed: dict[str, str] = {
        record.memory_id: "SUPERSEDED_BY_ACTIVE_EXPLICIT_CORRECTION"
        for record in initially_eligible
        if record.memory_id in correction_suppressed
    }
    correction_filtered = [
        record for record in initially_eligible if record.memory_id not in suppressed
    ]

    latest_by_group: dict[tuple[Any, ...], MemoryIndexRecordV1_1] = {}
    for record in correction_filtered:
        key = _r2_conflict_group_key(record)
        incumbent = latest_by_group.get(key)
        if incumbent is None:
            latest_by_group[key] = record
            continue
        if (_r2_timestamp(record.event_time), record.memory_id) > (
            _r2_timestamp(incumbent.event_time),
            incumbent.memory_id,
        ):
            suppressed[incumbent.memory_id] = "CONFLICT_GROUP_OLDER_EPISODE"
            latest_by_group[key] = record
        else:
            suppressed[record.memory_id] = "CONFLICT_GROUP_OLDER_EPISODE"

    winner_ids = {record.memory_id for record in latest_by_group.values()}
    eligible = tuple(
        record
        for record in ordered
        if record.memory_id in winner_ids
        and record.memory_id not in rejected
        and record.memory_id not in suppressed
    )
    trace = tuple(
        EligibilityTraceItemV1_1(
            memory_id=record.memory_id,
            outcome=(
                "REJECTED"
                if record.memory_id in rejected
                else "SUPPRESSED"
                if record.memory_id in suppressed
                else "ELIGIBLE"
            ),
            reason=rejected.get(record.memory_id) or suppressed.get(record.memory_id),
        )
        for record in ordered
    )
    return StateAwareEligibilityOutcomeV1_1(
        eligible_records=eligible,
        rejected_record_reasons=dict(rejected),
        suppressed_record_reasons=dict(suppressed),
        eligibility_trace=trace,
    )


def eligibility_contract() -> dict[str, Any]:
    return {
        "algorithm_id": "STATE_AWARE_PRE_CANDIDATE_ELIGIBILITY_V1_1",
        "stage": "RQ2-C0-R3",
        "operation_order": [
            "SCOPE_GUARD",
            "DELETION_GUARD",
            "TEMPORAL_VALIDITY_GUARD",
            "STATE_GUARD",
            "COMPLETED_STATE_GUARD",
            "INACTIVE_STATE_GUARD",
            "EXPLICIT_CORRECTION_SUPERSESSION",
            "CONFLICT_GROUP_PROJECTION",
            "DENSE_TOP_K_ONLY_AFTER_ELIGIBILITY",
        ],
        "rejection_codes": [
            "CROSS_STUDENT_SCOPE",
            "DELETED_MEMORY",
            "TEMPORALLY_INVALID",
            "STALE",
            "SUPERSEDED",
            "CANCELLED",
            "COMPLETED_NOT_REQUESTED",
            "INACTIVE_STATUS",
        ],
        "suppression_codes": [
            "SUPERSEDED_BY_ACTIVE_EXPLICIT_CORRECTION",
            "CONFLICT_GROUP_OLDER_EPISODE",
        ],
        "gold_fields_used": False,
        "fixture_fields_used": False,
        "source_role_used": False,
        "expected_ids_used": False,
        "persistent_retrieval_executed": False,
    }
