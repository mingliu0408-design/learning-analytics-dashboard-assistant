"""Canonical, facet-aware deterministic query analysis for Retrieval v2.4."""

from __future__ import annotations

import re

from utils.retrieval_v2.query_analysis import analyse_query as analyse_query_v23

from .models import QueryFacetV24, QueryPlanV24


_TYPO_NORMALISATIONS = {
    "multimodle": "multimodal",
    "multimodel": "multimodal",
}


def _normalise_typos(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+|[^A-Za-z0-9]+", query)
    normalised: list[str] = []
    for token in tokens:
        normalised.append(_TYPO_NORMALISATIONS.get(token.casefold(), token))
    return "".join(normalised)


def _canonical_query(base: object, original: str, intents: tuple[str, ...]) -> str:
    normalised = _normalise_typos(original.replace("_", " "))
    additions: list[str] = []
    week = getattr(base, "week", None)
    if week:
        additions.append(week)
    material = getattr(base, "material_type", None)
    if material == "lecture":
        additions.extend(["lecture", "title"])
        if "identify_topic" in intents:
            additions.extend(["lecture overview", "learning outcomes", "topic"])
        if "find_link" in intents:
            additions.extend(["lecture URL", "link"])
    elif material == "assessment":
        additions.extend(["Part A reflection guidance", "assessment guidance", "reflective writing"])
        if "find_link" in intents:
            additions.extend(["assessment URL", "Moodle link"])
    elif material == "moodle_link":
        additions.extend(["Moodle URL", "assessment link"])
    elif material == "reading":
        additions.extend(["reading list", "reading metadata"])
        if "identify_source" in intents:
            additions.extend(["core reading", "first listed"])
    elif material == "reflection":
        additions.extend(["reflection prompt", "reflection guidance"])
    part = getattr(base, "assessment_part", None)
    if part:
        additions.append(part)
    author = getattr(base, "named_author", None)
    title = getattr(base, "named_title", None)
    if author:
        additions.append(author)
    if title:
        additions.append(title)
    if "apply_to_reflection" in intents:
        additions.extend(["lecture overview", "learning outcomes", "reflection prompt"])
    return " ".join(dict.fromkeys(part.strip() for part in [normalised, *additions] if part.strip()))


def analyse_query_v24(query: str, query_type: str | None = None) -> QueryPlanV24:
    original = str(query or "").strip()
    base = analyse_query_v23(original, query_type)
    q = original.casefold().replace("_", " ")
    intents = list(base.intents)
    if re.search(r"\b(?:show|open|take me to)\b", q) and "find_link" not in intents:
        intents.append("find_link")
    if base.material_type == "lecture" and re.search(
        r"\b(?:topics?|about|focus|learning outcomes?|say about)\b", q
    ):
        intents.append("identify_topic")
    if base.material_type == "lecture" and re.search(
        r"\b(?:what|which).*\blecture\b.*\b(?:listed|title)\b|\bshow\b.*\blecture\b",
        q,
    ):
        intents.append("identify_lecture")
    if "lecture" in q and "reflection" in q and re.search(r"\b(?:apply|relate|use|connect)\b", q):
        intents.append("apply_to_reflection")

    dashboard_only = bool(
        re.search(
            r"\b(?:resources? views?|assessment views?|debate views?|video views?|"
            r"reply network|view network|total chars?|absstrcount)\b",
            q,
        )
    ) and "combine_dashboard_course" not in intents
    unknown_course_request = bool(
        re.search(
            r"\bwhat (?:does|do) (?:the )?(?:module|course materials?) say about\b|"
            r"\bis .+ covered in (?:the )?course\b|"
            r"\bfind (?:course|module) information about\b|"
            r"\b(?:find|locate|identify)\b.{0,80}\b(?:teaching material|indexed (?:course )?(?:material|evidence))\b|"
            r"\b(?:supplied )?course guidance\b|"
            r"\bwhich source is listed for\b",
            q,
        )
    )
    retrieval_requested = False if dashboard_only else bool(
        base.retrieval_requested or unknown_course_request
    )

    facets: list[QueryFacetV24] = []
    week = base.week
    minimum = base.minimum_evidence_level
    intents_tuple = tuple(dict.fromkeys(intents))
    if "apply_to_reflection" in intents_tuple:
        facets.extend(
            [
                QueryFacetV24(
                    "lecture_content",
                    "lecture_content",
                    week,
                    ("lecture_overview", "lecture_learning_outcomes"),
                    "excerpt",
                    "identify_topic",
                ),
                QueryFacetV24(
                    "reflection_prompt",
                    "reflection_prompt",
                    week,
                    ("reflection_prompt",),
                    "excerpt",
                    "apply_to_reflection",
                ),
            ]
        )
    elif base.material_type == "lecture":
        link_first = "find_link" in intents_tuple
        roles = (
            ("lecture_link", "lecture_overview", "lecture_learning_outcomes")
            if link_first
            else ("lecture_overview", "lecture_learning_outcomes", "lecture_link")
        )
        facet_intent = (
            "find_link" if link_first
            else "identify_topic" if "identify_topic" in intents_tuple
            else "identify_lecture"
        )
        facets.append(QueryFacetV24("lecture", "lecture", week, roles, minimum, facet_intent))
    elif base.material_type in {"assessment", "moodle_link"}:
        roles = (
            ("part_a_reflection_guidance", "assessment_link", "moodle_link", "assessment_guidance")
            if "find_link" in intents_tuple
            else ("part_a_reflection_guidance", "assessment_guidance", "assessment_link")
        )
        facets.append(
            QueryFacetV24(
                "assessment",
                "assessment",
                week,
                roles,
                minimum,
                "find_link" if "find_link" in intents_tuple else "assessment_guidance",
            )
        )
    elif base.material_type == "reflection":
        facets.append(
            QueryFacetV24(
                "reflection", "reflection", week, ("reflection_prompt", "assessment_guidance"), minimum, "reflection_prompt"
            )
        )
    elif base.material_type == "reading":
        facets.append(
            QueryFacetV24(
                "reading", "reading", week, ("reading_list", "reading_metadata"), minimum,
                "reading_content" if minimum in {"excerpt", "full_text"} else "identify_reading",
            )
        )
    elif base.material_type == "debate":
        facets.append(QueryFacetV24("debate", "debate", week, ("debate_prompt",), minimum, "debate_prompt"))
    else:
        facets.append(QueryFacetV24("course", "course", week, (), minimum, "course_search"))

    canonical = _canonical_query(base, original, intents_tuple)
    reason = (
        "Dashboard-only metric question; course retrieval is not applicable."
        if dashboard_only
        else "Explicit unknown-topic course request detected; retrieval must search before returning no_result."
        if unknown_course_request and not base.retrieval_requested
        else base.reason
    )
    return QueryPlanV24(
        original_query=original,
        canonical_retrieval_query=canonical,
        retrieval_requested=retrieval_requested,
        week=base.week,
        material_type=base.material_type,
        assessment_part=base.assessment_part,
        named_author=base.named_author,
        named_title=base.named_title,
        intents=intents_tuple,
        minimum_evidence_level=minimum,
        reliable_filters=base.reliable_filters,
        dashboard_evidence_requested=base.dashboard_evidence_requested,
        facets=tuple(facets),
        reason=reason,
    )
