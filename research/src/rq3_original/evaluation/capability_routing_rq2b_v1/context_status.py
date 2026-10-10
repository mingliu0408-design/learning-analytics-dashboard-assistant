"""Research-only mapping of production Memory output to P1 context state.

The mapping in this module consumes only the output of the existing
``prepare_mode_cm_context`` stage.  It does not inspect Capability Gold and it
does not add a second follow-up detector.  The separate deterministic-
ambiguity flag exists so the caller can reuse the production ambiguity guard
without pretending that the Memory resolver successfully resolved a referent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from utils.conversation_memory import MemoryResolution, MemoryRuntimeResult

from . import RQ2BError


ContextStatus = Literal[
    "NOT_REQUIRED",
    "RESOLVED",
    "MISSING_REQUIRED_CONTEXT",
]

NOT_REQUIRED: ContextStatus = "NOT_REQUIRED"
RESOLVED: ContextStatus = "RESOLVED"
MISSING_REQUIRED_CONTEXT: ContextStatus = "MISSING_REQUIRED_CONTEXT"

# Some production outcomes deliberately return ``resolved=True`` because the
# resolved query is an instruction to state a boundary or ask a clarification.
# They are not usable resolved referents for capability routing.
MISSING_RESOLUTION_TYPES = frozenset(
    {
        "no_active_plan",
        "course_entity_ambiguous",
        "unsupported_course_week",
        "follow_up_without_context",
        "underspecified_without_context",
    }
)
MISSING_MEMORY_CONTEXT_FLAGS = frozenset(
    {
        "no_active_plan",
        "state_reference_ambiguous",
    }
)


@dataclass(frozen=True)
class ContextStatusDecision:
    """Auditable, text-free P1 context decision."""

    status: ContextStatus
    context_resolution_required_prediction: bool
    clarification_required: bool
    clarification_reason: str
    resolver_is_follow_up: bool
    resolver_resolved: bool
    resolution_type: str
    missing_markers: tuple[str, ...]
    deterministic_ambiguity_guard: bool
    discrepancy_correction_need: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "context_resolution_required_prediction": (
                self.context_resolution_required_prediction
            ),
            "clarification_required": self.clarification_required,
            "clarification_reason": self.clarification_reason,
            "resolver_is_follow_up": self.resolver_is_follow_up,
            "resolver_resolved": self.resolver_resolved,
            "resolution_type": self.resolution_type,
            "missing_markers": list(self.missing_markers),
            "deterministic_ambiguity_guard": self.deterministic_ambiguity_guard,
            "discrepancy_correction_need": self.discrepancy_correction_need,
        }


def _resolution_from_runtime(
    value: MemoryRuntimeResult | MemoryResolution,
) -> MemoryResolution:
    if isinstance(value, MemoryResolution):
        return value
    if not isinstance(value, MemoryRuntimeResult):
        raise RQ2BError("BLOCKED_RQ2_B_CONTEXT_STATUS: invalid Memory runtime")
    if value.memory_resolution is None:
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: Memory resolution is absent"
        )
    return value.memory_resolution


def _missing_markers(resolution: MemoryResolution) -> tuple[str, ...]:
    markers: list[str] = []
    context: Mapping[str, Any] = resolution.memory_context or {}
    resolution_type = str(resolution.resolution_type or "")
    if resolution.is_follow_up and not resolution.resolved:
        markers.append("unresolved_follow_up")
    if resolution_type in MISSING_RESOLUTION_TYPES:
        markers.append(f"resolution_type:{resolution_type}")
    for flag in sorted(MISSING_MEMORY_CONTEXT_FLAGS):
        if bool(context.get(flag)):
            markers.append(f"memory_context:{flag}")
    return tuple(markers)


def derive_context_status(
    memory_runtime: MemoryRuntimeResult | MemoryResolution,
    *,
    deterministic_ambiguity_guard: bool = False,
    discrepancy_correction_need: bool = False,
) -> ContextStatusDecision:
    """Map production Memory output to the frozen three-state P1 contract.

    ``discrepancy_correction_need`` is the already-existing C_FULL Need Signal
    mandated by the RQ2-B contract.  It may mark context resolution as required,
    but it does not rewrite the resolver's three-state outcome.  Likewise, the
    existing deterministic ambiguity guard may require clarification without
    being misreported as a successful Memory resolution.
    """

    resolution = _resolution_from_runtime(memory_runtime)
    missing = _missing_markers(resolution)
    if missing:
        status: ContextStatus = MISSING_REQUIRED_CONTEXT
    elif resolution.is_follow_up and resolution.resolved:
        status = RESOLVED
    else:
        status = NOT_REQUIRED

    context_required = bool(
        status != NOT_REQUIRED or discrepancy_correction_need
    )
    clarification = bool(
        status == MISSING_REQUIRED_CONTEXT or deterministic_ambiguity_guard
    )
    if status == MISSING_REQUIRED_CONTEXT:
        clarification_reason = "MISSING_REQUIRED_CONTEXT"
    elif deterministic_ambiguity_guard:
        clarification_reason = "EXISTING_DETERMINISTIC_AMBIGUITY_GUARD"
    else:
        clarification_reason = ""

    decision = ContextStatusDecision(
        status=status,
        context_resolution_required_prediction=context_required,
        clarification_required=clarification,
        clarification_reason=clarification_reason,
        resolver_is_follow_up=bool(resolution.is_follow_up),
        resolver_resolved=bool(resolution.resolved),
        resolution_type=str(resolution.resolution_type or ""),
        missing_markers=missing,
        deterministic_ambiguity_guard=bool(deterministic_ambiguity_guard),
        discrepancy_correction_need=bool(discrepancy_correction_need),
    )
    validate_context_status_decision(decision)
    return decision


def validate_context_status_decision(decision: ContextStatusDecision) -> None:
    if decision.status not in {NOT_REQUIRED, RESOLVED, MISSING_REQUIRED_CONTEXT}:
        raise RQ2BError("BLOCKED_RQ2_B_CONTEXT_STATUS: unknown context status")
    if decision.status == RESOLVED and not (
        decision.resolver_is_follow_up and decision.resolver_resolved
    ):
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: RESOLVED lacks resolver evidence"
        )
    if decision.status == MISSING_REQUIRED_CONTEXT and not decision.missing_markers:
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: missing state lacks a production marker"
        )
    if decision.status == MISSING_REQUIRED_CONTEXT and not decision.clarification_required:
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: missing context must clarify"
        )
    if decision.context_resolution_required_prediction is False and (
        decision.status != NOT_REQUIRED or decision.discrepancy_correction_need
    ):
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: required prediction was suppressed"
        )


# Descriptive alias for callers that prefer an explicit production-runtime name.
context_status_from_production_memory = derive_context_status
