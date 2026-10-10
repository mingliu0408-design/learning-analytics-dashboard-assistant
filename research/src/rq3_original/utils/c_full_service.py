"""Shared production-safe LLM C_FULL orchestration.

This module contains the single C_FULL context and generation path used by the
Streamlit application and the LLM evaluation pipeline. It deliberately does
not import Streamlit or persist student state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import logging
import re
from types import SimpleNamespace
from typing import Any, Literal, Mapping, Sequence

from evaluation.assistant_modes import (
    build_rq1_evidence_summary,
    render_course_retrieval_direct_response,
    render_course_retrieval_fallback,
    render_direct_mode_c_response,
    render_memory_resolved_follow_up,
    route_for_mode_c,
)
from utils.conversation_memory import (
    MAX_SESSION_MEMORY_MESSAGES,
    detect_plan_memory_intent,
    merge_structured_session_memory,
    prepare_mode_cm_context,
)
from utils.course_material_retriever import (
    RetrievalResult,
    chunks_to_dicts,
    format_retrieved_chunks_for_prompt,
    retrieve_course_chunks,
    retrieval_result_to_dict,
)
from utils.course_metadata import get_lecture_metadata, lecture_titles_by_week
from utils.dashboard_domain_resolver import (
    detect_dashboard_application_target,
    detect_explicit_dashboard_domains,
    is_explicit_whole_dashboard_query,
)
from utils.evidence_synthesiser import (
    PAGE_DISPLAY,
    classify_query,
    classify_query_detailed,
    detect_explicit_target_domain,
    normalise_page,
)
from utils.recommendation_planner import build_recommendation_plan
from utils.query_paraphrase_normaliser import (
    normalise_overview_priority_paraphrase,
    normalise_query_paraphrases,
    unresolved_explicit_week_guard_candidate,
)
from utils.c_full_retrieval_adapter import (
    CourseEvidenceResult,
    render_supporting_sources,
    retrieve_course_evidence,
    safe_retrieval_details,
    validate_prompt_isolation,
)
from utils.production_intent_router import (
    KEYWORD_BASELINE,
    SEMANTIC_ENHANCED,
    resolve_intent_router_mode,
    route_production_intent,
)
from utils.intent_schema import FUTURE_SCOPE_OUTCOMES


RECOMMENDATION_ROUTES = {
    "rq2_recommendation",
    "overview_planning",
    "overview_recommendation",
    "course_only_planning",
}
DIRECT_FIRST_SENTENCE_ROUTES = {
    "technical_data",
    "access_or_capability",
    "course_content",
    "discrepancy_or_correction",
}
QUANTITATIVE_LABELS = {
    "total_video_view_events": "Total video-view events",
    "unique_lecture_videos_viewed": "Unique real lecture videos viewed",
    "average_percentage_among_viewed_videos": "Average watched percentage among viewed real videos",
    "average_percentage_across_real_lecture_rows": "Average across all real lecture rows",
    "average_percentage_across_all_tracked_rows": "Average across all tracked rows",
}
SAFE_C_FULL_ERROR_RESPONSE = "I could not generate a response right now. Please try again."
logger = logging.getLogger(__name__)

SourceScope = Literal[
    "memory_only", "dashboard_only", "course_only", "hybrid", "no_supported_source"
]


def _resolve_intent_shadow_activation(config: Any) -> bool:
    """Enable shadow only for the exact lazy-imported Stage-5C config type."""

    if config is None:
        return False
    try:
        looks_enabled = getattr(config, "enabled", None) is True
    except Exception:
        return False
    if not looks_enabled:
        return False
    try:
        from utils.c_full_intent_shadow import CFullIntentShadowConfig
    except Exception:
        return False
    return bool(
        type(config) is CFullIntentShadowConfig
        and config.enabled is True
        and config.mode == "shadow"
    )


@dataclass(frozen=True)
class SourceScopeDecision:
    """Authoritative C_FULL decision about which evidence providers may run."""

    scope: SourceScope
    retrieval_required: bool
    preserve_dashboard_evidence: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "retrieval_required": self.retrieval_required,
            "preserve_dashboard_evidence": self.preserve_dashboard_evidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CFullNeedSignals:
    """Transparent C_FULL-side signals used before any retrieval planning."""

    dashboard_activity_need: bool
    course_content_need: bool
    planning_application_need: bool
    explicit_dashboard_domain: str
    explicit_course_entity: bool
    week_reference: str
    dashboard_comparison_planning_need: bool
    course_location_need: bool
    plan_memory_need: bool
    discrepancy_correction_need: bool
    causal_wording: bool
    explicit_source_restriction: bool

    @property
    def hybrid_need(self) -> bool:
        return bool(
            self.course_content_need
            and self.planning_application_need
            and self.explicit_dashboard_domain
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dashboard_activity_need": self.dashboard_activity_need,
            "course_content_need": self.course_content_need,
            "planning_application_need": self.planning_application_need,
            "explicit_dashboard_domain": self.explicit_dashboard_domain,
            "explicit_course_entity": self.explicit_course_entity,
            "week_reference": self.week_reference,
            "dashboard_comparison_planning_need": self.dashboard_comparison_planning_need,
            "course_location_need": self.course_location_need,
            "plan_memory_need": self.plan_memory_need,
            "discrepancy_correction_need": self.discrepancy_correction_need,
            "causal_wording": self.causal_wording,
            "explicit_source_restriction": self.explicit_source_restriction,
            "hybrid_need": self.hybrid_need,
        }


@dataclass(frozen=True)
class CFullRuntimeResult:
    """Final LLM C_FULL result plus auditable orchestration metadata."""

    response: str
    original_query: str
    resolved_query: str
    effective_query: str
    query_type: str
    selected_route: str
    selected_evidence_sources: list[str]
    memory_metadata: dict[str, Any]
    structured_memory: dict[str, Any]
    retrieval_used: bool
    retrieved_chunk_titles: list[str]
    recommendation_plan: dict[str, Any]
    context: dict[str, Any]
    openai_messages: list[dict[str, str]]


@dataclass(frozen=True)
class CFullChatTurnOutcome:
    """Atomic result for committing a production chat turn after generation."""

    succeeded: bool
    response: str
    memory_turns: list[Any]
    structured_memory: dict[str, Any]
    runtime_result: CFullRuntimeResult | None = None


@dataclass(frozen=True)
class CommitResult:
    committed_structured_memory: dict[str, Any]
    committed_user_turn: dict[str, Any]
    committed_assistant_turn: dict[str, Any]
    post_commit_memory_metadata: dict[str, Any]
    active_plan_updated: bool
    active_course_item_updated: bool
    memory_commit_sources: list[str]
    preserve_existing_active_plan: bool
    preserve_existing_numbered_referents: bool
    numbered_referents_updated: bool
    numbered_referents_source: str
    selected_course_item: dict[str, Any]
    user_state_delta: dict[str, Any]
    assistant_commit_delta: dict[str, Any]
    final_turn_delta: dict[str, Any]


def _is_underspecified_without_context(query: str) -> bool:
    """Detect short referential requests whose missing referent needs clarification."""

    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip()
    if not q or len(q.split()) > 12:
        return False
    prior_answer_correction = bool(
        re.search(r"\b(?:last|previous) answer\b", q)
        and re.search(r"\b(?:used|meant|referring|correct)\b", q)
    )
    return prior_answer_correction or bool(
        re.search(
            r"\b(?:this|that|it|the other (?:one|point)|the (?:first|second|third|last) one)\b",
            q,
        )
        and re.search(
            r"\b(?:explain|expand|unpack|make of|suggest|positive|negative|good|bad|other point)\b",
            q,
        )
    )


def _build_special_outcome_context(
    *,
    outcome: str,
    original_query: str,
    normalised_query: str,
    effective_query: str,
    current_page: str,
    retrieval_backend: str,
    existing_session_memory: Mapping[str, Any] | None,
    memory_runtime: Any,
    intent_decision: Any,
    query_normalisations: Sequence[Mapping[str, Any]],
    query_normalisation_diagnostics: Sequence[Mapping[str, Any]],
    deterministic_reason: str = "",
) -> dict[str, Any]:
    """Build the normal C_FULL context contract without activating evidence providers."""

    memory_resolution = memory_runtime.memory_resolution
    assert memory_resolution is not None
    state = dict(existing_session_memory or {})
    routing = intent_decision.to_dict()
    routing["adapter_selected_intent"] = intent_decision.selected_intent
    routing["selected_intent"] = outcome
    routing["semantic_effective"] = bool(
        intent_decision.semantic_accepted and intent_decision.selected_intent == outcome
    )
    if deterministic_reason:
        routing["routing_source"] = "deterministic_guard"
        routing["fallback_reason"] = ";".join(
            part for part in (str(routing.get("fallback_reason") or ""), deterministic_reason) if part
        )
    route = "ambiguous_clarification" if outcome == "ambiguous" else outcome
    memory_dict = {
        "is_follow_up": memory_resolution.is_follow_up,
        "resolved": False,
        "original_query": memory_resolution.original_query,
        "resolved_query": normalised_query,
        "referenced_items": [],
        "memory_context": {},
        "structured_state": state,
        "resolution_type": "underspecified_without_context" if outcome == "ambiguous" else outcome,
        "runtime_metadata": memory_runtime.metadata(),
        "reason": deterministic_reason or f"Production special-outcome route: {outcome}.",
    }
    evidence = {
        "available": True,
        "primary_page": str(current_page),
        "query": effective_query,
        "query_type": outcome,
        "selected_sources": [],
        "selected_evidence": {},
        "interpretation": "No dashboard or course evidence is applicable to this conversational outcome.",
        "uncertainty": "",
        "source_scope": "no_supported_source",
        "source_scope_reason": "This outcome requires no dashboard, course, planner, or memory evidence.",
    }
    retrieval = {
        "query": effective_query,
        "retrieval_requested": False,
        "retrieval_used": False,
        "reason": "no_supported_source",
        "evidence_sufficiency": {"status": "not_applicable", "supporting_chunk_ids": []},
    }
    prompt = "\n".join(
        [
            "Authoritative C_FULL special outcome:", outcome,
            "Authoritative route:", route,
            "Do not use Dashboard evidence, Course retrieval, Planner output, or inferred Memory.",
            "Keep the response brief and student-facing.",
            f"Student message: {original_query}",
        ]
    )
    return {
        "original_student_query": original_query,
        "normalised_query": normalised_query,
        "query_normalisations": list(query_normalisations),
        "query_normalisation_diagnostics": list(query_normalisation_diagnostics),
        "resolved_student_query": "",
        "effective_query": effective_query,
        "intent_router_mode": routing["routing_mode"],
        "intent_routing": routing,
        "evidence_query": effective_query,
        "query_type": outcome,
        "selected_route": route,
        "rq1_selected_sources": [],
        "rq1_evidence_summary": evidence,
        "rq2_recommendation_plan": {},
        "course_metadata": {},
        "memory_resolution": memory_dict,
        "memory_metadata": memory_runtime.metadata(),
        "structured_memory": state,
        "retrieval_result": retrieval,
        "retrieved_context_chunks": [],
        "selected_course_item": {},
        "retrieval_content_level": "not_applicable",
        "course_claim_support_chunks": [],
        "course_content_answer_guard_applied": False,
        "course_item_selection": False,
        "current_page": str(current_page),
        "explicit_target_domain": "",
        "resolved_target_domain": "",
        "primary_evidence_domain": "",
        "supplementary_evidence_domains": [],
        "allowed_source_types": [],
        "excluded_source_types": ["memory", "dashboard", "course_material"],
        "prohibited_source_types": ["memory", "dashboard", "course_material"],
        "source_scope": "no_supported_source",
        "source_scope_reason": evidence["source_scope_reason"],
        "source_scope_decision": {
            "scope": "no_supported_source", "retrieval_required": False,
            "preserve_dashboard_evidence": False, "reason": evidence["source_scope_reason"],
        },
        "c_full_need_signals": {},
        "plan_memory_intent": "",
        "retrieval_query": effective_query,
        "prompt": prompt,
        "retrieval_backend": retrieval_backend,
        "retrieval_backend_requested": retrieval_backend,
        "retrieval_backend_used": retrieval_backend,
        "retrieval_version": "not_applicable",
        "backend_mode": "not_applicable",
        "semantic_backend_available": False,
        "retrieval_requested": False,
        "retrieval_used": False,
        "query_plan": {},
        "canonical_retrieval_query": effective_query,
        "evidence_sufficiency": retrieval["evidence_sufficiency"],
        "supporting_chunk_ids": [],
        "source_provenance": [],
        "index_hash": None,
        "supporting_sources": [],
        "source_display": [],
        "retrieval_warnings": [],
        "notes": "C_FULL no-source special-outcome handling.",
    }


def build_c_full_context(
    *,
    student_query: str,
    student_id: str,
    current_page: str,
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    existing_session_memory: Mapping[str, Any] | None,
    dashboard_data: Any,
    retrieval_backend: Literal["v1", "v2_4"] = "v1",
    retrieval_context: Mapping[str, Any] | None = None,
    allow_retrieval_v1_fallback: bool = False,
    intent_router_mode: str | None = None,
    intent_router_runtime: Any | None = None,
) -> dict[str, Any]:
    """Build the complete shared C_FULL context before a single LLM call."""

    # ``v2`` remains accepted only for the historical experimental regression
    # path. New production callers use the public v1/v2_4 contract.
    if retrieval_backend not in {"v1", "v2", "v2_4"}:
        raise ValueError("retrieval_backend must be 'v1' or 'v2_4'")
    try:
        routing_mode = resolve_intent_router_mode(intent_router_mode)
    except Exception:
        # Preserve the adapter's established invalid-mode fallback diagnostics.
        routing_mode = KEYWORD_BASELINE
    enable_p2a_extensions = routing_mode == SEMANTIC_ENHANCED
    original_query = str(student_query or "").strip()
    (
        normalised_query,
        query_normalisations,
        query_normalisation_diagnostics,
    ) = _normalise_c_full_query_detailed(
        original_query,
        current_page=current_page,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    guarded_week_candidate = unresolved_explicit_week_guard_candidate(
        original_query,
        query_normalisation_diagnostics,
        query_normalisations,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    if guarded_week_candidate:
        query_normalisation_diagnostics.append(
            {
                "detected_week_expression": guarded_week_candidate,
                "parsed_week_number": None,
                "supported_week": False,
                "normalisation_applied": False,
                "reason": "ambiguous_explicit_week_reference",
                "guard": "c_full_pre_retrieval",
            }
        )
    unsupported_week_reference = next(
        (
            diagnostic
            for diagnostic in query_normalisation_diagnostics
            if diagnostic.get("supported_week") is False
        ),
        None,
    )
    scenario = {
        "student_query": original_query,
        "student_id": str(student_id),
        "page": str(current_page),
        "conversation_history": list(conversation_history or []),
        "session_memory": dict(existing_session_memory or {}),
    }
    memory_runtime = prepare_mode_cm_context(
        student_query=normalised_query,
        conversation_history=scenario["conversation_history"],
        existing_session_memory=existing_session_memory,
        current_page=current_page,
        transactional_course_corrections=retrieval_backend == "v2_4",
        enable_p2a_extensions=enable_p2a_extensions,
    )
    memory_resolution = memory_runtime.memory_resolution
    assert memory_resolution is not None
    effective_query = (
        memory_resolution.resolved_query
        if memory_resolution.resolved
        else normalised_query
    )
    evidence_query = effective_query
    numeric_week_normalisations = [
        rule
        for rule in query_normalisations
        if rule.get("rule") == "numeric_week"
    ]
    leading_zero_numeric_week = any(
        re.fullmatch(
            r"week\s+0+[0-9]+",
            str(rule.get("from") or ""),
            flags=re.IGNORECASE,
        )
        for rule in numeric_week_normalisations
    )
    retrieval_query = (
        original_query
        if numeric_week_normalisations and not leading_zero_numeric_week
        else effective_query
    )
    memory_course_reference_ambiguous = memory_resolution.resolution_type in {
        "course_entity_ambiguous",
        "unsupported_course_week",
    }

    source_restrictions = detect_source_restrictions(
        normalised_query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    referenced_kind = str((memory_resolution.memory_context or {}).get("numbered_reference_kind", ""))
    original_target_domain = (
        detect_dashboard_application_target(normalised_query)
        or detect_explicit_target_domain(normalised_query)
    )
    effective_target_domain = detect_explicit_target_domain(effective_query)
    explicit_target_domain = original_target_domain or effective_target_domain
    memory_target_domain = _target_domain_from_memory(memory_runtime.structured_memory, memory_resolution.referenced_items)
    try:
        current_page_domain = normalise_page(current_page)
    except ValueError:
        current_page_domain = "overview"
    resolved_target_domain = (
        original_target_domain
        or (memory_target_domain if memory_resolution.resolved else "")
        or effective_target_domain
        or current_page_domain
    )
    evidence_page = PAGE_DISPLAY.get(resolved_target_domain, str(current_page))

    scenario_for_evidence = dict(scenario)
    scenario_for_evidence["student_query"] = evidence_query
    scenario_for_evidence["page"] = evidence_page
    scenario_for_evidence["resolved_target_domain"] = resolved_target_domain
    pre_active_course_item = dict(
        memory_runtime.structured_memory.get("active_course_item") or {}
    )
    pre_need_signals = detect_c_full_need_signals(
        effective_query,
        current_page=current_page,
        active_course_item=pre_active_course_item,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    pre_original_follow_up_signals = detect_c_full_need_signals(
        normalised_query,
        current_page=current_page,
        active_course_item=pre_active_course_item,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    pre_forced_query_type = authoritative_c_full_query_type(
        normalised_query,
        pre_original_follow_up_signals,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    intent_guard_reasons: list[str] = []
    if unsupported_week_reference:
        intent_guard_reasons.append("week_validation_fail_closed")
    if memory_resolution.resolved:
        intent_guard_reasons.append("memory_resolution_authoritative")
    if (memory_resolution.memory_context or {}).get("course_reference_correction"):
        intent_guard_reasons.append("course_correction_authoritative")
    if (
        source_restrictions["allowed_source_types"]
        != ["memory", "dashboard", "course_material"]
        or source_restrictions["excluded_source_types"]
    ):
        intent_guard_reasons.append("explicit_source_restriction")
    if (
        pre_forced_query_type
        and classify_query_detailed(effective_query).rule_id == "UNMATCHED_DEFAULT"
    ):
        intent_guard_reasons.append(f"authoritative_c_full_type:{pre_forced_query_type}")
    if _is_page_local_dashboard_priority(normalised_query):
        intent_guard_reasons.append("page_local_dashboard_priority")
    if (
        not memory_resolution.resolved
        and _is_underspecified_without_context(original_query)
        and not _is_natural_course_coverage_query(normalised_query)
    ):
        intent_guard_reasons.append("underspecified_without_context")
    intent_decision = route_production_intent(
        effective_query,
        current_page=evidence_page,
        mode=intent_router_mode,
        protected_guard_reasons=intent_guard_reasons,
        semantic_runtime=intent_router_runtime,
    )
    special_outcome = (
        intent_decision.selected_intent
        if intent_decision.selected_intent in {*FUTURE_SCOPE_OUTCOMES, "semantic_uncertain"}
        else ""
    )
    deterministic_special_reason = ""
    if (
        enable_p2a_extensions
        and
        not special_outcome
        and not memory_resolution.resolved
        and _is_underspecified_without_context(original_query)
        and not _is_natural_course_coverage_query(normalised_query)
    ):
        special_outcome = "ambiguous"
        deterministic_special_reason = "underspecified_without_context"
    if special_outcome:
        return _build_special_outcome_context(
            outcome=special_outcome,
            original_query=original_query,
            normalised_query=normalised_query,
            effective_query=effective_query,
            current_page=current_page,
            retrieval_backend=retrieval_backend,
            existing_session_memory=existing_session_memory,
            memory_runtime=memory_runtime,
            intent_decision=intent_decision,
            query_normalisations=query_normalisations,
            query_normalisation_diagnostics=query_normalisation_diagnostics,
            deterministic_reason=deterministic_special_reason,
        )
    evidence_result = build_rq1_evidence_summary(
        {
            **scenario_for_evidence,
            "query_type_override": intent_decision.selected_intent,
        },
        dashboard_data,
    )
    query_type = str(evidence_result.get("query_type") or classify_query(effective_query))
    active_plan = dict(memory_runtime.structured_memory.get("active_plan") or {})
    active_course_item = pre_active_course_item
    need_signals = pre_need_signals
    original_follow_up_signals = pre_original_follow_up_signals
    forced_query_type = pre_forced_query_type
    if forced_query_type and not (
        memory_resolution.resolved and referenced_kind == "action_plan"
    ):
        query_type = forced_query_type
        evidence_result = build_rq1_evidence_summary(
            {
                **scenario_for_evidence,
                "student_query": evidence_query,
                "query_type_override": forced_query_type,
            },
            dashboard_data,
        )
    if (
        _is_page_local_dashboard_priority(normalised_query)
        and query_type == "improvement_recommendation"
    ):
        query_type = "dashboard_interpretation"
        evidence_result = build_rq1_evidence_summary(
            {
                **scenario_for_evidence,
                "student_query": evidence_query,
                "query_type_override": query_type,
            },
            dashboard_data,
        )
    course_reference_resolved = bool(
        (memory_resolution.memory_context or {}).get("course_reference_resolved")
    )
    course_only_planning_requested = bool(
        source_restrictions["allowed_source_types"] == ["course_material"]
        and _is_course_only_planning_query(
            normalised_query,
            enable_p2a_extensions=enable_p2a_extensions,
        )
    )
    if course_only_planning_requested:
        query_type = "hybrid_course_and_planning"
    elif (
        course_reference_resolved
        and original_follow_up_signals.planning_application_need
        and original_follow_up_signals.explicit_dashboard_domain
    ):
        query_type = "hybrid_course_and_planning"
    elif course_reference_resolved:
        query_type = "course_content_question"
    elif need_signals.hybrid_need:
        query_type = "hybrid_course_and_planning"
    elif need_signals.course_content_need and not need_signals.dashboard_activity_need:
        query_type = "course_content_question"
    evidence_result["query_type"] = query_type
    if memory_resolution.resolved and referenced_kind == "action_plan":
        originating_goal = str(active_plan.get("goal") or "").strip()
        if originating_goal:
            evidence_query = originating_goal
            evidence_result = build_rq1_evidence_summary(
                {**scenario_for_evidence, "student_query": evidence_query},
                dashboard_data,
            )
            query_type = str(
                evidence_result.get("query_type") or classify_query(originating_goal)
            )
        if _plan_origin_uses_course_evidence(active_plan):
            retrieval_query = _action_plan_retrieval_query(
                active_plan=active_plan,
                referenced_items=memory_resolution.referenced_items,
                current_follow_up=original_query,
            )
    elif memory_resolution.resolved and referenced_kind == "analytical_list":
        query_type = "quantitative_metric_query"
        evidence_result = build_rq1_evidence_summary(
            {**scenario_for_evidence, "student_query": "average across all real lecture rows denominator inclusion rule", "page": PAGE_DISPLAY["lecture"]},
            dashboard_data,
        )
        evidence_result["query_type"] = query_type
        resolved_target_domain = "lecture"
    if memory_resolution.resolution_type in {"memory_state_query", "no_active_plan"}:
        query_type = "memory_state_query"
        evidence_result = _memory_only_evidence_result(effective_query, evidence_page)
    elif source_restrictions["allowed_source_types"] == ["course_material"] and query_type != "hybrid_course_and_planning":
        query_type = "course_content_question"
        evidence_result["query_type"] = query_type
    course_item_selection = _is_course_item_selection_query(normalised_query)
    if course_item_selection:
        query_type = "course_content_question"
        evidence_result["query_type"] = query_type
        evidence_result["interpretation"] = "Select one course item from retrieved course metadata only."
    named_course_location_subject = bool(enable_p2a_extensions and
        original_follow_up_signals.course_location_need
        and re.search(
            r"\b(?:about|on|for|connected (?:with|to)|relate to)\s+[a-z][a-z -]{3,}\b",
            normalised_query.casefold(),
        )
    )
    natural_course_reference_ambiguous = bool(
        query_type == "course_content_question"
        and (
            _is_natural_course_coverage_query(normalised_query)
            or (
                original_follow_up_signals.course_location_need
                and not named_course_location_subject
            )
        )
        and not extract_week_key(effective_query)
        and not active_course_item
    )
    course_reference_ambiguous = bool(
        memory_course_reference_ambiguous
        or natural_course_reference_ambiguous
        or unsupported_week_reference
    )
    if unsupported_week_reference:
        query_type = "course_content_question"
        evidence_result = _memory_only_evidence_result(effective_query, evidence_page)
        evidence_result["query_type"] = query_type
    if (
        query_type == "course_content_question"
        and active_course_item
        and not extract_week_key(retrieval_query)
        and _is_natural_course_coverage_query(normalised_query)
    ):
        retrieval_query = _course_item_retrieval_query(active_course_item, normalised_query)
    if (memory_resolution.memory_context or {}).get("course_reference_correction"):
        corrected_item = dict(
            (memory_resolution.memory_context or {}).get("resolved_course_entity") or {}
        )
        corrected_label = " ".join(
            part
            for part in (
                str(corrected_item.get("week") or "").strip(),
                str(
                    corrected_item.get("material_type")
                    or corrected_item.get("entity_type")
                    or "material"
                ).strip(),
            )
            if part
        )
        retrieval_query = (
            f"Corrected course reference:\n{corrected_label}\n\n"
            f"Current correction:\n{normalised_query}"
        )

    intent_routing = intent_decision.to_dict()
    intent_routing["adapter_selected_intent"] = intent_decision.selected_intent
    intent_routing["selected_intent"] = query_type
    intent_routing["semantic_effective"] = bool(
        intent_decision.semantic_accepted
        and query_type == intent_decision.selected_intent
    )
    if query_type != intent_decision.selected_intent:
        prior_reason = str(intent_routing.get("fallback_reason") or "")
        intent_routing["routing_source"] = "deterministic_guard"
        intent_routing["fallback_reason"] = ";".join(
            part
            for part in (prior_reason, "downstream_authoritative_override")
            if part
        )

    evidence_result = _apply_source_restrictions(evidence_result, source_restrictions)
    mode_c_route = route_for_mode_c(query_type, evidence_result)
    if enable_p2a_extensions and query_type == "access_or_capability_question":
        mode_c_route = "access_or_capability"
    elif enable_p2a_extensions and query_type == "discrepancy_or_correction":
        mode_c_route = "discrepancy_or_correction"
    plan_revision_requested = bool(
        (memory_resolution.memory_context or {}).get("plan_revision_requested")
    )
    if plan_revision_requested:
        mode_c_route = "memory_plan_revision"
    elif query_type == "memory_state_query":
        mode_c_route = "memory_state_direct_answer"
    elif course_reference_ambiguous:
        mode_c_route = "course_reference_clarification"
    elif query_type == "hybrid_course_and_planning":
        mode_c_route = "hybrid_course_and_planning"
    elif query_type == "quantitative_metric_query":
        mode_c_route = "technical_data"
    resolved_action_plan_follow_up = bool(
        memory_resolution.resolved
        and (
            referenced_kind == "action_plan"
            or (memory_resolution.memory_context or {}).get("completion_reference_resolved")
        )
    )
    selected_route = (
        "memory_plan_revision"
        if plan_revision_requested
        else
        "memory_resolved_follow_up"
        if memory_resolution.resolved
        and (
            resolved_action_plan_follow_up
            or (course_reference_resolved and query_type == "course_content_question")
        )
        else mode_c_route
        if query_type in {"memory_state_query", "hybrid_course_and_planning"}
        else "memory_resolved_follow_up" if memory_resolution.resolved else mode_c_route
    )
    dashboard_sources_before_scope = list(evidence_result.get("selected_sources", []))
    dashboard_evidence_before_scope = dict(evidence_result.get("selected_evidence") or {})
    source_scope = decide_c_full_source_scope(
        query_type=query_type,
        selected_route=selected_route,
        memory_resolved=memory_resolution.resolved,
        referenced_items=memory_resolution.referenced_items,
        active_course_item=bool(memory_runtime.structured_memory.get("active_course_item")),
        course_reference_ambiguous=course_reference_ambiguous,
        allowed_source_types=source_restrictions["allowed_source_types"],
        enable_p2a_extensions=enable_p2a_extensions,
    )
    retrieval_needed = source_scope.retrieval_required
    source_boundary_conflict = bool(
        (
            "course_material" not in source_restrictions["allowed_source_types"]
            if enable_p2a_extensions
            else source_restrictions["allowed_source_types"] == ["dashboard"]
        )
        and query_type in {"course_content_question", "hybrid_course_and_planning"}
    )
    if source_boundary_conflict:
        selected_route = "source_boundary_capability"
    elif (
        source_scope.scope == "course_only"
        and query_type == "hybrid_course_and_planning"
        and not memory_resolution.resolved
    ):
        selected_route = "course_only_planning"
    authoritative_query_type = query_type
    authoritative_selected_route = selected_route
    if source_scope.scope == "course_only" or source_boundary_conflict:
        evidence_result["selected_sources"] = []
        evidence_result["selected_evidence"] = {}
        evidence_result["interpretation"] = (
            "Dashboard-only evidence cannot answer the requested course-content question."
            if source_boundary_conflict
            else "This is a C_FULL course-material question; dashboard evidence is not applicable."
        )
    _assert_source_scope_invariants(
        decision=source_scope,
        retrieval_needed=retrieval_needed,
        authoritative_query_type=authoritative_query_type,
        authoritative_selected_route=authoritative_selected_route,
        query_type=query_type,
        selected_route=selected_route,
        dashboard_sources_before_scope=dashboard_sources_before_scope,
        dashboard_sources_after_scope=list(evidence_result.get("selected_sources", [])),
        dashboard_evidence_before_scope=dashboard_evidence_before_scope,
        dashboard_evidence_after_scope=dict(evidence_result.get("selected_evidence") or {}),
    )
    retrieval_v2_result: Any = None
    retrieval_adapter_result: CourseEvidenceResult | None = None
    retrieval_prompt_text: str | None = None
    retrieval_generation_context: dict[str, Any] | None = None
    if retrieval_backend == "v1":
        retrieval_adapter_result = retrieve_course_evidence(
            retrieval_query,
            backend="v1",
            top_k=20 if course_item_selection else 4,
            context={"query_type": query_type, "retrieval_needed": retrieval_needed},
        )
        retrieval_result = retrieval_adapter_result.compatibility_result
        retrieved_chunks = chunks_to_dicts(retrieval_result.chunks)
        retrieval_dict = retrieval_result_to_dict(retrieval_result)
    elif retrieval_backend == "v2":
        from utils.retrieval_v2.prompt_formatting import (
            allowed_chunks_for_generation,
            format_allowed_retrieval_context_for_prompt,
        )
        from utils.retrieval_v2.retriever import retrieve_course_materials_v2

        retrieval_v2_result = retrieve_course_materials_v2(
            retrieval_query, query_type=query_type, top_k=20 if course_item_selection else 4
        )
        allowed_items = allowed_chunks_for_generation(retrieval_v2_result)
        allowed_course_chunks = [item.chunk for item in allowed_items]
        retrieval_result = SimpleNamespace(
            query=retrieval_query,
            chunks=allowed_course_chunks,
            retrieval_used=retrieval_v2_result.retrieval_used,
            reason=retrieval_v2_result.reason,
        )
        retrieved_chunks = [item.to_generation_dict() for item in allowed_items]
        retrieval_dict = retrieval_v2_result.to_audit_dict()
        retrieval_generation_context = retrieval_v2_result.to_generation_dict()
        retrieval_prompt_text = format_allowed_retrieval_context_for_prompt(retrieval_v2_result)
    else:
        adapter_context = dict(retrieval_context or {})
        adapter_context.update(
            {
                "query_type": query_type,
                "retrieval_needed": retrieval_needed,
                "source_scope": source_scope.scope,
                "allow_v1_fallback": allow_retrieval_v1_fallback,
            }
        )
        retrieval_adapter_result = retrieve_course_evidence(
            retrieval_query,
            backend="v2_4",
            top_k=20 if course_item_selection else 5,
            context=adapter_context,
        )
        retrieval_result = retrieval_adapter_result.compatibility_result
        retrieved_chunks = list(retrieval_adapter_result.allowed_chunks)
        retrieval_dict = dict(retrieval_adapter_result.audit)
        retrieval_generation_context = dict(retrieval_adapter_result.generation)
        retrieval_prompt_text = retrieval_adapter_result.prompt_text
    _assert_source_scope_invariants(
        decision=source_scope,
        retrieval_needed=retrieval_needed,
        authoritative_query_type=authoritative_query_type,
        authoritative_selected_route=authoritative_selected_route,
        query_type=query_type,
        selected_route=selected_route,
        dashboard_sources_before_scope=dashboard_sources_before_scope,
        dashboard_sources_after_scope=list(evidence_result.get("selected_sources", [])),
        dashboard_evidence_before_scope=dashboard_evidence_before_scope,
        dashboard_evidence_after_scope=dict(evidence_result.get("selected_evidence") or {}),
        retrieval_used=bool(retrieval_result.retrieval_used),
    )
    selected_course_item = (
        _select_core_reading(retrieval_query, retrieval_result.chunks)
        if course_item_selection
        else {}
    )
    course_item_for_grounding = dict(
        selected_course_item or memory_runtime.structured_memory.get("active_course_item") or {}
    )
    if retrieval_backend == "v1":
        retrieval_sufficiency = _assess_retrieval_content_sufficiency(
            retrieved_chunks, course_item_for_grounding
        )
        retrieval_dict.update(retrieval_sufficiency)
    elif retrieval_backend == "v2":
        sufficiency_v2 = retrieval_v2_result.evidence_sufficiency
        available_levels = list(sufficiency_v2.available_content_levels)
        retrieval_sufficiency = {
            "retrieval_content_level": (
                "full_text" if "full_text" in available_levels
                else "body_excerpt" if "excerpt" in available_levels
                else "title_and_metadata" if "title_and_metadata" in available_levels
                else "citation_only" if "citation_only" in available_levels
                else "not_applicable"
            ),
            "course_claim_support_chunks": list(sufficiency_v2.supporting_chunk_ids),
        }
        retrieval_dict.update(retrieval_sufficiency)
    else:
        sufficiency_v2_4 = retrieval_adapter_result.evidence_sufficiency
        available_levels = list(sufficiency_v2_4.get("available_content_levels") or [])
        retrieval_sufficiency = {
            "retrieval_content_level": (
                "full_text" if "full_text" in available_levels
                else "body_excerpt" if "excerpt" in available_levels
                else "title_and_metadata" if "title_and_metadata" in available_levels
                else "citation_only" if "citation_only" in available_levels
                else "not_applicable"
            ),
            "course_claim_support_chunks": list(
                sufficiency_v2_4.get("supporting_chunk_ids") or []
            ),
        }
        retrieval_dict.update(retrieval_sufficiency)

    if not selected_course_item and source_scope.scope in {"course_only", "hybrid"}:
        selected_course_item = _derive_active_course_item(
            source_query=original_query,
            normalised_query=normalised_query,
            retrieval_query=retrieval_query,
            selected_route=selected_route,
            source_scope=source_scope.scope,
            retrieved_chunks=retrieved_chunks,
            supporting_sources=(
                retrieval_adapter_result.supporting_sources
                if retrieval_adapter_result is not None
                else []
            ),
            supporting_chunk_ids=retrieval_sufficiency[
                "course_claim_support_chunks"
            ],
            evidence_sufficiency=(retrieval_dict.get("evidence_sufficiency") or {}),
            active_course_item=active_course_item,
        )
        if selected_course_item:
            course_item_for_grounding = dict(selected_course_item)

    memory_dict = {
        "is_follow_up": memory_resolution.is_follow_up,
        "resolved": memory_resolution.resolved,
        "original_query": memory_resolution.original_query,
        "resolved_query": memory_resolution.resolved_query,
        "referenced_items": memory_resolution.referenced_items,
        "memory_context": memory_resolution.memory_context,
        "structured_state": memory_runtime.structured_memory,
        "resolution_type": memory_resolution.resolution_type,
        "runtime_metadata": memory_runtime.metadata(),
        "reason": memory_resolution.reason,
    }

    evidence_result = dict(evidence_result)
    evidence_result["memory_resolution"] = memory_dict
    evidence_result["course_retrieval"] = (
        retrieval_generation_context
        if retrieval_backend in {"v2", "v2_4"}
        else retrieval_dict
    )
    evidence_result["c_full_mode_c_route"] = mode_c_route
    evidence_result["original_student_query"] = original_query
    evidence_result["resolved_student_query"] = effective_query if memory_resolution.resolved else ""
    evidence_result["source_restrictions"] = source_restrictions
    evidence_result["source_scope"] = source_scope.scope
    evidence_result["source_scope_reason"] = source_scope.reason
    evidence_result["current_page"] = str(current_page)
    evidence_result["explicit_target_domain"] = explicit_target_domain
    evidence_result["resolved_target_domain"] = resolved_target_domain
    evidence_result["primary_evidence_domain"] = resolved_target_domain if evidence_result.get("selected_sources") else ""
    evidence_result["supplementary_evidence_domains"] = _supplementary_evidence_domains(
        evidence_result.get("selected_sources", []), resolved_target_domain
    )

    recommendation_plan: dict[str, Any] = {}
    direct_response_reference = ""
    # Planner activation follows the authoritative final route, regardless of
    # whether that route came from the legacy classifier or an accepted
    # semantic decision.  Previously an overview_planning route selected by the
    # keyword fallback could be left without a plan.
    planner_route = selected_route in {
        "hybrid_course_and_planning",
        "course_only_planning",
        "rq2_recommendation",
    } or (
        enable_p2a_extensions
        and selected_route in RECOMMENDATION_ROUTES
    )
    if not resolved_action_plan_follow_up and planner_route:
        recommendation_plan = build_recommendation_plan(
            student_query=effective_query,
            current_page=str(evidence_result.get("primary_page") or current_page),
            student_id=str(student_id),
            evidence_summary=evidence_result,
            retrieved_context_chunks=retrieved_chunks if retrieval_result.retrieval_used else None,
        )
        recommendation_plan = _enforce_requested_action_count(original_query, recommendation_plan)
    elif selected_route == "source_boundary_capability":
        direct_response_reference = _render_source_boundary_capability(
            query_type=query_type,
            allowed_source_types=["dashboard"],
        )
    elif mode_c_route == "memory_state_direct_answer":
        direct_response_reference = _render_memory_state_direct_answer(memory_resolution)
    elif mode_c_route == "course_reference_clarification":
        direct_response_reference = _render_course_reference_clarification(memory_resolution)
    elif memory_resolution.resolved:
        direct_response_reference = render_memory_resolved_follow_up(
            scenario=scenario_for_evidence,
            evidence_result=evidence_result,
            memory_resolution=memory_resolution,
        )
    elif query_type == "quantitative_metric_query":
        direct_response_reference = _render_quantitative_lecture_reference(evidence_result)
    elif evidence_result.get("available") is False and retrieval_backend == "v1":
        direct_response_reference = render_course_retrieval_fallback(scenario_for_evidence, retrieval_result)
    elif evidence_result.get("available") is False and retrieval_backend == "v2":
        from utils.retrieval_v2.prompt_formatting import render_student_boundary

        direct_response_reference = render_student_boundary(retrieval_v2_result)
    elif retrieval_backend == "v2" and (retrieval_result.retrieval_used or retrieval_needed):
        from utils.retrieval_v2.prompt_formatting import render_student_boundary

        direct_response_reference = render_student_boundary(retrieval_v2_result) or (
            "Use only the Retrieval v2 evidence whose IDs appear in evidence_sufficiency.supporting_chunk_ids."
        )
    elif retrieval_backend == "v2_4" and retrieval_needed:
        direct_response_reference = _render_v2_4_boundary_reference(
            retrieval_adapter_result.evidence_sufficiency,
            retrieval_adapter_result.retrieval_available,
        )
    elif retrieval_result.retrieval_used or retrieval_needed:
        direct_response_reference = render_course_retrieval_direct_response(
            scenario=scenario_for_evidence,
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=mode_c_route,
            retrieval_result=retrieval_result,
        )
    else:
        direct_response_reference = render_direct_mode_c_response(
            scenario=scenario_for_evidence,
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=mode_c_route,
        )

    source_categories = source_categories_for_decision(
        source_scope,
        memory_resolved=memory_resolution.resolved,
    )
    course_metadata = (
        course_metadata_for_context(scenario_for_evidence, evidence_result, selected_route)
        if "course_material" in source_categories["allowed"]
        else {}
    )
    effective_restrictions = {
        "allowed_source_types": source_categories["allowed"],
        "excluded_source_types": list(
            dict.fromkeys(
                [*source_categories["prohibited"], *source_restrictions["excluded_source_types"]]
            )
        ),
    }
    evidence_result["source_restrictions"] = effective_restrictions
    if "course_material" not in source_categories["allowed"]:
        evidence_result.pop("course_retrieval", None)
    prompt_evidence_result = _prompt_evidence_view(evidence_result)
    prompt = build_c_full_prompt(
        scenario=scenario_for_evidence,
        evidence_result=prompt_evidence_result,
        query_type=query_type,
        selected_route=selected_route,
        recommendation_plan=recommendation_plan,
        direct_response_reference=direct_response_reference,
        course_metadata=course_metadata,
        memory_context=memory_runtime.formatted_memory_context,
        retrieval_result=retrieval_dict,
        retrieved_chunks=retrieval_result.chunks,
        selected_course_item=selected_course_item,
        retrieval_prompt_text=retrieval_prompt_text,
        retrieval_generation_context=retrieval_generation_context,
        source_scope=source_scope.scope,
        allowed_source_categories=source_categories["allowed"],
        prohibited_source_categories=source_categories["prohibited"],
    )
    if retrieval_backend == "v2_4":
        validate_prompt_isolation(prompt, retrieval_adapter_result)
    context = {
        "original_student_query": original_query,
        "normalised_query": normalised_query,
        "query_normalisations": query_normalisations,
        "query_normalisation_diagnostics": query_normalisation_diagnostics,
        "resolved_student_query": effective_query if memory_resolution.resolved else "",
        "effective_query": effective_query,
        "intent_router_mode": intent_routing["routing_mode"],
        "intent_routing": intent_routing,
        "evidence_query": evidence_query,
        "query_type": query_type,
        "selected_route": selected_route,
        "rq1_selected_sources": list(evidence_result.get("selected_sources", [])),
        "rq1_evidence_summary": evidence_result,
        "rq2_recommendation_plan": recommendation_plan,
        "course_metadata": course_metadata,
        "memory_resolution": memory_dict,
        "memory_metadata": memory_runtime.metadata(),
        "structured_memory": memory_runtime.structured_memory,
        "retrieval_result": retrieval_dict,
        "retrieved_context_chunks": retrieved_chunks,
        "selected_course_item": selected_course_item,
        "retrieval_content_level": retrieval_sufficiency["retrieval_content_level"],
        "course_claim_support_chunks": retrieval_sufficiency["course_claim_support_chunks"],
        "course_content_answer_guard_applied": False,
        "course_item_selection": course_item_selection,
        "current_page": str(current_page),
        "explicit_target_domain": explicit_target_domain,
        "resolved_target_domain": resolved_target_domain,
        "primary_evidence_domain": evidence_result.get("primary_evidence_domain", ""),
        "supplementary_evidence_domains": evidence_result.get("supplementary_evidence_domains", []),
        "allowed_source_types": source_categories["allowed"],
        "excluded_source_types": effective_restrictions["excluded_source_types"],
        "prohibited_source_types": source_categories["prohibited"],
        "source_scope": source_scope.scope,
        "source_scope_reason": source_scope.reason,
        "source_scope_decision": source_scope.to_dict(),
        "c_full_need_signals": need_signals.to_dict(),
        "plan_memory_intent": (
            (memory_resolution.memory_context or {}).get("plan_memory_intent")
            or detect_plan_memory_intent(
                normalised_query,
                active_plan_exists=bool(active_plan),
                enable_p2a_extensions=enable_p2a_extensions,
            )
        ),
        "retrieval_query": retrieval_dict.get("query", retrieval_query),
        "prompt": prompt,
        "notes": "C_FULL uses shared Mode CM memory, resolved-query evidence/routing, and gated course retrieval.",
    }
    context.update(
        {
            "retrieval_backend": retrieval_backend,
            "retrieval_backend_requested": retrieval_backend,
            "retrieval_backend_used": retrieval_backend,
            "retrieval_version": (
                retrieval_adapter_result.retrieval_version
                if retrieval_adapter_result is not None
                else retrieval_dict.get("index_version", "retrieval_v2.3")
            ),
            "backend_mode": (
                retrieval_adapter_result.backend_mode
                if retrieval_adapter_result is not None
                else retrieval_dict.get("backend_mode", "legacy_v2")
            ),
            "semantic_backend_available": (
                retrieval_adapter_result.semantic_backend_available
                if retrieval_adapter_result is not None
                else bool(retrieval_dict.get("semantic_backend_available"))
            ),
            "retrieval_requested": bool(retrieval_dict.get("retrieval_requested")),
            "retrieval_used": bool(retrieval_dict.get("retrieval_used")),
            "query_plan": dict(retrieval_dict.get("query_plan") or {}),
            "canonical_retrieval_query": str(
                retrieval_dict.get("canonical_retrieval_query") or retrieval_query
            ),
            "evidence_sufficiency": dict(
                retrieval_dict.get("evidence_sufficiency") or {}
            ),
            "supporting_chunk_ids": list(
                (retrieval_dict.get("evidence_sufficiency") or {}).get(
                    "supporting_chunk_ids", []
                )
            ),
            "source_provenance": list(retrieval_dict.get("source_provenance") or []),
            "index_hash": retrieval_dict.get("index_hash"),
            "supporting_sources": [],
            "source_display": [],
            "retrieval_warnings": [],
        }
    )
    if retrieval_backend == "v2":
        context["retrieval_backend"] = "v2"
        context["retrieval_generation_context"] = retrieval_generation_context
        context["notes"] = (
            "C_FULL_RAG_V2 uses shared Mode CM memory, dashboard evidence/routing, and the "
            "post-freeze experimental Retrieval v2 sufficiency gate."
        )
    elif retrieval_backend == "v2_4":
        status = str(retrieval_adapter_result.evidence_sufficiency.get("status") or "")
        context.update(
            {
                "retrieval_backend_requested": retrieval_adapter_result.retrieval_backend_requested,
                "retrieval_backend_used": retrieval_adapter_result.retrieval_backend_used,
                "retrieval_version": retrieval_adapter_result.retrieval_version,
                "backend_mode": retrieval_adapter_result.backend_mode,
                "semantic_backend_available": retrieval_adapter_result.semantic_backend_available,
                "retrieval_available": retrieval_adapter_result.retrieval_available,
                "retrieval_generation_context": retrieval_generation_context,
                "supporting_sources": list(retrieval_adapter_result.supporting_sources),
                "source_display": render_supporting_sources(
                    retrieval_adapter_result.supporting_sources, status
                ),
                "retrieval_warnings": list(retrieval_adapter_result.warnings),
                "safe_retrieval_details": safe_retrieval_details(retrieval_dict),
                "notes": (
                    "Live C_FULL uses the frozen persisted Retrieval v2.4 lexical index for "
                    "course evidence while preserving Memory, dashboard evidence, routing, and planning."
                ),
            }
        )
    return context


def _prompt_evidence_view(evidence_result: Mapping[str, Any]) -> dict[str, Any]:
    """Hide stored chunk-ID provenance from the generator-facing Memory view.

    Active plans retain their frozen supporting IDs for audit and future reuse,
    but only IDs approved for the current retrieval turn may enter the prompt.
    """

    def strip_plan_chunk_ids(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: strip_plan_chunk_ids(item)
                for key, item in value.items()
                if key not in {
                    "supporting_course_chunk_ids",
                    "supporting_chunk_ids",
                    "chunk_ids",
                }
            }
        if isinstance(value, list):
            return [strip_plan_chunk_ids(item) for item in value]
        return value

    out = dict(evidence_result)
    if "memory_resolution" in out:
        out["memory_resolution"] = strip_plan_chunk_ids(out["memory_resolution"])
    return out


def _render_v2_4_boundary_reference(
    sufficiency: Mapping[str, Any],
    retrieval_available: bool,
) -> str:
    """Return explicit production guidance for each frozen sufficiency status."""

    if not retrieval_available:
        return (
            "Course retrieval is temporarily unavailable. Course evidence was not checked; "
            "do not make or imply any course-material claim."
        )
    status = str(sufficiency.get("status") or "")
    boundary = str(sufficiency.get("user_facing_boundary") or "").strip()
    if status == "sufficient":
        return (
            "Answer the supported course question from approved chunks only. Name the source "
            "and give the available week, section, or page. " + boundary
        ).strip()
    if status == "partially_sufficient":
        return (
            "Answer only the supported part and explicitly identify the missing evidence. "
            + boundary
        ).strip()
    if status == "metadata_only":
        return (
            "Identify only the source title, authors, citation, or verified link. Do not infer "
            "findings, methods, arguments, or conclusions. " + boundary
        ).strip()
    if status == "insufficient":
        return (
            "Related indexed evidence is not detailed enough. State what fuller source would "
            "be needed and do not fill the gap with general knowledge. " + boundary
        ).strip()
    if status == "no_result":
        return (
            "No relevant evidence was found in the indexed course corpus. Do not add unrelated "
            "dashboard evidence unless the question is hybrid."
        )
    if status == "not_applicable":
        return "Do not add a course-material section; continue with Dashboard or Memory evidence only."
    return boundary or "Do not make a course-material claim."


def source_categories_for_decision(
    decision: SourceScopeDecision,
    *,
    memory_resolved: bool,
) -> dict[str, list[str]]:
    """Map source scope to the only categories permitted in the final prompt."""

    if decision.scope == "no_supported_source":
        allowed = []
    elif decision.scope == "memory_only":
        allowed = ["memory"]
    elif decision.scope == "dashboard_only":
        allowed = (["memory"] if memory_resolved else []) + ["dashboard"]
    elif decision.scope == "course_only":
        allowed = (["memory"] if memory_resolved else []) + ["course_material"]
    else:
        allowed = ["memory", "dashboard", "course_material"]
    universe = ["memory", "dashboard", "course_material"]
    return {
        "allowed": allowed,
        "prohibited": [category for category in universe if category not in allowed],
    }


def _render_source_boundary_capability(
    *,
    query_type: str,
    allowed_source_types: Sequence[str],
) -> str:
    allowed = ", ".join(allowed_source_types) or "no sources"
    return (
        f"The requested {query_type.replace('_', ' ')} needs course-content evidence, but this turn "
        f"is restricted to {allowed}. Dashboard activity can show views or engagement, not what a "
        "lecture covered. State this boundary directly and ask whether course materials may be used."
    )


def build_c_full_openai_messages(context: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build the one final LLM request for C_FULL."""

    return [
        {
            "role": "system",
            "content": (
                "You are a careful student-facing learning analytics assistant. "
                "Follow Mode C behaviour while using shared short-term memory and retrieved course material only when explicitly relevant. "
                "Answer using only the supplied context, stay direct, and state uncertainty where needed."
            ),
        },
        {"role": "user", "content": str(context.get("prompt", ""))},
    ]


def generate_c_full_response(
    *,
    student_query: str,
    student_id: str,
    current_page: str,
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    existing_session_memory: Mapping[str, Any] | None,
    dashboard_data: Any,
    openai_client: Any,
    model: str = "gpt-4o-mini",
    retrieval_backend: Literal["v1", "v2_4"] = "v1",
    retrieval_context: Mapping[str, Any] | None = None,
    allow_retrieval_v1_fallback: bool = False,
    intent_router_mode: str | None = None,
    intent_router_runtime: Any | None = None,
    intent_shadow_config: Any | None = None,
    intent_shadow_runtime: Any | None = None,
) -> CFullRuntimeResult:
    """Generate one final student-facing response through the shared C_FULL path."""

    context = build_c_full_context(
        student_query=student_query,
        student_id=student_id,
        current_page=current_page,
        conversation_history=conversation_history,
        existing_session_memory=existing_session_memory,
        dashboard_data=dashboard_data,
        retrieval_backend=retrieval_backend,
        retrieval_context=retrieval_context,
        allow_retrieval_v1_fallback=allow_retrieval_v1_fallback,
        intent_router_mode=intent_router_mode,
        intent_router_runtime=intent_router_runtime,
    )
    messages = build_c_full_openai_messages(context)
    completion = openai_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    response = str(completion.choices[0].message.content or "").strip()
    if not response:
        raise RuntimeError("OpenAI returned an empty C_FULL response.")

    if _resolve_intent_shadow_activation(intent_shadow_config):
        # Deliberately lazy: feature-off production calls do not import, load,
        # read, or initialise any semantic-shadow dependency.
        from utils.c_full_intent_shadow import safe_attach_c_full_intent_shadow

        context = safe_attach_c_full_intent_shadow(
            context=context,
            openai_messages=messages,
            runtime=intent_shadow_runtime,
        )

    retrieval = context.get("retrieval_result") or {}
    return CFullRuntimeResult(
        response=response,
        original_query=str(context.get("original_student_query", "")),
        resolved_query=str(context.get("resolved_student_query", "")),
        effective_query=str(context.get("effective_query", "")),
        query_type=str(context.get("query_type", "")),
        selected_route=str(context.get("selected_route", "")),
        selected_evidence_sources=list(context.get("rq1_selected_sources", [])),
        memory_metadata=dict(context.get("memory_metadata", {})),
        structured_memory=dict(context.get("structured_memory", {})),
        retrieval_used=bool(retrieval.get("retrieval_used")),
        retrieved_chunk_titles=(
            [str(source.get("title") or source.get("source_title") or "") for source in context.get("supporting_sources", [])]
            if context.get("retrieval_backend_requested") == "v2_4"
            else list(retrieval.get("retrieved_chunk_titles", []))
        ),
        recommendation_plan=dict(context.get("rq2_recommendation_plan", {})),
        context=context,
        openai_messages=messages,
    )


def generate_c_full_chat_turn(
    *,
    student_query: str,
    student_id: str,
    current_page: str,
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    existing_session_memory: Mapping[str, Any] | None,
    dashboard_data: Any,
    openai_client: Any,
    model: str = "gpt-4o-mini",
    max_history_messages: int = MAX_SESSION_MEMORY_MESSAGES,
    retrieval_backend: Literal["v1", "v2_4"] = "v1",
    retrieval_context: Mapping[str, Any] | None = None,
    allow_retrieval_v1_fallback: bool = False,
    intent_router_mode: str | None = None,
    intent_router_runtime: Any | None = None,
    intent_shadow_config: Any | None = None,
    intent_shadow_runtime: Any | None = None,
) -> CFullChatTurnOutcome:
    """Generate and atomically prepare state updates for one live chat turn."""

    original_history = list(conversation_history or [])
    original_memory = dict(existing_session_memory or {})
    try:
        runtime_result = generate_c_full_response(
            student_query=student_query,
            student_id=student_id,
            current_page=current_page,
            conversation_history=original_history,
            existing_session_memory=original_memory,
            dashboard_data=dashboard_data,
            openai_client=openai_client,
            model=model,
            retrieval_backend=retrieval_backend,
            retrieval_context=retrieval_context,
            allow_retrieval_v1_fallback=allow_retrieval_v1_fallback,
            intent_router_mode=intent_router_mode,
            intent_router_runtime=intent_router_runtime,
            intent_shadow_config=intent_shadow_config,
            intent_shadow_runtime=intent_shadow_runtime,
        )
        return _complete_successful_c_full_transaction(
            runtime_result=runtime_result,
            turn_start_state=original_memory,
            original_history=original_history,
            student_query=student_query,
            current_page=current_page,
            max_history_messages=max_history_messages,
        )
    except Exception:
        logger.exception("C_FULL transaction failed; all state changes were rolled back")
        return CFullChatTurnOutcome(
            succeeded=False,
            response=SAFE_C_FULL_ERROR_RESPONSE,
            memory_turns=original_history,
            structured_memory=original_memory,
        )


def _complete_successful_c_full_transaction(
    *,
    runtime_result: CFullRuntimeResult,
    turn_start_state: Mapping[str, Any],
    original_history: Sequence[Any],
    student_query: str,
    current_page: str,
    max_history_messages: int,
) -> CFullChatTurnOutcome:
    """Complete every post-model stage inside the caller's atomic boundary."""

    final_response = _postprocess_successful_response(runtime_result)
    commit = commit_successful_c_full_turn(
        turn_start_state=turn_start_state,
        pre_generation_state=runtime_result.structured_memory,
        original_user_query=student_query,
        assistant_response=final_response,
        current_page=current_page,
        query_type=runtime_result.query_type,
        selected_route=runtime_result.selected_route,
        memory_resolution=runtime_result.context.get("memory_resolution") or {},
        recommendation_plan=runtime_result.recommendation_plan,
        retrieval_result=runtime_result.context.get("retrieval_result") or {},
        retrieved_chunks=runtime_result.context.get("retrieved_context_chunks") or [],
        resolved_target_domain=str(runtime_result.context.get("resolved_target_domain", "")),
        selected_course_item=runtime_result.context.get("selected_course_item") or {},
        source_scope=str(runtime_result.context.get("source_scope", "")),
        source_retrieval_query=str(runtime_result.context.get("retrieval_query", "")),
        source_course_reference=_course_reference_from_query(student_query),
        supporting_course_chunk_ids=runtime_result.context.get("supporting_chunk_ids") or [],
    )
    context = dict(runtime_result.context)
    post_commit_metadata = dict(commit.post_commit_memory_metadata)
    post_commit_metadata.update({
        "retrieval_content_level": context.get("retrieval_content_level", "not_applicable"),
        "course_claim_support_chunks": list(context.get("course_claim_support_chunks") or []),
        "course_content_answer_guard_applied": bool(context.get("course_content_answer_guard_applied")),
        "completion_progression_guard_applied": bool(context.get("completion_progression_guard_applied")),
    })
    context["pre_generation_structured_memory"] = dict(runtime_result.structured_memory)
    context["pre_generation_memory_metadata"] = dict(runtime_result.memory_metadata)
    context["structured_memory"] = dict(commit.committed_structured_memory)
    context["memory_metadata"] = post_commit_metadata
    context["post_commit_structured_memory"] = dict(commit.committed_structured_memory)
    context["post_commit_memory_metadata"] = post_commit_metadata
    context["memory_commit"] = {
        "active_plan_updated": commit.active_plan_updated,
        "active_course_item_updated": commit.active_course_item_updated,
        "memory_commit_sources": commit.memory_commit_sources,
        "preserve_existing_active_plan": commit.preserve_existing_active_plan,
        "preserve_existing_numbered_referents": commit.preserve_existing_numbered_referents,
        "numbered_referents_updated": commit.numbered_referents_updated,
        "numbered_referents_source": commit.numbered_referents_source,
        "selected_course_item": commit.selected_course_item,
        "user_state_delta": commit.user_state_delta,
        "assistant_commit_delta": commit.assistant_commit_delta,
        "final_turn_delta": commit.final_turn_delta,
    }
    runtime_result = replace(
        runtime_result,
        response=final_response,
        structured_memory=dict(commit.committed_structured_memory),
        memory_metadata=post_commit_metadata,
        context=context,
    )
    updated_history = [*original_history, commit.committed_user_turn, commit.committed_assistant_turn]
    return CFullChatTurnOutcome(
        succeeded=True,
        response=final_response,
        memory_turns=updated_history[-max_history_messages:],
        structured_memory=dict(commit.committed_structured_memory),
        runtime_result=runtime_result,
    )


def commit_successful_c_full_turn(
    *,
    turn_start_state: Mapping[str, Any],
    pre_generation_state: Mapping[str, Any],
    original_user_query: str,
    assistant_response: str,
    current_page: str,
    query_type: str,
    selected_route: str,
    memory_resolution: Mapping[str, Any],
    recommendation_plan: Mapping[str, Any],
    retrieval_result: Mapping[str, Any],
    retrieved_chunks: Sequence[Mapping[str, Any]],
    resolved_target_domain: str,
    selected_course_item: Mapping[str, Any] | None = None,
    source_scope: str = "",
    source_retrieval_query: str = "",
    source_course_reference: str = "",
    supporting_course_chunk_ids: Sequence[str] = (),
) -> CommitResult:
    """Commit one successful C_FULL turn from structured runtime artifacts."""

    if not str(assistant_response or "").strip():
        raise ValueError("A successful C_FULL commit requires a non-empty assistant response.")

    start_state = dict(turn_start_state or {})
    state = dict(pre_generation_state or {})
    existing_plan = dict(state.get("active_plan") or {})
    preserve_plan = selected_route in {
        "memory_resolved_follow_up",
        "memory_plan_revision",
    }
    plan_policy = (
        "revise" if selected_route == "memory_plan_revision"
        else "preserve" if preserve_plan
        else "none"
    )
    sources = ["explicit_user_state"]
    active_plan_updated = False
    authoritative_plan: dict[str, Any] = {}

    if _may_create_authoritative_plan(
        original_user_query, selected_route, query_type, memory_resolution, recommendation_plan
    ):
        steps = [str(step).strip() for step in recommendation_plan.get("action_steps", []) if str(step).strip()]
        signature = "|".join(step.casefold() for step in steps)
        authoritative_plan = {
            "plan_id": f"plan-{hashlib.sha1(signature.encode('utf-8')).hexdigest()[:12]}",
            "goal": str(state.get("active_goal") or original_user_query),
            "constraints": list(state.get("constraints") or [])[-4:],
            "steps": [
                {"index": index, "action_text": step, "status": "pending"}
                for index, step in enumerate(steps, start=1)
            ],
            "source_turn_id": "current_successful_turn",
            "source_query_type": query_type,
            "source_route": selected_route,
            "source_domain": resolved_target_domain,
            "source_page": current_page,
            "source_query": original_user_query,
            "source_scope": source_scope,
            "source_course_reference": source_course_reference,
            "source_retrieval_query": source_retrieval_query,
            "supporting_course_chunk_ids": list(supporting_course_chunk_ids),
        }
        authoritative_plan = _enrich_committed_plan(authoritative_plan)
        state["active_plan"] = authoritative_plan
        state["selected_actions"] = _actions_for_committed_plan(authoritative_plan)
        plan_policy = "create"
        active_plan_updated = authoritative_plan != existing_plan
        sources.append("recommendation_plan.action_steps")
    elif existing_plan:
        state["active_plan"] = _enrich_committed_plan(existing_plan)
        state["selected_actions"] = _actions_for_committed_plan(state["active_plan"])

    item = dict(selected_course_item or {})
    previous_item = dict(state.get("active_course_item") or {})
    if item:
        if (
            previous_item.get("course_item_id")
            and previous_item.get("course_item_id") == item.get("course_item_id")
        ):
            item["last_source_query"] = item.get("source_query", "")
            item["last_retrieval_query"] = item.get("retrieval_query", "")
            for field in ("source_query", "source_route", "source_scope"):
                if previous_item.get(field):
                    item[field] = previous_item[field]
        item.setdefault("source_turn_id", "current_successful_turn")
        state["active_course_item"] = item
        state["course_entity_candidates"] = [item]
        sources.append("retrieval.selected_course_item")
    active_course_item_updated = bool(item and item != previous_item)

    numbered_referents: list[dict[str, Any]] = []
    numbered_kind = ""
    originating_kind = str((memory_resolution.get("memory_context") or {}).get("numbered_reference_kind", ""))
    preserve_numbered = selected_route in {
        "memory_resolved_follow_up",
        "memory_plan_revision",
    } and originating_kind in {"analytical_list", "action_plan"}
    numbered_referents_updated = False
    numbered_referents_source = "preserved_structured_memory" if preserve_numbered else "none"
    if authoritative_plan:
        numbered_kind = "action_plan"
        numbered_referents = [
            {
                "number": str(step["index"]),
                "text": step["action_text"],
                "numbered_reference_kind": "action_plan",
                "origin_query_type": query_type,
                "origin_route": selected_route,
                "origin_evidence_domain": resolved_target_domain,
                "origin_payload_key": f"action_step_{step['index']}",
                "structured_payload": dict(step),
            }
            for step in authoritative_plan["steps"]
        ]
        state["generic_numbered_referents"] = numbered_referents
        state["recent_numbered_recommendations"] = numbered_referents
        state["numbered_reference_kind"] = numbered_kind
        numbered_referents_updated = True
        numbered_referents_source = "recommendation_plan.action_steps"
    elif query_type == "quantitative_metric_query":
        numbered_referents = _analytical_referents_from_response(assistant_response, query_type, selected_route, resolved_target_domain)
        if preserve_numbered:
            numbered_kind = "analytical_list"
            numbered_referents = list(state.get("generic_numbered_referents") or [])
            state["last_explained_numbered_items"] = list(memory_resolution.get("referenced_items") or [])
        elif numbered_referents:
            numbered_kind = "analytical_list"
            state["generic_numbered_referents"] = numbered_referents
            state["numbered_reference_kind"] = numbered_kind
            numbered_referents_updated = True
            numbered_referents_source = "authoritative_quantitative_response"
    elif preserve_numbered and originating_kind == "action_plan":
        numbered_kind = "action_plan"
        numbered_referents = list(state.get("generic_numbered_referents") or [])
        state["last_explained_plan_items"] = list(memory_resolution.get("referenced_items") or [])

    user_delta = _structured_state_delta(start_state, pre_generation_state)
    assistant_delta = _structured_state_delta(pre_generation_state, state)
    final_delta = _structured_state_delta(start_state, state)
    active_plan_updated = "active_plan" in final_delta["updated_fields"]
    active_course_item_updated = "active_course_item" in final_delta["updated_fields"]
    correction_changed_state = bool(
        user_delta.get("active_course_item_corrected")
        or user_delta.get("active_goal_corrected")
        or ("corrections" in user_delta["updated_fields"] and len(user_delta["updated_fields"]) > 1)
    )

    post_metadata = dict(memory_resolution.get("runtime_metadata") or {})
    post_metadata.update({
        "memory_triggered": bool(memory_resolution.get("is_follow_up")),
        "memory_resolved": bool(memory_resolution.get("resolved")),
        "memory_used": bool(memory_resolution.get("resolved")),
        "memory_resolution_type": str(memory_resolution.get("resolution_type", "")),
        "numbered_reference_resolved": bool(memory_resolution.get("referenced_items")),
        "numbered_reference_kind": (
            (memory_resolution.get("memory_context") or {}).get("numbered_reference_kind")
            or numbered_kind
            or state.get("numbered_reference_kind", "")
        ),
        "referenced_items": list(memory_resolution.get("referenced_items") or []),
        "resolved_query": str(memory_resolution.get("resolved_query", "")) if memory_resolution.get("resolved") else "",
        "active_plan": dict(state.get("active_plan") or {}),
        "completed_steps": list((state.get("active_plan") or {}).get("completed_steps") or []),
        "pending_steps": list((state.get("active_plan") or {}).get("pending_steps") or []),
        "next_pending_step": (state.get("active_plan") or {}).get("next_pending_step"),
        "active_plan_complete": bool((state.get("active_plan") or {}).get("active_plan_complete")),
        "active_plan_updated": active_plan_updated,
        "active_course_item": dict(state.get("active_course_item") or {}),
        "active_course_item_updated": active_course_item_updated,
        "corrections_applied": correction_changed_state,
        "course_reference_triggered": bool((memory_resolution.get("memory_context") or {}).get("course_reference_triggered")),
        "course_reference_resolved": bool((memory_resolution.get("memory_context") or {}).get("course_reference_resolved")),
        "resolved_course_entity": (memory_resolution.get("memory_context") or {}).get("resolved_course_entity") or {},
        "memory_state_query_subtype": (memory_resolution.get("memory_context") or {}).get("memory_state_query_subtype", ""),
        "completed_actions_used": bool((memory_resolution.get("memory_context") or {}).get("completion_reference_resolved")),
        "memory_fields_updated": list(final_delta["updated_fields"]),
        "user_state_delta": user_delta,
        "assistant_commit_delta": assistant_delta,
        "final_turn_delta": final_delta,
        "preserve_existing_numbered_referents": preserve_numbered,
        "numbered_referents_updated": numbered_referents_updated,
        "numbered_referents_source": numbered_referents_source,
        "post_commit": True,
    })
    user_turn = {"role": "user", "content": original_user_query, "page": current_page}
    assistant_turn = {
        "role": "assistant",
        "content": assistant_response,
        "page": current_page,
        "query_type": query_type,
        "selected_route": selected_route,
        "memory_turn_kind": "successful_c_full_commit",
        "plan_update_policy": plan_policy,
        "numbered_reference_kind": numbered_kind,
        "origin_query_type": query_type,
        "origin_route": selected_route,
        "structured_plan": authoritative_plan,
        "selected_course_item": item,
        "structured_payload": {"numbered_referents": numbered_referents},
    }
    return CommitResult(
        committed_structured_memory=state,
        committed_user_turn=user_turn,
        committed_assistant_turn=assistant_turn,
        post_commit_memory_metadata=post_metadata,
        active_plan_updated=active_plan_updated,
        active_course_item_updated=active_course_item_updated,
        memory_commit_sources=sources,
        preserve_existing_active_plan=preserve_plan,
        preserve_existing_numbered_referents=preserve_numbered,
        numbered_referents_updated=numbered_referents_updated,
        numbered_referents_source=numbered_referents_source,
        selected_course_item=item,
        user_state_delta=user_delta,
        assistant_commit_delta=assistant_delta,
        final_turn_delta=final_delta,
    )


def build_c_full_prompt(
    *,
    scenario: Mapping[str, Any],
    evidence_result: Mapping[str, Any],
    query_type: str,
    selected_route: str,
    recommendation_plan: Mapping[str, Any],
    direct_response_reference: str,
    course_metadata: Mapping[str, Any],
    memory_context: str,
    retrieval_result: Mapping[str, Any],
    retrieved_chunks: Sequence[Any],
    selected_course_item: Mapping[str, Any] | None = None,
    retrieval_prompt_text: str | None = None,
    retrieval_generation_context: Mapping[str, Any] | None = None,
    source_scope: SourceScope = "dashboard_only",
    allowed_source_categories: Sequence[str] = (),
    prohibited_source_categories: Sequence[str] = (),
) -> str:
    """Build the evaluated C_FULL prompt with source boundaries intact."""

    sections = [
        "You are a GenAI assistant embedded in a learning analytics dashboard.",
        "Generate the final student-facing response for C_FULL.",
        "",
        f"Current dashboard page: {scenario.get('page', '')}",
        f"Student query: {scenario.get('student_query', '')}",
        f"Query type: {query_type}",
        f"Selected route: {selected_route}",
        "",
        "Authoritative source scope:",
        f"- scope: {source_scope}",
        "- allowed source categories: " + (", ".join(allowed_source_categories) or "none"),
        "- prohibited source categories: " + (", ".join(prohibited_source_categories) or "none"),
        "The prohibited categories must not be used for claims even if related words appear in the query.",
        "",
        "RQ1 selected evidence summary:",
        json.dumps(evidence_result, ensure_ascii=False, indent=2),
        "",
        "Route-specific instructions:",
        mode_c_route_guidance(selected_route, query_type),
    ]
    if recommendation_plan:
        sections.extend(
            [
                "",
                "RQ2 recommendation plan:",
                json.dumps(recommendation_plan, ensure_ascii=False, indent=2),
                "",
                "Use the recommendation plan naturally; do not invent evidence beyond the plan, selected evidence, or course metadata.",
            ]
        )
    course_allowed = "course_material" in allowed_source_categories
    memory_allowed = "memory" in allowed_source_categories
    if course_allowed and course_metadata:
        sections.extend(["", "Verified course metadata:", json.dumps(course_metadata, ensure_ascii=False, indent=2)])
    if course_allowed and selected_course_item:
        sections.extend(
            [
                "",
                "Authoritative selected course item:",
                json.dumps(selected_course_item, ensure_ascii=False, indent=2),
                "Name this exact item in the answer; do not substitute another reading.",
            ]
        )
    if direct_response_reference:
        sections.extend(
            [
                "",
                "Deterministic route reference only:",
                direct_response_reference,
                "Do not copy this reference mechanically.",
            ]
        )
    sections.extend(
        [
            "",
            "Source restrictions:",
            json.dumps(evidence_result.get("source_restrictions", {}), ensure_ascii=False, indent=2),
        ]
    )
    if memory_allowed:
        sections.extend(["", "C_FULL memory context:", memory_context])
    if course_allowed:
        sections.extend(
            [
                "",
                "C_FULL course-material retrieval status:",
                json.dumps(
                    retrieval_generation_context
                    if retrieval_generation_context is not None
                    else retrieval_result,
                    ensure_ascii=False,
                    indent=2,
                ),
                "",
                "Retrieved course-material chunks:",
                retrieval_prompt_text
                if retrieval_prompt_text is not None
                else format_retrieved_chunks_for_prompt(retrieved_chunks),
            ]
        )
    sections.extend(
        [
            "",
            "Grounding rules:",
            "- Memory supports only previous conversational references and explicit student statements."
            if memory_allowed
            else "- Memory is prohibited for claims in this turn.",
            "- Dashboard evidence supports claims about the student's activity."
            if "dashboard" in allowed_source_categories
            else "- Dashboard evidence is prohibited for claims in this turn.",
            "- Retrieved course material supports course, task, or content guidance only."
            if course_allowed
            else "- Course-material evidence and course metadata are prohibited for claims in this turn.",
            "- Enforce the authoritative source scope above. Omit prohibited evidence even if it appears elsewhere in context.",
            "- Never attribute a week-level Dashboard count to one specific reading, lecture, or paper.",
            "- Never reconstruct missing row-level records. If row_records.available is false, say that only aggregate evidence is available.",
            "- If retrieval_content_level is citation_only or title_and_metadata, do not infer a reading's arguments, methods, findings, benefits, or conclusions.",
            "- When the student asks for exactly three actions, visibly format exactly three non-empty lines as 1., 2., and 3.",
            "- Do not infer learning quality, ability, motivation, or causal effects.",
            "- Do not expose internal implementation details or file names.",
            "- Keep the answer concise and student-facing.",
        ]
    )
    return "\n".join(sections)


def mode_c_route_guidance(selected_route: str, query_type: str) -> str:
    if selected_route == "memory_plan_revision":
        return (
            "Use the revised structured active plan. Preserve completed actions exactly, "
            "show the updated constraint and pending actions, and do not create a replacement plan."
        )
    if selected_route == "memory_state_direct_answer":
        return "Answer only from explicit session Memory. If the requested state is absent, say so directly. Do not use Dashboard data or create a recommendation."
    if selected_route == "hybrid_course_and_planning":
        return "Use retrieved course context for content claims, the primary Dashboard domain for student activity, and the recommendation plan for visibly numbered actions. Keep the three source roles separate."
    if selected_route == "course_only_planning":
        return "Build the application plan only from approved course material. Do not imply access to or personalisation from Dashboard activity."
    if selected_route == "source_boundary_capability":
        return "State directly that the permitted dashboard data cannot answer the requested course-content question. Do not guess the course content or substitute activity data."
    if selected_route == "course_reference_clarification":
        return "Ask which of the recent course items the student means. Do not retrieve, select, or guess one."
    if query_type == "quantitative_metric_query":
        return "Report only supplied Lecture calculations. Include numerator, numeric denominator, and inclusion rule; never reconstruct unavailable rows or call an undefined metric a completion rate."
    if selected_route in DIRECT_FIRST_SENTENCE_ROUTES:
        return "Start with a direct answer. Explain provenance, availability, limitations, metadata, or correction; do not turn it into a plan."
    if selected_route == "metric_definition":
        return "Define the metric directly and briefly; do not add unnecessary action steps."
    if selected_route == "cross_page_relationship":
        return "Compare relevant cross-page patterns cautiously and avoid causal claims."
    if selected_route == "dashboard_interpretation":
        return "Explain the selected evidence pattern. A small next step is allowed only when it follows naturally."
    if selected_route == "reflection_structure":
        return "Give a concrete reflection structure and use dashboard activity only cautiously as context."
    if selected_route in RECOMMENDATION_ROUTES:
        return "Provide a concrete, evidence-grounded recommendation because the query asks for planning or improvement."
    if selected_route == "memory_resolved_follow_up":
        return "Use the resolved memory context for the referenced prior advice; do not claim previous context is unavailable."
    if selected_route == "follow_up_without_context":
        return "Explain the follow-up is underspecified and answer cautiously with available evidence."
    return f"Follow route {selected_route} for query type {query_type}."


def course_metadata_for_context(
    scenario: Mapping[str, Any],
    evidence_result: Mapping[str, Any],
    selected_route: str,
) -> dict[str, Any]:
    query = str(scenario.get("student_query", ""))
    metadata: dict[str, Any] = {}
    week = extract_week_key(query)
    if week:
        record = get_lecture_metadata(week)
        if record:
            metadata[week] = record
    if selected_route == "course_content" or any(term in query.lower() for term in ("lecture", "video", "pre-recorded", "week")):
        metadata.setdefault("lecture_titles_by_week", lecture_titles_by_week())
    return metadata


def extract_week_key(text: str) -> str:
    match = re.search(r"\bW(?:eek)?\s*(\d{1,2})\b", str(text), flags=re.IGNORECASE)
    if not match:
        return ""
    number = int(match.group(1))
    return f"W{number}" if 1 <= number <= 12 else ""


def normalise_c_full_query(query: str) -> tuple[str, list[dict[str, str]]]:
    """Apply explicitly allowlisted lexical and paraphrase corrections."""

    value, corrections, _diagnostics = _normalise_c_full_query_detailed(query)
    return value, corrections


def _normalise_c_full_query_detailed(
    query: str,
    *,
    current_page: str = "",
    enable_p2a_extensions: bool = True,
) -> tuple[str, list[dict[str, str]], list[dict[str, Any]]]:
    """Return lexical/page-aware normalisation plus separate diagnostics."""

    paraphrase = normalise_query_paraphrases(
        query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    paraphrase = normalise_overview_priority_paraphrase(
        paraphrase,
        current_page=current_page,
    )
    value = paraphrase.normalised_query
    corrections: list[dict[str, str]] = list(paraphrase.applied_rules)
    for misspelling, replacement in {
        "multimodle": "multimodal",
        "lectre": "lecture",
        "refleciton": "reflection",
        "resouces": "resources",
    }.items():
        if re.search(rf"\b{re.escape(misspelling)}\b", value, re.IGNORECASE):
            value = re.sub(
                rf"\b{re.escape(misspelling)}\b",
                replacement,
                value,
                flags=re.IGNORECASE,
            )
            corrections.append({"from": misspelling, "to": replacement})
    return value, corrections, list(paraphrase.diagnostics)


def _is_page_local_dashboard_priority(query: str) -> bool:
    """Return whether a priority phrase is limited to one dashboard page/domain."""

    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip()
    if not re.search(
        r"\b(?:focus on first|work on first|needs? (?:(?:the )?most )?attention|"
        r"improve first|biggest concern)\b",
        q,
    ):
        return False
    named_domains = detect_explicit_dashboard_domains(q)
    return len(named_domains) <= 1 and not is_explicit_whole_dashboard_query(q)


def detect_c_full_need_signals(
    query: str,
    *,
    current_page: str = "",
    active_course_item: Mapping[str, Any] | None = None,
    enable_p2a_extensions: bool = True,
) -> CFullNeedSignals:
    """Separate dashboard, course-content, and application needs audibly.

    A week or a dashboard-domain noun is only an entity signal. Course need
    additionally requires content-seeking or course-application language, while
    activity metrics remain strong dashboard signals.
    """

    q = re.sub(r"\s+", " ", str(query or "").casefold().replace("_", " ")).strip()
    week = extract_week_key(q)
    natural_course_coverage = _is_natural_course_coverage_query(q)
    try:
        page_domain = normalise_page(current_page) if current_page else ""
    except ValueError:
        page_domain = ""
    named_dashboard_domains = detect_explicit_dashboard_domains(q)
    explicit_domain = (
        detect_dashboard_application_target(q)
        or (named_dashboard_domains[0] if named_dashboard_domains else "")
    )
    dashboard_comparison_planning_need = bool(
        len(named_dashboard_domains) >= 2
        and re.search(
            r"\b(?:prioriti[sz]e|priority|bigger concern|which area|compare|relate|"
            r"related|unrelated|relationship|linked|connected|associated|correlated|connection|"
            r"patterns?|help explain|line up|go together|similar|differ|different|contrast|affect|"
            r"dashboard concern|focus|weakest|attention|work on|engagement gap|"
            r"falling behind)\b",
            q,
        )
    )
    location_pattern = (
        r"\b(?:where (?:can i )?(?:find|access)|where is|(?:can you )?show me|"
        + (
            r"give me(?=.{0,50}\b(?:w\d+|week\s+(?:\d+|[a-z-]+)|lecture|the reading|course material)\b)|"
            r"open|locate|find"
            if enable_p2a_extensions
            else r"give me(?: (?:the )?link)?|open"
        )
        + r")\b"
    )
    course_location_need = bool(
        re.search(
            location_pattern,
            q,
        )
        and (
            bool(re.search(r"\b(?:lecture|reading|debate material|course material|material|it|that)\b", q))
            or bool(active_course_item)
        )
    )
    plan_memory_need = bool(detect_plan_memory_intent(q))
    discrepancy_pattern = (
        r"\b(?:dashboard|data|number)\b.{0,100}\b(?:says?|shows?|zero|no|missing|wrong)\b"
        r".{0,120}\bbut\b|\b(?:not show|does not show|doesn't show|did not count|"
        r"activity is missing|number is wrong)\b"
    )
    if enable_p2a_extensions:
        discrepancy_pattern += (
            r"|\bcount cannot be right\b|"
            r"\b(?:attributed|assigned)\b.{0,100}\b(?:wrong|incorrect|correct)\b|"
            r"\bi meant\b.{0,100}\brather than\b"
        )
    discrepancy_correction_need = bool(
        re.search(
            discrepancy_pattern,
            q,
        )
    )
    causal_wording = bool(
        re.search(r"\b(?:cause|caused|causal|explain|because|lead to|affect|impact)\b", q)
    )
    explicit_source_restriction = bool(
        re.search(r"\b(?:dashboard data|course materials?|retrieved course evidence) only\b", q)
    )

    dashboard_activity_need = bool(
        re.search(
            r"\b(?:my|dashboard)\b.{0,80}\b(?:views?|engagement|posts?|replies|percentage|percent|"
            r"activity|low|increase|improve|edited characters?)\b",
            q,
        )
        or re.search(
            r"\b(?:debate|lecture|video|resources?|reflection)\s+(?:views?|posts?|replies|"
            r"percentage|activity|engagement|edited characters?)\b",
            q,
        )
        or re.search(
            r"\b(?:engagement|activity)\b.{0,50}\b(?:panels?|display|summary|pattern)\b|"
            r"\b(?:resource|reflection|discussion[- ]board) activity\b|"
            r"\bwhen i (?:open|view|access)\b.{0,50}\blearning resources?\b|"
            r"\bparticipation pattern\b",
            q,
        )
    )
    if dashboard_comparison_planning_need or discrepancy_correction_need:
        dashboard_activity_need = True
    planning_pattern = (
        r"\bhow (?:should|can|do) i (?:use|apply|connect|relate|integrate)\b|"
        r"\buse\b.{0,80}\b(?:in|for) my\b|"
        r"\b(?:apply|integrate)\b|"
        r"\b(?:connect|relate)\b.{0,80}\b(?:to|with) my\b|"
        r"\bimprove\b|\bhow (?:should|can|do) i\b|\brecommend\b"
        if enable_p2a_extensions
        else r"\b(?:use|apply|connect|relate|integrate)\b|\bimprove\b|\bhow (?:should|can|do) i\b|\brecommend\b"
    )
    planning_application_need = bool(re.search(planning_pattern, q))
    if planning_application_need and explicit_domain:
        dashboard_activity_need = True
    p2a_content_language = bool(enable_p2a_extensions and (
        re.search(
            r"\b(?:course guidance|teaching material|indexed (?:course )?(?:material|evidence)|retrieved material)\b",
            q,
        )
        or re.search(
            r"\b(?:identify|locate|find|summari[sz]e)\b.{0,80}"
            r"\b(?:course|teaching|indexed|retrieved|reading|lecture|debate)\b.{0,50}"
            r"\b(?:material|evidence|guidance|reading|lecture|discussion|supports?)\b",
            q,
        )
        or bool(week and re.search(r"\b(?:what question|what prompt|what topic|what was .* about|what .* cover)\b", q))
        or bool(re.search(r"\bwhich source is listed for\b", q))
    ))
    content_language = bool(
        natural_course_coverage
        or
        re.search(
            r"\b(?:what (?:was|is|are)|what did we|tell me|explain|summari[sz]e)\b.{0,100}"
            r"\b(?:about|topics?|cover(?:ed)?|content|findings?|arguments?|lecture|reading|week\s*\d+)\b",
            q,
        )
        or re.search(r"\b(?:topics?|what we covered|course content|course materials?)\b", q)
        or p2a_content_language
    )
    p2a_course_entity = bool(enable_p2a_extensions and (
        re.search(
            r"\b(?:course guidance|teaching material|indexed (?:course )?(?:material|evidence)|retrieved material)\b",
            q,
        )
        or re.search(r"\bwhich source is listed for\b", q)
    ))
    explicit_course_entity = bool(
        week
        or re.search(r"\b(?:core reading|course materials?|module content|lecture content)\b", q)
        or p2a_course_entity
        or (
            natural_course_coverage
            and (
                bool(re.search(r"\blecture\b", q))
                or page_domain == "lecture"
                or bool(active_course_item)
            )
        )
    )
    application_to_course_entity = bool(
        explicit_course_entity
        and planning_application_need
        and re.search(
            r"\b(?:lecture|reading|course materials?|what we covered|week\s*\d+|w\d+)\b",
            q,
        )
    )
    course_content_need = bool(
        explicit_course_entity
        and not dashboard_activity_need
        and (content_language or application_to_course_entity or course_location_need)
    )
    # A true cross-source application request may also mention an activity goal;
    # retain both needs rather than allowing the activity signal to suppress course content.
    if explicit_course_entity and planning_application_need and explicit_domain:
        course_content_need = bool(content_language or application_to_course_entity)

    return CFullNeedSignals(
        dashboard_activity_need=dashboard_activity_need,
        course_content_need=course_content_need,
        planning_application_need=planning_application_need,
        explicit_dashboard_domain=explicit_domain,
        explicit_course_entity=explicit_course_entity,
        week_reference=week,
        dashboard_comparison_planning_need=dashboard_comparison_planning_need,
        course_location_need=course_location_need,
        plan_memory_need=plan_memory_need,
        discrepancy_correction_need=discrepancy_correction_need,
        causal_wording=causal_wording,
        explicit_source_restriction=explicit_source_restriction,
    )


def authoritative_c_full_query_type(
    query: str,
    signals: CFullNeedSignals,
    *,
    enable_p2a_extensions: bool = True,
) -> str:
    """Return only high-confidence C_FULL overrides for natural query forms."""

    keyword_detail = classify_query_detailed(query)
    if (
        keyword_detail.is_explicit_match
        and keyword_detail.legacy_query_type == "cross_page_relationship"
    ):
        return "cross_page_relationship"
    if signals.plan_memory_need:
        return ""
    if signals.discrepancy_correction_need:
        return "discrepancy_or_correction"
    if signals.dashboard_comparison_planning_need:
        return "cross_page_relationship"
    if signals.course_location_need:
        return "course_content_question"
    if signals.course_content_need and not signals.dashboard_activity_need:
        return "course_content_question"
    if (
        enable_p2a_extensions
        and
        signals.dashboard_activity_need
        and not signals.course_content_need
        and re.search(
            r"\b(?:dashboard|activity (?:page|record|display|summary)|"
            r"viewing (?:habit|pattern)|participation pattern|recorded activity|"
            r"engagement\b.{0,50}\b(?:panels?|display|summary|pattern)|"
            r"(?:resource|reflection|discussion[- ]board) activity|"
            r"(?:open|view|access) learning resources?)\b",
            str(query or "").casefold(),
        )
    ):
        return "dashboard_interpretation"
    return ""


def _is_natural_course_coverage_query(query: str) -> bool:
    q = re.sub(r"\s+", " ", str(query or "").casefold()).strip()
    return bool(
        re.search(r"\bwhat did (?:the|this) lecture cover\b", q)
        or re.search(r"\bwhat was covered in (?:the|this) lecture\b", q)
        or re.search(r"\bwhat did we cover\b", q)
        or re.search(r"\bremind me what (?:the|this) lecture covered\b", q)
        or re.search(r"\bwhat (?:was|is) it about\b", q)
        or re.search(r"\b(?:explain|summari[sz]e) it\b", q)
        or re.search(r"\bwhat did it cover\b", q)
        or re.search(r"\bwhat were its main topics\b", q)
        or re.search(r"\bwhat did that cover\b", q)
        or re.search(r"\bwhat was that about\b", q)
        or re.search(r"\btell me more about that\b", q)
        or re.search(r"\bexplain that material\b", q)
        or re.search(r"\bwhat was the previous material about\b", q)
    )


def _is_course_only_planning_query(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> bool:
    q = str(query or "").casefold()
    return bool(
        re.search(
            r"\b(?:improve|plan|strategy|strategies|recommend|advice|apply|"
            + ("" if enable_p2a_extensions else "use|")
            + r"connect|"
            r"what should i do|how (?:can|should|do) i)\b",
            q,
        )
    )


def _plan_origin_uses_course_evidence(plan: Mapping[str, Any]) -> bool:
    return bool(
        str(plan.get("source_scope") or "") in {"course_only", "hybrid"}
        or str(plan.get("source_query_type") or "")
        in {"course_content_question", "hybrid_course_and_planning"}
        or str(plan.get("source_route") or "")
        in {"course_content", "course_only_planning", "hybrid_course_and_planning"}
    )


def _course_reference_from_query(query: str) -> str:
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    week = extract_week_key(q)
    material_match = re.search(
        r"\b(lecture|reading|course materials?|module content)\b",
        q,
        flags=re.IGNORECASE,
    )
    parts = [week.replace("W", "Week ") if week else ""]
    if material_match:
        parts.append(material_match.group(1).lower())
    return " ".join(part for part in parts if part).strip()


def _action_plan_retrieval_query(
    *,
    active_plan: Mapping[str, Any],
    referenced_items: Sequence[Mapping[str, Any]],
    current_follow_up: str,
) -> str:
    original_goal = str(
        active_plan.get("source_query")
        or active_plan.get("source_retrieval_query")
        or active_plan.get("goal")
        or ""
    ).strip()
    reference = str(active_plan.get("source_course_reference") or "").strip()
    if not reference:
        reference = _course_reference_from_query(original_goal)
    item_texts = [
        str(item.get("text") or item.get("action_text") or "").strip()
        for item in referenced_items
        if str(item.get("text") or item.get("action_text") or "").strip()
    ]
    if not item_texts:
        pending = active_plan.get("next_pending_step") or {}
        pending_text = str(pending.get("action_text") or "").strip()
        if pending_text:
            item_texts.append(pending_text)
    sections = ["Original hybrid goal:", original_goal]
    if reference:
        sections.extend(["", "Original course reference:", reference])
    sections.extend(
        [
            "",
            "Referenced plan item:",
            " | ".join(item_texts),
            "",
            "Current follow-up:",
            str(current_follow_up or "").strip(),
        ]
    )
    return "\n".join(sections).strip()


def _course_item_retrieval_query(
    course_item: Mapping[str, Any],
    current_query: str,
) -> str:
    label = " ".join(
        str(course_item.get(key) or "").strip()
        for key in ("week", "entity_type", "title")
        if str(course_item.get(key) or "").strip()
    )
    return f"Resolved course item:\n{label}\n\nCurrent query:\n{str(current_query or '').strip()}"


def detect_source_restrictions(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> dict[str, list[str]]:
    """Parse explicit source-scope instructions before evidence construction."""

    q = str(query or "").lower()
    allowed: list[str] = ["memory", "dashboard", "course_material"]
    excluded: list[str] = []
    if re.search(r"\b(?:course materials?|retrieved (?:course )?evidence) only\b", q):
        allowed = ["course_material"]
        excluded = ["memory", "dashboard"]
    elif enable_p2a_extensions and re.search(
        r"\b(?:dashboard (?:data )?only|from (?:my|the) dashboard only|"
        r"using only (?:my|the) dashboard(?: data)?)\b",
        q,
    ):
        allowed = ["dashboard"]
        excluded = ["memory", "course_material"]
    elif re.search(r"\bdashboard data only\b", q):
        allowed = ["dashboard"]
        excluded = ["memory", "course_material"]
    elif enable_p2a_extensions and re.search(
        r"\b(?:do not use|don't use|exclude|without)\s+(?:the\s+)?course materials?\b",
        q,
    ):
        allowed = ["memory", "dashboard"]
        excluded = ["course_material"]
    for domain in ("resources", "lecture", "debate", "reflection"):
        if re.search(rf"\b(?:do not use|don't use|exclude|without)\s+(?:the\s+)?{domain}\b", q):
            excluded.append(f"dashboard:{domain}")
    return {
        "allowed_source_types": allowed,
        "excluded_source_types": list(dict.fromkeys(excluded)),
    }


def decide_c_full_source_scope(
    *,
    query_type: str,
    selected_route: str,
    memory_resolved: bool,
    referenced_items: Sequence[Mapping[str, Any]],
    active_course_item: bool,
    course_reference_ambiguous: bool,
    allowed_source_types: Sequence[str],
    enable_p2a_extensions: bool = True,
) -> SourceScopeDecision:
    """Choose source scope from authoritative Memory, RQ1, and Mode C results.

    Retrieval implementations may refine a course query only after this
    decision. They are never permitted to classify the top-level user intent.
    """

    allowed = list(allowed_source_types)
    if query_type == "memory_state_query" or selected_route == "memory_state_direct_answer":
        return SourceScopeDecision(
            "memory_only", False, False, "The query asks for explicit structured session Memory state."
        )
    if course_reference_ambiguous or selected_route == "course_reference_clarification":
        return SourceScopeDecision(
            "memory_only",
            False,
            False,
            "The course reference is unresolved; clarification must precede retrieval.",
        )
    if enable_p2a_extensions and "course_material" not in allowed:
        conflict = query_type in {"course_content_question", "hybrid_course_and_planning"}
        return SourceScopeDecision(
            "dashboard_only",
            False,
            not conflict,
            (
                "The source restriction excludes course material required by this course-content request."
                if conflict
                else "The student explicitly excluded course-material evidence."
            ),
        )
    if allowed == ["dashboard"]:
        return SourceScopeDecision(
            "dashboard_only",
            False,
            query_type not in {"course_content_question", "hybrid_course_and_planning"},
            (
                "The dashboard-only restriction conflicts with a course-content request; "
                "the route must state the source boundary."
                if query_type in {"course_content_question", "hybrid_course_and_planning"}
                else "The student explicitly restricted the answer to dashboard data."
            ),
        )
    if allowed == ["course_material"]:
        return SourceScopeDecision(
            "course_only", True, False, "The student explicitly restricted the answer to course materials."
        )
    if memory_resolved and selected_route in {
        "memory_resolved_follow_up",
        "memory_plan_revision",
    }:
        origin_types = {
            str(item.get("origin_query_type") or "") for item in referenced_items
        }
        origin_routes = {
            str(item.get("origin_route") or "") for item in referenced_items
        }
        origin_types.discard("")
        origin_routes.discard("")
        if "hybrid_course_and_planning" in origin_types | origin_routes:
            return SourceScopeDecision(
                "hybrid",
                True,
                True,
                "Memory resolved items from the original hybrid course-and-planning route.",
            )
        if "course_content_question" in origin_types or "course_content" in origin_routes:
            return SourceScopeDecision(
                "course_only",
                True,
                False,
                "Memory resolved items from the original course-content route.",
            )
        if referenced_items and (origin_types or origin_routes):
            return SourceScopeDecision(
                "dashboard_only",
                False,
                True,
                "Memory resolved original dashboard-plan items; their stored source route remains authoritative.",
            )
        if active_course_item and query_type == "course_content_question":
            return SourceScopeDecision(
                "course_only",
                True,
                False,
                "Memory resolved an active course item whose content is required by the follow-up.",
            )
    if query_type == "hybrid_course_and_planning" or selected_route == "hybrid_course_and_planning":
        return SourceScopeDecision(
            "hybrid",
            True,
            True,
            "C_FULL identified both a course-content need and a dashboard-grounded planning need.",
        )
    if query_type == "course_content_question":
        return SourceScopeDecision(
            "course_only", True, False, "C_FULL classified the resolved query as a genuine course-content question."
        )
    return SourceScopeDecision(
        "dashboard_only",
        False,
        True,
        (
            "C_FULL classified the resolved query as dashboard-focused "
            f"({query_type or 'dashboard_interpretation'}); course retrieval is not required."
        ),
    )


def _assert_source_scope_invariants(
    *,
    decision: SourceScopeDecision,
    retrieval_needed: bool,
    authoritative_query_type: str,
    authoritative_selected_route: str,
    query_type: str,
    selected_route: str,
    dashboard_sources_before_scope: Sequence[str],
    dashboard_sources_after_scope: Sequence[str],
    dashboard_evidence_before_scope: Mapping[str, Any],
    dashboard_evidence_after_scope: Mapping[str, Any],
    retrieval_used: bool | None = None,
) -> None:
    """Fail closed if orchestration violates C_FULL source ownership."""

    assert query_type == authoritative_query_type, "Retrieval altered the authoritative C_FULL query type"
    assert selected_route == authoritative_selected_route, "Retrieval altered the authoritative C_FULL route"
    if decision.scope == "memory_only":
        assert not retrieval_needed, "Memory-only scope must not request course retrieval"
    elif decision.scope == "dashboard_only":
        assert not retrieval_needed, "Dashboard-only scope must not request course retrieval"
        if decision.preserve_dashboard_evidence:
            assert list(dashboard_sources_after_scope) == list(dashboard_sources_before_scope), (
                "Dashboard-only scope must preserve selected evidence sources"
            )
            assert dict(dashboard_evidence_after_scope) == dict(dashboard_evidence_before_scope), (
                "Dashboard-only scope must preserve selected dashboard evidence"
            )
        else:
            assert not dashboard_sources_after_scope and not dashboard_evidence_after_scope, (
                "A source-boundary route must not imply dashboard evidence can answer course content"
            )
    elif decision.scope == "course_only":
        assert retrieval_needed, "Course-only scope must request course retrieval"
        assert not dashboard_sources_after_scope and not dashboard_evidence_after_scope, (
            "Course-only scope must not expose dashboard evidence"
        )
    elif decision.scope == "hybrid":
        assert retrieval_needed, "Hybrid scope must request course retrieval"
        assert list(dashboard_sources_after_scope) == list(dashboard_sources_before_scope), (
            "Hybrid scope must preserve dashboard evidence sources"
        )
        assert dict(dashboard_evidence_after_scope) == dict(dashboard_evidence_before_scope), (
            "Hybrid scope must preserve selected dashboard evidence"
        )
    if retrieval_used is not None and decision.scope in {"memory_only", "dashboard_only"}:
        assert not retrieval_used, f"{decision.scope} scope must not use course retrieval"


def _apply_source_restrictions(
    evidence_result: Mapping[str, Any],
    restrictions: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    result = dict(evidence_result)
    allowed = set(restrictions.get("allowed_source_types") or [])
    excluded = set(restrictions.get("excluded_source_types") or [])
    if "dashboard" not in allowed:
        result["selected_sources"] = []
        result["selected_evidence"] = {}
        result["interpretation"] = "Dashboard evidence was excluded by the student's explicit source restriction."
        result["uncertainty"] = "Only allowed retrieved course-material evidence may be used."
        return result
    sources = [
        source
        for source in result.get("selected_sources", [])
        if f"dashboard:{source.split('.', 1)[0]}" not in excluded
    ]
    selected = dict(result.get("selected_evidence") or {})
    for excluded_item in excluded:
        if excluded_item.startswith("dashboard:"):
            selected.pop(excluded_item.split(":", 1)[1], None)
    result["selected_sources"] = sources
    result["selected_evidence"] = selected
    return result


def _memory_only_evidence_result(query: str, page: str) -> dict[str, Any]:
    return {
        "available": True,
        "primary_page": page,
        "query": query,
        "query_type": "memory_state_query",
        "selected_sources": [],
        "selected_evidence": {},
        "interpretation": "Answer from explicit session Memory only.",
        "uncertainty": "No Dashboard evidence may substitute for missing session Memory state.",
    }


def _target_domain_from_memory(
    state: Mapping[str, Any],
    referenced_items: Sequence[Mapping[str, Any]],
) -> str:
    active_plan = state.get("active_plan") or {}
    if referenced_items and str(state.get("numbered_reference_kind") or "") == "action_plan":
        source_domain = str(active_plan.get("source_domain") or "")
        if source_domain:
            return source_domain
    reference_text = " ".join(str(item.get("text", "")) for item in referenced_items)
    domain = detect_explicit_target_domain(reference_text)
    if domain:
        return domain
    entity = state.get("active_course_item") or {}
    entity_type = str(entity.get("entity_type", ""))
    if entity_type == "lecture":
        return "lecture"
    if entity_type == "reading":
        return "resources"
    next_step = active_plan.get("next_pending_step") or {}
    return detect_explicit_target_domain(str(next_step.get("action_text", "")))


def _supplementary_evidence_domains(sources: Sequence[str], primary: str) -> list[str]:
    domains: list[str] = []
    for source in sources:
        domain = str(source).split(".", 1)[0]
        if domain != primary and domain not in domains:
            domains.append(domain)
    return domains


def _render_memory_state_direct_answer(resolution: Any) -> str:
    context = resolution.memory_context or {}
    if context.get("state_reference_ambiguous"):
        return str(context.get("clarification_prompt") or "Please clarify what previous state you mean.")
    subtype = context.get("memory_state_query_subtype", "memory state")
    value = context.get("memory_state_value")
    if not value:
        return f"No explicit {subtype.replace('_', ' ')} is stored in this session Memory."
    if subtype == "current_course_item" and isinstance(value, Mapping):
        value = {
            key: value.get(key)
            for key in ("week", "entity_type", "material_type", "title")
            if value.get(key)
        }

    def prompt_safe(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                key: prompt_safe(child)
                for key, child in item.items()
                if key not in {
                    "chunk_ids", "supporting_chunk_ids", "supporting_course_chunk_ids",
                    "document_ids", "source_chunk_id",
                }
            }
        if isinstance(item, list):
            return [prompt_safe(child) for child in item]
        return item

    return (
        f"The explicit session Memory for {subtype.replace('_', ' ')} is: "
        f"{prompt_safe(value)}"
    )


def _render_course_reference_clarification(resolution: Any) -> str:
    context = resolution.memory_context or {}
    if context.get("unsupported_week"):
        expression = str(context.get("detected_week_expression") or "that week")
        return f"{expression} is outside the supported W1-W12 course range. Please choose a week from W1 to W12."
    candidates = context.get("course_entity_candidates") or []
    labels = [
        " ".join(str(item.get(key, "")) for key in ("week", "entity_type", "title") if item.get(key))
        for item in candidates
    ]
    if labels:
        return "I found more than one possible recent course item. Please specify which one you mean: " + "; ".join(labels)
    return (
        "There are multiple lectures in the course. Please specify the week or lecture title "
        "so I can retrieve the right course material."
    )


def _render_quantitative_lecture_reference(evidence_result: Mapping[str, Any]) -> str:
    lecture = (evidence_result.get("selected_evidence") or {}).get("lecture", {})
    quantitative = lecture.get("quantitative_metrics") or {}
    if not quantitative.get("row_level_records_available"):
        return "The available evidence contains only aggregate statistics, so I cannot reliably list each tracked row."
    calculations = quantitative.get("calculations") or {}
    lines = ["Use these supplied Lecture calculations only:"]
    for name, calculation in calculations.items():
        lines.append(
            f"- {name}: value={calculation.get('value')}; numerator={calculation.get('numerator')}; "
            f"denominator={calculation.get('denominator')}; rule={calculation.get('inclusion_rule')}"
        )
    return "\n".join(lines)


def _enforce_requested_action_count(query: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(plan)
    q = str(query or "").lower()
    match = re.search(r"\bexactly\s+(three|3)\s+(?:numbered\s+)?(?:actions?|steps?)\b", q)
    if not match:
        return out
    steps = [str(step).strip() for step in out.get("action_steps", []) if str(step).strip()]
    out["action_steps"] = steps[:3]
    return out


def _is_course_item_selection_query(query: str) -> bool:
    q = str(query or "").lower()
    has_week_item = bool(
        re.search(r"\b(?:w\d{1,2}|week\s*\d{1,2})\b.{0,40}\b(?:core\s+)?(?:reading|paper)\b", q)
        or re.search(r"\b(?:core\s+)?(?:reading|paper)\b.{0,20}\b(?:from|for)\s+(?:w\d{1,2}|week\s*\d{1,2})\b", q)
    )
    selection_intent = bool(
        re.search(r"\bchoose\b", q)
        or re.search(r"\bwhich\b.{0,80}\b(?:first|start|review|read|single|one|relevant)\b", q)
        or re.search(r"\bwhat is the first\b", q)
    )
    return has_week_item and selection_intent


def _select_core_reading(query: str, chunks: Sequence[Any]) -> dict[str, Any]:
    """Select the first complete entry in a requested week's Core Reading section."""

    week = extract_week_key(query)
    candidates = [chunk for chunk in chunks if not week or str(getattr(chunk, "week", "") or "").upper() == week]
    candidates.sort(key=lambda chunk: ("core reading" not in str(getattr(chunk, "text", "")).lower(), str(getattr(chunk, "chunk_id", ""))))
    for chunk in candidates:
        text = str(getattr(chunk, "text", ""))
        heading = re.search(r"\bCore readings?\s*:?[ ]*", text, flags=re.IGNORECASE)
        if not heading:
            continue
        section = text[heading.end():]
        boundary = re.search(
            r"\b(?:Further readings?|Recommended readings?|Additional readings?|Optional readings?|"
            r"Learning activities|Seminar activities|Assessment|Week\s+\d{1,2}:)\b",
            section,
            flags=re.IGNORECASE,
        )
        if boundary:
            section = section[:boundary.start()]
        match = re.match(
            r"\s*(.{3,260}?\(\d{4}[a-z]?\)\.)\s+(.{3,320}?\.)",
            section,
            flags=re.IGNORECASE,
        )
        if match:
            citation = re.sub(r"\s+", " ", match.group(1)).strip()
            title = re.sub(r"\s+", " ", match.group(2)).strip().rstrip(".")
            if not re.search(r"[A-Za-z]", citation) or not re.search(r"[A-Za-z]", title):
                continue
            return {
                "entity_type": "reading",
                "week": week or str(getattr(chunk, "week", "") or "").upper(),
                "title": title,
                "citation": citation,
                "source_chunk_id": str(getattr(chunk, "chunk_id", "")),
                "source_turn_id": "current_successful_turn",
            }
    return {}


def _derive_active_course_item(
    *,
    source_query: str,
    normalised_query: str,
    retrieval_query: str,
    selected_route: str,
    source_scope: str,
    retrieved_chunks: Sequence[Mapping[str, Any]],
    supporting_sources: Sequence[Mapping[str, Any]],
    supporting_chunk_ids: Sequence[str],
    evidence_sufficiency: Mapping[str, Any],
    active_course_item: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote one sufficiently resolved retrieved course entity into Memory."""

    status = str(evidence_sufficiency.get("status") or "")
    support_ids = [str(value) for value in supporting_chunk_ids if str(value)]
    if status not in {"sufficient", "partially_sufficient"} or not support_ids:
        return {}
    combined_query = f"{normalised_query}\n{retrieval_query}"
    requested_week = extract_week_key(combined_query)
    source_weeks = {
        str(item.get("week") or "").upper()
        for item in [*retrieved_chunks, *supporting_sources]
        if str(item.get("week") or "").strip()
    }
    if requested_week:
        source_weeks = {week for week in source_weeks if week == requested_week}
    if len(source_weeks) != 1:
        return {}
    week = next(iter(source_weeks))

    material_match = re.search(
        r"\b(lecture|reading|debate|assessment|reflection)\b",
        combined_query,
        flags=re.IGNORECASE,
    )
    material_type = material_match.group(1).lower() if material_match else ""
    if not material_type:
        material_type = str(
            (active_course_item or {}).get("material_type")
            or (active_course_item or {}).get("entity_type")
            or "material"
        )

    title = ""
    if material_type == "lecture":
        metadata = get_lecture_metadata(week) or {}
        title = str(metadata.get("title") or "").strip()
    if not title:
        preferred = next(
            (
                item
                for item in supporting_sources
                if str(item.get("week") or "").upper() == week
                and str(item.get("material_type") or "").casefold() == material_type
            ),
            None,
        )
        title = str((preferred or {}).get("title") or "").strip()
    if not title:
        return {}

    chunk_ids = list(
        dict.fromkeys(
            str(item.get("chunk_id") or "")
            for item in retrieved_chunks
            if str(item.get("chunk_id") or "")
        )
    )
    document_ids = list(
        dict.fromkeys(
            str(item.get("source_title") or "")
            for item in supporting_sources
            if str(item.get("source_title") or "")
        )
    )
    signature = f"{week}|{material_type}|{title}".casefold()
    return {
        "course_item_id": f"course-{hashlib.sha1(signature.encode('utf-8')).hexdigest()[:12]}",
        "week": week,
        "entity_type": material_type,
        "material_type": material_type,
        "title": title,
        "source_query": source_query,
        "source_route": selected_route,
        "source_scope": source_scope,
        "document_ids": document_ids,
        "chunk_ids": chunk_ids,
        "supporting_chunk_ids": support_ids,
        "retrieval_query": retrieval_query,
        "updated_at_turn": "current_successful_turn",
    }


def _may_create_authoritative_plan(
    query: str,
    route: str,
    query_type: str,
    memory_resolution: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> bool:
    genuine_route = route in RECOMMENDATION_ROUTES or route == "hybrid_course_and_planning"
    explicit_intent = bool(
        re.search(r"\b(?:plan|improve|recommend|recommendation|actions?|steps?|what should i do|how should i)\b", query, re.I)
    )
    excluded = route == "memory_resolved_follow_up" or query_type in {
        "memory_state_query", "quantitative_metric_query", "course_content_question", "metric_clarification"
    }
    return bool(genuine_route and explicit_intent and not excluded and plan.get("action_steps"))


def _enrich_committed_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(plan or {})
    steps = [dict(step) for step in out.get("steps", [])]
    steps.sort(key=lambda step: int(step.get("index", 0)))
    out["steps"] = steps
    out["completed_steps"] = [step for step in steps if step.get("status") == "completed"]
    out["pending_steps"] = [step for step in steps if step.get("status") != "completed"]
    out["next_pending_step"] = out["pending_steps"][0] if out["pending_steps"] else None
    out["active_plan_complete"] = bool(steps) and not out["pending_steps"]
    return out


def _actions_for_committed_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "text": str(step.get("action_text", "")),
            "number": str(step.get("index", "")),
            "status": str(step.get("status", "pending")),
            "source_turn": plan.get("source_turn_id", ""),
        }
        for step in plan.get("steps", [])
    ]


def _structured_state_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Describe explicit state changes between two transaction checkpoints."""

    tracked = (
        "active_goal", "goals", "constraints", "selected_actions", "completed_actions",
        "corrections", "relevant_pages", "generic_numbered_referents",
        "numbered_reference_kind", "active_plan", "active_course_item",
        "course_entity_candidates",
    )
    list_fields = {
        "goals", "constraints", "selected_actions", "completed_actions", "corrections",
        "relevant_pages", "generic_numbered_referents", "course_entity_candidates",
    }
    dict_fields = {"active_plan", "active_course_item"}
    def semantic(raw: Any) -> Any:
        if isinstance(raw, Mapping):
            return {
                key: semantic(item)
                for key, item in raw.items()
                if key not in {"source_turn", "source_turn_id"}
            }
        if isinstance(raw, list):
            return [semantic(item) for item in raw]
        return raw
    def value(state: Mapping[str, Any], field: str) -> Any:
        if field in list_fields:
            return semantic(list(state.get(field) or []))
        if field in dict_fields:
            return semantic(dict(state.get(field) or {}))
        return str(state.get(field) or "")
    updated = [field for field in tracked if value(before, field) != value(after, field)]
    before_plan = before.get("active_plan") or {}
    after_plan = after.get("active_plan") or {}
    before_item = before.get("active_course_item") or {}
    after_item = after.get("active_course_item") or {}
    before_goal = str(before.get("active_goal") or "")
    after_goal = str(after.get("active_goal") or "")
    corrections_added = max(0, len(after.get("corrections") or []) - len(before.get("corrections") or []))
    return {
        "updated_fields": updated,
        "state_changed": bool(updated),
        "active_plan_progress_updated": bool(before_plan and after_plan and before_plan != after_plan),
        "active_plan_created": bool(not before_plan and after_plan),
        "active_plan_replaced": bool(
            before_plan and after_plan and before_plan.get("plan_id") != after_plan.get("plan_id")
        ),
        "active_course_item_corrected": bool(
            before_item and after_item and before_item != after_item and corrections_added
        ),
        "active_course_item_created": bool(not before_item and after_item),
        "active_course_item_cleared": bool(before_item and not after_item),
        "active_goal_corrected": bool(before_goal and after_goal and before_goal != after_goal and corrections_added),
        "constraints_updated": "constraints" in updated,
        "completed_actions_updated": "completed_actions" in updated or (
            before_plan.get("completed_steps") != after_plan.get("completed_steps")
        ),
        "corrections_added": corrections_added,
        "selected_course_item_committed": bool(not before_item and after_item),
        "numbered_referents_created": bool(
            not before.get("generic_numbered_referents") and after.get("generic_numbered_referents")
        ),
    }


def _assess_retrieval_content_sufficiency(
    chunks: Sequence[Mapping[str, Any]],
    selected_course_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Classify how much claim-supporting content exists for one selected reading."""

    item = dict(selected_course_item or {})
    if str(item.get("entity_type") or "") != "reading":
        return {"retrieval_content_level": "not_applicable", "course_claim_support_chunks": []}
    title = re.sub(r"\W+", " ", str(item.get("title") or "")).casefold().strip()
    citation = str(item.get("citation") or "").casefold().strip()
    source_id = str(item.get("source_chunk_id") or "")
    relevant: list[Mapping[str, Any]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        normalized = re.sub(r"\W+", " ", text).casefold()
        citation_signal = bool(citation and citation[: min(45, len(citation))] in text.casefold())
        if (
            (source_id and str(chunk.get("chunk_id") or "") == source_id)
            or (title and title in normalized)
            or citation_signal
        ):
            relevant.append(chunk)
    metadata_only_fallback = False
    if not relevant:
        week = str(item.get("week") or "").upper()
        relevant = [
            chunk for chunk in chunks
            if (not week or str(chunk.get("week") or "").upper() == week)
            and re.search(r"\breadings?\b|\burl\b|\bselect activity\b", str(chunk.get("text") or ""), re.I)
        ]
        metadata_only_fallback = bool(relevant)
    support_ids = [str(chunk.get("chunk_id") or "") for chunk in relevant if chunk.get("chunk_id")]
    if not support_ids and source_id:
        support_ids = [source_id]
    level = (
        "title_and_metadata"
        if metadata_only_fallback
        else "citation_only" if (item.get("title") or item.get("citation")) else "title_and_metadata"
    )
    rank = {"citation_only": 1, "title_and_metadata": 2, "abstract_or_summary": 3, "body_excerpt": 4, "full_text": 5}
    for chunk in relevant:
        text = str(chunk.get("text") or "")
        lower = text.lower()
        candidate = "citation_only"
        if re.search(r"\b(?:full text|full-text)\b", lower) and len(text) >= 2000:
            candidate = "full_text"
        elif re.search(r"\babstract\b|\b(?:course|reading|paper) summary\b|\bsummary\s*:", lower):
            candidate = "abstract_or_summary"
        elif (
            len(text) >= 600
            and not re.search(r"\bcore readings?\b|\bfurther readings?\b|\brecommended readings?\b", lower)
            and str(chunk.get("source_type") or "") in {"reading", "paper", "pdf"}
        ):
            candidate = "body_excerpt"
        elif re.search(r"\burl\b|\bselect activity\b|\breadings?\b", lower) and not item.get("citation"):
            candidate = "title_and_metadata"
        if rank[candidate] > rank[level]:
            level = candidate
    return {
        "retrieval_content_level": level,
        "course_claim_support_chunks": list(dict.fromkeys(support_ids)),
    }


def _normalise_guidance_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-*:")


def _extract_plan_guidance(
    referenced_items: Sequence[tuple[str, str]], model_response: str
) -> dict[str, str]:
    """Pair model explanations with authoritative items without trusting model numbering."""

    response = model_response.strip()
    if not response:
        return {}

    requested_numbers = [number for number, _ in referenced_items]
    candidates: dict[str, str] = {}

    inline_pattern = re.compile(
        r"(?:\bfor\s+)?(?:the\s+last\s+original\s+plan\s+)?item\s+(\d+)\s*[:,]\s*",
        re.I,
    )
    inline_matches = list(inline_pattern.finditer(response))
    for position, match in enumerate(inline_matches):
        end = inline_matches[position + 1].start() if position + 1 < len(inline_matches) else len(response)
        candidates[match.group(1)] = response[match.end():end].strip(" \t\r\n.;")

    numbered_matches = list(re.finditer(r"(?m)^\s*(\d+)[.)]\s+(.+?)(?=\n\s*\d+[.)]\s+|\Z)", response, re.S))
    if numbered_matches:
        numbered = [
            (match.group(1), _normalise_guidance_text(match.group(2)))
            for match in numbered_matches
        ]
        if all(number in {candidate_number for candidate_number, _ in numbered} for number in requested_numbers):
            candidates.update(dict(numbered))
        else:
            for (requested_number, _), (_, guidance) in zip(referenced_items, numbered):
                candidates[requested_number] = guidance
    elif len(referenced_items) == 1 and not candidates:
        candidates[requested_numbers[0]] = response

    guidance_by_number: dict[str, str] = {}
    for number, action_text in referenced_items:
        guidance = _normalise_guidance_text(candidates.get(number, ""))
        action = _normalise_guidance_text(action_text)
        if not guidance or guidance.casefold().rstrip(".") == action.casefold().rstrip("."):
            continue
        guidance_by_number[number] = guidance
    return guidance_by_number


def _render_active_plan_explanation(
    referenced_items: Sequence[Mapping[str, Any]], model_response: str
) -> str:
    """Render authoritative plan indexes/text while retaining usable model guidance."""

    items = [
        (str(item.get("number") or ""), str(item.get("text") or "").strip())
        for item in referenced_items
        if item.get("number") and str(item.get("text") or "").strip()
    ]
    guidance = _extract_plan_guidance(items, model_response)
    rendered: list[str] = []
    for number, action_text in items:
        block = f"{number}. {action_text}"
        if guidance.get(number):
            block += f"\n   Guidance: {guidance[number]}"
        rendered.append(block)
    return "Requested original plan step(s):\n\n" + "\n\n".join(rendered)


def _render_completion_progression(
    completed_items: Sequence[Mapping[str, Any]], next_pending_step: Mapping[str, Any]
) -> str:
    completed = [
        (str(item.get("number") or item.get("index") or ""), str(item.get("text") or item.get("action_text") or "").strip())
        for item in completed_items
        if (item.get("number") or item.get("index"))
        and str(item.get("text") or item.get("action_text") or "").strip()
    ]
    next_number = str(next_pending_step.get("index") or next_pending_step.get("number") or "")
    next_text = str(next_pending_step.get("action_text") or next_pending_step.get("text") or "").strip()
    completed_block = "\n".join(f"{number}. {text}" for number, text in completed)
    return (
        f"You have completed:\n\n{completed_block}\n\n"
        f"Your next step is:\n\n{next_number}. {next_text}"
    )


def _render_citation_only_course_response(
    course_item: Mapping[str, Any], content_level: str
) -> str:
    title = str(course_item.get("title") or "").strip()
    citation = str(course_item.get("citation") or "").strip()
    week = str(course_item.get("week") or "").strip()
    label = title or " ".join(part for part in (week, "reading") if part).strip() or "the selected reading"
    bibliographic = "\n".join(part for part in (label, citation) if part)
    selection_note = (
        f" It was selected as the first complete item under the retrieved {week} Core Reading section."
        if week and title
        else ""
    )
    return (
        f"The retrieved course materials identify this reading:\n\n{bibliographic}\n\n"
        "However, the available indexed material contains only the title, citation, or course link, "
        "not the paper abstract or body. I therefore cannot reliably summarise its specific arguments "
        f"from the retrieved evidence.{selection_note}"
    )


def _render_active_plan_recall(plan: Mapping[str, Any]) -> str:
    if not plan or not plan.get("steps"):
        return (
            "There is no active plan stored in this session. Tell me the goal you want help "
            "with if you would like to create one."
        )
    goal = str(plan.get("goal") or "your current goal")
    lines = [f"Active plan for: {goal}"]
    for step in plan.get("steps", []):
        lines.append(
            f"{step.get('index')}. {step.get('action_text')} [{step.get('status', 'pending')}]"
        )
    return "\n".join(lines)


def _render_plan_revision(plan: Mapping[str, Any]) -> str:
    if not plan:
        return "There is no active plan to revise."
    constraints = list(plan.get("current_constraints") or plan.get("constraints") or [])
    lines = [
        f"I updated the pending actions in the existing plan (revision {plan.get('revision_number', 1)}).",
        "Current constraint: " + (", ".join(map(str, constraints)) or "none stated"),
    ]
    for step in plan.get("steps", []):
        lines.append(
            f"{step.get('index')}. {step.get('action_text')} [{step.get('status', 'pending')}]"
        )
    return "\n".join(lines)


def _postprocess_successful_response(result: CFullRuntimeResult) -> str:
    response = result.response.strip()
    if result.selected_route == "semantic_uncertain":
        routing = result.context.get("intent_routing") or {}
        hint = str(routing.get("clarification_hint_intent") or "")
        if hint == "planning_or_strategy":
            return "I’m not completely sure what you mean. Are you asking me to help organise a study plan?"
        if hint == "improvement_recommendation":
            return "I’m not completely sure what you mean. Are you asking for a study improvement or next step?"
        if hint == "course_content_question":
            return "Are you asking about course material, or about something shown on your dashboard?"
        if hint == "dashboard_metric_or_activity":
            return "Are you asking me to explain a dashboard metric or activity pattern?"
        return "Could you clarify what you’d like help with?"
    if result.selected_route == "social_interaction":
        return "Hello! I’m here whenever you’d like help with your learning dashboard or course materials."
    if result.selected_route == "unsupported_task":
        return (
            "I can help you understand your learning dashboard and available course materials, "
            "but I can’t carry out that action for you."
        )
    if result.selected_route == "out_of_scope":
        return (
            "That request is outside this learning-dashboard assistant’s scope. I can help with "
            "your dashboard activity, course materials, study recommendations, or a saved study plan."
        )
    if result.selected_route in {"ambiguous_clarification", "follow_up_without_context"}:
        return "I’m not sure what you’re referring to. Could you clarify the item or topic you want me to explain?"
    if result.selected_route == "source_boundary_capability":
        if result.context.get("intent_router_mode") == KEYWORD_BASELINE:
            return (
                "Dashboard data can show your lecture views and engagement, but it does not contain "
                "the lecture topics or content. Because you asked me to use dashboard data only, I "
                "cannot answer what Week 5 covered. You can allow course materials if you want that content checked."
            )
        week = extract_week_key(result.original_query)
        request_label = (
            f"what {week.replace('W', 'Week ')} covered"
            if week
            else "the requested course content"
        )
        return (
            "Dashboard data can show your lecture views and engagement, but it does not contain "
            "lecture, reading, or debate topics. Because you excluded course-material evidence, I "
            f"cannot answer {request_label}. You can allow course materials if you want that content checked."
        )
    if result.selected_route == "discrepancy_or_correction":
        return (
            "The dashboard record conflicts with what you reported doing. Activity logs can miss "
            "work because of timing, ingestion, page selection, or the dashboard's activity "
            "definition, but the available evidence does not identify one specific cause. Check "
            "the selected dates/page and the official submission or activity record; if the mismatch "
            "remains, report it to the module team with the approximate time of your work."
        )
    resolution = result.context.get("memory_resolution") or {}
    resolution_context = resolution.get("memory_context") or {}
    if (
        result.query_type == "memory_state_query"
        and resolution_context.get("memory_state_query_subtype") == "active_plan"
    ):
        return _render_active_plan_recall(
            resolution_context.get("memory_state_value") or {}
        )
    if result.selected_route == "memory_plan_revision":
        return _render_plan_revision(
            (result.structured_memory or {}).get("active_plan") or {}
        )
    if result.query_type == "quantitative_metric_query":
        return _render_quantitative_final(
            result.context.get("rq1_evidence_summary") or {},
            requested_quantitative_keys(
                result.original_query,
                result.effective_query,
                result.context.get("memory_resolution") or {},
            ),
            completion_rate_scope=bool(
                re.search(r"\b(?:lecture\s+)?completion (?:rate|percentage|percent)\b", result.original_query, re.I)
            ),
        )
    active_plan = dict((result.structured_memory or {}).get("active_plan") or {})
    if (
        resolution_context.get("completion_reference_resolved")
        and resolution.get("referenced_items")
        and active_plan.get("next_pending_step")
    ):
        result.context["completion_progression_guard_applied"] = True
        return _render_completion_progression(
            resolution.get("referenced_items") or [],
            active_plan.get("next_pending_step") or {},
        )
    if (
        result.selected_route == "memory_resolved_follow_up"
        and resolution_context.get("numbered_reference_kind") == "action_plan"
        and resolution.get("referenced_items")
    ):
        return _render_active_plan_explanation(resolution.get("referenced_items") or [], response)
    if _may_create_authoritative_plan(
        result.original_query,
        result.selected_route,
        result.query_type,
        result.context.get("memory_resolution") or {},
        result.recommendation_plan,
    ):
        steps = [str(step).strip() for step in result.recommendation_plan.get("action_steps", []) if str(step).strip()]
        response = _render_authoritative_recommendation(
            result.recommendation_plan,
            (result.structured_memory or {}).get("active_course_item") or {},
        )
    selected = result.context.get("selected_course_item") or {}
    if result.context.get("course_item_selection") and selected:
        return _render_authoritative_course_selection(selected)
    active_item = dict((result.structured_memory or {}).get("active_course_item") or {})
    content_level = str(result.context.get("retrieval_content_level") or "not_applicable")
    if (
        str(active_item.get("entity_type") or "") == "reading"
        and content_level in {"citation_only", "title_and_metadata"}
        and (
            result.selected_route == "memory_resolved_follow_up"
            or result.query_type == "course_content_question"
        )
    ):
        result.context["course_content_answer_guard_applied"] = True
        return _render_citation_only_course_response(active_item, content_level)
    response = _apply_v2_4_sufficiency_guard(result, response)
    if (
        result.selected_route == "cross_page_relationship"
        and (result.context.get("c_full_need_signals") or {}).get("causal_wording")
        and "not confirmed cause" not in response.casefold()
    ):
        response += (
            "\n\nThese activity traces can show an association between the patterns, not a "
            "confirmed cause."
        )
    return response


def _apply_v2_4_sufficiency_guard(
    result: CFullRuntimeResult,
    response: str,
) -> str:
    """Fail closed on unsupported v2.4 course claims after fake/live generation."""

    context = result.context
    if context.get("retrieval_backend_requested") != "v2_4":
        return response
    used = context.get("retrieval_backend_used")
    if used == "v1":
        return response
    retrieval = context.get("retrieval_result") or {}
    sufficiency = retrieval.get("evidence_sufficiency") or {}
    status = str(sufficiency.get("status") or "not_applicable")
    boundary = str(sufficiency.get("user_facing_boundary") or "").strip()
    has_dashboard_evidence = bool(context.get("rq1_selected_sources"))

    if status == "not_applicable":
        return response
    if not context.get("retrieval_available", True):
        warning = (
            "Course retrieval is temporarily unavailable, so course evidence was not checked."
        )
        return f"{response}\n\n{warning}" if has_dashboard_evidence else warning
    if status == "metadata_only":
        source_lines = list(context.get("source_display") or [])
        identified = "\n".join(f"- {line}" for line in source_lines)
        base = "Source identified; full content is not indexed."
        if identified:
            base += "\n\n" + identified
        return base + (f"\n\n{boundary}" if boundary else "")
    if status == "no_result":
        message = "No relevant evidence was found in the indexed course corpus."
        return f"{response}\n\n{message}" if has_dashboard_evidence else message
    if status == "insufficient":
        message = boundary or (
            "Related indexed evidence exists, but it is not detailed enough; a fuller course source is needed."
        )
        return f"{response}\n\n{message}" if has_dashboard_evidence else message
    if status == "partially_sufficient":
        message = boundary or "Only part of the course question is supported by indexed evidence."
        return f"{response}\n\n{message}"
    return response


def _render_quantitative_final(
    evidence_result: Mapping[str, Any],
    selected_keys: Sequence[str] | None = None,
    completion_rate_scope: bool = False,
) -> str:
    lecture = (evidence_result.get("selected_evidence") or {}).get("lecture") or {}
    quantitative = lecture.get("quantitative_metrics") or {}
    calculations = quantitative.get("calculations") or {}
    requested = list(selected_keys or QUANTITATIVE_LABELS)
    requested_names = ", ".join(QUANTITATIVE_LABELS.get(key, key.replace("_", " ")) for key in requested)
    availability_note = str(
        quantitative.get("row_level_availability_note")
        or (lecture.get("row_records") or {}).get("availability_note")
        or evidence_result.get("uncertainty")
        or ""
    ).strip()
    if not lecture:
        return (
            "No lecture activity data is available for this student, so I cannot calculate: "
            f"{requested_names}. No zero value has been assumed."
        )
    if not calculations and quantitative and not quantitative.get("row_level_records_available"):
        note = f" {availability_note}" if availability_note else ""
        return (
            "Lecture aggregate information is available, but the row-level data required for these calculations is unavailable, "
            f"so I cannot calculate: {requested_names}.{note} No zero value has been assumed."
        )
    if not calculations:
        return (
            "Lecture data is present, but the requested calculation is not available in the supplied evidence, "
            f"so I cannot calculate: {requested_names}. No zero value has been assumed."
        )
    sections = []
    iterable = [(key, calculations[key]) for key in requested if key in calculations]
    for index, (key, calc) in enumerate(iterable, start=1):
        value = calc.get("value")
        unit = str(calc.get("unit", ""))
        suffix = "%" if "percent" in unit.lower() or "percentage" in key else (" events" if key == "total_video_view_events" else "")
        denominator_label = "Row scope" if key == "total_video_view_events" else "Denominator"
        sections.append(
            f"{index}. {QUANTITATIVE_LABELS.get(key, key.replace('_', ' ').title())}:\n"
            f"- Value: {value}{suffix}\n"
            f"- Unit: {unit or ('percentage' if suffix == '%' else 'count')}\n"
            f"- Numerator: {calc.get('numerator')}\n"
            f"- {denominator_label}: {calc.get('denominator')}\n"
            f"- Inclusion rule: {calc.get('inclusion_rule')}"
        )
    missing = [key for key in requested if key not in calculations]
    if missing:
        names = ", ".join(QUANTITATIVE_LABELS.get(key, key.replace("_", " ")) for key in missing)
        sections.append(
            f"Unavailable requested calculation: {names}. The supplied Lecture evidence does not contain this calculation; no zero value has been assumed."
        )
    if completion_rate_scope:
        sections.append(
            "Scope limitation: this reports the average watched percentage among viewed real videos. "
            "It is not a universally defined course-completion rate and does not measure understanding or course completion."
        )
    return "\n\n".join(sections)


def requested_quantitative_keys(
    original_query: str,
    effective_query: str,
    memory_resolution: Mapping[str, Any],
) -> list[str]:
    """Return authoritative calculation keys explicitly requested by the student."""

    resolution = memory_resolution or {}
    selected: list[str] = []
    for item in resolution.get("referenced_items") or []:
        key = str(item.get("origin_payload_key", ""))
        text = str(item.get("text", "")).lower()
        if key:
            selected.append(key)
        elif "across real lecture rows" in text or "all real lecture rows" in text:
            selected.append("average_percentage_across_real_lecture_rows")
        elif "among viewed" in text:
            selected.append("average_percentage_among_viewed_videos")
        elif "all tracked rows" in text:
            selected.append("average_percentage_across_all_tracked_rows")
    if selected:
        return list(dict.fromkeys(selected))
    q = f"{original_query} {effective_query}".lower()
    all_keys = [
        "total_video_view_events",
        "unique_lecture_videos_viewed",
        "average_percentage_among_viewed_videos",
        "average_percentage_across_real_lecture_rows",
        "average_percentage_across_all_tracked_rows",
    ]
    if re.search(
        r"\b(?:report separately|all five|full five|each calculation|for each|every calculation|"
        r"(?:show|report|give me) all(?: lecture)? (?:metrics?|calculations?))\b",
        q,
    ):
        return all_keys
    patterns = (
        ("total_video_view_events", r"\b(?:total|sum|number of)\s+(?:video[- ]view events?|lecture views?)\b"),
        ("unique_lecture_videos_viewed", r"\b(?:how many\s+)?(?:unique\s+)?(?:real\s+)?lecture videos?\b.{0,30}\b(?:view|viewed)\b|\bunique videos? viewed\b"),
        ("average_percentage_among_viewed_videos", r"\b(?:average watched percentage|average view percentage|average percentage viewed|average percentage watched|average percent viewed|average percent watched|percentage viewed on average|percentage watched on average|my average viewing percentage|my average video[- ]view percentage|lecture completion (?:rate|percentage|percent)|my completion rate|among viewed(?: real)? videos?|viewed average|lecture average)\b"),
        ("average_percentage_across_real_lecture_rows", r"\baverage across (?:all )?real lecture rows\b|\breal rows average\b"),
        ("average_percentage_across_all_tracked_rows", r"\baverage across all tracked rows\b|\ball rows average\b"),
    )
    for key, pattern in patterns:
        if re.search(pattern, q):
            selected.append(key)
    return list(dict.fromkeys(selected)) or all_keys


def _render_authoritative_plan_response(response: str, steps: Sequence[str]) -> str:
    """Keep non-plan prose and insert exactly one visible authoritative plan block."""

    kept_lines = [
        line for line in response.splitlines()
        if not re.match(r"^\s*\d{1,2}[.)\-:]\s+", line)
    ]
    prose = "\n".join(kept_lines)
    for step in steps:
        stem = step.strip().rstrip(".")
        prose = re.sub(re.escape(stem) + r"\.?", "", prose, flags=re.IGNORECASE)
    prose = re.sub(r"[ \t]{2,}", " ", prose)
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip(" \n,;:-")
    if not re.search(r"[A-Za-z0-9]", prose):
        prose = ""
    block = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return f"{prose}\n\n{block}".strip() if prose else block


def _render_authoritative_recommendation(
    plan: Mapping[str, Any], active_course_item: Mapping[str, Any] | None = None
) -> str:
    """Render the complete new-plan response only from structured planner fields."""

    sections: list[str] = []
    item = active_course_item or {}
    item_label = " ".join(
        str(item.get(key, "")).strip()
        for key in ("week", "entity_type", "title")
        if str(item.get(key, "")).strip()
    )
    if item_label:
        sections.append(f"Course item: {item_label}.")
    for label, key in (
        ("Your data suggests", "student_state"),
        ("The main issue to focus on is", "main_issue"),
        ("My recommendation is", "recommended_action"),
        ("Why this matters", "why_this_matters"),
        ("Why this fits your situation", "why_this_fits_the_student"),
    ):
        value = str(plan.get(key, "")).strip()
        if value:
            sections.append(f"{label}: {value}")
    steps = [str(step).strip() for step in plan.get("action_steps", []) if str(step).strip()]
    if steps:
        sections.append("Try this next:\n" + "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)))
    limitations = str(plan.get("uncertainty_or_limitations", "")).strip()
    if limitations:
        sections.append(f"Limitations: {limitations}")
    return "\n\n".join(sections)


def _render_authoritative_course_selection(selected: Mapping[str, Any]) -> str:
    week = str(selected.get("week", "")).strip()
    title = str(selected.get("title", "")).strip()
    citation = str(selected.get("citation", "")).strip()
    return (
        f"For {week}, start with:\n\n{title}\n{citation}\n\n"
        f"This is the first complete item listed under the retrieved {week} Core Reading section. "
        "The available selection metadata does not establish details from the paper body."
    )


def _analytical_referents_from_response(
    response: str, query_type: str, route: str, domain: str
) -> list[dict[str, Any]]:
    items = []
    payload_keys = [
        "total_video_view_events",
        "unique_lecture_videos_viewed",
        "average_percentage_among_viewed_videos",
        "average_percentage_across_real_lecture_rows",
        "average_percentage_across_all_tracked_rows",
    ]
    for match in re.finditer(r"(?m)^\s*(\d{1,2})[.)]\s+(.+)$", response):
        number = int(match.group(1))
        text = match.group(2).strip()
        lower = text.lower()
        inferred_key = ""
        for phrase, key in (
            ("total video-view", "total_video_view_events"),
            ("unique real lecture", "unique_lecture_videos_viewed"),
            ("among viewed real", "average_percentage_among_viewed_videos"),
            ("all real lecture rows", "average_percentage_across_real_lecture_rows"),
            ("all tracked rows", "average_percentage_across_all_tracked_rows"),
        ):
            if phrase in lower:
                inferred_key = key
                break
        items.append({
            "number": str(number),
            "text": text,
            "numbered_reference_kind": "analytical_list",
            "origin_query_type": query_type,
            "origin_route": route,
            "origin_evidence_domain": domain,
            "origin_payload_key": inferred_key or (payload_keys[number - 1] if number <= len(payload_keys) else ""),
            "structured_payload": {},
        })
    return items
