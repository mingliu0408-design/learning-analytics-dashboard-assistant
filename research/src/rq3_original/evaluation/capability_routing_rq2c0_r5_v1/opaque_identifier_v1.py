"""Schema validation for governed opaque memory linkage identifiers."""

from __future__ import annotations

import unicodedata
from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)


OPAQUE_IDENTIFIER_CONTRACT_ID = "GOVERNED_OPAQUE_IDENTIFIER_V1"
MAX_IDENTIFIER_UTF8_BYTES = 256


class OpaqueIdentifierError(ValueError):
    def __init__(self, code: str, field_name: str):
        self.code = code
        self.field_name = field_name
        super().__init__(f"{code}:{field_name}")


def validate_opaque_identifier_v1(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise OpaqueIdentifierError("IDENTIFIER_NOT_STRING", field_name)
    if value == "":
        raise OpaqueIdentifierError("IDENTIFIER_EMPTY", field_name)
    if value != unicodedata.normalize("NFC", value):
        raise OpaqueIdentifierError("IDENTIFIER_NOT_NFC", field_name)
    if value != value.strip():
        raise OpaqueIdentifierError("IDENTIFIER_SURROUNDING_WHITESPACE", field_name)
    if "\x00" in value:
        raise OpaqueIdentifierError("IDENTIFIER_CONTAINS_NUL", field_name)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise OpaqueIdentifierError("IDENTIFIER_NOT_STRING", field_name) from exc
    if len(encoded) > MAX_IDENTIFIER_UTF8_BYTES:
        raise OpaqueIdentifierError("IDENTIFIER_TOO_LONG", field_name)


def validate_governed_memory_identifiers_v1(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> None:
    values = (
        (episode.memory_id, "episode.memory_id"),
        (episode.payload_id, "episode.payload_id"),
        (episode.episode_id, "episode.episode_id"),
        (episode.source_turn_id, "episode.source_turn_id"),
        (payload_ref.memory_id, "payload_ref.memory_id"),
        (payload_ref.payload_id, "payload_ref.payload_id"),
        (payload.memory_id, "payload.memory_id"),
        (payload.payload_id, "payload.payload_id"),
        (payload.source_episode_id, "payload.source_episode_id"),
        (payload.source_turn_id, "payload.source_turn_id"),
    )
    for value, field_name in values:
        validate_opaque_identifier_v1(value, field_name)


def opaque_identifier_contract() -> dict[str, Any]:
    return {
        "schema_version": "opaque-identifier-contract-v1",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "contract_id": OPAQUE_IDENTIFIER_CONTRACT_ID,
        "governed_identifier_types": [
            "memory_id",
            "payload_id",
            "episode_id",
            "source_turn_id",
        ],
        "rules": {
            "type": "STRING",
            "unicode_normalisation": "NFC_REQUIRED_ALREADY_NORMALISED",
            "non_empty": True,
            "surrounding_whitespace": "PROHIBITED",
            "nul_character": "PROHIBITED",
            "maximum_utf8_bytes": MAX_IDENTIFIER_UTF8_BYTES,
            "trim_then_accept": False,
            "automatic_normalisation": False,
            "casefold": False,
            "punctuation_removal": False,
            "automatic_replacement_id": False,
        },
        "failure_codes": [
            "IDENTIFIER_NOT_STRING",
            "IDENTIFIER_EMPTY",
            "IDENTIFIER_NOT_NFC",
            "IDENTIFIER_SURROUNDING_WHITESPACE",
            "IDENTIFIER_CONTAINS_NUL",
            "IDENTIFIER_TOO_LONG",
        ],
        "all_episode_reference_payload_occurrences_validated": True,
        "store_global_uniqueness_implemented": False,
        "store_global_uniqueness_rq2c1_prerequisite": True,
        "fail_closed": True,
    }
