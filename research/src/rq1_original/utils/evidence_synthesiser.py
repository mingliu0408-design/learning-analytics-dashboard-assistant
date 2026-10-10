"""Selective dashboard evidence synthesis for the GenAI assistant.

This module implements the RQ1 layer: choose a small, relevant subset of
dashboard evidence for a student query. It deliberately does not call an LLM
and it does not modify chatbot state. The chatbot can later call
``synthesise_evidence`` before constructing its prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

import pandas as pd

from utils.course_metadata import LECTURE_METADATA_BY_WEEK, lecture_titles_by_week
from utils.dashboard_domain_resolver import (
    detect_explicit_dashboard_domains,
    resolve_dashboard_scope,
)
from utils.intent_schema import (
    LEGACY_QUERY_TYPES,
    DeterministicIntentResult,
    IntentReasonCode,
)


# Backward-compatible public alias.  The canonical ordered contract lives in
# ``intent_schema`` so the legacy classifier and future semantic schema cannot
# drift into two independently maintained lists.
QUERY_TYPES = LEGACY_QUERY_TYPES

# Navigation aliases accepted as current-page labels. Query-language domain
# detection is owned exclusively by ``dashboard_domain_resolver``.
PAGE_ALIASES = {
    "overview": "overview",
    "resource": "resources",
    "resources": "resources",
    "moodle": "resources",
    "reading": "resources",
    "readings": "resources",
    "lecture": "lecture",
    "lectures": "lecture",
    "video": "lecture",
    "videos": "lecture",
    "panopto": "lecture",
    "debate": "debate",
    "debates": "debate",
    "forum": "debate",
    "forums": "debate",
    "reflection": "reflection",
    "reflections": "reflection",
    "reflective": "reflection",
    "gdocs": "reflection",
    "google docs": "reflection",
}

PAGE_DISPLAY = {
    "overview": "Overview",
    "resources": "Resources",
    "lecture": "Lecture",
    "debate": "Debate",
    "reflection": "Reflection",
}

METRIC_DEFINITIONS = {
    "resources": {
        "Resources_views": (
            "Number of Moodle resource or reading view events. It shows access "
            "frequency, not whether the material was understood."
        ),
    },
    "lecture": {
        "Video Views": (
            "Number of Panopto video view events for recorded lectures. It shows "
            "watching activity, not learning quality."
        ),
        "Video View %": (
            "Approximate percentage of a lecture video watched. It can indicate "
            "the recorded playback proportion, but not attention or understanding."
        ),
        "Video_clicks": (
            "Number of Moodle clicks on video-related items. It is a platform "
            "access trace, not a direct learning outcome."
        ),
    },
    "debate": {
        "Debate_views": (
            "Number of Moodle debate view events. It shows that debate pages or "
            "posts were opened, not that the student understood or evaluated them."
        ),
        "Debate_posts": (
            "Number of debate posting events or active posting weeks, depending "
            "on the source table. It indicates contribution frequency, not quality."
        ),
        "Debate_replies": (
            "Number of replies made to debate posts. It indicates interaction "
            "frequency, not depth or criticality."
        ),
        "Reply network": (
            "Directed links showing who replied to whom and how often. It shows "
            "interaction structure, not the quality of the exchange."
        ),
        "View network": (
            "Directed links showing who viewed whose debate contributions. It "
            "shows visibility or browsing behaviour, not comprehension."
        ),
    },
    "reflection": {
        "Total_chars": (
            "Total characters edited in the reflection document. It indicates "
            "amount of writing activity, not reflective quality."
        ),
        "absStrCount": (
            "Number of edited characters in Google Docs activity logs. It shows "
            "writing volume and timing, not whether the reflection is good."
        ),
    },
}

DATA_PROVENANCE = {
    "overview": "Overview evidence is a compressed synthesis of Resources, Lecture, Debate, and Reflection activity summaries.",
    "resources": "Resources evidence comes from Moodle logs and aggregate feature counts.",
    "lecture": "Lecture evidence comes from Panopto/Echo360 logs and Moodle video click logs.",
    "debate": "Debate evidence comes from Moodle logs plus reply and view network tables.",
    "reflection": "Reflection evidence comes from Google Docs activity logs and cohort time-series data.",
}

METRIC_QUERY_ALIASES = {
    "resources": {
        "Resources_views": ("resource view", "resource views", "reading view", "moodle view"),
    },
    "lecture": {
        "Video Views": ("video view", "video views", "lecture view", "panopto view"),
        "Video View %": ("view percent", "view percentage", "watched percent", "watched percentage"),
        "Video_clicks": ("video click", "video clicks", "lecture click", "moodle video"),
    },
    "debate": {
        "Debate_views": ("debate view", "debate views", "view count", "views"),
        "Debate_posts": ("debate post", "debate posts", "post count", "posts"),
        "Debate_replies": ("debate reply", "debate replies", "reply count", "replies"),
        "Reply network": ("reply network", "replying network"),
        "View network": ("view network", "viewing network"),
    },
    "reflection": {
        "Total_chars": ("total char", "total chars", "total character", "total characters"),
        "absStrCount": ("edited character", "edited characters", "writing volume", "character count"),
    },
}


@dataclass(frozen=True)
class DashboardData:
    """Container for dashboard datasets used by the evidence synthesiser.

    All fields are optional except the core activity tables. Passing empty
    DataFrames is acceptable; the synthesiser will report missing evidence
    rather than failing.
    """

    moodle: pd.DataFrame
    echo: pd.DataFrame
    gdocs: pd.DataFrame
    features: pd.DataFrame
    reply_network: pd.DataFrame | None = None
    view_network: pd.DataFrame | None = None
    gdocs_ts: pd.DataFrame | None = None
    course_context: Mapping[str, str] | None = None
    goals: pd.DataFrame | None = None
    reflections: pd.DataFrame | None = None


def classify_query_detailed(query: str) -> DeterministicIntentResult:
    """Classify a query and expose which unchanged legacy branch returned it.

    The classifier is intentionally transparent and rule-based. This makes it
    suitable for dissertation evaluation because each classification can be
    inspected, challenged, and refined without changing model behaviour.
    """

    original_query = str(query or "")
    q = _normalise_text(query)

    def result(
        legacy_query_type: str,
        reason: IntentReasonCode,
        rule_family: str,
        *,
        match_kind: str = "pattern",
        classification_strength: str = "explicit",
        is_default_fallback: bool = False,
        is_empty_query: bool = False,
    ) -> DeterministicIntentResult:
        return DeterministicIntentResult(
            original_query=original_query,
            normalised_query=q,
            legacy_query_type=legacy_query_type,
            rule_id=reason.value,
            rule_family=rule_family,
            match_kind=match_kind,
            is_explicit_match=not is_default_fallback,
            is_default_fallback=is_default_fallback,
            is_empty_query=is_empty_query,
            classification_strength=classification_strength,
            reason_codes=(reason.value,),
        )

    if not q:
        return result(
            "dashboard_interpretation",
            IntentReasonCode.EMPTY_QUERY_DEFAULT,
            "fallback",
            match_kind="empty_default",
            classification_strength="default",
            is_default_fallback=True,
            is_empty_query=True,
        )

    if _matches_any(
        q,
        (
            r"\bwhat (?:is|was|'s) my (?:current |previous )?goal\b",
            r"\bwhat (?:exact )?(?:time )?constraint did i give\b",
            r"\bwhat actions? have i completed\b",
            r"\bwhat is my next plan step\b",
        ),
    ):
        return result(
            "memory_state_query",
            IntentReasonCode.MEMORY_STATE_PATTERN,
            "memory_state",
        )

    has_course_entity = bool(
        re.search(r"\b(?:w\d{1,2}|week\s*\d{1,2}).*\b(?:lecture|reading)\b|\b(?:lecture|reading)\b.*\b(?:w\d{1,2}|week\s*\d{1,2})\b", q)
        or re.search(r"\b(?:w\d{1,2}|week\s*\d{1,2}).*\b(?:course|module)\s+(?:topic|material|content)\b", q)
        or re.search(r"\b(?:core reading|course material|multimodal learning analytics)\b", q)
    )
    has_planning_intent = bool(
        re.search(
            r"\b(?:how should i use|how can i use|use\b.{0,80}\b(?:in|for) my|"
            r"apply\b.{0,80}\b(?:to|in)|integrate\b.{0,80}\binto)\b",
            q,
        )
    )
    has_dashboard_course_relation = bool(
        re.search(r"\b(?:relate|connect|compare|link)\b", q)
        and re.search(r"\b(?:my|dashboard|activity|engagement|views?|posts?|replies|writing)\b", q)
    )
    if has_course_entity and (has_planning_intent or has_dashboard_course_relation):
        return result(
            "hybrid_course_and_planning",
            IntentReasonCode.HYBRID_COURSE_PLANNING_SIGNAL,
            "hybrid_course_planning",
            match_kind="derived_signal",
            classification_strength="derived",
        )

    if _matches_any(
        q,
        (
            r"\bwhich (?:single|one)?\s*w\d{1,2}\s+(?:core\s+)?reading\b.*\b(?:review|start|read|relevant)\b",
            r"\bchoose one (?:core )?reading from w\d{1,2}\b",
            r"\bwhich (?:single )?core reading from w\d{1,2}\b.*\b(?:review|start|read|first)\b",
            r"\bchoose (?:one |a )?w\d{1,2} core reading\b",
            r"\b(?:which|choose|what is)\b.{0,30}\b(?:paper|reading) (?:from|for) (?:week\s*\d{1,2}|w\d{1,2})\b.*\b(?:first|review|read|start|one)\b",
            r"\bwhat is the first w\d{1,2} (?:paper|reading) i should read\b",
        ),
    ):
        return result(
            "course_content_question",
            IntentReasonCode.COURSE_READING_SELECTION_PATTERN,
            "course_reading_selection",
        )

    if _matches_any(
        q,
        (
            r"\bhow many (?:unique )?(?:real )?lecture videos? (?:have i|did i) view(?:ed)?\b",
            r"\b(?:total|sum|number of)\s+(?:video[- ]view events?|lecture views?)\b",
            r"\bunique\s+(?:lecture )?videos?\s+viewed\b",
            r"\baverage\s+(?:watched|view)\s*(?:percentage|percent|%)\b",
            r"\b(?:my\s+)?lecture completion (?:percentage|percent|%)\b",
            r"\b(?:my\s+)?(?:lecture\s+)?completion rate\b",
            r"\bhow is my lecture completion calculated\b",
            r"\bcalculate my lecture completion rate\b",
            r"\b(?:my\s+)?average watched (?:percentage|percent|%)\b",
            r"\b(?:denominator|numerator|every tracked lecture row|all tracked rows|row-level)\b",
        ),
    ):
        return result(
            "quantitative_metric_query",
            IntentReasonCode.QUANTITATIVE_METRIC_PATTERN,
            "quantitative_metric",
        )

    if _matches_any(
        q,
        (
            r"\b(can you|could you|do you|are you able to).*\b(access|get|see|view|retrieve|read)\b",
            r"\b(access|get access|full pre-recorded|full lecture|lecture transcript|recording content)\b",
            r"\b(no visibility|visibility|read by email|email subscription|outside moodle)\b",
        ),
    ):
        return result(
            "access_or_capability_question",
            IntentReasonCode.ACCESS_CAPABILITY_PATTERN,
            "access_capability",
        )

    if _matches_any(
        q,
        (
            r"\b(not reflected|not showing|doesn't show|does not show|missing from|not captured)\b",
            r"\b(i completed|i did complete|i submitted|i have submitted|i finished)\b",
            r"\b(correct this|correction|incorrect|wrong data)\b",
        ),
    ):
        return result(
            "discrepancy_or_correction",
            IntentReasonCode.DISCREPANCY_CORRECTION_PATTERN,
            "discrepancy_correction",
        )

    if _matches_any(
        q,
        (
            r"\b(reflection|reflective|essay|writing)\b.*\b(structure|template|outline|format|organise|organize|include)\b",
            r"\b(structure|template|outline|format)\b.*\b(reflection|reflective|essay|writing)\b",
        ),
    ):
        return result(
            "reflection_structure_question",
            IntentReasonCode.REFLECTION_STRUCTURE_PATTERN,
            "reflection_structure",
        )

    if _matches_any(
        q,
        (
            r"\b(what|which).*\b(w[0-9]+|week\s*[0-9]+).*\b(lecture|pre-recorded|video).*\b(about|talked about|covered|topics?|content)\b",
            r"\b(what|which).*\b(lecture|pre-recorded|video).*\b(about|talked about|covered|topics?|content)\b",
            r"\b(w[0-9]+|week\s*[0-9]+).*\b(lecture|pre-recorded|video).*\b(about|talked about|covered|topics?|content)\b",
            r"\b(?:explain|summarise|summarize|what is|tell me about).*\b(?:reading|lecture|course material)\b",
            r"\b(?:reading|lecture).*\b(?:explain|detail|about|content|mean)\b",
            r"\b(?:what|which|summarise|summarize|explain).*\b(?:findings?|arguments?|methods?|conclusions?|claims?)\b.*\b(?:reading|paper)\b",
            r"\b(?:reading|paper)\b.*\b(?:findings?|arguments?|methods?|conclusions?|claims?)\b",
            r"\bwhat (?:does|do)\b.{0,40}\b(?:reading|paper)\b.{0,20}\b(?:say|argue|claim|cover)\b",
            r"\bwhat (?:does|do) (?:the )?(?:module|course materials?) say about\b",
            r"\b(?:is .+ covered in (?:the )?course|find (?:course|module) information about)\b",
            r"\bwhich\s+(?:w\d+\s+)?reading\b.*\bshould\s+i\s+(?:review|read|choose)\b",
        ),
    ):
        return result(
            "course_content_question",
            IntentReasonCode.COURSE_CONTENT_PATTERN,
            "course_content",
        )

    if _matches_any(
        q,
        (
            r"\b(relate|related|unrelated|relationship|connected|connection|link|linked)\b",
            r"\b(compare|comparison|between|across|alongside|differ|different|contrast)\b",
            r"\b(correlat|association|associated|affect|impact|influence)\b",
            r"\bline up\b",
        ),
    ):
        return result(
            "cross_page_relationship",
            IntentReasonCode.CROSS_PAGE_RELATIONSHIP_PATTERN,
            "cross_page_relationship",
        )

    if _matches_any(
        q,
        (
            r"\b(where.*data|data.*from|data.*based|source|log|logs|calculated|calculation)\b",
            r"\b(measured|measurement|tracked|recorded|collected|collection|privacy|anonymous)\b",
            r"\b(missing data|no data|download|export|column|table)\b",
            r"\b(accurate|accuracy|reliable|reliability|correct|incorrect|valid|validity)\b",
            r"\b(trust|trustworthy|exact|wrong|error|errors)\b",
        ),
    ):
        return result(
            "technical_data_question",
            IntentReasonCode.TECHNICAL_DATA_PATTERN,
            "technical_data",
        )

    if _is_metric_question(q):
        return result(
            "metric_clarification",
            IntentReasonCode.METRIC_CLARIFICATION_HELPER,
            "metric_clarification",
            match_kind="helper",
            classification_strength="derived",
        )

    if _is_metric_interpretation_question(q):
        return result(
            "dashboard_interpretation",
            IntentReasonCode.DASHBOARD_INTERPRETATION_HELPER,
            "dashboard_interpretation",
            match_kind="helper",
            classification_strength="derived",
        )

    if _matches_any(
        q,
        (
            r"\b(plan|planning|goal|strategy|schedule|routine|habit)\b",
            r"\b(next week|this week|set a goal|time management)\b",
            r"\b(when should i|how often should i)\b",
        ),
    ):
        return result(
            "planning_or_strategy",
            IntentReasonCode.PLANNING_STRATEGY_PATTERN,
            "planning_strategy",
        )

    if _matches_any(
        q,
        (
            r"\b(improve|increase|boost|better|strengthen|work on)\b",
            r"\b(recommend|recommendation|suggest|advice|next step|next steps)\b",
            r"\b(what should i do|how can i|how do i)\b",
        ),
    ):
        return result(
            "improvement_recommendation",
            IntentReasonCode.IMPROVEMENT_RECOMMENDATION_PATTERN,
            "improvement_recommendation",
        )

    if _matches_any(
        q,
        (
            r"\b(why should i care|does this matter|why does it matter)\b",
            r"\b(is this bad|is that bad|am i doing badly|good or bad)\b",
            r"\b(worried|anxious|confused|frustrated|fair|unfair)\b",
        ),
    ):
        return result(
            "emotional_or_justification",
            IntentReasonCode.EMOTIONAL_JUSTIFICATION_PATTERN,
            "emotional_justification",
        )

    return result(
        "dashboard_interpretation",
        IntentReasonCode.UNMATCHED_DEFAULT,
        "fallback",
        match_kind="unmatched_default",
        classification_strength="default",
        is_default_fallback=True,
    )


def classify_query(query: str) -> str:
    """Return the unchanged legacy query-type string for existing callers."""

    return classify_query_detailed(query).legacy_query_type


def select_evidence_sources(
    primary_page: str,
    query_type: str,
    query: str = "",
) -> list[str]:
    """Return source identifiers that should be used for the query.

    Source identifiers have the form ``page.component``. The function selects
    data categories, not raw rows. Raw data is summarised later by
    ``select_evidence``.
    """

    if query_type not in QUERY_TYPES:
        raise ValueError(f"Unknown query_type: {query_type}")

    page = normalise_page(primary_page)
    mentioned_pages = _mentioned_pages(query)
    resolved_scope = resolve_dashboard_scope(query)
    sources: list[str] = []

    def add(page_name: str, component: str) -> None:
        source = f"{page_name}.{component}"
        if source not in sources:
            sources.append(source)

    if query_type == "memory_state_query":
        return sources

    if query_type == "cross_page_relationship" and resolved_scope:
        for scoped_page in resolved_scope:
            add(scoped_page, "activity_summary")
        if "debate" in resolved_scope and "reflection" in resolved_scope:
            add("reflection", "course_task_context")
        return sources

    if page == "overview":
        add("overview", "activity_summary")
        return sources

    if query_type == "hybrid_course_and_planning":
        add(page, "activity_summary")
        return sources

    if query_type == "quantitative_metric_query":
        add("lecture", "metric_definitions")
        add("lecture", "activity_summary")
        add("lecture", "quantitative_metrics")
        add("lecture", "row_records")
        return sources

    if query_type == "metric_clarification":
        add(page, "metric_definitions")
        return sources

    if query_type == "technical_data_question":
        add(page, "metric_definitions")
        add(page, "data_provenance")
        add(page, "data_availability")
        add(page, "data_limitations")
        return sources

    if query_type == "course_content_question":
        add(page, "data_provenance")
        add(page, "course_metadata")
        add(page, "data_limitations")
        return sources

    if query_type == "access_or_capability_question":
        add(page, "data_provenance")
        add(page, "data_availability")
        add(page, "data_limitations")
        return sources

    if query_type == "discrepancy_or_correction":
        add(page, "activity_summary")
        add(page, "data_provenance")
        add(page, "data_limitations")
        return sources

    if query_type == "reflection_structure_question":
        add("reflection", "activity_summary")
        add("lecture", "preparation_summary")
        add("resources", "preparation_summary")
        add("debate", "preparation_summary")
        return sources

    if query_type == "dashboard_interpretation":
        add(page, "metric_definitions")
        add(page, "activity_summary")
        if page == "debate":
            add(page, "network_summary")
        if page == "reflection":
            add(page, "cohort_comparison")
        return sources

    if query_type == "improvement_recommendation":
        add(page, "metric_definitions")
        add(page, "activity_summary")
        for support_page in _supporting_pages_for_improvement(page):
            add(support_page, "preparation_summary")
        return sources

    if query_type == "cross_page_relationship":
        add(page, "activity_summary")
        related = [p for p in mentioned_pages if p != page]
        if not related:
            related = _default_related_pages(page)
        for related_page in related:
            add(related_page, "activity_summary")
        if "debate" in {page, *related} and "reflection" in {page, *related}:
            add("reflection", "course_task_context")
        return sources

    if query_type == "planning_or_strategy":
        add(page, "activity_summary")
        for support_page in _supporting_pages_for_improvement(page):
            add(support_page, "preparation_summary")
        if _matches_any(_normalise_text(query), (r"\b(reflection|reflect|notice|noticed)\b",)):
            add("reflection", "student_reflections")
        if _matches_any(_normalise_text(query), (r"\b(goal|goals|plan|plans)\b",)):
            add("reflection", "student_goals")
        return sources

    if query_type == "emotional_or_justification":
        add(page, "metric_definitions")
        add(page, "activity_summary")
        add(page, "learning_purpose")
        return sources

    return sources


def select_evidence(
    query: str,
    primary_page: str,
    student_id: Any,
    data: DashboardData,
    query_type: str | None = None,
) -> dict[str, Any]:
    """Select and summarise the dashboard evidence for a query.

    This is the main evidence selection function requested for RQ1. It returns
    only the selected evidence, grouped by page, without adding interpretation
    text or prompt instructions.
    """

    qtype = query_type or classify_query(query)
    sources = select_evidence_sources(primary_page, qtype, query)
    return _materialise_sources(sources, student_id, data, query=query)


def synthesise_evidence(
    query: str,
    primary_page: str,
    student_id: Any,
    data: DashboardData,
    target_domain: str = "",
    query_type_override: str = "",
) -> dict[str, Any]:
    """Build a structured evidence summary for a student query.

    The returned dictionary is ready to be inserted into a later chatbot prompt
    or logged for evaluation. It includes the selected evidence and explicit
    uncertainty notes to prevent overclaiming.
    """

    current_page = normalise_page(primary_page)
    explicit_target = detect_explicit_target_domain(query)
    page = normalise_page(target_domain) if target_domain else (explicit_target or current_page)
    qtype = str(query_type_override or classify_query(query))
    if qtype not in QUERY_TYPES:
        raise ValueError(f"Unknown query_type override: {qtype}")
    sources = select_evidence_sources(page, qtype, query)
    selected = _materialise_sources(sources, student_id, data, query=query)

    return {
        "primary_page": PAGE_DISPLAY[page],
        "current_page": PAGE_DISPLAY[current_page],
        "explicit_target_domain": explicit_target,
        "resolved_target_domain": page,
        "primary_evidence_domain": page,
        "supplementary_evidence_domains": _supplementary_domains(sources, page),
        "query": query,
        "query_type": qtype,
        "selected_sources": sources,
        "selected_evidence": selected,
        "interpretation": _build_interpretation(page, qtype, selected),
        "uncertainty": _build_uncertainty(qtype, sources, selected),
    }


def normalise_page(page: str) -> str:
    """Convert a page label or alias to one of the canonical page keys."""

    p = _normalise_text(page)
    if p in PAGE_ALIASES:
        return PAGE_ALIASES[p]
    if p in PAGE_DISPLAY:
        return p
    raise ValueError(f"Unknown dashboard page: {page}")


def detect_explicit_target_domain(query: str) -> str:
    """Detect a dashboard domain explicitly named by the effective query."""

    domains = detect_explicit_dashboard_domains(query)
    return domains[0] if domains else ""


def _supplementary_domains(sources: Sequence[str], primary: str) -> list[str]:
    domains: list[str] = []
    for source in sources:
        domain = source.split(".", 1)[0]
        if domain != primary and domain not in domains:
            domains.append(domain)
    return domains


def _materialise_sources(
    sources: list[str],
    student_id: Any,
    data: DashboardData,
    query: str = "",
) -> dict[str, Any]:
    """Create nested evidence summaries for selected source identifiers."""

    sid = _coerce_student_id(student_id)
    evidence: dict[str, Any] = {}

    for source in sources:
        page, component = source.split(".", 1)
        page_evidence = evidence.setdefault(page, {})

        if component == "metric_definitions":
            page_evidence["metric_definitions"] = _metric_definitions_for_query(page, query)
        elif component == "data_provenance":
            page_evidence["data_provenance"] = DATA_PROVENANCE.get(page)
        elif component == "data_limitations":
            page_evidence["data_limitations"] = _data_limitations_for(page)
        elif component == "course_metadata":
            page_evidence["course_metadata"] = _course_metadata_for(page, data)
        elif component == "data_availability":
            page_evidence["data_availability"] = _summarise_data_availability(page, sid, data)
        elif component == "activity_summary":
            page_evidence["activity_summary"] = _summarise_page_activity(page, sid, data)
        elif component == "quantitative_metrics":
            page_evidence["quantitative_metrics"] = _summarise_lecture_quantitative(sid, data)
        elif component == "row_records":
            quantitative = _summarise_lecture_quantitative(sid, data)
            page_evidence["row_records"] = {
                "available": quantitative["row_level_records_available"],
                "records": quantitative["row_level_records"],
                "availability_note": quantitative["row_level_availability_note"],
            }
        elif component == "network_summary":
            page_evidence["network_summary"] = _summarise_debate_networks(sid, data)
        elif component == "cohort_comparison":
            page_evidence["cohort_comparison"] = _summarise_reflection_cohort(sid, data)
        elif component == "preparation_summary":
            page_evidence["preparation_summary"] = _summarise_preparation(page, sid, data)
        elif component == "course_task_context":
            page_evidence["course_task_context"] = _course_context_for(page, data)
        elif component == "student_reflections":
            page_evidence["student_reflections"] = _summarise_optional_text_table(
                data.reflections,
                preferred_columns=("Reflection", "reflection", "text"),
                label="student reflections",
            )
        elif component == "student_goals":
            page_evidence["student_goals"] = _summarise_optional_text_table(
                data.goals,
                preferred_columns=("Goal", "goal"),
                label="student goals",
            )
        elif component == "learning_purpose":
            page_evidence["learning_purpose"] = _learning_purpose_for(page)

    return evidence


def _summarise_page_activity(
    page: str,
    student_id: int,
    data: DashboardData,
) -> dict[str, Any]:
    """Summarise page-specific activity for one student."""

    if page == "overview":
        return _summarise_overview(student_id, data)
    if page == "resources":
        return _summarise_resources(student_id, data)
    if page == "lecture":
        return _summarise_lecture(student_id, data)
    if page == "debate":
        return _summarise_debate(student_id, data)
    if page == "reflection":
        return _summarise_reflection(student_id, data)
    return {"available": False, "note": "Unknown page."}


def _summarise_resources(student_id: int, data: DashboardData) -> dict[str, Any]:
    moodle = _student_rows(data.moodle, student_id)
    resource_logs = moodle[moodle.get("Event").eq("Resources_views")] if not moodle.empty else pd.DataFrame()
    feature = _feature_row(data.features, student_id)

    return {
        "available": not resource_logs.empty or bool(feature),
        "views": _feature_value(feature, "Resources_views", default=len(resource_logs)),
        "active_weeks": _unique_count(resource_logs, "Week"),
        "active_week_list": _week_list(resource_logs, "Week"),
        "most_active_day": _mode_value(resource_logs, "Day_of_week"),
        "weekly_counts": _event_counts_by_week(resource_logs),
        "claim_boundary": (
            "Resource views indicate access frequency and timing. They do not "
            "prove reading quality, understanding, or preparation depth."
        ),
    }


def _summarise_lecture(student_id: int, data: DashboardData) -> dict[str, Any]:
    echo = _student_rows(data.echo, student_id)
    moodle = _student_rows(data.moodle, student_id)
    video_clicks = moodle[moodle.get("Event").eq("Video_views")] if not moodle.empty else pd.DataFrame()
    feature = _feature_row(data.features, student_id)

    if echo.empty:
        viewed_videos = 0
        missed_weeks: list[str] = []
        avg_percent = _feature_value(feature, "Video_view%_avg")
    else:
        viewed_videos = int((pd.to_numeric(echo.get("Video Views"), errors="coerce").fillna(0) > 0).sum())
        missed = echo[
            pd.to_numeric(echo.get("Video Views"), errors="coerce").fillna(0).eq(0)
        ]
        missed_weeks = _week_list(missed, "Content_week")
        avg_percent = _mean_value(echo, "Video View %")

    return {
        "available": not echo.empty or not video_clicks.empty or bool(feature),
        "video_views_sum": _feature_value(feature, "Video_views_sum", default=_sum_value(echo, "Video Views")),
        "video_clicks": _feature_value(feature, "Video_clicks", default=len(video_clicks)),
        "viewed_videos": viewed_videos,
        "missed_content_weeks": missed_weeks,
        "average_video_view_percent": avg_percent,
        "weekly_video_clicks": _event_counts_by_week(video_clicks),
        "claim_boundary": (
            "Video views and view percentages indicate watching activity. They "
            "cannot prove attention, comprehension, or note-taking quality."
        ),
    }


def _summarise_lecture_quantitative(student_id: int, data: DashboardData) -> dict[str, Any]:
    """Return auditable Lecture calculations without reconstructing missing rows."""

    echo = _student_rows(data.echo, student_id)
    required = {"Class", "Content_week", "Video Views", "Video View %"}
    row_level_available = not echo.empty and required.issubset(echo.columns)
    if not row_level_available:
        return {
            "row_level_records_available": False,
            "row_level_records": [],
            "row_level_availability_note": (
                "The available evidence contains only aggregate statistics, so I cannot reliably list each tracked row."
            ),
            "calculations": {},
        }

    rows = echo.loc[:, ["Class", "Content_week", "Video Views", "Video View %"]].copy()
    views = pd.to_numeric(rows["Video Views"], errors="coerce").fillna(0)
    percentages = pd.to_numeric(rows["Video View %"], errors="coerce")
    real_mask = ~rows["Class"].astype(str).str.contains("No Lecture Video", case=False, na=False)
    viewed_mask = views.gt(0)

    def average_record(mask: pd.Series, label: str) -> dict[str, Any]:
        included = percentages[mask & percentages.notna()]
        numerator = float(included.sum())
        denominator = int(included.count())
        return {
            "value": round(numerator / denominator, 2) if denominator else None,
            "numerator": round(numerator, 2),
            "denominator": denominator,
            "inclusion_rule": label,
        }

    records = [
        {
            "class": str(row["Class"]),
            "content_week": f"W{int(row['Content_week'])}" if pd.notna(row["Content_week"]) else "",
            "video_view_events": int(row["Video Views"]) if pd.notna(row["Video Views"]) else 0,
            "video_view_percent": float(row["Video View %"]) if pd.notna(row["Video View %"]) else None,
        }
        for _, row in rows.iterrows()
    ]
    return {
        "row_level_records_available": True,
        "row_level_records": records,
        "row_level_availability_note": "Actual student Lecture rows are present in the selected context.",
        "calculations": {
            "total_video_view_events": {
                "value": int(views.sum()),
                "numerator": int(views.sum()),
                "denominator": int(len(rows)),
                "inclusion_rule": "Sum Video Views across all tracked Lecture rows.",
            },
            "unique_lecture_videos_viewed": {
                "value": int((viewed_mask & real_mask).sum()),
                "numerator": int((viewed_mask & real_mask).sum()),
                "denominator": int(real_mask.sum()),
                "inclusion_rule": "Count real Lecture rows with at least one Video Views event; exclude 'No Lecture Video'.",
            },
            "average_percentage_among_viewed_videos": average_record(
                viewed_mask & real_mask,
                "Mean Video View % over real Lecture rows with Video Views > 0.",
            ),
            "average_percentage_across_real_lecture_rows": average_record(
                real_mask,
                "Mean Video View % over all real Lecture rows; exclude 'No Lecture Video'.",
            ),
            "average_percentage_across_all_tracked_rows": average_record(
                pd.Series(True, index=rows.index),
                "Mean Video View % over every tracked Lecture row, including 'No Lecture Video'.",
            ),
        },
    }


def _summarise_debate(student_id: int, data: DashboardData) -> dict[str, Any]:
    moodle = _student_rows(data.moodle, student_id)
    debate_logs = moodle[moodle.get("Activity").eq("Debate")] if not moodle.empty else pd.DataFrame()
    feature = _feature_row(data.features, student_id)

    posts = debate_logs[debate_logs.get("Event").eq("Debate_posts")] if not debate_logs.empty else pd.DataFrame()
    replies = debate_logs[debate_logs.get("Event").eq("Debate_replies")] if not debate_logs.empty else pd.DataFrame()
    views = debate_logs[debate_logs.get("Event").eq("Debate_views")] if not debate_logs.empty else pd.DataFrame()

    return {
        "available": not debate_logs.empty or bool(feature),
        "views": _feature_value(feature, "Debate_views", default=len(views)),
        "posts": _feature_value(feature, "Debate_posts", default=len(posts)),
        "replies": _feature_value(feature, "Debate_replies", default=len(replies)),
        "active_post_weeks": _week_list(posts, "Week"),
        "active_reply_weeks": _week_list(replies, "Week"),
        "active_view_weeks": _week_list(views, "Week"),
        "weekly_event_counts": {
            "views": _event_counts_by_week(views),
            "posts": _event_counts_by_week(posts),
            "replies": _event_counts_by_week(replies),
        },
        "unique_students_i_viewed": _feature_value(feature, "Num_unique_students_i_viewed"),
        "unique_students_who_viewed_me": _feature_value(feature, "Num_unique_students_have_viewed"),
        "unique_students_i_replied_to": _feature_value(feature, "Num_unique_students_i_replied"),
        "unique_students_who_replied_to_me": _feature_value(feature, "Num_unique_students_have_replied"),
        "claim_boundary": (
            "Debate counts indicate participation frequency and interaction "
            "structure. They do not directly measure argument quality, critical "
            "thinking, or understanding."
        ),
    }


def _summarise_reflection(student_id: int, data: DashboardData) -> dict[str, Any]:
    gdocs = _student_rows(data.gdocs, student_id)
    feature = _feature_row(data.features, student_id)

    active = pd.DataFrame()
    if not gdocs.empty and "absStrCount" in gdocs:
        counts = pd.to_numeric(gdocs["absStrCount"], errors="coerce").fillna(0)
        active = gdocs[counts.gt(0)]

    return {
        "available": not gdocs.empty or bool(feature),
        "total_chars": _feature_value(feature, "Total_chars", default=_sum_value(gdocs, "absStrCount")),
        "active_weeks": _unique_count(active, "Week"),
        "active_week_list": _week_list(active, "Week"),
        "most_active_day": _mode_value(active, "dayOfWeek"),
        "weekly_character_counts": _sum_by_week(active, "absStrCount"),
        "claim_boundary": (
            "Reflection character counts indicate writing volume and timing. "
            "They do not evaluate reflective depth, accuracy, or insight."
        ),
    }


def _summarise_overview(student_id: int, data: DashboardData) -> dict[str, Any]:
    """Build a lightweight cross-page overview summary.

    This is deliberately compressed: it supports broad overview questions
    without dumping all dashboard data into the assistant prompt.
    """

    resources = _summarise_resources(student_id, data)
    lecture = _summarise_lecture(student_id, data)
    debate = _summarise_debate(student_id, data)
    reflection = _summarise_reflection(student_id, data)
    summaries = {
        "resources": resources,
        "lecture": lecture,
        "debate": debate,
        "reflection": reflection,
    }

    return {
        "available": any(bool(summary.get("available")) for summary in summaries.values()),
        "resource_activity_summary": _compress_resource_summary(resources),
        "lecture_video_activity_summary": _compress_lecture_summary(lecture),
        "debate_activity_summary": _compress_debate_summary(debate),
        "reflection_activity_summary": _compress_reflection_summary(reflection),
        "major_observation": _overview_major_observation(summaries),
        "possible_focus_area": _overview_focus_area(summaries),
        "uncertainty": (
            "Overview combines activity traces from several pages. It can show "
            "patterns in access, viewing, contribution, and writing activity, but "
            "it cannot prove learning quality, motivation, attention, or comprehension."
        ),
    }


def _compress_resource_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    weekly = summary.get("weekly_counts", {})
    return {
        "available": summary.get("available", False),
        "views": summary.get("views"),
        "active_weeks": summary.get("active_weeks"),
        "most_active_day": summary.get("most_active_day"),
        "weekly_extremes": _weekly_extremes_text(weekly),
        "claim_boundary": summary.get("claim_boundary"),
    }


def _compress_lecture_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": summary.get("available", False),
        "viewed_videos": summary.get("viewed_videos"),
        "average_video_view_percent": summary.get("average_video_view_percent"),
        "missed_content_weeks": summary.get("missed_content_weeks"),
        "video_clicks": summary.get("video_clicks"),
        "claim_boundary": summary.get("claim_boundary"),
    }


def _compress_debate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": summary.get("available", False),
        "views": summary.get("views"),
        "posts": summary.get("posts"),
        "replies": summary.get("replies"),
        "active_post_weeks": summary.get("active_post_weeks"),
        "active_reply_weeks": summary.get("active_reply_weeks"),
        "claim_boundary": summary.get("claim_boundary"),
    }


def _compress_reflection_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    weekly = summary.get("weekly_character_counts", {})
    return {
        "available": summary.get("available", False),
        "total_chars": summary.get("total_chars"),
        "active_weeks": summary.get("active_weeks"),
        "active_week_list": summary.get("active_week_list"),
        "weekly_extremes": _weekly_extremes_text(weekly),
        "claim_boundary": summary.get("claim_boundary"),
    }


def _overview_major_observation(summaries: Mapping[str, Mapping[str, Any]]) -> str:
    resources = summaries["resources"]
    lecture = summaries["lecture"]
    debate = summaries["debate"]
    reflection = summaries["reflection"]

    resource_views = _numeric_or_zero(resources.get("views"))
    resource_weeks = _numeric_or_zero(resources.get("active_weeks"))
    debate_views = _numeric_or_zero(debate.get("views"))
    debate_posts = _numeric_or_zero(debate.get("posts"))
    debate_replies = _numeric_or_zero(debate.get("replies"))
    reflection_weeks = _numeric_or_zero(reflection.get("active_weeks"))
    viewed_videos = _numeric_or_zero(lecture.get("viewed_videos"))

    if resource_views and resource_weeks >= max(reflection_weeks, viewed_videos):
        return (
            f"Resource activity is the broadest selected signal: {resources.get('views')} "
            f"resource views across {resources.get('active_weeks')} active weeks."
        )
    if debate_views and debate_views > (debate_posts + debate_replies):
        return (
            f"Debate activity includes more viewing than visible contribution: {debate.get('views')} "
            f"views compared with {debate.get('posts')} posts and {debate.get('replies')} replies."
        )
    if reflection.get("total_chars"):
        return (
            f"Reflection activity is visible across {reflection.get('active_weeks')} active weeks "
            f"with {reflection.get('total_chars')} edited characters."
        )
    if viewed_videos:
        return (
            f"Lecture activity shows {lecture.get('viewed_videos')} viewed videos with average view "
            f"percentage {lecture.get('average_video_view_percent')}."
        )
    return "The selected overview evidence is too sparse to identify a strong activity pattern."


def _overview_focus_area(summaries: Mapping[str, Mapping[str, Any]]) -> str:
    resources = summaries["resources"]
    lecture = summaries["lecture"]
    debate = summaries["debate"]
    reflection = summaries["reflection"]

    missed = lecture.get("missed_content_weeks") or []
    if missed:
        return f"Check one missed or low-view lecture week first, starting with {_format_list(missed[:2])}."

    debate_views = _numeric_or_zero(debate.get("views"))
    debate_posts = _numeric_or_zero(debate.get("posts"))
    debate_replies = _numeric_or_zero(debate.get("replies"))
    if debate_views > max(debate_posts + debate_replies, 0):
        return "Turn one debate item you have already viewed into a short reply or question."

    resource_extremes = _weekly_extremes_text(resources.get("weekly_counts"))
    if resource_extremes:
        return f"Use the resource weekly pattern to choose one low-activity week to revisit: {resource_extremes}."

    if reflection.get("active_weeks"):
        return "Use one recent learning activity as material for a structured reflection entry."

    return "Choose one specific dashboard page and turn one visible pattern into a small next action."


def _weekly_extremes_text(weekly: Any) -> str:
    if not isinstance(weekly, Mapping) or not weekly:
        return ""
    numeric = []
    for week, value in weekly.items():
        try:
            numeric.append((str(week), float(value)))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return ""
    low_week, low_val = min(numeric, key=lambda item: item[1])
    high_week, high_val = max(numeric, key=lambda item: item[1])
    low_text = int(low_val) if low_val.is_integer() else low_val
    high_text = int(high_val) if high_val.is_integer() else high_val
    if low_week == high_week:
        return f"{high_week} is the only selected week with {high_text} events"
    return f"lowest selected week is {low_week} ({low_text}); highest selected week is {high_week} ({high_text})"


def _numeric_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_list(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        return ", ".join(map(str, value))
    return "none selected"


def _summarise_debate_networks(student_id: int, data: DashboardData) -> dict[str, Any]:
    reply = _network_rows(data.reply_network, student_id)
    view = _network_rows(data.view_network, student_id)

    return {
        "available": not reply.empty or not view.empty,
        "reply_network": _network_counts(reply, student_id),
        "view_network": _network_counts(view, student_id),
        "claim_boundary": (
            "Networks show who interacted with whose debate contributions and "
            "how often. They do not show the quality or sentiment of interaction."
        ),
    }


def _summarise_reflection_cohort(student_id: int, data: DashboardData) -> dict[str, Any]:
    gdocs = _student_rows(data.gdocs, student_id)
    cohort = data.gdocs_ts if data.gdocs_ts is not None else pd.DataFrame()

    if gdocs.empty or cohort.empty:
        return {
            "available": False,
            "note": "Student or cohort reflection time-series data is not available.",
        }

    student_total = _sum_value(gdocs, "absStrCount")
    current_total = _sum_value(cohort, "currentCohort")
    previous_total = _sum_value(cohort, "previousCohorts")

    return {
        "available": True,
        "student_total_chars": student_total,
        "current_cohort_total_reference": current_total,
        "previous_cohorts_total_reference": previous_total,
        "comparison_note": (
            "This is a volume/timing comparison only. Cohort totals are context "
            "for interpreting activity patterns, not benchmarks of writing quality."
        ),
    }


def _summarise_preparation(
    page: str,
    student_id: int,
    data: DashboardData,
) -> dict[str, Any]:
    """Return a compact page summary for cross-page support."""

    summary = _summarise_page_activity(page, student_id, data)
    if page == "resources":
        return {
            "preparation_pattern": (
                f"{summary.get('views', 'No')} resource views across "
                f"{summary.get('active_weeks', 0)} active weeks."
            ),
            "most_active_day": summary.get("most_active_day"),
            "claim_boundary": summary.get("claim_boundary"),
        }
    if page == "lecture":
        return {
            "preparation_pattern": (
                f"{summary.get('viewed_videos', 0)} lecture videos viewed; "
                f"average view percent: {summary.get('average_video_view_percent')}."
            ),
            "missed_content_weeks": summary.get("missed_content_weeks"),
            "claim_boundary": summary.get("claim_boundary"),
        }
    if page == "debate":
        return {
            "participation_pattern": (
                f"{summary.get('posts', 0)} posts, {summary.get('replies', 0)} replies, "
                f"{summary.get('views', 0)} views."
            ),
            "claim_boundary": summary.get("claim_boundary"),
        }
    if page == "reflection":
        return {
            "reflection_pattern": (
                f"{summary.get('total_chars', 0)} edited characters across "
                f"{summary.get('active_weeks', 0)} active weeks."
            ),
            "claim_boundary": summary.get("claim_boundary"),
        }
    return {"available": False}


def _summarise_data_availability(
    page: str,
    student_id: int,
    data: DashboardData,
) -> dict[str, Any]:
    """Summarise whether selected raw data exists for this student and page."""

    if page == "lecture":
        rows = _student_rows(data.echo, student_id)
    elif page == "reflection":
        rows = _student_rows(data.gdocs, student_id)
    else:
        rows = _student_rows(data.moodle, student_id)
        if page == "resources":
            rows = rows[rows.get("Event").eq("Resources_views")] if not rows.empty else rows
        elif page == "debate":
            rows = rows[rows.get("Activity").eq("Debate")] if not rows.empty else rows

    return {
        "available": not rows.empty,
        "row_count": int(len(rows)),
        "columns": list(rows.columns) if not rows.empty else [],
    }


def _course_context_for(page: str, data: DashboardData) -> str:
    if data.course_context and page in data.course_context:
        return data.course_context[page]
    if page == "reflection":
        return (
            "Debate and reflection can be discussed as related learning tasks: "
            "debate activity may give students ideas to write about, and reflection "
            "may help consolidate points from debate. The dashboard can show "
            "activity patterns, not a causal learning pathway."
        )
    return (
        "Course task context was not provided. Use only dashboard activity "
        "patterns and avoid claims about task content."
    )


def _course_metadata_for(page: str, data: DashboardData) -> dict[str, Any]:
    """Return available course/activity metadata, not full teaching content."""

    if page == "lecture":
        echo = data.echo if data.echo is not None else pd.DataFrame()
        echo_titles: dict[str, str] = {}
        if not echo.empty and "Content_week" in echo.columns and "Class" in echo.columns:
            temp = echo[["Content_week", "Class"]].drop_duplicates().sort_values("Content_week")
            echo_titles = {
                f"W{int(row.Content_week)}": str(row.Class)
                for row in temp.itertuples(index=False)
                if pd.notna(row.Content_week)
            }

        verified_titles = lecture_titles_by_week()
        all_titles = dict(echo_titles)
        all_titles.update(verified_titles)
        if not all_titles:
            return {
                "available": False,
                "note": "Lecture metadata is not available in the dashboard data or verified course metadata.",
            }

        return {
            "available": True,
            "lecture_titles_by_week": all_titles,
            "verified_week_metadata": LECTURE_METADATA_BY_WEEK,
            "echo_titles_by_week": echo_titles,
            "content_limitation": (
                "The metadata includes lecture titles and short weekly-page summaries, "
                "not full lecture recordings or transcripts."
            ),
        }

    return {
        "available": False,
        "note": "Course-content metadata is not available for this page in the dashboard data.",
    }


def _metric_definitions_for_query(page: str, query: str) -> dict[str, str]:
    """Return only metric definitions that appear relevant to the query.

    If the query does not clearly name a metric, fall back to all definitions
    for the current page. This keeps clarification questions focused while
    still supporting broader technical questions such as "is this data accurate?"
    """

    definitions = METRIC_DEFINITIONS.get(page, {})
    aliases = METRIC_QUERY_ALIASES.get(page, {})
    q = _normalise_text(query)

    if not q:
        return definitions

    selected: dict[str, str] = {}
    for metric, metric_aliases in aliases.items():
        for alias in metric_aliases:
            if re.search(rf"\b{re.escape(alias)}\b", q):
                if metric in definitions:
                    selected[metric] = definitions[metric]
                break

    if page == "debate" and re.search(r"\b(arrow|arrows|node|nodes|edge|edges|connection|connections)\b", q):
        for metric in ("Reply network", "View network"):
            selected[metric] = definitions[metric]

    return selected or definitions


def _data_limitations_for(page: str) -> list[str]:
    """Describe limits of the selected dashboard data source."""

    shared = [
        "The dashboard uses activity traces from learning platforms, so it can miss learning that happened offline or outside the tracked tools.",
        "Counts can support reflection on behaviour patterns, but they should not be read as grades or direct measures of learning quality.",
    ]
    page_specific = {
        "resources": [
            "A resource view means a Moodle item was opened; it does not show how much was read or understood.",
        ],
        "lecture": [
            "A video view or percentage watched does not prove attention, note-taking, or comprehension.",
        ],
        "debate": [
            "Debate views, posts, replies, and networks show frequency and interaction structure, not argument quality or critical thinking.",
            "Network counts can be affected by filtering, week selection, and whether the interaction was a view or reply.",
        ],
        "reflection": [
            "Reflection character counts show writing volume and timing, not reflective depth or insight.",
        ],
    }
    return shared + page_specific.get(page, [])


def _learning_purpose_for(page: str) -> str:
    purposes = {
        "resources": (
            "Resource engagement helps students notice whether they are accessing "
            "materials regularly enough to prepare for lectures, debate, and reflection."
        ),
        "lecture": (
            "Lecture video engagement helps students monitor whether they are "
            "keeping up with recorded content before connected learning activities."
        ),
        "debate": (
            "Debate engagement helps students monitor participation in peer-facing "
            "discussion activities and identify whether they are mostly viewing or "
            "also contributing."
        ),
        "reflection": (
            "Reflection engagement helps students monitor whether reflective writing "
            "is regular and distributed rather than only completed near deadlines."
        ),
    }
    return purposes.get(page, "This dashboard page helps monitor learning activity patterns.")


def _build_interpretation(
    primary_page: str,
    query_type: str,
    selected: Mapping[str, Any],
) -> str:
    """Provide guidance for how the selected evidence should be used."""

    page = PAGE_DISPLAY[primary_page]

    if query_type == "memory_state_query":
        return "Answer from explicit session Memory only; dashboard evidence is not selected."
    if query_type == "hybrid_course_and_planning":
        return (
            "Use the primary dashboard domain only for student activity, retrieved course material for content claims, "
            "and build a concrete recommendation that keeps those sources separate."
        )
    if query_type == "quantitative_metric_query":
        return (
            "Use only the supplied Lecture calculations and actual row records. Include numeric denominators and inclusion rules. "
            "If row records are unavailable, refuse to reconstruct them."
        )

    if query_type == "metric_clarification":
        return (
            f"Answer by explaining the {page} metric definition only. Do not infer "
            "whether the student's learning is good or bad from the metric alone."
        )
    if primary_page == "overview":
        return (
            "Use compressed Resources, Lecture, Debate, and Reflection summaries "
            "to answer the overview question. Provide one cautious observation or "
            "focus area, and avoid claims about learning quality or motivation."
        )
    if query_type == "reflection_structure_question":
        return (
            "Provide a concrete reflection writing structure. Use selected dashboard "
            "evidence only as optional context, and do not infer reflection quality "
            "from character counts."
        )
    if query_type == "course_content_question":
        return (
            "Answer using available course/activity metadata only. If full content "
            "or transcripts are unavailable, say that clearly."
        )
    if query_type == "access_or_capability_question":
        return (
            "Explain what the dashboard/system can and cannot access. Do not claim "
            "visibility over full lecture content, email reads, or external activity "
            "unless that evidence is present."
        )
    if query_type == "discrepancy_or_correction":
        return (
            "Acknowledge the student's correction and explain that dashboard logs "
            "may not capture every submission or activity. Recommend checking the "
            "official platform or instructor confirmation."
        )
    if query_type == "dashboard_interpretation":
        return (
            f"Use the selected {page} activity patterns to explain what the dashboard "
            "shows about frequency, timing, and distribution of engagement."
        )
    if query_type == "improvement_recommendation":
        return (
            f"Use {page} evidence to identify the immediate behaviour to improve, "
            "then use the selected preparation evidence from related pages to suggest "
            "one or two feasible next steps."
        )
    if query_type == "cross_page_relationship":
        return (
            "Compare only the selected page summaries. Discuss plausible connections "
            "between activity patterns, but avoid causal claims unless the data directly "
            "supports them."
        )
    if query_type == "planning_or_strategy":
        return (
            "Use selected activity patterns to support a practical short-term plan. "
            "Prefer small, measurable actions tied to the current dashboard evidence."
        )
    if query_type == "technical_data_question":
        return (
            "Answer using metric definitions, provenance, and data availability. "
            "Do not add behavioural interpretation unless the student asks for it."
        )
    if query_type == "emotional_or_justification":
        return (
            "Use evidence to normalise and clarify what the dashboard can and cannot "
            "show. Avoid judgemental wording and avoid treating activity traces as grades."
        )
    return "Use selected evidence only."


def _build_uncertainty(
    query_type: str,
    sources: list[str],
    selected: Mapping[str, Any],
) -> str:
    """Create an explicit uncertainty statement for the selected evidence."""

    notes = [
        "Dashboard logs describe observable activity, not learning quality or motivation.",
    ]

    source_set = set(sources)
    if _source_selected(source_set, "overview", {"activity_summary"}):
        notes.append("Overview synthesis compresses multiple activity summaries, so it should be treated as a high-level guide rather than a complete audit.")
    if _source_selected(source_set, "resources", {"activity_summary", "preparation_summary", "metric_definitions"}):
        notes.append("Resource views cannot prove that readings were completed or understood.")
    if _source_selected(source_set, "lecture", {"activity_summary", "preparation_summary", "metric_definitions"}):
        notes.append("Video views cannot prove attention or comprehension.")
    if _source_selected(
        source_set,
        "debate",
        {"activity_summary", "network_summary", "preparation_summary", "metric_definitions"},
    ):
        notes.append("Debate posts, replies, and views cannot prove contribution quality.")
    if _source_selected(source_set, "reflection", {"activity_summary", "cohort_comparison", "preparation_summary"}):
        notes.append("Reflection character counts cannot prove reflective depth.")
    if query_type == "cross_page_relationship":
        notes.append(
            "Cross-page patterns should be treated as associations, not causal evidence; "
            "they cannot prove either dependence or independence."
        )
    if query_type in {"course_content_question", "access_or_capability_question"}:
        notes.append("Available dashboard evidence may include activity logs or titles, not full teaching content.")
    if query_type == "discrepancy_or_correction":
        notes.append("Dashboard logs may not capture all submissions, external activity, or timing details.")
    if query_type == "reflection_structure_question":
        notes.append("Reflection structure advice is a writing scaffold; character counts cannot prove reflective quality.")

    if _contains_unavailable_evidence(selected):
        notes.append("Some selected evidence is unavailable or empty for this student.")

    return " ".join(notes)


def _source_selected(
    sources: set[str],
    page: str,
    components: set[str],
) -> bool:
    return any(f"{page}.{component}" in sources for component in components)


def _supporting_pages_for_improvement(page: str) -> list[str]:
    support = {
        "debate": ["lecture", "resources"],
        "lecture": ["resources"],
        "resources": ["lecture", "debate"],
        "reflection": ["lecture", "debate", "resources"],
    }
    return support.get(page, [])


def _default_related_pages(page: str) -> list[str]:
    related = {
        "debate": ["reflection"],
        "reflection": ["debate"],
        "lecture": ["resources", "debate"],
        "resources": ["lecture", "debate"],
    }
    return related.get(page, [])


def _mentioned_pages(query: str) -> list[str]:
    return detect_explicit_dashboard_domains(query)


def _is_metric_interpretation_question(query: str) -> bool:
    metric_terms = (
        r"\b(resources?_views|video_views|video_clicks|debate_views|debate_posts|debate_replies|total_chars|absstrcount)\b",
        r"\b(resource|resources|video|lecture|debate|post|posts|reply|replies|reflection|character|chars|strings)\b",
    )
    interpretation_terms = (
        r"\b(my|mine)\b.*\b(show|shows|suggest|suggests|indicate|indicates|tell|tells|interpret|comment)\b",
        r"\b(what do|what does|what would|how do i).*\b(show|suggest|indicate|interpret|comment)\b",
        r"\b(major observation|specific points|identify gaps|overall activity)\b",
    )
    return _matches_any(query, metric_terms) and _matches_any(query, interpretation_terms)


def _is_metric_question(query: str) -> bool:
    has_metric_word = _matches_any(
        query,
        (
            r"\b(view|views|post|posts|reply|replies|click|clicks|percentage|percent)\b",
            r"\b(metric|number|count|arrow|network|characters?|chars)\b",
        ),
    )
    asks_meaning = _matches_any(
        query,
        (
            r"\bwhat (?:does|do)\b.*\b(?:mean|means|count as)\b",
            r"\bwhat (?:is|are)\b.*\b(?:metric|meaning|definition)\b",
            r"\b(?:meaning|define|definition)\b",
            r"\b(explain.*metric|explain.*number|explain.*arrow)\b",
        ),
    )
    return has_metric_word and asks_meaning


def _student_rows(df: pd.DataFrame | None, student_id: int) -> pd.DataFrame:
    if df is None or df.empty or "ID" not in df.columns:
        return pd.DataFrame()
    ids = pd.to_numeric(df["ID"], errors="coerce")
    return df[ids.eq(student_id)].copy()


def _feature_row(features: pd.DataFrame | None, student_id: int) -> dict[str, Any]:
    if features is None or features.empty or "ID" not in features.columns:
        return {}
    ids = pd.to_numeric(features["ID"], errors="coerce")
    rows = features[ids.eq(student_id)]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _feature_value(
    feature: Mapping[str, Any],
    column: str,
    default: Any = None,
) -> Any:
    if column not in feature or pd.isna(feature[column]):
        return default
    return _clean_number(feature[column])


def _network_rows(df: pd.DataFrame | None, student_id: int) -> pd.DataFrame:
    if df is None or df.empty or "From" not in df.columns or "To" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["From"] = pd.to_numeric(out["From"], errors="coerce")
    out["To"] = pd.to_numeric(out["To"], errors="coerce")
    return out[out["From"].eq(student_id) | out["To"].eq(student_id)].copy()


def _network_counts(rows: pd.DataFrame, student_id: int) -> dict[str, Any]:
    if rows.empty:
        return {
            "available": False,
            "total_edges": 0,
            "outgoing_interactions": 0,
            "incoming_interactions": 0,
            "unique_people": 0,
        }

    counts = pd.to_numeric(rows.get("count"), errors="coerce").fillna(0)
    outgoing = rows["From"].eq(student_id)
    incoming = rows["To"].eq(student_id)
    people = set(rows.loc[outgoing, "To"].dropna().astype(int).tolist())
    people.update(rows.loc[incoming, "From"].dropna().astype(int).tolist())
    people.discard(student_id)

    return {
        "available": True,
        "total_edges": int(len(rows)),
        "outgoing_interactions": _clean_number(counts[outgoing].sum()),
        "incoming_interactions": _clean_number(counts[incoming].sum()),
        "unique_people": int(len(people)),
        "weeks": _week_list(rows, "week"),
    }


def _event_counts_by_week(rows: pd.DataFrame) -> dict[str, int]:
    if rows.empty or "Week" not in rows.columns:
        return {}
    weeks = pd.to_numeric(rows["Week"], errors="coerce").dropna().astype(int)
    counts = weeks.value_counts().sort_index()
    return {f"W{week}": int(count) for week, count in counts.items()}


def _sum_by_week(rows: pd.DataFrame, value_col: str) -> dict[str, Any]:
    if rows.empty or "Week" not in rows.columns or value_col not in rows.columns:
        return {}
    temp = rows.copy()
    temp["Week"] = pd.to_numeric(temp["Week"], errors="coerce")
    temp[value_col] = pd.to_numeric(temp[value_col], errors="coerce").fillna(0)
    grouped = temp.dropna(subset=["Week"]).groupby("Week")[value_col].sum().sort_index()
    return {f"W{int(week)}": _clean_number(value) for week, value in grouped.items()}


def _week_list(rows: pd.DataFrame, column: str) -> list[str]:
    if rows.empty or column not in rows.columns:
        return []
    values = pd.to_numeric(rows[column], errors="coerce").dropna().astype(int).unique()
    return [f"W{value}" for value in sorted(values)]


def _unique_count(rows: pd.DataFrame, column: str) -> int:
    if rows.empty or column not in rows.columns:
        return 0
    return int(pd.to_numeric(rows[column], errors="coerce").dropna().nunique())


def _mode_value(rows: pd.DataFrame, column: str) -> str | None:
    if rows.empty or column not in rows.columns:
        return None
    counts = rows[column].dropna().astype(str).value_counts()
    if counts.empty:
        return None
    return str(counts.index[0])


def _sum_value(rows: pd.DataFrame, column: str) -> Any:
    if rows.empty or column not in rows.columns:
        return 0
    values = pd.to_numeric(rows[column], errors="coerce").fillna(0)
    return _clean_number(values.sum())


def _mean_value(rows: pd.DataFrame, column: str) -> Any:
    if rows.empty or column not in rows.columns:
        return None
    values = pd.to_numeric(rows[column], errors="coerce").dropna()
    if values.empty:
        return None
    return _clean_number(values.mean())


def _summarise_optional_text_table(
    df: pd.DataFrame | None,
    preferred_columns: tuple[str, ...],
    label: str,
    limit: int = 3,
) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "available": False,
            "note": f"No {label} were provided to the synthesiser.",
        }

    text_col = next((col for col in preferred_columns if col in df.columns), None)
    if text_col is None:
        return {
            "available": False,
            "note": f"{label.title()} table was provided but no recognised text column was found.",
            "columns": list(df.columns),
        }

    values = [
        str(value).strip()
        for value in df[text_col].dropna().tolist()
        if str(value).strip()
    ]
    return {
        "available": bool(values),
        "items": values[:limit],
        "omitted_count": max(0, len(values) - limit),
    }


def _contains_unavailable_evidence(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("available") is False:
            return True
        return any(_contains_unavailable_evidence(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_unavailable_evidence(v) for v in value)
    return False


def _coerce_student_id(student_id: Any) -> int:
    if isinstance(student_id, pd.Series):
        if student_id.empty:
            raise ValueError("student_id Series is empty")
        student_id = student_id.iloc[0]
    if isinstance(student_id, (list, tuple)):
        if not student_id:
            raise ValueError("student_id list is empty")
        student_id = student_id[0]
    numeric = pd.to_numeric(student_id, errors="coerce")
    if pd.isna(numeric):
        raise ValueError(f"Could not parse student_id: {student_id}")
    return int(numeric)


def _clean_number(value: Any) -> Any:
    if pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return round(number, 2)


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)
