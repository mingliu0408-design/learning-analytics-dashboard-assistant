"""Common offline interfaces for the six frozen RQ2-V2 method identities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import MODEL_IDS, PREDICTION_SCHEMA_VERSION
from .contracts import Stage0ContractError, validate_case, validate_prediction


class PaidAPIExecutionBlocked(RuntimeError):
    """Raised when Stage 0 is asked to execute a paid/provider-backed method."""


class UnfrozenLegacyMappingError(RuntimeError):
    """Raised when B1 execution is requested before its development mapping freeze."""


@dataclass(frozen=True)
class RouterPrediction:
    case_id: str
    model_id: str
    dialogue_action: str
    rag_required: bool
    memory_required: bool
    planning_required: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = PREDICTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "model_id": self.model_id,
            "dialogue_action": self.dialogue_action,
            "rag_required": self.rag_required,
            "memory_required": self.memory_required,
            "planning_required": self.planning_required,
            "metadata": dict(self.metadata),
        }
        validate_prediction(value)
        return value


class Stage0RouterInterface(ABC):
    """A prediction-only interface; training and provider execution are absent."""

    model_id: str

    @abstractmethod
    def predict(self, case: Mapping[str, Any]) -> RouterPrediction:
        raise NotImplementedError


class DummyRouter(Stage0RouterInterface):
    """Deterministic fixture router used only for Stage 0 interface smoke tests."""

    def __init__(
        self,
        model_id: str,
        *,
        dialogue_action: str = "ANSWER",
        rag_required: bool = False,
        memory_required: bool = False,
        planning_required: bool = False,
    ) -> None:
        if model_id not in MODEL_IDS:
            raise Stage0ContractError(f"unknown RQ2-V2 model_id: {model_id}")
        self.model_id = model_id
        self._output = {
            "dialogue_action": dialogue_action,
            "rag_required": bool(rag_required),
            "memory_required": bool(memory_required),
            "planning_required": bool(planning_required),
        }

    def predict(self, case: Mapping[str, Any]) -> RouterPrediction:
        validate_case(case)
        return RouterPrediction(
            case_id=str(case["case_id"]),
            model_id=self.model_id,
            metadata={
                "execution_mode": "STAGE0_DUMMY",
                "provider_call_count": 0,
                "network_access": False,
                "training_performed": False,
            },
            **self._output,
        )


class LegacyIntentCascadeInterface(Stage0RouterInterface):
    """B1 adapter boundary using an externally frozen RQ1 predictor and mapping.

    Stage 0 deliberately ships no mapping.  A later authorised development
    stage must supply a complete mapping for the exact 16-label C0 universe and
    mark it frozen before this class may predict.
    """

    model_id = "R2V2-B1_LEGACY_INTENT"

    def __init__(
        self,
        *,
        legacy_predictor: Callable[[Mapping[str, Any]], str],
        frozen_label_universe: tuple[str, ...],
        intent_to_capability_mapping: Mapping[str, Mapping[str, bool]] | None,
        mapping_frozen: bool,
    ) -> None:
        self._legacy_predictor = legacy_predictor
        self._labels = tuple(frozen_label_universe)
        self._mapping = (
            {str(key): dict(value) for key, value in intent_to_capability_mapping.items()}
            if intent_to_capability_mapping is not None
            else None
        )
        self._mapping_frozen = bool(mapping_frozen)

    def predict(self, case: Mapping[str, Any]) -> RouterPrediction:
        validate_case(case)
        if not self._mapping_frozen or self._mapping is None:
            raise UnfrozenLegacyMappingError(
                "B1 Intent-to-Capability mapping is pending development-only freeze"
            )
        if set(self._mapping) != set(self._labels):
            raise Stage0ContractError("B1 mapping must cover the exact frozen label universe")
        intent = str(self._legacy_predictor(case))
        if intent not in self._labels:
            raise Stage0ContractError(f"RQ1 predictor returned an unknown intent: {intent}")
        mapped = self._mapping[intent]
        return RouterPrediction(
            case_id=str(case["case_id"]),
            model_id=self.model_id,
            dialogue_action="ANSWER",
            rag_required=bool(mapped["rag_required"]),
            memory_required=bool(mapped["memory_required"]),
            planning_required=bool(mapped["planning_required"]),
            metadata={
                "execution_mode": "FROZEN_LEGACY_CASCADE",
                "legacy_intent": intent,
                "provider_call_count": 0,
                "network_access": False,
                "training_performed": False,
            },
        )


def run_no_paid_api_dry_run(case: Mapping[str, Any]) -> dict[str, Any]:
    """Exercise all method identities with local dummy predictions only."""

    predictions = [DummyRouter(model_id).predict(case).to_dict() for model_id in MODEL_IDS]
    provider_calls = sum(
        int(prediction["metadata"]["provider_call_count"])
        for prediction in predictions
    )
    network_access = any(
        bool(prediction["metadata"]["network_access"])
        for prediction in predictions
    )
    if provider_calls or network_access:
        raise PaidAPIExecutionBlocked("Stage 0 dry-run attempted external execution")
    return {
        "status": "PASS",
        "model_ids": list(MODEL_IDS),
        "prediction_count": len(predictions),
        "provider_calls": provider_calls,
        "network_access": network_access,
        "training_performed": False,
        "final_test_executed": False,
    }

