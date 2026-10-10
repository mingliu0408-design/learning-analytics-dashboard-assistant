"""Finalize the frozen Stage 4L Memory Specialist DEV execution."""

from __future__ import annotations

import collections
import csv
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

from .memory_specialist_common import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    CLIENT_MAX_RETRIES,
    DEV_PROTOCOL_DIR,
    ERROR_REGISTRY_PATH,
    EXPECTED_EVALUATION_PROTOCOL_SHA256,
    EXPECTED_P3_CONTRACT_SHA256,
    EXPECTED_PROMPT_SHA256,
    EXPECTED_SCHEMA_SHA256,
    FOLD_HASHES_PATH,
    FROZEN_CONFIGURATION_PATH,
    LOGICAL_CALL_CEILING,
    MANIFEST_DIFF_PATH,
    MAX_OUTPUT_TOKENS,
    METRICS_PATH,
    MIN_INITIAL_REQUEST_DELAY_SECONDS,
    OUTPUT_SHA256_MANIFEST_PATH,
    PHYSICAL_ATTEMPT_CEILING,
    PREDICTIONS_PATH,
    RESULTS_REPORT_PATH,
    SOURCE_VERIFICATION_PATH,
    STATUS_PATH,
    TARGET_FIELD,
    TERMINAL_RESULTS_PATH,
    TEST_REPORT_PATH,
    TRACK_DIR,
    USAGE_PATH,
    VERIFICATION_REPORT_PATH,
    V2_MANIFEST_PATH,
    atomic_write_json,
    atomic_write_text,
    canonical_sha256,
    credential_or_partition_scan,
    load_json,
    load_jsonl,
    sha256_file,
    verify_frozen_sources,
    verify_git_boundary,
    verify_manifest_v2,
    write_output_sha256_manifest,
    write_post_execution_source_verification,
)


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
    raise RuntimeError(f"Expected YES or NO, observed {value!r}")


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return round(float(numerator) / float(denominator), 12)


def _binary_metrics(
    case_ids: Sequence[str],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    valid_ids = [case_id for case_id in case_ids if case_id in predictions]
    if not valid_ids:
        return {
            "status": "NOT_COMPUTABLE_NO_VALID_PREDICTIONS",
            "case_count": 0,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "specificity": None,
            "confusion_matrix": {"tp": 0, "fp": 0, "tn": 0, "fn": 0},
            "positive_prediction_count": 0,
            "positive_prediction_rate": None,
            "metric_denominators": {
                "accuracy": 0,
                "precision": 0,
                "recall": 0,
                "specificity": 0,
            },
        }
    tp = fp = tn = fn = 0
    for case_id in valid_ids:
        gold = _yes_no(gold_by_id[case_id]["final_memory_required"])
        predicted = predictions[case_id]
        if gold and predicted:
            tp += 1
        elif not gold and predicted:
            fp += 1
        elif not gold and not predicted:
            tn += 1
        else:
            fn += 1
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "status": "COMPUTED_ON_VALID_PREDICTIONS",
        "case_count": len(valid_ids),
        "accuracy": _safe_div(tp + tn, len(valid_ids)),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": _safe_div(tn, tn + fp),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "positive_prediction_count": tp + fp,
        "positive_prediction_rate": _safe_div(tp + fp, len(valid_ids)),
        "metric_denominators": {
            "accuracy": len(valid_ids),
            "precision": tp + fp,
            "recall": tp + fn,
            "specificity": tn + fp,
        },
    }


def _stratified_metrics(
    groups: Mapping[str, Sequence[str]],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group_name in sorted(groups):
        case_ids = list(groups[group_name])
        valid_count = sum(case_id in predictions for case_id in case_ids)
        result[group_name] = {
            "total_cases": len(case_ids),
            "valid_predictions": valid_count,
            "coverage": _safe_div(valid_count, len(case_ids)),
            "complete_case_metrics": _binary_metrics(
                case_ids, gold_by_id, predictions
            ),
        }
    return result


def _family_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    families: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        families[row["scenario_family_id"]].append(case_id)
    if any(len(case_ids) != 2 for case_ids in families.values()):
        raise RuntimeError("Every DEV ANSWER family must contain exactly two utterances")
    fully_covered = both_correct = prediction_consistent = 0
    for case_ids in families.values():
        if not all(case_id in predictions for case_id in case_ids):
            continue
        fully_covered += 1
        values = {predictions[case_id] for case_id in case_ids}
        prediction_consistent += int(len(values) == 1)
        both_correct += int(
            all(
                predictions[case_id]
                == _yes_no(gold_by_id[case_id]["final_memory_required"])
                for case_id in case_ids
            )
        )
    total = len(families)
    return {
        "total_answer_families": total,
        "fully_covered_families": fully_covered,
        "fully_covered_family_rate": _safe_div(fully_covered, total),
        "family_both_utterances_correct_count": both_correct,
        "family_both_utterances_correct_complete_case_rate": (
            _safe_div(both_correct, fully_covered) if fully_covered else None
        ),
        "family_both_utterances_correct_coverage_adjusted_rate": _safe_div(
            both_correct, total
        ),
        "family_prediction_consistent_count": prediction_consistent,
        "family_prediction_consistency_complete_case_rate": (
            _safe_div(prediction_consistent, fully_covered)
            if fully_covered
            else None
        ),
        "family_prediction_consistency_coverage_adjusted_rate": _safe_div(
            prediction_consistent, total
        ),
    }


def _memory_contrast_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    atomic_rows = _read_csv(DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv")
    groups: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in atomic_rows:
        if (
            row["annotation_case_id"] in gold_by_id
            and row["dev_contrast_axis"] == "MEMORY"
        ):
            groups[row["dev_contrast_group_id"]].append(row)
    fully_covered = contrast_consistent = gold_pattern_match = 0
    details: list[dict[str, Any]] = []
    for group_id, rows in sorted(groups.items()):
        families: dict[str, list[str]] = collections.defaultdict(list)
        for row in rows:
            families[row["scenario_family_id"]].append(row["annotation_case_id"])
        if len(families) != 2 or any(len(ids) != 2 for ids in families.values()):
            raise RuntimeError(f"Memory contrast shape differs: {group_id}")
        case_ids = [row["annotation_case_id"] for row in rows]
        covered = all(case_id in predictions for case_id in case_ids)
        family_consistent = False
        direction_matches = False
        exact_gold_pattern = False
        if covered:
            fully_covered += 1
            family_consistent = all(
                len({predictions[case_id] for case_id in ids}) == 1
                for ids in families.values()
            )
            if family_consistent:
                ordered_families = sorted(families)
                predicted_bits = [
                    int(predictions[families[family_id][0]])
                    for family_id in ordered_families
                ]
                gold_bits: list[int] = []
                for family_id in ordered_families:
                    family_gold = {
                        _yes_no(gold_by_id[case_id]["final_memory_required"])
                        for case_id in families[family_id]
                    }
                    if len(family_gold) != 1:
                        raise RuntimeError(
                            f"Gold is inconsistent within Memory family: {family_id}"
                        )
                    gold_bits.append(int(next(iter(family_gold))))
                direction_matches = (
                    predicted_bits[1] - predicted_bits[0]
                    == gold_bits[1] - gold_bits[0]
                )
                contrast_consistent += int(direction_matches)
            exact_gold_pattern = all(
                predictions[case_id]
                == _yes_no(gold_by_id[case_id]["final_memory_required"])
                for case_id in case_ids
            )
            gold_pattern_match += int(exact_gold_pattern)
        details.append(
            {
                "contrast_group_id": group_id,
                "utterance_count": len(case_ids),
                "family_count": len(families),
                "fully_covered": covered,
                "within_family_prediction_consistent": family_consistent,
                "directed_memory_bit_change_matches_gold": direction_matches,
                "memory_gold_pattern_matched": exact_gold_pattern,
            }
        )
    total = len(groups)
    return {
        "definition": (
            "For each frozen MEMORY-axis DEV contrast group, both utterances must "
            "agree within each family and the directed Memory-bit change between "
            "the two sorted family identities must match frozen Gold."
        ),
        "total_memory_contrast_groups": total,
        "fully_covered_memory_contrast_groups": fully_covered,
        "fully_covered_rate": _safe_div(fully_covered, total),
        "memory_contrast_consistent_count": contrast_consistent,
        "memory_contrast_consistency_complete_case_rate": (
            _safe_div(contrast_consistent, fully_covered)
            if fully_covered
            else None
        ),
        "memory_contrast_consistency_coverage_adjusted_rate": _safe_div(
            contrast_consistent, total
        ),
        "memory_gold_pattern_contrast_match_count": gold_pattern_match,
        "memory_gold_pattern_contrast_match_complete_case_rate": (
            _safe_div(gold_pattern_match, fully_covered)
            if fully_covered
            else None
        ),
        "memory_gold_pattern_contrast_match_coverage_adjusted_rate": _safe_div(
            gold_pattern_match, total
        ),
        "groups": details,
    }


def _verify_call_ledger(
    attempts: Sequence[Mapping[str, Any]],
    journal: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_numbers = [int(record["physical_attempt_number"]) for record in attempts]
    if physical_numbers != list(range(1, len(attempts) + 1)):
        raise RuntimeError("Physical attempt records are not in deterministic order")
    if len(attempts) > PHYSICAL_ATTEMPT_CEILING:
        raise RuntimeError("Physical-attempt ceiling exceeded")
    expected_terminal_ids = [
        f"R2V2-MEMORY-SPECIALIST-DEV-{index:04d}"
        for index in range(1, len(terminals) + 1)
    ]
    if [record["logical_call_id"] for record in terminals] != expected_terminal_ids:
        raise RuntimeError("Terminal results are not in deterministic logical order")
    if len({record["logical_call_id"] for record in terminals}) != len(terminals):
        raise RuntimeError("Duplicate terminal logical call ID")

    events_by_attempt: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for event in journal:
        events_by_attempt[str(event["physical_attempt_id"])].append(event)
    attempt_ids = [str(record["physical_attempt_id"]) for record in attempts]
    if set(events_by_attempt) != set(attempt_ids):
        raise RuntimeError("Call journal IDs differ from attempt records")
    attempts_by_id = {str(record["physical_attempt_id"]): record for record in attempts}
    for attempt_id in attempt_ids:
        events = events_by_attempt[attempt_id]
        if [event["event"] for event in events] != [
            "ATTEMPT_RESERVED",
            "ATTEMPT_COMPLETED",
        ]:
            raise RuntimeError(f"Incomplete call journal lifecycle: {attempt_id}")
        attempt = attempts_by_id[attempt_id]
        if any(event["request_sha256"] != attempt["request_sha256"] for event in events):
            raise RuntimeError(f"Call journal request hash differs: {attempt_id}")
        if events[1]["attempt_record_sha256"] != canonical_sha256(attempt):
            raise RuntimeError(f"Attempt-record journal hash differs: {attempt_id}")

    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for attempt in attempts:
        attempts_by_logical[str(attempt["logical_call_id"])].append(attempt)
    retry_count = 0
    for terminal in terminals:
        logical_attempts = attempts_by_logical[str(terminal["logical_call_id"])]
        if len(logical_attempts) != int(terminal["attempts_used"]):
            raise RuntimeError("Terminal attempts_used differs from ledger")
        if len(logical_attempts) > 2:
            raise RuntimeError("Per-logical-case retry ceiling exceeded")
        if len(logical_attempts) == 2:
            retry_count += 1
            first_error = logical_attempts[0]["schema_validation"]["error"]
            if first_error not in {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}:
                raise RuntimeError("Retry followed a non-structured-output error")
            if logical_attempts[0]["request_sha256"] != logical_attempts[1][
                "request_sha256"
            ]:
                raise RuntimeError("Retry request hash differs from initial request")
    initial_attempts = [record for record in attempts if record["attempt_number"] == 1]
    if len(initial_attempts) != len(terminals):
        raise RuntimeError("Initial attempt count differs from logical terminal count")
    pacing_intervals = [
        float(record["seconds_since_prior_initial_request_start"])
        for record in initial_attempts
        if record.get("seconds_since_prior_initial_request_start") is not None
    ]
    if any(value < MIN_INITIAL_REQUEST_DELAY_SECONDS for value in pacing_intervals):
        raise RuntimeError("Minimum initial-request pacing interval was not met")
    return {
        "status": "PASS",
        "logical_terminal_results": len(terminals),
        "physical_attempts": len(attempts),
        "physical_attempt_ceiling": PHYSICAL_ATTEMPT_CEILING,
        "retry_count": retry_count,
        "journal_events": len(journal),
        "reserved_events": sum(event["event"] == "ATTEMPT_RESERVED" for event in journal),
        "completed_events": sum(event["event"] == "ATTEMPT_COMPLETED" for event in journal),
        "uncompleted_reservations": 0,
        "initial_request_count": len(initial_attempts),
        "minimum_required_initial_request_delay_seconds": (
            MIN_INITIAL_REQUEST_DELAY_SECONDS
        ),
        "minimum_observed_initial_request_interval_seconds": (
            min(pacing_intervals) if pacing_intervals else None
        ),
        "serial_execution": True,
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
    discrepancies = [
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
        "schema_version": "rq2-v2-stage4-l-memory-specialist-usage-and-cost-v1",
        "pricing_reference_date": PRICING_REFERENCE_DATE,
        "pricing_reference": {
            "input_usd_per_1m_text_tokens": str(INPUT_PRICE_PER_MILLION),
            "output_usd_per_1m_text_tokens": str(OUTPUT_PRICE_PER_MILLION),
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
            "usage_arithmetic_discrepancy_attempt_ids": discrepancies,
        },
        "approximate_cost_usd": {
            "input": format(input_cost, ".8f"),
            "output": format(output_cost, ".8f"),
            "total": format(total_cost, ".8f"),
        },
        "cost_label": (
            "Approximate calculation from provider-returned usage and the stated "
            "reference rates; not a billing statement."
        ),
    }


def _build_metrics(
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
    manifest_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    gold_rows = [
        row
        for row in _read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        if row["final_dialogue_action"] == "ANSWER"
    ]
    gold_by_id = {row["annotation_case_id"]: row for row in gold_rows}
    if len(gold_by_id) != LOGICAL_CALL_CEILING:
        raise RuntimeError("Frozen DEV Gold is not exactly 64 ANSWER cases")
    manifest_ids = [str(record["annotation_case_id"]) for record in manifest_records]
    if set(manifest_ids) != set(gold_by_id):
        raise RuntimeError("Authorized manifest population differs from DEV ANSWER Gold")
    predictions = {
        str(record["annotation_case_id"]): bool(record["prediction"][TARGET_FIELD])
        for record in terminals
        if record["terminal_status"] == "VALID_PREDICTION"
    }
    status_counts = collections.Counter(
        str(record["terminal_status"]) for record in terminals
    )
    provider_terminal_statuses = {
        "PROVIDER_ERROR",
        "PROVIDER_REFUSAL",
        "RETURNED_MODEL_MISMATCH",
    }
    invalid_attempt_count = sum(
        record["schema_validation"]["error"]
        in {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}
        for record in attempts
    )
    provider_error_attempt_count = sum(
        record.get("provider_error") is not None for record in attempts
    )
    page_groups: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        page_groups[row["current_page"]].append(case_id)
    fold_groups: dict[str, list[str]] = collections.defaultdict(list)
    for record in manifest_records:
        fold_groups[str(record["outer_fold"])].append(
            str(record["annotation_case_id"])
        )
    valid_count = len(predictions)
    return {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-dev-metrics-v1",
        "evaluation_scope": "FROZEN_DEV_ANSWER_MEMORY_SPECIALIST_ONLY",
        "generalization_claim": "NONE_DEV_ONLY",
        "joint_b4_comparison_performed": False,
        "composition_scored": False,
        "coverage": {
            "total_authorized_answer_cases": LOGICAL_CALL_CEILING,
            "logical_terminal_results": len(terminals),
            "valid_predictions": valid_count,
            "valid_prediction_coverage": _safe_div(
                valid_count, LOGICAL_CALL_CEILING
            ),
            "missing_or_invalid_predictions": LOGICAL_CALL_CEILING - valid_count,
            "invalid_structured_output_attempt_count": invalid_attempt_count,
            "terminal_invalid_structured_output_count": status_counts[
                "INVALID_STRUCTURED_OUTPUT"
            ],
            "provider_error_attempt_count": provider_error_attempt_count,
            "terminal_provider_error_count": sum(
                status_counts[status] for status in provider_terminal_statuses
            ),
            "retry_count": sum(
                max(0, int(record["attempts_used"]) - 1) for record in terminals
            ),
            "physical_attempt_count": len(attempts),
            "terminal_status_counts": dict(sorted(status_counts.items())),
        },
        "complete_case_metrics": _binary_metrics(
            list(gold_by_id), gold_by_id, predictions
        ),
        "coverage_adjusted_status": {
            "status": (
                "COMPLETE_64_OF_64"
                if valid_count == LOGICAL_CALL_CEILING
                else "INCOMPLETE_DO_NOT_TREAT_AS_FULL_DEV_ESTIMATE"
            ),
            "missing_outputs_imputed": False,
            "complete_case_metrics_reported_separately": True,
        },
        "family_metrics": _family_metrics(gold_by_id, predictions),
        "memory_contrast_metrics": _memory_contrast_metrics(
            gold_by_id, predictions
        ),
        "page_stratified_metrics": _stratified_metrics(
            page_groups, gold_by_id, predictions
        ),
        "fold_stratified_metrics": _stratified_metrics(
            fold_groups, gold_by_id, predictions
        ),
    }


def _write_predictions_and_errors(
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
    manifest_records: Sequence[Mapping[str, Any]],
) -> None:
    terminal_by_logical = {
        str(record["logical_call_id"]): record for record in terminals
    }
    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for attempt in attempts:
        attempts_by_logical[str(attempt["logical_call_id"])].append(attempt)
    prediction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    for manifest_record in manifest_records:
        logical_id = str(manifest_record["logical_call_id"])
        terminal = terminal_by_logical.get(logical_id)
        if terminal is None:
            prediction_rows.append(
                {
                    "logical_call_id": logical_id,
                    "annotation_case_id": manifest_record["annotation_case_id"],
                    "fold_id": manifest_record["outer_fold"],
                    TARGET_FIELD: "",
                    "terminal_status": "NOT_EXECUTED_DUE_TO_RUN_STOP",
                    "attempts_used": 0,
                    "response_id": "",
                    "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
                    "returned_model": "",
                }
            )
            error_rows.append(
                {
                    "logical_call_id": logical_id,
                    "annotation_case_id": manifest_record["annotation_case_id"],
                    "fold_id": manifest_record["outer_fold"],
                    "terminal_status": "NOT_EXECUTED_DUE_TO_RUN_STOP",
                    "attempts_used": 0,
                    "schema_error": "",
                    "provider_exception_type": "",
                    "provider_error_category": "",
                    "provider_http_status": "",
                    "provider_error_code": "",
                    "provider_error_param": "",
                    "provider_request_id": "",
                    "sanitized_error_message": "",
                    "response_id": "",
                }
            )
            continue
        prediction = terminal.get("prediction") or {}
        prediction_rows.append(
            {
                "logical_call_id": logical_id,
                "annotation_case_id": terminal["annotation_case_id"],
                "fold_id": terminal["fold_id"],
                TARGET_FIELD: _bool_csv(prediction.get(TARGET_FIELD)),
                "terminal_status": terminal["terminal_status"],
                "attempts_used": terminal["attempts_used"],
                "response_id": terminal["response_id"] or "",
                "requested_model": terminal["requested_model"],
                "returned_model": terminal["returned_model"] or "",
            }
        )
        if terminal["terminal_status"] != "VALID_PREDICTION":
            final_attempt = attempts_by_logical[logical_id][-1]
            provider_error = terminal.get("provider_error") or {}
            error_rows.append(
                {
                    "logical_call_id": logical_id,
                    "annotation_case_id": terminal["annotation_case_id"],
                    "fold_id": terminal["fold_id"],
                    "terminal_status": terminal["terminal_status"],
                    "attempts_used": terminal["attempts_used"],
                    "schema_error": final_attempt["schema_validation"]["error"] or "",
                    "provider_exception_type": provider_error.get("exception_type") or "",
                    "provider_error_category": provider_error.get("category") or "",
                    "provider_http_status": provider_error.get("http_status") or "",
                    "provider_error_code": provider_error.get("provider_error_code") or "",
                    "provider_error_param": provider_error.get("provider_error_param") or "",
                    "provider_request_id": provider_error.get("provider_request_id") or "",
                    "sanitized_error_message": provider_error.get(
                        "sanitized_error_message"
                    )
                    or "",
                    "response_id": terminal["response_id"] or "",
                }
            )
    _atomic_write_csv(
        PREDICTIONS_PATH,
        (
            "logical_call_id",
            "annotation_case_id",
            "fold_id",
            TARGET_FIELD,
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
            "provider_exception_type",
            "provider_error_category",
            "provider_http_status",
            "provider_error_code",
            "provider_error_param",
            "provider_request_id",
            "sanitized_error_message",
            "response_id",
        ),
        error_rows,
    )


def _metric(value: Any) -> str:
    return "NOT_COMPUTABLE" if value is None else f"{float(value):.6f}"


def _stratified_table(values: Mapping[str, Any]) -> str:
    return "\n".join(
        f"| {name} | {entry['valid_predictions']}/{entry['total_cases']} | "
        f"{_metric(entry['complete_case_metrics']['accuracy'])} | "
        f"{_metric(entry['complete_case_metrics']['precision'])} | "
        f"{_metric(entry['complete_case_metrics']['recall'])} | "
        f"{_metric(entry['complete_case_metrics']['f1'])} | "
        f"{_metric(entry['complete_case_metrics']['specificity'])} |"
        for name, entry in values.items()
    )


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
    confusion = core["confusion_matrix"]
    family = metrics["family_metrics"]
    contrast = metrics["memory_contrast_metrics"]
    actual_usage = usage["actual_provider_usage"]
    status = (
        "FROZEN_AFTER_DEV_EXECUTION"
        if complete
        else "MEMORY_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
    )
    return f"""# Memory Specialist DEV Execution Results

MEMORY_SPECIALIST_STATUS = `{status}`

These are conditional DEV-only estimates for the frozen Memory Specialist. They
are not final generalization evidence, and no joint-B4 or composition comparison
is performed here.

## Execution and coverage

- Requested model: `{', '.join(requested_models) or 'NONE'}`
- Returned model: `{', '.join(returned_models) or 'NONE'}`
- Stop reason: `{stop_reason or 'NONE'}`
- Logical terminal results: `{coverage['logical_terminal_results']}/64`
- Physical attempts: `{coverage['physical_attempt_count']}/128`
- Invalid-output retries: `{coverage['retry_count']}`
- Ledger verification: `{ledger['status']}`
- Valid predictions: `{coverage['valid_predictions']}/64` (`{coverage['valid_prediction_coverage']:.6f}`)
- Invalid structured-output attempts: `{coverage['invalid_structured_output_attempt_count']}`
- Terminal invalid structured outputs: `{coverage['terminal_invalid_structured_output_count']}`
- Provider-error attempts: `{coverage['provider_error_attempt_count']}`
- Terminal provider errors/refusals/model mismatches: `{coverage['terminal_provider_error_count']}`

## Complete-case Memory metrics

- Accuracy: `{_metric(core['accuracy'])}`
- Precision: `{_metric(core['precision'])}`
- Recall: `{_metric(core['recall'])}`
- F1: `{_metric(core['f1'])}`
- Specificity: `{_metric(core['specificity'])}` ({confusion['tn']}/{confusion['tn'] + confusion['fp']})
- Confusion matrix: TP `{confusion['tp']}`, FP `{confusion['fp']}`, TN `{confusion['tn']}`, FN `{confusion['fn']}`
- Positive predictions: `{core['positive_prediction_count']}/{core['case_count']}` (`{_metric(core['positive_prediction_rate'])}`)

Missing or invalid outputs are not imputed. When coverage is incomplete, every
metric above is a complete-case metric and coverage remains explicit.

## Family and Memory-contrast metrics

- Family both utterances correct: `{family['family_both_utterances_correct_count']}/{family['fully_covered_families']}` (`{_metric(family['family_both_utterances_correct_complete_case_rate'])}`)
- Family prediction consistency: `{family['family_prediction_consistent_count']}/{family['fully_covered_families']}` (`{_metric(family['family_prediction_consistency_complete_case_rate'])}`)
- Memory contrast consistency: `{contrast['memory_contrast_consistent_count']}/{contrast['fully_covered_memory_contrast_groups']}` (`{_metric(contrast['memory_contrast_consistency_complete_case_rate'])}`)
- Memory Gold-pattern contrast match: `{contrast['memory_gold_pattern_contrast_match_count']}/{contrast['fully_covered_memory_contrast_groups']}` (`{_metric(contrast['memory_gold_pattern_contrast_match_complete_case_rate'])}`)

## Page-stratified metrics

| Page | Coverage | Accuracy | Precision | Recall | F1 | Specificity |
|---|---:|---:|---:|---:|---:|---:|
{_stratified_table(metrics['page_stratified_metrics'])}

## Fold-stratified metrics

| Fold | Coverage | Accuracy | Precision | Recall | F1 | Specificity |
|---|---:|---:|---:|---:|---:|---:|
{_stratified_table(metrics['fold_stratified_metrics'])}

## Actual provider usage and approximate cost

- Input tokens: `{actual_usage['input_tokens']}`
- Output tokens: `{actual_usage['output_tokens']}`
- Total tokens: `{actual_usage['total_tokens']}`
- Actual physical attempts: `{actual_usage['physical_attempts']}`
- Approximate cost: `${usage['approximate_cost_usd']['total']}` USD
- Pricing reference: `{PRICING_REFERENCE_DATE}`; input `${INPUT_PRICE_PER_MILLION}`/1M and output `${OUTPUT_PRICE_PER_MILLION}`/1M text tokens.

The cost is an approximate calculation from provider-returned usage and the
stated reference rates.

Provider-call boundary: DEV Memory Specialist `64` logical cases; RAG Specialist
`0`; P2 `0`; P3 `0`; P1 `0`; RQ3 `0`; future held-out execution `0`.
"""


def _test_report(track_l_count: int | None, k0_count: int | None) -> dict[str, Any]:
    if track_l_count is None or k0_count is None:
        return {
            "schema_version": "rq2-v2-stage4-l-test-report-v1",
            "status": "PENDING_FINAL_POST_EXECUTION_TEST_RUN",
            "track_l_tests": None,
            "frozen_k0_tests": None,
            "total_tests": None,
            "failures": None,
            "errors": None,
        }
    if track_l_count < 1 or k0_count != 24:
        raise RuntimeError("Final test counts do not match the authorized suites")
    return {
        "schema_version": "rq2-v2-stage4-l-test-report-v1",
        "status": "PASS",
        "commands": [
            (
                "PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/bin/python3 -m "
                "unittest -v evaluation.capability_routing_rq2_v2_stage4."
                "track_l_memory_specialist_execution.tests."
                "test_memory_specialist_execution evaluation."
                "capability_routing_rq2_v2_stage4."
                "track_l_memory_specialist_execution.tests."
                "test_memory_specialist_results"
            ),
            (
                "PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/bin/python3 -m "
                "unittest -v evaluation.capability_routing_rq2_v2_stage4."
                "track_k0_specialists.tests.test_specialist_protocol"
            ),
        ],
        "track_l_tests": {"passed": track_l_count, "failed": 0},
        "frozen_k0_tests": {"passed": k0_count, "failed": 0},
        "total_tests": track_l_count + k0_count,
        "failures": 0,
        "errors": 0,
    }


def _status_report(
    complete: bool,
    stop_reason: str | None,
    metrics: Mapping[str, Any],
    requested_models: Sequence[str],
    returned_models: Sequence[str],
    test_report: Mapping[str, Any],
) -> str:
    coverage = metrics["coverage"]
    status = (
        "FROZEN_AFTER_DEV_EXECUTION"
        if complete
        else "MEMORY_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
    )
    return f"""# RQ2-V2 Stage 4L Status

MEMORY_SPECIALIST_STATUS = `{status}`

- Scope: frozen Memory Specialist on 64 DEV ANSWER utterances only
- Stop reason: `{stop_reason or 'NONE'}`
- Requested model identities: `{', '.join(requested_models) or 'NONE'}`
- Returned model identities: `{', '.join(returned_models) or 'NONE'}`
- Logical terminal results: `{coverage['logical_terminal_results']}/64`
- Physical attempts: `{coverage['physical_attempt_count']}/128`
- Retries: `{coverage['retry_count']}`
- Valid predictions: `{coverage['valid_predictions']}/64`
- Prompt SHA-256: `{EXPECTED_PROMPT_SHA256}`
- Schema SHA-256: `{EXPECTED_SCHEMA_SHA256}`
- Frozen-source pre/post verification: `PASS`
- Final test status: `{test_report['status']}`
- RAG Specialist/P2/P3/P1/RQ3/future held-out provider calls: `0`

No composition or held-out execution is authorized by this freeze.
"""


def _verification_report(
    metrics: Mapping[str, Any],
    ledger: Mapping[str, Any],
    diff_report: Mapping[str, Any],
    source_verification: Mapping[str, Any],
    complete: bool,
    stop_reason: str | None,
    test_report: Mapping[str, Any],
) -> str:
    coverage = metrics["coverage"]
    return f"""# Memory Specialist DEV Execution Verification

Status: `{'PASS_COMPLETE_EXECUTION_AND_FREEZE' if complete else 'PASS_FAIL_CLOSED_INCOMPLETE_EXECUTION'}`

- Starting working directory/branch/HEAD boundary: `PASS`
- Frozen Stage 4K-0 hashes before and after: `{source_verification['status']}`
- Frozen Stage 4K-0 files verified: `{source_verification['post_execution']['k0_file_count']}`
- Frozen upstream source hashes verified: `{source_verification['post_execution']['upstream_file_count']}`
- Prompt SHA-256: `{EXPECTED_PROMPT_SHA256}`
- Schema SHA-256: `{EXPECTED_SCHEMA_SHA256}`
- P3 composition-contract SHA-256: `{EXPECTED_P3_CONTRACT_SHA256}`
- Evaluation-protocol SHA-256: `{EXPECTED_EVALUATION_PROTOCOL_SHA256}`
- Manifest V1/V2 difference boundary: `{diff_report['status']}`
- Semantic request elements preserved: `{str(diff_report['all_semantic_request_elements_identical']).lower()}`
- Logical terminal results: `{coverage['logical_terminal_results']}/64`
- Physical attempts: `{ledger['physical_attempts']}/128`
- Retries: `{ledger['retry_count']}`
- Complete durable journal lifecycles: `{ledger['completed_events']}`
- Uncompleted reservations: `{ledger['uncompleted_reservations']}`
- Serial execution: `{str(ledger['serial_execution']).lower()}`
- Minimum initial-request delay required: `{MIN_INITIAL_REQUEST_DELAY_SECONDS:.1f}` seconds
- Minimum observed interval: `{ledger['minimum_observed_initial_request_interval_seconds']}` seconds
- SDK `max_retries`: `{CLIENT_MAX_RETRIES}`
- Stop reason: `{stop_reason or 'NONE'}`
- Output credential and prohibited-partition scan: `PASS`
- Final tests: `{test_report['status']}`; total `{test_report['total_tests']}`; failures `{test_report['failures']}`; errors `{test_report['errors']}`
- RAG Specialist provider calls: `0`
- P2 provider calls/scoring: `0`
- P3 provider calls/scoring: `0`
- P1 provider calls/execution: `0`
- RQ3 provider calls/execution: `0`
- Future held-out provider calls/access: `0`

The Memory Specialist is frozen only when all 64 logical cases have valid strict
one-boolean structured predictions. This report does not authorize composition
or any future held-out execution.
"""


def finalize(
    *,
    stop_reason: str | None,
    manifest_diff_report: Mapping[str, Any] | None,
    track_l_test_count: int | None,
    k0_test_count: int | None,
) -> dict[str, Any]:
    verify_git_boundary(require_clean=False)
    frozen_sources = verify_frozen_sources()
    manifest_records, verified_diff = verify_manifest_v2()
    attempts = load_jsonl(ATTEMPT_RECORDS_PATH)
    terminals = load_jsonl(TERMINAL_RESULTS_PATH)
    journal = load_jsonl(CALL_JOURNAL_PATH)
    if not attempts or not terminals:
        raise RuntimeError("No Memory Specialist attempt/terminal outputs are available")
    ledger = _verify_call_ledger(attempts, journal, terminals)
    _write_predictions_and_errors(terminals, attempts, manifest_records)
    usage = _usage_report(attempts)
    atomic_write_json(USAGE_PATH, usage)
    metrics = _build_metrics(terminals, attempts, manifest_records)
    atomic_write_json(METRICS_PATH, metrics)
    write_post_execution_source_verification(frozen_sources)
    source_verification = load_json(SOURCE_VERIFICATION_PATH)

    requested_models = sorted(
        {
            str(record["requested_model"])
            for record in attempts
            if record.get("requested_model")
        }
    )
    returned_models = sorted(
        {
            str(record["returned_model"])
            for record in attempts
            if record.get("returned_model")
        }
    )
    complete = (
        len(terminals) == LOGICAL_CALL_CEILING
        and metrics["coverage"]["valid_predictions"] == LOGICAL_CALL_CEILING
        and ledger["status"] == "PASS"
        and requested_models == [AUTHORIZED_MODEL_SNAPSHOT]
        and returned_models == [AUTHORIZED_MODEL_SNAPSHOT]
    )
    status = (
        "FROZEN_AFTER_DEV_EXECUTION"
        if complete
        else "MEMORY_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
    )
    fold_hashes = load_json(FOLD_HASHES_PATH)["specialists"]["memory"]
    diff_report = dict(manifest_diff_report or verified_diff)
    final_configuration = {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-frozen-configuration-v1",
        "MEMORY_SPECIALIST_STATUS": status,
        "execution_scope": "64_FROZEN_DEV_ANSWER_UTTERANCES_MEMORY_ONLY",
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "schema_sha256": EXPECTED_SCHEMA_SHA256,
        "fold_specific_examples_and_order": fold_hashes["folds"],
        "final_full_dev_examples_and_order": fold_hashes["full_dev"],
        "temperature": 0,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "sdk_transport_retries": CLIENT_MAX_RETRIES,
        "manual_retry_policy": {
            "maximum_retries_per_logical_case": 1,
            "only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
            "identical_request_required": True,
            "correction_message_added": False,
            "silent_repair_allowed": False,
        },
        "execution_evidence": {
            "logical_terminal_results": len(terminals),
            "valid_predictions": metrics["coverage"]["valid_predictions"],
            "physical_attempts": len(attempts),
            "retries": ledger["retry_count"],
            "requested_models": requested_models,
            "returned_models": returned_models,
            "manifest_v1_sha256": diff_report["v1_manifest_sha256"],
            "manifest_v2_sha256": diff_report["v2_manifest_sha256"],
            "attempt_records_sha256": sha256_file(ATTEMPT_RECORDS_PATH),
            "call_journal_sha256": sha256_file(CALL_JOURNAL_PATH),
            "terminal_results_sha256": sha256_file(TERMINAL_RESULTS_PATH),
            "dev_predictions_sha256": sha256_file(PREDICTIONS_PATH),
            "frozen_source_verification_sha256": sha256_file(
                SOURCE_VERIFICATION_PATH
            ),
        },
        "provider_call_boundary": {
            "memory_specialist_dev_logical_calls": len(terminals),
            "memory_specialist_dev_physical_attempts": len(attempts),
            "rag_specialist_calls": 0,
            "p2_calls_or_scoring": 0,
            "p3_calls_or_scoring": 0,
            "p1_calls_or_execution": 0,
            "rq3_calls_or_execution": 0,
            "future_held_out_calls_or_access": 0,
            "further_authority_inferred": False,
        },
    }
    atomic_write_json(FROZEN_CONFIGURATION_PATH, final_configuration)

    test_report = _test_report(track_l_test_count, k0_test_count)
    atomic_write_json(TEST_REPORT_PATH, test_report)
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
        _status_report(
            complete,
            stop_reason,
            metrics,
            requested_models,
            returned_models,
            test_report,
        ),
    )
    preliminary_scan_paths = (
        V2_MANIFEST_PATH,
        MANIFEST_DIFF_PATH,
        SOURCE_VERIFICATION_PATH,
        ATTEMPT_RECORDS_PATH,
        CALL_JOURNAL_PATH,
        TERMINAL_RESULTS_PATH,
        PREDICTIONS_PATH,
        ERROR_REGISTRY_PATH,
        USAGE_PATH,
        METRICS_PATH,
        FROZEN_CONFIGURATION_PATH,
        RESULTS_REPORT_PATH,
        STATUS_PATH,
        TEST_REPORT_PATH,
    )
    credential_or_partition_scan(preliminary_scan_paths)
    atomic_write_text(
        VERIFICATION_REPORT_PATH,
        _verification_report(
            metrics,
            ledger,
            diff_report,
            source_verification,
            complete,
            stop_reason,
            test_report,
        ),
    )
    final_scan_paths = (*preliminary_scan_paths, VERIFICATION_REPORT_PATH)
    security = credential_or_partition_scan(final_scan_paths)
    output_manifest = write_output_sha256_manifest()
    credential_or_partition_scan((*final_scan_paths, OUTPUT_SHA256_MANIFEST_PATH))
    return {
        "MEMORY_SPECIALIST_STATUS": status,
        "logical_calls": len(terminals),
        "physical_attempts": len(attempts),
        "retries": ledger["retry_count"],
        "valid_predictions": metrics["coverage"]["valid_predictions"],
        "invalid_structured_output_attempts": metrics["coverage"][
            "invalid_structured_output_attempt_count"
        ],
        "terminal_provider_errors": metrics["coverage"][
            "terminal_provider_error_count"
        ],
        "requested_models": requested_models,
        "returned_models": returned_models,
        "approximate_cost_usd": usage["approximate_cost_usd"]["total"],
        "stop_reason": stop_reason,
        "test_status": test_report["status"],
        "output_files_hashed": output_manifest["file_count"],
        "security_scan_files": security["files_scanned"],
        "openai_sdk_version": importlib.metadata.version("openai"),
        "python_version": sys.version.split()[0],
    }
