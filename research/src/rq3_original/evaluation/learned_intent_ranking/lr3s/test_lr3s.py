"""Governance, weighting, determinism, and evaluator tests for LR-3S."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
LR3 = HERE.parent / "lr3"
LR3R = HERE.parent / "lr3r"
ROOT = HERE.parents[2]
for path in [str(HERE), str(LR3), str(LR3R), str(ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from compact_models import build_compact_model
from data_loader import (
    LR1R, LR2R, build_epoch_sampler_inputs, generate_epoch_pairs, load_dev_views,
    load_frozen_candidate_artifacts, resolve_dev_records, sha256_file, verify_checksum_manifest,
)
from evaluate_ranker import evaluate_records, learned_score_function
from feature_builder import numpy_pair_features, torch_pair_features
from runtime_fidelity import run_runtime_fidelity_preflight

from weighted_train import (
    BATCH_SIZE, EARLY_STOPPING_PATIENCE, GRADIENT_CLIP_NORM, LEARNING_RATE, MAX_EPOCHS,
    TRAINING_SEEDS, WEIGHT_DECAY, configure_determinism, parameter_tensor_hash, train_one_seed,
)
from weighting import CONDITIONS, directed_membership_hash, unordered_pair_id, weight_epoch_rows


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class LR3SResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_determinism()
        cls.sampler = build_epoch_sampler_inputs()
        cls.frozen = load_frozen_candidate_artifacts()
        cls.dev = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
        cls.views = load_dev_views(cls.dev)
        cls.runtime, cls.query_vectors, cls.cosine, cls.mpnet = run_runtime_fidelity_preflight(cls.dev, cls.frozen)
        cls.registry = read_json(HERE / "lr3s_checkpoint_registry_v1.json")
        cls.validation = read_json(HERE / "lr3s_validation_report_v1.json")
        cls.protocol = read_json(HERE / "lr3s_experiment_protocol_v1.json")
        cls.embedding_by_id = {
            example_id: cls.frozen["embeddings"][position].copy()
            for position, example_id in enumerate(cls.frozen["example_ids"])
        }

    def test_prior_stage_hashes_pass(self):
        contracts = [
            (LR2R, "lr2r_output_checksums_v1.sha256"),
            (LR3, "lr3_output_checksums_v1.sha256"),
            (LR3R, "lr3r_output_checksums_v1.sha256"),
        ]
        for directory, manifest in contracts:
            self.assertTrue(all(row["match"] for row in verify_checksum_manifest(directory / manifest, directory)))

    def test_d0_frozen_metrics_reproduce_exactly(self):
        d0 = read_json(LR3R / "lr3r_m64_training_results_v1.json")["view_a_aggregate"]
        comparison = read_json(HERE / "lr3s_model_comparison_v1.json")["comparison_table"]["D0_DIRECTED_EQUAL_WEIGHT"]
        self.assertEqual(d0["mrr"]["mean"], 0.6561020695197911)
        self.assertEqual(comparison["mrr_mean"], d0["mrr"]["mean"])
        self.assertEqual(comparison["top1_mean"], d0["top1_accuracy"]["mean"])
        self.assertEqual(comparison["macro_f1_mean"], d0["macro_f1"]["mean"])

    def test_membership_identical_and_only_weights_differ(self):
        weighted_only = {"unordered_pair_id", "unordered_pair_multiplicity", "base_pair_weight", "class_multiplier", "final_row_weight"}
        for epoch in range(50):
            d0 = generate_epoch_pairs(self.sampler, epoch)
            for condition in CONDITIONS:
                weighted, audit = weight_epoch_rows(d0, condition, epoch)
                self.assertEqual(audit["directed_membership_sha256"], directed_membership_hash(d0))
                self.assertEqual([row["pair_id"] for row in weighted], [row["pair_id"] for row in d0])
                for baseline, row in zip(d0, weighted):
                    self.assertEqual(baseline, {key: value for key, value in row.items() if key not in weighted_only})

    def test_unordered_identity_and_multiplicity_are_deterministic(self):
        self.assertEqual(unordered_pair_id("b", "a"), unordered_pair_id("a", "b"))
        self.assertNotEqual(unordered_pair_id("ab", "c"), unordered_pair_id("a", "bc"))
        for epoch in range(50):
            rows, audit = weight_epoch_rows(generate_epoch_pairs(self.sampler, epoch), CONDITIONS[0], epoch)
            self.assertEqual(audit["unexpected_multiplicity_count"], 0)
            self.assertTrue(all(row["unordered_pair_multiplicity"] in {1, 2} for row in rows))

    def test_s1_and_s2_weight_invariants(self):
        for epoch in range(50):
            directed = generate_epoch_pairs(self.sampler, epoch)
            s1, s1_audit = weight_epoch_rows(directed, CONDITIONS[0], epoch)
            s2, s2_audit = weight_epoch_rows(directed, CONDITIONS[1], epoch)
            for rows, use_base in [(s1, False), (s2, True)]:
                totals = {}
                for row in rows:
                    value = row["base_pair_weight"] if use_base else row["final_row_weight"]
                    totals[row["unordered_pair_id"]] = totals.get(row["unordered_pair_id"], 0.0) + value
                self.assertTrue(all(abs(value - 1.0) <= 1e-12 for value in totals.values()))
            self.assertAlmostEqual(s2_audit["total_effective_positive_weight"], s2_audit["total_effective_negative_weight"], places=12)
            self.assertEqual(s1_audit["effective_total_sample_weight"], s2_audit["effective_total_sample_weight"])

    def test_training_pair_prohibitions(self):
        dev_ids = {row["record_id"] for row in self.dev}
        for epoch in range(50):
            for row in generate_epoch_pairs(self.sampler, epoch):
                endpoints = {row["anchor_record_id"], row["candidate_record_id"]}
                self.assertNotEqual(row["anchor_record_id"], row["candidate_record_id"])
                self.assertTrue(endpoints <= self.sampler["eligible_ids"])
                self.assertFalse(endpoints & self.sampler["singleton_ids"])
                self.assertFalse(endpoints & dev_ids)
                self.assertIn(row["relationship_class"], {"SAME_INTENT_POSITIVE", "SAFE_RANDOM_NEGATIVE"})

    def test_feature_and_m64_architecture_unchanged(self):
        q, c = self.frozen["embeddings"][:2]
        feature = numpy_pair_features(q, c)
        np.testing.assert_array_equal(feature, numpy_pair_features(c, q))
        tq, tc = torch.from_numpy(q[None].copy()), torch.from_numpy(c[None].copy())
        torch.testing.assert_close(torch_pair_features(tq, tc), torch.from_numpy(feature[None]), rtol=0, atol=0)
        model = build_compact_model("M64", 1536)
        self.assertEqual(model.hidden.out_features, 64)
        self.assertEqual(model.dropout.p, 0.5)
        self.assertEqual(sum(parameter.numel() for parameter in model.parameters()), 101505)

    def test_optimizer_hyperparameters_and_mpnet_frozen(self):
        lr3r = read_json(LR3R / "lr3r_experiment_protocol_v1.json")
        self.assertEqual(tuple(self.protocol["training_seeds"]), TRAINING_SEEDS)
        for key, value in {
            "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY, "batch_size": BATCH_SIZE,
            "max_epochs": MAX_EPOCHS, "early_stopping_patience": EARLY_STOPPING_PATIENCE,
            "gradient_clip_norm": GRADIENT_CLIP_NORM, "dropout": 0.5,
        }.items():
            self.assertEqual(self.protocol[key], value)
            self.assertEqual(self.protocol[key], lr3r[key])
        self.assertTrue(all(not parameter.requires_grad for parameter in self.mpnet.parameters()))
        model = build_compact_model("M64", 1536)
        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
        self.assertFalse({id(p) for group in optimizer.param_groups for p in group["params"]} & {id(p) for p in self.mpnet.parameters()})

    def test_checkpoint_hashes_and_same_seed_replay(self):
        for condition in CONDITIONS:
            expected = next(entry for entry in self.registry["entries"] if entry["condition"] == condition and entry["training_seed"] == 20260813)
            checkpoint = torch.load(HERE / expected["checkpoint_path"], map_location="cpu", weights_only=True)
            self.assertEqual(parameter_tensor_hash(checkpoint["state_dict"]), expected["checkpoint_tensor_hash"])
            replay = train_one_seed(
                condition=condition, training_seed=20260813, sampler=self.sampler, embedding_by_id=self.embedding_by_id,
                dev_records=self.dev, dev_query_vectors=self.query_vectors, index_records=self.frozen["index_records"],
                index_embeddings=self.frozen["embeddings"], view_ids=self.views,
                production_labels=self.frozen["production_labels"], mpnet_model=self.mpnet,
            )
            self.assertEqual(replay["checkpoint_tensor_hash"], expected["checkpoint_tensor_hash"])
            self.assertEqual(replay["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["mrr"], expected["view_a_metrics"]["mrr"])

    def test_evaluation_universe_page_filtering_family_collapse_and_max_unchanged(self):
        reference = {row["record_id"]: row for row in self.cosine}
        for condition in CONDITIONS:
            entry = next(row for row in self.registry["entries"] if row["condition"] == condition)
            checkpoint = torch.load(HERE / entry["checkpoint_path"], map_location="cpu", weights_only=True)
            model = build_compact_model("M64", 1536); model.load_state_dict(checkpoint["state_dict"])
            predictions = evaluate_records(self.dev, self.query_vectors, self.frozen["index_records"], self.frozen["embeddings"], learned_score_function(model))
            for row in predictions:
                frozen = reference[row["record_id"]]
                self.assertEqual(row["eligible_example_count"], frozen["eligible_example_count"])
                self.assertEqual(row["eligible_label_count"], frozen["eligible_label_count"])
                self.assertEqual(row["excluded_current_page_records"], frozen["excluded_current_page_records"])
                by_id = {hit["example_id"]: hit for hit in row["example_hits"]}
                for candidate in row["intent_ranking"]:
                    self.assertEqual(candidate["score"], by_id[candidate["example_ids"][0]]["score"])
                    self.assertEqual(candidate["score"], max(hit["score"] for hit in row["example_hits"] if hit["semantic_label"] == candidate["label"]))

    def test_protected_files_unchanged(self):
        self.assertEqual(self.validation["protected_snapshot_before"], self.validation["protected_snapshot_after"])
        for snapshot in self.validation["protected_snapshot_before"].values():
            for relative, digest in snapshot.items():
                self.assertEqual(sha256_file(ROOT / relative), digest)


if __name__ == "__main__":
    unittest.main()
