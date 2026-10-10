"""Isolated post-freeze Retrieval v2.4 lexical experiment."""

from .config import RETRIEVAL_VERSION_V24

__all__ = ["CourseMaterialRetrieverV24", "RETRIEVAL_VERSION_V24"]


def __getattr__(name: str):
    if name == "CourseMaterialRetrieverV24":
        from .retriever import CourseMaterialRetrieverV24

        return CourseMaterialRetrieverV24
    raise AttributeError(name)
