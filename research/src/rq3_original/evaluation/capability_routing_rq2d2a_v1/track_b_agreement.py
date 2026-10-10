"""Source-blinded agreement aligned only by opaque review_case_id."""

from __future__ import annotations

from collections import Counter
import math
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from . import CAPABILITIES
from .validate_completed_packets import capability_set, forbidden_set


class AgreementError(RuntimeError):
    pass


def _align(
    rows_a: Sequence[Mapping[str, str]], rows_b: Sequence[Mapping[str, str]]
) -> tuple[list[Mapping[str, str]], list[Mapping[str, str]]]:
    by_a = {row["review_case_id"]: row for row in rows_a}
    by_b = {row["review_case_id"]: row for row in rows_b}
    if len(by_a) != len(rows_a) or len(by_b) != len(rows_b) or set(by_a) != set(by_b):
        raise AgreementError("agreement inputs do not align by review_case_id")
    ids = sorted(by_a)
    return [by_a[case_id] for case_id in ids], [by_b[case_id] for case_id in ids]


def percent_agreement(left: Sequence[Any], right: Sequence[Any]) -> float:
    if not left or len(left) != len(right):
        raise AgreementError("agreement vectors must be nonempty and aligned")
    return sum(a == b for a, b in zip(left, right)) / len(left)


def cohens_kappa(
    left: Sequence[Any], right: Sequence[Any], categories: Iterable[Any]
) -> dict[str, Any]:
    observed = percent_agreement(left, right)
    count = len(left)
    categories = tuple(categories)
    counts_left, counts_right = Counter(left), Counter(right)
    expected = sum(
        counts_left[category] / count * counts_right[category] / count
        for category in categories
    )
    denominator = 1.0 - expected
    if math.isclose(denominator, 0.0, abs_tol=1e-12):
        status = (
            "PERFECT_AGREEMENT_ZERO_VARIANCE"
            if math.isclose(observed, 1.0, abs_tol=1e-12)
            else "UNDEFINED_ZERO_VARIANCE"
        )
        value = None
    else:
        status = "DEFINED"
        value = (observed - expected) / denominator
    return {
        "value": value,
        "status": status,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "record_count": count,
        "diagnostic_only": True,
    }


def categorical(
    left: Sequence[str], right: Sequence[str], categories: Sequence[str]
) -> dict[str, Any]:
    return {
        "agreement_count": sum(a == b for a, b in zip(left, right)),
        "record_count": len(left),
        "percent_agreement": percent_agreement(left, right),
        "cohens_kappa": cohens_kappa(left, right, categories),
        "reviewer_support_distribution": {
            "A": {category: Counter(left)[category] for category in categories},
            "B": {category: Counter(right)[category] for category in categories},
        },
    }


def binary(left: Sequence[str], right: Sequence[str]) -> dict[str, Any]:
    value = categorical(left, right, ("NO", "YES"))
    both_yes = sum(a == b == "YES" for a, b in zip(left, right))
    both_no = sum(a == b == "NO" for a, b in zip(left, right))
    a_only = sum(a == "YES" and b == "NO" for a, b in zip(left, right))
    b_only = sum(a == "NO" and b == "YES" for a, b in zip(left, right))
    positive_denominator = 2 * both_yes + a_only + b_only
    negative_denominator = 2 * both_no + a_only + b_only
    value.update(
        {
            "positive_agreement": (
                2 * both_yes / positive_denominator if positive_denominator else None
            ),
            "negative_agreement": (
                2 * both_no / negative_denominator if negative_denominator else None
            ),
            "positive_support": {
                "A": sum(item == "YES" for item in left),
                "B": sum(item == "YES" for item in right),
            },
        }
    )
    return value


def quadratic_weighted_kappa(left: Sequence[int], right: Sequence[int]) -> dict[str, Any]:
    if not left or len(left) != len(right) or any(value not in range(1, 6) for value in (*left, *right)):
        raise AgreementError("invalid naturalness vectors")
    count = len(left)
    counts_left, counts_right = Counter(left), Counter(right)
    observed_disagreement = sum(((a - b) ** 2) / 16 for a, b in zip(left, right)) / count
    expected_disagreement = sum(
        ((a - b) ** 2) / 16 * counts_left[a] / count * counts_right[b] / count
        for a in range(1, 6)
        for b in range(1, 6)
    )
    if math.isclose(expected_disagreement, 0.0, abs_tol=1e-12):
        status = "PERFECT_AGREEMENT_ZERO_VARIANCE"
        value = None
    else:
        status = "DEFINED"
        value = 1.0 - observed_disagreement / expected_disagreement
    return {
        "value": value,
        "status": status,
        "observed_disagreement": observed_disagreement,
        "expected_disagreement": expected_disagreement,
        "record_count": count,
        "diagnostic_only": True,
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def set_agreement(left: Sequence[set[str]], right: Sequence[set[str]]) -> dict[str, Any]:
    similarities = [_jaccard(a, b) for a, b in zip(left, right)]
    return {
        "exact_set_agreement_count": sum(a == b for a, b in zip(left, right)),
        "record_count": len(left),
        "exact_set_agreement": percent_agreement(left, right),
        "mean_jaccard_similarity": mean(similarities),
        "median_jaccard_similarity": median(similarities),
        "empty_empty_jaccard_definition": 1.0,
    }


def calculate_agreement(
    rows_a: Sequence[Mapping[str, str]], rows_b: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    aligned_a, aligned_b = _align(rows_a, rows_b)
    field_categories = {
        "case_validity": ("INCLUDE_VALID_CASE", "EXCLUDE_INVALID_CASE", "UNCERTAIN"),
        "context_link_valid": ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN"),
        "context_sufficient": ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN"),
        "capability_unambiguous": ("YES", "NO", "UNCERTAIN"),
    }
    general = {
        field: categorical(
            [row[field] for row in aligned_a],
            [row[field] for row in aligned_b],
            categories,
        )
        for field, categories in field_categories.items()
    }
    natural_a = [int(row["query_naturalness_1_to_5"]) for row in aligned_a]
    natural_b = [int(row["query_naturalness_1_to_5"]) for row in aligned_b]
    naturalness = {
        "exact_agreement_count": sum(a == b for a, b in zip(natural_a, natural_b)),
        "record_count": len(natural_a),
        "exact_agreement": percent_agreement(natural_a, natural_b),
        "quadratic_weighted_kappa": quadratic_weighted_kappa(natural_a, natural_b),
        "fixed_categories": [1, 2, 3, 4, 5],
    }
    context_resolution = binary(
        [row["context_resolution_required"] for row in aligned_a],
        [row["context_resolution_required"] for row in aligned_b],
    )
    per_capability = {
        capability: binary(
            [row[capability] for row in aligned_a],
            [row[capability] for row in aligned_b],
        )
        for capability in CAPABILITIES
    }
    sets_a = [capability_set(row) for row in aligned_a]
    sets_b = [capability_set(row) for row in aligned_b]
    flat_a = [row[capability] for row in aligned_a for capability in CAPABILITIES]
    flat_b = [row[capability] for row in aligned_b for capability in CAPABILITIES]
    capability_sets = {
        **set_agreement(sets_a, sets_b),
        "all_capability_micro_agreement_count": sum(a == b for a, b in zip(flat_a, flat_b)),
        "all_capability_micro_comparison_count": len(flat_a),
        "all_capability_micro_agreement": percent_agreement(flat_a, flat_b),
        "flattened_binary_cohens_kappa": cohens_kappa(flat_a, flat_b, ("NO", "YES")),
    }
    forbidden_sets = set_agreement(
        [forbidden_set(row) for row in aligned_a],
        [forbidden_set(row) for row in aligned_b],
    )
    return {
        "schema_version": "track-b-inter-reviewer-agreement-v1",
        "stage": "RQ2-D2A",
        "status": "PASS",
        "source_blinded": True,
        "alignment_key": "review_case_id",
        "row_position_alignment_used": False,
        "record_count": 48,
        "reviewer_ids": ["A", "B"],
        **general,
        "query_naturalness_1_to_5": naturalness,
        "context_resolution_required": context_resolution,
        "capabilities": per_capability,
        "capability_set": capability_sets,
        "forbidden_capability_set": forbidden_sets,
        "rationale_reviewer_id_and_date_excluded_from_agreement": True,
        "kappa_role": "DIAGNOSTIC_ONLY",
        "capability_gold_formed": False,
    }


def _close(observed: float | None, expected: float) -> None:
    if observed is None or not math.isclose(observed, expected, abs_tol=1e-12):
        raise AgreementError("BLOCKED_RQ2_D2A_AGREEMENT_REPRODUCTION_MISMATCH")


def validate_expected_agreement(value: Mapping[str, Any]) -> None:
    capability_set_value = value["capability_set"]
    _close(capability_set_value["exact_set_agreement"], 0.9375)
    _close(capability_set_value["all_capability_micro_agreement"], 0.9791666666666666)
    _close(
        capability_set_value["flattened_binary_cohens_kappa"]["value"],
        0.9360521056916585,
    )
    _close(capability_set_value["mean_jaccard_similarity"], 0.9479166666666666)
    _close(capability_set_value["median_jaccard_similarity"], 1.0)
    if value["query_naturalness_1_to_5"]["exact_agreement_count"] != 32:
        raise AgreementError("BLOCKED_RQ2_D2A_AGREEMENT_REPRODUCTION_MISMATCH")
    _close(
        value["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
        0.4722222222222222,
    )
    expected_fields = {
        "context_sufficient": (47, 0.8461538461538458),
        "context_resolution_required": (42, 0.6),
    }
    for field, (agreement_count, kappa) in expected_fields.items():
        if value[field]["agreement_count"] != agreement_count:
            raise AgreementError("BLOCKED_RQ2_D2A_AGREEMENT_REPRODUCTION_MISMATCH")
        _close(value[field]["cohens_kappa"]["value"], kappa)
    expected_capabilities = {
        "dashboard_evidence": (47, 0.9459459459459458),
        "course_retrieval": (46, 0.7767441860465117),
        "episodic_memory": (47, 0.9484978540772531),
        "planning": (48, 1.0),
        "safe_direct_response": (47, 0.9506172839506172),
        "clarification": (47, 0.8461538461538458),
    }
    for capability, (agreement_count, kappa) in expected_capabilities.items():
        observed = value["capabilities"][capability]
        if observed["agreement_count"] != agreement_count:
            raise AgreementError("BLOCKED_RQ2_D2A_AGREEMENT_REPRODUCTION_MISMATCH")
        _close(observed["cohens_kappa"]["value"], kappa)
    forbidden = value["forbidden_capability_set"]
    _close(forbidden["exact_set_agreement"], 0.8958333333333334)
    _close(forbidden["mean_jaccard_similarity"], 0.9166666666666666)
    _close(forbidden["median_jaccard_similarity"], 1.0)
    for field in ("case_validity", "context_link_valid", "capability_unambiguous"):
        kappa = value[field]["cohens_kappa"]
        if kappa["value"] is not None or kappa["status"] != "PERFECT_AGREEMENT_ZERO_VARIANCE":
            raise AgreementError("zero-variance kappa policy mismatch")
