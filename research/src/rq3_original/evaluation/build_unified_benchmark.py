"""Build the unified capability benchmark scenario file.

The unified benchmark combines the original replay scenarios, the short-term
memory diagnostic scenarios, the course-material retrieval scenarios, and a
small set of hand-written hybrid/stress cases. It is a capability-based
diagnostic benchmark, not a real-world deployment sample.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    GOLD_LABELS_PATH,
    QUALITY_DIMENSIONS,
    load_gold_overlay,
)


MAIN_SCENARIOS = PROJECT_ROOT / "evaluation" / "scenarios.jsonl"
MEMORY_SCENARIOS = PROJECT_ROOT / "evaluation" / "multiturn_scenarios.jsonl"
RAG_SCENARIOS = PROJECT_ROOT / "evaluation" / "rag_scenarios.jsonl"
OUTPUT = PROJECT_ROOT / "evaluation" / "unified_benchmark_scenarios.jsonl"

CORE_DIMENSIONS = [
    "response_relevance",
    "evidence_integration",
    "context_awareness",
    "personalisation",
    "explanatory_quality",
    "uncertainty_handling",
    "unsupported_claims_risk",
    "route_appropriateness",
]

ACTIONABLE_QUERY_TYPES = {
    "improvement_recommendation",
    "planning_or_strategy",
    "reflection_structure_question",
}

TECHNICAL_QUERY_TYPES = {
    "technical_data_question",
    "access_or_capability_question",
    "discrepancy_or_correction",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL records."""

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
    """Write JSONL records."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_unified_scenarios() -> list[dict[str, Any]]:
    """Build scenarios, then apply the independent frozen gold overlay."""

    raw_rows: list[dict[str, Any]] = []
    for row in load_jsonl(MAIN_SCENARIOS):
        raw_rows.append(from_main_scenario(row))
    for row in load_jsonl(MEMORY_SCENARIOS):
        raw_rows.append(from_memory_scenario(row))
    for row in load_jsonl(RAG_SCENARIOS):
        raw_rows.append(from_rag_scenario(row))
    for row in additional_scenarios():
        raw_rows.append(from_additional_scenario(row))

    gold = load_gold_overlay(GOLD_LABELS_PATH)
    unified: list[dict[str, Any]] = []
    for idx, row in enumerate(raw_rows, start=1):
        item = dict(row)
        item["scenario_id"] = f"U{idx:03d}"
        label = gold.get(item["scenario_id"])
        if not label:
            raise ValueError(f"Missing frozen gold label for {item['scenario_id']}")
        item.setdefault("conversation_history", [])
        item.setdefault("expected_memory_items", [])
        item.setdefault("expected_memory_state_fields", [])
        item.setdefault("expected_sources", [])
        item.setdefault("expected_topics", [])
        item.setdefault("notes", "")
        item.update(
            {
                "query_type": label["gold_query_type"],
                "scenario_group": label["gold_scenario_group"],
                "required_capabilities": list(label["gold_required_capabilities"]),
                "expected_route": label["gold_expected_route"],
                "expected_memory": bool(label["gold_expected_memory"]),
                "expected_retrieval": bool(label["gold_expected_retrieval"]),
                **label,
                "predicted_query_type": "",
                "predicted_route": "",
                "predicted_memory_trigger": None,
                "predicted_retrieval_decision": None,
            }
        )
        # Retain the legacy mixed-rubric field for backward compatibility only.
        # The final evaluation consumes the two gold_applicable_* fields above.
        item["applicable_judge_dimensions"] = applicable_dimensions(item)
        unified.append(item)
    validate_unified_scenarios(unified)
    return unified


def from_main_scenario(row: dict[str, Any]) -> dict[str, Any]:
    """Convert an original A/B/C scenario to the unified schema."""

    query = str(row.get("student_query", ""))
    query_type = str(row.get("query_type") or "")
    expected_retrieval = False
    group = "unlabelled"
    capabilities: list[str] = []
    return base_record(
        source_dataset="main_benchmark",
        source_scenario_id=row.get("scenario_id", ""),
        page=row.get("page", ""),
        student_id=row.get("student_id", "301127"),
        student_query=query,
        query_type=query_type,
        scenario_group=group,
        required_capabilities=capabilities,
        expected_route=expected_route_for_group(group, query_type),
        expected_retrieval=expected_retrieval,
        expected_memory=False,
        expected_sources=row.get("expected_evidence_sources", []),
        expected_topics=[],
        notes="Derived from the original offline benchmark.",
    )


def from_memory_scenario(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a short-term memory diagnostic scenario."""

    query = str(row.get("student_query", ""))
    query_type = ""
    expected_items = [str(item) for item in row.get("expected_memory_items", [])]
    expected_memory = bool(row.get("expected_memory", expected_items))
    expected_retrieval = False
    group = "memory_follow_up" if expected_memory else "negative_control"
    if group == "negative_control":
        expected_retrieval = False
    capabilities = capabilities_for_group(group, query_type, expected_retrieval, expected_memory=expected_memory)
    if group == "negative_control":
        notes = (
            "Derived from the short-term memory diagnostic dataset. Negative control: no memory resolution is "
            "expected, and course-material retrieval is not expected unless the query explicitly asks for "
            "course/task/material guidance."
        )
    else:
        notes = "Derived from the short-term memory diagnostic dataset."
    return base_record(
        source_dataset="memory_diagnostic",
        source_scenario_id=row.get("scenario_id", ""),
        page=row.get("page", ""),
        student_id=row.get("student_id", "301127"),
        student_query=query,
        query_type=query_type,
        scenario_group=group,
        required_capabilities=capabilities,
        expected_route="memory_follow_up" if expected_memory else "dashboard_interpretation",
        expected_retrieval=expected_retrieval,
        expected_memory=expected_memory,
        expected_memory_items=expected_items,
        expected_memory_state_fields=row.get("expected_memory_state_fields", []),
        expected_sources=[],
        expected_topics=row.get("expected_resolved_topics", []),
        conversation_history=row.get("conversation_history", []),
        notes=notes,
    )


def from_rag_scenario(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a course-material retrieval scenario."""

    query = str(row.get("student_query", ""))
    query_type = ""
    expected_retrieval = bool(row.get("expected_retrieval"))
    group = "course_material_retrieval" if expected_retrieval else "negative_control"
    capabilities = capabilities_for_group(group, query_type, expected_retrieval, expected_memory=False)
    return base_record(
        source_dataset="rag_diagnostic",
        source_scenario_id=row.get("scenario_id", ""),
        page=row.get("page", ""),
        student_id=row.get("student_id", "301127"),
        student_query=query,
        query_type=query_type,
        scenario_group=group,
        required_capabilities=capabilities,
        expected_route="course_material_retrieval" if expected_retrieval else "dashboard_interpretation",
        expected_retrieval=expected_retrieval,
        expected_memory=False,
        expected_sources=row.get("expected_sources", []),
        expected_topics=row.get("expected_topics", []),
        notes=row.get("notes", "Derived from the course-material retrieval diagnostic dataset."),
    )


def from_additional_scenario(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a hand-written unified scenario."""

    query = str(row["student_query"])
    query_type = str(row.get("query_type") or "")
    expected_memory = bool(row.get("expected_memory"))
    expected_retrieval = bool(row.get("expected_retrieval", False))
    group = str(row["scenario_group"])
    capabilities = row.get("required_capabilities") or capabilities_for_group(
        group, query_type, expected_retrieval, expected_memory=expected_memory
    )
    return base_record(
        source_dataset="handwritten_unified",
        source_scenario_id=row.get("source_scenario_id", ""),
        page=row.get("page", ""),
        student_id=row.get("student_id", "301127"),
        student_query=query,
        query_type=query_type,
        scenario_group=group,
        required_capabilities=capabilities,
        expected_route=row.get("expected_route", expected_route_for_group(group, query_type)),
        expected_retrieval=expected_retrieval,
        expected_memory=expected_memory,
        expected_memory_items=row.get("expected_memory_items", []),
        expected_memory_state_fields=row.get("expected_memory_state_fields", []),
        expected_sources=row.get("expected_sources", []),
        expected_topics=row.get("expected_topics", []),
        conversation_history=row.get("conversation_history", []),
        notes=row.get("notes", "Hand-written unified benchmark scenario."),
    )


def base_record(**kwargs: Any) -> dict[str, Any]:
    """Return a record with the common schema."""

    return {
        "scenario_id": "",
        "source_dataset": kwargs.get("source_dataset", ""),
        "source_scenario_id": kwargs.get("source_scenario_id", ""),
        "page": kwargs.get("page", ""),
        "student_id": kwargs.get("student_id", "301127"),
        "student_query": kwargs.get("student_query", ""),
        "conversation_history": kwargs.get("conversation_history", []),
        "query_type": kwargs.get("query_type", ""),
        "scenario_group": kwargs.get("scenario_group", ""),
        "required_capabilities": list(kwargs.get("required_capabilities", [])),
        "expected_route": kwargs.get("expected_route", ""),
        "expected_retrieval": bool(kwargs.get("expected_retrieval", False)),
        "expected_memory": bool(kwargs.get("expected_memory", False)),
        "expected_memory_items": [str(item) for item in kwargs.get("expected_memory_items", [])],
        "expected_memory_state_fields": list(kwargs.get("expected_memory_state_fields", [])),
        "expected_sources": list(kwargs.get("expected_sources", [])),
        "expected_topics": list(kwargs.get("expected_topics", [])),
        "applicable_judge_dimensions": [],
        "notes": kwargs.get("notes", ""),
    }


def scenario_group_for_query(query_type: str, query: str, expected_retrieval: bool) -> str:
    """Assign an original scenario to a capability group."""

    if query_type == "metric_clarification":
        return "metric_clarification"
    if expected_retrieval:
        return "course_material_retrieval"
    if query_type in TECHNICAL_QUERY_TYPES or query_type == "access_or_capability_question":
        return "technical_access_or_discrepancy"
    if query_type == "cross_page_relationship":
        return "cross_page_evidence_synthesis"
    if query_type in {"improvement_recommendation", "planning_or_strategy", "reflection_structure_question"}:
        return "recommendation_planning"
    if "relate" in query.lower() or "across" in query.lower():
        return "cross_page_evidence_synthesis"
    return "dashboard_interpretation"


def capabilities_for_group(
    group: str,
    query_type: str,
    expected_retrieval: bool,
    expected_memory: bool,
) -> list[str]:
    """Return required capabilities for a group/query."""

    capabilities: list[str] = []
    if group != "course_material_retrieval":
        capabilities.append("dashboard_evidence")
    if query_type in ACTIONABLE_QUERY_TYPES or group in {"recommendation_planning", "hybrid_memory_and_retrieval", "hybrid_evidence_and_retrieval"}:
        capabilities.append("recommendation_planning")
    if group != "negative_control" and (expected_memory or group in {"memory_follow_up", "hybrid_memory_and_retrieval"}):
        capabilities.append("short_term_memory")
    if group != "negative_control" and (expected_retrieval or group in {"course_material_retrieval", "hybrid_memory_and_retrieval", "hybrid_evidence_and_retrieval"}):
        capabilities.append("course_material_retrieval")
    if group == "technical_access_or_discrepancy" or query_type in TECHNICAL_QUERY_TYPES:
        capabilities.append("technical_access_handling")
    if group.startswith("hybrid"):
        capabilities.append("hybrid")
    return _dedupe(capabilities) or ["dashboard_evidence"]


def expected_route_for_group(group: str, query_type: str) -> str:
    """Return a compact expected route label for evaluation metadata."""

    if group == "memory_follow_up":
        return "memory_follow_up"
    if group == "course_material_retrieval":
        return "course_material_retrieval"
    if group.startswith("hybrid"):
        return group
    if group == "technical_access_or_discrepancy":
        return "direct_technical_access_or_discrepancy"
    if group == "recommendation_planning":
        return "recommendation_planning"
    if group == "cross_page_evidence_synthesis":
        return "cross_page_evidence_synthesis"
    if query_type == "metric_clarification":
        return "metric_clarification"
    return "dashboard_interpretation"


def applicable_dimensions(row: dict[str, Any]) -> list[str]:
    """Return rubric dimensions applicable to a scenario."""

    dims = list(CORE_DIMENSIONS)
    query_type = row.get("query_type", "")
    group = row.get("scenario_group", "")
    if query_type in ACTIONABLE_QUERY_TYPES or group in {
        "recommendation_planning",
        "memory_follow_up",
        "hybrid_memory_and_retrieval",
        "hybrid_evidence_and_retrieval",
    }:
        dims.insert(4, "actionability")
    if row.get("expected_memory") or "short_term_memory" in row.get("required_capabilities", []):
        dims.append("memory_followup_accuracy")
    if row.get("expected_retrieval") or "course_material_retrieval" in row.get("required_capabilities", []):
        dims.extend(["retrieval_grounding", "course_context_use"])
    return _dedupe(dims)


def additional_scenarios() -> list[dict[str, Any]]:
    """Hand-written scenarios that fill capability gaps and hybrid cases."""

    return [
        {
            "source_scenario_id": "H001",
            "page": "Debate",
            "student_query": "What does Debate_replies mean?",
            "scenario_group": "metric_clarification",
            "expected_route": "metric_clarification",
        },
        {
            "source_scenario_id": "H002",
            "page": "Lecture",
            "student_query": "What does Video View % mean?",
            "scenario_group": "metric_clarification",
            "expected_route": "metric_clarification",
        },
        {
            "source_scenario_id": "H003",
            "page": "Reflection",
            "student_query": "What does Total_chars mean?",
            "scenario_group": "metric_clarification",
            "expected_route": "metric_clarification",
        },
        {
            "source_scenario_id": "H004",
            "page": "Resources",
            "student_query": "What does Resources_views mean?",
            "scenario_group": "metric_clarification",
            "expected_route": "metric_clarification",
        },
        {
            "source_scenario_id": "H005",
            "page": "Debate",
            "student_query": "What does the reply network show?",
            "scenario_group": "metric_clarification",
            "expected_route": "metric_clarification",
        },
        {
            "source_scenario_id": "H006",
            "page": "Debate",
            "student_query": "How does debate relate to reflection?",
            "scenario_group": "cross_page_evidence_synthesis",
            "expected_route": "cross_page_evidence_synthesis",
        },
        {
            "source_scenario_id": "H007",
            "page": "Resources",
            "student_query": "How do my resource views and lecture viewing relate?",
            "scenario_group": "cross_page_evidence_synthesis",
            "expected_route": "cross_page_evidence_synthesis",
        },
        {
            "source_scenario_id": "H008",
            "page": "Lecture",
            "student_query": "How do lecture videos connect to debate preparation?",
            "scenario_group": "cross_page_evidence_synthesis",
            "expected_route": "cross_page_evidence_synthesis",
        },
        {
            "source_scenario_id": "H009",
            "page": "Reflection",
            "student_query": "Does my reflection activity relate to resources?",
            "scenario_group": "cross_page_evidence_synthesis",
            "expected_route": "cross_page_evidence_synthesis",
        },
        {
            "source_scenario_id": "H010",
            "page": "Overview",
            "student_query": "How do my overall resource, lecture, debate and reflection patterns fit together?",
            "scenario_group": "cross_page_evidence_synthesis",
            "expected_route": "cross_page_evidence_synthesis",
        },
        {
            "source_scenario_id": "H011",
            "page": "Lecture",
            "student_query": "Can you explain the second point using W4 lecture guidance?",
            "conversation_history": [
                {"role": "assistant", "content": "1. Revisit W4 lecture.\n2. Connect one lecture idea to your reflection.\n3. Ask one question in debate."}
            ],
            "scenario_group": "hybrid_memory_and_retrieval",
            "expected_memory": True,
            "expected_memory_items": ["2"],
            "expected_retrieval": True,
            "expected_sources": ["course_metadata", "Module Weekly Pages"],
            "expected_topics": ["W4", "Learning Analytics", "reflection"],
        },
        {
            "source_scenario_id": "H012",
            "page": "Debate",
            "student_query": "Based on my debate data and this week's debate task, what should I do next?",
            "scenario_group": "hybrid_evidence_and_retrieval",
            "expected_retrieval": True,
            "expected_sources": ["Module Weekly Pages"],
            "expected_topics": ["debate", "forum"],
        },
        {
            "source_scenario_id": "H013",
            "page": "Reflection",
            "student_query": "What about the second step for Part A?",
            "conversation_history": [
                {"role": "assistant", "content": "1. Choose one weekly activity.\n2. Link it to the Part A reflection guidance.\n3. Write one next-step plan."}
            ],
            "scenario_group": "hybrid_memory_and_retrieval",
            "expected_memory": True,
            "expected_memory_items": ["2"],
            "expected_retrieval": True,
            "expected_sources": ["Module Handbook"],
            "expected_topics": ["Part A", "reflection"],
        },
        {
            "source_scenario_id": "H014",
            "page": "Resources",
            "student_query": "What is my most active resource day?",
            "scenario_group": "negative_control",
            "expected_route": "dashboard_interpretation",
            "expected_retrieval": False,
            "expected_memory": False,
        },
        {
            "source_scenario_id": "H015",
            "page": "Debate",
            "student_query": "Can you explain this point?",
            "conversation_history": [
                {"role": "assistant", "content": "1. Choose one debate post you already viewed."}
            ],
            "scenario_group": "memory_follow_up",
            "expected_memory": True,
            "expected_memory_items": ["1"],
            "expected_topics": ["debate post"],
        },
    ]


def validate_unified_scenarios(rows: list[dict[str, Any]]) -> None:
    """Validate the generated scenario file before writing."""

    ids = [row["scenario_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Unified scenario IDs are not unique.")
    required = {
        "scenario_id",
        "source_dataset",
        "source_scenario_id",
        "page",
        "student_id",
        "student_query",
        "conversation_history",
        "scenario_group",
        "required_capabilities",
        "expected_route",
        "expected_retrieval",
        "expected_memory",
        "expected_memory_items",
        "expected_sources",
        "expected_topics",
        "applicable_judge_dimensions",
        "notes",
    }
    valid_dims = set(CORE_DIMENSIONS + ["actionability", "memory_followup_accuracy", "retrieval_grounding", "course_context_use"])
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"{row.get('scenario_id')} missing fields: {sorted(missing)}")
        if not row["required_capabilities"]:
            raise ValueError(f"{row['scenario_id']} has no required capabilities.")
        if row["scenario_group"] == "negative_control":
            if row.get("expected_memory"):
                raise ValueError(f"{row['scenario_id']} negative_control cannot expect memory.")
            if row.get("expected_retrieval"):
                raise ValueError(f"{row['scenario_id']} negative_control cannot expect retrieval.")
            forbidden = {"short_term_memory", "course_material_retrieval"} & set(row["required_capabilities"])
            if forbidden:
                raise ValueError(
                    f"{row['scenario_id']} negative_control has forbidden capabilities: {sorted(forbidden)}"
                )
        invalid_dims = set(row["applicable_judge_dimensions"]) - valid_dims
        if invalid_dims:
            raise ValueError(f"{row['scenario_id']} has invalid judge dimensions: {sorted(invalid_dims)}")
        if set(row.get("gold_applicable_quality_dimensions", [])) - set(QUALITY_DIMENSIONS):
            raise ValueError(f"{row['scenario_id']} has invalid frozen quality applicability")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def main() -> None:
    rows = build_unified_scenarios()
    write_jsonl(rows, OUTPUT)
    print(f"Built {len(rows)} unified benchmark scenarios.")
    print(f"Saved: {OUTPUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
