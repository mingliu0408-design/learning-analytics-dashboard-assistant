"""Build one mode-independent reference evidence pack per unified scenario."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.assistant_modes import load_dashboard_data  # noqa: E402
from evaluation.unified_evaluation_contract import (  # noqa: E402
    GOLD_LABELS_PATH,
    REFERENCE_EVIDENCE_PATH,
    REFERENCE_EVIDENCE_VERSION,
    SCENARIOS_PATH,
    load_gold_overlay,
    load_jsonl,
)
from utils.course_material_retriever import chunks_to_dicts, retrieve_course_chunks  # noqa: E402
from utils.evidence_synthesiser import select_evidence  # noqa: E402


def reference_source_restrictions(
    gold: Mapping[str, Any], *, course_evidence_available: bool | None = None,
) -> dict[str, Any]:
    capabilities = set(gold.get("gold_required_capabilities") or [])
    return {
        "dashboard_claims": "Use only the supplied dashboard evidence for student-specific activity claims.",
        "course_claims": "Use only the supplied course evidence for course-content or task claims.",
        "memory_claims": "Use only the fixed conversation history for prior-turn claims.",
        "dashboard_evidence_available": "dashboard_evidence" in capabilities,
        "course_evidence_available": (
            bool(gold.get("gold_expected_retrieval"))
            if course_evidence_available is None
            else course_evidence_available
        ),
    }


def build_reference_evidence_rows(
    scenarios: list[dict[str, Any]], gold_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    dashboard_data = load_dashboard_data(PROJECT_ROOT)
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = str(scenario.get("scenario_id", ""))
        gold = gold_by_id[scenario_id]
        capabilities = set(gold.get("gold_required_capabilities") or [])
        dashboard_evidence: dict[str, Any] = {}
        if "dashboard_evidence" in capabilities:
            dashboard_evidence = select_evidence(
                str(scenario.get("student_query", "")),
                str(scenario.get("page", "")),
                scenario.get("student_id", "301127"),
                dashboard_data,
                query_type=str(gold.get("gold_query_type", "")),
            )
        course_chunks: list[dict[str, Any]] = []
        if gold.get("gold_expected_retrieval"):
            result = retrieve_course_chunks(
                str(scenario.get("student_query", "")),
                query_type=str(gold.get("gold_query_type", "")),
                top_k=2,
            )
            course_chunks = chunks_to_dicts(result.chunks)
        rows.append(
            {
                "scenario_id": scenario_id,
                "reference_student_query": scenario.get("student_query", ""),
                "reference_conversation_history": scenario.get("conversation_history", []),
                "reference_page": scenario.get("page", ""),
                "reference_dashboard_evidence": dashboard_evidence,
                "reference_course_evidence": course_chunks,
                "reference_source_restrictions": reference_source_restrictions(
                    gold, course_evidence_available=bool(course_chunks)
                ),
                "reference_evidence_notes": "Built once from the frozen scenario and gold task intent, never from a mode response. Human review is required before formal judging.",
                "reference_chunk_ids": [str(chunk.get("chunk_id", "")) for chunk in course_chunks],
                "reference_evidence_version": REFERENCE_EVIDENCE_VERSION,
                "review_status": "pending",
                "reviewed_by": "",
                "reviewed_at": "",
                "review_notes": "",
            }
        )
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    rows = build_reference_evidence_rows(load_jsonl(SCENARIOS_PATH), load_gold_overlay(GOLD_LABELS_PATH))
    write_jsonl(rows, REFERENCE_EVIDENCE_PATH)
    print(f"Built {len(rows)} pending-review reference evidence rows at {REFERENCE_EVIDENCE_PATH}")


if __name__ == "__main__":
    main()
