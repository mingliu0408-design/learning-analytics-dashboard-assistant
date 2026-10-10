"""Mesgar-inspired symmetric interaction features over frozen vectors."""

from __future__ import annotations

import numpy as np
import torch


FEATURE_SCHEMA = "concat(abs(q-c),q*c)-v1"


def numpy_pair_features(query: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    q = np.asarray(query, dtype=np.float32)
    c = np.asarray(candidate, dtype=np.float32)
    if q.shape != c.shape or q.ndim < 1:
        raise ValueError("query and candidate vectors must have the same non-scalar shape")
    return np.concatenate((np.abs(q - c), q * c), axis=-1).astype(np.float32, copy=False)


def torch_pair_features(query: torch.Tensor, candidate: torch.Tensor) -> torch.Tensor:
    if query.shape != candidate.shape or query.ndim < 1:
        raise ValueError("query and candidate tensors must have the same non-scalar shape")
    if query.dtype != torch.float32 or candidate.dtype != torch.float32:
        raise ValueError("LR-3 neural features require float32 tensors")
    return torch.cat((torch.abs(query - candidate), query * candidate), dim=-1)


def expected_feature_dimension(embedding_dimension: int) -> int:
    if embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be positive")
    return 2 * int(embedding_dimension)

