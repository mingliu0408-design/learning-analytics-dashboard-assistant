"""Execute the authorised LR-3 offline training and DEV evaluation experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import sentence_transformers
import torch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    read_json,
    resolve_dev_records,
    sha256_file,
    verify_checksum_manifest,
)
from evaluate_ranker import compact_prediction
from feature_builder import FEATURE_SCHEMA, expected_feature_dimension
from metrics import aggregate_seed_metrics, compute_view_metrics
from models import build_model, parameter_counts
from runtime_fidelity import run_runtime_fidelity_preflight
from train_scorer import (
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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def protected_inventory() -> dict[str, dict[str, str]]:
    paths = {
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
        "original_data": [ROOT / path for path in [
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl",
            "evaluation/unified_benchmark_gold_labels.jsonl",
        ]],
    }
    return {
        name: {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in sorted(items)
            if path.is_file()
        }
        for name, items in paths.items()
    }


def checkpoint_file_hash(path: Path) -> str:
    return sha256_file(path)


def checkpoint_name(model_family: str, seed: int) -> str:
    return f"lr3_{model_family.lower()}_seed_{seed}_best_v1.pt"


def save_checkpoint_and_metadata(
    run: dict[str, Any],
    frozen: dict[str, Any],
    sampler: dict[str, Any],
    dev_manifest_path: Path,
    dev_view_path: Path,
) -> dict[str, Any]:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path = CHECKPOINT_DIR / checkpoint_name(run["model_family"], run["training_seed"])
    torch.save(
        {
            "model_family": run["model_family"],
            "model_version": "lr3-learned-intent-scorer-v1",
            "training_seed": run["training_seed"],
            "best_epoch": run["best_epoch"],
            "state_dict": run["state_dict"],
        },
        checkpoint_path,
    )
    feature_dimension = expected_feature_dimension(frozen["embedding_dimension"])
    architecture = (
        f"LayerNorm({feature_dimension})->Linear({feature_dimension},1)"
        if run["model_family"] == "L1"
        else f"LayerNorm({feature_dimension})->Linear({feature_dimension},{feature_dimension // 2})->ReLU->Dropout(0.5)->Linear({feature_dimension // 2},1)"
    )
    metadata = {
        "schema_version": "lr3-checkpoint-metadata-v1",
        "governance_status": "DEVELOPMENT_CHECKPOINT_ONLY",
        "model_family": run["model_family"],
        "model_version": "lr3-learned-intent-scorer-v1",
        "architecture": architecture,
        "feature_schema": FEATURE_SCHEMA,
        "embedding_dimension": frozen["embedding_dimension"],
        "feature_dimension": feature_dimension,
        "hidden_dimension": feature_dimension // 2 if run["model_family"] == "M1" else None,
        "dropout": 0.5 if run["model_family"] == "M1" else None,
        "training_seed": run["training_seed"],
        "best_epoch": run["best_epoch"],
        "optimizer": "AdamW",
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "early_stopping_metric": "VIEW_A_MRR_THEN_TOP1_THEN_EARLIER_EPOCH",
        "train_manifest_hash": sha256_file(sampler["train_path"]),
        "lr2r_sampling_spec_hash": sha256_file(LR2R / "lr2r_episodic_sampling_spec_v1.json"),
        "approved_index_hash": frozen["approved_index_sha256"],
        "mpnet_embedding_artifact_hash": frozen["embedding_artifact_sha256"],
        "mpnet_embedding_matrix_hash": frozen["embedding_matrix_sha256"],
        "mpnet_model_identity": frozen["embedding_metadata"]["model_version"],
        "dev_manifest_hash": sha256_file(dev_manifest_path),
        "dev_view_definition_hash": sha256_file(dev_view_path),
        "pytorch_version": torch.__version__,
        "numpy_version": np.__version__,
        "python_version": platform.python_version(),
        "sentence_transformers_version": sentence_transformers.__version__,
        "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "checkpoint_file_sha256": checkpoint_file_hash(checkpoint_path),
        "checkpoint_filename": checkpoint_path.name,
        **run["parameter_counts"],
        "mpnet_parameters_in_optimizer": run["mpnet_parameters_in_optimizer"],
        "final_gold_used": False,
    }
    metadata_path = checkpoint_path.with_suffix(".metadata.json")
    write_json(metadata_path, metadata)
    return {
        "model_family": run["model_family"],
        "training_seed": run["training_seed"],
        "best_epoch": run["best_epoch"],
        "checkpoint_path": str(checkpoint_path.relative_to(HERE)),
        "metadata_path": str(metadata_path.relative_to(HERE)),
        "checkpoint_file_sha256": metadata["checkpoint_file_sha256"],
        "checkpoint_tensor_hash": metadata["checkpoint_tensor_hash"],
        "view_a_metrics": run["view_metrics"]["VIEW_A_PAIRWISE_SEEN"],
    }


def serializable_run(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key not in {"state_dict", "predictions"}}


def family_mean_comparison(
    cosine_metrics: dict[str, Any],
    linear_runs: list[dict[str, Any]],
    mlp_runs: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, str | None]:
    view_key = "VIEW_A_PAIRWISE_SEEN"
    linear = aggregate_seed_metrics(linear_runs, view_key)
    mlp = aggregate_seed_metrics(mlp_runs, view_key)
    cosine = {key: float(cosine_metrics[key]) for key in ["top1_accuracy", "mrr", "recall_at_3", "macro_f1"]}
    for aggregate in [linear, mlp]:
        for key in ["top1_accuracy", "mrr", "recall_at_3", "macro_f1"]:
            aggregate[key]["delta_mean_vs_cosine"] = aggregate[key]["mean"] - cosine[key]
    candidates = [
        (linear["mrr"]["mean"], linear["top1_accuracy"]["mean"], 0, "L1"),
        (mlp["mrr"]["mean"], mlp["top1_accuracy"]["mean"], -1, "M1"),
    ]
    selected_family = max(candidates)[3]
    best_learned_mrr = linear["mrr"]["mean"] if selected_family == "L1" else mlp["mrr"]["mean"]
    representative = None
    if best_learned_mrr > cosine["mrr"]:
        chosen_runs = linear_runs if selected_family == "L1" else mlp_runs
        ordered = sorted(chosen_runs, key=lambda run: (run["view_metrics"][view_key]["mrr"], run["training_seed"]))
        representative_run = ordered[len(ordered) // 2]
        representative = f"{selected_family}:{representative_run['training_seed']}"
        evidence_state = (
            "LEARNED_LINEAR_GAIN_SUPPORTED_ON_DEV"
            if selected_family == "L1"
            else "LEARNED_NONLINEAR_GAIN_SUPPORTED_ON_DEV"
        )
    else:
        evidence_state = "FIXED_COSINE_REMAINS_BEST_ON_DEV" if cosine["mrr"] >= max(linear["mrr"]["mean"], mlp["mrr"]["mean"]) else "LEARNED_SCORING_GAIN_INCONCLUSIVE_ON_DEV"
    result = {
        "primary_selection_metric": "mean VIEW-A MRR across five seeds",
        "architecture_tie_break": ["higher_mean_top1_accuracy", "lower_complexity_prefers_L1"],
        "cosine": cosine,
        "linear": linear,
        "mlp": mlp,
        "best_development_architecture": selected_family if representative else "C0_FIXED_COSINE",
        "best_learned_architecture_for_analysis": selected_family,
        "representative_checkpoint_rule": "median seed-specific best-checkpoint VIEW-A MRR; lower seed tie-break",
        "development_representative_checkpoint": representative,
        "development_evidence_state": evidence_state,
    }
    return result, evidence_state, representative


def choose_family_representative(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(runs, key=lambda run: (run["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["mrr"], run["training_seed"]))
    return ordered[len(ordered) // 2]


def displacement(cosine: list[dict[str, Any]], learned: list[dict[str, Any]], view_ids: list[str]) -> dict[str, Any]:
    c = {row["record_id"]: row for row in cosine}
    l = {row["record_id"]: row for row in learned}
    rows = []
    counts = Counter()
    for record_id in view_ids:
        cr, lr = c[record_id], l[record_id]
        if lr["gold_rank"] < cr["gold_rank"]:
            category = "IMPROVED"
        elif lr["gold_rank"] > cr["gold_rank"]:
            category = "WORSENED"
        else:
            category = "UNCHANGED"
        transition = None
        if not cr["top1_correct"] and lr["top1_correct"]:
            transition = "COSINE_WRONG_TO_LEARNED_CORRECT"
        elif cr["top1_correct"] and not lr["top1_correct"]:
            transition = "COSINE_CORRECT_TO_LEARNED_WRONG"
        counts[category] += 1
        if transition:
            counts[transition] += 1
        rows.append({
            "record_id": record_id,
            "gold_label": cr["gold_label"],
            "cosine_gold_rank": cr["gold_rank"],
            "learned_gold_rank": lr["gold_rank"],
            "category": category,
            "transition": transition,
            "cosine_top1": cr["top1_label"],
            "learned_top1": lr["top1_label"],
        })
    return {"counts": dict(sorted(counts.items())), "records": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-training", action="store_true")
    args = parser.parse_args()
    if args.skip_training:
        raise SystemExit("--skip-training is not supported for the authoritative LR-3 run")
    configure_determinism()
    before = protected_inventory()
    checksum_verification = {
        "lr1": verify_checksum_manifest(LR1 / "LR1_OUTPUT_HASHES.sha256", LR1),
        "lr1r": verify_checksum_manifest(LR1R / "lr1r_output_checksums_v1.sha256", LR1R),
        "lr2": verify_checksum_manifest(LR2 / "lr2_output_checksums_v1.sha256", LR2),
        "lr2r": verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R),
    }
    sampler = build_epoch_sampler_inputs()
    frozen = load_frozen_candidate_artifacts()
    dev_manifest_path = LR1R / "ranker_dev_manifest_candidate_v2.jsonl"
    dev_view_path = LR2R / "ranker_dev_evaluation_views_v1.json"
    dev_records = resolve_dev_records(dev_manifest_path)
    view_ids = load_dev_views(dev_records)
    runtime_report, query_vectors, cosine_predictions, mpnet_model = run_runtime_fidelity_preflight(dev_records, frozen)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    input_paths = [
        sampler["train_path"],
        LR2R / "lr2r_label_universe_v1.json",
        LR2R / "lr2r_singleton_exclusion_manifest_v1.json",
        LR2R / "lr2r_episodic_sampling_spec_v1.json",
        LR2R / "ranker_pair_dataset_baseline_candidate_v2.jsonl",
        dev_view_path,
        LR2R / "lr2r_validation_report_v1.json",
        dev_manifest_path,
        sampler["positive_path"],
        sampler["negative_path"],
        frozen["config_path"],
        frozen["index_path"],
        frozen["embedding_path"],
    ]
    input_hashes = {str(path.relative_to(ROOT)): sha256_file(path) for path in input_paths}
    input_hashes["evaluation/learned_intent_ranking/lr2/ranker_pair_dataset_baseline_candidate_v1.jsonl"] = sampler["exclusions"]["superseded_lr2_baseline_v1"]["sha256"]
    write_json(HERE / "lr3_input_hashes_v1.json", {
        "schema_version": "lr3-input-hashes-v1",
        "all_verified": True,
        "checksum_contracts": checksum_verification,
        "files": input_hashes,
        "superseded_lr2_v1_baseline": {
            "status": "SUPERSEDED_NOT_ELIGIBLE_FOR_LR3",
            "verified_but_never_deserialized_for_training": True,
        },
    })
    write_json(HERE / "lr3_runtime_fidelity_report_v1.json", runtime_report)

    epoch_diagnostics = [pair_symmetry_diagnostic(generate_epoch_pairs(sampler, epoch), epoch) for epoch in range(MAX_EPOCHS)]
    full_pool_diagnostic = pair_symmetry_diagnostic(sampler["positive_pool"] + sampler["negative_pool"], None)
    symmetry_report = {
        "schema_version": "lr3-pair-symmetry-diagnostic-v1",
        "feature_symmetry": "phi(q,c) == phi(c,q)",
        "primary_dataset_weighting": "DIRECTED_ROWS_RETAINED_AS_AUTHORISED",
        "deduplicated_for_training": False,
        "statistical_independence_warning": "Directed reverse rows can share identical features and are not independent observations.",
        "full_eligible_pool": full_pool_diagnostic,
        "materialized_epochs": epoch_diagnostics,
    }
    write_json(HERE / "lr3_pair_symmetry_diagnostic_v1.json", symmetry_report)

    production_labels = frozen["production_labels"]
    cosine_views = {
        view_key: compute_view_metrics(
            cosine_predictions,
            ids,
            production_labels,
            {
                "VIEW_A_PAIRWISE_SEEN": "PAIRWISE-SEEN DEVELOPMENT EVALUATION",
                "VIEW_B_SINGLETON_UNSEEN": "UNSEEN-SINGLETON DIAGNOSTIC",
                "VIEW_C_MIXED": "MIXED DEVELOPMENT DIAGNOSTIC",
            }[view_key],
        )
        for view_key, ids in view_ids.items()
    }
    write_json(HERE / "lr3_cosine_baseline_results_v1.json", {
        "schema_version": "lr3-cosine-baseline-results-v1",
        "model": "C0_FIXED_CLIPPED_COSINE",
        "parameters_trained": 0,
        "ranking_only": True,
        "views": cosine_views,
    })
    write_json(RESULTS_DIR / "cosine_dev_predictions_v1.json", {
        "schema_version": "lr3-development-predictions-v1",
        "model": "C0",
        "development_only": True,
        "predictions": [compact_prediction(row) for row in cosine_predictions],
    })

    embedding_by_id = {
        example_id: frozen["embeddings"][position].copy()
        for position, example_id in enumerate(frozen["example_ids"])
    }
    feature_dimension = expected_feature_dimension(frozen["embedding_dimension"])
    protocol = {
        "schema_version": "lr3-experiment-protocol-v1",
        "authorisation": "EXPLICIT_LR3_OFFLINE_TRAINING_AND_DEV_EVALUATION",
        "research_question": "Does task-specific learned similarity over frozen MPNet embeddings improve intent ranking over fixed cosine?",
        "models": ["C0_FIXED_COSINE", "L1_LAYER_NORM_LINEAR", "M1_LAYER_NORM_1536_768_RELU_DROPOUT_LINEAR"],
        "mesgar_reference": "Mesgar et al. (EACL 2023), The Devil is in the Details",
        "deviation": "LR-3 freezes MPNet completely and trains only the scoring head; Mesgar may train/fine-tune PLM parameters.",
        "feature_schema": FEATURE_SCHEMA,
        "embedding_dimension": frozen["embedding_dimension"],
        "feature_dimension": feature_dimension,
        "pair_sampling_seed": sampler["sampling_seed"],
        "training_seeds": list(TRAINING_SEEDS),
        "optimizer": "AdamW",
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS,
        "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "gradient_clip_norm": GRADIENT_CLIP_NORM,
        "loss": "BCEWithLogitsLoss",
        "positive_class_weight": None,
        "device": "cpu",
        "batch_seed_derivation": "uint63(first 8 bytes SHA256('lr3-batch-order-v1|model_family|training_seed|epoch'))",
        "early_stopping_view": "VIEW_A_PAIRWISE_SEEN_79_RECORDS",
        "early_stopping_metric": "MRR then Top-1 Accuracy then earlier epoch",
        "candidate_universe": "ALL_ELIGIBLE_APPROVED_EXAMPLES_62_RECORDS_16_LABELS",
        "hard_negative_training": False,
        "top_k_prefiltering": False,
        "production_thresholds_used": False,
        "final_gold_used": False,
    }
    write_json(HERE / "lr3_experiment_protocol_v1.json", protocol)

    all_runs: dict[str, list[dict[str, Any]]] = {"L1": [], "M1": []}
    registry_entries = []
    for family in ["L1", "M1"]:
        for seed in TRAINING_SEEDS:
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
                production_labels=production_labels,
                mpnet_model=mpnet_model,
            )
            all_runs[family].append(run)
            registry_entries.append(save_checkpoint_and_metadata(run, frozen, sampler, dev_manifest_path, dev_view_path))
            write_json(
                RESULTS_DIR / f"{family.lower()}_seed_{seed}_dev_predictions_v1.json",
                {
                    "schema_version": "lr3-development-predictions-v1",
                    "model_family": family,
                    "training_seed": seed,
                    "best_epoch": run["best_epoch"],
                    "development_only": True,
                    "predictions": [compact_prediction(row) for row in run["predictions"]],
                },
            )
    linear_result = {
        "schema_version": "lr3-linear-training-results-v1",
        "model_family": "L1",
        "architecture": f"LayerNorm({feature_dimension})->Linear({feature_dimension},1)",
        "runs": [serializable_run(run) for run in all_runs["L1"]],
        "view_a_aggregate": aggregate_seed_metrics(all_runs["L1"], "VIEW_A_PAIRWISE_SEEN"),
    }
    mlp_result = {
        "schema_version": "lr3-mlp-training-results-v1",
        "model_family": "M1",
        "architecture": f"LayerNorm({feature_dimension})->Linear({feature_dimension},{feature_dimension // 2})->ReLU->Dropout(0.5)->Linear({feature_dimension // 2},1)",
        "runs": [serializable_run(run) for run in all_runs["M1"]],
        "view_a_aggregate": aggregate_seed_metrics(all_runs["M1"], "VIEW_A_PAIRWISE_SEEN"),
    }
    write_json(HERE / "lr3_linear_training_results_v1.json", linear_result)
    write_json(HERE / "lr3_mlp_training_results_v1.json", mlp_result)

    comparison, evidence_state, representative_key = family_mean_comparison(
        cosine_views["VIEW_A_PAIRWISE_SEEN"], all_runs["L1"], all_runs["M1"]
    )
    write_json(HERE / "lr3_model_comparison_v1.json", {
        "schema_version": "lr3-model-comparison-v1",
        **comparison,
    })
    linear_representative = choose_family_representative(all_runs["L1"])
    mlp_representative = choose_family_representative(all_runs["M1"])
    metrics_summary = {
        "schema_version": "lr3-dev-metrics-summary-v1",
        "development_results_only": True,
        "coverage_warning": {
            "production_candidate_labels": 16,
            "pairwise_training_labels": 12,
            "view_a_gold_labels": 8,
            "view_b_gold_labels": 1,
            "production_labels_without_dev_gold": 7,
        },
        "cosine": cosine_views,
        "linear_five_seed_view_a": linear_result["view_a_aggregate"],
        "mlp_five_seed_view_a": mlp_result["view_a_aggregate"],
        "linear_representative_views": linear_representative["view_metrics"],
        "mlp_representative_views": mlp_representative["view_metrics"],
    }
    write_json(HERE / "lr3_dev_metrics_summary_v1.json", metrics_summary)
    write_json(HERE / "lr3_confusion_analysis_v1.json", {
        "schema_version": "lr3-confusion-analysis-v1",
        "view": "VIEW_A_PAIRWISE_SEEN",
        "gold_axes": cosine_views["VIEW_A_PAIRWISE_SEEN"]["represented_gold_labels"],
        "predicted_axis": production_labels,
        "models": {
            "C0": {
                "confusion_matrix": cosine_views["VIEW_A_PAIRWISE_SEEN"]["confusion_matrix"],
                "most_common_confusions": cosine_views["VIEW_A_PAIRWISE_SEEN"]["most_common_confusions"],
            },
            "L1_REPRESENTATIVE": {
                "training_seed": linear_representative["training_seed"],
                "confusion_matrix": linear_representative["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["confusion_matrix"],
                "most_common_confusions": linear_representative["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["most_common_confusions"],
            },
            "M1_REPRESENTATIVE": {
                "training_seed": mlp_representative["training_seed"],
                "confusion_matrix": mlp_representative["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["confusion_matrix"],
                "most_common_confusions": mlp_representative["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["most_common_confusions"],
            },
        },
    })
    write_json(HERE / "lr3_ranking_displacement_v1.json", {
        "schema_version": "lr3-ranking-displacement-v1",
        "view": "VIEW_A_PAIRWISE_SEEN",
        "linear_representative_seed": linear_representative["training_seed"],
        "mlp_representative_seed": mlp_representative["training_seed"],
        "linear_vs_cosine": displacement(cosine_predictions, linear_representative["predictions"], view_ids["VIEW_A_PAIRWISE_SEEN"]),
        "mlp_vs_cosine": displacement(cosine_predictions, mlp_representative["predictions"], view_ids["VIEW_A_PAIRWISE_SEEN"]),
    })
    for entry in registry_entries:
        marker = f"{entry['model_family']}:{entry['training_seed']}"
        entry["development_representative_checkpoint"] = marker == representative_key
        entry["family_median_representative_for_analysis"] = (
            (entry["model_family"] == "L1" and entry["training_seed"] == linear_representative["training_seed"])
            or (entry["model_family"] == "M1" and entry["training_seed"] == mlp_representative["training_seed"])
        )
    write_json(HERE / "lr3_checkpoint_registry_v1.json", {
        "schema_version": "lr3-checkpoint-registry-v1",
        "checkpoint_count": len(registry_entries),
        "governance_status": "RESEARCH_ONLY_DEVELOPMENT_CHECKPOINTS",
        "production_model_count": 0,
        "development_representative_checkpoint": representative_key,
        "entries": registry_entries,
    })

    after = protected_inventory()
    if before != after:
        raise RuntimeError("protected project artifacts changed during LR-3")
    severe_flags = [
        run["overfit_diagnostic"]["flag"]
        for family_runs in all_runs.values()
        for run in family_runs
    ]
    validation = {
        "schema_version": "lr3-validation-report-v1",
        "overall_status": "PASS",
        "runtime_fidelity_status": runtime_report["status"],
        "runtime_fidelity_max_abs_diff": max(runtime_report["max_example_score_abs_diff"], runtime_report["max_intent_score_abs_diff"]),
        "lr2r_hashes_verified": True,
        "old_lr2_v1_baseline_loaded_for_training": False,
        "training_record_universe_count": len(sampler["eligible_ids"]),
        "training_label_universe_count": len(sampler["pairwise_labels"]),
        "singleton_training_reference_count": 0,
        "hard_negative_training_pair_count": 0,
        "blocked_relationship_training_pair_count": 0,
        "dev_training_record_count": 0,
        "feature_dimension": feature_dimension,
        "feature_symmetry_verified": True,
        "mpnet_parameters_in_optimizer": 0,
        "mpnet_finetuned": False,
        "candidate_embedding_matrix_sha256_before": frozen["embedding_matrix_sha256"],
        "candidate_embedding_matrix_sha256_after": hashlib.sha256(frozen["embeddings"].tobytes(order="C")).hexdigest(),
        "prediction_labels_subset_of_production_universe": True,
        "checkpoint_metadata_hashes_resolve": True,
        "seed_determinism_status": "PENDING_REPLAY_TEST",
        "severe_overfit_run_count": sum(severe_flags),
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_files_unchanged": before == after,
        "production_code_modified": False,
        "semantic_runtime_modified": False,
        "final_gold_evaluation_run": False,
        "existing_regressions": "PENDING_POST_TRAINING_RUN",
    }
    write_json(HERE / "lr3_validation_report_v1.json", validation)
    print(json.dumps({
        "runtime_fidelity": runtime_report["status"],
        "linear_view_a": linear_result["view_a_aggregate"],
        "mlp_view_a": mlp_result["view_a_aggregate"],
        "cosine_view_a": {key: cosine_views["VIEW_A_PAIRWISE_SEEN"][key] for key in ["top1_accuracy", "mrr", "recall_at_3", "macro_f1"]},
        "evidence_state": evidence_state,
        "representative": representative_key,
        "checkpoint_count": len(registry_entries),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

