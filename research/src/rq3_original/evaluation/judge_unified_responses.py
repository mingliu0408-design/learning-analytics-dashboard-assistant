"""LLM judge for unified capability benchmark responses.

By default this script uses the OpenAI API. Use ``--dry-run`` for local
debugging with deterministic heuristic scores that preserve the output schema.
"""

from __future__ import annotations

import argparse
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

from evaluation.automatic_metrics import (  # noqa: E402
    answers_question_heuristic,
    has_internal_error_message,
    has_uncertainty_statement,
    number_of_action_steps,
    number_of_dashboard_evidence_mentions,
    number_of_generic_phrases,
    response_length_words,
)


RESPONSES = PROJECT_ROOT / "evaluation" / "outputs" / "unified_llm_responses.jsonl"
OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "unified_llm_judge_scores.jsonl"

DIMENSIONS = [
    "response_relevance",
    "evidence_integration",
    "context_awareness",
    "personalisation",
    "actionability",
    "explanatory_quality",
    "uncertainty_handling",
    "unsupported_claims_risk",
    "route_appropriateness",
    "memory_followup_accuracy",
    "retrieval_grounding",
    "course_context_use",
]
RISK_DIMENSION = "unsupported_claims_risk"


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(description="Judge unified benchmark responses.")
    parser.add_argument("--responses", type=Path, default=RESPONSES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--model", default=os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic heuristic scoring.")
    parser.add_argument("--resume", action="store_true", help="Append missing judgements to an existing output file.")
    parser.add_argument("--overwrite", action="store_true", help="Replace any existing output file before judging.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request OpenAI timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retries after the initial OpenAI attempt.")
    parser.add_argument("--retry-sleep", type=float, default=5.0, help="Seconds to sleep between failed attempts.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL records."""

    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
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


def append_jsonl_record(handle: Any, row: Mapping[str, Any]) -> None:
    """Append one JSONL record and flush it immediately."""

    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()


def load_existing_judgement_keys(path: Path) -> set[tuple[str, str]]:
    """Load already judged ``(scenario_id, mode)`` keys from an output file."""

    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in existing output {path} line {line_no}: {exc}") from exc
            key = judgement_key(row)
            if key != ("", ""):
                keys.add(key)
    return keys


def judgement_key(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return the resume key for a response or judgement record."""

    return str(record.get("scenario_id", "")), str(record.get("mode", ""))


def initialise_openai_client() -> Any:
    """Initialise the OpenAI client without exposing secrets."""

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Use --dry-run for local heuristic judging.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise SystemExit("The OpenAI Python package is not available.") from exc
    return OpenAI()


def judge_dry_run(record: Mapping[str, Any]) -> dict[str, Any]:
    """Create rubric-shaped heuristic scores for debugging."""

    response = str(record.get("response") or record.get("generated_response", ""))
    applicable = set(record.get("applicable_judge_dimensions", []))
    internal_error = has_internal_error_message(response)
    uncertainty = has_uncertainty_statement(response)
    evidence_mentions = number_of_dashboard_evidence_mentions(response)
    action_steps = number_of_action_steps(response)
    generic = number_of_generic_phrases(response)
    length = response_length_words(response)
    answers = answers_question_heuristic(str(record.get("student_query", "")), response)

    raw_scores: dict[str, int | None] = {
        "response_relevance": 5 if answers and not internal_error else 2,
        "evidence_integration": _clip(2 + min(3, evidence_mentions // 4)),
        "context_awareness": _score_route(record),
        "personalisation": _clip(2 + min(3, evidence_mentions // 5)),
        "actionability": _clip(2 + min(3, action_steps)),
        "explanatory_quality": 4 if re.search(r"\b(because|why|means|shows|suggests|matters)\b", response.lower()) and length >= 30 else 2,
        "uncertainty_handling": 5 if uncertainty else 2,
        "unsupported_claims_risk": _risk_score(response, uncertainty, internal_error, generic),
        "route_appropriateness": _score_route(record),
        "memory_followup_accuracy": _score_memory(record, response),
        "retrieval_grounding": _score_retrieval(record, response),
        "course_context_use": _score_course_context(record, response),
    }
    scores = {dim: (raw_scores[dim] if dim in applicable else None) for dim in DIMENSIONS}
    rationales = {
        dim: "Dry-run heuristic score; use OpenAI judging for the final benchmark."
        if scores[dim] is not None
        else "Not applicable to this scenario."
        for dim in DIMENSIONS
    }
    return output_record(record, scores=scores, rationales=rationales)


def judge_openai(client: Any, model: str, record: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    """Judge one response with OpenAI."""

    prompt = build_judge_prompt(record)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict educational technology evaluation judge. Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        timeout=timeout,
    )
    content = completion.choices[0].message.content or "{}"
    parsed = json.loads(content)
    scores = validate_scores(parsed.get("scores", {}), record.get("applicable_judge_dimensions", []))
    rationales = validate_rationales(parsed.get("rationales", {}), scores)
    return output_record(record, scores=scores, rationales=rationales)


def build_judge_prompt(record: Mapping[str, Any]) -> str:
    """Build the unified judge prompt."""

    rubric = {
        "response_relevance": "Does the response directly answer the student query? 1-5, higher is better.",
        "evidence_integration": "Uses relevant dashboard evidence for behavioural claims. 1-5.",
        "context_awareness": "Understands page, query type, scenario group, and cross-page context. 1-5.",
        "personalisation": "Tailored to this student's dashboard evidence. 1-5.",
        "actionability": "Concrete realistic next steps when advice is appropriate. 1-5.",
        "explanatory_quality": "Explains why the interpretation or recommendation matters. 1-5.",
        "uncertainty_handling": "Avoids overclaiming and states limitations where appropriate. 1-5.",
        "unsupported_claims_risk": "Risk of unsupported claims. 1-5 where 1 is low risk and 5 is high risk.",
        "route_appropriateness": "Uses the right response route for the query and capability needs. 1-5.",
        "memory_followup_accuracy": "Resolves and answers referenced previous items accurately when memory is required. 1-5.",
        "retrieval_grounding": "Uses retrieved chunks only for supported course/task/content claims. 1-5.",
        "course_context_use": "Uses course-material context appropriately where needed. 1-5.",
    }
    rules = [
        "Score only dimensions listed in applicable_judge_dimensions. Return null for all others.",
        "Do not reward memory use when the scenario does not require memory.",
        "Do not reward retrieval use when the scenario does not require course context.",
        "Penalise invented previous conversation details.",
        "Penalise invented course content or requirements beyond retrieved chunks.",
        "Penalise unsupported claims about student learning quality, motivation, comprehension, or grades.",
        "Dashboard evidence supports student-specific behavioural claims; course chunks support course/task guidance.",
        "Unsupported_claims_risk is lower-is-better; all other scored dimensions are higher-is-better.",
    ]
    compact_record = {
        "scenario": {
            key: record.get(key)
            for key in [
                "scenario_id",
                "scenario_group",
                "page",
                "student_query",
                "conversation_history",
                "required_capabilities",
                "applicable_judge_dimensions",
                "expected_route",
                "expected_memory",
                "expected_memory_items",
                "expected_memory_state_fields",
                "expected_retrieval",
                "expected_sources",
                "expected_topics",
            ]
        },
        "assistant_output": {
            key: record.get(key)
            for key in [
                "mode",
                "query_type",
                "selected_route",
                "memory_triggered",
                "memory_used",
                "memory_resolved",
                "memory_metadata",
                "resolved_student_query",
                "retrieval_used",
                "retrieved_chunk_ids",
                "retrieved_chunk_titles",
                "response",
            ]
        },
        "available_context": {
            "rq1_evidence_summary": record.get("rq1_evidence_summary", {}),
            "memory_resolution": record.get("memory_resolution", {}),
            "retrieved_context_chunks": record.get("retrieved_context_chunks", []),
        },
    }
    return (
        "Evaluate this unified benchmark response.\n\n"
        f"Rubric:\n{json.dumps(rubric, ensure_ascii=False, indent=2)}\n\n"
        f"Rules:\n{json.dumps(rules, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON exactly like:\n"
        "{\n"
        "  \"scores\": {\"response_relevance\": 5, \"evidence_integration\": 4, \"context_awareness\": 4, \"personalisation\": 4, \"actionability\": null, \"explanatory_quality\": 4, \"uncertainty_handling\": 4, \"unsupported_claims_risk\": 1, \"route_appropriateness\": 5, \"memory_followup_accuracy\": null, \"retrieval_grounding\": null, \"course_context_use\": null},\n"
        "  \"rationales\": {\"response_relevance\": \"...\", \"actionability\": \"Not applicable because...\"}\n"
        "}\n\n"
        f"Record:\n{json.dumps(compact_record, ensure_ascii=False, indent=2)}"
    )


def validate_scores(scores: Mapping[str, Any], applicable: list[str]) -> dict[str, int | None]:
    """Validate scores while allowing null for non-applicable dimensions."""

    applicable_set = set(applicable)
    out: dict[str, int | None] = {}
    for dim in DIMENSIONS:
        if dim not in applicable_set:
            out[dim] = None
            continue
        value = scores.get(dim)
        out[dim] = _clip(value)
    return out


def validate_rationales(rationales: Mapping[str, Any], scores: Mapping[str, int | None]) -> dict[str, str]:
    """Return one rationale per dimension."""

    return {
        dim: str(rationales.get(dim) or ("Not applicable." if value is None else "No rationale provided.")).strip()
        for dim, value in scores.items()
    }


def output_record(
    record: Mapping[str, Any],
    scores: Mapping[str, int | None],
    rationales: Mapping[str, str],
) -> dict[str, Any]:
    """Build final judge output record."""

    overall = overall_applicable_mean(scores, risk_adjusted=False)
    risk_adjusted = overall_applicable_mean(scores, risk_adjusted=True)
    return {
        "scenario_id": record.get("scenario_id", ""),
        "mode": record.get("mode", ""),
        "page": record.get("page", ""),
        "query_type": record.get("query_type", ""),
        "scenario_group": record.get("scenario_group", ""),
        "required_capabilities": record.get("required_capabilities", []),
        "selected_route": record.get("selected_route", ""),
        "scores": dict(scores),
        "rationales": dict(rationales),
        "overall_applicable_mean": overall,
        "overall_applicable_mean_risk_adjusted": risk_adjusted,
        "unsupported_claims_risk": scores.get("unsupported_claims_risk"),
        "judge_failed": False,
        "error_message": "",
    }


def failure_output_record(record: Mapping[str, Any], error_message: str) -> dict[str, Any]:
    """Build a structured failure row so judging can continue after one bad record."""

    scores = {dim: None for dim in DIMENSIONS}
    rationales = {dim: "Judge failed for this record." for dim in DIMENSIONS}
    return {
        "scenario_id": record.get("scenario_id", ""),
        "mode": record.get("mode", ""),
        "page": record.get("page", ""),
        "query_type": record.get("query_type", ""),
        "scenario_group": record.get("scenario_group", ""),
        "required_capabilities": record.get("required_capabilities", []),
        "selected_route": record.get("selected_route", ""),
        "scores": scores,
        "rationales": rationales,
        "overall_applicable_mean": None,
        "overall_applicable_mean_risk_adjusted": None,
        "unsupported_claims_risk": None,
        "judge_failed": True,
        "error_message": str(error_message)[:1000],
    }


def judge_with_retries(
    client: Any,
    model: str,
    record: Mapping[str, Any],
    timeout: float,
    max_retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    """Judge one record, retrying transient failures and returning a failure row if needed."""

    attempts = max(1, int(max_retries) + 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return judge_openai(client, model, record, timeout=timeout)
        except Exception as exc:  # OpenAI, timeout, JSON parsing, and validation failures are all recoverable per record.
            last_error = exc
            if attempt < attempts:
                print(
                    "Retrying "
                    f"{record.get('scenario_id')} mode={record.get('mode')} "
                    f"after attempt {attempt}/{attempts} failed: {exc}"
                )
                time.sleep(max(0.0, retry_sleep))
    return failure_output_record(record, str(last_error or "Unknown judge failure."))


def overall_applicable_mean(scores: Mapping[str, int | None], risk_adjusted: bool) -> float | None:
    """Compute aggregate over applicable dimensions."""

    values: list[float] = []
    for dim, value in scores.items():
        if value is None:
            continue
        if dim == RISK_DIMENSION:
            if risk_adjusted:
                values.append(float(6 - value))
            continue
        values.append(float(value))
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _score_route(record: Mapping[str, Any]) -> int:
    route = str(record.get("selected_route", "")).lower()
    expected = str(record.get("expected_route", "")).lower()
    group = str(record.get("scenario_group", "")).lower()
    if expected and expected in route:
        return 5
    if group == "recommendation_planning" and "recommendation" in route:
        return 5
    if group == "course_material_retrieval" and bool(record.get("retrieval_used")):
        return 4
    if group == "memory_follow_up" and bool(record.get("memory_resolved")):
        return 5
    if group == "negative_control" and not record.get("memory_used") and not record.get("retrieval_used"):
        return 5
    return 3


def _score_memory(record: Mapping[str, Any], response: str) -> int:
    if not record.get("expected_memory"):
        return 5 if not record.get("memory_resolved") else 2
    if not record.get("memory_resolved"):
        return 1
    expected = [str(item) for item in record.get("expected_memory_items", [])]
    expected_state_fields = [str(field) for field in record.get("expected_memory_state_fields", [])]
    structured_state = (record.get("memory_resolution", {}) or {}).get("structured_state", {}) or {}
    state_ok = all(bool(structured_state.get(field)) for field in expected_state_fields)
    actual = [
        str(item.get("number", ""))
        for item in (record.get("memory_resolution", {}) or {}).get("referenced_items", [])
    ]
    response_l = response.lower()
    topic_ok = all(str(topic).lower() in response_l for topic in record.get("expected_topics", []))
    if expected and actual == expected and topic_ok:
        return 5
    if expected and actual == expected:
        return 4
    if expected_state_fields and state_ok and topic_ok:
        return 5
    if expected_state_fields and state_ok:
        return 4
    if not expected and not expected_state_fields and topic_ok:
        return 5
    return 2


def _score_retrieval(record: Mapping[str, Any], response: str) -> int:
    if not record.get("expected_retrieval"):
        return 5 if not record.get("retrieval_used") else 2
    if record.get("retrieval_used"):
        return 5 if _topic_match(record, response) else 4
    return 4 if _acknowledges_limitation(response) else 1


def _score_course_context(record: Mapping[str, Any], response: str) -> int:
    if not record.get("expected_retrieval"):
        return 5 if not _has_course_context(response) else 3
    if _has_course_context(response) and (_topic_match(record, response) or record.get("retrieval_used")):
        return 5
    return 3 if _acknowledges_limitation(response) else 2


def _risk_score(response: str, uncertainty: bool, internal_error: bool, generic: int) -> int:
    if internal_error:
        return 5
    lowered = response.lower()
    risk = 1
    if re.search(r"\b(proves?|demonstrates understanding|you are motivated|your grade|you learned)\b", lowered):
        risk += 2
    if not uncertainty:
        risk += 1
    if generic:
        risk += 1
    return _clip(risk)


def _topic_match(record: Mapping[str, Any], response: str) -> bool:
    haystack = " ".join(
        [response]
        + record.get("retrieved_chunk_ids", [])
        + record.get("retrieved_chunk_titles", [])
        + [str(chunk.get("text", "")) for chunk in record.get("retrieved_context_chunks", [])]
    ).lower()
    topics = [str(topic).lower() for topic in record.get("expected_topics", []) if str(topic).strip()]
    return all(topic in haystack for topic in topics) if topics else True


def _has_course_context(response: str) -> bool:
    return bool(re.search(r"\b(course material|weekly page|handbook|reading|readings|assessment|lecture topic|module)\b", response.lower()))


def _acknowledges_limitation(response: str) -> bool:
    return bool(re.search(r"\b(insufficient|not enough|did not find|cannot|can't|limited|no strong matching)\b", response.lower()))


def _clip(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 1
    return max(1, min(5, number))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    args = parse_args()
    responses_path = resolve_path(args.responses)
    output_path = resolve_path(args.output)
    if args.resume and args.overwrite:
        raise SystemExit("Use either --resume or --overwrite, not both.")

    records = load_jsonl(responses_path)
    if args.limit is not None:
        records = records[: args.limit]

    existing_keys: set[tuple[str, str]] = set()
    if output_path.exists():
        if args.overwrite:
            output_path.unlink()
        elif args.resume:
            existing_keys = load_existing_judgement_keys(output_path)
        else:
            raise SystemExit(
                f"Output already exists: {display_path(output_path)}. "
                "Use --resume to continue missing records or --overwrite to replace it."
            )

    pending_records = [record for record in records if judgement_key(record) not in existing_keys]
    already_judged = len(records) - len(pending_records)

    print(f"Responses: {display_path(responses_path)}")
    print(f"Output: {display_path(output_path)}")
    print(f"Total records selected: {len(records)}")
    if args.resume:
        print(f"Already judged records in selected set: {already_judged}")
        print(f"Pending records: {len(pending_records)}")
    if not args.dry_run:
        print(f"OpenAI timeout: {args.timeout}s; max retries: {args.max_retries}; retry sleep: {args.retry_sleep}s")

    client = None if args.dry_run or not pending_records else initialise_openai_client()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("a", encoding="utf-8") as f:
        for idx, record in enumerate(pending_records, start=1):
            print(
                f"Judging {idx}/{len(pending_records)} "
                f"(selected total {len(records)}): {record.get('scenario_id')} mode={record.get('mode')}"
            )
            judged = (
                judge_dry_run(record)
                if args.dry_run
                else judge_with_retries(
                    client=client,
                    model=args.model,
                    record=record,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    retry_sleep=args.retry_sleep,
                )
            )
            append_jsonl_record(f, judged)
            written += 1
            status = "failed" if judged.get("judge_failed") else "completed"
            print(f"Judged {record.get('scenario_id')} mode={record.get('mode')} ({status}); flushed to output.")

    print(f"Newly judged records written: {written}")
    if args.resume:
        print(f"Total judged records in selected set after this run: {already_judged + written}/{len(records)}")
    print(f"Saved: {display_path(output_path)}")
    if args.dry_run:
        print("Judge mode: dry-run heuristic. Use without --dry-run for final LLM judging.")
    else:
        print(f"Judge mode: OpenAI API model={args.model}")


if __name__ == "__main__":
    main()
