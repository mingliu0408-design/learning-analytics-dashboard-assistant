"""Frozen-candidate DEV evaluation and C0 reproduction gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import ROOT, VIEW_A, VIEW_B, VIEW_C
from .governed_data_loader import canonical_json_bytes, sha256_file


LR3 = ROOT / "evaluation/learned_intent_ranking/lr3"
if str(LR3) not in sys.path:
    sys.path.insert(0, str(LR3))

from evaluate_ranker import compact_prediction  # type: ignore[import-not-found]  # noqa: E402
from metrics import compute_view_metrics  # type: ignore[import-not-found]  # noqa: E402


EXPECTED_C0 = {
    "mrr": 0.6072081575246132,
    "top1_accuracy": 0.3924050632911392,
    "recall_at_3": 0.7468354430379747,
    "macro_f1": 0.47164045141018823,
}
TOLERANCE = 1e-12


def evaluate_all_views(
    predictions: list[dict[str, Any]], bundle: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    names = {
        VIEW_A: "PAIRWISE-SEEN DEVELOPMENT EVALUATION",
        VIEW_B: "UNSEEN-SINGLETON DIAGNOSTIC",
        VIEW_C: "MIXED DEVELOPMENT DIAGNOSTIC",
    }
    return {
        view: compute_view_metrics(
            predictions,
            bundle["view_ids"][view],
            bundle["frozen"]["production_labels"],
            names[view],
        )
        for view in (VIEW_A, VIEW_B, VIEW_C)
    }


def _ranking_identity(prediction: dict[str, Any]) -> tuple[Any, ...]:
    return (
        prediction["record_id"],
        prediction["gold_rank"],
        prediction["top1_label"],
        tuple(
            (
                row["label"],
                tuple(row["example_ids"]),
            )
            for row in prediction["intent_ranking"]
        ),
    )


def run_c0_reproduction_gate(
    bundle: dict[str, Any],
    predictions: list[dict[str, Any]],
    prediction_ledger_path: Path,
) -> dict[str, Any]:
    metrics = evaluate_all_views(predictions, bundle)
    view_a = metrics[VIEW_A]
    differences = {
        metric: abs(float(view_a[metric]) - expected)
        for metric, expected in EXPECTED_C0.items()
    }
    reference_path = LR3 / "results/cosine_dev_predictions_v1.json"
    if not reference_path.is_file():
        raise RuntimeError("frozen local C0 prediction reference is unavailable")
    reference = json.loads(reference_path.read_text(encoding="utf-8"))["predictions"]
    reference_by_id = {row["record_id"]: row for row in reference}
    ranking_matches = sum(
        _ranking_identity(row) == _ranking_identity(reference_by_id[row["record_id"]])
        for row in predictions
    )
    view_a_ids = set(bundle["view_ids"][VIEW_A])
    view_a_ranking_matches = sum(
        _ranking_identity(row) == _ranking_identity(reference_by_id[row["record_id"]])
        for row in predictions
        if row["record_id"] in view_a_ids
    )
    passed = (
        len(predictions) == 84
        and ranking_matches == 84
        and view_a_ranking_matches == 79
        and all(value <= TOLERANCE for value in differences.values())
    )
    if not passed:
        raise RuntimeError("BLOCKED_RQ1_B_C0_REPRODUCTION_MISMATCH")
    prediction_ledger_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_ledger_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "rq1b-c0-local-prediction-ledger-v1",
                "development_only": True,
                "predictions": [compact_prediction(row) for row in predictions],
                "contains_natural_language": False,
            }
        )
    )
    return {
        "schema_version": "rq1b-c0-reproduction-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "model": "C0_FROZEN_MPNET_COSINE",
        "candidate_example_count": 62,
        "candidate_label_count": 16,
        "intent_aggregation": "MAX",
        "top_k_prefiltering": False,
        "view_a_record_count": 79,
        "expected_view_a_metrics": EXPECTED_C0,
        "actual_view_metrics": metrics,
        "absolute_metric_differences": differences,
        "absolute_tolerance": TOLERANCE,
        "all_dev_ranking_identity_match_count": ranking_matches,
        "all_dev_ranking_identity_required": 84,
        "view_a_ranking_identity_match_count": view_a_ranking_matches,
        "view_a_ranking_identity_required": 79,
        "local_prediction_ledger_relative_path": str(prediction_ledger_path.relative_to(ROOT)),
        "local_prediction_ledger_sha256": sha256_file(prediction_ledger_path),
        "prediction_ledger_tracked": False,
        "final_gold_accessed": False,
    }
