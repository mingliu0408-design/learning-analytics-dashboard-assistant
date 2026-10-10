"""C4_REAL_V1 provider-neutral service orchestration.

This is deliberately a new service.  It does not import or rewrite the legacy
``c_full_service`` and it binds no network, model, RAG, or Memory provider.
Track R and Track M implementations can be injected through the contracts in
``c4_real_contracts`` without changing the orchestration order.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence
import uuid

from utils.c4_real_contracts import (
    C4Mode,
    C4GenerationPreparation,
    C4RealDependencies,
    C4RealRequest,
    C4RealResult,
    ClarificationDecision,
    CompiledEvidence,
    CourseRAGResult,
    EvidenceSynthesisResult,
    GenerationResult,
    GuardedOutput,
    MemoryItem,
    MemoryReadResult,
    MemoryScope,
    MemoryWriteProposal,
    MODE_POLICIES,
    ModuleActivation,
    P3CapabilityRoute,
    P3_ROUTER_METHOD_ID,
    PlannerResult,
)
from utils.c4_real_trace import C4TraceRecorder


@dataclass(frozen=True)
class _PreGenerationState:
    clarification: ClarificationDecision
    route: P3CapabilityRoute | None
    activation: ModuleActivation
    dashboard_evidence: EvidenceSynthesisResult | None
    course_rag: CourseRAGResult | None
    learner_memory: MemoryReadResult | None
    memory_operationally_enabled: bool
    compiled_evidence: CompiledEvidence
    planner_result: PlannerResult | None
    provider_generation_payload: Mapping[str, Any]


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class C4RealService:
    """Execute one C4 request with immutable mode gates and injected providers."""

    service_identity = "C4_REAL_V1"

    def __init__(self, dependencies: C4RealDependencies) -> None:
        self.dependencies = dependencies

    def _run_pre_generation(
        self,
        request: C4RealRequest,
        recorder: C4TraceRecorder,
        *,
        payload_builder: Any | None,
    ) -> _PreGenerationState:
        """Run the one shared C4 path that precedes response transport."""

        # 1. Clarification Gate.
        with recorder.provider_call("clarification_gate"):
            clarification = self.dependencies.clarification_gate.evaluate(
                request.primary_input
            )
        if not isinstance(clarification, ClarificationDecision):
            raise TypeError("Clarification Gate returned an invalid contract")
        recorder.record_clarification(clarification)

        route: P3CapabilityRoute | None = None
        if clarification.needs_clarification:
            activation = ModuleActivation(False, False, False, False)
            recorder.p3_route = {"status": "SKIPPED_BY_CLARIFICATION_GATE"}
            recorder.planner_status = "SKIPPED_BY_CLARIFICATION_GATE"
        elif request.mode in {C4Mode.C0_ORIGINAL, C4Mode.C1_EVIDENCE}:
            activation = MODE_POLICIES[request.mode].activate(
                P3CapabilityRoute(False, False, False)
            )
            recorder.p3_route = {
                "status": "BYPASSED_BY_MODE_CONTRACT",
                "mode_contract": "C0_C1_ZERO_P3",
            }
        else:
            # 2. Frozen scenario-level P3 route.
            with recorder.provider_call("frozen_scenario_route_provider"):
                route = self.dependencies.route_provider.route(request.primary_input)
            if not isinstance(route, P3CapabilityRoute):
                raise TypeError("P3 Router returned an invalid route contract")
            if route.method_id != P3_ROUTER_METHOD_ID:
                raise ValueError(
                    "C4_REAL_V1 accepts only the frozen RQ2_FINAL_ROUTER_FOR_RQ3 method"
                )
            recorder.record_route(route)
            activation = MODE_POLICIES[request.mode].activate(route)
        recorder.record_activation(activation)

        # 3. Dashboard Evidence Synthesis. C0 intentionally skips this.
        dashboard_evidence: EvidenceSynthesisResult | None = None
        if activation.evidence_synthesis:
            with recorder.provider_call("dashboard_evidence_synthesis"):
                dashboard_evidence = self.dependencies.evidence_synthesiser.synthesise(
                    request=request,
                    primary_input=request.primary_input,
                )
            if not isinstance(dashboard_evidence, EvidenceSynthesisResult):
                raise TypeError("Evidence Synthesiser returned an invalid contract")
            recorder.evidence_ids.extend(
                item.evidence_id for item in dashboard_evidence.items
            )
            recorder.limitations.extend(dashboard_evidence.limitations)

        # 4. Optional Course RAG.
        course_rag: CourseRAGResult | None = None
        if activation.rag:
            with recorder.provider_call("course_rag"):
                course_rag = self.dependencies.course_rag.retrieve(
                    request=request,
                    evidence=dashboard_evidence,
                )
            if not isinstance(course_rag, CourseRAGResult):
                raise TypeError("Course RAG returned an invalid contract")
            recorder.course_source_ids.extend(
                source.source_id for source in course_rag.sources
            )
            recorder.evidence_ids.extend(
                source.source_id for source in course_rag.sources
            )
            recorder.limitations.extend(course_rag.limitations)

        # 5. Optional Learner Memory.
        learner_memory: MemoryReadResult | None = None
        memory_operationally_enabled = False
        if activation.memory:
            with recorder.provider_call("learner_memory"):
                memory_operationally_enabled = (
                    self.dependencies.learner_memory.is_enabled(request.memory_scope)
                )
                if memory_operationally_enabled:
                    learner_memory = self.dependencies.learner_memory.read(
                        scope=request.memory_scope,
                        request=request,
                    )
            if not memory_operationally_enabled:
                recorder.limitations.append(
                    "Learner Memory is disabled by the student control"
                )
            elif not isinstance(learner_memory, MemoryReadResult):
                raise TypeError("Learner Memory returned an invalid contract")
            else:
                recorder.memory_ids.extend(item.memory_id for item in learner_memory.items)
                recorder.memory_item_types.extend(
                    item.item_type for item in learner_memory.items
                )
                recorder.limitations.extend(learner_memory.limitations)

        # 6. Evidence Compiler.
        with recorder.provider_call("evidence_compiler"):
            compiled = self.dependencies.evidence_compiler.compile(
                request=request,
                clarification=clarification,
                route=route,
                activation=activation,
                dashboard_evidence=dashboard_evidence,
                course_rag=course_rag,
                learner_memory=learner_memory,
            )
        if not isinstance(compiled, CompiledEvidence):
            raise TypeError("Evidence Compiler returned an invalid contract")
        recorder.evidence_ids.extend(compiled.evidence_ids)
        recorder.limitations.extend(compiled.limitations)

        # 7. Optional Recommendation Planner.
        planner_result: PlannerResult | None = None
        if activation.planning:
            with recorder.provider_call("recommendation_planner"):
                planner_result = self.dependencies.planner.plan(
                    request=request,
                    compiled_evidence=compiled,
                )
            if not isinstance(planner_result, PlannerResult):
                raise TypeError("Planner returned an invalid contract")
            recorder.planner_status = planner_result.status
            recorder.limitations.extend(planner_result.limitations)
        elif not clarification.needs_clarification:
            recorder.planner_status = "SKIPPED_MODE_OR_P3"

        # 8. Pure provider-safe payload construction. This is deliberately not
        # the Common Generator transport and cannot emit a student response.
        provider_payload: Mapping[str, Any] = {}
        planner_blocked = (
            planner_result is not None
            and planner_result.status == "UNSUPPORTED_OR_INCONSISTENT"
        )
        if payload_builder is not None and not planner_blocked:
            builder = getattr(payload_builder, "build_request_payload_v2", None)
            if not callable(builder):
                raise TypeError(
                    "Preparation requires a provider-compatible V2 payload builder"
                )
            with recorder.provider_call("generation_payload_construction"):
                provider_payload = builder(
                    request=request,
                    compiled_evidence=compiled,
                    planner_result=planner_result,
                )
            if not isinstance(provider_payload, Mapping):
                raise TypeError("Generation payload builder returned an invalid contract")

        return _PreGenerationState(
            clarification=clarification,
            route=route,
            activation=activation,
            dashboard_evidence=dashboard_evidence,
            course_rag=course_rag,
            learner_memory=learner_memory,
            memory_operationally_enabled=memory_operationally_enabled,
            compiled_evidence=compiled,
            planner_result=planner_result,
            provider_generation_payload=dict(provider_payload),
        )

    def _commit_trace(self, recorder: C4TraceRecorder):
        recorder.modules_called.append("trace_commit")
        trace = recorder.finish()
        sink_error: Exception | None = None
        sink = self.dependencies.trace_sink
        if sink is not None:
            try:
                sink.commit(trace)
            except Exception as error:  # pragma: no cover - explicit fail-closed path
                recorder.record_error(error)
                trace = recorder.finish()
                sink_error = error
        return trace, sink_error

    def execute(self, request: C4RealRequest) -> C4RealResult:
        """Run the governed C4 sequence and commit exactly one request trace."""

        recorder = C4TraceRecorder(request)
        output: GuardedOutput | None = None
        proposal: MemoryWriteProposal | None = None
        error_text = ""
        success = False
        try:
            state = self._run_pre_generation(
                request,
                recorder,
                payload_builder=None,
            )

            # 8. Common Generator.
            with recorder.provider_call("common_generator"):
                generated = self.dependencies.generator.generate(
                    request=request,
                    clarification=state.clarification,
                    route=state.route,
                    activation=state.activation,
                    compiled_evidence=state.compiled_evidence,
                    planner_result=state.planner_result,
                )
            if not isinstance(generated, GenerationResult):
                raise TypeError("Common Generator returned an invalid contract")
            recorder.record_generator(generated)

            # 9. Output guard.
            with recorder.provider_call("output_guard"):
                output = self.dependencies.output_guard.apply(
                    request=request,
                    generated=generated,
                    activation=state.activation,
                    compiled_evidence=state.compiled_evidence,
                    planner_result=state.planner_result,
                )
            if not isinstance(output, GuardedOutput):
                raise TypeError("Output guard returned an invalid contract")
            recorder.limitations.extend(output.limitations)

            # 10. Optional Memory-write proposal.
            if state.activation.memory and state.memory_operationally_enabled:
                with recorder.provider_call("memory_write_proposal"):
                    proposal = self.dependencies.learner_memory.propose_write(
                        scope=request.memory_scope,
                        request=request,
                        compiled_evidence=state.compiled_evidence,
                        guarded_output=output,
                        planner_result=state.planner_result,
                    )
                if proposal is not None:
                    if not isinstance(proposal, MemoryWriteProposal):
                        raise TypeError("Memory provider returned an invalid write proposal")
                    proposal.validate_source()
            success = True
        except Exception as error:  # Fail closed and preserve a trace.
            recorder.record_error(error)
            error_text = f"{type(error).__name__}: C4_REAL_V1 orchestration failed"
            output = None
            proposal = None

        # 11. Trace commit. No subsequent orchestration module may run.
        trace, sink_error = self._commit_trace(recorder)
        if sink_error is not None:
            success = False
            output = None
            proposal = None
            error_text = (
                f"{type(sink_error).__name__}: C4_REAL_V1 trace commit failed"
            )
        return C4RealResult(
            success=success,
            output=output,
            trace=trace,
            memory_write_proposal=proposal,
            error=error_text,
        )

    def prepare_generation_request(
        self,
        request: C4RealRequest,
        *,
        payload_builder: Any | None = None,
    ) -> C4GenerationPreparation:
        """Prepare one provider-safe request without any generation transport."""

        recorder = C4TraceRecorder(request)
        state: _PreGenerationState | None = None
        success = False
        generation_ready = False
        error_text = ""
        try:
            state = self._run_pre_generation(
                request,
                recorder,
                payload_builder=payload_builder or self.dependencies.generator,
            )
            if (
                state.planner_result is not None
                and state.planner_result.status == "UNSUPPORTED_OR_INCONSISTENT"
            ):
                raise ValueError("Planner result blocks generation readiness")
            if not state.provider_generation_payload:
                raise ValueError("Provider-safe generation payload was not constructed")
            success = True
            generation_ready = True
        except Exception as error:
            recorder.record_error(error)
            error_text = (
                f"{type(error).__name__}: C4_REAL_PRE_GENERATION_V1 preparation failed"
            )

        trace, sink_error = self._commit_trace(recorder)
        if sink_error is not None:
            success = False
            generation_ready = False
            error_text = (
                f"{type(sink_error).__name__}: C4_REAL_PRE_GENERATION_V1 trace commit failed"
            )

        hashes: dict[str, str] = {}
        if state is not None:
            route_value = state.route.to_trace_dict() if state.route else None
            planner_value = (
                {
                    "status": state.planner_result.status,
                    "plan": state.planner_result.plan,
                    "limitations": list(state.planner_result.limitations),
                }
                if state.planner_result is not None
                else None
            )
            hashes = {
                "compiled_evidence_sha256": state.compiled_evidence.compiled_evidence_sha256,
                "planner_result_sha256": _canonical_sha256(planner_value),
                "provider_generation_payload_sha256": _canonical_sha256(
                    state.provider_generation_payload
                ),
                "mechanism_state_sha256": _canonical_sha256(
                    {
                        "clarification": {
                            "needs_clarification": state.clarification.needs_clarification,
                            "reason_code": state.clarification.reason_code,
                            "gate_id": state.clarification.gate_id,
                        },
                        "route": route_value,
                        "activation": state.activation.to_trace_dict(),
                        "compiled_evidence_sha256": state.compiled_evidence.compiled_evidence_sha256,
                        "planner_result": planner_value,
                        "provider_generation_payload_sha256": _canonical_sha256(
                            state.provider_generation_payload
                        ),
                    }
                ),
            }
        return C4GenerationPreparation(
            success=success,
            generation_ready=generation_ready,
            generation_sent=False,
            clarification=state.clarification if state else None,
            route=state.route if state else None,
            activation=state.activation if state else None,
            dashboard_evidence=state.dashboard_evidence if state else None,
            course_rag=state.course_rag if state else None,
            learner_memory=state.learner_memory if state else None,
            compiled_evidence=state.compiled_evidence if state else None,
            planner_result=state.planner_result if state else None,
            provider_generation_payload=(
                dict(state.provider_generation_payload) if state else {}
            ),
            trace=trace,
            deterministic_hashes=hashes,
            error=error_text,
        )

    def reset_state(self, request: C4RealRequest) -> None:
        """Clear exactly the fully qualified request scope."""

        self.dependencies.learner_memory.reset(request.memory_scope)

    def reset_session(
        self, scope: MemoryScope, *, next_state_reset_id: str | None = None
    ) -> str:
        """Clear one session/condition scope and return its successor reset ID."""

        self.dependencies.learner_memory.reset(scope)
        return next_state_reset_id or str(uuid.uuid4())

    def view_learner_memory(self, scope: MemoryScope) -> Sequence[MemoryItem]:
        return tuple(self.dependencies.learner_memory.view(scope))

    def correct_learner_memory(
        self, scope: MemoryScope, memory_id: str, corrected_value: Any
    ) -> None:
        if not str(memory_id or "").strip():
            raise ValueError("memory_id must be non-empty")
        self.dependencies.learner_memory.correct(scope, memory_id, corrected_value)

    def delete_learner_memory(self, scope: MemoryScope, memory_id: str) -> None:
        if not str(memory_id or "").strip():
            raise ValueError("memory_id must be non-empty")
        self.dependencies.learner_memory.delete(scope, memory_id)

    def disable_learner_memory(self, scope: MemoryScope, disabled: bool = True) -> None:
        self.dependencies.learner_memory.set_enabled(scope, not disabled)

    def clear_research_memory(self, student_id: str) -> None:
        if not str(student_id or "").strip():
            raise ValueError("student_id must be non-empty")
        self.dependencies.learner_memory.clear_research_memory(student_id)


def mode_policy(mode: C4Mode | str):
    """Public, read-only mode-contract lookup used by UI and replay checks."""

    return MODE_POLICIES[C4Mode(mode)]
