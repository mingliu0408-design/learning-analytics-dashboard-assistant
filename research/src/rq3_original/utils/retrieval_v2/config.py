"""Central configuration for Retrieval v2.

Retrieval v2 is a post-freeze experimental retrieval extension.  All paths and
ranking/chunking constants live here so the v1 implementation remains frozen.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETRIEVAL_VERSION = "retrieval_v2.3"


@dataclass(frozen=True)
class RetrievalConfigV2:
    manifest_path: Path = PROJECT_ROOT / "course_materials_v2" / "manifest.jsonl"
    output_dir: Path = PROJECT_ROOT / "evaluation" / "outputs" / "retrieval_v2"
    index_dir: Path = PROJECT_ROOT / "evaluation" / "outputs" / "retrieval_v2" / "index"
    target_chunk_chars: int = 900
    min_chunk_chars: int = 220
    max_chunk_chars: int = 1200
    overlap_chars: int = 140
    maximum_prompt_expanded_context_chars: int = 6000
    maximum_chunks_per_source: int = 3
    lexical_candidate_top_k: int = 20
    semantic_candidate_top_k: int = 20
    rrf_constant: int = 60
    final_top_k: int = 5
    minimum_lexical_score: float = 0.05
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    enable_neighbour_expansion: bool = True

    def fingerprint_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, Path):
                value[key] = str(item)
        return value


DEFAULT_CONFIG = RetrievalConfigV2()

PRIVACY_EXCLUSION_PATTERNS = (
    "chat_history.csv",
    ".env",
    "secrets.toml",
    "system data/configuration",
    "evaluation/outputs",
    "human_annotation",
    "student_info",
    "private_student",
    "__macosx",
    ".ds_store",
    "__pycache__",
    ".cache",
)


def is_privacy_excluded(source_path: str) -> tuple[bool, str]:
    normalised = str(source_path).replace("\\", "/").lower()
    for pattern in PRIVACY_EXCLUSION_PATTERNS:
        if pattern in normalised:
            return True, pattern
    return False, ""
