"""Recompute the exact source-blinded 23-case adjudication set."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import (
    AGREEMENT_FIELDS,
    EXPECTED_DISAGREEMENT_IDS,
    EXPECTED_FIELD_DISAGREEMENTS,
    id_set_sha256,
)
from .validate_completed_packets import forbidden_set


class DisagreementManifestError(RuntimeError):
    pass


def _different(field: str, left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    if field == "forbidden_capabilities":
        return forbidden_set(left) != forbidden_set(right)
    return left[field] != right[field]


def build_disagreement_manifest(
    rows_a: Sequence[Mapping[str, str]], rows_b: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    by_a = {row["review_case_id"]: row for row in rows_a}
    by_b = {row["review_case_id"]: row for row in rows_b}
    if set(by_a) != set(by_b) or len(by_a) != 48:
        raise DisagreementManifestError("packet ID alignment mismatch")
    cases: list[dict[str, Any]] = []
    counts = {field: 0 for field in AGREEMENT_FIELDS}
    for case_id in sorted(by_a):
        reasons = [field for field in AGREEMENT_FIELDS if _different(field, by_a[case_id], by_b[case_id])]
        for field in reasons:
            counts[field] += 1
        if reasons:
            cases.append({"review_case_id": case_id, "disagreement_reasons": reasons})
    observed_ids = tuple(case["review_case_id"] for case in cases)
    if (
        len(cases) != 23
        or observed_ids != EXPECTED_DISAGREEMENT_IDS
        or counts != EXPECTED_FIELD_DISAGREEMENTS
    ):
        raise DisagreementManifestError("BLOCKED_RQ2_D2A_DISAGREEMENT_SET_MISMATCH")
    return {
        "schema_version": "track-b-disagreement-manifest-v1",
        "stage": "RQ2-D2A",
        "status": "AWAITING_HUMAN_ADJUDICATION",
        "comparison_alignment": "review_case_id",
        "trigger_fields": list(AGREEMENT_FIELDS),
        "excluded_non_trigger_fields": ["reviewer_rationale", "reviewer_id", "review_date"],
        "unique_disagreement_case_count": 23,
        "disagreement_case_id_set_sha256": id_set_sha256(observed_ids),
        "field_level_disagreement_counts": counts,
        "cases": cases,
        "computed_from_actual_canonical_packets": True,
        "hardcoded_result_used_as_computation_substitute": False,
        "adjudication_decision_count": 0,
        "capability_gold_frozen": False,
    }
