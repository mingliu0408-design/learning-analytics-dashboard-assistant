"""RQ1-A LR4B contract package; no training or model execution lives here."""

from .contract_schema import (
    QUERY_ONLY_V1,
    STRUCTURED_CONTEXT_V1,
    keyword_single_candidate_reciprocal_rank,
    keyword_single_candidate_ranking,
)
from .context_representation import (
    build_query_only_representation,
    build_structured_context_representation,
    normalise_source_field,
)

__all__ = [
    "QUERY_ONLY_V1",
    "STRUCTURED_CONTEXT_V1",
    "build_query_only_representation",
    "build_structured_context_representation",
    "keyword_single_candidate_reciprocal_rank",
    "keyword_single_candidate_ranking",
    "normalise_source_field",
]
