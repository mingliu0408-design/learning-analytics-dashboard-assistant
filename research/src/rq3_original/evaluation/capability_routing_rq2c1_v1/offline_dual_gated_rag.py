"""Offline dual-gated RAG using the frozen candidate and sufficiency interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
import hashlib
import os
import socket
from typing import Any, Mapping
from unittest.mock import patch

from evaluation.capability_routing_rq2c0_v1.rag_gate_contract import (
    assert_existing_sufficiency_interface,
    evidence_admission_allowed,
    normalise_sufficiency_status,
    retrieval_candidate_gate,
)
from utils.c_full_retrieval_adapter import (
    retrieve_course_evidence,
    validate_generation_isolation,
)
from utils.retrieval_v2.models import CourseChunkV2, QueryPlanV2, RetrievedChunkV2
from utils.retrieval_v2.sufficiency import evaluate_evidence_sufficiency


@dataclass(frozen=True)
class OfflineRAGResult:
    candidate_allowed: bool
    retrieval_attempted: bool
    retrieved_ids: tuple[str, ...]
    sufficiency_status: str
    admitted_ids: tuple[str, ...]
    clarification_required: bool
    disposition: str
    rejection_reasons: Mapping[str, str]


@dataclass(frozen=True)
class LocalCourseRAGExecution:
    retrieval_attempted: bool
    retrieval_available: bool
    sufficiency_status: str
    retrieved_count: int
    supporting_count: int
    admitted_ids: tuple[str, ...]
    clarification_required: bool
    provider_calls: int = 0
    network_access: bool = False


def _network_block(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("network access blocked during offline RAG")


def run_local_course_rag(query: str) -> LocalCourseRAGExecution:
    """Execute the frozen local v2.4 retriever and the P2 sufficiency gate."""

    with ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "", "CUDA_VISIBLE_DEVICES": ""},
                clear=False,
            )
        )
        stack.enter_context(patch("socket.create_connection", _network_block))
        stack.enter_context(patch.object(socket.socket, "connect", _network_block))
        result = retrieve_course_evidence(
            str(query),
            backend="v2_4",
            top_k=5,
            context={"retrieval_needed": True, "allow_v1_fallback": False},
        )
    validate_generation_isolation(result)
    status = normalise_sufficiency_status(
        str(result.evidence_sufficiency.get("status", "no_result"))
    )
    supporting = tuple(str(value) for value in result.supporting_chunk_ids)
    admitted = (
        supporting
        if evidence_admission_allowed(status, len(supporting))
        else ()
    )
    return LocalCourseRAGExecution(
        retrieval_attempted=True,
        retrieval_available=bool(result.retrieval_available),
        sufficiency_status=status,
        retrieved_count=len(result.audit.get("retrieved_chunk_ids") or ()),
        supporting_count=len(supporting),
        admitted_ids=admitted,
        clarification_required=status == "AMBIGUOUS",
    )


def _candidate_id(fixture_id: str) -> str:
    return "course_candidate_" + fixture_id.rsplit("-", 1)[-1]


def run_candidate_gate_fixture(
    fixture_id: str, value: Mapping[str, Any]
) -> OfflineRAGResult:
    allowed = retrieval_candidate_gate(
        p1_course_retrieval=bool(value.get("p1_course_retrieval")),
        p1_clarification=bool(value.get("p1_clarification")),
        course_source_authorised=bool(value.get("source_authorised")),
    )
    rejection: dict[str, str] = {}
    if bool(value.get("p1_clarification")):
        rejection["retrieval"] = "CLARIFICATION_BLOCKS_TOOL_EXECUTION"
    elif not bool(value.get("p1_course_retrieval")):
        rejection["retrieval"] = "COURSE_CAPABILITY_ABSENT"
    elif not bool(value.get("source_authorised")):
        rejection["retrieval"] = "COURSE_SOURCE_NOT_AUTHORISED"
    return OfflineRAGResult(
        candidate_allowed=allowed,
        retrieval_attempted=allowed,
        retrieved_ids=(_candidate_id(fixture_id),) if allowed else (),
        sufficiency_status="NOT_APPLICABLE",
        admitted_ids=(),
        clarification_required=bool(value.get("p1_clarification")),
        disposition="RETRIEVAL_CANDIDATE_ALLOWED" if allowed else "NO_TOOL_EXECUTION",
        rejection_reasons=rejection,
    )


def _controlled_chunks(initial: tuple[Mapping[str, Any], ...]) -> tuple[RetrievedChunkV2, ...]:
    chunks: list[RetrievedChunkV2] = []
    for item in initial:
        declared = str(item.get("content_level", "unavailable"))
        support_state = str(item.get("support_status", ""))
        if support_state == "UNSUPPORTED":
            level = "unavailable"
        elif declared == "partial_excerpt":
            level = "excerpt"
        else:
            level = declared
        evidence_id = str(item["evidence_id"])
        text = str(item.get("raw_content") or "")
        chunk = CourseChunkV2(
            chunk_id=evidence_id,
            document_id="controlled-" + hashlib.sha256(evidence_id.encode()).hexdigest()[:12],
            source_file="controlled-local-fixture",
            source_type="controlled_fixture",
            material_type="reading",
            title="Controlled evidence",
            section_path=("Controlled section",),
            text=text,
            week=None,
            page_number=None,
            assessment_part=None,
            content_level=level,
            parent_chunk_id=None,
            previous_chunk_id=None,
            next_chunk_id=None,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            metadata={"controlled_support_state": support_state},
        )
        chunks.append(RetrievedChunkV2(chunk=chunk))
    return tuple(chunks)


def run_sufficiency_fixture(
    value: Mapping[str, Any], initial: tuple[Mapping[str, Any], ...]
) -> OfflineRAGResult:
    assert_existing_sufficiency_interface()
    chunks = _controlled_chunks(initial)
    support_states = {str(item.get("support_status", "")) for item in initial}
    declared_levels = {str(item.get("content_level", "")) for item in initial}
    minimum = (
        "full_text"
        if "partial_excerpt" in declared_levels
        else "excerpt"
        if chunks
        else "title_and_metadata"
    )
    plan = QueryPlanV2(
        query=str(value.get("text", "")),
        retrieval_requested=True,
        material_type="reading",
        intents=("explain_findings",),
        minimum_evidence_level=minimum,
        reason="controlled offline sufficiency conformance",
    )
    existing = evaluate_evidence_sufficiency(plan, chunks)
    status = normalise_sufficiency_status(existing.status)
    # The controlled chunk's declared support state is an input-side extraction
    # assertion, distinct from every expected_* scoring field. It may only make
    # the existing interface more conservative.
    if "UNSUPPORTED" in support_states:
        status = "UNSUPPORTED"
    admitted = (
        tuple(existing.supporting_chunk_ids)
        if evidence_admission_allowed(status, len(existing.supporting_chunk_ids))
        else ()
    )
    rejection: dict[str, str] = {}
    if status in {"AMBIGUOUS", "UNSUPPORTED"}:
        reason = f"{status}_EVIDENCE"
        rejection = {item.chunk.chunk_id: reason for item in chunks}
    elif status == "NO_RESULT":
        rejection = {"retrieval": "NO_RESULT"}
    disposition = {
        "SUPPORTED": "SUPPORTED_EVIDENCE_ADMITTED",
        "AMBIGUOUS": "SAFE_CLARIFICATION",
        "UNSUPPORTED": "SAFE_INSUFFICIENCY",
        "NO_RESULT": "SAFE_NO_RESULT",
        "NOT_APPLICABLE": "NO_RETRIEVAL_EVIDENCE",
    }[status]
    return OfflineRAGResult(
        candidate_allowed=True,
        retrieval_attempted=True,
        retrieved_ids=tuple(item.chunk.chunk_id for item in chunks),
        sufficiency_status=status,
        admitted_ids=admitted,
        clarification_required=status == "AMBIGUOUS",
        disposition=disposition,
        rejection_reasons=rejection,
    )
