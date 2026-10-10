"""Fail-closed payload/reference/episode identity and provenance binding."""

from __future__ import annotations

from typing import Any

from .payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)
from .student_scope_hash_contract import (
    ScopeContractError,
    derive_storage_namespace_v1,
    derive_student_scope_hash_v1,
    validate_storage_namespace_v1,
)


class PayloadIntegrityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_payload_identity_binding_v1_2(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> None:
    if not (episode.memory_id == payload_ref.memory_id == payload.memory_id):
        raise PayloadIntegrityError("MEMORY_ID_MISMATCH")
    if not (episode.payload_id == payload_ref.payload_id == payload.payload_id):
        raise PayloadIntegrityError("PAYLOAD_ID_MISMATCH")
    try:
        expected_scope_hash = derive_student_scope_hash_v1(episode.student_scope_id)
    except ScopeContractError as exc:
        raise PayloadIntegrityError(exc.code) from exc
    if not (
        payload.student_scope_hash
        == payload_ref.student_scope_hash
        == expected_scope_hash
    ):
        raise PayloadIntegrityError("STUDENT_SCOPE_HASH_MISMATCH")
    expected_namespace = derive_storage_namespace_v1(expected_scope_hash)
    try:
        validate_storage_namespace_v1(payload.storage_namespace, expected_scope_hash)
        validate_storage_namespace_v1(payload_ref.storage_namespace, expected_scope_hash)
    except ScopeContractError as exc:
        raise PayloadIntegrityError("STORAGE_NAMESPACE_MISMATCH") from exc
    if not (
        payload.storage_namespace
        == payload_ref.storage_namespace
        == expected_namespace
    ):
        raise PayloadIntegrityError("STORAGE_NAMESPACE_MISMATCH")
    if payload.source_episode_id != episode.episode_id:
        raise PayloadIntegrityError("SOURCE_EPISODE_MISMATCH")
    if payload.source_turn_id != episode.source_turn_id:
        raise PayloadIntegrityError("SOURCE_TURN_MISMATCH")


def payload_identity_binding_contract() -> dict[str, Any]:
    return {
        "schema_version": "payload-identity-binding-contract-v1",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "binding_id": "PERSISTENT_MEMORY_PAYLOAD_IDENTITY_BINDING_V1_2",
        "episode_is_governed_identity_authority": True,
        "payload_may_override_episode_authority": False,
        "required_equalities": [
            "payload.memory_id == payload_ref.memory_id == episode.memory_id",
            "payload.payload_id == payload_ref.payload_id == episode.payload_id",
            "payload.student_scope_hash == payload_ref.student_scope_hash == derived episode scope hash",
            "payload.storage_namespace == payload_ref.storage_namespace == derived namespace",
            "payload.source_episode_id == episode.episode_id",
            "payload.source_turn_id == episode.source_turn_id",
        ],
        "failure_codes": [
            "MEMORY_ID_MISMATCH",
            "PAYLOAD_ID_MISMATCH",
            "STUDENT_SCOPE_HASH_MISMATCH",
            "STORAGE_NAMESPACE_MISMATCH",
            "SOURCE_EPISODE_MISMATCH",
            "SOURCE_TURN_MISMATCH",
        ],
        "fail_closed": True,
    }
