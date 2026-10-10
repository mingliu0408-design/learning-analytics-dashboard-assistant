"""Simple non-LLM metrics for offline response diagnostics."""

from __future__ import annotations

import re
from typing import Any, Mapping


DASHBOARD_EVIDENCE_TERMS = (
    "dashboard",
    "data",
    "metric",
    "view",
    "views",
    "post",
    "posts",
    "reply",
    "replies",
    "network",
    "resources",
    "resource",
    "lecture",
    "video",
    "panopto",
    "moodle",
    "reflection",
    "gdocs",
    "week",
    "weeks",
    "activity",
    "engagement",
    "count",
    "counts",
)

GENERIC_PHRASES = (
    "keep up the good work",
    "stay motivated",
    "try your best",
    "great question",
    "it depends",
    "be proactive",
    "manage your time",
    "study harder",
    "review regularly",
    "make a plan",
    "set a goal",
)

UNCERTAINTY_PATTERNS = (
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bnot necessarily\b",
    r"\bdoes not prove\b",
    r"\bdo not prove\b",
    r"\bdoesn't prove\b",
    r"\bmay\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\blimitation\b",
    r"\blimitations\b",
    r"\buncertain\b",
    r"\bnot a direct measure\b",
    r"\bnot directly measure\b",
)

ACTION_STEP_PATTERNS = (
    r"^\s*\d+[\).\s-]",
    r"^\s*[-*]\s+",
    r"\btry\b",
    r"\baim to\b",
    r"\bconsider\b",
    r"\bplan\b",
    r"\bset aside\b",
    r"\breview\b",
    r"\bwatch\b",
    r"\breply\b",
    r"\bwrite\b",
)


def compute_automatic_metrics(
    generated_response: str,
    evidence_summary: Mapping[str, Any] | None = None,
    student_query: str = "",
) -> dict[str, Any]:
    """Compute simple diagnostics for a generated assistant response."""

    text = generated_response or ""
    return {
        "response_length_words": response_length_words(text),
        "number_of_action_steps": number_of_action_steps(text),
        "number_of_dashboard_evidence_mentions": number_of_dashboard_evidence_mentions(text),
        "number_of_generic_phrases": number_of_generic_phrases(text),
        "has_uncertainty_statement": has_uncertainty_statement(text),
        "simple_overlap_with_evidence": simple_overlap_with_evidence(text, evidence_summary or {}),
        "has_internal_error_message": has_internal_error_message(text),
        "answers_question_heuristic": answers_question_heuristic(student_query, text),
    }


def response_length_words(text: str) -> int:
    """Count word-like tokens."""

    return len(re.findall(r"\b[\w%'-]+\b", text or ""))


def number_of_action_steps(text: str) -> int:
    """Estimate how many actionable suggestions appear in the response."""

    count = 0
    for line in (text or "").splitlines():
        line_l = line.lower()
        if any(re.search(pattern, line_l) for pattern in ACTION_STEP_PATTERNS):
            count += 1
    return count


def number_of_dashboard_evidence_mentions(text: str) -> int:
    """Count occurrences of dashboard/evidence terms."""

    lowered = (text or "").lower()
    count = 0
    for term in DASHBOARD_EVIDENCE_TERMS:
        count += len(re.findall(rf"\b{re.escape(term)}\b", lowered))
    return count


def number_of_generic_phrases(text: str) -> int:
    """Count common generic advice phrases."""

    lowered = (text or "").lower()
    return sum(lowered.count(phrase) for phrase in GENERIC_PHRASES)


def has_uncertainty_statement(text: str) -> bool:
    """Check for explicit uncertainty or limitation wording."""

    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in UNCERTAINTY_PATTERNS)


def has_internal_error_message(text: str) -> bool:
    """Flag internal failure/fallback wording that should not reach students."""

    lowered = (text or "").lower()
    internal_patterns = (
        r"\btraceback\b",
        r"\bexception\b",
        r"\bnot supported by the rq1 evidence synthesiser\b",
        r"\brq1 evidence synthesiser\b",
        r"\brq1 evidence synthesis could not\b",
        r"\brecommendation planning could not\b",
        r"\bunsupported page\b",
        r"\bpage '[^']+' is not supported\b",
        r"\bnonetype\b",
        r"\bkeyerror\b",
        r"\bvalueerror\b",
    )
    return any(re.search(pattern, lowered) for pattern in internal_patterns)


def answers_question_heuristic(query: str, response: str) -> bool:
    """Weakly estimate whether the response addresses the query intent.

    This is only a diagnostic for triage. It intentionally uses transparent
    keyword rules rather than pretending to judge semantic correctness.
    """

    q = (query or "").lower()
    r = (response or "").lower()
    if not q or not r or has_internal_error_message(r):
        return False

    if re.search(r"\b(what does|what do|mean|means|count as|definition|define)\b", q):
        return bool(re.search(r"\b(mean|means|count|counts|refers to|is|are|measured|metric)\b", r))
    if re.search(r"\b(based|source|from|collected|measured|tracked|accurate|data)\b", q):
        return bool(re.search(r"\b(based|source|comes from|collected|measured|tracked|logs|data|limitations?)\b", r))
    if re.search(r"\b(access|full|visibility|email subscription|read by email)\b", q):
        return bool(re.search(r"\b(cannot|can't|does not|do not|not appear|access|visible|visibility|email)\b", r))
    if re.search(r"\b(not reflected|not showing|missing|completed|submitted)\b", q):
        return bool(re.search(r"\b(not shown|not include|may not capture|submission|official|instructor|platform)\b", r))
    if re.search(r"\b(plan|next week|10-day|catch up|schedule|strategy)\b", q):
        return bool(re.search(r"\b(day|week|plan|step|next|focus|schedule)\b", r))
    if re.search(r"\b(improve|suggest|recommend|advice|better|what should i do|how can i)\b", q):
        return bool(re.search(r"\b(step|try|recommend|suggest|useful|action|next|focus)\b", r))
    if re.search(r"\b(structure|template|outline|format)\b", q):
        return bool(re.search(r"\b(what happened|what did i learn|evidence|what will i do next|structure)\b", r))
    if re.search(r"\b(about|talked about|covered|content)\b", q):
        return bool(re.search(r"\b(about|metadata|title|lecture|content|transcript|recording)\b", r))

    query_tokens = _content_tokens(q)
    response_tokens = _content_tokens(r)
    if not query_tokens:
        return True
    return len(query_tokens.intersection(response_tokens)) >= 1


def simple_overlap_with_evidence(
    text: str,
    evidence_summary: Mapping[str, Any],
) -> float:
    """Compute a rough token overlap ratio between response and evidence.

    This is a weak diagnostic only. It helps flag responses that mention none
    of the selected evidence terms, but it is not a quality score.
    """

    evidence_text = _flatten_to_text(evidence_summary)
    evidence_tokens = _content_tokens(evidence_text)
    if not evidence_tokens:
        return 0.0

    response_tokens = _content_tokens(text)
    overlap = evidence_tokens.intersection(response_tokens)
    return round(len(overlap) / len(evidence_tokens), 3)


def _flatten_to_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_flatten_to_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_to_text(v) for v in value)
    return str(value)


def _content_tokens(text: str) -> set[str]:
    stopwords = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "this",
        "that",
        "it",
        "as",
        "by",
        "be",
        "not",
    }
    return {
        token
        for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_%'-]+\b", text.lower())
        if len(token) > 2 and token not in stopwords
    }
