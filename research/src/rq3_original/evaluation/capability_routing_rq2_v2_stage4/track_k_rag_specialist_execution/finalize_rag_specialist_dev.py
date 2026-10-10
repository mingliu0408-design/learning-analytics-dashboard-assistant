"""Finalize Stage 4K RAG Specialist outputs and DEV-only metrics."""

from __future__ import annotations

import collections
import csv
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .rag_specialist_protocol import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    CLIENT_MAX_RETRIES,
    DEV_PROTOCOL_DIR,
    ERROR_REGISTRY_PATH,
    EXPECTED_EVALUATION_PROTOCOL_SHA256,
    EXPECTED_P2_CONTRACT_SHA256,
    EXPECTED_PROMPT_SHA256,
    EXPECTED_SCHEMA_SHA256,
    FROZEN_CONFIGURATION_PATH,
    INPUT_PRICE_USD_PER_MILLION,
    LOGICAL_CALL_CEILING,
    MANIFEST_DIFF_PATH,
    MAX_OUTPUT_TOKENS,
    METRICS_PATH,
    MIN_INITIAL_REQUEST_INTERVAL_SECONDS,
    OUTPUT_PRICE_USD_PER_MILLION,
    PHYSICAL_ATTEMPT_CEILING,
    PREDICTIONS_PATH,
    PRE_EXECUTION_VERIFICATION_PATH,
    PRICING_REFERENCE_DATE,
    RESULTS_REPORT_PATH,
    RUN_VERSION,
    STATUS_PATH,
    TERMINAL_RESULTS_PATH,
    TEST_RESULTS_PATH,
    USAGE_AND_COST_PATH,
    V2_MANIFEST_PATH,
    VERIFICATION_REPORT_PATH,
    atomic_write_json,
    atomic_write_text,
    canonical_sha256,
    load_jsonl,
    read_csv,
    sha256_file,
    utc_now,
    verify_required_protocol,
    verify_worktree_boundary,
)


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 12)


def _gold_bool(value: str) -> bool:
    if value == "YES":
        return True
    if value == "NO":
        return False
    raise RuntimeError(f"Unexpected frozen RAG Gold value: {value}")


def _binary_metrics(
    case_ids: Sequence[str],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for case_id in case_ids:
        gold = _gold_bool(gold_by_id[case_id]["final_rag_required"])
        predicted = predictions[case_id]
        tp += int(gold and predicted)
        fp += int(not gold and predicted)
        tn += int(not gold and not predicted)
        fn += int(gold and not predicted)
    count = len(case_ids)
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    if precision is None or recall is None or precision + recall == 0:
        f1 = None if precision is None or recall is None else 0.0
    else:
        f1 = round(2 * precision * recall / (precision + recall), 12)
    positive_count = tp + fp
    return {
        "status": "COMPUTED_ON_VALID_TERMINAL_PREDICTIONS",
        "case_count": count,
        "accuracy": _safe_div(tp + tn, count),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": _safe_div(tn, tn + fp),
        "specificity_numerator_tn": tn,
        "specificity_denominator_tn_plus_fp": tn + fp,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "positive_prediction_count": positive_count,
        "positive_prediction_rate": _safe_div(positive_count, count),
    }


def _stratified_metrics(
    groups: Mapping[str, Sequence[str]],
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group_name in sorted(groups):
        ids = list(groups[group_name])
        valid = [case_id for case_id in ids if case_id in predictions]
        result[group_name] = {
            "total_cases": len(ids),
            "valid_predictions": len(valid),
            "coverage": _safe_div(len(valid), len(ids)),
            "complete_case_metrics": _binary_metrics(valid, gold_by_id, predictions),
        }
    return result


def _family_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    families: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        families[row["scenario_family_id"]].append(case_id)
    if len(families) != 32 or any(len(ids) != 2 for ids in families.values()):
        raise RuntimeError("Frozen RAG population must contain 32 two-utterance families")
    covered = both_correct = prediction_consistent = 0
    for ids in families.values():
        if not all(case_id in predictions for case_id in ids):
            continue
        covered += 1
        prediction_consistent += int(len({predictions[case_id] for case_id in ids}) == 1)
        both_correct += int(
            all(
                predictions[case_id]
                == _gold_bool(gold_by_id[case_id]["final_rag_required"])
                for case_id in ids
            )
        )
    return {
        "total_two_utterance_families": len(families),
        "fully_covered_families": covered,
        "fully_covered_family_rate": _safe_div(covered, len(families)),
        "family_both_utterances_correct_count": both_correct,
        "family_both_utterances_correct_complete_case_rate": (
            _safe_div(both_correct, covered) if covered else None
        ),
        "family_both_utterances_correct_coverage_adjusted_rate": _safe_div(
            both_correct, len(families)
        ),
        "family_prediction_consistency_count": prediction_consistent,
        "family_prediction_consistency_complete_case_rate": (
            _safe_div(prediction_consistent, covered) if covered else None
        ),
    }


def _rag_contrast_metrics(
    gold_by_id: Mapping[str, Mapping[str, str]],
    predictions: Mapping[str, bool],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in read_csv(DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv"):
        if (
            row["annotation_case_id"] in gold_by_id
            and row["dev_contrast_axis"] == "RAG"
        ):
            groups[row["dev_contrast_group_id"]].append(row)
    if len(groups) != 2:
        raise RuntimeError("Frozen DEV population must contain two RAG contrast groups")
    fully_covered = contrast_consistent = gold_pattern_matched = 0
    details: list[dict[str, Any]] = []
    for group_id, rows in sorted(groups.items()):
        family_cases: dict[str, list[str]] = collections.defaultdict(list)
        for row in rows:
            family_cases[row["scenario_family_id"]].append(row["annotation_case_id"])
        if len(family_cases) != 2 or any(len(ids) != 2 for ids in family_cases.values()):
            raise RuntimeError("RAG contrast group family shape changed")
        all_ids = [case_id for ids in family_cases.values() for case_id in ids]
        covered = all(case_id in predictions for case_id in all_ids)
        family_prediction_consistent = False
        directed_change_matched = False
        pattern_matched = False
        if covered:
            fully_covered += 1
            predicted_family: dict[str, bool] = {}
            gold_family: dict[str, bool] = {}
            family_prediction_consistent = True
            for family_id, ids in family_cases.items():
                predicted_values = {predictions[case_id] for case_id in ids}
                gold_values = {
                    _gold_bool(gold_by_id[case_id]["final_rag_required"])
                    for case_id in ids
                }
                if len(gold_values) != 1:
                    raise RuntimeError("Frozen RAG Gold is inconsistent within a family")
                gold_family[family_id] = next(iter(gold_values))
                if len(predicted_values) != 1:
                    family_prediction_consistent = False
                else:
                    predicted_family[family_id] = next(iter(predicted_values))
            if family_prediction_consistent:
                ordered_families = sorted(family_cases)
                predicted_change = [
                    int(predicted_family[right]) - int(predicted_family[left])
                    for left, right in zip(
                        ordered_families,
                        ordered_families[1:],
                    )
                ]
                gold_change = [
                    int(gold_family[right]) - int(gold_family[left])
                    for left, right in zip(
                        ordered_families,
                        ordered_families[1:],
                    )
                ]
                directed_change_matched = predicted_change == gold_change
                contrast_consistent += int(directed_change_matched)
            pattern_matched = all(
                predictions[case_id]
                == _gold_bool(gold_by_id[case_id]["final_rag_required"])
                for case_id in all_ids
            )
            gold_pattern_matched += int(pattern_matched)
        details.append(
            {
                "contrast_group_id": group_id,
                "utterance_count": len(all_ids),
                "family_count": len(family_cases),
                "fully_covered": covered,
                "predicted_within_family_consistent": family_prediction_consistent,
                "directed_rag_bit_change_matched_gold": directed_change_matched,
                "rag_gold_pattern_matched": pattern_matched,
            }
        )
    total = len(groups)
    return {
        "definition": (
            "Eligible RAG-axis contrast groups only. RAG contrast consistency "
            "requires both predictions within each family to agree and the directed "
            "family-level RAG-bit change to match frozen Gold. Gold-pattern match "
            "requires every utterance RAG prediction to equal frozen Gold."
        ),
        "total_eligible_rag_contrast_groups": total,
        "fully_covered_rag_contrast_groups": fully_covered,
        "fully_covered_rate": _safe_div(fully_covered, total),
        "rag_contrast_consistent_count": contrast_consistent,
        "rag_contrast_consistency_complete_case_rate": (
            _safe_div(contrast_consistent, fully_covered) if fully_covered else None
        ),
        "rag_contrast_consistency_coverage_adjusted_rate": _safe_div(
            contrast_consistent, total
        ),
        "rag_gold_pattern_contrast_match_count": gold_pattern_matched,
        "rag_gold_pattern_contrast_match_complete_case_rate": (
            _safe_div(gold_pattern_matched, fully_covered) if fully_covered else None
        ),
        "rag_gold_pattern_contrast_match_coverage_adjusted_rate": _safe_div(
            gold_pattern_matched, total
        ),
        "groups": details,
    }


def verify_call_ledger(
    attempts: Sequence[Mapping[str, Any]],
    journal: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_numbers = [int(record["physical_attempt_number"]) for record in attempts]
    if physical_numbers != list(range(1, len(attempts) + 1)):
        raise RuntimeError("Physical attempt order is not contiguous")
    if len(attempts) > PHYSICAL_ATTEMPT_CEILING:
        raise RuntimeError("Physical attempt ceiling exceeded")
    events_by_attempt: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for event in journal:
        events_by_attempt[event["physical_attempt_id"]].append(event)
    attempt_ids = [record["physical_attempt_id"] for record in attempts]
    if set(events_by_attempt) != set(attempt_ids):
        raise RuntimeError("Call journal attempt IDs differ from attempt records")
    completion_outcome: dict[str, str] = {}
    for attempt in attempts:
        events = events_by_attempt[attempt["physical_attempt_id"]]
        if [event["event"] for event in events] != [
            "ATTEMPT_RESERVED",
            "ATTEMPT_COMPLETED",
        ]:
            raise RuntimeError("Call journal reservation/completion lifecycle is incomplete")
        if events[0]["request_sha256"] != attempt["request_sha256"]:
            raise RuntimeError("Journal reservation request hash mismatch")
        if events[1]["attempt_record_sha256"] != canonical_sha256(attempt):
            raise RuntimeError("Journal completion attempt-record hash mismatch")
        completion_outcome[attempt["physical_attempt_id"]] = events[1]["outcome"]
    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for attempt in attempts:
        attempts_by_logical[attempt["logical_call_id"]].append(attempt)
    retry_count = 0
    for logical_id, logical_attempts in attempts_by_logical.items():
        if len(logical_attempts) > 2:
            raise RuntimeError(f"More than two attempts for {logical_id}")
        if [record["attempt_number"] for record in logical_attempts] != list(
            range(1, len(logical_attempts) + 1)
        ):
            raise RuntimeError(f"Attempt numbering changed for {logical_id}")
        if len(logical_attempts) == 2:
            retry_count += 1
            first = logical_attempts[0]
            if completion_outcome[first["physical_attempt_id"]] != "INVALID_STRUCTURED_OUTPUT":
                raise RuntimeError("Retry followed a non-retryable outcome")
            if logical_attempts[1]["request_sha256"] != first["request_sha256"]:
                raise RuntimeError("Retry request differs from initial request")
    terminal_by_logical = {record["logical_call_id"]: record for record in terminals}
    if len(terminal_by_logical) != len(terminals):
        raise RuntimeError("Duplicate logical terminal result")
    for logical_id, terminal in terminal_by_logical.items():
        if len(attempts_by_logical[logical_id]) != int(terminal["attempts_used"]):
            raise RuntimeError("Terminal attempts_used differs from attempt records")
    initial_attempts = [record for record in attempts if record["attempt_number"] == 1]
    for record in initial_attempts[1:]:
        interval = record.get("initial_request_interval_seconds")
        if interval is None or float(interval) < MIN_INITIAL_REQUEST_INTERVAL_SECONDS:
            raise RuntimeError("Initial provider-request pacing fell below 2.0 seconds")
    return {
        "status": "PASS_DURABLE_BOUNDED_CALL_LEDGER",
        "logical_terminal_records": len(terminals),
        "physical_attempt_records": len(attempts),
        "physical_attempt_ceiling": PHYSICAL_ATTEMPT_CEILING,
        "journal_events": len(journal),
        "reserved_events": sum(event["event"] == "ATTEMPT_RESERVED" for event in journal),
        "completed_events": sum(event["event"] == "ATTEMPT_COMPLETED" for event in journal),
        "uncompleted_reservations": 0,
        "retry_count": retry_count,
        "retry_policy_violations": 0,
        "initial_request_count": len(initial_attempts),
        "minimum_initial_request_interval_seconds": (
            min(
                float(record["initial_request_interval_seconds"])
                for record in initial_attempts[1:]
            )
            if len(initial_attempts) > 1
            else None
        ),
    }


def usage_report(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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
    input_price = Decimal(INPUT_PRICE_USD_PER_MILLION)
    output_price = Decimal(OUTPUT_PRICE_USD_PER_MILLION)
    input_cost = Decimal(input_tokens) * input_price / Decimal(1_000_000)
    output_cost = Decimal(output_tokens) * output_price / Decimal(1_000_000)
    return {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-usage-and-cost-v1",
        "pricing_reference_date": PRICING_REFERENCE_DATE,
        "pricing_reference": {
            "input_usd_per_1m_text_tokens": INPUT_PRICE_USD_PER_MILLION,
            "output_usd_per_1m_text_tokens": OUTPUT_PRICE_USD_PER_MILLION,
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
            "total": format(input_cost + output_cost, ".8f"),
        },
        "cost_label": (
            "Approximate calculation from provider-returned usage and the stated "
            "reference rates; not a billing statement."
        ),
    }


def _gold_rows_for_manifest(
    manifest: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    ids = {record["annotation_case_id"] for record in manifest}
    rows = {
        row["annotation_case_id"]: row
        for row in read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        if row["annotation_case_id"] in ids
    }
    if set(rows) != ids or len(rows) != LOGICAL_CALL_CEILING:
        raise RuntimeError("Frozen DEV RAG Gold does not match manifest population")
    if any(
        row["partition"] != "DEV" or row["final_dialogue_action"] != "ANSWER"
        for row in rows.values()
    ):
        raise RuntimeError("Metrics population crossed the DEV ANSWER boundary")
    return rows


def build_metrics(
    manifest: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    gold_by_id = _gold_rows_for_manifest(manifest)
    predictions = {
        record["annotation_case_id"]: bool(record["prediction"]["rag_required"])
        for record in terminals
        if record["terminal_status"] == "VALID_PREDICTION"
    }
    manifest_order = [record["annotation_case_id"] for record in manifest]
    valid_ids = [case_id for case_id in manifest_order if case_id in predictions]
    status_counts = collections.Counter(record["terminal_status"] for record in terminals)
    provider_statuses = {
        "PROVIDER_ERROR",
        "PROVIDER_REFUSAL",
        "RETURNED_MODEL_MISMATCH",
    }
    page_groups: dict[str, list[str]] = collections.defaultdict(list)
    for case_id in manifest_order:
        page_groups[gold_by_id[case_id]["current_page"]].append(case_id)
    fold_groups: dict[str, list[str]] = collections.defaultdict(list)
    for record in manifest:
        fold_groups[record["outer_fold"]].append(record["annotation_case_id"])
    metrics = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-dev-metrics-v1",
        "evaluation_scope": "DEV_ONLY_RAG_SPECIALIST_ANSWER_CASES",
        "generalization_claim": "NONE",
        "coverage": {
            "total_authorized_dev_answer_cases": LOGICAL_CALL_CEILING,
            "logical_terminal_records": len(terminals),
            "valid_predictions": len(predictions),
            "valid_prediction_coverage": _safe_div(
                len(predictions), LOGICAL_CALL_CEILING
            ),
            "missing_or_invalid_predictions": LOGICAL_CALL_CEILING - len(predictions),
            "invalid_structured_output_count": status_counts[
                "INVALID_STRUCTURED_OUTPUT"
            ],
            "provider_error_count": sum(
                status_counts[status] for status in provider_statuses
            ),
            "retry_count": sum(
                max(0, int(record["attempts_used"]) - 1) for record in terminals
            ),
            "physical_attempt_count": len(attempts),
            "terminal_status_counts": dict(sorted(status_counts.items())),
        },
        "complete_case_metrics": _binary_metrics(
            valid_ids, gold_by_id, predictions
        ),
        "coverage_adjusted_status": {
            "status": (
                "COMPLETE_64_OF_64"
                if len(predictions) == LOGICAL_CALL_CEILING
                else "INCOMPLETE_DO_NOT_TREAT_AS_FULL_DEV_ESTIMATE"
            ),
            "missing_outputs_imputed": False,
            "fallback_used": False,
        },
        "family_metrics": _family_metrics(gold_by_id, predictions),
        "rag_contrast_metrics": _rag_contrast_metrics(gold_by_id, predictions),
        "page_stratified_metrics": _stratified_metrics(
            page_groups, gold_by_id, predictions
        ),
        "fold_stratified_metrics": _stratified_metrics(
            fold_groups, gold_by_id, predictions
        ),
        "joint_b4_comparison_performed": False,
        "composition_scoring_performed": False,
        "test_scoring_performed": False,
    }
    return metrics, gold_by_id


def _write_predictions_and_errors(
    manifest: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> None:
    terminal_by_logical = {
        terminal["logical_call_id"]: terminal for terminal in terminals
    }
    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for attempt in attempts:
        attempts_by_logical[attempt["logical_call_id"]].append(attempt)
    prediction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    for record in manifest:
        terminal = terminal_by_logical.get(record["logical_call_id"])
        if terminal is None:
            prediction_rows.append(
                {
                    "logical_call_id": record["logical_call_id"],
                    "annotation_case_id": record["annotation_case_id"],
                    "fold_id": record["outer_fold"],
                    "rag_required": "",
                    "terminal_status": "NOT_EXECUTED_DUE_TO_RUN_STOP",
                    "attempts_used": 0,
                    "response_id": "",
                    "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
                    "returned_model": "",
                    "request_sha256": record["provider_facing_request_sha256"],
                }
            )
            continue
        prediction = terminal.get("prediction")
        prediction_rows.append(
            {
                "logical_call_id": terminal["logical_call_id"],
                "annotation_case_id": terminal["annotation_case_id"],
                "fold_id": terminal["fold_id"],
                "rag_required": (
                    str(prediction["rag_required"]).lower() if prediction else ""
                ),
                "terminal_status": terminal["terminal_status"],
                "attempts_used": terminal["attempts_used"],
                "response_id": terminal.get("response_id") or "",
                "requested_model": terminal["requested_model"],
                "returned_model": terminal.get("returned_model") or "",
                "request_sha256": terminal["request_sha256"],
            }
        )
        for attempt in attempts_by_logical[terminal["logical_call_id"]]:
            validation = attempt["schema_validation"]
            provider_error = attempt.get("provider_error") or {}
            if validation["valid"] and not provider_error:
                continue
            error_rows.append(
                {
                    "physical_attempt_id": attempt["physical_attempt_id"],
                    "logical_call_id": attempt["logical_call_id"],
                    "annotation_case_id": attempt["annotation_case_id"],
                    "fold_id": attempt["fold_id"],
                    "attempt_number": attempt["attempt_number"],
                    "schema_validation_error": validation.get("error") or "",
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
                }
            )
    prediction_fields = [
        "logical_call_id",
        "annotation_case_id",
        "fold_id",
        "rag_required",
        "terminal_status",
        "attempts_used",
        "response_id",
        "requested_model",
        "returned_model",
        "request_sha256",
    ]
    error_fields = [
        "physical_attempt_id",
        "logical_call_id",
        "annotation_case_id",
        "fold_id",
        "attempt_number",
        "schema_validation_error",
        "provider_exception_type",
        "provider_error_category",
        "provider_http_status",
        "provider_error_code",
        "provider_error_param",
        "provider_request_id",
        "sanitized_error_message",
    ]
    for path, fields, rows in (
        (PREDICTIONS_PATH, prediction_fields, prediction_rows),
        (ERROR_REGISTRY_PATH, error_fields, error_rows),
    ):
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)


def _format_metric(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _load_test_summary() -> dict[str, Any] | None:
    if not TEST_RESULTS_PATH.is_file():
        return None
    result = json.loads(TEST_RESULTS_PATH.read_text(encoding="utf-8"))
    return result


def _stratified_markdown(title: str, values: Mapping[str, Any]) -> str:
    lines = [
        f"### {title}",
        "",
        "| Stratum | Valid/Total | Accuracy | Precision | Recall | F1 | Specificity |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in sorted(values.items()):
        metric = item["complete_case_metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    f"{item['valid_predictions']}/{item['total_cases']}",
                    _format_metric(metric["accuracy"]),
                    _format_metric(metric["precision"]),
                    _format_metric(metric["recall"]),
                    _format_metric(metric["f1"]),
                    _format_metric(metric["specificity"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _reports(
    status: str,
    metrics: Mapping[str, Any],
    usage: Mapping[str, Any],
    ledger: Mapping[str, Any],
    source_hashes_match: bool,
    requested_models: Sequence[str],
    returned_models: Sequence[str],
    stop_reason: str | None,
    test_summary: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    coverage = metrics["coverage"]
    core = metrics["complete_case_metrics"]
    confusion = core["confusion_matrix"]
    family = metrics["family_metrics"]
    contrast = metrics["rag_contrast_metrics"]
    provider_usage = usage["actual_provider_usage"]
    cost = usage["approximate_cost_usd"]
    tests_line = (
        f"{test_summary['tests_run']} run, {test_summary['failures']} failures, "
        f"{test_summary['errors']} errors, {test_summary['skipped']} skipped"
        if test_summary
        else "not yet recorded"
    )
    results = f"""# RAG Specialist DEV Execution Results

Status: `{status}`

- Run version: `{RUN_VERSION}`
- Stop reason: `{stop_reason or 'NONE'}`
- Requested model identities: `{', '.join(requested_models) or 'NONE'}`
- Returned model identities: `{', '.join(returned_models) or 'NONE'}`
- Logical terminal records: `{coverage['logical_terminal_records']}/64`
- Physical attempts: `{coverage['physical_attempt_count']}/128`
- Retries: `{coverage['retry_count']}`
- Valid prediction coverage: `{coverage['valid_predictions']}/64` (`{_format_metric(coverage['valid_prediction_coverage'])}`)
- Invalid structured-output terminals: `{coverage['invalid_structured_output_count']}`
- Provider/refusal/model-identity errors: `{coverage['provider_error_count']}`

## Complete-case RAG metrics

- Accuracy: `{_format_metric(core['accuracy'])}`
- Precision: `{_format_metric(core['precision'])}`
- Recall: `{_format_metric(core['recall'])}`
- F1: `{_format_metric(core['f1'])}`
- Specificity: `{_format_metric(core['specificity'])}` (`{core['specificity_numerator_tn']}/{core['specificity_denominator_tn_plus_fp']}`)
- Confusion matrix: TP=`{confusion['tp']}`, FP=`{confusion['fp']}`, TN=`{confusion['tn']}`, FN=`{confusion['fn']}`
- Positive predictions: `{core['positive_prediction_count']}/{core['case_count']}` (`{_format_metric(core['positive_prediction_rate'])}`)

Missing or invalid outputs are excluded from complete-case metrics and are never imputed.

## Family and RAG-contrast metrics

- Family-both-utterances-correct: `{family['family_both_utterances_correct_count']}/{family['fully_covered_families']}` (`{_format_metric(family['family_both_utterances_correct_complete_case_rate'])}` complete-case)
- Family prediction consistency: `{family['family_prediction_consistency_count']}/{family['fully_covered_families']}` (`{_format_metric(family['family_prediction_consistency_complete_case_rate'])}` complete-case)
- RAG contrast consistency: `{contrast['rag_contrast_consistent_count']}/{contrast['fully_covered_rag_contrast_groups']}` (`{_format_metric(contrast['rag_contrast_consistency_complete_case_rate'])}` complete-case)
- RAG Gold-pattern contrast match: `{contrast['rag_gold_pattern_contrast_match_count']}/{contrast['fully_covered_rag_contrast_groups']}` (`{_format_metric(contrast['rag_gold_pattern_contrast_match_complete_case_rate'])}` complete-case)

{_stratified_markdown('Page-stratified metrics', metrics['page_stratified_metrics'])}

{_stratified_markdown('Fold-stratified metrics', metrics['fold_stratified_metrics'])}

## Usage and approximate cost

- Input tokens: `{provider_usage['input_tokens']}`
- Output tokens: `{provider_usage['output_tokens']}`
- Total tokens: `{provider_usage['total_tokens']}`
- Actual physical attempts: `{provider_usage['physical_attempts']}`
- Approximate input cost: USD `{cost['input']}`
- Approximate output cost: USD `{cost['output']}`
- Approximate total cost: USD `{cost['total']}`

The cost is an approximate calculation from provider-returned usage and the user-stated 2026-08-31 reference rates. It is not a billing statement.

## Boundaries

- TEST calls/access: `0`
- Memory-Specialist calls: `0`
- P2/P3 composition calls or scoring: `0`
- P1 calls: `0`
- RQ3 calls: `0`
- Joint B4 calls or comparison: `0`
- Final full-DEV prompt executed on TEST: `false`
- Tests: `{tests_line}`
"""
    verification = f"""# RAG Specialist DEV Execution Verification

Status: `{status}`

- Frozen Stage 4K-0 source hashes matched before and after execution: `{str(source_hashes_match).lower()}`
- Frozen prompt SHA-256: `{EXPECTED_PROMPT_SHA256}`
- Frozen schema SHA-256: `{EXPECTED_SCHEMA_SHA256}`
- P2 composition contract SHA-256: `{EXPECTED_P2_CONTRACT_SHA256}`
- Evaluation protocol SHA-256: `{EXPECTED_EVALUATION_PROTOCOL_SHA256}`
- Authorized model snapshot: `{AUTHORIZED_MODEL_SNAPSHOT}`
- Requested model identities: `{', '.join(requested_models) or 'NONE'}`
- Returned model identities: `{', '.join(returned_models) or 'NONE'}`
- Temperature: `0`
- Maximum output tokens: `{MAX_OUTPUT_TOKENS}`
- Stream: `false`
- SDK max retries: `{CLIENT_MAX_RETRIES}`
- Invalid structured-output retry ceiling per logical case: `1`
- Logical records: `{coverage['logical_terminal_records']}/64`
- Physical attempts: `{ledger['physical_attempt_records']}/128`
- Durable journal reservations/completions: `{ledger['reserved_events']}/{ledger['completed_events']}`
- Retry-policy violations: `{ledger['retry_policy_violations']}`
- Minimum observed interval between initial requests: `{_format_metric(ledger['minimum_initial_request_interval_seconds'])}` seconds
- Valid predictions: `{coverage['valid_predictions']}/64`
- Credentials or request headers recorded: `false`
- TEST identifiers/provider calls: `0`
- Memory-Specialist provider calls: `0`
- P2/P3/P1/RQ3 provider calls: `0`
- Tests: `{tests_line}`
"""
    status_report = f"""# Status

`RAG_SPECIALIST_STATUS = {status}`

- DEV valid prediction coverage: `{coverage['valid_predictions']}/64`
- Physical attempts: `{coverage['physical_attempt_count']}/128`
- Retries: `{coverage['retry_count']}`
- Frozen source identity after execution: `{'PASS' if source_hashes_match else 'FAIL'}`
- Requested model: `{', '.join(requested_models) or 'NONE'}`
- Returned model: `{', '.join(returned_models) or 'NONE'}`
- TEST, Memory-Specialist, P2/P3, P1, and RQ3 calls: `0`
- Composition and TEST execution remain unauthorized and were not performed.
"""
    return results, verification, status_report


def finalize(
    *,
    stop_reason: str | None = None,
    pre_http_verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_worktree_boundary()
    if not all(
        path.is_file()
        for path in (ATTEMPT_RECORDS_PATH, CALL_JOURNAL_PATH, TERMINAL_RESULTS_PATH)
    ):
        raise RuntimeError("Execution ledger is incomplete; cannot finalize")
    manifest = load_jsonl(V2_MANIFEST_PATH)
    attempts = load_jsonl(ATTEMPT_RECORDS_PATH)
    journal = load_jsonl(CALL_JOURNAL_PATH)
    terminals = load_jsonl(TERMINAL_RESULTS_PATH)
    ledger = verify_call_ledger(attempts, journal, terminals)
    post_protocol = verify_required_protocol()
    pre_record = json.loads(PRE_EXECUTION_VERIFICATION_PATH.read_text(encoding="utf-8"))
    source_hashes_match = (
        pre_record["protocol"]["k0_source_hashes"]
        == post_protocol["k0_source_hashes"]
        and pre_record["protocol"]["external_dev_source_hashes"]
        == post_protocol["external_dev_source_hashes"]
    )
    if not source_hashes_match:
        raise RuntimeError("Frozen source hashes changed during provider execution")
    _write_predictions_and_errors(manifest, terminals, attempts)
    metrics, _ = build_metrics(manifest, terminals, attempts)
    usage = usage_report(attempts)
    atomic_write_json(METRICS_PATH, metrics)
    atomic_write_json(USAGE_AND_COST_PATH, usage)

    coverage = metrics["coverage"]
    requested_models = sorted(
        {str(record["requested_model"]) for record in attempts if record.get("requested_model")}
    )
    returned_models = sorted(
        {str(record["returned_model"]) for record in attempts if record.get("returned_model")}
    )
    fully_valid = (
        len(terminals) == LOGICAL_CALL_CEILING
        and coverage["valid_predictions"] == LOGICAL_CALL_CEILING
        and requested_models == [AUTHORIZED_MODEL_SNAPSHOT]
        and returned_models == [AUTHORIZED_MODEL_SNAPSHOT]
        and source_hashes_match
    )
    status = (
        "FROZEN_AFTER_DEV_EXECUTION"
        if fully_valid
        else "RAG_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
    )
    diff_report = json.loads(MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
    test_summary = _load_test_summary()
    primary_hashes = {
        path.name: sha256_file(path)
        for path in (
            ATTEMPT_RECORDS_PATH,
            CALL_JOURNAL_PATH,
            TERMINAL_RESULTS_PATH,
            PREDICTIONS_PATH,
            ERROR_REGISTRY_PATH,
            USAGE_AND_COST_PATH,
            METRICS_PATH,
        )
    }
    frozen_configuration = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-frozen-configuration-v1",
        "RAG_SPECIALIST_STATUS": status,
        "run_version": RUN_VERSION,
        "finalized_at": utc_now(),
        "stop_reason": stop_reason,
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "requested_model_identities": requested_models,
        "returned_model_identities": returned_models,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "schema_sha256": EXPECTED_SCHEMA_SHA256,
        "fold_examples_and_order": post_protocol["folds"],
        "final_full_dev_examples_and_order": post_protocol["final_full_dev"],
        "temperature": 0,
        "maximum_output_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "retry_policy": {
            "sdk_transport_retries": CLIENT_MAX_RETRIES,
            "invalid_structured_output_retries_max_per_case": 1,
            "retry_condition": "INVALID_JSON_OR_FROZEN_STRICT_SCHEMA_FAILURE_ONLY",
            "correction_message_added": False,
            "silent_repair_allowed": False,
        },
        "logical_call_ceiling": LOGICAL_CALL_CEILING,
        "physical_attempt_ceiling": PHYSICAL_ATTEMPT_CEILING,
        "actual_logical_terminal_results": len(terminals),
        "actual_physical_attempts": len(attempts),
        "valid_prediction_count": coverage["valid_predictions"],
        "dev_prediction_sha256": sha256_file(PREDICTIONS_PATH),
        "v2_manifest_sha256": sha256_file(V2_MANIFEST_PATH),
        "v1_v2_diff_status": diff_report["status"],
        "pre_execution_k0_source_hashes": pre_record["protocol"]["k0_source_hashes"],
        "post_execution_k0_source_hashes": post_protocol["k0_source_hashes"],
        "pre_execution_external_dev_source_hashes": pre_record["protocol"][
            "external_dev_source_hashes"
        ],
        "post_execution_external_dev_source_hashes": post_protocol[
            "external_dev_source_hashes"
        ],
        "pre_post_source_hashes_identical": source_hashes_match,
        "primary_output_sha256": primary_hashes,
        "call_ledger_verification": ledger,
        "test_summary": test_summary,
        "execution_scope_assertions": {
            "dev_rag_specialist_logical_calls": len(terminals),
            "test_calls": 0,
            "test_inputs_accessed": 0,
            "memory_specialist_calls": 0,
            "p2_calls_or_scoring": 0,
            "p3_calls_or_scoring": 0,
            "p1_calls": 0,
            "rq3_calls": 0,
            "joint_b4_calls": 0,
            "joint_b4_comparison_performed": False,
            "final_full_dev_prompt_executed_on_test": False,
        },
    }
    atomic_write_json(FROZEN_CONFIGURATION_PATH, frozen_configuration)
    results, verification, status_report = _reports(
        status,
        metrics,
        usage,
        ledger,
        source_hashes_match,
        requested_models,
        returned_models,
        stop_reason,
        test_summary,
    )
    atomic_write_text(RESULTS_REPORT_PATH, results)
    atomic_write_text(VERIFICATION_REPORT_PATH, verification)
    atomic_write_text(STATUS_PATH, status_report)
    return {
        "status": status,
        "logical_terminal_results": len(terminals),
        "physical_attempts": len(attempts),
        "retries": coverage["retry_count"],
        "valid_predictions": coverage["valid_predictions"],
        "requested_models": requested_models,
        "returned_models": returned_models,
        "approximate_cost_usd": usage["approximate_cost_usd"]["total"],
        "source_hashes_match": source_hashes_match,
        "test_summary_recorded": test_summary is not None,
    }


def main() -> int:
    result = finalize()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
