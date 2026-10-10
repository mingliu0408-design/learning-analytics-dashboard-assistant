"""Aggregate-only error analysis for frozen RQ2-D4 predictions."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    evaluate_capability_predictions,
)
from evaluation.capability_routing_rq2d3_r1_v1.exact_set_utility import (
    exact_jaccard_utility_v1,
)

from . import CAPABILITIES, COMPARISONS, METHODS, capability_order


def _sets(row: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    return (
        frozenset(row["gold_capabilities"]),
        frozenset(row["predicted_capabilities"]),
    )


def capability_set_error_summary(
    rows: Sequence[Mapping[str, Any]], *, transition_limit: int = 12
) -> dict[str, Any]:
    counts = Counter(exact=0, under_prediction=0, over_prediction=0, mixed_error=0)
    transitions: Counter[tuple[tuple[str, ...], tuple[str, ...]]] = Counter()
    for row in rows:
        gold, predicted = _sets(row)
        if gold == predicted:
            counts["exact"] += 1
        elif predicted < gold:
            counts["under_prediction"] += 1
        elif gold < predicted:
            counts["over_prediction"] += 1
        else:
            counts["mixed_error"] += 1
        if gold != predicted:
            transitions[(tuple(capability_order(gold)), tuple(capability_order(predicted)))] += 1
    common = [
        {
            "gold_capabilities": list(gold),
            "predicted_capabilities": list(predicted),
            "count": count,
        }
        for (gold, predicted), count in sorted(
            transitions.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )[:transition_limit]
    ]
    return {
        "record_count": len(rows),
        "exact_set_correct_count": counts["exact"],
        "under_prediction_count": counts["under_prediction"],
        "over_prediction_count": counts["over_prediction"],
        "mixed_error_count": counts["mixed_error"],
        "most_common_gold_to_prediction_transitions": common,
    }


def context_subset_summary(
    rows_by_method: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for subset_name, expected, expected_count in (
        ("CONTEXT_RESOLUTION_REQUIRED_YES", True, 39),
        ("CONTEXT_RESOLUTION_REQUIRED_NO", False, 9),
    ):
        method_metrics: dict[str, Any] = {}
        for method in METHODS:
            subset = [
                row
                for row in rows_by_method[method]
                if bool(row["gold_context_resolution_required"]) is expected
            ]
            if len(subset) != expected_count:
                raise RuntimeError("BLOCKED_RQ2_D4_METRIC_OR_STATISTICAL_FAILURE")
            metrics = evaluate_capability_predictions(subset)
            method_metrics[method] = {
                "record_count": len(subset),
                "macro_f1_all_six": metrics["macro_f1_all_six"],
                "exact_set_accuracy": metrics["exact_set_accuracy"],
                "required_capability_recall": metrics["required_capability_recall"],
                "unnecessary_capability_rate": metrics["unnecessary_capability_rate"],
            }
        result[subset_name] = {
            "record_count": expected_count,
            "methods": method_metrics,
        }
    return result


def clarification_summary(
    rows_by_method: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    result: dict[str, Any] = {"gold_clarification_case_count": 4, "methods": {}}
    for method in METHODS:
        rows = rows_by_method[method]
        positives = [row for row in rows if "clarification" in row["gold_capabilities"]]
        negatives = [row for row in rows if "clarification" not in row["gold_capabilities"]]
        if len(positives) != 4 or len(negatives) != 44:
            raise RuntimeError("BLOCKED_RQ2_D4_METRIC_OR_STATISTICAL_FAILURE")
        true_positive = sum(
            "clarification" in row["predicted_capabilities"] for row in positives
        )
        false_positive = sum(
            "clarification" in row["predicted_capabilities"] for row in negatives
        )
        result["methods"][method] = {
            "clarification_recall": true_positive / 4,
            "true_positive_count": true_positive,
            "false_negative_count": 4 - true_positive,
            "non_clarification_case_count": 44,
            "unnecessary_clarification_count": false_positive,
            "unnecessary_clarification_rate": false_positive / 44,
        }
    return result


def contrast_pair_consistency(
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for comparison in COMPARISONS:
        left, right = comparison.split("_VS_")
        categories = Counter(
            both_improved=0,
            one_improved_one_declined=0,
            both_declined=0,
            all_tie=0,
            one_improved_one_tied=0,
            one_declined_one_tied=0,
        )
        for _, case_ids in ordered_groups:
            signs: list[int] = []
            for case_id in case_ids:
                delta: Fraction = exact_jaccard_utility_v1(
                    predictions_by_method[left][case_id], gold_by_id[case_id]
                ) - exact_jaccard_utility_v1(
                    predictions_by_method[right][case_id], gold_by_id[case_id]
                )
                signs.append(1 if delta > 0 else -1 if delta < 0 else 0)
            if signs == [1, 1]:
                categories["both_improved"] += 1
            elif signs == [-1, -1]:
                categories["both_declined"] += 1
            elif signs == [0, 0]:
                categories["all_tie"] += 1
            elif 1 in signs and -1 in signs:
                categories["one_improved_one_declined"] += 1
            elif 1 in signs:
                categories["one_improved_one_tied"] += 1
            else:
                categories["one_declined_one_tied"] += 1
        result[comparison] = {
            "group_count": 24,
            **{name: int(categories[name]) for name in categories},
            "diagnostic_only": True,
        }
    return result


def build_error_analysis(
    rows_by_method: Mapping[str, Sequence[Mapping[str, Any]]],
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    return {
        "schema_version": "rq2d4-final-error-summary-v1",
        "status": "FROZEN_AGGREGATE_RESULT",
        "per_method_capability_set_errors": {
            method: capability_set_error_summary(rows_by_method[method])
            for method in METHODS
        },
        "context_subsets": context_subset_summary(rows_by_method),
        "clarification": clarification_summary(rows_by_method),
        "contrast_pair_consistency": contrast_pair_consistency(
            ordered_groups, predictions_by_method, gold_by_id
        ),
        "case_ids_in_output": False,
        "governed_text_in_output": False,
    }
