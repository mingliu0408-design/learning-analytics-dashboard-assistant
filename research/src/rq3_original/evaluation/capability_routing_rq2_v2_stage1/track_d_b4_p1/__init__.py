"""Offline RQ2-V2 Stage 1D B4 and P1 research harnesses.

Only deterministic mock-provider execution is implemented here.  The package
contains no network client, paid-provider integration, trained model, frozen
thresholds, or final few-shot selection.
"""

from .b4 import (
    B4CapabilityResponse,
    B4OfflineHarness,
    B4ResponseParseError,
    PRIMARY_SEMANTIC_INPUT_FIELDS,
    PRIMARY_SEMANTIC_INPUT_PROFILE,
    PromptInputError,
    build_b4_prompt,
    extract_primary_semantic_input,
    parse_b4_response,
)
from .mock_provider import DeterministicMockProvider
from .p1 import P1HybridRouter

__all__ = [
    "B4CapabilityResponse",
    "B4OfflineHarness",
    "B4ResponseParseError",
    "DeterministicMockProvider",
    "P1HybridRouter",
    "PRIMARY_SEMANTIC_INPUT_FIELDS",
    "PRIMARY_SEMANTIC_INPUT_PROFILE",
    "PromptInputError",
    "build_b4_prompt",
    "extract_primary_semantic_input",
    "parse_b4_response",
]
