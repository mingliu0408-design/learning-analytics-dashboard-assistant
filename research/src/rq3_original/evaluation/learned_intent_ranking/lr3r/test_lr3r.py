"""Governance, architecture, determinism, and evaluation tests for LR-3R."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
LR3 = HERE.parent / "lr3"
ROOT = HERE.parents[2]
for path in [str(HERE), str(LR3), str(ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from data_loader import (
    LR1R,
    LR2R,
    build_epoch_sampler_inputs,
    generate_epoch_pairs,
    load_dev_views,
    load_frozen_candidate_artifacts,
    resolve_dev_records,
    sha256_file,
    verify_checksum_manifest,
)
from evaluate_ranker import evaluate_records, learned_score_function
from feature_builder import expected_feature_dimension, numpy_pair_features, torch_pair_features
from runtime_fidelity import run_runtime_fidelity_preflight

from compact_models import build_compact_model
from compact_train import (
    BATCH_SIZE,
    EARLY_STOPPING_PATIENCE,
    GRADIENT_CLIP_NORM,
    LEARNING_RATE,
    MAX_EPOCHS,
    TRAINING_SEEDS,
    WEIGHT_DECAY,
    configure_determinism,
    parameter_tensor_hash,
    train_one_seed,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class LR3RResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_determinism()
        cls.sampler = build_epoch_sampler_inputs()
        cls.frozen = load_frozen_candidate_artifacts()
        cls.dev = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
        cls.views = load_dev_views(cls.dev)
        cls.runtime, cls.query_vectors, cls.cosine_predictions, cls.mpnet = run_runtime_fidelity_preflight(cls.dev, cls.frozen)
        cls.registry = read_json(HERE / "lr3r_checkpoint_registry_v1.json")
        cls.validation = read_json(HERE / "lr3r_validation_report_v1.json")
        cls.protocol = read_json(HERE / "lr3r_experiment_protocol_v1.json")
        cls.embedding_by_id = {
            example_id: cls.frozen["embeddings"][position].copy()
            for position, example_id in enumerate(cls.frozen["example_ids"])
        }

    def test_frozen_lr3_and_lr2r_hashes_verify(self):
        lr3 = verify_checksum_manifest(LR3 / "lr3_output_checksums_v1.sha256", LR3)
        lr2r = verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R)
        self.assertTrue(all(row["match"] for row in lr3))
        self.assertTrue(all(row["match"] for row in lr2r))

    def test_training_pair_membership_and_prohibitions(self):
        dev_ids = {row["record_id"] for row in self.dev}
        for epoch in range(50):
            rows = generate_epoch_pairs(self.sampler, epoch)
            self.assertEqual(len(rows), 228)
            self.assertEqual(sum(row["target"] for row in rows), 114)
            for row in rows:
                endpoints = {row["anchor_record_id"], row["candidate_record_id"]}
                self.assertTrue(endpoints <= self.sampler["eligible_ids"])
                self.assertFalse(endpoints & self.sampler["singleton_ids"])
                self.assertFalse(endpoints & dev_ids)
                self.assertEqual(
                    row["relationship_class"],
                    "SAME_INTENT_POSITIVE" if row["target"] else "SAFE_RANDOM_NEGATIVE",
                )

    def test_feature_construction_is_unchanged(self):
        q, c = self.frozen["embeddings"][:2]
        feature = numpy_pair_features(q, c)
        self.assertEqual(feature.shape, (1536,))
        np.testing.assert_array_equal(feature, numpy_pair_features(c, q))
        tq, tc = torch.from_numpy(q[None].copy()), torch.from_numpy(c[None].copy())
        torch.testing.assert_close(torch_pair_features(tq, tc), torch.from_numpy(feature[None]), rtol=0, atol=0)

    def test_compact_architectures_exactly_match_specification(self):
        features = torch.zeros((2, 1536), dtype=torch.float32)
        expected = {"M64": (64, 101505), "M128": (128, 199937)}
        for family, (hidden, parameter_count) in expected.items():
            model = build_compact_model(family, 1536)
            self.assertEqual(tuple(model.layer_norm.normalized_shape), (1536,))
            self.assertEqual(model.hidden.in_features, 1536)
            self.assertEqual(model.hidden.out_features, hidden)
            self.assertIsInstance(model.activation, torch.nn.ReLU)
            self.assertEqual(model.dropout.p, 0.5)
            self.assertEqual(model.output.in_features, hidden)
            self.assertEqual(model.output.out_features, 1)
            self.assertEqual(model(features).shape, (2,))
            self.assertEqual(sum(parameter.numel() for parameter in model.parameters()), parameter_count)

    def test_mpnet_frozen_and_optimizer_scorer_only(self):
        self.assertTrue(all(not parameter.requires_grad for parameter in self.mpnet.parameters()))
        mpnet_ids = {id(parameter) for parameter in self.mpnet.parameters()}
        for family in ["M64", "M128"]:
            model = build_compact_model(family, 1536)
            optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
            optimizer_ids = {id(parameter) for group in optimizer.param_groups for parameter in group["params"]}
            self.assertFalse(mpnet_ids & optimizer_ids)
            self.assertEqual(optimizer_ids, {id(parameter) for parameter in model.parameters()})

    def test_seeds_and_hyperparameters_equal_lr3(self):
        lr3_protocol = read_json(LR3 / "lr3_experiment_protocol_v1.json")
        self.assertEqual(tuple(self.protocol["training_seeds"]), TRAINING_SEEDS)
        for key, value in {
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "batch_size": BATCH_SIZE,
            "max_epochs": MAX_EPOCHS,
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
            "gradient_clip_norm": GRADIENT_CLIP_NORM,
            "dropout": 0.5,
            "loss": "BCEWithLogitsLoss",
        }.items():
            self.assertEqual(self.protocol[key], value)
            if key != "dropout":
                self.assertEqual(self.protocol[key], lr3_protocol[key])

    def test_checkpoint_metadata_and_tensor_hashes_resolve(self):
        self.assertEqual(self.registry["checkpoint_count"], 10)
        for entry in self.registry["entries"]:
            checkpoint_path = HERE / entry["checkpoint_path"]
            metadata = read_json(HERE / entry["metadata_path"])
            checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            self.assertEqual(sha256_file(checkpoint_path), metadata["checkpoint_file_sha256"])
            self.assertEqual(parameter_tensor_hash(checkpoint["state_dict"]), metadata["checkpoint_tensor_hash"])
            self.assertEqual(metadata["mpnet_parameters_in_optimizer"], 0)

    def test_same_seed_replay_reproduces_tensor_hashes(self):
        for family in ["M64", "M128"]:
            expected = next(
                entry for entry in self.registry["entries"]
                if entry["model_family"] == family and entry["training_seed"] == 20260813
            )
            replay = train_one_seed(
                model_family=family,
                training_seed=20260813,
                feature_dimension=1536,
                sampler=self.sampler,
                embedding_by_id=self.embedding_by_id,
                dev_records=self.dev,
                dev_query_vectors=self.query_vectors,
                index_records=self.frozen["index_records"],
                index_embeddings=self.frozen["embeddings"],
                view_ids=self.views,
                production_labels=self.frozen["production_labels"],
                mpnet_model=self.mpnet,
            )
            self.assertEqual(replay["checkpoint_tensor_hash"], expected["checkpoint_tensor_hash"])
            self.assertEqual(replay["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["mrr"], expected["view_a_metrics"]["mrr"])

    def test_evaluation_universe_family_collapse_and_max_aggregation_unchanged(self):
        cosine = {row["record_id"]: row for row in self.cosine_predictions}
        for family in ["M64", "M128"]:
            entry = next(row for row in self.registry["entries"] if row["model_family"] == family)
            checkpoint = torch.load(HERE / entry["checkpoint_path"], map_location="cpu", weights_only=True)
            model = build_compact_model(family, 1536)
            model.load_state_dict(checkpoint["state_dict"])
            predictions = evaluate_records(
                self.dev, self.query_vectors, self.frozen["index_records"], self.frozen["embeddings"], learned_score_function(model)
            )
            for row in predictions:
                reference = cosine[row["record_id"]]
                self.assertEqual(row["eligible_example_count"], reference["eligible_example_count"])
                self.assertEqual(row["eligible_label_count"], reference["eligible_label_count"])
                self.assertEqual(row["excluded_current_page_records"], reference["excluded_current_page_records"])
                by_id = {hit["example_id"]: hit for hit in row["example_hits"]}
                for candidate in row["intent_ranking"]:
                    contributor = by_id[candidate["example_ids"][0]]
                    self.assertEqual(candidate["score"], contributor["score"])
                    self.assertEqual(candidate["score"], max(hit["score"] for hit in row["example_hits"] if hit["semantic_label"] == candidate["label"]))

    def test_frozen_reference_metrics_match_lr3_exactly(self):
        comparison = read_json(HERE / "lr3r_model_comparison_v1.json")["architecture_table"]
        cosine = read_json(LR3 / "lr3_cosine_baseline_results_v1.json")["views"]["VIEW_A_PAIRWISE_SEEN"]
        l1 = read_json(LR3 / "lr3_linear_training_results_v1.json")["view_a_aggregate"]
        m1 = read_json(LR3 / "lr3_mlp_training_results_v1.json")["view_a_aggregate"]
        self.assertEqual(comparison["C0"]["mrr_mean"], cosine["mrr"])
        for family, frozen in [("L1", l1), ("M1", m1)]:
            self.assertEqual(comparison[family]["mrr_mean"], frozen["mrr"]["mean"])
            self.assertEqual(comparison[family]["top1_mean"], frozen["top1_accuracy"]["mean"])
            self.assertEqual(comparison[family]["macro_f1_mean"], frozen["macro_f1"]["mean"])

    def test_bootstrap_is_deterministic(self):
        artifact = read_json(HERE / "lr3r_development_uncertainty_analysis_v1.json")
        self.assertEqual(artifact["bootstrap_seed"], 20260813)
        self.assertEqual(artifact["bootstrap_resamples"], 10000)
        count = artifact["query_count"]
        indices = np.random.default_rng(20260813).integers(0, count, size=(10000, count))
        for family, analysis in artifact["architectures"].items():
            deltas = np.asarray([row["delta_vs_cosine"] for row in analysis["queries"]], dtype=np.float64)
            means = deltas[indices].mean(axis=1)
            self.assertEqual(float(np.percentile(means, 2.5)), analysis["bootstrap_95_percent_ci"]["lower"])
            self.assertEqual(float(np.percentile(means, 97.5)), analysis["bootstrap_95_percent_ci"]["upper"])

    def test_protected_files_unchanged(self):
        self.assertTrue(self.validation["protected_files_unchanged"])
        self.assertEqual(self.validation["protected_snapshot_before"], self.validation["protected_snapshot_after"])
        for group, snapshot in self.validation["protected_snapshot_before"].items():
            for relative, digest in snapshot.items():
                self.assertEqual(sha256_file(ROOT / relative), digest, f"changed: {group}/{relative}")


if __name__ == "__main__":
    unittest.main()
