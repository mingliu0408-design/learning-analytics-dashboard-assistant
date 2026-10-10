"""Typed, provider-neutral contracts for the RQ3 C4_REAL_V1 service.

The contracts keep the frozen four-field P3 input separate from orchestration
state.  In particular, student identity, reset identifiers, retrieved evidence,
and learner Memory never become Router features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


P3_ROUTER_METHOD_ID = "R2V2-P3_RAG_MEMORY_SPECIALISTS"
CLARIFICATION_GATE_ID = "R2V2-CG1_CLARIFICATION_RULE"
TRACK_S_NO_REAL_ANSWER = "SUPPRESSED_NO_REAL_ANSWER"


class C4Mode(str, Enum):
    """The complete and exact C4_REAL_V1 condition vocabulary."""

    C0_ORIGINAL = "C0_ORIGINAL"
    C1_EVIDENCE = "C1_EVIDENCE"
    C2_EVIDENCE_RAG = "C2_EVIDENCE_RAG"
    C3_EVIDENCE_MEMORY = "C3_EVIDENCE_MEMORY"
    C4_EVIDENCE_PLANNING = "C4_EVIDENCE_PLANNING"
    C5_FULL_C4 = "C5_FULL_C4"
    C5_MINUS_RAG = "C5_MINUS_RAG"
    C5_MINUS_MEMORY = "C5_MINUS_MEMORY"
    C5_MINUS_PLANNING = "C5_MINUS_PLANNING"


class ExecutionContext(str, Enum):
    INTERACTIVE = "interactive"
    EVALUATION = "evaluation"


@dataclass(frozen=True)
class P3CapabilityRoute:
    """The three frozen P3 capability bits consumed by C4."""

    rag_required: bool
    memory_required: bool
    planning_required: bool
    method_id: str = P3_ROUTER_METHOD_ID
    decision_id: str = ""
    provider_identity: str = ""
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("rag_required", "memory_required", "planning_required"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "decision_id": self.decision_id,
            "provider_identity": self.provider_identity,
            "rag_required": self.rag_required,
            "memory_required": self.memory_required,
            "planning_required": self.planning_required,
        }


@dataclass(frozen=True)
class ModePolicy:
    explicit_evidence: bool
    allow_rag: bool
    allow_memory: bool
    allow_planning: bool

    def activate(self, route: P3CapabilityRoute) -> "ModuleActivation":
        """Apply an irreversible upper bound to the P3 route."""

        return ModuleActivation(
            evidence_synthesis=self.explicit_evidence,
            rag=self.allow_rag and route.rag_required,
            memory=self.allow_memory and route.memory_required,
            planning=self.allow_planning and route.planning_required,
            forced_off=tuple(
                name
                for name, requested, allowed in (
                    ("course_rag", route.rag_required, self.allow_rag),
                    ("learner_memory", route.memory_required, self.allow_memory),
                    ("recommendation_planner", route.planning_required, self.allow_planning),
                )
                if requested and not allowed
            ),
        )


@dataclass(frozen=True)
class ModuleActivation:
    evidence_synthesis: bool
    rag: bool
    memory: bool
    planning: bool
    forced_off: tuple[str, ...] = ()

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "evidence_synthesis": self.evidence_synthesis,
            "rag": self.rag,
            "memory": self.memory,
            "planning": self.planning,
            "forced_off": list(self.forced_off),
        }


MODE_POLICIES: Mapping[C4Mode, ModePolicy] = MappingProxyType(
    {
        C4Mode.C0_ORIGINAL: ModePolicy(False, False, False, False),
        C4Mode.C1_EVIDENCE: ModePolicy(True, False, False, False),
        C4Mode.C2_EVIDENCE_RAG: ModePolicy(True, True, False, False),
        C4Mode.C3_EVIDENCE_MEMORY: ModePolicy(True, False, True, False),
        C4Mode.C4_EVIDENCE_PLANNING: ModePolicy(True, False, False, True),
        C4Mode.C5_FULL_C4: ModePolicy(True, True, True, True),
        C4Mode.C5_MINUS_RAG: ModePolicy(True, False, True, True),
        C4Mode.C5_MINUS_MEMORY: ModePolicy(True, True, False, True),
        C4Mode.C5_MINUS_PLANNING: ModePolicy(True, True, True, False),
    }
)


@dataclass(frozen=True)
class PrimarySemanticInput:
    """The exact model-visible representation frozen by RQ2-V2."""

    current_query: str
    current_page: str
    dashboard_context: Any
    visible_conversation_history: tuple[Mapping[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        # Keep this key set exact. Compatibility Memory/RAG state is not added.
        return {
            "current_query": self.current_query,
            "current_page": self.current_page,
            "dashboard_context": self.dashboard_context,
            "visible_conversation_history": [dict(item) for item in self.visible_conversation_history],
        }


@dataclass(frozen=True)
class C4RealRequest:
    request_id: str
    scenario_id: str
    mode: C4Mode
    current_query: str
    current_page: str
    dashboard_context: Any
    visible_conversation_history: tuple[Mapping[str, Any], ...]
    student_id: str
    session_id: str
    state_reset_id: str
    execution_context: ExecutionContext = ExecutionContext.INTERACTIVE

    def __post_init__(self) -> None:
        if not isinstance(self.mode, C4Mode):
            object.__setattr__(self, "mode", C4Mode(self.mode))
        if not isinstance(self.execution_context, ExecutionContext):
            object.__setattr__(self, "execution_context", ExecutionContext(self.execution_context))
        object.__setattr__(
            self,
            "visible_conversation_history",
            tuple(dict(item) for item in self.visible_conversation_history),
        )
        for name in (
            "request_id",
            "scenario_id",
            "current_query",
            "current_page",
            "student_id",
            "session_id",
            "state_reset_id",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")

    @property
    def primary_input(self) -> PrimarySemanticInput:
        return PrimarySemanticInput(
            current_query=self.current_query,
            current_page=self.current_page,
            dashboard_context=self.dashboard_context,
            visible_conversation_history=self.visible_conversation_history,
        )

    @property
    def memory_scope(self) -> "MemoryScope":
        return MemoryScope(
            execution_context=self.execution_context,
            student_id=self.student_id,
            session_id=self.session_id,
            scenario_id=self.scenario_id,
            condition_id=self.mode.value,
            state_reset_id=self.state_reset_id,
        )


@dataclass(frozen=True)
class MemoryScope:
    """Complete isolation key; no component may silently drop a field."""

    execution_context: ExecutionContext
    student_id: str
    session_id: str
    scenario_id: str
    condition_id: str
    state_reset_id: str

    def key(self) -> tuple[str, ...]:
        return (
            self.execution_context.value,
            self.student_id,
            self.session_id,
            self.scenario_id,
            self.condition_id,
            self.state_reset_id,
        )


@dataclass(frozen=True)
class ClarificationDecision:
    needs_clarification: bool
    reason_code: str = "ANSWER"
    gate_id: str = CLARIFICATION_GATE_ID
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.needs_clarification) is not bool:
            raise TypeError("needs_clarification must be a bool")


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    content: Any
    evidence_strength: str = "DASHBOARD_OUTPUT_LEVEL"
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceSynthesisResult:
    items: tuple[EvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()
    status: str = "AVAILABLE"


@dataclass(frozen=True)
class CourseSource:
    source_id: str
    source_type: str
    content: Any
    document_title: str = ""
    week: str | None = None
    section: str | None = None
    evidence_strength: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CourseRAGResult:
    sources: tuple[CourseSource, ...] = ()
    limitations: tuple[str, ...] = ()
    result_status: str = "NO_RESULT"


@dataclass(frozen=True)
class MemoryItem:
    memory_id: str
    item_type: str
    value: Any
    provenance: str = ""
    version: int | None = None
    timestamp_version: Mapping[str, Any] = field(default_factory=dict)
    provenance_details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryReadResult:
    items: tuple[MemoryItem, ...] = ()
    limitations: tuple[str, ...] = ()
    status: str = "NO_MATCH"


@dataclass(frozen=True)
class CompiledEvidence:
    content: Any
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    compiled_evidence_sha256: str = ""
    deterministic_token_count: int = 0
    deterministic_token_budget: int = 0


@dataclass(frozen=True)
class PlannerResult:
    status: str
    plan: Any = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationResult:
    text: str
    generator_identity: str
    output_kind: str
    limitations: tuple[str, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_amount: float | None = None
    cost_currency: str = "USD"


@dataclass(frozen=True)
class GuardedOutput:
    text: str
    generator_identity: str
    output_kind: str
    limitations: tuple[str, ...] = ()
    guard_flags: tuple[str, ...] = ()


ALLOWED_LEARNER_FACT_SOURCES = frozenset(
    {"student_explicit", "dashboard_observation", "human_correction"}
)


@dataclass(frozen=True)
class MemoryWriteProposal:
    proposal_id: str
    item_type: str
    value: Any
    source_type: str
    status: str = "PENDING_HUMAN_CONFIRMATION"

    def validate_source(self) -> None:
        if self.source_type not in ALLOWED_LEARNER_FACT_SOURCES:
            raise ValueError(
                "Memory-write proposals may use only student, dashboard, or human-correction sources"
            )
        if self.status != "PENDING_HUMAN_CONFIRMATION":
            raise ValueError("C4_REAL_V1 may create proposals but may not auto-commit learner facts")


@dataclass(frozen=True)
class C4RealResult:
    success: bool
    output: GuardedOutput | None
    trace: Any
    memory_write_proposal: MemoryWriteProposal | None = None
    error: str = ""


@dataclass(frozen=True)
class C4GenerationPreparation:
    """Provider-neutral result produced before any response transport.

    The preparation contract intentionally retains the complete internal
    mechanism objects for audit while exposing a separately projected provider
    payload.  A preparation can never contain a generated answer or a target
    Memory-write proposal.
    """

    success: bool
    generation_ready: bool
    generation_sent: bool
    clarification: ClarificationDecision | None
    route: P3CapabilityRoute | None
    activation: ModuleActivation | None
    dashboard_evidence: EvidenceSynthesisResult | None
    course_rag: CourseRAGResult | None
    learner_memory: MemoryReadResult | None
    compiled_evidence: CompiledEvidence | None
    planner_result: PlannerResult | None
    provider_generation_payload: Mapping[str, Any]
    trace: Any
    deterministic_hashes: Mapping[str, str]
    error: str = ""


@runtime_checkable
class ClarificationGate(Protocol):
    identity: str

    def evaluate(self, primary_input: PrimarySemanticInput) -> ClarificationDecision: ...


@runtime_checkable
class P3Router(Protocol):
    """A live P3 decision source used only after separate execution authority."""

    identity: str

    def route(self, primary_input: PrimarySemanticInput) -> P3CapabilityRoute: ...


@runtime_checkable
class FrozenScenarioRouteProvider(Protocol):
    """Return one immutable scenario-level route by four-field semantic hash.

    Evaluation implementations must fail closed on a cache miss. Interactive
    implementations may delegate one miss to a separately authorised live P3
    router and cache that result for the request.
    """

    identity: str

    def route(self, primary_input: PrimarySemanticInput) -> P3CapabilityRoute: ...


@runtime_checkable
class EvidenceSynthesiser(Protocol):
    identity: str

    def synthesise(
        self, *, request: C4RealRequest, primary_input: PrimarySemanticInput
    ) -> EvidenceSynthesisResult: ...


@runtime_checkable
class CourseRAGProvider(Protocol):
    identity: str

    def retrieve(
        self,
        *,
        request: C4RealRequest,
        evidence: EvidenceSynthesisResult | None,
    ) -> CourseRAGResult: ...


@runtime_checkable
class LearnerMemoryProvider(Protocol):
    identity: str

    def is_enabled(self, scope: MemoryScope) -> bool: ...

    def read(self, *, scope: MemoryScope, request: C4RealRequest) -> MemoryReadResult: ...

    def propose_write(
        self,
        *,
        scope: MemoryScope,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        guarded_output: GuardedOutput,
        planner_result: PlannerResult | None,
    ) -> MemoryWriteProposal | None: ...

    def reset(self, scope: MemoryScope) -> None: ...

    def view(self, scope: MemoryScope) -> Sequence[MemoryItem]: ...

    def correct(self, scope: MemoryScope, memory_id: str, value: Any) -> None: ...

    def delete(self, scope: MemoryScope, memory_id: str) -> None: ...

    def set_enabled(self, scope: MemoryScope, enabled: bool) -> None: ...

    def clear_research_memory(self, student_id: str) -> None: ...


@runtime_checkable
class EvidenceCompiler(Protocol):
    identity: str

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
    ) -> CompiledEvidence: ...


@runtime_checkable
class RecommendationPlanner(Protocol):
    identity: str

    def plan(
        self, *, request: C4RealRequest, compiled_evidence: CompiledEvidence
    ) -> PlannerResult: ...


@runtime_checkable
class CommonGenerator(Protocol):
    identity: str

    def generate(
        self,
        *,
        request: C4RealRequest,
        clarification: ClarificationDecision,
        route: P3CapabilityRoute | None,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GenerationResult: ...


@runtime_checkable
class OutputGuard(Protocol):
    identity: str

    def apply(
        self,
        *,
        request: C4RealRequest,
        generated: GenerationResult,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GuardedOutput: ...


@dataclass(frozen=True)
class C4RealDependencies:
    clarification_gate: ClarificationGate
    p3_router: FrozenScenarioRouteProvider
    evidence_synthesiser: EvidenceSynthesiser
    course_rag: CourseRAGProvider
    learner_memory: LearnerMemoryProvider
    evidence_compiler: EvidenceCompiler
    planner: RecommendationPlanner
    generator: CommonGenerator
    output_guard: OutputGuard
    trace_sink: Any = field(default=None)

    @property
    def route_provider(self) -> FrozenScenarioRouteProvider:
        """Explicit alias retained while the Track-S field name stays stable."""

        return self.p3_router
