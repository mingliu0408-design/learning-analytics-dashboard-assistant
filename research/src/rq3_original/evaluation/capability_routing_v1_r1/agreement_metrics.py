"""Agreement metrics required after two independent human packets freeze."""

from __future__ import annotations

from collections import Counter
import math
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from . import PREDICTED_CAPABILITIES
from .human_review_schema import validate_independent_reviewer_ids


class AgreementMetricError(ValueError):
    pass


def _require_pairs(values_a: Sequence[Any], values_b: Sequence[Any]) -> int:
    if len(values_a) != len(values_b) or not values_a:
        raise AgreementMetricError("agreement inputs must be non-empty and aligned")
    return len(values_a)


def percent_agreement(values_a: Sequence[Any], values_b: Sequence[Any]) -> float:
    count = _require_pairs(values_a, values_b)
    return sum(left == right for left, right in zip(values_a, values_b)) / count


def cohens_kappa(
    values_a: Sequence[Any],
    values_b: Sequence[Any],
    *,
    categories: Iterable[Any] | None = None,
) -> dict[str, Any]:
    count = _require_pairs(values_a, values_b)
    universe = tuple(
        dict.fromkeys(
            categories if categories is not None else [*values_a, *values_b]
        )
    )
    if not universe:
        raise AgreementMetricError("kappa category universe is empty")
    observed = percent_agreement(values_a, values_b)
    counts_a, counts_b = Counter(values_a), Counter(values_b)
    expected = sum(
        (counts_a.get(category, 0) / count) * (counts_b.get(category, 0) / count)
        for category in universe
    )
    denominator = 1.0 - expected
    if math.isclose(denominator, 0.0, abs_tol=1e-12):
        return {
            "value": None,
            "status": "UNDEFINED_ZERO_VARIANCE",
            "observed_agreement": observed,
            "expected_agreement": expected,
            "record_count": count,
            "diagnostic_only": True,
        }
    return {
        "value": (observed - expected) / denominator,
        "status": "DEFINED",
        "observed_agreement": observed,
        "expected_agreement": expected,
        "record_count": count,
        "diagnostic_only": True,
    }


def quadratic_weighted_kappa(
    values_a: Sequence[int], values_b: Sequence[int], *, minimum: int = 1, maximum: int = 5
) -> dict[str, Any]:
    count = _require_pairs(values_a, values_b)
    if maximum <= minimum:
        raise AgreementMetricError("invalid weighted-kappa scale")
    if any(value < minimum or value > maximum for value in [*values_a, *values_b]):
        raise AgreementMetricError("weighted-kappa value outside frozen scale")
    span_squared = float((maximum - minimum) ** 2)
    observed_disagreement = sum(
        ((left - right) ** 2) / span_squared
        for left, right in zip(values_a, values_b)
    ) / count
    counts_a, counts_b = Counter(values_a), Counter(values_b)
    expected_disagreement = sum(
        (((left - right) ** 2) / span_squared)
        * (counts_a.get(left, 0) / count)
        * (counts_b.get(right, 0) / count)
        for left in range(minimum, maximum + 1)
        for right in range(minimum, maximum + 1)
    )
    if math.isclose(expected_disagreement, 0.0, abs_tol=1e-12):
        return {
            "value": None,
            "status": "UNDEFINED_ZERO_VARIANCE",
            "observed_disagreement": observed_disagreement,
            "expected_disagreement": expected_disagreement,
            "record_count": count,
            "diagnostic_only": True,
        }
    return {
        "value": 1.0 - observed_disagreement / expected_disagreement,
        "status": "DEFINED",
        "observed_disagreement": observed_disagreement,
        "expected_disagreement": expected_disagreement,
        "record_count": count,
        "diagnostic_only": True,
    }


def binary_agreement(values_a: Sequence[bool], values_b: Sequence[bool]) -> dict[str, Any]:
    if len(values_a) != len(values_b):
        raise AgreementMetricError("binary agreement inputs are not aligned")
    if not values_a:
        return {
            "percent_agreement": None,
            "positive_agreement": None,
            "negative_agreement": None,
            "cohens_kappa": {
                "value": None,
                "status": "NO_ELIGIBLE_CASES",
                "record_count": 0,
                "diagnostic_only": True,
            },
            "support_by_reviewer": {
                "reviewer_a_positive": 0,
                "reviewer_b_positive": 0,
                "record_count": 0,
            },
        }
    count = _require_pairs(values_a, values_b)
    both_positive = sum(left and right for left, right in zip(values_a, values_b))
    a_only = sum(left and not right for left, right in zip(values_a, values_b))
    b_only = sum(not left and right for left, right in zip(values_a, values_b))
    both_negative = sum(not left and not right for left, right in zip(values_a, values_b))
    positive_denominator = 2 * both_positive + a_only + b_only
    negative_denominator = 2 * both_negative + a_only + b_only
    return {
        "percent_agreement": (both_positive + both_negative) / count,
        "positive_agreement": (
            (2 * both_positive) / positive_denominator
            if positive_denominator
            else None
        ),
        "negative_agreement": (
            (2 * both_negative) / negative_denominator
            if negative_denominator
            else None
        ),
        "cohens_kappa": cohens_kappa(
            values_a, values_b, categories=(False, True)
        ),
        "support_by_reviewer": {
            "reviewer_a_positive": sum(values_a),
            "reviewer_b_positive": sum(values_b),
            "record_count": count,
        },
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def set_agreement(
    sets_a: Sequence[set[str]], sets_b: Sequence[set[str]]
) -> dict[str, Any]:
    if len(sets_a) != len(sets_b):
        raise AgreementMetricError("set agreement inputs are not aligned")
    if not sets_a:
        return {
            "exact_set_agreement": None,
            "mean_jaccard_similarity": None,
            "median_jaccard_similarity": None,
            "record_count": 0,
        }
    count = _require_pairs(sets_a, sets_b)
    similarities = [_jaccard(left, right) for left, right in zip(sets_a, sets_b)]
    return {
        "exact_set_agreement": sum(left == right for left, right in zip(sets_a, sets_b))
        / count,
        "mean_jaccard_similarity": mean(similarities),
        "median_jaccard_similarity": median(similarities),
        "record_count": count,
    }


def _aligned_rows(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    by_a = {str(row["case_id"]): row for row in rows_a}
    by_b = {str(row["case_id"]): row for row in rows_b}
    if len(by_a) != len(rows_a) or len(by_b) != len(rows_b) or set(by_a) != set(by_b):
        raise AgreementMetricError("reviewer packets have non-identical case identity")
    ordered_ids = sorted(by_a)
    return [by_a[key] for key in ordered_ids], [by_b[key] for key in ordered_ids]


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def _boolean(row: Mapping[str, Any], field: str) -> bool:
    value = _text(row, field)
    if value not in {"YES", "NO"}:
        raise AgreementMetricError(f"binary annotation is incomplete: {field}")
    return value == "YES"


def _optional_boolean(row: Mapping[str, Any], field: str) -> bool | None:
    value = _text(row, field)
    if not value:
        return None
    if value not in {"YES", "NO"}:
        raise AgreementMetricError(f"binary annotation is invalid: {field}")
    return value == "YES"


def _capability_set(row: Mapping[str, Any]) -> set[str]:
    return {
        capability
        for capability in PREDICTED_CAPABILITIES
        if _boolean(row, capability)
    }


def _forbidden_set(row: Mapping[str, Any]) -> set[str]:
    return {
        value.strip()
        for value in _text(row, "forbidden_capabilities").split(";")
        if value.strip()
    }


def calculate_full_agreement(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Calculate all required metrics only after two human packets close."""

    reviewer_a, reviewer_b = validate_independent_reviewer_ids(rows_a, rows_b)
    aligned_a, aligned_b = _aligned_rows(rows_a, rows_b)

    def categorical(field: str, categories: Sequence[str]) -> dict[str, Any]:
        left = [_text(row, field) for row in aligned_a]
        right = [_text(row, field) for row in aligned_b]
        return {
            "percent_agreement": percent_agreement(left, right),
            "cohens_kappa": cohens_kappa(left, right, categories=categories),
        }

    context_pairs = [
        (left, right)
        for row_a, row_b in zip(aligned_a, aligned_b)
        if (left := _optional_boolean(row_a, "context_resolution_required"))
        is not None
        and (right := _optional_boolean(row_b, "context_resolution_required"))
        is not None
    ]
    context_left = [left for left, _ in context_pairs]
    context_right = [right for _, right in context_pairs]
    capabilities: dict[str, Any] = {}
    total_matches = 0
    total_comparisons = 0
    for capability in PREDICTED_CAPABILITIES:
        pairs = [
            (left, right)
            for row_a, row_b in zip(aligned_a, aligned_b)
            if (left := _optional_boolean(row_a, capability)) is not None
            and (right := _optional_boolean(row_b, capability)) is not None
        ]
        left = [value for value, _ in pairs]
        right = [value for _, value in pairs]
        capabilities[capability] = binary_agreement(left, right)
        total_matches += sum(a == b for a, b in zip(left, right))
        total_comparisons += len(pairs)

    complete_set_pairs = [
        (_capability_set(row_a), _capability_set(row_b))
        for row_a, row_b in zip(aligned_a, aligned_b)
        if all(_optional_boolean(row_a, capability) is not None for capability in PREDICTED_CAPABILITIES)
        and all(_optional_boolean(row_b, capability) is not None for capability in PREDICTED_CAPABILITIES)
    ]
    capability_sets_a = [left for left, _ in complete_set_pairs]
    capability_sets_b = [right for _, right in complete_set_pairs]
    forbidden_sets_a = [_forbidden_set(row) for row in aligned_a]
    forbidden_sets_b = [_forbidden_set(row) for row in aligned_b]
    return {
        "schema_version": "human-agreement-results-v1",
        "record_count": len(aligned_a),
        "reviewer_ids": [reviewer_a, reviewer_b],
        "case_validity": categorical(
            "case_validity",
            ("INCLUDE_VALID_CASE", "EXCLUDE_INVALID_CASE", "UNCERTAIN"),
        ),
        "query_naturalness_1_to_5": {
            "quadratic_weighted_kappa": quadratic_weighted_kappa(
                [int(_text(row, "query_naturalness_1_to_5")) for row in aligned_a],
                [int(_text(row, "query_naturalness_1_to_5")) for row in aligned_b],
            )
        },
        "context_sufficient": categorical(
            "context_sufficient", ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN")
        ),
        "capability_unambiguous": categorical(
            "capability_unambiguous", ("YES", "NO", "UNCERTAIN")
        ),
        "context_resolution_required": binary_agreement(context_left, context_right),
        "capabilities": capabilities,
        "capability_set": {
            **set_agreement(capability_sets_a, capability_sets_b),
            "all_capability_micro_agreement": (
                total_matches / total_comparisons if total_comparisons else None
            ),
            "all_capability_micro_comparison_count": total_comparisons,
        },
        "forbidden_capability_set": set_agreement(
            forbidden_sets_a, forbidden_sets_b
        ),
        "kappa_interpretation": "DIAGNOSTIC_ONLY",
    }


def human_agreement_contract_document() -> dict[str, Any]:
    capability_metrics = [
        "PERCENT_AGREEMENT",
        "POSITIVE_AGREEMENT",
        "NEGATIVE_AGREEMENT",
        "COHENS_KAPPA",
        "SUPPORT_BY_REVIEWER",
    ]
    return {
        "schema_version": "human-agreement-contract-v1",
        "stage": "RQ2-A-R1",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "calculation_authorised_before_both_packets_frozen": False,
        "case_validity_metrics": ["PERCENT_AGREEMENT", "COHENS_KAPPA"],
        "naturalness_metric": "QUADRATIC_WEIGHTED_KAPPA",
        "context_sufficient_metrics": ["PERCENT_AGREEMENT", "COHENS_KAPPA"],
        "capability_unambiguous_metrics": [
            "PERCENT_AGREEMENT",
            "COHENS_KAPPA",
        ],
        "context_resolution_required_metrics": capability_metrics[:-1],
        "per_capability_metrics": {
            capability: capability_metrics for capability in PREDICTED_CAPABILITIES
        },
        "capability_set_metrics": [
            "EXACT_SET_AGREEMENT",
            "MEAN_JACCARD_SIMILARITY",
            "MEDIAN_JACCARD_SIMILARITY",
            "ALL_CAPABILITY_MICRO_AGREEMENT",
        ],
        "forbidden_capability_set_metrics": [
            "EXACT_SET_AGREEMENT",
            "MEAN_JACCARD_SIMILARITY",
            "MEDIAN_JACCARD_SIMILARITY",
        ],
        "single_overall_kappa_sufficient": False,
        "kappa_role": "DIAGNOSTIC_ONLY",
        "zero_variance_kappa_policy": "RETURN_NULL_WITH_UNDEFINED_ZERO_VARIANCE_STATUS",
        "missing_optional_capability_label_policy": (
            "PAIRWISE_COMPLETE_WITH_EXPLICIT_RECORD_COUNT"
        ),
        "low_kappa_alone_may_delete_case": False,
        "low_kappa_alone_may_change_label": False,
        "kappa_paradox_acknowledged": True,
    }
