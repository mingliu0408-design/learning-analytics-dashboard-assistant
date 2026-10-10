"""Small retrieval-only provider interface for later C4_REAL injection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import RetrievalEnvelope
from .retrievers import C4RAGHybrid, C4RAGLegacyLexical, R0_ID, R1_ID


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FROZEN_SELECTION_PATH = (
    PROJECT_ROOT
    / "evaluation/rq3_real_c4/track_r_rag/selected_c4_rag_frozen_v1.json"
)


class C4CourseRAGProvider:
    """Retrieve course evidence after an upstream RAG-required decision.

    This object makes zero response-generation calls.  It has no Dashboard
    input and therefore cannot fall back to unrelated Dashboard evidence.
    """

    def __init__(self, implementation_id: str | None = None) -> None:
        selected = implementation_id or self._frozen_implementation_id()
        if selected == R0_ID:
            self._retriever = C4RAGLegacyLexical()
        elif selected == R1_ID:
            self._retriever = C4RAGHybrid()
        else:
            raise ValueError(f"Unknown C4 Course-RAG implementation: {selected}")
        self.implementation_id = selected

    @staticmethod
    def _frozen_implementation_id() -> str:
        if not FROZEN_SELECTION_PATH.is_file():
            # During the Track R comparison only; final artefacts always bind one.
            return R1_ID
        payload = json.loads(FROZEN_SELECTION_PATH.read_text(encoding="utf-8"))
        return str(payload["selected_implementation_id"])

    def retrieve(
        self,
        student_query: str,
        current_page: str,
        visible_history: Any,
        *,
        student_id: str | int | None = None,
        top_k: int = 5,
    ) -> RetrievalEnvelope:
        del student_id  # Retrieval is course-corpus scoped and student-identity independent.
        return self._retriever.retrieve(
            student_query,
            current_page,
            visible_history,
            top_k=top_k,
            retrieval_enabled=True,
        )
