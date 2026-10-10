"""Central claim-sensitive evidence-sufficiency gate for Retrieval v2."""

from __future__ import annotations

from typing import Sequence

from .models import EvidenceSufficiencyV2, QueryPlanV2, RetrievedChunkV2


_LEVEL_RANK = {
    "unavailable": 0,
    "citation_only": 1,
    "title_and_metadata": 2,
    "excerpt": 3,
    "full_text": 4,
}


def evaluate_evidence_sufficiency(
    plan: QueryPlanV2,
    chunks: Sequence[RetrievedChunkV2],
) -> EvidenceSufficiencyV2:
    """Decide what the generator may claim; retrieval activation is not evidence."""

    required = plan.minimum_evidence_level
    if not plan.retrieval_requested:
        return EvidenceSufficiencyV2(
            status="not_applicable",
            answerable=False,
            required_content_level=required,
            available_content_levels=(),
            supporting_chunk_ids=(),
            unsupported_requested_claim_types=(),
            reason="Course-material retrieval was not applicable to this query.",
            user_facing_boundary="No course-material claim should be added.",
            allowed_claim_scope=(),
        )
    if not chunks:
        return EvidenceSufficiencyV2(
            status="no_result",
            answerable=False,
            required_content_level=required,
            available_content_levels=(),
            supporting_chunk_ids=(),
            unsupported_requested_claim_types=plan.intents,
            reason="No sufficiently relevant indexed course-material chunk was found.",
            user_facing_boundary="No sufficiently relevant indexed course material was found.",
            allowed_claim_scope=(),
        )

    levels = tuple(dict.fromkeys(item.chunk.content_level for item in chunks))
    content_claims = tuple(
        intent for intent in plan.intents
        if intent in {"summarise_content", "explain_findings", "explain_methods", "obtain_task_guidance"}
    )

    def claim_eligible(item: RetrievedChunkV2) -> bool:
        chunk = item.chunk
        if any(intent in plan.intents for intent in {"explain_findings", "explain_methods"}):
            # A weekly page that names a paper is not that paper's body.
            return chunk.material_type == "reading" and chunk.content_level in {"excerpt", "full_text"}
        if "summarise_content" in plan.intents and plan.material_type == "reading":
            return chunk.material_type == "reading" and chunk.content_level in {"excerpt", "full_text"}
        if plan.material_type == "lecture" and "obtain_task_guidance" in plan.intents:
            haystack = " ".join((chunk.title, *chunk.section_path)).casefold()
            return chunk.content_level in {"excerpt", "full_text"} and (
                "lecture" in haystack or "reflection" in haystack
            )
        return True

    eligible = [item for item in chunks if claim_eligible(item)]
    best = max((_LEVEL_RANK.get(item.chunk.content_level, 0) for item in eligible), default=0)
    required_rank = _LEVEL_RANK.get(required, 2)
    support = tuple(
        item.chunk.chunk_id
        for item in eligible
        if _LEVEL_RANK.get(item.chunk.content_level, 0) >= min(required_rank, 2)
    )

    if best >= required_rank:
        scope = ["identify_source", "name_source"]
        if "find_link" in plan.intents:
            scope.append("provide_verified_link")
        if required_rank >= 3:
            scope.append("describe_extracted_course_content")
        return EvidenceSufficiencyV2(
            status="sufficient",
            answerable=True,
            required_content_level=required,
            available_content_levels=levels,
            supporting_chunk_ids=support or tuple(item.chunk.chunk_id for item in chunks),
            unsupported_requested_claim_types=(),
            reason=f"Retrieved evidence meets the required {required} content level.",
            user_facing_boundary="Answer only within the extracted evidence and name the supporting source.",
            allowed_claim_scope=tuple(scope),
        )

    metadata_levels = {"citation_only", "title_and_metadata"}
    if set(levels).issubset(metadata_levels) or (content_claims and not eligible):
        identify_or_link = any(intent in plan.intents for intent in {"identify_source", "find_link"})
        supported_scope = tuple(
            scope for scope, condition in (
                ("identify_source", True),
                ("provide_verified_link", "find_link" in plan.intents),
            ) if condition
        )
        return EvidenceSufficiencyV2(
            status="metadata_only",
            answerable=identify_or_link and not content_claims,
            required_content_level=required,
            available_content_levels=levels,
            supporting_chunk_ids=tuple(
                item.chunk.chunk_id for item in chunks
                if item.chunk.content_level in metadata_levels
            ),
            unsupported_requested_claim_types=content_claims,
            reason="Retrieved evidence contains only titles, citations, ordered-list metadata, or links.",
            user_facing_boundary=(
                "The source can be identified, but its arguments, methods, findings, and conclusions cannot be inferred."
            ),
            allowed_claim_scope=supported_scope,
        )

    if best > 0:
        return EvidenceSufficiencyV2(
            status="partially_sufficient",
            answerable=False,
            required_content_level=required,
            available_content_levels=levels,
            supporting_chunk_ids=tuple(item.chunk.chunk_id for item in chunks),
            unsupported_requested_claim_types=content_claims or plan.intents,
            reason="Some relevant content was retrieved, but it does not meet every requested claim's evidence level.",
            user_facing_boundary="Answer only the supported portion and state what content remains unavailable.",
            allowed_claim_scope=("identify_source", "describe_available_excerpt"),
        )

    return EvidenceSufficiencyV2(
        status="insufficient",
        answerable=False,
        required_content_level=required,
        available_content_levels=levels,
        supporting_chunk_ids=(),
        unsupported_requested_claim_types=plan.intents,
        reason="Retrieved records contain no usable claim-supporting content.",
        user_facing_boundary=f"A source with {required} evidence is needed.",
        allowed_claim_scope=(),
    )
