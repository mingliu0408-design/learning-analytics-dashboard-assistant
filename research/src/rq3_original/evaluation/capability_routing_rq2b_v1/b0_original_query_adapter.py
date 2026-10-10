"""True original-query-only B0 adapter for the RQ2-B offline experiment.

``build_c_full_context`` cannot be used for B0 because it unconditionally
calls ``prepare_mode_cm_context``.  This research-only adapter therefore
composes the existing production normalisation, C0 routing, evidence, source-
scope, and Planner functions while exposing no history or structured-Memory
argument.  Capability projection is delegated to the existing Legacy
measurement projection rather than copied here.
"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import re
from typing import Any, Mapping
from unittest.mock import patch

from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
    _deterministic_guards,
    _project_capabilities,
    provider_free_environment,
)
from utils.intent_schema import FUTURE_SCOPE_OUTCOMES
import utils.c_full_service as production_service
import utils.production_intent_router as production_router

from . import B0_IDENTITY, RQ1_FINAL_ROUTER, RQ2BError


COUNTED_PRODUCTION_FUNCTIONS = (
    "detect_c_full_need_signals",
    "authoritative_c_full_query_type",
    "route_production_intent",
    "build_rq1_evidence_summary",
    "decide_c_full_source_scope",
    "build_recommendation_plan",
)
FORBIDDEN_B0_CALLS = (
    "build_c_full_context",
    "prepare_mode_cm_context",
)


def _forbidden_b0_call(name: str) -> Any:
    raise RQ2BError(
        "BLOCKED_RQ2_B_B0_IMPLEMENTATION: B0 called forbidden production "
        f"function {name}"
    )


def _hash_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _intent_routing_payload(intent_decision: Any, query_type: str) -> dict[str, Any]:
    routing = intent_decision.to_dict()
    routing["adapter_selected_intent"] = intent_decision.selected_intent
    routing["selected_intent"] = str(query_type)
    routing["semantic_effective"] = bool(
        intent_decision.semantic_accepted
        and str(query_type) == intent_decision.selected_intent
    )
    if str(query_type) != intent_decision.selected_intent:
        prior_reason = str(routing.get("fallback_reason") or "")
        routing["routing_source"] = "deterministic_guard"
        routing["fallback_reason"] = ";".join(
            part
            for part in (prior_reason, "downstream_authoritative_override")
            if part
        )
    return routing


def _special_outcome_context(
    *,
    outcome: str,
    intent_decision: Any,
    current_page: str,
) -> dict[str, Any]:
    selected_route = "ambiguous_clarification" if outcome == "ambiguous" else outcome
    return {
        "query_type": outcome,
        "selected_route": selected_route,
        "intent_routing": _intent_routing_payload(intent_decision, outcome),
        "rq1_selected_sources": [],
        "rq1_evidence_summary": {
            "selected_sources": [],
            "selected_evidence": {},
        },
        "allowed_source_types": [],
        "source_scope": "no_supported_source",
        "source_scope_decision": {
            "scope": "no_supported_source",
            "retrieval_required": False,
            "preserve_dashboard_evidence": False,
        },
        "retrieval_requested": False,
        "retrieval_used": False,
        "rq2_recommendation_plan": {},
        "current_page": str(current_page),
        "memory_resolution": {},
    }


def _build_original_query_context(
    *,
    original_query: str,
    current_page: str,
    student_id: str,
    semantic_runtime: Any,
    dashboard_data: Any,
) -> dict[str, Any]:
    """Compose the production no-Memory decision path from existing functions."""

    routing_mode = production_router.resolve_intent_router_mode(
        production_router.SEMANTIC_ENHANCED
    )
    enable_p2a_extensions = routing_mode == production_router.SEMANTIC_ENHANCED
    original_query = str(original_query or "").strip()
    (
        normalised_query,
        query_normalisations,
        query_normalisation_diagnostics,
    ) = production_service._normalise_c_full_query_detailed(
        original_query,
        current_page=str(current_page),
        enable_p2a_extensions=enable_p2a_extensions,
    )
    guarded_week_candidate = (
        production_service.unresolved_explicit_week_guard_candidate(
            original_query,
            query_normalisation_diagnostics,
            query_normalisations,
            enable_p2a_extensions=enable_p2a_extensions,
        )
    )
    unsupported_week_reference = bool(
        guarded_week_candidate
        or any(
            diagnostic.get("supported_week") is False
            for diagnostic in query_normalisation_diagnostics
        )
    )

    source_restrictions = production_service.detect_source_restrictions(
        normalised_query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    original_target_domain = (
        production_service.detect_dashboard_application_target(normalised_query)
        or production_service.detect_explicit_target_domain(normalised_query)
    )
    try:
        current_page_domain = production_service.normalise_page(current_page)
    except ValueError:
        current_page_domain = "overview"
    resolved_target_domain = original_target_domain or current_page_domain
    evidence_page = production_service.PAGE_DISPLAY.get(
        resolved_target_domain, str(current_page)
    )

    need_signals = production_service.detect_c_full_need_signals(
        normalised_query,
        current_page=str(current_page),
        active_course_item={},
        enable_p2a_extensions=enable_p2a_extensions,
    )
    forced_query_type = production_service.authoritative_c_full_query_type(
        normalised_query,
        need_signals,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    deterministic_ambiguity = bool(
        production_service._is_underspecified_without_context(original_query)
        and not production_service._is_natural_course_coverage_query(
            normalised_query
        )
    )
    intent_guard_reasons: list[str] = []
    if unsupported_week_reference:
        intent_guard_reasons.append("week_validation_fail_closed")
    if (
        source_restrictions["allowed_source_types"]
        != ["memory", "dashboard", "course_material"]
        or source_restrictions["excluded_source_types"]
    ):
        intent_guard_reasons.append("explicit_source_restriction")
    if (
        forced_query_type
        and production_service.classify_query_detailed(normalised_query).rule_id
        == "UNMATCHED_DEFAULT"
    ):
        intent_guard_reasons.append(
            f"authoritative_c_full_type:{forced_query_type}"
        )
    if production_service._is_page_local_dashboard_priority(normalised_query):
        intent_guard_reasons.append("page_local_dashboard_priority")
    if deterministic_ambiguity:
        intent_guard_reasons.append("underspecified_without_context")

    intent_decision = production_service.route_production_intent(
        normalised_query,
        current_page=evidence_page,
        mode=production_router.SEMANTIC_ENHANCED,
        protected_guard_reasons=intent_guard_reasons,
        semantic_runtime=semantic_runtime,
    )
    special_outcome = (
        intent_decision.selected_intent
        if intent_decision.selected_intent
        in {*FUTURE_SCOPE_OUTCOMES, "semantic_uncertain"}
        else ""
    )
    if not special_outcome and deterministic_ambiguity:
        special_outcome = "ambiguous"
    if special_outcome:
        return _special_outcome_context(
            outcome=special_outcome,
            intent_decision=intent_decision,
            current_page=current_page,
        )

    scenario_for_evidence = {
        "student_query": normalised_query,
        "student_id": str(student_id),
        "page": evidence_page,
        "resolved_target_domain": resolved_target_domain,
        "query_type_override": intent_decision.selected_intent,
    }
    evidence_result = production_service.build_rq1_evidence_summary(
        scenario_for_evidence, dashboard_data
    )
    query_type = str(
        evidence_result.get("query_type")
        or production_service.classify_query(normalised_query)
    )
    if forced_query_type:
        query_type = forced_query_type
        evidence_result = production_service.build_rq1_evidence_summary(
            {**scenario_for_evidence, "query_type_override": forced_query_type},
            dashboard_data,
        )
    if (
        production_service._is_page_local_dashboard_priority(normalised_query)
        and query_type == "improvement_recommendation"
    ):
        query_type = "dashboard_interpretation"
        evidence_result = production_service.build_rq1_evidence_summary(
            {**scenario_for_evidence, "query_type_override": query_type},
            dashboard_data,
        )

    course_only_planning_requested = bool(
        source_restrictions["allowed_source_types"] == ["course_material"]
        and production_service._is_course_only_planning_query(
            normalised_query,
            enable_p2a_extensions=enable_p2a_extensions,
        )
    )
    if course_only_planning_requested:
        query_type = "hybrid_course_and_planning"
    elif need_signals.hybrid_need:
        query_type = "hybrid_course_and_planning"
    elif need_signals.course_content_need and not need_signals.dashboard_activity_need:
        query_type = "course_content_question"
    evidence_result["query_type"] = query_type
    if (
        source_restrictions["allowed_source_types"] == ["course_material"]
        and query_type != "hybrid_course_and_planning"
    ):
        query_type = "course_content_question"
        evidence_result["query_type"] = query_type

    course_item_selection = production_service._is_course_item_selection_query(
        normalised_query
    )
    if course_item_selection:
        query_type = "course_content_question"
        evidence_result["query_type"] = query_type
    named_course_location_subject = bool(
        enable_p2a_extensions
        and need_signals.course_location_need
        and re.search(
            r"\b(?:about|on|for|connected (?:with|to)|relate to)\s+[a-z][a-z -]{3,}\b",
            normalised_query.casefold(),
        )
    )
    course_reference_ambiguous = bool(
        unsupported_week_reference
        or (
            query_type == "course_content_question"
            and (
                production_service._is_natural_course_coverage_query(
                    normalised_query
                )
                or (
                    need_signals.course_location_need
                    and not named_course_location_subject
                )
            )
            and not production_service.extract_week_key(normalised_query)
        )
    )
    if unsupported_week_reference:
        query_type = "course_content_question"
        evidence_result["query_type"] = query_type

    intent_routing = _intent_routing_payload(intent_decision, query_type)
    evidence_result = production_service._apply_source_restrictions(
        evidence_result, source_restrictions
    )
    selected_route = production_service.route_for_mode_c(
        query_type, evidence_result
    )
    if query_type == "access_or_capability_question":
        selected_route = "access_or_capability"
    elif query_type == "discrepancy_or_correction":
        selected_route = "discrepancy_or_correction"
    if course_reference_ambiguous:
        selected_route = "course_reference_clarification"
    elif query_type == "hybrid_course_and_planning":
        selected_route = "hybrid_course_and_planning"
    elif query_type == "quantitative_metric_query":
        selected_route = "technical_data"

    dashboard_sources_before_scope = list(
        evidence_result.get("selected_sources", [])
    )
    dashboard_evidence_before_scope = dict(
        evidence_result.get("selected_evidence") or {}
    )
    source_scope = production_service.decide_c_full_source_scope(
        query_type=query_type,
        selected_route=selected_route,
        memory_resolved=False,
        referenced_items=(),
        active_course_item=False,
        course_reference_ambiguous=course_reference_ambiguous,
        allowed_source_types=source_restrictions["allowed_source_types"],
        enable_p2a_extensions=enable_p2a_extensions,
    )
    source_boundary_conflict = bool(
        "course_material" not in source_restrictions["allowed_source_types"]
        and query_type
        in {"course_content_question", "hybrid_course_and_planning"}
    )
    if source_boundary_conflict:
        selected_route = "source_boundary_capability"
    elif (
        source_scope.scope == "course_only"
        and query_type == "hybrid_course_and_planning"
    ):
        selected_route = "course_only_planning"
    if source_scope.scope == "course_only" or source_boundary_conflict:
        evidence_result["selected_sources"] = []
        evidence_result["selected_evidence"] = {}

    production_service._assert_source_scope_invariants(
        decision=source_scope,
        retrieval_needed=source_scope.retrieval_required,
        authoritative_query_type=query_type,
        authoritative_selected_route=selected_route,
        query_type=query_type,
        selected_route=selected_route,
        dashboard_sources_before_scope=dashboard_sources_before_scope,
        dashboard_sources_after_scope=list(
            evidence_result.get("selected_sources", [])
        ),
        dashboard_evidence_before_scope=dashboard_evidence_before_scope,
        dashboard_evidence_after_scope=dict(
            evidence_result.get("selected_evidence") or {}
        ),
    )
    source_categories = production_service.source_categories_for_decision(
        source_scope, memory_resolved=False
    )

    planner_route = bool(
        selected_route
        in {
            "hybrid_course_and_planning",
            "course_only_planning",
            "rq2_recommendation",
        }
        or (
            enable_p2a_extensions
            and selected_route in production_service.RECOMMENDATION_ROUTES
        )
    )
    recommendation_plan: dict[str, Any] = {}
    if planner_route:
        recommendation_plan = production_service.build_recommendation_plan(
            student_query=normalised_query,
            current_page=str(
                evidence_result.get("primary_page") or current_page
            ),
            student_id=str(student_id),
            evidence_summary=evidence_result,
            retrieved_context_chunks=None,
        )

    return {
        "query_type": query_type,
        "selected_route": selected_route,
        "intent_routing": intent_routing,
        "rq1_selected_sources": list(
            evidence_result.get("selected_sources", [])
        ),
        "rq1_evidence_summary": evidence_result,
        "allowed_source_types": source_categories["allowed"],
        "source_scope": source_scope.scope,
        "source_scope_decision": source_scope.to_dict(),
        "retrieval_requested": bool(source_scope.retrieval_required),
        "retrieval_used": False,
        "rq2_recommendation_plan": recommendation_plan,
        "c_full_need_signals": need_signals.to_dict(),
        "current_page": str(current_page),
        "memory_resolution": {},
    }


def measure_b0_case(
    *,
    case_id: str,
    original_query: str,
    current_page: str,
    semantic_runtime: Any,
    dashboard_data: Any,
    student_id: str = "301127",
) -> dict[str, Any]:
    """Measure one case without accepting or reading any Memory input."""

    mocks: dict[str, Any] = {}
    with provider_free_environment(), ExitStack() as stack:
        for name in FORBIDDEN_B0_CALLS:
            mocks[name] = stack.enter_context(
                patch.object(
                    production_service,
                    name,
                    side_effect=lambda *_args, _name=name, **_kwargs: (
                        _forbidden_b0_call(_name)
                    ),
                )
            )
        for name in COUNTED_PRODUCTION_FUNCTIONS:
            mocks[name] = stack.enter_context(
                patch.object(
                    production_service,
                    name,
                    wraps=getattr(production_service, name),
                )
            )
        context = _build_original_query_context(
            original_query=original_query,
            current_page=current_page,
            student_id=student_id,
            semantic_runtime=semantic_runtime,
            dashboard_data=dashboard_data,
        )

    production_call_counts = {
        name: int(mocks[name].call_count)
        for name in (*FORBIDDEN_B0_CALLS, *COUNTED_PRODUCTION_FUNCTIONS)
    }
    production_call_counts.update(
        {
            "conversation_history_read": 0,
            "structured_memory_read": 0,
        }
    )
    if any(
        production_call_counts[name] != 0
        for name in (
            "build_c_full_context",
            "prepare_mode_cm_context",
            "conversation_history_read",
            "structured_memory_read",
        )
    ):
        raise RQ2BError(
            "BLOCKED_RQ2_B_B0_IMPLEMENTATION: B0 accessed context resolution"
        )

    projection = _project_capabilities(context, production_call_counts)
    if projection.get("episodic_memory") is not False:
        raise RQ2BError(
            "BLOCKED_RQ2_B_B0_IMPLEMENTATION: B0 projected Episodic Memory"
        )
    intent_routing: Mapping[str, Any] = context.get("intent_routing") or {}
    selected_intent = str(
        intent_routing.get("adapter_selected_intent")
        or intent_routing.get("selected_intent")
        or context.get("query_type")
        or ""
    )
    planner_requested = production_call_counts["build_recommendation_plan"] > 0
    if projection["planning"] != planner_requested:
        raise RQ2BError(
            "BLOCKED_RQ2_B_B0_IMPLEMENTATION: Planner projection mismatch"
        )
    return {
        "schema_version": "rq2b-b0-prediction-v1",
        "case_id": str(case_id),
        "original_query_hash": _hash_text(original_query),
        "baseline_identity": B0_IDENTITY,
        "router_identity": RQ1_FINAL_ROUTER,
        "original_query_only": True,
        "context_resolution_enabled": False,
        "build_c_full_context_call_count": 0,
        "prepare_mode_cm_context_call_count": 0,
        "conversation_history_read_count": 0,
        "structured_memory_read_count": 0,
        "working_context_used": False,
        "selected_intent": selected_intent,
        "selected_route": str(context.get("selected_route") or ""),
        "source_scope": str(context.get("source_scope") or ""),
        "source_scope_decision": dict(
            context.get("source_scope_decision") or {}
        ),
        "retrieval_requested": bool(context.get("retrieval_requested")),
        "planner_requested": planner_requested,
        "context_resolution_required_prediction": False,
        "capability_projection": projection,
        "deterministic_guard": _deterministic_guards(context),
        "production_function_call_counts": production_call_counts,
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
    }


class B0OriginalQueryAdapter:
    """Named adapter that exposes only original-query B0 measurement."""

    identity = B0_IDENTITY
    router_identity = RQ1_FINAL_ROUTER
    context_resolution_enabled = False
    original_query_only = True

    def __init__(self, *, semantic_runtime: Any, dashboard_data: Any) -> None:
        self._semantic_runtime = semantic_runtime
        self._dashboard_data = dashboard_data

    def measure_fields(
        self,
        *,
        case_id: str,
        original_query: str,
        current_page: str,
    ) -> dict[str, Any]:
        return measure_b0_case(
            case_id=case_id,
            original_query=original_query,
            current_page=current_page,
            semantic_runtime=self._semantic_runtime,
            dashboard_data=self._dashboard_data,
        )

    def measure(self, case: Any) -> dict[str, Any]:
        # Intentionally read only these three fields.  In particular, do not
        # touch ``conversation_history`` or any structured-Memory attribute.
        return self.measure_fields(
            case_id=str(case.case_id),
            original_query=str(case.current_query),
            current_page=str(case.current_page),
        )


B0OriginalQueryCapabilityAdapterV1 = B0OriginalQueryAdapter
