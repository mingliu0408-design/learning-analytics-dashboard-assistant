"""Effective RQ2-C1 text-only private payload boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from evaluation.capability_routing_rq2c0_r2_v1.episode_schema_v1_1 import (
    MemoryEpisodeV1_1,
)
from evaluation.capability_routing_rq2c0_r2_v1.payload_schema import (
    MemoryPayloadRefV1,
    validate_payload_reference,
)
from evaluation.capability_routing_rq2c0_r2_v1.text_normalisation import (
    normalise_text_for_hash,
    normalised_text_hash,
)


PAYLOAD_SCOPE_ID = "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1"
STRUCTURED_PAYLOAD_BLOCKER = "BLOCKED_RQ2_C0_R3_STRUCTURED_PAYLOAD_OUT_OF_SCOPE"


@dataclass(frozen=True)
class MemoryPayloadV1_1:
    payload_id: str
    memory_id: str
    canonical_text: str
    structured_value: Mapping[str, Any] | None
    content_type: str
    locale: str
    source_episode_id: str
    source_turn_id: str
    content_hash: str


def validate_text_only_payload_scope_v1_1(payload: MemoryPayloadV1_1) -> None:
    value = payload.structured_value
    if value is not None and not (isinstance(value, Mapping) and len(value) == 0):
        raise ValueError(STRUCTURED_PAYLOAD_BLOCKER)


def canonical_payload_content_hash_v1_1(payload: MemoryPayloadV1_1) -> str:
    validate_text_only_payload_scope_v1_1(payload)
    return normalised_text_hash(payload.canonical_text)


def canonical_payload_length_v1_1(payload: MemoryPayloadV1_1) -> int:
    validate_text_only_payload_scope_v1_1(payload)
    return len(normalise_text_for_hash(payload.canonical_text).encode("utf-8"))


def payload_embedding_text_v1_1(payload: MemoryPayloadV1_1) -> str:
    validate_text_only_payload_scope_v1_1(payload)
    return payload.canonical_text


def payload_retrieval_text_v1_1(payload: MemoryPayloadV1_1) -> str:
    validate_text_only_payload_scope_v1_1(payload)
    return payload.canonical_text


def validate_payload_episode_reference_consistency_v1_1(
    episode: MemoryEpisodeV1_1,
    payload_ref: MemoryPayloadRefV1,
    payload: MemoryPayloadV1_1,
) -> None:
    validate_payload_reference(payload_ref)
    validate_text_only_payload_scope_v1_1(payload)
    if not (
        episode.memory_id == payload_ref.memory_id == payload.memory_id
        and episode.payload_id == payload_ref.payload_id == payload.payload_id
    ):
        raise ValueError("BLOCKED_RQ2_C0_R3_PAYLOAD_SCOPE: identity")
    computed_hash = canonical_payload_content_hash_v1_1(payload)
    if not (
        computed_hash
        == episode.raw_content_hash
        == payload_ref.content_hash
        == payload.content_hash
    ):
        raise ValueError("BLOCKED_RQ2_C0_R3_PAYLOAD_SCOPE: content hash mismatch")
    if payload_ref.content_length != canonical_payload_length_v1_1(payload):
        raise ValueError("BLOCKED_RQ2_C0_R3_PAYLOAD_SCOPE: content length mismatch")


def text_only_payload_contract() -> dict[str, Any]:
    payload_fields = [field.name for field in fields(MemoryPayloadV1_1)]
    governed_episode_metadata = [
        "MEMORY_TYPE",
        "ENTITIES",
        "STATUS",
        "EXPLICITNESS",
        "VALID_FROM",
        "VALID_UNTIL",
        "SUPERSESSION_LINKS",
        "EVENT_TYPE",
    ]
    return {
        "scope_id": PAYLOAD_SCOPE_ID,
        "schema_version": "memory-payload-v1.1-text-only",
        "stage": "RQ2-C0-R3",
        "payload_schema": "MemoryPayloadV1_1",
        "payload_fields": payload_fields,
        "structured_value_allowed_values": ["NULL", "EMPTY_MAPPING"],
        "nonempty_structured_value_failure": STRUCTURED_PAYLOAD_BLOCKER,
        "sole_hashed_content": "CANONICAL_TEXT",
        "sole_embedding_content": "CANONICAL_TEXT",
        "sole_retrieval_content": "CANONICAL_TEXT",
        "sole_length_content": "NORMALISED_CANONICAL_TEXT_UTF8",
        "text_hash_normalisation": "FROZEN_R2_TEXT_NORMALISATION",
        "typed_values_location": "GOVERNED_EPISODE_AND_INDEX_METADATA",
        "typed_values": governed_episode_metadata,
        "typed_values_duplicated_into_structured_value": False,
        "general_structured_payload_support": False,
        "general_canonical_json_serialisation": "FUTURE_WORK",
        "structured_payload_hashing": "FUTURE_WORK",
        "git_eligible": False,
        "review_zip_eligible": False,
        "persistent_store_implemented": False,
    }
