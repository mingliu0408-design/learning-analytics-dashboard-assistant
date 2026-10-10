"""Research-only P1 ContextEnvelope-to-CapabilityPlan router."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from evaluation.capability_routing_v1.capability_schema import (
    CapabilityPlanV1,
    build_capability_plan,
)
from evaluation.capability_routing_v1.context_envelope import (
    ContextEnvelopeV1,
    build_context_envelope,
)
import utils.c_full_service as production_service

from . import CAPABILITIES, EXECUTION_CAPABILITIES, P1_IDENTITY, capability_order
from .c0_full_score_vector import score_c0_full_vector
from .capability_evidence import (
    build_deterministic_capability_evidence,
    build_semantic_capability_evidence,
    detect_existing_need_signals,
    merge_capability_evidence,
)
from .context_status import derive_context_status
from .gold_preflight import RoutingCaseInput
from .p1_policy_family import policy_from_id, validate_capability_plan


def _effective_query(memory_runtime: Any, normalised_query: str) -> str:
    resolution = memory_runtime.memory_resolution
    if resolution is None:
        raise RuntimeError("BLOCKED_RQ2_B_CONTEXT_STATUS: absent Memory resolution")
    return (
        str(resolution.resolved_query).strip()
        if resolution.resolved and str(resolution.resolved_query).strip()
        else str(normalised_query).strip()
    )


def _selected_route_for_memory_parity(memory_runtime: Any, c0_row: Mapping[str, Any]) -> str:
    resolution = memory_runtime.memory_resolution
    resolution_type = str(getattr(resolution, "resolution_type", "") or "")
    if resolution_type in {"memory_state_query", "no_active_plan"}:
        return "memory_state_direct_answer"
    if bool(getattr(resolution, "resolved", False)):
        return "memory_resolved_follow_up"
    return str(c0_row.get("production_selected_intent") or "")


def _envelope(
    case: RoutingCaseInput,
    *,
    memory_runtime: Any,
    resolved_query: str,
    context_required: bool,
    source_restrictions: Mapping[str, Any],
) -> ContextEnvelopeV1:
    state = dict(memory_runtime.structured_memory or {})
    explicit_constraints = list(state.get("constraints") or [])
    restrictions: list[str] = []
    allowed = list(source_restrictions.get("allowed_source_types") or [])
    excluded = list(source_restrictions.get("excluded_source_types") or [])
    if allowed != ["memory", "dashboard", "course_material"]:
        restrictions.extend(f"allow:{value}" for value in allowed)
    restrictions.extend(f"exclude:{value}" for value in excluded)
    base = build_context_envelope(
        case_id=case.case_id,
        original_query=case.current_query,
        current_page=case.current_page,
        conversation_history=case.conversation_history,
        structured_memory=state,
        explicit_constraints=explicit_constraints,
        explicit_source_restrictions=restrictions,
        context_resolution_required=context_required,
    )
    referenced = tuple(memory_runtime.referenced_items or ())
    sources = list(base.context_sources)
    provenance = [dict(row) for row in base.context_provenance]
    if referenced and "referenced_action" not in sources:
        sources.append("referenced_action")
        provenance.append(
            {"source": "referenced_action", "active": True, "item_count": len(referenced)}
        )
    return replace(
        base,
        resolved_query=resolved_query,
        referenced_items=referenced or base.referenced_items,
        context_resolution_required=context_required,
        context_sources=tuple(sources),
        context_provenance=tuple(provenance),
    )


def _final_capabilities(
    merged: tuple[str, ...], *, clarification_required: bool,
    deterministic_forbidden: tuple[str, ...],
) -> tuple[str, ...]:
    if clarification_required:
        return ("clarification",)
    active = set(merged) - {"clarification", *deterministic_forbidden}
    if active & set(EXECUTION_CAPABILITIES):
        active.discard("safe_direct_response")
    else:
        active = {"safe_direct_response"}
    return capability_order(active)


def _source_forbidden_capabilities(
    source_restrictions: Mapping[str, Any],
) -> tuple[str, ...]:
    """Map only production-detected source exclusions to Capability exclusions."""

    excluded = set(source_restrictions.get("excluded_source_types") or ())
    forbidden: list[str] = []
    if "dashboard" in excluded:
        forbidden.append("dashboard_evidence")
    if "course_material" in excluded:
        forbidden.append("course_retrieval")
    if "memory" in excluded:
        forbidden.append("episodic_memory")
    return capability_order(forbidden)


def _complete_plan(
    *,
    case_id: str,
    required: tuple[str, ...],
    deterministic_forbidden: tuple[str, ...],
    context_required: bool,
    clarification_reason: str,
    semantic: Any,
    evidence: Mapping[str, tuple[str, ...]],
    source_restrictions: Mapping[str, Any],
    policy_id: str,
) -> CapabilityPlanV1:
    base = build_capability_plan(
        case_id=case_id,
        required_capabilities=required,
        forbidden_capabilities=deterministic_forbidden,
        context_resolution_required=context_required,
        clarification_reason=clarification_reason,
        source_policy={
            "policy_id": policy_id,
            "allowed_source_types": list(
                source_restrictions.get("allowed_source_types") or []
            ),
            "excluded_source_types": list(
                source_restrictions.get("excluded_source_types") or []
            ),
        },
        decision_trace=(
            "production_context_resolution",
            "frozen_c0_full_score_vector",
            "frozen_intent_capability_seed_map",
            "existing_deterministic_need_signals",
            "clarification_and_safe_direct_exclusivity",
        ),
    )
    scores = {
        name: semantic.maximum_mapped_intent_score.get(name) for name in CAPABILITIES
    }
    if "clarification" in required:
        plan_evidence = {"clarification": (clarification_reason,)}
    elif required == ("safe_direct_response",):
        plan_evidence = {
            "safe_direct_response": tuple(
                evidence.get("safe_direct_response") or ("no_execution_capability",)
            )
        }
    else:
        plan_evidence = {name: tuple(evidence.get(name) or ()) for name in required}
    return replace(base, capability_scores=scores, capability_evidence=plan_evidence)


def route_p1_case(
    case: RoutingCaseInput,
    *,
    policy_id: str,
    semantic_runtime: Any,
) -> dict[str, Any]:
    """Route one case without admitting any Gold or split metadata as a feature."""

    policy = policy_from_id(policy_id)
    (
        normalised_query,
        query_normalisations,
        query_normalisation_diagnostics,
    ) = production_service._normalise_c_full_query_detailed(
        case.current_query,
        current_page=case.current_page,
        enable_p2a_extensions=True,
    )
    memory_runtime = production_service.prepare_mode_cm_context(
        student_query=normalised_query,
        conversation_history=list(case.conversation_history),
        existing_session_memory=None,
        current_page=case.current_page,
        transactional_course_corrections=True,
        enable_p2a_extensions=True,
    )
    effective_query = _effective_query(memory_runtime, normalised_query)
    need_signals = detect_existing_need_signals(
        effective_query,
        current_page=case.current_page,
        structured_memory=memory_runtime.structured_memory,
    )
    resolution = memory_runtime.memory_resolution
    deterministic_ambiguity = bool(
        resolution is not None
        and not resolution.resolved
        and production_service._is_underspecified_without_context(case.current_query)
        and not production_service._is_natural_course_coverage_query(normalised_query)
    )
    status = derive_context_status(
        memory_runtime,
        deterministic_ambiguity_guard=deterministic_ambiguity,
        discrepancy_correction_need=need_signals.discrepancy_correction_need,
    )
    source_restrictions = production_service.detect_source_restrictions(
        normalised_query, enable_p2a_extensions=True
    )
    deterministic_forbidden = _source_forbidden_capabilities(source_restrictions)
    envelope = _envelope(
        case,
        memory_runtime=memory_runtime,
        resolved_query=effective_query,
        context_required=status.context_resolution_required_prediction,
        source_restrictions=source_restrictions,
    )
    c0_row = score_c0_full_vector(
        effective_query,
        case.current_page,
        review_case_id=case.case_id,
        runtime=semantic_runtime,
    )
    selected_intents = policy.select_intents(c0_row["eligible_ranking"])
    score_by_intent = {
        str(row["intent_id"]): float(row["score"])
        for row in c0_row["intent_axes"]
        if bool(row["eligible"])
    }
    semantic = build_semantic_capability_evidence(
        intent_scores=score_by_intent,
        selected_intents=selected_intents,
        policy_id=policy_id,
    )
    selected_route = _selected_route_for_memory_parity(memory_runtime, c0_row)
    deterministic = build_deterministic_capability_evidence(
        need_signals=need_signals,
        memory_runtime=memory_runtime,
        selected_route=selected_route,
    )
    merged, evidence = merge_capability_evidence(semantic, deterministic)
    required = _final_capabilities(
        merged,
        clarification_required=status.clarification_required,
        deterministic_forbidden=deterministic_forbidden,
    )
    plan = _complete_plan(
        case_id=case.case_id,
        required=required,
        deterministic_forbidden=deterministic_forbidden,
        context_required=status.context_resolution_required_prediction,
        clarification_reason=status.clarification_reason,
        semantic=semantic,
        evidence=evidence,
        source_restrictions=source_restrictions,
        policy_id=policy_id,
    )
    safety = validate_capability_plan(required)
    if any(safety.values()):
        raise RuntimeError("BLOCKED_RQ2_B_POLICY_FAMILY: invalid CapabilityPlan")
    return {
        "schema_version": "rq2b-p1-local-prediction-v1",
        "review_case_id": case.case_id,
        "router_identity": P1_IDENTITY,
        "policy_id": policy_id,
        "predicted_capabilities": list(plan.required_capabilities),
        "context_resolution_required_prediction": (
            status.context_resolution_required_prediction
        ),
        "context_status": status.to_dict(),
        "context_envelope": envelope.to_dict(),
        "capability_plan": plan.to_dict(),
        "semantic_evidence": semantic.to_dict(),
        "deterministic_evidence": deterministic.to_dict(),
        "deterministic_forbidden_capabilities": list(deterministic_forbidden),
        "query_normalisation_count": len(query_normalisations),
        "query_normalisation_diagnostic_count": len(
            query_normalisation_diagnostics
        ),
        "selected_route_for_memory_parity": selected_route,
        "c0_score_vector": c0_row,
        "production_function_call_counts": {
            "prepare_mode_cm_context": 1,
            "detect_c_full_need_signals": 1,
            "c0_full_predict": 1,
            "c0_default_predict": 1,
            "route_production_intent": 1,
        },
        "clarification_triggered_by_semantic_uncertain_only": False,
        "gold_feature_used": False,
        "scenario_family_used_as_feature": False,
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
    }


def prediction_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the minimal local prediction surface used by metrics."""

    return {
        "review_case_id": str(row["review_case_id"]),
        "predicted_capabilities": list(row["predicted_capabilities"]),
        "context_resolution_required_prediction": bool(
            row["context_resolution_required_prediction"]
        ),
        "policy_id": str(row["policy_id"]),
    }
