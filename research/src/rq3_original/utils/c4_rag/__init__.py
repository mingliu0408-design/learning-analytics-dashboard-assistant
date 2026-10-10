"""Retrieval-only Course-RAG implementations for RQ3-REAL-C4 Track R.

This package contains no response generation and is not wired into Streamlit or
the C4 service.  The frozen RQ2 P3 Specialist remains the authority that decides
whether this provider is called.
"""

from .models import EvidenceStrength, RetrievalEnvelope, ResultStatus, SelectedChunk
from .provider import C4CourseRAGProvider
from .retrievers import C4RAGLegacyLexical, C4RAGHybrid

__all__ = [
    "C4CourseRAGProvider",
    "C4RAGHybrid",
    "C4RAGLegacyLexical",
    "EvidenceStrength",
    "RetrievalEnvelope",
    "ResultStatus",
    "SelectedChunk",
]
