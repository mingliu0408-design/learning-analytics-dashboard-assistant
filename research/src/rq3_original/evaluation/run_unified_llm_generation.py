"""Generate LLM responses for the unified capability benchmark.

Default behaviour uses the OpenAI API and writes one JSONL record per
scenario-mode pair. Use ``--dry-run`` only for local debugging; the dissertation
benchmark should use real LLM-generated responses.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.assistant_modes import load_dashboard_data, run_assistant_mode  # noqa: E402
from evaluation.run_llm_generation import (  # noqa: E402
    generate_mode_response,
    initialise_openai_client,
    normalise_mode,
)
from evaluation.unified_evaluation_contract import GOLD_LABELS_PATH, load_gold_overlay  # noqa: E402
from utils.c_full_service import build_c_full_context  # noqa: E402


SCENARIOS = PROJECT_ROOT / "evaluation" / "unified_benchmark_scenarios.jsonl"
OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_llm_responses_v1.jsonl"
DEFAULT_MODES = ["A", "B", "C", "CM", "CR", "C_FULL"]


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(description="Generate unified benchmark LLM responses.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES), help="Comma-separated modes to run.")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model for real LLM generation.")
    parser.add_argument("--max-scenarios", type=int, default=None, help="Optional maximum number of scenarios.")
    parser.add_argument(
        "--scenario-groups",
        default="",
        help="Optional comma-separated scenario_group filter.",
    )
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic local mode renderers for debugging instead of OpenAI generation.",
    )
    writes = parser.add_mutually_exclusive_group()
    writes.add_argument("--resume", action="store_true", help="Continue only missing scenario-mode pairs from an existing validated output.")
    writes.add_argument("--overwrite", action="store_true", help="Replace an existing output before generation.")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON records."""

    if not path.exists():
        raise FileNotFoundError(f"Missing scenario file: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} line {line_no}: {exc}") from exc
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    """Write newline-delimited JSON records."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_path(path: Path) -> Path:
    """Resolve a path relative to the project root."""

    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_modes(value: str) -> list[str]:
    """Parse and normalise a comma-separated mode list."""

    modes = [normalise_mode(part.strip()) for part in value.split(",") if part.strip()]
    if not modes:
        raise ValueError("At least one mode must be specified.")
    return modes


def filter_scenarios(rows: list[dict[str, Any]], groups: str, max_scenarios: int | None) -> list[dict[str, Any]]:
    """Apply optional group and count filters."""

    selected = list(rows)
    if groups:
        wanted = {group.strip() for group in groups.split(",") if group.strip()}
        selected = [row for row in selected if row.get("scenario_group") in wanted]
    if max_scenarios is not None:
        selected = selected[: max_scenarios]
    return selected


def attach_gold_labels(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach frozen labels without using production prediction functions."""

    overlay = load_gold_overlay(GOLD_LABELS_PATH)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        scenario_id = str(row.get("scenario_id", ""))
        if scenario_id not in overlay:
            raise ValueError(f"Missing frozen gold label for {scenario_id}")
        item = dict(row)
        item.update(overlay[scenario_id])
        enriched.append(item)
    return enriched


def dry_run_record(mode: str, scenario: dict[str, Any], dashboard_data: Any) -> dict[str, Any]:
    """Generate a deterministic record for local debugging."""

    if mode in {"C_FULL_KEYWORD", "C_FULL_SEMANTIC"}:
        intent_router_mode = (
            "keyword_baseline" if mode == "C_FULL_KEYWORD" else "semantic_enhanced"
        )
        context = build_c_full_context(
            student_query=str(scenario.get("student_query", "")),
            student_id=str(scenario.get("student_id", "")),
            current_page=str(scenario.get("page", "")),
            conversation_history=scenario.get("conversation_history")
            or scenario.get("prior_turns")
            or [],
            existing_session_memory=scenario.get("session_memory")
            or scenario.get("c_full_memory")
            or {},
            dashboard_data=dashboard_data,
            intent_router_mode=intent_router_mode,
        )
        retrieval = context.get("retrieval_result") or {}
        return {
            "mode": mode,
            "generation_type": "dry_run_context_only",
            "model": "dry_run_context_only",
            "query_type": context.get("query_type", ""),
            "selected_route": context.get("selected_route", ""),
            "response": "[DRY RUN: C_FULL context built without an LLM call]",
            "generated_response": "[DRY RUN: C_FULL context built without an LLM call]",
            "rq1_selected_sources": context.get("rq1_selected_sources", []),
            "rq1_evidence_summary": context.get("rq1_evidence_summary", {}),
            "memory_resolution": context.get("memory_resolution", {}),
            "memory_metadata": context.get("memory_metadata", {}),
            "memory_triggered": bool((context.get("memory_metadata") or {}).get("memory_triggered")),
            "memory_used": bool((context.get("memory_metadata") or {}).get("memory_used")),
            "memory_resolved": bool((context.get("memory_metadata") or {}).get("memory_resolved")),
            "resolved_student_query": context.get("resolved_student_query", ""),
            "retrieval_result": retrieval,
            "retrieval_used": bool(retrieval.get("retrieval_used")),
            "retrieved_context_chunks": context.get("retrieved_context_chunks", []),
            "retrieved_chunk_ids": list(retrieval.get("retrieved_chunk_ids") or []),
            "retrieved_chunk_titles": list(retrieval.get("retrieved_chunk_titles") or []),
            "constructed_prompt": context.get("prompt", ""),
            "notes": context.get("notes", ""),
            "intent_routing": context.get("intent_routing", {}),
        }

    result = run_assistant_mode(mode, scenario, dashboard_data)
    return {
        "mode": mode,
        "generation_type": "dry_run_deterministic",
        "model": "dry_run_deterministic",
        "query_type": result.effective_query_type or scenario.get("query_type", ""),
        "selected_route": result.selected_route,
        "response": result.generated_response,
        "generated_response": result.generated_response,
        "rq1_selected_sources": result.rq1_selected_sources,
        "rq1_evidence_summary": result.rq1_evidence_summary,
        "memory_resolution": result.memory_resolution,
        "memory_metadata": result.memory_metadata,
        "memory_triggered": result.memory_triggered,
        "memory_used": result.memory_used,
        "memory_resolved": result.memory_resolved,
        "resolved_student_query": result.resolved_student_query,
        "retrieval_result": result.retrieval_result,
        "retrieval_used": result.retrieval_used,
        "retrieved_context_chunks": result.retrieved_context_chunks,
        "retrieved_chunk_ids": [chunk.get("chunk_id", "") for chunk in result.retrieved_context_chunks],
        "retrieved_chunk_titles": [chunk.get("title", "") for chunk in result.retrieved_context_chunks],
        "constructed_prompt": result.constructed_prompt,
        "notes": result.notes,
    }


def unified_response_record(
    scenario: dict[str, Any],
    mode: str,
    generated: dict[str, Any],
    model: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Shape a mode response into the unified output schema."""

    memory_resolution = generated.get("memory_resolution") or {}
    retrieval_result = generated.get("retrieval_result") or {}
    response = generated.get("response") or generated.get("generated_response", "")
    predicted_query_type = generated.get("query_type") or scenario.get("predicted_query_type", "")
    predicted_route = generated.get("selected_route", "")
    predicted_memory_trigger = bool(generated.get("memory_triggered") or memory_resolution.get("is_follow_up"))
    predicted_retrieval_decision = bool(generated.get("retrieval_used") or retrieval_result.get("retrieval_used"))
    return {
        "scenario_id": scenario.get("scenario_id", ""),
        "source_dataset": scenario.get("source_dataset", ""),
        "source_scenario_id": scenario.get("source_scenario_id", ""),
        "scenario_group": scenario.get("scenario_group", ""),
        "mode": mode,
        "student_id": scenario.get("student_id", ""),
        "page": scenario.get("page", ""),
        "student_query": scenario.get("student_query", ""),
        "conversation_history": scenario.get("conversation_history", []),
        "required_capabilities": scenario.get("required_capabilities", []),
        "applicable_judge_dimensions": scenario.get("applicable_judge_dimensions", []),
        "expected_route": scenario.get("expected_route", ""),
        "expected_memory": scenario.get("expected_memory", False),
        "expected_memory_items": scenario.get("expected_memory_items", []),
        "expected_memory_state_fields": scenario.get("expected_memory_state_fields", []),
        "expected_retrieval": scenario.get("expected_retrieval", False),
        "expected_sources": scenario.get("expected_sources", []),
        "expected_topics": scenario.get("expected_topics", []),
        "gold_query_type": scenario.get("gold_query_type", scenario.get("query_type", "")),
        "gold_scenario_group": scenario.get("gold_scenario_group", scenario.get("scenario_group", "")),
        "gold_expected_route": scenario.get("gold_expected_route", scenario.get("expected_route", "")),
        "gold_expected_memory": scenario.get("gold_expected_memory", scenario.get("expected_memory", False)),
        "gold_expected_retrieval": scenario.get("gold_expected_retrieval", scenario.get("expected_retrieval", False)),
        "gold_required_capabilities": scenario.get("gold_required_capabilities", scenario.get("required_capabilities", [])),
        "gold_applicable_quality_dimensions": scenario.get("gold_applicable_quality_dimensions", scenario.get("applicable_judge_dimensions", [])),
        "gold_applicable_mechanism_dimensions": scenario.get("gold_applicable_mechanism_dimensions", []),
        "gold_notes": scenario.get("gold_notes", ""),
        "gold_label_version": scenario.get("gold_label_version", ""),
        "predicted_query_type": predicted_query_type,
        "predicted_route": predicted_route,
        "predicted_memory_trigger": predicted_memory_trigger,
        "predicted_retrieval_decision": predicted_retrieval_decision,
        "query_type": predicted_query_type,
        "selected_route": predicted_route,
        "memory_triggered": predicted_memory_trigger,
        "memory_used": bool(generated.get("memory_used") or memory_resolution.get("resolved")),
        "memory_resolved": bool(generated.get("memory_resolved") or memory_resolution.get("resolved")),
        "resolved_student_query": generated.get("resolved_student_query", ""),
        "retrieval_used": predicted_retrieval_decision,
        "retrieved_chunk_ids": generated.get("retrieved_chunk_ids", []),
        "retrieved_chunk_titles": generated.get("retrieved_chunk_titles", []),
        "retrieved_context_chunks": generated.get("retrieved_context_chunks", []),
        "response": response,
        "generated_response": response,
        "generation_model": generated.get("model") or ("dry_run_deterministic" if dry_run else model),
        "generation_type": generated.get("generation_type", "openai_llm" if not dry_run else "dry_run_deterministic"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "constructed_prompt": generated.get("constructed_prompt") or generated.get("prompt", ""),
        "openai_messages": generated.get("openai_messages", []),
        "rq1_selected_sources": generated.get("rq1_selected_sources", []),
        "rq1_evidence_summary": generated.get("rq1_evidence_summary", {}),
        "rq2_recommendation_plan": generated.get("rq2_recommendation_plan", {}),
        "memory_resolution": memory_resolution,
        "memory_metadata": generated.get("memory_metadata") or memory_resolution.get("runtime_metadata", {}),
        "retrieval_result": retrieval_result,
        "notes": generated.get("notes", ""),
        "generation_succeeded": bool(generated.get("generation_succeeded", True)),
        "original_student_query": generated.get("original_student_query", scenario.get("student_query", "")),
        "effective_query": generated.get("effective_query", ""),
        "pre_generation_structured_memory": generated.get("pre_generation_structured_memory", {}),
        "post_commit_structured_memory": generated.get("post_commit_structured_memory", {}),
        "post_commit_memory_metadata": generated.get("post_commit_memory_metadata", {}),
        "memory_commit": generated.get("memory_commit", {}),
        "intent_routing": generated.get("intent_routing", {}),
        "automatic_metrics": generated.get("automatic_metrics", {}),
    }


def run_generation(
    scenarios: list[dict[str, Any]],
    modes: list[str],
    model: str,
    dry_run: bool,
    output_path: Path | None = None,
    resume: bool = False,
    overwrite: bool = False,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Incrementally generate and checkpoint every scenario-mode pair."""

    dashboard_data = load_dashboard_data(PROJECT_ROOT)
    expected_model = "dry_run_deterministic" if dry_run else model
    scenario_hash = _scenario_set_hash(scenarios)
    expected_keys = {(str(s.get("scenario_id", "")), mode) for s in scenarios for mode in modes}
    rows: list[dict[str, Any]] = []
    completed_keys: set[tuple[str, str]] = set()
    append_handle = None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not (resume or overwrite):
            raise FileExistsError(
                f"Output already exists: {output_path}. Use --resume or --overwrite; no API calls were made."
            )
        if overwrite:
            output_path.write_text("", encoding="utf-8")
        elif resume and output_path.exists():
            rows = load_jsonl(output_path)
            completed_keys = _validate_resume_records(
                rows, expected_keys, expected_model, scenario_hash, len(scenarios)
            )
        append_handle = output_path.open("a", encoding="utf-8")
    if not dry_run and client is None:
        client = initialise_openai_client()
    total = len(scenarios) * len(modes)
    try:
        for scenario in scenarios:
            for mode in modes:
                key = (str(scenario.get("scenario_id", "")), mode)
                if key in completed_keys:
                    print(f"Skipped completed: {key[0]} mode={mode}")
                    continue
                try:
                    generated = (
                        dry_run_record(mode, scenario, dashboard_data)
                        if dry_run
                        else generate_mode_response(mode, scenario, dashboard_data, client, model)
                    )
                    record = unified_response_record(scenario, mode, generated, model, dry_run=dry_run)
                except Exception as exc:
                    raise RuntimeError(f"Unified generation failed for scenario_id={key[0]} mode={mode}") from exc
                record["scenario_set_hash"] = scenario_hash
                record["scenario_count"] = len(scenarios)
                if append_handle is not None:
                    append_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    append_handle.flush()
                    os.fsync(append_handle.fileno())
                rows.append(record)
                completed_keys.add(key)
                print(f"Generated {len(completed_keys)}/{total}: {key[0]} mode={mode}")
    finally:
        if append_handle is not None:
            append_handle.close()
    actual_keys = {(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in rows}
    if actual_keys != expected_keys or len(rows) != len(expected_keys):
        raise RuntimeError(
            f"Unified generation incomplete: expected {len(expected_keys)} unique records, got {len(actual_keys)}. Do not judge this output."
        )
    return rows


def _scenario_set_hash(scenarios: list[dict[str, Any]]) -> str:
    payload = json.dumps(scenarios, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_resume_records(
    rows: list[dict[str, Any]],
    expected_keys: set[tuple[str, str]],
    expected_model: str,
    scenario_hash: str,
    scenario_count: int,
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=1):
        key = (str(row.get("scenario_id", "")), str(row.get("mode", "")))
        if key in keys:
            raise ValueError(f"Duplicate unified generation key at record {index}: {key}")
        if key not in expected_keys:
            raise ValueError(f"Existing record is outside the selected scenario/mode set: {key}")
        if str(row.get("generation_model", "")) != expected_model:
            raise ValueError(
                f"Generation model mismatch for {key}: existing={row.get('generation_model')} requested={expected_model}"
            )
        if row.get("scenario_set_hash") != scenario_hash or int(row.get("scenario_count", -1)) != scenario_count:
            raise ValueError(f"Scenario set identity mismatch for existing record {key}")
        keys.add(key)
    return keys


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    scenario_path = resolve_path(args.scenarios)
    output_path = resolve_path(args.output)
    scenarios = filter_scenarios(
        attach_gold_labels(load_jsonl(scenario_path)),
        args.scenario_groups,
        args.max_scenarios,
    )
    modes = parse_modes(args.modes)
    rows = run_generation(
        scenarios=scenarios,
        modes=modes,
        model=args.model,
        dry_run=args.dry_run,
        output_path=output_path,
        resume=args.resume,
        overwrite=args.overwrite,
    )
    print(f"Generated {len(rows)} unified response records.")
    print(f"Saved: {display_path(output_path)}")
    if args.dry_run:
        print("Generation mode: dry-run deterministic. Use without --dry-run for the LLM-generated benchmark.")
    else:
        print(f"Generation mode: OpenAI API model={args.model}")


if __name__ == "__main__":
    main()
