"""Frozen M0/M1/M2 session-state candidate and admission composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from evaluation.capability_routing_rq2c0_v1.memory_use_gate_contract import (
    MEMORY_POLICY_IDS,
    MemoryCandidateSignals,
    StateItemStatus,
    memory_candidate,
    state_item_admissible,
)


@dataclass(frozen=True)
class SessionStateInput:
    case_id: str
    p1_clarification: bool
    signals: MemoryCandidateSignals


@dataclass(frozen=True)
class SessionStateResult:
    case_id: str
    policy_id: str
    candidate: bool
    state_object_present: bool
    state_admitted: bool
    execution_blocked_by_clarification: bool
    persistent_store_access_count: int


def session_input_from_p1(row: Mapping[str, Any]) -> SessionStateInput:
    envelope = dict(row.get("context_envelope") or {})
    status = dict(row.get("context_status") or {})
    evidence = dict(row.get("deterministic_evidence") or {})
    needs = dict(evidence.get("need_signals") or {})
    predicted = set(str(value) for value in row.get("predicted_capabilities", ()))
    active_plan = envelope.get("active_plan")
    completion_present = bool(
        isinstance(active_plan, Mapping)
        and str(active_plan.get("status", "")).upper() == "COMPLETED"
    )
    signals = MemoryCandidateSignals(
        p1_episodic_memory="episodic_memory" in predicted,
        resolver_is_follow_up=bool(status.get("resolver_is_follow_up")),
        resolver_resolved=bool(status.get("resolver_resolved")),
        active_goal_present=bool(envelope.get("active_goal")),
        active_plan_present=bool(active_plan),
        constraint_present=bool(envelope.get("explicit_constraints")),
        correction_present=bool(envelope.get("latest_correction")),
        completion_present=completion_present,
        referenced_item_present=bool(envelope.get("referenced_items")),
        plan_memory_need=bool(needs.get("plan_memory_need")),
        discrepancy_correction_need=bool(needs.get("discrepancy_correction_need")),
        missing_context=str(status.get("status")) == "MISSING_REQUIRED_CONTEXT",
    )
    return SessionStateInput(
        case_id=str(row["review_case_id"]),
        p1_clarification="clarification" in predicted
        or bool((row.get("capability_plan") or {}).get("clarification_required")),
        signals=signals,
    )


def run_session_state_gate(
    value: SessionStateInput, policy_id: str
) -> SessionStateResult:
    if policy_id not in MEMORY_POLICY_IDS:
        raise ValueError("unknown frozen session policy")
    candidate = memory_candidate(policy_id, value.signals)
    blocked = value.p1_clarification
    state_status = StateItemStatus(
        belongs_to_current_scope=True,
        active=value.signals.state_object_present,
        completed=False,
        cancelled=False,
        superseded=False,
        stale=False,
        directly_supports_current_need=candidate and value.signals.state_object_present,
    )
    admitted = bool(
        candidate
        and not blocked
        and value.signals.state_object_present
        and state_item_admissible(state_status)
    )
    return SessionStateResult(
        case_id=value.case_id,
        policy_id=policy_id,
        candidate=candidate,
        state_object_present=value.signals.state_object_present,
        state_admitted=admitted,
        execution_blocked_by_clarification=blocked and candidate,
        persistent_store_access_count=0,
    )
