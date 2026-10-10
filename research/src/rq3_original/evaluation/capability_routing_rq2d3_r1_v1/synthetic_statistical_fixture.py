"""Completely synthetic 24x2 fixtures for D3-R1 statistical validation."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    evaluate_capability_predictions,
)

from . import CAPABILITIES, METRIC_IMPLEMENTATION_SHA256, REGISTERED_BOOTSTRAP_METRICS
from .cluster_bootstrap import MetricCallbackBindingV1


def synthetic_24x2_fixture_v1() -> dict[str, Any]:
    groups: list[tuple[str, tuple[str, str]]] = []
    gold: dict[str, frozenset[str]] = {}
    left: dict[str, frozenset[str]] = {}
    right: dict[str, frozenset[str]] = {}
    for index in range(24):
        group_id = f"SYN-GROUP-{index + 1:04d}"
        case_a = f"SYN-CASE-{index + 1:04d}-A"
        case_b = f"SYN-CASE-{index + 1:04d}-B"
        groups.append((group_id, (case_a, case_b)))
        primary = CAPABILITIES[index % len(CAPABILITIES)]
        secondary = CAPABILITIES[(index + 1) % len(CAPABILITIES)]
        gold[case_a] = frozenset({primary})
        gold[case_b] = frozenset({primary, secondary})
        if index % 4 == 0:
            left[case_a], left[case_b] = gold[case_a], gold[case_b]
            right[case_a], right[case_b] = frozenset(), frozenset({primary})
        elif index % 4 == 1:
            left[case_a], left[case_b] = frozenset({primary}), frozenset({primary})
            right[case_a], right[case_b] = gold[case_a], gold[case_b]
        elif index % 4 == 2:
            left[case_a], left[case_b] = gold[case_a], frozenset({secondary})
            right[case_a], right[case_b] = frozenset({secondary}), gold[case_b]
        else:
            left[case_a], left[case_b] = gold[case_a], gold[case_b]
            right[case_a], right[case_b] = gold[case_a], gold[case_b]
    return {
        "groups": tuple(groups),
        "gold": gold,
        "left": left,
        "right": right,
    }


def all_tie_fixture_v1() -> dict[str, Any]:
    fixture = synthetic_24x2_fixture_v1()
    return {**fixture, "right": dict(fixture["left"])}


def frozen_metric_binding_v1() -> MetricCallbackBindingV1:
    cache: list[tuple[Sequence[Mapping[str, Any]], dict[str, Any]]] = []

    def evaluate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        for candidate, result in cache:
            if candidate is rows:
                return result
        result = evaluate_capability_predictions(rows)
        cache.append((rows, result))
        if len(cache) > 2:
            cache.pop(0)
        return result

    keys = {
        "SIX_CAPABILITY_MACRO_F1": "macro_f1_all_six",
        "EXACT_SET_ACCURACY": "exact_set_accuracy",
        "REQUIRED_CAPABILITY_RECALL": "required_capability_recall",
        "UNNECESSARY_CAPABILITY_RATE": "unnecessary_capability_rate",
    }
    callbacks = {
        name: (lambda rows, result_key=result_key: float(evaluate(rows)[result_key]))
        for name, result_key in keys.items()
    }
    if tuple(callbacks) != REGISTERED_BOOTSTRAP_METRICS:
        raise RuntimeError("synthetic callback order mismatch")
    return MetricCallbackBindingV1(
        binding_id="RQ2B_FROZEN_CAPABILITY_METRICS_V1",
        implementation_sha256=METRIC_IMPLEMENTATION_SHA256,
        callbacks=callbacks,
        synthetic_test_only=False,
    )


def synthetic_metric_binding_v1() -> MetricCallbackBindingV1:
    """Lightweight callbacks used only to validate resampling mechanics."""

    def exact(rows: Sequence[Mapping[str, Any]]) -> float:
        return sum(
            set(row["gold_capabilities"]) == set(row["predicted_capabilities"])
            for row in rows
        ) / len(rows)

    def required(rows: Sequence[Mapping[str, Any]]) -> float:
        found = sum(
            len(set(row["gold_capabilities"]) & set(row["predicted_capabilities"]))
            for row in rows
        )
        total = sum(len(set(row["gold_capabilities"])) for row in rows)
        return found / total if total else 0.0

    def unnecessary(rows: Sequence[Mapping[str, Any]]) -> float:
        extra = sum(
            len(set(row["predicted_capabilities"]) - set(row["gold_capabilities"]))
            for row in rows
        )
        predicted = sum(len(set(row["predicted_capabilities"])) for row in rows)
        return extra / predicted if predicted else 0.0

    callbacks = {
        "SIX_CAPABILITY_MACRO_F1": exact,
        "EXACT_SET_ACCURACY": exact,
        "REQUIRED_CAPABILITY_RECALL": required,
        "UNNECESSARY_CAPABILITY_RATE": unnecessary,
    }
    return MetricCallbackBindingV1(
        binding_id="SYNTHETIC_TEST_ONLY_RESAMPLING_CALLBACKS_V1",
        implementation_sha256="SYNTHETIC_TEST_ONLY",
        callbacks=callbacks,
        synthetic_test_only=True,
    )


def synthetic_fixture_manifest_v1() -> dict[str, Any]:
    fixture = synthetic_24x2_fixture_v1()
    return {
        "fixture_id": "RQ2_D3_R1_SYNTHETIC_STATISTICAL_FIXTURE_V1",
        "synthetic": True,
        "group_count": len(fixture["groups"]),
        "cases_per_group": 2,
        "case_count": len(fixture["gold"]),
        "uses_real_track_b_case_ids": False,
        "uses_real_track_b_group_ids": False,
        "uses_track_b_text_labels_predictions_or_metrics": False,
        "includes_all_tie_fixture": True,
        "includes_positive_negative_and_zero_cluster_deltas": True,
        "includes_multilabel_partial_overlap": True,
        "includes_both_empty": True,
        "includes_holm_tie_fixture": True,
        "includes_deterministic_bootstrap_fixture": True,
    }
