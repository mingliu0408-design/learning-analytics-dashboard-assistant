"""Text-only payload metadata, non-emptiness, hash, and byte-length integrity."""

from __future__ import annotations

import hashlib
from typing import Any

from evaluation.capability_routing_rq2c0_r2_v1.text_normalisation import (
    normalise_text_for_hash,
)

from .payload_identity_binding import PayloadIntegrityError
from .payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)


def canonical_payload_bytes_v1_2(payload: MemoryPayloadV1_2) -> bytes:
    if not isinstance(payload.canonical_text, str):
        raise PayloadIntegrityError("INVALID_CANONICAL_PAYLOAD_TYPE")
    try:
        canonical = normalise_text_for_hash(payload.canonical_text).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PayloadIntegrityError("INVALID_CANONICAL_PAYLOAD_ENCODING") from exc
    if not canonical:
        raise PayloadIntegrityError("EMPTY_CANONICAL_PAYLOAD")
    return canonical


def validate_payload_metadata_consistency_v1_2(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> None:
    if not (
        payload.content_type == payload_ref.content_type == "text/plain"
    ):
        raise PayloadIntegrityError("CONTENT_TYPE_MISMATCH")
    if not (payload.encoding == payload_ref.encoding == "UTF-8"):
        raise PayloadIntegrityError("ENCODING_MISMATCH")
    if (
        not isinstance(payload.locale, str)
        or not payload.locale
        or payload.locale != payload.locale.strip()
        or len(payload.locale) > 35
        or payload.locale != payload_ref.locale
    ):
        raise PayloadIntegrityError("LOCALE_MISMATCH")
    canonical = canonical_payload_bytes_v1_2(payload)
    computed_hash = hashlib.sha256(canonical).hexdigest()
    if not (
        computed_hash
        == payload.content_hash
        == payload_ref.content_hash
        == episode.raw_content_hash
    ):
        raise PayloadIntegrityError("CONTENT_HASH_MISMATCH")
    if (
        type(payload_ref.content_length) is not int
        or payload_ref.content_length != len(canonical)
    ):
        raise PayloadIntegrityError("CONTENT_LENGTH_MISMATCH")


def payload_metadata_consistency_contract() -> dict[str, Any]:
    return {
        "schema_version": "payload-metadata-consistency-contract-v1",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "text_normalisation": "FROZEN_R2_TEXT_NORMALISATION",
        "canonical_bytes": "frozen_normalise(canonical_text).encode('utf-8')",
        "canonical_payload_must_be_nonempty": True,
        "empty_failure_code": "EMPTY_CANONICAL_PAYLOAD",
        "canonical_text_runtime_type": "str",
        "invalid_type_failure_code": "INVALID_CANONICAL_PAYLOAD_TYPE",
        "invalid_utf8_failure_code": "INVALID_CANONICAL_PAYLOAD_ENCODING",
        "content_type_exact": "text/plain",
        "encoding_exact": "UTF-8",
        "locale": {
            "equal_between_payload_and_reference": True,
            "non_empty": True,
            "maximum_length": 35,
            "surrounding_whitespace": "PROHIBITED",
            "unknown_locale_value": "und",
            "language_detection": False,
            "automatic_correction": False,
        },
        "hash_algorithm": "SHA-256",
        "hash_triplet_consistency": True,
        "content_length_unit": "NORMALISED_UTF8_BYTES",
        "unicode_character_count_used": False,
        "structured_value_allowed_values": ["NULL", "EMPTY_MAPPING"],
        "fail_closed": True,
    }
