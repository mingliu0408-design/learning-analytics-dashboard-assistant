"""R2V2-B3: three deterministic L2 Logistic Regression OvR classifiers."""

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
from .errors import DevelopmentDataError, ModelStateError
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


MODEL_ID = "R2V2-B3_OVR"
STATE_SCHEMA_VERSION = "rq2-v2-track-c-b3-ovr-state-v2"


def _validate_class_weight(
    class_weight: str | Mapping[int | bool, float] | None,
) -> str | dict[int, float] | None:
    if class_weight is None or class_weight == "balanced":
        return class_weight
    if isinstance(class_weight, str):
        raise ValueError("class_weight string must be 'balanced'")
    if not isinstance(class_weight, Mapping):
        raise ValueError("class_weight must be None, 'balanced', or a binary mapping")
    result: dict[int, float] = {}
    for key, value in class_weight.items():
        integer_key = int(key)
        numeric_value = float(value)
        if integer_key not in {0, 1} or not math.isfinite(numeric_value) or numeric_value <= 0:
            raise ValueError("class_weight must contain positive weights for classes 0/1")
        result[integer_key] = numeric_value
    if set(result) != {0, 1}:
        raise ValueError("class_weight mapping must contain classes 0 and 1")
    return result


class OvRLogisticRouter:
    """One independent L2-regularised binary classifier per capability."""

    model_id = MODEL_ID

    def __init__(
        self,
        embedding_adapter: EmbeddingAdapter,
        *,
        thresholds: Mapping[str, float] | None = None,
        regularization_c: float = 1.0,
        random_seed: int = 20260830,
        class_weight: str | Mapping[int | bool, float] | None = None,
        max_iter: int = 1000,
        tolerance: float = 1e-8,
    ) -> None:
        if not math.isfinite(float(regularization_c)) or regularization_c <= 0:
            raise ValueError("regularization_c must be finite and positive")
        if max_iter < 1:
            raise ValueError("max_iter must be positive")
        if not math.isfinite(float(tolerance)) or tolerance <= 0:
            raise ValueError("tolerance must be finite and positive")
        self.embedding_adapter = embedding_adapter
        self.thresholds = validate_thresholds(
            thresholds, default=0.5, minimum=0.0, maximum=1.0
        )
        self.regularization_c = float(regularization_c)
        self.random_seed = int(random_seed)
        self.class_weight = _validate_class_weight(class_weight)
        self.max_iter = int(max_iter)
        self.tolerance = float(tolerance)
        self._coefficients: dict[str, np.ndarray] | None = None
        self._intercepts: dict[str, float] | None = None
        self._training_counts: dict[str, dict[str, int]] | None = None

    @property
    def fitted(self) -> bool:
        return self._coefficients is not None

    @property
    def coefficients(self) -> dict[str, np.ndarray]:
        self._require_fitted()
        assert self._coefficients is not None
        return {label: value.copy() for label, value in self._coefficients.items()}

    @property
    def intercepts(self) -> dict[str, float]:
        self._require_fitted()
        assert self._intercepts is not None
        return dict(self._intercepts)

    def _require_fitted(self) -> None:
        if self._coefficients is None or self._intercepts is None:
            raise ModelStateError("R2V2-B3_OVR is not fitted")

    def fit(self, cases: Sequence[Mapping[str, Any]]) -> "OvRLogisticRouter":
        rows = validate_development_cases(cases)
        labels = development_label_matrix(rows)
        assert_non_degenerate_labels(labels, context=MODEL_ID)
        embeddings = encode_case_batch(self.embedding_adapter, rows)
        try:
            from sklearn.linear_model import LogisticRegression
        except (ImportError, ModuleNotFoundError) as exc:
            raise DevelopmentDataError("scikit-learn is required for R2V2-B3_OVR") from exc

        coefficients: dict[str, np.ndarray] = {}
        intercepts: dict[str, float] = {}
        counts: dict[str, dict[str, int]] = {}
        for position, label in enumerate(CAPABILITIES):
            target = labels[:, position].astype(np.int8)
            classifier = LogisticRegression(
                C=self.regularization_c,
                # scikit-learn 1.9 expresses pure L2 as l1_ratio=0.0;
                # explicitly passing penalty="l2" is deprecated there.
                l1_ratio=0.0,
                solver="liblinear",
                class_weight=self.class_weight,
                random_state=self.random_seed,
                max_iter=self.max_iter,
                tol=self.tolerance,
                fit_intercept=True,
            )
            classifier.fit(embeddings, target)
            if tuple(int(value) for value in classifier.classes_.tolist()) != (0, 1):
                raise ModelStateError(f"unexpected learned class order for {label}")
            coefficient = np.asarray(classifier.coef_[0], dtype=np.float64)
            intercept = float(classifier.intercept_[0])
            if coefficient.shape != (embeddings.shape[1],) or not np.isfinite(coefficient).all():
                raise ModelStateError(f"invalid learned coefficient for {label}")
            if not math.isfinite(intercept):
                raise ModelStateError(f"invalid learned intercept for {label}")
            coefficients[label] = coefficient
            intercepts[label] = intercept
            counts[label] = {
                "positive": int(np.sum(target == 1)),
                "negative": int(np.sum(target == 0)),
            }
        self._coefficients = coefficients
        self._intercepts = intercepts
        self._training_counts = counts
        return self

    @staticmethod
    def _sigmoid(values: np.ndarray) -> np.ndarray:
        result = np.empty_like(values, dtype=np.float64)
        positive = values >= 0
        result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
        exponential = np.exp(values[~positive])
        result[~positive] = exponential / (1.0 + exponential)
        return result

    def _probability_rows(self, embeddings: np.ndarray) -> list[dict[str, float]]:
        self._require_fitted()
        assert self._coefficients is not None
        assert self._intercepts is not None
        columns = {
            label: self._sigmoid(
                embeddings @ self._coefficients[label] + self._intercepts[label]
            )
            for label in CAPABILITIES
        }
        return [
            {label: float(columns[label][row]) for label in CAPABILITIES}
            for row in range(embeddings.shape[0])
        ]

    def predict_proba(
        self,
        cases: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> dict[str, float] | list[dict[str, float]]:
        rows, single = coerce_case_batch(cases)
        probabilities = self._probability_rows(
            encode_case_batch(self.embedding_adapter, rows)
        )
        return probabilities[0] if single else probabilities

    def predict(
        self,
        cases: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        rows, single = coerce_case_batch(cases)
        probabilities = self._probability_rows(
            encode_case_batch(self.embedding_adapter, rows)
        )
        predictions = []
        for case, values in zip(rows, probabilities, strict=True):
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
                    value_kind="positive_probabilities",
                )
            )
        return predictions[0] if single else predictions

    def _serializable_class_weight(self) -> str | dict[str, float] | None:
        if isinstance(self.class_weight, dict):
            return {str(key): float(value) for key, value in self.class_weight.items()}
        return self.class_weight

    def save(self, path: str | Path) -> None:
        self._require_fitted()
        assert self._coefficients is not None
        assert self._intercepts is not None
        assert self._training_counts is not None
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            **state_header(self.embedding_adapter, model_id=MODEL_ID),
            "thresholds": dict(self.thresholds),
            "regularization_c": self.regularization_c,
            "random_seed": self.random_seed,
            "class_weight": self._serializable_class_weight(),
            "max_iter": self.max_iter,
            "tolerance": self.tolerance,
            "coefficients": {
                label: self._coefficients[label].tolist() for label in CAPABILITIES
            },
            "intercepts": dict(self._intercepts),
            "training_counts": self._training_counts,
        }
        save_json_state(path, state)

    @classmethod
    def load(
        cls,
        path: str | Path,
        embedding_adapter: EmbeddingAdapter,
    ) -> "OvRLogisticRouter":
        state = load_json_state(path)
        if state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ModelStateError("unsupported B3 OvR state schema")
        dimension = validate_state_header(
            state, embedding_adapter, expected_model_id=MODEL_ID
        )
        try:
            class_weight_value = state.get("class_weight")
            if isinstance(class_weight_value, Mapping):
                class_weight: str | dict[int, float] | None = {
                    int(key): float(value)
                    for key, value in class_weight_value.items()
                }
            else:
                class_weight = class_weight_value
            router = cls(
                embedding_adapter,
                thresholds=state["thresholds"],
                regularization_c=float(state["regularization_c"]),
                random_seed=int(state["random_seed"]),
                class_weight=class_weight,
                max_iter=int(state["max_iter"]),
                tolerance=float(state["tolerance"]),
            )
            coefficients = {
                label: np.asarray(state["coefficients"][label], dtype=np.float64)
                for label in CAPABILITIES
            }
            intercepts = {
                label: float(state["intercepts"][label]) for label in CAPABILITIES
            }
            training_counts = {
                label: {
                    "positive": int(state["training_counts"][label]["positive"]),
                    "negative": int(state["training_counts"][label]["negative"]),
                }
                for label in CAPABILITIES
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelStateError("malformed B3 OvR state") from exc
        for label in CAPABILITIES:
            if (
                coefficients[label].shape != (dimension,)
                or not np.isfinite(coefficients[label]).all()
                or not math.isfinite(intercepts[label])
            ):
                raise ModelStateError(f"invalid saved B3 parameters for {label}")
            if training_counts[label]["positive"] < 1 or training_counts[label]["negative"] < 1:
                raise ModelStateError(f"invalid saved training counts for {label}")
        router._coefficients = coefficients
        router._intercepts = intercepts
        router._training_counts = training_counts
        return router
