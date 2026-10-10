"""Deterministic, local-only providers for Track S tests and replay.

Every identity is explicitly marked as a mock.  These providers make no
network calls and the generator always suppresses response content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Sequence
import uuid

from utils.c4_real_contracts import (
    C4RealDependencies,
    C4RealRequest,
    ClarificationDecision,
    CompiledEvidence,
    CourseRAGResult,
    CourseSource,
    EvidenceItem,
    EvidenceSynthesisResult,
    GenerationResult,
    GuardedOutput,
    MemoryItem,
    MemoryReadResult,
    MemoryScope,
    MemoryWriteProposal,
    ModuleActivation,
    P3CapabilityRoute,
    P3_ROUTER_METHOD_ID,
    PlannerResult,
    PrimarySemanticInput,
    TRACK_S_NO_REAL_ANSWER,
)
from utils.c4_real_trace import InMemoryTraceSink


@dataclass
class MockCallLog:
    calls: list[str] = field(default_factory=list)
    router_payloads: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str) -> None:
        self.calls.append(name)


class MockClarificationGate:
    identity = "TRACK_S_MOCK_CLARIFICATION_GATE"

    def __init__(self, call_log: MockCallLog, *, clarify: bool = False) -> None:
        self.call_log = call_log
        self.clarify = clarify

    def evaluate(self, primary_input: PrimarySemanticInput) -> ClarificationDecision:
        self.call_log.add("clarification_gate")
        return ClarificationDecision(
            needs_clarification=self.clarify,
            reason_code="TRACK_S_MOCK_CLARIFY" if self.clarify else "ANSWER",
        )


class MockP3Router:
    identity = "TRACK_S_MOCK_PRECOMPUTED_ROUTE_CACHE"

    def __init__(self, call_log: MockCallLog, route: P3CapabilityRoute) -> None:
        self.call_log = call_log
        self.static_route = route
        self._cache: dict[str, P3CapabilityRoute] = {}

    def route(self, primary_input: PrimarySemanticInput) -> P3CapabilityRoute:
        payload = primary_input.to_payload()
        key = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.call_log.add("frozen_scenario_route_provider")
        if key not in self._cache:
            self.call_log.add("p3_scenario_decision")
            self.call_log.router_payloads.append(payload)
            self._cache[key] = self.static_route
        return self._cache[key]


class MockEvidenceSynthesiser:
    identity = "TRACK_S_MOCK_EVIDENCE_SYNTHESISER"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def synthesise(
        self, *, request: C4RealRequest, primary_input: PrimarySemanticInput
    ) -> EvidenceSynthesisResult:
        self.call_log.add("dashboard_evidence_synthesis")
        return EvidenceSynthesisResult(
            items=(
                EvidenceItem(
                    evidence_id=f"mock-dashboard:{request.scenario_id}",
                    evidence_type="TRACK_S_MOCK_DASHBOARD_EVIDENCE",
                    content={"mock_only": True, "page": primary_input.current_page},
                ),
            ),
            limitations=("Dashboard evidence is synthetic Track-S scaffolding.",),
            status="AVAILABLE",
        )


class MockCourseRAGProvider:
    identity = "TRACK_S_MOCK_COURSE_RAG"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def retrieve(
        self,
        *,
        request: C4RealRequest,
        evidence: EvidenceSynthesisResult | None,
    ) -> CourseRAGResult:
        self.call_log.add("course_rag")
        return CourseRAGResult(
            sources=(
                CourseSource(
                    source_id=f"mock-course:{request.scenario_id}",
                    source_type="TRACK_S_MOCK_COURSE_SOURCE",
                    content={"mock_only": True},
                ),
            ),
            limitations=("Course retrieval is a mock; no course index was queried.",),
            result_status="SUPPORTED",
        )


class MockLearnerMemoryProvider:
    identity = "TRACK_S_MOCK_LEARNER_MEMORY"

    def __init__(
        self, call_log: MockCallLog, *, propose_from_student: bool = False
    ) -> None:
        self.call_log = call_log
        self._items: dict[tuple[str, ...], dict[str, MemoryItem]] = {}
        self._enabled: dict[tuple[str, ...], bool] = {}
        self._proposals: dict[tuple[str, ...], list[MemoryWriteProposal]] = {}
        self.propose_from_student = propose_from_student

    @property
    def proposals(self) -> tuple[MemoryWriteProposal, ...]:
        return tuple(
            proposal
            for key in sorted(self._proposals)
            for proposal in self._proposals[key]
        )

    def is_enabled(self, scope: MemoryScope) -> bool:
        self.call_log.add("learner_memory.is_enabled")
        return self._enabled.get(scope.key(), True)

    def read(self, *, scope: MemoryScope, request: C4RealRequest) -> MemoryReadResult:
        self.call_log.add("learner_memory.read")
        items = self._items.get(scope.key(), {})
        return MemoryReadResult(
            items=tuple(items[key] for key in sorted(items)),
            limitations=("Learner Memory is an isolated in-process Track-S mock.",),
            status="AVAILABLE" if items else "NO_MATCH",
        )

    def propose_write(
        self,
        *,
        scope: MemoryScope,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        guarded_output: GuardedOutput,
        planner_result: PlannerResult | None,
    ) -> MemoryWriteProposal | None:
        self.call_log.add("learner_memory.propose_write")
        if not self.propose_from_student:
            return None
        proposal = MemoryWriteProposal(
            proposal_id=f"mock-proposal:{uuid.uuid4()}",
            item_type="student_statement",
            value=request.current_query,
            source_type="student_explicit",
        )
        # Proposals remain separate from learner facts pending human action.
        self._proposals.setdefault(scope.key(), []).append(proposal)
        return proposal

    def reset(self, scope: MemoryScope) -> None:
        self.call_log.add("learner_memory.reset")
        self._items.pop(scope.key(), None)
        self._enabled.pop(scope.key(), None)
        self._proposals.pop(scope.key(), None)

    def view(self, scope: MemoryScope) -> Sequence[MemoryItem]:
        self.call_log.add("learner_memory.view")
        values = self._items.get(scope.key(), {})
        return tuple(values[key] for key in sorted(values))

    def correct(self, scope: MemoryScope, memory_id: str, value: Any) -> None:
        self.call_log.add("learner_memory.correct")
        items = self._items.setdefault(scope.key(), {})
        if memory_id not in items:
            raise KeyError(memory_id)
        current = items[memory_id]
        items[memory_id] = MemoryItem(
            memory_id=current.memory_id,
            item_type=current.item_type,
            value=value,
            provenance="human_correction",
        )

    def delete(self, scope: MemoryScope, memory_id: str) -> None:
        self.call_log.add("learner_memory.delete")
        items = self._items.setdefault(scope.key(), {})
        if memory_id not in items:
            raise KeyError(memory_id)
        del items[memory_id]

    def set_enabled(self, scope: MemoryScope, enabled: bool) -> None:
        self.call_log.add("learner_memory.set_enabled")
        self._enabled[scope.key()] = bool(enabled)

    def clear_research_memory(self, student_id: str) -> None:
        self.call_log.add("learner_memory.clear_research_memory")
        for key in [key for key in self._items if key[1] == student_id]:
            del self._items[key]
        for key in [key for key in self._enabled if key[1] == student_id]:
            del self._enabled[key]
        for key in [key for key in self._proposals if key[1] == student_id]:
            del self._proposals[key]

    def seed(self, scope: MemoryScope, item: MemoryItem) -> None:
        self._items.setdefault(scope.key(), {})[item.memory_id] = item


class MockEvidenceCompiler:
    identity = "TRACK_S_MOCK_EVIDENCE_COMPILER"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def compile(
        self,
        *,
        request: C4RealRequest,
        clarification: ClarificationDecision,
        route: P3CapabilityRoute | None,
        activation: ModuleActivation,
        dashboard_evidence: EvidenceSynthesisResult | None,
        course_rag: CourseRAGResult | None,
        learner_memory: MemoryReadResult | None,
    ) -> CompiledEvidence:
        self.call_log.add("evidence_compiler")
        evidence_ids = tuple(
            [item.evidence_id for item in (dashboard_evidence.items if dashboard_evidence else ())]
            + [source.source_id for source in (course_rag.sources if course_rag else ())]
        )
        return CompiledEvidence(
            content={
                "mock_only": True,
                "clarification": clarification.needs_clarification,
                "activation": activation.to_trace_dict(),
                "memory_item_count": len(learner_memory.items) if learner_memory else 0,
            },
            evidence_ids=evidence_ids,
            limitations=("Compiled evidence contains no provider-generated answer.",),
        )


class MockRecommendationPlanner:
    identity = "TRACK_S_MOCK_RECOMMENDATION_PLANNER"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def plan(
        self, *, request: C4RealRequest, compiled_evidence: CompiledEvidence
    ) -> PlannerResult:
        self.call_log.add("recommendation_planner")
        return PlannerResult(
            status="USED",
            plan={"mock_only": True, "recommendation_content": None},
            limitations=("Planning content is suppressed in Track S.",),
        )


class MockCommonGenerator:
    identity = "TRACK_S_MOCK_COMMON_GENERATOR"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def generate(
        self,
        *,
        request: C4RealRequest,
        clarification: ClarificationDecision,
        route: P3CapabilityRoute | None,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GenerationResult:
        self.call_log.add("common_generator")
        return GenerationResult(
            text="",
            generator_identity=self.identity,
            output_kind=TRACK_S_NO_REAL_ANSWER,
            limitations=("Real LLM response generation is not authorized in Track S.",),
        )


class MockOutputGuard:
    identity = "TRACK_S_MOCK_OUTPUT_GUARD"

    def __init__(self, call_log: MockCallLog) -> None:
        self.call_log = call_log

    def apply(
        self,
        *,
        request: C4RealRequest,
        generated: GenerationResult,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GuardedOutput:
        del activation, compiled_evidence, planner_result
        self.call_log.add("output_guard")
        if generated.generator_identity != MockCommonGenerator.identity:
            raise ValueError("Track S output guard rejected a non-mock generator")
        if generated.output_kind != TRACK_S_NO_REAL_ANSWER or generated.text:
            raise ValueError("Track S output guard rejected generated answer content")
        return GuardedOutput(
            text="",
            generator_identity=generated.generator_identity,
            output_kind=generated.output_kind,
            limitations=generated.limitations,
        )


def build_mock_dependencies(
    *,
    route: P3CapabilityRoute | None = None,
    clarify: bool = False,
    propose_from_student: bool = False,
    call_log: MockCallLog | None = None,
) -> tuple[
    C4RealDependencies,
    MockLearnerMemoryProvider,
    InMemoryTraceSink,
    MockCallLog,
]:
    """Create the complete mock-only Track-S provider bundle."""

    log = call_log or MockCallLog()
    selected_route = route or P3CapabilityRoute(
        rag_required=True,
        memory_required=True,
        planning_required=True,
        method_id=P3_ROUTER_METHOD_ID,
        decision_id="TRACK_S_MOCK_ROUTE",
        provider_identity=MockP3Router.identity,
        limitations=("P3 bits are supplied by a static Track-S mock.",),
    )
    memory = MockLearnerMemoryProvider(
        log, propose_from_student=propose_from_student
    )
    sink = InMemoryTraceSink()
    dependencies = C4RealDependencies(
        clarification_gate=MockClarificationGate(log, clarify=clarify),
        p3_router=MockP3Router(log, selected_route),
        evidence_synthesiser=MockEvidenceSynthesiser(log),
        course_rag=MockCourseRAGProvider(log),
        learner_memory=memory,
        evidence_compiler=MockEvidenceCompiler(log),
        planner=MockRecommendationPlanner(log),
        generator=MockCommonGenerator(log),
        output_guard=MockOutputGuard(log),
        trace_sink=sink,
    )
    return dependencies, memory, sink, log
