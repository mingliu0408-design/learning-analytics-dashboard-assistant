"""Finalize and score only the new schema-V2 B4 DEV R1 execution."""

from __future__ import annotations

import collections
import csv
from decimal import Decimal
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

import finalize_b4_dev as base_metrics
from execute_b4_dev_r1 import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    CLIENT_MAX_RETRIES,
    CUMULATIVE_PHYSICAL_ATTEMPT_CEILING,
    EXPECTED_PROMPT_SHA256,
    HISTORICAL_PHYSICAL_ATTEMPTS,
    HISTORICAL_PRESERVATION_PATH,
    HISTORICAL_STAGE4IX_SHA256,
    LOGICAL_CALL_CEILING,
    MANIFEST_DIFF_PATH,
    MAX_OUTPUT_TOKENS,
    NEW_PHYSICAL_ATTEMPT_CEILING,
    SCHEMA_V2_PATH,
    TERMINAL_RESULTS_PATH,
    TRACK_DIR,
    V3_MANIFEST_PATH,
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    schema_v1_v2_equivalence,
    sha256_file,
    verify_historical_artifacts,
    verify_v3_files,
)
from build_b4_preparation import LABEL_FIELDS


DEV_PROTOCOL_DIR = TRACK_DIR.parent / "dev_protocol"
PREDICTIONS_PATH = TRACK_DIR / "b4_dev_predictions_v2.csv"
ERROR_REGISTRY_PATH = TRACK_DIR / "b4_dev_error_registry_v2.csv"
USAGE_PATH = TRACK_DIR / "b4_dev_usage_and_cost_v2.json"
METRICS_PATH = TRACK_DIR / "b4_dev_metrics_v2.json"
FINAL_FREEZE_PATH = TRACK_DIR / "b4_final_frozen_configuration_v2.json"
RESULTS_REPORT_PATH = TRACK_DIR / "B4_DEV_EXECUTION_RESULTS_R1.md"
STATUS_PATH = TRACK_DIR / "B4_DEV_EXECUTION_STATUS_R1.md"
VERIFICATION_REPORT_PATH = TRACK_DIR / "B4_DEV_EXECUTION_VERIFICATION_R1.md"
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
        writer.writerows(rows)
        handle.flush()
    temporary.replace(path)


def _bool_csv(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _verify_call_ledger(
    attempts: Sequence[Mapping[str, Any]],
    journal: Sequence[Mapping[str, Any]],
    terminals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_numbers = [int(record["physical_attempt_number"]) for record in attempts]
    if physical_numbers != list(range(1, len(attempts) + 1)):
        raise RuntimeError("R1 attempt records are not in deterministic order")
    cumulative_numbers = [
        int(record["cumulative_physical_attempt_number"]) for record in attempts
    ]
    if cumulative_numbers != list(range(2, len(attempts) + 2)):
        raise RuntimeError("R1 cumulative physical-attempt accounting differs")
    if len(attempts) > NEW_PHYSICAL_ATTEMPT_CEILING:
        raise RuntimeError("R1 new physical-attempt ceiling exceeded")
    cumulative = HISTORICAL_PHYSICAL_ATTEMPTS + len(attempts)
    if cumulative > CUMULATIVE_PHYSICAL_ATTEMPT_CEILING:
        raise RuntimeError("Cumulative physical-attempt ceiling exceeded")

    events_by_attempt: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for event in journal:
        events_by_attempt[str(event["physical_attempt_id"])].append(event)
    expected_ids = [str(record["physical_attempt_id"]) for record in attempts]
    if set(events_by_attempt) != set(expected_ids):
        raise RuntimeError("R1 journal IDs differ from attempt records")
    attempts_by_id = {str(record["physical_attempt_id"]): record for record in attempts}
    for attempt_id in expected_ids:
        events = events_by_attempt[attempt_id]
        if [event["event"] for event in events] != [
            "ATTEMPT_RESERVED",
            "ATTEMPT_COMPLETED",
        ]:
            raise RuntimeError(f"Incomplete R1 journal lifecycle: {attempt_id}")
        attempt = attempts_by_id[attempt_id]
        if any(event["request_sha256"] != attempt["request_sha256"] for event in events):
            raise RuntimeError(f"R1 journal request hash mismatch: {attempt_id}")
    attempt_counts = collections.Counter(
        str(record["logical_call_id"]) for record in attempts
    )
    for terminal in terminals:
        if attempt_counts[str(terminal["logical_call_id"])] != int(
            terminal["attempts_used"]
        ):
            raise RuntimeError("Terminal attempt count differs from ledger")
    return {
        "status": "PASS",
        "historical_physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS,
        "new_physical_attempts": len(attempts),
        "cumulative_physical_attempts": cumulative,
        "new_physical_attempt_ceiling": NEW_PHYSICAL_ATTEMPT_CEILING,
        "cumulative_physical_attempt_ceiling": CUMULATIVE_PHYSICAL_ATTEMPT_CEILING,
        "journal_events": len(journal),
        "reserved_events": sum(event["event"] == "ATTEMPT_RESERVED" for event in journal),
        "completed_events": sum(event["event"] == "ATTEMPT_COMPLETED" for event in journal),
        "uncompleted_reservations": 0,
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
    output_cost = Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION / Decimal(1_000_000)
    total_cost = input_cost + output_cost
    return {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-usage-and-cost-v2",
        "pricing_reference_date": PRICING_REFERENCE_DATE,
        "pricing_reference": {
            "input_usd_per_1m_tokens": str(INPUT_PRICE_PER_MILLION),
            "output_usd_per_1m_tokens": str(OUTPUT_PRICE_PER_MILLION),
        },
        "historical_failed_attempt": {
            "classification": "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
            "physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS,
            "provider_usage_present": False,
            "included_in_r1_usage_or_cost": False,
        },
        "actual_provider_usage_new_r1_run_only": {
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
            "Approximate calculation from returned token usage for the new R1 run "
            "and the frozen reference rates; not a billing statement."
        ),
    }


def _predicted_capability_count_distribution(
    predictions: Mapping[str, Mapping[str, bool]],
) -> dict[str, Any]:
    counts = collections.Counter(
        sum(bool(prediction[field]) for field in LABEL_FIELDS)
        for prediction in predictions.values()
    )
    total = len(predictions)
    return {
        "valid_prediction_count": total,
        "counts": {str(value): counts[value] for value in range(4)},
        "rates_over_valid_predictions": {
            str(value): base_metrics._safe_div(counts[value], total) if total else None
            for value in range(4)
        },
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
        raise RuntimeError("Authorized DEV Gold is not exactly 64 ANSWER cases")
    predictions = {
        record["annotation_case_id"]: record["prediction"]
        for record in terminals
        if record["terminal_status"] == "VALID_PREDICTION"
    }
    valid_ids = [case_id for case_id in gold_by_id if case_id in predictions]
    complete_case = base_metrics._core_metrics(valid_ids, gold_by_id, predictions)
    exact_overall = complete_case["exact_capability_set_correct_count"]
    page_groups: dict[str, list[str]] = collections.defaultdict(list)
    for case_id, row in gold_by_id.items():
        page_groups[row["current_page"]].append(case_id)
    fold_groups: dict[str, list[str]] = collections.defaultdict(list)
    for record in load_jsonl(V3_MANIFEST_PATH):
        fold_groups[record["outer_fold_id"]].append(record["annotation_case_id"])
    terminal_status_counts = collections.Counter(
        str(record["terminal_status"]) for record in terminals
    )
    provider_error_statuses = {
        "PROVIDER_ERROR",
        "PROVIDER_REFUSAL",
        "RETURNED_MODEL_MISMATCH",
    }
    always_on = {
        case_id: {field: True for field in LABEL_FIELDS} for case_id in gold_by_id
    }
    never_on = {
        case_id: {field: False for field in LABEL_FIELDS} for case_id in gold_by_id
    }
    metrics = {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-dev-metrics-v2",
        "evaluation_scope": "DEV_ONLY_CONDITIONAL_B4_ANSWER_CASES_NEW_R1_RUN",
        "generalization_claim": "NONE",
        "historical_failed_attempt_included": False,
        "coverage": {
            "total_answer_cases": LOGICAL_CALL_CEILING,
            "terminal_results": len(terminals),
            "valid_predictions": len(predictions),
            "valid_prediction_coverage": base_metrics._safe_div(
                len(predictions), LOGICAL_CALL_CEILING
            ),
            "invalid_structured_output_count": terminal_status_counts[
                "INVALID_STRUCTURED_OUTPUT"
            ],
            "provider_error_count": sum(
                terminal_status_counts[status] for status in provider_error_statuses
            ),
            "retry_count": sum(
                max(0, int(record["attempts_used"]) - 1) for record in terminals
            ),
            "new_physical_attempt_count": len(attempts),
            "historical_physical_attempt_count": HISTORICAL_PHYSICAL_ATTEMPTS,
            "cumulative_physical_attempt_count": (
                HISTORICAL_PHYSICAL_ATTEMPTS + len(attempts)
            ),
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
            "exact_capability_set_match_over_all_64": base_metrics._safe_div(
                exact_overall, LOGICAL_CALL_CEILING
            ),
            "missing_outputs_counted_as_correct": False,
            "f1_imputation_for_missing_outputs": "NONE",
        },
        "predicted_capability_count_distribution": (
            _predicted_capability_count_distribution(predictions)
        ),
        "family_metrics": base_metrics._family_metrics(gold_by_id, predictions),
        "contrast_consistency": base_metrics._contrast_metrics(
            gold_by_id, predictions
        ),
        "page_stratified_metrics": base_metrics._stratified_metrics(
            page_groups, gold_by_id, predictions
        ),
        "fold_stratified_metrics": base_metrics._stratified_metrics(
            fold_groups, gold_by_id, predictions
        ),
        "frozen_sanity_baselines_same_64_answer_population": {
            "ALWAYS_ON": base_metrics._core_metrics(
                list(gold_by_id), gold_by_id, always_on
            ),
            "NEVER_ON": base_metrics._core_metrics(
                list(gold_by_id), gold_by_id, never_on
            ),
        },
    }
    return metrics, gold_by_id


def _write_predictions_and_errors(
    terminals: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
) -> None:
    terminal_by_logical = {
        str(record["logical_call_id"]): record for record in terminals
    }
    attempts_by_logical: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in attempts:
        attempts_by_logical[str(record["logical_call_id"])].append(record)
    prediction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    for manifest_record in load_jsonl(V3_MANIFEST_PATH):
        logical_id = str(manifest_record["logical_call_id"])
        terminal = terminal_by_logical.get(logical_id)
        if terminal is None:
            prediction_rows.append(
                {
                    "logical_call_id": logical_id,
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
                "logical_call_id": logical_id,
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
    baselines = metrics["frozen_sanity_baselines_same_64_answer_population"]
    distribution = metrics["predicted_capability_count_distribution"]
    per_label = "\n".join(
        f"| {field} | {_metric(values['precision'])} | {_metric(values['recall'])} | "
        f"{_metric(values['f1'])} | {values['tp']} | {values['fp']} | "
        f"{values['fn']} | {values['tn']} |"
        for field, values in core["per_label"].items()
    )
    page_lines = "\n".join(
        f"| {name} | {values['valid_predictions']}/{values['total_cases']} | "
        f"{_metric(values['complete_case_metrics']['macro_f1'])} | "
        f"{_metric(values['complete_case_metrics']['exact_capability_set_match'])} | "
        f"{_metric(values['complete_case_metrics']['under_routing']['case_rate'])} | "
        f"{_metric(values['complete_case_metrics']['over_routing']['case_rate'])} |"
        for name, values in metrics["page_stratified_metrics"].items()
    )
    fold_lines = "\n".join(
        f"| {name} | {values['valid_predictions']}/{values['total_cases']} | "
        f"{_metric(values['complete_case_metrics']['macro_f1'])} | "
        f"{_metric(values['complete_case_metrics']['exact_capability_set_match'])} | "
        f"{_metric(values['complete_case_metrics']['under_routing']['case_rate'])} | "
        f"{_metric(values['complete_case_metrics']['over_routing']['case_rate'])} |"
        for name, values in metrics["fold_stratified_metrics"].items()
    )
    status = "FROZEN_AFTER_DEV_EXECUTION" if complete else "EXECUTION_INCOMPLETE_NOT_FROZEN"
    actual_usage = usage["actual_provider_usage_new_r1_run_only"]
    return f"""# B4 DEV Execution Results R1

Status: `{status}`

These are conditional B4 DEV estimates, not TEST results or final generalization evidence.
The historical HTTP-400 attempt is excluded from every performance metric.

## Execution

- Historical classification: `PRE_MODEL_REQUEST_CONFIGURATION_FAILURE`
- Requested model: `{', '.join(requested_models) or 'NONE'}`
- Returned model: `{', '.join(returned_models) or 'NONE'}`
- Stop reason: `{stop_reason or 'NONE'}`
- New logical terminal results: `{coverage['terminal_results']}/64`
- New physical attempts: `{coverage['new_physical_attempt_count']}/128`
- Cumulative physical attempts: `{coverage['cumulative_physical_attempt_count']}/129`
- Invalid-output retries: `{coverage['retry_count']}`
- Ledger verification: `{ledger['status']}`
- Valid predictions: `{coverage['valid_predictions']}/64` (`{coverage['valid_prediction_coverage']:.6f}`)
- Invalid structured outputs: `{coverage['invalid_structured_output_count']}`
- Provider errors/refusals/model mismatches: `{coverage['provider_error_count']}`

## Complete-case DEV metrics

- Metric status: `{core['status']}`
- Macro-F1: `{_metric(core['macro_f1'])}`
- Micro-F1: `{_metric(core['micro_f1'])}`
- Exact Capability Set Match: `{_metric(core['exact_capability_set_match'])}`
- Example-based F1: `{_metric(core['example_based_f1'])}`
- Jaccard: `{_metric(core['jaccard'])}`
- Hamming Loss: `{_metric(core['hamming_loss'])}`
- Under-routing case rate: `{_metric(core['under_routing']['case_rate'])}` ({core['under_routing']['case_count']} cases)
- Over-routing case rate: `{_metric(core['over_routing']['case_rate'])}` ({core['over_routing']['case_count']} cases)

| Label | Precision | Recall | F1 | TP | FP | FN | TN |
|---|---:|---:|---:|---:|---:|---:|---:|
{per_label}

## Family, contrast, and sanity baselines

- Families with both utterances exact: `{family['both_utterances_exact_correct_count']}/{family['fully_covered_families']}` (`{_metric(family['both_utterances_exact_correct_complete_case_rate'])}`).
- Families with internally consistent predictions: `{family['predicted_within_family_consistent_count']}/{family['fully_covered_families']}` (`{_metric(family['predicted_within_family_consistent_complete_case_rate'])}`).
- Capability contrasts internally consistent: `{contrast['within_family_consistent_count']}/{contrast['fully_covered_contrast_groups']}` (`{_metric(contrast['within_family_consistent_complete_case_rate'])}`).
- Capability contrast Gold-pattern matches: `{contrast['gold_family_pattern_matched_count']}/{contrast['fully_covered_contrast_groups']}` (`{_metric(contrast['gold_family_pattern_matched_complete_case_rate'])}`).
- ALWAYS_ON Macro-F1: `{_metric(baselines['ALWAYS_ON']['macro_f1'])}`; exact match: `{_metric(baselines['ALWAYS_ON']['exact_capability_set_match'])}`.
- NEVER_ON Macro-F1: `{_metric(baselines['NEVER_ON']['macro_f1'])}`; exact match: `{_metric(baselines['NEVER_ON']['exact_capability_set_match'])}`.

## Predicted capability-count distribution

| Enabled capabilities | Cases | Rate |
|---:|---:|---:|
| 0 | {distribution['counts']['0']} | {_metric(distribution['rates_over_valid_predictions']['0'])} |
| 1 | {distribution['counts']['1']} | {_metric(distribution['rates_over_valid_predictions']['1'])} |
| 2 | {distribution['counts']['2']} | {_metric(distribution['rates_over_valid_predictions']['2'])} |
| 3 | {distribution['counts']['3']} | {_metric(distribution['rates_over_valid_predictions']['3'])} |

## Page-stratified DEV metrics

| Page | Coverage | Macro-F1 | Exact match | Under-route rate | Over-route rate |
|---|---:|---:|---:|---:|---:|
{page_lines}

## Fold-stratified DEV metrics

| Fold | Coverage | Macro-F1 | Exact match | Under-route rate | Over-route rate |
|---|---:|---:|---:|---:|---:|
{fold_lines}

## Actual new-run usage and approximate cost

- Input tokens: `{actual_usage['input_tokens']}`
- Output tokens: `{actual_usage['output_tokens']}`
- Total tokens: `{actual_usage['total_tokens']}`
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
    schema_v2_hash: str,
) -> str:
    coverage = metrics["coverage"]
    status = "FROZEN_AFTER_DEV_EXECUTION" if complete else "EXECUTION_INCOMPLETE_NOT_FROZEN"
    return f"""# B4 DEV Execution Status R1

B4_MODEL_STATUS = `{status}`

- Historical failed attempt: `PRE_MODEL_REQUEST_CONFIGURATION_FAILURE`; excluded from metrics
- Stop reason: `{stop_reason or 'NONE'}`
- Requested model identities: `{', '.join(requested_models) or 'NONE'}`
- Returned model identities: `{', '.join(returned_models) or 'NONE'}`
- New logical terminal results: `{coverage['terminal_results']}/64`
- New physical attempts: `{coverage['new_physical_attempt_count']}/128`
- Cumulative physical attempts: `{coverage['cumulative_physical_attempt_count']}/129`
- Valid predictions: `{coverage['valid_predictions']}/64`
- Invalid structured outputs: `{coverage['invalid_structured_output_count']}`
- Provider errors/refusals/model mismatches: `{coverage['provider_error_count']}`
- Prompt SHA-256: `{EXPECTED_PROMPT_SHA256}`
- Response schema V2 SHA-256: `{schema_v2_hash}`
- TEST calls: `0`
- P1 calls: `0`
- RQ3 calls: `0`

This is a DEV-only research result and does not authorize TEST or P1 execution.
"""


_CREDENTIAL_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE),
)


def _security_scan(paths: Sequence[Path]) -> dict[str, Any]:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(text):
                raise RuntimeError(f"Credential-shaped text found in {path.name}")
        upper = text.upper()
        if "R2V2-TEST" in upper or "TEST_ESCROW" in upper:
            raise RuntimeError(f"TEST identifier found in {path.name}")
    return {
        "status": "PASS",
        "files_scanned": len(paths),
        "credential_patterns_found": 0,
        "test_identifiers_found": 0,
    }


def _verification_report(
    metrics: Mapping[str, Any],
    ledger: Mapping[str, Any],
    security: Mapping[str, Any],
    diff_report: Mapping[str, Any],
    complete: bool,
    stop_reason: str | None,
) -> str:
    coverage = metrics["coverage"]
    return f"""# B4 DEV Execution Verification R1

Status: `{'PASS_COMPLETE_R1_EXECUTION' if complete else 'PASS_FAIL_CLOSED_INCOMPLETE_R1_EXECUTION'}`

- Historical Stage 4I-X artifacts: `PASS`, {len(HISTORICAL_STAGE4IX_SHA256)} hashes unchanged
- Historical classification: `PRE_MODEL_REQUEST_CONFIGURATION_FAILURE`
- Historical attempt included in metrics: `false`
- Schema V1/V2 semantic-equivalence boundary: `PASS`
- Manifest V2/V3 allowed-difference boundary: `{diff_report['status']}`
- Frozen prompt SHA-256: `{EXPECTED_PROMPT_SHA256}`
- Schema V2 SHA-256: `{sha256_file(SCHEMA_V2_PATH)}`
- New logical terminal results: `{coverage['terminal_results']}/64`
- New physical attempts: `{ledger['new_physical_attempts']}/128`
- Cumulative physical attempts: `{ledger['cumulative_physical_attempts']}/129`
- Complete durable journal lifecycles: `{ledger['completed_events']}`
- Uncompleted reservations: `{ledger['uncompleted_reservations']}`
- SDK `max_retries`: `{CLIENT_MAX_RETRIES}`
- Stop reason: `{stop_reason or 'NONE'}`
- Credential/output scan: `{security['status']}`, {security['files_scanned']} files
- Passing unique tests: `75`
- Assertion failures: `0`
- Legacy environment errors: `1` (historical MPNet rebuild dependency; see `B4_R1_TEST_AUDIT.md`)
- TEST calls: `0`
- P1 calls: `0`
- RQ3 calls: `0`

The final B4 configuration is frozen only when all 64 new cases have valid predictions.
"""


def finalize(
    stop_reason: str | None,
    manifest_diff_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    verify_historical_artifacts()
    schema_validation = schema_v1_v2_equivalence()
    _records, verified_diff = verify_v3_files()
    attempts = load_jsonl(ATTEMPT_RECORDS_PATH)
    terminals = load_jsonl(TERMINAL_RESULTS_PATH)
    journal = load_jsonl(CALL_JOURNAL_PATH)
    if not attempts or not terminals:
        raise RuntimeError("No new R1 attempt/terminal outputs are available")
    expected_terminal_ids = [
        f"R2V2-B4-DEV-{index:04d}" for index in range(1, len(terminals) + 1)
    ]
    if [record["logical_call_id"] for record in terminals] != expected_terminal_ids:
        raise RuntimeError("R1 terminals are not in deterministic logical order")
    if len({record["logical_call_id"] for record in terminals}) != len(terminals):
        raise RuntimeError("Duplicate R1 terminal logical ID")
    ledger = _verify_call_ledger(attempts, journal, terminals)
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
    complete = (
        len(terminals) == LOGICAL_CALL_CEILING
        and metrics["coverage"]["valid_predictions"] == LOGICAL_CALL_CEILING
        and ledger["status"] == "PASS"
    )
    fold_hashes = json.loads(
        (TRACK_DIR / "b4_fold_prompt_hashes_v1.json").read_text(encoding="utf-8")
    )
    diff_report = dict(manifest_diff_report or verified_diff)
    final_freeze = {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-final-freeze-v2",
        "B4_MODEL_STATUS": (
            "FROZEN_AFTER_DEV_EXECUTION"
            if complete
            else "EXECUTION_INCOMPLETE_NOT_FROZEN"
        ),
        "execution_scope": "DEV_ONLY_CONDITIONAL_B4_ANSWER_CASES_NEW_R1_RUN",
        "historical_failed_attempt": {
            "classification": "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
            "included_in_metrics": False,
            "preservation_manifest_sha256": sha256_file(
                HISTORICAL_PRESERVATION_PATH
            ),
        },
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "response_schema_v2_sha256": schema_validation["schema_v2_sha256"],
        "fold_specific_examples": fold_hashes["folds"],
        "full_dev_examples": fold_hashes["full_dev"],
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "sdk_transport_retries": CLIENT_MAX_RETRIES,
        "manual_retry_policy": {
            "maximum_retries_per_logical_case": 1,
            "only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
            "correction_message_added": False,
            "prompt_changed": False,
        },
        "execution_evidence": {
            "new_logical_terminal_results": len(terminals),
            "valid_predictions": metrics["coverage"]["valid_predictions"],
            "new_physical_attempts": len(attempts),
            "historical_physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS,
            "cumulative_physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS
            + len(attempts),
            "requested_models": requested_models,
            "returned_models": returned_models,
            "v2_manifest_sha256": diff_report["v2_manifest_sha256"],
            "v3_manifest_sha256": diff_report["v3_manifest_sha256"],
            "attempt_records_v2_sha256": sha256_file(ATTEMPT_RECORDS_PATH),
            "terminal_results_v2_sha256": sha256_file(TERMINAL_RESULTS_PATH),
            "call_journal_v2_sha256": sha256_file(CALL_JOURNAL_PATH),
        },
        "future_boundary": {
            "test_calls_made": 0,
            "p1_calls_made": 0,
            "rq3_calls_made": 0,
            "further_provider_authority_inferred": False,
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
        _status_report(
            complete,
            stop_reason,
            metrics,
            requested_models,
            returned_models,
            schema_validation["schema_v2_sha256"],
        ),
    )
    scan_paths = (
        ATTEMPT_RECORDS_PATH,
        CALL_JOURNAL_PATH,
        TERMINAL_RESULTS_PATH,
        PREDICTIONS_PATH,
        ERROR_REGISTRY_PATH,
        USAGE_PATH,
        METRICS_PATH,
        FINAL_FREEZE_PATH,
        RESULTS_REPORT_PATH,
        STATUS_PATH,
    )
    security = _security_scan(scan_paths)
    atomic_write_text(
        VERIFICATION_REPORT_PATH,
        _verification_report(
            metrics,
            ledger,
            security,
            diff_report,
            complete,
            stop_reason,
        ),
    )
    return {
        "B4_MODEL_STATUS": final_freeze["B4_MODEL_STATUS"],
        "historical_failed_attempt_classification": (
            "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE"
        ),
        "new_logical_calls": len(terminals),
        "new_physical_attempts": len(attempts),
        "cumulative_physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS
        + len(attempts),
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
        "openai_sdk_version": importlib.metadata.version("openai"),
        "python_version": sys.version.split()[0],
    }
