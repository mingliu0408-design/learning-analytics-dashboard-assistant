"""Central, versioned configuration for Retrieval v2.4."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.retrieval_v2.config import PROJECT_ROOT


RETRIEVAL_VERSION_V24 = "retrieval_v2.4"
ROLE_EXTRACTION_VERSION = "content_roles_v1.2"


@dataclass(frozen=True)
class RetrievalConfigV24:
    index_dir: Path = (
        PROJECT_ROOT / "evaluation" / "outputs" / "retrieval_v2" / "index_v2_4"
    )
    lexical_candidate_top_k: int = 20
    final_top_k: int = 5
    maximum_chunks_per_source: int = 3
    rrf_constant: int = 60
    minimum_lexical_score: float = 0.01
    minimum_raw_overlap: int = 2
    fuzzy_term_cutoff: float = 0.76
    title_weight: float = 3.4
    section_weight: float = 2.8
    body_weight: float = 1.0
    canonical_metadata_weight: float = 3.6
    url_weight: float = 0.45
    link_intent_url_weight: float = 3.2
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    def fingerprint_dict(self) -> dict[str, object]:
        return {
            key: str(value) if isinstance(value, Path) else value
            for key, value in self.__dict__.items()
            if key != "index_dir"
        }


DEFAULT_CONFIG_V24 = RetrievalConfigV24()
