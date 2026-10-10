"""Development-only data gates, grouped splitting, tuning, and evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import math
from typing import Any, Protocol

import numpy as np

from evaluation.capability_routing_rq2_v2_stage0.metrics import evaluate_predictions

from .canonical_text import serialize_canonical_text
from .errors import DegenerateLabelError, DevelopmentDataError
from .router_common import CAPABILITIES


LEARNING_CURVE_SAMPLING_METHOD = "SEEDED_SIGNATURE_ROUND_ROBIN_V1"


class DevelopmentRouter(Protocol):
    def fit(self, cases: Sequence[Mapping[str, Any]]) -> Any:
        ...

    def predict(self, cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        ...


def development_labels(case: Mapping[str, Any]) -> dict[str, bool]:
    """Extract core DEV labels without ever adding them to serialized text."""

    primary = case.get("development_labels")
    legacy = case.get("gold")
    if primary is None and legacy is None:
        raise DevelopmentDataError(
            "case requires development_labels or DEV-partition Stage 0 gold"
        )
    if primary is not None and not isinstance(primary, Mapping):
        raise DevelopmentDataError("development_labels must be a mapping")
    if legacy is not None and not isinstance(legacy, Mapping):
        raise DevelopmentDataError("gold must be a mapping")
    labels = dict(primary if primary is not None else legacy)
    allowed = set(CAPABILITIES) | {"dialogue_action"}
    unknown = sorted(str(key) for key in set(labels) - allowed)
    if unknown:
        raise DevelopmentDataError(
            "development label payload contains unknown fields: " + ", ".join(unknown)
        )
    action = str(labels.get("dialogue_action", "ANSWER"))
    if action != "ANSWER":
        raise DevelopmentDataError(
            "clarification cases are not applicable to B2/B3 core-label development"
        )
    result: dict[str, bool] = {}
    for label in CAPABILITIES:
        if label not in labels or not isinstance(labels[label], bool):
            raise DevelopmentDataError(f"development label {label} must be boolean")
        result[label] = labels[label]
    if primary is not None and legacy is not None:
        legacy_action = str(legacy.get("dialogue_action", "ANSWER"))
        if legacy_action != action or any(legacy.get(label) != result[label] for label in CAPABILITIES):
            raise DevelopmentDataError("development_labels and gold disagree")
    return result


def validate_development_cases(
    cases: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Fail closed on TEST, PILOT, clarification, malformed, or ungrouped input."""

    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise DevelopmentDataError("development cases must be a sequence")
    if not cases:
        raise DevelopmentDataError("development cases must not be empty")
    rows = list(cases)
    seen_case_ids: set[str] = set()
    for position, case in enumerate(rows):
        if not isinstance(case, Mapping):
            raise DevelopmentDataError(f"development case {position} is not a mapping")
        partition = str(case.get("partition", ""))
        if partition == "TEST":
            raise DevelopmentDataError("TEST records are forbidden in development utilities")
        if partition != "DEV":
            raise DevelopmentDataError(
                f"development utilities require partition DEV, observed {partition!r}"
            )
        case_id = str(case.get("case_id", "")).strip()
        if not case_id:
            raise DevelopmentDataError(f"development case {position} lacks case_id")
        if case_id in seen_case_ids:
            raise DevelopmentDataError(f"duplicate development case_id: {case_id}")
        seen_case_ids.add(case_id)
        family_id = str(case.get("scenario_family_id", "")).strip()
        if not family_id:
            raise DevelopmentDataError(
                f"development case {case_id} lacks scenario_family_id"
            )
        serialize_canonical_text(case)
        development_labels(case)
    return rows


def development_label_matrix(cases: Sequence[Mapping[str, Any]]) -> np.ndarray:
    rows = validate_development_cases(cases)
    return np.asarray(
        [[development_labels(case)[label] for label in CAPABILITIES] for case in rows],
        dtype=np.int8,
    )


def assert_non_degenerate_labels(
    labels: np.ndarray,
    *,
    context: str,
) -> None:
    matrix = np.asarray(labels)
    if matrix.ndim != 2 or matrix.shape[1] != len(CAPABILITIES):
        raise DevelopmentDataError("capability-label matrix shape is invalid")
    for position, label in enumerate(CAPABILITIES):
        positives = int(np.sum(matrix[:, position] == 1))
        negatives = int(np.sum(matrix[:, position] == 0))
        if not positives or not negatives:
            raise DegenerateLabelError(
                f"{context}: {label} requires positive and negative examples; "
                f"observed positive={positives}, negative={negatives}"
            )


def _capability_signature(case: Mapping[str, Any]) -> str:
    labels = development_labels(case)
    return "".join("1" if labels[label] else "0" for label in CAPABILITIES)


def _family_signature_map(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    observed: dict[str, set[str]] = {}
    for case in rows:
        family_id = str(case["scenario_family_id"])
        observed.setdefault(family_id, set()).add(_capability_signature(case))
    inconsistent = sorted(
        family_id for family_id, signatures in observed.items() if len(signatures) != 1
    )
    if inconsistent:
        raise DevelopmentDataError(
            "scenario family has inconsistent capability labels: "
            + ", ".join(inconsistent)
        )
    return {
        family_id: next(iter(signatures))
        for family_id, signatures in observed.items()
    }


def deterministic_stratified_family_order(
    cases: Sequence[Mapping[str, Any]],
    *,
    random_seed: int = 20260830,
) -> tuple[str, ...]:
    """Order complete families by seeded round-robin capability signature.

    Every prefix is as even as availability permits across the observed
    RAG/Memory/Planning signatures. Family IDs are sorted only before seeded
    permutation, never used as the selection priority.
    """

    rows = validate_development_cases(cases)
    seed = int(random_seed)
    if seed < 0:
        raise DevelopmentDataError("random_seed must be non-negative")
    family_signatures = _family_signature_map(rows)
    by_signature: dict[str, list[str]] = {}
    for family_id, signature in family_signatures.items():
        by_signature.setdefault(signature, []).append(family_id)
    signatures = sorted(by_signature)
    rng = np.random.default_rng(seed)
    signature_order = [
        signatures[int(index)] for index in rng.permutation(len(signatures)).tolist()
    ]
    queues: dict[str, list[str]] = {}
    for signature in signatures:
        families = sorted(by_signature[signature])
        queues[signature] = [
            families[int(index)]
            for index in rng.permutation(len(families)).tolist()
        ]
    positions = {signature: 0 for signature in signatures}
    ordered: list[str] = []
    while len(ordered) < len(family_signatures):
        progressed = False
        for signature in signature_order:
            position = positions[signature]
            if position >= len(queues[signature]):
                continue
            ordered.append(queues[signature][position])
            positions[signature] += 1
            progressed = True
        if not progressed:
            raise DevelopmentDataError("stratified family ordering made no progress")
    return tuple(ordered)


def grouped_cross_validation_splits(
    cases: Sequence[Mapping[str, Any]],
    *,
    n_splits: int = 4,
    random_seed: int = 20260830,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    """Return deterministic stratified-group folds by scenario family.

    The stratum is the frozen RAG/Memory/Planning bit signature. A family must
    have one consistent signature, and no family can cross fold boundaries.
    """

    rows = validate_development_cases(cases)
    family_ids = np.asarray([str(case["scenario_family_id"]) for case in rows])
    signatures = np.asarray([_capability_signature(case) for case in rows])
    family_signatures = _family_signature_map(rows)
    signature_family_counts: dict[str, int] = {}
    for signature in family_signatures.values():
        signature_family_counts[signature] = signature_family_counts.get(signature, 0) + 1
    unique_family_count = len(set(family_ids.tolist()))
    if n_splits < 2 or n_splits > unique_family_count:
        raise DevelopmentDataError(
            f"n_splits must be in [2, {unique_family_count}], observed {n_splits}"
        )
    insufficient = {
        signature: count
        for signature, count in signature_family_counts.items()
        if count < n_splits
    }
    if insufficient:
        details = ", ".join(
            f"{signature}={count}" for signature, count in sorted(insufficient.items())
        )
        raise DevelopmentDataError(
            f"each capability stratum needs at least {n_splits} families: {details}"
        )
    try:
        from sklearn.model_selection import StratifiedGroupKFold
    except (ImportError, ModuleNotFoundError) as exc:
        raise DevelopmentDataError("scikit-learn is required for grouped CV") from exc
    splitter = StratifiedGroupKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=int(random_seed),
    )
    placeholder = np.zeros((len(rows), 1), dtype=np.float64)
    try:
        splits = tuple(
            (
                tuple(int(index) for index in train_indices.tolist()),
                tuple(int(index) for index in validation_indices.tolist()),
            )
            for train_indices, validation_indices in splitter.split(
                placeholder, y=signatures, groups=family_ids
            )
        )
    except ValueError as exc:
        raise DevelopmentDataError(f"unable to construct grouped CV: {exc}") from exc
    assert_family_never_crosses_folds(rows, splits)
    return splits


def assert_family_never_crosses_folds(
    cases: Sequence[Mapping[str, Any]],
    splits: Sequence[tuple[Sequence[int], Sequence[int]]],
) -> None:
    rows = validate_development_cases(cases)
    if not splits:
        raise DevelopmentDataError("at least one grouped split is required")
    all_indices = set(range(len(rows)))
    validation_counts = {index: 0 for index in all_indices}
    for fold_index, (train_indices, validation_indices) in enumerate(splits):
        train = {int(index) for index in train_indices}
        validation = {int(index) for index in validation_indices}
        if not train or not validation:
            raise DevelopmentDataError(f"fold {fold_index} has an empty side")
        if not train <= all_indices or not validation <= all_indices:
            raise DevelopmentDataError(f"fold {fold_index} contains an invalid index")
        if train & validation:
            raise DevelopmentDataError(f"fold {fold_index} repeats a case across sides")
        train_families = {str(rows[index]["scenario_family_id"]) for index in train}
        validation_families = {
            str(rows[index]["scenario_family_id"]) for index in validation
        }
        overlap = sorted(train_families & validation_families)
        if overlap:
            raise DevelopmentDataError(
                f"scenario families cross fold {fold_index}: {', '.join(overlap)}"
            )
        for index in validation:
            validation_counts[index] += 1
    invalid_counts = [index for index, count in validation_counts.items() if count != 1]
    if invalid_counts:
        raise DevelopmentDataError(
            "grouped CV must validate every case exactly once: " + str(invalid_counts)
        )


def _binary_f1(y_true: np.ndarray, predicted: np.ndarray) -> tuple[float, float]:
    truth = np.asarray(y_true, dtype=bool)
    guess = np.asarray(predicted, dtype=bool)
    tp = int(np.sum(truth & guess))
    fp = int(np.sum(~truth & guess))
    fn = int(np.sum(truth & ~guess))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return float(f1), float(recall)


def search_per_label_thresholds(
    cases: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, float]],
    *,
    candidate_thresholds: Sequence[float]
    | Mapping[str, Sequence[float]]
    | None = None,
) -> dict[str, Any]:
    """Tune three independent thresholds on DEV labels only.

    Ties use higher recall and then the lower threshold. This is a deterministic
    development convention, not a final-test or winner-selection claim.
    """

    rows = validate_development_cases(cases)
    if len(score_rows) != len(rows):
        raise DevelopmentDataError("score rows must align one-to-one with cases")
    labels = development_label_matrix(rows)
    selected: dict[str, float] = {}
    details: dict[str, dict[str, float | int]] = {}
    for label_position, label in enumerate(CAPABILITIES):
        try:
            values = np.asarray([float(row[label]) for row in score_rows], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as exc:
            raise DevelopmentDataError(f"invalid scores for {label}") from exc
        if not np.isfinite(values).all():
            raise DevelopmentDataError(f"non-finite scores for {label}")
        if isinstance(candidate_thresholds, Mapping):
            candidates = [float(value) for value in candidate_thresholds.get(label, ())]
        elif candidate_thresholds is not None:
            candidates = [float(value) for value in candidate_thresholds]
        else:
            maximum = float(np.max(values))
            candidates = sorted(set(values.tolist()))
            candidates.append(float(np.nextafter(maximum, math.inf)))
        if not candidates or any(not math.isfinite(value) for value in candidates):
            raise DevelopmentDataError(f"candidate thresholds for {label} are invalid")
        candidates = sorted(set(candidates))
        truth = labels[:, label_position].astype(bool)
        best: tuple[tuple[float, float, float], float, float, float] | None = None
        for threshold in candidates:
            f1, recall = _binary_f1(truth, values >= threshold)
            key = (f1, recall, -threshold)
            if best is None or key > best[0]:
                best = (key, threshold, f1, recall)
        assert best is not None
        selected[label] = float(best[1])
        details[label] = {
            "threshold": float(best[1]),
            "f1": float(best[2]),
            "recall": float(best[3]),
            "candidate_count": len(candidates),
        }
    return {"thresholds": selected, "per_label": details}


def _stage0_metric_case(case: Mapping[str, Any]) -> dict[str, Any]:
    labels = development_labels(case)
    if case.get("schema_version") == "rq2-v2-case-v1" and "gold" in case:
        return deepcopy(dict(case))
    model_input = dict(case["model_input"])
    model_input.setdefault("current_page", "Other")
    model_input.setdefault("dashboard_context", "")
    model_input.setdefault("visible_conversation_history", [])
    model_input.setdefault("rag_context_state", "UNKNOWN")
    model_input.setdefault("memory_context_state", "UNKNOWN")
    case_id = str(case["case_id"])
    return {
        "schema_version": "rq2-v2-case-v1",
        "case_id": case_id,
        "scenario_family_id": str(case["scenario_family_id"]),
        "utterance_id": str(case.get("utterance_id") or f"{case_id}-DEV"),
        "provenance": {
            "type": "RESEARCHER_SYNTHETIC",
            "source_asset_id": "STAGE1_TRACK_C_TRANSIENT_METRIC_ADAPTER",
            "prior_exposure_to_model_selection": True,
            "human_verified": False,
        },
        "partition": "DEV",
        "model_input": model_input,
        "gold": {"dialogue_action": "ANSWER", **labels},
        "governance": {
            "final_test_eligible": False,
            "fixture_only": True,
            "authentic_student_data_claim": False,
            "contains_restricted_data": False,
        },
    }


def evaluate_with_stage0_metrics(
    cases: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = validate_development_cases(cases)
    if len(predictions) != len(rows):
        raise DevelopmentDataError("prediction count does not match development cases")
    return evaluate_predictions(
        [_stage0_metric_case(case) for case in rows],
        [dict(prediction) for prediction in predictions],
    )


def run_learning_curve(
    cases: Sequence[Mapping[str, Any]],
    router_factory: Callable[[], DevelopmentRouter],
    *,
    training_family_counts: Sequence[int],
    n_splits: int = 4,
    random_seed: int = 20260830,
) -> list[dict[str, Any]]:
    """Run family-grouped, DEV-only learning-curve fits."""

    rows = validate_development_cases(cases)
    seed = int(random_seed)
    if seed < 0:
        raise DevelopmentDataError("random_seed must be non-negative")
    counts = sorted(set(int(value) for value in training_family_counts))
    if not counts or counts[0] < 1:
        raise DevelopmentDataError("training_family_counts must be positive")
    splits = grouped_cross_validation_splits(
        rows, n_splits=n_splits, random_seed=random_seed
    )
    results: list[dict[str, Any]] = []
    for fold, (train_indices, validation_indices) in enumerate(splits):
        fold_training_pool = [rows[index] for index in train_indices]
        sampling_seed = seed
        train_families = deterministic_stratified_family_order(
            fold_training_pool,
            random_seed=sampling_seed,
        )
        if counts[-1] > len(train_families):
            raise DevelopmentDataError(
                f"fold {fold} has only {len(train_families)} training families"
            )
        validation_cases = [rows[index] for index in validation_indices]
        for family_count in counts:
            selected_family_order = train_families[:family_count]
            selected_families = set(selected_family_order)
            training_cases = [
                rows[index]
                for index in train_indices
                if str(rows[index]["scenario_family_id"]) in selected_families
            ]
            labels = development_label_matrix(training_cases)
            assert_non_degenerate_labels(
                labels,
                context=(
                    f"learning curve fold={fold} family_count={family_count}"
                ),
            )
            selected_signature_counts: dict[str, int] = {}
            selected_family_signatures = _family_signature_map(training_cases)
            for signature in selected_family_signatures.values():
                selected_signature_counts[signature] = (
                    selected_signature_counts.get(signature, 0) + 1
                )
            router = router_factory()
            router.fit(training_cases)
            predictions = router.predict(validation_cases)
            results.append(
                {
                    "fold": fold,
                    "family_sampling_method": LEARNING_CURVE_SAMPLING_METHOD,
                    "family_sampling_seed": sampling_seed,
                    "training_family_count": family_count,
                    "training_family_ids": list(selected_family_order),
                    "training_signature_family_counts": dict(
                        sorted(selected_signature_counts.items())
                    ),
                    "training_case_count": len(training_cases),
                    "validation_family_count": len(
                        {str(case["scenario_family_id"]) for case in validation_cases}
                    ),
                    "validation_case_count": len(validation_cases),
                    "metrics": evaluate_with_stage0_metrics(
                        validation_cases, predictions
                    ),
                }
            )
    return results


def compare_core_and_synthetic_augmentation(
    core_training_cases: Sequence[Mapping[str, Any]],
    synthetic_augmentation_cases: Sequence[Mapping[str, Any]],
    validation_cases: Sequence[Mapping[str, Any]],
    router_factory: Callable[[], DevelopmentRouter],
) -> dict[str, Any]:
    """Compare core DEV with core-plus-synthetic DEV on one disjoint DEV set."""

    core = validate_development_cases(core_training_cases)
    synthetic = validate_development_cases(synthetic_augmentation_cases)
    validation = validate_development_cases(validation_cases)
    for case in synthetic:
        provenance_type = str((case.get("provenance") or {}).get("type", ""))
        if provenance_type not in {"RESEARCHER_SYNTHETIC", "LLM_AUGMENTED"}:
            raise DevelopmentDataError(
                "augmentation cases must declare RESEARCHER_SYNTHETIC or LLM_AUGMENTED"
            )
    combined = [*core, *synthetic]
    validate_development_cases(combined)
    training_families = {str(case["scenario_family_id"]) for case in combined}
    validation_families = {str(case["scenario_family_id"]) for case in validation}
    overlap = sorted(training_families & validation_families)
    if overlap:
        raise DevelopmentDataError(
            "training and validation scenario families overlap: " + ", ".join(overlap)
        )

    core_router = router_factory()
    core_router.fit(core)
    core_metrics = evaluate_with_stage0_metrics(
        validation, core_router.predict(validation)
    )
    augmented_router = router_factory()
    augmented_router.fit(combined)
    augmented_metrics = evaluate_with_stage0_metrics(
        validation, augmented_router.predict(validation)
    )
    metric_names = (
        "macro_f1",
        "micro_f1",
        "example_based_f1",
        "exact_set_match",
        "hamming_loss",
        "under_routing_rate",
        "over_routing_rate",
    )
    return {
        "status": "DEVELOPMENT_ONLY_NO_WINNER_CLAIM",
        "core_training_case_count": len(core),
        "synthetic_augmentation_case_count": len(synthetic),
        "validation_case_count": len(validation),
        "core_metrics": core_metrics,
        "augmented_metrics": augmented_metrics,
        "metric_deltas_augmented_minus_core": {
            name: float(augmented_metrics[name] - core_metrics[name])
            for name in metric_names
        },
    }
