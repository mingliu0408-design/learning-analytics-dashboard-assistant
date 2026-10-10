"""Aggregate multi-label metrics for the RQ2-B capability experiment."""

from __future__ import annotations

from collections import Counter
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from . import CAPABILITIES, EXECUTION_CAPABILITIES, capability_order


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return _safe_div(2.0 * precision * recall, precision + recall)


def _sets(row: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    gold = set(row.get("gold_capabilities") or ())
    predicted = set(row.get("predicted_capabilities") or ())
    forbidden = set(row.get("forbidden_capabilities") or ())
    if not gold <= set(CAPABILITIES) or not predicted <= set(CAPABILITIES):
        raise ValueError("metric row contains a capability outside the frozen universe")
    return gold, predicted, forbidden


def confusion_for_capability(
    rows: Sequence[Mapping[str, Any]], capability: str
) -> dict[str, int]:
    if capability not in CAPABILITIES:
        raise ValueError(capability)
    counts = Counter(tp=0, fp=0, fn=0, tn=0)
    for row in rows:
        gold, predicted, _ = _sets(row)
        actual = capability in gold
        guess = capability in predicted
        key = "tp" if actual and guess else "fp" if guess else "fn" if actual else "tn"
        counts[key] += 1
    return {key: int(counts[key]) for key in ("tp", "fp", "fn", "tn")}


def binary_metrics(counts: Mapping[str, int]) -> dict[str, float | int]:
    tp = int(counts["tp"])
    fp = int(counts["fp"])
    fn = int(counts["fn"])
    tn = int(counts["tn"])
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "support": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "accuracy": _safe_div(tp + tn, tp + fp + fn + tn),
    }


def evaluate_capability_predictions(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the complete, query-free metric contract for one prediction set."""

    if not rows:
        raise ValueError("at least one prediction row is required")
    per_capability = {
        capability: binary_metrics(confusion_for_capability(rows, capability))
        for capability in CAPABILITIES
    }
    totals = {
        key: sum(int(per_capability[name][key]) for name in CAPABILITIES)
        for key in ("tp", "fp", "fn", "tn")
    }
    micro = binary_metrics(totals)
    supported = [
        name for name in CAPABILITIES if int(per_capability[name]["support"]) > 0
    ]
    exact_values: list[float] = []
    jaccard_values: list[float] = []
    predicted_counts: list[int] = []
    multi_exact_values: list[float] = []
    required_total = 0
    required_found = 0
    unnecessary_total = 0
    forbidden_violations = 0
    for row in rows:
        gold, predicted, forbidden = _sets(row)
        exact_values.append(float(gold == predicted))
        union = gold | predicted
        jaccard_values.append(_safe_div(len(gold & predicted), len(union)) if union else 1.0)
        predicted_counts.append(len(predicted))
        required_total += len(gold)
        required_found += len(gold & predicted)
        unnecessary_total += len(predicted - gold)
        forbidden_violations += int(bool(predicted & forbidden))
        if len(gold) > 1:
            multi_exact_values.append(float(gold == predicted))

    tool_trigger = {
        name: {
            "precision": per_capability[name]["precision"],
            "recall": per_capability[name]["recall"],
            "support": per_capability[name]["support"],
        }
        for name in EXECUTION_CAPABILITIES
    }
    context_gold = [bool(row.get("gold_context_resolution_required")) for row in rows]
    context_pred = [
        bool(row.get("predicted_context_resolution_required")) for row in rows
    ]
    context_counts = Counter(tp=0, fp=0, fn=0, tn=0)
    for actual, guess in zip(context_gold, context_pred):
        key = "tp" if actual and guess else "fp" if guess else "fn" if actual else "tn"
        context_counts[key] += 1
    context_metrics = binary_metrics(context_counts)
    clarification = per_capability["clarification"]
    safe_direct = per_capability["safe_direct_response"]
    return {
        "record_count": len(rows),
        "capability_order": list(CAPABILITIES),
        "per_capability": per_capability,
        "macro_f1_all_six": mean(
            float(per_capability[name]["f1"]) for name in CAPABILITIES
        ),
        "macro_f1_supported_capabilities_only": mean(
            float(per_capability[name]["f1"]) for name in supported
        )
        if supported
        else 0.0,
        "supported_capabilities": supported,
        "exact_set_accuracy": mean(exact_values),
        "micro_precision": micro["precision"],
        "micro_recall": micro["recall"],
        "micro_f1": micro["f1"],
        "required_capability_recall": _safe_div(required_found, required_total),
        "unnecessary_capability_rate": _safe_div(
            unnecessary_total, sum(predicted_counts)
        ),
        "mean_set_jaccard": mean(jaccard_values),
        "median_set_jaccard": median(jaccard_values),
        "forbidden_capability_violation_rate": _safe_div(
            forbidden_violations, len(rows)
        ),
        "forbidden_capability_violation_count": forbidden_violations,
        "mean_predicted_capability_count": mean(predicted_counts),
        "tool_trigger_metrics": tool_trigger,
        "context_resolution_accuracy": context_metrics["accuracy"],
        "context_resolution_positive_recall": context_metrics["recall"],
        "context_resolution_confusion": {
            key: context_metrics[key] for key in ("tp", "fp", "fn", "tn")
        },
        "clarification_precision": clarification["precision"],
        "clarification_recall": clarification["recall"],
        "unnecessary_clarification_rate": _safe_div(
            int(clarification["fp"]), len(rows)
        ),
        "safe_direct_response_accuracy": safe_direct["accuracy"],
        "multi_capability_case_count": len(multi_exact_values),
        "multi_capability_exact_set_accuracy": mean(multi_exact_values)
        if multi_exact_values
        else None,
    }


def attach_gold_for_metrics(
    predictions: Iterable[Mapping[str, Any]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join opaque IDs to Gold only at the metric boundary."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for prediction in predictions:
        case_id = str(prediction["review_case_id"])
        if case_id in seen or case_id not in labels_by_id:
            raise ValueError("prediction/Gold identity mismatch")
        seen.add(case_id)
        label = labels_by_id[case_id]
        rows.append(
            {
                "review_case_id": case_id,
                "gold_capabilities": list(
                    capability_order(label["gold_capabilities"])
                ),
                "predicted_capabilities": list(
                    capability_order(prediction["predicted_capabilities"])
                ),
                "forbidden_capabilities": list(
                    capability_order(label.get("forbidden_capabilities") or ())
                ),
                "gold_context_resolution_required": bool(
                    label["context_resolution_required"]
                ),
                "predicted_context_resolution_required": bool(
                    prediction.get("context_resolution_required_prediction")
                ),
            }
        )
    if seen != set(labels_by_id):
        raise ValueError("prediction set does not cover the Gold set exactly")
    return rows
