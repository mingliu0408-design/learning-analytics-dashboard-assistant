"""Versioned episode, tracked-safe reference, and private payload linkage schemas."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Mapping

from evaluation.capability_routing_rq2c0_r2_v1.episode_schema_v1_1 import (
    MemoryEpisodeV1_1,
)


@dataclass(frozen=True)
class MemoryEpisodeV1_2(MemoryEpisodeV1_1):
    """R2 episode fields retained as the effective R4 linkage authority."""


@dataclass(frozen=True)
class MemoryPayloadRefV1_2:
    payload_id: str
    memory_id: str
    student_scope_hash: str
    content_hash: str
    content_length: int
    content_type: str
    locale: str
    encoding: str
    storage_namespace: str
    local_only: bool
    encrypted_at_rest_required: bool
    created_at: str


@dataclass(frozen=True)
class MemoryPayloadV1_2:
    payload_id: str
    memory_id: str
    student_scope_hash: str
    storage_namespace: str
    canonical_text: str
    structured_value: Mapping[str, Any] | None
    content_type: str
    locale: str
    encoding: str
    source_episode_id: str
    source_turn_id: str
    content_hash: str


def payload_linkage_schema_contract() -> dict[str, Any]:
    authority_fields = (
        "episode_id",
        "memory_id",
        "payload_id",
        "student_scope_id",
        "source_turn_id",
        "event_time",
        "created_at",
        "ingested_at",
        "raw_content_hash",
    )
    return {
        "schema_version": "persistent-memory-payload-linkage-v1.2",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "historical_episode_schema": "MemoryEpisodeV1_1",
        "effective_episode_schema": "MemoryEpisodeV1_2",
        "effective_payload_reference_schema": "MemoryPayloadRefV1_2",
        "effective_private_payload_schema": "MemoryPayloadV1_2",
        "episode_fields": [field.name for field in fields(MemoryEpisodeV1_2)],
        "episode_linkage_authority_fields": list(authority_fields),
        "payload_reference_fields": [
            field.name for field in fields(MemoryPayloadRefV1_2)
        ],
        "private_payload_fields": [field.name for field in fields(MemoryPayloadV1_2)],
        "episode_contains_raw_payload_text": False,
        "private_payload_contains_raw_student_scope_id": False,
        "private_payload_storage": "IGNORED_LOCAL_ONLY_PRIVATE_STORE",
        "private_payload_git_eligible": False,
        "private_payload_review_zip_eligible": False,
        "content_type": "text/plain",
        "encoding": "UTF-8",
        "local_only": True,
        "encrypted_at_rest_required": True,
    }
