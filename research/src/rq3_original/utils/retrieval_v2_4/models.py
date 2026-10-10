"""Typed contracts for the isolated Retrieval v2.4 experiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from utils.retrieval_v2.models import CourseChunkV2, EvidenceSufficiencyV2


@dataclass(frozen=True)
class CourseChunkV24:
    chunk_id: str
    document_id: str
    source_file: str
    source_type: str
    material_type: str
    title: str
    section_path: tuple[str, ...]
    text: str
    week: str | None
    page_number: int | None
    assessment_part: str | None
    content_level: str
    parent_chunk_id: str | None
    previous_chunk_id: str | None
    next_chunk_id: str | None
    source_hash: str
    content_roles: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_v23(cls, chunk: CourseChunkV2, content_roles: tuple[str, ...]) -> "CourseChunkV24":
        payload = chunk.to_dict()
        payload["section_path"] = tuple(payload["section_path"])
        return cls(**payload, content_roles=content_roles)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CourseChunkV24":
        payload = dict(value)
        payload["section_path"] = tuple(payload.get("section_path") or ())
        payload["content_roles"] = tuple(payload.get("content_roles") or ())
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["section_path"] = list(self.section_path)
        value["content_roles"] = list(self.content_roles)
        return value


@dataclass(frozen=True)
class QueryFacetV24:
    facet_id: str
    facet_type: str
    week: str | None
    material_roles: tuple[str, ...]
    required_content_level: str
    intent: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["material_roles"] = list(self.material_roles)
        return value


@dataclass(frozen=True)
class QueryPlanV24:
    original_query: str
    canonical_retrieval_query: str
    retrieval_requested: bool
    week: str | None
    material_type: str | None
    assessment_part: str | None
    named_author: str | None
    named_title: str | None
    intents: tuple[str, ...]
    minimum_evidence_level: str
    reliable_filters: tuple[str, ...]
    dashboard_evidence_requested: bool
    facets: tuple[QueryFacetV24, ...]
    reason: str

    @property
    def query(self) -> str:
        return self.original_query

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["intents"] = list(self.intents)
        value["reliable_filters"] = list(self.reliable_filters)
        value["facets"] = [facet.to_dict() for facet in self.facets]
        return value


@dataclass(frozen=True)
class RetrievedChunkV24:
    chunk: CourseChunkV24
    lexical_rank: int | None
    fused_rank: int | None
    rerank_rank: int | None
    reranker_score: float
    rerank_reasons: tuple[str, ...]
    gate_reasons: tuple[str, ...]
    matched_facets: tuple[str, ...]
    reserved_before_source_cap: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.chunk.to_dict(),
            "lexical_rank": self.lexical_rank,
            "fused_rank": self.fused_rank,
            "rerank_rank": self.rerank_rank,
            "reranker_score": self.reranker_score,
            "rerank_reasons": list(self.rerank_reasons),
            "gate_reasons": list(self.gate_reasons),
            "matched_facets": list(self.matched_facets),
            "reserved_before_source_cap": self.reserved_before_source_cap,
        }


@dataclass(frozen=True)
class RetrievalResultV24:
    original_query: str
    canonical_retrieval_query: str
    query_plan: QueryPlanV24
    retrieval_requested: bool
    retrieval_used: bool
    retrieved_chunks: tuple[RetrievedChunkV24, ...]
    evidence_sufficiency: EvidenceSufficiencyV2
    stage_audit: dict[str, dict[str, Any]]
    candidate_diagnostics: dict[str, Any]
    reason: str
    index_version: str
    index_hash: str
    backend_mode: str
    semantic_backend_available: bool
    latency_ms: float

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "query": self.original_query,
            "original_query": self.original_query,
            "canonical_retrieval_query": self.canonical_retrieval_query,
            "query_plan": self.query_plan.to_dict(),
            "retrieval_requested": self.retrieval_requested,
            "retrieval_used": self.retrieval_used,
            "retrieved_chunks": [item.to_dict() for item in self.retrieved_chunks],
            "retrieved_chunk_ids": [item.chunk.chunk_id for item in self.retrieved_chunks],
            "retrieved_sources": [item.chunk.source_file for item in self.retrieved_chunks],
            "evidence_sufficiency": self.evidence_sufficiency.to_dict(),
            "stage_audit": self.stage_audit,
            "candidate_diagnostics": self.candidate_diagnostics,
            "reason": self.reason,
            "index_version": self.index_version,
            "index_hash": self.index_hash,
            "backend_mode": self.backend_mode,
            "semantic_backend_available": self.semantic_backend_available,
            "latency_ms": self.latency_ms,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_audit_dict()
