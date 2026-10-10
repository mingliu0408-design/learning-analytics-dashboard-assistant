"""Small shared helpers for B2/B3 batching, predictions, and state files."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any

from evaluation.capability_routing_rq2_v2_stage0 import CAPABILITY_FIELDS
from evaluation.capability_routing_rq2_v2_stage0.contracts import validate_prediction

from .canonical_text import (
    PRIMARY_FEATURE_PROFILE,
    SERIALIZER_VERSION,
    serialize_canonical_batch,
)
from .embeddings import EmbeddingAdapter, adapter_signature, validated_encode
from .errors import CanonicalInputError, ModelStateError


CAPABILITIES = tuple(CAPABILITY_FIELDS)


def coerce_case_batch(
    cases: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], bool]:
    if isinstance(cases, Mapping):
        return [cases], True
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise CanonicalInputError("cases must be one mapping or a sequence of mappings")
    if not cases:
        raise CanonicalInputError("cases must not be empty")
    if any(not isinstance(case, Mapping) for case in cases):
        raise CanonicalInputError("every case must be a mapping")
    return list(cases), False


def encode_case_batch(
    adapter: EmbeddingAdapter,
    cases: Sequence[Mapping[str, Any]],
):
    texts = serialize_canonical_batch(cases)
    return validated_encode(adapter, texts)


def validate_thresholds(
    thresholds: Mapping[str, float] | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> dict[str, float]:
    raw = dict(thresholds or {})
    unknown = sorted(set(raw) - set(CAPABILITIES))
    if unknown:
        raise ValueError("unknown threshold labels: " + ", ".join(unknown))
    result: dict[str, float] = {}
    for label in CAPABILITIES:
        value = float(raw.get(label, default))
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(
                f"threshold for {label} must be finite and in [{minimum}, {maximum}]"
            )
        result[label] = value
    return result


def prediction_record(
    *,
    case: Mapping[str, Any],
    model_id: str,
    decisions: Mapping[str, bool],
    values: Mapping[str, float],
    thresholds: Mapping[str, float],
    value_kind: str,
) -> dict[str, Any]:
    case_id = str(case.get("case_id", "")).strip()
    if not case_id:
        raise CanonicalInputError("prediction cases require a non-empty case_id")
    prediction = {
        "schema_version": "rq2-v2-prediction-v1",
        "case_id": case_id,
        "model_id": model_id,
        "dialogue_action": "ANSWER",
        **{label: bool(decisions[label]) for label in CAPABILITIES},
        "metadata": {
            "execution_mode": "STAGE1_TRACK_C_LOCAL",
            "provider_call_count": 0,
            "network_access": False,
            "training_performed": False,
            "serializer_version": SERIALIZER_VERSION,
            "primary_feature_profile": PRIMARY_FEATURE_PROFILE,
            value_kind: {label: float(values[label]) for label in CAPABILITIES},
            "thresholds": {label: float(thresholds[label]) for label in CAPABILITIES},
        },
    }
    validate_prediction(prediction)
    return prediction


def state_header(adapter: EmbeddingAdapter, *, model_id: str) -> dict[str, Any]:
    embedding_model_id, dimension = adapter_signature(adapter)
    return {
        "model_id": model_id,
        "serializer_version": SERIALIZER_VERSION,
        "primary_feature_profile": PRIMARY_FEATURE_PROFILE,
        "embedding_model_id": embedding_model_id,
        "embedding_dimension": dimension,
    }


def validate_state_header(
    state: Mapping[str, Any],
    adapter: EmbeddingAdapter,
    *,
    expected_model_id: str,
) -> int:
    expected_embedding_id, expected_dimension = adapter_signature(adapter)
    if state.get("model_id") != expected_model_id:
        raise ModelStateError("saved model_id is incompatible")
    if state.get("serializer_version") != SERIALIZER_VERSION:
        raise ModelStateError("saved serializer version is incompatible")
    if state.get("primary_feature_profile") != PRIMARY_FEATURE_PROFILE:
        raise ModelStateError("saved primary feature profile is incompatible")
    if state.get("embedding_model_id") != expected_embedding_id:
        raise ModelStateError("saved embedding model identity is incompatible")
    try:
        dimension = int(state.get("embedding_dimension"))
    except (TypeError, ValueError) as exc:
        raise ModelStateError("saved embedding dimension is invalid") from exc
    if dimension != expected_dimension:
        raise ModelStateError("saved embedding dimension is incompatible")
    return dimension


def save_json_state(path: str | Path, state: Mapping[str, Any]) -> None:
    target = Path(path)
    if target.exists() and not target.is_file():
        raise ModelStateError(f"state path is not a regular file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        dict(state), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    target.write_text(payload, encoding="utf-8")


def load_json_state(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelStateError(f"model state is unavailable: {source}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelStateError(f"unable to read model state: {source}") from exc
    if not isinstance(value, dict):
        raise ModelStateError("model state must be a JSON object")
    return value
