"""Research-only LR-3 learned similarity heads."""

from __future__ import annotations

import torch
from torch import nn


class LinearSimilarityScorer(nn.Module):
    model_family = "L1"

    def __init__(self, feature_dimension: int) -> None:
        super().__init__()
        self.feature_dimension = int(feature_dimension)
        self.layer_norm = nn.LayerNorm(self.feature_dimension)
        self.output = nn.Linear(self.feature_dimension, 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.output(self.layer_norm(features)).squeeze(-1)


class MLPSimilarityScorer(nn.Module):
    model_family = "M1"

    def __init__(self, feature_dimension: int, dropout: float = 0.5) -> None:
        super().__init__()
        self.feature_dimension = int(feature_dimension)
        self.hidden_dimension = self.feature_dimension // 2
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


def build_model(model_family: str, feature_dimension: int) -> nn.Module:
    if model_family == "L1":
        return LinearSimilarityScorer(feature_dimension)
    if model_family == "M1":
        return MLPSimilarityScorer(feature_dimension, dropout=0.5)
    raise ValueError(f"unsupported model family: {model_family}")


def parameter_counts(model: nn.Module) -> dict[str, int]:
    return {
        "total_parameters": sum(parameter.numel() for parameter in model.parameters()),
        "trainable_parameters": sum(
            parameter.numel() for parameter in model.parameters() if parameter.requires_grad
        ),
    }

