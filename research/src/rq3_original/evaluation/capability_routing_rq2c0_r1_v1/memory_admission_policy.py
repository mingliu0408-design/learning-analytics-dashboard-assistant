"""Persistent-memory admission, freshness, conflict, and scope contracts."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .persistent_memory_schema import MemoryAdmissionDecisionV1


REJECTION_PRIORITY = (
    "CROSS_STUDENT_SCOPE",
    "DELETED",
    "SUPERSEDED",
    "CANCELLED_OR_COMPLETED",
    "STALE",
    "INACTIVE",
    "RELEVANCE_UNSUPPORTED",
)


def decide_admission(
    *,
    memory_id: str,
    relevance_supported: bool,
    active: bool,
    stale: bool = False,
    superseded: bool = False,
    cancelled: bool = False,
    completed: bool = False,
    deleted: bool = False,
    cross_scope: bool = False,
    completion_itself_queried: bool = False,
    conflict_status: str = "NONE",
) -> MemoryAdmissionDecisionV1:
    failure_reason: str | None = None
    if cross_scope:
        failure_reason = "CROSS_STUDENT_SCOPE"
    elif deleted:
        failure_reason = "DELETED"
    elif superseded:
        failure_reason = "SUPERSEDED"
    elif cancelled or (completed and not completion_itself_queried):
        failure_reason = "CANCELLED_OR_COMPLETED"
    elif stale:
        failure_reason = "STALE"
    elif not active:
        failure_reason = "INACTIVE"
    elif not relevance_supported:
        failure_reason = "RELEVANCE_UNSUPPORTED"
    return MemoryAdmissionDecisionV1(
        memory_id=memory_id,
        admitted=failure_reason is None,
        relevance_supported=relevance_supported,
        active=active,
        stale=stale,
        superseded=superseded,
        cancelled=cancelled,
        deleted=deleted,
        cross_scope=cross_scope,
        conflict_status=conflict_status,
        failure_reason=failure_reason,
    )


def latest_explicit_correction(
    candidates: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    eligible = [
        item
        for item in candidates
        if item.get("memory_type") == "CORRECTION"
        and item.get("explicitness") == "EXPLICIT_STUDENT"
        and item.get("status") == "ACTIVE"
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (str(item.get("created_at") or ""), str(item.get("memory_id") or "")))


def admission_conflict_contract() -> dict[str, Any]:
    return {
        "schema_version": "memory-admission-conflict-contract-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "admission_requires": [
            "SEMANTIC_OR_ENTITY_RELEVANCE_SUPPORTED",
            "ACTIVE_STATUS",
            "TEMPORALLY_VALID",
            "CURRENT_STUDENT_SCOPE",
            "NOT_STALE",
            "NOT_SUPERSEDED",
            "NOT_CANCELLED_OR_COMPLETED_UNLESS_COMPLETION_QUERIED",
            "NOT_DELETED",
        ],
        "rejection_priority": list(REJECTION_PRIORITY),
        "latest_explicit_correction_wins": True,
        "raw_episode_removed_on_supersession": False,
        "per_student_namespace_required": True,
        "cross_student_search": False,
        "explicit_deletion_required": True,
        "tombstone_support_required": True,
        "deleted_memory_retrieval": False,
        "llm_summary_as_sole_fact_source": False,
        "source_provenance_required": True,
        "version_history_required": True,
        "sensitive_inference_persistence_allowed": False,
        "raw_memory_in_tracked_outputs": False,
        "public_memory_store_upload_allowed": False,
        "production_encryption_prerequisite": True,
        "production_persistence_prerequisite": True,
        "production_encryption_implemented": False,
        "production_persistence_implemented": False,
        "production_behavior_changed": False,
        "p2_implemented": False,
    }
