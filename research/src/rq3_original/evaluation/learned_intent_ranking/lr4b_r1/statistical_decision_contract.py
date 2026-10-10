"""Pure, standard-library implementation of the frozen RQ1-C decisions.

This module consumes metrics supplied by a future authorised caller.  It has no
data-path or model-loading code and cannot open final-gold material.
"""

from __future__ import annotations

import itertools
import math
import random
import statistics
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence


FIVE_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)
RANDOMISATION_ALPHA = 0.05
RANDOMISATION_EXACT_NONZERO_LIMIT = 20
RANDOMISATION_MONTE_CARLO_RESAMPLES = 100_000
RANDOMISATION_SEED = 20260825
BOOTSTRAP_RESAMPLES = 50_000
BOOTSTRAP_SEED = 20260826
BOOTSTRAP_CONFIDENCE = 0.95
MACRO_F1_NONINFERIORITY_TOLERANCE = 0.01
WEAK_CLASS_MINIMUM_SUPPORT = 5
WEAK_CLASS_MAXIMUM_F1_DROP = 0.15


class StatisticalContractError(ValueError):
    """Raised for invalid metric-only inputs."""


def _finite_values(values: Iterable[float], role: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result:
        raise StatisticalContractError(f"{role} must be non-empty")
    if any(not math.isfinite(value) for value in result):
        raise StatisticalContractError(f"{role} must contain finite values")
    return result


def paired_deltas(
    m64_reciprocal_ranks: Iterable[float],
    c0_reciprocal_ranks: Iterable[float],
) -> tuple[float, ...]:
    """Return query-aligned RR(M64) - RR(C0) differences."""

    m64 = _finite_values(m64_reciprocal_ranks, "m64 reciprocal ranks")
    c0 = _finite_values(c0_reciprocal_ranks, "c0 reciprocal ranks")
    if len(m64) != len(c0):
        raise StatisticalContractError("paired metric lengths differ")
    return tuple(left - right for left, right in zip(m64, c0, strict=True))


def paired_approximate_randomisation_test(
    m64_reciprocal_ranks: Iterable[float],
    c0_reciprocal_ranks: Iterable[float],
    *,
    monte_carlo_resamples: int = RANDOMISATION_MONTE_CARLO_RESAMPLES,
    random_seed: int = RANDOMISATION_SEED,
) -> dict[str, object]:
    """Two-sided paired sign-flip test with the preregistered correction."""

    deltas = paired_deltas(m64_reciprocal_ranks, c0_reciprocal_ranks)
    nonzero = tuple(value for value in deltas if value != 0.0)
    observed = abs(statistics.fmean(deltas))
    denominator = len(deltas)
    tolerance = 1e-15

    if len(nonzero) <= RANDOMISATION_EXACT_NONZERO_LIMIT:
        method = "EXACT_SIGN_FLIP_ENUMERATION"
        resample_count = 1 << len(nonzero)
        extreme_count = 0
        for signs in itertools.product((-1.0, 1.0), repeat=len(nonzero)):
            permuted = sum(sign * value for sign, value in zip(signs, nonzero, strict=True))
            statistic = abs(permuted / denominator)
            if statistic + tolerance >= observed:
                extreme_count += 1
    else:
        if not isinstance(monte_carlo_resamples, int) or monte_carlo_resamples <= 0:
            raise StatisticalContractError("Monte Carlo resamples must be positive")
        method = "MONTE_CARLO_SIGN_FLIP"
        resample_count = monte_carlo_resamples
        extreme_count = 0
        generator = random.Random(random_seed)
        for _ in range(resample_count):
            permuted = sum(
                value if generator.getrandbits(1) else -value
                for value in nonzero
            )
            statistic = abs(permuted / denominator)
            if statistic + tolerance >= observed:
                extreme_count += 1

    return {
        "method": method,
        "two_sided": True,
        "pair_count": len(deltas),
        "nonzero_pair_count": len(nonzero),
        "observed_absolute_mean_delta_rr": observed,
        "extreme_count": extreme_count,
        "resample_count": resample_count,
        "p_value": (extreme_count + 1) / (resample_count + 1),
        "p_value_correction": "PLUS_ONE_NUMERATOR_AND_DENOMINATOR",
        "random_seed": random_seed if method == "MONTE_CARLO_SIGN_FLIP" else None,
    }


def _linear_percentile(ordered: Sequence[float], probability: float) -> float:
    if not ordered:
        raise StatisticalContractError("percentile input must be non-empty")
    if not 0.0 <= probability <= 1.0:
        raise StatisticalContractError("percentile probability is invalid")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def paired_bootstrap_ci(
    m64_reciprocal_ranks: Iterable[float],
    c0_reciprocal_ranks: Iterable[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    random_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Percentile CI from paired query-level bootstrap resampling."""

    deltas = paired_deltas(m64_reciprocal_ranks, c0_reciprocal_ranks)
    if not isinstance(resamples, int) or resamples <= 0:
        raise StatisticalContractError("bootstrap resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise StatisticalContractError("bootstrap confidence is invalid")
    generator = random.Random(random_seed)
    count = len(deltas)
    estimates = [
        sum(deltas[generator.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    ]
    estimates.sort()
    tail = (1.0 - confidence) / 2.0
    return {
        "method": "PAIRED_QUERY_LEVEL_PERCENTILE_BOOTSTRAP",
        "pair_count": count,
        "resample_count": resamples,
        "confidence": confidence,
        "lower_bound": _linear_percentile(estimates, tail),
        "upper_bound": _linear_percentile(estimates, 1.0 - tail),
        "percentile_interpolation": "LINEAR_TYPE_7",
        "random_seed": random_seed,
    }


def paired_effect_size(
    m64_reciprocal_ranks: Iterable[float],
    c0_reciprocal_ranks: Iterable[float],
) -> dict[str, object]:
    """Return the preregistered paired descriptive and rank-biserial effects."""

    deltas = paired_deltas(m64_reciprocal_ranks, c0_reciprocal_ranks)
    wins = sum(value > 0 for value in deltas)
    ties = sum(value == 0 for value in deltas)
    losses = sum(value < 0 for value in deltas)
    denominator = wins + losses
    return {
        "mean_delta_rr": statistics.fmean(deltas),
        "median_delta_rr": statistics.median(deltas),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "matched_rank_biserial_correlation": (
            (wins - losses) / denominator if denominator else None
        ),
        "matched_rank_biserial_status": (
            "DEFINED" if denominator else "UNDEFINED_ALL_TIES"
        ),
    }


def _decimal_metric(value: object, role: str) -> Decimal:
    if isinstance(value, bool):
        raise StatisticalContractError(f"{role} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise StatisticalContractError(f"{role} must be numeric") from exc
    if not result.is_finite():
        raise StatisticalContractError(f"{role} must be finite")
    return result


def select_representative_seed(seed_metrics: Iterable[Mapping[str, object]]) -> int:
    """Select the mean-nearest View-A seed using the frozen tie-break order."""

    rows = tuple(seed_metrics)
    if len(rows) != len(FIVE_SEEDS):
        raise StatisticalContractError("representative selection requires five seeds")
    parsed: list[tuple[int, Decimal, Decimal, Decimal]] = []
    for row in rows:
        try:
            seed = int(row["seed"])
            mrr = _decimal_metric(row["view_a_mrr"], "View-A MRR")
            top1 = _decimal_metric(row["view_a_top1"], "View-A Top-1")
            macro_f1 = _decimal_metric(row["view_a_macro_f1"], "View-A Macro-F1")
        except KeyError as exc:
            raise StatisticalContractError("representative seed metric field missing") from exc
        parsed.append((seed, mrr, top1, macro_f1))
    seeds = tuple(seed for seed, *_ in parsed)
    if len(set(seeds)) != len(seeds) or set(seeds) != set(FIVE_SEEDS):
        raise StatisticalContractError("representative seed set mismatch")
    mean_mrr = sum((row[1] for row in parsed), Decimal(0)) / Decimal(len(parsed))
    return min(
        parsed,
        key=lambda row: (
            abs(row[1] - mean_mrr),
            -row[2],
            -row[3],
            row[0],
        ),
    )[0]


def primary_statistical_gate(
    *,
    representative_m64_mrr: float,
    c0_mrr: float,
    mean_delta_rr: float,
    bootstrap_lower_bound: float,
    paired_randomisation_p_value: float,
) -> bool:
    return (
        representative_m64_mrr > c0_mrr
        and mean_delta_rr > 0.0
        and bootstrap_lower_bound > 0.0
        and paired_randomisation_p_value < RANDOMISATION_ALPHA
    )


def top1_macro_f1_gate(
    *,
    representative_m64_top1: float,
    c0_top1: float,
    representative_m64_macro_f1: float,
    c0_macro_f1: float,
) -> bool:
    m64_top1 = _decimal_metric(representative_m64_top1, "representative M64 Top-1")
    baseline_top1 = _decimal_metric(c0_top1, "C0 Top-1")
    m64_macro_f1 = _decimal_metric(
        representative_m64_macro_f1,
        "representative M64 Macro-F1",
    )
    baseline_macro_f1 = _decimal_metric(c0_macro_f1, "C0 Macro-F1")
    return (
        m64_top1 >= baseline_top1
        and m64_macro_f1
        >= baseline_macro_f1 - Decimal(str(MACRO_F1_NONINFERIORITY_TOLERANCE))
    )


def weak_class_gate(per_label_metrics: Mapping[str, Mapping[str, object]]) -> bool:
    """Apply hard collapse limits only to labels with final support at least 5."""

    for metrics in per_label_metrics.values():
        support = int(metrics["support"])
        c0_f1 = _decimal_metric(metrics["c0_f1"], "C0 per-label F1")
        m64_f1 = _decimal_metric(metrics["m64_f1"], "M64 per-label F1")
        if support < WEAK_CLASS_MINIMUM_SUPPORT:
            continue
        if c0_f1 - m64_f1 > Decimal(str(WEAK_CLASS_MAXIMUM_F1_DROP)):
            return False
        if c0_f1 > 0 and m64_f1 <= 0:
            return False
    return True


def seed_robustness_gate(seed_mrrs: Iterable[float], c0_mrr: float) -> bool:
    values = _finite_values(seed_mrrs, "seed MRR values")
    if len(values) != len(FIVE_SEEDS):
        raise StatisticalContractError("seed robustness requires five seeds")
    return statistics.fmean(values) > c0_mrr and sum(value > c0_mrr for value in values) >= 4


def holm_adjusted_p_values(p_values: Iterable[float]) -> tuple[float, ...]:
    """Return Holm step-down adjusted p-values in original input order."""

    values = tuple(float(value) for value in p_values)
    if not values or any(not 0.0 <= value <= 1.0 for value in values):
        raise StatisticalContractError("Holm p-values must be within [0, 1]")
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    adjusted = [0.0] * len(values)
    running = 0.0
    for rank, (original_index, value) in enumerate(ordered):
        running = max(running, min(1.0, (len(values) - rank) * value))
        adjusted[original_index] = running
    return tuple(adjusted)


def final_selection_gate(
    *,
    primary_mrr_significance: bool,
    top1_direction: bool,
    macro_f1_tolerance: bool,
    weak_class: bool,
    seed_robustness: bool,
    no_final_gold_tuning: bool,
    no_taxonomy_change: bool,
) -> str:
    gates = (
        primary_mrr_significance,
        top1_direction,
        macro_f1_tolerance,
        weak_class,
        seed_robustness,
        no_final_gold_tuning,
        no_taxonomy_change,
    )
    return "M64_REPLACES_C0" if all(gates) else "C0_REMAINS_SELECTED"
