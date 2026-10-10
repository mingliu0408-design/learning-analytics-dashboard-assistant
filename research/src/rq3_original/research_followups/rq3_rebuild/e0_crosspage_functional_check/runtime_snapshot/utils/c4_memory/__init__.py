"""Research-only persistent learner Memory for RQ3-REAL Track M.

This package is deliberately not wired into C_FULL or Streamlit.  It performs
local SQLite persistence and offline retrieval only.
"""

from .c4_memory_provider import C4LearnerMemoryProvider
from .c4_memory_retriever import FrozenLocalMPNetBackend
from .c4_memory_store import C4MemoryStore, MemoryRecord
from .c4_memory_writer import C4MemoryWriter, StructuredMemoryCandidate

__all__ = [
    "C4LearnerMemoryProvider",
    "C4MemoryStore",
    "C4MemoryWriter",
    "FrozenLocalMPNetBackend",
    "MemoryRecord",
    "StructuredMemoryCandidate",
]
