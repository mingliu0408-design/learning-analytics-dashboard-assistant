"""Lightweight deterministic retrieval over local course materials.

This module is intentionally small and inspectable. It builds an in-memory
index from the anonymised course-material files bundled with the repository,
cleans obvious Moodle/navigation noise, and retrieves relevant chunks with a
transparent lexical scorer. It does not use external APIs, vector databases,
persistent memory, or online services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html
import math
from pathlib import Path
import re
from typing import Any, Sequence

from utils.course_metadata import LECTURE_METADATA_BY_WEEK


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CourseChunk:
    """One cleaned, source-traceable course-material chunk."""

    chunk_id: str
    source_file: str
    source_type: str
    title: str
    text: str
    week: str | None = None
    page: str | None = None
    task_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    """Result returned by the course-material retriever."""

    query: str
    chunks: list[CourseChunk]
    retrieval_used: bool
    reason: str = ""


_CHUNK_CACHE: list[CourseChunk] | None = None

COURSE_MATERIAL_PATHS = {
    "weekly_pages": PROJECT_ROOT / "System Data" / "Module" / "Module Weekly Pages.html",
    "handbook": PROJECT_ROOT / "System Data" / "Module" / "Module Handbook.doc",
    "readings": PROJECT_ROOT / "System Data" / "Module" / "Module readings.pdf",
    "moodle_links": PROJECT_ROOT / "input" / "moodle_links.pdf",
    "references": PROJECT_ROOT / "input" / "references.txt",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "should",
    "the",
    "this",
    "to",
    "what",
    "where",
    "which",
    "with",
    "you",
    "your",
}

NOISE_PATTERNS = (
    r"^skip to main content$",
    r"^expand all$",
    r"^collapse all$",
    r"^search course$",
    r"^ucl moodle$",
    r"^my courses$",
    r"^feedback tracker$",
    r"^dashboard$",
    r"^course: .*moodle$",
    r"^completion requirements?$",
    r"^mark as done$",
    r"^done: view$",
    r"^to do:.*$",
    r"^restricted.*$",
    r"^not available.*$",
    r"^javascript.*$",
    r"^new relic.*$",
    r"^var [a-z0-9_]+.*$",
    r"^\{.*\}$",
)

RETRIEVAL_QUERY_TYPES = {
    "course_content_question",
    "hybrid_course_and_planning",
    "reflection_structure_question",
    "reflection_structure",
    "reflection_guidance",
    "debate_guidance",
    "assessment_guidance",
}


def load_course_material_chunks(force_rebuild: bool = False) -> list[CourseChunk]:
    """Load or build the in-memory course-material chunks."""

    global _CHUNK_CACHE
    if _CHUNK_CACHE is None or force_rebuild:
        _CHUNK_CACHE = build_course_chunks()
    return list(_CHUNK_CACHE)


def clean_course_text(raw_text: str) -> str:
    """Clean obvious Moodle/navigation/HTML noise before chunking.

    The goal is not perfect document conversion. It is to remove high-volume
    navigation, scripts, styles, buttons, and repeated Moodle boilerplate so
    retrieval favours course/task content.
    """

    raw = str(raw_text or "")
    raw = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<nav\b.*?</nav>", " ", raw)
    raw = re.sub(r"(?is)<header\b.*?</header>", " ", raw)
    raw = re.sub(r"(?is)<footer\b.*?</footer>", " ", raw)
    raw = re.sub(r"(?is)<xml\b.*?</xml>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(?:p|div|li|h[1-6]|tr|td|section|article)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = raw.replace("\xa0", " ")

    lines: list[str] = []
    seen_consecutive = ""
    for line in raw.splitlines():
        cleaned = _compact(line)
        if not cleaned or _is_noise_line(cleaned):
            continue
        if cleaned == seen_consecutive:
            continue
        seen_consecutive = cleaned
        lines.append(cleaned)
    return "\n".join(lines)


def build_course_chunks() -> list[CourseChunk]:
    """Build cleaned course-material chunks from the local repository files."""

    chunks: list[CourseChunk] = []
    chunks.extend(_chunks_from_course_metadata())
    chunks.extend(_chunks_from_weekly_pages(COURSE_MATERIAL_PATHS["weekly_pages"]))
    chunks.extend(_chunks_from_handbook(COURSE_MATERIAL_PATHS["handbook"]))
    chunks.extend(_chunks_from_pdf(COURSE_MATERIAL_PATHS["readings"], source_type="reading", task_type="reading"))
    chunks.extend(
        _chunks_from_pdf(COURSE_MATERIAL_PATHS["moodle_links"], source_type="moodle_link", task_type="moodle_link")
    )
    chunks.extend(_chunks_from_references(COURSE_MATERIAL_PATHS["references"]))
    return _dedupe_chunks(chunks)


def should_use_course_retrieval(query: str, query_type: str | None = None) -> bool:
    """Return whether a query needs course-material context.

    Dashboard-only metric, provenance, accuracy, and data-source questions are
    intentionally excluded unless the wording also asks about course content,
    readings, tasks, assessment, or links.
    """

    q = _normalise_text(query)
    qt = str(query_type or "").strip()
    if not q:
        return False

    if _is_dashboard_metric_only_query(q, qt):
        return False

    if _has_explicit_course_material_intent(q):
        return True

    if qt in {
        "hybrid_course_and_planning",
        "reflection_structure_question",
        "reflection_structure",
        "reflection_guidance",
        "debate_guidance",
        "assessment_guidance",
    }:
        return True

    if qt == "course_content_question":
        return _has_course_content_question(q)

    if qt == "access_or_capability_question":
        return _has_access_or_link_retrieval_intent(q)

    return False


def _is_dashboard_metric_only_query(q: str, query_type: str | None = None) -> bool:
    """Detect dashboard metric questions that should stay dashboard-only.

    The retriever should not be used for metrics such as ``assessment views``
    or ``Resources_views`` just because they contain course-looking words like
    ``assessment`` or ``resources``.
    """

    metric_terms = (
        r"\bassessment\s+views?\b",
        r"\bresources?\s+views?\b",
        r"\bresource\s+activity\b",
        r"\bdebate\s+(?:views?|posts?|replies?)\b",
        r"\breply\s+network\b",
        r"\bview\s+network\b",
        r"\bvideo\s+(?:views?|view\s*%|percentage)\b",
        r"\b(?:total\s+chars?|absstrcount|characters?|chars?)\b",
    )
    metric_intent = (
        r"\b(?:metric|mean|means|count as|counts as|measured|measurement|show|shows|interpret|"
        r"accurate|accuracy|data source|source|logs?|visibility)\b"
    )
    if any(re.search(pattern, q) for pattern in metric_terms):
        return True
    if query_type in {"metric_clarification", "technical_data_question"} and re.search(metric_intent, q):
        return not _has_explicit_non_metric_course_context(q)
    return False


def _has_explicit_course_material_intent(q: str) -> bool:
    """Return true for explicit course/task/content/material requests.

    This intentionally excludes vague dashboard or memory follow-up wording.
    A resolved memory query that merely mentions "lecture" or "reflection" is
    not enough; the student must ask for course material, task guidance, a
    prompt, a link, readings, or lecture content.
    """

    explicit_patterns = (
        r"\bwhat\s+(?:does|do)\s+(?:the\s+)?(?:course|module)\s+materials?\s+say\b",
        r"\baccording\s+to\s+(?:the\s+)?(?:course|module|weekly|lecture|reading|assessment|reflection|debate|handbook)\b",
        r"\bbased\s+on\s+(?:the\s+)?(?:course\s+materials?|module\s+materials?|weekly\s+page|lecture\s+guidance|reflection\s+prompt|debate\s+task|assessment|part\s+[ab])\b",
        r"\busing\s+(?:(?:w[0-9]+|week\s*[0-9]+)\s+)?(?:lecture\s+guidance|course\s+materials?|module\s+materials?|reflection\s+prompt|debate\s+task|assessment\s+guidance)\b",
        r"\b(?:course\s+materials?|module\s+materials?|module\s+guide|weekly\s+page|handbook|assignment\s+brief|assessment\s+brief|assessment\s+criteria|marking\s+criteria)\b",
        r"\b(?:reading|readings|reading\s+list|article|paper|literature|reference|references|citation)\b",
        r"\b(?:reflection\s+prompt|reflection\s+structure|reflective\s+writing|portfolio|part\s+a|part\s+b)\b",
        r"\b(?:debate\s+prompt|debate\s+task|debate\s+question|forum\s+discussion|participation\s+guidance)\b",
        r"\b(?:moodle\s+link|course\s+link|live\s+session\s+link|recording\s+link)\b",
        r"\b(?:where\s+is|find|locate)\b.{0,80}\b(?:link|moodle|live\s+session|recording|lecture|reading|resource)\b",
        r"\b(?:w[0-9]+|week\s*[0-9]+)(?:'s)?\b(?=.{0,80}\b(?:lecture|pre-recorded\s+lecture|recorded\s+lecture|video|live\s+session|debate\s+task|reflection\s+prompt|assessment|readings?)\b)(?=.{0,80}\b(?:about|topic|covered|content|readings?|link|task|prompt|guidance)\b)",
        r"\b(?:lecture|pre-recorded\s+lecture|recorded\s+lecture|video|session)\b.{0,80}\b(?:about|topic|covered|content|guidance)\b",
        r"\b(?:what\s+is|what's|what\s+was|what\s+were)\b.{0,80}\b(?:lecture|pre-recorded\s+lecture|recorded\s+lecture|readings?|debate\s+task|reflection\s+prompt|assessment)\b.{0,80}\b(?:about|topic|asking|ask|require|for)\b",
    )
    return any(re.search(pattern, q) for pattern in explicit_patterns)


def _has_course_content_question(q: str) -> bool:
    """Detect course-content questions when the classifier already suggests content."""

    return bool(
        re.search(
            r"\b(?:lecture|pre-recorded\s+lecture|recorded\s+lecture|video|session)\b.{0,80}\b(?:about|topic|covered|content)\b",
            q,
        )
        or re.search(
            r"\b(?:w[0-9]+|week\s*[0-9]+)(?:'s)?\b(?=.{0,80}\b(?:lecture|pre-recorded\s+lecture|recorded\s+lecture|video|live\s+session)\b)(?=.{0,80}\b(?:about|topic|covered|content|link)\b)",
            q,
        )
        or re.search(r"\b(?:readings?|reading\s+list|debate\s+task|reflection\s+prompt|assessment\s+brief|course\s+materials?|module\s+materials?)\b", q)
    )


def _has_access_or_link_retrieval_intent(q: str) -> bool:
    """Retrieve for locating course links, not for pure capability questions."""

    return bool(
        re.search(r"\b(?:where\s+is|find|locate)\b.{0,80}\b(?:link|moodle|live\s+session|recording)\b", q)
        or re.search(r"\b(?:moodle\s+link|course\s+link|live\s+session\s+link|recording\s+link)\b", q)
    )


def _has_explicit_non_metric_course_context(q: str) -> bool:
    """Return whether a technical/metric query also asks for course context."""

    return bool(
        re.search(
            r"\b(?:course\s+materials?|module\s+materials?|weekly\s+page|handbook|readings?|"
            r"reflection\s+prompt|debate\s+task|assessment\s+criteria|lecture\s+guidance|moodle\s+link)\b",
            q,
        )
    )


def retrieve_course_chunks(
    query: str,
    query_type: str | None = None,
    top_k: int = 4,
) -> RetrievalResult:
    """Retrieve course-material chunks for a query with lexical scoring."""

    query = str(query or "").strip()
    if not should_use_course_retrieval(query, query_type):
        return RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was not needed for this query.",
        )

    chunks = load_course_material_chunks()
    if not chunks:
        return RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="No course-material chunks were available.",
        )

    scored = [
        (score, chunk)
        for chunk in chunks
        if (score := _score_chunk(query=query, query_type=query_type, chunk=chunk)) > 0
    ]
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
    if not scored or scored[0][0] < 2.0:
        return RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was requested, but no sufficiently relevant chunk was found.",
        )

    selected = [chunk for _, chunk in scored[: max(1, int(top_k))]]
    return RetrievalResult(
        query=query,
        chunks=selected,
        retrieval_used=True,
        reason=f"Retrieved {len(selected)} course-material chunk(s) using lexical scoring.",
    )


def format_retrieved_chunks_for_prompt(chunks: Sequence[CourseChunk]) -> str:
    """Format retrieved chunks as transparent prompt context."""

    if not chunks:
        return "No course-material chunks were retrieved."
    parts: list[str] = []
    for chunk in chunks:
        labels = [
            f"id={chunk.chunk_id}",
            f"source={chunk.source_file}",
            f"type={chunk.source_type}",
        ]
        if chunk.week:
            labels.append(f"week={chunk.week}")
        if chunk.task_type:
            labels.append(f"task_type={chunk.task_type}")
        parts.append(
            "["
            + "; ".join(labels)
            + "]\n"
            + f"Title: {chunk.title}\n"
            + f"Text: {chunk.text}"
        )
    return "\n\n".join(parts)


def chunks_to_dicts(chunks: Sequence[CourseChunk]) -> list[dict[str, Any]]:
    """Convert chunks to JSON-serialisable dictionaries."""

    return [
        {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_file,
            "source_type": chunk.source_type,
            "title": chunk.title,
            "text": chunk.text,
            "week": chunk.week,
            "page": chunk.page,
            "task_type": chunk.task_type,
            "metadata": dict(chunk.metadata),
        }
        for chunk in chunks
    ]


def retrieval_result_to_dict(result: RetrievalResult) -> dict[str, Any]:
    """Convert a retrieval result to a JSON-serialisable dictionary."""

    return {
        "query": result.query,
        "retrieval_used": result.retrieval_used,
        "reason": result.reason,
        "chunks": chunks_to_dicts(result.chunks),
        "retrieved_chunk_ids": [chunk.chunk_id for chunk in result.chunks],
        "retrieved_chunk_titles": [chunk.title for chunk in result.chunks],
        "retrieved_sources": [chunk.source_file for chunk in result.chunks],
    }


def _chunks_from_course_metadata() -> list[CourseChunk]:
    chunks: list[CourseChunk] = []
    for week, record in sorted(LECTURE_METADATA_BY_WEEK.items()):
        title = f"{week}: {record.get('title', '')}"
        source_notes = " ".join(map(str, record.get("source_notes", [])))
        text = _compact(
            " ".join(
                [
                    f"{week} lecture title: {record.get('title', '')}.",
                    f"Recorded lecture title: {record.get('recorded_lecture_title', '')}.",
                    f"Summary: {record.get('content_summary', '')}.",
                    str(record.get("disambiguation_note", "")),
                    f"Source notes: {source_notes}",
                ]
            )
        )
        chunks.append(
            CourseChunk(
                chunk_id=f"course_metadata_{week.lower()}",
                source_file="utils/course_metadata.py",
                source_type="course_metadata",
                title=title,
                text=text,
                week=week,
                page="Lecture",
                task_type="lecture",
                metadata={"confidence": record.get("confidence", "")},
            )
        )
    return chunks


def _chunks_from_weekly_pages(path: Path) -> list[CourseChunk]:
    if not path.exists():
        return []
    text = _read_text(path)
    lines = _lines(clean_course_text(text))
    starts = [idx for idx, line in enumerate(lines) if re.match(r"^Week\s+\d+\b", line, flags=re.IGNORECASE)]
    chunks: list[CourseChunk] = []

    if starts and starts[0] > 0:
        general = "\n".join(lines[: starts[0]])
        if len(general) > 120:
            chunks.extend(
                _split_long_text(
                    chunk_id_prefix="weekly_general",
                    source_file=_relative_source(path),
                    source_type="weekly_page",
                    title="General Moodle course page material",
                    text=general,
                    task_type="course_material",
                )
            )

    for section_no, start in enumerate(starts):
        end = starts[section_no + 1] if section_no + 1 < len(starts) else len(lines)
        section_lines = lines[start:end]
        if not section_lines:
            continue
        header = section_lines[0]
        week = _extract_week(header)
        section_text = "\n".join(section_lines)
        week_prefix = f"{week.lower()}_{section_no}" if week else str(section_no)
        chunks.extend(
            _split_long_text(
                chunk_id_prefix=f"weekly_{week_prefix}",
                source_file=_relative_source(path),
                source_type="weekly_page",
                title=header,
                text=section_text,
                week=week,
                task_type="weekly_overview",
            )
        )

        task_counter = 0
        for idx, line in enumerate(section_lines[1:], start=1):
            task_type = _infer_task_type(line)
            if task_type == "course_material":
                continue
            task_counter += 1
            context_lines = [header, line]
            if idx + 1 < len(section_lines) and _infer_task_type(section_lines[idx + 1]) == "course_material":
                context_lines.append(section_lines[idx + 1])
            chunks.append(
                CourseChunk(
                    chunk_id=f"weekly_{week_prefix}_{task_type}_{task_counter}",
                    source_file=_relative_source(path),
                    source_type="weekly_page",
                    title=line[:120],
                    text=_truncate_text(" ".join(context_lines)),
                    week=week,
                    page=_page_from_task(task_type),
                    task_type=task_type,
                    metadata={"section_title": header},
                )
            )
    return chunks


def _chunks_from_handbook(path: Path) -> list[CourseChunk]:
    if not path.exists():
        return []
    text = _read_text(path, encoding="latin-1")
    lines = _lines(clean_course_text(text))
    starts: list[int] = []
    for idx, line in enumerate(lines):
        if _is_handbook_heading(line):
            starts.append(idx)
    if not starts:
        starts = [0]
    chunks: list[CourseChunk] = []
    for section_no, start in enumerate(starts):
        end = starts[section_no + 1] if section_no + 1 < len(starts) else len(lines)
        section_lines = lines[start:end]
        if not section_lines:
            continue
        title = section_lines[0]
        section_text = "\n".join(section_lines)
        task_type = _infer_task_type(section_text)
        source_type = "handbook"
        chunks.extend(
            _split_long_text(
                chunk_id_prefix=f"handbook_{_slug(title) or section_no}",
                source_file=_relative_source(path),
                source_type=source_type,
                title=title,
                text=section_text,
                task_type=task_type,
                page=_page_from_task(task_type),
            )
        )
    return chunks


def _chunks_from_pdf(path: Path, source_type: str, task_type: str) -> list[CourseChunk]:
    if not path.exists():
        return []
    text_by_page = _extract_pdf_pages(path)
    chunks: list[CourseChunk] = []
    for page_no, raw in enumerate(text_by_page, start=1):
        cleaned = clean_course_text(raw)
        if len(cleaned) < 80:
            continue
        week = _extract_week(cleaned)
        title = f"{path.stem} page {page_no}"
        if week:
            title = f"{week} {title}"
        chunks.extend(
            _split_long_text(
                chunk_id_prefix=f"{_slug(path.stem)}_p{page_no}",
                source_file=_relative_source(path),
                source_type=source_type,
                title=title,
                text=cleaned,
                week=week,
                task_type=task_type,
                page="Resources" if task_type in {"reading", "moodle_link"} else None,
                metadata={"page_number": page_no},
            )
        )
    return chunks


def _chunks_from_references(path: Path) -> list[CourseChunk]:
    if not path.exists():
        return []
    text = clean_course_text(_read_text(path))
    sections = [section.strip() for section in re.split(r"\n(?=#+\s+)", text) if section.strip()]
    chunks: list[CourseChunk] = []
    for idx, section in enumerate(sections or [text], start=1):
        lines = _lines(section)
        title = re.sub(r"^#+\s*", "", lines[0]) if lines else f"References {idx}"
        chunks.append(
            CourseChunk(
                chunk_id=f"references_{idx}",
                source_file=_relative_source(path),
                source_type="literature",
                title=title,
                text=_truncate_text(section),
                task_type=_infer_task_type(section),
                metadata={"source_note": "Local references file used by the dashboard/help materials."},
            )
        )
    return chunks


def _split_long_text(
    chunk_id_prefix: str,
    source_file: str,
    source_type: str,
    title: str,
    text: str,
    week: str | None = None,
    page: str | None = None,
    task_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    max_chars: int = 1400,
) -> list[CourseChunk]:
    text = _compact_multiline(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|(?<=\.)\s+(?=[A-Z0-9])", text) if p.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs or [text]:
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current} {paragraph}".strip()
        else:
            if current:
                pieces.append(current)
            current = paragraph
    if current:
        pieces.append(current)
    if not pieces:
        pieces = [text[:max_chars]]

    chunks: list[CourseChunk] = []
    for idx, piece in enumerate(pieces, start=1):
        suffix = f"_{idx}" if len(pieces) > 1 else ""
        chunks.append(
            CourseChunk(
                chunk_id=f"{chunk_id_prefix}{suffix}",
                source_file=source_file,
                source_type=source_type,
                title=title,
                text=_truncate_text(piece, max_chars=max_chars),
                week=week or _extract_week(piece),
                page=page,
                task_type=task_type or _infer_task_type(piece),
                metadata=metadata or {},
            )
        )
    return chunks


def _score_chunk(query: str, query_type: str | None, chunk: CourseChunk) -> float:
    q = _normalise_text(query)
    q_tokens = _expanded_query_tokens(q)
    c_text = _normalise_text(" ".join([chunk.title, chunk.text, chunk.source_file, chunk.task_type or "", chunk.week or ""]))
    c_tokens = set(_tokens(c_text))
    overlap = sum(2.0 if token in {"reflection", "debate", "reading", "readings", "lecture", "assessment"} else 1.0 for token in q_tokens if token in c_tokens)
    score = overlap / math.sqrt(max(8, len(c_tokens)))

    week = _extract_week(q)
    if week and chunk.week == week:
        score += 6.0
    elif week and week.lower() in c_text:
        score += 3.0

    for phrase in _important_phrases(q):
        if phrase in c_text:
            score += 2.0

    task_hints = _query_task_hints(q, query_type)
    if chunk.task_type in task_hints:
        score += 4.0
    if chunk.source_type in {"handbook", "course_metadata", "reading", "moodle_link"} and chunk.task_type in task_hints:
        score += 1.5
    if "reading" in task_hints and chunk.source_type in {"reading", "moodle_link", "weekly_page"}:
        score += 2.5
    if "reference" in task_hints and chunk.source_type == "literature":
        score += 6.0
    if "assessment" in task_hints and chunk.source_type == "handbook":
        score += 3.0
    if "lecture" in task_hints and chunk.source_type in {"course_metadata", "weekly_page"}:
        score += 2.0
    if "reflection" in task_hints and re.search(r"\b(reflect|reflection|portfolio|part a)\b", c_text):
        score += 3.0
    if "debate" in task_hints and re.search(r"\b(debate|forum|discussion)\b", c_text):
        score += 3.0
    if "moodle_link" in task_hints and re.search(r"\b(link|url|moodle|recording)\b", c_text):
        score += 3.0

    if re.search(r"\b(metric|data source|logs?|accurate|views?)\b", q) and not task_hints:
        score -= 4.0
    return score


def _expanded_query_tokens(q: str) -> set[str]:
    tokens = set(_tokens(q))
    if re.search(r"\breflect", q):
        tokens.update({"reflection", "reflective", "portfolio", "writing"})
    if "debate" in q or "forum" in q:
        tokens.update({"debate", "forum", "discussion"})
    if "reading" in q or "readings" in q:
        tokens.update({"reading", "readings", "resource"})
    if "lecture" in q or "video" in q:
        tokens.update({"lecture", "video", "recording"})
    if "assessment" in q or "assignment" in q:
        tokens.update({"assessment", "assignment", "criteria"})
    if "moodle" in q or "link" in q:
        tokens.update({"moodle", "link", "url"})
    return tokens


def _query_task_hints(q: str, query_type: str | None) -> set[str]:
    hints: set[str] = set()
    qt = str(query_type or "")
    if qt in {"reflection_structure_question", "reflection_structure", "reflection_guidance"}:
        hints.add("reflection")
    if qt == "course_content_question" and re.search(r"\b(lecture|video|recording|pre-recorded|w\d+|week\s+\d+)\b", q):
        hints.add("lecture")
    if "reflect" in q or "portfolio" in q or "part a" in q:
        hints.add("reflection")
    if "debate" in q or "forum" in q:
        hints.add("debate")
    if "reading" in q or "readings" in q or "paper" in q or "article" in q:
        hints.add("reading")
    if "reference" in q or "references" in q or "citation" in q:
        hints.add("reference")
    if "lecture" in q or "video" in q or "recording" in q or "pre-recorded" in q:
        hints.add("lecture")
    if "assessment" in q or "assignment" in q or "handbook" in q or "criteria" in q or "deadline" in q:
        hints.add("assessment")
    if "moodle" in q or "link" in q or "url" in q:
        hints.add("moodle_link")
    return hints


def _important_phrases(q: str) -> list[str]:
    phrases: list[str] = []
    for pattern in (
        r"w\d+",
        r"week\s+\d+",
        r"pre-recorded lecture",
        r"reflection structure",
        r"reflective writing",
        r"debate prompt",
        r"assessment criteria",
        r"moodle link",
        r"live session",
    ):
        phrases.extend(match.group(0) for match in re.finditer(pattern, q))
    return phrases


def _read_text(path: Path, encoding: str = "utf-8") -> str:
    try:
        return path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return path.read_bytes().decode("latin-1", errors="ignore")


def _extract_pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _is_noise_line(line: str) -> bool:
    lower = line.strip().lower()
    if len(lower) <= 1:
        return True
    if len(lower) > 500 and len(lower.split()) < 8:
        return True
    if any(re.search(pattern, lower) for pattern in NOISE_PATTERNS):
        return True
    if lower.startswith(("m.", "yui_", "function(", "document.", "window.", "var m =", "const ")):
        return True
    return False


def _lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _is_handbook_heading(line: str) -> bool:
    line_l = line.lower().strip(":")
    exact = {
        "module overview",
        "module summary",
        "module syllabus",
        "specification",
        "core reading",
        "module aims",
        "intended learning outcomes",
        "module assessment",
        "overview",
        "part a",
        "part a: critical analysis and reflection portfolio",
        "part b: design case extension or design critique",
        "assessment criteria",
        "the core elements of academic reflective writing",
        "referencing & plagiarism",
        "attendance",
    }
    return line_l in exact or bool(re.match(r"^session\s+\d+\b", line_l))


def _infer_task_type(text: str) -> str:
    t = _normalise_text(text)
    if re.search(r"\b(reflection|reflective|portfolio|part a|writing)\b", t):
        return "reflection"
    if re.search(r"\b(debate|forum|discussion)\b", t):
        return "debate"
    if re.search(r"\b(reading|readings|paper|article|literature|reference)\b", t):
        return "reading"
    if re.search(r"\b(lecture|video|recording|pre-recorded|live session|echo360|panopto)\b", t):
        return "lecture"
    if re.search(r"\b(assessment|assignment|criteria|deadline|submission|part b|marking)\b", t):
        return "assessment"
    if re.search(r"\b(moodle|url|link|vpn)\b", t):
        return "moodle_link"
    if re.search(r"\b(group activit|design case)\b", t):
        return "group_activity"
    return "course_material"


def _page_from_task(task_type: str | None) -> str | None:
    if task_type == "reflection":
        return "Reflection"
    if task_type == "debate":
        return "Debate"
    if task_type == "lecture":
        return "Lecture"
    if task_type in {"reading", "moodle_link"}:
        return "Resources"
    return None


def _extract_week(text: str) -> str | None:
    match = re.search(r"\bW(?:eek)?\s*([0-9]{1,2})\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return f"W{int(match.group(1))}"


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _normalise_text(text))
        if len(token) > 2 and token not in STOPWORDS
    ]


def _normalise_text(text: str) -> str:
    return _compact(str(text or "").lower().replace("_", " "))


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _compact_multiline(text: str) -> str:
    lines = [_compact(line) for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _truncate_text(text: str, max_chars: int = 1400) -> str:
    text = _compact(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _normalise_text(text)).strip("_")
    return slug[:60]


def _relative_source(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _dedupe_chunks(chunks: list[CourseChunk]) -> list[CourseChunk]:
    seen: set[tuple[str, str, str]] = set()
    used_ids: set[str] = set()
    deduped: list[CourseChunk] = []
    for chunk in chunks:
        key = (chunk.source_file, chunk.title, chunk.text[:180])
        if key in seen or len(chunk.text.strip()) < 30:
            continue
        seen.add(key)
        if chunk.chunk_id in used_ids:
            suffix = 2
            new_id = f"{chunk.chunk_id}_{suffix}"
            while new_id in used_ids:
                suffix += 1
                new_id = f"{chunk.chunk_id}_{suffix}"
            chunk = CourseChunk(
                chunk_id=new_id,
                source_file=chunk.source_file,
                source_type=chunk.source_type,
                title=chunk.title,
                text=chunk.text,
                week=chunk.week,
                page=chunk.page,
                task_type=chunk.task_type,
                metadata=chunk.metadata,
            )
        used_ids.add(chunk.chunk_id)
        deduped.append(chunk)
    return deduped
