"""Offline assistant mode runners for replay evaluation.

This module does not import Streamlit and does not call the production chatbot.
The first version returns deterministic offline responses plus constructed
prompts. Later, the same functions can call the OpenAI API behind the same
interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.evidence_synthesiser import DashboardData, classify_query, synthesise_evidence
from utils.conversation_memory import (
    MemoryResolution,
    format_memory_context_for_prompt,
    prepare_mode_cm_context,
)
from utils.course_material_retriever import (
    RetrievalResult,
    chunks_to_dicts,
    format_retrieved_chunks_for_prompt,
    retrieve_course_chunks,
    retrieval_result_to_dict,
    should_use_course_retrieval,
)
from utils.recommendation_planner import build_recommendation_plan, render_student_response
from utils.retrieval_v2.prompt_formatting import (
    allowed_chunks_for_generation as allowed_chunks_for_generation_v2,
    format_allowed_retrieval_context_for_prompt as format_retrieval_result_for_prompt_v2,
    render_student_boundary as render_student_boundary_v2,
)
from utils.retrieval_v2.retriever import retrieve_course_materials_v2


SUPPORTED_RQ1_PAGES = {"Overview", "Resources", "Lecture", "Debate", "Reflection"}


@dataclass
class AssistantModeResult:
    """Result returned by an offline assistant mode."""

    generated_response: str
    constructed_prompt: str
    rq1_selected_sources: list[str]
    rq1_evidence_summary: dict[str, Any]
    notes: str = ""
    selected_route: str = ""
    effective_query_type: str = ""
    memory_resolution: dict[str, Any] = field(default_factory=dict)
    memory_metadata: dict[str, Any] = field(default_factory=dict)
    resolved_student_query: str = ""
    original_student_query: str = ""
    retrieval_result: dict[str, Any] = field(default_factory=dict)
    retrieved_context_chunks: list[dict[str, Any]] = field(default_factory=list)
    memory_triggered: bool = False
    memory_used: bool = False
    memory_resolved: bool = False
    retrieval_used: bool = False
    required_capabilities: list[str] = field(default_factory=list)


def load_dashboard_data(project_root: Path = PROJECT_ROOT) -> DashboardData:
    """Load local anonymised dashboard data for offline replay."""

    required = {
        "moodle": project_root / "input" / "moodle" / "moodle_logs.csv",
        "echo": project_root / "input" / "echo" / "echo_logs.csv",
        "gdocs": project_root / "input" / "gdocs" / "activities.pkl",
        "features": project_root / "input" / "features" / "features.csv",
        "reply_network": project_root / "input" / "debate" / "reply_network.csv",
        "view_network": project_root / "input" / "debate" / "view_network.csv",
        "gdocs_ts": project_root / "input" / "gdocs" / "ts_cohorts.csv",
    }
    if not all(path.is_file() for path in required.values()):
        from evaluation.packaged_dashboard_fixture import build_packaged_dashboard_frames

        return DashboardData(**build_packaged_dashboard_frames())

    return DashboardData(
        moodle=pd.read_csv(required["moodle"]),
        echo=pd.read_csv(required["echo"]),
        gdocs=pd.read_pickle(required["gdocs"]),
        features=pd.read_csv(required["features"]),
        reply_network=pd.read_csv(required["reply_network"]),
        view_network=pd.read_csv(required["view_network"]),
        gdocs_ts=pd.read_csv(required["gdocs_ts"]),
    )


def run_assistant_mode(
    mode: str,
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """Run one offline assistant mode for a scenario."""

    mode = mode.upper().strip()
    if mode == "A":
        return run_mode_a_baseline(scenario)
    if mode == "B":
        return run_mode_b_rq1(scenario, dashboard_data)
    if mode == "C":
        return run_mode_c_rq1_rq2(scenario, dashboard_data)
    if mode in {"CM", "C_MEMORY"}:
        return run_mode_c_with_memory(scenario, dashboard_data)
    if mode in {"CR", "C_RAG"}:
        return run_mode_c_with_retrieval(scenario, dashboard_data)
    if mode in {"CR_V2", "C_RAG_V2"}:
        return run_mode_c_with_retrieval_v2(scenario, dashboard_data)
    if mode in {"C_FULL", "FULL", "CX"}:
        return run_mode_c_full(scenario, dashboard_data)
    if mode == "C_FULL_RAG_V2":
        return run_mode_c_full_v2(scenario, dashboard_data)
    raise ValueError(
        "Unsupported mode: " + mode
        + ". Expected A, B, C, CM, CR, C_FULL, CR_V2/C_RAG_V2, or C_FULL_RAG_V2."
    )


def run_mode_a_baseline(scenario: dict[str, Any]) -> AssistantModeResult:
    """Baseline-style page-specific assistant.

    This approximates the current assistant's information shape: current page,
    page-specific dashboard context, written feedback, few-shot style guidance,
    and the student's query. It deliberately does not use the RQ1 evidence
    synthesiser.
    """

    prompt = build_baseline_prompt(scenario)
    reference = str(scenario.get("baseline_reference_response") or "").strip()
    if reference:
        generated = (
            "[OFFLINE MODE A MOCK]\n"
            "This mode represents the existing baseline assistant. No API call was made; "
            "the stored baseline/reference response is returned for replay.\n\n"
            f"{reference}"
        )
    else:
        generated = (
            "[OFFLINE MODE A MOCK]\n"
            "No baseline reference response was available for this scenario. "
            "The constructed baseline prompt is available in constructed_prompt."
        )

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=[],
        rq1_evidence_summary={},
    )


def run_mode_b_rq1(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """RQ1 evidence-synthesis assistant.

    The mode constructs an assistant prompt from the selected RQ1 evidence
    summary. It returns a deterministic mock response for now.
    """

    evidence_result = build_rq1_evidence_summary(scenario, dashboard_data)
    prompt = build_rq1_prompt(scenario, evidence_result)
    selected_sources = evidence_result.get("selected_sources", [])
    selected_evidence = evidence_result.get("selected_evidence", {})

    if evidence_result.get("available") is False:
        generated = (
            "[OFFLINE MODE B MOCK]\n"
            "RQ1 evidence synthesis could not be applied to this scenario because "
            f"{evidence_result.get('reason', 'the page is unsupported')}."
        )
    else:
        generated = (
            "[OFFLINE MODE B MOCK]\n"
            f"Query type: {evidence_result.get('query_type')}.\n"
            f"Selected evidence sources: {', '.join(selected_sources)}.\n"
            "A live assistant response should answer using only this selected evidence, "
            "avoid broad dashboard dumping, and preserve the uncertainty boundaries.\n\n"
            f"Evidence summary:\n{json.dumps(selected_evidence, ensure_ascii=False, indent=2)}"
        )

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(selected_sources),
        rq1_evidence_summary=evidence_result,
        notes=str(evidence_result.get("reason", "")),
    )


def run_mode_c_rq1_rq2(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """RQ1 + RQ2 recommendation-planning assistant."""

    evidence_result = build_rq1_evidence_summary(scenario, dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(str(scenario.get("student_query", ""))))
    selected_route = route_for_mode_c(query_type, evidence_result)

    if evidence_result.get("available") is False:
        prompt = build_rq1_prompt(scenario, evidence_result) + f"\n\nMode C route: {selected_route}"
        generated = render_overview_fallback(scenario, query_type)
        notes = "Graceful fallback because structured RQ1 evidence is unavailable for this page."
    elif selected_route == "rq2_recommendation":
        recommendation_plan = build_recommendation_plan(
            student_query=str(scenario.get("student_query", "")),
            current_page=str(scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=None,
        )
        prompt = (
            build_rq1_prompt(scenario, evidence_result)
            + "\n\nMode C route: rq2_recommendation"
            + "\n\nRQ2 recommendation plan:\n"
            + json.dumps(recommendation_plan, ensure_ascii=False, indent=2)
        )
        generated = render_student_response(recommendation_plan)
        notes = "RQ2 recommendation planner applied without retrieved context chunks."
    else:
        prompt = build_rq1_prompt(scenario, evidence_result) + f"\n\nMode C route: {selected_route}"
        generated = render_direct_mode_c_response(
            scenario=scenario,
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=selected_route,
        )
        notes = f"Mode C used direct route: {selected_route}."

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(evidence_result.get("selected_sources", [])),
        rq1_evidence_summary=evidence_result,
        notes=notes,
        selected_route=selected_route,
        effective_query_type=query_type,
    )


def run_mode_c_with_memory(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """Mode C plus short-term rule-based conversational memory."""

    original_query = str(scenario.get("student_query", ""))
    history = scenario.get("conversation_history") or scenario.get("prior_turns") or []
    memory_runtime = prepare_mode_cm_context(
        student_query=original_query,
        conversation_history=history,
        existing_session_memory=scenario.get("session_memory") or scenario.get("c_full_memory"),
        current_page=str(scenario.get("page", "")),
    )
    memory_resolution = memory_runtime.memory_resolution
    assert memory_resolution is not None
    memory_dict = asdict(memory_resolution)
    memory_dict["runtime_metadata"] = memory_runtime.metadata()

    if not memory_resolution.resolved:
        result = run_mode_c_rq1_rq2(scenario, dashboard_data)
        result.memory_resolution = memory_dict
        result.memory_metadata = memory_runtime.metadata()
        result.original_student_query = original_query
        result.resolved_student_query = ""
        result.memory_triggered = bool(memory_resolution.is_follow_up)
        result.memory_used = False
        result.memory_resolved = False
        result.required_capabilities = list(scenario.get("required_capabilities", []))
        return result

    scenario_for_evidence = dict(scenario)
    scenario_for_evidence["student_query"] = memory_resolution.resolved_query

    evidence_result = build_rq1_evidence_summary(scenario_for_evidence, dashboard_data)
    query_type = str(
        evidence_result.get("query_type")
        or classify_query(str(scenario_for_evidence.get("student_query", "")))
    )
    original_route = route_for_mode_c(query_type, evidence_result)
    selected_route = "memory_resolved_follow_up"
    evidence_result["memory_resolution"] = memory_dict
    evidence_result["original_student_query"] = original_query
    evidence_result["resolved_student_query"] = memory_resolution.resolved_query
    evidence_result["mode_c_route_before_memory"] = original_route

    prompt = (
        build_rq1_prompt(scenario_for_evidence, evidence_result)
        + "\n\nMode CM route: memory_resolved_follow_up"
        + "\n\nShort-term memory context:\n"
        + format_memory_context_for_prompt(memory_resolution)
    )
    generated = render_memory_resolved_follow_up(
        scenario=scenario_for_evidence,
        evidence_result=evidence_result,
        memory_resolution=memory_resolution,
    )

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(evidence_result.get("selected_sources", [])),
        rq1_evidence_summary=evidence_result,
        notes=(
            "Mode CM resolved a context-dependent follow-up from recent conversational memory. "
            f"Original Mode C route after resolution would have been: {original_route}."
        ),
        selected_route=selected_route,
        effective_query_type=query_type,
        memory_resolution=memory_dict,
        memory_metadata=memory_runtime.metadata(),
        resolved_student_query=memory_resolution.resolved_query,
        original_student_query=original_query,
        memory_triggered=True,
        memory_used=True,
        memory_resolved=True,
        required_capabilities=list(scenario.get("required_capabilities", [])),
    )


def run_mode_c_with_retrieval(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """Mode C plus lightweight course-material retrieval support.

    This optional mode keeps Mode C's dashboard-evidence routing intact and
    adds local course-material chunks only when the query asks for course/task
    context that dashboard evidence alone cannot provide.
    """

    query = str(scenario.get("student_query", ""))
    evidence_result = build_rq1_evidence_summary(scenario, dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(query))
    selected_route = route_for_mode_c(query_type, evidence_result)
    retrieval_needed = should_use_course_retrieval(query, query_type)

    if not retrieval_needed:
        result = run_mode_c_rq1_rq2(scenario, dashboard_data)
        retrieval_result = RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was not needed for this query.",
        )
        result.retrieval_result = retrieval_result_to_dict(retrieval_result)
        result.retrieved_context_chunks = []
        result.notes = (result.notes + " " if result.notes else "") + "Mode CR did not use course retrieval for this query."
        return result

    retrieval_result = retrieve_course_chunks(query, query_type, top_k=4)
    retrieved_chunks = chunks_to_dicts(retrieval_result.chunks)

    if evidence_result.get("available") is False:
        prompt = build_rq1_prompt(scenario, evidence_result)
        generated = render_course_retrieval_fallback(scenario, retrieval_result)
        notes = "Mode CR used course-material retrieval with limited or unavailable RQ1 dashboard evidence."
    elif selected_route == "rq2_recommendation":
        recommendation_plan = build_recommendation_plan(
            student_query=query,
            current_page=str(evidence_result.get("primary_page") or scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=retrieved_chunks,
        )
        prompt = (
            build_rq1_prompt(scenario, evidence_result)
            + "\n\nMode CR route: rq2_recommendation"
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
            + "\n\nRQ2 recommendation plan with retrieved context:\n"
            + json.dumps(recommendation_plan, ensure_ascii=False, indent=2)
        )
        generated = render_student_response(recommendation_plan)
        if not retrieval_result.retrieval_used:
            generated += (
                "\n\nCourse-material limitation: I did not find a strong matching course-material chunk, "
                "so I should not add course-specific requirements beyond the dashboard evidence."
            )
        notes = "Mode CR passed retrieved course-material chunks into the RQ2 recommendation planner."
    else:
        prompt = (
            build_rq1_prompt(scenario, evidence_result)
            + f"\n\nMode CR route: {selected_route}"
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
        )
        generated = render_course_retrieval_direct_response(
            scenario=scenario,
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=selected_route,
            retrieval_result=retrieval_result,
        )
        notes = f"Mode CR used direct route {selected_route} with course-material retrieval context."

    retrieval_dict = retrieval_result_to_dict(retrieval_result)
    evidence_result = dict(evidence_result)
    evidence_result["course_retrieval"] = retrieval_dict

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(evidence_result.get("selected_sources", [])),
        rq1_evidence_summary=evidence_result,
        notes=notes,
        selected_route=selected_route,
        effective_query_type=query_type,
        retrieval_result=retrieval_dict,
        retrieved_context_chunks=retrieved_chunks,
    )


def _v2_planner_chunks(result: Any) -> list[dict[str, Any]]:
    """Expose only sufficiency-approved v2 evidence to the existing planner."""

    chunks: list[dict[str, Any]] = []
    for item in allowed_chunks_for_generation_v2(result):
        value = item.to_generation_dict()
        value["retrieval_source_type"] = value.get("source_type")
        value["source_type"] = "course_material"
        chunks.append(value)
    return chunks


def _render_v2_offline_response(result: Any) -> str:
    sufficiency = result.evidence_sufficiency
    boundary = render_student_boundary_v2(result)
    if sufficiency.status == "not_applicable":
        return boundary
    allowed = allowed_chunks_for_generation_v2(result)
    if sufficiency.status in {"no_result", "insufficient"}:
        return boundary
    source_lines = []
    for item in allowed[:3]:
        chunk = item.chunk
        excerpt = _short_excerpt(chunk.text, 360)
        source_lines.append(
            f"- {chunk.title} ({chunk.source_file}, {chunk.week or 'week unspecified'}): {excerpt}"
        )
    introduction = (
        "The indexed course evidence supports this answer:"
        if sufficiency.answerable
        else "The indexed course evidence supports only this limited source information:"
    )
    response = introduction
    if source_lines:
        response += "\n\n" + "\n".join(source_lines)
    if boundary:
        response += "\n\nEvidence boundary: " + boundary
    return response


def run_mode_c_with_retrieval_v2(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """CR_V2/C_RAG_V2: post-freeze experimental Retrieval v2 mode."""

    query = str(scenario.get("student_query", ""))
    evidence_result = build_rq1_evidence_summary(scenario, dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(query))
    selected_route = route_for_mode_c(query_type, evidence_result)
    retrieval = retrieve_course_materials_v2(query, query_type=query_type, top_k=4)
    retrieval_dict = retrieval.to_audit_dict()
    planner_chunks = _v2_planner_chunks(retrieval)

    if not retrieval.retrieval_requested:
        result = run_mode_c_rq1_rq2(scenario, dashboard_data)
        result.retrieval_result = retrieval_dict
        result.retrieved_context_chunks = []
        result.notes = (result.notes + " " if result.notes else "") + (
            "CR_V2 did not activate course retrieval for this query."
        )
        return result

    if selected_route == "rq2_recommendation" and planner_chunks:
        recommendation_plan = build_recommendation_plan(
            student_query=query,
            current_page=str(evidence_result.get("primary_page") or scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=planner_chunks,
        )
        generated = render_student_response(recommendation_plan)
        boundary = render_student_boundary_v2(retrieval)
        if boundary:
            generated += "\n\nCourse-evidence boundary: " + boundary
        prompt = (
            build_rq1_prompt(scenario, evidence_result)
            + "\n\nMode CR_V2 route: rq2_recommendation"
            + "\n\n"
            + format_retrieval_result_for_prompt_v2(retrieval)
            + "\n\nRQ2 recommendation plan with Retrieval v2 evidence:\n"
            + json.dumps(recommendation_plan, ensure_ascii=False, indent=2)
        )
    else:
        generated = _render_v2_offline_response(retrieval)
        prompt = (
            build_rq1_prompt(scenario, evidence_result)
            + f"\n\nMode CR_V2 route: {selected_route}\n\n"
            + format_retrieval_result_for_prompt_v2(retrieval)
        )

    evidence_result = dict(evidence_result)
    evidence_result["course_retrieval_v2"] = retrieval_dict
    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(evidence_result.get("selected_sources", [])),
        rq1_evidence_summary=evidence_result,
        notes="CR_V2 used the post-freeze experimental Retrieval v2 sufficiency contract.",
        selected_route=selected_route,
        effective_query_type=query_type,
        retrieval_result=retrieval_dict,
        retrieved_context_chunks=[item.to_dict() for item in allowed_chunks_for_generation_v2(retrieval)],
        retrieval_used=retrieval.retrieval_used,
        required_capabilities=list(scenario.get("required_capabilities", [])),
    )


def run_mode_c_full_v2(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """C_FULL_RAG_V2 with existing Memory/dashboard paths and Retrieval v2 only."""

    original_query = str(scenario.get("student_query", ""))
    history = scenario.get("conversation_history") or scenario.get("prior_turns") or []
    memory_runtime = prepare_mode_cm_context(
        student_query=original_query,
        conversation_history=history,
        existing_session_memory=scenario.get("session_memory") or scenario.get("c_full_memory"),
        current_page=str(scenario.get("page", "")),
    )
    memory_resolution = memory_runtime.memory_resolution
    assert memory_resolution is not None
    effective_query = memory_resolution.resolved_query if memory_resolution.resolved else original_query
    scenario_for_evidence = dict(scenario)
    scenario_for_evidence["student_query"] = effective_query
    base = run_mode_c_with_retrieval_v2(scenario_for_evidence, dashboard_data)
    memory_dict = asdict(memory_resolution)
    memory_dict["runtime_metadata"] = memory_runtime.metadata()
    retrieval = base.retrieval_result
    selected_route = "memory_resolved_follow_up" if memory_resolution.resolved else base.selected_route
    prompt = (
        base.constructed_prompt
        + "\n\nMode C_FULL_RAG_V2 route: "
        + selected_route
        + "\n\nShort-term Memory context:\n"
        + format_memory_context_for_prompt(memory_resolution)
        + "\n\nSource roles: Memory resolves conversational references; dashboard evidence describes student activity; "
        "Retrieval v2 supports only course claims allowed by evidence_sufficiency."
    )
    generated = base.generated_response
    if memory_resolution.resolved:
        generated = render_memory_resolved_follow_up(
            scenario=scenario_for_evidence,
            evidence_result=base.rq1_evidence_summary,
            memory_resolution=memory_resolution,
        )
        sufficiency = retrieval.get("evidence_sufficiency", {})
        if sufficiency.get("status") not in {"not_applicable", "no_result"}:
            generated += "\n\n" + base.generated_response
        elif sufficiency.get("status") == "no_result":
            generated += "\n\nCourse-evidence boundary: " + sufficiency.get("user_facing_boundary", "")
    base.generated_response = generated
    base.constructed_prompt = prompt
    base.notes = "C_FULL_RAG_V2 reused Memory, dashboard synthesis, routing, and planning with Retrieval v2."
    base.selected_route = selected_route
    base.memory_resolution = memory_dict
    base.memory_metadata = memory_runtime.metadata()
    base.resolved_student_query = effective_query if memory_resolution.resolved else ""
    base.original_student_query = original_query
    base.memory_triggered = bool(memory_resolution.is_follow_up)
    base.memory_used = bool(memory_resolution.resolved)
    base.memory_resolved = bool(memory_resolution.resolved)
    return base


def run_mode_c_full(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> AssistantModeResult:
    """Integrated Mode C with optional memory and course-material retrieval.

    C_FULL is an offline prototype that composes the existing optional
    extensions. It does not replace Mode C, Mode CM, or Mode CR.
    """

    original_query = str(scenario.get("student_query", ""))
    history = scenario.get("conversation_history") or scenario.get("prior_turns") or []
    memory_runtime = prepare_mode_cm_context(
        student_query=original_query,
        conversation_history=history,
        existing_session_memory=scenario.get("session_memory") or scenario.get("c_full_memory"),
        current_page=str(scenario.get("page", "")),
    )
    memory_resolution = memory_runtime.memory_resolution
    assert memory_resolution is not None
    memory_dict = asdict(memory_resolution)
    memory_dict["runtime_metadata"] = memory_runtime.metadata()
    query_for_evidence = memory_resolution.resolved_query if memory_resolution.resolved else original_query

    scenario_for_evidence = dict(scenario)
    scenario_for_evidence["student_query"] = query_for_evidence
    evidence_result = build_rq1_evidence_summary(scenario_for_evidence, dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(query_for_evidence))
    mode_c_route = route_for_mode_c(query_type, evidence_result)

    retrieval_needed = should_use_course_retrieval(query_for_evidence, query_type)
    retrieval_result = (
        retrieve_course_chunks(query_for_evidence, query_type, top_k=4)
        if retrieval_needed
        else RetrievalResult(
            query=query_for_evidence,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was not needed for this resolved query.",
        )
    )
    retrieved_chunks = chunks_to_dicts(retrieval_result.chunks)
    retrieval_dict = retrieval_result_to_dict(retrieval_result)

    selected_route = "memory_resolved_follow_up" if memory_resolution.resolved else mode_c_route
    evidence_result = dict(evidence_result)
    evidence_result["c_full_mode_c_route"] = mode_c_route
    evidence_result["memory_resolution"] = memory_dict
    evidence_result["course_retrieval"] = retrieval_dict
    evidence_result["original_student_query"] = original_query
    evidence_result["resolved_student_query"] = query_for_evidence if memory_resolution.resolved else ""

    if evidence_result.get("available") is False:
        generated = render_course_retrieval_fallback(scenario_for_evidence, retrieval_result)
        prompt = (
            build_rq1_prompt(scenario_for_evidence, evidence_result)
            + "\n\nMode C_FULL route: "
            + selected_route
            + "\n\nMemory context:\n"
            + format_memory_context_for_prompt(memory_resolution)
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
        )
        notes = "C_FULL used graceful fallback because structured dashboard evidence was unavailable."
    elif mode_c_route == "rq2_recommendation":
        recommendation_plan = build_recommendation_plan(
            student_query=query_for_evidence,
            current_page=str(evidence_result.get("primary_page") or scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=retrieved_chunks if retrieval_result.retrieval_used else None,
        )
        generated = render_student_response(recommendation_plan)
        if memory_resolution.resolved:
            if memory_resolution.referenced_items:
                item_numbers = ", ".join(item["number"] for item in memory_resolution.referenced_items)
                acknowledgement = f"I’m reading your question as a follow-up about previous item(s) {item_numbers}."
            else:
                acknowledgement = _structured_memory_acknowledgement(memory_resolution)
            generated = acknowledgement + "\n\n" + generated
        if retrieval_needed and not retrieval_result.retrieval_used:
            generated += (
                "\n\nCourse-material limitation: I did not find a strong matching course-material chunk, "
                "so I should not add course-specific requirements beyond the dashboard evidence."
            )
        prompt = (
            build_rq1_prompt(scenario_for_evidence, evidence_result)
            + "\n\nMode C_FULL route: "
            + selected_route
            + "\n\nMode C route before C_FULL composition: "
            + mode_c_route
            + "\n\nMemory context:\n"
            + format_memory_context_for_prompt(memory_resolution)
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
            + "\n\nRQ2 recommendation plan:\n"
            + json.dumps(recommendation_plan, ensure_ascii=False, indent=2)
        )
        notes = "C_FULL used RQ2 recommendation planning with optional memory and retrieval context."
    elif memory_resolution.resolved:
        generated = render_memory_resolved_follow_up(
            scenario=scenario_for_evidence,
            evidence_result=evidence_result,
            memory_resolution=memory_resolution,
        )
        if retrieval_result.retrieval_used:
            generated += (
                "\n\nRelevant course-material context:\n"
                + _retrieved_course_context_text(retrieval_result.chunks)
                + "\n\nBoundary: I used the previous conversation only to resolve your reference, dashboard evidence for your activity, and course material for task guidance."
            )
        elif retrieval_needed:
            generated += (
                "\n\nCourse-material limitation: I did not find a strong matching course-material chunk, "
                "so I should not add course-specific requirements beyond the dashboard evidence."
            )
        prompt = (
            build_rq1_prompt(scenario_for_evidence, evidence_result)
            + "\n\nMode C_FULL route: memory_resolved_follow_up"
            + "\n\nMemory context:\n"
            + format_memory_context_for_prompt(memory_resolution)
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
        )
        notes = "C_FULL resolved a short-term follow-up and used retrieval only if the resolved query required it."
    else:
        prompt = (
            build_rq1_prompt(scenario_for_evidence, evidence_result)
            + "\n\nMode C_FULL route: "
            + selected_route
            + "\n\nRetrieved course-material chunks:\n"
            + format_retrieved_chunks_for_prompt(retrieval_result.chunks)
        )
        if retrieval_result.retrieval_used or retrieval_needed:
            generated = render_course_retrieval_direct_response(
                scenario=scenario_for_evidence,
                evidence_result=evidence_result,
                dashboard_data=dashboard_data,
                selected_route=mode_c_route,
                retrieval_result=retrieval_result,
            )
        else:
            generated = render_direct_mode_c_response(
                scenario=scenario_for_evidence,
                evidence_result=evidence_result,
                dashboard_data=dashboard_data,
                selected_route=mode_c_route,
            )
        notes = "C_FULL used Mode C routing with optional retrieval context."

    return AssistantModeResult(
        generated_response=generated,
        constructed_prompt=prompt,
        rq1_selected_sources=list(evidence_result.get("selected_sources", [])),
        rq1_evidence_summary=evidence_result,
        notes=notes,
        selected_route=selected_route,
        effective_query_type=query_type,
        memory_resolution=memory_dict,
        memory_metadata=memory_runtime.metadata(),
        resolved_student_query=query_for_evidence if memory_resolution.resolved else "",
        original_student_query=original_query,
        retrieval_result=retrieval_dict,
        retrieved_context_chunks=retrieved_chunks,
        memory_triggered=bool(memory_resolution.is_follow_up),
        memory_used=bool(memory_resolution.resolved),
        memory_resolved=bool(memory_resolution.resolved),
        retrieval_used=bool(retrieval_result.retrieval_used),
        required_capabilities=list(scenario.get("required_capabilities", [])),
    )


def render_course_retrieval_fallback(scenario: dict[str, Any], retrieval_result: Any) -> str:
    """Render a graceful response when only course retrieval is available."""

    if retrieval_result.retrieval_used:
        return (
            "The dashboard evidence is limited for this question, so I used the available course-material context instead.\n\n"
            + _retrieved_course_context_text(retrieval_result.chunks)
            + "\n\nLimitations: this course-material context can guide course/task interpretation, but it does not show your personal activity."
        )
    return (
        "I do not have enough dashboard evidence or a strong matching course-material chunk to answer this precisely. "
        "Please ask about a specific lecture week, reading, debate prompt, reflection task, or assessment item."
    )


def render_course_retrieval_direct_response(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
    dashboard_data: DashboardData,
    selected_route: str,
    retrieval_result: Any,
) -> str:
    """Render direct Mode C routes with optional retrieved course context."""

    base = render_direct_mode_c_response(
        scenario=scenario,
        evidence_result=evidence_result,
        dashboard_data=dashboard_data,
        selected_route=selected_route,
    )
    if not retrieval_result.retrieval_used:
        return (
            base
            + "\n\nCourse-material limitation: I did not find a strong matching course-material chunk, "
            "so I should not add course-specific requirements beyond the selected dashboard evidence."
        )

    course_context = _retrieved_course_context_text(retrieval_result.chunks)
    if selected_route == "course_content":
        return (
            "The retrieved course material provides the most relevant available course context for this question.\n\n"
            + course_context
            + "\n\nDashboard boundary: dashboard activity logs can show access or viewing behaviour, but course-material chunks are what support claims about topics, readings, prompts, links, or assessment guidance."
        )
    if selected_route == "access_or_capability":
        return (
            base
            + "\n\nRelevant retrieved course-material context:\n"
            + course_context
            + "\n\nAccess boundary: I can use only the retrieved local course-material text, not private systems or unavailable full recordings."
        )
    if selected_route == "reflection_structure":
        return (
            base
            + "\n\nRelevant course-material guidance:\n"
            + course_context
            + "\n\nUse this as task guidance, not as evidence of reflection quality."
        )
    return (
        base
        + "\n\nRelevant course-material context:\n"
        + course_context
        + "\n\nBoundary: use dashboard evidence for your activity pattern and course-material chunks for course/task guidance."
    )


def _retrieved_course_context_text(chunks: list[Any], max_chunks: int = 3) -> str:
    """Summarise retrieved chunks for deterministic student-facing responses."""

    if not chunks:
        return "No course-material chunks were retrieved."
    lines: list[str] = []
    for chunk in chunks[:max_chunks]:
        title = getattr(chunk, "title", "")
        source = getattr(chunk, "source_file", "")
        week = getattr(chunk, "week", None)
        task_type = getattr(chunk, "task_type", None)
        labels = []
        if week:
            labels.append(str(week))
        if task_type:
            labels.append(str(task_type))
        label_text = f" ({', '.join(labels)})" if labels else ""
        source_text = f" from {source}" if source else ""
        excerpt = _short_excerpt(getattr(chunk, "text", ""))
        lines.append(f"- {title}{label_text}{source_text}: {excerpt}")
    return "\n".join(lines)


def _short_excerpt(text: Any, max_chars: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def build_baseline_prompt(scenario: dict[str, Any]) -> str:
    """Construct a baseline-style prompt without RQ1 selective synthesis."""

    page = scenario.get("page", "")
    return "\n".join(
        [
            "You are a GenAI assistant embedded in a learning analytics dashboard.",
            "Use the current page's visual description, written feedback, few-shot examples, and page data.",
            "Do not use cross-page evidence unless it is already present in the current page context.",
            "",
            f"Current page: {page}",
            f"Query type: {scenario.get('query_type', '')}",
            f"Student query: {scenario.get('student_query', '')}",
            "",
            "Baseline page context:",
            baseline_context_placeholder(page),
        ]
    )


def build_rq1_prompt(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    """Construct a prompt using the RQ1 selected evidence summary."""

    return "\n".join(
        [
            "You are a GenAI assistant embedded in a learning analytics dashboard.",
            "Answer using the selected evidence only. Do not dump all dashboard data.",
            "Avoid claims about learning quality, understanding, or causality unless the evidence supports them.",
            "",
            f"Current page: {scenario.get('page', '')}",
            f"Student query: {scenario.get('student_query', '')}",
            f"Query type: {evidence_result.get('query_type', scenario.get('query_type', ''))}",
            "",
            "RQ1 selected evidence summary:",
            json.dumps(evidence_result, ensure_ascii=False, indent=2),
        ]
    )


def build_rq1_evidence_summary(
    scenario: dict[str, Any],
    dashboard_data: DashboardData,
) -> dict[str, Any]:
    """Run the RQ1 synthesiser when the scenario page is supported."""

    page = str(scenario.get("page", "")).strip()
    query = str(scenario.get("student_query", ""))
    query_type = str(scenario.get("query_type_override") or classify_query(query))
    effective_page = page
    overview_target = ""
    if page == "Overview":
        overview_target = infer_specific_page_from_overview_query(query)
        if overview_target:
            effective_page = overview_target

    if page not in SUPPORTED_RQ1_PAGES:
        return {
            "available": False,
            "primary_page": page,
            "query": query,
            "query_type": query_type,
            "selected_sources": [],
            "selected_evidence": {},
            "interpretation": "",
            "uncertainty": "",
            "reason": (
                "Structured evidence is currently available for Resources, Lecture, "
                "Debate, and Reflection pages. Use one of those pages for a "
                "data-specific replay answer."
            ),
        }

    try:
        result = synthesise_evidence(
            query=str(scenario.get("student_query", "")),
            primary_page=effective_page,
            student_id=scenario.get("student_id"),
            data=dashboard_data,
            target_domain=str(scenario.get("resolved_target_domain", "")),
            query_type_override=str(scenario.get("query_type_override") or ""),
        )
        if overview_target:
            result["overview_route"] = {
                "from_page": "Overview",
                "routed_to_page": overview_target,
                "reason": "The overview query mentions a specific dashboard page or metric.",
            }
        return result
    except Exception as exc:
        return {
            "available": False,
            "primary_page": effective_page,
            "query": query,
            "query_type": query_type,
            "selected_sources": [],
            "selected_evidence": {},
            "interpretation": "",
            "uncertainty": "",
            "reason": f"Structured evidence could not be prepared for this scenario: {exc}",
        }


def route_for_mode_c(query_type: str, evidence_result: dict[str, Any]) -> str:
    """Choose the Mode C response route from query type and evidence status."""

    if evidence_result.get("available") is False:
        return "overview_fallback"
    if _is_follow_up_without_context(str(evidence_result.get("query", ""))):
        return "follow_up_without_context"
    if evidence_result.get("overview_route"):
        return "overview_metric_specific"
    if _page_key(evidence_result) == "overview":
        if query_type == "planning_or_strategy":
            return "overview_planning"
        if query_type == "improvement_recommendation":
            return "overview_recommendation"
        return "overview_summary"
    if query_type == "reflection_structure_question":
        return "reflection_structure"
    if query_type in {"improvement_recommendation", "planning_or_strategy"}:
        return "rq2_recommendation"
    if query_type == "metric_clarification":
        return "metric_definition"
    if query_type == "technical_data_question":
        return "technical_data"
    if query_type == "course_content_question":
        return "course_content"
    if query_type == "access_or_capability_question":
        return "access_or_capability"
    if query_type == "discrepancy_or_correction":
        return "discrepancy_or_correction"
    if query_type == "cross_page_relationship":
        return "cross_page_relationship"
    if query_type == "emotional_or_justification":
        return "emotional_or_justification"
    return "dashboard_interpretation"


def render_direct_mode_c_response(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
    dashboard_data: DashboardData,
    selected_route: str,
) -> str:
    """Render direct non-RQ2 routes for Mode C."""

    if selected_route == "overview_summary":
        return render_overview_summary(evidence_result)
    if selected_route == "overview_planning":
        return render_overview_planning(evidence_result)
    if selected_route == "overview_recommendation":
        return render_overview_recommendation(evidence_result)
    if selected_route == "overview_metric_specific":
        return render_overview_metric_specific(scenario, evidence_result, dashboard_data)
    if selected_route == "follow_up_without_context":
        return render_follow_up_without_context(evidence_result)
    if selected_route == "memory_resolved_follow_up":
        resolution_data = evidence_result.get("memory_resolution") or {}
        resolution = MemoryResolution(
            is_follow_up=bool(resolution_data.get("is_follow_up")),
            resolved=bool(resolution_data.get("resolved")),
            original_query=str(resolution_data.get("original_query", "")),
            resolved_query=str(resolution_data.get("resolved_query", "")),
            referenced_items=list(resolution_data.get("referenced_items", [])),
            memory_context=dict(resolution_data.get("memory_context", {})),
            structured_state=dict(resolution_data.get("structured_state", {})),
            resolution_type=str(resolution_data.get("resolution_type", "")),
            reason=str(resolution_data.get("reason", "")),
        )
        return render_memory_resolved_follow_up(scenario, evidence_result, resolution)
    if selected_route == "reflection_structure":
        return render_reflection_structure(evidence_result)
    if selected_route == "metric_definition":
        return render_metric_definition(evidence_result)
    if selected_route == "technical_data":
        return render_technical_data(scenario, evidence_result)
    if selected_route == "course_content":
        return render_course_content(scenario, evidence_result, dashboard_data)
    if selected_route == "access_or_capability":
        return render_access_or_capability(scenario, evidence_result)
    if selected_route == "discrepancy_or_correction":
        return render_discrepancy_or_correction(scenario, evidence_result)
    if selected_route == "cross_page_relationship":
        return render_cross_page_relationship(evidence_result)
    if selected_route == "emotional_or_justification":
        return render_emotional_or_justification(evidence_result)
    return render_dashboard_interpretation(evidence_result)


def render_memory_resolved_follow_up(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
    memory_resolution: MemoryResolution,
) -> str:
    """Render a student-facing answer for a resolved short-term follow-up."""

    if not memory_resolution.referenced_items:
        return _render_structured_memory_follow_up(evidence_result, memory_resolution)

    item_numbers = ", ".join(item["number"] for item in memory_resolution.referenced_items)
    lines = [
        f"I’m reading your question as a follow-up about previous item(s) {item_numbers}.",
        "Here is how to do them concretely:",
    ]
    for item in memory_resolution.referenced_items:
        lines.append(
            f"{item['number']}. {item['text']}: {_memory_item_guidance(item['text'], evidence_result)}"
        )

    evidence_text = _memory_evidence_context(evidence_result)
    if evidence_text:
        lines.extend(["", f"Dashboard context I used cautiously: {evidence_text}"])

    uncertainty = str(evidence_result.get("uncertainty", "")).strip()
    limitation = (
        uncertainty
        or "Dashboard logs can show activity patterns, but they cannot prove understanding, motivation, or learning quality."
    )
    lines.extend(
        [
            "",
            "Limitations: I used only the recent conversation items supplied in this scenario and the selected dashboard evidence. "
            + limitation,
        ]
    )
    return "\n".join(lines)


def _structured_memory_acknowledgement(memory_resolution: MemoryResolution) -> str:
    state = memory_resolution.structured_state or {}
    parts = ["I’m continuing from the learning plan in this recent conversation."]
    if state.get("active_goal"):
        parts.append(f"I kept your stated goal in view: {state['active_goal']}")
    if state.get("constraints"):
        parts.append(f"I also kept your latest constraint in view: {state['constraints'][-1]}")
    if state.get("completed_actions"):
        parts.append(f"I treated this as reported progress: {state['completed_actions'][-1]}")
    if state.get("corrections"):
        parts.append(f"I used your newest correction: {state['corrections'][-1]}")
    return " ".join(parts)


def _render_structured_memory_follow_up(
    evidence_result: dict[str, Any],
    memory_resolution: MemoryResolution,
) -> str:
    """Render a transparent deterministic response for plan-state continuity."""

    state = memory_resolution.structured_state or {}
    lines = [_structured_memory_acknowledgement(memory_resolution)]
    pending = [
        action for action in state.get("selected_actions", [])
        if isinstance(action, dict) and action.get("status") != "completed"
    ]
    if pending:
        lines.extend(["", f"The next unfinished action from that plan is: {pending[0].get('text', '')}"])
    else:
        lines.extend(
            [
                "",
                "You have not left an unfinished action in the remembered plan, so the next step should be a new small action grounded in the current dashboard evidence.",
            ]
        )

    evidence_text = _memory_evidence_context(evidence_result)
    if evidence_text:
        lines.extend(["", f"Dashboard context I used cautiously: {evidence_text}"])
    lines.extend(
        [
            "",
            "Memory boundary: I used only explicit statements from the recent session. I did not infer ability, motivation, comprehension, or a lasting personal profile.",
        ]
    )
    return "\n".join(lines)


def _memory_item_guidance(item_text: str, evidence_result: dict[str, Any]) -> str:
    """Create concise guidance for one referenced previous item."""

    text = str(item_text or "").lower()
    if re.search(r"\b(debate|post|reply|peer)\b", text):
        debate = _page_evidence(evidence_result, "debate")
        pattern = _activity_pattern_text("debate", debate) if debate else ""
        suffix = f" This fits the selected debate pattern: {pattern}" if pattern else ""
        return (
            "choose one post you have already viewed, write a short reply that first summarises the peer’s point, "
            "then add your own view, and end with one follow-up question."
            + suffix
        )
    if re.search(r"\b(reflect|reflection|paragraph|writing|essay)\b", text):
        reflection = _page_evidence(evidence_result, "reflection")
        pattern = _activity_pattern_text("reflection", reflection) if reflection else ""
        suffix = f" Use your reflection activity only as context: {pattern}" if pattern else ""
        return (
            "write one paragraph using this structure: what happened, what idea it connects to, what changed in your understanding, "
            "and what you will do next. Do not treat character count as reflection quality."
            + suffix
        )
    if re.search(r"\b(lecture|video|w\d+|week|recording)\b", text):
        lecture = _page_evidence(evidence_result, "lecture")
        pattern = _activity_pattern_text("lecture", lecture) if lecture else ""
        suffix = f" The selected lecture evidence says: {pattern}" if pattern else ""
        return (
            "pick one lecture or video segment, write two short notes, then turn one note into a question or example you can reuse."
            + suffix
        )
    if re.search(r"\b(resource|reading|moodle|material)\b", text):
        resources = _page_evidence(evidence_result, "resources")
        pattern = _activity_pattern_text("resources", resources) if resources else ""
        suffix = f" The selected resource evidence says: {pattern}" if pattern else ""
        return (
            "choose one resource item, skim it once for the main idea, then write one sentence connecting it to a lecture, debate, or reflection task."
            + suffix
        )
    return (
        "turn this into one small action you can complete in 15-20 minutes, then record one sentence about what you learned or what to do next."
    )


def _memory_evidence_context(evidence_result: dict[str, Any]) -> str:
    selected = evidence_result.get("selected_evidence", {})
    if not isinstance(selected, dict):
        return ""
    patterns: list[str] = []
    for page in ("resources", "lecture", "debate", "reflection", "overview"):
        page_evidence = selected.get(page)
        if isinstance(page_evidence, dict) and page_evidence:
            patterns.append(f"{page.title()}: {_activity_pattern_text(page, page_evidence)}")
    return " ".join(patterns)


def render_overview_fallback(scenario: dict[str, Any], query_type: str) -> str:
    """Graceful student-facing fallback for unsupported Overview scenarios."""

    query = str(scenario.get("student_query", ""))
    if query_type in {"improvement_recommendation", "planning_or_strategy"}:
        general = (
            "A useful next step is to choose one specific feedback page first, then turn one visible pattern into a small action."
        )
    elif query_type == "metric_clarification":
        general = "I can explain a metric most accurately when you open the page where that metric appears."
    else:
        general = "I can give a cautious general answer, but I need a specific feedback page for precise evidence."

    return (
        "This prototype has structured dashboard evidence for Resources, Lecture, Debate, and Reflection. "
        "The Overview page combines signals, so I should not pretend to have a precise selected evidence set for it.\n\n"
        f"For your question, \"{query}\", {general} "
        "Please select Resources, Lecture, Debate, or Reflection if you want a data-specific answer."
    )


def render_overview_summary(evidence_result: dict[str, Any]) -> str:
    summary = _overview_activity(evidence_result)
    if not summary:
        return (
            "The selected overview evidence is too sparse to identify a reliable activity pattern. "
            "Please open Resources, Lecture, Debate, or Reflection for a more specific answer."
        )

    resources = summary.get("resource_activity_summary", {})
    lecture = summary.get("lecture_video_activity_summary", {})
    debate = summary.get("debate_activity_summary", {})
    reflection = summary.get("reflection_activity_summary", {})
    query = str(evidence_result.get("query", "")).lower()
    query_type = str(evidence_result.get("query_type", ""))

    if query_type == "metric_clarification" and "assessment" in query:
        lines = [
            "Assessment views are not available as a separately verified evidence source in this offline prototype.",
            (
                "If the dashboard label refers to Assessment_views, treat it cautiously as assessment-related "
                "page or item access frequency, not as assessment performance or understanding."
            ),
            "The selected Overview evidence I can use here covers Resources, Lecture, Debate, and Reflection activity only.",
            f"Limitations: {summary.get('uncertainty')}",
        ]
        return "\n".join(lines)

    lines = [
        f"One cautious major observation is: {summary.get('major_observation')}",
        "Selected overview evidence:",
        f"- Resources: {_overview_resource_text(resources)}",
        f"- Lecture: {_overview_lecture_text(lecture)}",
        f"- Debate: {_overview_debate_text(debate)}",
        f"- Reflection: {_overview_reflection_text(reflection)}",
        f"Possible focus area: {summary.get('possible_focus_area')}",
        f"Limitations: {summary.get('uncertainty')}",
    ]
    return "\n".join(line for line in lines if line.strip())


def render_overview_planning(evidence_result: dict[str, Any]) -> str:
    summary = _overview_activity(evidence_result)
    if not summary:
        return render_overview_summary(evidence_result)

    query = str(evidence_result.get("query", ""))
    days = 10 if re.search(r"\b10\b|ten", query, flags=re.IGNORECASE) else 7
    lecture = summary.get("lecture_video_activity_summary", {})
    resources = summary.get("resource_activity_summary", {})
    debate = summary.get("debate_activity_summary", {})
    reflection = summary.get("reflection_activity_summary", {})
    low_resource = _low_week_from_extremes(resources.get("weekly_extremes"))
    high_resource = _high_week_from_extremes(resources.get("weekly_extremes"))
    missed = _as_list(lecture.get("missed_content_weeks"))

    priority = (
        "The main evidence-based priority is to close one preparation gap, then use it in a visible debate or reflection action."
    )
    plan = _overview_plan_steps(days=days, low_resource=low_resource, missed_weeks=missed)
    why = (
        f"This fits your data because Resources show {resources.get('views')} views across "
        f"{resources.get('active_weeks')} active weeks"
    )
    if low_resource or high_resource:
        why += f", with {low_resource or 'one lower week'} lower than {high_resource or 'one higher week'}"
    why += (
        f"; Lecture shows {lecture.get('viewed_videos')} viewed videos and missed weeks {_join(missed)}; "
        f"Debate shows {debate.get('views')} views, {debate.get('posts')} posts, and {debate.get('replies')} replies; "
        f"Reflection shows {reflection.get('total_chars')} edited characters across {reflection.get('active_weeks')} active weeks."
    )

    return (
        f"{priority}\n\n"
        f"{days}-day plan:\n"
        + "\n".join(f"{idx}. {step}" for idx, step in enumerate(plan, start=1))
        + f"\n\nWhy this plan fits: {why}\n\n"
        f"Limitations: {summary.get('uncertainty')}"
    )


def render_overview_recommendation(evidence_result: dict[str, Any]) -> str:
    summary = _overview_activity(evidence_result)
    if not summary:
        return render_overview_summary(evidence_result)

    resources = summary.get("resource_activity_summary", {})
    lecture = summary.get("lecture_video_activity_summary", {})
    debate = summary.get("debate_activity_summary", {})
    reflection = summary.get("reflection_activity_summary", {})
    low_resource = _low_week_from_extremes(resources.get("weekly_extremes"))
    missed = _as_list(lecture.get("missed_content_weeks"))

    first_step = (
        f"Start with one lecture gap, such as {_join(missed[:1])}, and write two notes you can reuse."
        if missed
        else "Start by choosing one lecture or resource item from this week and write two reusable notes."
    )
    second_step = (
        f"Use one of those notes in debate: your record shows {debate.get('views')} views, "
        f"{debate.get('posts')} posts, and {debate.get('replies')} replies, so a useful next action is one structured reply."
    )
    third_step = (
        f"Use reflection to consolidate the action: your reflection log shows {reflection.get('total_chars')} edited characters "
        f"across {reflection.get('active_weeks')} active weeks, but that is writing activity, not a quality score."
    )
    if low_resource:
        first_step = f"Revisit a low resource week first, especially {low_resource}, and write two notes you can reuse."

    return (
        f"Your data suggests broad resource activity, some missed or lower lecture/video engagement, and debate activity that can be made more deliberate.\n\n"
        f"A useful first step is: {first_step}\n\n"
        f"A second step is: {second_step}\n\n"
        f"A third step is: {third_step}\n\n"
        f"This fits your situation because Resources show {resources.get('views')} views across {resources.get('active_weeks')} active weeks, "
        f"Lecture shows missed weeks {_join(missed)}, and Debate shows visible viewing plus posting/replying activity.\n\n"
        f"The dashboard cannot prove learning quality, motivation, or comprehension, so treat this as a starting point. {summary.get('uncertainty')}"
    )


def render_overview_metric_specific(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
    dashboard_data: DashboardData,
) -> str:
    query_type = str(evidence_result.get("query_type", ""))
    if query_type in {"improvement_recommendation", "planning_or_strategy"}:
        recommendation_plan = build_recommendation_plan(
            student_query=str(scenario.get("student_query", "")),
            current_page=str(evidence_result.get("primary_page", scenario.get("page", ""))),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=None,
        )
        return render_student_response(recommendation_plan)
    if query_type == "metric_clarification":
        return render_metric_definition(evidence_result)
    if query_type == "technical_data_question":
        return render_technical_data(scenario, evidence_result)
    if query_type == "course_content_question":
        return render_course_content(scenario, evidence_result, dashboard_data)
    if query_type == "access_or_capability_question":
        return render_access_or_capability(scenario, evidence_result)
    if query_type == "discrepancy_or_correction":
        return render_discrepancy_or_correction(scenario, evidence_result)
    if query_type == "reflection_structure_question":
        return render_reflection_structure(evidence_result)
    if query_type == "cross_page_relationship":
        return render_cross_page_relationship(evidence_result)
    if query_type == "emotional_or_justification":
        return render_emotional_or_justification(evidence_result)
    return render_dashboard_interpretation(evidence_result)


def render_follow_up_without_context(evidence_result: dict[str, Any]) -> str:
    if _page_key(evidence_result) == "overview":
        summary = _overview_activity(evidence_result)
        if not summary:
            return (
                "I do not have the previous numbered list in this offline scenario, and the selected evidence is too sparse to infer the intended follow-up."
            )
        lecture = summary.get("lecture_video_activity_summary", {})
        resources = summary.get("resource_activity_summary", {})
        debate = summary.get("debate_activity_summary", {})
        missed = _as_list(lecture.get("missed_content_weeks"))
        low_resource = _low_week_from_extremes(resources.get("weekly_extremes"))
        step_one = (
            f"revisit {_join(missed[:1])} in the lecture/video evidence and write two notes"
            if missed
            else "choose one lecture or resource item and write two notes"
        )
        step_two = (
            f"use one note in a short debate reply; your debate record shows {debate.get('views')} views, "
            f"{debate.get('posts')} posts, and {debate.get('replies')} replies"
        )
        if low_resource:
            step_one = f"revisit the lower resource week {low_resource} and write two notes"
        return (
            "I do not have the previous numbered list in this offline scenario, but based on your dashboard evidence, "
            f"the two most useful next steps are: 1. {step_one}; 2. {step_two}.\n\n"
            f"Limitations: {summary.get('uncertainty')}"
        )

    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    return (
        "I do not have the previous numbered list in this offline scenario, but based on the selected dashboard evidence, "
        f"the most useful next step is to {_short_next_step(page, page_evidence)}\n\n"
        f"Selected evidence: {_activity_pattern_text(page, page_evidence)}"
    )


def render_reflection_structure(evidence_result: dict[str, Any]) -> str:
    reflection = _page_evidence(evidence_result, "reflection")
    context = _activity_pattern_text("reflection", reflection)
    return (
        "A useful reflection structure is: what happened, what you learned, what evidence connects to it, and what you will do next.\n\n"
        "1. What happened? Name one learning activity, such as a lecture point, resource, debate exchange, or task.\n"
        "2. What did I learn? Explain the concept or idea in your own words.\n"
        "3. What evidence connects to this? Link one lecture/resource/debate detail to your reflection.\n"
        "4. What will I do next? Write one specific next-step plan.\n\n"
        f"Dashboard context, used cautiously: {context}\n\n"
        "Limitations: character counts and activity logs can show writing activity and timing, but they do not judge reflection quality."
    )


def render_metric_definition(evidence_result: dict[str, Any]) -> str:
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    definitions = page_evidence.get("metric_definitions", {})
    if not definitions:
        return (
            "I do not have a clear metric definition selected for this question. "
            "Please ask about the specific metric name shown on the dashboard."
        )
    lines = [f"{metric}: {definition}" for metric, definition in definitions.items()]
    return "\n".join(lines) + "\n\nThese metrics describe activity traces, not learning quality or understanding."


def render_technical_data(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    query = str(scenario.get("student_query", "")).lower()
    parts = [_technical_first_sentence(page, query)]
    if page_evidence.get("data_provenance"):
        parts.append(f"Data source: {page_evidence['data_provenance']}")
    availability = page_evidence.get("data_availability")
    if isinstance(availability, dict):
        if availability.get("available"):
            parts.append(f"For this student/page, the selected data contains {availability.get('row_count')} relevant rows.")
        else:
            parts.append("For this student/page, the selected data appears to be unavailable or empty.")
    limitations = page_evidence.get("data_limitations") or []
    if limitations:
        parts.append("Limitations: " + " ".join(map(str, limitations)))
    return "\n\n".join(parts) if parts else "I do not have enough provenance information to answer this data question precisely."


def render_course_content(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
    dashboard_data: DashboardData,
) -> str:
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    metadata = page_evidence.get("course_metadata", {})
    query = str(scenario.get("student_query", ""))
    week = _extract_week(query)

    if isinstance(metadata, dict) and metadata.get("available"):
        verified = metadata.get("verified_week_metadata", {})
        if week and isinstance(verified, dict) and week in verified:
            record = verified[week]
            title = record.get("title", "")
            recorded_title = record.get("recorded_lecture_title", title)
            confidence = record.get("confidence", "unknown")
            summary = record.get("content_summary", "")
            disambiguation = record.get("disambiguation_note", "")
            source_notes = record.get("source_notes", [])
            source_files = record.get("source_files") or []
            source_text = " ".join(map(str, source_notes[:3]))
            if confidence == "high":
                first = f"{week}'s pre-recorded lecture is best supported as \"{recorded_title}\" on {title}."
            else:
                first = (
                    f"The available metadata for {week}'s pre-recorded lecture is limited; "
                    f"the best available title is \"{recorded_title}\"."
                )
            parts = [first]
            if summary:
                parts.append(f"Available course metadata says it is about: {summary}")
            if disambiguation:
                parts.append(disambiguation)
            if source_files:
                parts.append(f"Verified metadata confidence: {confidence}. Source files: {', '.join(map(str, source_files))}.")
            elif source_text:
                parts.append(f"Verified metadata confidence: {confidence}. Source notes: {source_text}")
            parts.append(
                "I cannot access or summarise the full recording/transcript unless that content is provided in the course materials."
            )
            return "\n\n".join(parts)

        titles = metadata.get("lecture_titles_by_week", {})
        if week and week in titles:
            return (
                f"{week}'s recorded lecture is labelled as: {titles[week]}.\n\n"
                "I do not have enough verified course metadata to summarise the full lecture beyond that title."
            )
        if titles:
            title_list = "; ".join(f"{w}: {title}" for w, title in sorted(titles.items())[:10])
            return (
                "The available metadata includes lecture titles, not full lecture recordings or transcripts. "
                f"Available titles include: {title_list}."
            )

    return (
        "The current dashboard evidence does not include the full lecture content or transcript. "
        "It may include activity logs or titles, but not enough to answer what the lecture covered in detail."
    )


def render_access_or_capability(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    query = str(scenario.get("student_query", "")).lower()
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    provenance = page_evidence.get("data_provenance", "The dashboard uses tracked platform activity.")
    limitations = " ".join(map(str, page_evidence.get("data_limitations") or []))

    if "email" in query:
        return (
            "The dashboard does not appear to capture whether you read debate posts through email subscription. "
            f"{provenance} If a debate post was read outside Moodle, it may not appear as a Moodle debate view.\n\n"
            f"Limitations: {limitations}"
        )
    if "full" in query or "access" in query or "lecture" in query:
        return (
            "I cannot access the full pre-recorded lecture content unless it is included in the provided course materials. "
            f"{provenance} The available evidence can support activity/log questions, not full content access.\n\n"
            f"Limitations: {limitations}"
        )
    return (
        f"{provenance} I can only answer from the evidence available in the dashboard export, not from external tools or private activity."
    )


def render_discrepancy_or_correction(
    scenario: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    page = _page_key(evidence_result)
    pattern = _activity_pattern_text(page, _page_evidence(evidence_result, page))
    return (
        "If you completed the essay but it is not shown here, the dashboard log may not include the official submission record. "
        "The dashboard is based on activity logs, so it may not capture every submission, essay completion, external activity, or timing detail.\n\n"
        f"What the selected dashboard evidence shows: {pattern}\n\n"
        "For confirmation of an essay submission or deadline status, please check the official submission platform or ask the instructor/module team. "
        "I should not treat the dashboard log as the final record of whether you completed the essay."
    )


def render_dashboard_interpretation(evidence_result: dict[str, Any]) -> str:
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    pattern = _activity_pattern_text(page, page_evidence)
    next_step = _short_next_step(page, page_evidence)
    uncertainty = evidence_result.get("uncertainty", "")
    response = f"The selected dashboard evidence shows: {pattern}"
    if next_step:
        response += f"\n\nA small next step could be: {next_step}"
    if uncertainty:
        response += f"\n\nLimitations: {uncertainty}"
    return response


def render_cross_page_relationship(evidence_result: dict[str, Any]) -> str:
    selected = evidence_result.get("selected_evidence", {})
    patterns = []
    for page in ("resources", "lecture", "debate", "reflection"):
        if page in selected:
            patterns.append(f"{page.title()}: {_activity_pattern_text(page, selected[page])}")
    uncertainty = evidence_result.get("uncertainty", "")
    return (
        "The selected evidence supports a cautious comparison:\n"
        + "\n".join(f"- {pattern}" for pattern in patterns)
        + "\n\nThese patterns can suggest relationships between activities, but they do not prove causality."
        + (f"\n\nLimitations: {uncertainty}" if uncertainty else "")
    )


def render_emotional_or_justification(evidence_result: dict[str, Any]) -> str:
    page = _page_key(evidence_result)
    page_evidence = _page_evidence(evidence_result, page)
    purpose = page_evidence.get("learning_purpose", "This feedback is intended to help you reflect on learning activity patterns.")
    pattern = _activity_pattern_text(page, page_evidence)
    return (
        f"{purpose}\n\n"
        f"The dashboard pattern selected for your question is: {pattern}\n\n"
        "This should not be read as a judgement of whether you are a good or bad student. "
        "Activity traces are useful for reflection, but they do not directly measure understanding or effort."
    )


def infer_specific_page_from_overview_query(query: str) -> str:
    """Return a specific page when an Overview query clearly names one."""

    q = str(query or "").strip().lower()
    if re.search(r"\b(resources?_views|resource|resources|reading|readings|moodle resource)\b", q):
        return "Resources"
    if re.search(r"\b(video_views|video_clicks|video|videos|lecture|lectures|pre-recorded|recorded|panopto|echo360)\b", q):
        return "Lecture"
    if re.search(r"\b(debate_views|debate_posts|debate_replies|debate|debates|post|posts|reply|replies|email subscription)\b", q):
        return "Debate"
    if re.search(r"\b(total_chars|absstrcount|reflection|reflective|essay|writing|strings|character|characters)\b", q):
        return "Reflection"
    return ""


def _is_follow_up_without_context(query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    return bool(
        re.search(r"\b(do|doing|suggest|explain|what about|how about|expand on).*\b\d+\s*(and|&)\s*\d+\b", q)
        or re.search(r"^\s*(do\s*)?\d+\s*(and|&)\s*\d+\s*$", q)
        or re.search(r"\b(the\s*)?(first|second|third|fourth|last)\s+one\b", q)
        or re.search(r"\b(point|number|item)\s*\d+\b", q)
    )


def _overview_activity(evidence_result: dict[str, Any]) -> dict[str, Any]:
    page_evidence = _page_evidence(evidence_result, "overview")
    summary = page_evidence.get("activity_summary", {})
    if isinstance(summary, dict) and summary.get("available"):
        return summary
    return {}


def _overview_plan_steps(days: int, low_resource: str, missed_weeks: list[str]) -> list[str]:
    first_missed = _join(missed_weeks[:1])
    second_missed = _join(missed_weeks[1:2])
    if days >= 10:
        return [
            f"Days 1-2: revisit one lecture/video gap, starting with {first_missed}, and write two reusable notes.",
            f"Day 3: check the lower resource week {low_resource or 'shown in the resource pattern'} and choose one material to revisit.",
            "Days 4-5: pick one debate post you already viewed, summarise the peer's point, add your own view, and ask one follow-up question.",
            f"Days 6-7: move to another lecture/video gap, such as {second_missed}, and connect one idea to a resource or debate point.",
            "Day 8: write one reflection paragraph using: what happened, what you learned, what evidence connects, and what you will do next.",
            "Day 9: check whether one low-activity area now has a concrete note, reply, or reflection entry.",
            "Day 10: choose the next single focus area for the following week instead of trying to fix every metric at once.",
        ]
    return [
        f"Day 1: revisit one lecture/video gap, starting with {first_missed}, and write two reusable notes.",
        f"Day 2: check the lower resource week {low_resource or 'shown in the resource pattern'} and choose one material to revisit.",
        "Days 3-4: write one short debate reply that summarises a peer's point, adds your own view, and asks one follow-up question.",
        "Day 5: use one lecture/resource/debate point in a structured reflection paragraph.",
        "Day 6: check whether the action created one concrete output: a note, reply, or reflection entry.",
        "Day 7: set one next-week focus from the remaining low or missed activity pattern.",
    ]


def _low_week_from_extremes(text: Any) -> str:
    match = re.search(r"lowest selected week is\s+([A-Za-z0-9]+)", str(text or ""))
    return match.group(1) if match else ""


def _high_week_from_extremes(text: Any) -> str:
    match = re.search(r"highest selected week is\s+([A-Za-z0-9]+)", str(text or ""))
    return match.group(1) if match else ""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _technical_first_sentence(page: str, query: str) -> str:
    if page == "lecture":
        if "live" in query or "pre-recorded" in query or "recorded" in query:
            return "This data is based on recorded lecture video activity, not live-session attendance."
        return "This lecture data comes from recorded lecture viewing and video access logs."
    if page == "resources":
        return "Resources_views are measured from Moodle resource or reading view events in the selected logs."
    if page == "debate":
        return "This debate data is collected from Moodle debate logs and the reply/view network tables."
    if page == "reflection":
        return "This reflection data is collected from Google Docs activity logs, not from judging the reflection content."
    return "This dashboard data is based on tracked platform activity logs, not direct evidence of learning quality."


def _overview_resource_text(value: Any) -> str:
    summary = value if isinstance(value, dict) else {}
    text = f"{summary.get('views')} views across {summary.get('active_weeks')} active weeks"
    if summary.get("most_active_day"):
        text += f"; most active day: {summary.get('most_active_day')}"
    if summary.get("weekly_extremes"):
        text += f"; {summary.get('weekly_extremes')}"
    return text + "."


def _overview_lecture_text(value: Any) -> str:
    summary = value if isinstance(value, dict) else {}
    return (
        f"{summary.get('viewed_videos')} viewed videos; average view percentage "
        f"{summary.get('average_video_view_percent')}; missed weeks: {_join(summary.get('missed_content_weeks'))}."
    )


def _overview_debate_text(value: Any) -> str:
    summary = value if isinstance(value, dict) else {}
    return (
        f"{summary.get('views')} views, {summary.get('posts')} posts, and "
        f"{summary.get('replies')} replies."
    )


def _overview_reflection_text(value: Any) -> str:
    summary = value if isinstance(value, dict) else {}
    text = f"{summary.get('total_chars')} edited characters across {summary.get('active_weeks')} active weeks"
    if summary.get("weekly_extremes"):
        text += f"; {summary.get('weekly_extremes')}"
    return text + "."


def _page_key(evidence_result: dict[str, Any]) -> str:
    page = str(evidence_result.get("primary_page", "")).strip().lower()
    if page == "overview":
        return "overview"
    if page == "resources":
        return "resources"
    if page == "lecture":
        return "lecture"
    if page == "debate":
        return "debate"
    if page == "reflection":
        return "reflection"
    selected = evidence_result.get("selected_evidence", {})
    if isinstance(selected, dict) and selected:
        return next(iter(selected.keys()))
    return page


def _page_evidence(evidence_result: dict[str, Any], page: str) -> dict[str, Any]:
    selected = evidence_result.get("selected_evidence", {})
    if isinstance(selected, dict):
        value = selected.get(page, {})
        return value if isinstance(value, dict) else {}
    return {}


def _activity_pattern_text(page: str, page_evidence: dict[str, Any]) -> str:
    activity = page_evidence.get("activity_summary", {})
    if not isinstance(activity, dict):
        return "there is not enough selected activity evidence to describe a detailed pattern."
    if page == "resources":
        weekly = activity.get("weekly_counts", {})
        extremes = _weekly_extremes(weekly)
        detail = f"{activity.get('views')} resource views across {activity.get('active_weeks')} active weeks"
        if activity.get("most_active_day"):
            detail += f", with {activity.get('most_active_day')} as the most active day"
        if extremes:
            detail += f"; {extremes}"
        return detail + "."
    if page == "debate":
        network = page_evidence.get("network_summary", {})
        detail = (
            f"{activity.get('views')} debate views, {activity.get('posts')} posts, and {activity.get('replies')} replies"
        )
        if activity.get("active_post_weeks") or activity.get("active_reply_weeks"):
            detail += (
                f"; post weeks: {_join(activity.get('active_post_weeks'))}; "
                f"reply weeks: {_join(activity.get('active_reply_weeks'))}"
            )
        if isinstance(network, dict) and network.get("available"):
            reply = network.get("reply_network", {})
            view = network.get("view_network", {})
            detail += (
                f"; reply network unique people: {reply.get('unique_people')}; "
                f"view network unique people: {view.get('unique_people')}"
            )
        return detail + "."
    if page == "reflection":
        weekly = activity.get("weekly_character_counts", {})
        extremes = _weekly_extremes(weekly)
        detail = (
            f"{activity.get('total_chars')} edited characters across {activity.get('active_weeks')} active weeks"
        )
        if activity.get("active_week_list"):
            detail += f"; active weeks: {_join(activity.get('active_week_list'))}"
        if extremes:
            detail += f"; {extremes}"
        return detail + ". Character counts show writing activity, not reflection quality."
    if page == "lecture":
        detail = (
            f"{activity.get('viewed_videos')} viewed videos, average view percentage "
            f"{activity.get('average_video_view_percent')}, and missed content weeks: {_join(activity.get('missed_content_weeks'))}"
        )
        return detail + ". Viewing logs do not prove attention or comprehension."
    return "there is selected evidence, but no page-specific summary formatter for it."


def _short_next_step(page: str, page_evidence: dict[str, Any]) -> str:
    if page == "resources":
        return "choose one low-activity or important week and check whether any resource from that week needs attention."
    if page == "debate":
        return "choose one viewed debate post and decide whether it needs a short reply."
    if page == "reflection":
        activity = page_evidence.get("activity_summary", {})
        if not isinstance(activity, dict) or not activity.get("active_weeks"):
            return "create a first baseline reflection entry, then choose a realistic day for the next entry."
        return "use one active week as a model and write one focused reflection note for a less active week."
    if page == "lecture":
        return "check one missed or low-view lecture week before drawing conclusions from the chart."
    return ""


def _weekly_extremes(weekly: Any) -> str:
    if not isinstance(weekly, dict) or not weekly:
        return ""
    numeric = []
    for week, value in weekly.items():
        try:
            numeric.append((str(week), float(value)))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return ""
    low_week, low_val = min(numeric, key=lambda item: item[1])
    high_week, high_val = max(numeric, key=lambda item: item[1])
    if low_week == high_week:
        return f"{high_week} is the only selected week with {int(high_val) if high_val.is_integer() else high_val} events"
    low_text = int(low_val) if low_val.is_integer() else low_val
    high_text = int(high_val) if high_val.is_integer() else high_val
    return f"lowest selected week is {low_week} ({low_text}); highest selected week is {high_week} ({high_text})"


def _join(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        return ", ".join(map(str, value))
    return "none selected"


def _extract_week(query: str) -> str:
    match = re.search(r"\bW\s*([0-9]+)\b", query, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\bweek\s*([0-9]+)\b", query, flags=re.IGNORECASE)
    return f"W{int(match.group(1))}" if match else ""


def baseline_context_placeholder(page: str) -> str:
    """Describe the baseline page-specific context shape."""

    if page == "Resources":
        return "Resources visual description, written feedback, Moodle resource log summary, and resources few-shot examples."
    if page == "Lecture":
        return "Lecture visual description, written feedback, Panopto/Echo360 log summary, and lecture few-shot examples."
    if page == "Debate":
        return "Debate network visual description, written feedback, debate metric summary, and debate few-shot examples."
    if page == "Reflection":
        return "Reflection visual description, written feedback, GDocs activity summary, and reflection few-shot examples."
    if page == "Overview":
        return "Historical overview context from the original example conversation data."
    return "Page-specific visual description, written feedback, few-shot examples, and current page data."
