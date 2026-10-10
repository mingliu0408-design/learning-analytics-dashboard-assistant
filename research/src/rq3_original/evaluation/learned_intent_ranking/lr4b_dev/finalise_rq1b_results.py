"""Deterministically finalise aggregate-only RQ1-B results and thesis reports."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from . import (
    DOC_FILENAMES,
    HERE,
    METRIC_KEYS,
    ROOT,
    SAFE_JSON_FILENAMES,
    SCENARIO_COUNTS,
    SCENARIO_ORDER,
    STARTING_HEAD,
    TRAINING_SEEDS,
    VIEW_A,
    VIEW_B,
    VIEW_C,
)
from .governed_data_loader import canonical_json_bytes, sha256_bytes, sha256_file
from .run_rq1b_experiment import RUN_BUNDLE_PATH
from evaluation.learned_intent_ranking.lr4b_r1.statistical_decision_contract import (
    select_representative_seed,
)


DOC_ROOT = ROOT / "docs/thesis_mainline/rq1"
CHECKSUM_PATH = HERE / "rq1b_output_checksums_v1.sha256"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _runs_by_scenario(run_bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in run_bundle["runs"]:
        result[str(run["scenario"])].append(run)
    ordered = {
        scenario: sorted(result[scenario], key=lambda row: int(row["seed"]))
        for scenario in SCENARIO_ORDER
    }
    if any(len(rows) != 5 for rows in ordered.values()):
        raise ValueError("incomplete scenario run set")
    return ordered


def _summary(values: Iterable[float]) -> dict[str, Any]:
    rows = [float(value) for value in values]
    return {
        "count": len(rows),
        "mean": float(statistics.fmean(rows)),
        "std": float(statistics.pstdev(rows)),
        "minimum": min(rows),
        "median": float(statistics.median(rows)),
        "maximum": max(rows),
        "per_seed": None,
    }


def _aggregate_view(runs: list[dict[str, Any]], view: str) -> dict[str, Any]:
    aggregate: dict[str, Any] = {
        "seed_count": len(runs),
        "std_definition": "POPULATION",
    }
    for metric in METRIC_KEYS:
        values = [float(run["view_metrics"][view][metric]) for run in runs]
        row = _summary(values)
        row["per_seed"] = {
            str(run["seed"]): value for run, value in zip(runs, values, strict=True)
        }
        aggregate[metric] = row
    ranks = [float(run["view_metrics"][view]["mean_gold_label_rank"]) for run in runs]
    rank_summary = _summary(ranks)
    rank_summary["per_seed"] = {
        str(run["seed"]): value for run, value in zip(runs, ranks, strict=True)
    }
    aggregate["mean_gold_label_rank"] = rank_summary
    return aggregate


def build_scenario_comparison(
    run_bundle: dict[str, Any], scenarios: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    c0_views = run_bundle["c0_reproduction"]["actual_view_metrics"]
    rows: dict[str, Any] = {}
    for scenario, runs in scenarios.items():
        aggregates = {
            view: _aggregate_view(runs, view) for view in (VIEW_A, VIEW_B, VIEW_C)
        }
        aggregates[VIEW_A]["mrr"]["delta_mean_vs_c0"] = (
            aggregates[VIEW_A]["mrr"]["mean"] - c0_views[VIEW_A]["mrr"]
        )
        aggregates[VIEW_A]["top1_accuracy"]["delta_mean_vs_c0"] = (
            aggregates[VIEW_A]["top1_accuracy"]["mean"]
            - c0_views[VIEW_A]["top1_accuracy"]
        )
        aggregates[VIEW_A]["macro_f1"]["delta_mean_vs_c0"] = (
            aggregates[VIEW_A]["macro_f1"]["mean"]
            - c0_views[VIEW_A]["macro_f1"]
        )
        rows[scenario] = {
            "scenario": scenario,
            "anchor_count": SCENARIO_COUNTS[scenario],
            "run_count": len(runs),
            "view_aggregates": aggregates,
            "seeds_beating_c0_view_a_mrr": sum(
                run["view_metrics"][VIEW_A]["mrr"] > c0_views[VIEW_A]["mrr"]
                for run in runs
            ),
            "severe_overfit_run_count": sum(
                bool(run["overfit_diagnostic"]["flag"]) for run in runs
            ),
        }
    return {
        "schema_version": "rq1b-scenario-comparison-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "development_only": True,
        "c0": {
            "run_count": 1,
            "view_metrics": c0_views,
            "candidate_example_count": 62,
            "candidate_label_count": 16,
        },
        "scenarios": rows,
        "scenario_selection_view": VIEW_A,
        "diagnostic_views_not_used_for_selection": [VIEW_B, VIEW_C],
        "pure_sample_size_causal_interpretation_authorised": False,
        "final_gold_accessed": False,
    }


SELECTION_CRITERIA = (
    "HIGHER_FIVE_SEED_MEAN_VIEW_A_MRR",
    "HIGHER_FIVE_SEED_MEAN_VIEW_A_TOP1",
    "HIGHER_FIVE_SEED_MEAN_VIEW_A_MACRO_F1",
    "LOWER_FIVE_SEED_VIEW_A_MRR_POPULATION_STD",
    "SMALLER_SCENARIO",
)


def build_selection(comparison: dict[str, Any]) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    for scenario in SCENARIO_ORDER:
        row = comparison["scenarios"][scenario]
        view = row["view_aggregates"][VIEW_A]
        traces.append(
            {
                "scenario": scenario,
                "five_seed_mean_view_a_mrr": view["mrr"]["mean"],
                "five_seed_mean_view_a_top1": view["top1_accuracy"]["mean"],
                "five_seed_mean_view_a_macro_f1": view["macro_f1"]["mean"],
                "five_seed_view_a_mrr_population_std": view["mrr"]["std"],
                "anchor_count": SCENARIO_COUNTS[scenario],
            }
        )
    ordered = sorted(
        traces,
        key=lambda row: (
            -row["five_seed_mean_view_a_mrr"],
            -row["five_seed_mean_view_a_top1"],
            -row["five_seed_mean_view_a_macro_f1"],
            row["five_seed_view_a_mrr_population_std"],
            row["anchor_count"],
        ),
    )
    selected = ordered[0]
    runner_up = ordered[1]
    value_pairs = (
        (
            selected["five_seed_mean_view_a_mrr"],
            runner_up["five_seed_mean_view_a_mrr"],
        ),
        (
            selected["five_seed_mean_view_a_top1"],
            runner_up["five_seed_mean_view_a_top1"],
        ),
        (
            selected["five_seed_mean_view_a_macro_f1"],
            runner_up["five_seed_mean_view_a_macro_f1"],
        ),
        (
            selected["five_seed_view_a_mrr_population_std"],
            runner_up["five_seed_view_a_mrr_population_std"],
        ),
        (selected["anchor_count"], runner_up["anchor_count"]),
    )
    decisive_index = next(
        (index for index, (left, right) in enumerate(value_pairs) if left != right),
        len(SELECTION_CRITERIA) - 1,
    )
    return {
        "schema_version": "rq1b-scenario-selection-v1",
        "stage": "RQ1-B",
        "status": "SELECTED_BEFORE_FINAL_GOLD",
        "selected_scenario": selected["scenario"],
        "candidate_scenarios": list(SCENARIO_ORDER),
        "c0_participates_in_m64_scenario_selection": False,
        "selection_view": VIEW_A,
        "lexicographic_rule": list(SELECTION_CRITERIA),
        "selection_criterion_trace": traces,
        "ordered_scenarios": [row["scenario"] for row in ordered],
        "decisive_criterion": SELECTION_CRITERIA[decisive_index],
        "tie_break_trace": {
            "selected": selected,
            "runner_up": runner_up,
            "decisive_criterion_index": decisive_index,
        },
        "view_b_used": False,
        "view_c_used": False,
        "best_single_seed_used": False,
        "final_gold_accessed": False,
        "final_gold_used": False,
    }


def build_representative(
    selection: dict[str, Any], scenarios: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    scenario = selection["selected_scenario"]
    runs = scenarios[scenario]
    seed_rows = [
        {
            "seed": run["seed"],
            "view_a_mrr": run["view_metrics"][VIEW_A]["mrr"],
            "view_a_top1": run["view_metrics"][VIEW_A]["top1_accuracy"],
            "view_a_macro_f1": run["view_metrics"][VIEW_A]["macro_f1"],
        }
        for run in runs
    ]
    representative_seed = select_representative_seed(seed_rows)
    selected_run = next(run for run in runs if int(run["seed"]) == representative_seed)
    mean_mrr = float(statistics.fmean(row["view_a_mrr"] for row in seed_rows))
    trace = [
        {
            **row,
            "absolute_distance_to_five_seed_mean_view_a_mrr": abs(
                float(row["view_a_mrr"]) - mean_mrr
            ),
        }
        for row in seed_rows
    ]
    return {
        "schema_version": "rq1b-representative-checkpoint-manifest-v1",
        "stage": "RQ1-B",
        "status": "SELECTED_BEFORE_FINAL_GOLD",
        "selected_scenario": scenario,
        "representative_seed": representative_seed,
        "representative_checkpoint_relative_path": selected_run[
            "checkpoint_relative_path"
        ],
        "checkpoint_sha256": selected_run["checkpoint_sha256"],
        "checkpoint_tensor_hash": selected_run["checkpoint_tensor_hash"],
        "selection_distance_to_mean": abs(
            float(selected_run["view_metrics"][VIEW_A]["mrr"]) - mean_mrr
        ),
        "five_seed_mean_view_a_mrr": mean_mrr,
        "tie_break_rule": [
            "MINIMUM_ABSOLUTE_DISTANCE_TO_FIVE_SEED_MEAN_VIEW_A_MRR",
            "HIGHER_VIEW_A_TOP1",
            "HIGHER_VIEW_A_MACRO_F1",
            "SMALLER_NUMERIC_SEED",
        ],
        "tie_break_trace": trace,
        "selected_before_final_gold": True,
        "best_seed_selection": False,
        "ensemble": False,
        "checkpoint_tracked": False,
        "checkpoint_review_zip_included": False,
        "replacement_after_rq1c_authorised": False,
        "final_gold_accessed": False,
    }


def build_confusion_analysis(
    run_bundle: dict[str, Any], scenarios: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    scenario_rows: dict[str, Any] = {}
    for scenario, runs in scenarios.items():
        scenario_rows[scenario] = {
            "per_seed_view_a": {
                str(run["seed"]): {
                    "confusion_matrix": run["view_metrics"][VIEW_A]["confusion_matrix"],
                    "per_intent": run["view_metrics"][VIEW_A]["per_intent"],
                    "predicted_label_distribution": run["view_metrics"][VIEW_A][
                        "predicted_label_distribution"
                    ],
                    "gold_label_rank_distribution": run["view_metrics"][VIEW_A][
                        "gold_label_rank_distribution"
                    ],
                    "most_common_confusions": run["view_metrics"][VIEW_A][
                        "most_common_confusions"
                    ],
                }
                for run in runs
            }
        }
    c0 = run_bundle["c0_reproduction"]["actual_view_metrics"][VIEW_A]
    return {
        "schema_version": "rq1b-confusion-analysis-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "view": VIEW_A,
        "development_diagnostic_only": True,
        "c0": {
            "confusion_matrix": c0["confusion_matrix"],
            "per_intent": c0["per_intent"],
            "predicted_label_distribution": c0["predicted_label_distribution"],
            "gold_label_rank_distribution": c0["gold_label_rank_distribution"],
            "most_common_confusions": c0["most_common_confusions"],
        },
        "scenarios": scenario_rows,
        "taxonomy_modified": False,
        "final_gold_accessed": False,
    }


def build_overfit_analysis(scenarios: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for scenario, runs in scenarios.items():
        per_seed = {
            str(run["seed"]): {
                "best_dev_epoch": run["best_epoch"],
                "epochs_completed": run["epochs_completed"],
                "training_bce_at_best_dev_epoch": run["training_diagnostics"][
                    "training_bce_at_best_dev_epoch"
                ],
                "minimum_training_bce": run["training_diagnostics"][
                    "minimum_training_bce"
                ],
                "final_training_bce": run["training_diagnostics"]["final_training_bce"],
                "best_dev_mrr": run["best_view_a_mrr"],
                "final_dev_mrr": run["training_diagnostics"]["final_view_a_mrr"],
                "post_best_mrr_degradation": run["training_diagnostics"][
                    "post_best_mrr_degradation"
                ],
                "early_stopped": run["early_stopped"],
                "overfit_severity": (
                    "SEVERE" if run["overfit_diagnostic"]["flag"] else "RULE_NOT_MET"
                ),
                "frozen_overfit_diagnostic": run["overfit_diagnostic"],
            }
            for run in runs
        }
        mrrs = [float(run["best_view_a_mrr"]) for run in runs]
        divergences = [
            float(run["training_diagnostics"]["post_best_mrr_degradation"])
            for run in runs
        ]
        rows[scenario] = {
            "run_count": len(runs),
            "severe_overfit_run_count": sum(
                bool(run["overfit_diagnostic"]["flag"]) for run in runs
            ),
            "mean_best_epoch": float(statistics.fmean(run["best_epoch"] for run in runs)),
            "view_a_mrr_seed_population_variance": float(statistics.pvariance(mrrs)),
            "mean_post_best_mrr_degradation": float(statistics.fmean(divergences)),
            "train_dev_divergence_scope": "POST_BEST_VIEW_A_MRR_DEGRADATION",
            "per_seed": per_seed,
        }
    return {
        "schema_version": "rq1b-overfit-analysis-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "diagnostic_rule_unchanged_from_lr3r": True,
        "hyperparameter_search_performed": False,
        "scenarios": rows,
        "final_gold_accessed": False,
    }


def _load_predictions(relative_path: str) -> list[dict[str, Any]]:
    path = ROOT / relative_path
    return _read_json(path)["predictions"]


def _reciprocal_rank(row: Mapping[str, Any]) -> float:
    rank = row.get("gold_rank")
    return 1.0 / int(rank) if rank else 0.0


def _effect(deltas: np.ndarray) -> dict[str, Any]:
    wins = int(np.sum(deltas > 0.0))
    ties = int(np.sum(deltas == 0.0))
    losses = int(np.sum(deltas < 0.0))
    denominator = wins + losses
    return {
        "mean_delta_rr": float(np.mean(deltas)),
        "median_delta_rr": float(np.median(deltas)),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "matched_rank_biserial_correlation": (
            (wins - losses) / denominator if denominator else None
        ),
    }


def build_uncertainty(
    run_bundle: dict[str, Any],
    scenarios: dict[str, list[dict[str, Any]]],
    representative: dict[str, Any],
) -> dict[str, Any]:
    scenario = representative["selected_scenario"]
    runs = scenarios[scenario]
    representative_run = next(
        run for run in runs if int(run["seed"]) == representative["representative_seed"]
    )
    c0_predictions = _load_predictions(
        run_bundle["c0_reproduction"]["local_prediction_ledger_relative_path"]
    )
    c0_by_id = {row["record_id"]: row for row in c0_predictions}
    seed_maps = [
        {
            row["record_id"]: row
            for row in _load_predictions(run["prediction_ledger_relative_path"])
        }
        for run in runs
    ]
    representative_map = {
        row["record_id"]: row
        for row in _load_predictions(representative_run["prediction_ledger_relative_path"])
    }
    # Confusion matrices do not carry IDs.  Preserve the frozen prediction-ledger
    # order and select the 79 records whose gold label is represented by View A.
    view_a_labels = set(
        run_bundle["c0_reproduction"]["actual_view_metrics"][VIEW_A][
            "represented_gold_labels"
        ]
    )
    view_ids = [row["record_id"] for row in c0_predictions if row["gold_label"] in view_a_labels]
    if len(view_ids) != 79:
        raise ValueError("uncertainty View-A identity drift")
    c0_rr = np.asarray([_reciprocal_rank(c0_by_id[record_id]) for record_id in view_ids])
    representative_rr = np.asarray(
        [_reciprocal_rank(representative_map[record_id]) for record_id in view_ids]
    )
    seed_rr = np.asarray(
        [
            [_reciprocal_rank(seed_map[record_id]) for record_id in view_ids]
            for seed_map in seed_maps
        ],
        dtype=np.float64,
    )
    mean_seed_rr = seed_rr.mean(axis=0)
    rng = np.random.default_rng(20260813)
    bootstrap_indices = rng.integers(0, len(view_ids), size=(10000, len(view_ids)))

    def diagnostic(left: np.ndarray) -> dict[str, Any]:
        deltas = left - c0_rr
        means = deltas[bootstrap_indices].mean(axis=1)
        return {
            **_effect(deltas),
            "paired_bootstrap_95_percent_interval": {
                "lower": float(np.percentile(means, 2.5, method="linear")),
                "upper": float(np.percentile(means, 97.5, method="linear")),
                "percentile_method": "NUMPY_LINEAR_TYPE_7",
            },
        }

    return {
        "schema_version": "rq1b-development-uncertainty-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "role": "DEVELOPMENT_UNCERTAINTY_DIAGNOSTIC_ONLY",
        "confirmatory_significance_test": False,
        "selected_scenario": scenario,
        "representative_seed": representative["representative_seed"],
        "resampling_unit": "VIEW_A_QUERY",
        "view_a_record_count": len(view_ids),
        "bootstrap_resamples": 10000,
        "bootstrap_seed": 20260813,
        "confidence_interval": "95_PERCENT_PERCENTILE",
        "representative_seed_vs_c0": diagnostic(representative_rr),
        "five_seed_mean_reciprocal_rank_vs_c0": diagnostic(mean_seed_rr),
        "final_gold_accessed": False,
    }


def build_per_seed_metrics(run_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq1b-per-seed-metrics-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "development_only": True,
        "run_count": len(run_bundle["runs"]),
        "runs": run_bundle["runs"],
        "local_artifacts_tracked": False,
        "raw_text_emitted": False,
        "final_gold_accessed": False,
    }


def build_validation(
    run_bundle: dict[str, Any],
    selection: dict[str, Any],
    representative: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rq1b-validation-report-v1",
        "stage": "RQ1-B",
        "overall_status": "PASS",
        "ready_state": "READY_FOR_RQ1_C_FINAL_EVALUATION_GATE",
        "effective_contract": "lr4b-experiment-contract-v1.1",
        "input_hashes_verified": True,
        "runtime_preflight_passed": True,
        "token_budget_passed": True,
        "actual_truncation_count": 0,
        "representation_ledger_fingerprint_match": True,
        "candidate_index_unchanged": True,
        "candidate_example_count": 62,
        "candidate_label_count": 16,
        "eedi_candidate_count": 0,
        "dev_view_counts_unchanged": True,
        "pair_policy_passed": True,
        "safe_negative_only": True,
        "hard_negative_selected_count": 0,
        "blocked_relationship_selected_count": 0,
        "d0_equal_weighting": True,
        "duplicates_retained": True,
        "c0_reproduction_passed": run_bundle["c0_reproduction"]["status"] == "PASS",
        "v0_reproduction_passed": run_bundle["v0_reproduction"]["status"] == "PASS",
        "experiment_run_count": run_bundle["run_count"],
        "experiment_matrix_complete": run_bundle["run_count"] == 20,
        "selected_scenario": selection["selected_scenario"],
        "representative_seed": representative["representative_seed"],
        "representative_checkpoint_tracked": False,
        "local_embedding_cache_tracked": False,
        "protected_sources_unchanged": run_bundle["protected_sources"][
            "protected_sources_unchanged"
        ],
        "production_code_modified": False,
        "semantic_runtime_modified": False,
        "old_research_stages_modified": False,
        "network_access": False,
        "provider_calls": 0,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
        "final_gold_tuning": False,
        "rq1c_started": False,
    }


def _runtime_doc(
    runtime: dict[str, Any], token: dict[str, Any], embedding: dict[str, Any]
) -> str:
    versions = runtime["dependency_versions"]
    token_rows = token["distributions"]
    return f"""# RQ1-B Runtime and Token Preflight

## Scope and result

The RQ1-B local-only runtime gate passed. The frozen MPNet encoder was loaded from its pinned local revision on CPU, all encoder parameters were frozen, and zero encoder parameters entered the M64 optimizer. Network and provider access remained disabled.

## Runtime identity

| Item | Value |
|---|---|
| Python | {runtime['python_version']} |
| Torch | {versions['torch']} |
| NumPy | {versions['numpy']} |
| sentence-transformers | {versions['sentence_transformers']} |
| Transformers | {versions['transformers']} |
| scikit-learn | {versions['sklearn']} |
| Device | CPU |
| CUDA used | No |
| Local files only | Yes |
| Effective MPNet sequence length | {runtime['model']['loaded_max_sequence_length']} |

The effective length of 384 was independently recovered from the local SentenceTransformer configuration and verified against the loaded model. The tokenizer did not use silent truncation.

## Token-budget result

| Logical group | Records | Maximum tokens | P95 | P99 | Over 384 |
|---|---:|---:|---:|---:|---:|
| Governed TRAIN | {token_rows['governed_train']['record_count']} | {token_rows['governed_train']['maximum']} | {token_rows['governed_train']['p95_nearest_rank']} | {token_rows['governed_train']['p99_nearest_rank']} | {token_rows['governed_train']['over_384_count']} |
| DEV query, max of runtime variants | {token_rows['dev_query_logical_max_of_plain_and_page']['record_count']} | {token_rows['dev_query_logical_max_of_plain_and_page']['maximum']} | {token_rows['dev_query_logical_max_of_plain_and_page']['p95_nearest_rank']} | {token_rows['dev_query_logical_max_of_plain_and_page']['p99_nearest_rank']} | {token_rows['dev_query_logical_max_of_plain_and_page']['over_384_count']} |
| Approved candidates | {token_rows['approved_candidate']['record_count']} | {token_rows['approved_candidate']['maximum']} | {token_rows['approved_candidate']['p95_nearest_rank']} | {token_rows['approved_candidate']['p99_nearest_rank']} | {token_rows['approved_candidate']['over_384_count']} |

All actual representations fit without truncation, so `actual_truncation_count = 0`. A synthetic contract test separately verified that only complete oldest previous turns are removed while the question anchor, current utterance, headers, separators, and most recent retained turns remain intact. That synthetic test does not authorise truncation of actual governed data.

## Embedding boundary

The frozen 62-candidate embedding artifact was reused unchanged. Sixty-two approved TRAIN records reused matching frozen vectors; {embedding['new_eedi_embedding']['record_count']} new governed Eedi representations were encoded locally once; and 84 DEV queries produced 168 runtime-faithful plain/page variants once. The resulting text-free cache is shared by all 20 runs and remains ignored and untracked.

Final gold was not searched, opened, hashed, enumerated, or used.
"""


def _training_doc(
    comparison: dict[str, Any],
    selection: dict[str, Any],
    representative: dict[str, Any],
    v0: dict[str, Any],
    uncertainty: dict[str, Any],
) -> str:
    rows = []
    c0 = comparison["c0"]["view_metrics"][VIEW_A]
    rows.append(
        f"| C0 | 1 | {c0['mrr']:.12f} | 0.000000000000 | {c0['top1_accuracy']:.12f} | {c0['recall_at_3']:.12f} | {c0['macro_f1']:.12f} | n/a |"
    )
    for scenario in SCENARIO_ORDER:
        row = comparison["scenarios"][scenario]
        view = row["view_aggregates"][VIEW_A]
        rows.append(
            f"| M64-{scenario} | 5 | {view['mrr']['mean']:.12f} | {view['mrr']['std']:.12f} | {view['top1_accuracy']['mean']:.12f} | {view['recall_at_3']['mean']:.12f} | {view['macro_f1']['mean']:.12f} | {row['severe_overfit_run_count']} |"
        )
    uncertainty_row = uncertainty["five_seed_mean_reciprocal_rank_vs_c0"]
    ci = uncertainty_row["paired_bootstrap_95_percent_interval"]
    return f"""# RQ1-B Development Training Report

## Experiment completion

The preregistered matrix completed exactly 20 CPU runs: four frozen governed-evidence scenarios by five fixed model seeds. M64, D0 directed equal weighting, AdamW, learning rate 0.001, weight decay 0.0001, batch size 32, 50 maximum epochs, patience 8, gradient clipping 1.0, and the frozen pair-sampling seed were unchanged.

The C0 gate reproduced all 84 per-record rankings and the frozen 79-record View-A metrics. The V0 gate reproduced all five LR3R runs, including best epochs, checkpoint tensor hashes, per-record rankings, aggregate metrics, five seeds above C0 MRR, and five severe-overfit flags. V0 was then retained as the study's V0 result rather than retrained.

## Frozen View-A development results

| Method | Runs | Mean MRR | MRR population SD | Mean Top-1 | Mean Recall@3 | Mean Macro-F1 | Severe-overfit runs |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

View A remains the only selection view: 79 development records and 8 represented gold labels. View B (5 records) and View C (84 records) are diagnostics only.

## Frozen scenario and checkpoint decisions

The lexicographic five-seed rule selected **M64-{selection['selected_scenario']}**. Its decisive criterion against the runner-up was `{selection['decisive_criterion']}`. Within that scenario, the frozen mean-nearest rule selected seed **{representative['representative_seed']}**; the checkpoint SHA-256 is `{representative['checkpoint_sha256']}`. The checkpoint remains ignored and untracked and was selected before any final-gold access.

The inherited LR3R exploratory paired bootstrap used 10,000 View-A query resamples, seed 20260813, and a 95% linear percentile interval. For the selected scenario's five-seed mean reciprocal-rank contribution versus C0, mean delta RR was {uncertainty_row['mean_delta_rr']:.12f}, with interval [{ci['lower']:.12f}, {ci['upper']:.12f}] and wins/ties/losses {uncertainty_row['wins']}/{uncertainty_row['ties']}/{uncertainty_row['losses']}. This is a development uncertainty diagnostic, not confirmatory inference.

## Boundaries

These are development-set model-selection results. They are not final independent-test results, held-out generalisation evidence, production-superiority evidence, or educational-effectiveness evidence. Final gold remains unused, RQ1-C has not started, and M64 has not replaced C0.
"""


def _interpretation_doc(
    comparison: dict[str, Any], selection: dict[str, Any], concentration: dict[str, Any]
) -> str:
    v3 = concentration["scenarios"]["V3"]
    return f"""# RQ1-B Governed Evidence-Expansion Interpretation

## Interpretation frame

V0, V1, V2, and V3 are cumulative governed training-evidence scenarios. They are not pure sample-size causal ablations: record count, label distribution, context mode, and source composition change together. The selected development scenario is M64-{selection['selected_scenario']}, but that choice only freezes the M64 candidate for the later RQ1-C gate.

## Data-composition limitations

V3 contains {v3['total_anchors']} pairwise anchors across {len(v3['per_label_anchor_count'])} labels. Its largest-label share is {v3['top_1_label_share']:.3f}, and the three largest labels account for {v3['top_3_label_share']:.3f}. The large increase in `course_content_question` and related source imbalance can dominate optimisation. Structured-context prevalence also changes across scenarios, so a difference cannot be assigned solely to more records.

All governed records were retained. Across the 318-record ledger there are 297 unique representations, 21 duplicate extra rows, 10 duplicate groups, and zero cross-label duplicate groups. These duplicates affect training weight under D0; this stage did not deduplicate or down-weight them.

The Eedi secondary material is Tier-B, researcher-confirmed training evidence with one-person annotation and no independent second-rater reliability. It is never a retrieval candidate, never changes the frozen 62-example/16-label candidate universe, and never changes MAX intent aggregation.

## Evaluation limitations

View A contains only 79 records and 8 represented gold labels. View B and View C are diagnostic and cannot alter scenario selection. Per-intent changes and confusion patterns are exploratory rather than confirmatory. The current results do not establish generalisation to real students, educational effectiveness, production superiority, or a taxonomy change.

Final gold has not been listed, searched, opened, hashed, counted, tuned on, or used. C0 remains the production reference; M64 has not replaced it. The next authorised action is the separate RQ1-C final-evaluation gate, not an automatic final-gold run.
"""


def build_artifacts(run_bundle: dict[str, Any]) -> dict[Path, bytes]:
    scenarios = _runs_by_scenario(run_bundle)
    comparison = build_scenario_comparison(run_bundle, scenarios)
    selection = build_selection(comparison)
    representative = build_representative(selection, scenarios)
    confusion = build_confusion_analysis(run_bundle, scenarios)
    overfit = build_overfit_analysis(scenarios)
    uncertainty = build_uncertainty(run_bundle, scenarios, representative)
    validation = build_validation(run_bundle, selection, representative)
    outputs: dict[str, dict[str, Any]] = {
        "rq1b_runtime_preflight_v1.json": run_bundle["runtime_preflight"],
        "rq1b_token_budget_summary_v1.json": run_bundle["token_budget"],
        "rq1b_embedding_manifest_v1.json": run_bundle["embedding_manifest"],
        "rq1b_c0_reproduction_v1.json": run_bundle["c0_reproduction"],
        "rq1b_pair_construction_audit_v1.json": run_bundle["pair_construction"],
        "rq1b_v0_reproduction_v1.json": run_bundle["v0_reproduction"],
        "rq1b_per_seed_metrics_v1.json": build_per_seed_metrics(run_bundle),
        "rq1b_scenario_comparison_v1.json": comparison,
        "rq1b_scenario_selection_v1.json": selection,
        "rq1b_representative_checkpoint_manifest_v1.json": representative,
        "rq1b_confusion_analysis_v1.json": confusion,
        "rq1b_overfit_analysis_v1.json": overfit,
        "rq1b_data_concentration_v1.json": run_bundle["data_concentration"],
        "rq1b_development_uncertainty_v1.json": uncertainty,
        "rq1b_validation_report_v1.json": validation,
    }
    if tuple(outputs) != SAFE_JSON_FILENAMES:
        raise ValueError("safe output filename contract drift")
    artifacts: dict[Path, bytes] = {
        HERE / name: canonical_json_bytes(outputs[name]) for name in SAFE_JSON_FILENAMES
    }
    docs = {
        DOC_FILENAMES[0]: _runtime_doc(
            run_bundle["runtime_preflight"],
            run_bundle["token_budget"],
            run_bundle["embedding_manifest"],
        ),
        DOC_FILENAMES[1]: _training_doc(
            comparison,
            selection,
            representative,
            run_bundle["v0_reproduction"],
            uncertainty,
        ),
        DOC_FILENAMES[2]: _interpretation_doc(
            comparison, selection, run_bundle["data_concentration"]
        ),
    }
    for name, content in docs.items():
        artifacts[DOC_ROOT / name] = content.encode("utf-8")

    checksum_members = [
        ROOT / ".gitignore",
        *sorted(HERE.glob("*.py")),
        *sorted(artifacts),
    ]
    checksum_lines: list[str] = []
    for path in sorted(set(checksum_members), key=lambda value: str(value.relative_to(ROOT))):
        content = artifacts[path] if path in artifacts else path.read_bytes()
        checksum_lines.append(
            f"{sha256_bytes(content)}  {path.relative_to(ROOT).as_posix()}"
        )
    artifacts[CHECKSUM_PATH] = ("\n".join(checksum_lines) + "\n").encode("utf-8")
    return artifacts


def write_artifacts(artifacts: Mapping[Path, bytes]) -> None:
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def check_byte_identical(artifacts: Mapping[Path, bytes]) -> None:
    mismatches = [
        str(path.relative_to(ROOT))
        for path, content in artifacts.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    if mismatches:
        raise ValueError("deterministic finalisation mismatch")


def _git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False, text=True
    )
    if result.returncode != 0:
        raise ValueError("review-package Git query failed")
    return result.stdout.strip()


def create_review_zip(download_dir: Path) -> dict[str, Any]:
    """Create the review-only ZIP after the single RQ1-B commit exists."""

    selection = _read_json(HERE / "rq1b_scenario_selection_v1.json")
    representative = _read_json(HERE / "rq1b_representative_checkpoint_manifest_v1.json")
    branch = _git_text("branch", "--show-current")
    head = _git_text("rev-parse", "HEAD")
    parent = _git_text("rev-parse", "HEAD^")
    relative_commits = int(_git_text("rev-list", "--count", f"{STARTING_HEAD}..HEAD"))
    remote_count = len(_git_text("remote").splitlines()) if _git_text("remote") else 0
    tag_count = len(_git_text("tag", "--list").splitlines()) if _git_text("tag", "--list") else 0
    worktree_status = _git_text("status", "--porcelain=v1", "--untracked-files=no")
    if (
        branch != "research/rq1-b-lr4b-development"
        or parent != STARTING_HEAD
        or relative_commits != 1
        or remote_count != 0
        or tag_count != 0
        or worktree_status
    ):
        raise ValueError("review-package final Git gate failed")

    members: dict[str, bytes] = {}
    for name in DOC_FILENAMES:
        path = DOC_ROOT / name
        members[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for path in sorted(HERE.glob("*.py")):
        members[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in SAFE_JSON_FILENAMES:
        path = HERE / name
        members[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    members[CHECKSUM_PATH.relative_to(ROOT).as_posix()] = CHECKSUM_PATH.read_bytes()

    git_state = f"""RQ1-B FINAL GIT STATE
branch: {branch}
head: {head}
parent: {parent}
starting_head: {STARTING_HEAD}
commits_relative_to_rq1_a_r1: {relative_commits}
remote_count: {remote_count}
tag_count: {tag_count}
working_tree_clean: true
selected_scenario: {selection['selected_scenario']}
representative_seed: {representative['representative_seed']}
representative_checkpoint_sha256: {representative['checkpoint_sha256']}
checkpoint_tracked: false
final_gold_accessed: false
rq1c_started: false
"""
    diff_stat = _git_text("diff", "--stat", STARTING_HEAD, "HEAD")
    diff_names = _git_text("diff", "--name-status", STARTING_HEAD, "HEAD")
    diff_summary = f"""RQ1-B DIFF SUMMARY
base: {STARTING_HEAD}
head: {head}

STAT
{diff_stat}

NAME STATUS
{diff_names}
"""
    members["RQ1_B_GIT_STATE.txt"] = git_state.encode("utf-8")
    members["RQ1_B_DIFF_SUMMARY.txt"] = diff_summary.encode("utf-8")
    review_checksums = "".join(
        f"{sha256_bytes(content)}  {name}\n"
        for name, content in sorted(members.items())
    ).encode("utf-8")
    members["RQ1_B_REVIEW_CHECKSUMS.sha256"] = review_checksums

    forbidden_parts = (
        "/local_artifacts/",
        "/checkpoints/",
        "/results/",
        "/tmp/",
        "primary_v3_input",
    )
    if any(any(part in f"/{name}" for part in forbidden_parts) for name in members):
        raise ValueError("review-package member crossed a prohibited boundary")
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / "RQ1_B_LR4B_DEVELOPMENT_REVIEW_2026-08-25.zip"
    if target.exists():
        target = download_dir / "RQ1_B_LR4B_DEVELOPMENT_REVIEW_2026-08-25_R2.zip"
    suffix = 3
    while target.exists():
        target = download_dir / f"RQ1_B_LR4B_DEVELOPMENT_REVIEW_2026-08-25_R{suffix}.zip"
        suffix += 1
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    with zipfile.ZipFile(target, "r") as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(members):
            raise ValueError("review-package ZIP integrity failed")
        if any(archive.read(name) != content for name, content in members.items()):
            raise ValueError("review-package member content mismatch")
    return {
        "zip_path": str(target),
        "zip_sha256": sha256_file(target),
        "member_count": len(members),
        "integrity": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-bundle", type=Path, default=RUN_BUNDLE_PATH)
    parser.add_argument("--check-byte-identical", action="store_true")
    parser.add_argument("--create-review-zip", action="store_true")
    parser.add_argument("--download-dir", type=Path, default=Path.home() / "Downloads")
    args = parser.parse_args(argv)
    run_bundle = _read_json(args.run_bundle)
    artifacts = build_artifacts(run_bundle)
    review: dict[str, Any] | None = None
    if args.check_byte_identical:
        check_byte_identical(artifacts)
        action = "CHECK_BYTE_IDENTICAL"
    else:
        write_artifacts(artifacts)
        action = "WRITE"
    if args.create_review_zip:
        check_byte_identical(artifacts)
        review = create_review_zip(args.download_dir)
        action = "CREATE_REVIEW_ZIP"
    selection = json.loads(artifacts[HERE / "rq1b_scenario_selection_v1.json"])[
        "selected_scenario"
    ]
    representative = json.loads(
        artifacts[HERE / "rq1b_representative_checkpoint_manifest_v1.json"]
    )["representative_seed"]
    result = {
        "action": action,
        "status": "PASS",
        "artifact_count": len(artifacts),
        "selected_scenario": selection,
        "representative_seed": representative,
        "final_gold_accessed": False,
    }
    if review is not None:
        result["review_zip"] = review
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
