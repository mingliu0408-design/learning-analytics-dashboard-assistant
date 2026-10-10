"""Retrieval v2 — post-freeze experimental retrieval extension."""

from .config import DEFAULT_CONFIG, RETRIEVAL_VERSION, RetrievalConfigV2
from .models import (
    CourseChunkV2,
    EvidenceSufficiencyV2,
    QueryPlanV2,
    RetrievalResultV2,
    RetrievedChunkV2,
)

__all__ = [
    "CourseChunkV2",
    "CourseMaterialRetrieverV2",
    "DEFAULT_CONFIG",
    "DisabledEmbeddingProvider",
    "EvidenceSufficiencyV2",
    "FakeEmbeddingProvider",
    "QueryPlanV2",
    "RETRIEVAL_VERSION",
    "RetrievalConfigV2",
    "RetrievalResultV2",
    "RetrievedChunkV2",
    "SentenceTransformerEmbeddingProvider",
    "analyse_query",
    "retrieve_course_materials_v2",
]


def __getattr__(name: str):
    """Load heavier retrieval components lazily, keeping module CLIs warning-free."""

    if name == "analyse_query":
        from .query_analysis import analyse_query

        return analyse_query
    if name in {"CourseMaterialRetrieverV2", "retrieve_course_materials_v2"}:
        from .retriever import CourseMaterialRetrieverV2, retrieve_course_materials_v2

        return {
            "CourseMaterialRetrieverV2": CourseMaterialRetrieverV2,
            "retrieve_course_materials_v2": retrieve_course_materials_v2,
        }[name]
    if name in {
        "DisabledEmbeddingProvider",
        "FakeEmbeddingProvider",
        "SentenceTransformerEmbeddingProvider",
    }:
        from .semantic_index import (
            DisabledEmbeddingProvider,
            FakeEmbeddingProvider,
            SentenceTransformerEmbeddingProvider,
        )

        return {
            "DisabledEmbeddingProvider": DisabledEmbeddingProvider,
            "FakeEmbeddingProvider": FakeEmbeddingProvider,
            "SentenceTransformerEmbeddingProvider": SentenceTransformerEmbeddingProvider,
        }[name]
    raise AttributeError(name)
