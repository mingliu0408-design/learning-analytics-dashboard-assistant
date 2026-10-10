"""Deterministic contract and leakage tests for RQ2-V2 Stage 4H."""

from __future__ import annotations

import csv
import json
import socket
import unittest
from pathlib import Path

import numpy as np

from .track_h import (
    CAPABILITIES,
    DEV_PROTOCOL_ROOT,
    ENCODER_DIMENSION,
    ENCODER_MODEL_NAME,
    ENCODER_REVISION,
    EXPECTED_SOURCE_HASHES,
    FEATURE_PROFILE,
    FORBIDDEN_SERIALIZED_FIELDS,
    FOLD_IDS,
    PACKAGE_ROOT,
    SEMANTIC_FIELDS,
    SERIALIZER_VERSION,
    B3Config,
    ContractError,
    DegenerateLabelError,
    apply_thresholds,
    b2_outer_fold,
    b3_candidate_grid,
    b3_outer_fold,
    deterministic_learning_subset,
    embedding_matrix_hash,
    fit_ovr,
    fit_prototypes,
    load_answer_dataset,
    network_blocked,
    predict_from_b2_payload,
    predict_from_b3_payload,
    select_b3_candidate,
    select_threshold,
    serialize_semantic_input,
    sha256_file,
    source_text_hash,
    verify_source_hashes,
)


def read_csv(name: str) -> list[dict[str, str]]:
    with (PACKAGE_ROOT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class Stage4HContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_answer_dataset()
        cls.embedding_path = PACKAGE_ROOT / "dev_embeddings_v1.npy"
        cls.X = np.load(cls.embedding_path, allow_pickle=False)
        cls.embedding_identity = json.loads(
            (PACKAGE_ROOT / "dev_embedding_identity_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.metrics = json.loads(
            (PACKAGE_ROOT / "track_h_metrics_v1.json").read_text(encoding="utf-8")
        )

    def test_01_frozen_dev_source_hashes(self) -> None:
        self.assertEqual(verify_source_hashes(), EXPECTED_SOURCE_HASHES)

    def test_02_answer_only_training_population(self) -> None:
        self.assertEqual(self.dataset.size, 64)
        self.assertEqual(len({row["scenario_family_id"] for row in self.dataset.rows}), 32)
        self.assertTrue(
            all(row["final_dialogue_action"] == "ANSWER" for row in self.dataset.rows)
        )
        np.testing.assert_array_equal(np.sum(self.dataset.y, axis=0), [32, 32, 32])
        self.assertEqual(
            self.metrics["population"]["clarify_utterances_used_as_capability_negatives"],
            0,
        )

    def test_03_zero_heldout_identifiers_in_dev_population(self) -> None:
        self.assertTrue(all(row["partition"] == "DEV" for row in self.dataset.rows))
        self.assertTrue(
            all("TEST" not in row["annotation_case_id"] for row in self.dataset.rows)
        )
        audit = self.metrics["governance_audit"]
        self.assertEqual(audit["held_out_artifact_access_count"], 0)
        self.assertEqual(audit["held_out_identifier_count"], 0)

    def test_04_family_and_atomic_component_isolation(self) -> None:
        family_folds: dict[str, set[str]] = {}
        component_folds: dict[str, set[str]] = {}
        for row in self.dataset.rows:
            family_folds.setdefault(row["scenario_family_id"], set()).add(row["fold_id"])
            component_folds.setdefault(row["dev_atomic_component_id"], set()).add(
                row["fold_id"]
            )
        self.assertTrue(all(len(folds) == 1 for folds in family_folds.values()))
        self.assertTrue(all(len(folds) == 1 for folds in component_folds.values()))
        self.assertEqual(set(self.dataset.fold_ids), set(FOLD_IDS))

    def test_05_embedding_revision_dimension_and_hash(self) -> None:
        identity = self.embedding_identity
        self.assertEqual(identity["model_name"], ENCODER_MODEL_NAME)
        self.assertEqual(identity["revision"], ENCODER_REVISION)
        self.assertEqual(identity["dimension"], ENCODER_DIMENSION)
        self.assertEqual(self.X.shape, (64, ENCODER_DIMENSION))
        self.assertEqual(self.X.dtype, np.dtype("float32"))
        self.assertEqual(
            embedding_matrix_hash(self.X), identity["embedding_matrix_sha256"]
        )
        self.assertEqual(
            sha256_file(self.embedding_path), identity["embedding_artifact_sha256"]
        )

    def test_06_source_text_and_serializer_identity(self) -> None:
        self.assertEqual(self.embedding_identity["feature_profile"], FEATURE_PROFILE)
        self.assertEqual(
            self.embedding_identity["serializer_version"], SERIALIZER_VERSION
        )
        self.assertEqual(
            self.embedding_identity["source_text_sha256"],
            source_text_hash(self.dataset.serialized_texts),
        )

    def test_07_hidden_fields_absent_from_serialized_text(self) -> None:
        for row, serialized in zip(
            self.dataset.rows, self.dataset.serialized_texts, strict=True
        ):
            decoded = json.loads(serialized)
            self.assertEqual(tuple(decoded), SEMANTIC_FIELDS)
            for field in FORBIDDEN_SERIALIZED_FIELDS:
                self.assertNotIn(field, decoded)
            self.assertEqual(serialized, serialize_semantic_input(row))

    def test_08_no_network_or_model_download_contract(self) -> None:
        identity = self.embedding_identity
        self.assertTrue(identity["local_files_only"])
        self.assertTrue(identity["network_blocked"])
        self.assertFalse(identity["model_weights_committed"])
        audit = self.metrics["governance_audit"]
        self.assertEqual(audit["network_call_count"], 0)
        self.assertEqual(audit["model_download_count"], 0)
        with self.assertRaises(ContractError):
            with network_blocked():
                socket.create_connection(("127.0.0.1", 9), timeout=0.01)

    def test_09_b2_inner_outer_indices_are_disjoint(self) -> None:
        outer = FOLD_IDS[0]
        result = b2_outer_fold(self.X, self.dataset.y, self.dataset.fold_ids, outer)
        training = set(result["outer_train_indices"].tolist())
        validation = set(result["outer_validation_indices"].tolist())
        self.assertFalse(training & validation)
        self.assertEqual(training | validation, set(range(64)))
        self.assertEqual(len(training), 48)
        self.assertEqual(len(validation), 16)
        self.assertEqual(result["inner_oof_scores"].shape, (48, 3))

    def test_10_b2_outer_validation_labels_unused_for_thresholds(self) -> None:
        outer = FOLD_IDS[1]
        baseline = b2_outer_fold(
            self.X, self.dataset.y, self.dataset.fold_ids, outer
        )
        mutated_y = self.dataset.y.copy()
        validation = self.dataset.fold_ids == outer
        mutated_y[validation] = 1 - mutated_y[validation]
        mutated = b2_outer_fold(self.X, mutated_y, self.dataset.fold_ids, outer)
        self.assertEqual(baseline["thresholds"], mutated["thresholds"])
        np.testing.assert_array_equal(
            baseline["validation_scores"], mutated["validation_scores"]
        )
        np.testing.assert_array_equal(
            baseline["validation_predictions"], mutated["validation_predictions"]
        )

    def test_11_b3_inner_outer_indices_are_disjoint(self) -> None:
        outer = FOLD_IDS[0]
        candidates = b3_candidate_grid()[:2]
        result = b3_outer_fold(
            self.X,
            self.dataset.y,
            self.dataset.fold_ids,
            self.dataset.rows,
            outer,
            candidates,
        )
        training = set(result["outer_train_indices"].tolist())
        validation = set(result["outer_validation_indices"].tolist())
        self.assertFalse(training & validation)
        self.assertEqual(training | validation, set(range(64)))
        self.assertEqual(len(result["candidate_results"]), 2)

    def test_12_b3_outer_validation_labels_unused_for_selection(self) -> None:
        outer = FOLD_IDS[2]
        candidates = b3_candidate_grid()[:2]
        baseline = b3_outer_fold(
            self.X,
            self.dataset.y,
            self.dataset.fold_ids,
            self.dataset.rows,
            outer,
            candidates,
        )
        mutated_y = self.dataset.y.copy()
        validation = self.dataset.fold_ids == outer
        mutated_y[validation] = 1 - mutated_y[validation]
        mutated = b3_outer_fold(
            self.X,
            mutated_y,
            self.dataset.fold_ids,
            self.dataset.rows,
            outer,
            candidates,
        )
        self.assertEqual(
            baseline["selected"]["config"], mutated["selected"]["config"]
        )
        self.assertEqual(
            baseline["selected"]["thresholds"], mutated["selected"]["thresholds"]
        )
        np.testing.assert_array_equal(
            baseline["validation_probabilities"],
            mutated["validation_probabilities"],
        )
        np.testing.assert_array_equal(
            baseline["validation_predictions"], mutated["validation_predictions"]
        )

    def test_13_fixed_b3_candidate_grid(self) -> None:
        grid = b3_candidate_grid()
        self.assertEqual(len(grid), 8)
        self.assertEqual(
            [(config.C, config.class_weight) for config in grid],
            [
                (0.01, None),
                (0.01, "balanced"),
                (0.1, None),
                (0.1, "balanced"),
                (1.0, None),
                (1.0, "balanced"),
                (10.0, None),
                (10.0, "balanced"),
            ],
        )
        frozen = json.loads(
            (PACKAGE_ROOT / "b3_candidate_grid_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(frozen["candidate_count"], 8)
        self.assertFalse(frozen["grid_expanded_after_scoring"])

    def test_14_threshold_objective_and_tie_break_order(self) -> None:
        perfect = select_threshold(
            np.asarray([0.0, 1.0, 2.0, 3.0]), np.asarray([0, 0, 1, 1])
        )
        self.assertEqual(perfect["threshold"], 2.0)
        self.assertEqual(perfect["f1"], 1.0)
        recall_priority = select_threshold(
            np.asarray([0.0, 1.0, 2.0, 3.0]), np.asarray([1, 0, 1, 0])
        )
        predictions = apply_thresholds(
            np.asarray([[0.0], [1.0], [2.0], [3.0]]),
            [recall_priority],
        )[:, 0]
        self.assertGreaterEqual(int(np.sum(predictions)), 1)
        self.assertEqual(
            recall_priority,
            select_threshold(
                np.asarray([0.0, 1.0, 2.0, 3.0]), np.asarray([1, 0, 1, 0])
            ),
        )

    def test_15_deterministic_b3_config_selection_and_simplicity(self) -> None:
        tied_metrics = {
            "macro_f1": 0.5,
            "exact_capability_set_match": 0.25,
            "jaccard": 0.4,
            "under_routing_rate": 0.2,
            "over_routing_rate": 0.3,
        }
        candidates = [
            {
                "config": B3Config("z", 1.0, None),
                "metrics": tied_metrics,
            },
            {
                "config": B3Config("b", 0.1, "balanced"),
                "metrics": tied_metrics,
            },
            {
                "config": B3Config("a", 0.1, None),
                "metrics": tied_metrics,
            },
        ]
        self.assertEqual(select_b3_candidate(candidates)["config"].config_id, "a")

    def test_16_degenerate_label_failure_handling(self) -> None:
        X = np.asarray([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]])
        y = np.asarray([[1, 0, 1], [1, 1, 0], [1, 0, 1]])
        with self.assertRaises(DegenerateLabelError):
            fit_prototypes(X, y, "unit-test degenerate prototypes")
        with self.assertRaises(DegenerateLabelError):
            fit_ovr(X, y, b3_candidate_grid()[0], "unit-test degenerate OvR")
        with self.assertRaises(DegenerateLabelError):
            select_threshold(np.asarray([0.0, 1.0]), np.asarray([1, 1]))

    def test_17_b2_frozen_model_json_roundtrip_reproducibility(self) -> None:
        payload = json.loads(
            (PACKAGE_ROOT / "b2_frozen_model_v1.json").read_text(encoding="utf-8")
        )
        scores, predictions = predict_from_b2_payload(self.X, payload)
        roundtrip = json.loads(json.dumps(payload, sort_keys=True))
        scores_again, predictions_again = predict_from_b2_payload(self.X, roundtrip)
        np.testing.assert_array_equal(scores, scores_again)
        np.testing.assert_array_equal(predictions, predictions_again)

    def test_18_b3_frozen_model_json_roundtrip_reproducibility(self) -> None:
        payload = json.loads(
            (PACKAGE_ROOT / "b3_frozen_model_v1.json").read_text(encoding="utf-8")
        )
        probabilities, predictions = predict_from_b3_payload(self.X, payload)
        roundtrip = json.loads(json.dumps(payload, sort_keys=True))
        probabilities_again, predictions_again = predict_from_b3_payload(
            self.X, roundtrip
        )
        np.testing.assert_array_equal(probabilities, probabilities_again)
        np.testing.assert_array_equal(predictions, predictions_again)

    def test_19_required_output_files_and_row_counts(self) -> None:
        required = {
            "dev_embedding_identity_v1.json",
            "b2_nested_oof_scores_v1.csv",
            "b2_nested_oof_predictions_v1.csv",
            "b2_full_dev_oof_scores_v1.csv",
            "b2_frozen_model_v1.json",
            "b3_candidate_grid_v1.json",
            "b3_outer_fold_selection_v1.csv",
            "b3_nested_oof_probabilities_v1.csv",
            "b3_nested_oof_predictions_v1.csv",
            "b3_full_dev_candidate_results_v1.csv",
            "b3_full_dev_oof_probabilities_v1.csv",
            "b3_frozen_model_v1.json",
            "learning_curves_v1.csv",
            "track_h_metrics_v1.json",
            "TRACK_H_DEV_RESULTS.md",
            "STATUS.md",
        }
        self.assertTrue(all((PACKAGE_ROOT / name).is_file() for name in required))
        self.assertEqual(len(read_csv("b2_nested_oof_scores_v1.csv")), 64)
        self.assertEqual(len(read_csv("b3_nested_oof_probabilities_v1.csv")), 64)
        self.assertEqual(len(read_csv("b3_full_dev_candidate_results_v1.csv")), 8)
        self.assertEqual(len(read_csv("b3_full_dev_oof_probabilities_v1.csv")), 512)
        self.assertEqual(len(read_csv("learning_curves_v1.csv")), 40)

    def test_20_nested_prediction_files_cover_each_answer_once(self) -> None:
        expected = set(self.dataset.case_ids)
        for name in (
            "b2_nested_oof_predictions_v1.csv",
            "b3_nested_oof_predictions_v1.csv",
        ):
            rows = read_csv(name)
            observed = [row["annotation_case_id"] for row in rows]
            self.assertEqual(len(observed), 64)
            self.assertEqual(set(observed), expected)
            self.assertEqual(len(set(observed)), 64)

    def test_21_learning_subsets_are_deterministic_and_component_complete(self) -> None:
        outer = FOLD_IDS[3]
        first = deterministic_learning_subset(self.dataset, outer, 0.5)
        second = deterministic_learning_subset(self.dataset, outer, 0.5)
        self.assertEqual(first["component_ids"], second["component_ids"])
        self.assertEqual(first["selection_digest"], second["selection_digest"])
        selected = set(first["indices"].tolist())
        for component in first["component_ids"]:
            complete = {
                index
                for index, row in enumerate(self.dataset.rows)
                if row["dev_atomic_component_id"] == component
                and row["fold_id"] != outer
            }
            self.assertTrue(complete)
            self.assertTrue(complete <= selected)

    def test_22_outer_fold_b3_selection_has_eight_predeclared_candidates(self) -> None:
        selections = self.metrics["b3"]["outer_fold_selections"]
        self.assertEqual(len(selections), 4)
        for selection in selections:
            self.assertEqual(len(selection["candidate_summaries"]), 8)
            config_ids = {
                item["config"]["config_id"]
                for item in selection["candidate_summaries"]
            }
            self.assertEqual(
                config_ids, {config.config_id for config in b3_candidate_grid()}
            )

    def test_23_output_manifest_hashes(self) -> None:
        manifest = json.loads(
            (PACKAGE_ROOT / "OUTPUT_SHA256_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(manifest["large_mpnet_weights_included"])
        for item in manifest["files"]:
            path = PACKAGE_ROOT / item["name"]
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_size, item["size_bytes"])
            self.assertEqual(sha256_file(path), item["sha256"])

    def test_24_writer_metrics_are_explicitly_not_evaluable(self) -> None:
        for model_key, metric_key in (
            ("b2", "nested_oof_primary_estimate"),
            ("b3", "nested_oof_primary_algorithm_estimate"),
        ):
            writer = self.metrics[model_key][metric_key]["writer_a_b_metrics"]
            self.assertEqual(writer["status"], "NOT_EVALUABLE")
            self.assertIn("absent", writer["reason"])


if __name__ == "__main__":
    unittest.main()
