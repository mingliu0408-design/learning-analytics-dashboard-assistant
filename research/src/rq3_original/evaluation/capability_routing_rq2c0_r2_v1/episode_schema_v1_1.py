"""PersistentLearnerMemoryV1_1 episode schema linked to private payloads."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Mapping

from .payload_schema import (
    MemoryPayloadRefV1,
    MemoryPayloadV1,
    computed_payload_content_hash,
)


@dataclass(frozen=True)
class MemoryEpisodeV1_1:
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
    payload_id: str
    event_time: str
    ingested_at: str
    timezone: str
    status_reason: str
    source_kind: str
    projection_eligible: bool


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def validate_episode_payload_consistency(
    episode: MemoryEpisodeV1_1,
    payload_ref: MemoryPayloadRefV1,
    payload: MemoryPayloadV1,
) -> None:
    if not (
        episode.memory_id == payload_ref.memory_id == payload.memory_id
        and episode.payload_id == payload_ref.payload_id == payload.payload_id
    ):
        raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: identity")
    computed = computed_payload_content_hash(payload)
    if not (
        computed
        == episode.raw_content_hash
        == payload_ref.content_hash
        == payload.content_hash
    ):
        raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: content hash mismatch")
    if _parse_time(episode.ingested_at) < _parse_time(episode.event_time):
        raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: ingestion precedes event")


def episode_schema_contract() -> dict[str, Any]:
    fields_v1_1 = [field.name for field in fields(MemoryEpisodeV1_1)]
    return {
        "schema_version": "persistent-learner-memory-schema-v1-1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "historical_contract_retained": "PersistentLearnerMemoryV1",
        "current_contract": "PersistentLearnerMemoryV1_1",
        "episode_schema": "MemoryEpisodeV1_1",
        "episode_fields": fields_v1_1,
        "added_fields": [
            "payload_id",
            "event_time",
            "ingested_at",
            "timezone",
            "status_reason",
            "source_kind",
            "projection_eligible",
        ],
        "episode_contains_raw_text": False,
        "payload_content_hash_equals_episode_raw_content_hash": True,
        "payload_reference_hash_equals_episode_raw_content_hash": True,
        "event_time_distinct_from_ingested_at": True,
        "persistent_store_implemented": False,
        "production_namespace": False,
    }
