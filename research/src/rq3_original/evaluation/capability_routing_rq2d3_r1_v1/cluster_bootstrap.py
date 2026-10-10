"""Whole-cluster bootstrap and explicit Type-7 percentile intervals."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import random
from typing import Any, Callable, Mapping, Sequence

from . import (
    BOOTSTRAP_GROUP_COUNT,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CASES_PER_GROUP,
    METRIC_IMPLEMENTATION_SHA256,
    REGISTERED_BOOTSTRAP_METRICS,
)


MetricCallback = Callable[[Sequence[Mapping[str, Any]]], float]


@dataclass(frozen=True)
class MetricCallbackBindingV1:
    binding_id: str
    implementation_sha256: str
    callbacks: Mapping[str, MetricCallback]
    synthetic_test_only: bool = False


def validate_metric_binding_v1(binding: MetricCallbackBindingV1) -> None:
    if tuple(binding.callbacks) != REGISTERED_BOOTSTRAP_METRICS:
        raise ValueError("metric callbacks must match the four frozen metrics in order")
    if binding.synthetic_test_only:
        if not binding.binding_id.startswith("SYNTHETIC_TEST_ONLY_"):
            raise ValueError("synthetic metric binding must be explicitly marked")
    elif binding.implementation_sha256 != METRIC_IMPLEMENTATION_SHA256:
        raise ValueError("metric callback implementation identity mismatch")


def type7_quantile_v1(sorted_values: Sequence[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("at least one sorted value is required")
    values = [float(value) for value in sorted_values]
    if any(values[index] > values[index + 1] for index in range(len(values) - 1)):
        raise ValueError("Type-7 input must already be sorted")
    if not 0.0 <= p <= 1.0:
        raise ValueError("quantile probability must be in [0,1]")
    if len(values) == 1:
        return values[0]
    h = (len(values) - 1) * p
    j = math.floor(h)
    gamma = h - j
    if j == len(values) - 1:
        return values[-1]
    return (1.0 - gamma) * values[j] + gamma * values[j + 1]


def _validate_groups(
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
) -> tuple[tuple[str, tuple[str, str]], ...]:
    if len(ordered_groups) != BOOTSTRAP_GROUP_COUNT:
        raise ValueError("whole-cluster bootstrap requires exactly 24 groups")
    group_ids = [group_id for group_id, _ in ordered_groups]
    if group_ids != sorted(group_ids, key=lambda value: value.encode("utf-8")):
        raise ValueError("groups must be ordered by UTF-8 group ID")
    if len(set(group_ids)) != BOOTSTRAP_GROUP_COUNT:
        raise ValueError("group IDs must be unique")
    seen: set[str] = set()
    normalised: list[tuple[str, tuple[str, str]]] = []
    for group_id, case_ids in ordered_groups:
        if len(case_ids) != CASES_PER_GROUP or len(set(case_ids)) != CASES_PER_GROUP:
            raise ValueError("each group must contain exactly two unique cases")
        ordered_cases = tuple(sorted(case_ids, key=lambda value: value.encode("utf-8")))
        if seen & set(ordered_cases):
            raise ValueError("a case belongs to multiple groups")
        seen.update(ordered_cases)
        normalised.append((group_id, ordered_cases))
    if len(seen) != BOOTSTRAP_GROUP_COUNT * CASES_PER_GROUP:
        raise ValueError("bootstrap grouping does not cover 48 unique cases")
    return tuple(normalised)


def _metric_rows(
    sample_case_ids: Sequence[str],
    predictions: Mapping[str, frozenset[str]],
    gold: Mapping[str, frozenset[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "gold_capabilities": tuple(gold[case_id]),
            "predicted_capabilities": tuple(predictions[case_id]),
            "forbidden_capabilities": (),
            "gold_context_resolution_required": False,
            "predicted_context_resolution_required": False,
        }
        for case_id in sample_case_ids
    ]


def run_whole_cluster_bootstrap_v1(
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    left_predictions: Mapping[str, frozenset[str]],
    right_predictions: Mapping[str, frozenset[str]],
    gold: Mapping[str, frozenset[str]],
    metric_binding: MetricCallbackBindingV1,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    groups = _validate_groups(ordered_groups)
    validate_metric_binding_v1(metric_binding)
    case_ids = {case_id for _, cases in groups for case_id in cases}
    if not case_ids or set(left_predictions) != case_ids or set(right_predictions) != case_ids or set(gold) != case_ids:
        raise ValueError("prediction/Gold identities must exactly match all grouped cases")
    if resamples <= 0:
        raise ValueError("resample count must be positive")
    rng = random.Random()
    rng.seed(seed, version=2)
    distributions = {name: [] for name in REGISTERED_BOOTSTRAP_METRICS}
    group_selection_count = 0
    case_slot_count = 0
    repeated_group_draw_count = 0
    for _ in range(resamples):
        selected_indices = [rng.randrange(BOOTSTRAP_GROUP_COUNT) for _ in range(BOOTSTRAP_GROUP_COUNT)]
        group_selection_count += len(selected_indices)
        repeated_group_draw_count += len(selected_indices) - len(set(selected_indices))
        sample_case_ids = [case_id for index in selected_indices for case_id in groups[index][1]]
        case_slot_count += len(sample_case_ids)
        left_rows = _metric_rows(sample_case_ids, left_predictions, gold)
        right_rows = _metric_rows(sample_case_ids, right_predictions, gold)
        for name, callback in metric_binding.callbacks.items():
            distributions[name].append(float(callback(left_rows)) - float(callback(right_rows)))
    summaries: dict[str, Any] = {}
    for name, values in distributions.items():
        ordered = sorted(values)
        encoded = ("\n".join(format(value, ".17g") for value in values) + "\n").encode("ascii")
        summaries[name] = {
            "delta_count": len(values),
            "distribution_sha256": hashlib.sha256(encoded).hexdigest(),
            "lower_95_type7": type7_quantile_v1(ordered, 0.025),
            "upper_95_type7": type7_quantile_v1(ordered, 0.975),
        }
    return {
        "contract_id": "RQ2_TRACK_B_CLUSTER_BOOTSTRAP_TYPE7_V1",
        "group_count": BOOTSTRAP_GROUP_COUNT,
        "cases_per_group": CASES_PER_GROUP,
        "resamples": resamples,
        "seed": seed,
        "rng": "random.Random.seed(version=2)+randrange(24)",
        "group_selection_count": group_selection_count,
        "case_slot_count": case_slot_count,
        "repeated_group_draw_count": repeated_group_draw_count,
        "case_level_sampling_used": False,
        "duplicate_group_draws_retained": True,
        "comparison_direction": "LEFT_MINUS_RIGHT",
        "metric_callback_binding_id": metric_binding.binding_id,
        "metric_callback_implementation_sha256": metric_binding.implementation_sha256,
        "synthetic_metric_binding": metric_binding.synthetic_test_only,
        "metrics": summaries,
        "_distributions": distributions,
    }
