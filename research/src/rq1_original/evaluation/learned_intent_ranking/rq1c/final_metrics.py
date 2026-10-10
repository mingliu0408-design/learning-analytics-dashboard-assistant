"""Fixed-universe final metrics and the unmodified RQ1-A-R1 decision contract."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Iterable, Mapping

from evaluation.learned_intent_ranking.lr4b_r1 import statistical_decision_contract as stats

from . import LABEL_UNIVERSE, REPRESENTATIVE_SEED, V0_SEEDS


class FinalMetricError(ValueError):
    pass


def _prediction_by_id(predictions: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    rows = tuple(predictions)
    result = {str(row["record_id"]): row for row in rows}
    if len(result) != len(rows):
        raise FinalMetricError("duplicate prediction record ID")
    return result


def reciprocal_rank(row: Mapping[str, Any]) -> float:
    rank = row.get("gold_rank")
    return 1.0 / int(rank) if rank is not None and int(rank) > 0 else 0.0


def compute_fixed16_metrics(
    predictions: list[Mapping[str, Any]],
    label_universe: Iterable[str] = LABEL_UNIVERSE,
) -> dict[str, Any]:
    labels = tuple(label_universe)
    if labels != LABEL_UNIVERSE:
        raise FinalMetricError("metric label universe drift")
    if not predictions:
        raise FinalMetricError("prediction collection is empty")
    _prediction_by_id(predictions)
    label_set = set(labels)
    for row in predictions:
        if row.get("gold_label") not in label_set or row.get("top1_label") not in label_set:
            raise FinalMetricError("prediction label outside frozen universe")
        ranking = tuple(str(value) for value in row.get("ranking", ()))
        if not ranking or len(ranking) != len(set(ranking)) or not set(ranking) <= label_set:
            raise FinalMetricError("prediction ranking is invalid")
        expected_rank = (
            ranking.index(str(row["gold_label"])) + 1
            if str(row["gold_label"]) in ranking
            else None
        )
        if row.get("gold_rank") != expected_rank:
            raise FinalMetricError("prediction gold rank is inconsistent")
    reciprocal_ranks = [reciprocal_rank(row) for row in predictions]
    recall3 = [
        1.0 if row.get("gold_rank") is not None and int(row["gold_rank"]) <= 3 else 0.0
        for row in predictions
    ]
    correct = sum(row["top1_label"] == row["gold_label"] for row in predictions)
    per_label: dict[str, dict[str, Any]] = {}
    confusion = {gold: {predicted: 0 for predicted in labels} for gold in labels}
    for row in predictions:
        confusion[str(row["gold_label"])][str(row["top1_label"])] += 1
    for label in labels:
        tp = sum(row["gold_label"] == label and row["top1_label"] == label for row in predictions)
        fp = sum(row["gold_label"] != label and row["top1_label"] == label for row in predictions)
        fn = sum(row["gold_label"] == label and row["top1_label"] != label for row in predictions)
        support = sum(row["gold_label"] == label for row in predictions)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    rank_distribution = Counter(
        str(row["gold_rank"]) if row.get("gold_rank") is not None else "MISSING"
        for row in predictions
    )
    missing_rank_value = len(labels) + 1
    mean_gold_rank = statistics.fmean(
        int(row["gold_rank"]) if row.get("gold_rank") is not None else missing_rank_value
        for row in predictions
    )
    return {
        "record_count": len(predictions),
        "prediction_label_universe": list(labels),
        "macro_f1_universe_policy": "FIXED_16_LABEL_UNIVERSE_INCLUDING_ZERO_SUPPORT_LABELS",
        "mrr": statistics.fmean(reciprocal_ranks),
        "top1_accuracy": correct / len(predictions),
        "top1_correct_count": correct,
        "recall_at_3": statistics.fmean(recall3),
        "macro_f1": statistics.fmean(row["f1"] for row in per_label.values()),
        "mean_gold_rank": mean_gold_rank,
        "missing_gold_rank_value": missing_rank_value,
        "per_label": per_label,
        "confusion_matrix": confusion,
        "rank_distribution": dict(sorted(rank_distribution.items())),
        "raw_query_emitted": False,
    }


def paired_outcomes(
    left: Iterable[Mapping[str, Any]], right: Iterable[Mapping[str, Any]]
) -> dict[str, int]:
    left_by_id = _prediction_by_id(left)
    right_by_id = _prediction_by_id(right)
    if set(left_by_id) != set(right_by_id):
        raise FinalMetricError("paired prediction IDs differ")
    deltas = [
        reciprocal_rank(left_by_id[key]) - reciprocal_rank(right_by_id[key])
        for key in sorted(left_by_id)
    ]
    return {
        "wins": sum(value > 0 for value in deltas),
        "ties": sum(value == 0 for value in deltas),
        "losses": sum(value < 0 for value in deltas),
    }


def run_frozen_final_decision(
    *,
    c0_predictions: list[Mapping[str, Any]],
    m64_predictions_by_seed: Mapping[int, list[Mapping[str, Any]]],
    bootstrap_resamples: int = stats.BOOTSTRAP_RESAMPLES,
    randomisation_resamples: int = stats.RANDOMISATION_MONTE_CARLO_RESAMPLES,
) -> dict[str, Any]:
    if tuple(sorted(m64_predictions_by_seed)) != V0_SEEDS:
        raise FinalMetricError("five-seed prediction set mismatch")
    c0_by_id = _prediction_by_id(c0_predictions)
    representative = m64_predictions_by_seed[REPRESENTATIVE_SEED]
    representative_by_id = _prediction_by_id(representative)
    if set(c0_by_id) != set(representative_by_id):
        raise FinalMetricError("representative and C0 prediction IDs differ")
    ordered_ids = sorted(c0_by_id)
    c0_rr = [reciprocal_rank(c0_by_id[key]) for key in ordered_ids]
    m64_rr = [reciprocal_rank(representative_by_id[key]) for key in ordered_ids]
    c0_metrics = compute_fixed16_metrics(c0_predictions)
    seed_metrics = {
        seed: compute_fixed16_metrics(predictions)
        for seed, predictions in m64_predictions_by_seed.items()
    }
    randomisation = stats.paired_approximate_randomisation_test(
        m64_rr,
        c0_rr,
        monte_carlo_resamples=randomisation_resamples,
        random_seed=stats.RANDOMISATION_SEED,
    )
    bootstrap = stats.paired_bootstrap_ci(
        m64_rr,
        c0_rr,
        resamples=bootstrap_resamples,
        confidence=stats.BOOTSTRAP_CONFIDENCE,
        random_seed=stats.BOOTSTRAP_SEED,
    )
    effect = stats.paired_effect_size(m64_rr, c0_rr)
    representative_metrics = seed_metrics[REPRESENTATIVE_SEED]
    primary_gate = stats.primary_statistical_gate(
        representative_m64_mrr=representative_metrics["mrr"],
        c0_mrr=c0_metrics["mrr"],
        mean_delta_rr=effect["mean_delta_rr"],
        bootstrap_lower_bound=bootstrap["lower_bound"],
        paired_randomisation_p_value=randomisation["p_value"],
    )
    top1_direction = representative_metrics["top1_accuracy"] >= c0_metrics["top1_accuracy"]
    macro_f1_tolerance = (
        representative_metrics["macro_f1"]
        >= c0_metrics["macro_f1"] - stats.MACRO_F1_NONINFERIORITY_TOLERANCE
    )
    combined_direction_gate = stats.top1_macro_f1_gate(
        representative_m64_top1=representative_metrics["top1_accuracy"],
        c0_top1=c0_metrics["top1_accuracy"],
        representative_m64_macro_f1=representative_metrics["macro_f1"],
        c0_macro_f1=c0_metrics["macro_f1"],
    )
    weak_inputs = {
        label: {
            "support": c0_metrics["per_label"][label]["support"],
            "c0_f1": c0_metrics["per_label"][label]["f1"],
            "m64_f1": representative_metrics["per_label"][label]["f1"],
        }
        for label in LABEL_UNIVERSE
    }
    weak_gate = stats.weak_class_gate(weak_inputs)
    seed_gate = stats.seed_robustness_gate(
        [seed_metrics[seed]["mrr"] for seed in V0_SEEDS],
        c0_metrics["mrr"],
    )
    decision = stats.final_selection_gate(
        primary_mrr_significance=primary_gate,
        top1_direction=top1_direction,
        macro_f1_tolerance=macro_f1_tolerance,
        weak_class=weak_gate,
        seed_robustness=seed_gate,
        no_final_gold_tuning=True,
        no_taxonomy_change=True,
    )
    return {
        "schema_version": "rq1c-frozen-final-decision-v1",
        "primary_metric": "MRR",
        "primary_comparison": "REPRESENTATIVE_M64_VS_C0",
        "representative_seed": REPRESENTATIVE_SEED,
        "c0_metrics": c0_metrics,
        "m64_metrics_by_seed": {str(seed): seed_metrics[seed] for seed in V0_SEEDS},
        "paired_randomisation": randomisation,
        "paired_bootstrap": bootstrap,
        "paired_effect": effect,
        "paired_outcomes": paired_outcomes(representative, c0_predictions),
        "gates": {
            "primary_mrr_significance": primary_gate,
            "top1_direction": top1_direction,
            "macro_f1_tolerance": macro_f1_tolerance,
            "combined_top1_macro_f1_contract_call": combined_direction_gate,
            "weak_class": weak_gate,
            "seed_robustness": seed_gate,
            "no_final_gold_tuning": True,
            "no_taxonomy_change": True,
        },
        "selection": decision,
        "failure_decision": "C0_REMAINS_SELECTED",
        "randomisation_resamples": randomisation_resamples,
        "bootstrap_resamples": bootstrap_resamples,
        "statistical_module": (
            "evaluation.learned_intent_ranking.lr4b_r1.statistical_decision_contract"
        ),
        "raw_query_emitted": False,
    }


def holm_secondary(p_values: Iterable[float]) -> tuple[float, ...]:
    return stats.holm_adjusted_p_values(p_values)
