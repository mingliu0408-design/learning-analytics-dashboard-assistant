"""Read-only Stage 4H-R1 sanity-baseline and separability diagnostics.

The functions in this module consume frozen DEV Gold and existing nested OOF
outputs.  They do not fit a model, select a threshold, or alter any prior
artifact.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from .track_h import (
    CAPABILITIES,
    PACKAGE_ROOT,
    DevDataset,
    compute_core_metrics,
    load_answer_dataset,
)


STARTING_HEAD = "7be7abd4cb72ee08a4bfacea0301e648c298b3cd"
TRACK_RELATIVE = Path(
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3"
)
EXPECTED_PRIOR_FILE_COUNT = 25
EXPECTED_PRIOR_MANIFEST_SHA256 = (
    "8b2e1142f6ab68947a18c3f4698ce9956d8876d85b8ad7d4cf320c2c05de0aca"
)
BOOTSTRAP_SEED = 20260831
BOOTSTRAP_REPLICATES = 10_000

BASELINE_DEFINITIONS = {
    "R2V2-D0_ALWAYS_ON": {
        "model_id": "R2V2-D0_ALWAYS_ON",
        "model_kind": "DETERMINISTIC_DIAGNOSTIC_BASELINE",
        "conditional_core_population": "64 DEV ANSWER utterances",
        "rag_required": "YES",
        "memory_required": "YES",
        "planning_required": "YES",
        "learned_model": False,
        "thresholds": None,
    },
    "R2V2-D1_NEVER_ON": {
        "model_id": "R2V2-D1_NEVER_ON",
        "model_kind": "DETERMINISTIC_DIAGNOSTIC_BASELINE",
        "conditional_core_population": "64 DEV ANSWER utterances",
        "rag_required": "NO",
        "memory_required": "NO",
        "planning_required": "NO",
        "learned_model": False,
        "thresholds": None,
    },
}


class DiagnosticContractError(RuntimeError):
    """Raised when an immutable input or diagnostic contract is violated."""


@dataclass(frozen=True)
class FrozenInputs:
    dataset: DevDataset
    b2_predictions: np.ndarray
    b3_predictions: np.ndarray
    b2_scores: np.ndarray
    b3_probabilities: np.ndarray


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(arguments: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=PACKAGE_ROOT.parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise DiagnosticContractError(
            f"git {' '.join(arguments)} failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def prior_artifact_manifest() -> dict[str, Any]:
    """Verify all starting-HEAD Track H files against Git and SHA-256."""

    repo_root = PACKAGE_ROOT.parents[2]
    listing = _git_bytes(
        [
            "ls-tree",
            "-r",
            "--name-only",
            STARTING_HEAD,
            "--",
            TRACK_RELATIVE.as_posix(),
        ]
    ).decode("utf-8").splitlines()
    paths = sorted(listing, key=lambda value: value.encode("utf-8"))
    if len(paths) != EXPECTED_PRIOR_FILE_COUNT:
        raise DiagnosticContractError(
            f"expected {EXPECTED_PRIOR_FILE_COUNT} prior files, observed {len(paths)}"
        )
    entries: list[dict[str, Any]] = []
    for relative in paths:
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise DiagnosticContractError(
                f"prior Track H artifact is missing, non-regular, or symlinked: {relative}"
            )
        worktree_data = path.read_bytes()
        committed_data = _git_bytes(["show", f"{STARTING_HEAD}:{relative}"])
        if worktree_data != committed_data:
            raise DiagnosticContractError(
                f"immutable prior Track H artifact changed: {relative}"
            )
        entries.append(
            {
                "path": relative,
                "size_bytes": len(worktree_data),
                "sha256": sha256_bytes(worktree_data),
            }
        )
    identity_payload = {
        "starting_head": STARTING_HEAD,
        "file_count": len(entries),
        "files": entries,
    }
    canonical = (
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    identity_sha256 = sha256_bytes(canonical)
    if identity_sha256 != EXPECTED_PRIOR_MANIFEST_SHA256:
        raise DiagnosticContractError(
            "prior Track H canonical manifest changed: "
            f"{identity_sha256} != {EXPECTED_PRIOR_MANIFEST_SHA256}"
        )
    return {
        "schema_version": "rq2-v2-stage4h-r1-prior-track-h-sha256-v1",
        **identity_payload,
        "canonical_identity_sha256": identity_sha256,
        "all_worktree_bytes_equal_starting_head_blobs": True,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _aligned_prediction_matrix(
    dataset: DevDataset,
    filename: str,
) -> np.ndarray:
    rows = _read_csv(PACKAGE_ROOT / filename)
    if len(rows) != dataset.size:
        raise DiagnosticContractError(
            f"{filename} must contain {dataset.size} prediction rows"
        )
    by_id = {row["annotation_case_id"]: row for row in rows}
    if len(by_id) != dataset.size or set(by_id) != set(dataset.case_ids):
        raise DiagnosticContractError(f"{filename} case-ID coverage mismatch")
    prediction = np.empty((dataset.size, 3), dtype=np.int8)
    for index, source_row in enumerate(dataset.rows):
        row = by_id[source_row["annotation_case_id"]]
        if row["scenario_family_id"] != source_row["scenario_family_id"]:
            raise DiagnosticContractError(f"family mismatch in {filename}")
        for column, capability in enumerate(CAPABILITIES):
            token = capability.lower()
            gold = int(row[f"gold_{token}"])
            predicted = int(row[f"predicted_{token}"])
            if gold != int(dataset.y[index, column]):
                raise DiagnosticContractError(f"Gold mismatch in {filename}")
            if predicted not in (0, 1):
                raise DiagnosticContractError(f"non-binary prediction in {filename}")
            prediction[index, column] = predicted
    return prediction


def _aligned_score_matrix(
    dataset: DevDataset,
    filename: str,
    suffix: str,
    expected_predictions: np.ndarray,
) -> np.ndarray:
    rows = _read_csv(PACKAGE_ROOT / filename)
    if len(rows) != dataset.size:
        raise DiagnosticContractError(f"{filename} score row count mismatch")
    by_id = {row["annotation_case_id"]: row for row in rows}
    if len(by_id) != dataset.size or set(by_id) != set(dataset.case_ids):
        raise DiagnosticContractError(f"{filename} case-ID coverage mismatch")
    scores = np.empty((dataset.size, 3), dtype=np.float64)
    for index, source_row in enumerate(dataset.rows):
        row = by_id[source_row["annotation_case_id"]]
        for column, capability in enumerate(CAPABILITIES):
            token = capability.lower()
            value = float(row[f"{token}_{suffix}"])
            predicted = int(row[f"{token}_prediction"])
            if not np.isfinite(value):
                raise DiagnosticContractError(f"non-finite raw score in {filename}")
            if predicted != int(expected_predictions[index, column]):
                raise DiagnosticContractError(
                    f"score/prediction mismatch for {capability} in {filename}"
                )
            scores[index, column] = value
    return scores


def load_frozen_inputs() -> FrozenInputs:
    dataset = load_answer_dataset()
    b2_predictions = _aligned_prediction_matrix(
        dataset, "b2_nested_oof_predictions_v1.csv"
    )
    b3_predictions = _aligned_prediction_matrix(
        dataset, "b3_nested_oof_predictions_v1.csv"
    )
    b2_scores = _aligned_score_matrix(
        dataset,
        "b2_nested_oof_scores_v1.csv",
        "score",
        b2_predictions,
    )
    b3_probabilities = _aligned_score_matrix(
        dataset,
        "b3_nested_oof_probabilities_v1.csv",
        "probability",
        b3_predictions,
    )
    return FrozenInputs(
        dataset=dataset,
        b2_predictions=b2_predictions,
        b3_predictions=b3_predictions,
        b2_scores=b2_scores,
        b3_probabilities=b3_probabilities,
    )


def baseline_predictions(dataset: DevDataset) -> dict[str, np.ndarray]:
    return {
        "R2V2-D0_ALWAYS_ON": np.ones_like(dataset.y, dtype=np.int8),
        "R2V2-D1_NEVER_ON": np.zeros_like(dataset.y, dtype=np.int8),
    }


def prediction_prevalence(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=np.int8)
    y_pred = np.asarray(y_pred, dtype=np.int8)
    if y_true.shape != y_pred.shape or y_true.shape[1] != 3:
        raise DiagnosticContractError("prevalence arrays must have aligned shape (n, 3)")
    per_capability: dict[str, Any] = {}
    for column, capability in enumerate(CAPABILITIES):
        truth = y_true[:, column]
        prediction = y_pred[:, column]
        tp = int(np.sum((truth == 1) & (prediction == 1)))
        fp = int(np.sum((truth == 0) & (prediction == 1)))
        tn = int(np.sum((truth == 0) & (prediction == 0)))
        fn = int(np.sum((truth == 1) & (prediction == 0)))
        per_capability[capability] = {
            "gold_positive_count": int(np.sum(truth == 1)),
            "gold_negative_count": int(np.sum(truth == 0)),
            "predicted_yes_count": int(np.sum(prediction == 1)),
            "predicted_no_count": int(np.sum(prediction == 0)),
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "positive_prediction_rate": float(np.mean(prediction == 1)),
            "zero_true_negatives": tn == 0,
        }
    signatures = ["".join(str(int(bit)) for bit in row) for row in y_pred]
    distribution = {
        f"{value:03b}": signatures.count(f"{value:03b}") for value in range(8)
    }
    return {
        "case_count": len(y_true),
        "per_capability": per_capability,
        "predicted_capability_signature_distribution": distribution,
        "prediction_000_count": distribution["000"],
        "prediction_111_count": distribution["111"],
        "mean_predicted_capability_count_per_case": float(np.mean(np.sum(y_pred, axis=1))),
    }


def raw_score_separability(
    y_true: np.ndarray,
    scores: np.ndarray,
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=np.int8)
    scores = np.asarray(scores, dtype=np.float64)
    if y_true.shape != scores.shape or y_true.shape[1] != 3:
        raise DiagnosticContractError("separability arrays must have aligned shape (n, 3)")
    result: dict[str, Any] = {}
    for column, capability in enumerate(CAPABILITIES):
        truth = y_true[:, column]
        values = scores[:, column]
        auc = float(roc_auc_score(truth, values))
        average_precision = float(average_precision_score(truth, values))
        minimum = float(np.min(values))
        maximum = float(np.max(values))
        result[capability] = {
            "roc_auc": auc,
            "average_precision": average_precision,
            "mean_score_gold_yes": float(np.mean(values[truth == 1])),
            "mean_score_gold_no": float(np.mean(values[truth == 0])),
            "score_minimum": minimum,
            "score_maximum": maximum,
            "score_range_width": maximum - minimum,
            "roc_auc_below_0_5": auc < 0.5,
            "scores_flipped_or_labels_reversed": False,
        }
    return result


def _bootstrap_metric_arrays(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    sampled_indices: np.ndarray,
) -> dict[str, np.ndarray]:
    truth = y_true[sampled_indices]
    prediction = y_pred[sampled_indices]
    tp = np.sum((truth == 1) & (prediction == 1), axis=1)
    fp = np.sum((truth == 0) & (prediction == 1), axis=1)
    fn = np.sum((truth == 1) & (prediction == 0), axis=1)
    denominator = 2 * tp + fp + fn
    per_label_f1 = np.divide(
        2 * tp,
        denominator,
        out=np.zeros_like(denominator, dtype=np.float64),
        where=denominator != 0,
    )
    exact = np.mean(np.all(truth == prediction, axis=2), axis=1)
    intersection = np.sum((truth == 1) & (prediction == 1), axis=2)
    union = np.sum((truth == 1) | (prediction == 1), axis=2)
    jaccard_by_case = np.divide(
        intersection,
        union,
        out=np.ones_like(intersection, dtype=np.float64),
        where=union != 0,
    )
    under = np.mean(np.any((truth == 1) & (prediction == 0), axis=2), axis=1)
    over = np.mean(np.any((truth == 0) & (prediction == 1), axis=2), axis=1)
    return {
        "macro_f1": np.mean(per_label_f1, axis=1),
        "exact_capability_set_match": exact,
        "jaccard": np.mean(jaccard_by_case, axis=1),
        "under_routing_rate": under,
        "over_routing_rate": over,
    }


def _point_metric_summary(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    indices = np.arange(len(y_true), dtype=int)[None, :]
    return {
        name: float(values[0])
        for name, values in _bootstrap_metric_arrays(y_true, y_pred, indices).items()
    }


def _distribution_summary(values: np.ndarray, point_estimate: float) -> dict[str, Any]:
    lower, median, upper = np.percentile(
        values, [2.5, 50.0, 97.5], method="linear"
    )
    return {
        "point_estimate": float(point_estimate),
        "bootstrap_mean": float(np.mean(values)),
        "bootstrap_standard_deviation": float(np.std(values, ddof=1)),
        "percentile_2_5": float(lower),
        "percentile_50": float(median),
        "percentile_97_5": float(upper),
        "replicates_below_zero": int(np.sum(values < 0)),
        "replicates_equal_zero": int(np.sum(values == 0)),
        "replicates_above_zero": int(np.sum(values > 0)),
        "difference_statistically_established": False,
    }


def family_cluster_bootstrap(
    dataset: DevDataset,
    predictions: Mapping[str, np.ndarray],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Run a paired family-cluster bootstrap using both utterances per draw."""

    family_to_indices: dict[str, list[int]] = {}
    for index, row in enumerate(dataset.rows):
        family_to_indices.setdefault(row["scenario_family_id"], []).append(index)
    families = sorted(family_to_indices, key=lambda value: value.encode("utf-8"))
    if len(families) != 32 or any(len(family_to_indices[family]) != 2 for family in families):
        raise DiagnosticContractError("bootstrap requires 32 families with two utterances each")
    family_indices = np.asarray(
        [sorted(family_to_indices[family]) for family in families], dtype=int
    )
    rng = np.random.default_rng(seed)
    sampled_family_positions = rng.integers(
        0, len(families), size=(replicates, len(families)), endpoint=False
    )
    sampled_indices = family_indices[sampled_family_positions].reshape(replicates, -1)

    samples: dict[str, dict[str, np.ndarray]] = {}
    intervals: dict[str, Any] = {}
    point_metrics: dict[str, dict[str, float]] = {}
    for model_id, prediction in predictions.items():
        prediction = np.asarray(prediction, dtype=np.int8)
        if prediction.shape != dataset.y.shape:
            raise DiagnosticContractError(f"bootstrap prediction shape mismatch: {model_id}")
        point = _point_metric_summary(dataset.y, prediction)
        distributions = _bootstrap_metric_arrays(
            dataset.y, prediction, sampled_indices
        )
        point_metrics[model_id] = point
        samples[model_id] = distributions
        intervals[model_id] = {
            metric: _distribution_summary(values, point[metric])
            for metric, values in distributions.items()
        }

    difference_specs = {
        "B2_MACRO_F1_MINUS_B3_MACRO_F1": (
            "R2V2-B2_PROTOTYPE",
            "R2V2-B3_OVR",
        ),
        "B2_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1": (
            "R2V2-B2_PROTOTYPE",
            "R2V2-D0_ALWAYS_ON",
        ),
        "B3_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1": (
            "R2V2-B3_OVR",
            "R2V2-D0_ALWAYS_ON",
        ),
    }
    difference_samples: dict[str, np.ndarray] = {}
    difference_summaries: dict[str, Any] = {}
    for name, (left, right) in difference_specs.items():
        values = samples[left]["macro_f1"] - samples[right]["macro_f1"]
        point = point_metrics[left]["macro_f1"] - point_metrics[right]["macro_f1"]
        difference_samples[name] = values
        difference_summaries[name] = {
            "left_model": left,
            "right_model": right,
            **_distribution_summary(values, point),
        }

    return {
        "schema_version": "rq2-v2-stage4h-r1-family-cluster-bootstrap-v1",
        "seed": seed,
        "replicates": replicates,
        "resampling_unit": "scenario_family_id",
        "family_count_per_replicate": len(families),
        "utterance_count_per_replicate": len(families) * 2,
        "paired_resampling_across_models": True,
        "confidence_interval": "95% percentile interval",
        "percentile_method": "numpy linear",
        "model_intervals": intervals,
        "difference_intervals": difference_summaries,
        "samples": samples,
        "difference_samples": difference_samples,
    }


def complete_diagnostic_computation() -> dict[str, Any]:
    frozen = load_frozen_inputs()
    baselines = baseline_predictions(frozen.dataset)
    all_predictions = {
        **baselines,
        "R2V2-B2_PROTOTYPE": frozen.b2_predictions,
        "R2V2-B3_OVR": frozen.b3_predictions,
    }
    baseline_metrics = {
        model_id: compute_core_metrics(
            frozen.dataset.y, prediction, frozen.dataset.rows
        )
        for model_id, prediction in baselines.items()
    }
    prevalence = {
        "R2V2-B2_PROTOTYPE": prediction_prevalence(
            frozen.dataset.y, frozen.b2_predictions
        ),
        "R2V2-B3_OVR": prediction_prevalence(
            frozen.dataset.y, frozen.b3_predictions
        ),
    }
    separability = {
        "R2V2-B2_PROTOTYPE": raw_score_separability(
            frozen.dataset.y, frozen.b2_scores
        ),
        "R2V2-B3_OVR": raw_score_separability(
            frozen.dataset.y, frozen.b3_probabilities
        ),
    }
    bootstrap = family_cluster_bootstrap(frozen.dataset, all_predictions)
    return {
        "frozen_inputs": frozen,
        "baseline_definitions": BASELINE_DEFINITIONS,
        "baseline_predictions": baselines,
        "all_predictions": all_predictions,
        "baseline_metrics": baseline_metrics,
        "prevalence": prevalence,
        "separability": separability,
        "bootstrap": bootstrap,
    }
