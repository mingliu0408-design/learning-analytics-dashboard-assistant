"""Schema and safety validation for B0/B1/P1 persisted predictions."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from . import CAPABILITIES, METHOD_IDS


PREDICTION_FIELDS = (
    "review_case_id",
    "method_id",
    "context_resolution_required_prediction",
    "predicted_capabilities",
    "prediction_trace_hash",
)


def prediction_trace_hash_v1(payload: Mapping[str, Any]) -> str:
    safe = {
        "method_id": str(payload["method_id"]),
        "context_resolution_required_prediction": bool(payload["context_resolution_required_prediction"]),
        "predicted_capabilities": sorted(payload["predicted_capabilities"]),
    }
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_prediction_rows_v1(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    material = list(rows)
    if len(material) != 144:
        raise ValueError("prediction contract requires 144 rows")
    seen: set[tuple[str, str]] = set()
    counts = {method: 0 for method in METHOD_IDS}
    capability_set = set(CAPABILITIES)
    for row in material:
        if set(row) != set(PREDICTION_FIELDS):
            raise ValueError("prediction schema mismatch")
        method = str(row["method_id"])
        case_id = str(row["review_case_id"])
        key = (method, case_id)
        capabilities = set(row["predicted_capabilities"])
        if method not in METHOD_IDS or key in seen or not case_id:
            raise ValueError("prediction identity mismatch")
        if not capabilities or not capabilities <= capability_set:
            raise ValueError("prediction capability set invalid")
        if "clarification" in capabilities and capabilities != {"clarification"}:
            raise ValueError("clarification must be exclusive")
        if "safe_direct_response" in capabilities and capabilities != {"safe_direct_response"}:
            raise ValueError("safe-direct must be exclusive")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row["prediction_trace_hash"])):
            raise ValueError("prediction trace hash invalid")
        expected_hash = prediction_trace_hash_v1(row)
        if row["prediction_trace_hash"] != expected_hash:
            raise ValueError("prediction trace hash mismatch")
        seen.add(key)
        counts[method] += 1
    if counts != {"B0": 48, "B1": 48, "P1": 48}:
        raise ValueError("prediction method counts mismatch")
    case_sets = {method: {case_id for observed_method, case_id in seen if observed_method == method} for method in METHOD_IDS}
    if not (case_sets["B0"] == case_sets["B1"] == case_sets["P1"]):
        raise ValueError("prediction method coverage mismatch")
    return {
        "status": "PASS",
        "prediction_count": 144,
        "prediction_count_by_method": counts,
        "unique_case_count": 48,
        "missing_id_count": 0,
        "duplicate_method_case_count": 0,
        "empty_capability_plan_count": 0,
        "clarification_exclusivity_violation_count": 0,
        "safe_direct_exclusivity_violation_count": 0,
    }


def prediction_contract_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-prediction-contract-v1",
        "status": "FROZEN",
        "fields": list(PREDICTION_FIELDS),
        "methods": list(METHOD_IDS),
        "predictions_per_method": 48,
        "total_predictions": 144,
        "capability_universe": list(CAPABILITIES),
        "capability_set_nonempty": True,
        "clarification_exclusive": True,
        "safe_direct_response_exclusive": True,
        "tracked_per_case_predictions": False,
        "prediction_ledgers_local_only": True,
    }
