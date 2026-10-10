"""Tracked-safe payload references and private local-only payload schema."""

from __future__ import annotations

from dataclasses import dataclass, fields
import re
from typing import Any, Mapping

from .text_normalisation import normalised_text_hash


@dataclass(frozen=True)
class MemoryPayloadRefV1:
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
class MemoryPayloadV1:
    payload_id: str
    memory_id: str
    canonical_text: str
    structured_value: Mapping[str, Any] | None
    content_type: str
    locale: str
    source_episode_id: str
    source_turn_id: str
    content_hash: str


def computed_payload_content_hash(payload: MemoryPayloadV1) -> str:
    if payload.structured_value not in (None, {}):
        raise ValueError("RQ2-C0-R2 does not define structured-value hashing")
    return normalised_text_hash(payload.canonical_text)


def validate_payload_reference(value: MemoryPayloadRefV1) -> None:
    if not value.local_only or not value.encrypted_at_rest_required:
        raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: privacy boundary")
    if value.encoding.upper() != "UTF-8" or value.content_length < 0:
        raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: encoding or length")
    for digest in (value.student_scope_hash, value.content_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("BLOCKED_RQ2_C0_R2_PAYLOAD_SCHEMA: hash")


def payload_boundary_contract() -> dict[str, Any]:
    return {
        "schema_version": "private-memory-payload-boundary-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "tracked_safe_schema": {
            "name": "MemoryPayloadRefV1",
            "fields": [field.name for field in fields(MemoryPayloadRefV1)],
            "actual_text_allowed": False,
        },
        "private_local_schema": {
            "name": "MemoryPayloadV1",
            "fields": [field.name for field in fields(MemoryPayloadV1)],
            "storage": "IGNORED_LOCAL_ONLY_PRIVATE_STORE",
            "git_eligible": False,
            "review_zip_eligible": False,
            "canonical_text_tracked": False,
            "structured_value_tracked": False,
        },
        "content_hash_consistency_required": True,
        "encrypted_at_rest_required": True,
        "persistent_store_implemented": False,
        "production_payload_storage_implemented": False,
    }
