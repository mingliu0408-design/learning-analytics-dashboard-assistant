"""Typed retrieval envelope used by both Track R candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EvidenceStrength(str, Enum):
    FULL_TEXT_SUPPORT = "FULL_TEXT_SUPPORT"
    BODY_EXCERPT = "BODY_EXCERPT"
    SUMMARY_SUPPORT = "SUMMARY_SUPPORT"
    TITLE_AND_METADATA_ONLY = "TITLE_AND_METADATA_ONLY"
    LINK_ONLY = "LINK_ONLY"
    WEAK_MATCH = "WEAK_MATCH"
    NO_RESULT = "NO_RESULT"


SUBSTANTIVE_STRENGTHS = frozenset(
    {
        EvidenceStrength.FULL_TEXT_SUPPORT,
        EvidenceStrength.BODY_EXCERPT,
        EvidenceStrength.SUMMARY_SUPPORT,
    }
)


class ResultStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    LIMITED_EVIDENCE = "LIMITED_EVIDENCE"
    WEAK_MATCH = "WEAK_MATCH"
    NO_RESULT = "NO_RESULT"


@dataclass(frozen=True)
class SelectedChunk:
    """One selected, source-traceable course chunk."""

    rank: int
    chunk_id: str
    document_id: str
    document_title: str
    source_path: str
    source_sha256: str
    source_type: str
    text: str
    week: str | None
    section: str | None
    page: str | None
    evidence_strength: EvidenceStrength
    substantive_claim_support: bool
    lexical_score: float | None
    dense_score: float | None
    fusion_rank: int | None

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_strength"] = self.evidence_strength.value
        if not include_text:
            value.pop("text", None)
        return value


@dataclass(frozen=True)
class RetrievalEnvelope:
    """Provider return type.  NO_RESULT is a valid, non-exceptional result."""

    implementation_id: str
    query: str
    result_status: ResultStatus
    selected_chunks: tuple[SelectedChunk, ...]
    limitations: tuple[str, ...]
    latency_ms: float

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(item.chunk_id for item in self.selected_chunks)

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.document_id for item in self.selected_chunks))

    @property
    def document_titles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.document_title for item in self.selected_chunks))

    @property
    def weeks(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.week for item in self.selected_chunks if item.week))

    @property
    def sections(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.section for item in self.selected_chunks if item.section))

    @property
    def evidence_strength_classes(self) -> tuple[str, ...]:
        if not self.selected_chunks:
            return (EvidenceStrength.NO_RESULT.value,)
        return tuple(item.evidence_strength.value for item in self.selected_chunks)

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        return {
            "implementation_id": self.implementation_id,
            "query": self.query,
            "result_status": self.result_status.value,
            "selected_chunks": [
                item.to_dict(include_text=include_text) for item in self.selected_chunks
            ],
            "chunk_ids": list(self.chunk_ids),
            "document_ids": list(self.document_ids),
            "document_titles": list(self.document_titles),
            "weeks": list(self.weeks),
            "sections": list(self.sections),
            "evidence_strength_classes": list(self.evidence_strength_classes),
            "limitations": list(self.limitations),
            "latency_ms": self.latency_ms,
        }
