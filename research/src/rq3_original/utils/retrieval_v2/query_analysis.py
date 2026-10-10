"""Deterministic query planning and conservative metadata constraints."""

from __future__ import annotations

import re

from .models import QueryPlanV2


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _week(query: str) -> str | None:
    match = re.search(r"\b(?:w\s*|week\s*)(\d{1,2})\b", query, re.I)
    if match:
        return f"W{int(match.group(1))}"
    words = "|".join(_NUMBER_WORDS)
    match = re.search(rf"\bweek\s+({words})\b", query, re.I)
    return f"W{_NUMBER_WORDS[match.group(1).lower()]}" if match else None


def _material_type(query: str) -> str | None:
    q = query.casefold()
    patterns = (
        ("moodle_link", r"\b(?:moodle|course|session|recording)\s+link\b|\burl\b"),
        ("handbook", r"\bhandbook\b"),
        ("assessment", r"\b(?:assessment|assignment|marking criteria|part\s+[ab])\b"),
        ("lecture", r"\b(?:lecture|slides?|recorded video|pre-recorded)\b"),
        ("reflection", r"\b(?:reflection|reflective|portfolio)\b"),
        ("debate", r"\b(?:debate|forum)\b"),
        ("reading", r"\b(?:reading|paper|article|citation|literature)\b"),
        ("weekly_page", r"\bweekly page\b"),
    )
    for material, pattern in patterns:
        if re.search(pattern, q):
            return material
    return None


def _intents(query: str) -> tuple[str, ...]:
    q = query.casefold()
    found: list[str] = []
    patterns = (
        ("find_link", r"\b(?:where|find|locate|link|url|access)\b"),
        ("explain_findings", r"\b(?:findings?|results?|conclusions?|main arguments?)\b"),
        ("explain_methods", r"\b(?:methods?|methodology|how did (?:the )?(?:authors?|paper|study))\b"),
        ("summarise_content", r"\b(?:summari[sz]e|summary|about|content|topics?|say about)\b"),
        ("retrieve_assessment_criteria", r"\b(?:assessment|marking) criteria\b"),
        ("obtain_task_guidance", r"\b(?:guidance|how should i|apply|task|prompt|structure)\b"),
        ("identify_source", r"\b(?:which|what|identify|title|author|listed first|review first)\b"),
        ("combine_dashboard_course", r"\b(?:dashboard|views?|engagement|activity|analytics feedback)\b.*\b(?:course|lecture|reading|reflection|debate)\b|\b(?:course|lecture|reading)\b.*\b(?:dashboard|views?|engagement|activity|analytics feedback)\b"),
    )
    for intent, pattern in patterns:
        if re.search(pattern, q):
            found.append(intent)
    return tuple(found)


def _author(query: str) -> str | None:
    et_al = re.search(r"\b([A-Z][A-Za-z'’-]+(?:\s+(?:and|&|et\s+al\.?))?)\s*(?:\(?(?:19|20)\d{2}\)?)", query)
    if et_al:
        return et_al.group(1).strip()
    possessive = re.search(r"\b([A-Z][A-Za-z'’-]+(?:\s+et\s+al\.?)?)['’]s\s+(?:paper|reading|study)", query)
    return possessive.group(1).strip() if possessive else None


def _named_title(query: str) -> str | None:
    quoted = re.search(r"[\"“]([^\"”]{4,160})[\"”]", query)
    return quoted.group(1).strip() if quoted else None


def analyse_query(query: str, query_type: str | None = None) -> QueryPlanV2:
    """Create a claim-sensitive QueryPlanV2 without over-filtering."""

    query = str(query or "").strip()
    q = query.casefold().replace("_", " ")
    week = _week(query)
    intents = _intents(query)
    material = _material_type(query)
    material_is_explicit = material is not None
    author = _author(query)
    named_title = _named_title(query)
    if material is None and author and any(
        intent in intents for intent in {"explain_findings", "explain_methods", "summarise_content"}
    ):
        material = "reading"
    part_match = re.search(r"\bpart\s*([ab])\b", q)
    part = f"Part {part_match.group(1).upper()}" if part_match else None

    dashboard_metric = bool(
        re.search(
            r"\b(?:resources? views?|assessment views?|debate views?|video views?|reply network|view network|total chars?|absstrcount)\b",
            q,
        )
    )
    explicit_course = bool(
        material
        or author
        or named_title
        or re.search(r"\b(?:course|module) materials?\b|\bweek\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b|\bw\d+\b", q)
    )
    hybrid = "combine_dashboard_course" in intents
    retrieval_requested = bool(explicit_course and (not dashboard_metric or hybrid))
    if dashboard_metric and not hybrid:
        retrieval_requested = False

    content_intents = {"explain_findings", "explain_methods"}
    if any(intent in content_intents for intent in intents):
        minimum = "full_text"
    elif "obtain_task_guidance" in intents and "find_link" not in intents:
        minimum = "excerpt"
    elif "summarise_content" in intents and material not in {"lecture", None}:
        minimum = "excerpt"
    else:
        minimum = "title_and_metadata"

    reliable: list[str] = []
    if week:
        reliable.append("week")
    if material and material_is_explicit:
        reliable.append("material_type")
    if part:
        reliable.append("assessment_part")
    reason = (
        "Dashboard-only metric question; course retrieval is not applicable."
        if dashboard_metric and not hybrid
        else "Explicit course-material intent detected."
        if retrieval_requested
        else "No explicit course-material retrieval intent detected."
    )
    return QueryPlanV2(
        query=query,
        retrieval_requested=retrieval_requested,
        week=week,
        material_type=material,
        assessment_part=part,
        named_author=author,
        named_title=named_title,
        intents=intents,
        minimum_evidence_level=minimum,
        reliable_filters=tuple(reliable),
        dashboard_evidence_requested=dashboard_metric or hybrid,
        reason=reason,
    )
