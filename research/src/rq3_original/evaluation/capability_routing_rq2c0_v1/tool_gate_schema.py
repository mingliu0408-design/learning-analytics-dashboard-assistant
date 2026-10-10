"""Research-only P2 schema contracts; no routing or tool execution occurs here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


RAG_STATUSES = ("SUPPORTED", "AMBIGUOUS", "UNSUPPORTED", "NO_RESULT")


@dataclass(frozen=True)
class ToolCandidatePlanV1:
    schema_version: str
    case_id: str
    p1_policy_id: str
    p1_required_capabilities: tuple[str, ...]
    rag_candidate: bool
    episodic_state_candidate: bool
    candidate_evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    forbidden_tools: tuple[str, ...] = ()
    clarification_blocks_execution: bool = False
    decision_trace: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in (
            "p1_required_capabilities",
            "forbidden_tools",
            "decision_trace",
        ):
            value[name] = list(value[name])
        value["candidate_evidence"] = {
            key: list(items) for key, items in self.candidate_evidence.items()
        }
        return value


@dataclass(frozen=True)
class RAGGateDecisionV1:
    candidate: bool
    retrieval_attempted: bool
    source_authorised: bool
    retrieval_status: str
    evidence_sufficiency: str
    supporting_chunk_count: int
    evidence_admitted_to_generation: bool
    clarification_required: bool
    failure_reason: str = ""

    def __post_init__(self) -> None:
        if self.supporting_chunk_count < 0:
            raise ValueError("supporting_chunk_count cannot be negative")
        if self.evidence_admitted_to_generation and (
            self.evidence_sufficiency != "SUPPORTED" or self.supporting_chunk_count < 1
        ):
            raise ValueError("Only supported evidence may enter generation")
        if self.clarification_required and self.evidence_admitted_to_generation:
            raise ValueError("Clarification blocks evidence admission")


@dataclass(frozen=True)
class MemoryUseGateDecisionV1:
    candidate: bool
    working_context_available: bool
    state_use_required: bool
    additional_retrieval_required: bool
    memory_query_attempted: bool
    candidate_item_count: int
    relevant_item_count: int
    stale_item_count: int
    superseded_item_count: int
    state_admitted_to_generation: bool
    clarification_required: bool
    failure_reason: str = ""

    def __post_init__(self) -> None:
        counts = (
            self.candidate_item_count,
            self.relevant_item_count,
            self.stale_item_count,
            self.superseded_item_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Memory item counts cannot be negative")
        if self.relevant_item_count > self.candidate_item_count:
            raise ValueError("Relevant items cannot exceed candidates")
        if self.clarification_required and self.state_admitted_to_generation:
            raise ValueError("Clarification blocks state admission")


@dataclass(frozen=True)
class P2ExecutionPlanV1:
    p1_plan_immutable: bool
    rag_gate: RAGGateDecisionV1
    memory_gate: MemoryUseGateDecisionV1
    dashboard_evidence_allowed: bool
    planning_allowed: bool
    safe_direct_response: bool
    clarification: bool
    execution_trace: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.p1_plan_immutable:
            raise ValueError("P1 plan must remain immutable")
        if self.clarification and any(
            (
                self.rag_gate.retrieval_attempted,
                self.rag_gate.evidence_admitted_to_generation,
                self.memory_gate.state_admitted_to_generation,
                self.dashboard_evidence_allowed,
                self.planning_allowed,
            )
        ):
            raise ValueError("Clarification must block all execution")


def schema_contract() -> dict[str, Any]:
    schemas = {}
    for cls in (
        ToolCandidatePlanV1,
        RAGGateDecisionV1,
        MemoryUseGateDecisionV1,
        P2ExecutionPlanV1,
    ):
        schemas[cls.__name__] = {
            "fields": list(cls.__dataclass_fields__),
            "research_only": True,
            "production_namespace": False,
        }
    return {
        "schema_version": "tool-gate-schema-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "schemas": schemas,
        "invariants": [
            "P1_PLAN_IMMUTABLE",
            "CLARIFICATION_BLOCKS_EXECUTION",
            "ONLY_SUPPORTED_EVIDENCE_ADMITTED",
            "STALE_OR_SUPERSEDED_STATE_NEVER_ADMITTED",
            "NO_GOLD_FIELDS_IN_DECISIONS",
        ],
        "production_integration": False,
        "p2_implemented": False,
    }
