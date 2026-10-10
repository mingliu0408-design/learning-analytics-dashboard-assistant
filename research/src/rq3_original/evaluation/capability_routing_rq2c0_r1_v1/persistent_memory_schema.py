"""Research-only data contracts for PersistentLearnerMemoryV1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


ALLOWED_MEMORY_TYPES = (
    "GOAL",
    "PLAN",
    "CONSTRAINT",
    "PREFERENCE",
    "CORRECTION",
    "COMPLETION",
    "REFERENCED_ITEM",
    "LEARNING_EVENT",
)

FORBIDDEN_AUTOMATIC_MEMORY_TYPES = (
    "INFERRED_PERSONALITY",
    "INFERRED_MENTAL_HEALTH",
    "INFERRED_SRL_LEVEL",
    "UNCONFIRMED_ABILITY_DEFICIT",
    "OTHER_STUDENT_STATE",
)

MEMORY_STATUSES = (
    "ACTIVE",
    "STALE",
    "SUPERSEDED",
    "COMPLETED",
    "CANCELLED",
    "DELETED",
)


@dataclass(frozen=True)
class MemoryEpisodeV1:
    memory_id: str
    student_scope_id: str
    episode_id: str
    source_turn_id: str
    memory_type: str
    raw_content_hash: str
    created_at: str
    valid_from: str
    valid_until: str | None
    status: str
    explicitness: str
    confidence: float
    entities: tuple[str, ...]
    supersedes_memory_id: str | None
    provenance: Mapping[str, str]
    embedding_hash: str | None


@dataclass(frozen=True)
class MemoryStateProjectionV1:
    student_scope_id: str
    active_goal: Mapping[str, Any] | None
    active_plan: Mapping[str, Any] | None
    active_constraints: tuple[Mapping[str, Any], ...]
    active_preferences: tuple[Mapping[str, Any], ...]
    latest_corrections: tuple[Mapping[str, Any], ...]
    completed_steps: tuple[Mapping[str, Any], ...]
    referenced_items: tuple[Mapping[str, Any], ...]
    source_memory_ids: tuple[str, ...]
    projection_version: str
    updated_at: str


@dataclass(frozen=True)
class MemoryWriteDecisionV1:
    candidate: bool
    write_authorised: bool
    memory_type: str | None
    explicit_student_source: bool
    verified_system_event: bool
    sensitive_inference: bool
    duplicate_of: str | None
    supersedes: str | None
    failure_reason: str | None
    decision_trace: tuple[str, ...]


@dataclass(frozen=True)
class MemoryRetrievalPlanV1:
    query_hash: str
    context_status: str
    capability_evidence: tuple[str, ...]
    unresolved_referents: tuple[str, ...]
    target_memory_types: tuple[str, ...]
    entity_constraints: tuple[str, ...]
    temporal_constraints: Mapping[str, str]
    candidate_policy_id: str
    top_k: int
    decision_trace: tuple[str, ...]


@dataclass(frozen=True)
class MemoryCandidateV1:
    memory_id: str
    dense_rank: int | None
    lexical_entity_match: bool
    type_compatibility: bool
    temporal_validity: bool
    status_validity: bool
    scope_validity: bool
    source_confidence: float
    retrieval_evidence: tuple[str, ...]


@dataclass(frozen=True)
class MemoryAdmissionDecisionV1:
    memory_id: str
    admitted: bool
    relevance_supported: bool
    active: bool
    stale: bool
    superseded: bool
    cancelled: bool
    deleted: bool
    cross_scope: bool
    conflict_status: str
    failure_reason: str | None


SCHEMA_CLASSES = (
    MemoryEpisodeV1,
    MemoryStateProjectionV1,
    MemoryWriteDecisionV1,
    MemoryRetrievalPlanV1,
    MemoryCandidateV1,
    MemoryAdmissionDecisionV1,
)


def validate_memory_episode(value: MemoryEpisodeV1) -> None:
    if value.memory_type not in ALLOWED_MEMORY_TYPES:
        raise ValueError("BLOCKED_RQ2_C0_R1_MEMORY_SCHEMA: memory type")
    if value.status not in MEMORY_STATUSES:
        raise ValueError("BLOCKED_RQ2_C0_R1_MEMORY_SCHEMA: status")
    if not 0.0 <= value.confidence <= 1.0:
        raise ValueError("BLOCKED_RQ2_C0_R1_MEMORY_SCHEMA: confidence")
    if value.memory_type in FORBIDDEN_AUTOMATIC_MEMORY_TYPES:
        raise ValueError("BLOCKED_RQ2_C0_R1_MEMORY_SCHEMA: inferred type")


def schema_contract() -> dict[str, Any]:
    return {
        "schema_version": "persistent-learner-memory-schema-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "namespace": "RESEARCH_ONLY_PERSISTENT_LEARNER_MEMORY_V1",
        "schema_fields": {
            cls.__name__: [field.name for field in fields(cls)] for cls in SCHEMA_CLASSES
        },
        "allowed_memory_types": list(ALLOWED_MEMORY_TYPES),
        "forbidden_automatic_memory_types": list(FORBIDDEN_AUTOMATIC_MEMORY_TYPES),
        "memory_statuses": list(MEMORY_STATUSES),
        "dashboard_metric_written_to_profile_automatically": False,
        "dashboard_derived_goal_allowed_only_if_explicit_student_statement": True,
        "raw_episode_storage": "APPEND_ONLY",
        "active_state_source": "VERSIONED_PROJECTION",
        "production_namespace": False,
        "store_implemented": False,
        "embedding_retrieval_implemented": False,
        "p2_router_implemented": False,
    }


def serialise_schema_instance(value: Any) -> dict[str, Any]:
    if value.__class__ not in SCHEMA_CLASSES:
        raise TypeError("unsupported PersistentLearnerMemoryV1 schema instance")
    return asdict(value)
