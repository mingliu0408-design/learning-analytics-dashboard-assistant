"""R2V2-B2: positive-minus-negative capability prototype router."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from pathlib import Path
from typing import Any

import numpy as np

from .development import (
    assert_non_degenerate_labels,
    development_label_matrix,
    validate_development_cases,
)
from .embeddings import EmbeddingAdapter
from .errors import DegenerateLabelError, ModelStateError
from .router_common import (
    CAPABILITIES,
    coerce_case_batch,
    encode_case_batch,
    load_json_state,
    prediction_record,
    save_json_state,
    state_header,
    validate_state_header,
    validate_thresholds,
)


MODEL_ID = "R2V2-B2_PROTOTYPE"
STATE_SCHEMA_VERSION = "rq2-v2-track-c-b2-prototype-state-v2"


class PrototypeRouter:
    """Independent binary prototypes over one shared frozen text embedding."""

    model_id = MODEL_ID

    def __init__(
        self,
        embedding_adapter: EmbeddingAdapter,
        *,
        thresholds: Mapping[str, float] | None = None,
    ) -> None:
        self.embedding_adapter = embedding_adapter
        self.thresholds = validate_thresholds(
            thresholds, default=0.0, minimum=-2.0, maximum=2.0
        )
        self._positive_prototypes: dict[str, np.ndarray] | None = None
        self._negative_prototypes: dict[str, np.ndarray] | None = None
        self._training_counts: dict[str, dict[str, int]] | None = None

    @property
    def fitted(self) -> bool:
        return self._positive_prototypes is not None

    @property
    def positive_prototypes(self) -> dict[str, np.ndarray]:
        self._require_fitted()
        assert self._positive_prototypes is not None
        return {label: value.copy() for label, value in self._positive_prototypes.items()}

    @property
    def negative_prototypes(self) -> dict[str, np.ndarray]:
        self._require_fitted()
        assert self._negative_prototypes is not None
        return {label: value.copy() for label, value in self._negative_prototypes.items()}

    def _require_fitted(self) -> None:
        if self._positive_prototypes is None or self._negative_prototypes is None:
            raise ModelStateError("R2V2-B2_PROTOTYPE is not fitted")

    def fit(self, cases: Sequence[Mapping[str, Any]]) -> "PrototypeRouter":
        rows = validate_development_cases(cases)
        labels = development_label_matrix(rows)
        assert_non_degenerate_labels(labels, context=MODEL_ID)
        embeddings = encode_case_batch(self.embedding_adapter, rows)
        positive: dict[str, np.ndarray] = {}
        negative: dict[str, np.ndarray] = {}
        counts: dict[str, dict[str, int]] = {}
        for position, label in enumerate(CAPABILITIES):
            mask = labels[:, position].astype(bool)
            positive_value = np.mean(embeddings[mask], axis=0, dtype=np.float64)
            negative_value = np.mean(embeddings[~mask], axis=0, dtype=np.float64)
            positive_norm = float(np.linalg.norm(positive_value))
            negative_norm = float(np.linalg.norm(negative_value))
            if positive_norm <= 0.0 or negative_norm <= 0.0:
                raise DegenerateLabelError(
                    f"{MODEL_ID}: {label} produced a zero-norm "
                    f"{'positive' if positive_norm <= 0.0 else 'negative'} prototype"
                )
            positive[label] = positive_value
            negative[label] = negative_value
            counts[label] = {
                "positive": int(np.sum(mask)),
                "negative": int(np.sum(~mask)),
            }
        self._positive_prototypes = positive
        self._negative_prototypes = negative
        self._training_counts = counts
        return self

    @staticmethod
    def _cosine_rows(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
        row_norms = np.linalg.norm(matrix, axis=1)
        vector_norm = float(np.linalg.norm(vector))
        if vector_norm <= 0.0 or np.any(row_norms <= 0.0):
            raise ModelStateError("cosine scoring encountered a zero-norm vector")
        return (matrix @ vector) / (row_norms * vector_norm)

    def _score_rows(self, embeddings: np.ndarray) -> list[dict[str, float]]:
        self._require_fitted()
        assert self._positive_prototypes is not None
        assert self._negative_prototypes is not None
        columns: dict[str, np.ndarray] = {}
        for label in CAPABILITIES:
            positive_cosine = self._cosine_rows(
                embeddings, self._positive_prototypes[label]
            )
            negative_cosine = self._cosine_rows(
                embeddings, self._negative_prototypes[label]
            )
            columns[label] = positive_cosine - negative_cosine
        return [
            {label: float(columns[label][row]) for label in CAPABILITIES}
            for row in range(embeddings.shape[0])
        ]

    def predict_scores(
        self,
        cases: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> dict[str, float] | list[dict[str, float]]:
        rows, single = coerce_case_batch(cases)
        scores = self._score_rows(encode_case_batch(self.embedding_adapter, rows))
        return scores[0] if single else scores

    def predict(
        self,
        cases: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        rows, single = coerce_case_batch(cases)
        scores = self._score_rows(encode_case_batch(self.embedding_adapter, rows))
        predictions = []
        for case, values in zip(rows, scores, strict=True):
            decisions = {
                label: values[label] >= self.thresholds[label]
                for label in CAPABILITIES
            }
            predictions.append(
                prediction_record(
                    case=case,
                    model_id=MODEL_ID,
                    decisions=decisions,
                    values=values,
                    thresholds=self.thresholds,
                    value_kind="prototype_scores",
                )
            )
        return predictions[0] if single else predictions

    def save(self, path: str | Path) -> None:
        self._require_fitted()
        assert self._positive_prototypes is not None
        assert self._negative_prototypes is not None
        assert self._training_counts is not None
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            **state_header(self.embedding_adapter, model_id=MODEL_ID),
            "thresholds": dict(self.thresholds),
            "positive_prototypes": {
                label: self._positive_prototypes[label].tolist()
                for label in CAPABILITIES
            },
            "negative_prototypes": {
                label: self._negative_prototypes[label].tolist()
                for label in CAPABILITIES
            },
            "training_counts": self._training_counts,
        }
        save_json_state(path, state)

    @classmethod
    def load(
        cls,
        path: str | Path,
        embedding_adapter: EmbeddingAdapter,
    ) -> "PrototypeRouter":
        state = load_json_state(path)
        if state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ModelStateError("unsupported B2 prototype state schema")
        dimension = validate_state_header(
            state, embedding_adapter, expected_model_id=MODEL_ID
        )
        try:
            router = cls(embedding_adapter, thresholds=state["thresholds"])
            positive = {
                label: np.asarray(state["positive_prototypes"][label], dtype=np.float64)
                for label in CAPABILITIES
            }
            negative = {
                label: np.asarray(state["negative_prototypes"][label], dtype=np.float64)
                for label in CAPABILITIES
            }
            training_counts = {
                label: {
                    "positive": int(state["training_counts"][label]["positive"]),
                    "negative": int(state["training_counts"][label]["negative"]),
                }
                for label in CAPABILITIES
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelStateError("malformed B2 prototype state") from exc
        for label in CAPABILITIES:
            for kind, vector in (("positive", positive[label]), ("negative", negative[label])):
                if (
                    vector.shape != (dimension,)
                    or not np.isfinite(vector).all()
                    or math.isclose(float(np.linalg.norm(vector)), 0.0, abs_tol=0.0)
                ):
                    raise ModelStateError(
                        f"invalid saved {kind} prototype for {label}"
                    )
            if training_counts[label]["positive"] < 1 or training_counts[label]["negative"] < 1:
                raise ModelStateError(f"invalid saved training counts for {label}")
        router._positive_prototypes = positive
        router._negative_prototypes = negative
        router._training_counts = training_counts
        return router
