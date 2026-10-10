"""Shared helpers for offline evaluation analysis scripts.

The functions here intentionally operate only on saved evaluation artefacts.
They do not call the Streamlit app and they do not generate new assistant
responses.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "outputs"
SCENARIOS_PATH = PROJECT_ROOT / "evaluation" / "scenarios.jsonl"

RESPONSE_SET_LABELS = {
    "deterministic": "Deterministic/template",
    "llm": "LLM-generated",
}
RESPONSE_SET_SUFFIX = {
    "deterministic": "",
    "llm": "_llm_generated",
}

JUDGE_SCORE_FILES = {
    "deterministic": OUTPUT_DIR / "llm_judge_scores.jsonl",
    "llm": OUTPUT_DIR / "llm_judge_scores_llm_generated.jsonl",
}
AUTOMATIC_METRICS_FILES = {
    "deterministic": OUTPUT_DIR / "automatic_metrics.csv",
    "llm": OUTPUT_DIR / "automatic_metrics_llm_generated.csv",
}
RESPONSE_FILES = {
    "deterministic": {
        "A": OUTPUT_DIR / "responses_mode_a.jsonl",
        "B": OUTPUT_DIR / "responses_mode_b.jsonl",
        "C": OUTPUT_DIR / "responses_mode_c.jsonl",
    },
    "llm": {
        "A": OUTPUT_DIR / "responses_mode_a_llm.jsonl",
        "B": OUTPUT_DIR / "responses_mode_b_llm.jsonl",
        "C": OUTPUT_DIR / "responses_mode_c_llm.jsonl",
    },
}

MODE_ORDER = ["A", "B", "C"]
POSITIVE_DIMENSIONS = [
    "response_relevance",
    "evidence_integration",
    "context_awareness",
    "personalisation",
    "actionability",
    "explanatory_quality",
    "uncertainty_handling",
]
RISK_DIMENSION = "unsupported_claims_risk"
ALL_SCORE_DIMENSIONS = POSITIVE_DIMENSIONS + [RISK_DIMENSION]
AGGREGATE_DIMENSIONS = ["overall_positive_mean", "overall_applicable_mean"]

ACTIONABILITY_APPLICABLE_QUERY_TYPES = {
    "improvement_recommendation",
    "planning_or_strategy",
    "reflection_structure_question",
}
ACTIONABILITY_APPLICABLE_ROUTES = {
    "overview_planning",
    "overview_recommendation",
    "rq2_recommendation",
    "reflection_structure",
    "reflection_structure_question",
}
TECHNICAL_OR_FACTUAL_QUERY_TYPES = {
    "technical_data_question",
    "access_or_capability_question",
    "course_content_question",
    "discrepancy_or_correction",
    "metric_clarification",
}

AUTOMATIC_METRIC_COLUMNS = [
    "response_length_words",
    "number_of_action_steps",
    "number_of_dashboard_evidence_mentions",
    "number_of_generic_phrases",
    "has_uncertainty_statement",
    "simple_overlap_with_evidence",
    "has_internal_error_message",
    "answers_question_heuristic",
]


def display_path(path: Path) -> str:
    """Return a readable path for console output."""

    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def output_path(base_name: str, response_set: str, extension: str = ".csv") -> Path:
    """Build an output path with the response-set suffix."""

    suffix = RESPONSE_SET_SUFFIX[response_set]
    return OUTPUT_DIR / f"{base_name}{suffix}{extension}"


def existing_response_sets(kind: str = "judge") -> list[str]:
    """Return response sets that have the requested saved artefacts."""

    if kind == "judge":
        paths = JUDGE_SCORE_FILES
    elif kind == "metrics":
        paths = AUTOMATIC_METRICS_FILES
    elif kind == "responses":
        return [
            response_set
            for response_set, files in RESPONSE_FILES.items()
            if all(path.exists() for path in files.values())
        ]
    else:
        raise ValueError(f"Unsupported artefact kind: {kind}")
    return [response_set for response_set, path in paths.items() if path.exists()]


def preferred_response_set() -> str:
    """Return the preferred main result set for dissertation tables."""

    if JUDGE_SCORE_FILES["llm"].exists():
        return "llm"
    return "deterministic"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON records with a clear error message."""

    if not path.exists():
        raise FileNotFoundError(f"Missing file: {display_path(path)}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {display_path(path)} line {line_no}: {exc}") from exc
    return records


def write_jsonl(records: Iterable[Mapping[str, Any]], path: Path) -> None:
    """Write newline-delimited JSON records."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(dict(record), ensure_ascii=False) + "\n")


def load_scenarios() -> pd.DataFrame:
    """Load replay scenarios as a dataframe."""

    return pd.DataFrame(load_jsonl(SCENARIOS_PATH))


def load_judge_scores(response_set: str) -> pd.DataFrame:
    """Load and flatten judge scores for one response set."""

    path = JUDGE_SCORE_FILES[response_set]
    records = load_jsonl(path)
    rows = [flatten_judge_record(record, response_set) for record in records]
    return pd.DataFrame(rows)


def flatten_judge_record(record: Mapping[str, Any], response_set: str) -> dict[str, Any]:
    """Flatten one nested judge record and add aggregate scores."""

    scores = record.get("scores", {})
    row: dict[str, Any] = {
        "generation_type": response_set,
        "generation_label": RESPONSE_SET_LABELS[response_set],
        "scenario_id": str(record.get("scenario_id", "")),
        "mode": str(record.get("mode", "")).upper(),
        "page": record.get("page", ""),
        "query_type": record.get("query_type", ""),
        "selected_route": record.get("selected_route", ""),
        "brief_rationale": record.get("brief_rationale", ""),
    }
    for dimension in ALL_SCORE_DIMENSIONS:
        row[dimension] = score_or_none(scores.get(dimension))

    positive = [row[d] for d in POSITIVE_DIMENSIONS if row[d] is not None]
    row["overall_positive_mean"] = round(sum(positive) / len(positive), 3) if positive else None

    applicable = applicable_positive_dimensions(
        query_type=str(row["query_type"]),
        selected_route=str(row["selected_route"]),
    )
    applicable_values = [row[d] for d in applicable if row[d] is not None]
    row["overall_applicable_mean"] = (
        round(sum(applicable_values) / len(applicable_values), 3) if applicable_values else None
    )
    return row


def applicable_positive_dimensions(query_type: str, selected_route: str) -> list[str]:
    """Return dimensions included in the adjusted positive aggregate."""

    dimensions = [
        "response_relevance",
        "evidence_integration",
        "context_awareness",
        "personalisation",
        "explanatory_quality",
        "uncertainty_handling",
    ]
    if query_type in ACTIONABILITY_APPLICABLE_QUERY_TYPES or selected_route in ACTIONABILITY_APPLICABLE_ROUTES:
        dimensions.insert(4, "actionability")
    return dimensions


def score_or_none(value: Any) -> int | None:
    """Coerce a judge score to the 1-5 range or return None."""

    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(1, min(5, number))


def load_response_records(response_set: str) -> pd.DataFrame:
    """Load saved response records for A/B/C."""

    rows: list[dict[str, Any]] = []
    for mode, path in RESPONSE_FILES[response_set].items():
        for record in load_jsonl(path):
            item = dict(record)
            item["mode"] = str(item.get("mode") or mode).upper()
            item["generation_type"] = response_set
            item["generation_label"] = RESPONSE_SET_LABELS[response_set]
            rows.append(item)
    return pd.DataFrame(rows)


def order_modes(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a dataframe by generation type, mode, and scenario when present."""

    out = df.copy()
    if "mode" in out.columns:
        out["mode"] = pd.Categorical(out["mode"], categories=MODE_ORDER, ordered=True)
    sort_cols = [col for col in ["generation_type", "mode", "scenario_id"] if col in out.columns]
    return out.sort_values(sort_cols).reset_index(drop=True) if sort_cols else out
