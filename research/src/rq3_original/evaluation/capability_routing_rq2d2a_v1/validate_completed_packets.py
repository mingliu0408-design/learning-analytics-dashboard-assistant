"""Validate both canonical 48-by-21 completed human-review packets."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

from . import (
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_A_SIZE,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    CANONICAL_B_SIZE,
    CAPABILITIES,
    PACKET_FIELDS,
    ROOT,
    csv_rows,
    id_set_sha256,
    ordered_id_sha256,
    sha256_file,
)


CASE_VALIDITY_VALUES = {"INCLUDE_VALID_CASE", "EXCLUDE_INVALID_CASE", "UNCERTAIN"}
CONTEXT_LINK_VALUES = {"YES", "NO", "NOT_APPLICABLE", "UNCERTAIN"}
CONTEXT_SUFFICIENT_VALUES = {"YES", "NO", "NOT_APPLICABLE", "UNCERTAIN"}
CAPABILITY_UNAMBIGUOUS_VALUES = {"YES", "NO", "UNCERTAIN"}
BINARY_VALUES = {"YES", "NO"}


class CompletedPacketValidationError(RuntimeError):
    pass


def forbidden_set(row: Mapping[str, str]) -> set[str]:
    value = str(row.get("forbidden_capabilities") or "").strip()
    if not value:
        return set()
    entries = [entry.strip() for entry in value.split(";") if entry.strip()]
    if len(entries) != len(set(entries)) or not set(entries) <= set(CAPABILITIES):
        raise CompletedPacketValidationError("unknown or duplicate forbidden capability")
    return set(entries)


def capability_set(row: Mapping[str, str]) -> set[str]:
    return {capability for capability in CAPABILITIES if row[capability] == "YES"}


def _validate_row(row: Mapping[str, str]) -> None:
    if row["case_validity"] not in CASE_VALIDITY_VALUES:
        raise CompletedPacketValidationError("invalid case_validity")
    if row["query_naturalness_1_to_5"] not in {"1", "2", "3", "4", "5"}:
        raise CompletedPacketValidationError("naturalness is not an integer from 1 to 5")
    if row["context_link_valid"] not in CONTEXT_LINK_VALUES:
        raise CompletedPacketValidationError("invalid context_link_valid")
    if row["context_sufficient"] not in CONTEXT_SUFFICIENT_VALUES:
        raise CompletedPacketValidationError("invalid context_sufficient")
    if row["capability_unambiguous"] not in CAPABILITY_UNAMBIGUOUS_VALUES:
        raise CompletedPacketValidationError("invalid capability_unambiguous")
    if row["context_resolution_required"] not in BINARY_VALUES:
        raise CompletedPacketValidationError("invalid context_resolution_required")
    if any(row[capability] not in BINARY_VALUES for capability in CAPABILITIES):
        raise CompletedPacketValidationError("invalid capability annotation")
    active = capability_set(row)
    if row["case_validity"] == "INCLUDE_VALID_CASE" and not active:
        raise CompletedPacketValidationError("included case has an empty capability set")
    if "clarification" in active and active != {"clarification"}:
        raise CompletedPacketValidationError("clarification is not exclusive")
    if "safe_direct_response" in active and active != {"safe_direct_response"}:
        raise CompletedPacketValidationError("safe_direct_response is not exclusive")
    if active & forbidden_set(row):
        raise CompletedPacketValidationError("required and forbidden capabilities overlap")
    if not str(row["reviewer_rationale"]).strip():
        raise CompletedPacketValidationError("reviewer rationale is blank")
    try:
        date.fromisoformat(row["review_date"])
    except ValueError as exc:
        raise CompletedPacketValidationError("review_date is not ISO-8601") from exc


def _validate_one(
    path: Path,
    expected_sha256: str,
    expected_size: int,
    reviewer_id: str,
) -> list[dict[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise CompletedPacketValidationError("canonical packet is not a regular file")
    if sha256_file(path) != expected_sha256 or path.stat().st_size != expected_size:
        raise CompletedPacketValidationError("canonical packet identity mismatch")
    rows = csv_rows(path)
    if len(rows) != 48 or not rows or tuple(rows[0]) != PACKET_FIELDS:
        raise CompletedPacketValidationError("canonical packet shape mismatch")
    if len({row["review_case_id"] for row in rows}) != 48:
        raise CompletedPacketValidationError("duplicate review_case_id")
    for row in rows:
        _validate_row(row)
    if {row["reviewer_id"] for row in rows} != {reviewer_id}:
        raise CompletedPacketValidationError("reviewer identity mismatch")
    if {row["review_date"] for row in rows} != {"2026-08-29"}:
        raise CompletedPacketValidationError("canonical review date mismatch")
    return rows


def validate_completed_packets(
    root: Path = ROOT,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    rows_a = _validate_one(
        root / CANONICAL_A_RELATIVE,
        CANONICAL_A_SHA256,
        CANONICAL_A_SIZE,
        "A",
    )
    rows_b = _validate_one(
        root / CANONICAL_B_RELATIVE,
        CANONICAL_B_SHA256,
        CANONICAL_B_SIZE,
        "B",
    )
    ids_a = [row["review_case_id"] for row in rows_a]
    ids_b = [row["review_case_id"] for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise CompletedPacketValidationError("packet case-set/order contract mismatch")
    expected_uniform = {
        "case_validity": "INCLUDE_VALID_CASE",
        "context_link_valid": "YES",
        "capability_unambiguous": "YES",
    }
    for field, value in expected_uniform.items():
        if any(row[field] != value for row in rows_a + rows_b):
            raise CompletedPacketValidationError("current expected uniform field mismatch")
    return rows_a, rows_b, {
        "schema_version": "track-b-completed-packet-validation-v1",
        "stage": "RQ2-D2A",
        "status": "PASS",
        "record_count_per_packet": 48,
        "column_count_per_packet": 21,
        "exact_header": list(PACKET_FIELDS),
        "case_id_set_sha256": id_set_sha256(ids_a),
        "same_case_id_set": True,
        "different_row_order": True,
        "reviewer_a_order_sha256": ordered_id_sha256(ids_a),
        "reviewer_b_order_sha256": ordered_id_sha256(ids_b),
        "reviewer_ids": ["A", "B"],
        "review_date": "2026-08-29",
        "all_required_human_fields_completed": True,
        "rationale_nonempty_count": {"A": 48, "B": 48},
        "case_validity_counts": {
            "A": {"INCLUDE_VALID_CASE": 48},
            "B": {"INCLUDE_VALID_CASE": 48},
        },
        "context_link_valid_counts": {"A": {"YES": 48}, "B": {"YES": 48}},
        "capability_unambiguous_counts": {"A": {"YES": 48}, "B": {"YES": 48}},
        "empty_included_capability_set_count": 0,
        "clarification_exclusivity_violation_count": 0,
        "safe_direct_exclusivity_violation_count": 0,
        "forbidden_required_overlap_count": 0,
        "unknown_capability_count": 0,
        "gold_formed": False,
    }
