"""Isolated RQ2-V2 Stage 1 Track C prototype and OvR routers."""

from __future__ import annotations

from .canonical_text import (
    PRIMARY_FEATURE_FIELDS,
    PRIMARY_FEATURE_PROFILE,
    SERIALIZER_VERSION,
    serialize_canonical_batch,
    serialize_canonical_text,
)
from .development import (
    LEARNING_CURVE_SAMPLING_METHOD,
    assert_family_never_crosses_folds,
    compare_core_and_synthetic_augmentation,
    deterministic_stratified_family_order,
    evaluate_with_stage0_metrics,
    grouped_cross_validation_splits,
    run_learning_curve,
    search_per_label_thresholds,
)
from .embeddings import FrozenMpnetEmbeddingAdapter
from .ovr_router import OvRLogisticRouter
from .prototype_router import PrototypeRouter


__all__ = [
    "FrozenMpnetEmbeddingAdapter",
    "LEARNING_CURVE_SAMPLING_METHOD",
    "OvRLogisticRouter",
    "PRIMARY_FEATURE_FIELDS",
    "PRIMARY_FEATURE_PROFILE",
    "PrototypeRouter",
    "SERIALIZER_VERSION",
    "assert_family_never_crosses_folds",
    "compare_core_and_synthetic_augmentation",
    "deterministic_stratified_family_order",
    "evaluate_with_stage0_metrics",
    "grouped_cross_validation_splits",
    "run_learning_curve",
    "search_per_label_thresholds",
    "serialize_canonical_batch",
    "serialize_canonical_text",
]
