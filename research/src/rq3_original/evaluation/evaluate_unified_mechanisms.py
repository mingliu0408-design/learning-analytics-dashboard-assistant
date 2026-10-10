"""Deterministic mechanism evaluation against frozen gold and reference evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    EXPECTED_RECORD_COUNT,
    EXPECTED_SCENARIO_COUNT,
    FROZEN_RESPONSES_SHA256,
    GOLD_LABELS_PATH,
    GOLD_LABEL_VERSION,
    MECHANISM_DIMENSIONS,
    MECHANISM_RUBRIC_VERSION_V2,
    EXPECTED_MODES,
    REFERENCE_EVIDENCE_PATH,
    SCENARIOS_PATH,
    EvaluationValidationError,
    file_sha256,
    load_gold_overlay,
    load_jsonl,
    mechanism_score,
    rows_by_id,
)


RESPONSES = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_llm_responses_v1.jsonl"
OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_mechanism_scores_v2.jsonl"
V1_OUTPUT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_mechanism_scores_v1.jsonl"
VALIDATION_JSON = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "mechanism_v2_validation_report.json"
VALIDATION_MARKDOWN = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "mechanism_v2_validation_report.md"
SPOT_CHECK = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "mechanism_v2_spot_check.md"
FROZEN_V1_MECHANISM_SHA256 = "58bb3e2b48fdd87c8ad4afac89725091e229ccabab292c19b6d5fc500b00b110"

ACTUAL_ROUTE_TO_GOLD_ROUTE = {
    "recommendation_planning": "recommendation_planning",
    "rq2_recommendation": "recommendation_planning",
    "reflection_structure": "course_material_retrieval",
    "memory_follow_up": "memory_follow_up",
    "memory_resolved_follow_up": "memory_follow_up",
    "memory_state_direct_answer": "memory_follow_up",
    "course_content": "course_material_retrieval",
    "course_material_retrieval": "course_material_retrieval",
    "dashboard_interpretation": "dashboard_interpretation",
    "metric_definition": "metric_clarification",
    "metric_clarification": "metric_clarification",
    "technical_data": "direct_technical_access_or_discrepancy",
    "data_provenance": "direct_technical_access_or_discrepancy",
    "access_or_capability": "direct_technical_access_or_discrepancy",
    "discrepancy_or_correction": "direct_technical_access_or_discrepancy",
    "direct_technical_access_or_discrepancy": "direct_technical_access_or_discrepancy",
    "cross_page_relationship": "cross_page_evidence_synthesis",
    "cross_page_evidence_synthesis": "cross_page_evidence_synthesis",
    "hybrid_course_and_planning": "hybrid_evidence_and_retrieval",
    "hybrid_evidence_and_retrieval": "hybrid_evidence_and_retrieval",
    "hybrid_memory_and_retrieval": "hybrid_memory_and_retrieval",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate unified internal mechanisms deterministically.")
    parser.add_argument("--responses", type=Path, default=RESPONSES)
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_PATH)
    parser.add_argument("--gold-labels", type=Path, default=GOLD_LABELS_PATH)
    parser.add_argument("--reference-evidence", type=Path, default=REFERENCE_EVIDENCE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    writes = parser.add_mutually_exclusive_group()
    writes.add_argument("--resume", action="store_true")
    writes.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def validate_output_destination(output: Path) -> None:
    if output.resolve() == V1_OUTPUT.resolve():
        raise EvaluationValidationError(
            "protected_v1_output",
            f"Refusing to overwrite frozen legacy mechanism v1 output: {V1_OUTPUT}",
        )


def route_matches(predicted: str, expected: str) -> bool:
    """Only an explicitly declared actual→gold route mapping may pass."""

    return ACTUAL_ROUTE_TO_GOLD_ROUTE.get(str(predicted).strip().lower()) == str(expected).strip().lower()


def expected_item_accuracy(record: Mapping[str, Any]) -> bool:
    expected = [str(value) for value in record.get("expected_memory_items", [])]
    resolution = record.get("memory_resolution") or {}
    actual = [str(item.get("number", "")) for item in resolution.get("referenced_items", [])]
    expected_fields = [str(value) for value in record.get("expected_memory_state_fields", [])]
    state = resolution.get("structured_state", {}) or {}
    return (not expected or actual == expected) and all(bool(state.get(field)) for field in expected_fields)


def _reference_course_text(reference: Mapping[str, Any]) -> str:
    return " ".join(
        f"{chunk.get('title', '')} {chunk.get('text', '')}"
        for chunk in reference.get("reference_course_evidence", [])
    ).lower()


TOKEN_ALIASES = {
    "accessed": "access", "accesses": "access", "accessing": "access",
    "opened": "open", "opens": "open", "opening": "open",
    "viewed": "view", "views": "view", "viewing": "view",
    "written": "write", "writing": "write", "wrote": "write", "edited": "edit", "editing": "edit",
    "summarise": "summary", "summarised": "summary", "summarises": "summary",
    "summarize": "summary", "summarized": "summary", "summarizes": "summary", "summarizing": "summary",
    "select": "choose", "selected": "choose", "pick": "choose", "picked": "choose",
    "perspective": "viewpoint", "opinion": "viewpoint", "viewpoint": "viewpoint",
    "conclude": "end", "concludes": "end", "finish": "end", "finished": "end",
    "respond": "reply", "response": "reply", "replies": "reply", "replied": "reply",
    "reflections": "reflection", "reflective": "reflection", "reflecting": "reflection",
    "understood": "understand", "understanding": "understand", "completed": "completion", "learned": "learning",
    "connections": "connection", "interactions": "interaction", "participants": "participant",
    "characters": "character", "readings": "reading", "resources": "resource", "lectures": "lecture",
}


def _normalise_text(value: str) -> str:
    value = re.sub(r"\bweek\s*(\d+)\b", r"w\1", value.lower())
    return " ".join(TOKEN_ALIASES.get(token, token) for token in re.findall(r"[a-z0-9]+", value))


def _content_tokens(value: str) -> set[str]:
    stop = {
        "the", "and", "that", "this", "with", "from", "your", "course", "material", "only", "into",
        "have", "has", "for", "you", "its", "was", "were", "are", "can", "could", "would", "should",
        "one", "also", "based", "using", "use", "will", "what", "when", "where", "which", "their",
    }
    return {token for token in _normalise_text(value).split() if len(token) > 2 and token not in stop}


def _response_text(record: Mapping[str, Any]) -> str:
    return str(record.get("response") or record.get("generated_response", ""))


def _course_sentences(value: str) -> list[str]:
    return [
        re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", item).strip()
        for item in re.split(r"(?<=[.!?])\s+|\n+", value)
        if item.strip()
    ]


def _is_general_advice(sentence: str) -> bool:
    lowered = sentence.lower().strip(" -*0123456789.)")
    explicit_attribution = bool(re.search(
        r"\b(?:course material|handbook|module|lecture|reading|assessment|assignment|source)\b.{0,45}"
        r"\b(?:says?|states?|requires?|specifies?|covers?|focuses?|explains?|defines?|lists?|indicates?)\b",
        lowered,
    ))
    advice = bool(
        re.match(r"(?:choose|pick|write|take|compare|review|revisit|reflect|identify|add|end|start|try|consider|use|link|connect|ensure|focus)\b", lowered)
        or re.search(r"\b(?:i recommend|you (?:can|could|should|might)|consider|try to|as a next step)\b", lowered)
        or re.search(r"\bguidance\b.{0,80}\b(?:write|choose|link|connect|reflect|use)\b", lowered)
    )
    return advice and not explicit_attribution


def _is_course_fact_claim(sentence: str) -> bool:
    lowered = sentence.lower()
    if _is_general_advice(sentence):
        return False
    if re.search(r"\b(?:you have|your data|your (?:debate|lecture|resource|reflection) (?:record|activity)|dashboard|characters?\s+(?:edited|across))\b", lowered):
        return False
    if re.search(r"\b(?:this information is derived|these (?:themes|elements))\b", lowered):
        return False
    entity = bool(re.search(
        r"\b(?:course material|handbook|module|lecture|reading|assessment|assignment|part [ab]|w\s*\d+|week\s*\d+|forum|debate task|session|paper)\b",
        lowered,
    ))
    factual_relation = bool(re.search(
        r"\b(?:says?|states?|requires?|specifies?|covers?|focuses?|introduces?|explains?|defines?|lists?|includes?|is titled|is about|argues?|finds?|shows?|suggests?|outlined?|consists?|has two parts)\b",
        lowered,
    ))
    named_course_fact = bool(re.search(r"\b(?:w\s*\d+|week\s*\d+|part [ab])\b.{0,70}\b(?:lecture|learning analytics|reflection|assignment|forum|debate|reading)\b", lowered))
    return entity and (factual_relation or named_course_fact)


def _reference_is_weak(reference: Mapping[str, Any]) -> bool:
    chunks = list(reference.get("reference_course_evidence") or [])
    return bool(chunks) and all(len(_content_tokens(str(chunk.get("text", "")))) <= 7 for chunk in chunks)


def course_claim_audit(record: Mapping[str, Any], reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Classify visible course-factual claims without treating ordinary advice as a course claim."""

    reference_text = _reference_course_text(reference)
    reference_tokens = _content_tokens(reference_text)
    weak_reference = _reference_is_weak(reference)
    audits: list[dict[str, Any]] = []
    for sentence in _course_sentences(_response_text(record)):
        if _is_general_advice(sentence):
            if re.search(r"\b(?:lecture|reading|course|assessment|assignment|part [ab]|w\s*\d+|week\s*\d+)\b", sentence, re.I):
                audits.append({"claim": sentence, "classification": "ordinary_advice", "support": "not_required"})
            continue
        if not _is_course_fact_claim(sentence):
            continue
        claim_tokens = _content_tokens(sentence)
        overlap = len(claim_tokens & reference_tokens) / len(claim_tokens) if claim_tokens else 0.0
        unsupported_tokens = claim_tokens - reference_tokens
        sentence_normalised = _normalise_text(sentence)
        exact_chunk_match = any(
            _normalise_text(str(chunk.get("text", ""))) in sentence_normalised
            for chunk in reference.get("reference_course_evidence", [])
            if _normalise_text(str(chunk.get("text", "")))
        )
        if exact_chunk_match or (overlap >= 0.58 and not (weak_reference and len(unsupported_tokens) >= 4)):
            support = "supported"
        elif overlap >= 0.32 and not (weak_reference and len(unsupported_tokens) >= 6):
            support = "partially_supported"
        else:
            support = "unsupported"
        audits.append({
            "claim": sentence, "classification": "course_factual_claim", "support": support,
            "token_overlap": round(overlap, 3),
        })
    return audits


def retrieval_grounding_assessment(record: Mapping[str, Any], reference: Mapping[str, Any]) -> tuple[int, str]:
    """Score only course-factual claims; clearly framed ordinary advice needs no chunk support."""

    retrieval_used = bool(record.get("retrieval_used") or record.get("predicted_retrieval_decision"))
    if not retrieval_used:
        return 1, "Retrieval was required but no retrieval attempt was recorded."
    chunks = list(reference.get("reference_course_evidence") or [])
    response = _response_text(record)
    response_lower = response.lower()
    if not chunks:
        no_result_acknowledged = bool(
            re.search(r"\bno relevant (?:course |module )?(?:material|content|chunks?|information|sources?|evidence)\b.{0,50}\b(?:found|available|retrieved|provided)\b", response_lower)
            or re.search(r"\b(?:could not|couldn't|cannot|can't|unable to)\s+(?:find|locate|retrieve)\b.{0,100}\b(?:course|module|material|content|information|source|evidence)\b", response_lower)
        )
        invented_course_answer = bool(
            re.search(r"\b(?:the )?(?:course|module|lecture|reading|material)s?\b.{0,40}\b(?:says?|states?|requires?|specifies?|explains?|recommends?|instructs?)\b", response_lower)
            or re.search(r"\b(?:laboratory|lab) coats?\b.{0,50}\b(?:must|should|required|size(?:s|d)?|small|medium|large|x+l)\b", response_lower)
        )
        if no_result_acknowledged and not invented_course_answer:
            return 5, "Retrieval was attempted; the response reports that no relevant course material was found and invents no course content."
        return 1, "No reference course chunk exists and the response did not give a clean, non-invented no-result report."

    reference_text = _reference_course_text(reference)
    content_level = str(record.get("retrieval_content_level") or (record.get("retrieval_result") or {}).get("retrieval_content_level") or "")
    citation_only = content_level in {"citation_only", "title_and_metadata"} or _reference_is_weak(reference)
    specific_refusal = bool(
        re.search(r"\b(?:only|contains?)\b.{0,80}\b(?:title|citation|metadata)\b", response_lower)
        and re.search(r"\b(?:cannot|can't|not enough|unable to)\b.{0,100}\b(?:summari[sz]e|arguments?|findings?|details?)\b", response_lower)
    )
    if citation_only and specific_refusal:
        return 5, "The available evidence is title/citation-only and the response explicitly refuses to invent unavailable content."
    unsupported_strong_claim = any(
        re.search(r"\b(proves?|guarantees?|causes?|improves? (?:achievement|learning|grades?)|demonstrates? that)\b", sentence, re.I)
        and not re.search(r"\b(?:not|does not|doesn't|cannot|can't|do not|don't)\b", sentence, re.I)
        for sentence in _course_sentences(response)
    ) and not any(phrase in reference_text for phrase in ("proves", "guarantees", "improves achievement", "causes"))
    if unsupported_strong_claim:
        return 1, "The response makes a strong course-content claim that is absent from the common reference evidence."

    claim_audits = course_claim_audit(record, reference)
    factual = [item for item in claim_audits if item["classification"] == "course_factual_claim"]
    unsupported = [item for item in factual if item["support"] == "unsupported"]
    partial = [item for item in factual if item["support"] == "partially_supported"]
    if unsupported:
        return 1, f"{len(unsupported)} material course-factual claim(s) were unsupported by the common reference evidence."
    if citation_only:
        return 3, "Only weak title/label evidence was available; the visible course claim was bounded, but the evidence cannot support a detailed content account."
    if partial:
        return 3, f"Course evidence was used, but {len(partial)} claim(s) were only partially supported."
    if factual:
        return 5, f"All {len(factual)} material course-factual claim(s) were supported; remaining course mentions were framed as general advice."
    return 3, "Retrieval was used without an unsupported course fact, but the final response made only a weak or advisory connection to the course evidence."


def retrieval_grounding_score(record: Mapping[str, Any], reference: Mapping[str, Any]) -> int:
    return retrieval_grounding_assessment(record, reference)[0]


def course_context_assessment(record: Mapping[str, Any], reference: Mapping[str, Any]) -> tuple[int, str]:
    response = _normalise_text(_response_text(record))
    reference_text = _normalise_text(_reference_course_text(reference))
    if not reference_text:
        return 1, "No common reference course evidence exists, so course context cannot be credited."
    topics = [str(topic) for topic in record.get("expected_topics", []) if str(topic).strip()]
    if topics:
        used: list[str] = []
        for topic in topics:
            topic_tokens = _content_tokens(topic) or set(_normalise_text(topic).split())
            response_tokens = set(response.split())
            reference_tokens = set(reference_text.split())
            threshold = max(1, round(len(topic_tokens) * 0.75))
            if len(topic_tokens & response_tokens) >= threshold and len(topic_tokens & reference_tokens) >= threshold:
                used.append(topic)
        if len(used) == len(topics):
            return 5, f"All required course topics were stated or paraphrased in the response and supported by the common reference evidence: {', '.join(used)}."
        if used:
            return 3, f"Only {len(used)} of {len(topics)} required supported course topics appeared in the final response."
        return 1, "Required course topics appeared in the reference evidence but not in the final response."
    claims = [item for item in course_claim_audit(record, reference) if item["classification"] == "course_factual_claim"]
    if claims and all(item["support"] == "supported" for item in claims):
        return 5, f"All {len(claims)} visible course-context claim(s) were supported by the common reference evidence."
    if claims and any(item["support"] in {"supported", "partially_supported"} for item in claims):
        return 3, "Some visible course context was supported, but its use was incomplete or partially matched."
    return 1, "The final response did not use supported course context."


def course_context_score(record: Mapping[str, Any], reference: Mapping[str, Any]) -> int:
    return course_context_assessment(record, reference)[0]


def _normalise_action(value: str) -> str:
    return _normalise_text(re.sub(r"\b(?:step|action)\s*\d+\b", " ", value, flags=re.I))


def _step_action(step: Any) -> str:
    if isinstance(step, Mapping):
        return str(step.get("action_text") or step.get("text") or step.get("action") or "").strip()
    return str(step).strip()


def _plan_steps(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_steps = list(plan.get("action_steps") or plan.get("steps") or [])
    steps: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_steps, start=1):
        action = _step_action(raw)
        if not action:
            continue
        steps.append({
            "index": raw.get("index", raw.get("number", position)) if isinstance(raw, Mapping) else position,
            "action_text": action,
            "status": raw.get("status", "pending") if isinstance(raw, Mapping) else "pending",
        })
    return steps


def _structured_plan(record: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], list[dict[str, Any]]]:
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for field in ("rq2_recommendation_plan", "recommendation_plan", "active_plan"):
        value = record.get(field) or {}
        if isinstance(value, Mapping):
            candidates.append((field, value))
    for state_field in (
        "postcommit_state", "post_commit_state", "post_commit_structured_memory", "structured_memory", "memory_state",
    ):
        state = record.get(state_field) or {}
        if isinstance(state, Mapping):
            plan = state.get("active_plan") or {}
            if isinstance(plan, Mapping):
                candidates.append((f"{state_field}.active_plan", plan))
    for source, plan in candidates:
        steps = _plan_steps(plan)
        if steps:
            return source, plan, steps
    return "", {}, []


def _action_match(action: str, response: str) -> tuple[bool, float, int]:
    action_normalised = _normalise_action(action)
    response_normalised = _normalise_action(response)
    if action_normalised and action_normalised in response_normalised:
        return True, 1.0, response_normalised.index(action_normalised)
    action_tokens = _content_tokens(action_normalised)
    response_tokens = _content_tokens(response_normalised)
    coverage = len(action_tokens & response_tokens) / len(action_tokens) if action_tokens else 0.0
    similarity = SequenceMatcher(None, action_normalised, response_normalised).ratio()
    response_sequence = response_normalised.split()
    positions = sorted(
        response_sequence.index(token) for token in action_tokens if token in response_sequence
    )
    position = positions[len(positions) // 2] if positions else len(response_normalised) + 1
    return coverage >= 0.55 or similarity >= 0.62, max(coverage, similarity), position


def _plan_members(plan: Mapping[str, Any]) -> list[tuple[Any, str]]:
    return [(step.get("index"), _normalise_action(step.get("action_text", ""))) for step in _plan_steps(plan)]


def _visible_numbered_items(response: str) -> dict[int, str]:
    return {
        int(match.group(1)): match.group(2).strip()
        for match in re.finditer(r"(?m)^\s*(\d+)[.)]\s+(.+)$", response)
    }


def plan_state_consistency_assessment(record: Mapping[str, Any]) -> tuple[int, str]:
    """Evaluate genuine planner state across all documented formal-generation fields."""

    response = _response_text(record)
    source, plan, steps = _structured_plan(record)
    if not steps:
        return 1, "No structured plan was present; visible numbering alone is insufficient."
    indexes = [step.get("index") for step in steps]
    if indexes != list(range(1, len(steps) + 1)):
        return 1, f"Structured {source} contained unstable or non-consecutive step indexes."
    invalid_statuses = [step.get("status") for step in steps if step.get("status") not in {"pending", "completed"}]
    if invalid_statuses:
        return 1, f"Structured {source} contained invalid step status values: {invalid_statuses}."

    pre_plan = (record.get("pre_generation_structured_memory") or {}).get("active_plan") or {}
    post_plan = (record.get("post_commit_structured_memory") or {}).get("active_plan") or {}
    resolution = record.get("memory_resolution") or {}
    referenced = list(resolution.get("referenced_items") or [])
    if pre_plan and post_plan and referenced and _plan_members(pre_plan) != _plan_members(post_plan):
        return 1, "Active-plan membership or indexes changed during an explanatory follow-up."

    expected_steps = steps
    if referenced:
        expected_steps = []
        members = {str(step["index"]): step for step in steps}
        for item in referenced:
            number = str(item.get("number") or item.get("index") or "")
            member = members.get(number)
            if not member:
                return 1, f"Referenced item {number or '?'} was not a member of the authoritative active plan."
            item_text = str(item.get("text") or item.get("action_text") or "")
            if item_text and not _action_match(item_text, member["action_text"])[0]:
                return 1, f"Referenced item {number} conflicted with authoritative plan membership."
            expected_steps.append(member)

    query = str(record.get("student_query", ""))
    completion_query = bool(re.search(r"\b(?:completed?|done|finished)\b", query, re.I))
    if completion_query and post_plan:
        post_steps = _plan_steps(post_plan)
        first_pending = next((step for step in post_steps if step.get("status") == "pending"), None)
        next_pending = post_plan.get("next_pending_step") or {}
        if first_pending:
            if not next_pending or str(next_pending.get("index")) != str(first_pending.get("index")):
                return 1, "The structured next-pending step did not match the first pending plan member after completion."
            if not re.search(r"\b(?:next|current|pending)\b", response, re.I) or not _action_match(first_pending["action_text"], response)[0]:
                return 1, "The visible next step conflicted with the structured next-pending state."

    visible_numbered = _visible_numbered_items(response)
    expected_indexes = {int(step["index"]) for step in expected_steps}
    if len(visible_numbered) == len(expected_steps) and set(visible_numbered) == expected_indexes:
        numbered_matches = [
            _action_match(step["action_text"], visible_numbered[int(step["index"])])[0]
            for step in expected_steps
        ]
        numbered_matched = sum(numbered_matches)
        if numbered_matched == len(expected_steps):
            return 5, f"Structured {source} with {len(steps)} action_steps was found; authoritative indexes and all visible numbered actions matched."
        minimum_minor_match = max(1, (2 * len(expected_steps) + 2) // 3)
        if numbered_matched >= minimum_minor_match:
            return 3, f"Structured {source} was present; {numbered_matched} of {len(expected_steps)} indexed visible actions matched with a minor omission."
        return 1, f"Visible numbered actions materially conflicted with structured {source} membership."

    matches = [_action_match(step["action_text"], response) for step in expected_steps]
    matched = sum(result[0] for result in matches)
    matched_positions = [result[2] for result in matches if result[0]]
    ordered = matched_positions == sorted(matched_positions)
    if matched == len(expected_steps) and ordered:
        return 5, f"Structured {source} with {len(steps)} action_steps was found; all required visible actions matched in order after normalisation."
    minimum_minor_match = max(1, (2 * len(expected_steps) + 2) // 3)
    if matched >= minimum_minor_match and ordered:
        return 3, f"Structured {source} was present; {matched} of {len(expected_steps)} required actions matched, with a minor omission or wording mismatch."
    return 1, f"Structured {source} was present, but only {matched} of {len(expected_steps)} required actions matched or their order conflicted."


def plan_state_consistency_score(record: Mapping[str, Any]) -> int:
    return plan_state_consistency_assessment(record)[0]


def negative_control_assessment(record: Mapping[str, Any]) -> tuple[int, str]:
    resolution = record.get("memory_resolution") or {}
    if record.get("memory_triggered") or record.get("memory_resolved"):
        return 1, "Memory was activated or resolved even though the scenario is a Memory negative control."
    if record.get("retrieval_used") or record.get("predicted_retrieval_decision"):
        return 1, "Course retrieval was activated without justification in the negative-control scenario."
    if resolution.get("referenced_items") or resolution.get("course_reference_resolved") or resolution.get("memory_reference_resolved"):
        return 1, "The resolution metadata contains a nonexistent prior referent."
    if resolution.get("resolution_type") or resolution.get("memory_resolution_type"):
        return 1, "The response recorded a Memory resolution type for a non-resolving history."
    query = str(record.get("student_query", ""))
    response = _response_text(record)
    ambiguous = bool(re.search(
        r"\b(?:item|step|point)\s*(?:\d+|one|two|three)|"
        r"\b(?:this|that|those|last)\s+(?:one|step|point)\b|"
        r"\b(?:do|suggest).{0,25}\b\d+\s*(?:and|,)\s*\d+",
        query,
        re.I,
    ))
    invented_reference = bool(re.search(
        r"\b(?:you (?:said|chose|selected|mentioned)|your (?:saved )?(?:goal|constraint)|"
        r"original (?:item|step)\s*\d+|(?:item|step|task)\s*[23]\s+(?:is|means|requires)|"
        r"for (?:item|step|task)\s*[23]\s*:)\b",
        response,
        re.I,
    ))
    if ambiguous and invented_reference:
        return 1, "The response invented concrete content for a numbered referent that was absent from the supplied history."
    acknowledgement = bool(re.search(
        r"\b(?:which|clarif|unclear|underspecified|not clear|no (?:saved |prior )?(?:item|step|context)|"
        r"don't have|do not have|cannot determine|can't determine|can you share|could you share|specifics?.{0,20}(?:aren't|are not) clear)\b",
        response,
        re.I,
    ))
    if ambiguous:
        if acknowledgement:
            return 5, "The missing numbered referent was explicitly acknowledged; Memory and retrieval remained off and no prior item was invented."
        return 3, "Memory and retrieval remained off, but the ambiguous numbered reference was handled without an explicit clarification boundary."
    standalone_advice = bool(re.search(r"\b(?:improve|recommend|suggest|advice|what should i do|how can i|plan|next steps?)\b", query, re.I))
    post_plan = (record.get("post_commit_structured_memory") or {}).get("active_plan") or {}
    if standalone_advice and (post_plan or re.search(r"(?m)^\s*(?:\d+[.)]|[-*])\s+", response)):
        return 5, "Memory and retrieval were not activated; the fresh plan was requested by the current standalone query and did not rely on prior history."
    return 5, "Memory and retrieval remained off, and the response did not invent a prior goal, constraint, plan, or course item."


def negative_control_score(record: Mapping[str, Any]) -> int:
    return negative_control_assessment(record)[0]


METRIC_CONCEPTS: dict[str, dict[str, tuple[str, ...]]] = {
    "assessment_views": {
        "entity": ("assessment",), "meaning": ("access", "open", "view"),
        "boundary": ("understand", "completion", "quality", "learning", "achievement"),
    },
    "resources_views": {
        "entity": ("resource", "reading"), "meaning": ("access", "open", "view"),
        "boundary": ("understand", "completion", "quality", "learning", "achievement", "engagement"),
    },
    "debate_views": {
        "entity": ("debate", "post", "page"), "meaning": ("open", "view"),
        "boundary": ("understand", "quality", "learning", "achievement", "critical"),
    },
    "debate_posts": {
        "entity": ("post", "contribution"), "meaning": ("write", "made", "number", "count", "frequency"),
        "boundary": ("quality", "understand", "learning", "critical", "depth"),
    },
    "debate_replies": {
        "entity": ("reply", "debate"), "meaning": ("reply", "write", "made", "number", "count", "frequency"),
        "boundary": ("quality", "understand", "learning", "critical", "depth"),
    },
    "unique_viewers": {
        "entity": ("unique", "distinct", "viewer", "student", "people"), "meaning": ("view", "open", "number", "count"),
        "boundary": ("understand", "quality", "learning", "influence", "achievement"),
    },
    "total_chars": {
        "entity": ("character", "chars", "text"), "meaning": ("edit", "enter", "write", "amount", "volume", "total"),
        "boundary": ("quality", "depth", "insight", "learning", "achievement"),
    },
    "reply_network": {
        "entity": ("reply", "network", "interaction", "connection"), "meaning": ("who", "whom", "directed", "connection", "structure", "frequency", "interaction"),
        "boundary": ("quality", "depth", "learning", "understand", "sentiment", "influence"),
    },
    "lecture_views": {
        "entity": ("lecture", "video"), "meaning": ("view", "watch", "event", "number", "count"),
        "boundary": ("attention", "understand", "completion", "quality", "learning", "achievement"),
    },
    "average_video_completion_percentage": {
        "entity": ("video", "lecture"), "meaning": ("percent", "percentage", "proportion", "watch", "view"),
        "boundary": ("attention", "understand", "completion rate", "course completion", "quality", "learning", "achievement"),
    },
}


def _metric_definition_keys(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        keys: list[str] = []
        for key, item in value.items():
            if key == "metric_definitions" and isinstance(item, Mapping):
                keys.extend(str(metric) for metric in item)
            keys.extend(_metric_definition_keys(item))
        return keys
    if isinstance(value, list):
        return [key for item in value for key in _metric_definition_keys(item)]
    return []


def _metric_concept_key(record: Mapping[str, Any], reference: Mapping[str, Any]) -> str:
    raw_query = str(record.get("student_query", "")).lower()
    query = _normalise_text(raw_query)
    if re.search(r"video view", query) and ("%" in raw_query or re.search(r"\b(?:percent|percentage|average)\b", raw_query)):
        return "average_video_completion_percentage"
    patterns = (
        ("reply_network", r"reply network"),
        ("total_chars", r"total chars|total_chars|character"),
        ("resources_views", r"resource view|resource metric"),
        ("debate_replies", r"debate reply"),
        ("debate_posts", r"debate_posts|debate posts"),
        ("debate_views", r"debate view"),
        ("unique_viewers", r"unique|distinct viewer"),
        ("assessment_views", r"assessment"),
        ("lecture_views", r"lecture view|video view"),
    )
    for key, pattern in patterns:
        if re.search(pattern, query):
            return key
    reference_keys = " ".join(_metric_definition_keys(reference)).lower()
    if "resources_views" in reference_keys:
        return "resources_views"
    if "total_chars" in reference_keys:
        return "total_chars"
    if "reply network" in reference_keys:
        return "reply_network"
    if "debate_replies" in reference_keys:
        return "debate_replies"
    if "video views" in reference_keys:
        return "lecture_views"
    return ""


def _contains_concept(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _limitation_present(response: str, boundary_terms: tuple[str, ...]) -> bool:
    for sentence in _course_sentences(response):
        normalised = _normalise_text(sentence)
        if not _contains_concept(normalised, boundary_terms):
            continue
        if re.search(r"\b(?:not|does not|doesn't|cannot|can't|no proof|do not|don't|does not by itself|not by itself)\b", sentence, re.I):
            return True
    return False


def _metric_misuse(response: str, boundary_terms: tuple[str, ...]) -> bool:
    for sentence in _course_sentences(response):
        normalised = _normalise_text(sentence)
        if not _contains_concept(normalised, boundary_terms):
            continue
        if re.search(r"\b(?:not|does not|doesn't|cannot|can't|no proof|do not|don't)\b", sentence, re.I):
            continue
        if re.search(r"\b(?:proves?|guarantees?|demonstrates?|confirms?|means (?:that )?you|shows? (?:that )?you)\b", sentence, re.I):
            return True
    return False


def metric_definition_guard_assessment(
    record: Mapping[str, Any], reference: Mapping[str, Any],
) -> tuple[int, str]:
    query = str(record.get("student_query", "")).lower()
    response = _response_text(record)
    response_normalised = _normalise_text(response)
    metric_key = _metric_concept_key(record, reference)
    concept = METRIC_CONCEPTS.get(metric_key)
    if not concept:
        return 1, "The requested metric could not be mapped to a documented canonical benchmark concept."
    meaning_ok = _contains_concept(response_normalised, concept["entity"]) and _contains_concept(response_normalised, concept["meaning"])
    if not meaning_ok:
        return 1, f"The response did not state the core meaning of canonical metric {metric_key}."
    if _metric_misuse(response, concept["boundary"]):
        return 1, f"The response treated {metric_key} as proof of a learning, quality, completion, or achievement outcome."
    def semantic_numbers(value: str) -> set[str]:
        value = re.sub(r"(?m)^\s*\d+[.)]\s+", "", value).replace(",", "")
        return set(re.findall(r"\d+(?:\.\d+)?", value))

    reference_numbers = semantic_numbers(json.dumps(reference, ensure_ascii=False))
    query_numbers = semantic_numbers(query)
    response_numbers = semantic_numbers(response.lower())
    if response_numbers - reference_numbers - query_numbers:
        return 1, f"The response introduced numerical values absent from the query and frozen reference evidence for {metric_key}."
    if _limitation_present(response, concept["boundary"]):
        return 5, f"The response correctly defined {metric_key} and explicitly preserved its claim boundary."
    return 3, f"The response stated the basic meaning of {metric_key}, but omitted an important claim-boundary limitation."


def metric_definition_guard_score(record: Mapping[str, Any], reference: Mapping[str, Any]) -> int:
    return metric_definition_guard_assessment(record, reference)[0]


def evaluate_record(
    record: Mapping[str, Any], gold: Mapping[str, Any], reference: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    applicable_list = list(gold.get("gold_applicable_mechanism_dimensions") or [])
    applicable = set(applicable_list)
    expected_memory = bool(gold.get("gold_expected_memory"))
    expected_retrieval = bool(gold.get("gold_expected_retrieval"))
    memory_triggered = bool(record.get("memory_triggered") or record.get("predicted_memory_trigger"))
    memory_resolved = bool(record.get("memory_resolved"))
    retrieval_used = bool(record.get("retrieval_used") or record.get("predicted_retrieval_decision"))
    actual_route = str(record.get("selected_route") or record.get("predicted_route", ""))
    expected_route = str(gold.get("gold_expected_route", ""))
    route_ok = route_matches(actual_route, expected_route)
    retrieval_grounding = retrieval_grounding_assessment(record, reference)
    course_context = course_context_assessment(record, reference)
    plan_consistency = plan_state_consistency_assessment(record)
    negative_control = negative_control_assessment(record)
    metric_guard = metric_definition_guard_assessment(record, reference)
    assessments: dict[str, tuple[int, str]] = {
        "route_correctness": (
            5 if route_ok else 1,
            f"Actual route {actual_route or '<empty>'} {'matches' if route_ok else 'does not match'} frozen expected route {expected_route} under the explicit route map.",
        ),
        "memory_activation_correctness": (
            5 if memory_triggered == expected_memory else 1,
            f"Memory activation was {memory_triggered}; frozen expectation was {expected_memory}.",
        ),
        "memory_resolution_accuracy": (
            5 if expected_memory and memory_resolved and expected_item_accuracy(record) else 1,
            "Memory resolved and the referenced items/state fields matched the frozen expectation."
            if expected_memory and memory_resolved and expected_item_accuracy(record)
            else "Expected Memory resolution or referenced items/state fields did not match the frozen expectation.",
        ),
        "retrieval_activation_correctness": (
            5 if retrieval_used == expected_retrieval else 1,
            f"Retrieval activation was {retrieval_used}; frozen expectation was {expected_retrieval}.",
        ),
        "retrieval_grounding": retrieval_grounding if expected_retrieval else (1, "Retrieval grounding is not evaluated when retrieval is not expected."),
        "course_context_use": course_context,
        "negative_control_correctness": negative_control,
        "plan_state_consistency": plan_consistency,
        "metric_definition_guard_correctness": metric_guard,
    }
    scores = {dimension: (assessments[dimension][0] if dimension in applicable else None) for dimension in MECHANISM_DIMENSIONS}
    rationales = {
        dimension: (assessments[dimension][1] if dimension in applicable else None)
        for dimension in MECHANISM_DIMENSIONS
    }
    aggregate = mechanism_score(scores)
    result = {
        "scenario_id": record.get("scenario_id", ""), "mode": record.get("mode", ""),
        "scenario_group": gold.get("gold_scenario_group", ""),
        "applicable_mechanism_dimensions": applicable_list,
        "applicable_dimensions": applicable_list,
        "applicable_dimension_count": len(applicable_list),
        "scores": scores, "rationales": rationales, "mechanism_score": aggregate,
        "judge_failed": False,
        "validation_metadata": {
            "generation_succeeded": bool(record.get("generation_succeeded", True)),
            "score_domain_valid": all(value in {1, 3, 5, None} for value in scores.values()),
            "non_applicable_scores_null": all(scores[dimension] is None for dimension in set(MECHANISM_DIMENSIONS) - applicable),
            "applicable_rationales_present": all(bool(rationales[dimension]) for dimension in applicable),
            "applicable_dimension_count_matches": len(applicable) == sum(value is not None for value in scores.values()),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(), **metadata,
    }
    result.update({f"{dimension}_reason": rationales[dimension] for dimension in MECHANISM_DIMENSIONS})
    return result


def metadata_for(responses: Path, scenarios: Path, gold: Path, reference: Path) -> dict[str, Any]:
    return {
        "mechanism_rubric_version": MECHANISM_RUBRIC_VERSION_V2,
        "gold_label_version": GOLD_LABEL_VERSION,
        "responses_file_sha256": file_sha256(responses), "scenario_set_sha256": file_sha256(scenarios),
        "gold_labels_sha256": file_sha256(gold), "reference_evidence_sha256": file_sha256(reference),
    }


def run_mechanism_evaluation(
    records: list[dict[str, Any]], gold: Mapping[str, Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]], output: Path, metadata: Mapping[str, Any],
    resume: bool, overwrite: bool,
    validate_rows: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> list[dict[str, Any]]:
    expected = {(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in records}
    if len(expected) != len(records):
        raise EvaluationValidationError("duplicate_response_key", "Duplicate response keys")
    rows: list[dict[str, Any]] = []
    completed: set[tuple[str, str]] = set()
    if output.exists():
        if resume:
            rows = load_jsonl(output)
            for row in rows:
                key = (str(row.get("scenario_id", "")), str(row.get("mode", "")))
                if key in completed:
                    raise EvaluationValidationError("duplicate_mechanism_key", str(key))
                if key not in expected or any(row.get(field) != value for field, value in metadata.items()):
                    raise EvaluationValidationError("resume_metadata_mismatch", str(key))
                completed.add(key)
        elif not overwrite:
            raise FileExistsError(f"Output exists: {output}; use --resume or --overwrite")
    for record in records:
        key = (str(record.get("scenario_id", "")), str(record.get("mode", "")))
        if key in completed:
            continue
        if key[0] not in gold or key[0] not in references:
            raise EvaluationValidationError("missing_gold_or_reference", key[0])
        rows.append(evaluate_record(record, gold[key[0]], references[key[0]], metadata))
        completed.add(key)
    if len(rows) != len(expected) or completed != expected:
        raise EvaluationValidationError("incomplete_mechanism_run", f"Expected {len(expected)}, got {len(completed)}")
    if validate_rows is not None:
        validate_rows(rows)
    _atomic_write_jsonl(output, rows)
    return rows


def _atomic_write_jsonl(output: Path, rows: list[dict[str, Any]]) -> None:
    """Durably replace ``output`` only after a complete temporary file is synced."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_formal_response_input(
    records: list[dict[str, Any]], scenario_rows: list[dict[str, Any]], responses_path: Path,
    *,
    enforce_frozen_hash: bool = True,
    expected_scenario_count: int = EXPECTED_SCENARIO_COUNT,
    expected_record_count: int = EXPECTED_RECORD_COUNT,
) -> dict[str, Any]:
    response_hash = file_sha256(responses_path)
    if not enforce_frozen_hash:
        print(
            "WARNING: frozen response hash validation disabled for an explicit local test fixture; "
            "this is not a formal evaluation run.",
            file=sys.stderr,
        )
    if enforce_frozen_hash and response_hash != FROZEN_RESPONSES_SHA256:
        raise EvaluationValidationError(
            "frozen_response_hash_mismatch",
            f"Expected {FROZEN_RESPONSES_SHA256}, got {response_hash}",
        )
    scenario_id_list = [str(row.get("scenario_id", "")) for row in scenario_rows]
    scenario_ids = set(scenario_id_list)
    if len(scenario_rows) != expected_scenario_count or len(scenario_ids) != expected_scenario_count or "" in scenario_ids:
        raise EvaluationValidationError(
            "invalid_scenario_set", f"Expected {expected_scenario_count} unique scenario IDs, got {len(scenario_rows)}/{len(scenario_ids)}",
        )
    expected_pairs = {(scenario_id, mode) for scenario_id in scenario_ids for mode in EXPECTED_MODES}
    actual_pairs = [(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in records]
    counts = Counter(mode for _, mode in actual_pairs)
    failures = [
        key for key, row in zip(actual_pairs, records)
        if row.get("generation_succeeded") is not True or bool(row.get("generation_failed"))
    ]
    empty_responses = [key for key, row in zip(actual_pairs, records) if not _response_text(row).strip()]
    if len(records) != expected_record_count:
        raise EvaluationValidationError("incomplete_response_file", f"Expected {expected_record_count}, got {len(records)}")
    if len(set(actual_pairs)) != expected_record_count:
        raise EvaluationValidationError("duplicate_response_key", f"Responses do not contain {expected_record_count} unique keys")
    if set(actual_pairs) != expected_pairs:
        missing = sorted(expected_pairs - set(actual_pairs))
        extra = sorted(set(actual_pairs) - expected_pairs)
        raise EvaluationValidationError("response_pair_mismatch", f"missing={missing[:5]}; extra={extra[:5]}")
    if any(counts.get(mode) != len(scenario_ids) for mode in EXPECTED_MODES):
        raise EvaluationValidationError("mode_count_mismatch", str(dict(counts)))
    if failures:
        raise EvaluationValidationError("generation_failures_present", str(failures[:5]))
    if empty_responses:
        raise EvaluationValidationError("empty_final_responses", str(empty_responses[:5]))
    return {
        "responses_file_sha256": response_hash,
        "record_count": len(records),
        "unique_key_count": len(set(actual_pairs)),
        "records_per_mode": {mode: counts[mode] for mode in EXPECTED_MODES},
        "generation_failure_count": len(failures),
        "empty_response_count": len(empty_responses),
        "expected_pairs_complete": True,
    }


def validate_gold_reference_inputs(
    records: list[dict[str, Any]], gold_rows: list[dict[str, Any]], reference_rows: list[dict[str, Any]],
    *, expected_scenario_count: int = EXPECTED_SCENARIO_COUNT,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate complete, reviewed 62-scenario overlays before any scoring."""

    gold = rows_by_id(gold_rows)
    references = rows_by_id(reference_rows)
    response_ids = {str(row.get("scenario_id", "")) for row in records}
    if len(gold) != expected_scenario_count:
        raise EvaluationValidationError("incomplete_gold_overlay", f"Expected {expected_scenario_count} unique gold rows, got {len(gold)}")
    if len(references) != expected_scenario_count:
        raise EvaluationValidationError("incomplete_reference_overlay", f"Expected {expected_scenario_count} unique reference rows, got {len(references)}")
    if response_ids != set(gold) or response_ids != set(references):
        raise EvaluationValidationError(
            "overlay_scenario_mismatch",
            f"responses={len(response_ids)} gold={len(gold)} references={len(references)}",
        )
    completed_statuses = {"approved", "revised"}
    for scenario_id, row in gold.items():
        status = str(row.get("gold_review_status", "")).strip().lower()
        if status not in completed_statuses:
            raise EvaluationValidationError("pending_gold_review", f"{scenario_id}: {status or 'missing'}")
        applicable = row.get("gold_applicable_mechanism_dimensions")
        if not isinstance(applicable, list) or not applicable:
            raise EvaluationValidationError("missing_applicable_mechanism_dimensions", scenario_id)
        unknown = set(applicable) - set(MECHANISM_DIMENSIONS)
        if unknown:
            raise EvaluationValidationError("unknown_applicable_mechanism_dimensions", f"{scenario_id}: {sorted(unknown)}")
    for scenario_id, row in references.items():
        statuses = [row.get(field) for field in ("review_status", "reference_review_status") if field in row]
        if not statuses or any(str(status).strip().lower() not in completed_statuses for status in statuses):
            raise EvaluationValidationError("pending_reference_review", f"{scenario_id}: {statuses or ['missing']}")
    return gold, references


def validate_mechanism_output(
    rows: list[dict[str, Any]], expected_pairs: set[tuple[str, str]], metadata: Mapping[str, Any],
) -> dict[str, Any]:
    keys = [(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in rows]
    mode_counts = Counter(mode for _, mode in keys)
    if len(rows) != EXPECTED_RECORD_COUNT or len(set(keys)) != EXPECTED_RECORD_COUNT or set(keys) != expected_pairs:
        raise EvaluationValidationError("invalid_v2_output_keys", f"records={len(rows)} unique={len(set(keys))}")
    if any(mode_counts.get(mode) != 62 for mode in EXPECTED_MODES):
        raise EvaluationValidationError("invalid_v2_mode_counts", str(dict(mode_counts)))
    failures: list[tuple[str, str]] = []
    for key, row in zip(keys, rows):
        if row.get("judge_failed"):
            failures.append(key)
        if any(row.get(field) != value for field, value in metadata.items()):
            raise EvaluationValidationError("v2_metadata_mismatch", str(key))
        applicable = set(row.get("applicable_mechanism_dimensions") or [])
        scores = row.get("scores") or {}
        rationales = row.get("rationales") or {}
        if set(scores) != set(MECHANISM_DIMENSIONS) or set(rationales) != set(MECHANISM_DIMENSIONS):
            raise EvaluationValidationError("invalid_v2_dimension_fields", str(key))
        for dimension in MECHANISM_DIMENSIONS:
            value = scores[dimension]
            if dimension in applicable:
                if type(value) is not int or value not in {1, 3, 5}:
                    raise EvaluationValidationError("invalid_v2_applicable_score", f"{key} {dimension}={value!r}")
                if not str(rationales[dimension] or "").strip():
                    raise EvaluationValidationError("missing_v2_rationale", f"{key} {dimension}")
            elif value is not None or rationales[dimension] is not None:
                raise EvaluationValidationError("non_applicable_v2_value", f"{key} {dimension}")
        expected_score = mechanism_score(scores)
        if row.get("mechanism_score") != expected_score:
            raise EvaluationValidationError("v2_aggregate_mismatch", f"{key}: {row.get('mechanism_score')} != {expected_score}")
        if row.get("applicable_dimension_count") != len(applicable):
            raise EvaluationValidationError("v2_applicable_count_mismatch", str(key))
        if not all((row.get("validation_metadata") or {}).values()):
            raise EvaluationValidationError("v2_validation_metadata_failed", str(key))
    if failures:
        raise EvaluationValidationError("v2_failed_records", str(failures[:5]))
    return {
        "record_count": len(rows), "unique_key_count": len(set(keys)),
        "records_per_mode": {mode: mode_counts[mode] for mode in EXPECTED_MODES},
        "judge_failed_count": len(failures), "all_scores_and_rationales_valid": True,
        "all_mechanism_means_valid": True,
    }


def _score_distributions(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    for mode in EXPECTED_MODES:
        result[mode] = {}
        mode_rows = [row for row in rows if row.get("mode") == mode]
        for dimension in MECHANISM_DIMENSIONS:
            counts = Counter(row.get("scores", {}).get(dimension) for row in mode_rows)
            result[mode][dimension] = {str(key): counts[key] for key in (1, 3, 5, None) if counts[key]}
    return result


def write_spot_check_report(
    response_rows: list[dict[str, Any]], output_rows: list[dict[str, Any]], references: Mapping[str, Mapping[str, Any]],
) -> None:
    response_index = {(str(row["scenario_id"]), str(row["mode"])): row for row in response_rows}
    output_index = {(str(row["scenario_id"]), str(row["mode"])): row for row in output_rows}
    pairs = [
        ("U058", "CR"), ("U058", "C_FULL"), ("U060", "CR"), ("U060", "C_FULL"),
        ("U039", "CR"), ("U039", "C_FULL"), ("U059", "CR"), ("U059", "C_FULL"),
    ]
    lines = [
        "# Mechanism v2 course-claim spot check", "",
        "This report applies the general v2 claim-scope rules; it does not hard-code scenario scores.", "",
    ]
    for key in pairs:
        record = response_index[key]
        scored = output_index[key]
        reference = references[key[0]]
        audits = course_claim_audit(record, reference)
        lines.extend([
            f"## {key[0]} — {key[1]}", "",
            f"- Retrieval used: `{bool(record.get('retrieval_used'))}`",
            f"- Retrieval grounding: `{scored['scores'].get('retrieval_grounding')}`",
            f"- Course context use: `{scored['scores'].get('course_context_use')}`",
            f"- Grounding rationale: {scored['rationales'].get('retrieval_grounding')}", "",
            "### Common reference course evidence", "",
        ])
        for chunk in reference.get("reference_course_evidence", []):
            lines.append(f"- `{chunk.get('chunk_id', '')}` — {chunk.get('title', '')}: {str(chunk.get('text', '')).strip()}")
        if not reference.get("reference_course_evidence"):
            lines.append("- None.")
        lines.extend(["", "### Visible response", "", "```text", _response_text(record), "```", "", "### Claim classification", ""])
        if audits:
            for item in audits:
                lines.append(f"- **{item['classification']} / {item['support']}** — {item['claim']}")
        else:
            lines.append("- No material course-factual claim was detected; the visible course-related wording was advisory or non-factual.")
        lines.append("")
    SPOT_CHECK.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_validation_reports(
    input_validation: Mapping[str, Any], output_validation: Mapping[str, Any],
    v1_rows: list[dict[str, Any]], v2_rows: list[dict[str, Any]], v1_hash_before: str, v1_hash_after: str,
) -> None:
    before = _score_distributions(v1_rows)
    after = _score_distributions(v2_rows)
    changed = {
        mode: {
            dimension: {"v1": before[mode][dimension], "v2": after[mode][dimension]}
            for dimension in MECHANISM_DIMENSIONS if before[mode][dimension] != after[mode][dimension]
        }
        for mode in EXPECTED_MODES
    }
    review_candidates = sorted({
        f"{row['scenario_id']}:{row['mode']}"
        for row in v2_rows if row.get("scores", {}).get("retrieval_grounding") == 3
    })
    report = {
        "status": "PASS", "mechanism_rubric_version": MECHANISM_RUBRIC_VERSION_V2,
        "input_validation": dict(input_validation), "output_validation": dict(output_validation),
        "v1_output_path": str(V1_OUTPUT), "v1_sha256_before": v1_hash_before, "v1_sha256_after": v1_hash_after,
        "v1_unchanged": v1_hash_before == v1_hash_after == FROZEN_V1_MECHANISM_SHA256,
        "v2_output_path": str(OUTPUT), "before_distributions": before, "after_distributions": after,
        "changed_distributions": changed,
        "remaining_human_review_candidates": review_candidates,
    }
    VALIDATION_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Mechanism v2 validation report", "", "Status: **PASS**", "",
        f"- Frozen response SHA-256: `{input_validation['responses_file_sha256']}`",
        f"- v2 records / unique keys: {output_validation['record_count']} / {output_validation['unique_key_count']}",
        f"- Failed records: {output_validation['judge_failed_count']}",
        f"- v1 unchanged: `{report['v1_unchanged']}` (`{v1_hash_after}`)",
        f"- Mechanism rubric: `{MECHANISM_RUBRIC_VERSION_V2}`", "",
        "## Before/after applicable-score distributions", "",
        "| Mode | Dimension | v1 | v2 |", "|---|---|---:|---:|",
    ]
    for mode in EXPECTED_MODES:
        for dimension in MECHANISM_DIMENSIONS:
            if before[mode][dimension] != after[mode][dimension]:
                lines.append(f"| {mode} | {dimension} | `{before[mode][dimension]}` | `{after[mode][dimension]}` |")
    lines.extend(["", "## Remaining human-review candidates", ""])
    if review_candidates:
        lines.extend(f"- `{value}` — deterministic grounding score 3 (partial/weak evidence connection)." for value in review_candidates)
    else:
        lines.append("None.")
    VALIDATION_MARKDOWN.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    paths = [
        path if path.is_absolute() else PROJECT_ROOT / path
        for path in (args.responses, args.scenarios, args.gold_labels, args.reference_evidence, args.output)
    ]
    responses, scenarios, gold_path, reference_path, output = paths
    validate_output_destination(output)
    v1_hash_before = file_sha256(V1_OUTPUT)
    if v1_hash_before != FROZEN_V1_MECHANISM_SHA256:
        raise EvaluationValidationError(
            "frozen_v1_hash_mismatch", f"Expected {FROZEN_V1_MECHANISM_SHA256}, got {v1_hash_before}",
        )
    response_rows = load_jsonl(responses)
    scenario_rows = load_jsonl(scenarios)
    input_validation = validate_formal_response_input(response_rows, scenario_rows, responses)
    gold, references = validate_gold_reference_inputs(
        response_rows, load_jsonl(gold_path), load_jsonl(reference_path),
    )
    metadata = metadata_for(responses, scenarios, gold_path, reference_path)
    expected_pairs = {(str(row["scenario_id"]), mode) for row in scenario_rows for mode in EXPECTED_MODES}
    rows = run_mechanism_evaluation(
        response_rows, gold, references, output, metadata, args.resume, args.overwrite,
        validate_rows=lambda candidate: validate_mechanism_output(candidate, expected_pairs, metadata),
    )
    output_validation = validate_mechanism_output(rows, expected_pairs, metadata)
    v1_hash_after = file_sha256(V1_OUTPUT)
    if v1_hash_after != v1_hash_before:
        raise EvaluationValidationError("frozen_v1_modified", f"before={v1_hash_before}; after={v1_hash_after}")
    v1_rows = load_jsonl(V1_OUTPUT)
    write_validation_reports(input_validation, output_validation, v1_rows, rows, v1_hash_before, v1_hash_after)
    write_spot_check_report(response_rows, rows, references)
    print(
        f"Mechanism v2 evaluation complete: {len(rows)} records; "
        f"input_sha256={input_validation['responses_file_sha256']}; saved to {output}"
    )


if __name__ == "__main__":
    main()
