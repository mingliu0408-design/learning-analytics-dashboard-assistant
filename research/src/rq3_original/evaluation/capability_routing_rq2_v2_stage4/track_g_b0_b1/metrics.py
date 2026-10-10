"""Deterministic Stage 4G clarification, core, and end-to-end metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence


CAPABILITY_KEYS = ("rag", "memory", "planning")


def _q(value: float) -> float:
    return round(float(value), 6)


def _rate(numerator: int | float, denominator: int | float) -> float:
    return _q(float(numerator) / float(denominator)) if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = _rate(2 * precision * recall, precision + recall)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def clarification_metrics(rows: Sequence[Mapping[str, Any]], *, strata: bool = True) -> dict[str, Any]:
    tp = sum(r["gold_dialogue_action"] == "CLARIFY" and r["predicted_dialogue_action"] == "CLARIFY" for r in rows)
    fp = sum(r["gold_dialogue_action"] == "ANSWER" and r["predicted_dialogue_action"] == "CLARIFY" for r in rows)
    fn = sum(r["gold_dialogue_action"] == "CLARIFY" and r["predicted_dialogue_action"] == "ANSWER" for r in rows)
    correct = sum(r["gold_dialogue_action"] == r["predicted_dialogue_action"] for r in rows)
    answer_count = sum(r["gold_dialogue_action"] == "ANSWER" for r in rows)
    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["scenario_family_id"])].append(row)
    family_correct = sum(
        len(items) == 2
        and all(x["gold_dialogue_action"] == x["predicted_dialogue_action"] for x in items)
        for items in by_family.values()
    )
    value: dict[str, Any] = {
        "population_count": len(rows),
        "gold_answer_count": answer_count,
        "gold_clarify_count": len(rows) - answer_count,
        "clarify": _prf(tp, fp, fn),
        "dialogue_action_accuracy": _rate(correct, len(rows)),
        "false_clarify_rate_on_gold_answer": _rate(fp, answer_count),
        "family_both_utterances_correct": {
            "correct_families": family_correct,
            "family_count": len(by_family),
            "rate": _rate(family_correct, len(by_family)),
        },
    }
    if strata:
        pages = sorted({str(row["current_page"]) for row in rows})
        value["page_stratified_metrics"] = {
            page: clarification_metrics(
                [row for row in rows if row["current_page"] == page], strata=False
            )
            for page in pages
        }
        value["writer_a_vs_writer_b_metrics"] = {
            "status": "NOT_AVAILABLE_AUTHORIZED_WRITER_JOIN_ABSENT",
            "reason": "Writer identity is absent from the frozen Stage 4-0 DEV inputs and cannot be inferred from identifiers.",
        }
    return value


def _bits(row: Mapping[str, Any], prefix: str) -> tuple[bool, bool, bool]:
    return tuple(bool(row[f"{prefix}_{key}"]) for key in CAPABILITY_KEYS)  # type: ignore[return-value]


def _contrast_consistency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group = str(row.get("dev_contrast_group_id") or "")
        axis = str(row.get("dev_contrast_axis") or "")
        if group and axis in {"RAG", "MEMORY", "PLANNING"}:
            grouped[group].append(row)
    eligible = 0
    consistent = 0
    for items in grouped.values():
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(value) != 2 for value in families.values()):
            continue
        eligible += 1
        family_ids = sorted(families)
        gold_family: list[tuple[bool, bool, bool]] = []
        predicted_family: list[tuple[bool, bool, bool]] = []
        internally_consistent = True
        for family_id in family_ids:
            gold_values = {_bits(row, "gold") for row in families[family_id]}
            predicted_values = {_bits(row, "predicted") for row in families[family_id]}
            if len(gold_values) != 1 or len(predicted_values) != 1:
                internally_consistent = False
                break
            gold_family.append(next(iter(gold_values)))
            predicted_family.append(next(iter(predicted_values)))
        if not internally_consistent:
            continue
        gold_delta = tuple(int(b) - int(a) for a, b in zip(gold_family[0], gold_family[1]))
        predicted_delta = tuple(
            int(b) - int(a) for a, b in zip(predicted_family[0], predicted_family[1])
        )
        if predicted_delta == gold_delta:
            consistent += 1
    return {
        "definition": "Exact pairwise capability-change vector after requiring internally consistent predictions for both utterances in each family.",
        "eligible_contrast_groups": eligible,
        "consistent_contrast_groups": consistent,
        "rate": _rate(consistent, eligible),
    }


def core_metrics(rows: Sequence[Mapping[str, Any]], *, strata: bool = True) -> dict[str, Any]:
    per_label: dict[str, dict[str, Any]] = {}
    pooled_tp = pooled_fp = pooled_fn = 0
    labels = ("RAG", "Memory", "Planning")
    for label, key in zip(labels, CAPABILITY_KEYS):
        tp = sum(bool(r[f"gold_{key}"]) and bool(r[f"predicted_{key}"]) for r in rows)
        fp = sum(not bool(r[f"gold_{key}"]) and bool(r[f"predicted_{key}"]) for r in rows)
        fn = sum(bool(r[f"gold_{key}"]) and not bool(r[f"predicted_{key}"]) for r in rows)
        per_label[label] = _prf(tp, fp, fn)
        pooled_tp += tp
        pooled_fp += fp
        pooled_fn += fn
    exact = sum(_bits(row, "gold") == _bits(row, "predicted") for row in rows)
    example_f1: list[float] = []
    jaccard: list[float] = []
    mismatched_bits = 0
    under = over = 0
    for row in rows:
        gold = _bits(row, "gold")
        predicted = _bits(row, "predicted")
        gold_set = {index for index, value in enumerate(gold) if value}
        predicted_set = {index for index, value in enumerate(predicted) if value}
        intersection = len(gold_set.intersection(predicted_set))
        example_f1.append(
            1.0 if not gold_set and not predicted_set else 2 * intersection / (len(gold_set) + len(predicted_set))
        )
        union = len(gold_set.union(predicted_set))
        jaccard.append(1.0 if not union else intersection / union)
        mismatched_bits += sum(a != b for a, b in zip(gold, predicted))
        under += bool(gold_set - predicted_set)
        over += bool(predicted_set - gold_set)
    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["scenario_family_id"])].append(row)
    family_correct = sum(
        len(items) == 2 and all(_bits(row, "gold") == _bits(row, "predicted") for row in items)
        for items in by_family.values()
    )
    result: dict[str, Any] = {
        "population_count": len(rows),
        "macro_f1": _q(sum(value["f1"] for value in per_label.values()) / len(per_label)),
        "micro_f1": _prf(pooled_tp, pooled_fp, pooled_fn)["f1"],
        "per_label": per_label,
        "exact_capability_set_match": _rate(exact, len(rows)),
        "example_based_f1": _q(sum(example_f1) / len(example_f1)) if example_f1 else 0.0,
        "jaccard": _q(sum(jaccard) / len(jaccard)) if jaccard else 0.0,
        "hamming_loss": _rate(mismatched_bits, len(rows) * len(CAPABILITY_KEYS)),
        "under_routing_rate": _rate(under, len(rows)),
        "over_routing_rate": _rate(over, len(rows)),
        "family_both_utterances_correct": {
            "correct_families": family_correct,
            "family_count": len(by_family),
            "rate": _rate(family_correct, len(by_family)),
        },
        "contrast_consistency": _contrast_consistency(rows),
    }
    if strata:
        pages = sorted({str(row["current_page"]) for row in rows})
        result["page_stratified_metrics"] = {
            page: core_metrics([row for row in rows if row["current_page"] == page], strata=False)
            for page in pages
        }
        result["writer_a_vs_writer_b_metrics"] = {
            "status": "NOT_AVAILABLE_AUTHORIZED_WRITER_JOIN_ABSENT",
            "reason": "Writer identity is absent from the frozen Stage 4-0 DEV inputs and cannot be inferred from identifiers.",
        }
    return result


def end_to_end_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exact = 0
    action_correct = 0
    by_family: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        action_match = row["gold_dialogue_action"] == row["predicted_dialogue_action"]
        action_correct += action_match
        if row["gold_dialogue_action"] == "CLARIFY":
            route_exact = bool(action_match)
        else:
            route_exact = bool(action_match and _bits(row, "gold") == _bits(row, "predicted"))
        exact += route_exact
        by_family[str(row["scenario_family_id"])].append(route_exact)
    family_exact = sum(len(values) == 2 and all(values) for values in by_family.values())
    predicted_clarify = sum(row["predicted_dialogue_action"] == "CLARIFY" for row in rows)
    return {
        "population_count": len(rows),
        "full_route_signature_exact_match": _rate(exact, len(rows)),
        "dialogue_action_accuracy": _rate(action_correct, len(rows)),
        "family_level_full_route_consistency": {
            "correct_families": family_exact,
            "family_count": len(by_family),
            "rate": _rate(family_exact, len(by_family)),
        },
        "predicted_clarify_count": predicted_clarify,
        "core_executed_count": len(rows) - predicted_clarify,
    }


__all__ = ["clarification_metrics", "core_metrics", "end_to_end_metrics"]
