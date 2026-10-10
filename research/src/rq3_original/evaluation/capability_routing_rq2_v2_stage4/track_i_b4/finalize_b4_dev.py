"""Create deterministic B4 DEV derived outputs, metrics, and final freeze."""

from __future__ import annotations

import collections
import csv
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from build_b4_preparation import LABEL_FIELDS
from execute_b4_dev import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    EXPECTED_PROMPT_SHA256,
    EXPECTED_SCHEMA_SHA256,
    LOGICAL_CALL_CEILING,
    MANIFEST_DIFF_PATH,
    MAX_OUTPUT_TOKENS,
    PHYSICAL_ATTEMPT_CEILING,
    TERMINAL_RESULTS_PATH,
    TRACK_DIR,
    V2_MANIFEST_PATH,
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    sha256_file,
)


DEV_PROTOCOL_DIR = TRACK_DIR.parent / "dev_protocol"
PREDICTIONS_PATH = TRACK_DIR / "b4_dev_predictions_v1.csv"
ERROR_REGISTRY_PATH = TRACK_DIR / "b4_dev_error_registry_v1.csv"
USAGE_PATH = TRACK_DIR / "b4_dev_usage_and_cost_v1.json"
METRICS_PATH = TRACK_DIR / "b4_dev_metrics_v1.json"
FINAL_FREEZE_PATH = TRACK_DIR / "b4_final_frozen_configuration_v1.json"
RESULTS_REPORT_PATH = TRACK_DIR / "B4_DEV_EXECUTION_RESULTS.md"
STATUS_PATH = TRACK_DIR / "B4_DEV_EXECUTION_STATUS.md"
INPUT_PRICE_PER_MILLION = Decimal("0.15")
OUTPUT_PRICE_PER_MILLION = Decimal("0.60")
PRICING_REFERENCE_DATE = "2026-08-31"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        handle.flush()
    temporary.replace(path)


def _bool_csv(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _yes_no(value: str) -> bool:
    if value == "YES":
        return True
    if value == "NO":
        return False
    raise ValueError(f"Expected YES or NO, observed {value!r}")


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return round(float(numerator) / float(denominator), 12)


def _prediction_signature(prediction: Mapping[str, bool]) -> str:
    return "".join("1" if prediction[field] else "0" for field in LABEL_FIELDS)


def _gold_labels(row: Mapping[str, str]) -> dict[str, bool]:
    return {
        "rag_required": _yes_no(row["final_rag_required"]),
        "memory_required": _yes_no(row["final_memory_required"]),
        "planning_required": _yes_no(row["final_planning_required"]),
    }


def _core_metrics(
    case_ids: Sequence[str],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    ids = [case_id for case_id in case_ids if case_id in predictions]
    if not ids:
        return {
            "status": "NOT_COMPUTABLE_NO_VALID_PREDICTIONS",
            "case_count": 0,
            "macro_f1": None,
            "micro_f1": None,
            "micro_precision": None,
            "micro_recall": None,
            "per_label": {
                field: {
                    "tp": 0,
                    "fp": 0,
                    "fn": 0,
                    "tn": 0,
                    "precision": None,
                    "recall": None,
                    "f1": None,
                }
                for field in LABEL_FIELDS
            },
            "exact_capability_set_match": None,
            "exact_capability_set_correct_count": 0,
            "example_based_f1": None,
            "jaccard": None,
            "hamming_loss": None,
            "under_routing": {
                "case_count": 0,
                "case_rate": None,
                "label_decision_count": 0,
                "label_decision_rate": None,
            },
            "over_routing": {
                "case_count": 0,
                "case_rate": None,
                "label_decision_count": 0,
                "label_decision_rate": None,
            },
        }
    per_label: dict[str, Any] = {}
    total_tp = total_fp = total_fn = total_tn = 0
    exact_correct = 0
    example_f1_values: list[float] = []
    jaccard_values: list[float] = []
    hamming_errors = 0
    under_case_count = 0
    over_case_count = 0
    under_label_count = 0
    over_label_count = 0

    for field in LABEL_FIELDS:
        tp = fp = fn = tn = 0
        for case_id in ids:
            gold = _gold_labels(gold_by_id[case_id])[field]
            predicted = bool(predictions[case_id][field])
            if gold and predicted:
                tp += 1
            elif not gold and predicted:
                fp += 1
            elif gold and not predicted:
                fn += 1
            else:
                tn += 1
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_label[field] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_tn += tn

    for case_id in ids:
        gold = _gold_labels(gold_by_id[case_id])
        prediction = predictions[case_id]
        exact = all(bool(prediction[field]) == gold[field] for field in LABEL_FIELDS)
        exact_correct += int(exact)
        gold_positive = {field for field in LABEL_FIELDS if gold[field]}
        predicted_positive = {
            field for field in LABEL_FIELDS if bool(prediction[field])
        }
        intersection = len(gold_positive & predicted_positive)
        combined_size = len(gold_positive) + len(predicted_positive)
        union_size = len(gold_positive | predicted_positive)
        example_f1_values.append(
            1.0 if combined_size == 0 else (2.0 * intersection / combined_size)
        )
        jaccard_values.append(1.0 if union_size == 0 else intersection / union_size)
        misses = sum(gold[field] and not prediction[field] for field in LABEL_FIELDS)
        extras = sum(not gold[field] and prediction[field] for field in LABEL_FIELDS)
        hamming_errors += misses + extras
        under_label_count += misses
        over_label_count += extras
        under_case_count += int(misses > 0)
        over_case_count += int(extras > 0)

    macro_f1 = (
        round(sum(per_label[field]["f1"] for field in LABEL_FIELDS) / 3.0, 12)
        if ids
        else 0.0
    )
    micro_precision = _safe_div(total_tp, total_tp + total_fp)
    micro_recall = _safe_div(total_tp, total_tp + total_fn)
    micro_f1 = _safe_div(
        2 * micro_precision * micro_recall,
        micro_precision + micro_recall,
    )
    return {
        "status": "COMPUTED_ON_VALID_PREDICTIONS",
        "case_count": len(ids),
        "macro_f1": macro_f1,
        "micro_f1": micro_f1,
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "per_label": per_label,
        "exact_capability_set_match": _safe_div(exact_correct, len(ids)),
        "exact_capability_set_correct_count": exact_correct,
        "example_based_f1": (
            round(sum(example_f1_values) / len(example_f1_values), 12)
            if example_f1_values
            else 0.0
        ),
        "jaccard": (
            round(sum(jaccard_values) / len(jaccard_values), 12)
            if jaccard_values
            else 0.0
        ),
        "hamming_loss": _safe_div(hamming_errors, len(ids) * 3),
        "under_routing": {
            "case_count": under_case_count,
            "case_rate": _safe_div(under_case_count, len(ids)),
            "label_decision_count": under_label_count,
            "label_decision_rate": _safe_div(under_label_count, len(ids) * 3),
        },
        "over_routing": {
            "case_count": over_case_count,
            "case_rate": _safe_div(over_case_count, len(ids)),
            "label_decision_count": over_label_count,
            "label_decision_rate": _safe_div(over_label_count, len(ids) * 3),
        },
    }


def _stratified_metrics(
    groups: Mapping[str, Sequence[str]],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group_name in sorted(groups):
        case_ids = list(groups[group_name])
        valid_ids = [case_id for case_id in case_ids if case_id in predictions]
        result[group_name] = {
            "total_cases": len(case_ids),
            "valid_predictions": len(valid_ids),
            "coverage": _safe_div(len(valid_ids), len(case_ids)),
            "complete_case_metrics": _core_metrics(
                valid_ids,
                gold_by_id,
                predictions,
            ),
        }
    return result


def _family_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    families: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        families[row["scenario_family_id"]].append(case_id)
    if any(len(case_ids) != 2 for case_ids in families.values()):
        raise RuntimeError("Every B4 ANSWER family must contain exactly two utterances")
    fully_covered = both_exact = predicted_within_family_consistent = 0
    for case_ids in families.values():
        if not all(case_id in predictions for case_id in case_ids):
            continue
        fully_covered += 1
        signatures = {
            _prediction_signature(predictions[case_id]) for case_id in case_ids
        }
        predicted_within_family_consistent += int(len(signatures) == 1)
        both_exact += int(
            all(
                predictions[case_id] == _gold_labels(gold_by_id[case_id])
                for case_id in case_ids
            )
        )
    total = len(families)
    return {
        "total_answer_families": total,
        "fully_covered_families": fully_covered,
        "fully_covered_family_rate": _safe_div(fully_covered, total),
        "both_utterances_exact_correct_count": both_exact,
        "both_utterances_exact_correct_complete_case_rate": (
            _safe_div(both_exact, fully_covered) if fully_covered else None
        ),
        "both_utterances_exact_correct_coverage_adjusted_rate": _safe_div(
            both_exact, total
        ),
        "predicted_within_family_consistent_count": predicted_within_family_consistent,
        "predicted_within_family_consistent_complete_case_rate": (
            _safe_div(predicted_within_family_consistent, fully_covered)
            if fully_covered
            else None
        ),
    }


def _contrast_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    atomic_rows = _read_csv(DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv")
    groups: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for row in atomic_rows:
        if row["annotation_case_id"] not in gold_by_id:
            continue
        if row["dev_contrast_axis"] not in {"RAG", "MEMORY", "PLANNING"}:
            continue
        groups[(row["dev_contrast_group_id"], row["dev_contrast_axis"])].append(row)

    fully_covered = within_family_consistent = gold_pattern_matched = 0
    group_details: list[dict[str, Any]] = []
    for (group_id, axis), rows in sorted(groups.items()):
        case_ids = [row["annotation_case_id"] for row in rows]
        families: dict[str, list[str]] = collections.defaultdict(list)
        for row in rows:
            families[row["scenario_family_id"]].append(row["annotation_case_id"])
        covered = all(case_id in predictions for case_id in case_ids)
        family_consistent = False
        pattern_matched = False
        if covered:
            fully_covered += 1
            predicted_family_signatures: dict[str, str] = {}
            family_consistent = True
            for family_id, family_case_ids in families.items():
                signatures = {
                    _prediction_signature(predictions[case_id])
                    for case_id in family_case_ids
                }
                if len(signatures) != 1:
                    family_consistent = False
                else:
                    predicted_family_signatures[family_id] = next(iter(signatures))
            within_family_consistent += int(family_consistent)
            if family_consistent:
                expected_family_signatures = {
                    family_id: "".join(
                        "1" if value else "0"
                        for value in _gold_labels(gold_by_id[family_case_ids[0]]).values()
                    )
                    for family_id, family_case_ids in families.items()
                }
                pattern_matched = predicted_family_signatures == expected_family_signatures
                gold_pattern_matched += int(pattern_matched)
        group_details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "utterance_count": len(case_ids),
                "family_count": len(families),
                "fully_covered": covered,
                "predicted_within_family_consistent": family_consistent,
                "gold_family_pattern_matched": pattern_matched,
            }
        )
    total = len(groups)
    return {
        "definition": (
            "Capability-axis DEV contrast components only; CLARIFICATION components are "
            "not evaluable by conditional B4. A pattern match requires both utterances "
            "within each family to agree and every predicted family signature to match "
            "the frozen Gold family signature."
        ),
        "total_evaluable_contrast_groups": total,
        "fully_covered_contrast_groups": fully_covered,
        "fully_covered_rate": _safe_div(fully_covered, total),
        "within_family_consistent_count": within_family_consistent,
        "within_family_consistent_complete_case_rate": (
            _safe_div(within_family_consistent, fully_covered)
            if fully_covered
            else None
        ),
        "gold_family_pattern_matched_count": gold_pattern_matched,
        "gold_family_pattern_matched_complete_case_rate": (
            _safe_div(gold_pattern_matched, fully_covered)
            if fully_covered
            else None
        ),
        "gold_family_pattern_matched_coverage_adjusted_rate": _safe_div(
            gold_pattern_matched, total
        ),
        "groups": group_details,
    }


def _verify_call_ledger(
    attempts: Sequence[Mapping[str, Any]],
    journal: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_numbers = [record["physical_attempt_number"] for record in attempts]
    if physical_numbers != list(range(1, len(attempts) + 1)):
        raise RuntimeError("Attempt records are not in deterministic physical order")
    events_by_attempt: dict[str, list[str]] = collections.defaultdict(list)
    for event in journal:
        events_by_attempt[event["physical_attempt_id"]].append(event["event"])
    expected_ids = [record["physical_attempt_id"] for record in attempts]
    if set(events_by_attempt) != set(expected_ids):
        raise RuntimeError("Call journal physical-attempt IDs differ from attempt records")
    for attempt_id in expected_ids:
        if events_by_attempt[attempt_id] != ["ATTEMPT_RESERVED", "ATTEMPT_COMPLETED"]:
            raise RuntimeError(f"Incomplete call journal lifecycle for {attempt_id}")
    if len(attempts) > PHYSICAL_ATTEMPT_CEILING:
        raise RuntimeError("Actual attempt count exceeds physical ceiling")
    return {
        "status": "PASS",
        "physical_attempt_records": len(attempts),
        "journal_events": len(journal),
        "reserved_events": sum(event["event"] == "ATTEMPT_RESERVED" for event in journal),
        "completed_events": sum(event["event"] == "ATTEMPT_COMPLETED" for event in journal),
        "uncompleted_reservations": 0,
        "physical_attempt_ceiling": PHYSICAL_ATTEMPT_CEILING,
    }


def _usage_report(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    input_tokens = sum(
        int(record["input_tokens"])
        for record in attempts
        if record.get("input_tokens") is not None
    )
    output_tokens = sum(
        int(record["output_tokens"])
        for record in attempts
        if record.get("output_tokens") is not None
    )
    total_tokens = sum(
        int(record["total_tokens"])
        for record in attempts
        if record.get("total_tokens") is not None
    )
    arithmetic_discrepancies = [
        record["physical_attempt_id"]
        for record in attempts
        if record.get("input_tokens") is not None
        and record.get("output_tokens") is not None
        and record.get("total_tokens") is not None
        and int(record["input_tokens"]) + int(record["output_tokens"])
        != int(record["total_tokens"])
    ]
    input_cost = Decimal(input_tokens) * INPUT_PRICE_PER_MILLION / Decimal(1_000_000)
    output_cost = (
        Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION / Decimal(1_000_000)
    )
    total_cost = input_cost + output_cost
    return {
        "schema_version": "rq2-v2-stage4-i-x-b4-usage-and-cost-v1",
        "pricing_reference_date": PRICING_REFERENCE_DATE,
        "pricing_reference": {
            "input_usd_per_1m_tokens": str(INPUT_PRICE_PER_MILLION),
            "output_usd_per_1m_tokens": str(OUTPUT_PRICE_PER_MILLION),
        },
        "actual_provider_usage": {
            "physical_attempts": len(attempts),
            "attempts_with_usage": sum(
                record.get("total_tokens") is not None for record in attempts
            ),
            "attempts_without_usage": sum(
                record.get("total_tokens") is None for record in attempts
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "usage_arithmetic_discrepancy_attempt_ids": arithmetic_discrepancies,
        },
        "approximate_cost_usd": {
            "input": format(input_cost, ".8f"),
            "output": format(output_cost, ".8f"),
            "total": format(total_cost, ".8f"),
        },
        "cost_label": (
            "Approximate calculation from returned provider token usage and the "
            "user-stated reference rates; not a billing statement."
        ),
    }


def _build_metrics(
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Mapping[str, str]]]:
    gold_rows = [
        row
        for row in _read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        if row["final_dialogue_action"] == "ANSWER"
    ]
    gold_by_id = {row["annotation_case_id"]: row for row in gold_rows}
    if len(gold_by_id) != LOGICAL_CALL_CEILING:
        raise RuntimeError("Authorized DEV Gold does not contain 64 ANSWER cases")
    predictions = {
        record["annotation_case_id"]: record["prediction"]
        for record in terminals
        if record["terminal_status"] == "VALID_PREDICTION"
    }
    valid_ids = [case_id for case_id in gold_by_id if case_id in predictions]
    complete_case = _core_metrics(valid_ids, gold_by_id, predictions)
    exact_overall = complete_case["exact_capability_set_correct_count"]
    page_groups: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        page_groups[row["current_page"]].append(case_id)
    fold_groups: dict[str, list[str]] = collections.defaultdict(list)
    for record in load_jsonl(V2_MANIFEST_PATH):
        fold_groups[record["outer_fold_id"]].append(record["annotation_case_id"])

    terminal_status_counts = collections.Counter(
        record["terminal_status"] for record in terminals
    )
    provider_error_statuses = {
        "PROVIDER_ERROR",
        "PROVIDER_REFUSAL",
        "RETURNED_MODEL_MISMATCH",
    }
    metrics = {
        "schema_version": "rq2-v2-stage4-i-x-b4-dev-metrics-v1",
        "evaluation_scope": "DEV_ONLY_CONDITIONAL_B4_ANSWER_CASES",
        "generalization_claim": "NONE",
        "coverage": {
            "total_answer_cases": LOGICAL_CALL_CEILING,
            "terminal_results": len(terminals),
            "valid_predictions": len(predictions),
            "valid_prediction_coverage": _safe_div(
                len(predictions), LOGICAL_CALL_CEILING
            ),
            "invalid_structured_output_count": terminal_status_counts[
                "INVALID_STRUCTURED_OUTPUT"
            ],
            "provider_error_count": sum(
                terminal_status_counts[status] for status in provider_error_statuses
            ),
            "retry_count": sum(max(0, int(record["attempts_used"]) - 1) for record in terminals),
            "physical_attempt_count": len(attempts),
            "terminal_status_counts": dict(sorted(terminal_status_counts.items())),
        },
        "complete_case_metrics": complete_case,
        "coverage_adjusted_status": {
            "status": (
                "COMPLETE_64_OF_64"
                if len(predictions) == LOGICAL_CALL_CEILING
                else "INCOMPLETE_DO_NOT_TREAT_AS_FULL_DEV_ESTIMATE"
            ),
            "valid_predictions": len(predictions),
            "missing_or_invalid_predictions": LOGICAL_CALL_CEILING - len(predictions),
            "exact_correct_count_over_all_64": exact_overall,
            "exact_capability_set_match_over_all_64": _safe_div(
                exact_overall, LOGICAL_CALL_CEILING
            ),
            "missing_outputs_counted_as_correct": False,
            "f1_imputation_for_missing_outputs": "NONE",
        },
        "family_metrics": _family_metrics(gold_by_id, predictions),
        "contrast_consistency": _contrast_metrics(gold_by_id, predictions),
        "page_stratified_metrics": _stratified_metrics(
            page_groups, gold_by_id, predictions
        ),
        "fold_stratified_metrics": _stratified_metrics(
            fold_groups, gold_by_id, predictions
        ),
    }
    return metrics, gold_by_id


def _write_predictions_and_errors(
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> None:
    prediction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in attempts:
        attempts_by_logical[record["logical_call_id"]].append(record)
    terminal_by_logical = {
        terminal["logical_call_id"]: terminal for terminal in terminals
    }
    for manifest_record in load_jsonl(V2_MANIFEST_PATH):
        terminal = terminal_by_logical.get(manifest_record["logical_call_id"])
        if terminal is None:
            prediction_rows.append(
                {
                    "logical_call_id": manifest_record["logical_call_id"],
                    "annotation_case_id": manifest_record["annotation_case_id"],
                    "fold_id": manifest_record["outer_fold_id"],
                    "rag_required": "",
                    "memory_required": "",
                    "planning_required": "",
                    "terminal_status": "NOT_EXECUTED_DUE_TO_RUN_STOP",
                    "attempts_used": 0,
                    "response_id": "",
                    "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
                    "returned_model": "",
                }
            )
            continue
        prediction = terminal.get("prediction") or {}
        prediction_rows.append(
            {
                "logical_call_id": terminal["logical_call_id"],
                "annotation_case_id": terminal["annotation_case_id"],
                "fold_id": terminal["fold_id"],
                "rag_required": _bool_csv(prediction.get("rag_required")),
                "memory_required": _bool_csv(prediction.get("memory_required")),
                "planning_required": _bool_csv(prediction.get("planning_required")),
                "terminal_status": terminal["terminal_status"],
                "attempts_used": terminal["attempts_used"],
                "response_id": terminal["response_id"] or "",
                "requested_model": terminal["requested_model"],
                "returned_model": terminal["returned_model"] or "",
            }
        )
        if terminal["terminal_status"] != "VALID_PREDICTION":
            final_attempt = attempts_by_logical[terminal["logical_call_id"]][-1]
            provider_error = terminal.get("provider_error") or {}
            error_rows.append(
                {
                    "logical_call_id": terminal["logical_call_id"],
                    "annotation_case_id": terminal["annotation_case_id"],
                    "fold_id": terminal["fold_id"],
                    "terminal_status": terminal["terminal_status"],
                    "attempts_used": terminal["attempts_used"],
                    "schema_error": final_attempt["schema_validation"]["error"] or "",
                    "provider_error_type": provider_error.get("error_type") or "",
                    "provider_error_category": provider_error.get("category") or "",
                    "provider_status_code": provider_error.get("status_code") or "",
                    "provider_error_code": provider_error.get("code") or "",
                    "response_id": terminal["response_id"] or "",
                }
            )
    _atomic_write_csv(
        PREDICTIONS_PATH,
        (
            "logical_call_id",
            "annotation_case_id",
            "fold_id",
            "rag_required",
            "memory_required",
            "planning_required",
            "terminal_status",
            "attempts_used",
            "response_id",
            "requested_model",
            "returned_model",
        ),
        prediction_rows,
    )
    _atomic_write_csv(
        ERROR_REGISTRY_PATH,
        (
            "logical_call_id",
            "annotation_case_id",
            "fold_id",
            "terminal_status",
            "attempts_used",
            "schema_error",
            "provider_error_type",
            "provider_error_category",
            "provider_status_code",
            "provider_error_code",
            "response_id",
        ),
        error_rows,
    )


def _format_metric(value: Any) -> str:
    return "NOT_COMPUTABLE" if value is None else f"{float(value):.6f}"


def _results_report(
    metrics: Mapping[str, Any],
    usage: Mapping[str, Any],
    requested_models: Sequence[str],
    returned_models: Sequence[str],
    ledger: Mapping[str, Any],
    complete: bool,
    stop_reason: str | None,
) -> str:
    coverage = metrics["coverage"]
    core = metrics["complete_case_metrics"]
    family = metrics["family_metrics"]
    contrast = metrics["contrast_consistency"]
    per_label_lines = "\n".join(
        f"| {field} | {_format_metric(values['precision'])} | "
        f"{_format_metric(values['recall'])} | {_format_metric(values['f1'])} | "
        f"{values['tp']} | {values['fp']} | "
        f"{values['fn']} | {values['tn']} |"
        for field, values in core["per_label"].items()
    )
    status = "FROZEN_AFTER_DEV_EXECUTION" if complete else "EXECUTION_INCOMPLETE_NOT_FROZEN"
    return f"""# B4 DEV Execution Results

Status: `{status}`

These are conditional B4 DEV estimates, not TEST results or final generalization evidence.

## Execution

- Requested model: `{', '.join(requested_models)}`
- Returned model: `{', '.join(returned_models) or 'NONE'}`
- Stop reason: `{stop_reason or 'NONE'}`
- Logical terminal results: `{coverage['terminal_results']}`
- Physical attempts: `{coverage['physical_attempt_count']}`
- Manual invalid-output retries: `{coverage['retry_count']}`
- Call-ledger verification: `{ledger['status']}`
- Valid predictions: `{coverage['valid_predictions']}/64` (`{coverage['valid_prediction_coverage']:.6f}`)
- Invalid structured outputs: `{coverage['invalid_structured_output_count']}`
- Provider errors/refusals/model mismatches: `{coverage['provider_error_count']}`

## Complete-case DEV metrics

- Metric status: `{core['status']}`
- Macro-F1: `{_format_metric(core['macro_f1'])}`
- Micro-F1: `{_format_metric(core['micro_f1'])}`
- Exact Capability Set Match: `{_format_metric(core['exact_capability_set_match'])}`
- Example-based F1: `{_format_metric(core['example_based_f1'])}`
- Jaccard: `{_format_metric(core['jaccard'])}`
- Hamming Loss: `{_format_metric(core['hamming_loss'])}`
- Under-routing case rate: `{_format_metric(core['under_routing']['case_rate'])}` ({core['under_routing']['case_count']} cases)
- Over-routing case rate: `{_format_metric(core['over_routing']['case_rate'])}` ({core['over_routing']['case_count']} cases)

| Label | Precision | Recall | F1 | TP | FP | FN | TN |
|---|---:|---:|---:|---:|---:|---:|---:|
{per_label_lines}

## Family and contrast metrics

- Families with both utterances exact: `{family['both_utterances_exact_correct_count']}/{family['fully_covered_families']}` complete families (`{_format_metric(family['both_utterances_exact_correct_complete_case_rate'])}`).
- Capability contrast Gold-pattern matches: `{contrast['gold_family_pattern_matched_count']}/{contrast['fully_covered_contrast_groups']}` complete contrast groups (`{_format_metric(contrast['gold_family_pattern_matched_complete_case_rate'])}`).

## Actual usage and approximate cost

- Input tokens: `{usage['actual_provider_usage']['input_tokens']}`
- Output tokens: `{usage['actual_provider_usage']['output_tokens']}`
- Total tokens: `{usage['actual_provider_usage']['total_tokens']}`
- Approximate cost: `${usage['approximate_cost_usd']['total']}` USD
- Pricing reference: `{PRICING_REFERENCE_DATE}`; input `${INPUT_PRICE_PER_MILLION}`/1M and output `${OUTPUT_PRICE_PER_MILLION}`/1M tokens.

No TEST, P1, or RQ3 provider call was made.
"""


def _status_report(
    complete: bool,
    stop_reason: str | None,
    metrics: Mapping[str, Any],
    requested_models: Sequence[str],
    returned_models: Sequence[str],
) -> str:
    coverage = metrics["coverage"]
    status = (
        "FROZEN_AFTER_DEV_EXECUTION"
        if complete
        else "EXECUTION_INCOMPLETE_NOT_FROZEN"
    )
    return f"""# B4 DEV Execution Status

B4_MODEL_STATUS = `{status}`

- Stop reason: `{stop_reason or 'NONE'}`
- Requested model identities: `{', '.join(requested_models) or 'NONE'}`
- Returned model identities: `{', '.join(returned_models) or 'NONE'}`
- Logical terminal results: `{coverage['terminal_results']}/64`
- Physical attempts: `{coverage['physical_attempt_count']}/128`
- Valid predictions: `{coverage['valid_predictions']}/64`
- Invalid structured outputs: `{coverage['invalid_structured_output_count']}`
- Provider errors/refusals/model mismatches: `{coverage['provider_error_count']}`
- Prompt hash: `{EXPECTED_PROMPT_SHA256}`
- Response-schema hash: `{EXPECTED_SCHEMA_SHA256}`
- TEST calls: `0`
- P1 calls: `0`
- RQ3 calls: `0`

This status is a DEV-only research result and does not authorize TEST execution.
"""


def finalize(
    stop_reason: str | None,
    manifest_diff_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    attempts = load_jsonl(ATTEMPT_RECORDS_PATH)
    terminals = load_jsonl(TERMINAL_RESULTS_PATH)
    journal = load_jsonl(CALL_JOURNAL_PATH)
    if not attempts or not terminals:
        raise RuntimeError("No provider attempt/terminal outputs are available to finalize")
    expected_terminal_ids = [f"R2V2-B4-DEV-{index:04d}" for index in range(1, len(terminals) + 1)]
    if [record["logical_call_id"] for record in terminals] != expected_terminal_ids:
        raise RuntimeError("Terminal results are not in deterministic logical order")
    if len({record["logical_call_id"] for record in terminals}) != len(terminals):
        raise RuntimeError("Duplicate terminal logical_call_id")
    ledger = _verify_call_ledger(attempts, journal)
    _write_predictions_and_errors(terminals, attempts)
    usage = _usage_report(attempts)
    atomic_write_json(USAGE_PATH, usage)
    metrics, _gold_by_id = _build_metrics(terminals, attempts)
    atomic_write_json(METRICS_PATH, metrics)

    requested_models = sorted(
        {str(record["requested_model"]) for record in attempts if record.get("requested_model")}
    )
    returned_models = sorted(
        {str(record["returned_model"]) for record in attempts if record.get("returned_model")}
    )
    complete = len(terminals) == LOGICAL_CALL_CEILING and ledger["status"] == "PASS"
    fold_hashes = json.loads(
        (TRACK_DIR / "b4_fold_prompt_hashes_v1.json").read_text(encoding="utf-8")
    )
    diff_report = (
        dict(manifest_diff_report)
        if manifest_diff_report is not None
        else json.loads(MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
    )
    final_freeze = {
        "schema_version": "rq2-v2-stage4-i-x-b4-final-freeze-v1",
        "B4_MODEL_STATUS": (
            "FROZEN_AFTER_DEV_EXECUTION"
            if complete
            else "EXECUTION_INCOMPLETE_NOT_FROZEN"
        ),
        "execution_scope": "DEV_ONLY_CONDITIONAL_B4_ANSWER_CASES",
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "response_schema_sha256": EXPECTED_SCHEMA_SHA256,
        "full_dev_examples": {
            "example_ids_in_order": fold_hashes["full_dev"]["example_ids"],
            "signatures_in_order": fold_hashes["full_dev"]["signatures"],
            "example_set_sha256": fold_hashes["full_dev"]["example_set_sha256"],
            "prompt_package_sha256": fold_hashes["full_dev"]["prompt_package_sha256"],
        },
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "sdk_transport_retries": 0,
        "manual_retry_policy": {
            "maximum_retries_per_logical_case": 1,
            "only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
            "correction_message_added": False,
            "prompt_changed": False,
        },
        "execution_evidence": {
            "logical_terminal_results": len(terminals),
            "physical_attempts": len(attempts),
            "requested_models": requested_models,
            "returned_models": returned_models,
            "v1_manifest_sha256": diff_report["v1_manifest_sha256"],
            "v2_manifest_sha256": diff_report["v2_manifest_sha256"],
            "attempt_records_sha256": sha256_file(ATTEMPT_RECORDS_PATH),
            "terminal_results_sha256": sha256_file(TERMINAL_RESULTS_PATH),
            "call_journal_sha256": sha256_file(CALL_JOURNAL_PATH),
        },
        "future_boundary": {
            "intended_future_use": "ONE_TIME_TEST_B4_EXECUTION_AFTER_SEPARATE_DIRECT_AUTHORIZATION",
            "test_calls_made": 0,
            "p1_calls_made": 0,
            "rq3_calls_made": 0,
        },
    }
    atomic_write_json(FINAL_FREEZE_PATH, final_freeze)
    atomic_write_text(
        RESULTS_REPORT_PATH,
        _results_report(
            metrics,
            usage,
            requested_models,
            returned_models,
            ledger,
            complete,
            stop_reason,
        ),
    )
    atomic_write_text(
        STATUS_PATH,
        _status_report(complete, stop_reason, metrics, requested_models, returned_models),
    )
    return {
        "B4_MODEL_STATUS": final_freeze["B4_MODEL_STATUS"],
        "logical_calls": len(terminals),
        "physical_attempts": len(attempts),
        "retries": metrics["coverage"]["retry_count"],
        "valid_predictions": metrics["coverage"]["valid_predictions"],
        "invalid_structured_outputs": metrics["coverage"][
            "invalid_structured_output_count"
        ],
        "provider_errors": metrics["coverage"]["provider_error_count"],
        "requested_models": requested_models,
        "returned_models": returned_models,
        "approximate_cost_usd": usage["approximate_cost_usd"]["total"],
        "stop_reason": stop_reason,
    }
