"""Validate all 23 complete-row third-human adjudication decisions."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from . import (
    ADJUDICATION_HUMAN_FIELDS,
    ADJUDICATION_PACKET_FIELDS,
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    CANONICAL_ADJUDICATION_SIZE,
    CAPABILITIES,
    D2A_BLANK_ADJUDICATION_RELATIVE,
    D2A_CANONICAL_A_RELATIVE,
    D2A_CANONICAL_B_RELATIVE,
    D2A_DISAGREEMENT_RELATIVE,
    GOLD_FIELDS,
    REVIEWER_FIELDS,
    ROOT,
    VISIBLE_FIELDS,
    csv_rows,
    id_set_sha256,
    normalise_forbidden,
    ordered_id_sha256,
    sha256_file,
)


class CompletedAdjudicationValidationError(RuntimeError):
    pass


IMMUTABLE_PACKET_FIELDS = (
    *VISIBLE_FIELDS,
    "disagreement_reasons",
    *(f"reviewer_a_{field}" for field in REVIEWER_FIELDS),
    *(f"reviewer_b_{field}" for field in REVIEWER_FIELDS),
)


def _active(row: Mapping[str, str]) -> set[str]:
    return {
        capability
        for capability in CAPABILITIES
        if row[f"adjudicated_{capability}"] == "YES"
    }


def _validate_decision(row: Mapping[str, str]) -> None:
    if row["adjudicated_case_validity"] not in {
        "INCLUDE_VALID_CASE",
        "EXCLUDE_INVALID_CASE",
    }:
        raise CompletedAdjudicationValidationError("invalid final case validity")
    if row["adjudicated_query_naturalness_1_to_5"] not in {"1", "2", "3", "4", "5"}:
        raise CompletedAdjudicationValidationError("invalid final naturalness")
    for field in (
        "context_link_valid",
        "context_sufficient",
        "capability_unambiguous",
        "context_resolution_required",
        *CAPABILITIES,
    ):
        if row[f"adjudicated_{field}"] not in {"YES", "NO"}:
            raise CompletedAdjudicationValidationError("UNCERTAIN/NOT_APPLICABLE final value")
    active = _active(row)
    if row["adjudicated_case_validity"] == "INCLUDE_VALID_CASE" and not active:
        raise CompletedAdjudicationValidationError("included adjudication has empty capability set")
    if "clarification" in active and active != {"clarification"}:
        raise CompletedAdjudicationValidationError("clarification is not exclusive")
    if "safe_direct_response" in active and active != {"safe_direct_response"}:
        raise CompletedAdjudicationValidationError("safe direct response is not exclusive")
    forbidden = set(normalise_forbidden(row["adjudicated_forbidden_capabilities"]))
    if active & forbidden:
        raise CompletedAdjudicationValidationError("required/forbidden capability overlap")
    if row["adjudicated_context_sufficient"] == "NO" and active != {"clarification"}:
        raise CompletedAdjudicationValidationError("context-insufficient adjudication is inconsistent")
    if not row["adjudicator_rationale"].strip():
        raise CompletedAdjudicationValidationError("adjudicator rationale is blank")


def validate_completed_adjudication(
    root: Path = ROOT,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, Any],
]:
    canonical_path = root / CANONICAL_ADJUDICATION_RELATIVE
    if (
        canonical_path.is_symlink()
        or not canonical_path.is_file()
        or sha256_file(canonical_path) != CANONICAL_ADJUDICATION_SHA256
        or canonical_path.stat().st_size != CANONICAL_ADJUDICATION_SIZE
    ):
        raise CompletedAdjudicationValidationError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_VALIDATION"
        )
    completed = csv_rows(canonical_path)
    blank = csv_rows(root / D2A_BLANK_ADJUDICATION_RELATIVE)
    reviewer_a = csv_rows(root / D2A_CANONICAL_A_RELATIVE)
    reviewer_b = csv_rows(root / D2A_CANONICAL_B_RELATIVE)
    if (
        len(completed) != 23
        or len(blank) != 23
        or not completed
        or tuple(completed[0]) != ADJUDICATION_PACKET_FIELDS
        or tuple(blank[0]) != ADJUDICATION_PACKET_FIELDS
    ):
        raise CompletedAdjudicationValidationError("completed adjudication shape mismatch")
    ids = [row["review_case_id"] for row in completed]
    blank_ids = [row["review_case_id"] for row in blank]
    if ids != blank_ids or len(set(ids)) != 23:
        raise CompletedAdjudicationValidationError("adjudication case order/identity mismatch")
    disagreement = __import__("json").loads(
        (root / D2A_DISAGREEMENT_RELATIVE).read_text(encoding="utf-8")
    )
    expected_ids = {case["review_case_id"] for case in disagreement["cases"]}
    if set(ids) != expected_ids:
        raise CompletedAdjudicationValidationError("D2A disagreement ID set mismatch")
    for observed, frozen in zip(completed, blank):
        if any(observed[field] != frozen[field] for field in IMMUTABLE_PACKET_FIELDS):
            raise CompletedAdjudicationValidationError("immutable adjudication field changed")
        _validate_decision(observed)
    by_a = {row["review_case_id"]: row for row in reviewer_a}
    by_b = {row["review_case_id"]: row for row in reviewer_b}
    if set(by_a) != set(by_b) or len(by_a) != 48:
        raise CompletedAdjudicationValidationError("canonical reviewer case set mismatch")
    for row in completed:
        case_id = row["review_case_id"]
        for field in REVIEWER_FIELDS:
            if (
                row[f"reviewer_a_{field}"] != by_a[case_id][field]
                or row[f"reviewer_b_{field}"] != by_b[case_id][field]
            ):
                raise CompletedAdjudicationValidationError("Reviewer A/B field changed")
    if (
        {row["adjudicator_id"] for row in completed} != {"C"}
        or {row["adjudication_date"] for row in completed} != {"2026-08-29"}
        or any(
            row["query_rewrite_performed"] != "false"
            or row["assistant_context_attached"] != "false"
            for row in completed
        )
    ):
        raise CompletedAdjudicationValidationError("adjudicator identity/date/immutable flag mismatch")
    # Empty forbidden-capability cells are explicit completed empty-set decisions.
    semantic_completion_count = sum(
        1
        for row in completed
        for field in ADJUDICATION_HUMAN_FIELDS
        if field == "adjudicated_forbidden_capabilities" or bool(row[field].strip())
    )
    if semantic_completion_count != 368:
        raise CompletedAdjudicationValidationError("adjudication cell completion mismatch")
    if Counter(row["adjudicated_case_validity"] for row in completed) != {
        "INCLUDE_VALID_CASE": 23
    }:
        raise CompletedAdjudicationValidationError("expected adjudication validity mismatch")
    if Counter(row["adjudicated_context_link_valid"] for row in completed) != {"YES": 23}:
        raise CompletedAdjudicationValidationError("expected context-link distribution mismatch")
    if Counter(row["adjudicated_capability_unambiguous"] for row in completed) != {"YES": 23}:
        raise CompletedAdjudicationValidationError("expected ambiguity distribution mismatch")
    if Counter(row["adjudicated_context_sufficient"] for row in completed) != {
        "YES": 21,
        "NO": 2,
    }:
        raise CompletedAdjudicationValidationError("expected adjudicated context distribution mismatch")
    return completed, reviewer_a, reviewer_b, {
        "schema_version": "track-b-completed-adjudication-validation-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "record_count": 23,
        "column_count": 52,
        "review_case_id_set_sha256": id_set_sha256(ids),
        "ordered_review_case_id_sha256": ordered_id_sha256(ids),
        "same_exact_disagreement_id_set": True,
        "same_row_order_as_frozen_blank": True,
        "duplicate_review_case_id_count": 0,
        "immutable_packet_field_count": len(IMMUTABLE_PACKET_FIELDS),
        "fixed_visible_fields_unchanged": True,
        "reviewer_a_fields_unchanged": True,
        "reviewer_b_fields_unchanged": True,
        "reviewer_rationales_unchanged": True,
        "disagreement_reasons_unchanged": True,
        "semantic_completed_adjudication_cell_count": semantic_completion_count,
        "semantic_expected_adjudication_cell_count": 368,
        "adjudicator_id": "C",
        "adjudication_date": "2026-08-29",
        "uncertain_or_not_applicable_value_count": 0,
        "case_validity_counts": {"INCLUDE_VALID_CASE": 23},
        "context_link_valid_counts": {"YES": 23},
        "context_sufficient_counts": {"YES": 21, "NO": 2},
        "capability_unambiguous_counts": {"YES": 23},
        "clarification_exclusivity_violation_count": 0,
        "safe_direct_exclusivity_violation_count": 0,
        "forbidden_required_overlap_count": 0,
        "context_insufficient_internal_consistency_violation_count": 0,
        "query_or_history_modified": False,
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
    }
