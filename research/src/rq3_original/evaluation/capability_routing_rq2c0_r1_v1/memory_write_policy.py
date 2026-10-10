"""Pure write, supersession, and deletion policy contracts; no store is implemented."""

from __future__ import annotations

from typing import Any

from .persistent_memory_schema import (
    ALLOWED_MEMORY_TYPES,
    FORBIDDEN_AUTOMATIC_MEMORY_TYPES,
    MemoryWriteDecisionV1,
)


ALLOWED_WRITE_EVENTS = (
    "EXPLICIT_STUDENT_FACT",
    "EXPLICIT_STUDENT_PREFERENCE",
    "EXPLICIT_STUDENT_CONSTRAINT",
    "EXPLICIT_STUDENT_GOAL",
    "EXPLICIT_STUDENT_CORRECTION",
    "VERIFIED_PLAN_STATE_CHANGE",
    "VERIFIED_COMPLETION_EVENT",
)

FORBIDDEN_WRITE_EVENTS = (
    "MODEL_INFERENCE_ONLY",
    "ASSISTANT_SUGGESTION_NOT_ACCEPTED",
    "UNVERIFIED_DASHBOARD_INTERPRETATION",
    "SENSITIVE_PROFILE_INFERENCE",
)


def decide_write(
    *,
    event_type: str,
    memory_type: str | None,
    explicit_student_source: bool,
    verified_system_event: bool,
    sensitive_inference: bool = False,
    duplicate_of: str | None = None,
    supersedes: str | None = None,
) -> MemoryWriteDecisionV1:
    candidate = event_type in ALLOWED_WRITE_EVENTS or event_type in FORBIDDEN_WRITE_EVENTS
    reasons: list[str] = []
    if event_type in FORBIDDEN_WRITE_EVENTS:
        reasons.append("FORBIDDEN_WRITE_EVENT")
    if memory_type not in ALLOWED_MEMORY_TYPES:
        reasons.append("UNAUTHORISED_MEMORY_TYPE")
    if memory_type in FORBIDDEN_AUTOMATIC_MEMORY_TYPES:
        reasons.append("FORBIDDEN_INFERENCE_TYPE")
    if sensitive_inference:
        reasons.append("SENSITIVE_INFERENCE")
    source_authorised = explicit_student_source or verified_system_event
    if not source_authorised:
        reasons.append("NO_EXPLICIT_OR_VERIFIED_SOURCE")
    if event_type not in ALLOWED_WRITE_EVENTS:
        reasons.append("EVENT_NOT_ON_WRITE_ALLOWLIST")
    write_authorised = not reasons and duplicate_of is None
    if duplicate_of is not None:
        reasons.append("DUPLICATE_NO_NEW_EPISODE")
    return MemoryWriteDecisionV1(
        candidate=candidate,
        write_authorised=write_authorised,
        memory_type=memory_type,
        explicit_student_source=explicit_student_source,
        verified_system_event=verified_system_event,
        sensitive_inference=sensitive_inference,
        duplicate_of=duplicate_of,
        supersedes=supersedes,
        failure_reason=reasons[0] if reasons else None,
        decision_trace=tuple(reasons or ("WRITE_AUTHORISED",)),
    )


def supersession_transition(old_memory_id: str, new_memory_id: str) -> dict[str, Any]:
    if not old_memory_id or not new_memory_id or old_memory_id == new_memory_id:
        raise ValueError("BLOCKED_RQ2_C0_R1_WRITE_POLICY: invalid supersession")
    return {
        "operation": "APPEND_NEW_EPISODE",
        "new_memory_id": new_memory_id,
        "new_status": "ACTIVE",
        "supersedes_memory_id": old_memory_id,
        "old_memory_id": old_memory_id,
        "old_status": "SUPERSEDED",
        "old_episode_deleted": False,
        "history_preserved": True,
    }


def deletion_transition(memory_id: str, deletion_event_hash: str) -> dict[str, Any]:
    if not memory_id or not deletion_event_hash:
        raise ValueError("BLOCKED_RQ2_C0_R1_WRITE_POLICY: invalid deletion")
    return {
        "memory_id": memory_id,
        "new_status": "DELETED",
        "tombstone_created": True,
        "retrieval_eligible": False,
        "raw_content_reexposed": False,
        "audit_deletion_event_hash": deletion_event_hash,
    }


def write_update_contract() -> dict[str, Any]:
    return {
        "schema_version": "memory-write-update-contract-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "allowed_write_events": list(ALLOWED_WRITE_EVENTS),
        "forbidden_write_events": list(FORBIDDEN_WRITE_EVENTS),
        "write_source_requirement": "EXPLICIT_STUDENT_STATEMENT_OR_VERIFIED_SYSTEM_EVENT",
        "model_inference_only_authorised": False,
        "assistant_suggestion_without_acceptance_authorised": False,
        "unverified_dashboard_profile_write_authorised": False,
        "sensitive_profile_inference_authorised": False,
        "correction_update": {
            "append_new_episode": True,
            "mark_old_superseded": True,
            "retain_supersedes_link": True,
            "delete_historical_fact": False,
        },
        "deletion": {
            "status": "DELETED",
            "tombstone_required": True,
            "future_retrieval_allowed": False,
            "audit_event_hash_retained": True,
        },
        "store_implemented": False,
        "production_behavior_changed": False,
    }
