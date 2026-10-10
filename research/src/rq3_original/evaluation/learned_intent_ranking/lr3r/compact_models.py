"""Research-only compact nonlinear similarity heads for LR-3R."""

from __future__ import annotations

import torch
from torch import nn


HIDDEN_DIMENSIONS = {"M64": 64, "M128": 128}


class CompactMLPSimilarityScorer(nn.Module):
    """The predeclared one-hidden-layer LR-3R capacity ablation."""

    def __init__(self, feature_dimension: int, hidden_dimension: int, dropout: float = 0.5) -> None:
        super().__init__()
        if hidden_dimension not in HIDDEN_DIMENSIONS.values():
            raise ValueError(f"unauthorised hidden dimension: {hidden_dimension}")
        self.feature_dimension = int(feature_dimension)
        self.hidden_dimension = int(hidden_dimension)
        self.dropout_probability = float(dropout)
        self.layer_norm = nn.LayerNorm(self.feature_dimension)
        self.hidden = nn.Linear(self.feature_dimension, self.hidden_dimension)
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(p=self.dropout_probability)
        self.output = nn.Linear(self.hidden_dimension, 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        normalized = self.layer_norm(features)
        hidden = self.activation(self.hidden(normalized))
        return self.output(self.dropout(hidden)).squeeze(-1)


def build_compact_model(model_family: str, feature_dimension: int) -> CompactMLPSimilarityScorer:
    try:
        hidden_dimension = HIDDEN_DIMENSIONS[model_family]
    except KeyError as exc:
        raise ValueError(f"unsupported LR-3R model family: {model_family}") from exc
    return CompactMLPSimilarityScorer(feature_dimension, hidden_dimension, dropout=0.5)


def parameter_counts(model: nn.Module) -> dict[str, int]:
    return {
        "total_parameters": sum(parameter.numel() for parameter in model.parameters()),
        "trainable_parameters": sum(
            parameter.numel() for parameter in model.parameters() if parameter.requires_grad
        ),
    }
