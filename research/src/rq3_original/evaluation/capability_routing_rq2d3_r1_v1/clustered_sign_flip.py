"""Exact two-sided contrast-clustered Monte Carlo sign-flip procedure."""

from __future__ import annotations

from fractions import Fraction
import itertools
import random
from typing import Any, Iterable, Sequence

from . import BOOTSTRAP_GROUP_COUNT, SIGN_FLIP_DRAWS, SIGN_FLIP_SEED


def cluster_mean_delta_v1(case_deltas: tuple[Fraction, Fraction]) -> Fraction:
    if not isinstance(case_deltas, tuple) or len(case_deltas) != 2:
        raise ValueError("each governed cluster must contain exactly two case deltas")
    return (Fraction(case_deltas[0]) + Fraction(case_deltas[1])) / 2


def ordered_cluster_deltas_v1(
    groups: Iterable[tuple[str, Sequence[tuple[str, Fraction]]]],
) -> tuple[tuple[str, Fraction], ...]:
    material = list(groups)
    if len(material) != BOOTSTRAP_GROUP_COUNT:
        raise ValueError("the frozen procedure requires exactly 24 clusters")
    group_ids = [str(group_id) for group_id, _ in material]
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("duplicate contrast group ID")
    result: list[tuple[str, Fraction]] = []
    for group_id, cases in sorted(material, key=lambda item: item[0].encode("utf-8")):
        ordered_cases = sorted(cases, key=lambda item: item[0].encode("utf-8"))
        if len(ordered_cases) != 2 or len({case_id for case_id, _ in ordered_cases}) != 2:
            raise ValueError("each cluster must contain two unique cases")
        result.append(
            (
                str(group_id),
                cluster_mean_delta_v1(
                    (Fraction(ordered_cases[0][1]), Fraction(ordered_cases[1][1]))
                ),
            )
        )
    return tuple(result)


def _fraction_document(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "value": float(value),
    }


def run_clustered_sign_flip_v1(
    ordered_cluster_deltas: Sequence[tuple[str, Fraction]],
    *,
    draws: int = SIGN_FLIP_DRAWS,
    seed: int = SIGN_FLIP_SEED,
) -> dict[str, Any]:
    if draws <= 0:
        raise ValueError("draw count must be positive")
    group_ids = [str(group_id) for group_id, _ in ordered_cluster_deltas]
    expected_order = sorted(group_ids, key=lambda value: value.encode("utf-8"))
    if len(group_ids) != BOOTSTRAP_GROUP_COUNT or group_ids != expected_order:
        raise ValueError("cluster deltas must be 24 unique IDs in UTF-8 order")
    if len(set(group_ids)) != BOOTSTRAP_GROUP_COUNT:
        raise ValueError("cluster IDs must be unique")
    deltas = [Fraction(delta) for _, delta in ordered_cluster_deltas]
    observed = abs(sum(deltas, Fraction(0, 1)) / BOOTSTRAP_GROUP_COUNT)
    nonzero_count = sum(delta != 0 for delta in deltas)
    rng = random.Random()
    rng.seed(seed, version=2)
    extreme_count = 0
    bit_draw_count = 0
    for _ in range(draws):
        signed_total = Fraction(0, 1)
        for delta in deltas:
            if delta == 0:
                continue
            bit = rng.getrandbits(1)
            bit_draw_count += 1
            signed_total += delta if bit == 1 else -delta
        draw_statistic = abs(signed_total / BOOTSTRAP_GROUP_COUNT)
        if draw_statistic >= observed:
            extreme_count += 1
    p_value = Fraction(extreme_count + 1, draws + 1)
    return {
        "contract_id": "RQ2_TRACK_B_CLUSTERED_TWO_SIDED_SIGN_FLIP_V1",
        "test_direction": "TWO_SIDED",
        "cluster_count": BOOTSTRAP_GROUP_COUNT,
        "denominator_cluster_count": BOOTSTRAP_GROUP_COUNT,
        "nonzero_cluster_count": nonzero_count,
        "zero_cluster_count": BOOTSTRAP_GROUP_COUNT - nonzero_count,
        "draw_count": draws,
        "seed": seed,
        "rng": "random.Random.seed(version=2)+getrandbits(1)",
        "rng_bit_draw_count": bit_draw_count,
        "observed_statistic": _fraction_document(observed),
        "extreme_rule": "T_DRAW_GTE_T_OBSERVED",
        "extreme_count": extreme_count,
        "p_numerator": p_value.numerator,
        "p_denominator": p_value.denominator,
        "p_value": float(p_value),
        "plus_one_correction": True,
        "utility_target": "CLUSTERED_PER_CASE_JACCARD_UTILITY_DIFFERENCE",
        "macro_f1_directly_tested": False,
    }


def exhaustive_sign_flip_fixture_v1(
    ordered_cluster_deltas: Sequence[tuple[str, Fraction]],
) -> dict[str, Any]:
    """Exact small-fixture oracle for validating two-sided extreme logic."""

    group_ids = [group_id for group_id, _ in ordered_cluster_deltas]
    if len(group_ids) != BOOTSTRAP_GROUP_COUNT or group_ids != sorted(
        group_ids, key=lambda value: value.encode("utf-8")
    ):
        raise ValueError("exhaustive fixture requires the canonical 24-group shape")
    deltas = [Fraction(delta) for _, delta in ordered_cluster_deltas]
    nonzero = [delta for delta in deltas if delta]
    if len(nonzero) > 12:
        raise ValueError("exhaustive oracle is limited to small synthetic fixtures")
    observed = abs(sum(deltas, Fraction(0, 1)) / BOOTSTRAP_GROUP_COUNT)
    extreme = 0
    total = 0
    for signs in itertools.product((-1, 1), repeat=len(nonzero)):
        total += 1
        statistic = abs(
            sum((sign * delta for sign, delta in zip(signs, nonzero)), Fraction(0, 1))
            / BOOTSTRAP_GROUP_COUNT
        )
        extreme += int(statistic >= observed)
    probability = Fraction(extreme, total)
    return {
        "pattern_count": total,
        "extreme_count": extreme,
        "probability_numerator": probability.numerator,
        "probability_denominator": probability.denominator,
        "probability": float(probability),
    }
