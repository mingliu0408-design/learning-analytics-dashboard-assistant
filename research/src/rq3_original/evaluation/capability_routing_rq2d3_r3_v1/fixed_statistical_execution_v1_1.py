"""Non-overridable D3-R1 statistics plus observed complete-metric deltas."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d3_r2_v1.fixed_statistical_execution import (
    run_fixed_primary_and_secondary_statistics_v1,
    run_fixed_synthetic_statistics_v1,
    verify_frozen_statistical_sources_v1,
)

from . import COMPARISONS, D3_R1_STATISTICAL_SHA256


DELTA_KEYS = (
    "macro_f1_all_six",
    "exact_set_accuracy",
    "required_capability_recall",
    "unnecessary_capability_rate",
)


def _run(
    *,
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
    method_metrics: Mapping[str, Mapping[str, Any]],
    synthetic: bool,
) -> dict[str, Any]:
    verify_frozen_statistical_sources_v1()
    base = (
        run_fixed_synthetic_statistics_v1(
            ordered_groups=ordered_groups,
            predictions_by_method=predictions_by_method,
            gold_by_id=gold_by_id,
        )
        if synthetic
        else run_fixed_primary_and_secondary_statistics_v1(
            ordered_groups=ordered_groups,
            predictions_by_method=predictions_by_method,
            gold_by_id=gold_by_id,
        )
    )
    for comparison in COMPARISONS:
        left, right = comparison.split("_VS_")
        base["comparisons"][comparison]["observed_deltas"] = {
            key: float(method_metrics[left][key]) - float(method_metrics[right][key])
            for key in DELTA_KEYS
        }
    return base


def run_fixed_track_b_statistics_v1_1(
    *,
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
    method_metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return _run(
        ordered_groups=ordered_groups,
        predictions_by_method=predictions_by_method,
        gold_by_id=gold_by_id,
        method_metrics=method_metrics,
        synthetic=False,
    )


def run_fixed_synthetic_statistics_v1_1(
    *,
    ordered_groups: Sequence[tuple[str, tuple[str, str]]],
    predictions_by_method: Mapping[str, Mapping[str, frozenset[str]]],
    gold_by_id: Mapping[str, frozenset[str]],
    method_metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return _run(
        ordered_groups=ordered_groups,
        predictions_by_method=predictions_by_method,
        gold_by_id=gold_by_id,
        method_metrics=method_metrics,
        synthetic=True,
    )


def fixed_statistical_contract_document_v1_1() -> dict[str, object]:
    identities = verify_frozen_statistical_sources_v1()
    return {
        "schema_version": "track-b-fixed-statistical-execution-contract-v1-1",
        "status": "FROZEN",
        "effective_contract_sha256": D3_R1_STATISTICAL_SHA256,
        "source_identities": identities,
        "real_interface": (
            "run_fixed_track_b_statistics_v1_1(*, ordered_groups, "
            "predictions_by_method, gold_by_id, method_metrics)"
        ),
        "caller_overridable_parameters": [],
        "primary": "P1_VS_B1",
        "secondary_holm": ["B1_VS_B0", "P1_VS_B0"],
        "sign_flip_draws": 100000,
        "sign_flip_seed": 20260829,
        "bootstrap_resamples": 50000,
        "bootstrap_seed": 20260828,
        "quantile": "LINEAR_TYPE_7",
        "observed_delta_keys": list(DELTA_KEYS),
        "real_and_synthetic_entries_separate": True,
    }
