"""Deterministic multi-valued content-role extraction for Retrieval v2.4."""

from __future__ import annotations

import re

from utils.retrieval_v2.models import CourseChunkV2


SUPPORTED_CONTENT_ROLES = (
    "lecture_overview",
    "lecture_learning_outcomes",
    "lecture_link",
    "reflection_prompt",
    "part_a_reflection_guidance",
    "assessment_guidance",
    "assessment_link",
    "reading_list",
    "reading_metadata",
    "moodle_link",
    "debate_prompt",
    "weekly_overview",
)


def derive_content_roles(chunk: CourseChunkV2) -> tuple[str, ...]:
    title = chunk.title.casefold()
    hierarchy = " > ".join(chunk.section_path).casefold()
    local_hierarchy = " > ".join(chunk.section_path[-2:]).casefold()
    body = chunk.text.casefold()
    context = " ".join((title, local_hierarchy, body))
    urls = [
        str(value).casefold()
        for value in (
            *(chunk.metadata.get("urls") or []),
            chunk.metadata.get("source_url") or "",
        )
        if value
    ]
    has_url = bool(urls or re.search(r"https?://|\burl\b", context))
    has_moodle = any("moodle.ucl.ac.uk" in url for url in urls)
    roles: set[str] = set()

    if chunk.material_type == "weekly_page" and re.search(
        r"\bweek\s*\d+\b|\bw\d+\b|select section week", title + " " + body
    ):
        roles.add("weekly_overview")
    if (
        "this week we will discuss" in body
        or "lecture focus" in context
        or (
            chunk.material_type in {"weekly_page", "lecture"}
            and "learning analytics" in context
            and len(body) >= 180
        )
    ):
        roles.add("lecture_overview")
    if re.search(r"\blearning outcomes?\b|\bby the end of (?:this )?(?:week|session)\b", context):
        roles.add("lecture_learning_outcomes")
        roles.add("lecture_overview")
    if has_url and re.search(r"\blecture\b|\brecording\b|\bpre-recorded\b", title + " " + local_hierarchy):
        roles.add("lecture_link")
    if (
        re.search(r"\bindividual reflection\b|\breflection questions?\b|\breflect upon\b", context)
        or ("reflection" in title and "?" in body)
    ):
        roles.add("reflection_prompt")
    if (
        chunk.assessment_part
        or re.search(
            r"\bassessment (?:guidance|criteria|requirements?)\b|"
            r"academic reflections?|reflective (?:writing|content)|general guidance on writing academic",
            context,
        )
        or re.search(r"\bpart\s+[ab]\b", title + " " + body)
        or "chapterid=207847" in context
    ):
        roles.add("assessment_guidance")
    if re.search(
        r"academic reflections?|reflective (?:writing|content)|general guidance on writing academic|"
        r"reflection guideline|chapterid=207847",
        context,
    ):
        roles.add("part_a_reflection_guidance")
        roles.add("assessment_guidance")
    if has_url and (
        "assessment" in context
        or "chapterid=207847" in context
        or "part a" in context
        or "reflection guideline" in context
    ):
        roles.add("assessment_link")
    if chunk.material_type == "reading" or re.search(r"\bcore readings?\b|\bfurther readings?\b", context):
        roles.add("reading_metadata")
    if chunk.material_type == "reading" or re.search(r"\breading list\b|\bw\d+ readings?\b|\bweek\s*\d+.*readings?\b", context):
        roles.add("reading_list")
    if has_moodle:
        roles.add("moodle_link")
    if re.search(r"\bdebate\b|\bthis house believes\b", context) and (
        "?" in body or "movement" in context or "forum" in context
    ):
        roles.add("debate_prompt")
    return tuple(role for role in SUPPORTED_CONTENT_ROLES if role in roles)


ROLE_COMPATIBILITY = {
    "lecture": {"lecture_overview", "lecture_learning_outcomes", "lecture_link"},
    "reflection": {"reflection_prompt", "part_a_reflection_guidance", "assessment_guidance"},
    "assessment": {"part_a_reflection_guidance", "assessment_guidance", "assessment_link"},
    "moodle_link": {"moodle_link", "assessment_link", "lecture_link"},
    "reading": {"reading_list", "reading_metadata"},
    "debate": {"debate_prompt"},
    "weekly_page": {"weekly_overview"},
}
