#!/usr/bin/env python3
"""Headless mock-only replay interface for C4_REAL_V1.

This runner never binds a network provider and never emits response text.  It
exists to exercise the same ``C4RealService`` entry point used by the
feature-flagged Streamlit scaffold.  It is not an RQ3 shard runner or scorer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


if __package__ in {None, ""}:
    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))

from evaluation.rq3_real_c4.mock_providers import build_mock_dependencies
from utils.c4_real_contracts import C4Mode, C4RealRequest, ExecutionContext
from utils.c4_real_service import C4RealService


DEFAULT_MOCK_SCENARIO: Mapping[str, Any] = {
    "track_s_mock": True,
    "scenario_id": "TRACK-S-MOCK-SCENARIO-001",
    "student_id": "TRACK-S-MOCK-STUDENT-001",
    "current_query": "Synthetic orchestration request; do not generate an answer.",
    "current_page": "Overview",
    "dashboard_context": {"mock_only": True, "activity_count": 2},
    "visible_conversation_history": [],
}


def _assert_mock_only_service(service: C4RealService) -> None:
    identities = {
        name: str(getattr(provider, "identity", ""))
        for name, provider in (
            ("clarification_gate", service.dependencies.clarification_gate),
            ("p3_router", service.dependencies.p3_router),
            ("evidence_synthesiser", service.dependencies.evidence_synthesiser),
            ("course_rag", service.dependencies.course_rag),
            ("learner_memory", service.dependencies.learner_memory),
            ("evidence_compiler", service.dependencies.evidence_compiler),
            ("planner", service.dependencies.planner),
            ("generator", service.dependencies.generator),
            ("output_guard", service.dependencies.output_guard),
        )
    }
    expected = {
        "clarification_gate": "TRACK_S_MOCK_CLARIFICATION_GATE",
        "p3_router": "TRACK_S_MOCK_PRECOMPUTED_ROUTE_CACHE",
        "evidence_synthesiser": "TRACK_S_MOCK_EVIDENCE_SYNTHESISER",
        "course_rag": "TRACK_S_MOCK_COURSE_RAG",
        "learner_memory": "TRACK_S_MOCK_LEARNER_MEMORY",
        "evidence_compiler": "TRACK_S_MOCK_EVIDENCE_COMPILER",
        "planner": "TRACK_S_MOCK_RECOMMENDATION_PLANNER",
        "generator": "TRACK_S_MOCK_COMMON_GENERATOR",
        "output_guard": "TRACK_S_MOCK_OUTPUT_GUARD",
    }
    invalid = {
        name: value for name, value in identities.items() if value != expected[name]
    }
    if invalid:
        raise ValueError(f"Headless replay rejected non-mock providers: {sorted(invalid)}")


def _normalise_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "track_s_mock",
        "scenario_id",
        "student_id",
        "current_query",
        "current_page",
        "dashboard_context",
        "visible_conversation_history",
    }
    missing = sorted(required - set(scenario))
    if missing:
        raise ValueError(f"Scenario is missing required fields: {missing}")
    if scenario.get("track_s_mock") is not True:
        raise ValueError("Track S replay accepts only inputs explicitly marked track_s_mock=true")
    prohibited = sorted(
        set(scenario)
        & {
            "gold",
            "gold_route",
            "expected_route",
            "reference_answer",
            "generated_answer",
            "score",
        }
    )
    if prohibited:
        raise ValueError(f"Track S replay rejects scoring/answer fields: {prohibited}")
    return {key: scenario[key] for key in required}


def run_scenario_all_modes(
    scenario: Mapping[str, Any],
    *,
    modes: Sequence[C4Mode] | None = None,
    service: C4RealService | None = None,
) -> list[dict[str, Any]]:
    """Replay one scenario independently across every requested condition."""

    normalised = _normalise_scenario(scenario)
    if service is None:
        dependencies, _, _, _ = build_mock_dependencies()
        service = C4RealService(dependencies)
    _assert_mock_only_service(service)

    selected_modes = tuple(modes or tuple(C4Mode))
    records: list[dict[str, Any]] = []
    for mode in selected_modes:
        reset_id = f"TRACK-S-RESET::{normalised['scenario_id']}::{mode.value}"
        request = C4RealRequest(
            request_id=f"TRACK-S-REQUEST::{normalised['scenario_id']}::{mode.value}",
            scenario_id=str(normalised["scenario_id"]),
            mode=mode,
            current_query=str(normalised["current_query"]),
            current_page=str(normalised["current_page"]),
            dashboard_context=normalised["dashboard_context"],
            visible_conversation_history=tuple(
                normalised["visible_conversation_history"]
            ),
            student_id=str(normalised["student_id"]),
            session_id=f"TRACK-S-SESSION::{normalised['scenario_id']}",
            state_reset_id=reset_id,
            execution_context=ExecutionContext.EVALUATION,
        )
        # Fresh database namespace and an explicit reset before every condition.
        service.reset_state(request)
        result = service.execute(request)
        if result.output is not None and result.output.text:
            raise RuntimeError("Track S replay must not produce response text")
        records.append(
            {
                "schema_version": "c4-real-v1-headless-replay-record-v1",
                "scenario_id": request.scenario_id,
                "request_id": request.request_id,
                "mode": mode.value,
                "success": result.success,
                "real_answer_generated": False,
                "output_kind": (
                    result.output.output_kind if result.output is not None else "NONE"
                ),
                "memory_write_proposal_created": result.memory_write_proposal is not None,
                "trace": result.trace.to_dict(),
            }
        )
    return records


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Line {line_number} must contain a JSON object")
        rows.append(value)
    return rows


def serialise_jsonl(records: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records
    ) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario-jsonl",
        type=Path,
        help="Optional synthetic/mock JSONL input. No controlled-RQ3 data is bundled.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        help="Optional trace-only output path; stdout is used when omitted.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[mode.value for mode in C4Mode],
        help="Subset of modes; all nine run by default.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    scenarios = (
        load_jsonl(args.scenario_jsonl)
        if args.scenario_jsonl is not None
        else [dict(DEFAULT_MOCK_SCENARIO)]
    )
    modes = tuple(C4Mode(value) for value in args.modes) if args.modes else None
    records = [
        record
        for scenario in scenarios
        for record in run_scenario_all_modes(scenario, modes=modes)
    ]
    payload = serialise_jsonl(records)
    if args.output_jsonl is None:
        sys.stdout.write(payload)
    else:
        args.output_jsonl.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
