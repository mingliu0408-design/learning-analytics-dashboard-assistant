"""Exact event-to-memory-type compatibility without automatic reclassification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EVENT_TO_MEMORY_TYPE = {
    "EXPLICIT_STUDENT_GOAL": "GOAL",
    "EXPLICIT_STUDENT_PLAN": "PLAN",
    "EXPLICIT_STUDENT_CONSTRAINT": "CONSTRAINT",
    "EXPLICIT_STUDENT_PREFERENCE": "PREFERENCE",
    "EXPLICIT_STUDENT_CORRECTION": "CORRECTION",
    "VERIFIED_COMPLETION_EVENT": "COMPLETION",
    "EXPLICIT_REFERENCED_ITEM": "REFERENCED_ITEM",
    "VERIFIED_LEARNING_EVENT": "LEARNING_EVENT",
}


@dataclass(frozen=True)
class EventTypeCompatibilityDecision:
    event_type: str
    supplied_memory_type: str | None
    expected_memory_type: str | None
    write_authorised: bool
    failure_reason: str | None
    automatic_reclassification: bool = False


def evaluate_event_type_compatibility(
    event_type: str, supplied_memory_type: str | None
) -> EventTypeCompatibilityDecision:
    expected = EVENT_TO_MEMORY_TYPE.get(str(event_type))
    if expected is None:
        return EventTypeCompatibilityDecision(
            event_type=str(event_type),
            supplied_memory_type=supplied_memory_type,
            expected_memory_type=None,
            write_authorised=False,
            failure_reason="UNSUPPORTED_EVENT_TYPE",
        )
    if supplied_memory_type != expected:
        return EventTypeCompatibilityDecision(
            event_type=str(event_type),
            supplied_memory_type=supplied_memory_type,
            expected_memory_type=expected,
            write_authorised=False,
            failure_reason="EVENT_MEMORY_TYPE_MISMATCH",
        )
    return EventTypeCompatibilityDecision(
        event_type=str(event_type),
        supplied_memory_type=supplied_memory_type,
        expected_memory_type=expected,
        write_authorised=True,
        failure_reason=None,
    )


def event_type_contract() -> dict[str, Any]:
    return {
        "schema_version": "event-memory-type-compatibility-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "event_to_memory_type": dict(sorted(EVENT_TO_MEMORY_TYPE.items())),
        "unsupported_event_failure_reason": "UNSUPPORTED_EVENT_TYPE",
        "mismatched_type_failure_reason": "EVENT_MEMORY_TYPE_MISMATCH",
        "automatic_reclassification": False,
    }
