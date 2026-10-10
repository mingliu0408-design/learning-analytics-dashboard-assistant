"""Phase C: isolated Gold join, aggregate scoring, and frozen statistics."""

from __future__ import annotations

import csv
from io import StringIO
import json
import os
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    attach_gold_for_metrics,
)
from evaluation.capability_routing_rq2d3_r3_v1.fixed_statistical_execution_v1_1 import (
    run_fixed_track_b_statistics_v1_1,
)
from evaluation.capability_routing_rq2d3_r3_v1.frozen_complete_metric_binding_v1_1 import (
    load_frozen_complete_track_b_metric_binding_v1_1,
)

from . import (
    CAPABILITIES,
    COMPARISONS,
    GROUPING_RELATIVE,
    GROUPING_SHA256,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    LOCAL_RESULTS_RELATIVE,
    METHODS,
    PREDICTION_RELATIVES,
    ROOT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    capability_order,
    jsonl_rows_from_bytes,
    sha256_bytes,
    write_new,
    yes,
)
from .error_analysis import build_error_analysis
from .run_capability_predictions import validate_prediction_row


LOCAL_RESULT_NAMES = {
    "metrics": "rq2d4_method_metrics_v1.json",
    "comparisons": "rq2d4_pairwise_comparisons_v1.json",
    "per_capability": "rq2d4_per_capability_metrics_v1.csv",
    "context": "rq2d4_context_subset_results_v1.json",
    "errors": "rq2d4_error_analysis_v1.json",
    "per_case": "rq2d4_per_case_scoring_v1.jsonl",
}


def _load_predictions() -> tuple[
    dict[str, list[dict[str, Any]]], dict[str, Mapping[str, frozenset[str]]], dict[str, Any]
]:
    rows_by_method: dict[str, list[dict[str, Any]]] = {}
    predictions_by_method: dict[str, Mapping[str, frozenset[str]]] = {}
    identities: dict[str, Any] = {}
    expected_ids: set[str] | None = None
    for method in METHODS:
        relative = PREDICTION_RELATIVES[method]
        payload = (ROOT / relative).read_bytes()
        rows = jsonl_rows_from_bytes(payload)
        for row in rows:
            validate_prediction_row(row, method)
        ids = {str(row["review_case_id"]) for row in rows}
        if len(rows) != 48 or len(ids) != 48 or (expected_ids is not None and ids != expected_ids):
            raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
        expected_ids = ids
        rows_by_method[method] = rows
        predictions_by_method[method] = {
            str(row["review_case_id"]): frozenset(row["predicted_capabilities"])
            for row in rows
        }
        identities[method] = {
            "relative_path": str(relative),
            "sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
            "record_count": 48,
        }
    return rows_by_method, predictions_by_method, identities


def _load_labels() -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]], dict[str, Any]]:
    payload = (ROOT / LABEL_GOLD_RELATIVE).read_bytes()
    if sha256_bytes(payload) != LABEL_GOLD_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    rows = jsonl_rows_from_bytes(payload)
    labels: dict[str, dict[str, Any]] = {}
    gold_sets: dict[str, frozenset[str]] = {}
    for row in rows:
        case_id = str(row["review_case_id"])
        selected = frozenset(name for name in CAPABILITIES if yes(row[name]))
        labels[case_id] = {
            "gold_capabilities": capability_order(selected),
            "forbidden_capabilities": capability_order(row["forbidden_capabilities"]),
            "context_resolution_required": yes(row["context_resolution_required"]),
        }
        gold_sets[case_id] = selected
    if len(rows) != 48 or len(labels) != 48:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    return labels, gold_sets, {
        "relative_path": str(LABEL_GOLD_RELATIVE),
        "sha256": LABEL_GOLD_SHA256,
        "size_bytes": len(payload),
        "record_count": 48,
        "open_count": 1,
    }


def _load_groups() -> tuple[tuple[tuple[str, tuple[str, str]], ...], dict[str, Any]]:
    payload = (ROOT / GROUPING_RELATIVE).read_bytes()
    if sha256_bytes(payload) != GROUPING_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    rows = jsonl_rows_from_bytes(payload)
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["contrast_group_id"]), []).append(
            str(row["review_case_id"])
        )
    ordered = tuple(
        (
            group_id,
            tuple(sorted(case_ids, key=lambda value: value.encode("utf-8"))),
        )
        for group_id, case_ids in sorted(
            grouped.items(), key=lambda item: item[0].encode("utf-8")
        )
    )
    if len(rows) != 48 or len(ordered) != 24 or any(len(cases) != 2 for _, cases in ordered):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    return ordered, {
        "relative_path": str(GROUPING_RELATIVE),
        "sha256": GROUPING_SHA256,
        "size_bytes": len(payload),
        "record_count": 48,
        "group_count": 24,
        "cases_per_group": 2,
        "open_count": 1,
    }


def _per_capability_csv(method_metrics: Mapping[str, Mapping[str, Any]]) -> bytes:
    handle = StringIO(newline="")
    fields = (
        "method_id",
        "capability",
        "tp",
        "fp",
        "fn",
        "tn",
        "support",
        "precision",
        "recall",
        "f1",
    )
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for method in METHODS:
        for capability in CAPABILITIES:
            values = method_metrics[method]["per_capability"][capability]
            writer.writerow(
                {
                    "method_id": method,
                    "capability": capability,
                    **{name: values[name] for name in fields[2:]},
                }
            )
    return handle.getvalue().encode("utf-8")


def _per_case_rows(rows_by_method: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for method in METHODS:
        for row in rows_by_method[method]:
            gold = set(row["gold_capabilities"])
            predicted = set(row["predicted_capabilities"])
            union = gold | predicted
            output.append(
                {
                    "review_case_id": row["review_case_id"],
                    "method_id": method,
                    "gold_capabilities": capability_order(gold),
                    "predicted_capabilities": capability_order(predicted),
                    "gold_context_resolution_required": bool(
                        row["gold_context_resolution_required"]
                    ),
                    "predicted_context_resolution_required": bool(
                        row["predicted_context_resolution_required"]
                    ),
                    "exact_set_correct": gold == predicted,
                    "set_jaccard": len(gold & predicted) / len(union) if union else 1.0,
                    "missing_capability_count": len(gold - predicted),
                    "unnecessary_capability_count": len(predicted - gold),
                }
            )
    return output


def score_predictions() -> dict[str, Any]:
    prediction_rows, predictions_by_method, prediction_identities = _load_predictions()
    labels_by_id, gold_by_id, label_identity = _load_labels()
    ordered_groups, grouping_identity = _load_groups()
    case_ids = {case_id for _, cases in ordered_groups for case_id in cases}
    if (
        set(labels_by_id) != case_ids
        or any(set(predictions_by_method[method]) != case_ids for method in METHODS)
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")

    metric_rows = {
        method: attach_gold_for_metrics(prediction_rows[method], labels_by_id)
        for method in METHODS
    }
    binding = load_frozen_complete_track_b_metric_binding_v1_1()
    method_metrics = {method: binding.evaluate(metric_rows[method]) for method in METHODS}
    comparisons = run_fixed_track_b_statistics_v1_1(
        ordered_groups=ordered_groups,
        predictions_by_method=predictions_by_method,
        gold_by_id=gold_by_id,
        method_metrics=method_metrics,
    )
    if set(comparisons.get("comparisons", {})) != set(COMPARISONS):
        raise RuntimeError("BLOCKED_RQ2_D4_METRIC_OR_STATISTICAL_FAILURE")
    errors = build_error_analysis(
        metric_rows, ordered_groups, predictions_by_method, gold_by_id
    )
    context_results = errors["context_subsets"]
    metrics_document = {
        "schema_version": "rq2d4-method-metrics-v1",
        "status": "FROZEN_LOCAL_RESULT",
        "methods": method_metrics,
        "record_count_per_method": 48,
        "method_count": 3,
        "metric_implementation_sha256": binding.implementation_sha256,
    }
    comparison_document = {
        "schema_version": "rq2d4-pairwise-comparisons-v1",
        "status": "FROZEN_LOCAL_RESULT",
        **comparisons,
    }
    per_case = _per_case_rows(metric_rows)
    documents: dict[str, bytes] = {
        "metrics": canonical_json_bytes(metrics_document),
        "comparisons": canonical_json_bytes(comparison_document),
        "per_capability": _per_capability_csv(method_metrics),
        "context": canonical_json_bytes(context_results),
        "errors": canonical_json_bytes(errors),
        "per_case": canonical_jsonl_bytes(per_case),
    }
    output_receipts: dict[str, Any] = {}
    for role, payload in documents.items():
        relative = LOCAL_RESULTS_RELATIVE / LOCAL_RESULT_NAMES[role]
        digest = write_new(ROOT / relative, payload)
        output_receipts[role] = {
            "relative_path": str(relative),
            "sha256": digest,
            "size_bytes": len(payload),
        }

    return {
        "phase": "C_GOLD_SCORING_AND_STATISTICS",
        "status": "PASS",
        "process_id": os.getpid(),
        "prediction_file_open_count": 3,
        "label_gold_open_count": 1,
        "grouping_open_count": 1,
        "combined_source_open_count": 0,
        "records_per_method": 48,
        "method_count": 3,
        "comparison_count": 3,
        "bootstrap_resamples_per_comparison": 50000,
        "sign_flip_draws_per_comparison": 100000,
        "label_identity": label_identity,
        "grouping_identity": grouping_identity,
        "prediction_identities": prediction_identities,
        "local_results": output_receipts,
        "per_case_scoring_record_count": len(per_case),
        "provider_calls": 0,
        "network_access": False,
    }


def main() -> int:
    print(json.dumps(score_predictions(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
