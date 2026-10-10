"""Dependency-free final TEST metrics using the frozen Stage 0/Stage 4 definitions."""

from __future__ import annotations

from collections import Counter, defaultdict
import random
from typing import Any, Mapping, Sequence

from .constants import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, CAPABILITY_KEYS


class MetricError(ValueError):
    """Raised when a metric population violates the frozen contracts."""


Signature = tuple[bool, bool, bool]


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def f1_value(precision: float, recall: float) -> float:
    return (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )


def prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1_value(precision, recall),
    }


def gold_signature(row: Mapping[str, Any]) -> Signature:
    return tuple(bool(row[f"gold_{key}_required"]) for key in CAPABILITY_KEYS)  # type: ignore[return-value]


def signature_text(value: Signature) -> str:
    return "".join("1" if bit else "0" for bit in value)


def action_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, str]
) -> dict[str, Any]:
    if not rows:
        raise MetricError("dialogue-action metrics require at least one case")
    per_class: dict[str, Any] = {}
    for action in ("ANSWER", "CLARIFY"):
        tp = sum(
            row["gold_dialogue_action"] == action
            and predictions[row["annotation_case_id"]] == action
            for row in rows
        )
        fp = sum(
            row["gold_dialogue_action"] != action
            and predictions[row["annotation_case_id"]] == action
            for row in rows
        )
        fn = sum(
            row["gold_dialogue_action"] == action
            and predictions[row["annotation_case_id"]] != action
            for row in rows
        )
        per_class[action] = prf(tp, fp, fn)
    correct = sum(
        row["gold_dialogue_action"] == predictions[row["annotation_case_id"]]
        for row in rows
    )
    return {
        "population_count": len(rows),
        "accuracy": safe_ratio(correct, len(rows)),
        "macro_f1": sum(item["f1"] for item in per_class.values()) / 2.0,
        "per_class": per_class,
        "confusion_matrix": {
            gold: {
                predicted: sum(
                    row["gold_dialogue_action"] == gold
                    and predictions[row["annotation_case_id"]] == predicted
                    for row in rows
                )
                for predicted in ("ANSWER", "CLARIFY")
            }
            for gold in ("ANSWER", "CLARIFY")
        },
    }


def core_basic_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, Signature]
) -> dict[str, Any]:
    """Stage 0 set metrics on a nonempty Gold-ANSWER population, unrounded."""

    if not rows:
        raise MetricError("core metrics require at least one Gold ANSWER case")
    per_label: dict[str, Any] = {}
    pooled_tp = pooled_fp = pooled_fn = pooled_tn = 0
    labels = ("RAG", "Memory", "Planning")
    for index, label in enumerate(labels):
        tp = sum(
            gold_signature(row)[index]
            and predictions[row["annotation_case_id"]][index]
            for row in rows
        )
        fp = sum(
            not gold_signature(row)[index]
            and predictions[row["annotation_case_id"]][index]
            for row in rows
        )
        fn = sum(
            gold_signature(row)[index]
            and not predictions[row["annotation_case_id"]][index]
            for row in rows
        )
        tn = len(rows) - tp - fp - fn
        value = prf(tp, fp, fn)
        value.update({"tn": tn, "specificity": safe_ratio(tn, tn + fp)})
        per_label[label] = value
        pooled_tp += tp
        pooled_fp += fp
        pooled_fn += fn
        pooled_tn += tn

    exact = 0
    example_f1_values: list[float] = []
    jaccard_values: list[float] = []
    under = over = mismatched_bits = predicted_capability_count = 0
    distribution: Counter[str] = Counter()
    for row in rows:
        case_id = row["annotation_case_id"]
        gold = gold_signature(row)
        predicted = predictions[case_id]
        exact += int(gold == predicted)
        gold_set = {index for index, value in enumerate(gold) if value}
        predicted_set = {index for index, value in enumerate(predicted) if value}
        intersection = len(gold_set & predicted_set)
        if not gold_set and not predicted_set:
            example_f1_values.append(1.0)
            jaccard_values.append(1.0)
        else:
            example_f1_values.append(
                safe_ratio(2 * intersection, len(gold_set) + len(predicted_set))
            )
            jaccard_values.append(safe_ratio(intersection, len(gold_set | predicted_set)))
        under += int(bool(gold_set - predicted_set))
        over += int(bool(predicted_set - gold_set))
        mismatched_bits += sum(a != b for a, b in zip(gold, predicted, strict=True))
        predicted_capability_count += sum(predicted)
        distribution[signature_text(predicted)] += 1

    micro_precision = safe_ratio(pooled_tp, pooled_tp + pooled_fp)
    micro_recall = safe_ratio(pooled_tp, pooled_tp + pooled_fn)
    return {
        "population_count": len(rows),
        "valid_prediction_coverage_count": len(rows),
        "valid_prediction_coverage_rate": 1.0,
        "macro_f1": sum(item["f1"] for item in per_label.values()) / 3.0,
        "micro_f1": f1_value(micro_precision, micro_recall),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "per_label": per_label,
        "exact_capability_set_match": safe_ratio(exact, len(rows)),
        "exact_correct_case_count": exact,
        "example_based_f1": sum(example_f1_values) / len(rows),
        "jaccard": sum(jaccard_values) / len(rows),
        "hamming_loss": safe_ratio(mismatched_bits, len(rows) * 3),
        "under_routing_count": under,
        "under_routing_rate": safe_ratio(under, len(rows)),
        "over_routing_count": over,
        "over_routing_rate": safe_ratio(over, len(rows)),
        "mean_predicted_capability_count": safe_ratio(
            predicted_capability_count, len(rows)
        ),
        "prediction_signature_distribution": dict(sorted(distribution.items())),
        "pooled_counts": {
            "tp": pooled_tp,
            "fp": pooled_fp,
            "fn": pooled_fn,
            "tn": pooled_tn,
        },
    }


def family_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, Signature]
) -> dict[str, Any]:
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["canonical_scenario_family_id"])].append(row)
    if not families or any(len(items) != 2 for items in families.values()):
        raise MetricError("family population must contain complete two-utterance families")
    both_correct = prediction_consistent = 0
    for items in families.values():
        predicted = {predictions[row["annotation_case_id"]] for row in items}
        prediction_consistent += int(len(predicted) == 1)
        both_correct += int(
            all(
                predictions[row["annotation_case_id"]] == gold_signature(row)
                for row in items
            )
        )
    return {
        "family_count": len(families),
        "both_utterances_exact_correct_count": both_correct,
        "both_utterances_exact_correct_rate": safe_ratio(
            both_correct, len(families)
        ),
        "prediction_consistent_count": prediction_consistent,
        "prediction_consistency_rate": safe_ratio(
            prediction_consistent, len(families)
        ),
    }


def capability_contrast_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, Signature]
) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group_id = str(row.get("contrast_group_id") or "")
        axis = str(row.get("contrast_axis") or "")
        if group_id and axis in {"RAG", "MEMORY", "PLANNING"}:
            groups[(group_id, axis)].append(row)
    details: list[dict[str, Any]] = []
    within = vector_match_count = pattern_match_count = 0
    for (group_id, axis), items in sorted(groups.items()):
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["canonical_scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(values) != 2 for values in families.values()):
            raise MetricError(f"malformed capability contrast group: {group_id}")
        predicted_family: dict[str, Signature] = {}
        gold_family: dict[str, Signature] = {}
        internally_consistent = True
        for family_id, values in families.items():
            predicted_values = {predictions[row["annotation_case_id"]] for row in values}
            gold_values = {gold_signature(row) for row in values}
            if len(predicted_values) != 1 or len(gold_values) != 1:
                internally_consistent = False
            else:
                predicted_family[family_id] = next(iter(predicted_values))
                gold_family[family_id] = next(iter(gold_values))
        vector_match = False
        if internally_consistent:
            left, right = sorted(families)
            gold_delta = tuple(
                int(b) - int(a)
                for a, b in zip(
                    gold_family[left], gold_family[right], strict=True
                )
            )
            predicted_delta = tuple(
                int(b) - int(a)
                for a, b in zip(
                    predicted_family[left], predicted_family[right], strict=True
                )
            )
            vector_match = predicted_delta == gold_delta
        pattern_match = internally_consistent and predicted_family == gold_family
        within += int(internally_consistent)
        vector_match_count += int(vector_match)
        pattern_match_count += int(pattern_match)
        details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "within_family_prediction_consistent": internally_consistent,
                "gold_capability_change_vector_matched": vector_match,
                "complete_gold_family_pattern_matched": pattern_match,
            }
        )
    total = len(groups)
    return {
        "definition": (
            "Capability-axis groups only; internally consistent two-utterance "
            "family predictions and the exact directed frozen Gold change vector."
        ),
        "eligible_contrast_groups": total,
        "within_family_prediction_consistent_groups": within,
        "within_family_prediction_consistency_rate": safe_ratio(within, total),
        "consistent_contrast_groups": vector_match_count,
        "contrast_consistency_rate": safe_ratio(vector_match_count, total),
        "complete_gold_pattern_matched_groups": pattern_match_count,
        "complete_gold_pattern_match_rate": safe_ratio(pattern_match_count, total),
        "groups": details,
    }


def core_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, Signature]
) -> dict[str, Any]:
    result = core_basic_metrics(rows, predictions)
    result["family_metrics"] = family_metrics(rows, predictions)
    result["capability_contrast"] = capability_contrast_metrics(rows, predictions)
    pages = sorted({str(row["current_page"]) for row in rows})
    writers = sorted({str(row["writer_id"]) for row in rows})
    result["page_stratified_metrics"] = {
        value: core_basic_metrics(
            [row for row in rows if row["current_page"] == value], predictions
        )
        for value in pages
    }
    result["writer_stratified_metrics"] = {
        value: core_basic_metrics(
            [row for row in rows if row["writer_id"] == value], predictions
        )
        for value in writers
    }
    return result


def _action_contrast_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, str]
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("contrast_group_id") and row.get("contrast_axis") == "CLARIFICATION":
            groups[str(row["contrast_group_id"])].append(row)
    details = []
    within = vector_count = pattern_count = 0
    for group_id, items in sorted(groups.items()):
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["canonical_scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(values) != 2 for values in families.values()):
            raise MetricError(f"malformed clarification contrast group: {group_id}")
        predicted: dict[str, str] = {}
        gold: dict[str, str] = {}
        internally_consistent = True
        for family_id, values in families.items():
            pv = {predictions[row["annotation_case_id"]] for row in values}
            gv = {str(row["gold_dialogue_action"]) for row in values}
            if len(pv) != 1 or len(gv) != 1:
                internally_consistent = False
            else:
                predicted[family_id] = next(iter(pv))
                gold[family_id] = next(iter(gv))
        vector_match = False
        if internally_consistent:
            left, right = sorted(families)
            encode = lambda value: int(value == "CLARIFY")
            vector_match = (
                encode(predicted[right]) - encode(predicted[left])
                == encode(gold[right]) - encode(gold[left])
            )
        pattern_match = internally_consistent and predicted == gold
        within += int(internally_consistent)
        vector_count += int(vector_match)
        pattern_count += int(pattern_match)
        details.append(
            {
                "contrast_group_id": group_id,
                "within_family_prediction_consistent": internally_consistent,
                "clarification_change_vector_matched": vector_match,
                "clarification_gold_pattern_matched": pattern_match,
            }
        )
    total = len(groups)
    return {
        "eligible_contrast_groups": total,
        "within_family_prediction_consistent_groups": within,
        "within_family_prediction_consistency_rate": safe_ratio(within, total),
        "consistent_contrast_groups": vector_count,
        "clarification_contrast_consistency_rate": safe_ratio(vector_count, total),
        "clarification_gold_pattern_matched_groups": pattern_count,
        "clarification_gold_pattern_match_rate": safe_ratio(pattern_count, total),
        "groups": details,
    }


def clarification_metrics(
    rows: Sequence[Mapping[str, Any]], predictions: Mapping[str, str]
) -> dict[str, Any]:
    result = action_metrics(rows, predictions)
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["canonical_scenario_family_id"])].append(row)
    if len(families) == 0 or any(len(items) != 2 for items in families.values()):
        raise MetricError("clarification family population is malformed")
    both_correct = sum(
        all(
            predictions[row["annotation_case_id"]] == row["gold_dialogue_action"]
            for row in items
        )
        for items in families.values()
    )
    consistent = sum(
        len({predictions[row["annotation_case_id"]] for row in items}) == 1
        for items in families.values()
    )
    result["gold_answer_count"] = sum(
        row["gold_dialogue_action"] == "ANSWER" for row in rows
    )
    result["gold_clarify_count"] = sum(
        row["gold_dialogue_action"] == "CLARIFY" for row in rows
    )
    result["family_both_utterances_correct"] = {
        "family_count": len(families),
        "correct_count": both_correct,
        "rate": safe_ratio(both_correct, len(families)),
    }
    result["family_prediction_consistency"] = {
        "family_count": len(families),
        "consistent_count": consistent,
        "rate": safe_ratio(consistent, len(families)),
    }
    result["clarification_contrast"] = _action_contrast_metrics(rows, predictions)
    result["page_stratified_metrics"] = {
        value: action_metrics(
            [row for row in rows if row["current_page"] == value], predictions
        )
        for value in sorted({str(row["current_page"]) for row in rows})
    }
    result["writer_stratified_metrics"] = {
        value: action_metrics(
            [row for row in rows if row["writer_id"] == value], predictions
        )
        for value in sorted({str(row["writer_id"]) for row in rows})
    }
    return result


def binary_metrics(
    rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, bool],
    gold_key: str,
) -> dict[str, Any]:
    tp = sum(bool(row[gold_key]) and predictions[row["annotation_case_id"]] for row in rows)
    fp = sum(not bool(row[gold_key]) and predictions[row["annotation_case_id"]] for row in rows)
    fn = sum(bool(row[gold_key]) and not predictions[row["annotation_case_id"]] for row in rows)
    tn = len(rows) - tp - fp - fn
    value = prf(tp, fp, fn)
    value.update(
        {
            "tn": tn,
            "accuracy": safe_ratio(tp + tn, len(rows)),
            "specificity": safe_ratio(tn, tn + fp),
            "positive_prediction_rate": safe_ratio(tp + fp, len(rows)),
            "population_count": len(rows),
        }
    )
    return value


def component_metrics(
    rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, bool],
    *,
    capability: str,
) -> dict[str, Any]:
    if capability not in {"rag", "memory"}:
        raise MetricError("component capability must be rag or memory")
    gold_key = f"gold_{capability}_required"
    result = binary_metrics(rows, predictions, gold_key)
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["canonical_scenario_family_id"])].append(row)
    if any(len(items) != 2 for items in families.values()):
        raise MetricError("component family population is malformed")
    both_correct = sum(
        all(predictions[row["annotation_case_id"]] == bool(row[gold_key]) for row in items)
        for items in families.values()
    )
    consistent = sum(
        len({predictions[row["annotation_case_id"]] for row in items}) == 1
        for items in families.values()
    )
    result["family_metrics"] = {
        "family_count": len(families),
        "both_utterances_correct_count": both_correct,
        "both_utterances_correct_rate": safe_ratio(both_correct, len(families)),
        "prediction_consistent_count": consistent,
        "prediction_consistency_rate": safe_ratio(consistent, len(families)),
    }
    axis = capability.upper()
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("contrast_group_id") and row.get("contrast_axis") == axis:
            groups[str(row["contrast_group_id"])].append(row)
    details = []
    vector_count = pattern_count = within = 0
    for group_id, items in sorted(groups.items()):
        group_families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            group_families[str(row["canonical_scenario_family_id"])].append(row)
        if len(group_families) != 2 or any(
            len(values) != 2 for values in group_families.values()
        ):
            raise MetricError(f"malformed specialist contrast group: {group_id}")
        pf: dict[str, bool] = {}
        gf: dict[str, bool] = {}
        internally_consistent = True
        for family_id, values in group_families.items():
            pv = {predictions[row["annotation_case_id"]] for row in values}
            gv = {bool(row[gold_key]) for row in values}
            if len(pv) != 1 or len(gv) != 1:
                internally_consistent = False
            else:
                pf[family_id] = next(iter(pv))
                gf[family_id] = next(iter(gv))
        vector_match = False
        if internally_consistent:
            left, right = sorted(group_families)
            vector_match = int(pf[right]) - int(pf[left]) == int(gf[right]) - int(
                gf[left]
            )
        pattern_match = internally_consistent and pf == gf
        within += int(internally_consistent)
        vector_count += int(vector_match)
        pattern_count += int(pattern_match)
        details.append(
            {
                "contrast_group_id": group_id,
                "within_family_prediction_consistent": internally_consistent,
                "target_change_vector_matched": vector_match,
                "target_gold_pattern_matched": pattern_match,
            }
        )
    result["contrast_metrics"] = {
        "eligible_contrast_groups": len(groups),
        "within_family_prediction_consistent_groups": within,
        "contrast_consistent_groups": vector_count,
        "contrast_consistency_rate": safe_ratio(vector_count, len(groups)),
        "gold_pattern_matched_groups": pattern_count,
        "gold_pattern_match_rate": safe_ratio(pattern_count, len(groups)),
        "groups": details,
    }
    result["page_stratified_metrics"] = {
        value: binary_metrics(
            [row for row in rows if row["current_page"] == value],
            predictions,
            gold_key,
        )
        for value in sorted({str(row["current_page"]) for row in rows})
    }
    result["writer_stratified_metrics"] = {
        value: binary_metrics(
            [row for row in rows if row["writer_id"] == value],
            predictions,
            gold_key,
        )
        for value in sorted({str(row["writer_id"]) for row in rows})
    }
    return result


def compare_component_to_b4(
    rows: Sequence[Mapping[str, Any]],
    specialist: Mapping[str, bool],
    b4: Mapping[str, bool],
    *,
    gold_key: str,
) -> dict[str, Any]:
    result = {
        "population_count": len(rows),
        "agreement_count": 0,
        "specialist_only_correct": 0,
        "b4_only_correct": 0,
        "both_correct": 0,
        "both_wrong": 0,
    }
    for row in rows:
        case_id = row["annotation_case_id"]
        gold = bool(row[gold_key])
        specialist_correct = specialist[case_id] == gold
        b4_correct = b4[case_id] == gold
        result["agreement_count"] += int(specialist[case_id] == b4[case_id])
        result["specialist_only_correct"] += int(specialist_correct and not b4_correct)
        result["b4_only_correct"] += int(b4_correct and not specialist_correct)
        result["both_correct"] += int(specialist_correct and b4_correct)
        result["both_wrong"] += int(not specialist_correct and not b4_correct)
    result["agreement_rate"] = safe_ratio(result["agreement_count"], len(rows))
    return result


def _route_bits(value: str) -> Signature | None:
    if len(value) == 3 and set(value) <= {"0", "1"}:
        return tuple(bit == "1" for bit in value)  # type: ignore[return-value]
    return None


def end_to_end_contrast_metrics(
    rows: Sequence[Mapping[str, Any]], route_predictions: Mapping[str, str]
) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group_id = str(row.get("contrast_group_id") or "")
        axis = str(row.get("contrast_axis") or "")
        if group_id and axis in {"RAG", "MEMORY", "PLANNING", "CLARIFICATION"}:
            groups[(group_id, axis)].append(row)
    details = []
    within = vector_count = pattern_count = 0
    for (group_id, axis), items in sorted(groups.items()):
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["canonical_scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(values) != 2 for values in families.values()):
            raise MetricError(f"malformed end-to-end contrast group: {group_id}")
        predicted: dict[str, str] = {}
        gold: dict[str, str] = {}
        internally_consistent = True
        for family_id, values in families.items():
            pv = {route_predictions[row["annotation_case_id"]] for row in values}
            gv = {
                "CLARIFY"
                if row["gold_dialogue_action"] == "CLARIFY"
                else signature_text(gold_signature(row))
                for row in values
            }
            if len(pv) != 1 or len(gv) != 1:
                internally_consistent = False
            else:
                predicted[family_id] = next(iter(pv))
                gold[family_id] = next(iter(gv))
        vector_match = False
        if internally_consistent:
            left, right = sorted(families)
            predicted_left = _route_bits(predicted[left])
            predicted_right = _route_bits(predicted[right])
            gold_left = _route_bits(gold[left])
            gold_right = _route_bits(gold[right])
            if all(
                value is not None
                for value in (predicted_left, predicted_right, gold_left, gold_right)
            ):
                vector_match = tuple(
                    int(b) - int(a)
                    for a, b in zip(predicted_left, predicted_right, strict=True)  # type: ignore[arg-type]
                ) == tuple(
                    int(b) - int(a)
                    for a, b in zip(gold_left, gold_right, strict=True)  # type: ignore[arg-type]
                )
            else:
                vector_match = predicted == gold
        pattern_match = internally_consistent and predicted == gold
        within += int(internally_consistent)
        vector_count += int(vector_match)
        pattern_count += int(pattern_match)
        details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "within_family_prediction_consistent": internally_consistent,
                "directed_full_route_change_consistent_with_gold": vector_match,
                "complete_gold_route_pattern_matched": pattern_match,
            }
        )
    total = len(groups)
    return {
        "eligible_contrast_groups": total,
        "within_family_prediction_consistent_groups": within,
        "within_family_prediction_consistency_rate": safe_ratio(within, total),
        "directed_full_route_change_consistent_groups": vector_count,
        "contrast_consistency_rate": safe_ratio(vector_count, total),
        "complete_gold_route_pattern_matched_groups": pattern_count,
        "complete_gold_route_pattern_match_rate": safe_ratio(pattern_count, total),
        "groups": details,
    }


def _end_to_end_basic(
    rows: Sequence[Mapping[str, Any]],
    action_predictions: Mapping[str, str],
    route_predictions: Mapping[str, str],
) -> dict[str, Any]:
    action = action_metrics(rows, action_predictions)
    exact = sum(
        route_predictions[row["annotation_case_id"]]
        == (
            "CLARIFY"
            if row["gold_dialogue_action"] == "CLARIFY"
            else signature_text(gold_signature(row))
        )
        for row in rows
    )
    return {
        "population_count": len(rows),
        "dialogue_action_accuracy": action["accuracy"],
        "dialogue_action_macro_f1": action["macro_f1"],
        "dialogue_action_per_class": action["per_class"],
        "full_route_signature_exact_count": exact,
        "full_route_signature_exact_match": safe_ratio(exact, len(rows)),
    }


def end_to_end_metrics(
    rows: Sequence[Mapping[str, Any]],
    action_predictions: Mapping[str, str],
    route_predictions: Mapping[str, str],
) -> dict[str, Any]:
    result = _end_to_end_basic(rows, action_predictions, route_predictions)
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["canonical_scenario_family_id"])].append(row)
    if any(len(items) != 2 for items in families.values()):
        raise MetricError("end-to-end family population is malformed")
    both_correct = sum(
        all(
            route_predictions[row["annotation_case_id"]]
            == (
                "CLARIFY"
                if row["gold_dialogue_action"] == "CLARIFY"
                else signature_text(gold_signature(row))
            )
            for row in items
        )
        for items in families.values()
    )
    consistent = sum(
        len({route_predictions[row["annotation_case_id"]] for row in items}) == 1
        for items in families.values()
    )
    result["family_both_utterances_correct"] = {
        "family_count": len(families),
        "correct_count": both_correct,
        "rate": safe_ratio(both_correct, len(families)),
    }
    result["family_prediction_consistency"] = {
        "family_count": len(families),
        "consistent_count": consistent,
        "rate": safe_ratio(consistent, len(families)),
    }
    result["complete_contrast"] = end_to_end_contrast_metrics(rows, route_predictions)
    result["page_stratified_metrics"] = {
        value: _end_to_end_basic(
            [row for row in rows if row["current_page"] == value],
            action_predictions,
            route_predictions,
        )
        for value in sorted({str(row["current_page"]) for row in rows})
    }
    result["writer_stratified_metrics"] = {
        value: _end_to_end_basic(
            [row for row in rows if row["writer_id"] == value],
            action_predictions,
            route_predictions,
        )
        for value in sorted({str(row["writer_id"]) for row in rows})
    }
    result["predicted_clarify_count"] = sum(
        value == "CLARIFY" for value in action_predictions.values()
    )
    result["core_executed_count"] = sum(
        value == "ANSWER" for value in action_predictions.values()
    )
    return result


BOOTSTRAP_METRICS = (
    "macro_f1",
    "exact_capability_set_match",
    "jaccard",
    "under_routing_rate",
    "over_routing_rate",
)


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise MetricError("percentile requires at least one value")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * probability
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_analysis(
    rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Signature]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["canonical_scenario_family_id"])].append(row)
    family_ids = sorted(families, key=lambda value: value.encode("utf-8"))
    if not family_ids or any(len(items) != 2 for items in families.values()):
        raise MetricError("bootstrap requires complete Gold ANSWER families")
    method_values = {
        method_id: {metric: [] for metric in BOOTSTRAP_METRICS}
        for method_id in predictions
    }
    pairs = (
        ("R2V2-B4_JOINT_LLM", "R2V2-B3_OVR", "B4_minus_B3"),
        ("R2V2-P1_HYBRID", "R2V2-B4_JOINT_LLM", "P1_minus_B4"),
        ("R2V2-P2_RAG_SPECIALIST_COMPOSITION", "R2V2-B4_JOINT_LLM", "P2_minus_B4"),
        ("R2V2-P3_RAG_MEMORY_SPECIALISTS", "R2V2-B4_JOINT_LLM", "P3_minus_B4"),
        ("R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", "R2V2-B4_JOINT_LLM", "P4_minus_B4"),
        ("R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", "R2V2-P3_RAG_MEMORY_SPECIALISTS", "P4_minus_P3"),
    )
    for left, right, _name in pairs:
        if left not in predictions or right not in predictions:
            raise MetricError("bootstrap paired-difference method is absent")
    difference_values = {
        name: {metric: [] for metric in BOOTSTRAP_METRICS}
        for _left, _right, name in pairs
    }
    rng = random.Random(seed)
    for _ in range(replicates):
        sampled_ids = [rng.choice(family_ids) for _ in family_ids]
        sampled_rows = [row for family_id in sampled_ids for row in families[family_id]]
        replicate_metrics: dict[str, dict[str, float]] = {}
        for method_id, method_predictions in predictions.items():
            value = core_basic_metrics(sampled_rows, method_predictions)
            replicate_metrics[method_id] = {
                metric: float(value[metric]) for metric in BOOTSTRAP_METRICS
            }
            for metric in BOOTSTRAP_METRICS:
                method_values[method_id][metric].append(replicate_metrics[method_id][metric])
        for left, right, name in pairs:
            for metric in BOOTSTRAP_METRICS:
                difference_values[name][metric].append(
                    replicate_metrics[left][metric] - replicate_metrics[right][metric]
                )

    def summarize(values: Mapping[str, Sequence[float]]) -> dict[str, Any]:
        return {
            metric: {
                "lower_2_5_percentile": percentile(metric_values, 0.025),
                "upper_97_5_percentile": percentile(metric_values, 0.975),
            }
            for metric, metric_values in values.items()
        }

    return {
        "schema_version": "rq2-v2-stage5e-family-clustered-bootstrap-v1",
        "label": "DESCRIPTIVE_FAMILY_CLUSTERED_UNCERTAINTY",
        "resampling_unit": "canonical_scenario_family_id",
        "population": "GOLD_ANSWER_FAMILIES",
        "family_count": len(family_ids),
        "seed": seed,
        "replicates": replicates,
        "interval": "PERCENTILE_95",
        "percentile_convention": "LINEAR_INTERPOLATION_AT_(N_MINUS_1)_TIMES_P",
        "method_intervals": {
            method_id: summarize(values)
            for method_id, values in sorted(method_values.items())
        },
        "paired_difference_intervals": {
            name: summarize(values)
            for name, values in difference_values.items()
        },
        "significance_claimed": False,
        "selection_rule_changed_by_bootstrap": False,
        "p4_promoted": False,
    }
