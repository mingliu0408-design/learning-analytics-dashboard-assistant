"""Ranking and classification metrics for authorised LR-3 DEV views."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any


METRIC_KEYS = ("top1_accuracy", "mrr", "recall_at_3", "macro_f1")


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "mean": None, "std": None, "min": None, "median": None, "max": None}
    return {
        "count": len(values),
        "mean": float(statistics.fmean(values)),
        "std": float(statistics.pstdev(values)),
        "min": float(min(values)),
        "median": float(statistics.median(values)),
        "max": float(max(values)),
    }


def compute_view_metrics(
    predictions: list[dict[str, Any]],
    record_ids: list[str],
    production_labels: list[str],
    view_name: str,
) -> dict[str, Any]:
    by_id = {row["record_id"]: row for row in predictions}
    rows = [by_id[record_id] for record_id in record_ids]
    if len(rows) != len(record_ids):
        raise ValueError(f"prediction coverage mismatch for {view_name}")
    gold_labels = sorted({row["gold_label"] for row in rows})
    correct = sum(row["top1_correct"] for row in rows)
    reciprocal_ranks = [1.0 / row["gold_rank"] if row["gold_rank"] else 0.0 for row in rows]
    recall3 = [1.0 if row["gold_rank"] and row["gold_rank"] <= 3 else 0.0 for row in rows]
    per_intent = {}
    for label in gold_labels:
        tp = sum(row["gold_label"] == label and row["top1_label"] == label for row in rows)
        fp = sum(row["gold_label"] != label and row["top1_label"] == label for row in rows)
        fn = sum(row["gold_label"] == label and row["top1_label"] != label for row in rows)
        support = sum(row["gold_label"] == label for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_intent[label] = {
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    macro_f1 = statistics.fmean(item["f1"] for item in per_intent.values())
    confusion = {
        gold: {predicted: 0 for predicted in production_labels}
        for gold in gold_labels
    }
    for row in rows:
        if row["top1_label"] not in production_labels:
            raise ValueError("prediction outside production universe")
        confusion[row["gold_label"]][row["top1_label"]] += 1
    confusions = Counter(
        (row["gold_label"], row["top1_label"])
        for row in rows
        if row["gold_label"] != row["top1_label"]
    )
    gold_rank_distribution = Counter(
        str(row["gold_rank"]) if row["gold_rank"] is not None else "MISSING"
        for row in rows
    )
    margins = [float(row["margin"]) for row in rows if row["margin"] is not None]
    gold_ranks = [float(row["gold_rank"]) for row in rows if row["gold_rank"] is not None]
    predicted_distribution = Counter(row["top1_label"] for row in rows)
    return {
        "view": view_name,
        "record_count": len(rows),
        "represented_gold_label_count": len(gold_labels),
        "represented_gold_labels": gold_labels,
        "prediction_universe_label_count": len(production_labels),
        "top1_correct_count": correct,
        "top1_accuracy": correct / len(rows),
        "mrr": statistics.fmean(reciprocal_ranks),
        "recall_at_3": statistics.fmean(recall3),
        "macro_f1": macro_f1,
        "mean_gold_label_rank": statistics.fmean(gold_ranks) if gold_ranks else math.inf,
        "gold_label_rank_distribution": dict(sorted(gold_rank_distribution.items())),
        "margin_summary": _summary(margins),
        "per_intent": per_intent,
        "confusion_matrix": confusion,
        "predicted_label_distribution": dict(sorted(predicted_distribution.items())),
        "most_common_confusions": [
            {"gold_label": gold, "predicted_label": predicted, "count": count}
            for (gold, predicted), count in confusions.most_common()
        ],
    }


def aggregate_seed_metrics(seed_rows: list[dict[str, Any]], view_key: str) -> dict[str, Any]:
    result: dict[str, Any] = {"seed_count": len(seed_rows), "std_definition": "population"}
    for metric in METRIC_KEYS:
        values = [float(row["view_metrics"][view_key][metric]) for row in seed_rows]
        result[metric] = {
            "mean": float(statistics.fmean(values)),
            "std": float(statistics.pstdev(values)),
            "min": float(min(values)),
            "max": float(max(values)),
            "per_seed": {str(row["training_seed"]): value for row, value in zip(seed_rows, values)},
        }
    return result

