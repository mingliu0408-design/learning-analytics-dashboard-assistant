"""Generate offline LLM responses for evaluation scenarios.

This script keeps the existing deterministic replay benchmark unchanged. It
creates a second set of response files where OpenAI generates the final
student-facing answer, while each mode receives different context:

    python evaluation/run_llm_generation.py --mode A --model gpt-4o-mini
    python evaluation/run_llm_generation.py --mode B --model gpt-4o-mini
    python evaluation/run_llm_generation.py --mode C --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.assistant_modes import (  # noqa: E402
    build_baseline_prompt,
    build_rq1_evidence_summary,
    build_rq1_prompt,
    load_dashboard_data,
    render_course_retrieval_direct_response,
    render_course_retrieval_fallback,
    render_direct_mode_c_response,
    render_memory_resolved_follow_up,
    route_for_mode_c,
)
from evaluation.automatic_metrics import compute_automatic_metrics  # noqa: E402
from utils.course_material_retriever import (  # noqa: E402
    RetrievalResult,
    chunks_to_dicts,
    format_retrieved_chunks_for_prompt,
    retrieve_course_chunks,
    retrieval_result_to_dict,
    should_use_course_retrieval,
)
from utils.course_metadata import get_lecture_metadata, lecture_titles_by_week  # noqa: E402
from utils.c_full_service import (  # noqa: E402
    build_c_full_context,
    generate_c_full_chat_turn,
)
from utils.conversation_memory import format_memory_context_for_prompt, prepare_mode_cm_context  # noqa: E402
from utils.evidence_synthesiser import classify_query  # noqa: E402
from utils.recommendation_planner import build_recommendation_plan  # noqa: E402


DEFAULT_SCENARIOS = PROJECT_ROOT / "evaluation" / "scenarios.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "outputs"
RECOMMENDATION_ROUTES = {
    "rq2_recommendation",
    "overview_planning",
    "overview_recommendation",
}
DIRECT_FIRST_SENTENCE_ROUTES = {
    "technical_data",
    "access_or_capability",
    "course_content",
    "discrepancy_or_correction",
}


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(description="Generate LLM-based offline responses.")
    parser.add_argument(
        "--mode",
        choices=[
            "A",
            "B",
            "C",
            "CM",
            "C_MEMORY",
            "CR",
            "C_RAG",
            "C_FULL",
            "C_FULL_KEYWORD",
            "C_FULL_SEMANTIC",
            "FULL",
            "CX",
            "a",
            "b",
            "c",
            "cm",
            "c_memory",
            "cr",
            "c_rag",
            "c_full",
            "c_full_keyword",
            "c_full_semantic",
            "full",
            "cx",
        ],
        required=True,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_GENERATION_MODEL", "gpt-4o-mini"),
        help="OpenAI model for response generation. Can also use OPENAI_GENERATION_MODEL.",
    )
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Optional number of scenarios to generate.")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON records."""

    if not path.exists():
        raise FileNotFoundError(f"Missing scenario file: {path}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} line {line_no}: {exc}") from exc
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """Write records as newline-delimited JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def output_path_for_mode(mode: str) -> Path:
    """Return the default LLM response output path for a mode."""

    return OUTPUT_DIR / f"responses_mode_{normalise_mode(mode).lower()}_llm.jsonl"


def normalise_mode(mode: str) -> str:
    """Normalise user-facing mode aliases."""

    mode = str(mode or "").upper().strip()
    if mode == "C_MEMORY":
        return "CM"
    if mode == "C_RAG":
        return "CR"
    if mode in {"FULL", "CX"}:
        return "C_FULL"
    return mode


def display_path(path: Path) -> str:
    """Return a readable path for command output."""

    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def initialise_openai_client() -> Any:
    """Create an OpenAI client or fail clearly without exposing secrets."""

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Set it locally before running LLM generation.")
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise SystemExit("The OpenAI Python package is not available in this environment.") from exc
    return OpenAI()


def generate_mode_response(
    mode: str,
    scenario: Mapping[str, Any],
    dashboard_data: Any,
    client: Any,
    model: str,
) -> dict[str, Any]:
    """Generate one LLM response record for a scenario and mode."""

    mode = normalise_mode(mode)
    if mode == "A":
        context = build_mode_a_context(scenario)
    elif mode == "B":
        context = build_mode_b_context(scenario, dashboard_data)
    elif mode == "C":
        context = build_mode_c_context(scenario, dashboard_data)
    elif mode == "CM":
        context = build_mode_cm_context(scenario, dashboard_data)
    elif mode == "CR":
        context = build_mode_cr_context(scenario, dashboard_data)
    elif mode in {"C_FULL", "C_FULL_KEYWORD", "C_FULL_SEMANTIC"}:
        intent_router_mode = {
            "C_FULL_KEYWORD": "keyword_baseline",
            "C_FULL_SEMANTIC": "semantic_enhanced",
        }.get(mode)
        return _generate_production_c_full_record(
            scenario,
            dashboard_data,
            client,
            model,
            benchmark_mode=mode,
            intent_router_mode=intent_router_mode,
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    messages = build_openai_messages(mode, context)
    generated_response = call_openai(client=client, model=model, messages=messages)

    evidence_summary = context.get("rq1_evidence_summary") or {}
    record = {
        "scenario_id": scenario.get("scenario_id", ""),
        "mode": mode,
        "generation_type": "openai_llm",
        "model": model,
        "student_id": scenario.get("student_id", ""),
        "page": scenario.get("page", ""),
        "student_query": scenario.get("student_query", ""),
        "original_student_query": context.get("original_student_query") or scenario.get("student_query", ""),
        "resolved_student_query": context.get("resolved_student_query", ""),
        "query_type": context.get("query_type") or scenario.get("query_type", ""),
        "original_query_type": scenario.get("query_type", ""),
        "selected_route": context.get("selected_route", ""),
        "generated_response": generated_response,
        "baseline_reference_response": scenario.get("baseline_reference_response", ""),
        "rq1_selected_sources": context.get("rq1_selected_sources", []),
        "evidence_sources": context.get("rq1_selected_sources", []),
        "rq1_evidence_summary": evidence_summary,
        "rq2_recommendation_plan": context.get("rq2_recommendation_plan", {}),
        "course_metadata": context.get("course_metadata", {}),
        "memory_resolution": context.get("memory_resolution", {}),
        "memory_triggered": bool((context.get("memory_resolution") or {}).get("is_follow_up")),
        "memory_used": bool((context.get("memory_resolution") or {}).get("resolved")),
        "memory_resolved": bool((context.get("memory_resolution") or {}).get("resolved")),
        "retrieval_result": context.get("retrieval_result", {}),
        "retrieval_used": bool((context.get("retrieval_result") or {}).get("retrieval_used")),
        "retrieved_context_chunks": context.get("retrieved_context_chunks", []),
        "retrieved_chunk_ids": [
            chunk.get("chunk_id", "") for chunk in context.get("retrieved_context_chunks", [])
        ],
        "retrieved_chunk_titles": [
            chunk.get("title", "") for chunk in context.get("retrieved_context_chunks", [])
        ],
        "required_capabilities": scenario.get("required_capabilities", []),
        "constructed_prompt": context.get("prompt", ""),
        "prompt": context.get("prompt", ""),
        "openai_messages": messages,
        "notes": context.get("notes", ""),
    }
    record["automatic_metrics"] = compute_automatic_metrics(
        generated_response=record["generated_response"],
        evidence_summary=evidence_summary,
        student_query=str(scenario.get("student_query", "")),
    )
    return record


def _generate_production_c_full_record(
    scenario: Mapping[str, Any],
    dashboard_data: Any,
    client: Any,
    model: str,
    *,
    benchmark_mode: str = "C_FULL",
    intent_router_mode: str | None = None,
) -> dict[str, Any]:
    """Generate formal C_FULL output through the exact production transaction."""

    history = scenario.get("conversation_history") or scenario.get("prior_turns") or []
    session_memory = scenario.get("session_memory") or scenario.get("c_full_memory") or {}
    outcome = generate_c_full_chat_turn(
        student_query=str(scenario.get("student_query", "")),
        student_id=str(scenario.get("student_id", "")),
        current_page=str(scenario.get("page", "")),
        conversation_history=history,
        existing_session_memory=session_memory,
        dashboard_data=dashboard_data,
        openai_client=client,
        model=model,
        intent_router_mode=intent_router_mode,
    )
    if not outcome.succeeded or outcome.runtime_result is None:
        raise RuntimeError(
            f"C_FULL generation transaction failed for scenario {scenario.get('scenario_id', '<unknown>')}"
        )
    runtime = outcome.runtime_result
    context = runtime.context
    evidence_summary = context.get("rq1_evidence_summary") or {}
    retrieval = context.get("retrieval_result") or {}
    record = {
        "scenario_id": scenario.get("scenario_id", ""),
        "mode": benchmark_mode,
        "generation_type": "openai_llm",
        "generation_succeeded": True,
        "model": model,
        "student_id": scenario.get("student_id", ""),
        "page": scenario.get("page", ""),
        "student_query": scenario.get("student_query", ""),
        "original_student_query": runtime.original_query,
        "resolved_student_query": runtime.resolved_query,
        "effective_query": runtime.effective_query,
        "query_type": runtime.query_type,
        "original_query_type": scenario.get("query_type", ""),
        "selected_route": runtime.selected_route,
        "generated_response": outcome.response,
        "response": outcome.response,
        "baseline_reference_response": scenario.get("baseline_reference_response", ""),
        "rq1_selected_sources": runtime.selected_evidence_sources,
        "evidence_sources": runtime.selected_evidence_sources,
        "rq1_evidence_summary": evidence_summary,
        "rq2_recommendation_plan": runtime.recommendation_plan,
        "course_metadata": context.get("course_metadata", {}),
        "memory_resolution": context.get("memory_resolution", {}),
        "memory_metadata": runtime.memory_metadata,
        "memory_triggered": bool(runtime.memory_metadata.get("memory_triggered")),
        "memory_used": bool(runtime.memory_metadata.get("memory_used")),
        "memory_resolved": bool(runtime.memory_metadata.get("memory_resolved")),
        "retrieval_result": retrieval,
        "retrieval_used": runtime.retrieval_used,
        "retrieved_context_chunks": context.get("retrieved_context_chunks", []),
        "retrieved_chunk_ids": list(retrieval.get("retrieved_chunk_ids") or []),
        "retrieved_chunk_titles": runtime.retrieved_chunk_titles,
        "required_capabilities": scenario.get("required_capabilities", []),
        "constructed_prompt": context.get("prompt", ""),
        "prompt": context.get("prompt", ""),
        "openai_messages": runtime.openai_messages,
        "pre_generation_structured_memory": context.get("pre_generation_structured_memory", {}),
        "post_commit_structured_memory": outcome.structured_memory,
        "post_commit_memory_metadata": context.get("post_commit_memory_metadata", {}),
        "memory_commit": context.get("memory_commit", {}),
        "intent_routing": context.get("intent_routing", {}),
        "notes": context.get("notes", ""),
    }
    record["automatic_metrics"] = compute_automatic_metrics(
        generated_response=outcome.response,
        evidence_summary=evidence_summary,
        student_query=str(scenario.get("student_query", "")),
    )
    return record


def build_mode_a_context(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """Build the baseline-style LLM context from page-specific scenario data."""

    baseline_prompt = build_baseline_prompt(dict(scenario))
    reference = str(scenario.get("baseline_reference_response") or "").strip()
    prompt_sections = [
        baseline_prompt,
        "",
        "Mode A generation task:",
        (
            "Generate a concise student-facing answer that simulates the original "
            "page-specific dashboard assistant. Use the current page context only. "
            "Do not introduce RQ1 cross-page evidence synthesis or RQ2 planning."
        ),
    ]
    if reference:
        prompt_sections.extend(
            [
                "",
                "Optional original/reference answer for orientation only:",
                reference,
                "",
                "Do not copy the reference answer directly. Write a fresh answer to the student's query.",
            ]
        )
    return {
        "query_type": scenario.get("query_type", ""),
        "selected_route": "baseline_page_specific",
        "rq1_selected_sources": [],
        "rq1_evidence_summary": {},
        "prompt": "\n".join(prompt_sections),
        "notes": "Mode A LLM receives baseline-style page-specific context only.",
    }


def build_mode_b_context(scenario: Mapping[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Build the RQ1 evidence-synthesis LLM context."""

    evidence_result = build_rq1_evidence_summary(dict(scenario), dashboard_data)
    query_type = str(evidence_result.get("query_type") or scenario.get("query_type", ""))
    prompt = "\n".join(
        [
            build_rq1_prompt(dict(scenario), evidence_result),
            "",
            "Mode B generation task:",
            (
                "Generate a student-facing answer grounded in the selected RQ1 evidence. "
                "Use only relevant selected evidence, explain uncertainty, and avoid "
                "unsupported claims about learning quality, motivation, or comprehension."
            ),
            "",
            "If the selected evidence is insufficient, say what is missing instead of guessing.",
        ]
    )
    return {
        "query_type": query_type,
        "selected_route": "rq1_evidence_response",
        "rq1_selected_sources": list(evidence_result.get("selected_sources", [])),
        "rq1_evidence_summary": evidence_result,
        "prompt": prompt,
        "notes": "Mode B LLM receives RQ1 selected evidence and uncertainty boundaries.",
    }


def build_mode_c_context(scenario: Mapping[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Build the RQ1 plus RQ2 routed LLM context."""

    evidence_result = build_rq1_evidence_summary(dict(scenario), dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(str(scenario.get("student_query", ""))))
    selected_route = route_for_mode_c(query_type, evidence_result)
    recommendation_plan: dict[str, Any] = {}
    direct_response_reference = ""
    course_metadata = course_metadata_for_scenario(scenario, evidence_result, selected_route)

    if selected_route == "rq2_recommendation":
        recommendation_plan = build_recommendation_plan(
            student_query=str(scenario.get("student_query", "")),
            current_page=str(evidence_result.get("primary_page") or scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=None,
        )
    elif selected_route in RECOMMENDATION_ROUTES:
        # Overview routes currently use the RQ1 overview evidence directly; the
        # LLM still receives route-specific instructions below.
        recommendation_plan = {}
    else:
        direct_response_reference = render_direct_mode_c_response(
            scenario=dict(scenario),
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=selected_route,
        )

    prompt = build_mode_c_prompt(
        scenario=scenario,
        evidence_result=evidence_result,
        query_type=query_type,
        selected_route=selected_route,
        recommendation_plan=recommendation_plan,
        direct_response_reference=direct_response_reference,
        course_metadata=course_metadata,
    )
    return {
        "query_type": query_type,
        "selected_route": selected_route,
        "rq1_selected_sources": list(evidence_result.get("selected_sources", [])),
        "rq1_evidence_summary": evidence_result,
        "rq2_recommendation_plan": recommendation_plan,
        "course_metadata": course_metadata,
        "prompt": prompt,
        "notes": "Mode C LLM receives the RQ1 evidence summary plus Mode C route information.",
    }


def build_mode_cr_context(scenario: Mapping[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Build Mode C with local course-material retrieval context."""

    evidence_result = build_rq1_evidence_summary(dict(scenario), dashboard_data)
    query = str(scenario.get("student_query", ""))
    query_type = str(evidence_result.get("query_type") or classify_query(query))
    selected_route = route_for_mode_c(query_type, evidence_result)
    retrieval_needed = should_use_course_retrieval(query, query_type)
    retrieval_result = (
        retrieve_course_chunks(query, query_type, top_k=4)
        if retrieval_needed
        else RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was not needed for this query.",
        )
    )
    retrieved_chunks = chunks_to_dicts(retrieval_result.chunks)
    recommendation_plan: dict[str, Any] = {}
    direct_response_reference = ""
    course_metadata = course_metadata_for_scenario(scenario, evidence_result, selected_route)

    if selected_route == "rq2_recommendation":
        recommendation_plan = build_recommendation_plan(
            student_query=query,
            current_page=str(evidence_result.get("primary_page") or scenario.get("page", "")),
            student_id=scenario.get("student_id", ""),
            evidence_summary=evidence_result,
            retrieved_context_chunks=retrieved_chunks if retrieval_result.retrieval_used else None,
        )
    elif evidence_result.get("available") is False:
        direct_response_reference = render_course_retrieval_fallback(dict(scenario), retrieval_result)
    else:
        direct_response_reference = render_course_retrieval_direct_response(
            scenario=dict(scenario),
            evidence_result=evidence_result,
            dashboard_data=dashboard_data,
            selected_route=selected_route,
            retrieval_result=retrieval_result,
        )

    prompt = build_mode_c_prompt(
        scenario=scenario,
        evidence_result=evidence_result,
        query_type=query_type,
        selected_route=selected_route,
        recommendation_plan=recommendation_plan,
        direct_response_reference=direct_response_reference,
        course_metadata=course_metadata,
    )
    prompt += "\n\nMode CR course-material retrieval status:\n"
    prompt += json.dumps(retrieval_result_to_dict(retrieval_result), ensure_ascii=False, indent=2)
    prompt += "\n\nRetrieved course-material chunks for prompt use:\n"
    prompt += format_retrieved_chunks_for_prompt(retrieval_result.chunks)
    prompt += "\n\nMode CR route guidance:\n"
    if retrieval_result.retrieval_used:
        prompt += (
            "Use the retrieved course-material context to supplement the dashboard evidence. "
            "Dashboard evidence should support claims about the student's behaviour. "
            "Course-material chunks should support claims about course tasks, weekly topics, readings, "
            "reflection prompts, debate guidance, Moodle links, or assessment guidance. "
            "Do not invent course requirements beyond the retrieved context."
        )
    elif retrieval_needed:
        prompt += (
            "Course-material retrieval was appropriate for this query, but no strong matching chunk was found. "
            "Say briefly that the available retrieved course context is insufficient and avoid guessing."
        )
    else:
        prompt += (
            "Course-material retrieval was not needed for this query. Behave like Mode C and do not add course-material claims."
        )

    return {
        "query_type": query_type,
        "selected_route": selected_route,
        "rq1_selected_sources": list(evidence_result.get("selected_sources", [])),
        "rq1_evidence_summary": evidence_result,
        "rq2_recommendation_plan": recommendation_plan,
        "course_metadata": course_metadata,
        "retrieval_result": retrieval_result_to_dict(retrieval_result),
        "retrieved_context_chunks": retrieved_chunks,
        "prompt": prompt,
        "notes": "Mode CR LLM receives Mode C evidence/routing plus optional local course-material retrieval context.",
    }


def build_mode_c_full_context(scenario: Mapping[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Backward-compatible thin wrapper around the shared C_FULL builder."""

    return build_c_full_context(
        student_query=str(scenario.get("student_query", "")),
        student_id=str(scenario.get("student_id", "")),
        current_page=str(scenario.get("page", "")),
        conversation_history=scenario.get("conversation_history") or scenario.get("prior_turns") or [],
        existing_session_memory=scenario.get("session_memory") or scenario.get("c_full_memory"),
        dashboard_data=dashboard_data,
    )


def build_mode_cm_context(scenario: Mapping[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Build Mode C with short-term memory context for LLM generation."""

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
    memory_dict = {
        "is_follow_up": memory_resolution.is_follow_up,
        "resolved": memory_resolution.resolved,
        "original_query": memory_resolution.original_query,
        "resolved_query": memory_resolution.resolved_query,
        "referenced_items": memory_resolution.referenced_items,
        "memory_context": memory_resolution.memory_context,
        "structured_state": memory_resolution.structured_state,
        "resolution_type": memory_resolution.resolution_type,
        "runtime_metadata": memory_runtime.metadata(),
        "reason": memory_resolution.reason,
    }
    if not memory_resolution.resolved:
        context = build_mode_c_context(scenario, dashboard_data)
        context["memory_resolution"] = memory_dict
        context["memory_metadata"] = memory_runtime.metadata()
        context["original_student_query"] = original_query
        context["resolved_student_query"] = ""
        context["notes"] = context.get("notes", "") + " Mode CM found no resolvable short-term memory context."
        return context

    scenario_for_evidence = dict(scenario)
    scenario_for_evidence["student_query"] = memory_resolution.resolved_query
    evidence_result = build_rq1_evidence_summary(scenario_for_evidence, dashboard_data)
    query_type = str(evidence_result.get("query_type") or classify_query(memory_resolution.resolved_query))
    original_route = route_for_mode_c(query_type, evidence_result)
    selected_route = "memory_resolved_follow_up"
    evidence_result["memory_resolution"] = memory_dict
    evidence_result["original_student_query"] = original_query
    evidence_result["resolved_student_query"] = memory_resolution.resolved_query
    evidence_result["mode_c_route_before_memory"] = original_route
    course_metadata = course_metadata_for_scenario(scenario_for_evidence, evidence_result, selected_route)
    direct_response_reference = render_memory_resolved_follow_up(
        scenario=scenario_for_evidence,
        evidence_result=evidence_result,
        memory_resolution=memory_resolution,
    )
    prompt = build_mode_c_prompt(
        scenario=scenario_for_evidence,
        evidence_result=evidence_result,
        query_type=query_type,
        selected_route=selected_route,
        recommendation_plan={},
        direct_response_reference=direct_response_reference,
        course_metadata=course_metadata,
    )
    prompt += "\n\nShort-term memory context:\n" + format_memory_context_for_prompt(memory_resolution)
    prompt += f"\n\nOriginal follow-up query: {original_query}"
    prompt += f"\nResolved query used for evidence selection: {memory_resolution.resolved_query}"
    return {
        "query_type": query_type,
        "selected_route": selected_route,
        "rq1_selected_sources": list(evidence_result.get("selected_sources", [])),
        "rq1_evidence_summary": evidence_result,
        "rq2_recommendation_plan": {},
        "course_metadata": course_metadata,
        "memory_resolution": memory_dict,
        "memory_metadata": memory_runtime.metadata(),
        "original_student_query": original_query,
        "resolved_student_query": memory_resolution.resolved_query,
        "prompt": prompt,
        "notes": f"Mode CM resolved short-term memory. Original Mode C route after resolution: {original_route}.",
    }


def build_mode_c_prompt(
    scenario: Mapping[str, Any],
    evidence_result: Mapping[str, Any],
    query_type: str,
    selected_route: str,
    recommendation_plan: Mapping[str, Any],
    direct_response_reference: str,
    course_metadata: Mapping[str, Any],
) -> str:
    """Construct the routed Mode C prompt."""

    route_guidance = mode_c_route_guidance(selected_route, query_type)
    sections = [
        "You are a GenAI assistant embedded in a learning analytics dashboard.",
        "Generate the final student-facing response for Mode C.",
        "",
        f"Current dashboard page: {scenario.get('page', '')}",
        f"Student query: {scenario.get('student_query', '')}",
        f"Query type: {query_type}",
        f"Selected route: {selected_route}",
        "",
        "RQ1 selected evidence summary:",
        json.dumps(evidence_result, ensure_ascii=False, indent=2),
        "",
        "Route-specific instructions:",
        route_guidance,
    ]
    if recommendation_plan:
        sections.extend(
            [
                "",
                "RQ2 recommendation plan:",
                json.dumps(recommendation_plan, ensure_ascii=False, indent=2),
                "",
                (
                    "Use the recommendation plan to produce a natural answer, but do not invent "
                    "extra evidence beyond the plan, RQ1 summary, or course metadata."
                ),
            ]
        )
    if course_metadata:
        sections.extend(
            [
                "",
                "Verified course metadata available for this query:",
                json.dumps(course_metadata, ensure_ascii=False, indent=2),
            ]
        )
    if direct_response_reference:
        sections.extend(
            [
                "",
                "Deterministic routed answer for behavioural reference only:",
                direct_response_reference,
                "",
                "Do not copy the reference mechanically. Use it to preserve the intended route behaviour.",
            ]
        )
    sections.extend(
        [
            "",
            "General constraints:",
            "- Answer the student's actual question directly.",
            "- Do not expose internal implementation details, file names, or unsupported-page errors.",
            "- Avoid causal claims unless the evidence explicitly supports them.",
            "- Activity logs can indicate activity patterns; they cannot prove understanding or learning quality.",
            "- Keep the answer clear and concise.",
        ]
    )
    return "\n".join(sections)


def mode_c_route_guidance(selected_route: str, query_type: str) -> str:
    """Return student-facing generation guidance for a Mode C route."""

    if selected_route in DIRECT_FIRST_SENTENCE_ROUTES:
        return (
            "Start with a direct first-sentence answer to the question. Explain the relevant "
            "data provenance, availability, limitation, course metadata, or correction issue. "
            "Do not turn this into a learning recommendation plan."
        )
    if selected_route == "metric_definition":
        return "Define the metric directly and briefly. Do not add unnecessary cross-page evidence or action steps."
    if selected_route == "cross_page_relationship":
        return (
            "Compare the relevant evidence patterns across pages. Avoid causal claims and include uncertainty."
        )
    if selected_route == "dashboard_interpretation":
        return (
            "Explain the selected evidence pattern. A short next step is allowed only if it naturally follows."
        )
    if selected_route == "reflection_structure":
        return (
            "Give a concrete reflection structure, such as what happened, what was learned, "
            "what evidence connects to it, and what the student will do next. Mention dashboard "
            "activity only cautiously as context."
        )
    if selected_route in RECOMMENDATION_ROUTES:
        return (
            "Provide a recommendation only because the query asks for improvement or planning. "
            "Follow this logic: what the data shows, why it matters, what to do next, and why it "
            "fits this student's situation. Make action steps concrete and evidence-grounded."
        )
    if selected_route == "overview_metric_specific":
        return "Answer using the routed page-specific evidence even though the original page is Overview."
    if selected_route == "overview_summary":
        return "Summarise the overall activity pattern cautiously and identify one possible focus area."
    if selected_route == "follow_up_without_context":
        return (
            "Explain that the follow-up is underspecified in offline replay and answer cautiously using the available evidence."
        )
    if selected_route == "memory_resolved_follow_up":
        return (
            "The student is asking a follow-up question that refers to previous assistant advice. "
            "Use the resolved memory context to answer the referenced items directly. "
            "Do not say that previous context is unavailable. "
            "Do not invent previous conversation details beyond the provided memory context. "
            "Keep the answer grounded in dashboard evidence and uncertainty boundaries."
        )
    if selected_route == "overview_fallback":
        return (
            "Provide a graceful fallback. Say which dashboard pages have structured evidence and ask the student to choose "
            "a specific feedback page if the available evidence is insufficient."
        )
    return f"Use the route {selected_route} for query type {query_type}, staying grounded in the selected evidence."


def course_metadata_for_scenario(
    scenario: Mapping[str, Any],
    evidence_result: Mapping[str, Any],
    selected_route: str,
) -> dict[str, Any]:
    """Return compact verified course metadata when it is relevant."""

    query = str(scenario.get("student_query", ""))
    query_l = query.lower()
    metadata: dict[str, Any] = {}
    week = extract_week_key(query)
    if week:
        record = get_lecture_metadata(week)
        if record:
            metadata[week] = record
    if selected_route == "course_content" or any(term in query_l for term in ("lecture", "video", "pre-recorded", "week")):
        metadata.setdefault("lecture_titles_by_week", lecture_titles_by_week())
    selected_evidence = evidence_result.get("selected_evidence", {})
    lecture_evidence = selected_evidence.get("lecture") if isinstance(selected_evidence, Mapping) else None
    if lecture_evidence:
        metadata.setdefault("lecture_evidence_metadata", lecture_evidence)
    return metadata


def extract_week_key(text: str) -> str:
    """Extract a compact week key such as W4 from text."""

    import re

    match = re.search(r"\bW(?:eek)?\s*(\d{1,2})\b", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return f"W{int(match.group(1))}"


def build_openai_messages(mode: str, context: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build chat messages sent to OpenAI."""

    system_prompt = (
        "You are a careful student-facing learning analytics assistant. "
        "Answer using only the information provided in the prompt. "
        "Be direct, grounded, and cautious about uncertainty."
    )
    if mode.upper() == "A":
        system_prompt += " Simulate the baseline page-specific assistant without using cross-page synthesis."
    elif mode.upper() == "B":
        system_prompt += " Use the RQ1 selected evidence synthesis as your grounding."
    elif mode.upper() == "C":
        system_prompt += " Follow the routed Mode C behaviour and use RQ2 planning only when the route calls for advice."
    elif normalise_mode(mode) == "CR":
        system_prompt += " Follow Mode C behaviour and use retrieved course-material chunks only for course/task context."
    elif normalise_mode(mode) == "C_FULL":
        system_prompt += " Follow Mode C behaviour while using short-term memory and course-material retrieval only when explicitly relevant."
    elif normalise_mode(mode) == "CM":
        system_prompt += " Follow Mode C behaviour and use the provided short-term memory context to resolve follow-up references."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": str(context.get("prompt", ""))},
    ]


def call_openai(client: Any, model: str, messages: list[dict[str, str]]) -> str:
    """Call OpenAI and return generated response text."""

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("OpenAI returned an empty response.")
    return content.strip()


def run_generation(
    mode: str,
    scenarios: list[dict[str, Any]],
    model: str,
) -> list[dict[str, Any]]:
    """Generate responses for all scenarios in one mode."""

    client = initialise_openai_client()
    dashboard_data = load_dashboard_data(PROJECT_ROOT)
    records: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios, start=1):
        record = generate_mode_response(
            mode=mode,
            scenario=scenario,
            dashboard_data=dashboard_data,
            client=client,
            model=model,
        )
        records.append(record)
        print(f"Generated {mode.upper()} response {index}/{len(scenarios)}: {record.get('scenario_id', '')}")
    return records


def main() -> None:
    args = parse_args()
    mode = normalise_mode(args.mode)
    scenario_path = args.scenarios if args.scenarios.is_absolute() else PROJECT_ROOT / args.scenarios
    output_path = args.output if args.output else output_path_for_mode(mode)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    scenarios = load_jsonl(scenario_path)
    if args.limit is not None:
        scenarios = scenarios[: args.limit]

    records = run_generation(mode=mode, scenarios=scenarios, model=args.model)
    write_jsonl(records, output_path)

    print(f"Mode {mode}: generated {len(records)} LLM responses.")
    print(f"Saved: {display_path(output_path)}")
    print("Each record includes generated_response, prompt, openai_messages, model, query_type, selected_route, and evidence fields.")


if __name__ == "__main__":
    main()
