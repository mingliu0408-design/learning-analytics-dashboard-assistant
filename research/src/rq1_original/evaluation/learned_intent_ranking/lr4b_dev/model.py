"""Thin, parity-checked wrapper around the frozen LR-3R M64 head."""

from __future__ import annotations

import sys
from typing import Any

import torch

from . import ROOT


LR3R = ROOT / "evaluation/learned_intent_ranking/lr3r"
if str(LR3R) not in sys.path:
    sys.path.insert(0, str(LR3R))

from compact_models import (  # type: ignore[import-not-found]  # noqa: E402
    CompactMLPSimilarityScorer,
    build_compact_model,
    parameter_counts,
)


FEATURE_DIMENSION = 1536
HIDDEN_DIMENSION = 64
EXPECTED_TRAINABLE_PARAMETERS = 101_505


def build_m64_model(feature_dimension: int = FEATURE_DIMENSION) -> CompactMLPSimilarityScorer:
    model = build_compact_model("M64", feature_dimension)
    counts = parameter_counts(model)
    if (
        model.feature_dimension != FEATURE_DIMENSION
        or model.hidden_dimension != HIDDEN_DIMENSION
        or model.dropout_probability != 0.5
        or counts["trainable_parameters"] != EXPECTED_TRAINABLE_PARAMETERS
    ):
        raise ValueError("frozen M64 architecture parity failed")
    expected_modules = (
        torch.nn.LayerNorm,
        torch.nn.Linear,
        torch.nn.ReLU,
        torch.nn.Dropout,
        torch.nn.Linear,
    )
    actual_modules = tuple(type(value) for value in model.children())
    if actual_modules != expected_modules:
        raise ValueError("frozen M64 module sequence drift")
    return model


def architecture_manifest() -> dict[str, Any]:
    model = build_m64_model()
    return {
        "architecture_id": "M64_LAYER_NORM_1536_64_RELU_DROPOUT_LINEAR",
        "feature_schema": "CONCAT_ABSOLUTE_DIFFERENCE_AND_ELEMENTWISE_PRODUCT",
        "feature_dimension": FEATURE_DIMENSION,
        "hidden_dimension": HIDDEN_DIMENSION,
        "dropout": 0.5,
        "trainable_parameter_count": parameter_counts(model)["trainable_parameters"],
        "frozen_lr3r_wrapper": True,
    }
