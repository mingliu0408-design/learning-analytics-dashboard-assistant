"""Family-cluster paired bootstrap diagnostics for Synthetic35."""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence

from .capability_metrics import evaluate_capability_predictions


BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 20_260_827
METRIC_KEYS = (
    "macro_f1_all_six",
    "exact_set_accuracy",
    "required_capability_recall",
    "unnecessary_capability_rate",
)


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("empty bootstrap distribution")
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    )


def family_cluster_paired_bootstrap(
    *,
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    family_by_id: Mapping[str, str],
    comparison_id: str,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Resample frozen scenario families and compute paired A-minus-B deltas."""

    by_a = {str(row["review_case_id"]): dict(row) for row in rows_a}
    by_b = {str(row["review_case_id"]): dict(row) for row in rows_b}
    if set(by_a) != set(by_b) or set(by_a) != set(family_by_id):
        raise ValueError("paired bootstrap identity mismatch")
    families = sorted(set(family_by_id.values()))
    if len(families) != 18:
        raise ValueError("paired bootstrap requires 18 frozen scenario families")
    ids_by_family = {
        family: sorted(
            case_id for case_id, value in family_by_id.items() if value == family
        )
        for family in families
    }
    point_a = evaluate_capability_predictions(list(by_a.values()))
    point_b = evaluate_capability_predictions(list(by_b.values()))
    point_delta = {
        key: float(point_a[key]) - float(point_b[key]) for key in METRIC_KEYS
    }
    rng = random.Random(seed)
    distributions = {key: [] for key in METRIC_KEYS}
    for _ in range(resamples):
        sampled_families = [rng.choice(families) for _ in families]
        sampled_ids = [
            case_id
            for family in sampled_families
            for case_id in ids_by_family[family]
        ]
        sample_a = evaluate_capability_predictions([by_a[case_id] for case_id in sampled_ids])
        sample_b = evaluate_capability_predictions([by_b[case_id] for case_id in sampled_ids])
        for key in METRIC_KEYS:
            distributions[key].append(float(sample_a[key]) - float(sample_b[key]))
    intervals: dict[str, Any] = {}
    for key, values in distributions.items():
        ordered = sorted(values)
        intervals[key] = {
            "delta_a_minus_b": point_delta[key],
            "ci_95_percentile": [
                _percentile(ordered, 0.025),
                _percentile(ordered, 0.975),
            ],
        }
    return {
        "comparison_id": comparison_id,
        "model_a_minus_model_b": True,
        "resampling_unit": "scenario_family",
        "family_count": len(families),
        "resamples": resamples,
        "seed": seed,
        "ci": "95_PERCENTILE",
        "development_diagnostic_only": True,
        "confirmatory_significance_test": False,
        "metrics": intervals,
    }


def development_uncertainty_report(
    *,
    p1_rows: Sequence[Mapping[str, Any]],
    b0_rows: Sequence[Mapping[str, Any]],
    b1_rows: Sequence[Mapping[str, Any]],
    family_by_id: Mapping[str, str],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    comparisons = [
        family_cluster_paired_bootstrap(
            rows_a=p1_rows,
            rows_b=b0_rows,
            family_by_id=family_by_id,
            comparison_id="P1_NESTED_OOF_MINUS_B0",
            resamples=resamples,
            seed=seed,
        ),
        family_cluster_paired_bootstrap(
            rows_a=p1_rows,
            rows_b=b1_rows,
            family_by_id=family_by_id,
            comparison_id="P1_NESTED_OOF_MINUS_B1",
            resamples=resamples,
            seed=seed,
        ),
        family_cluster_paired_bootstrap(
            rows_a=b1_rows,
            rows_b=b0_rows,
            family_by_id=family_by_id,
            comparison_id="B1_MINUS_B0",
            resamples=resamples,
            seed=seed,
        ),
    ]
    return {
        "schema_version": "rq2b-development-uncertainty-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "role": "DEVELOPMENT_DIAGNOSTIC_ONLY",
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "policy_grid_modified": False,
        "gold_modified": False,
    }
