"""Safe execution tracing for C4_REAL_V1 orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any, Iterator, Mapping
import uuid

from utils.c4_real_contracts import (
    C4RealRequest,
    ClarificationDecision,
    GenerationResult,
    ModuleActivation,
    P3CapabilityRoute,
)


TRACE_SCHEMA_VERSION = "c4-real-v1-execution-trace-v1"
TOKEN_COST_PLACEHOLDERS = {
    "input_tokens": None,
    "output_tokens": None,
    "total_tokens": None,
    "cost_amount": None,
    "cost_currency": "USD",
    "measurement_status": "NOT_MEASURED_TRACK_S",
}


@dataclass(frozen=True)
class C4ExecutionTrace:
    schema_version: str
    trace_id: str
    scenario_id: str
    request_id: str
    mode: str
    execution_context: str
    state_reset_id: str
    clarification: Mapping[str, Any]
    p3_route: Mapping[str, Any]
    module_activation: Mapping[str, Any]
    modules_actually_called: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    course_source_ids: tuple[str, ...]
    memory_ids: tuple[str, ...]
    memory_item_types: tuple[str, ...]
    planner_status: str
    generator_identity: str
    output_kind: str
    token_cost: Mapping[str, Any]
    latency_ms: float
    stage_latency_ms: Mapping[str, float]
    errors: tuple[Mapping[str, str], ...]
    limitations: tuple[str, ...]
    committed_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def safe_panel(self) -> dict[str, Any]:
        """Return the only fields permitted in the collapsed Streamlit panel."""

        return {
            "route decision": {
                "mode": self.mode,
                "clarification": dict(self.clarification),
                "p3_route": dict(self.p3_route),
                "modules_activated": dict(self.module_activation),
            },
            "course sources used": list(self.course_source_ids),
            "Memory item types used": list(self.memory_item_types),
            "Planning used": "recommendation_planner" in self.modules_actually_called,
            "limitations": list(self.limitations),
        }


class InMemoryTraceSink:
    """A deterministic local sink suitable for tests and mock replay only."""

    identity = "TRACK_S_IN_MEMORY_TRACE_SINK"

    def __init__(self) -> None:
        self.traces: list[C4ExecutionTrace] = []

    def commit(self, trace: C4ExecutionTrace) -> None:
        self.traces.append(trace)


class C4TraceRecorder:
    """Mutable request-local recorder that emits one immutable trace."""

    def __init__(self, request: C4RealRequest) -> None:
        self.request = request
        self.started_ns = perf_counter_ns()
        self.modules_called: list[str] = []
        self.stage_latency_ms: dict[str, float] = {}
        self.clarification: dict[str, Any] = {
            "gate_id": "",
            "decision": "NOT_RUN",
            "reason_code": "",
        }
        self.p3_route: dict[str, Any] = {"status": "NOT_RUN"}
        self.activation: dict[str, Any] = {
            "evidence_synthesis": False,
            "rag": False,
            "memory": False,
            "planning": False,
            "forced_off": [],
        }
        self.evidence_ids: list[str] = []
        self.course_source_ids: list[str] = []
        self.memory_ids: list[str] = []
        self.memory_item_types: list[str] = []
        self.planner_status = "NOT_APPLICABLE"
        self.generator_identity = "NOT_CALLED"
        self.output_kind = "NOT_PRODUCED"
        self.token_cost = dict(TOKEN_COST_PLACEHOLDERS)
        self.errors: list[dict[str, str]] = []
        self.limitations: list[str] = []

    @contextmanager
    def provider_call(self, module_name: str) -> Iterator[None]:
        self.modules_called.append(module_name)
        started = perf_counter_ns()
        try:
            yield
        finally:
            elapsed = (perf_counter_ns() - started) / 1_000_000
            self.stage_latency_ms[module_name] = round(
                self.stage_latency_ms.get(module_name, 0.0) + elapsed, 6
            )

    def record_clarification(self, decision: ClarificationDecision) -> None:
        self.clarification = {
            "gate_id": decision.gate_id,
            "decision": "CLARIFY" if decision.needs_clarification else "ANSWER",
            "reason_code": decision.reason_code,
        }
        self.limitations.extend(decision.limitations)

    def record_route(self, route: P3CapabilityRoute) -> None:
        self.p3_route = route.to_trace_dict()
        self.limitations.extend(route.limitations)

    def record_activation(self, activation: ModuleActivation) -> None:
        self.activation = activation.to_trace_dict()
        if activation.forced_off:
            self.limitations.append(
                "Mode contract forced OFF: " + ", ".join(activation.forced_off)
            )

    def record_generator(self, generated: GenerationResult) -> None:
        self.generator_identity = generated.generator_identity
        self.output_kind = generated.output_kind
        self.token_cost = {
            "input_tokens": generated.input_tokens,
            "output_tokens": generated.output_tokens,
            "total_tokens": generated.total_tokens,
            "cost_amount": generated.cost_amount,
            "cost_currency": generated.cost_currency,
            "measurement_status": (
                "PROVIDER_REPORTED"
                if generated.total_tokens is not None or generated.cost_amount is not None
                else "NOT_MEASURED_TRACK_S"
            ),
        }
        self.limitations.extend(generated.limitations)

    def record_error(self, error: BaseException) -> None:
        self.errors.append(
            {
                "error_type": type(error).__name__,
                "message": str(error)[:300],
            }
        )

    def finish(self) -> C4ExecutionTrace:
        latency_ms = (perf_counter_ns() - self.started_ns) / 1_000_000
        return C4ExecutionTrace(
            schema_version=TRACE_SCHEMA_VERSION,
            trace_id=str(uuid.uuid4()),
            scenario_id=self.request.scenario_id,
            request_id=self.request.request_id,
            mode=self.request.mode.value,
            execution_context=self.request.execution_context.value,
            state_reset_id=self.request.state_reset_id,
            clarification=dict(self.clarification),
            p3_route=dict(self.p3_route),
            module_activation=dict(self.activation),
            modules_actually_called=tuple(self.modules_called),
            evidence_ids=tuple(dict.fromkeys(self.evidence_ids)),
            course_source_ids=tuple(dict.fromkeys(self.course_source_ids)),
            memory_ids=tuple(dict.fromkeys(self.memory_ids)),
            memory_item_types=tuple(dict.fromkeys(self.memory_item_types)),
            planner_status=self.planner_status,
            generator_identity=self.generator_identity,
            output_kind=self.output_kind,
            token_cost=dict(self.token_cost),
            latency_ms=round(latency_ms, 6),
            stage_latency_ms=dict(self.stage_latency_ms),
            errors=tuple(dict(error) for error in self.errors),
            limitations=tuple(dict.fromkeys(value for value in self.limitations if value)),
            committed_at_utc=datetime.now(timezone.utc).isoformat(),
        )
