"""v1.3 source-stratified agreement with correct context-link population."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_v1_r1.agreement_metrics import (
    calculate_full_agreement,
    cohens_kappa,
    percent_agreement,
)

from . import PREDICTED_CAPABILITIES
from .human_review_schema_v1_3 import (
    CONTEXT_LINK_VALUES,
    has_displayed_history,
    validate_independent_reviewer_ids,
)


class AgreementV13Error(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def _align(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    by_a = {_text(row, "review_case_id"): row for row in rows_a}
    by_b = {_text(row, "review_case_id"): row for row in rows_b}
    if len(by_a) != len(rows_a) or len(by_b) != len(rows_b) or set(by_a) != set(by_b):
        raise AgreementV13Error("packets do not align by review_case_id")
    ids = sorted(by_a)
    return [by_a[key] for key in ids], [by_b[key] for key in ids]


def _as_v11(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{**dict(row), "case_id": _text(row, "review_case_id")} for row in rows]


def _context_link_metrics(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    source_by_id: Mapping[str, str],
) -> dict[str, Any]:
    applicable = [
        (left, right)
        for left, right in zip(rows_a, rows_b)
        if source_by_id[_text(left, "review_case_id")] == "synthetic"
        and has_displayed_history(left)
        and has_displayed_history(right)
    ]
    if not applicable:
        return {
            "status": "NOT_APPLICABLE",
            "applicable_case_count": 0,
            "authentic_not_applicable_cases_excluded": True,
            "percent_agreement": None,
            "cohens_kappa": None,
        }
    left_values = [_text(left, "context_link_valid") for left, _ in applicable]
    right_values = [_text(right, "context_link_valid") for _, right in applicable]
    return {
        "status": "CALCULATED_SYNTHETIC_DISPLAYED_HISTORY_ONLY",
        "applicable_case_count": len(applicable),
        "authentic_not_applicable_cases_excluded": True,
        "percent_agreement": percent_agreement(left_values, right_values),
        "cohens_kappa": cohens_kappa(
            left_values, right_values, categories=CONTEXT_LINK_VALUES
        ),
    }


def _included_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        if _text(row, "case_validity") == "INCLUDE_VALID_CASE":
            counts.update(
                capability
                for capability in PREDICTED_CAPABILITIES
                if _text(row, capability) == "YES"
            )
    return {capability: counts[capability] for capability in PREDICTED_CAPABILITIES}


def authentic_missing_context_summary(
    rows: Sequence[Mapping[str, Any]], source_by_id: Mapping[str, str]
) -> dict[str, int]:
    authentic = [
        row
        for row in rows
        if source_by_id[_text(row, "review_case_id")] == "authentic"
    ]
    return {
        "context_sufficient_no_count": sum(
            _text(row, "context_sufficient") == "NO" for row in authentic
        ),
        "context_resolution_required_count": sum(
            _text(row, "context_resolution_required") == "YES" for row in authentic
        ),
        "excluded_due_to_missing_context_count": sum(
            _text(row, "context_sufficient") == "NO"
            and _text(row, "case_validity") != "INCLUDE_VALID_CASE"
            for row in authentic
        ),
    }


def _metrics(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    source_by_id: Mapping[str, str],
) -> dict[str, Any]:
    value = calculate_full_agreement(_as_v11(rows_a), _as_v11(rows_b))
    value["context_link_valid"] = _context_link_metrics(
        rows_a, rows_b, source_by_id
    )
    value["included_case_capability_distribution_by_reviewer"] = {
        "reviewer_a": _included_distribution(rows_a),
        "reviewer_b": _included_distribution(rows_b),
    }
    return value


def calculate_source_stratified_agreement(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    mapping_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_independent_reviewer_ids(rows_a, rows_b)
    aligned_a, aligned_b = _align(rows_a, rows_b)
    source_by_id = {
        _text(row, "review_case_id"): _text(row, "source_bank")
        for row in mapping_rows
    }
    if set(source_by_id) != {_text(row, "review_case_id") for row in aligned_a}:
        raise AgreementV13Error("source mapping does not cover packet IDs")
    result: dict[str, Any] = {
        "schema_version": "human-agreement-results-v1.3",
        "overall_60": _metrics(aligned_a, aligned_b, source_by_id),
        "by_source": {},
        "authentic_missing_context_by_reviewer": {
            "reviewer_a": authentic_missing_context_summary(aligned_a, source_by_id),
            "reviewer_b": authentic_missing_context_summary(aligned_b, source_by_id),
        },
    }
    for source, expected_count in (("authentic", 25), ("synthetic", 35)):
        subset_a = [
            row
            for row in aligned_a
            if source_by_id[_text(row, "review_case_id")] == source
        ]
        subset_b = [
            row
            for row in aligned_b
            if source_by_id[_text(row, "review_case_id")] == source
        ]
        if len(subset_a) != expected_count or len(subset_b) != expected_count:
            raise AgreementV13Error("source subset count mismatch")
        subset_sources = {
            _text(row, "review_case_id"): source for row in subset_a
        }
        result["by_source"][source] = _metrics(
            subset_a, subset_b, subset_sources
        )
    return result


def human_agreement_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "human-agreement-contract-v1.3",
        "stage": "RQ2-A-R1C",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "calculation_before_both_packets_frozen": False,
        "overall_and_source_stratified_metrics_retained": True,
        "context_link_agreement_population": (
            "SYNTHETIC_CASES_WITH_DISPLAYED_CONVERSATION_HISTORY_ONLY"
        ),
        "authentic_context_link_validity_metric": "NOT_APPLICABLE",
        "authentic_not_applicable_values_count_as_agreement": False,
        "authentic_missing_context_reporting": [
            "CONTEXT_SUFFICIENT_NO_COUNT",
            "CONTEXT_RESOLUTION_REQUIRED_COUNT",
            "EXCLUDED_DUE_TO_MISSING_CONTEXT_COUNT",
        ],
        "required_general_metrics": [
            "VALIDITY_PERCENT_AGREEMENT_AND_KAPPA",
            "NATURALNESS_QUADRATIC_WEIGHTED_KAPPA",
            "CONTEXT_SUFFICIENT_PERCENT_AGREEMENT_AND_KAPPA",
            "CAPABILITY_UNAMBIGUOUS_PERCENT_AGREEMENT_AND_KAPPA",
            "CONTEXT_RESOLUTION_PERCENT_POSITIVE_NEGATIVE_AGREEMENT_AND_KAPPA",
            "PER_CAPABILITY_PERCENT_POSITIVE_NEGATIVE_AGREEMENT_KAPPA_AND_SUPPORT",
            "EXACT_SET_AGREEMENT",
            "MEAN_AND_MEDIAN_JACCARD",
            "ALL_CAPABILITY_MICRO_AGREEMENT",
            "FORBIDDEN_CAPABILITY_SET_AGREEMENT_AND_JACCARD",
        ],
        "kappa_role": "DIAGNOSTIC_ONLY",
        "zero_variance_kappa_policy": "RETURN_NULL_WITH_STATUS",
        "source_identity_visible_during_first_round": False,
    }
