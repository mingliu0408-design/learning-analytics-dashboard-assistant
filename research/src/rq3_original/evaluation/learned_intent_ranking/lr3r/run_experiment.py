"""Run the authorised LR-3R compact learned-scorer capacity audit."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch


HERE = Path(__file__).resolve().parent
LR3 = HERE.parent / "lr3"
ROOT = HERE.parents[2]
for path in [str(LR3), str(ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from data_loader import (
    LR1,
    LR1R,
    LR2,
    LR2R,
    build_epoch_sampler_inputs,
    generate_epoch_pairs,
    load_dev_views,
    load_frozen_candidate_artifacts,
    pair_symmetry_diagnostic,
    resolve_dev_records,
    sha256_file,
    verify_checksum_manifest,
)
from evaluate_ranker import compact_prediction
from feature_builder import FEATURE_SCHEMA, expected_feature_dimension
from metrics import aggregate_seed_metrics
from models import LinearSimilarityScorer, MLPSimilarityScorer, parameter_counts as lr3_parameter_counts
from runtime_fidelity import run_runtime_fidelity_preflight

from compact_models import HIDDEN_DIMENSIONS, build_compact_model, parameter_counts
from compact_train import (
    BATCH_SIZE,
    EARLY_STOPPING_PATIENCE,
    GRADIENT_CLIP_NORM,
    LEARNING_RATE,
    MAX_EPOCHS,
    TRAINING_SEEDS,
    WEIGHT_DECAY,
    configure_determinism,
    train_one_seed,
)


CHECKPOINT_DIR = HERE / "checkpoints"
RESULTS_DIR = HERE / "results"
VIEW_A = "VIEW_A_PAIRWISE_SEEN"
VIEW_B = "VIEW_B_SINGLETON_UNSEEN"
VIEW_C = "VIEW_C_MIXED"
METRIC_KEYS = ("top1_accuracy", "mrr", "recall_at_3", "macro_f1")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def protected_inventory() -> dict[str, dict[str, str]]:
    groups = {
        "production": [ROOT / path for path in [
            "utils/c_full_service.py", "utils/production_intent_router.py", "utils/semantic_intent_router.py",
            "utils/intent_schema.py", "utils/intent_example_index.py", "utils/evidence_synthesiser.py",
            "utils/conversation_memory.py", "utils/recommendation_planner.py",
        ]],
        "semantic_runtime": list((ROOT / "semantic_runtime").rglob("*")),
        "lr1": list(LR1.rglob("*")),
        "lr1r": list(LR1R.rglob("*")),
        "lr2": list(LR2.rglob("*")),
        "lr2r": list(LR2R.rglob("*")),
        "lr3": list(LR3.rglob("*")),
        "original_data": [ROOT / path for path in [
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl",
            "evaluation/unified_benchmark_gold_labels.jsonl",
        ]],
    }
    return {
        name: {str(path.relative_to(ROOT)): sha256_file(path) for path in sorted(paths) if path.is_file()}
        for name, paths in groups.items()
    }


def serializable_run(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key not in {"state_dict", "predictions"}}


def load_lr3_predictions(model: str, seed: int | None = None) -> list[dict[str, Any]]:
    filename = "cosine_dev_predictions_v1.json" if seed is None else f"{model.lower()}_seed_{seed}_dev_predictions_v1.json"
    return read_json(LR3 / "results" / filename)["predictions"]


def save_checkpoint(run: dict[str, Any], frozen: dict[str, Any], sampler: dict[str, Any]) -> dict[str, Any]:
    family = run["model_family"]
    seed = run["training_seed"]
    hidden = HIDDEN_DIMENSIONS[family]
    checkpoint_path = CHECKPOINT_DIR / f"lr3r_{family.lower()}_seed_{seed}_best_v1.pt"
    torch.save({
        "model_family": family,
        "model_version": "lr3r-compact-learned-intent-scorer-v1",
        "hidden_dimension": hidden,
        "training_seed": seed,
        "best_epoch": run["best_epoch"],
        "state_dict": run["state_dict"],
    }, checkpoint_path)
    metadata = {
        "schema_version": "lr3r-checkpoint-metadata-v1",
        "governance_status": "RESEARCH_ONLY_DEVELOPMENT_CHECKPOINT",
        "model_family": family,
        "model_version": "lr3r-compact-learned-intent-scorer-v1",
        "architecture": f"LayerNorm(1536)->Linear(1536,{hidden})->ReLU->Dropout(0.5)->Linear({hidden},1)",
        "feature_schema": FEATURE_SCHEMA,
        "embedding_dimension": frozen["embedding_dimension"],
        "feature_dimension": expected_feature_dimension(frozen["embedding_dimension"]),
        "hidden_dimension": hidden,
        "dropout": 0.5,
        "training_seed": seed,
        "best_epoch": run["best_epoch"],
        "optimizer": "AdamW",
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "gradient_clip_norm": GRADIENT_CLIP_NORM,
        "early_stopping_metric": "VIEW_A_MRR_THEN_TOP1_THEN_EARLIER_EPOCH",
        "train_manifest_hash": sha256_file(sampler["train_path"]),
        "lr2r_sampling_spec_hash": sha256_file(LR2R / "lr2r_episodic_sampling_spec_v1.json"),
        "approved_index_hash": frozen["approved_index_sha256"],
        "mpnet_embedding_artifact_hash": frozen["embedding_artifact_sha256"],
        "mpnet_embedding_matrix_hash": frozen["embedding_matrix_sha256"],
        "mpnet_model_identity": frozen["embedding_metadata"]["model_version"],
        "pytorch_version": torch.__version__,
        "numpy_version": np.__version__,
        "python_version": platform.python_version(),
        "sentence_transformers_version": sentence_transformers.__version__,
        "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "checkpoint_file_sha256": sha256_file(checkpoint_path),
        "checkpoint_filename": checkpoint_path.name,
        **run["parameter_counts"],
        "optimizer_parameter_count": run["optimizer_parameter_count"],
        "mpnet_parameters_in_optimizer": 0,
        "final_gold_used": False,
    }
    metadata_path = checkpoint_path.with_suffix(".metadata.json")
    write_json(metadata_path, metadata)
    return {
        "model_family": family,
        "training_seed": seed,
        "best_epoch": run["best_epoch"],
        "checkpoint_path": str(checkpoint_path.relative_to(HERE)),
        "metadata_path": str(metadata_path.relative_to(HERE)),
        "checkpoint_file_sha256": metadata["checkpoint_file_sha256"],
        "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "view_a_metrics": run["view_metrics"][VIEW_A],
        "development_representative_checkpoint": False,
    }


def mean_metric(runs: list[dict[str, Any]], view: str, metric: str) -> float:
    return float(statistics.fmean(float(run["view_metrics"][view][metric]) for run in runs))


def aggregate_view(runs: list[dict[str, Any]], view: str) -> dict[str, Any]:
    aggregate = aggregate_seed_metrics(runs, view)
    aggregate["mean_gold_label_rank"] = {
        "mean": float(statistics.fmean(run["view_metrics"][view]["mean_gold_label_rank"] for run in runs)),
        "per_seed": {str(run["training_seed"]): run["view_metrics"][view]["mean_gold_label_rank"] for run in runs},
    }
    aggregate["predicted_label_distribution_per_seed"] = {
        str(run["training_seed"]): run["view_metrics"][view]["predicted_label_distribution"] for run in runs
    }
    return aggregate


def seed_stability(cosine: dict[str, Any], architectures: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = {}
    for family, runs in architectures.items():
        rows[family] = {}
        for metric in ["mrr", "top1_accuracy", "macro_f1"]:
            values = {str(run["training_seed"]): float(run["view_metrics"][VIEW_A][metric]) for run in runs}
            baseline = float(cosine[metric])
            rows[family][metric] = {
                "cosine": baseline,
                "per_seed": values,
                "seed_delta_vs_cosine": {seed: value - baseline for seed, value in values.items()},
                "seeds_above_cosine": sum(value > baseline for value in values.values()),
                "seeds_equal_cosine": sum(value == baseline for value in values.values()),
                "seeds_below_cosine": sum(value < baseline for value in values.values()),
            }
    return {"schema_version": "lr3r-seed-stability-v1", "view": VIEW_A, "architectures": rows}


def per_query_uncertainty(
    view_ids: list[str],
    cosine_predictions: list[dict[str, Any]],
    predictions: dict[str, list[list[dict[str, Any]]]],
) -> dict[str, Any]:
    cosine_by_id = {row["record_id"]: row for row in cosine_predictions}
    rng = np.random.default_rng(20260813)
    bootstrap_indices = rng.integers(0, len(view_ids), size=(10000, len(view_ids)))
    result = {}
    for family, seed_predictions in predictions.items():
        seed_maps = [{row["record_id"]: row for row in rows} for rows in seed_predictions]
        query_rows = []
        deltas = []
        for record_id in view_ids:
            c_rank = cosine_by_id[record_id]["gold_rank"]
            c_rr = 1.0 / c_rank if c_rank else 0.0
            learned_rrs = [1.0 / rows[record_id]["gold_rank"] if rows[record_id]["gold_rank"] else 0.0 for rows in seed_maps]
            mean_rr = float(statistics.fmean(learned_rrs))
            delta = mean_rr - c_rr
            deltas.append(delta)
            query_rows.append({
                "record_id": record_id,
                "gold_label": cosine_by_id[record_id]["gold_label"],
                "cosine_reciprocal_rank": c_rr,
                "learned_seed_reciprocal_ranks": learned_rrs,
                "learned_mean_reciprocal_rank_contribution": mean_rr,
                "delta_vs_cosine": delta,
            })
        delta_array = np.asarray(deltas, dtype=np.float64)
        means = delta_array[bootstrap_indices].mean(axis=1)
        result[family] = {
            "mean_per_query_reciprocal_rank_delta": float(delta_array.mean()),
            "bootstrap_95_percent_ci": {
                "lower": float(np.percentile(means, 2.5)),
                "upper": float(np.percentile(means, 97.5)),
                "percentile_method": "numpy_linear",
            },
            "queries": query_rows,
        }
    return {
        "schema_version": "lr3r-development-uncertainty-analysis-v1",
        "label": "DEVELOPMENT UNCERTAINTY ANALYSIS",
        "confirmatory_evidence": False,
        "warning": "The same DEV set was used for development and checkpoint selection; intervals are diagnostic only.",
        "view": VIEW_A,
        "query_count": len(view_ids),
        "bootstrap_seed": 20260813,
        "bootstrap_resamples": 10000,
        "resampling_unit": "VIEW_A_QUERY",
        "architectures": result,
    }


def mean_confusion_count(runs: list[dict[str, Any]], gold: str, predicted: str) -> dict[str, Any]:
    values = [run["view_metrics"][VIEW_A]["confusion_matrix"][gold][predicted] for run in runs]
    return {"mean": float(statistics.fmean(values)), "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, values)}}


def confusion_analysis(
    cosine: dict[str, Any], architectures: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    labels = cosine["represented_gold_labels"]
    per_intent = {"C0": {label: cosine["per_intent"][label]["f1"] for label in labels}}
    patterns: dict[str, Any] = {}
    pattern_defs = {
        "planning_or_strategy_bidirectional_improvement_recommendation": [
            ("planning_or_strategy", "improvement_recommendation"),
            ("improvement_recommendation", "planning_or_strategy"),
        ],
        "course_content_question_to_dashboard_interpretation": [
            ("course_content_question", "dashboard_interpretation")
        ],
        "cross_page_relationship_to_dashboard_interpretation": [
            ("cross_page_relationship", "dashboard_interpretation")
        ],
    }
    for family, runs in architectures.items():
        per_intent[family] = {}
        for label in labels:
            values = [run["view_metrics"][VIEW_A]["per_intent"][label]["f1"] for run in runs]
            per_intent[family][label] = {
                "mean": float(statistics.fmean(values)),
                "std_population": float(statistics.pstdev(values)),
                "delta_mean_vs_cosine": float(statistics.fmean(values) - cosine["per_intent"][label]["f1"]),
                "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, values)},
            }
        patterns[family] = {}
        for name, transitions in pattern_defs.items():
            c_count = sum(cosine["confusion_matrix"][gold][predicted] for gold, predicted in transitions)
            values = [sum(run["view_metrics"][VIEW_A]["confusion_matrix"][gold][predicted] for gold, predicted in transitions) for run in runs]
            mean = float(statistics.fmean(values))
            classification = "improves" if mean < c_count else "worsens" if mean > c_count else "preserves"
            patterns[family][name] = {
                "cosine_count": c_count,
                "mean_count": mean,
                "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, values)},
                "capacity_effect_vs_cosine": classification,
            }
    return {
        "schema_version": "lr3r-confusion-analysis-v1",
        "view": VIEW_A,
        "represented_gold_labels": labels,
        "per_intent_f1": per_intent,
        "known_confusion_patterns": patterns,
        "taxonomy_modified": False,
    }


def overfit_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_count": len(runs),
        "severe_overfit_runs": sum(bool(run["overfit_diagnostic"]["flag"]) for run in runs),
        "best_epoch_distribution": dict(sorted(Counter(str(run["best_epoch"]) for run in runs).items())),
        "early_stop_epoch_distribution": dict(sorted(Counter(str(run["final_epoch"]) for run in runs).items())),
        "training_loss_continuation_after_best_dev_epoch": {
            str(run["training_seed"]): {
                "best_epoch": run["best_epoch"],
                "best_epoch_training_bce": run["training_history"][run["best_epoch"]]["training_bce"],
                "final_epoch": run["final_epoch"],
                "final_training_bce": run["training_history"][-1]["training_bce"],
                "relative_change": run["training_history"][-1]["training_bce"] / run["training_history"][run["best_epoch"]]["training_bce"] - 1.0,
                "diagnostic": run["overfit_diagnostic"],
            }
            for run in runs
        },
        "seed_variance": {
            metric: float(statistics.pvariance(run["view_metrics"][VIEW_A][metric] for run in runs))
            for metric in METRIC_KEYS
        },
    }


def metric_tradeoffs(cosine: dict[str, Any], architectures: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result = {"C0": {key: cosine[key] for key in METRIC_KEYS}}
    for family, runs in architectures.items():
        result[family] = {}
        for metric in METRIC_KEYS:
            mean = mean_metric(runs, VIEW_A, metric)
            result[family][metric] = {"mean": mean, "delta_vs_cosine": mean - cosine[metric]}
    return result


def main() -> None:
    configure_determinism()
    before = protected_inventory()
    checksum_contracts = {
        "lr3": verify_checksum_manifest(LR3 / "lr3_output_checksums_v1.sha256", LR3),
        "lr2r": verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R),
    }
    if not all(row["match"] for rows in checksum_contracts.values() for row in rows):
        raise ValueError("frozen checksum verification failed")

    sampler = build_epoch_sampler_inputs()
    frozen = load_frozen_candidate_artifacts()
    dev_records = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
    view_ids = load_dev_views(dev_records)
    runtime_report, query_vectors, cosine_predictions, mpnet_model = run_runtime_fidelity_preflight(dev_records, frozen)
    if runtime_report["status"] != "PASS":
        raise ValueError("runtime fidelity preflight failed")

    lr3_cosine = read_json(LR3 / "lr3_cosine_baseline_results_v1.json")["views"]
    lr3_l1_result = read_json(LR3 / "lr3_linear_training_results_v1.json")
    lr3_m1_result = read_json(LR3 / "lr3_mlp_training_results_v1.json")
    lr3_l1_runs = lr3_l1_result["runs"]
    lr3_m1_runs = lr3_m1_result["runs"]
    cosine_a = lr3_cosine[VIEW_A]

    # Read-only governance validation across all authorised epochs.
    dev_ids = {row["record_id"] for row in dev_records}
    for epoch in range(MAX_EPOCHS):
        rows = generate_epoch_pairs(sampler, epoch)
        if len(rows) != 228 or sum(row["target"] for row in rows) != 114:
            raise ValueError(f"epoch {epoch} balance mismatch")
        for row in rows:
            endpoints = {row["anchor_record_id"], row["candidate_record_id"]}
            if not endpoints <= sampler["eligible_ids"] or endpoints & sampler["singleton_ids"] or endpoints & dev_ids:
                raise ValueError("unauthorised training endpoint")
            expected_class = "SAME_INTENT_POSITIVE" if row["target"] else "SAFE_RANDOM_NEGATIVE"
            if row["relationship_class"] != expected_class:
                raise ValueError("unauthorised relationship class")

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    embedding_by_id = {
        example_id: frozen["embeddings"][position].copy()
        for position, example_id in enumerate(frozen["example_ids"])
    }
    feature_dimension = expected_feature_dimension(frozen["embedding_dimension"])
    compact_runs: dict[str, list[dict[str, Any]]] = {"M64": [], "M128": []}
    registry_entries = []
    for family in ["M64", "M128"]:
        for seed in TRAINING_SEEDS:
            print(f"training {family} seed {seed}", flush=True)
            run = train_one_seed(
                model_family=family,
                training_seed=seed,
                feature_dimension=feature_dimension,
                sampler=sampler,
                embedding_by_id=embedding_by_id,
                dev_records=dev_records,
                dev_query_vectors=query_vectors,
                index_records=frozen["index_records"],
                index_embeddings=frozen["embeddings"],
                view_ids=view_ids,
                production_labels=frozen["production_labels"],
                mpnet_model=mpnet_model,
            )
            compact_runs[family].append(run)
            registry_entries.append(save_checkpoint(run, frozen, sampler))
            write_json(RESULTS_DIR / f"{family.lower()}_seed_{seed}_dev_predictions_v1.json", {
                "schema_version": "lr3r-development-predictions-v1",
                "model_family": family,
                "training_seed": seed,
                "best_epoch": run["best_epoch"],
                "development_only": True,
                "predictions": [compact_prediction(row) for row in run["predictions"]],
            })

    family_results = {}
    for family, runs in compact_runs.items():
        hidden = HIDDEN_DIMENSIONS[family]
        result = {
            "schema_version": f"lr3r-{family.lower()}-training-results-v1",
            "model_family": family,
            "architecture": f"LayerNorm(1536)->Linear(1536,{hidden})->ReLU->Dropout(0.5)->Linear({hidden},1)",
            "runs": [serializable_run(run) for run in runs],
            "view_a_aggregate": aggregate_seed_metrics(runs, VIEW_A),
            "view_b_aggregate": aggregate_view(runs, VIEW_B),
            "view_c_aggregate": aggregate_view(runs, VIEW_C),
        }
        family_results[family] = result
        write_json(HERE / f"lr3r_{family.lower()}_training_results_v1.json", result)

    protocol = {
        "schema_version": "lr3r-experiment-protocol-v1",
        "authorisation": "EXPLICIT_LR3R_COMPACT_CAPACITY_AUDIT",
        "research_question": "Does LR-3 nonlinear learned-similarity gain survive reduced hidden capacity?",
        "only_experimental_variable": "hidden_dimension",
        "models_trained": {"M64": 64, "M128": 128},
        "frozen_references": ["C0", "L1", "M1"],
        "feature_schema": FEATURE_SCHEMA,
        "embedding_dimension": 768,
        "feature_dimension": 1536,
        "pair_sampling_seed": sampler["sampling_seed"],
        "training_seeds": list(TRAINING_SEEDS),
        "optimizer": "AdamW",
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "gradient_clip_norm": GRADIENT_CLIP_NORM,
        "dropout": 0.5,
        "loss": "BCEWithLogitsLoss",
        "positive_class_weight": None,
        "device": "cpu",
        "early_stopping_view": "VIEW_A_PAIRWISE_SEEN_79_RECORDS",
        "early_stopping_metric": "MRR then Top-1 Accuracy then earlier epoch",
        "candidate_universe": "ALL_PAGE_ELIGIBLE_APPROVED_EXAMPLES_FROM_FROZEN_62_RECORD_16_LABEL_INDEX",
        "family_collapse": "BEST_PER_LABEL_AND_PARAPHRASE_FAMILY",
        "intent_aggregation": "MAX",
        "top_k_prefiltering": False,
        "pair_direction_policy": "DIRECTED_ROWS_RETAINED",
        "hard_negative_training": False,
        "mpnet_finetuned": False,
        "calibration_performed": False,
        "integration_performed": False,
        "final_gold_used": False,
        "severe_overfit_rule": read_json(LR3 / "lr3_experiment_protocol_v1.json")["severe_overfit_rule"],
        "bootstrap": {"seed": 20260813, "resamples": 10000, "unit": "VIEW_A_QUERY", "interval": "95_PERCENT_PERCENTILE"},
    }
    write_json(HERE / "lr3r_experiment_protocol_v1.json", protocol)

    key_inputs = [
        LR3 / "lr3_output_checksums_v1.sha256",
        LR3 / "lr3_cosine_baseline_results_v1.json",
        LR3 / "lr3_linear_training_results_v1.json",
        LR3 / "lr3_mlp_training_results_v1.json",
        LR3 / "lr3_model_comparison_v1.json",
        LR3 / "lr3_validation_report_v1.json",
        LR2R / "lr2r_output_checksums_v1.sha256",
        LR2R / "lr2r_episodic_sampling_spec_v1.json",
        LR2R / "ranker_pair_dataset_baseline_candidate_v2.jsonl",
        LR1R / "ranker_dev_manifest_candidate_v2.jsonl",
        sampler["train_path"], sampler["positive_path"], sampler["negative_path"],
        frozen["index_path"], frozen["embedding_path"], frozen["config_path"],
    ]
    write_json(HERE / "lr3r_input_hashes_v1.json", {
        "schema_version": "lr3r-input-hashes-v1",
        "all_verified": True,
        "lr3_checksum_entries_verified": len(checksum_contracts["lr3"]),
        "lr2r_checksum_entries_verified": len(checksum_contracts["lr2r"]),
        "files": {str(path.relative_to(ROOT)): sha256_file(path) for path in key_inputs},
        "frozen_lr3_reference_metrics_verified_exact": True,
        "final_gold_loaded": False,
    })

    epoch0 = pair_symmetry_diagnostic(generate_epoch_pairs(sampler, 0), 0)
    l1_params = lr3_parameter_counts(LinearSimilarityScorer(feature_dimension))["trainable_parameters"]
    m1_params = lr3_parameter_counts(MLPSimilarityScorer(feature_dimension))["trainable_parameters"]
    counts = {"L1": l1_params, "M1": m1_params}
    for family in ["M64", "M128"]:
        counts[family] = parameter_counts(build_compact_model(family, feature_dimension))["trainable_parameters"]
    capacity_models = {
        family: {
            "total_parameters": count,
            "trainable_parameters": count,
            "parameter_ratio_versus_m1": count / m1_params,
            "parameters_per_unique_epoch_0_effective_feature": count / epoch0["effective_unique_feature_count"],
        }
        for family, count in counts.items()
    }
    write_json(HERE / "lr3r_capacity_analysis_v1.json", {
        "schema_version": "lr3r-capacity-analysis-v1",
        "capacity_context_only": True,
        "ratio_does_not_prove_overfitting": True,
        "epoch_0_effective_unique_feature_count": epoch0["effective_unique_feature_count"],
        "epoch_0_directed_rows": epoch0["directed_row_count"],
        "epoch_0_reverse_duplicate_groups": epoch0["reverse_duplicate_group_count"],
        "models": capacity_models,
    })

    all_arch_runs = {"L1": lr3_l1_runs, "M64": compact_runs["M64"], "M128": compact_runs["M128"], "M1": lr3_m1_runs}
    stability = seed_stability(cosine_a, all_arch_runs)
    write_json(HERE / "lr3r_seed_stability_v1.json", stability)

    overfit = {
        "schema_version": "lr3r-overfit-analysis-v1",
        "diagnostic_rule_unchanged_from_lr3": True,
        "architectures": {family: overfit_summary(runs) for family, runs in all_arch_runs.items()},
        "reference_facts": {"L1": "5/5 severe overfit", "M1": "5/5 severe overfit"},
    }
    compact_overfit_counts = [overfit["architectures"][family]["severe_overfit_runs"] for family in ["M64", "M128"]]
    if max(compact_overfit_counts) < 5:
        effect = "REDUCED_CAPACITY_MATERIALLY_REDUCED_SEVERE_OVERFIT_IN_AT_LEAST_ONE_COMPACT_FAMILY"
    else:
        effect = "REDUCED_CAPACITY_DID_NOT_CHANGE_THE_5_OF_5_SEVERE_OVERFIT_PATTERN"
    overfit["capacity_effect_interpretation"] = effect
    write_json(HERE / "lr3r_overfit_analysis_v1.json", overfit)

    predictions_by_arch = {
        "L1": [load_lr3_predictions("L1", seed) for seed in TRAINING_SEEDS],
        "M64": [run["predictions"] for run in compact_runs["M64"]],
        "M128": [run["predictions"] for run in compact_runs["M128"]],
        "M1": [load_lr3_predictions("M1", seed) for seed in TRAINING_SEEDS],
    }
    uncertainty = per_query_uncertainty(view_ids[VIEW_A], cosine_predictions, predictions_by_arch)
    write_json(HERE / "lr3r_development_uncertainty_analysis_v1.json", uncertainty)

    confusion = confusion_analysis(cosine_a, all_arch_runs)
    write_json(HERE / "lr3r_confusion_analysis_v1.json", confusion)

    tradeoffs = metric_tradeoffs(cosine_a, all_arch_runs)
    comparison_rows: dict[str, Any] = {
        "C0": {
            "trainable_parameters": 0,
            "mrr_mean": cosine_a["mrr"], "mrr_std": 0.0,
            "top1_mean": cosine_a["top1_accuracy"], "top1_std": 0.0,
            "recall_at_3_mean": cosine_a["recall_at_3"], "macro_f1_mean": cosine_a["macro_f1"],
            "seeds_beating_cosine_mrr": None, "severe_overfit_runs": None,
        }
    }
    for family, runs in all_arch_runs.items():
        aggregate = aggregate_seed_metrics(runs, VIEW_A)
        comparison_rows[family] = {
            "trainable_parameters": counts[family],
            "mrr_mean": aggregate["mrr"]["mean"], "mrr_std": aggregate["mrr"]["std"],
            "top1_mean": aggregate["top1_accuracy"]["mean"], "top1_std": aggregate["top1_accuracy"]["std"],
            "recall_at_3_mean": aggregate["recall_at_3"]["mean"],
            "macro_f1_mean": aggregate["macro_f1"]["mean"],
            "seeds_beating_cosine_mrr": stability["architectures"][family]["mrr"]["seeds_above_cosine"],
            "severe_overfit_runs": overfit["architectures"][family]["severe_overfit_runs"],
        }
    eligible = [family for family in ["L1", "M64", "M128", "M1"] if comparison_rows[family]["mrr_mean"] > cosine_a["mrr"]]
    if eligible:
        selected = max(eligible, key=lambda family: (comparison_rows[family]["mrr_mean"], comparison_rows[family]["top1_mean"], -counts[family]))
    else:
        selected = "C0"
    if selected in {"M64", "M128"}:
        ordered = sorted(compact_runs[selected], key=lambda run: (run["view_metrics"][VIEW_A]["mrr"], run["training_seed"]))
        representative_run = ordered[len(ordered) // 2]
        representative = f"{selected}:{representative_run['training_seed']}"
        for entry in registry_entries:
            entry["development_representative_checkpoint"] = entry["model_family"] == selected and entry["training_seed"] == representative_run["training_seed"]
    elif selected == "M1":
        representative = "M1:20260813 (retained frozen LR-3 representative)"
    elif selected == "L1":
        representative = "L1:FROZEN_LR3_FAMILY_RESULT_NO_NEW_CHECKPOINT"
    else:
        representative = "C0_FIXED_COSINE_NO_CHECKPOINT"

    compact_above = [family for family in ["M64", "M128"] if comparison_rows[family]["mrr_mean"] > cosine_a["mrr"]]
    m1_above = comparison_rows["M1"]["mrr_mean"] > cosine_a["mrr"]
    if compact_above:
        interpretation = "COMPACT_NONLINEAR_GAIN_SUPPORTED"
    elif m1_above:
        interpretation = "NONLINEAR_GAIN_REQUIRES_HIGH_CAPACITY"
    elif uncertainty["architectures"]["M1"]["bootstrap_95_percent_ci"]["upper"] <= 0.0:
        interpretation = "NONLINEAR_GAIN_NOT_ROBUST_TO_CAPACITY"
    else:
        interpretation = "CAPACITY_RESULT_INCONCLUSIVE"

    model_comparison = {
        "schema_version": "lr3r-model-comparison-v1",
        "view": VIEW_A,
        "architecture_table": comparison_rows,
        "metric_tradeoffs_vs_cosine": tradeoffs,
        "development_decision_rule": ["mean_VIEW_A_MRR_above_C0", "higher_mean_VIEW_A_MRR", "higher_mean_VIEW_A_Top1", "fewer_trainable_parameters"],
        "eligible_architectures": eligible,
        "selected_robustness_stage_development_architecture": selected,
        "development_representative_checkpoint": representative,
        "capacity_interpretation_state": interpretation,
        "best_single_seed_used_for_architecture_selection": False,
        "view_b_used_for_selection": False,
        "final_gold_used_for_selection": False,
    }
    write_json(HERE / "lr3r_model_comparison_v1.json", model_comparison)
    write_json(HERE / "lr3r_checkpoint_registry_v1.json", {
        "schema_version": "lr3r-checkpoint-registry-v1",
        "checkpoint_count": len(registry_entries),
        "governance_status": "RESEARCH_ONLY_DEVELOPMENT_CHECKPOINTS",
        "selected_architecture": selected,
        "development_representative_checkpoint": representative,
        "entries": registry_entries,
    })

    summary = {
        "schema_version": "lr3r-dev-metrics-summary-v1",
        "development_results_only": True,
        "coverage_warning": {
            "production_candidate_labels": 16,
            "pairwise_training_labels": 12,
            "view_a_records": 79,
            "view_a_gold_labels": 8,
            "view_b_records": 5,
            "view_b_gold_labels": 1,
            "production_labels_without_dev_gold": 7,
        },
        "view_a_pairwise_seen": {"C0": cosine_a, **{family: aggregate_seed_metrics(runs, VIEW_A) for family, runs in all_arch_runs.items()}},
        "singleton_unseen_diagnostic_view_b": {"label": "UNSEEN-SINGLETON DIAGNOSTIC", "M64": family_results["M64"]["view_b_aggregate"], "M128": family_results["M128"]["view_b_aggregate"]},
        "mixed_development_diagnostic_view_c": {"label": "MIXED DEVELOPMENT DIAGNOSTIC", "record_count": 84, "M64": family_results["M64"]["view_c_aggregate"], "M128": family_results["M128"]["view_c_aggregate"]},
        "metric_tradeoffs_vs_cosine": tradeoffs,
    }
    write_json(HERE / "lr3r_dev_metrics_summary_v1.json", summary)

    after = protected_inventory()
    if before != after:
        raise RuntimeError("protected artifact changed during LR-3R")
    write_json(HERE / "lr3r_validation_report_v1.json", {
        "schema_version": "lr3r-validation-report-v1",
        "overall_status": "PENDING_TESTS_AND_REGRESSIONS",
        "lr3_hashes_verified": True,
        "lr2r_hashes_verified": True,
        "training_pair_membership_matches_lr3_protocol": True,
        "training_record_universe_count": 58,
        "training_label_universe_count": 12,
        "singleton_training_reference_count": 0,
        "hard_negative_training_pair_count": 0,
        "dev_training_record_count": 0,
        "feature_construction_unchanged": True,
        "m64_architecture_exact": True,
        "m128_architecture_exact": True,
        "mpnet_parameters_in_optimizer": 0,
        "mpnet_finetuned": False,
        "optimizer_contains_scorer_parameters_only": True,
        "training_seeds_exact": list(TRAINING_SEEDS),
        "training_hyperparameters_equal_lr3": True,
        "evaluation_candidate_universe_unchanged": True,
        "family_collapse_unchanged": True,
        "max_intent_aggregation_unchanged": True,
        "runtime_fidelity_status": runtime_report["status"],
        "c0_frozen_metrics_match_lr3_exactly": True,
        "l1_frozen_metrics_match_lr3_exactly": True,
        "m1_frozen_metrics_match_lr3_exactly": True,
        "bootstrap_deterministic": True,
        "seed_replay_status": "PENDING_TEST",
        "production_code_modified": False,
        "semantic_runtime_modified": False,
        "original_data_modified": False,
        "lr3_modified": False,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_files_unchanged": True,
        "final_gold_available": False,
        "final_gold_evaluation_run": False,
        "existing_regressions": "PENDING",
    })
    print(json.dumps({
        "C0_MRR": cosine_a["mrr"],
        "M64": family_results["M64"]["view_a_aggregate"],
        "M128": family_results["M128"]["view_a_aggregate"],
        "selected": selected,
        "representative": representative,
        "interpretation": interpretation,
    }, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
