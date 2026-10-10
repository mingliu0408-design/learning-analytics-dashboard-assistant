"""Thin R2V2-B1 adapter around the frozen RQ1 C0 cosine runtime.

The real runtime path is:

``utils.production_intent_router.load_production_semantic_router``
    -> ``utils.semantic_intent_router.SemanticIntentRouter.predict``

Only ``current_query`` and the C0-compatible form of ``current_page`` enter
C0.  The adapter never retrains C0, changes its 62 examples, changes MAX
aggregation, inserts unsupported taxonomy labels, or uses case Gold.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import socket
from typing import Any, Callable, Iterator, Mapping
from unittest.mock import patch

from evaluation.capability_routing_rq2_v2_stage0.contracts import validate_case
from evaluation.capability_routing_rq2_v2_stage0.interfaces import RouterPrediction

from . import B1_MODEL_ID, PACKAGE_ROOT, PROJECT_ROOT


DEFAULT_MAPPING_PATH = (
    PACKAGE_ROOT / "config" / "b1_intent_to_capability_mapping_unfrozen_v1.json"
)
STAGE0_B1_CONTRACT_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "capability_routing_rq2_v2_stage0"
    / "config"
    / "b1_legacy_interface_v1.json"
)
SEMANTIC_CONFIG_PATH = (
    PROJECT_ROOT / "semantic_runtime" / "config" / "semantic_routing_config.json"
)

STRICT_FINAL_INFERENCE = "STRICT_FINAL_INFERENCE"
UNIT_TEST_TOY = "UNIT_TEST_TOY"
MAPPING_MODES = (STRICT_FINAL_INFERENCE, UNIT_TEST_TOY)

OFFLINE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


class B1AdapterError(RuntimeError):
    """Base class for fail-closed B1 errors."""


class B1MappingError(B1AdapterError):
    """Raised when an Intent-to-Capability mapping is malformed."""


class UnfrozenB1MappingError(B1MappingError):
    """Raised when strict inference is attempted with an unfrozen mapping."""


class IncompleteB1MappingError(B1MappingError):
    """Raised when the exact frozen 16-intent universe is not covered."""


class UnknownC0IntentError(B1AdapterError):
    """Raised rather than guessing a mapping for an unsupported C0 intent."""


class LocalC0AssetsUnavailableError(B1AdapterError):
    """Raised when the local-only frozen C0 runtime cannot be constructed."""


class C0InferenceError(B1AdapterError):
    """Raised when the frozen runtime does not return a valid available result."""


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B1MappingError(f"cannot load JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise B1MappingError(f"JSON payload must be an object: {path}")
    return value


def frozen_c0_label_universe() -> tuple[str, ...]:
    """Return the actual Stage 0-verified approved-index label axis."""

    contract = _load_json_object(STAGE0_B1_CONTRACT_PATH)
    if (
        contract.get("selected_rq1_router") != "C0_COSINE"
        or contract.get("approved_example_count") != 62
        or contract.get("aggregation")
        != "MAX_OVER_ELIGIBLE_APPROVED_EXAMPLES_PER_INTENT"
    ):
        raise B1AdapterError("frozen Stage 0 C0 identity metadata has drifted")
    rows = contract.get("frozen_label_universe")
    if not isinstance(rows, list):
        raise B1AdapterError("frozen Stage 0 C0 label universe is malformed")
    labels = tuple(str(item.get("label")) for item in rows if isinstance(item, dict))
    counts = [item.get("approved_example_count") for item in rows if isinstance(item, dict)]
    if len(labels) != 16 or len(set(labels)) != 16 or sum(int(item) for item in counts) != 62:
        raise B1AdapterError("frozen Stage 0 C0 label universe has drifted")
    unsupported = set(contract.get("runtime_taxonomy_labels_without_c0_index_support") or ())
    if unsupported != {"memory_state_query", "ambiguous"} or unsupported.intersection(labels):
        raise B1AdapterError("unsupported live-taxonomy boundary has drifted")
    return labels


def _basic_mapping_entries(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("schema_version") != "rq2-v2-b1-intent-capability-mapping-v1":
        raise B1MappingError("unsupported B1 mapping schema")
    entries = payload.get("mappings")
    if not isinstance(entries, list):
        raise B1MappingError("B1 mappings must be a list")
    by_intent: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise B1MappingError("each B1 mapping entry must be an object")
        intent_id = str(raw.get("intent_id") or "").strip()
        if not intent_id or intent_id in by_intent:
            raise B1MappingError("B1 mapping intent IDs must be non-empty and unique")
        by_intent[intent_id] = dict(raw)
    labels = set(frozen_c0_label_universe())
    observed = set(by_intent)
    if observed != labels:
        missing = sorted(labels - observed)
        extra = sorted(observed - labels)
        raise IncompleteB1MappingError(
            f"B1 mapping must cover the exact frozen 16-intent universe; "
            f"missing={missing}, extra={extra}"
        )
    return by_intent


def validate_mapping_payload(
    payload: Mapping[str, Any],
    *,
    mode: str = STRICT_FINAL_INFERENCE,
) -> dict[str, dict[str, bool]]:
    """Validate a strict future mapping or an explicitly isolated toy mapping."""

    if mode not in MAPPING_MODES:
        raise B1MappingError(f"unknown B1 mapping mode: {mode}")
    by_intent = _basic_mapping_entries(payload)
    status = str(payload.get("mapping_status") or "")
    scope = str(payload.get("mapping_scope") or "")

    if mode == STRICT_FINAL_INFERENCE:
        if status != "FROZEN_DEVELOPMENT_ONLY":
            raise UnfrozenB1MappingError(
                "strict B1 inference requires a development-only frozen mapping; "
                f"observed mapping_status={status or '<missing>'}"
            )
        if scope != "DEVELOPMENT_REVIEWED":
            raise B1MappingError("strict B1 mapping scope must be DEVELOPMENT_REVIEWED")
        if payload.get("development_data_review_complete") is not True:
            raise B1MappingError("strict B1 mapping requires completed development review")
        if payload.get("final_test_accessed_for_mapping") is not False:
            raise B1MappingError("strict B1 mapping must attest zero final-test access")
        if payload.get("final_inference_authorized") is not True:
            raise B1MappingError("strict B1 mapping requires explicit final-inference authorization")
        required_entry_status = "FROZEN_DEVELOPMENT_ONLY"
    else:
        if status != "TOY_FROZEN" or scope != "UNIT_TEST_TOY_ONLY":
            raise B1MappingError("toy mode accepts only a TOY_FROZEN unit-test mapping")
        if payload.get("not_for_development_or_final_inference") is not True:
            raise B1MappingError("toy mapping must be explicitly barred from real inference")
        required_entry_status = "TOY_FROZEN"

    result: dict[str, dict[str, bool]] = {}
    for intent_id, entry in by_intent.items():
        if entry.get("mapping_status") != required_entry_status:
            raise UnfrozenB1MappingError(
                f"B1 mapping entry is not frozen for {intent_id}"
            )
        values: dict[str, bool] = {}
        for field in ("proposed_rag", "proposed_memory", "proposed_planning"):
            value = entry.get(field)
            if not isinstance(value, bool):
                raise UnfrozenB1MappingError(
                    f"B1 mapping field {field} is not boolean for {intent_id}"
                )
            values[field] = value
        rationale = str(entry.get("mapping_rationale") or "").strip()
        if not rationale:
            raise B1MappingError(f"B1 mapping rationale is missing for {intent_id}")
        result[intent_id] = values
    return result


def load_mapping(
    path: str | Path,
    *,
    mode: str = STRICT_FINAL_INFERENCE,
) -> tuple[dict[str, Any], dict[str, dict[str, bool]]]:
    payload = _load_json_object(Path(path))
    return payload, validate_mapping_payload(payload, mode=mode)


def _blocked_network(*_args: Any, **_kwargs: Any) -> Any:
    raise LocalC0AssetsUnavailableError("frozen C0 attempted network access")


@contextmanager
def c0_offline_environment() -> Iterator[None]:
    """Force local-only execution and fail closed on direct socket access."""

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, OFFLINE_ENVIRONMENT, clear=False))
        stack.enter_context(patch("socket.create_connection", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect_ex", _blocked_network))
        yield


@dataclass(frozen=True)
class C0IntentPrediction:
    intent_id: str
    score: float | None
    margin: float | None
    c0_current_page: str | None


@dataclass(frozen=True)
class C0VisibleInput:
    """The complete, narrow, Gold-free feature surface passed to C0."""

    case_id: str
    current_query: str
    current_page: str

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.current_query.strip():
            raise C0InferenceError("C0 visible input requires non-empty identity and query")
        if self.current_page not in {
            "Overview",
            "Resources",
            "Lecture",
            "Debate",
            "Reflection",
            "Other",
        }:
            raise C0InferenceError("C0 visible input contains an invalid current page")


class FrozenC0Top1Predictor:
    """Load and call the repository's actual frozen C0 runtime, without fallback."""

    def __init__(self, runtime: Any | None = None) -> None:
        self._runtime = runtime
        self._labels = frozen_c0_label_universe()
        if runtime is not None:
            self._verify_runtime_identity(runtime)

    @staticmethod
    def _project_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def _verify_local_assets(self) -> None:
        config = _load_json_object(SEMANTIC_CONFIG_PATH)
        if (
            config.get("aggregation") != "max"
            or config.get("aggregate_all_examples") is not True
            or config.get("allow_network_downloads") is not False
        ):
            raise LocalC0AssetsUnavailableError("frozen C0 runtime config has drifted")
        artifacts = config.get("artifacts") or {}
        approved = artifacts.get("approved_index") or {}
        embeddings = artifacts.get("embedding_npz") or {}
        model = config.get("model") or {}
        required_files = (
            self._project_path(str(approved.get("path") or "")),
            self._project_path(str(approved.get("sha256_path") or "")),
            self._project_path(str(approved.get("metadata_path") or "")),
            self._project_path(str(embeddings.get("path") or "")),
            self._project_path(str(embeddings.get("sha256_path") or "")),
        )
        missing = [path.relative_to(PROJECT_ROOT).as_posix() for path in required_files if not path.is_file()]
        model_path = self._project_path(str(model.get("local_path") or ""))
        if not model_path.is_dir():
            missing.append(model_path.relative_to(PROJECT_ROOT).as_posix())
        if missing:
            raise LocalC0AssetsUnavailableError(
                "required frozen C0 assets are unavailable locally: " + ", ".join(missing)
            )
        for descriptor in (approved, embeddings):
            path = self._project_path(str(descriptor["path"]))
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            if observed != str(descriptor.get("sha256")):
                raise LocalC0AssetsUnavailableError(
                    f"frozen C0 artifact hash mismatch: {path.name}"
                )
        if (
            model.get("repo_id") != "sentence-transformers/all-mpnet-base-v2"
            or model.get("revision")
            != "e8c3b32edf5434bc2275fc9bab85f82640a19130"
            or model.get("local_files_only") is not True
        ):
            raise LocalC0AssetsUnavailableError("frozen C0 model identity has drifted")

    def _verify_runtime_identity(self, runtime: Any) -> None:
        if getattr(runtime, "aggregation_method", None) != "max":
            raise C0InferenceError("C0 runtime aggregation is not frozen MAX")
        frozen_index = getattr(runtime, "frozen_index", None)
        records = tuple(getattr(frozen_index, "records", ()) or ())
        labels = {str(getattr(record, "final_semantic_label", "")) for record in records}
        if len(records) != 62 or labels != set(self._labels):
            raise C0InferenceError("C0 runtime does not expose the exact frozen 62/16 index")

    def _runtime_instance(self) -> Any:
        if self._runtime is None:
            self._verify_local_assets()
            try:
                from utils.production_intent_router import load_production_semantic_router

                self._runtime = load_production_semantic_router()
            except Exception as exc:
                raise LocalC0AssetsUnavailableError(
                    f"cannot load local frozen C0 runtime: {type(exc).__name__}"
                ) from exc
            self._verify_runtime_identity(self._runtime)
        return self._runtime

    def predict_intent(self, visible: C0VisibleInput) -> C0IntentPrediction:
        query = visible.current_query
        page_value = visible.current_page
        # C0 has five canonical pages.  Stage 0's explicit "Other" value is
        # represented as no page prefix, retaining query-only candidates.
        c0_page = None if page_value == "Other" else page_value
        with c0_offline_environment():
            runtime = self._runtime_instance()
            prediction = runtime.predict(
                query,
                current_page=c0_page,
                top_k=62,
                candidate_limit=16,
                aggregate_all_examples=True,
            )
        result = getattr(prediction, "result", None)
        intent_id = str(getattr(result, "winning_label", "") or "")
        if getattr(result, "status", None) != "available" or not intent_id:
            reason = str(getattr(prediction, "reason", "") or "unavailable")
            raise C0InferenceError(f"frozen C0 inference unavailable: {reason}")
        if intent_id not in self._labels:
            raise UnknownC0IntentError(f"frozen C0 returned unsupported intent: {intent_id}")
        return C0IntentPrediction(
            intent_id=intent_id,
            score=float(result.winning_score),
            margin=float(result.margin) if result.margin is not None else None,
            c0_current_page=c0_page,
        )


IntentPredictor = Callable[[C0VisibleInput], str | C0IntentPrediction]


class B1LegacyIntentRouter:
    """Project frozen C0 Top-1 through an explicitly governed mapping."""

    model_id = B1_MODEL_ID

    def __init__(
        self,
        mapping_path: str | Path = DEFAULT_MAPPING_PATH,
        *,
        mapping_mode: str = STRICT_FINAL_INFERENCE,
        intent_predictor: IntentPredictor | Any | None = None,
    ) -> None:
        self.mapping_path = Path(mapping_path)
        self.mapping_mode = mapping_mode
        self.mapping_payload, self.mapping = load_mapping(
            self.mapping_path, mode=mapping_mode
        )
        self._labels = frozen_c0_label_universe()
        self._predictor = intent_predictor or FrozenC0Top1Predictor()

    def _predict_intent(self, visible: C0VisibleInput) -> C0IntentPrediction:
        predictor = self._predictor
        if hasattr(predictor, "predict_intent"):
            raw = predictor.predict_intent(visible)
        elif callable(predictor):
            raw = predictor(visible)
        else:
            raise B1AdapterError("B1 intent predictor is not callable")
        if isinstance(raw, C0IntentPrediction):
            result = raw
        else:
            result = C0IntentPrediction(
                intent_id=str(raw), score=None, margin=None, c0_current_page=None
            )
        if result.intent_id not in self._labels:
            raise UnknownC0IntentError(
                f"C0 intent is outside the frozen 16-label universe: {result.intent_id}"
            )
        return result

    def predict(self, case: Mapping[str, Any]) -> RouterPrediction:
        validate_case(case)
        model_input = case["model_input"]
        visible = C0VisibleInput(
            case_id=str(case["case_id"]),
            current_query=str(model_input["current_query"]),
            current_page=str(model_input["current_page"]),
        )
        c0 = self._predict_intent(visible)
        mapped = self.mapping.get(c0.intent_id)
        if mapped is None:
            raise IncompleteB1MappingError(
                f"required B1 mapping is missing for C0 intent: {c0.intent_id}"
            )
        return RouterPrediction(
            case_id=str(case["case_id"]),
            model_id=self.model_id,
            dialogue_action="ANSWER",
            rag_required=mapped["proposed_rag"],
            memory_required=mapped["proposed_memory"],
            planning_required=mapped["proposed_planning"],
            metadata={
                "execution_mode": (
                    "FROZEN_LEGACY_C0_CASCADE"
                    if self.mapping_mode == STRICT_FINAL_INFERENCE
                    else "UNIT_TEST_TOY_LEGACY_C0_CASCADE"
                ),
                "provider_call_count": 0,
                "network_access": False,
                "training_performed": False,
                "legacy_router_id": "C0_COSINE",
                "legacy_intent": c0.intent_id,
                "legacy_top1_score": c0.score,
                "legacy_top1_margin": c0.margin,
                "legacy_current_page": c0.c0_current_page,
                "mapping_id": str(self.mapping_payload.get("mapping_id") or ""),
                "mapping_status": str(self.mapping_payload["mapping_status"]),
                "mapping_scope": str(self.mapping_payload["mapping_scope"]),
                "model_visible_fields_used_by_c0": ["current_query", "current_page"],
            },
        )


__all__ = [
    "B1AdapterError",
    "B1LegacyIntentRouter",
    "B1MappingError",
    "C0InferenceError",
    "C0IntentPrediction",
    "C0VisibleInput",
    "DEFAULT_MAPPING_PATH",
    "FrozenC0Top1Predictor",
    "IncompleteB1MappingError",
    "LocalC0AssetsUnavailableError",
    "STRICT_FINAL_INFERENCE",
    "UNIT_TEST_TOY",
    "UnfrozenB1MappingError",
    "UnknownC0IntentError",
    "c0_offline_environment",
    "frozen_c0_label_universe",
    "load_mapping",
    "validate_mapping_payload",
]
