"""Validate the seven and only seven authorised Reviewer A corrections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import EXPECTED_CORRECTED_CASE_IDS, ROOT
from .packet_identity import PacketPaths, read_packet, validate_packet_identities


class LimitedCorrectionError(RuntimeError):
    pass


def validate_limited_correction(
    paths: PacketPaths | None = None, root: Path = ROOT
) -> dict[str, Any]:
    if paths is None:
        paths, _ = validate_packet_identities(root)
    original = read_packet(paths.original_a)
    corrected = read_packet(paths.corrected_a)
    if [row["review_case_id"] for row in original] != [
        row["review_case_id"] for row in corrected
    ]:
        raise LimitedCorrectionError("Reviewer A case order changed")
    changed: list[tuple[str, str, str, str]] = []
    for left, right in zip(original, corrected):
        if tuple(left) != tuple(right):
            raise LimitedCorrectionError("Reviewer A column order changed")
        for field in left:
            if left[field] != right[field]:
                changed.append(
                    (left["review_case_id"], field, left[field], right[field])
                )
    expected_ids = set(EXPECTED_CORRECTED_CASE_IDS)
    if len(changed) != 7:
        raise LimitedCorrectionError("Reviewer A correction is not exactly seven cells")
    if {field for _, field, _, _ in changed} != {"context_sufficient"}:
        raise LimitedCorrectionError("Reviewer A changed an unauthorised column")
    if {case_id for case_id, _, _, _ in changed} != expected_ids:
        raise LimitedCorrectionError("Reviewer A changed an unauthorised case")
    if any((before, after) != ("YES", "NOT_APPLICABLE") for _, _, before, after in changed):
        raise LimitedCorrectionError("Reviewer A correction direction mismatch")
    if {row["reviewer_id"] for row in corrected} != {"REVIEWER_A"}:
        raise LimitedCorrectionError("Reviewer A identity changed")
    if {row["review_date"] for row in corrected} != {"2026/8/26"}:
        raise LimitedCorrectionError("Reviewer A date changed before canonicalisation")
    return {
        "changed_cell_count": 7,
        "changed_column": "context_sufficient",
        "changed_review_case_ids": list(EXPECTED_CORRECTED_CASE_IDS),
        "change_from": "YES",
        "change_to": "NOT_APPLICABLE",
        "reviewer_id_unchanged": True,
        "review_date_unchanged_before_canonicalisation": True,
        "other_change_count": 0,
    }
