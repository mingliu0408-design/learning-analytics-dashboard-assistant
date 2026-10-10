"""Deterministic metadata- and content-aware reranking."""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

from .models import CourseChunkV2, QueryPlanV2, RetrievedChunkV2


_LEVEL_SCORE = {
    "unavailable": -3.0,
    "citation_only": 0.0,
    "title_and_metadata": 0.4,
    "excerpt": 1.0,
    "full_text": 1.4,
}


def _material_matches(query_material: str | None, chunk: CourseChunkV2) -> bool:
    if not query_material:
        return False
    if query_material == chunk.material_type:
        return True
    if query_material in {"assessment", "reflection", "debate"}:
        return query_material in " ".join((chunk.material_type, chunk.title, *chunk.section_path)).casefold()
    if query_material == "lecture":
        return chunk.material_type == "lecture" or "lecture" in chunk.title.casefold()
    return False


def rerank_candidates(
    fused: Sequence[tuple[CourseChunkV2, float, tuple[int | None, ...]]],
    plan: QueryPlanV2,
    top_k: int,
    maximum_chunks_per_source: int,
) -> list[RetrievedChunkV2]:
    scored: list[tuple[float, CourseChunkV2, float, tuple[int | None, ...], tuple[str, ...], dict[str, bool]]] = []
    query_lower = plan.query.casefold()
    seen_text: set[str] = set()
    for fused_rank, (chunk, fused_score, ranks) in enumerate(fused, start=1):
        score = fused_score * 100.0
        reasons: list[str] = [f"rrf_rank={fused_rank}"]
        metadata_matches = {
            "week": bool(plan.week and chunk.week == plan.week),
            "material_type": _material_matches(plan.material_type, chunk),
            "assessment_part": bool(plan.assessment_part and chunk.assessment_part == plan.assessment_part),
            "title": bool(plan.named_title and plan.named_title.casefold() in chunk.title.casefold()),
            "author": bool(plan.named_author and plan.named_author.casefold() in (chunk.title + " " + chunk.text).casefold()),
        }
        if metadata_matches["week"]:
            score += 8.0
            reasons.append("exact_week")
        if metadata_matches["material_type"]:
            score += 6.0
            reasons.append("exact_material_type")
        if metadata_matches["assessment_part"]:
            score += 7.0
            reasons.append("exact_assessment_part")
        if metadata_matches["title"]:
            score += 8.0
            reasons.append("exact_title_phrase")
        if metadata_matches["author"]:
            score += 7.0
            reasons.append("exact_author_phrase")
        section_text = " ".join(chunk.section_path).casefold()
        for term in ("core reading", "assessment criteria", "lecture", "reflection", "moodle"):
            if term in query_lower and term in section_text:
                score += 3.0
                reasons.append(f"section:{term}")
        score += _LEVEL_SCORE.get(chunk.content_level, -1.0)
        if plan.minimum_evidence_level in {"excerpt", "full_text"} and chunk.content_level in {"citation_only", "title_and_metadata"}:
            score -= 4.0
            reasons.append("content_level_below_claim_requirement")
        text_hash = hashlib.sha256(re.sub(r"\s+", " ", chunk.text).casefold().encode()).hexdigest()
        if text_hash in seen_text:
            score -= 20.0
            reasons.append("duplicate_text_penalty")
        seen_text.add(text_hash)
        scored.append((score, chunk, fused_score, ranks, tuple(reasons), metadata_matches))
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))

    diverse_first: list[tuple[float, CourseChunkV2, float, tuple[int | None, ...], tuple[str, ...], dict[str, bool]]] = []
    remaining: list[tuple[float, CourseChunkV2, float, tuple[int | None, ...], tuple[str, ...], dict[str, bool]]] = []
    seen_documents: set[str] = set()
    for item in scored:
        if item[1].document_id not in seen_documents:
            diverse_first.append(item)
            seen_documents.add(item[1].document_id)
        else:
            remaining.append(item)

    source_counts: dict[str, int] = {}
    selected: list[RetrievedChunkV2] = []
    diverse_ids = {item[1].chunk_id for item in diverse_first}
    for score, chunk, _fused_score, ranks, reasons, metadata_matches in [*diverse_first, *remaining]:
        count = source_counts.get(chunk.document_id, 0)
        if count >= maximum_chunks_per_source:
            continue
        source_counts[chunk.document_id] = count + 1
        selected.append(
            RetrievedChunkV2(
                chunk=chunk,
                lexical_rank=ranks[0] if ranks else None,
                semantic_rank=ranks[1] if len(ranks) > 1 else None,
                fused_rank=next(
                    index for index, item in enumerate(fused, start=1) if item[0].chunk_id == chunk.chunk_id
                ),
                reranker_score=round(score, 8),
                rerank_reason=reasons + (("source_diversity_first_pass",) if chunk.chunk_id in diverse_ids else ()),
                metadata_matches=metadata_matches,
            )
        )
        if len(selected) >= top_k:
            break
    return selected
