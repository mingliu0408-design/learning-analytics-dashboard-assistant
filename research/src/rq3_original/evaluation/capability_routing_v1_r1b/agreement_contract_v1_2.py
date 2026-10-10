"""Source-stratified v1.2 agreement contract and calculation helpers."""

from __future__ import annotations

from collections import Counter
from statistics import mean, median
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_v1_r1.agreement_metrics import (
    calculate_full_agreement,
    cohens_kappa,
    percent_agreement,
)

from . import PREDICTED_CAPABILITIES
from .human_review_schema_v1_2 import (
    CONTEXT_LINK_VALUES,
    validate_independent_reviewer_ids,
)


class SourceStratifiedAgreementError(ValueError):
    pass


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(row.get(field) or "").strip()


def _align(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    by_a = {_text(row, "review_case_id"): row for row in rows_a}
    by_b = {_text(row, "review_case_id"): row for row in rows_b}
    if len(by_a) != len(rows_a) or len(by_b) != len(rows_b) or set(by_a) != set(by_b):
        raise SourceStratifiedAgreementError("packets are not aligned by review_case_id")
    ids = sorted(by_a)
    return [by_a[key] for key in ids], [by_b[key] for key in ids]


def _as_v11(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{**dict(row), "case_id": _text(row, "review_case_id")} for row in rows]


def _context_link_agreement(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    left = [_text(row, "context_link_valid") for row in rows_a]
    right = [_text(row, "context_link_valid") for row in rows_b]
    return {
        "percent_agreement": percent_agreement(left, right),
        "cohens_kappa": cohens_kappa(left, right, categories=CONTEXT_LINK_VALUES),
    }


def _included_capability_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        if _text(row, "case_validity") == "INCLUDE_VALID_CASE":
            counts.update(
                capability
                for capability in PREDICTED_CAPABILITIES
                if _text(row, capability) == "YES"
            )
    return {capability: counts[capability] for capability in PREDICTED_CAPABILITIES}


def _metrics(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    value = calculate_full_agreement(_as_v11(rows_a), _as_v11(rows_b))
    value["context_link_valid"] = _context_link_agreement(rows_a, rows_b)
    value["included_case_capability_distribution_by_reviewer"] = {
        "reviewer_a": _included_capability_distribution(rows_a),
        "reviewer_b": _included_capability_distribution(rows_b),
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
        raise SourceStratifiedAgreementError("source mapping does not cover packet IDs")
    result: dict[str, Any] = {
        "schema_version": "human-agreement-results-v1.2",
        "overall_60": _metrics(aligned_a, aligned_b),
        "by_source": {},
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
            raise SourceStratifiedAgreementError("source subset count mismatch")
        result["by_source"][source] = _metrics(subset_a, subset_b)
    return result


def descriptive_source_comparison(
    adjudicated_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in ("authentic", "synthetic"):
        rows = [row for row in adjudicated_rows if _text(row, "source_bank") == source]
        if not rows:
            raise SourceStratifiedAgreementError("adjudicated source subset is empty")
        naturalness = [int(_text(row, "query_naturalness_1_to_5")) for row in rows]
        included = [row for row in rows if _text(row, "case_validity") == "INCLUDE_VALID_CASE"]
        capability_counts = Counter(
            capability
            for row in included
            for capability in PREDICTED_CAPABILITIES
            if _text(row, capability) == "YES"
        )
        result[source] = {
            "mean_naturalness": mean(naturalness),
            "median_naturalness": median(naturalness),
            "validity_inclusion_rate": len(included) / len(rows),
            "capability_prevalence": {
                capability: capability_counts[capability] / len(rows)
                for capability in PREDICTED_CAPABILITIES
            },
            "context_resolution_prevalence": sum(
                _text(row, "context_resolution_required") == "YES" for row in included
            )
            / len(rows),
            "multi_capability_prevalence": sum(
                sum(_text(row, capability) == "YES" for capability in PREDICTED_CAPABILITIES)
                >= 2
                for row in included
            )
            / len(rows),
        }
    return {"role": "DESCRIPTIVE_ONLY", "by_source": result}


def human_agreement_contract_document() -> dict[str, Any]:
    existing_metrics = [
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
    ]
    source_metrics = [
        "VALIDITY_AGREEMENT",
        "NATURALNESS_WEIGHTED_KAPPA",
        "CONTEXT_LINK_AGREEMENT",
        "CONTEXT_RESOLUTION_AGREEMENT",
        "PER_CAPABILITY_AGREEMENT",
        "EXACT_SET_AGREEMENT",
        "JACCARD",
        "INCLUDED_CASE_CAPABILITY_DISTRIBUTION",
    ]
    return {
        "schema_version": "human-agreement-contract-v1.2",
        "stage": "RQ2-A-R1B",
        "status": "FROZEN_BEFORE_HUMAN_ENTRY",
        "calculation_before_both_packets_frozen": False,
        "overall_60_metrics": existing_metrics,
        "authentic_25_metrics": source_metrics,
        "synthetic_35_metrics": source_metrics,
        "source_comparison_after_gold_freeze": [
            "MEAN_AND_MEDIAN_NATURALNESS",
            "VALIDITY_INCLUSION_RATE",
            "CAPABILITY_PREVALENCE",
            "CONTEXT_RESOLUTION_PREVALENCE",
            "MULTI_CAPABILITY_PREVALENCE",
        ],
        "source_comparison_role": "DESCRIPTIVE_ONLY",
        "automatic_source_based_deletion": False,
        "source_identity_visible_during_first_round": False,
        "single_overall_kappa_sufficient": False,
        "kappa_role": "DIAGNOSTIC_ONLY",
        "low_kappa_alone_may_delete_case": False,
        "low_kappa_alone_may_change_label": False,
        "zero_variance_kappa_policy": "RETURN_NULL_WITH_STATUS",
    }
