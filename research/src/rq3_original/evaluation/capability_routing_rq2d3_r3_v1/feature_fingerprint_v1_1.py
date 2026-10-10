"""Case-independent content and case-bound feature fingerprints."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from . import canonical_json_bytes


CONTENT_DOMAIN = b"RQ2_TRACK_B_FEATURE_CONTENT_V1_1\x00"
RECORD_DOMAIN = b"RQ2_TRACK_B_FEATURE_RECORD_V1_1\x00"
FEATURE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
)


def canonical_feature_content_v1_1(
    *, current_query: str, current_page: str, necessary_conversation_history: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(current_query, str) or not isinstance(current_page, str):
        raise TypeError("feature text fields must be strings")
    if not isinstance(necessary_conversation_history, (list, tuple)) or not all(
        isinstance(item, Mapping) for item in necessary_conversation_history
    ):
        raise TypeError("feature history must be a sequence of objects")
    return {
        "current_query": current_query,
        "current_page": current_page,
        "necessary_conversation_history": [dict(item) for item in necessary_conversation_history],
    }


def feature_content_fingerprint_v1_1(**content: Any) -> str:
    canonical = canonical_feature_content_v1_1(**content)
    return hashlib.sha256(CONTENT_DOMAIN + canonical_json_bytes(canonical).rstrip(b"\n")).hexdigest()


def feature_record_fingerprint_v1_1(review_case_id: str, content_fingerprint: str) -> str:
    if not review_case_id or len(content_fingerprint) != 64:
        raise ValueError("invalid feature identity")
    return hashlib.sha256(
        RECORD_DOMAIN
        + review_case_id.encode("utf-8")
        + b"\x00"
        + content_fingerprint.encode("ascii")
    ).hexdigest()


def build_feature_row_v1_1(row: Mapping[str, Any]) -> dict[str, Any]:
    if not set(FEATURE_FIELDS) <= set(row):
        raise ValueError("feature input field absent")
    content = canonical_feature_content_v1_1(
        current_query=str(row["current_query"]),
        current_page=str(row["current_page"]),
        necessary_conversation_history=row["necessary_conversation_history"],
    )
    content_hash = feature_content_fingerprint_v1_1(**content)
    case_id = str(row["review_case_id"])
    return {
        "review_case_id": case_id,
        **content,
        "feature_content_fingerprint": content_hash,
        "feature_record_fingerprint": feature_record_fingerprint_v1_1(case_id, content_hash),
    }


def validate_feature_row_v1_1(row: Mapping[str, Any]) -> None:
    expected = build_feature_row_v1_1(row)
    if dict(row) != expected:
        raise ValueError("feature fingerprint mismatch")


def feature_fingerprint_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-feature-fingerprint-contract-v1-1",
        "status": "FROZEN",
        "content_domain": "RQ2_TRACK_B_FEATURE_CONTENT_V1_1",
        "record_domain": "RQ2_TRACK_B_FEATURE_RECORD_V1_1",
        "content_fields": list(FEATURE_FIELDS[1:]),
        "record_identity_field": "review_case_id",
        "review_case_id_in_content_fingerprint": False,
        "review_case_id_in_record_fingerprint": True,
    }
