"""Minimal R2V2-P1_HYBRID fallback-policy skeleton."""

from __future__ import annotations

import math
from typing import Any, Mapping, Protocol

from evaluation.capability_routing_rq2_v2_stage0 import CAPABILITY_FIELDS
from evaluation.capability_routing_rq2_v2_stage0.interfaces import RouterPrediction

from .b4 import PRIMARY_SEMANTIC_INPUT_PROFILE, extract_primary_semantic_input


class HybridRoutingError(RuntimeError):
    """Raised when fallback accounting cannot be made canonical."""


class B4FallbackInterface(Protocol):
    @property
    def provider_call_count(self) -> int: ...

    def predict(
        self, *, case_id: str, model_input: Mapping[str, Any]
    ) -> RouterPrediction: ...


def _validate_number_mapping(
    name: str,
    values: Any,
) -> tuple[dict[str, float] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(values, Mapping):
        return None, [f"{name}_NOT_MAPPING"]
    expected = set(CAPABILITY_FIELDS)
    observed = set(values)
    if expected - observed:
        errors.append(f"{name}_MISSING_CAPABILITY")
    if observed - expected:
        errors.append(f"{name}_UNKNOWN_CAPABILITY")
    result: dict[str, float] = {}
    for field in CAPABILITY_FIELDS:
        if field not in values:
            continue
        raw_value = values[field]
        if type(raw_value) not in (int, float):
            errors.append(f"{name}_{field}_INVALID_TYPE")
            continue
        numeric = float(raw_value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            errors.append(f"{name}_{field}_OUT_OF_RANGE")
            continue
        result[field] = numeric
    return (result if not errors else None), errors


def _validate_disagreement_flags(
    values: Any,
) -> tuple[dict[str, bool] | None, list[str]]:
    if values is None:
        return {field: False for field in CAPABILITY_FIELDS}, []
    if not isinstance(values, Mapping):
        return None, ["SECONDARY_DISAGREEMENT_NOT_MAPPING"]
    unknown = set(values) - set(CAPABILITY_FIELDS)
    errors = ["SECONDARY_DISAGREEMENT_UNKNOWN_CAPABILITY"] if unknown else []
    result = {field: False for field in CAPABILITY_FIELDS}
    for field, value in values.items():
        if field not in result:
            continue
        if type(value) is not bool:
            errors.append(f"SECONDARY_DISAGREEMENT_{field}_INVALID_TYPE")
        else:
            result[field] = value
    return (result if not errors else None), errors


class P1HybridRouter:
    """Use a confident base route and delegate uncertain states to offline B4."""

    model_id = "R2V2-P1_HYBRID"

    def __init__(
        self,
        b4_fallback: B4FallbackInterface,
        *,
        base_prediction_source: str = "R2V2-B3_OVR",
    ) -> None:
        if not isinstance(base_prediction_source, str) or not base_prediction_source:
            raise ValueError("base_prediction_source must be non-empty")
        self._b4_fallback = b4_fallback
        self._base_prediction_source = base_prediction_source

    def predict(
        self,
        *,
        case_id: str,
        model_input: Mapping[str, Any],
        base_probabilities: Mapping[str, float],
        thresholds: Mapping[str, float],
        uncertainty_margins: Mapping[str, float] | None = None,
        secondary_disagreement_flags: Mapping[str, bool] | None = None,
        low_confidence_or_ood: bool = False,
    ) -> RouterPrediction:
        semantic_input = extract_primary_semantic_input(model_input)
        probabilities, probability_errors = _validate_number_mapping(
            "BASE_PROBABILITIES", base_probabilities
        )
        threshold_values, threshold_errors = _validate_number_mapping(
            "THRESHOLDS", thresholds
        )
        if uncertainty_margins is None:
            margin_values = {field: 0.0 for field in CAPABILITY_FIELDS}
            margin_errors: list[str] = []
        else:
            margin_values, margin_errors = _validate_number_mapping(
                "UNCERTAINTY_MARGINS", uncertainty_margins
            )
        disagreement_flags, disagreement_errors = _validate_disagreement_flags(
            secondary_disagreement_flags
        )
        low_flag_valid = type(low_confidence_or_ood) is bool
        low_flag_errors = [] if low_flag_valid else ["LOW_CONFIDENCE_OR_OOD_INVALID_TYPE"]
        intermediate_errors = [
            *probability_errors,
            *threshold_errors,
            *margin_errors,
            *disagreement_errors,
            *low_flag_errors,
        ]

        base_prediction: dict[str, bool] | None = None
        fallback_reasons: list[str] = []
        if probabilities is not None and threshold_values is not None:
            base_prediction = {
                field: probabilities[field] >= threshold_values[field]
                for field in CAPABILITY_FIELDS
            }
        if intermediate_errors:
            fallback_reasons.append("INVALID_OR_CONFLICTING_INTERMEDIATE_STATE")
        if (
            probabilities is not None
            and threshold_values is not None
            and margin_values is not None
        ):
            for field in CAPABILITY_FIELDS:
                if abs(probabilities[field] - threshold_values[field]) < margin_values[field]:
                    fallback_reasons.append(f"THRESHOLD_MARGIN:{field}")
        if disagreement_flags is not None:
            for field in CAPABILITY_FIELDS:
                if disagreement_flags[field]:
                    fallback_reasons.append(f"SECONDARY_DISAGREEMENT:{field}")
        if low_flag_valid and low_confidence_or_ood:
            fallback_reasons.append("LOW_CONFIDENCE_OR_OOD")

        common_metadata = {
            "base_probabilities": probabilities,
            "thresholds": threshold_values,
            "uncertainty_margins": margin_values,
            "secondary_disagreement_flags": disagreement_flags,
            "low_confidence_or_ood": (
                low_confidence_or_ood if low_flag_valid else None
            ),
            "intermediate_state_errors": intermediate_errors,
            "token_count": None,
            "estimated_cost": None,
            "latency": None,
            "network_access": False,
            "training_performed": False,
            "real_provider_call_count": 0,
            "input_profile": PRIMARY_SEMANTIC_INPUT_PROFILE,
        }

        if not fallback_reasons:
            if base_prediction is None:
                raise HybridRoutingError("confident route lacks a canonical base prediction")
            return RouterPrediction(
                case_id=case_id,
                model_id=self.model_id,
                dialogue_action="ANSWER",
                metadata={
                    **common_metadata,
                    "execution_mode": "OFFLINE_HYBRID_DIRECT_BASE",
                    "routing_source": "DIRECT_BASE_ROUTE",
                    "final_prediction_source": self._base_prediction_source,
                    "fallback_triggered": False,
                    "fallback_reasons": [],
                    "provider_call_count": 0,
                },
                **base_prediction,
            )

        before = int(self._b4_fallback.provider_call_count)
        fallback_prediction = self._b4_fallback.predict(
            case_id=case_id,
            model_input=semantic_input,
        )
        after = int(self._b4_fallback.provider_call_count)
        provider_calls = after - before
        if provider_calls != 1:
            raise HybridRoutingError("one uncertain P1 route must make exactly one B4 call")
        return RouterPrediction(
            case_id=case_id,
            model_id=self.model_id,
            dialogue_action="ANSWER",
            rag_required=fallback_prediction.rag_required,
            memory_required=fallback_prediction.memory_required,
            planning_required=fallback_prediction.planning_required,
            metadata={
                **common_metadata,
                "execution_mode": "OFFLINE_HYBRID_LLM_FALLBACK",
                "routing_source": "LLM_FALLBACK",
                "final_prediction_source": "R2V2-B4_LLM",
                "fallback_triggered": True,
                "fallback_reasons": fallback_reasons,
                "provider_call_count": provider_calls,
                "provider_total_call_count": after,
                "fallback_reason_code": fallback_prediction.metadata.get("reason_code"),
            },
        )
