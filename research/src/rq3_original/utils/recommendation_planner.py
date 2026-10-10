"""Retrieval-grounded recommendation planning for RQ2.

The planner consumes the selected RQ1 evidence summary and optional retrieved
context chunks. It does not call an LLM and it does not import Streamlit. Its
job is to create a structured recommendation plan that can later be rendered by
an assistant or used in offline evaluation.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


SUPPORTED_SOURCE_TYPES = {"dashboard", "course_material", "literature"}


def build_recommendation_plan(
    student_query: str,
    current_page: str,
    student_id: Any,
    evidence_summary: Mapping[str, Any],
    retrieved_context_chunks: Sequence[Mapping[str, Any] | str] | None = None,
) -> dict[str, Any]:
    """Create a structured recommendation plan from RQ1 evidence.

    Parameters
    ----------
    student_query:
        The student's original query.
    current_page:
        Dashboard page where the query was asked.
    student_id:
        Student identifier. It is included for traceability, not displayed.
    evidence_summary:
        Output from ``utils.evidence_synthesiser.synthesise_evidence``.
    retrieved_context_chunks:
        Optional RQ2 retrieval results. Each chunk may be a plain string or a
        dict with fields such as ``source_type``, ``text`` or ``claim``.

    Returns
    -------
    dict
        A recommendation plan with student state, action, rationale, supporting
        evidence, and limitations.
    """

    page_key = _normalise_page(current_page or evidence_summary.get("primary_page", ""))
    query_type = str(evidence_summary.get("query_type", ""))
    selected_evidence = evidence_summary.get("selected_evidence", {})
    chunks = _normalise_context_chunks(retrieved_context_chunks)

    dashboard_claims = _dashboard_claims(page_key, selected_evidence)
    context_claims = _context_claims(chunks)
    supporting_evidence = dashboard_claims + context_claims

    student_state = _student_state(page_key, selected_evidence)
    main_issue = _main_issue(page_key, query_type, selected_evidence)
    recommended_action = _recommended_action(page_key, query_type, selected_evidence)
    action_steps = _action_steps(page_key, query_type, selected_evidence)
    why_this_matters = _why_this_matters(page_key, selected_evidence, chunks)
    why_this_fits = _why_this_fits_student(page_key, selected_evidence)
    limitations = _limitations(evidence_summary, chunks)

    return {
        "student_id": str(student_id),
        "student_query": student_query,
        "current_page": current_page,
        "query_type": query_type,
        "student_state": student_state,
        "main_issue": main_issue,
        "recommended_action": recommended_action,
        "why_this_matters": why_this_matters,
        "why_this_fits_the_student": why_this_fits,
        "action_steps": action_steps,
        "supporting_evidence": supporting_evidence,
        "uncertainty_or_limitations": limitations,
    }


def render_student_response(plan: Mapping[str, Any], max_steps: int = 4) -> str:
    """Render a recommendation plan as a student-facing response."""

    steps = [str(step) for step in plan.get("action_steps", []) if str(step).strip()]
    steps = steps[:max_steps]
    step_text = "\n".join(f"{idx}. {step}" for idx, step in enumerate(steps, start=1))

    parts = [
        f"Your data suggests: {plan.get('student_state', '')}",
        f"The main issue to focus on is: {plan.get('main_issue', '')}",
        f"My recommendation is: {plan.get('recommended_action', '')}",
        f"Why this matters: {plan.get('why_this_matters', '')}",
        f"Why this fits your situation: {plan.get('why_this_fits_the_student', '')}",
    ]
    if step_text:
        parts.append("Try this next:\n" + step_text)
    parts.append(f"Limitations: {plan.get('uncertainty_or_limitations', '')}")
    return "\n\n".join(part for part in parts if part.strip())


def _dashboard_claims(
    page_key: str,
    selected_evidence: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Extract evidence claims from the RQ1 dashboard summary."""

    claims: list[dict[str, str]] = []

    page_evidence = selected_evidence.get(page_key, {})
    activity = _as_mapping(page_evidence.get("activity_summary"))
    if activity:
        claims.extend(_claims_from_activity(page_key, activity))

    network = _as_mapping(page_evidence.get("network_summary"))
    if page_key == "debate" and network:
        reply = _as_mapping(network.get("reply_network"))
        view = _as_mapping(network.get("view_network"))
        if reply.get("available"):
            claims.append(
                _claim(
                    "dashboard",
                    "The reply network contains "
                    f"{reply.get('total_edges')} edges, {reply.get('outgoing_interactions')} outgoing "
                    f"interactions, {reply.get('incoming_interactions')} incoming interactions, and "
                    f"{reply.get('unique_people')} unique people.",
                )
            )
        if view.get("available"):
            claims.append(
                _claim(
                    "dashboard",
                    "The view network contains "
                    f"{view.get('total_edges')} edges, {view.get('outgoing_interactions')} outgoing "
                    f"interactions, {view.get('incoming_interactions')} incoming interactions, and "
                    f"{view.get('unique_people')} unique people.",
                )
            )

    for related_page in ("lecture", "resources", "debate", "reflection"):
        if related_page == page_key:
            continue
        related = _as_mapping(selected_evidence.get(related_page, {}))
        prep = _as_mapping(related.get("preparation_summary"))
        if prep:
            for key in ("preparation_pattern", "participation_pattern", "reflection_pattern"):
                if prep.get(key):
                    claims.append(_claim("dashboard", str(prep[key])))
            if prep.get("missed_content_weeks"):
                claims.append(
                    _claim(
                        "dashboard",
                        f"Missed lecture content weeks: {', '.join(map(str, prep['missed_content_weeks']))}.",
                    )
                )
        related_activity = _as_mapping(related.get("activity_summary"))
        if related_activity:
            claims.extend(_claims_from_activity(related_page, related_activity))

        course_context = related.get("course_task_context")
        if course_context:
            claims.append(_claim("course_material", str(course_context)))

    return _dedupe_claims(claims)


def _claims_from_activity(page_key: str, activity: Mapping[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if page_key == "debate":
        claims.append(
            _claim(
                "dashboard",
                f"Debate activity shows {activity.get('views')} views, "
                f"{activity.get('posts')} posts, and {activity.get('replies')} replies.",
            )
        )
        if activity.get("active_post_weeks") or activity.get("active_reply_weeks"):
            claims.append(
                _claim(
                    "dashboard",
                    "Debate active weeks include posts in "
                    f"{_join_list(activity.get('active_post_weeks'))} and replies in "
                    f"{_join_list(activity.get('active_reply_weeks'))}.",
                )
            )
        if activity.get("unique_students_i_viewed") is not None:
            claims.append(
                _claim(
                    "dashboard",
                    f"The student viewed {activity.get('unique_students_i_viewed')} unique students, "
                    f"and {activity.get('unique_students_who_viewed_me')} unique students viewed the student.",
                )
            )
    elif page_key == "reflection":
        claims.append(
            _claim(
                "dashboard",
                f"Reflection activity shows {activity.get('total_chars')} edited characters "
                f"across {activity.get('active_weeks')} active weeks.",
            )
        )
        if activity.get("active_week_list"):
            claims.append(_claim("dashboard", f"Reflection active weeks: {_join_list(activity.get('active_week_list'))}."))
    elif page_key == "lecture":
        claims.append(
            _claim(
                "dashboard",
                f"Lecture activity shows {activity.get('viewed_videos')} viewed videos and "
                f"an average view percentage of {activity.get('average_video_view_percent')}.",
            )
        )
        if activity.get("missed_content_weeks"):
            claims.append(_claim("dashboard", f"Missed lecture content weeks: {_join_list(activity.get('missed_content_weeks'))}."))
    elif page_key == "resources":
        claims.append(
            _claim(
                "dashboard",
                f"Resources activity shows {activity.get('views')} resource views "
                f"across {activity.get('active_weeks')} active weeks.",
            )
        )
        if activity.get("most_active_day"):
            claims.append(_claim("dashboard", f"The most active resource day is {activity.get('most_active_day')}."))
    return claims


def _context_claims(chunks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convert retrieved chunks into supporting evidence claims."""

    claims: list[dict[str, str]] = []
    for chunk in chunks:
        text = chunk.get("claim") or chunk.get("text") or ""
        text = _compact(text)
        if not text:
            continue
        title = chunk.get("title", "")
        source_file = chunk.get("source_file", "")
        source_type = chunk.get("source_type", "course_material")
        if source_type not in SUPPORTED_SOURCE_TYPES:
            source_type = "course_material"
        prefix = "The course material"
        if source_file:
            prefix += f" from {source_file}"
        if title:
            prefix += f" ({title})"
        prefix += " suggests: "
        claims.append(_claim(source_type, prefix + _short_excerpt(text)))
    return _dedupe_claims(claims)


def _student_state(page_key: str, selected_evidence: Mapping[str, Any]) -> str:
    page = _as_mapping(selected_evidence.get(page_key, {}))
    activity = _as_mapping(page.get("activity_summary"))
    if not activity:
        return "The selected evidence does not include enough page-specific activity to describe a detailed state."

    if page_key == "debate":
        return (
            f"you have {activity.get('views')} debate views, {activity.get('posts')} posts, "
            f"and {activity.get('replies')} replies across the selected period."
        )
    if page_key == "reflection":
        return (
            f"you have {activity.get('total_chars')} edited reflection characters across "
            f"{activity.get('active_weeks')} active weeks."
        )
    if page_key == "lecture":
        missed = _join_list(activity.get("missed_content_weeks"))
        return (
            f"you viewed {activity.get('viewed_videos')} lecture videos with an average view "
            f"percentage of {activity.get('average_video_view_percent')}; missed content weeks: {missed}."
        )
    if page_key == "resources":
        weekly = _week_extremes_text(activity.get("weekly_counts"))
        extra = f"; {weekly}" if weekly else ""
        return (
            f"you have {activity.get('views')} resource views across "
            f"{activity.get('active_weeks')} active weeks{extra}."
        )
    return "the selected dashboard evidence shows activity patterns for this page."


def _main_issue(
    page_key: str,
    query_type: str,
    selected_evidence: Mapping[str, Any],
) -> str:
    page = _as_mapping(selected_evidence.get(page_key, {}))
    activity = _as_mapping(page.get("activity_summary"))

    if page_key == "reflection" and _to_number(activity.get("active_weeks")) == 0:
        return "create a first baseline reflection entry before comparing consistency across weeks."
    if query_type == "planning_or_strategy":
        return "choose a small next action that connects the current page activity with preparation evidence."
    if page_key == "debate":
        posts = _to_number(activity.get("posts"))
        replies = _to_number(activity.get("replies"))
        views = _to_number(activity.get("views"))
        if views and views > max(posts, replies):
            return "turn some debate viewing into a specific post or reply."
        return "make debate participation more deliberate and easier to repeat."
    if page_key == "reflection":
        if _to_number(activity.get("active_weeks")) == 0:
            return "create a first baseline reflection entry before comparing consistency across weeks."
        return "make reflection activity more structured, not just longer."
    if page_key == "lecture":
        return "use lecture viewing as preparation for a concrete follow-up activity."
    if page_key == "resources":
        return "turn resource access into a focused preparation routine."
    return "select a focused next learning action from the available dashboard evidence."


def _recommended_action(
    page_key: str,
    query_type: str,
    selected_evidence: Mapping[str, Any],
) -> str:
    reflection = _as_mapping(_as_mapping(selected_evidence.get("reflection", {})).get("activity_summary"))
    if page_key == "reflection" and _to_number(reflection.get("active_weeks")) == 0:
        return "create your first short baseline reflection entry, then use it to establish a repeatable routine."
    if query_type == "planning_or_strategy":
        if page_key == "debate":
            return "pair one preparation task with one debate reply next week."
        if page_key == "reflection":
            return "pair one learning activity review with one structured reflection entry next week."
        return "pick two small actions for next week: one preparation action and one follow-up activity."
    if page_key == "debate":
        return "choose one debate post you have already viewed and write one short, structured reply."
    if page_key == "reflection":
        return "write one focused reflection entry that links a learning activity, one course concept, and one next step."
    if query_type == "planning_or_strategy":
        return "pick two small actions for next week: one preparation action and one contribution or reflection action."
    if page_key == "lecture":
        return "watch or revisit one selected lecture segment, then record one point to use in debate or reflection."
    if page_key == "resources":
        return "choose one resource from an active study day and turn it into a brief note for a later activity."
    return "choose one small, evidence-linked action for the next study session."


def _action_steps(
    page_key: str,
    query_type: str,
    selected_evidence: Mapping[str, Any],
) -> list[str]:
    reflection = _as_mapping(_as_mapping(selected_evidence.get("reflection", {})).get("activity_summary"))
    if page_key == "reflection" and _to_number(reflection.get("active_weeks")) == 0:
        return [
            "Choose one recent learning activity to reflect on.",
            "Create the first baseline reflection entry using what happened, what you learned, and what comes next.",
            "Choose a realistic day for the next entry so a weekly pattern can begin.",
        ]
    if query_type == "planning_or_strategy":
        if page_key == "debate":
            return [
                "Choose one lecture or resource pattern from the selected evidence to prepare from.",
                "Pick one debate post you have already viewed.",
                "Write one short reply that summarises the peer's point and adds your own view.",
            ]
        if page_key == "reflection":
            return [
                "Choose one learning activity from the selected evidence.",
                "Write one reflection paragraph connecting it to a course concept.",
                "End with one next-step plan for the following week.",
            ]
        return [
            "Select one preparation gap or pattern from the selected evidence.",
            "Schedule one short preparation task before the next class activity.",
            "Choose one follow-up activity that uses that preparation.",
        ]
    if page_key == "debate":
        return [
            "Choose one debate post you have already viewed.",
            "Write a short reply that first summarises the peer's point.",
            "Add your own view or a link to one lecture/resource idea you prepared.",
            "End with one follow-up question that invites the peer to respond.",
        ]
    if page_key == "reflection":
        return [
            "Choose one recent learning activity from the dashboard.",
            "Connect it to one course concept or debate point.",
            "Explain what changed in your understanding.",
            "Write one next-step plan you can try before the next reflection.",
        ]
    if page_key == "lecture":
        return [
            "Pick one missed or partly watched lecture week from the selected evidence.",
            "Watch a focused segment and note one idea.",
            "Use that idea in one debate reply or reflection entry.",
        ]
    if page_key == "resources":
        return [
            "Pick one resource linked to the current topic.",
            "Write two bullet points from it.",
            "Use one bullet point in debate, lecture review, or reflection.",
        ]
    return [
        "Pick one specific activity from the selected evidence.",
        "Turn it into one short action for the next study session.",
    ]


def _why_this_matters(
    page_key: str,
    selected_evidence: Mapping[str, Any],
    chunks: list[dict[str, str]],
) -> str:
    context = _first_context_claim(chunks)
    if context:
        return context

    if page_key == "debate":
        return "the dashboard evidence can show whether debate activity is mainly viewing or also includes visible contribution."
    if page_key == "reflection":
        return "the dashboard evidence can show whether reflection writing is distributed across weeks, while not judging reflection quality."
    if page_key == "lecture":
        return "the dashboard evidence can show whether recorded lecture activity is being used as preparation."
    if page_key == "resources":
        return "the dashboard evidence can show whether resource access is regular enough to support later activities."
    return "the selected dashboard evidence can support a small next step, but it cannot directly measure learning quality."


def _why_this_fits_student(page_key: str, selected_evidence: Mapping[str, Any]) -> str:
    evidence = selected_evidence
    if page_key == "debate":
        debate = _as_mapping(_as_mapping(evidence.get("debate", {})).get("activity_summary"))
        network = _as_mapping(_as_mapping(evidence.get("debate", {})).get("network_summary"))
        lecture = _as_mapping(_as_mapping(evidence.get("lecture", {})).get("preparation_summary"))
        resources = _as_mapping(_as_mapping(evidence.get("resources", {})).get("preparation_summary"))
        parts = []
        if debate:
            parts.append(
                f"your debate record includes {debate.get('views')} views, "
                f"{debate.get('posts')} posts, and {debate.get('replies')} replies"
            )
        if lecture.get("preparation_pattern"):
            parts.append(_strip_terminal_punct(lecture["preparation_pattern"]))
        if resources.get("preparation_pattern"):
            parts.append(_strip_terminal_punct(resources["preparation_pattern"]))
        if network.get("available"):
            reply = _as_mapping(network.get("reply_network"))
            view = _as_mapping(network.get("view_network"))
            if reply.get("unique_people") is not None:
                parts.append(f"the reply network includes {reply.get('unique_people')} unique people")
            if view.get("unique_people") is not None:
                parts.append(f"the view network includes {view.get('unique_people')} unique people")
        return "; ".join(parts) + "." if parts else "it uses the selected debate evidence rather than assuming a general weakness."
    if page_key == "reflection":
        reflection = _as_mapping(_as_mapping(evidence.get("reflection", {})).get("activity_summary"))
        if reflection:
            if _to_number(reflection.get("active_weeks")) == 0:
                return (
                    "the selected evidence shows no active reflection week yet, so the plan starts by creating a first baseline entry."
                )
            weekly = _week_extremes_text(reflection.get("weekly_character_counts"))
            extra = f"; {weekly}" if weekly else ""
            return (
                f"it builds on your existing reflection activity: {reflection.get('total_chars')} edited characters "
                f"across {reflection.get('active_weeks')} active weeks{extra}."
            )
    if page_key == "resources":
        resources = _as_mapping(_as_mapping(evidence.get("resources", {})).get("activity_summary"))
        if resources:
            weekly = _week_extremes_text(resources.get("weekly_counts"))
            most_active = resources.get("most_active_day")
            details = [
                f"your resource activity shows {resources.get('views')} views across {resources.get('active_weeks')} active weeks"
            ]
            if most_active:
                details.append(f"your most active day is {most_active}")
            if weekly:
                details.append(weekly)
            return "; ".join(details) + "."
    if page_key == "lecture":
        lecture = _as_mapping(_as_mapping(evidence.get("lecture", {})).get("activity_summary"))
        if lecture:
            return (
                f"your lecture evidence shows {lecture.get('viewed_videos')} viewed videos, "
                f"average view percentage {lecture.get('average_video_view_percent')}, and missed weeks "
                f"{_join_list(lecture.get('missed_content_weeks'))}."
            )
    return "specific dashboard evidence is not available for a stronger fit rationale."


def _limitations(evidence_summary: Mapping[str, Any], chunks: list[dict[str, str]]) -> str:
    limits = []
    uncertainty = str(evidence_summary.get("uncertainty", "")).strip()
    if uncertainty:
        limits.append(uncertainty)
    if not chunks:
        limits.append(
            "No retrieved course-material or literature context was provided, so the recommendation is grounded only in dashboard evidence."
        )
    else:
        if any(str(chunk.get("source_type", "")).lower() == "moodle_link" for chunk in chunks):
            limits.append(
                "Some retrieved course-material context is link-level, so it can identify relevant course items but may not summarise their full content."
            )
        limits.append(
            "Retrieved course material is used only for task or course guidance; dashboard evidence is still needed for claims about this student's activity."
        )
    return " ".join(limits) if limits else "Use this as a dashboard-grounded suggestion, not as a judgement of learning quality."


def _normalise_context_chunks(
    chunks: Sequence[Mapping[str, Any] | str] | None,
) -> list[dict[str, str]]:
    normalised: list[dict[str, str]] = []
    for chunk in chunks or []:
        if isinstance(chunk, str):
            normalised.append({"source_type": "course_material", "text": chunk})
            continue
        text = str(chunk.get("claim") or chunk.get("text") or chunk.get("content") or "").strip()
        source_type = str(chunk.get("source_type") or chunk.get("type") or "course_material").strip()
        if source_type not in SUPPORTED_SOURCE_TYPES:
            source_type = "course_material"
        normalised.append(
            {
                "source_type": source_type,
                "text": text,
                "claim": str(chunk.get("claim") or "").strip(),
                "title": str(chunk.get("title") or "").strip(),
                "source_file": str(chunk.get("source_file") or "").strip(),
                "chunk_id": str(chunk.get("chunk_id") or "").strip(),
                "task_type": str(chunk.get("task_type") or "").strip(),
                "week": str(chunk.get("week") or "").strip(),
            }
        )
    return normalised


def _first_context_claim(chunks: list[dict[str, str]]) -> str:
    for chunk in chunks:
        text = chunk.get("claim") or chunk.get("text") or ""
        if text:
            title = chunk.get("title", "")
            source_file = chunk.get("source_file", "")
            source = f" from {source_file}" if source_file else ""
            label = f" ({title})" if title else ""
            return _compact(f"The course material{source}{label} suggests: {_short_excerpt(text)}")
    return ""


def _normalise_page(page: str) -> str:
    page_l = str(page or "").strip().lower()
    if page_l in {"resources", "resource", "moodle"}:
        return "resources"
    if page_l in {"lecture", "lectures", "video", "panopto"}:
        return "lecture"
    if page_l in {"debate", "debates", "forum"}:
        return "debate"
    if page_l in {"reflection", "reflections", "gdocs", "google docs"}:
        return "reflection"
    return page_l


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _claim(source_type: str, claim: str) -> dict[str, str]:
    return {"source_type": source_type, "claim": _compact(claim)}


def _dedupe_claims(claims: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for claim in claims:
        key = (claim.get("source_type", ""), claim.get("claim", ""))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        out.append(claim)
    return out


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _short_excerpt(text: str, max_chars: int = 240) -> str:
    text = _compact(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _strip_terminal_punct(text: Any) -> str:
    return str(text or "").strip().rstrip(".;")


def _join_list(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        return ", ".join(map(str, value))
    return "no selected weeks"


def _week_extremes_text(weekly: Any) -> str:
    if not isinstance(weekly, Mapping) or not weekly:
        return ""
    values = []
    for week, count in weekly.items():
        try:
            values.append((str(week), float(count)))
        except (TypeError, ValueError):
            continue
    if not values:
        return ""
    low_week, low_value = min(values, key=lambda item: item[1])
    high_week, high_value = max(values, key=lambda item: item[1])
    if low_week == high_week:
        return f"{high_week} is the only selected week"
    low = int(low_value) if low_value.is_integer() else low_value
    high = int(high_value) if high_value.is_integer() else high_value
    return f"lowest selected week is {low_week} ({low}) and highest selected week is {high_week} ({high})"


def _to_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
