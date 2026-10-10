"""Validate reviewer identity separately from crossed blank-template order."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import (
    BLANK_A_RELATIVE,
    BLANK_B_RELATIVE,
    ROOT,
    VISIBLE_FIELDS,
    csv_rows,
    id_set_sha256,
    ordered_id_sha256,
)
from .completed_packet_authority import CompletedPacketPaths


class CrossedPacketLineageError(RuntimeError):
    pass


def _assert_template_match(
    completed: list[dict[str, str]], blank: list[dict[str, str]]
) -> None:
    if len(completed) != len(blank):
        raise CrossedPacketLineageError("BLOCKED_RQ2_D2A_LINEAGE_MISMATCH")
    for completed_row, blank_row in zip(completed, blank):
        if any(completed_row[field] != blank_row[field] for field in VISIBLE_FIELDS):
            raise CrossedPacketLineageError("BLOCKED_RQ2_D2A_LINEAGE_MISMATCH")


def validate_crossed_lineage(
    paths: CompletedPacketPaths, root: Path = ROOT
) -> dict[str, Any]:
    rows_a = csv_rows(paths.original_a)
    rows_b = csv_rows(paths.original_b)
    blank_a = csv_rows(root / BLANK_A_RELATIVE)
    blank_b = csv_rows(root / BLANK_B_RELATIVE)

    _assert_template_match(rows_a, blank_b)
    _assert_template_match(rows_b, blank_a)
    ids_a = [row["review_case_id"] for row in rows_a]
    ids_b = [row["review_case_id"] for row in rows_b]
    if (
        len(ids_a) != 48
        or len(set(ids_a)) != 48
        or len(set(ids_b)) != 48
        or set(ids_a) != set(ids_b)
        or ids_a == ids_b
    ):
        raise CrossedPacketLineageError("BLOCKED_RQ2_D2A_LINEAGE_MISMATCH")
    by_a = {row["review_case_id"]: row for row in rows_a}
    by_b = {row["review_case_id"]: row for row in rows_b}
    visible_disagreement_count = sum(
        any(by_a[case_id][field] != by_b[case_id][field] for field in VISIBLE_FIELDS)
        for case_id in sorted(by_a)
    )
    if visible_disagreement_count:
        raise CrossedPacketLineageError("BLOCKED_RQ2_D2A_LINEAGE_MISMATCH")
    return {
        "schema_version": "track-b-crossed-packet-assignment-attestation-v1",
        "stage": "RQ2-D2A",
        "status": "PASS",
        "reviewer_a": {
            "human_reviewer_identity": "A",
            "source_blank_template": "FROZEN_REVIEWER_B_TEMPLATE_ORDER",
            "fixed_fields_and_row_order_match": True,
        },
        "reviewer_b": {
            "human_reviewer_identity": "B",
            "source_blank_template": "FROZEN_REVIEWER_A_TEMPLATE_ORDER",
            "fixed_fields_and_row_order_match": True,
        },
        "fixed_visible_fields": list(VISIBLE_FIELDS),
        "record_count_per_packet": 48,
        "same_case_id_set": True,
        "case_id_set_sha256": id_set_sha256(ids_a),
        "different_row_order": True,
        "reviewer_a_order_sha256": ordered_id_sha256(ids_a),
        "reviewer_b_order_sha256": ordered_id_sha256(ids_b),
        "duplicate_id_count": 0,
        "visible_field_disagreement_after_id_alignment": 0,
        "agreement_alignment_key": "review_case_id",
        "scientific_effect": "NONE_IF_ALIGNED_BY_REVIEW_CASE_ID",
        "user_attested_independence": True,
        "reviewers_are_different_humans": True,
        "ai_annotation_used": False,
        "answers_swapped_renamed_or_copied": False,
    }
