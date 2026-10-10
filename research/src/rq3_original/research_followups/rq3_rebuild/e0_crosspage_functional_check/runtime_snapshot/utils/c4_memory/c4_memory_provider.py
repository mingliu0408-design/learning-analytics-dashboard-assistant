"""Provider and later-UI control contract for C4 persistent learner Memory."""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Callable, Mapping, Sequence

from .c4_memory_retriever import C4MemoryRetriever, RetrievalResult, SemanticBackend
from .c4_memory_store import ARCHITECTURE_ID, C4MemoryStore, MemoryRecord, sha256_object
from .c4_memory_writer import (
    C4MemoryWriter,
    StructuredMemoryCandidate,
    WritePolicyResult,
)


PROVIDER_VERSION = "c4-learner-memory-provider-v1"
EVIDENCE_REPRESENTATION = "C4_READ_ONLY_MEMORY_EVIDENCE_V1"


class C4LearnerMemoryProvider:
    """Offline Track M provider; C4/P3 integration is deliberately absent."""

    def __init__(
        self,
        store: C4MemoryStore,
        *,
        semantic_backend: SemanticBackend | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.writer = C4MemoryWriter(store)
        self.retriever = C4MemoryRetriever(
            store,
            semantic_backend=semantic_backend,
            clock=clock,
        )

    @staticmethod
    def _student_scope_sha256(student_id: str) -> str:
        return hashlib.sha256(("C4_LEARNER_SCOPE_V1\0" + student_id).encode("utf-8")).hexdigest()

    @classmethod
    def _envelope(
        cls,
        *,
        student_id: str,
        retrieval: RetrievalResult,
        extra_limitations: Sequence[str] = (),
    ) -> dict[str, Any]:
        selected_items: list[dict[str, Any]] = []
        for candidate in retrieval.selected:
            record = candidate.record
            selected_items.append(
                {
                    "memory_id": record.memory_id,
                    "memory_type": record.memory_type,
                    "content": record.content,
                    "timestamp_version": {
                        "created_at": record.created_at,
                        "valid_from": record.valid_from,
                        "valid_to": record.valid_to,
                        "last_confirmed_at": record.last_confirmed_at,
                        "version": record.version,
                        "status": record.status,
                    },
                    "relevance_components": candidate.relevance_components(),
                    "provenance": {
                        "source_session_id": record.source_session_id,
                        "source_turn_id": record.source_turn_id,
                        "supersedes_memory_id": record.supersedes_memory_id,
                        "consent_status": record.consent_status,
                        "content_sha256": record.content_sha256,
                    },
                    "read_only_evidence": {
                        "representation": EVIDENCE_REPRESENTATION,
                        "mutable": False,
                        "content": record.content,
                        "content_sha256": record.content_sha256,
                    },
                }
            )
        limitations = list(dict.fromkeys([*retrieval.limitations, *extra_limitations]))
        body: dict[str, Any] = {
            "architecture_id": ARCHITECTURE_ID,
            "provider_version": PROVIDER_VERSION,
            "status": "AVAILABLE" if selected_items else "NO_MATCH",
            "student_scope_sha256": cls._student_scope_sha256(student_id),
            "selected_memory_items": selected_items,
            "retrieval": {
                "query_time": retrieval.query_time,
                "top_k_returned": len(selected_items),
                "active_candidate_count": retrieval.active_candidate_count,
                "visible_history_excluded_count": retrieval.visible_history_excluded_count,
                "conflict_excluded_count": retrieval.conflict_excluded_count,
                "semantic_backend": dict(retrieval.semantic_backend),
                "embeddings_exposed": False,
            },
            "limitations": limitations,
        }
        body["envelope_sha256"] = sha256_object(body)
        return body

    def retrieve(
        self,
        student_id: str,
        student_query: str,
        visible_history: Sequence[Mapping[str, Any] | Sequence[Any] | str] | None,
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Return a read-only Memory envelope or ``NO_MATCH``.

        The frozen P3 Memory Specialist gate is intentionally not invoked here;
        later C4 integration must call this provider only after that gate says
        Memory is required.
        """

        if not self.store.is_memory_enabled(student_id):
            retrieval = RetrievalResult(
                selected=(),
                query_time=self.retriever._clock(),
                semantic_backend={"backend": "NOT_USED", "network_allowed": False},
                limitations=("MEMORY_DISABLED_FOR_LEARNER",),
                active_candidate_count=0,
                visible_history_excluded_count=0,
                conflict_excluded_count=0,
            )
            return self._envelope(
                student_id=student_id,
                retrieval=retrieval,
                extra_limitations=("P3_GATE_NOT_EXECUTED_IN_TRACK_M",),
            )
        retrieval = self.retriever.retrieve(
            student_id,
            student_query,
            visible_history,
            top_k=top_k,
        )
        return self._envelope(
            student_id=student_id,
            retrieval=retrieval,
            extra_limitations=(
                "TRACK_M_RESEARCH_ONLY_NOT_C4_INTEGRATED",
                "P3_GATE_NOT_EXECUTED_IN_TRACK_M",
            ),
        )

    @staticmethod
    def _control_view(record: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": record.memory_id,
            "memory_type": record.memory_type,
            "content": record.content,
            "created_at": record.created_at,
            "valid_from": record.valid_from,
            "valid_to": record.valid_to,
            "last_confirmed_at": record.last_confirmed_at,
            "version": record.version,
            "confidence": record.confidence,
            "importance": record.importance,
            "content_sha256": record.content_sha256,
            "read_only": True,
        }

    def list_active_memories(self, student_id: str) -> list[dict[str, Any]]:
        return [self._control_view(record) for record in self.store.list_active_memories(student_id)]

    def correct_memory(
        self,
        *,
        student_id: str,
        target_memory_id: str,
        corrected_content: str,
        source_session_id: str,
        source_turn_id: str,
        user_turn: str,
        evidence_span: str,
        confidence: float = 1.0,
        event_at: str | datetime | None = None,
    ) -> WritePolicyResult:
        candidate = StructuredMemoryCandidate(
            operation="SUPERSEDE",
            memory_type="CORRECTION",
            content=corrected_content,
            target_memory_id=target_memory_id,
            confidence=confidence,
            evidence_span=evidence_span,
        )
        return self.writer.apply_candidate(
            student_id=student_id,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            source_text=user_turn,
            candidate=candidate,
            source_role="USER",
            claim_basis="EXPLICIT_USER_STATEMENT",
            event_at=event_at,
        )

    def delete_memory(
        self,
        *,
        student_id: str,
        target_memory_id: str,
        source_session_id: str,
        source_turn_id: str,
        user_turn: str,
        evidence_span: str,
        confidence: float = 1.0,
        event_at: str | datetime | None = None,
    ) -> WritePolicyResult:
        candidate = StructuredMemoryCandidate(
            operation="DELETE",
            memory_type=None,
            content=None,
            target_memory_id=target_memory_id,
            confidence=confidence,
            evidence_span=evidence_span,
        )
        return self.writer.apply_candidate(
            student_id=student_id,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            source_text=user_turn,
            candidate=candidate,
            source_role="USER",
            claim_basis="EXPLICIT_USER_STATEMENT",
            event_at=event_at,
        )

    def disable_memory_for_learner(
        self,
        student_id: str,
        *,
        event_at: str | datetime | None = None,
    ) -> None:
        self.store.set_memory_enabled(student_id, False, event_at=event_at)

    def enable_memory_for_learner(
        self,
        student_id: str,
        *,
        event_at: str | datetime | None = None,
    ) -> None:
        self.store.set_memory_enabled(student_id, True, event_at=event_at)

    def clear_experimental_learner_state(self, student_id: str) -> dict[str, int]:
        return self.store.clear_experimental_learner_state(student_id)
