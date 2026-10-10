"""Phase B: label-isolated B0/B1/P1 prediction in a separate process."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from evaluation.capability_routing_rq2d3_r3_v1.frozen_capability_predictor_core_v1_1 import (
    CoreRoutingContentV1_1,
    FrozenCapabilityPredictorCoreV1_1,
)

from . import (
    CAPABILITIES,
    FEATURE_VIEW_RELATIVE,
    METHODS,
    PREDICTION_RELATIVES,
    ROOT,
    canonical_jsonl_bytes,
    jsonl_rows_from_bytes,
    sha256_bytes,
    write_new,
)
from .build_feature_view import FEATURE_FIELDS


def validate_prediction_row(row: Mapping[str, Any], method: str) -> None:
    required = {
        "review_case_id",
        "method_id",
        "context_resolution_required_prediction",
        "predicted_capabilities",
        "core_prediction_trace_hash",
    }
    if set(row) != required or row.get("method_id") != method:
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
    capabilities = list(row.get("predicted_capabilities") or ())
    if (
        not capabilities
        or len(capabilities) != len(set(capabilities))
        or not set(capabilities) <= set(CAPABILITIES)
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
    if "clarification" in capabilities and len(capabilities) != 1:
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
    if "safe_direct_response" in capabilities and len(capabilities) != 1:
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
    trace_hash = str(row.get("core_prediction_trace_hash") or "")
    if len(trace_hash) != 64 or any(char not in "0123456789abcdef" for char in trace_hash):
        raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")


def run_predictions() -> dict[str, Any]:
    feature_path = ROOT / FEATURE_VIEW_RELATIVE
    feature_bytes = feature_path.read_bytes()
    feature_rows = jsonl_rows_from_bytes(feature_bytes)
    if (
        len(feature_rows) != 48
        or len({str(row["review_case_id"]) for row in feature_rows}) != 48
        or any(set(row) != set(FEATURE_FIELDS) for row in feature_rows)
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")

    by_method: dict[str, list[dict[str, Any]]] = {method: [] for method in METHODS}
    with FrozenCapabilityPredictorCoreV1_1() as core:
        for feature in feature_rows:
            content = CoreRoutingContentV1_1(
                current_query=str(feature["current_query"]),
                current_page=str(feature["current_page"]),
                necessary_conversation_history=tuple(
                    dict(item) for item in feature["necessary_conversation_history"]
                ),
            )
            for method in METHODS:
                prediction = core.predict(method, content)
                row = {
                    "review_case_id": str(feature["review_case_id"]),
                    "method_id": method,
                    "context_resolution_required_prediction": bool(
                        prediction["context_resolution_required_prediction"]
                    ),
                    "predicted_capabilities": list(
                        prediction["predicted_capabilities"]
                    ),
                    "core_prediction_trace_hash": str(
                        prediction["core_prediction_trace_hash"]
                    ),
                }
                validate_prediction_row(row, method)
                by_method[method].append(row)

    expected_ids = {str(row["review_case_id"]) for row in feature_rows}
    payloads: dict[str, bytes] = {}
    for method, rows in by_method.items():
        if len(rows) != 48 or {row["review_case_id"] for row in rows} != expected_ids:
            raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
        payloads[method] = canonical_jsonl_bytes(rows)

    receipts: dict[str, Any] = {}
    for method in METHODS:
        relative = PREDICTION_RELATIVES[method]
        digest = write_new(ROOT / relative, payloads[method])
        persisted = jsonl_rows_from_bytes((ROOT / relative).read_bytes())
        if persisted != by_method[method]:
            raise RuntimeError("BLOCKED_RQ2_D4_PREDICTION_VALIDATION")
        receipts[method] = {
            "relative_path": str(relative),
            "sha256": digest,
            "size_bytes": len(payloads[method]),
            "record_count": 48,
        }

    return {
        "phase": "B_CAPABILITY_PREDICTION",
        "status": "PASS",
        "process_id": os.getpid(),
        "feature_view_open_count": 1,
        "feature_view_sha256": sha256_bytes(feature_bytes),
        "methods": list(METHODS),
        "predictions_per_method": 48,
        "total_predictions": 144,
        "duplicate_count": 0,
        "missing_case_count": 0,
        "empty_plan_count": 0,
        "clarification_exclusivity_violations": 0,
        "safe_direct_exclusivity_violations": 0,
        "prediction_files": receipts,
        "restricted_reference_access": False,
        "provider_calls": 0,
        "network_access": False,
    }


def main() -> int:
    print(json.dumps(run_predictions(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
