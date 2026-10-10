"""Statistical algorithms sealed before the first restricted identity access.

Scores are never rounded or rewritten. A fixed 1e-12 numerical tolerance defines
zero differences, tied absolute ranks, and the at-least-as-extreme comparison.
Wilcoxon uses the exact conditional distribution of the observed average ranks,
including ties, calculated by integer dynamic programming. No auto test choice.
"""
from __future__ import annotations

import math
import statistics
import numpy as np

from f1_common import SEED, BOOTSTRAP_REPLICATES, MONTE_CARLO_ASSIGNMENTS, TIE_TOLERANCE


def mean(x):
    return float(statistics.mean(x)) if len(x) else None


def median(x):
    return float(statistics.median(x)) if len(x) else None


def wins_ties_losses(differences, higher_is_better=True):
    oriented = [x if higher_is_better else -x for x in differences]
    return {"wins": sum(x > TIE_TOLERANCE for x in oriented),
            "ties": sum(abs(x) <= TIE_TOLERANCE for x in oriented),
            "losses": sum(x < -TIE_TOLERANCE for x in oriented)}


def family_means(groups):
    return [mean(groups[k]) for k in sorted(groups)]


def cluster_bootstrap(groups):
    keys = sorted(groups)
    n = len(keys)
    result = {"method": "FAMILY_CLUSTER_NONPARAMETRIC_PERCENTILE", "confidence_level": 0.95,
              "replicates": BOOTSTRAP_REPLICATES, "seed": SEED, "eligible_families": n,
              "rng": "numpy.random.Generator(PCG64)", "quantile_method": "linear",
              "statistic": "MEAN_PAIRED_CASE_DIFFERENCE_WITH_ALL_SAMPLED_FAMILY_MEMBERS"}
    if n < 2:
        return result | {"status": "NOT_ESTIMABLE_INSUFFICIENT_FAMILIES", "ci_low": None, "ci_high": None}
    sums = np.array([math.fsum(groups[k]) for k in keys], dtype=float)
    counts = np.array([len(groups[k]) for k in keys], dtype=np.int64)
    rng = np.random.Generator(np.random.PCG64(SEED))
    indices = rng.integers(0, n, size=(BOOTSTRAP_REPLICATES, n), dtype=np.int64)
    replicates = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    bounds = np.quantile(replicates, [0.025, 0.975], method="linear")
    return result | {"status": "ESTIMABLE", "ci_low": float(bounds[0]), "ci_high": float(bounds[1])}


def sign_flip(differences):
    d = np.array(differences, dtype=float)
    n = len(d)
    if n == 0:
        return {"status": "NOT_ESTIMABLE_NO_COMPLETE_FAMILIES", "p_value": None,
                "family_count": 0, "assignment_count": 0}
    observed = abs(mean(d.tolist()))
    extreme = 0
    exact = n <= 20
    count = 2 ** n if exact else MONTE_CARLO_ASSIGNMENTS
    rng = np.random.Generator(np.random.PCG64(SEED))
    for start in range(0, count, 1000):
        batch = min(1000, count - start)
        if exact:
            bits = (np.arange(start, start + batch, dtype=np.uint64)[:, None]
                    >> np.arange(n, dtype=np.uint64)) & 1
            signs = 2 * bits.astype(np.int64) - 1
        else:
            signs = 2 * rng.integers(0, 2, size=(batch, n), dtype=np.int64) - 1
        simulated = np.abs((signs * d).mean(axis=1))
        extreme += int(np.sum(simulated >= observed - TIE_TOLERANCE))
    p = extreme / count if exact else (1 + extreme) / (1 + count)
    return {"status": "ESTIMABLE", "p_value": float(p), "family_count": n,
            "zero_family_differences_retained": int(np.sum(np.abs(d) <= TIE_TOLERANCE)),
            "observed_absolute_family_mean_difference": observed,
            "method": "EXACT_ENUMERATION" if exact else "MONTE_CARLO_SIGN_FLIP",
            "assignment_count": count, "extreme_count": extreme, "two_sided": True,
            "seed": SEED, "rng": "numpy.random.Generator(PCG64)",
            "extremeness_tolerance": TIE_TOLERANCE}


def average_ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    a = 0
    while a < len(order):
        b = a + 1
        while b < len(order) and abs(values[order[b]] - values[order[a]]) <= TIE_TOLERANCE:
            b += 1
        rank = ((a + 1) + b) / 2
        for i in order[a:b]:
            ranks[i] = rank
        a = b
    return ranks


def wilcoxon_and_rank_biserial(differences):
    d = [float(x) for x in differences if abs(x) > TIE_TOLERANCE]
    if not d:
        return {"wilcoxon_status": "NOT_ESTIMABLE_ALL_ZERO_WITH_EXACT_AGREEMENT_REPORTED",
                "wilcoxon_p_value": None, "wilcoxon_statistic": None,
                "nonzero_family_count": 0, "rank_biserial": None,
                "rank_biserial_status": "NOT_ESTIMABLE_ALL_ZERO", "positive_rank_sum": 0.0,
                "negative_rank_sum": 0.0}
    ranks = average_ranks([abs(x) for x in d])
    positive = math.fsum(r for r, x in zip(ranks, d) if x > 0)
    negative = math.fsum(r for r, x in zip(ranks, d) if x < 0)
    doubled = [int(round(2 * r)) for r in ranks]
    total = sum(doubled)
    observed = int(round(2 * positive))
    ways = {0: 1}
    for rank in doubled:
        updated = dict(ways)
        for rank_sum, number in ways.items():
            updated[rank_sum + rank] = updated.get(rank_sum + rank, 0) + number
        ways = updated
    observed_deviation = abs(2 * observed - total)
    extreme = sum(number for rank_sum, number in ways.items()
                  if abs(2 * rank_sum - total) >= observed_deviation)
    return {"wilcoxon_status": "ESTIMABLE", "wilcoxon_p_value": extreme / (2 ** len(d)),
            "wilcoxon_statistic": min(positive, negative), "nonzero_family_count": len(d),
            "wilcoxon_method": "EXACT_CONDITIONAL_AVERAGE_RANK_DP",
            "wilcoxon_two_sided": True, "wilcoxon_zero_method": "DROP_ZEROS",
            "wilcoxon_tie_method": "AVERAGE_RANKS", "wilcoxon_continuity_correction": False,
            "rank_biserial": (positive - negative) / (positive + negative),
            "rank_biserial_status": "ESTIMABLE", "positive_rank_sum": positive,
            "negative_rank_sum": negative}


def paired_dz(differences):
    d = [float(x) for x in differences]
    if len(d) < 2:
        return {"paired_dz": None, "paired_dz_status": "NOT_ESTIMABLE_INSUFFICIENT_FAMILIES",
                "family_difference_sample_sd": None, "family_mean_difference": mean(d)}
    sd = float(statistics.stdev(d))
    if sd == 0:
        return {"paired_dz": None, "paired_dz_status": "NOT_ESTIMABLE_ZERO_STANDARD_DEVIATION",
                "family_difference_sample_sd": 0.0, "family_mean_difference": mean(d),
                "common_difference": d[0]}
    return {"paired_dz": mean(d) / sd, "paired_dz_status": "ESTIMABLE",
            "family_difference_sample_sd": sd, "family_mean_difference": mean(d)}


def holm(pvalues):
    """Return adjusted values in original order; caller supplies exactly one family."""
    if any(p is None or not 0 <= p <= 1 for p in pvalues):
        raise ValueError("HOLM_REQUIRES_THE_COMPLETE_PREDECLARED_FAMILY")
    n = len(pvalues)
    result = [None] * n
    running = 0.0
    for rank, index in enumerate(sorted(range(n), key=lambda i: (pvalues[i], i))):
        running = max(running, (n - rank) * pvalues[index])
        result[index] = min(1.0, running)
    return result
