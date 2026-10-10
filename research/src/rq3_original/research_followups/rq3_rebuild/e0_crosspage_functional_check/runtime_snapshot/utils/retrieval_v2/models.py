"""Typed public contracts for the post-freeze experimental retrieval extension."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CONTENT_LEVELS = (
    "full_text",
    "excerpt",
    "title_and_metadata",
    "citation_only",
    "unavailable",
)
EXTRACTION_STATUSES = (
    "extracted",
    "partially_extracted",
    "metadata_only",
    "unreadable",
    "missing",
)
SUFFICIENCY_STATUSES = (
    "sufficient",
    "partially_sufficient",
    "metadata_only",
    "insufficient",
    "no_result",
    "not_applicable",
)


@dataclass(frozen=True)
class ManifestRecordV2:
    document_id: str
    source_path: str
    source_type: str
    material_type: str
    title: str
    week: str | None = None
    section: str | None = None
    page: int | None = None
    assessment_part: str | None = None
    source_url: str | None = None
    content_level: str = "unavailable"
    extraction_status: str = "missing"
    enabled: bool = True
    notes: str = ""
    excluded_reason: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManifestRecordV2":
        record = cls(**{key: value.get(key) for key in cls.__dataclass_fields__})
        if record.content_level not in CONTENT_LEVELS:
            raise ValueError(f"Invalid content_level for {record.document_id}: {record.content_level}")
        if record.extraction_status not in EXTRACTION_STATUSES:
            raise ValueError(
                f"Invalid extraction_status for {record.document_id}: {record.extraction_status}"
            )
        if not record.document_id or not record.source_path:
            raise ValueError("Manifest records require document_id and source_path")
        return record


@dataclass(frozen=True)
class ExtractedSectionV2:
    title: str
    section_path: tuple[str, ...]
    text: str
    week: str | None = None
    page_number: int | None = None
    assessment_part: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocumentV2:
    document_id: str
    source_path: str
    source_type: str
    material_type: str
    title: str
    source_hash: str
    content_level: str
    extraction_status: str
    extraction_method: str
    sections: tuple[ExtractedSectionV2, ...]
    week: str | None = None
    assessment_part: str | None = None
    source_url: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CourseChunkV2:
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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["section_path"] = list(self.section_path)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CourseChunkV2":
        payload = dict(value)
        payload["section_path"] = tuple(payload.get("section_path") or ())
        return cls(**payload)


@dataclass(frozen=True)
class QueryPlanV2:
    query: str
    retrieval_requested: bool
    week: str | None = None
    material_type: str | None = None
    assessment_part: str | None = None
    named_author: str | None = None
    named_title: str | None = None
    intents: tuple[str, ...] = ()
    minimum_evidence_level: str = "title_and_metadata"
    reliable_filters: tuple[str, ...] = ()
    dashboard_evidence_requested: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["intents"] = list(self.intents)
        value["reliable_filters"] = list(self.reliable_filters)
        return value


@dataclass(frozen=True)
class RetrievedChunkV2:
    chunk: CourseChunkV2
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    fused_rank: int | None = None
    reranker_score: float = 0.0
    rerank_reason: tuple[str, ...] = ()
    metadata_matches: dict[str, bool] = field(default_factory=dict)
    expanded_from_chunk_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = self.chunk.to_dict()
        value.update(
            {
                "lexical_rank": self.lexical_rank,
                "semantic_rank": self.semantic_rank,
                "fused_rank": self.fused_rank,
                "reranker_score": self.reranker_score,
                "rerank_reason": list(self.rerank_reason),
                "metadata_matches": dict(self.metadata_matches),
                "expanded_from_chunk_id": self.expanded_from_chunk_id,
            }
        )
        return value

    def to_generation_dict(self) -> dict[str, Any]:
        """Return prompt-safe evidence without neighbour IDs or ranking diagnostics."""

        chunk = self.chunk
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source_file": chunk.source_file,
            "source_type": chunk.source_type,
            "material_type": chunk.material_type,
            "source_title": chunk.metadata.get("document_title", chunk.title),
            "title": chunk.title,
            "section_path": list(chunk.section_path),
            "text": chunk.text,
            "week": chunk.week,
            "page_number": chunk.page_number,
            "assessment_part": chunk.assessment_part,
            "content_level": chunk.content_level,
            "source_url": chunk.metadata.get("source_url"),
        }


@dataclass(frozen=True)
class EvidenceSufficiencyV2:
    status: str
    answerable: bool
    required_content_level: str
    available_content_levels: tuple[str, ...]
    supporting_chunk_ids: tuple[str, ...]
    unsupported_requested_claim_types: tuple[str, ...]
    reason: str
    user_facing_boundary: str
    allowed_claim_scope: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in SUFFICIENCY_STATUSES:
            raise ValueError(f"Invalid sufficiency status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "available_content_levels",
            "supporting_chunk_ids",
            "unsupported_requested_claim_types",
            "allowed_claim_scope",
        ):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class RetrievalResultV2:
    query: str
    query_plan: QueryPlanV2
    retrieval_requested: bool
    retrieval_used: bool
    backend_mode: str
    semantic_backend_available: bool
    retrieved_chunks: tuple[RetrievedChunkV2, ...]
    candidate_diagnostics: dict[str, Any]
    evidence_sufficiency: EvidenceSufficiencyV2
    reason: str
    warnings: tuple[str, ...]
    index_version: str
    corpus_manifest_hash: str
    index_hash: str
    latency_ms: float

    @property
    def chunks(self) -> list[CourseChunkV2]:
        """Compatibility convenience for narrow integration adapters."""

        return [item.chunk for item in self.retrieved_chunks]

    def _base_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "query_plan": self.query_plan.to_dict(),
            "retrieval_requested": self.retrieval_requested,
            "retrieval_used": self.retrieval_used,
            "backend_mode": self.backend_mode,
            "semantic_backend_available": self.semantic_backend_available,
            "evidence_sufficiency": self.evidence_sufficiency.to_dict(),
            "reason": self.reason,
            "warnings": list(self.warnings),
            "index_version": self.index_version,
            "corpus_manifest_hash": self.corpus_manifest_hash,
            "index_hash": self.index_hash,
            "latency_ms": self.latency_ms,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """Serialise complete retrieval diagnostics outside generation prompts."""

        supporting = set(self.evidence_sufficiency.supporting_chunk_ids)
        value = self._base_dict()
        value.update(
            {
                "retrieved_chunks": [item.to_dict() for item in self.retrieved_chunks],
                "retrieved_chunk_ids": [item.chunk.chunk_id for item in self.retrieved_chunks],
                "retrieved_chunk_titles": [item.chunk.title for item in self.retrieved_chunks],
                "retrieved_sources": [item.chunk.source_file for item in self.retrieved_chunks],
                "rejected_non_supporting_chunk_ids": [
                    item.chunk.chunk_id
                    for item in self.retrieved_chunks
                    if item.chunk.chunk_id not in supporting
                ],
                "candidate_diagnostics": dict(self.candidate_diagnostics),
            }
        )
        return value

    def to_generation_dict(self) -> dict[str, Any]:
        """Serialise only sufficiency-approved evidence for model generation."""

        supporting = set(self.evidence_sufficiency.supporting_chunk_ids)
        allow_chunks = self.evidence_sufficiency.status not in {
            "no_result", "insufficient", "not_applicable"
        }
        approved = [
            item for item in self.retrieved_chunks
            if allow_chunks and item.chunk.chunk_id in supporting
        ]
        return {
            "query": self.query,
            "query_plan": {
                key: value
                for key, value in self.query_plan.to_dict().items()
                if key in {
                    "week", "material_type", "assessment_part", "intents",
                    "minimum_evidence_level", "dashboard_evidence_requested",
                }
            },
            "retrieval_requested": self.retrieval_requested,
            "retrieval_used": bool(approved),
            "evidence_sufficiency": self.evidence_sufficiency.to_dict(),
            "supporting_chunk_ids": [item.chunk.chunk_id for item in approved],
            "allowed_chunks": [item.to_generation_dict() for item in approved],
        }

    def to_dict(self) -> dict[str, Any]:
        """Backward-compatible alias for the full audit serialisation."""

        return self.to_audit_dict()
