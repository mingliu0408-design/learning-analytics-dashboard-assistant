"""Research-only LR-3 governance, runtime, architecture, and determinism tests."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import data_loader
from data_loader import LR1R, LR2R, build_epoch_sampler_inputs, generate_epoch_pairs, load_dev_views, load_frozen_candidate_artifacts, read_json, resolve_dev_records, sha256_file, verify_checksum_manifest
from evaluate_ranker import evaluate_records, learned_score_function
from feature_builder import expected_feature_dimension, numpy_pair_features, torch_pair_features
from models import LinearSimilarityScorer, MLPSimilarityScorer
from runtime_fidelity import run_runtime_fidelity_preflight
from train_scorer import configure_determinism, parameter_tensor_hash, train_one_seed


class LR3ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_determinism()
        cls.sampler = build_epoch_sampler_inputs()
        cls.frozen = load_frozen_candidate_artifacts()
        cls.dev = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
        cls.views = load_dev_views(cls.dev)
        cls.runtime_report, cls.query_vectors, cls.cosine_predictions, cls.mpnet = run_runtime_fidelity_preflight(cls.dev, cls.frozen)
        cls.registry = read_json(HERE / "lr3_checkpoint_registry_v1.json")
        cls.validation = read_json(HERE / "lr3_validation_report_v1.json")
        cls.embedding_by_id = {
            example_id: cls.frozen["embeddings"][position].copy()
            for position, example_id in enumerate(cls.frozen["example_ids"])
        }

    def test_lr2r_hashes_and_old_baseline_never_loaded(self):
        results = verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R)
        self.assertTrue(all(row["match"] for row in results))
        old_path = ROOT / self.sampler["exclusions"]["superseded_lr2_baseline_v1"]["path"]
        calls = []
        original = data_loader.read_jsonl

        def spy(path):
            calls.append(Path(path).resolve())
            return original(path)

        with mock.patch.object(data_loader, "read_jsonl", side_effect=spy):
            rebuilt = data_loader.build_epoch_sampler_inputs()
        self.assertEqual(len(rebuilt["eligible_train"]), 58)
        self.assertNotIn(old_path.resolve(), calls)

    def test_every_training_epoch_uses_only_repaired_governance(self):
        dev_ids = {row["record_id"] for row in self.dev}
        singleton_ids = self.sampler["singleton_ids"]
        allowed = self.sampler["eligible_ids"]
        for epoch in range(50):
            rows = generate_epoch_pairs(self.sampler, epoch)
            self.assertEqual(len(rows), 228)
            self.assertEqual(sum(row["target"] for row in rows), 114)
            for row in rows:
                self.assertIn(row["anchor_record_id"], allowed)
                self.assertIn(row["candidate_record_id"], allowed)
                self.assertNotIn(row["anchor_record_id"], singleton_ids)
                self.assertNotIn(row["candidate_record_id"], singleton_ids)
                self.assertNotIn(row["anchor_record_id"], dev_ids)
                self.assertNotIn(row["candidate_record_id"], dev_ids)
                self.assertNotEqual(row["anchor_record_id"], row["candidate_record_id"])
                if row["target"] == 0:
                    self.assertEqual(row["relationship_class"], "SAFE_RANDOM_NEGATIVE")
                else:
                    self.assertEqual(row["relationship_class"], "SAME_INTENT_POSITIVE")

    def test_feature_dimension_symmetry_and_model_shapes(self):
        dimension = self.frozen["embedding_dimension"]
        feature_dimension = expected_feature_dimension(dimension)
        self.assertEqual(dimension, 768)
        self.assertEqual(feature_dimension, 1536)
        q = self.frozen["embeddings"][0]
        c = self.frozen["embeddings"][1]
        np.testing.assert_array_equal(numpy_pair_features(q, c), numpy_pair_features(c, q))
        tq = torch.from_numpy(q[None, :].copy())
        tc = torch.from_numpy(c[None, :].copy())
        torch.testing.assert_close(torch_pair_features(tq, tc), torch_pair_features(tc, tq), rtol=0, atol=0)
        features = torch_pair_features(tq, tc)
        linear = LinearSimilarityScorer(feature_dimension)
        mlp = MLPSimilarityScorer(feature_dimension)
        self.assertEqual(tuple(linear.layer_norm.normalized_shape), (feature_dimension,))
        self.assertEqual(tuple(mlp.layer_norm.normalized_shape), (feature_dimension,))
        self.assertEqual(linear(features).shape, (1,))
        self.assertEqual(mlp(features).shape, (1,))
        self.assertEqual(mlp.hidden.out_features, 768)

    def test_runtime_fidelity_and_frozen_embeddings(self):
        self.assertEqual(self.runtime_report["status"], "PASS")
        self.assertEqual(self.runtime_report["record_count"], 84)
        self.assertLessEqual(self.runtime_report["max_example_score_abs_diff"], 1e-12)
        self.assertLessEqual(self.runtime_report["max_intent_score_abs_diff"], 1e-12)
        self.assertEqual(self.runtime_report["mpnet_trainable_parameter_count_in_lr3"], 0)
        matrix_hash = hashlib.sha256(self.frozen["embeddings"].tobytes(order="C")).hexdigest()
        self.assertEqual(matrix_hash, self.validation["candidate_embedding_matrix_sha256_before"])
        self.assertEqual(matrix_hash, self.validation["candidate_embedding_matrix_sha256_after"])

    def test_learned_inference_preserves_eligibility_family_max_and_universe(self):
        representative = next(
            entry for entry in self.registry["entries"] if entry["development_representative_checkpoint"]
        )
        metadata = read_json(HERE / representative["metadata_path"])
        checkpoint = torch.load(HERE / representative["checkpoint_path"], map_location="cpu", weights_only=True)
        model = MLPSimilarityScorer(metadata["feature_dimension"])
        model.load_state_dict(checkpoint["state_dict"])
        predictions = evaluate_records(
            self.dev,
            self.query_vectors,
            self.frozen["index_records"],
            self.frozen["embeddings"],
            learned_score_function(model),
        )
        cosine = {row["record_id"]: row for row in self.cosine_predictions}
        production_labels = set(self.frozen["production_labels"])
        for row in predictions:
            self.assertEqual(row["eligible_example_count"], cosine[row["record_id"]]["eligible_example_count"])
            self.assertEqual(row["excluded_current_page_records"], cosine[row["record_id"]]["excluded_current_page_records"])
            self.assertTrue({candidate["label"] for candidate in row["intent_ranking"]} <= production_labels)
            by_id = {hit["example_id"]: hit for hit in row["example_hits"]}
            for candidate in row["intent_ranking"]:
                contributor = by_id[candidate["example_ids"][0]]
                self.assertEqual(candidate["score"], contributor["score"])
                self.assertEqual(candidate["score"], max(hit["score"] for hit in row["example_hits"] if hit["semantic_label"] == candidate["label"]))

    def test_mpnet_absent_from_optimizer_and_checkpoint_metadata_resolves(self):
        self.assertTrue(all(not parameter.requires_grad for parameter in self.mpnet.parameters()))
        for entry in self.registry["entries"]:
            metadata_path = HERE / entry["metadata_path"]
            checkpoint_path = HERE / entry["checkpoint_path"]
            metadata = read_json(metadata_path)
            self.assertEqual(metadata["mpnet_parameters_in_optimizer"], 0)
            self.assertEqual(sha256_file(checkpoint_path), metadata["checkpoint_file_sha256"])
            checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            self.assertEqual(parameter_tensor_hash(checkpoint["state_dict"]), metadata["checkpoint_tensor_hash"])
            self.assertEqual(sha256_file(ROOT / "evaluation/learned_intent_ranking/lr1/ranker_train_manifest_candidate_v1.jsonl"), metadata["train_manifest_hash"])
            self.assertEqual(sha256_file(LR2R / "lr2r_episodic_sampling_spec_v1.json"), metadata["lr2r_sampling_spec_hash"])

    def test_same_seed_reproduces_l1_and_m1_tensor_hashes_predictions_and_metrics(self):
        feature_dimension = expected_feature_dimension(self.frozen["embedding_dimension"])
        for family in ["L1", "M1"]:
            expected_entry = next(
                entry for entry in self.registry["entries"]
                if entry["model_family"] == family and entry["training_seed"] == 20260813
            )
            replay = train_one_seed(
                model_family=family,
                training_seed=20260813,
                feature_dimension=feature_dimension,
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
            self.assertEqual(replay["checkpoint_tensor_hash"], expected_entry["checkpoint_tensor_hash"])
            saved_predictions = read_json(HERE / f"results/{family.lower()}_seed_20260813_dev_predictions_v1.json")["predictions"]
            self.assertEqual([row["top1_label"] for row in replay["predictions"]], [row["top1_label"] for row in saved_predictions])
            self.assertEqual(replay["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["mrr"], expected_entry["view_a_metrics"]["mrr"])
            self.assertEqual(replay["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]["top1_accuracy"], expected_entry["view_a_metrics"]["top1_accuracy"])

    def test_protected_files_unchanged(self):
        self.assertTrue(self.validation["protected_files_unchanged"])
        self.assertEqual(self.validation["protected_snapshot_before"], self.validation["protected_snapshot_after"])


if __name__ == "__main__":
    unittest.main()

