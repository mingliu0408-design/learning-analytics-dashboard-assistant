"""Versioned mechanism metrics with case-scoped admission identity."""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Sequence


METRIC_CONTRACT_ID = "CASE_SCOPED_MEMORY_IDENTITY_METRICS_V1"


def safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def binary_metrics(gold: Sequence[bool], predicted: Sequence[bool]) -> dict[str, Any]:
    if len(gold) != len(predicted):
        raise ValueError("metric length mismatch")
    tp = sum(g and p for g, p in zip(gold, predicted))
    fp = sum((not g) and p for g, p in zip(gold, predicted))
    fn = sum(g and (not p) for g, p in zip(gold, predicted))
    tn = sum((not g) and (not p) for g, p in zip(gold, predicted))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "support": sum(gold),
        "predicted_positive_count": sum(predicted),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "f1": safe_div(2 * precision * recall, precision + recall),
        "accuracy": safe_div(tp + tn, len(gold)),
        "unnecessary_use_rate": safe_div(fp, fp + tn),
    }


def case_scoped_admission_metrics(
    expected: Iterable[tuple[str, str]], predicted: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    gold = set(expected)
    observed = set(predicted)
    tp = len(gold & observed)
    fp = len(observed - gold)
    fn = len(gold - observed)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "metric_contract_id": METRIC_CONTRACT_ID,
        "identity": "(fixture_id, memory_id)",
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": safe_div(2 * precision * recall, precision + recall),
    }


def id_retrieval_metrics(
    expected: Iterable[tuple[str, ...]], predicted: Iterable[tuple[str, ...]]
) -> dict[str, Any]:
    rows = list(zip(expected, predicted))
    recall1: list[float] = []
    recall3: list[float] = []
    reciprocal: list[float] = []
    multi_hop: list[float] = []
    for gold_ids, predicted_ids in rows:
        gold = set(gold_ids)
        if not gold:
            continue
        recall1.append(safe_div(len(gold & set(predicted_ids[:1])), len(gold)))
        recall3.append(safe_div(len(gold & set(predicted_ids[:3])), len(gold)))
        ranks = [predicted_ids.index(value) + 1 for value in gold if value in predicted_ids]
        reciprocal.append(1.0 / min(ranks) if ranks else 0.0)
        if len(gold) > 1:
            multi_hop.append(float(gold.issubset(set(predicted_ids))))
    return {
        "recall_at_1": mean(recall1) if recall1 else 0.0,
        "recall_at_3": mean(recall3) if recall3 else 0.0,
        "mrr": mean(reciprocal) if reciprocal else 0.0,
        "multi_hop_complete_retrieval": mean(multi_hop) if multi_hop else 0.0,
        "recall_definition": "REQUIRED_IDS_RECOVERED_PROPORTION",
        "mrr_definition": "RANK_OF_FIRST_RELEVANT_ITEM",
        "multi_target_mrr_one_with_recall_at_1_below_one_is_valid": True,
    }
