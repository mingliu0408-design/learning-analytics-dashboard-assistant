"""Cryptographically bind a core prediction to its exact feature record."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, METHODS, PREDICTOR_CONTRACT_ID, canonical_json_bytes


BOUND_DOMAIN = b"RQ2_TRACK_B_BOUND_PREDICTION_V1_1\x00"


def bound_prediction_hash_v1_1(row: Mapping[str, Any]) -> str:
    payload = {
        "review_case_id": str(row["review_case_id"]),
        "feature_record_fingerprint": str(row["feature_record_fingerprint"]),
        "method_id": str(row["method_id"]),
        "context_resolution_required_prediction": bool(
            row["context_resolution_required_prediction"]
        ),
        "predicted_capabilities": sorted(
            set(str(value) for value in row["predicted_capabilities"]),
            key=lambda value: value.encode("utf-8"),
        ),
        "core_prediction_trace_hash": str(row["core_prediction_trace_hash"]),
        "predictor_contract_id": str(row["predictor_contract_id"]),
    }
    return hashlib.sha256(
        BOUND_DOMAIN + canonical_json_bytes(payload).rstrip(b"\n")
    ).hexdigest()


def bind_prediction_v1_1(
    feature_row: Mapping[str, Any], method_id: str, core_prediction: Mapping[str, Any]
) -> dict[str, Any]:
    capabilities = [name for name in CAPABILITIES if name in set(core_prediction["predicted_capabilities"])]
    if method_id not in METHODS or not capabilities:
        raise ValueError("invalid core prediction")
    if "clarification" in capabilities and len(capabilities) != 1:
        raise ValueError("clarification exclusivity violation")
    if "safe_direct_response" in capabilities and len(capabilities) != 1:
        raise ValueError("safe-direct exclusivity violation")
    row = {
        "review_case_id": str(feature_row["review_case_id"]),
        "feature_content_fingerprint": str(feature_row["feature_content_fingerprint"]),
        "feature_record_fingerprint": str(feature_row["feature_record_fingerprint"]),
        "method_id": method_id,
        "context_resolution_required_prediction": bool(
            core_prediction["context_resolution_required_prediction"]
        ),
        "predicted_capabilities": capabilities,
        "core_prediction_trace_hash": str(core_prediction["core_prediction_trace_hash"]),
        "bound_prediction_hash": "",
        "predictor_contract_id": PREDICTOR_CONTRACT_ID,
    }
    row["bound_prediction_hash"] = bound_prediction_hash_v1_1(row)
    return row


def validate_bound_prediction_v1_1(
    row: Mapping[str, Any], feature_row: Mapping[str, Any]
) -> None:
    if row.get("review_case_id") != feature_row.get("review_case_id"):
        raise ValueError("prediction case binding mismatch")
    for name in ("feature_content_fingerprint", "feature_record_fingerprint"):
        if row.get(name) != feature_row.get(name):
            raise ValueError("prediction feature binding mismatch")
    if row.get("predictor_contract_id") != PREDICTOR_CONTRACT_ID:
        raise ValueError("predictor contract mismatch")
    if row.get("bound_prediction_hash") != bound_prediction_hash_v1_1(row):
        raise ValueError("bound prediction hash mismatch")


def validate_prediction_set_v1_1(
    rows: Sequence[Mapping[str, Any]], features: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    feature_by_id = {str(row["review_case_id"]): row for row in features}
    if len(feature_by_id) != len(features):
        raise ValueError("duplicate feature case")
    seen: set[tuple[str, str]] = set()
    by_method = {method: 0 for method in METHODS}
    for row in rows:
        key = (str(row["method_id"]), str(row["review_case_id"]))
        if key in seen or key[0] not in METHODS or key[1] not in feature_by_id:
            raise ValueError("prediction identity mismatch")
        seen.add(key)
        validate_bound_prediction_v1_1(row, feature_by_id[key[1]])
        by_method[key[0]] += 1
    required = {(method, case_id) for method in METHODS for case_id in feature_by_id}
    if seen != required:
        raise ValueError("prediction coverage mismatch")
    return {"total": len(rows), **by_method}


def bound_prediction_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-bound-prediction-contract-v1-1",
        "status": "FROZEN",
        "domain": "RQ2_TRACK_B_BOUND_PREDICTION_V1_1",
        "predictor_contract_id": PREDICTOR_CONTRACT_ID,
        "predictions_per_method": 48,
        "total_predictions": 144,
        "review_case_id_used_by_core": False,
        "case_and_feature_binding_required": True,
        "clarification_exclusive": True,
        "safe_direct_response_exclusive": True,
    }
