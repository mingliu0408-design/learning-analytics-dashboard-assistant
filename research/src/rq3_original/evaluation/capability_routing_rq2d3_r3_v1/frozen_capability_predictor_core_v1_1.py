"""Frozen B0/B1/P1 core whose public input contains no case identity."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, METHODS, PREDICTOR_CONTRACT_ID, canonical_json_bytes


@dataclass(frozen=True)
class CoreRoutingContentV1_1:
    current_query: str
    current_page: str
    necessary_conversation_history: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _RuntimeCase:
    case_id: str
    current_query: str
    current_page: str
    conversation_history: tuple[Mapping[str, Any], ...]


class _MemoizedRuntime:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._cache: dict[tuple[Any, ...], Any] = {}

    @property
    def frozen_index(self) -> Any:
        return self._runtime.frozen_index

    def predict(self, query: str, **kwargs: Any) -> Any:
        key = (
            str(query),
            tuple(
                sorted(
                    (name, tuple(value) if isinstance(value, list) else value)
                    for name, value in kwargs.items()
                )
            ),
        )
        if key not in self._cache:
            self._cache[key] = self._runtime.predict(query, **kwargs)
        return self._cache[key]


def _capabilities(projection: Mapping[str, Any]) -> list[str]:
    return [name for name in CAPABILITIES if bool(projection.get(name))]


def _without_case_id(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "case_id"}


def trace_projection_v1_1(
    method: str,
    measured: Mapping[str, Any],
    *,
    context_prediction: bool,
    capabilities: Sequence[str],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "method_id": method,
        "context_resolution_required_prediction": bool(context_prediction),
        "predicted_capabilities": [name for name in CAPABILITIES if name in set(capabilities)],
    }
    if method == "B0":
        base["method_trace"] = {
            name: measured.get(name)
            for name in (
                "selected_intent",
                "selected_route",
                "source_scope",
                "retrieval_requested",
                "planner_requested",
                "deterministic_guard",
                "original_query_hash",
                "capability_projection",
                "production_function_call_counts",
            )
        }
    elif method == "B1":
        base["method_trace"] = {
            name: measured.get(name)
            for name in (
                "selected_intent",
                "selected_route",
                "source_scope",
                "retrieval_requested",
                "planner_requested",
                "deterministic_guard",
                "original_query_hash",
                "resolved_query_hash",
                "capability_projection",
                "production_call_counts",
            )
        }
    elif method == "P1":
        base["method_trace"] = {
            "policy_id": measured.get("policy_id"),
            "selected_route_for_memory_parity": measured.get("selected_route_for_memory_parity"),
            "context_status": measured.get("context_status"),
            "semantic_evidence": measured.get("semantic_evidence"),
            "deterministic_evidence": measured.get("deterministic_evidence"),
            "production_function_call_counts": measured.get("production_function_call_counts"),
            "context_envelope": _without_case_id(dict(measured.get("context_envelope") or {})),
            "capability_plan": _without_case_id(dict(measured.get("capability_plan") or {})),
        }
    else:
        raise ValueError("unknown frozen method")
    return base


def core_trace_hash_v1_1(projection: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        b"RQ2_TRACK_B_CORE_PREDICTION_TRACE_V1_1\x00"
        + canonical_json_bytes(projection).rstrip(b"\n")
    ).hexdigest()


class FrozenCapabilityPredictorCoreV1_1:
    """Actual provider-free B0/B1/P1 runtime with a case-ID-free public input."""

    contract_id = PREDICTOR_CONTRACT_ID

    def __init__(self) -> None:
        self._stack = ExitStack()
        from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
            LegacyHardRoutingCapabilityAdapterV1,
            _dashboard_fixture,
            provider_free_environment,
        )
        import utils.production_intent_router as production_router

        self._stack.enter_context(provider_free_environment())
        self._raw_runtime = production_router.load_production_semantic_router()
        self._runtime = _MemoizedRuntime(self._raw_runtime)
        self._dashboard = _dashboard_fixture()
        self._b1 = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=self._raw_runtime, dashboard_data=self._dashboard
        )

    def close(self) -> None:
        self._stack.close()

    def __enter__(self) -> "FrozenCapabilityPredictorCoreV1_1":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def predict(self, method: str, content: CoreRoutingContentV1_1) -> dict[str, Any]:
        if method not in METHODS or not isinstance(content, CoreRoutingContentV1_1):
            raise TypeError("frozen core accepts only method and CoreRoutingContentV1_1")
        case = _RuntimeCase(
            case_id="ROUTING_CONTENT_ONLY",
            current_query=content.current_query,
            current_page=content.current_page,
            conversation_history=tuple(dict(item) for item in content.necessary_conversation_history),
        )
        if method == "B0":
            from evaluation.capability_routing_rq2b_v1.b0_original_query_adapter import measure_b0_case

            measured = measure_b0_case(
                case_id=case.case_id,
                original_query=case.current_query,
                current_page=case.current_page,
                semantic_runtime=self._runtime,
                dashboard_data=self._dashboard,
            )
            capabilities = _capabilities(dict(measured["capability_projection"]))
            context_prediction = False
        elif method == "B1":
            measured = self._b1.measure(case)
            capabilities = _capabilities(dict(measured["capability_projection"]))
            context_prediction = _context_prediction_v1_1(case)
        else:
            from evaluation.capability_routing_rq2b_v1.p1_capability_router import route_p1_case

            measured = route_p1_case(
                case, policy_id="P1_D05_SIGNAL_UNION", semantic_runtime=self._runtime
            )
            capabilities = list(measured["predicted_capabilities"])
            context_prediction = bool(measured["context_resolution_required_prediction"])
        projection = trace_projection_v1_1(
            method,
            measured,
            context_prediction=context_prediction,
            capabilities=capabilities,
        )
        return {
            "context_resolution_required_prediction": context_prediction,
            "predicted_capabilities": [name for name in CAPABILITIES if name in set(capabilities)],
            "core_prediction_trace_hash": core_trace_hash_v1_1(projection),
            "_trace_projection": projection,
        }


def _context_prediction_v1_1(case: _RuntimeCase) -> bool:
    import utils.c_full_service as production_service
    from evaluation.capability_routing_rq2b_v1.context_status import derive_context_status

    runtime = production_service.prepare_mode_cm_context(
        student_query=case.current_query,
        conversation_history=list(case.conversation_history),
        existing_session_memory=None,
        current_page=case.current_page,
        transactional_course_corrections=True,
        enable_p2a_extensions=True,
    )
    resolution = runtime.memory_resolution
    effective_query = (
        resolution.resolved_query
        if resolution is not None and resolution.resolved
        else case.current_query
    )
    signals = production_service.detect_c_full_need_signals(
        effective_query,
        current_page=case.current_page,
        active_course_item=dict(runtime.structured_memory.get("active_course_item") or {}),
        enable_p2a_extensions=True,
    )
    deterministic_ambiguity = bool(
        resolution is not None
        and not resolution.resolved
        and production_service._is_underspecified_without_context(case.current_query)
        and not production_service._is_natural_course_coverage_query(case.current_query)
    )
    return derive_context_status(
        runtime,
        deterministic_ambiguity_guard=deterministic_ambiguity,
        discrepancy_correction_need=signals.discrepancy_correction_need,
    ).context_resolution_required_prediction


def predictor_core_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-frozen-capability-predictor-core-contract-v1-1",
        "status": "FROZEN",
        "contract_id": PREDICTOR_CONTRACT_ID,
        "public_input_fields": [
            "current_query",
            "current_page",
            "necessary_conversation_history",
        ],
        "review_case_id_in_public_input": False,
        "feature_record_fingerprint_in_public_input": False,
        "contrast_group_id_in_public_input": False,
        "methods": list(METHODS),
        "p1_policy": "P1_D05_SIGNAL_UNION",
        "model_training": False,
    }
