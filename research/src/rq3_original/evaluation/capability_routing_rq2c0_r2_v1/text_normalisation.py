"""Frozen public normalisation and representation rules; no encoder is executed."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


FROZEN_DENSE_ENCODER = {
    "model": "sentence-transformers/all-mpnet-base-v2",
    "revision": "e8c3b32edf5434bc2275fc9bab85f82640a19130",
    "local_files_only": True,
    "normalize_embeddings": True,
    "device": "CPU",
    "fallback_encoder_allowed": False,
    "model_download_authorised": False,
}


def normalise_text_for_hash(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def normalised_text_hash(value: str) -> str:
    return hashlib.sha256(normalise_text_for_hash(value).encode("utf-8")).hexdigest()


def normalise_lexical_entity(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("P")
    )
    return re.sub(r"\s+", " ", text).strip()


def dense_query_representation(
    *, original_query: str, resolved_query: str, resolver_authorised: bool
) -> str:
    if resolver_authorised and str(resolved_query).strip():
        return str(resolved_query)
    return str(original_query)


def dense_memory_representation(payload: Any) -> str:
    if not hasattr(payload, "canonical_text"):
        raise TypeError("Memory dense representation requires MemoryPayloadV1")
    return str(payload.canonical_text)


def representation_contract() -> dict[str, Any]:
    return {
        "text_hash_normalisation": [
            "UNICODE_NFC",
            "CRLF_AND_CR_TO_LF",
            "STRIP_LEADING_AND_TRAILING_WHITESPACE",
            "PRESERVE_INTERNAL_WHITESPACE",
            "PRESERVE_PUNCTUATION",
            "PRESERVE_CASE",
            "UTF8_ENCODING",
        ],
        "lexical_entity_normalisation": [
            "UNICODE_NFKC",
            "CASEFOLD",
            "REMOVE_UNICODE_PUNCTUATION",
            "COLLAPSE_WHITESPACE",
        ],
        "dense_query": "RESOLVED_QUERY_IF_NONEMPTY_AND_RESOLVER_AUTHORISED_ELSE_ORIGINAL_QUERY",
        "dense_memory": "PRIVATE_PAYLOAD_CANONICAL_TEXT_ONLY",
        "forbidden_embedding_components": [
            "GOLD_LABELS",
            "MEMORY_STATUS",
            "SOURCE_ROLE",
            "EXPECTED_FIXTURE_IDS",
        ],
        "encoder": dict(FROZEN_DENSE_ENCODER),
        "encoder_executed": False,
    }
