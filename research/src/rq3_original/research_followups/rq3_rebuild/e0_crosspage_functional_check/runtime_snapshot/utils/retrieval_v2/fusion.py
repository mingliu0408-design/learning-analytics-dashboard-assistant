"""Stable reciprocal-rank fusion for independent candidate sets."""

from __future__ import annotations

from typing import Sequence

from .models import CourseChunkV2


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[tuple[CourseChunkV2, float]]],
    constant: int = 60,
) -> list[tuple[CourseChunkV2, float, tuple[int | None, ...]]]:
    chunks: dict[str, CourseChunkV2] = {}
    scores: dict[str, float] = {}
    ranks: dict[str, list[int | None]] = {}
    width = len(ranked_lists)
    for list_index, candidates in enumerate(ranked_lists):
        for rank, (chunk, _raw_score) in enumerate(candidates, start=1):
            chunks[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (constant + rank)
            ranks.setdefault(chunk.chunk_id, [None] * width)[list_index] = rank
    fused = [
        (chunks[chunk_id], score, tuple(ranks[chunk_id]))
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return fused
