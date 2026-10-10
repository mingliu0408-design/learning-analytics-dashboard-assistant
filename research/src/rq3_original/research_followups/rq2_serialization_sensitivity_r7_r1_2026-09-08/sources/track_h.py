"""Deterministic DEV-only research utilities for R2V2-B2 and R2V2-B3.

This module deliberately has no provider integration and no fallback model
resolution.  The sentence encoder is loaded from one absolute, frozen local
revision while network sockets are blocked.  IDs and audit metadata are used
only to preserve grouping and report results; the serializer exposes exactly
the four frozen semantic fields.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import socket
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Keep all numerical libraries single-threaded for reproducible small-data work.
for _thread_variable in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_thread_variable, "1")

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parent
DEV_PROTOCOL_ROOT = PACKAGE_ROOT.parent / "dev_protocol"

FEATURE_PROFILE = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
SERIALIZER_VERSION = "R2V2_PRIMARY_SEMANTIC_INPUT_V1_SERIALIZER_V1"
SEMANTIC_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
FORBIDDEN_SERIALIZED_FIELDS = (
    "annotation_case_id",
    "scenario_family_id",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "fold_id",
    "fold_role",
    "partition",
    "final_dialogue_action",
    "final_routing_signature",
    "final_rag_required",
    "final_memory_required",
    "final_planning_required",
    "final_naturalness",
    "writer_id",
)

ENCODER_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
ENCODER_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
ENCODER_DIMENSION = 768
ENCODER_PATH = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/"
    "semantic_runtime/models/all-mpnet-base-v2/"
    + ENCODER_REVISION
)

CAPABILITIES = ("RAG", "Memory", "Planning")
LABEL_FIELDS = (
    "final_rag_required",
    "final_memory_required",
    "final_planning_required",
)
FOLD_IDS = tuple(f"DEV-CV-FOLD-{number}" for number in range(1, 5))
RANDOM_STATE = 20260831

EXPECTED_SOURCE_HASHES = {
    "dev_capability_gold_v1.csv": (
        "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56"
    ),
    "dev_atomic_group_map_v1.csv": (
        "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f"
    ),
    "dev_cv_folds_v1.csv": (
        "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46"
    ),
    "stage4_dev_protocol_v1.json": (
        "9e4e8afa354f544d58d6d30187af194e52968df5ec21ccbdcb7f6585adb75336"
    ),
}


class ContractError(RuntimeError):
    """Raised when a frozen source or scientific contract is violated."""


class DegenerateLabelError(ContractError):
    """Raised when a training or calibration population has one label class."""


@dataclass(frozen=True)
class DevDataset:
    """The 64 authorized ANSWER cases plus audit-only grouping metadata."""

    rows: tuple[dict[str, str], ...]
    serialized_texts: tuple[str, ...]
    y: np.ndarray
    fold_ids: np.ndarray

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(row["annotation_case_id"] for row in self.rows)

    @property
    def size(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class B3Config:
    config_id: str
    C: float
    class_weight: str | None

    @property
    def simplicity_key(self) -> tuple[float, int, str]:
        return (self.C, 0 if self.class_weight is None else 1, self.config_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "C": self.C,
            "class_weight": self.class_weight,
            "penalty": "l2",
            "solver": "liblinear",
            "random_state": RANDOM_STATE,
            "max_iter": 5000,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_hashes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected in EXPECTED_SOURCE_HASHES.items():
        path = DEV_PROTOCOL_ROOT / name
        if not path.is_file():
            raise ContractError(f"missing frozen DEV source: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ContractError(
                f"frozen DEV source hash mismatch for {name}: {actual} != {expected}"
            )
        observed[name] = actual
    return observed


def canonical_history(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError("visible_conversation_history is not valid JSON") from exc
    if not isinstance(value, list):
        raise ContractError("visible_conversation_history must be a list")
    canonical: list[dict[str, Any]] = []
    for message in value:
        if not isinstance(message, Mapping):
            raise ContractError("each visible history item must be an object")
        canonical.append({key: message[key] for key in sorted(message)})
    return canonical


def serialize_semantic_input(row: Mapping[str, Any]) -> str:
    """Serialize exactly the four frozen semantic fields as canonical JSON."""

    missing = [field for field in SEMANTIC_FIELDS if field not in row]
    if missing:
        raise ContractError(f"missing frozen semantic fields: {missing}")
    payload = {
        "current_query": str(row["current_query"]),
        "current_page": str(row["current_page"]),
        "dashboard_context": str(row["dashboard_context"]),
        "visible_conversation_history": canonical_history(
            row["visible_conversation_history"]
        ),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    decoded = json.loads(serialized)
    if tuple(decoded) != SEMANTIC_FIELDS:
        raise ContractError("serializer field order or membership changed")
    return serialized


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_answer_dataset() -> DevDataset:
    """Load only the frozen ANSWER population and attach audit-only metadata."""

    verify_source_hashes()
    gold_rows = _read_csv(DEV_PROTOCOL_ROOT / "dev_capability_gold_v1.csv")
    group_rows = _read_csv(DEV_PROTOCOL_ROOT / "dev_atomic_group_map_v1.csv")
    fold_rows = _read_csv(DEV_PROTOCOL_ROOT / "dev_cv_folds_v1.csv")

    if len(gold_rows) != 72:
        raise ContractError(f"expected 72 DEV rows, observed {len(gold_rows)}")
    if {row["partition"] for row in gold_rows} != {"DEV"}:
        raise ContractError("non-DEV partition found in sanitized DEV source")
    if sum(row["final_dialogue_action"] == "ANSWER" for row in gold_rows) != 64:
        raise ContractError("expected exactly 64 ANSWER utterances")

    group_by_id = {row["annotation_case_id"]: row for row in group_rows}
    if len(group_by_id) != 72:
        raise ContractError("group map must contain 72 unique DEV case IDs")
    validation_fold_by_id: dict[str, str] = {}
    for row in fold_rows:
        if row["fold_role"] == "VALIDATION":
            case_id = row["annotation_case_id"]
            if case_id in validation_fold_by_id:
                raise ContractError(f"multiple validation folds for {case_id}")
            validation_fold_by_id[case_id] = row["fold_id"]
    if len(validation_fold_by_id) != 72:
        raise ContractError("every DEV case must have exactly one validation fold")

    answer_rows: list[dict[str, str]] = []
    for gold in gold_rows:
        if gold["final_dialogue_action"] != "ANSWER":
            continue
        case_id = gold["annotation_case_id"]
        if case_id not in group_by_id or case_id not in validation_fold_by_id:
            raise ContractError(f"missing grouping or fold metadata for {case_id}")
        merged = dict(gold)
        merged.update(group_by_id[case_id])
        merged["fold_id"] = validation_fold_by_id[case_id]
        if merged["fold_id"] not in FOLD_IDS:
            raise ContractError(f"unexpected fold ID for {case_id}")
        answer_rows.append(merged)

    answer_rows.sort(key=lambda row: row["annotation_case_id"].encode("utf-8"))
    if len(answer_rows) != 64:
        raise ContractError("ANSWER-only loader did not produce 64 cases")
    if len({row["scenario_family_id"] for row in answer_rows}) != 32:
        raise ContractError("ANSWER-only loader did not produce 32 families")

    y = np.asarray(
        [
            [1 if row[field] == "YES" else 0 for field in LABEL_FIELDS]
            for row in answer_rows
        ],
        dtype=np.int8,
    )
    if np.any(np.sum(y, axis=0) != 32):
        raise ContractError("each capability must have 32 YES ANSWER utterances")
    texts = tuple(serialize_semantic_input(row) for row in answer_rows)
    return DevDataset(
        rows=tuple(answer_rows),
        serialized_texts=texts,
        y=y,
        fold_ids=np.asarray([row["fold_id"] for row in answer_rows], dtype=object),
    )


@contextmanager
def network_blocked() -> Iterable[None]:
    """Block socket connection attempts while the frozen encoder is loaded."""

    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise ContractError("network access is prohibited in RQ2-V2 Stage 4H")

    socket.create_connection = blocked  # type: ignore[assignment]
    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def embedding_matrix_hash(matrix: np.ndarray) -> str:
    canonical = np.asarray(matrix, dtype="<f4", order="C")
    return sha256_bytes(canonical.tobytes(order="C"))


def source_text_hash(texts: Sequence[str]) -> str:
    return sha256_bytes("\n".join(texts).encode("utf-8"))


def encode_frozen_texts(texts: Sequence[str]) -> tuple[np.ndarray, dict[str, Any]]:
    """Encode texts once with the exact local MPNet revision in offline mode."""

    if not ENCODER_PATH.is_dir():
        raise ContractError(f"frozen local encoder directory missing: {ENCODER_PATH}")
    for variable in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[variable] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    with network_blocked():
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            str(ENCODER_PATH),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
        )
        dimension_method = getattr(model, "get_embedding_dimension", None)
        dimension = (
            int(dimension_method())
            if dimension_method is not None
            else int(model.get_sentence_embedding_dimension())
        )
        if dimension != ENCODER_DIMENSION:
            raise ContractError(
                f"frozen encoder dimension mismatch: {dimension} != {ENCODER_DIMENSION}"
            )
        matrix = model.encode(
            list(texts),
            batch_size=16,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    matrix = np.asarray(matrix, dtype=np.float32, order="C")
    if matrix.shape != (len(texts), ENCODER_DIMENSION):
        raise ContractError(f"unexpected embedding shape: {matrix.shape}")
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1)
    if not np.allclose(norms, 1.0, atol=2e-6, rtol=0.0):
        raise ContractError("frozen embeddings are not unit-normalized")
    identity = {
        "schema_version": "rq2-v2-stage4h-dev-embedding-identity-v1",
        "model_name": ENCODER_MODEL_NAME,
        "revision": ENCODER_REVISION,
        "dimension": ENCODER_DIMENSION,
        "dtype": "float32",
        "normalization": "L2_UNIT",
        "feature_profile": FEATURE_PROFILE,
        "serializer_version": SERIALIZER_VERSION,
        "semantic_fields": list(SEMANTIC_FIELDS),
        "row_count": len(texts),
        "row_order": "annotation_case_id UTF-8 bytewise ascending (audit-only)",
        "source_text_sha256": source_text_hash(texts),
        "embedding_matrix_sha256": embedding_matrix_hash(matrix),
        "local_files_only": True,
        "network_blocked": True,
        "model_weights_committed": False,
    }
    return matrix, identity


def validate_binary_training_labels(y: np.ndarray, context: str) -> None:
    y = np.asarray(y)
    if y.ndim == 1:
        y = y[:, None]
    for column in range(y.shape[1]):
        unique = np.unique(y[:, column])
        if not np.array_equal(unique, np.asarray([0, 1])):
            name = CAPABILITIES[column] if column < len(CAPABILITIES) else str(column)
            raise DegenerateLabelError(
                f"{context} lacks a positive or negative example for {name}: {unique.tolist()}"
            )


def _binary_prf(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | int]:
    y_true = np.asarray(y_true, dtype=np.int8)
    y_pred = np.asarray(y_pred, dtype=np.int8)
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def select_threshold(scores: np.ndarray, y_true: np.ndarray) -> dict[str, Any]:
    """Select a threshold with the frozen label-level lexicographic objective."""

    scores = np.asarray(scores, dtype=np.float64)
    y_true = np.asarray(y_true, dtype=np.int8)
    if scores.ndim != 1 or y_true.ndim != 1 or len(scores) != len(y_true):
        raise ContractError("threshold inputs must be aligned one-dimensional arrays")
    validate_binary_training_labels(y_true, "threshold calibration population")
    if not np.all(np.isfinite(scores)):
        raise ContractError("threshold scores must be finite")
    unique = sorted(float(value) for value in np.unique(scores))
    candidates = unique + [float(np.nextafter(unique[-1], math.inf))]
    midpoint = (unique[0] + unique[-1]) / 2.0
    ranked: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    for threshold in candidates:
        prediction = (scores >= threshold).astype(np.int8)
        stats = _binary_prf(y_true, prediction)
        key = (
            -float(stats["f1"]),
            -float(stats["recall"]),
            -float(stats["precision"]),
            abs(threshold - midpoint),
            threshold,
        )
        ranked.append(
            (
                key,
                {
                    "threshold": threshold,
                    "f1": stats["f1"],
                    "recall": stats["recall"],
                    "precision": stats["precision"],
                    "midpoint": midpoint,
                    "distance_to_midpoint": abs(threshold - midpoint),
                    "candidate_count": len(candidates),
                },
            )
        )
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def fit_prototypes(X: np.ndarray, y: np.ndarray, context: str) -> dict[str, Any]:
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.int8)
    validate_binary_training_labels(y, context)
    positives: list[np.ndarray] = []
    negatives: list[np.ndarray] = []
    for column in range(y.shape[1]):
        positive = np.mean(X[y[:, column] == 1], axis=0)
        negative = np.mean(X[y[:, column] == 0], axis=0)
        positive_norm = float(np.linalg.norm(positive))
        negative_norm = float(np.linalg.norm(negative))
        if positive_norm == 0.0 or negative_norm == 0.0:
            raise ContractError(f"zero-norm prototype in {context}")
        positives.append(positive / positive_norm)
        negatives.append(negative / negative_norm)
    return {
        "positive": np.asarray(positives, dtype=np.float64),
        "negative": np.asarray(negatives, dtype=np.float64),
    }


def prototype_scores(X: np.ndarray, prototypes: Mapping[str, Any]) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    positive = np.asarray(prototypes["positive"], dtype=np.float64)
    negative = np.asarray(prototypes["negative"], dtype=np.float64)
    return X @ positive.T - X @ negative.T


def thresholds_from_scores(scores: np.ndarray, y: np.ndarray) -> list[dict[str, Any]]:
    return [select_threshold(scores[:, column], y[:, column]) for column in range(3)]


def apply_thresholds(scores: np.ndarray, thresholds: Sequence[Mapping[str, Any] | float]) -> np.ndarray:
    values = np.asarray(
        [
            float(item["threshold"]) if isinstance(item, Mapping) else float(item)
            for item in thresholds
        ],
        dtype=np.float64,
    )
    return (np.asarray(scores, dtype=np.float64) >= values[None, :]).astype(np.int8)


def _contrast_consistency(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        group = row.get("dev_contrast_group_id", "")
        if group:
            groups.setdefault(group, []).append(index)
    eligible = 0
    consistent = 0
    for indices in groups.values():
        families: dict[str, list[int]] = {}
        for index in indices:
            families.setdefault(rows[index]["scenario_family_id"], []).append(index)
        if len(families) != 2:
            continue
        ordered_families = sorted(families, key=lambda value: value.encode("utf-8"))
        if any(len(families[family]) != 2 for family in ordered_families):
            continue
        eligible += 1
        true_family: list[np.ndarray] = []
        pred_family: list[np.ndarray] = []
        stable = True
        for family in ordered_families:
            family_indices = families[family]
            true_values = y_true[family_indices]
            pred_values = y_pred[family_indices]
            if not np.all(true_values == true_values[0]) or not np.all(
                pred_values == pred_values[0]
            ):
                stable = False
            true_family.append(true_values[0])
            pred_family.append(pred_values[0])
        if stable:
            true_change = true_family[1].astype(int) - true_family[0].astype(int)
            pred_change = pred_family[1].astype(int) - pred_family[0].astype(int)
            if np.array_equal(true_change, pred_change):
                consistent += 1
    return {
        "eligible_groups": eligible,
        "consistent_groups": consistent,
        "rate": consistent / eligible if eligible else None,
        "definition": (
            "Both utterances must agree within each ANSWER family and the directed "
            "capability-change vector between the two families must match Gold."
        ),
    }


def compute_core_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    rows: Sequence[Mapping[str, str]],
    *,
    include_strata: bool = True,
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=np.int8)
    y_pred = np.asarray(y_pred, dtype=np.int8)
    if y_true.shape != y_pred.shape or y_true.ndim != 2 or y_true.shape[1] != 3:
        raise ContractError("metric arrays must have aligned shape (n, 3)")
    if len(rows) != len(y_true):
        raise ContractError("metric metadata must align with predictions")
    per_label = {
        capability: _binary_prf(y_true[:, column], y_pred[:, column])
        for column, capability in enumerate(CAPABILITIES)
    }
    pooled = _binary_prf(y_true.reshape(-1), y_pred.reshape(-1))
    exact_by_case = np.all(y_true == y_pred, axis=1)
    example_f1: list[float] = []
    jaccards: list[float] = []
    for truth, prediction in zip(y_true, y_pred, strict=True):
        intersection = int(np.sum((truth == 1) & (prediction == 1)))
        truth_count = int(np.sum(truth))
        prediction_count = int(np.sum(prediction))
        denom_f1 = truth_count + prediction_count
        union = int(np.sum((truth == 1) | (prediction == 1)))
        example_f1.append(2.0 * intersection / denom_f1 if denom_f1 else 1.0)
        jaccards.append(intersection / union if union else 1.0)
    under = np.any((y_true == 1) & (y_pred == 0), axis=1)
    over = np.any((y_true == 0) & (y_pred == 1), axis=1)

    family_indices: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        family_indices.setdefault(row["scenario_family_id"], []).append(index)
    malformed_families = [family for family, indices in family_indices.items() if len(indices) != 2]
    family_both = None
    family_both_count = 0
    if not malformed_families and family_indices:
        family_both_count = sum(
            bool(np.all(exact_by_case[indices])) for indices in family_indices.values()
        )
        family_both = family_both_count / len(family_indices)

    result: dict[str, Any] = {
        "case_count": len(y_true),
        "family_count": len(family_indices),
        "macro_f1": float(np.mean([per_label[name]["f1"] for name in CAPABILITIES])),
        "micro_f1": pooled["f1"],
        "per_label": per_label,
        "exact_capability_set_match": float(np.mean(exact_by_case)),
        "exact_case_count": int(np.sum(exact_by_case)),
        "example_based_f1": float(np.mean(example_f1)),
        "jaccard": float(np.mean(jaccards)),
        "hamming_loss": float(np.mean(y_true != y_pred)),
        "under_routing_rate": float(np.mean(under)),
        "under_routed_case_count": int(np.sum(under)),
        "over_routing_rate": float(np.mean(over)),
        "over_routed_case_count": int(np.sum(over)),
        "family_both_utterances_correct_rate": family_both,
        "family_both_utterances_correct_count": family_both_count,
        "family_both_utterances_denominator": len(family_indices),
        "malformed_family_count": len(malformed_families),
        "contrast_consistency": _contrast_consistency(y_true, y_pred, rows),
    }
    if include_strata:
        page_metrics: dict[str, Any] = {}
        for page in sorted({row["current_page"] for row in rows}):
            indices = [i for i, row in enumerate(rows) if row["current_page"] == page]
            page_metrics[page] = compute_core_metrics(
                y_true[indices],
                y_pred[indices],
                [rows[i] for i in indices],
                include_strata=False,
            )
        result["page_stratified_metrics"] = page_metrics
        result["writer_a_b_metrics"] = {
            "status": "NOT_EVALUABLE",
            "reason": (
                "Writer identity is intentionally absent from the authorized sanitized DEV "
                "protocol, and no external audit-only writer join was authorized."
            ),
        }
    return result


def b2_outer_fold(
    X: np.ndarray,
    y: np.ndarray,
    fold_ids: np.ndarray,
    outer_fold: str,
) -> dict[str, Any]:
    """Run one B2 outer fold without reading outer-validation labels."""

    outer_train = np.flatnonzero(fold_ids != outer_fold)
    outer_validation = np.flatnonzero(fold_ids == outer_fold)
    inner_folds = [fold for fold in FOLD_IDS if fold != outer_fold]
    inner_scores = np.full((len(X), 3), np.nan, dtype=np.float64)
    for inner_validation_fold in inner_folds:
        inner_training = np.flatnonzero(
            (fold_ids != outer_fold) & (fold_ids != inner_validation_fold)
        )
        inner_validation = np.flatnonzero(fold_ids == inner_validation_fold)
        prototypes = fit_prototypes(
            X[inner_training],
            y[inner_training],
            f"B2 outer={outer_fold} inner={inner_validation_fold}",
        )
        inner_scores[inner_validation] = prototype_scores(X[inner_validation], prototypes)
    if np.any(~np.isfinite(inner_scores[outer_train])):
        raise ContractError(f"incomplete B2 inner OOF scores for {outer_fold}")
    thresholds = thresholds_from_scores(inner_scores[outer_train], y[outer_train])
    outer_prototypes = fit_prototypes(
        X[outer_train], y[outer_train], f"B2 outer training {outer_fold}"
    )
    validation_scores = prototype_scores(X[outer_validation], outer_prototypes)
    validation_predictions = apply_thresholds(validation_scores, thresholds)
    return {
        "outer_fold": outer_fold,
        "outer_train_indices": outer_train,
        "outer_validation_indices": outer_validation,
        "inner_oof_scores": inner_scores[outer_train],
        "inner_oof_indices": outer_train,
        "thresholds": thresholds,
        "outer_prototypes": outer_prototypes,
        "validation_scores": validation_scores,
        "validation_predictions": validation_predictions,
    }


def nested_b2(X: np.ndarray, dataset: DevDataset) -> dict[str, Any]:
    scores = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    predictions = np.full((dataset.size, 3), -1, dtype=np.int8)
    threshold_by_case = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    fold_calibrations: list[dict[str, Any]] = []
    for outer_fold in FOLD_IDS:
        result = b2_outer_fold(X, dataset.y, dataset.fold_ids, outer_fold)
        indices = result["outer_validation_indices"]
        scores[indices] = result["validation_scores"]
        predictions[indices] = result["validation_predictions"]
        threshold_values = [item["threshold"] for item in result["thresholds"]]
        threshold_by_case[indices] = np.asarray(threshold_values)[None, :]
        fold_calibrations.append(
            {
                "outer_fold": outer_fold,
                "outer_training_case_count": len(result["outer_train_indices"]),
                "outer_validation_case_count": len(indices),
                "inner_folds": [fold for fold in FOLD_IDS if fold != outer_fold],
                "thresholds": {
                    capability: result["thresholds"][column]
                    for column, capability in enumerate(CAPABILITIES)
                },
            }
        )
    if np.any(~np.isfinite(scores)) or np.any(predictions < 0):
        raise ContractError("incomplete nested B2 OOF result")
    return {
        "scores": scores,
        "predictions": predictions,
        "threshold_by_case": threshold_by_case,
        "fold_calibrations": fold_calibrations,
        "metrics": compute_core_metrics(dataset.y, predictions, dataset.rows),
    }


def full_dev_b2(X: np.ndarray, dataset: DevDataset) -> dict[str, Any]:
    oof_scores = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    for outer_fold in FOLD_IDS:
        training = np.flatnonzero(dataset.fold_ids != outer_fold)
        validation = np.flatnonzero(dataset.fold_ids == outer_fold)
        prototypes = fit_prototypes(
            X[training], dataset.y[training], f"B2 ordinary OOF {outer_fold}"
        )
        oof_scores[validation] = prototype_scores(X[validation], prototypes)
    if np.any(~np.isfinite(oof_scores)):
        raise ContractError("incomplete full-DEV B2 OOF scores")
    thresholds = thresholds_from_scores(oof_scores, dataset.y)
    diagnostic_predictions = apply_thresholds(oof_scores, thresholds)
    final_prototypes = fit_prototypes(X, dataset.y, "B2 full DEV fit")
    return {
        "oof_scores": oof_scores,
        "thresholds": thresholds,
        "diagnostic_predictions": diagnostic_predictions,
        "diagnostic_metrics": compute_core_metrics(
            dataset.y, diagnostic_predictions, dataset.rows
        ),
        "final_prototypes": final_prototypes,
    }


def b3_candidate_grid() -> tuple[B3Config, ...]:
    candidates: list[B3Config] = []
    for C in (0.01, 0.1, 1.0, 10.0):
        token = str(C).replace(".", "p")
        for class_weight in (None, "balanced"):
            weight_token = "NONE" if class_weight is None else "BALANCED"
            candidates.append(
                B3Config(
                    config_id=f"B3_C_{token}_CW_{weight_token}",
                    C=C,
                    class_weight=class_weight,
                )
            )
    return tuple(candidates)


def fit_ovr(X: np.ndarray, y: np.ndarray, config: B3Config, context: str) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.int8)
    validate_binary_training_labels(y, context)
    coefficients: list[np.ndarray] = []
    intercepts: list[float] = []
    iterations: list[int] = []
    for column, capability in enumerate(CAPABILITIES):
        estimator = LogisticRegression(
            C=config.C,
            class_weight=config.class_weight,
            penalty="l2",
            solver="liblinear",
            random_state=RANDOM_STATE,
            max_iter=5000,
            tol=1e-8,
            fit_intercept=True,
        )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="'penalty' was deprecated.*",
                category=FutureWarning,
                module=r"sklearn\.linear_model\._logistic",
            )
            estimator.fit(X, y[:, column])
        if not np.array_equal(estimator.classes_, np.asarray([0, 1])):
            raise ContractError(f"unexpected B3 classes for {capability} in {context}")
        if int(estimator.n_iter_[0]) >= 5000:
            raise ContractError(f"B3 failed to converge for {capability} in {context}")
        coefficients.append(np.asarray(estimator.coef_[0], dtype=np.float64))
        intercepts.append(float(estimator.intercept_[0]))
        iterations.append(int(estimator.n_iter_[0]))
    return {
        "config": config,
        "coefficients": np.asarray(coefficients, dtype=np.float64),
        "intercepts": np.asarray(intercepts, dtype=np.float64),
        "iterations": iterations,
    }


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    result = np.empty_like(values)
    positive = values >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result


def predict_ovr_probabilities(X: np.ndarray, model: Mapping[str, Any]) -> np.ndarray:
    coefficients = np.asarray(model["coefficients"], dtype=np.float64)
    intercepts = np.asarray(model["intercepts"], dtype=np.float64)
    return sigmoid(np.asarray(X, dtype=np.float64) @ coefficients.T + intercepts[None, :])


def _candidate_selection_key(metrics: Mapping[str, Any], config: B3Config) -> tuple[Any, ...]:
    return (
        -float(metrics["macro_f1"]),
        -float(metrics["exact_capability_set_match"]),
        -float(metrics["jaccard"]),
        float(metrics["under_routing_rate"]),
        float(metrics["over_routing_rate"]),
        config.simplicity_key,
        config.config_id.encode("utf-8"),
    )


def select_b3_candidate(candidate_results: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not candidate_results:
        raise ContractError("cannot select from an empty B3 candidate list")
    return min(
        candidate_results,
        key=lambda result: _candidate_selection_key(
            result["metrics"], result["config"]
        ),
    )


def _b3_inner_oof_for_config(
    X: np.ndarray,
    y: np.ndarray,
    fold_ids: np.ndarray,
    outer_fold: str,
    config: B3Config,
) -> tuple[np.ndarray, np.ndarray]:
    outer_training = np.flatnonzero(fold_ids != outer_fold)
    probabilities = np.full((len(X), 3), np.nan, dtype=np.float64)
    for inner_validation_fold in (fold for fold in FOLD_IDS if fold != outer_fold):
        inner_training = np.flatnonzero(
            (fold_ids != outer_fold) & (fold_ids != inner_validation_fold)
        )
        inner_validation = np.flatnonzero(fold_ids == inner_validation_fold)
        model = fit_ovr(
            X[inner_training],
            y[inner_training],
            config,
            f"B3 {config.config_id} outer={outer_fold} inner={inner_validation_fold}",
        )
        probabilities[inner_validation] = predict_ovr_probabilities(
            X[inner_validation], model
        )
    if np.any(~np.isfinite(probabilities[outer_training])):
        raise ContractError(
            f"incomplete B3 inner OOF probabilities for {outer_fold} {config.config_id}"
        )
    return outer_training, probabilities[outer_training]


def b3_outer_fold(
    X: np.ndarray,
    y: np.ndarray,
    fold_ids: np.ndarray,
    rows: Sequence[Mapping[str, str]],
    outer_fold: str,
    candidates: Sequence[B3Config] | None = None,
) -> dict[str, Any]:
    """Select and apply B3 for one outer fold without reading validation labels."""

    candidates = tuple(candidates or b3_candidate_grid())
    candidate_results: list[dict[str, Any]] = []
    outer_training = np.flatnonzero(fold_ids != outer_fold)
    outer_validation = np.flatnonzero(fold_ids == outer_fold)
    for config in candidates:
        inner_indices, inner_probabilities = _b3_inner_oof_for_config(
            X, y, fold_ids, outer_fold, config
        )
        if not np.array_equal(inner_indices, outer_training):
            raise ContractError("B3 inner indices do not equal outer training complement")
        thresholds = thresholds_from_scores(inner_probabilities, y[outer_training])
        predictions = apply_thresholds(inner_probabilities, thresholds)
        metrics = compute_core_metrics(
            y[outer_training],
            predictions,
            [rows[index] for index in outer_training],
        )
        candidate_results.append(
            {
                "config": config,
                "thresholds": thresholds,
                "metrics": metrics,
                "inner_oof_probabilities": inner_probabilities,
            }
        )
    selected = select_b3_candidate(candidate_results)
    model = fit_ovr(
        X[outer_training],
        y[outer_training],
        selected["config"],
        f"B3 selected outer training {outer_fold}",
    )
    validation_probabilities = predict_ovr_probabilities(X[outer_validation], model)
    validation_predictions = apply_thresholds(
        validation_probabilities, selected["thresholds"]
    )
    return {
        "outer_fold": outer_fold,
        "outer_train_indices": outer_training,
        "outer_validation_indices": outer_validation,
        "candidate_results": candidate_results,
        "selected": selected,
        "outer_model": model,
        "validation_probabilities": validation_probabilities,
        "validation_predictions": validation_predictions,
    }


def nested_b3(X: np.ndarray, dataset: DevDataset) -> dict[str, Any]:
    probabilities = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    predictions = np.full((dataset.size, 3), -1, dtype=np.int8)
    threshold_by_case = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    fold_selections: list[dict[str, Any]] = []
    for outer_fold in FOLD_IDS:
        result = b3_outer_fold(
            X, dataset.y, dataset.fold_ids, dataset.rows, outer_fold
        )
        indices = result["outer_validation_indices"]
        probabilities[indices] = result["validation_probabilities"]
        predictions[indices] = result["validation_predictions"]
        selected = result["selected"]
        threshold_values = [item["threshold"] for item in selected["thresholds"]]
        threshold_by_case[indices] = np.asarray(threshold_values)[None, :]
        fold_selections.append(
            {
                "outer_fold": outer_fold,
                "outer_training_case_count": len(result["outer_train_indices"]),
                "outer_validation_case_count": len(indices),
                "selected_config": selected["config"].as_dict(),
                "inner_oof_metrics": selected["metrics"],
                "thresholds": {
                    capability: selected["thresholds"][column]
                    for column, capability in enumerate(CAPABILITIES)
                },
                "candidate_summaries": [
                    {
                        "config": candidate["config"].as_dict(),
                        "metrics": candidate["metrics"],
                        "thresholds": {
                            capability: candidate["thresholds"][column]
                            for column, capability in enumerate(CAPABILITIES)
                        },
                    }
                    for candidate in result["candidate_results"]
                ],
            }
        )
    if np.any(~np.isfinite(probabilities)) or np.any(predictions < 0):
        raise ContractError("incomplete nested B3 OOF result")
    return {
        "probabilities": probabilities,
        "predictions": predictions,
        "threshold_by_case": threshold_by_case,
        "fold_selections": fold_selections,
        "metrics": compute_core_metrics(dataset.y, predictions, dataset.rows),
    }


def _ordinary_b3_oof(
    X: np.ndarray,
    dataset: DevDataset,
    config: B3Config,
) -> np.ndarray:
    probabilities = np.full((dataset.size, 3), np.nan, dtype=np.float64)
    for outer_fold in FOLD_IDS:
        training = np.flatnonzero(dataset.fold_ids != outer_fold)
        validation = np.flatnonzero(dataset.fold_ids == outer_fold)
        model = fit_ovr(
            X[training],
            dataset.y[training],
            config,
            f"B3 full-DEV candidate OOF {config.config_id} {outer_fold}",
        )
        probabilities[validation] = predict_ovr_probabilities(X[validation], model)
    if np.any(~np.isfinite(probabilities)):
        raise ContractError(f"incomplete B3 full-DEV OOF for {config.config_id}")
    return probabilities


def full_dev_b3(X: np.ndarray, dataset: DevDataset) -> dict[str, Any]:
    candidate_results: list[dict[str, Any]] = []
    for config in b3_candidate_grid():
        probabilities = _ordinary_b3_oof(X, dataset, config)
        thresholds = thresholds_from_scores(probabilities, dataset.y)
        predictions = apply_thresholds(probabilities, thresholds)
        metrics = compute_core_metrics(dataset.y, predictions, dataset.rows)
        candidate_results.append(
            {
                "config": config,
                "oof_probabilities": probabilities,
                "thresholds": thresholds,
                "predictions": predictions,
                "metrics": metrics,
            }
        )
    selected = select_b3_candidate(candidate_results)
    final_model = fit_ovr(
        X, dataset.y, selected["config"], "B3 final full-DEV fit"
    )
    return {
        "candidate_results": candidate_results,
        "selected": selected,
        "final_model": final_model,
    }


def capability_signature(values: Sequence[int]) -> str:
    return "".join(str(int(value)) for value in values)


def build_error_registry(
    dataset: DevDataset,
    predictions: np.ndarray,
) -> list[dict[str, Any]]:
    registry: list[dict[str, Any]] = []
    for index, (truth, prediction) in enumerate(
        zip(dataset.y, predictions, strict=True)
    ):
        if np.array_equal(truth, prediction):
            continue
        false_negatives = [
            CAPABILITIES[column]
            for column in range(3)
            if truth[column] == 1 and prediction[column] == 0
        ]
        false_positives = [
            CAPABILITIES[column]
            for column in range(3)
            if truth[column] == 0 and prediction[column] == 1
        ]
        row = dataset.rows[index]
        registry.append(
            {
                "annotation_case_id": row["annotation_case_id"],
                "scenario_family_id": row["scenario_family_id"],
                "outer_fold": row["fold_id"],
                "current_page": row["current_page"],
                "gold_capability_signature": capability_signature(truth),
                "predicted_capability_signature": capability_signature(prediction),
                "false_negative_capabilities": "|".join(false_negatives),
                "false_positive_capabilities": "|".join(false_positives),
            }
        )
    return registry


def _component_summary(
    dataset: DevDataset,
    indices: Sequence[int],
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for index in indices:
        row = dataset.rows[index]
        component = row["dev_atomic_component_id"]
        summary = summaries.setdefault(
            component,
            {
                "indices": [],
                "families": set(),
                "signatures": {},
                "fold_id": row["fold_id"],
            },
        )
        if summary["fold_id"] != row["fold_id"]:
            raise ContractError(f"atomic component crosses folds: {component}")
        summary["indices"].append(index)
        family = row["scenario_family_id"]
        summary["families"].add(family)
        summary["signatures"][family] = row["final_family_routing_signature"]
    return summaries


def deterministic_learning_subset(
    dataset: DevDataset,
    outer_fold: str,
    fraction: float,
) -> dict[str, Any]:
    """Select complete components with deterministic signature-aware balance."""

    pool_indices = np.flatnonzero(dataset.fold_ids != outer_fold).tolist()
    components = _component_summary(dataset, pool_indices)
    component_ids = sorted(components, key=lambda value: value.encode("utf-8"))
    all_families = sorted(
        {dataset.rows[index]["scenario_family_id"] for index in pool_indices}
    )
    target_families = int(round(len(all_families) * fraction))
    if fraction == 1.0:
        selected_ids = component_ids
    else:
        full_signature_counts = {f"{value:03b}": 0 for value in range(8)}
        for family in all_families:
            family_index = next(
                index
                for index in pool_indices
                if dataset.rows[index]["scenario_family_id"] == family
            )
            signature = dataset.rows[family_index]["final_family_routing_signature"]
            full_signature_counts[signature] += 1

        sizes = [len(components[item]["families"]) for item in component_ids]
        best: tuple[tuple[Any, ...], tuple[int, ...]] | None = None
        attainable_counts = {0}
        for size in sizes:
            attainable_counts |= {count + size for count in tuple(attainable_counts)}
        possible_counts = sorted(
            (count for count in attainable_counts if count > 0),
            key=lambda value: (abs(value - target_families), value),
        )
        nearest_count = possible_counts[0]
        for length in range(1, len(component_ids) + 1):
            for combo in itertools.combinations(range(len(component_ids)), length):
                family_count = sum(sizes[index] for index in combo)
                if family_count != nearest_count:
                    continue
                selected_components = [component_ids[index] for index in combo]
                fold_family_counts = {fold: 0 for fold in FOLD_IDS if fold != outer_fold}
                signature_counts = {f"{value:03b}": 0 for value in range(8)}
                selected_indices: list[int] = []
                for component in selected_components:
                    summary = components[component]
                    fold_family_counts[summary["fold_id"]] += len(summary["families"])
                    for signature in summary["signatures"].values():
                        signature_counts[signature] += 1
                    selected_indices.extend(summary["indices"])
                degeneracy_count = 0
                for inner_fold in fold_family_counts:
                    inner_indices = [
                        index
                        for index in selected_indices
                        if dataset.rows[index]["fold_id"] != inner_fold
                    ]
                    if not inner_indices:
                        degeneracy_count += 3
                        continue
                    for column in range(3):
                        if len(np.unique(dataset.y[inner_indices, column])) < 2:
                            degeneracy_count += 1
                missing_folds = sum(count == 0 for count in fold_family_counts.values())
                signature_sse = sum(
                    (signature_counts[signature] - full_signature_counts[signature] * fraction)
                    ** 2
                    for signature in signature_counts
                )
                fold_target = nearest_count / 3.0
                fold_sse = sum(
                    (count - fold_target) ** 2 for count in fold_family_counts.values()
                )
                digest = hashlib.sha256(
                    (
                        f"{RANDOM_STATE}|{outer_fold}|{fraction:.2f}|"
                        + "|".join(selected_components)
                    ).encode("utf-8")
                ).hexdigest()
                key = (
                    degeneracy_count,
                    missing_folds,
                    signature_sse,
                    fold_sse,
                    len(selected_components),
                    digest,
                )
                if best is None or key < best[0]:
                    best = (key, combo)
        if best is None:
            raise ContractError(
                f"no deterministic learning subset for {outer_fold} fraction={fraction}"
            )
        selected_ids = [component_ids[index] for index in best[1]]

    selected_indices = sorted(
        index
        for component in selected_ids
        for index in components[component]["indices"]
    )
    selected_families = {
        dataset.rows[index]["scenario_family_id"] for index in selected_indices
    }
    return {
        "indices": np.asarray(selected_indices, dtype=int),
        "component_ids": selected_ids,
        "family_count": len(selected_families),
        "component_count": len(selected_ids),
        "target_family_count": target_families,
        "actual_fraction": len(selected_families) / len(all_families),
        "selection_digest": hashlib.sha256(
            "\n".join(selected_ids).encode("utf-8")
        ).hexdigest(),
    }


def _subset_calibration_scores(
    X: np.ndarray,
    dataset: DevDataset,
    selected_indices: np.ndarray,
    *,
    model_name: str,
    b3_config: B3Config | None = None,
) -> np.ndarray:
    selected_folds = sorted(
        set(dataset.fold_ids[selected_indices]), key=lambda value: value.encode("utf-8")
    )
    if len(selected_folds) != 3:
        raise DegenerateLabelError(
            f"learning subset has {len(selected_folds)} inner groups rather than three"
        )
    scores = np.full((len(selected_indices), 3), np.nan, dtype=np.float64)
    for inner_fold in selected_folds:
        local_training = np.flatnonzero(dataset.fold_ids[selected_indices] != inner_fold)
        local_validation = np.flatnonzero(dataset.fold_ids[selected_indices] == inner_fold)
        training_indices = selected_indices[local_training]
        validation_indices = selected_indices[local_validation]
        if model_name == "B2":
            model = fit_prototypes(
                X[training_indices],
                dataset.y[training_indices],
                f"B2 learning calibration {inner_fold}",
            )
            scores[local_validation] = prototype_scores(X[validation_indices], model)
        elif model_name == "B3" and b3_config is not None:
            model = fit_ovr(
                X[training_indices],
                dataset.y[training_indices],
                b3_config,
                f"B3 learning calibration {inner_fold}",
            )
            scores[local_validation] = predict_ovr_probabilities(
                X[validation_indices], model
            )
        else:
            raise ContractError(f"unknown learning-curve model: {model_name}")
    if np.any(~np.isfinite(scores)):
        raise ContractError("incomplete grouped learning calibration scores")
    return scores


def learning_curves(
    X: np.ndarray,
    dataset: DevDataset,
    final_b3_config: B3Config,
) -> dict[str, Any]:
    """Run descriptive grouped learning curves for fixed B2 and final B3."""

    fold_rows: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, Any]] = {"B2": {}, "B3": {}}
    for model_name in ("B2", "B3"):
        for fraction in (0.25, 0.50, 0.75, 1.00):
            pooled_true: list[np.ndarray] = []
            pooled_pred: list[np.ndarray] = []
            pooled_rows: list[Mapping[str, str]] = []
            all_evaluable = True
            for outer_fold in FOLD_IDS:
                subset = deterministic_learning_subset(dataset, outer_fold, fraction)
                selected = subset["indices"]
                validation = np.flatnonzero(dataset.fold_ids == outer_fold)
                base_row: dict[str, Any] = {
                    "model": model_name,
                    "requested_training_family_fraction": fraction,
                    "outer_fold": outer_fold,
                    "target_training_families": subset["target_family_count"],
                    "actual_training_families": subset["family_count"],
                    "actual_training_family_fraction": subset["actual_fraction"],
                    "training_atomic_components": subset["component_count"],
                    "selection_digest": subset["selection_digest"],
                    "validation_cases": len(validation),
                }
                try:
                    calibration_scores = _subset_calibration_scores(
                        X,
                        dataset,
                        selected,
                        model_name=model_name,
                        b3_config=final_b3_config if model_name == "B3" else None,
                    )
                    thresholds = thresholds_from_scores(
                        calibration_scores, dataset.y[selected]
                    )
                    if model_name == "B2":
                        fitted = fit_prototypes(
                            X[selected],
                            dataset.y[selected],
                            f"B2 learning outer fit {outer_fold} {fraction}",
                        )
                        validation_scores = prototype_scores(X[validation], fitted)
                    else:
                        fitted = fit_ovr(
                            X[selected],
                            dataset.y[selected],
                            final_b3_config,
                            f"B3 learning outer fit {outer_fold} {fraction}",
                        )
                        validation_scores = predict_ovr_probabilities(
                            X[validation], fitted
                        )
                    prediction = apply_thresholds(validation_scores, thresholds)
                    metrics = compute_core_metrics(
                        dataset.y[validation],
                        prediction,
                        [dataset.rows[index] for index in validation],
                    )
                    base_row.update(
                        {
                            "status": "EVALUATED",
                            "reason": "",
                            "macro_f1": metrics["macro_f1"],
                            "micro_f1": metrics["micro_f1"],
                            "exact_capability_set_match": metrics[
                                "exact_capability_set_match"
                            ],
                            "jaccard": metrics["jaccard"],
                            "under_routing_rate": metrics["under_routing_rate"],
                            "over_routing_rate": metrics["over_routing_rate"],
                        }
                    )
                    pooled_true.append(dataset.y[validation])
                    pooled_pred.append(prediction)
                    pooled_rows.extend(dataset.rows[index] for index in validation)
                except DegenerateLabelError as exc:
                    all_evaluable = False
                    base_row.update(
                        {
                            "status": "NOT_EVALUABLE",
                            "reason": str(exc),
                            "macro_f1": None,
                            "micro_f1": None,
                            "exact_capability_set_match": None,
                            "jaccard": None,
                            "under_routing_rate": None,
                            "over_routing_rate": None,
                        }
                    )
                fold_rows.append(base_row)
            key = f"{fraction:.2f}"
            if all_evaluable and len(pooled_true) == 4:
                aggregate[model_name][key] = {
                    "status": "EVALUATED",
                    "requested_training_family_fraction": fraction,
                    "metrics": compute_core_metrics(
                        np.vstack(pooled_true), np.vstack(pooled_pred), pooled_rows
                    ),
                }
            else:
                aggregate[model_name][key] = {
                    "status": "NOT_EVALUABLE",
                    "requested_training_family_fraction": fraction,
                    "reason": (
                        "At least one grouped outer-fold training subset was degenerate; "
                        "no pooled metric is reported."
                    ),
                    "evaluable_outer_folds": len(pooled_true),
                }
    return {"fold_rows": fold_rows, "aggregate": aggregate}


def b2_frozen_payload(
    full_result: Mapping[str, Any],
    embedding_identity: Mapping[str, Any],
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    prototypes = full_result["final_prototypes"]
    return {
        "schema_version": "rq2-v2-stage4h-b2-frozen-model-v1",
        "model_id": "R2V2-B2_PROTOTYPE",
        "training_population": "64 DEV ANSWER utterances / 32 ANSWER families",
        "scoring": "cosine_to_positive_prototype_minus_cosine_to_negative_prototype",
        "capabilities": list(CAPABILITIES),
        "thresholds": {
            capability: full_result["thresholds"][column]
            for column, capability in enumerate(CAPABILITIES)
        },
        "prototypes": {
            capability: {
                "positive": prototypes["positive"][column].tolist(),
                "negative": prototypes["negative"][column].tolist(),
            }
            for column, capability in enumerate(CAPABILITIES)
        },
        "encoder_identity": dict(embedding_identity),
        "serializer_identity": {
            "feature_profile": FEATURE_PROFILE,
            "serializer_version": SERIALIZER_VERSION,
            "semantic_fields": list(SEMANTIC_FIELDS),
        },
        "training_source_sha256": dict(source_hashes),
        "full_dev_oof_threshold_calibration_diagnostic": full_result[
            "diagnostic_metrics"
        ],
        "not_primary_nested_estimate": True,
    }


def b3_frozen_payload(
    full_result: Mapping[str, Any],
    embedding_identity: Mapping[str, Any],
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    selected = full_result["selected"]
    final_model = full_result["final_model"]
    config: B3Config = selected["config"]
    return {
        "schema_version": "rq2-v2-stage4h-b3-frozen-model-v1",
        "model_id": "R2V2-B3_OVR",
        "training_population": "64 DEV ANSWER utterances / 32 ANSWER families",
        "configuration": config.as_dict(),
        "capabilities": list(CAPABILITIES),
        "thresholds": {
            capability: selected["thresholds"][column]
            for column, capability in enumerate(CAPABILITIES)
        },
        "coefficients": {
            capability: final_model["coefficients"][column].tolist()
            for column, capability in enumerate(CAPABILITIES)
        },
        "intercepts": {
            capability: float(final_model["intercepts"][column])
            for column, capability in enumerate(CAPABILITIES)
        },
        "fit_iterations": {
            capability: int(final_model["iterations"][column])
            for column, capability in enumerate(CAPABILITIES)
        },
        "encoder_identity": dict(embedding_identity),
        "serializer_identity": {
            "feature_profile": FEATURE_PROFILE,
            "serializer_version": SERIALIZER_VERSION,
            "semantic_fields": list(SEMANTIC_FIELDS),
        },
        "training_source_sha256": dict(source_hashes),
        "full_dev_oof_threshold_calibration_diagnostic": selected["metrics"],
        "not_primary_nested_estimate": True,
    }


def predict_from_b2_payload(X: np.ndarray, payload: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    prototypes = {
        "positive": np.asarray(
            [payload["prototypes"][capability]["positive"] for capability in CAPABILITIES]
        ),
        "negative": np.asarray(
            [payload["prototypes"][capability]["negative"] for capability in CAPABILITIES]
        ),
    }
    scores = prototype_scores(X, prototypes)
    thresholds = [payload["thresholds"][capability] for capability in CAPABILITIES]
    return scores, apply_thresholds(scores, thresholds)


def predict_from_b3_payload(X: np.ndarray, payload: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    model = {
        "coefficients": np.asarray(
            [payload["coefficients"][capability] for capability in CAPABILITIES]
        ),
        "intercepts": np.asarray(
            [payload["intercepts"][capability] for capability in CAPABILITIES]
        ),
    }
    probabilities = predict_ovr_probabilities(X, model)
    thresholds = [payload["thresholds"][capability] for capability in CAPABILITIES]
    return probabilities, apply_thresholds(probabilities, thresholds)
