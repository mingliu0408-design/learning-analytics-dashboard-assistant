"""Frozen contracts shared by the final unified evaluation layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
SCENARIOS_PATH = EVALUATION_DIR / "unified_benchmark_scenarios.jsonl"
GOLD_LABELS_PATH = EVALUATION_DIR / "unified_benchmark_gold_labels.jsonl"
REFERENCE_EVIDENCE_PATH = EVALUATION_DIR / "unified_reference_evidence_v1.jsonl"
EXPECTED_MODES = ["A", "B", "C", "CM", "CR", "C_FULL"]
EXPECTED_SCENARIO_COUNT = 62
EXPECTED_RECORD_COUNT = EXPECTED_SCENARIO_COUNT * len(EXPECTED_MODES)
FROZEN_RESPONSES_SHA256 = "c86d00089f4671477ebb6c20e18306e763e3d5b10d5dd16766614bf46adcf014"
GOLD_LABEL_VERSION = "unified-gold-v1.0"
QUALITY_RUBRIC_VERSION = "unified-quality-v1.1"
MECHANISM_RUBRIC_VERSION = "unified-mechanism-v1.0"
MECHANISM_RUBRIC_VERSION_V2 = "unified-mechanism-v2"
REFERENCE_EVIDENCE_VERSION = "unified-reference-evidence-v1.0"
JUDGE_PROMPT_VERSION = "blind-quality-v1.2"

QUALITY_DIMENSIONS = [
    "response_relevance",
    "evidence_integration",
    "context_awareness",
    "personalisation",
    "actionability",
    "explanatory_quality",
    "epistemic_calibration",
    "unsupported_claims_risk",
]
RISK_DIMENSION = "unsupported_claims_risk"
MECHANISM_DIMENSIONS = [
    "route_correctness",
    "memory_activation_correctness",
    "memory_resolution_accuracy",
    "retrieval_activation_correctness",
    "retrieval_grounding",
    "course_context_use",
    "negative_control_correctness",
    "plan_state_consistency",
    "metric_definition_guard_correctness",
]
SCENARIO_GROUPS = {
    "dashboard_interpretation",
    "metric_clarification",
    "technical_access_or_discrepancy",
    "recommendation_planning",
    "memory_follow_up",
    "negative_control",
    "course_material_retrieval",
    "cross_page_evidence_synthesis",
    "hybrid_memory_and_retrieval",
    "hybrid_evidence_and_retrieval",
}
QUERY_TYPES = {
    "access_or_capability_question",
    "course_content_question",
    "cross_page_relationship",
    "dashboard_interpretation",
    "discrepancy_or_correction",
    "emotional_or_justification",
    "improvement_recommendation",
    "metric_clarification",
    "planning_or_strategy",
    "reflection_structure_question",
    "technical_data_question",
}
EXPECTED_ROUTES = {
    "course_material_retrieval",
    "cross_page_evidence_synthesis",
    "dashboard_interpretation",
    "direct_technical_access_or_discrepancy",
    "hybrid_evidence_and_retrieval",
    "hybrid_memory_and_retrieval",
    "memory_follow_up",
    "metric_clarification",
    "recommendation_planning",
}
CAPABILITIES = {
    "course_material_retrieval",
    "dashboard_evidence",
    "hybrid",
    "recommendation_planning",
    "short_term_memory",
    "technical_access_handling",
}


class EvaluationValidationError(ValueError):
    """A blocking evaluation-integrity or judge-output error."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationValidationError("malformed_json", f"{path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise EvaluationValidationError("invalid_record_type", f"{path}:{line_number} must be an object")
            rows.append(value)
    return rows


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows_by_id(rows: Iterable[Mapping[str, Any]], field: str = "scenario_id") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(field, ""))
        if not key:
            raise EvaluationValidationError("missing_key", f"Missing {field}")
        if key in out:
            raise EvaluationValidationError("duplicate_key", f"Duplicate {field}: {key}")
        out[key] = dict(row)
    return out


def load_gold_overlay(path: Path = GOLD_LABELS_PATH) -> dict[str, dict[str, Any]]:
    return rows_by_id(load_jsonl(path))


def aligned_quality_score(scores: Mapping[str, int | None]) -> float | None:
    values: list[float] = []
    for dimension in QUALITY_DIMENSIONS:
        value = scores.get(dimension)
        if value is None:
            continue
        values.append(float(6 - value if dimension == RISK_DIMENSION else value))
    return round(sum(values) / len(values), 3) if values else None


def mechanism_score(scores: Mapping[str, int | None]) -> float | None:
    values = [float(scores[dimension]) for dimension in MECHANISM_DIMENSIONS if scores.get(dimension) is not None]
    return round(sum(values) / len(values), 3) if values else None


def validate_dimension_payload(
    payload: Any,
    applicable_dimensions: Iterable[str],
    dimensions: list[str],
) -> tuple[dict[str, int | None], dict[str, str | None]]:
    if not isinstance(payload, dict):
        raise EvaluationValidationError("invalid_top_level", "Judge output must be a JSON object")
    if set(payload) != {"scores", "rationales"}:
        raise EvaluationValidationError("invalid_top_level_fields", "Judge output must contain only scores and rationales")
    scores = payload.get("scores")
    rationales = payload.get("rationales")
    if not isinstance(scores, dict) or not isinstance(rationales, dict):
        raise EvaluationValidationError("invalid_dimension_container", "scores and rationales must be objects")
    if set(scores) != set(dimensions) or set(rationales) != set(dimensions):
        raise EvaluationValidationError("invalid_dimension_fields", "All and only declared dimensions are required")
    applicable = set(applicable_dimensions)
    if not applicable <= set(dimensions):
        raise EvaluationValidationError("unknown_applicable_dimension", f"Unknown dimensions: {sorted(applicable - set(dimensions))}")
    validated_scores: dict[str, int | None] = {}
    validated_rationales: dict[str, str | None] = {}
    for dimension in dimensions:
        score = scores[dimension]
        rationale = rationales[dimension]
        if dimension in applicable:
            if isinstance(score, bool) or type(score) is not int:
                raise EvaluationValidationError("invalid_score_type", f"{dimension} must be an integer")
            if not 1 <= score <= 5:
                raise EvaluationValidationError("score_out_of_range", f"{dimension} must be between 1 and 5")
            if not isinstance(rationale, str) or not rationale.strip():
                raise EvaluationValidationError("missing_rationale", f"{dimension} requires a non-empty rationale")
            validated_scores[dimension] = score
            validated_rationales[dimension] = rationale.strip()
        else:
            if score is not None:
                raise EvaluationValidationError("non_applicable_score_not_null", f"{dimension} must be null")
            if rationale is not None and (not isinstance(rationale, str) or not rationale.strip()):
                raise EvaluationValidationError("invalid_non_applicable_rationale", f"{dimension} rationale must be null or non-empty")
            validated_scores[dimension] = None
            validated_rationales[dimension] = rationale.strip() if isinstance(rationale, str) else None
    return validated_scores, validated_rationales
