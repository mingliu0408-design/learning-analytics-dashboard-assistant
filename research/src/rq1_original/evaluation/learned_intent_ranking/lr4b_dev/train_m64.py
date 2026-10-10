"""Thin training wrapper that injects only the governed scenario sampler."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import torch

from . import (
    CHECKPOINT_DIR,
    PREDICTION_LEDGER_DIR,
    ROOT,
    TRAINING_HISTORY_DIR,
    VIEW_A,
)
from .governed_data_loader import canonical_json_bytes, sha256_file
from .pair_builder import generate_epoch_pairs


LR3 = ROOT / "evaluation/learned_intent_ranking/lr3"
LR3R = ROOT / "evaluation/learned_intent_ranking/lr3r"
for candidate in (LR3R, LR3):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import compact_train as frozen_train  # type: ignore[import-not-found]  # noqa: E402
from evaluate_ranker import compact_prediction  # type: ignore[import-not-found]  # noqa: E402


@contextmanager
def _scenario_sampler_injection() -> Iterator[None]:
    original: Callable[..., list[dict[str, Any]]] = frozen_train.generate_epoch_pairs
    frozen_train.generate_epoch_pairs = generate_epoch_pairs
    try:
        yield
    finally:
        frozen_train.generate_epoch_pairs = original


def configure_determinism() -> None:
    frozen_train.configure_determinism()
    if not torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("BLOCKED_RQ1_B_NONDETERMINISTIC_RUNTIME")
    if torch.get_num_threads() != 1:
        raise RuntimeError("single-thread deterministic runtime was not established")


def _save_local_artifacts(
    run: dict[str, Any], scenario: str
) -> dict[str, Any]:
    seed = int(run["training_seed"])
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    PREDICTION_LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path = CHECKPOINT_DIR / f"rq1b_m64_{scenario.lower()}_seed_{seed}_best_v1.pt"
    torch.save(
        {
            "schema_version": "rq1b-m64-development-checkpoint-v1",
            "scenario": scenario,
            "training_seed": seed,
            "best_epoch": run["best_epoch"],
            "architecture": "M64",
            "state_dict": run["state_dict"],
            "final_gold_used": False,
        },
        checkpoint_path,
    )
    prediction_path = (
        PREDICTION_LEDGER_DIR
        / f"rq1b_m64_{scenario.lower()}_seed_{seed}_dev_predictions_v1.json"
    )
    prediction_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "rq1b-development-prediction-ledger-v1",
                "scenario": scenario,
                "training_seed": seed,
                "best_epoch": run["best_epoch"],
                "development_only": True,
                "contains_natural_language": False,
                "predictions": [compact_prediction(row) for row in run["predictions"]],
            }
        )
    )
    history_path = (
        TRAINING_HISTORY_DIR
        / f"rq1b_m64_{scenario.lower()}_seed_{seed}_training_history_v1.json"
    )
    history_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "rq1b-training-history-v1",
                "scenario": scenario,
                "training_seed": seed,
                "contains_natural_language": False,
                "history": run["training_history"],
            }
        )
    )
    return {
        "checkpoint_relative_path": str(checkpoint_path.relative_to(ROOT)),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "prediction_ledger_relative_path": str(prediction_path.relative_to(ROOT)),
        "prediction_ledger_sha256": sha256_file(prediction_path),
        "training_history_relative_path": str(history_path.relative_to(ROOT)),
        "training_history_sha256": sha256_file(history_path),
    }


def train_scenario_seed(
    *,
    scenario: str,
    seed: int,
    sampler: dict[str, Any],
    bundle: dict[str, Any],
    embeddings: dict[str, Any],
    mpnet_model: torch.nn.Module,
) -> dict[str, Any]:
    configure_determinism()
    with _scenario_sampler_injection():
        run = frozen_train.train_one_seed(
            model_family="M64",
            training_seed=seed,
            feature_dimension=1536,
            sampler=sampler,
            embedding_by_id=embeddings["embedding_by_id"],
            dev_records=bundle["dev_records"],
            dev_query_vectors=embeddings["dev_vectors"],
            index_records=bundle["frozen"]["index_records"],
            index_embeddings=bundle["frozen"]["embeddings"],
            view_ids=bundle["view_ids"],
            production_labels=bundle["frozen"]["production_labels"],
            mpnet_model=mpnet_model,
        )
    paths = _save_local_artifacts(run, scenario)
    history = run["training_history"]
    best_epoch = int(run["best_epoch"])
    best_row = next(row for row in history if int(row["epoch"]) == best_epoch)
    final_row = history[-1]
    return {
        "scenario": scenario,
        "seed": seed,
        "model_family": "M64",
        "best_epoch": best_epoch,
        "epochs_completed": run["epochs_completed"],
        "final_epoch": run["final_epoch"],
        "early_stopped": run["early_stopped"],
        "early_stop_reason": (
            "PATIENCE_8_WITHOUT_VIEW_A_IMPROVEMENT"
            if run["early_stopped"] else "MAXIMUM_EPOCHS_REACHED"
        ),
        "training_pair_count_per_epoch": [row["directed_row_count"] for row in history],
        "positive_count_per_epoch": [row["positive_count"] for row in history],
        "negative_count_per_epoch": [row["negative_count"] for row in history],
        "best_view_a_mrr": run["view_metrics"][VIEW_A]["mrr"],
        "best_view_a_top1": run["view_metrics"][VIEW_A]["top1_accuracy"],
        "best_view_a_macro_f1": run["view_metrics"][VIEW_A]["macro_f1"],
        "view_metrics": run["view_metrics"],
        "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "parameter_counts": run["parameter_counts"],
        "optimizer_parameter_count": run["optimizer_parameter_count"],
        "mpnet_parameters_in_optimizer": run["mpnet_parameters_in_optimizer"],
        "overfit_diagnostic": run["overfit_diagnostic"],
        "training_diagnostics": {
            "training_bce_at_best_dev_epoch": best_row["training_bce"],
            "minimum_training_bce": min(row["training_bce"] for row in history),
            "final_training_bce": final_row["training_bce"],
            "final_view_a_mrr": final_row["view_a_mrr"],
            "post_best_mrr_degradation": (
                run["view_metrics"][VIEW_A]["mrr"] - final_row["view_a_mrr"]
            ),
        },
        **paths,
    }


EXPECTED_V0_AGGREGATE = {
    "mrr_mean": 0.6561020695197911,
    "mrr_std": 0.02091832780394292,
    "top1_mean": 0.4632911392405063,
    "recall_at_3_mean": 0.8050632911392406,
    "macro_f1_mean": 0.47246923941485797,
    "seeds_beating_c0_mrr": 5,
    "severe_overfit_runs": 5,
}


def _ranking_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["record_id"],
        row["gold_rank"],
        row["top1_label"],
        tuple((item["label"], tuple(item["example_ids"])) for item in row["intent_ranking"]),
    )


def verify_v0_reproduction(v0_runs: list[dict[str, Any]], c0_mrr: float) -> dict[str, Any]:
    import statistics

    reference_result_path = LR3R / "lr3r_m64_training_results_v1.json"
    if not reference_result_path.is_file():
        raise RuntimeError("frozen local V0 metrics reference unavailable")
    reference_runs = json.loads(reference_result_path.read_text(encoding="utf-8"))["runs"]
    reference_by_seed = {int(row["training_seed"]): row for row in reference_runs}
    per_seed: list[dict[str, Any]] = []
    for run in v0_runs:
        seed = int(run["seed"])
        reference = reference_by_seed[seed]
        reference_prediction_path = LR3R / "results" / f"m64_seed_{seed}_dev_predictions_v1.json"
        current_prediction_path = ROOT / run["prediction_ledger_relative_path"]
        reference_predictions = json.loads(reference_prediction_path.read_text(encoding="utf-8"))[
            "predictions"
        ]
        current_predictions = json.loads(current_prediction_path.read_text(encoding="utf-8"))[
            "predictions"
        ]
        ranking_match = [
            _ranking_identity(left) == _ranking_identity(right)
            for left, right in zip(current_predictions, reference_predictions, strict=True)
        ]
        metric_differences = {
            metric: abs(
                float(run["view_metrics"][VIEW_A][metric])
                - float(reference["view_metrics"][VIEW_A][metric])
            )
            for metric in ("mrr", "top1_accuracy", "recall_at_3", "macro_f1")
        }
        passed = (
            run["best_epoch"] == reference["best_epoch"]
            and run["checkpoint_tensor_hash"] == reference["checkpoint_tensor_hash"]
            and all(ranking_match)
            and all(value <= 1e-12 for value in metric_differences.values())
        )
        per_seed.append(
            {
                "seed": seed,
                "best_epoch_match": run["best_epoch"] == reference["best_epoch"],
                "checkpoint_tensor_hash_match": (
                    run["checkpoint_tensor_hash"] == reference["checkpoint_tensor_hash"]
                ),
                "dev_ranking_match_count": sum(ranking_match),
                "dev_ranking_required": 84,
                "view_a_metric_absolute_differences": metric_differences,
                "pass": passed,
            }
        )
    mrrs = [float(run["view_metrics"][VIEW_A]["mrr"]) for run in v0_runs]
    aggregate = {
        "mrr_mean": float(statistics.fmean(mrrs)),
        "mrr_std": float(statistics.pstdev(mrrs)),
        "top1_mean": float(
            statistics.fmean(run["view_metrics"][VIEW_A]["top1_accuracy"] for run in v0_runs)
        ),
        "recall_at_3_mean": float(
            statistics.fmean(run["view_metrics"][VIEW_A]["recall_at_3"] for run in v0_runs)
        ),
        "macro_f1_mean": float(
            statistics.fmean(run["view_metrics"][VIEW_A]["macro_f1"] for run in v0_runs)
        ),
        "seeds_beating_c0_mrr": sum(value > c0_mrr for value in mrrs),
        "severe_overfit_runs": sum(run["overfit_diagnostic"]["flag"] for run in v0_runs),
    }
    differences = {
        key: abs(float(aggregate[key]) - float(expected))
        for key, expected in EXPECTED_V0_AGGREGATE.items()
        if isinstance(expected, float)
    }
    passed = (
        len(v0_runs) == 5
        and all(row["pass"] for row in per_seed)
        and all(value <= 1e-12 for value in differences.values())
        and aggregate["seeds_beating_c0_mrr"] == 5
        and aggregate["severe_overfit_runs"] == 5
    )
    if not passed:
        raise RuntimeError("BLOCKED_RQ1_B_V0_REPRODUCTION_MISMATCH")
    return {
        "schema_version": "rq1b-v0-reproduction-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "scenario": "V0",
        "run_count": len(v0_runs),
        "per_seed_parity": per_seed,
        "expected_aggregate": EXPECTED_V0_AGGREGATE,
        "actual_aggregate": aggregate,
        "aggregate_absolute_differences": differences,
        "absolute_tolerance": 1e-12,
        "v0_runs_reused_as_primary_v0_results": True,
        "final_gold_accessed": False,
    }
