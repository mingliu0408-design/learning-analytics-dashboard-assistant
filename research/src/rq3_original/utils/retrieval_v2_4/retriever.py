"""Role-aware, facet-aware lexical Retrieval v2.4 runtime."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re
import time
from typing import Any, Sequence

from utils.retrieval_v2.sufficiency import evaluate_evidence_sufficiency

from .config import DEFAULT_CONFIG_V24, RETRIEVAL_VERSION_V24, RetrievalConfigV24
from .index_store import load_index_bundle_v24
from .lexical import FieldAwareLexicalIndexV24, lexical_overlap
from .models import (
    CourseChunkV24,
    QueryFacetV24,
    QueryPlanV24,
    RetrievedChunkV24,
    RetrievalResultV24,
)
from .query_analysis import analyse_query_v24


FAILURE_STAGES = (
    "query_trigger",
    "metadata_filter",
    "lexical_candidate_generation",
    "lexical_overlap_gate",
    "fusion",
    "reranking",
    "source_cap",
    "final_selection",
    "no_failure",
)
_LEVEL_SCORE = {
    "unavailable": -4.0,
    "citation_only": 0.0,
    "title_and_metadata": 1.0,
    "excerpt": 3.0,
    "full_text": 5.0,
}


def _has_url(chunk: CourseChunkV24) -> bool:
    return bool(chunk.metadata.get("urls") or chunk.metadata.get("source_url") or "http" in chunk.text.casefold())


def _role_group(chunk: CourseChunkV24) -> str:
    roles = set(chunk.content_roles)
    for group, members in (
        ("overview", {"lecture_overview", "lecture_learning_outcomes", "weekly_overview"}),
        ("prompt", {"reflection_prompt", "debate_prompt", "part_a_reflection_guidance", "assessment_guidance"}),
        ("link", {"lecture_link", "assessment_link", "moodle_link"}),
        ("reading", {"reading_list", "reading_metadata"}),
    ):
        if roles & members:
            return group
    return "other"


def _coarse_matches(facet: QueryFacetV24, chunk: CourseChunkV24) -> bool:
    if facet.facet_type == "lecture":
        return chunk.material_type == "lecture"
    if facet.facet_type == "assessment":
        return chunk.material_type in {"assessment", "moodle_link"}
    if facet.facet_type == "reading":
        return chunk.material_type == "reading"
    if facet.facet_type == "reflection":
        return chunk.material_type == "reflection"
    if facet.facet_type == "debate":
        return chunk.material_type == "debate"
    return False


def facet_matches_chunk(
    plan: QueryPlanV24, facet: QueryFacetV24, chunk: CourseChunkV24
) -> bool:
    if facet.week and chunk.week != facet.week:
        return False
    roles = set(chunk.content_roles)
    if facet.material_roles and not (roles & set(facet.material_roles) or _coarse_matches(facet, chunk)):
        return False
    if plan.assessment_part and chunk.assessment_part != plan.assessment_part:
        if not roles & {"part_a_reflection_guidance", "assessment_guidance", "assessment_link"}:
            return False
    return True


def _strong_metadata_gate(
    plan: QueryPlanV24, facet: QueryFacetV24, chunk: CourseChunkV24
) -> tuple[bool, str]:
    roles = set(chunk.content_roles)
    requested_roles = set(facet.material_roles)
    exact_role = bool(roles & requested_roles or _coarse_matches(facet, chunk))
    if facet.week and chunk.week == facet.week and exact_role:
        return True, "strong_metadata:exact_week+exact_role"
    if plan.assessment_part and roles & {"part_a_reflection_guidance", "assessment_guidance", "assessment_link"}:
        return True, "strong_metadata:assessment_part+verified_assessment_role"
    if facet.intent == "find_link" and exact_role and _has_url(chunk):
        return True, "strong_metadata:url_intent+exact_target_role"
    if plan.named_author and plan.named_author.casefold() in (chunk.title + " " + chunk.text).casefold():
        if not plan.week or chunk.week == plan.week:
            return True, "strong_metadata:named_author+compatible_week"
    if plan.named_title and plan.named_title.casefold() in chunk.title.casefold():
        return True, "strong_metadata:canonical_title_phrase"
    return False, ""


def _intent_score(
    plan: QueryPlanV24,
    facet_ids: set[str],
    chunk: CourseChunkV24,
) -> tuple[float, list[str]]:
    roles = set(chunk.content_roles)
    title = chunk.title.casefold()
    body = chunk.text.casefold()
    score = _LEVEL_SCORE.get(chunk.content_level, -1.0)
    reasons: list[str] = [f"content_level:{chunk.content_level}"]
    if plan.week and chunk.week == plan.week:
        score += 9.0
        reasons.append("exact_week")
    if "identify_topic" in plan.intents or "lecture_content" in facet_ids:
        if "lecture_overview" in roles:
            score += 24.0
            reasons.append("intent:lecture_overview")
        if "lecture_learning_outcomes" in roles:
            score += 20.0
            reasons.append("intent:lecture_learning_outcomes")
        if chunk.content_level in {"excerpt", "full_text"}:
            score += 6.0
            reasons.append("intent:detailed_lecture_content")
    if "identify_lecture" in plan.intents:
        if re.match(r"^(?:w\d+|week\s+\d+).*lecture", title):
            score += 24.0
            reasons.append("intent:explicit_week_title")
        if "lecture_link" in roles:
            score += 10.0
            reasons.append("intent:lecture_listing_link")
    if "find_link" in plan.intents:
        if _has_url(chunk):
            score += 12.0
            reasons.append("intent:url_bearing")
        if roles & {"lecture_link", "assessment_link", "moodle_link"}:
            score += 18.0
            reasons.append("intent:direct_target_link")
        if title.startswith("url "):
            score += 8.0
            reasons.append("intent:explicit_url_anchor")
        if "forceview=1" in body or "forceview=1" in str(chunk.metadata.get("source_url") or ""):
            score += 5.0
            reasons.append("intent:direct_forceview_url")
        if "moodle" in plan.original_query.casefold() and chunk.document_id == "moodle_links":
            score += 16.0
            reasons.append("intent:verified_moodle_links_source")
    if "apply_to_reflection" in plan.intents:
        if "lecture_content" in facet_ids and roles & {"lecture_overview", "lecture_learning_outcomes"}:
            score += 26.0
            reasons.append("facet:lecture_content")
        if "reflection_prompt" in facet_ids and "reflection_prompt" in roles:
            score += 30.0
            reasons.append("facet:reflection_prompt")
    if plan.material_type in {"assessment", "moodle_link"}:
        if "part_a_reflection_guidance" in roles:
            score += 24.0
            reasons.append("intent:part_a_reflection_guidance")
        if "assessment_guidance" in roles:
            score += 15.0
            reasons.append("intent:assessment_guidance")
        if "assessment_link" in roles:
            score += 15.0
            reasons.append("intent:assessment_link")
        if "chapterid=207847" in body or "chapterid=207847" in str(chunk.metadata):
            score += 18.0
            reasons.append("intent:part_a_guidance_target")
    if plan.material_type == "reading":
        if "reading_list" in roles:
            score += 12.0
            reasons.append("intent:reading_list")
        if "core reading" in body and int(chunk.metadata.get("piece_index", 99)) == 0:
            score += 18.0
            reasons.append("intent:first_core_reading")
    return score, reasons


class CourseMaterialRetrieverV24:
    def __init__(self, config: RetrievalConfigV24 = DEFAULT_CONFIG_V24) -> None:
        bundle = load_index_bundle_v24(config)
        self.config = config
        self.chunks = list(bundle.chunks)
        self.index_metadata = bundle.metadata

    def retrieve(
        self, query: str, query_type: str | None = None, top_k: int | None = None
    ) -> RetrievalResultV24:
        started = time.perf_counter()
        plan = analyse_query_v24(query, query_type)
        limit = top_k or self.config.final_top_k
        audit: dict[str, dict[str, Any]] = {
            chunk.chunk_id: {
                "present_in_corpus": True,
                "after_metadata_filter": False,
                "matched_filter_facets": [],
                "lexical_candidate_rank": None,
                "lexical_candidate_facet_ranks": {},
                "retained_after_lexical_gate": False,
                "gate_reasons": [],
                "fusion_rank": None,
                "rerank_rank": None,
                "retained_after_source_cap": False,
                "final_rank": None,
            }
            for chunk in self.chunks
        }
        if not plan.retrieval_requested:
            sufficiency = evaluate_evidence_sufficiency(plan, ())
            return RetrievalResultV24(
                original_query=plan.original_query,
                canonical_retrieval_query=plan.canonical_retrieval_query,
                query_plan=plan,
                retrieval_requested=False,
                retrieval_used=False,
                retrieved_chunks=(),
                evidence_sufficiency=sufficiency,
                stage_audit=audit,
                candidate_diagnostics={"facets": [], "final_candidate_count": 0},
                reason=plan.reason,
                index_version=RETRIEVAL_VERSION_V24,
                index_hash=self.index_metadata["index_hash"],
                backend_mode="lexical_degraded",
                semantic_backend_available=False,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        gated_lists: list[list[tuple[CourseChunkV24, float]]] = []
        raw_scores: dict[str, float] = {}
        matched_facets: dict[str, set[str]] = defaultdict(set)
        facet_diagnostics: list[dict[str, Any]] = []
        for facet in plan.facets:
            pool = [chunk for chunk in self.chunks if facet_matches_chunk(plan, facet, chunk)]
            for chunk in pool:
                audit[chunk.chunk_id]["after_metadata_filter"] = True
                audit[chunk.chunk_id]["matched_filter_facets"].append(facet.facet_id)
            candidates = FieldAwareLexicalIndexV24(pool, self.config).search(
                plan.canonical_retrieval_query,
                self.config.lexical_candidate_top_k,
                link_intent=facet.intent == "find_link",
            )
            retained: list[tuple[CourseChunkV24, float]] = []
            for rank, (chunk, score) in enumerate(candidates, start=1):
                current = audit[chunk.chunk_id]["lexical_candidate_rank"]
                audit[chunk.chunk_id]["lexical_candidate_rank"] = rank if current is None else min(current, rank)
                audit[chunk.chunk_id]["lexical_candidate_facet_ranks"][facet.facet_id] = rank
                overlap = lexical_overlap(plan.canonical_retrieval_query, chunk)
                strong, strong_reason = _strong_metadata_gate(plan, facet, chunk)
                reasons: list[str] = []
                if overlap >= self.config.minimum_raw_overlap:
                    reasons.append(f"lexical_overlap:{overlap}")
                if strong:
                    reasons.append(strong_reason)
                if not reasons:
                    continue
                audit[chunk.chunk_id]["retained_after_lexical_gate"] = True
                audit[chunk.chunk_id]["gate_reasons"] = list(
                    dict.fromkeys([*audit[chunk.chunk_id]["gate_reasons"], *reasons])
                )
                retained.append((chunk, score))
                raw_scores[chunk.chunk_id] = max(raw_scores.get(chunk.chunk_id, 0.0), score)
                matched_facets[chunk.chunk_id].add(facet.facet_id)
            gated_lists.append(retained)
            facet_diagnostics.append(
                {
                    "facet_id": facet.facet_id,
                    "facet_type": facet.facet_type,
                    "filtered_candidates": len(pool),
                    "lexical_candidates": len(candidates),
                    "post_gate_candidates": len(retained),
                }
            )

        fused_scores: dict[str, float] = defaultdict(float)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        for ranked in gated_lists:
            for rank, (chunk, _score) in enumerate(ranked, start=1):
                fused_scores[chunk.chunk_id] += 1.0 / (self.config.rrf_constant + rank)
        fused_ids = sorted(fused_scores, key=lambda chunk_id: (-fused_scores[chunk_id], chunk_id))
        for rank, chunk_id in enumerate(fused_ids, start=1):
            audit[chunk_id]["fusion_rank"] = rank

        scored: list[tuple[float, CourseChunkV24, tuple[str, ...]]] = []
        for chunk_id in fused_ids:
            chunk = chunks_by_id[chunk_id]
            score = fused_scores[chunk_id] * 100.0 + min(raw_scores.get(chunk_id, 0.0), 50.0) * 0.2
            intent_score, reasons = _intent_score(plan, matched_facets[chunk_id], chunk)
            score += intent_score
            scored.append((score, chunk, tuple(reasons)))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        for rank, (_score, chunk, _reasons) in enumerate(scored, start=1):
            audit[chunk.chunk_id]["rerank_rank"] = rank

        reserved_ids: list[str] = []
        for facet in plan.facets:
            candidate = next(
                (
                    chunk.chunk_id
                    for _score, chunk, _reasons in scored
                    if facet.facet_id in matched_facets[chunk.chunk_id]
                ),
                None,
            )
            if candidate and candidate not in reserved_ids:
                reserved_ids.append(candidate)
        if "find_link" in plan.intents:
            direct = next(
                (
                    chunk.chunk_id
                    for _score, chunk, _reasons in scored
                    if _has_url(chunk)
                    and set(chunk.content_roles) & {"lecture_link", "assessment_link", "moodle_link"}
                ),
                None,
            )
            if direct and direct not in reserved_ids:
                reserved_ids.append(direct)

        scored_by_id = {chunk.chunk_id: (score, chunk, reasons) for score, chunk, reasons in scored}
        ordered = [scored_by_id[chunk_id] for chunk_id in reserved_ids]
        ordered.extend(item for item in scored if item[1].chunk_id not in set(reserved_ids))
        selected_raw: list[tuple[float, CourseChunkV24, tuple[str, ...], bool]] = []
        source_counts: dict[str, int] = defaultdict(int)
        source_role_groups: dict[str, set[str]] = defaultdict(set)
        selected_ids: set[str] = set()
        for score, chunk, reasons in ordered:
            if chunk.chunk_id in selected_ids:
                continue
            reserved = chunk.chunk_id in reserved_ids
            group = _role_group(chunk)
            role_slot = group not in source_role_groups[chunk.document_id]
            if not reserved and source_counts[chunk.document_id] >= self.config.maximum_chunks_per_source and not role_slot:
                continue
            source_counts[chunk.document_id] += 1
            source_role_groups[chunk.document_id].add(group)
            selected_ids.add(chunk.chunk_id)
            audit[chunk.chunk_id]["retained_after_source_cap"] = True
            selected_raw.append((score, chunk, reasons, reserved))
            if len(selected_raw) >= limit:
                break

        selected: list[RetrievedChunkV24] = []
        for final_rank, (score, chunk, reasons, reserved) in enumerate(selected_raw, start=1):
            audit[chunk.chunk_id]["final_rank"] = final_rank
            selected.append(
                RetrievedChunkV24(
                    chunk=chunk,
                    lexical_rank=audit[chunk.chunk_id]["lexical_candidate_rank"],
                    fused_rank=audit[chunk.chunk_id]["fusion_rank"],
                    rerank_rank=audit[chunk.chunk_id]["rerank_rank"],
                    reranker_score=round(score, 8),
                    rerank_reasons=reasons,
                    gate_reasons=tuple(audit[chunk.chunk_id]["gate_reasons"]),
                    matched_facets=tuple(sorted(matched_facets[chunk.chunk_id])),
                    reserved_before_source_cap=reserved,
                )
            )
        sufficiency = evaluate_evidence_sufficiency(plan, selected)
        return RetrievalResultV24(
            original_query=plan.original_query,
            canonical_retrieval_query=plan.canonical_retrieval_query,
            query_plan=plan,
            retrieval_requested=True,
            retrieval_used=bool(selected),
            retrieved_chunks=tuple(selected),
            evidence_sufficiency=sufficiency,
            stage_audit=audit,
            candidate_diagnostics={
                "facets": facet_diagnostics,
                "fusion_candidate_count": len(fused_ids),
                "reranked_candidate_count": len(scored),
                "reserved_candidate_ids": reserved_ids,
                "final_candidate_count": len(selected),
            },
            reason=sufficiency.reason,
            index_version=RETRIEVAL_VERSION_V24,
            index_hash=self.index_metadata["index_hash"],
            backend_mode="lexical_degraded",
            semantic_backend_available=False,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )


def diagnose_gold_chunks(
    result: RetrievalResultV24 | dict[str, Any], gold_chunk_ids: Sequence[str]
) -> dict[str, Any]:
    value = result.to_audit_dict() if isinstance(result, RetrievalResultV24) else result
    gold = list(gold_chunk_ids)
    audit = value["stage_audit"]
    if not gold:
        return {
            "gold_chunk_filter_recall": None,
            "gold_chunk_candidate_recall_at_20": None,
            "gold_chunk_post_gate_recall": None,
            "gold_chunk_post_rerank_recall_at_5": None,
            "gold_chunk_final_recall_at_5": None,
            "failure_stage": "no_failure",
            "gold_chunk_stage_details": {},
        }

    details: dict[str, dict[str, Any]] = {}
    stages: list[str] = []
    for chunk_id in gold:
        stage = audit.get(chunk_id)
        if stage and stage.get("final_rank") is not None and stage.get("final_rank") <= 5:
            failure = "no_failure"
        elif not value["retrieval_requested"]:
            failure = "query_trigger"
        elif stage is None or not stage.get("present_in_corpus"):
            failure = "metadata_filter"
        elif not stage.get("after_metadata_filter"):
            failure = "metadata_filter"
        elif stage.get("lexical_candidate_rank") is None:
            failure = "lexical_candidate_generation"
        elif not stage.get("retained_after_lexical_gate"):
            failure = "lexical_overlap_gate"
        elif stage.get("fusion_rank") is None:
            failure = "fusion"
        elif stage.get("rerank_rank") is None or stage.get("rerank_rank") > 5:
            failure = "reranking"
        elif not stage.get("retained_after_source_cap"):
            failure = "source_cap"
        elif stage.get("final_rank") is None or stage.get("final_rank") > 5:
            failure = "final_selection"
        else:
            failure = "final_selection"
        stages.append(failure)
        details[chunk_id] = {**(stage or {}), "failure_stage": failure}

    def recall(predicate: Any) -> float:
        return sum(bool(predicate(audit.get(chunk_id, {}))) for chunk_id in gold) / len(gold)

    failures = [stage for stage in stages if stage != "no_failure"]
    failure = min(failures, key=FAILURE_STAGES.index) if failures else "no_failure"
    return {
        "gold_chunk_filter_recall": recall(lambda item: item.get("after_metadata_filter")),
        "gold_chunk_candidate_recall_at_20": recall(lambda item: item.get("lexical_candidate_rank") is not None and item.get("lexical_candidate_rank") <= 20),
        "gold_chunk_post_gate_recall": recall(lambda item: item.get("retained_after_lexical_gate")),
        "gold_chunk_post_rerank_recall_at_5": recall(lambda item: item.get("rerank_rank") is not None and item.get("rerank_rank") <= 5),
        "gold_chunk_final_recall_at_5": recall(lambda item: item.get("final_rank") is not None and item.get("final_rank") <= 5),
        "failure_stage": failure,
        "gold_chunk_stage_details": details,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect Retrieval v2.4")
    parser.add_argument("command", choices=["query"])
    parser.add_argument("--query", required=True)
    args = parser.parse_args(argv)
    result = CourseMaterialRetrieverV24().retrieve(args.query)
    print(json.dumps(result.to_audit_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
