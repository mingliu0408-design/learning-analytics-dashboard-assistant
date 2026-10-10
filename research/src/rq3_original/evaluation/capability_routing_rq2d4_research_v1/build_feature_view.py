"""Phase A: one-process projection from combined governed text to feature view."""

from __future__ import annotations

import json
import os
from typing import Any

from . import (
    COMBINED_SOURCE_RELATIVE,
    COMBINED_SOURCE_SHA256,
    FEATURE_VIEW_RELATIVE,
    ROOT,
    canonical_jsonl_bytes,
    jsonl_rows_from_bytes,
    sha256_bytes,
    write_new,
)


FEATURE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
)
FORBIDDEN_FEATURE_KEYS = frozenset(
    {
        "dashboard_evidence",
        "course_retrieval",
        "episodic_memory",
        "planning",
        "safe_direct_response",
        "clarification",
        "context_resolution_required",
        "forbidden_capabilities",
        "case_validity",
        "context_sufficient",
        "capability_unambiguous",
        "gold_decision_source",
        "source_role",
    }
)


def _normalise_history(value: Any) -> list[dict[str, Any]]:
    """Deserialize the frozen JSON-string history without altering its turns."""

    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    result = [dict(item) for item in parsed]
    if any(set(item) != {"role", "content"} for item in result):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    if any(not isinstance(item["role"], str) or not isinstance(item["content"], str) for item in result):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    return result


def build_feature_view() -> dict[str, Any]:
    source = ROOT / COMBINED_SOURCE_RELATIVE
    source_bytes = source.read_bytes()
    if sha256_bytes(source_bytes) != COMBINED_SOURCE_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    rows = jsonl_rows_from_bytes(source_bytes)
    if len(rows) != 48 or len({str(row["review_case_id"]) for row in rows}) != 48:
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    projected = [
        {
            "review_case_id": row["review_case_id"],
            "current_query": row["current_query"],
            "current_page": row["current_page"],
            "necessary_conversation_history": _normalise_history(
                row["necessary_conversation_history"]
            ),
        }
        for row in rows
    ]
    if any(
        set(row) != set(FEATURE_FIELDS) or set(row) & FORBIDDEN_FEATURE_KEYS
        for row in projected
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    payload = canonical_jsonl_bytes(projected)
    target = ROOT / FEATURE_VIEW_RELATIVE
    digest = write_new(target, payload)
    reread = jsonl_rows_from_bytes(target.read_bytes())
    if reread != projected:
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    return {
        "phase": "A_FEATURE_PROJECTION",
        "status": "PASS",
        "process_id": os.getpid(),
        "combined_source_open_count": 1,
        "record_count": len(projected),
        "unique_case_count": len({row["review_case_id"] for row in projected}),
        "feature_fields": list(FEATURE_FIELDS),
        "history_representation": "JSON_STRING_DESERIALISED_TO_ROLE_CONTENT_TURNS",
        "history_text_modified": False,
        "gold_field_count": 0,
        "feature_view_relative_path": str(FEATURE_VIEW_RELATIVE),
        "feature_view_sha256": digest,
        "feature_view_size_bytes": len(payload),
    }


def main() -> int:
    print(json.dumps(build_feature_view(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
