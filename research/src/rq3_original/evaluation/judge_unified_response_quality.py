"""Blind visible-response quality judge for the final unified benchmark."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    EXPECTED_RECORD_COUNT,
    GOLD_LABELS_PATH,
    GOLD_LABEL_VERSION,
    JUDGE_PROMPT_VERSION,
    QUALITY_DIMENSIONS,
    QUALITY_RUBRIC_VERSION,
    REFERENCE_EVIDENCE_PATH,
    SCENARIOS_PATH,
    EvaluationValidationError,
    aligned_quality_score,
    canonical_sha256,
    file_sha256,
    load_gold_overlay,
    load_jsonl,
    rows_by_id,
    validate_dimension_payload,
)


RESPONSES = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_llm_responses_v1.jsonl"
OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2" / "unified_quality_judge_v1_1.jsonl"
EXPLORATORY_OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2" / "exploratory_quality_judge_v1_1.jsonl"
RAW_OUTPUT_LIMIT = 12000
ANCHORS = {
    "response_relevance": {
        "1": "Fails to answer the question or is mostly off-topic.",
        "3": "Answers the main question but misses an important part or adds substantial irrelevant content.",
        "5": "Directly and completely answers every explicit part without meaningful distraction.",
    },
    "evidence_integration": {
        "1": "Omits required evidence, uses incorrect evidence, or relies on irrelevant sources.",
        "3": "Uses some relevant evidence but connects it incompletely or adds unnecessary sources.",
        "5": "Accurately selects and integrates all necessary evidence without irrelevant material.",
    },
    "context_awareness": {
        "1": "Ignores or contradicts relevant history, corrections, references, or constraints.",
        "3": "Uses some context correctly but misses one important reference or constraint.",
        "5": "Consistently resolves all relevant context, corrections, pronouns, and constraints.",
    },
    "personalisation": {
        "1": "Gives generic advice despite required student-specific evidence.",
        "3": "Mentions student evidence but does not meaningfully adapt the answer.",
        "5": "Meaningfully adapts the answer using relevant student evidence and constraints.",
    },
    "actionability": {
        "1": "Offers vague encouragement with no executable next step.",
        "3": "Contains concrete steps that are weakly prioritised or insufficiently connected to the task.",
        "5": "Gives specific, feasible, ordered actions aligned with evidence and constraints.",
    },
    "explanatory_quality": {
        "1": "Provides unsupported conclusions or no explanation.",
        "3": "Partly explains the answer but leaves key reasoning unclear.",
        "5": "Clearly explains how the evidence supports the answer at an appropriate level of detail.",
    },
    "epistemic_calibration": {
        "1": "Overclaims certainty, invents unavailable information, or omits a necessary limitation.",
        "3": "Is mostly calibrated but mildly overstates or gives a vague limitation.",
        "5": "States conclusions and limitations precisely without unnecessary boilerplate.",
    },
    "unsupported_claims_risk": {
        "1": "All important factual or evidential claims are supported or clearly qualified.",
        "3": "Contains a minor unsupported inference that does not change the core answer.",
        "5": "Fabricates data, course content, Memory, findings, motivation, learning quality, or outcomes.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the blind unified response-quality judge.")
    parser.add_argument("--responses", type=Path, default=RESPONSES)
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_PATH)
    parser.add_argument("--gold-labels", type=Path, default=GOLD_LABELS_PATH)
    parser.add_argument("--reference-evidence", type=Path, default=REFERENCE_EVIDENCE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--model", default=os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"))
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scenario", action="append", default=[], help="Exploratory scenario ID; repeat for multiple IDs.")
    parser.add_argument("--max-records", type=int, default=None, help="Exploratory cap applied after scenario filtering.")
    parser.add_argument("--allow-partial", action="store_true", help="Permit a separate incomplete exploratory judge run.")
    writes = parser.add_mutually_exclusive_group()
    writes.add_argument("--resume", action="store_true")
    writes.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def build_blind_quality_payload(
    record: Mapping[str, Any], gold: Mapping[str, Any], reference: Mapping[str, Any]
) -> dict[str, Any]:
    applicable = list(gold.get("gold_applicable_quality_dimensions") or [])
    return {
        "scenario_id": record.get("scenario_id", ""),
        "student_query": reference.get("reference_student_query", ""),
        "conversation_history": reference.get("reference_conversation_history", []),
        "current_page": reference.get("reference_page", ""),
        "reference_dashboard_evidence": reference.get("reference_dashboard_evidence", {}),
        "reference_course_evidence": reference.get("reference_course_evidence", []),
        "final_assistant_response": record.get("response") or record.get("generated_response", ""),
        "applicable_quality_dimensions": applicable,
        "source_restrictions": reference.get("reference_source_restrictions", {}),
        "reference_evidence_notes": reference.get("reference_evidence_notes", ""),
        "neutral_task_intent": gold.get("gold_notes", ""),
    }


def build_blind_quality_prompt(
    record: Mapping[str, Any], gold: Mapping[str, Any], reference: Mapping[str, Any],
    *, applicable_only: bool = False, validation_feedback: str = "",
) -> str:
    payload = build_blind_quality_payload(record, gold, reference)
    applicable = list(gold.get("gold_applicable_quality_dimensions") or [])
    non_applicable = [dimension for dimension in QUALITY_DIMENSIONS if dimension not in applicable]
    example = build_quality_output_example(applicable, applicable_only=applicable_only)
    rules = [
        "Judge only the visible final answer against the supplied query, history, evidence, and restrictions.",
        "Do not infer or score implementation mechanisms; judge only the visible answer.",
        "For every applicable dimension return an integer 1-5 and a concise rationale citing a specific response passage and relevant evidence.",
        (
            "Return only applicable dimensions; program code will add nulls for non-applicable dimensions after strict validation."
            if applicable_only
            else "For every non-applicable dimension return null for both its score and rationale."
        ),
        "Higher is better except unsupported_claims_risk, where 1 is low risk and 5 is high risk.",
        "Unsupported-claims risk concerns factual or evidential claims, not stylistic wording.",
        "Each rationale must justify its numeric score using that dimension's 1/3/5 anchor.",
        "A score of 5 must not be paired with a material criticism that corresponds to the 1 or 3 anchor.",
        "If the response overstates, misses an important limitation, fails to resolve ambiguity, or only partially satisfies a dimension, that dimension cannot receive 5.",
        "When a query refers to numbered items that are absent from the supplied history, top context-awareness or epistemic-calibration requires explicitly acknowledging that the items cannot be resolved; clarification or a clearly labelled fresh provisional plan is acceptable, but silently inventing the original items is not.",
        "Return JSON only with exactly the fields shown in the example; do not add, omit, or rename fields.",
        "Before returning the JSON, verify that every rationale describes performance consistent with its numeric score. If the rationale identifies a material defect, do not assign 5.",
    ]
    repair = (
        "\n\nThe previous output failed validation. Correct the structure once using this error:\n"
        f"{validation_feedback}\n"
        if validation_feedback
        else ""
    )
    return (
        "Blindly evaluate the visible educational assistant response.\n\n"
        f"Dimension anchors (1/3/5):\n{json.dumps(ANCHORS, ensure_ascii=False, indent=2)}\n\n"
        f"Applicable dimensions (exact):\n{json.dumps(applicable, ensure_ascii=False)}\n\n"
        f"Non-applicable dimensions (exact):\n{json.dumps(non_applicable, ensure_ascii=False)}\n\n"
        "Required direction: unsupported_claims_risk uses 1 = low risk and 5 = high risk.\n\n"
        f"Exact JSON example for this scenario:\n{json.dumps(example, ensure_ascii=False, indent=2)}\n\n"
        f"Rules:\n{json.dumps(rules, ensure_ascii=False, indent=2)}\n\n"
        f"Evaluation input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        f"{repair}"
    )


def build_quality_output_example(applicable: list[str], *, applicable_only: bool = False) -> dict[str, Any]:
    fields = applicable if applicable_only else QUALITY_DIMENSIONS
    return {
        "scores": {dimension: (3 if dimension in applicable else None) for dimension in fields},
        "rationales": {
            dimension: ("Specific response-and-evidence rationale." if dimension in applicable else None)
            for dimension in fields
        },
    }


def build_quality_output_schema(applicable: list[str]) -> dict[str, Any]:
    """Return the per-scenario strict JSON Schema used by Structured Outputs."""

    applicable_set = set(applicable)
    score_properties = {
        dimension: (
            {"type": "integer", "minimum": 1, "maximum": 5}
            if dimension in applicable_set
            else {"type": "null"}
        )
        for dimension in QUALITY_DIMENSIONS
    }
    rationale_properties = {
        dimension: (
            {"type": "string", "minLength": 1}
            if dimension in applicable_set
            else {"type": "null"}
        )
        for dimension in QUALITY_DIMENSIONS
    }
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "properties": score_properties,
                "required": list(QUALITY_DIMENSIONS),
                "additionalProperties": False,
            },
            "rationales": {
                "type": "object",
                "properties": rationale_properties,
                "required": list(QUALITY_DIMENSIONS),
                "additionalProperties": False,
            },
        },
        "required": ["scores", "rationales"],
        "additionalProperties": False,
    }


class JudgeOutputValidationError(EvaluationValidationError):
    def __init__(self, error_type: str, message: str, raw_output: str) -> None:
        super().__init__(error_type, message)
        self.raw_output = raw_output[:RAW_OUTPUT_LIMIT]
        self.returned_score_fields: list[str] = []
        self.returned_rationale_fields: list[str] = []
        self.contract_mode = "unknown"
        self.schema_repair_attempted = False
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                if isinstance(parsed.get("scores"), dict):
                    self.returned_score_fields = sorted(map(str, parsed["scores"]))
                if isinstance(parsed.get("rationales"), dict):
                    self.returned_rationale_fields = sorted(map(str, parsed["rationales"]))
        except json.JSONDecodeError:
            pass


def _validate_applicable_only_payload(
    payload: Any, applicable: list[str]
) -> tuple[dict[str, int | None], dict[str, str | None]]:
    if not isinstance(payload, dict) or set(payload) != {"scores", "rationales"}:
        raise EvaluationValidationError("invalid_top_level_fields", "Fallback output must contain only scores and rationales")
    scores, rationales = payload.get("scores"), payload.get("rationales")
    if not isinstance(scores, dict) or not isinstance(rationales, dict):
        raise EvaluationValidationError("invalid_dimension_container", "scores and rationales must be objects")
    expected = set(applicable)
    if set(scores) != expected or set(rationales) != expected:
        raise EvaluationValidationError("invalid_dimension_fields", f"Fallback fields must equal applicable dimensions: {sorted(expected)}")
    expanded_scores: dict[str, int | None] = {}
    expanded_rationales: dict[str, str | None] = {}
    for dimension in QUALITY_DIMENSIONS:
        if dimension not in expected:
            expanded_scores[dimension] = None
            expanded_rationales[dimension] = None
            continue
        score, rationale = scores[dimension], rationales[dimension]
        if isinstance(score, bool) or type(score) is not int:
            raise EvaluationValidationError("invalid_score_type", f"{dimension} must be an integer")
        if not 1 <= score <= 5:
            raise EvaluationValidationError("score_out_of_range", f"{dimension} must be between 1 and 5")
        if not isinstance(rationale, str) or not rationale.strip():
            raise EvaluationValidationError("missing_rationale", f"{dimension} requires a non-empty rationale")
        expanded_scores[dimension] = score
        expanded_rationales[dimension] = rationale.strip()
    return expanded_scores, expanded_rationales


_TOP_SCORE_NEGATIVE_PATTERNS = (
    ("overstates", re.compile(r"\boverstates?\b", re.IGNORECASE)),
    ("fails to", re.compile(r"\bfails?\s+to\b", re.IGNORECASE)),
    ("does not clearly", re.compile(r"\bdoes\s+not\s+clearly\b", re.IGNORECASE)),
    ("misses an important", re.compile(r"\bmiss(?:es|ed)\s+an?\s+important\b", re.IGNORECASE)),
    ("only partially", re.compile(r"\bonly\s+partially\b", re.IGNORECASE)),
    ("not fully", re.compile(r"\bnot\s+fully\b", re.IGNORECASE)),
    ("unsupported inference", re.compile(r"\bunsupported\s+inferences?\b", re.IGNORECASE)),
    ("substantial irrelevant", re.compile(r"\bsubstantial(?:ly)?\s+irrelevant\b", re.IGNORECASE)),
)

_BENIGN_NEGATED_PATTERNS = (
    re.compile(r"\bdoes\s+not\s+overstate\b", re.IGNORECASE),
    re.compile(r"\bdoesn['’]?t\s+overstate\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+fabricate\b", re.IGNORECASE),
    re.compile(r"\bdoesn['’]?t\s+fabricate\b", re.IGNORECASE),
    re.compile(r"\b(?:there\s+(?:are|is)\s+)?no\s+unsupported\s+(?:claims?|inferences?)\b", re.IGNORECASE),
    re.compile(r"\b(?:contains?|makes?|offers?|includes?)\s+no\s+unsupported\s+(?:claims?|inferences?)\b", re.IGNORECASE),
    re.compile(r"\b(?:does\s+not|doesn['’]?t)\s+make\s+unsupported\s+inferences?\b", re.IGNORECASE),
    re.compile(r"\b(?:avoids?|without)\s+(?:any\s+)?unsupported\s+inferences?\b", re.IGNORECASE),
    re.compile(r"\b(?:does\s+not|doesn['’]?t)\s+miss\s+(?:any\s+)?(?:relevant|important)\s+context\b", re.IGNORECASE),
    re.compile(r"\b(?:does\s+not|doesn['’]?t)\s+fail\s+to\b", re.IGNORECASE),
    re.compile(r"\bno\s+substantial(?:ly)?\s+irrelevant\s+(?:content|material|detail|information)\b", re.IGNORECASE),
)


def validate_score_rationale_anchor_consistency(
    scores: Mapping[str, int | None], rationales: Mapping[str, str | None],
) -> None:
    """Reject only unambiguous top-score criticisms; risk uses the reverse direction."""

    contradictions: list[str] = []
    for dimension in QUALITY_DIMENSIONS:
        if dimension == "unsupported_claims_risk" or scores.get(dimension) != 5:
            continue
        rationale = str(rationales.get(dimension) or "")
        searchable = rationale
        for benign in _BENIGN_NEGATED_PATTERNS:
            searchable = benign.sub(" ", searchable)
        for label, pattern in _TOP_SCORE_NEGATIVE_PATTERNS:
            if pattern.search(searchable):
                contradictions.append(f"{dimension}: {label}")
                break
    if contradictions:
        raise EvaluationValidationError(
            "score_rationale_anchor_mismatch",
            "Score 5 conflicts with a material criticism in the rationale: " + "; ".join(contradictions),
        )


def _unresolved_numbered_reference(reference: Mapping[str, Any]) -> tuple[int, ...]:
    query = str(reference.get("reference_student_query", ""))
    match = re.search(
        r"\b(?:items?|steps?|points?)\s*(\d+)\s*(?:and|&|,)\s*(\d+)\b"
        r"|\bdo\s+(\d+)\s*(?:and|&|,)\s*(\d+)\b",
        query,
        flags=re.IGNORECASE,
    )
    if not match:
        return ()
    numbers = tuple(int(value) for value in match.groups() if value is not None)
    history = "\n".join(
        str(item.get("content", "")) if isinstance(item, Mapping) else str(item)
        for item in (reference.get("reference_conversation_history") or [])
    )
    defined = all(
        re.search(rf"(?:^|\n)\s*{number}\s*[.)]\s*\S|\b(?:item|step|point)\s*{number}\b", history, re.IGNORECASE)
        for number in numbers
    )
    return () if defined else numbers


def _acknowledges_missing_numbered_reference(response: str) -> bool:
    patterns = (
        r"\b(?:do\s+not|don['’]?t|cannot|can['’]?t)\s+(?:have|see|know|identify|resolve|determine|tell)\b",
        r"\b(?:history|conversation|context)\b.{0,45}\b(?:does\s+not|doesn['’]?t|lacks?|contains?\s+no|has\s+no)\b",
        r"\b(?:not\s+clear|not\s+sure|unclear)\b.{0,55}\b(?:item|step|point|refer)\w*\b",
        r"\b(?:could|can|would)\s+you\b.{0,35}\b(?:share|paste|provide|clarify)\b",
        r"\bplease\b.{0,25}\b(?:share|paste|provide|clarify)\b",
    )
    return any(re.search(pattern, response, re.IGNORECASE) for pattern in patterns)


def validate_unresolved_numbered_reference_scores(
    scores: Mapping[str, int | None], record: Mapping[str, Any], reference: Mapping[str, Any],
) -> None:
    """Prevent silent invention from receiving top context/calibration scores."""

    numbers = _unresolved_numbered_reference(reference)
    if not numbers:
        return
    response = str(record.get("response") or record.get("generated_response") or "")
    top_dimensions = [
        dimension for dimension in ("context_awareness", "epistemic_calibration")
        if scores.get(dimension) == 5
    ]
    if top_dimensions and not _acknowledges_missing_numbered_reference(response):
        raise EvaluationValidationError(
            "unresolved_numbered_reference_top_score",
            f"Top score requires explicitly acknowledging unresolved numbered items {list(numbers)}: {top_dimensions}",
        )


def parse_and_validate_quality_output(
    content: str, applicable: list[str], *, applicable_only: bool = False,
    record: Mapping[str, Any] | None = None, reference: Mapping[str, Any] | None = None,
) -> tuple[dict[str, int | None], dict[str, str | None]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise JudgeOutputValidationError("malformed_json", str(exc), content) from exc
    try:
        scores, rationales = (
            _validate_applicable_only_payload(payload, applicable)
            if applicable_only
            else validate_dimension_payload(payload, applicable, QUALITY_DIMENSIONS)
        )
        validate_score_rationale_anchor_consistency(scores, rationales)
        if record is not None and reference is not None:
            validate_unresolved_numbered_reference_scores(scores, record, reference)
        return scores, rationales
    except EvaluationValidationError as exc:
        raise JudgeOutputValidationError(exc.error_type, str(exc), content) from exc


def _strict_schema_response_format(applicable: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "blind_quality_judgement",
            "strict": True,
            "schema": build_quality_output_schema(applicable),
        },
    }


def _strict_schema_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, TypeError) or (
        any(token in message for token in ("json_schema", "structured output", "response_format"))
        and any(token in message for token in ("unsupported", "not support", "unknown", "invalid"))
    )


def _request_judge_output(
    client: Any, model: str, record: Mapping[str, Any], gold: Mapping[str, Any],
    reference: Mapping[str, Any], temperature: float, timeout: float,
    *, applicable_only: bool, validation_feedback: str = "",
) -> str:
    applicable = list(gold.get("gold_applicable_quality_dimensions") or [])
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict blind response-quality judge. Return JSON only."},
            {
                "role": "user",
                "content": build_blind_quality_prompt(
                    record, gold, reference,
                    applicable_only=applicable_only,
                    validation_feedback=validation_feedback,
                ),
            },
        ],
        temperature=temperature,
        response_format=(
            {"type": "json_object"}
            if applicable_only
            else _strict_schema_response_format(applicable)
        ),
        timeout=timeout,
    )
    return completion.choices[0].message.content or ""


def judge_openai(
    client: Any,
    model: str,
    record: Mapping[str, Any],
    gold: Mapping[str, Any],
    reference: Mapping[str, Any],
    temperature: float,
    timeout: float,
) -> tuple[dict[str, int | None], dict[str, str | None], str, str, bool, str | None]:
    applicable = list(gold.get("gold_applicable_quality_dimensions") or [])
    applicable_only = False
    contract_mode = "strict_json_schema"
    try:
        raw = _request_judge_output(
            client, model, record, gold, reference, temperature, timeout,
            applicable_only=False,
        )
    except Exception as exc:
        if not _strict_schema_unavailable(exc):
            raise
        print(f"Strict Structured Outputs unavailable; using applicable-only fallback: {exc}")
        applicable_only = True
        contract_mode = "applicable_only_fallback"
        raw = _request_judge_output(
            client, model, record, gold, reference, temperature, timeout,
            applicable_only=True,
        )
    try:
        scores, rationales = parse_and_validate_quality_output(
            raw, applicable, applicable_only=applicable_only, record=record, reference=reference,
        )
        return scores, rationales, raw, contract_mode, False, None
    except JudgeOutputValidationError as exc:
        print(f"Judge output validation failed ({exc.error_type}); making one explicit repair attempt.")
        feedback = f"{exc.error_type}: {exc}. Required fields/example are shown above."
        repaired_raw = _request_judge_output(
            client, model, record, gold, reference, temperature, timeout,
            applicable_only=applicable_only,
            validation_feedback=feedback,
        )
        try:
            scores, rationales = parse_and_validate_quality_output(
                repaired_raw, applicable, applicable_only=applicable_only, record=record, reference=reference,
            )
        except JudgeOutputValidationError as final_exc:
            final_exc.contract_mode = contract_mode
            final_exc.schema_repair_attempted = True
            raise
        return scores, rationales, repaired_raw, contract_mode, True, exc.error_type


def dry_run_scores(applicable: list[str]) -> tuple[dict[str, int | None], dict[str, str | None]]:
    scores = {dimension: (3 if dimension in applicable else None) for dimension in QUALITY_DIMENSIONS}
    rationales = {
        dimension: ("Local schema-validation placeholder citing the supplied response." if dimension in applicable else None)
        for dimension in QUALITY_DIMENSIONS
    }
    return scores, rationales


def run_metadata(
    *, model: str, temperature: float, responses_path: Path, scenarios_path: Path, gold_path: Path,
    reference_path: Path, timeout: float = 60.0, max_retries: int = 3, retry_sleep: float = 5.0,
    run_scope: str = "formal_complete", selected_record_count: int = EXPECTED_RECORD_COUNT,
) -> dict[str, Any]:
    config = {
        "judge_model": model,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "quality_rubric_version": QUALITY_RUBRIC_VERSION,
        "gold_label_version": GOLD_LABEL_VERSION,
        "judge_temperature": temperature,
        "judge_timeout": timeout,
        "judge_max_retries": max_retries,
        "judge_retry_sleep": retry_sleep,
        "judge_run_scope": run_scope,
        "selected_record_count": selected_record_count,
        "formal_expected_record_count": EXPECTED_RECORD_COUNT,
    }
    return {
        **config,
        "responses_file_sha256": file_sha256(responses_path),
        "scenario_set_sha256": file_sha256(scenarios_path),
        "gold_labels_sha256": file_sha256(gold_path),
        "reference_evidence_sha256": file_sha256(reference_path),
        "judge_configuration_sha256": canonical_sha256(config),
    }


def output_record(
    record: Mapping[str, Any], gold: Mapping[str, Any], scores: Mapping[str, int | None],
    rationales: Mapping[str, str | None], metadata: Mapping[str, Any], attempts: int,
    *, contract_mode: str = "deterministic_dry_run", schema_repair_attempted: bool = False,
    validation_error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "scenario_id": record.get("scenario_id", ""),
        "mode": record.get("mode", ""),
        "scenario_group": gold.get("gold_scenario_group", ""),
        "applicable_dimensions": list(gold.get("gold_applicable_quality_dimensions") or []),
        "scores": dict(scores),
        "rationales": dict(rationales),
        "quality_score": aligned_quality_score(scores),
        "judge_failed": False,
        "validation_error_type": validation_error_type,
        "error_message": "",
        "attempts": attempts,
        "judge_contract_mode": contract_mode,
        "schema_repair_attempted": schema_repair_attempted,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }


def failure_record(
    record: Mapping[str, Any], gold: Mapping[str, Any], metadata: Mapping[str, Any],
    attempts: int, error_type: str, message: str, *, raw_output: str = "",
    returned_score_fields: list[str] | None = None,
    returned_rationale_fields: list[str] | None = None,
    contract_mode: str = "unknown", schema_repair_attempted: bool = False,
) -> dict[str, Any]:
    applicable = list(gold.get("gold_applicable_quality_dimensions") or [])
    non_applicable = [dimension for dimension in QUALITY_DIMENSIONS if dimension not in applicable]
    return {
        "scenario_id": record.get("scenario_id", ""),
        "mode": record.get("mode", ""),
        "scenario_group": gold.get("gold_scenario_group", ""),
        "applicable_dimensions": list(gold.get("gold_applicable_quality_dimensions") or []),
        "scores": {dimension: None for dimension in QUALITY_DIMENSIONS},
        "rationales": {dimension: None for dimension in QUALITY_DIMENSIONS},
        "quality_score": None,
        "judge_failed": True,
        "validation_error_type": error_type,
        "validation_error_message": message[:1000],
        "error_message": message[:1000],
        "raw_judge_output": raw_output[:RAW_OUTPUT_LIMIT],
        "returned_score_fields": returned_score_fields or [],
        "returned_rationale_fields": returned_rationale_fields or [],
        "expected_applicable_dimensions": applicable,
        "expected_non_applicable_dimensions": non_applicable,
        "attempts": attempts,
        "judge_contract_mode": contract_mode,
        "schema_repair_attempted": schema_repair_attempted,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }


def judge_with_retries(
    *, client: Any, model: str, record: Mapping[str, Any], gold: Mapping[str, Any],
    reference: Mapping[str, Any],
    metadata: Mapping[str, Any], temperature: float, timeout: float, max_retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    attempts = max(1, max_retries + 1)
    last_error: Exception | None = None
    contract_mode = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            scores, rationales, _, contract_mode, repaired, repaired_error_type = judge_openai(
                client, model, record, gold, reference, temperature, timeout
            )
            return output_record(
                record, gold, scores, rationales, metadata, attempt,
                contract_mode=contract_mode, schema_repair_attempted=repaired,
                validation_error_type=repaired_error_type,
            )
        except JudgeOutputValidationError as exc:
            return failure_record(
                record, gold, metadata, attempt, exc.error_type, str(exc),
                raw_output=exc.raw_output,
                returned_score_fields=exc.returned_score_fields,
                returned_rationale_fields=exc.returned_rationale_fields,
                contract_mode=exc.contract_mode,
                schema_repair_attempted=exc.schema_repair_attempted,
            )
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                print(
                    f"Network/API retry {attempt}/{attempts - 1} for "
                    f"{record.get('scenario_id')} mode={record.get('mode')}: {type(exc).__name__}: {exc}"
                )
                time.sleep(max(0.0, retry_sleep))
    error_type = last_error.error_type if isinstance(last_error, EvaluationValidationError) else type(last_error).__name__
    return failure_record(
        record, gold, metadata, attempts, error_type, str(last_error or "Unknown judge error"),
        contract_mode=contract_mode,
    )


def validate_resume(rows: list[dict[str, Any]], expected_keys: set[tuple[str, str]], metadata: Mapping[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    metadata_fields = set(metadata)
    for index, row in enumerate(rows, start=1):
        key = (str(row.get("scenario_id", "")), str(row.get("mode", "")))
        if key in keys:
            raise EvaluationValidationError("duplicate_key", f"Duplicate quality-judge key at record {index}: {key}")
        if key not in expected_keys:
            raise EvaluationValidationError("unknown_key", f"Unexpected quality-judge key: {key}")
        for field in metadata_fields:
            if row.get(field) != metadata.get(field):
                raise EvaluationValidationError("resume_metadata_mismatch", f"{field} mismatch for {key}")
        keys.add(key)
    return keys


def initialise_openai_client() -> Any:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. No judge calls were made.")
    from openai import OpenAI
    return OpenAI()


def append_checkpoint(handle: Any, row: Mapping[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def select_records_for_scope(
    all_records: list[dict[str, Any]], scenario_ids: list[str], max_records: int | None,
    allow_partial: bool,
) -> tuple[list[dict[str, Any]], str]:
    requested = {str(value) for value in scenario_ids}
    records = [
        record for record in all_records
        if not requested or str(record.get("scenario_id", "")) in requested
    ]
    if requested:
        found = {str(record.get("scenario_id", "")) for record in records}
        missing = requested - found
        if missing:
            raise EvaluationValidationError("unknown_partial_scenario", f"Unknown scenario IDs: {sorted(missing)}")
    if max_records is not None:
        if max_records < 1:
            raise EvaluationValidationError("invalid_max_records", "--max-records must be positive")
        records = records[:max_records]
    partial_requested = bool(requested or max_records is not None or len(records) != EXPECTED_RECORD_COUNT)
    if partial_requested and not allow_partial:
        raise EvaluationValidationError(
            "incomplete_response_file" if not requested and max_records is None else "partial_run_not_enabled",
            f"Formal quality judging requires {EXPECTED_RECORD_COUNT} records; use --allow-partial only for exploratory runs",
        )
    return records, "exploratory_partial" if allow_partial else "formal_complete"


def run_quality_judge(
    *, records: list[dict[str, Any]], gold: Mapping[str, Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]], output_path: Path,
    metadata: Mapping[str, Any], model: str, temperature: float, timeout: float,
    max_retries: int, retry_sleep: float, resume: bool, overwrite: bool,
    dry_run: bool, client: Any = None,
) -> list[dict[str, Any]]:
    expected_keys = {(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in records}
    if len(expected_keys) != len(records):
        raise EvaluationValidationError("duplicate_response_key", "Response file contains duplicate scenario-mode keys")
    existing: list[dict[str, Any]] = []
    if output_path.exists():
        if overwrite:
            output_path.unlink()
        elif resume:
            existing = load_jsonl(output_path)
        else:
            raise FileExistsError(f"Output exists: {output_path}; use --resume or --overwrite")
    completed = validate_resume(existing, expected_keys, metadata) if existing else set()
    if not dry_run and client is None and len(completed) < len(records):
        client = initialise_openai_client()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(existing)
    total = len(records)
    with output_path.open("a", encoding="utf-8") as handle:
        for record in records:
            key = (str(record.get("scenario_id", "")), str(record.get("mode", "")))
            if key in completed:
                continue
            label = gold.get(key[0])
            if not label:
                raise EvaluationValidationError("missing_gold_label", key[0])
            reference = references.get(key[0])
            if not reference:
                raise EvaluationValidationError("missing_reference_evidence", key[0])
            if dry_run:
                scores, rationales = dry_run_scores(list(label.get("gold_applicable_quality_dimensions") or []))
                judged = output_record(record, label, scores, rationales, metadata, 0)
            else:
                judged = judge_with_retries(
                    client=client, model=model, record=record, gold=label, reference=reference, metadata=metadata,
                    temperature=temperature, timeout=timeout, max_retries=max_retries,
                    retry_sleep=retry_sleep,
                )
            append_checkpoint(handle, judged)
            rows.append(judged)
            completed.add(key)
            print(
                f"Judged {len(completed)}/{total}: {key[0]} mode={key[1]} "
                f"({'failed' if judged.get('judge_failed') else 'completed'})"
            )
    if len(completed) != len(expected_keys) or len(rows) != len(expected_keys):
        raise EvaluationValidationError("incomplete_judge_run", f"Expected {len(expected_keys)} unique records, got {len(completed)}")
    if any(row.get("judge_failed") for row in rows):
        raise EvaluationValidationError("judge_failures_present", "One or more quality judgements failed strict validation")
    return rows


def main() -> None:
    args = parse_args()
    responses_path, scenarios_path, gold_path, reference_path, output_path = map(
        lambda path: path if path.is_absolute() else PROJECT_ROOT / path,
        (args.responses, args.scenarios, args.gold_labels, args.reference_evidence, args.output),
    )
    records, run_scope = select_records_for_scope(
        load_jsonl(responses_path), args.scenario, args.max_records, args.allow_partial
    )
    if args.allow_partial and output_path == OUTPUT:
        output_path = EXPLORATORY_OUTPUT
    metadata = run_metadata(
        model="dry_run_deterministic" if args.dry_run else args.model,
        temperature=args.temperature,
        responses_path=responses_path,
        scenarios_path=scenarios_path,
        gold_path=gold_path,
        reference_path=reference_path,
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_sleep=args.retry_sleep,
        run_scope=run_scope,
        selected_record_count=len(records),
    )
    rows = run_quality_judge(
        records=records, gold=load_gold_overlay(gold_path),
        references=rows_by_id(load_jsonl(reference_path)), output_path=output_path,
        metadata=metadata, model=args.model, temperature=args.temperature,
        timeout=args.timeout, max_retries=args.max_retries, retry_sleep=args.retry_sleep,
        resume=args.resume, overwrite=args.overwrite, dry_run=args.dry_run,
    )
    print(f"Quality judgements complete: {len(rows)} records; saved to {output_path}")
    if run_scope == "formal_complete":
        print(f"Full benchmark count validated: {EXPECTED_RECORD_COUNT}")
    else:
        print(f"Exploratory partial judge only: {len(records)}/{EXPECTED_RECORD_COUNT} records; not a formal result.")


if __name__ == "__main__":
    main()
