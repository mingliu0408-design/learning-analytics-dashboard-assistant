"""Small dependency-free set-valued metric harness for RQ2-V2 toy fixtures."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from . import CAPABILITY_FIELDS
from .contracts import Stage0ContractError, validate_case, validate_prediction


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def _index_by_case_id(
    rows: Iterable[Mapping[str, Any]], *, kind: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = dict(row)
        case_id = str(value.get("case_id", ""))
        if not case_id or case_id in result:
            raise Stage0ContractError(f"{kind} case IDs must be non-empty and unique")
        result[case_id] = value
    return result


def evaluate_predictions(
    cases: Iterable[Mapping[str, Any]],
    predictions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate capability sets on ANSWER cases and answerability separately."""

    case_index = _index_by_case_id(cases, kind="gold")
    prediction_index = _index_by_case_id(predictions, kind="prediction")
    if set(case_index) != set(prediction_index):
        raise Stage0ContractError("gold and prediction case-ID sets differ")
    for case in case_index.values():
        validate_case(case)
    for prediction in prediction_index.values():
        validate_prediction(prediction)

    answerable_ids = [
        case_id
        for case_id, case in case_index.items()
        if case["gold"]["dialogue_action"] == "ANSWER"
    ]
    if not answerable_ids:
        raise Stage0ContractError("capability metrics require at least one ANSWER case")

    per_label_counts = {
        field: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for field in CAPABILITY_FIELDS
    }
    exact_matches = 0
    example_f1_values: list[float] = []
    jaccard_values: list[float] = []
    under_routed_cases = 0
    over_routed_cases = 0

    for case_id in answerable_ids:
        gold = case_index[case_id]["gold"]
        predicted = prediction_index[case_id]
        tp = fp = fn = 0
        exact = True
        for field in CAPABILITY_FIELDS:
            gold_value = bool(gold[field])
            predicted_value = bool(predicted[field])
            if gold_value and predicted_value:
                per_label_counts[field]["tp"] += 1
                tp += 1
            elif not gold_value and predicted_value:
                per_label_counts[field]["fp"] += 1
                fp += 1
                exact = False
            elif gold_value and not predicted_value:
                per_label_counts[field]["fn"] += 1
                fn += 1
                exact = False
            else:
                per_label_counts[field]["tn"] += 1
        if exact:
            exact_matches += 1
        under_routed_cases += int(fn > 0)
        over_routed_cases += int(fp > 0)
        if tp == fp == fn == 0:
            example_f1_values.append(1.0)
            jaccard_values.append(1.0)
        else:
            example_f1_values.append(_safe_ratio(2 * tp, 2 * tp + fp + fn))
            jaccard_values.append(_safe_ratio(tp, tp + fp + fn))

    per_label: dict[str, dict[str, Any]] = {}
    for field, counts in per_label_counts.items():
        precision = _safe_ratio(counts["tp"], counts["tp"] + counts["fp"])
        recall = _safe_ratio(counts["tp"], counts["tp"] + counts["fn"])
        per_label[field] = {
            **counts,
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
        }

    total_tp = sum(item["tp"] for item in per_label_counts.values())
    total_fp = sum(item["fp"] for item in per_label_counts.values())
    total_fn = sum(item["fn"] for item in per_label_counts.values())
    total_tn = sum(item["tn"] for item in per_label_counts.values())
    micro_precision = _safe_ratio(total_tp, total_tp + total_fp)
    micro_recall = _safe_ratio(total_tp, total_tp + total_fn)
    answerability_correct = sum(
        case["gold"]["dialogue_action"]
        == prediction_index[case_id]["dialogue_action"]
        for case_id, case in case_index.items()
    )

    answerable_count = len(answerable_ids)
    assignment_count = answerable_count * len(CAPABILITY_FIELDS)
    gold_positive_assignments = total_tp + total_fn
    gold_negative_assignments = total_tn + total_fp
    return {
        "primary_metric": "macro_f1",
        "case_count": len(case_index),
        "answerable_case_count": answerable_count,
        "clarification_case_count": len(case_index) - answerable_count,
        "macro_f1": sum(item["f1"] for item in per_label.values())
        / len(CAPABILITY_FIELDS),
        "micro_f1": _f1(micro_precision, micro_recall),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "per_label": per_label,
        "example_based_f1": sum(example_f1_values) / answerable_count,
        "jaccard_similarity": sum(jaccard_values) / answerable_count,
        "exact_set_match": exact_matches / answerable_count,
        "hamming_loss": (total_fp + total_fn) / assignment_count,
        "under_routing_rate": under_routed_cases / answerable_count,
        "over_routing_rate": over_routed_cases / answerable_count,
        "under_routing_assignment_rate": _safe_ratio(
            total_fn, gold_positive_assignments
        ),
        "over_routing_assignment_rate": _safe_ratio(
            total_fp, gold_negative_assignments
        ),
        "answerability_accuracy": answerability_correct / len(case_index),
        "counts": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "tn": total_tn,
            "under_routed_cases": under_routed_cases,
            "over_routed_cases": over_routed_cases,
        },
    }


def evaluate_contrast_consistency(
    cases: Iterable[Mapping[str, Any]],
    predictions: Iterable[Mapping[str, Any]],
    contrast_pairs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check whether predicted route changes match frozen Gold contrast changes."""

    case_index = _index_by_case_id(cases, kind="gold")
    prediction_index = _index_by_case_id(predictions, kind="prediction")
    details: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for pair in contrast_pairs:
        contrast_id = str(pair.get("contrast_id", ""))
        if not contrast_id or contrast_id in seen_ids:
            raise Stage0ContractError("contrast IDs must be non-empty and unique")
        seen_ids.add(contrast_id)
        left_id = str(pair["case_a_id"])
        right_id = str(pair["case_b_id"])
        if left_id not in case_index or right_id not in case_index:
            raise Stage0ContractError(f"unknown contrast case in {contrast_id}")
        gold_changed = sorted(
            field
            for field in CAPABILITY_FIELDS
            if bool(case_index[left_id]["gold"][field])
            != bool(case_index[right_id]["gold"][field])
        )
        expected = sorted(str(value) for value in pair["expected_changed_labels"])
        if gold_changed != expected:
            raise Stage0ContractError(
                f"contrast contract does not match Gold for {contrast_id}"
            )
        predicted_changed = sorted(
            field
            for field in CAPABILITY_FIELDS
            if bool(prediction_index[left_id][field])
            != bool(prediction_index[right_id][field])
        )
        consistent = predicted_changed == expected
        details.append(
            {
                "contrast_id": contrast_id,
                "expected_changed_labels": expected,
                "predicted_changed_labels": predicted_changed,
                "consistent": consistent,
            }
        )
    return {
        "pair_count": len(details),
        "consistent_count": sum(item["consistent"] for item in details),
        "consistency_rate": (
            sum(item["consistent"] for item in details) / len(details)
            if details
            else 0.0
        ),
        "details": details,
    }

