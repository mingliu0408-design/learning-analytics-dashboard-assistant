"""Structure-aware deterministic chunking for Retrieval v2."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import re
from typing import Iterable

from .config import DEFAULT_CONFIG, RetrievalConfigV2
from .models import CourseChunkV2, ExtractedDocumentV2, ExtractedSectionV2


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:20]}"


def _split_text(text: str, config: RetrievalConfigV2) -> list[str]:
    clean = re.sub(r"[ \t]+", " ", text).strip()
    if len(clean) <= config.max_chunk_chars:
        return [clean] if clean else []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", clean) if part.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + len(sentence) + 1 <= config.target_chunk_chars:
            current += " " + sentence
            continue
        pieces.append(current[: config.max_chunk_chars].strip())
        overlap = current[-config.overlap_chars :].strip()
        boundary = overlap.find(" ")
        if boundary >= 0:
            overlap = overlap[boundary + 1 :]
        current = f"{overlap} {sentence}".strip()
        while len(current) > config.max_chunk_chars:
            cut = current.rfind(" ", 0, config.max_chunk_chars)
            cut = cut if cut >= config.min_chunk_chars else config.max_chunk_chars
            pieces.append(current[:cut].strip())
            current = current[max(0, cut - config.overlap_chars) :].strip()
    if current:
        pieces.append(current[: config.max_chunk_chars].strip())
    return [piece for piece in pieces if piece]


def _section_chunks(
    document: ExtractedDocumentV2,
    section: ExtractedSectionV2,
    section_index: int,
    config: RetrievalConfigV2,
) -> list[CourseChunkV2]:
    heading = " > ".join(section.section_path)
    body_budget = max(config.min_chunk_chars, config.max_chunk_chars - len(heading) - 2)
    local_config = replace(
        config,
        target_chunk_chars=min(config.target_chunk_chars, body_budget),
        max_chunk_chars=body_budget,
    )
    pieces = _split_text(section.text, local_config)
    parent_id = _stable_id(
        "parent",
        document.document_id,
        str(section_index),
        " > ".join(section.section_path),
        section.text,
    )
    provisional: list[CourseChunkV2] = []
    section_body = re.sub(r"\s+", " ", section.text).strip()
    effective_content_level = document.content_level
    if document.content_level == "full_text" and (
        len(section_body) < 180
        or section_body.casefold().startswith(("select activity", "url "))
        or (
            "http" in section_body.casefold()
            and len(re.sub(r"https?://\S+", "", section_body).strip()) < 140
        )
    ):
        # The source document has full text, but this particular structural
        # unit contains only a title/link and cannot support body-content claims.
        effective_content_level = "title_and_metadata"
    for piece_index, piece in enumerate(pieces):
        text = f"{heading}\n{piece}" if heading and not piece.startswith(section.title) else piece
        chunk_id = _stable_id(
            "v2",
            document.document_id,
            " > ".join(section.section_path),
            piece,
        )
        provisional.append(
            CourseChunkV2(
                chunk_id=chunk_id,
                document_id=document.document_id,
                source_file=document.source_path,
                source_type=document.source_type,
                material_type=document.material_type,
                title=section.title or document.title,
                section_path=section.section_path,
                text=text,
                week=section.week or document.week,
                page_number=section.page_number,
                assessment_part=section.assessment_part or document.assessment_part,
                content_level=effective_content_level,
                parent_chunk_id=parent_id,
                previous_chunk_id=None,
                next_chunk_id=None,
                source_hash=document.source_hash,
                metadata={
                    **section.metadata,
                    "document_title": document.title,
                    "extraction_method": document.extraction_method,
                    "extraction_status": document.extraction_status,
                    "source_url": section.source_url or document.source_url,
                    "section_index": section_index,
                    "piece_index": piece_index,
                },
            )
        )
    return [
        replace(
            item,
            previous_chunk_id=provisional[index - 1].chunk_id if index else None,
            next_chunk_id=provisional[index + 1].chunk_id if index + 1 < len(provisional) else None,
        )
        for index, item in enumerate(provisional)
    ]


def chunk_documents(
    documents: Iterable[ExtractedDocumentV2],
    config: RetrievalConfigV2 = DEFAULT_CONFIG,
) -> list[CourseChunkV2]:
    """Chunk each document without crossing source, week, part, or section boundaries."""

    chunks: list[CourseChunkV2] = []
    exact_text_seen: set[str] = set()
    for document in documents:
        for section_index, section in enumerate(document.sections):
            for chunk in _section_chunks(document, section, section_index, config):
                fingerprint = hashlib.sha256(re.sub(r"\s+", " ", chunk.text).casefold().encode()).hexdigest()
                if fingerprint in exact_text_seen:
                    continue
                exact_text_seen.add(fingerprint)
                chunks.append(chunk)
    return chunks


def expand_neighbour_context(
    selected: Iterable[CourseChunkV2],
    all_chunks: Iterable[CourseChunkV2],
    max_context_chars: int = DEFAULT_CONFIG.maximum_prompt_expanded_context_chars,
) -> list[CourseChunkV2]:
    """Expand with immediate neighbours while respecting a strict text budget."""

    by_id = {chunk.chunk_id: chunk for chunk in all_chunks}
    result: list[CourseChunkV2] = []
    seen: set[str] = set()
    used = 0
    for chunk in selected:
        candidates = [by_id.get(chunk.previous_chunk_id or ""), chunk, by_id.get(chunk.next_chunk_id or "")]
        for candidate in candidates:
            if candidate is None or candidate.chunk_id in seen:
                continue
            if used + len(candidate.text) > max_context_chars:
                continue
            result.append(candidate)
            seen.add(candidate.chunk_id)
            used += len(candidate.text)
    return result
