"""Feature/label schema and future three-process firewall contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable


FEATURE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
)
LABEL_FIELDS = (
    "review_case_id",
    "context_resolution_required",
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
    "forbidden_capabilities",
)
PREDICTOR_FORBIDDEN_FIELDS = frozenset(LABEL_FIELDS[1:]) | {
    "gold_decision_source",
    "source_role",
    "contrast_group_id",
    "query_naturalness_1_to_5",
    "case_validity",
    "context_sufficient",
    "capability_unambiguous",
    "reviewer_id",
    "reviewer_rationale",
}


def extract_feature_view_v1(combined_records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in combined_records:
        row = {field: record[field] for field in FEATURE_FIELDS}
        if not isinstance(row["review_case_id"], str) or not row["review_case_id"]:
            raise ValueError("feature review_case_id invalid")
        if not isinstance(row["current_query"], str) or not row["current_query"].strip():
            raise ValueError("feature query invalid")
        if not isinstance(row["current_page"], str):
            raise ValueError("feature page invalid")
        if not isinstance(row["necessary_conversation_history"], list):
            raise ValueError("feature history must be a list")
        rows.append(row)
    if len(rows) != 48 or len({row["review_case_id"] for row in rows}) != 48:
        raise ValueError("feature view must contain 48 unique cases")
    return rows, {
        "combined_source_open_count": 1,
        "combined_source_read_count": 1,
        "feature_row_count": 48,
        "exported_fields": list(FEATURE_FIELDS),
        "forbidden_keys_exported": 0,
        "predictor_modules_imported": 0,
    }


def validate_feature_view_v1(rows: list[Mapping[str, Any]]) -> None:
    if len(rows) != 48 or any(set(row) != set(FEATURE_FIELDS) for row in rows):
        raise ValueError("feature-only view schema mismatch")
    if len({str(row["review_case_id"]) for row in rows}) != 48:
        raise ValueError("feature-only view identity mismatch")


def feature_label_firewall_contract_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-feature-label-process-firewall-contract-v1",
        "status": "FROZEN",
        "combined_source_role": "SEALED_COMBINED_CASE_SOURCE",
        "combined_source_is_label_free": False,
        "feature_extractor_process": {
            "process_id": "TRACK_B_FEATURE_EXTRACTOR_V1",
            "combined_source_open_read": "1/1",
            "output_fields": list(FEATURE_FIELDS),
            "forbidden_keys_exported": 0,
            "predictor_modules_imported": 0,
            "must_exit_before_predictor": True,
        },
        "predictor_process": {
            "fresh_process": True,
            "allowed_inputs": ["FEATURE_ONLY_VIEW", "FROZEN_MODEL_RUNTIME_ARTIFACTS"],
            "forbidden_inputs": ["SEALED_COMBINED_CASE_SOURCE", "LABEL_ONLY_GOLD", "GROUPING_LEDGER", "HIDDEN_LEGACY"],
            "method_order": ["B0", "B1", "P1"],
            "review_case_id_is_feature": False,
        },
        "metric_process": {
            "fresh_process": True,
            "starts_after_prediction_firewall": True,
            "label_only_gold_open_read": "1/1",
            "grouping_ledger_open_read": "1/1",
            "combined_source_open_read": "0/0",
        },
        "feature_fields": list(FEATURE_FIELDS),
        "label_fields": list(LABEL_FIELDS),
        "predictor_forbidden_fields": sorted(PREDICTOR_FORBIDDEN_FIELDS),
    }
