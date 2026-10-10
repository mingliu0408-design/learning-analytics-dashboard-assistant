"""Source-aware, allowlist-only ingestion for Retrieval v2."""

from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .config import PROJECT_ROOT, is_privacy_excluded
from .manifest import sha256_file, source_path_for
from .models import ExtractedDocumentV2, ExtractedSectionV2, ManifestRecordV2


_WEEK_RE = re.compile(r"\b(?:W|Week\s*)(\d{1,2})\b", re.IGNORECASE)
_PART_RE = re.compile(r"\bPart\s+([AB])\b", re.IGNORECASE)


class _StructuredHTMLParser(HTMLParser):
    """Small dependency-free HTML extractor retaining headings and links."""

    BLOCK_TAGS = {"p", "div", "li", "tr", "br", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, int | None]] = []
        self._parts: list[str] = []
        self._heading_level: int | None = None
        self._ignore_depth = 0
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "header", "xml"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._heading_level = int(tag[1])
        elif tag in self.BLOCK_TAGS:
            self._flush()
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav", "footer", "header", "xml"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth:
            return
        if tag == "a" and self._href:
            self._parts.append(f" URL: {self._href}")
            self._href = ""
        if re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK_TAGS:
            self._flush()
            if re.fullmatch(r"h[1-6]", tag):
                self._heading_level = None

    def handle_data(self, data: str) -> None:
        if not self._ignore_depth:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        value = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        self._parts = []
        if value and value not in {"-->", "<!--"}:
            self.lines.append((value, self._heading_level))


def _normalise_week(text: str) -> str | None:
    match = _WEEK_RE.search(text or "")
    return f"W{int(match.group(1))}" if match else None


def _assessment_part(text: str) -> str | None:
    match = _PART_RE.search(text or "")
    return f"Part {match.group(1).upper()}" if match else None


def _noise(line: str) -> bool:
    lower = line.casefold().strip()
    return (
        len(lower) < 2
        or lower in {"url", "forum", "book", "page", "feedback", "questionnaire", "checklist"}
        or lower.startswith(("skip to main", "javascript", "window.", "document.", "var "))
    )


def _sections_from_lines(
    lines: Iterable[tuple[str, int | None]],
    document_title: str,
    default_week: str | None = None,
    default_part: str | None = None,
    page_number: int | None = None,
) -> tuple[ExtractedSectionV2, ...]:
    sections: list[ExtractedSectionV2] = []
    headings: list[str] = [document_title]
    current_title = document_title
    current_lines: list[str] = []
    current_week = default_week
    current_part = default_part

    def flush() -> None:
        nonlocal current_lines
        text = "\n".join(dict.fromkeys(line for line in current_lines if not _noise(line))).strip()
        if text:
            urls = re.findall(r"https?://[^\s]+", text)
            sections.append(
                ExtractedSectionV2(
                    title=current_title,
                    section_path=tuple(headings),
                    text=text,
                    week=current_week or _normalise_week(text),
                    page_number=page_number,
                    assessment_part=current_part or _assessment_part(text),
                    source_url=urls[0].rstrip(".,)") if urls else None,
                    metadata={"urls": [url.rstrip(".,)") for url in urls]},
                )
            )
        current_lines = []

    for line, level in lines:
        line = re.sub(r"\s+", " ", line).strip()
        week = _normalise_week(line)
        part = _assessment_part(line)
        inferred_heading = bool(
            level
            or week
            or re.match(r"^(?:Week\s+\d+|Session\s+\d+|Part\s+[AB]\b|Assessment Criteria|Module (?:Overview|Syllabus|Assessment)|Core Readings?)", line, re.I)
        )
        if inferred_heading:
            flush()
            current_title = line[:240]
            target_level = max(1, min(6, level or (2 if week or part else 3)))
            headings = headings[:target_level]
            while len(headings) < target_level:
                headings.append(document_title)
            if len(headings) == target_level:
                headings[-1] = current_title
            else:
                headings.append(current_title)
            if week:
                current_week = week
                current_part = default_part
            if part:
                current_part = part
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush()
    return tuple(sections)


def _extract_html(path: Path, record: ManifestRecordV2, method: str) -> ExtractedDocumentV2:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        text = raw.decode("latin-1", errors="replace")
    parser = _StructuredHTMLParser()
    parser.feed(text)
    parser.close()
    sections = _sections_from_lines(parser.lines, record.title, record.week, record.assessment_part)
    status = record.extraction_status if sections else "unreadable"
    warnings = () if sections else ("HTML extraction produced no usable sections.",)
    return _document(record, path, sections, status, method, warnings)


def _extract_pdf(path: Path, record: ManifestRecordV2) -> ExtractedDocumentV2:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        return _document(record, path, (), "unreadable", "pypdf_unavailable", (str(exc),))
    sections: list[ExtractedSectionV2] = []
    warnings: list[str] = []
    try:
        reader = PdfReader(str(path))
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = re.sub(r"\s+", " ", page.extract_text() or "").strip()
            except Exception as exc:
                warnings.append(f"Page {page_number} extraction failed: {type(exc).__name__}")
                continue
            if not text:
                continue
            page_lines = [(segment.strip(), None) for segment in re.split(r"(?=Week\s+\d+\s*:)|\n", text) if segment.strip()]
            extracted = _sections_from_lines(
                page_lines,
                record.title,
                record.week,
                record.assessment_part,
                page_number,
            )
            sections.extend(extracted)
    except Exception as exc:
        return _document(record, path, (), "unreadable", "pypdf", (f"PDF read failed: {type(exc).__name__}",))
    status = record.extraction_status if sections else "unreadable"
    if warnings and sections and status == "extracted":
        status = "partially_extracted"
    return _document(record, path, tuple(sections), status, "pypdf", tuple(warnings))


def _extract_txt(path: Path, record: ManifestRecordV2) -> ExtractedDocumentV2:
    text = path.read_text(encoding="utf-8")
    lines: list[tuple[str, int | None]] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)", line.strip())
        lines.append((match.group(2), len(match.group(1))) if match else (line, None))
    sections = _sections_from_lines(lines, record.title, record.week, record.assessment_part)
    return _document(record, path, sections, record.extraction_status, "utf8_text", ())


def _extract_python_metadata(path: Path, record: ManifestRecordV2) -> ExtractedDocumentV2:
    from utils.course_metadata import LECTURE_METADATA_BY_WEEK

    sections: list[ExtractedSectionV2] = []
    for week, item in sorted(LECTURE_METADATA_BY_WEEK.items()):
        title = str(item.get("title") or f"{week} lecture")
        text = " ".join(
            part for part in (
                f"{week} lecture title: {title}.",
                f"Recorded lecture title: {item.get('recorded_lecture_title', '')}.",
                f"Summary: {item.get('content_summary', '')}",
                str(item.get("disambiguation_note") or ""),
                "Source notes: " + " ".join(map(str, item.get("source_notes") or [])),
            ) if part.strip()
        )
        sections.append(
            ExtractedSectionV2(
                title=f"{week}: {title}",
                section_path=(record.title, week, title),
                text=text,
                week=week,
                metadata={"confidence": item.get("confidence", "")},
            )
        )
    return _document(record, path, tuple(sections), record.extraction_status, "verified_python_metadata", ())


def _document(
    record: ManifestRecordV2,
    path: Path,
    sections: tuple[ExtractedSectionV2, ...],
    status: str,
    method: str,
    warnings: tuple[str, ...],
) -> ExtractedDocumentV2:
    return ExtractedDocumentV2(
        document_id=record.document_id,
        source_path=record.source_path,
        source_type=record.source_type,
        material_type=record.material_type,
        title=record.title,
        source_hash=sha256_file(path) if path.is_file() else "",
        content_level=record.content_level,
        extraction_status=status,
        extraction_method=method,
        sections=sections,
        week=record.week,
        assessment_part=record.assessment_part,
        source_url=record.source_url,
        warnings=warnings,
    )


def ingest_record(
    record: ManifestRecordV2, project_root: Path = PROJECT_ROOT
) -> ExtractedDocumentV2:
    """Ingest one validated manifest record and retain provenance."""

    excluded, reason = is_privacy_excluded(record.source_path)
    if excluded:
        raise ValueError(f"Refusing privacy-excluded source {record.source_path}: {reason}")
    path = source_path_for(record, project_root)
    if not path.is_file():
        return _document(record, path, (), "missing", "none", ("Source file is missing.",))
    if record.source_type == "html":
        return _extract_html(path, record, "html_parser")
    if record.source_type == "legacy_doc":
        prefix = path.read_bytes()[:1024].lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            return _extract_html(path, record, "html_in_legacy_doc")
        commands: list[tuple[str, list[str]]] = []
        if shutil.which("textutil"):
            commands.append(("textutil", ["textutil", "-convert", "txt", "-stdout", str(path)]))
        if shutil.which("antiword"):
            commands.append(("antiword", ["antiword", str(path)]))
        if shutil.which("catdoc"):
            commands.append(("catdoc", ["catdoc", str(path)]))
        for method, command in commands:
            completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
            if completed.returncode != 0 or not completed.stdout.strip():
                continue
            text = completed.stdout.decode("utf-8", errors="replace")
            lines = [(line, None) for line in text.splitlines() if line.strip()]
            sections = _sections_from_lines(lines, record.title, record.week, record.assessment_part)
            if sections:
                return _document(
                    replace(record, content_level="excerpt"),
                    path,
                    sections,
                    "partially_extracted",
                    f"best_effort_{method}",
                    ("Binary legacy DOC extraction is best-effort and may omit structure or embedded content.",),
                )
        return _document(
            record,
            path,
            (),
            "unreadable",
            "legacy_doc_no_safe_local_extractor",
            ("Binary legacy DOC was not decoded as raw text; install a safe local extractor.",),
        )
    if record.source_type == "pdf":
        return _extract_pdf(path, record)
    if record.source_type == "txt":
        return _extract_txt(path, record)
    if record.source_type == "python_metadata":
        return _extract_python_metadata(path, record)
    if record.source_type == "docx":
        try:
            from docx import Document
        except Exception:
            return _document(record, path, (), "unreadable", "python_docx_unavailable", ("python-docx is not installed.",))
        doc = Document(str(path))
        lines = [(paragraph.text, None) for paragraph in doc.paragraphs if paragraph.text.strip()]
        sections = _sections_from_lines(lines, record.title, record.week, record.assessment_part)
        return _document(record, path, sections, record.extraction_status, "python_docx", ())
    raise ValueError(f"Unsupported source_type: {record.source_type}")


def ingest_manifest(records: Iterable[ManifestRecordV2]) -> list[ExtractedDocumentV2]:
    return [ingest_record(record) for record in records if record.enabled]
