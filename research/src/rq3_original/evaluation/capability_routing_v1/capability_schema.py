"""Frozen research schemas for multi-label capability plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from . import DETERMINISTIC_GUARDS, PREDICTED_CAPABILITIES, RQ1_FINAL_ROUTER


class CapabilitySchemaError(ValueError):
    pass


EXECUTABLE_CAPABILITIES = frozenset(
    {"dashboard_evidence", "course_retrieval", "episodic_memory", "planning"}
)
DIRECT_OR_CLARIFICATION = frozenset({"safe_direct_response", "clarification"})


@dataclass(frozen=True)
class CapabilityPlanV1:
    schema_version: str
    case_id: str
    required_capabilities: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...]
    context_resolution_required: bool
    capability_scores: Mapping[str, float | None] = field(default_factory=dict)
    capability_evidence: Mapping[str, Sequence[str]] = field(default_factory=dict)
    clarification_required: bool = False
    clarification_reason: str = ""
    deterministic_guard_state: Mapping[str, str] = field(default_factory=dict)
    source_policy: Mapping[str, Any] = field(default_factory=dict)
    router_identity: str = RQ1_FINAL_ROUTER
    decision_trace: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != "capability-plan-v1":
            raise CapabilitySchemaError("CapabilityPlanV1 schema version mismatch")
        if not self.case_id.strip():
            raise CapabilitySchemaError("case_id is required")
        required = tuple(dict.fromkeys(self.required_capabilities))
        forbidden = tuple(dict.fromkeys(self.forbidden_capabilities))
        if required != self.required_capabilities or forbidden != self.forbidden_capabilities:
            raise CapabilitySchemaError("capability lists must be unique and ordered")
        universe = set(PREDICTED_CAPABILITIES)
        if not set(required) <= universe or not set(forbidden) <= universe:
            raise CapabilitySchemaError("capability outside frozen predicted universe")
        if set(required) & set(forbidden):
            raise CapabilitySchemaError("required and forbidden capabilities overlap")
        if not required:
            raise CapabilitySchemaError("empty CapabilityPlan is forbidden")
        if "clarification" in required:
            if required != ("clarification",) or not self.clarification_required:
                raise CapabilitySchemaError("clarification must be exclusive")
        elif self.clarification_required:
            raise CapabilitySchemaError("clarification flag lacks clarification capability")
        if "safe_direct_response" in required and len(required) != 1:
            raise CapabilitySchemaError("safe direct response is exclusive")
        if self.router_identity != RQ1_FINAL_ROUTER:
            raise CapabilitySchemaError("only the frozen C0 Router identity is allowed")
        if set(self.deterministic_guard_state) - set(DETERMINISTIC_GUARDS):
            raise CapabilitySchemaError("unknown deterministic guard")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_capabilities"] = list(self.required_capabilities)
        value["forbidden_capabilities"] = list(self.forbidden_capabilities)
        value["decision_trace"] = list(self.decision_trace)
        value["capability_evidence"] = {
            key: list(items) for key, items in self.capability_evidence.items()
        }
        return value


def build_capability_plan(
    *,
    case_id: str,
    required_capabilities: Sequence[str],
    forbidden_capabilities: Sequence[str] = (),
    context_resolution_required: bool = False,
    clarification_reason: str = "",
    deterministic_guard_state: Mapping[str, str] | None = None,
    source_policy: Mapping[str, Any] | None = None,
    decision_trace: Sequence[str] = (),
) -> CapabilityPlanV1:
    required = tuple(dict.fromkeys(str(value) for value in required_capabilities))
    return CapabilityPlanV1(
        schema_version="capability-plan-v1",
        case_id=case_id,
        required_capabilities=required,
        forbidden_capabilities=tuple(
            dict.fromkeys(str(value) for value in forbidden_capabilities)
        ),
        context_resolution_required=bool(context_resolution_required),
        capability_scores={name: None for name in PREDICTED_CAPABILITIES},
        capability_evidence={name: () for name in required},
        clarification_required="clarification" in required,
        clarification_reason=str(clarification_reason),
        deterministic_guard_state=dict(deterministic_guard_state or {}),
        source_policy=dict(source_policy or {}),
        router_identity=RQ1_FINAL_ROUTER,
        decision_trace=tuple(str(value) for value in decision_trace),
    )


def capability_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "capability-schema-v1",
        "stage": "RQ2-A",
        "status": "FROZEN_RESEARCH_ONLY",
        "semantic_distinction": {
            "intent": "DESCRIPTIVE_SEMANTIC_RANKING_TARGET",
            "capability": "EXECUTABLE_SYSTEM_REQUIREMENT",
            "one_to_one_mapping_forbidden": True,
            "multi_label_allowed": True,
        },
        "predicted_capabilities": list(PREDICTED_CAPABILITIES),
        "executable_capabilities": sorted(EXECUTABLE_CAPABILITIES),
        "deterministic_guards": list(DETERMINISTIC_GUARDS),
        "deterministic_guards_are_predicted_capabilities": False,
        "working_context_is_capability": False,
        "clarification_exclusive_with_all_other_capabilities": True,
        "safe_direct_response_exclusive_with_executable_capabilities": True,
        "safe_direct_response_exclusive_with_all_other_capabilities": True,
        "empty_plan_allowed": False,
        "capability_implies_data_access_authority": False,
        "course_retrieval_requires_evidence_sufficiency_gate": True,
        "episodic_memory_requires_relevance_active_and_stale_state_gates": True,
        "router_identity": RQ1_FINAL_ROUTER,
        "production_router_implemented": False,
    }
