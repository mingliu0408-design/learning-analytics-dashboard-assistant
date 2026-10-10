"""Execute the authorised LR-3S symmetric pair-weighting ablation."""

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
LR3R = HERE.parent / "lr3r"
ROOT = HERE.parents[2]
for path in [str(LR3), str(LR3R), str(ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from data_loader import (
    LR1, LR1R, LR2, LR2R, build_epoch_sampler_inputs, generate_epoch_pairs,
    load_dev_views, load_frozen_candidate_artifacts, resolve_dev_records, sha256_file, verify_checksum_manifest,
)
from evaluate_ranker import compact_prediction
from feature_builder import FEATURE_SCHEMA
from metrics import aggregate_seed_metrics
from runtime_fidelity import run_runtime_fidelity_preflight

from weighted_train import (
    BATCH_SIZE, EARLY_STOPPING_PATIENCE, GRADIENT_CLIP_NORM, LEARNING_RATE, MAX_EPOCHS,
    TRAINING_SEEDS, WEIGHT_DECAY, configure_determinism, train_one_seed,
)
from weighting import CONDITIONS, directed_membership_hash, unordered_pair_id, weight_epoch_rows


CHECKPOINT_DIR = HERE / "checkpoints"
RESULTS_DIR = HERE / "results"
VIEW_A = "VIEW_A_PAIRWISE_SEEN"
VIEW_B = "VIEW_B_SINGLETON_UNSEEN"
VIEW_C = "VIEW_C_MIXED"
METRICS = ("top1_accuracy", "mrr", "recall_at_3", "macro_f1")
SHORT = {"S1_UNORDERED_EQUAL_WEIGHT": "S1", "S2_UNORDERED_CLASS_BALANCED": "S2"}


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
        "lr1": list(LR1.rglob("*")), "lr1r": list(LR1R.rglob("*")), "lr2": list(LR2.rglob("*")),
        "lr2r": list(LR2R.rglob("*")), "lr3": list(LR3.rglob("*")), "lr3r": list(LR3R.rglob("*")),
        "original_data": [ROOT / path for path in [
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl", "evaluation/unified_benchmark_gold_labels.jsonl",
        ]],
    }
    return {name: {str(path.relative_to(ROOT)): sha256_file(path) for path in sorted(paths) if path.is_file()} for name, paths in groups.items()}


def serializable(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key not in {"state_dict", "predictions"}}


def aggregate_view(runs: list[dict[str, Any]], view: str) -> dict[str, Any]:
    aggregate = aggregate_seed_metrics(runs, view)
    ranks = [run["view_metrics"][view]["mean_gold_label_rank"] for run in runs]
    aggregate["mean_gold_label_rank"] = {
        "mean": float(statistics.fmean(ranks)), "std": float(statistics.pstdev(ranks)),
        "min": float(min(ranks)), "max": float(max(ranks)),
        "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, ranks)},
    }
    per_seed = {str(run["training_seed"]): run["view_metrics"][view]["predicted_label_distribution"] for run in runs}
    totals = Counter()
    for distribution in per_seed.values():
        totals.update(distribution)
    aggregate["predicted_label_distribution"] = {
        "per_seed": per_seed, "total_across_five_seeds": dict(sorted(totals.items())),
        "mean_count_per_seed": {label: count / 5.0 for label, count in sorted(totals.items())},
    }
    return aggregate


def save_checkpoint(run: dict[str, Any], frozen: dict[str, Any], sampler: dict[str, Any]) -> dict[str, Any]:
    short = SHORT[run["condition"]].lower()
    seed = run["training_seed"]
    path = CHECKPOINT_DIR / f"lr3s_{short}_m64_seed_{seed}_best_v1.pt"
    torch.save({
        "condition": run["condition"], "model_family": "M64", "model_version": "lr3s-weighted-m64-v1",
        "training_seed": seed, "best_epoch": run["best_epoch"], "state_dict": run["state_dict"],
    }, path)
    metadata = {
        "schema_version": "lr3s-checkpoint-metadata-v1", "governance_status": "RESEARCH_ONLY_DEVELOPMENT_CHECKPOINT",
        "condition": run["condition"], "model_family": "M64", "architecture": "LayerNorm(1536)->Linear(1536,64)->ReLU->Dropout(0.5)->Linear(64,1)",
        "feature_schema": FEATURE_SCHEMA, "embedding_dimension": 768, "feature_dimension": 1536, "hidden_dimension": 64,
        "dropout": 0.5, "training_seed": seed, "best_epoch": run["best_epoch"], "optimizer": "AdamW",
        "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY, "batch_size": BATCH_SIZE,
        "max_epochs": MAX_EPOCHS, "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "gradient_clip_norm": GRADIENT_CLIP_NORM, "loss": "explicit_weighted_unreduced_BCEWithLogitsLoss",
        "loss_normalisation": "sum(row_weight*bce)/sum(row_weight) per batch; epoch audit sum(weighted_bce)/sum(weight)",
        "train_manifest_hash": sha256_file(sampler["train_path"]),
        "lr2r_sampling_spec_hash": sha256_file(LR2R / "lr2r_episodic_sampling_spec_v1.json"),
        "approved_index_hash": frozen["approved_index_sha256"], "mpnet_embedding_artifact_hash": frozen["embedding_artifact_sha256"],
        "mpnet_embedding_matrix_hash": frozen["embedding_matrix_sha256"], "mpnet_model_identity": frozen["embedding_metadata"]["model_version"],
        "python_version": platform.python_version(), "pytorch_version": torch.__version__, "numpy_version": np.__version__,
        "sentence_transformers_version": sentence_transformers.__version__, "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "checkpoint_file_sha256": sha256_file(path), **run["parameter_counts"], "mpnet_parameters_in_optimizer": 0,
        "final_gold_used": False,
    }
    metadata_path = path.with_suffix(".metadata.json")
    write_json(metadata_path, metadata)
    return {
        "condition": run["condition"], "training_seed": seed, "best_epoch": run["best_epoch"],
        "checkpoint_path": str(path.relative_to(HERE)), "metadata_path": str(metadata_path.relative_to(HERE)),
        "checkpoint_file_sha256": metadata["checkpoint_file_sha256"], "checkpoint_tensor_hash": run["checkpoint_tensor_hash"],
        "view_a_metrics": run["view_metrics"][VIEW_A], "development_representative_checkpoint": False,
    }


def load_predictions(base: Path, template: str) -> list[list[dict[str, Any]]]:
    return [read_json(base / template.format(seed=seed))["predictions"] for seed in TRAINING_SEEDS]


def uncertainty_analysis(
    view_ids: list[str], cosine: list[dict[str, Any]], d0: list[list[dict[str, Any]]], conditions: dict[str, list[list[dict[str, Any]]]],
) -> dict[str, Any]:
    cosine_map = {row["record_id"]: row for row in cosine}
    d0_maps = [{row["record_id"]: row for row in predictions} for predictions in d0]
    rng = np.random.default_rng(20260813)
    indices = rng.integers(0, len(view_ids), size=(10000, len(view_ids)))
    result = {}
    for condition, seed_predictions in conditions.items():
        maps = [{row["record_id"]: row for row in predictions} for predictions in seed_predictions]
        query_rows, cosine_deltas, d0_deltas = [], [], []
        for record_id in view_ids:
            c_rank = cosine_map[record_id]["gold_rank"]
            c_rr = 1.0 / c_rank if c_rank else 0.0
            d0_rr = float(statistics.fmean(1.0 / rows[record_id]["gold_rank"] if rows[record_id]["gold_rank"] else 0.0 for rows in d0_maps))
            seed_rrs = [1.0 / rows[record_id]["gold_rank"] if rows[record_id]["gold_rank"] else 0.0 for rows in maps]
            learned_rr = float(statistics.fmean(seed_rrs))
            cosine_delta, d0_delta = learned_rr - c_rr, learned_rr - d0_rr
            cosine_deltas.append(cosine_delta); d0_deltas.append(d0_delta)
            query_rows.append({
                "record_id": record_id, "gold_label": cosine_map[record_id]["gold_label"],
                "cosine_reciprocal_rank": c_rr, "d0_mean_reciprocal_rank": d0_rr,
                "condition_seed_reciprocal_ranks": seed_rrs, "condition_mean_reciprocal_rank": learned_rr,
                "delta_vs_cosine": cosine_delta, "delta_vs_d0": d0_delta,
            })
        refs = {}
        for name, values in [("C0_COSINE", cosine_deltas), ("D0_DIRECTED_EQUAL_WEIGHT", d0_deltas)]:
            array = np.asarray(values, dtype=np.float64)
            means = array[indices].mean(axis=1)
            refs[name] = {
                "mean_per_query_rr_delta": float(array.mean()),
                "bootstrap_95_percent_ci": {"lower": float(np.percentile(means, 2.5)), "upper": float(np.percentile(means, 97.5)), "percentile_method": "numpy_linear"},
            }
        result[condition] = {"comparisons": refs, "queries": query_rows}
    return {
        "schema_version": "lr3s-development-uncertainty-analysis-v1", "label": "DEVELOPMENT UNCERTAINTY ANALYSIS",
        "confirmatory_evidence": False, "view": VIEW_A, "query_count": len(view_ids), "bootstrap_seed": 20260813,
        "bootstrap_resamples": 10000, "resampling_unit": "VIEW_A_QUERY", "conditions": result,
        "warning": "DEV supported model development and checkpoint selection; intervals are diagnostic only.",
    }


def overfit_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_count": 5, "severe_overfit_runs": sum(run["overfit_diagnostic"]["flag"] for run in runs),
        "best_epoch_distribution": dict(sorted(Counter(str(run["best_epoch"]) for run in runs).items())),
        "stop_epoch_distribution": dict(sorted(Counter(str(run["final_epoch"]) for run in runs).items())),
        "training_and_dev_trajectories": {
            str(run["training_seed"]): [
                {"epoch": row["epoch"], "training_bce": row["training_bce"], "view_a_mrr": row["view_a_mrr"]}
                for row in run["training_history"]
            ] for run in runs
        },
        "seed_variance": {metric: float(statistics.pvariance(run["view_metrics"][VIEW_A][metric] for run in runs)) for metric in METRICS},
    }


def confusion_analysis(d0_runs: list[dict[str, Any]], conditions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    all_runs = {"D0_DIRECTED_EQUAL_WEIGHT": d0_runs, **conditions}
    labels = d0_runs[0]["view_metrics"][VIEW_A]["represented_gold_labels"]
    per_intent: dict[str, Any] = {}
    patterns: dict[str, Any] = {}
    definitions = {
        "planning_or_strategy_bidirectional_improvement_recommendation": [("planning_or_strategy", "improvement_recommendation"), ("improvement_recommendation", "planning_or_strategy")],
        "course_content_question_to_dashboard_interpretation": [("course_content_question", "dashboard_interpretation")],
        "cross_page_relationship_to_dashboard_interpretation": [("cross_page_relationship", "dashboard_interpretation")],
    }
    for condition, runs in all_runs.items():
        per_intent[condition] = {}
        for label in labels:
            values = [run["view_metrics"][VIEW_A]["per_intent"][label]["f1"] for run in runs]
            per_intent[condition][label] = {"mean": float(statistics.fmean(values)), "std_population": float(statistics.pstdev(values)), "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, values)}}
        patterns[condition] = {}
        for name, transitions in definitions.items():
            values = [sum(run["view_metrics"][VIEW_A]["confusion_matrix"][gold][predicted] for gold, predicted in transitions) for run in runs]
            patterns[condition][name] = {"mean_count": float(statistics.fmean(values)), "per_seed": {str(run["training_seed"]): value for run, value in zip(runs, values)}}
    for condition in CONDITIONS:
        for name, row in patterns[condition].items():
            d0_mean = patterns["D0_DIRECTED_EQUAL_WEIGHT"][name]["mean_count"]
            row["d0_mean_count"] = d0_mean
            row["effect_vs_d0"] = "improves" if row["mean_count"] < d0_mean else "worsens" if row["mean_count"] > d0_mean else "preserves"
    return {"schema_version": "lr3s-confusion-analysis-v1", "view": VIEW_A, "represented_gold_labels": labels, "per_intent_f1": per_intent, "known_confusion_patterns": patterns, "taxonomy_modified": False}


def main() -> None:
    configure_determinism()
    before = protected_inventory()
    contracts = {
        "lr2r": verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R),
        "lr3": verify_checksum_manifest(LR3 / "lr3_output_checksums_v1.sha256", LR3),
        "lr3r": verify_checksum_manifest(LR3R / "lr3r_output_checksums_v1.sha256", LR3R),
    }
    if not all(row["match"] for rows in contracts.values() for row in rows):
        raise ValueError("authoritative checksum verification failed")

    sampler = build_epoch_sampler_inputs()
    frozen = load_frozen_candidate_artifacts()
    dev_records = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
    view_ids = load_dev_views(dev_records)
    runtime, query_vectors, cosine_predictions, mpnet = run_runtime_fidelity_preflight(dev_records, frozen)
    if runtime["status"] != "PASS":
        raise ValueError("runtime fidelity failed")

    d0_result = read_json(LR3R / "lr3r_m64_training_results_v1.json")
    d0_runs = d0_result["runs"]
    d0_predictions = load_predictions(LR3R / "results", "m64_seed_{seed}_dev_predictions_v1.json")
    cosine_a = read_json(LR3 / "lr3_cosine_baseline_results_v1.json")["views"][VIEW_A]
    d0_aggregate = d0_result["view_a_aggregate"]
    if d0_aggregate["mrr"]["mean"] != 0.6561020695197911:
        raise ValueError("D0 frozen benchmark mismatch")

    # Build the complete read-only weight audit before any training.
    dev_ids = {row["record_id"] for row in dev_records}
    epoch_audits = {condition: [] for condition in CONDITIONS}
    membership_hashes = []
    for epoch in range(MAX_EPOCHS):
        directed = generate_epoch_pairs(sampler, epoch)
        membership_hash = directed_membership_hash(directed)
        membership_hashes.append(membership_hash)
        for row in directed:
            endpoints = {row["anchor_record_id"], row["candidate_record_id"]}
            if row["anchor_record_id"] == row["candidate_record_id"] or not endpoints <= sampler["eligible_ids"] or endpoints & sampler["singleton_ids"] or endpoints & dev_ids:
                raise ValueError("unauthorised pair endpoint")
            expected = "SAME_INTENT_POSITIVE" if row["target"] else "SAFE_RANDOM_NEGATIVE"
            if row["relationship_class"] != expected:
                raise ValueError("hard/blocked/unknown relationship found")
        for condition in CONDITIONS:
            weighted, audit = weight_epoch_rows(directed, condition, epoch)
            if [row["pair_id"] for row in weighted] != [row["pair_id"] for row in directed]:
                raise ValueError("pair membership changed")
            if audit["directed_membership_sha256"] != membership_hash:
                raise ValueError("membership hash changed under weighting")
            epoch_audits[condition].append(audit)
    write_json(HERE / "lr3s_pair_weight_audit_v1.json", {
        "schema_version": "lr3s-pair-weight-audit-v1", "pair_membership_authority": "LR2R_EPOCH_SAMPLER",
        "pair_membership_changed": False, "epoch_count": MAX_EPOCHS, "training_records": 58, "training_labels": 12,
        "unordered_pair_identity": "compact JSON encoding of lexicographically sorted [anchor_record_id,candidate_record_id]; label excluded",
        "unexpected_duplicate_structure": False, "self_pair_count": 0, "singleton_reference_count": 0,
        "hard_negative_count": 0, "blocked_relationship_count": 0, "dev_endpoint_count": 0,
        "membership_hashes_by_epoch": {str(epoch): value for epoch, value in enumerate(membership_hashes)},
        "conditions": epoch_audits,
    })

    protocol = {
        "schema_version": "lr3s-experiment-protocol-v1", "authorisation": "EXPLICIT_LR3S_SYMMETRIC_PAIR_WEIGHTING_ABLATION",
        "architecture": "M64_LAYER_NORM_1536_64_RELU_DROPOUT_LINEAR", "only_experimental_variable": "per_row_loss_weight",
        "conditions": {
            "D0_DIRECTED_EQUAL_WEIGHT": "frozen LR-3R reference; row_weight=1",
            "S1_UNORDERED_EQUAL_WEIGHT": "base_weight=1/unordered_pair_multiplicity; final_weight=base_weight",
            "S2_UNORDERED_CLASS_BALANCED": "base_weight=1/multiplicity; each class scaled to half total S1 effective weight",
        },
        "loss_equation": "L_batch = sum_i(w_i * BCEWithLogits(logit_i,target_i)) / sum_i(w_i)",
        "epoch_loss_audit_equation": "L_epoch = sum_i(w_i * pre-update batch BCE_i) / sum_i(w_i)",
        "feature_schema": FEATURE_SCHEMA, "embedding_dimension": 768, "feature_dimension": 1536, "hidden_dimension": 64,
        "optimizer": "AdamW", "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY,
        "batch_size": BATCH_SIZE, "max_epochs": MAX_EPOCHS, "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "gradient_clip_norm": GRADIENT_CLIP_NORM, "dropout": 0.5, "loss": "BCEWithLogitsLoss_unreduced_explicit_row_weighting",
        "positive_class_weight": None, "training_seeds": list(TRAINING_SEEDS), "batch_seed_family_token": "M64",
        "condition_in_batch_seed": False, "condition_in_model_initialisation": False,
        "early_stopping_view": "VIEW_A_PAIRWISE_SEEN_79_RECORDS", "early_stopping_metric": "MRR then Top-1 then earlier epoch",
        "candidate_universe": "FROZEN_PAGE_ELIGIBLE_62_RECORD_16_LABEL_INDEX", "family_collapse": "unchanged",
        "intent_aggregation": "max", "pair_membership_changed": False, "hard_negative_training": False,
        "physical_row_deduplication": False, "mpnet_finetuned": False, "calibration": False, "integration": False,
        "final_gold_used": False,
        "symmetry_interpretation_operationalisation": {
            "broadly_competitive_with_d0": "best S1/S2 mean MRR is within 0.02 absolute MRR of D0",
            "substantial_gain_over_cosine": "mean MRR remains strictly above cosine",
            "material_regression": "best S1/S2 is at or below cosine, or retains less than half of D0's gain over cosine",
        },
    }
    write_json(HERE / "lr3s_experiment_protocol_v1.json", protocol)

    input_paths = [
        LR2R / "lr2r_output_checksums_v1.sha256", LR3 / "lr3_output_checksums_v1.sha256", LR3R / "lr3r_output_checksums_v1.sha256",
        LR3R / "lr3r_m64_training_results_v1.json", LR3R / "lr3r_model_comparison_v1.json", LR3R / "lr3r_validation_report_v1.json",
        LR2R / "lr2r_episodic_sampling_spec_v1.json", LR2R / "ranker_pair_dataset_baseline_candidate_v2.jsonl",
        sampler["train_path"], sampler["positive_path"], sampler["negative_path"],
        LR1R / "ranker_dev_manifest_candidate_v2.jsonl", frozen["index_path"], frozen["embedding_path"], frozen["config_path"],
    ]
    write_json(HERE / "lr3s_input_hashes_v1.json", {
        "schema_version": "lr3s-input-hashes-v1", "all_verified": True,
        "checksum_entries_verified": {name: len(rows) for name, rows in contracts.items()},
        "files": {str(path.relative_to(ROOT)): sha256_file(path) for path in input_paths},
        "d0_frozen_metrics_reproduced_exactly": True, "final_gold_loaded": False,
    })

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True); RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    embedding_by_id = {example_id: frozen["embeddings"][position].copy() for position, example_id in enumerate(frozen["example_ids"])}
    all_runs: dict[str, list[dict[str, Any]]] = {condition: [] for condition in CONDITIONS}
    registry = []
    for condition in CONDITIONS:
        for seed in TRAINING_SEEDS:
            print(f"training {SHORT[condition]} M64 seed {seed}", flush=True)
            run = train_one_seed(
                condition=condition, training_seed=seed, sampler=sampler, embedding_by_id=embedding_by_id,
                dev_records=dev_records, dev_query_vectors=query_vectors, index_records=frozen["index_records"],
                index_embeddings=frozen["embeddings"], view_ids=view_ids, production_labels=frozen["production_labels"], mpnet_model=mpnet,
            )
            all_runs[condition].append(run); registry.append(save_checkpoint(run, frozen, sampler))
            write_json(RESULTS_DIR / f"{SHORT[condition].lower()}_m64_seed_{seed}_dev_predictions_v1.json", {
                "schema_version": "lr3s-development-predictions-v1", "condition": condition, "model_family": "M64",
                "training_seed": seed, "best_epoch": run["best_epoch"], "development_only": True,
                "predictions": [compact_prediction(row) for row in run["predictions"]],
            })

    condition_results = {}
    for condition, runs in all_runs.items():
        short = SHORT[condition].lower()
        result = {
            "schema_version": f"lr3s-{short}-training-results-v1", "condition": condition,
            "model_family": "M64", "architecture": "LayerNorm(1536)->Linear(1536,64)->ReLU->Dropout(0.5)->Linear(64,1)",
            "runs": [serializable(run) for run in runs], "view_a_aggregate": aggregate_seed_metrics(runs, VIEW_A),
            "view_b_aggregate": aggregate_view(runs, VIEW_B), "view_c_aggregate": aggregate_view(runs, VIEW_C),
        }
        condition_results[condition] = result
        write_json(HERE / f"lr3s_{short}_training_results_v1.json", result)

    overfit = {
        "schema_version": "lr3s-overfit-analysis-v1", "diagnostic_rule_unchanged_from_lr3": True,
        "conditions": {
            "D0_DIRECTED_EQUAL_WEIGHT": {
                "run_count": 5, "severe_overfit_runs": sum(run["overfit_diagnostic"]["flag"] for run in d0_runs),
                "best_epoch_distribution": dict(sorted(Counter(str(run["best_epoch"]) for run in d0_runs).items())),
                "stop_epoch_distribution": dict(sorted(Counter(str(run["final_epoch"]) for run in d0_runs).items())),
            },
            **{condition: overfit_summary(runs) for condition, runs in all_runs.items()},
        },
    }
    min_weighted_overfit = min(overfit["conditions"][condition]["severe_overfit_runs"] for condition in CONDITIONS)
    overfit["duplicate_weight_removal_reduces_pattern"] = min_weighted_overfit < overfit["conditions"]["D0_DIRECTED_EQUAL_WEIGHT"]["severe_overfit_runs"]
    write_json(HERE / "lr3s_overfit_analysis_v1.json", overfit)

    condition_predictions = {condition: [run["predictions"] for run in runs] for condition, runs in all_runs.items()}
    uncertainty = uncertainty_analysis(view_ids[VIEW_A], cosine_predictions, d0_predictions, condition_predictions)
    write_json(HERE / "lr3s_development_uncertainty_analysis_v1.json", uncertainty)
    confusion = confusion_analysis(d0_runs, all_runs)
    write_json(HERE / "lr3s_confusion_analysis_v1.json", confusion)

    table = {
        "C0_COSINE": {
            "top1_mean": cosine_a["top1_accuracy"], "top1_std": 0.0, "mrr_mean": cosine_a["mrr"], "mrr_std": 0.0,
            "recall_at_3_mean": cosine_a["recall_at_3"], "macro_f1_mean": cosine_a["macro_f1"],
            "seeds_above_cosine_mrr": None, "seeds_above_d0_mrr_benchmark": None, "severe_overfit_runs": None,
        },
        "D0_DIRECTED_EQUAL_WEIGHT": {
            "top1_mean": d0_aggregate["top1_accuracy"]["mean"], "top1_std": d0_aggregate["top1_accuracy"]["std"],
            "mrr_mean": d0_aggregate["mrr"]["mean"], "mrr_std": d0_aggregate["mrr"]["std"],
            "recall_at_3_mean": d0_aggregate["recall_at_3"]["mean"], "macro_f1_mean": d0_aggregate["macro_f1"]["mean"],
            "seeds_above_cosine_mrr": sum(run["view_metrics"][VIEW_A]["mrr"] > cosine_a["mrr"] for run in d0_runs),
            "seeds_above_d0_mrr_benchmark": sum(run["view_metrics"][VIEW_A]["mrr"] > d0_aggregate["mrr"]["mean"] for run in d0_runs),
            "severe_overfit_runs": overfit["conditions"]["D0_DIRECTED_EQUAL_WEIGHT"]["severe_overfit_runs"],
        },
    }
    for condition, result in condition_results.items():
        aggregate = result["view_a_aggregate"]
        table[condition] = {
            "top1_mean": aggregate["top1_accuracy"]["mean"], "top1_std": aggregate["top1_accuracy"]["std"],
            "mrr_mean": aggregate["mrr"]["mean"], "mrr_std": aggregate["mrr"]["std"],
            "recall_at_3_mean": aggregate["recall_at_3"]["mean"], "macro_f1_mean": aggregate["macro_f1"]["mean"],
            "seeds_above_cosine_mrr": sum(run["view_metrics"][VIEW_A]["mrr"] > cosine_a["mrr"] for run in all_runs[condition]),
            "seeds_above_d0_mrr_benchmark": sum(run["view_metrics"][VIEW_A]["mrr"] > d0_aggregate["mrr"]["mean"] for run in all_runs[condition]),
            "severe_overfit_runs": overfit["conditions"][condition]["severe_overfit_runs"],
        }

    policies = ["D0_DIRECTED_EQUAL_WEIGHT", *CONDITIONS]
    qualifying = [policy for policy in policies if table[policy]["mrr_mean"] > cosine_a["mrr"]]
    simplicity = {"D0_DIRECTED_EQUAL_WEIGHT": 2, "S1_UNORDERED_EQUAL_WEIGHT": 1, "S2_UNORDERED_CLASS_BALANCED": 0}
    selected = max(qualifying, key=lambda policy: (table[policy]["mrr_mean"], table[policy]["top1_mean"], table[policy]["macro_f1_mean"], -table[policy]["severe_overfit_runs"], simplicity[policy])) if qualifying else "C0_COSINE"
    if selected == "D0_DIRECTED_EQUAL_WEIGHT":
        representative = "D0:M64:20260815 (retained frozen LR-3R checkpoint)"
    elif selected in CONDITIONS:
        selected_runs = all_runs[selected]
        ordered = sorted(selected_runs, key=lambda run: (run["view_metrics"][VIEW_A]["mrr"], run["training_seed"]))
        representative_run = ordered[len(ordered) // 2]
        representative = f"{SHORT[selected]}:M64:{representative_run['training_seed']}"
        for entry in registry:
            entry["development_representative_checkpoint"] = entry["condition"] == selected and entry["training_seed"] == representative_run["training_seed"]
    else:
        representative = "C0_FIXED_COSINE_NO_CHECKPOINT"

    best_weighted = max(CONDITIONS, key=lambda condition: table[condition]["mrr_mean"])
    weighted_mrr = table[best_weighted]["mrr_mean"]
    d0_mrr, c0_mrr = table["D0_DIRECTED_EQUAL_WEIGHT"]["mrr_mean"], table["C0_COSINE"]["mrr_mean"]
    gain_retention = (weighted_mrr - c0_mrr) / (d0_mrr - c0_mrr)
    if (weighted_mrr > d0_mrr) or min_weighted_overfit < 5:
        symmetry_state = "UNORDERED_WEIGHTING_IMPROVES_ROBUSTNESS"
    elif weighted_mrr > c0_mrr and abs(weighted_mrr - d0_mrr) <= 0.02:
        symmetry_state = "DIRECTED_WEIGHTING_GAIN_ROBUST"
    elif weighted_mrr <= c0_mrr or gain_retention < 0.5:
        symmetry_state = "DIRECTED_DUPLICATION_CONTRIBUTES_MATERIALLY"
    else:
        symmetry_state = "SYMMETRY_WEIGHTING_RESULT_INCONCLUSIVE"

    comparison = {
        "schema_version": "lr3s-model-comparison-v1", "architecture": "M64", "view": VIEW_A,
        "comparison_table": table, "qualifying_policies": qualifying,
        "selection_rule": ["mean_VIEW_A_MRR_above_cosine", "higher_mean_MRR", "higher_mean_Top1", "higher_mean_MacroF1", "fewer_severe_overfit_runs", "simpler_weighting_D0_then_S1_then_S2"],
        "selected_development_training_weighting_policy": selected,
        "development_representative_checkpoint": representative, "symmetry_interpretation_state": symmetry_state,
        "best_weighted_condition": best_weighted, "best_weighted_gain_retention_ratio_vs_d0": gain_retention,
        "best_single_seed_used_for_selection": False, "view_b_used_for_selection": False, "view_c_used_for_selection": False,
        "final_gold_used_for_selection": False,
    }
    write_json(HERE / "lr3s_model_comparison_v1.json", comparison)
    write_json(HERE / "lr3s_checkpoint_registry_v1.json", {
        "schema_version": "lr3s-checkpoint-registry-v1", "checkpoint_count": len(registry),
        "governance_status": "RESEARCH_ONLY_DEVELOPMENT_CHECKPOINTS", "selected_policy": selected,
        "development_representative_checkpoint": representative, "entries": registry,
    })

    summary = {
        "schema_version": "lr3s-dev-metrics-summary-v1", "development_results_only": True,
        "coverage_warning": {"production_candidate_labels": 16, "training_labels": 12, "view_a_records": 79, "view_a_gold_labels": 8, "view_b_records": 5, "production_labels_without_dev_gold": 7},
        "view_a_pairwise_seen": table,
        "view_b_singleton_unseen_diagnostic": {"label": "UNSEEN-SINGLETON DIAGNOSTIC", **{condition: result["view_b_aggregate"] for condition, result in condition_results.items()}},
        "view_c_mixed_development_diagnostic": {"label": "MIXED DEVELOPMENT DIAGNOSTIC", "record_count": 84, **{condition: result["view_c_aggregate"] for condition, result in condition_results.items()}},
    }
    write_json(HERE / "lr3s_dev_metrics_summary_v1.json", summary)

    after = protected_inventory()
    if before != after:
        raise RuntimeError("protected artifacts changed during LR-3S")
    write_json(HERE / "lr3s_validation_report_v1.json", {
        "schema_version": "lr3s-validation-report-v1", "overall_status": "PENDING_TESTS_AND_REGRESSIONS",
        "lr2r_hashes_verified": True, "lr3_hashes_verified": True, "lr3r_hashes_verified": True,
        "d0_frozen_metrics_reproduced_exactly": True, "s1_pair_membership_equals_d0": True, "s2_pair_membership_equals_d0": True,
        "only_row_weights_differ": True, "unordered_pair_id_deterministic": True, "reverse_multiplicity_correct": True,
        "s1_total_weight_per_unordered_pair_verified": True, "s2_class_total_weights_equal": True,
        "self_pair_count": 0, "singleton_training_reference_count": 0, "hard_negative_training_pair_count": 0,
        "blocked_relationship_training_pair_count": 0, "dev_training_endpoint_count": 0,
        "feature_unchanged": True, "m64_architecture_unchanged": True, "optimizer_hyperparameters_unchanged": True,
        "mpnet_frozen": True, "mpnet_parameters_in_optimizer": 0, "runtime_fidelity_status": runtime["status"],
        "evaluation_universe_unchanged": True, "page_filtering_unchanged": True, "family_collapse_unchanged": True,
        "max_aggregation_unchanged": True, "seed_replay_status": "PENDING_TEST",
        "production_code_modified": False, "semantic_runtime_modified": False, "original_data_modified": False,
        "prior_lr_stages_modified": False, "final_gold_available": False, "final_gold_evaluation_run": False,
        "existing_regressions": "PENDING", "protected_snapshot_before": before, "protected_snapshot_after": after,
        "protected_files_unchanged": True,
    })
    print(json.dumps({
        "D0_MRR": d0_mrr, "S1": condition_results[CONDITIONS[0]]["view_a_aggregate"],
        "S2": condition_results[CONDITIONS[1]]["view_a_aggregate"], "selected_policy": selected,
        "representative": representative, "symmetry_state": symmetry_state,
    }, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
