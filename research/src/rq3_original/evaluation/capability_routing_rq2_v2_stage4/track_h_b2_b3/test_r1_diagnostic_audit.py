"""Tests for the read-only Stage 4H-R1 diagnostic amendment."""

from __future__ import annotations

import ast
import csv
import json
import unittest
from pathlib import Path

import numpy as np

from .diagnostic_audit import (
    BASELINE_DEFINITIONS,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EXPECTED_PRIOR_MANIFEST_SHA256,
    PACKAGE_ROOT,
    STARTING_HEAD,
    baseline_predictions,
    family_cluster_bootstrap,
    load_frozen_inputs,
    prediction_prevalence,
    prior_artifact_manifest,
    raw_score_separability,
)
from .track_h import CAPABILITIES, compute_core_metrics


def read_csv(name: str) -> list[dict[str, str]]:
    with (PACKAGE_ROOT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Stage4HR1DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = load_frozen_inputs()
        cls.baselines = baseline_predictions(cls.frozen.dataset)
        cls.diagnostic = json.loads(
            (PACKAGE_ROOT / "track_h_r1_diagnostic_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.prior_record = json.loads(
            (PACKAGE_ROOT / "PRIOR_TRACK_H_SHA256_V1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_01_all_prior_artifact_hashes_unchanged(self) -> None:
        observed = prior_artifact_manifest()
        self.assertEqual(observed["starting_head"], STARTING_HEAD)
        self.assertEqual(observed["file_count"], 25)
        self.assertEqual(
            observed["canonical_identity_sha256"],
            EXPECTED_PRIOR_MANIFEST_SHA256,
        )
        self.assertEqual(observed["files"], self.prior_record["files"])
        self.assertEqual(self.prior_record["verification"]["files_changed"], 0)
        self.assertEqual(self.prior_record["verification"]["bytes_changed"], 0)

    def test_02_frozen_model_threshold_prediction_and_metric_hashes(self) -> None:
        expected = {
            "b2_frozen_model_v1.json": (
                "fec02db702dd9ce0a86934c4fe626b27944657b92241ce8e35d4cf06c3fbda17"
            ),
            "b3_frozen_model_v1.json": (
                "256315f594687763513d7586f18b76e94e073ec87e3babec842eab9e3430eb32"
            ),
            "b2_nested_oof_predictions_v1.csv": (
                "1e82d8f5f30528b5334cd89ff9427c6a157a6b0ab42bc779d358ac4a5351ca76"
            ),
            "b3_nested_oof_predictions_v1.csv": (
                "ccd013ee6157858f1508f4fac823fc4a339f530cc27bce3908600ce49a7df00f"
            ),
            "track_h_metrics_v1.json": (
                "090bc568f6243b25e9b60fa1c5007cb93a5e0c836e2285de106d53c59fbe4992"
            ),
        }
        for name, digest in expected.items():
            self.assertEqual(sha256_file(PACKAGE_ROOT / name), digest)

    def test_03_always_on_and_never_on_definitions(self) -> None:
        always = BASELINE_DEFINITIONS["R2V2-D0_ALWAYS_ON"]
        never = BASELINE_DEFINITIONS["R2V2-D1_NEVER_ON"]
        self.assertEqual(
            [always["rag_required"], always["memory_required"], always["planning_required"]],
            ["YES", "YES", "YES"],
        )
        self.assertEqual(
            [never["rag_required"], never["memory_required"], never["planning_required"]],
            ["NO", "NO", "NO"],
        )
        self.assertFalse(always["learned_model"])
        self.assertFalse(never["learned_model"])
        self.assertIsNone(always["thresholds"])
        self.assertIsNone(never["thresholds"])
        np.testing.assert_array_equal(
            self.baselines["R2V2-D0_ALWAYS_ON"], np.ones((64, 3), dtype=np.int8)
        )
        np.testing.assert_array_equal(
            self.baselines["R2V2-D1_NEVER_ON"], np.zeros((64, 3), dtype=np.int8)
        )

    def test_04_hand_computable_sanity_baseline_metrics(self) -> None:
        always = compute_core_metrics(
            self.frozen.dataset.y,
            self.baselines["R2V2-D0_ALWAYS_ON"],
            self.frozen.dataset.rows,
        )
        never = compute_core_metrics(
            self.frozen.dataset.y,
            self.baselines["R2V2-D1_NEVER_ON"],
            self.frozen.dataset.rows,
        )
        self.assertAlmostEqual(always["macro_f1"], 2.0 / 3.0)
        self.assertAlmostEqual(always["micro_f1"], 2.0 / 3.0)
        self.assertEqual(always["exact_capability_set_match"], 8 / 64)
        self.assertAlmostEqual(always["jaccard"], 0.5)
        self.assertEqual(always["hamming_loss"], 0.5)
        self.assertEqual(always["under_routing_rate"], 0.0)
        self.assertEqual(always["over_routing_rate"], 56 / 64)
        self.assertEqual(never["macro_f1"], 0.0)
        self.assertEqual(never["exact_capability_set_match"], 8 / 64)
        self.assertAlmostEqual(never["jaccard"], 8 / 64)
        self.assertEqual(never["under_routing_rate"], 56 / 64)
        self.assertEqual(never["over_routing_rate"], 0.0)

    def test_05_baseline_prediction_files_cover_64_answer_cases(self) -> None:
        expected_ids = set(self.frozen.dataset.case_ids)
        for name, expected_signature in (
            ("d0_always_on_predictions_v1.csv", "111"),
            ("d1_never_on_predictions_v1.csv", "000"),
        ):
            rows = read_csv(name)
            self.assertEqual(len(rows), 64)
            self.assertEqual({row["annotation_case_id"] for row in rows}, expected_ids)
            self.assertTrue(
                all(row["predicted_capability_signature"] == expected_signature for row in rows)
            )

    def test_06_confusion_counts_and_zero_true_negative_flags(self) -> None:
        b2 = prediction_prevalence(
            self.frozen.dataset.y, self.frozen.b2_predictions
        )
        b3 = prediction_prevalence(
            self.frozen.dataset.y, self.frozen.b3_predictions
        )
        expected = {
            "B2": {
                "RAG": (30, 32, 0, 2),
                "Memory": (30, 32, 0, 2),
                "Planning": (30, 20, 12, 2),
            },
            "B3": {
                "RAG": (26, 32, 0, 6),
                "Memory": (27, 32, 0, 5),
                "Planning": (30, 14, 18, 2),
            },
        }
        for label, audit in (("B2", b2), ("B3", b3)):
            for capability in CAPABILITIES:
                item = audit["per_capability"][capability]
                observed = (
                    item["true_positives"],
                    item["false_positives"],
                    item["true_negatives"],
                    item["false_negatives"],
                )
                self.assertEqual(observed, expected[label][capability])
                self.assertEqual(
                    item["zero_true_negatives"], capability in {"RAG", "Memory"}
                )

    def test_07_signature_distribution_and_capability_count(self) -> None:
        b2 = prediction_prevalence(
            self.frozen.dataset.y, self.frozen.b2_predictions
        )
        b3 = prediction_prevalence(
            self.frozen.dataset.y, self.frozen.b3_predictions
        )
        self.assertEqual(b2["prediction_000_count"], 0)
        self.assertEqual(b2["prediction_111_count"], 46)
        self.assertEqual(b2["mean_predicted_capability_count_per_case"], 2.71875)
        self.assertEqual(
            sum(b2["predicted_capability_signature_distribution"].values()), 64
        )
        self.assertEqual(
            sum(b3["predicted_capability_signature_distribution"].values()), 64
        )

    def test_08_hand_computable_roc_auc_and_average_precision(self) -> None:
        truth = np.asarray([0, 0, 1, 1], dtype=np.int8)
        score = np.asarray([0.1, 0.4, 0.35, 0.8], dtype=np.float64)
        result = raw_score_separability(
            np.tile(truth[:, None], (1, 3)),
            np.tile(score[:, None], (1, 3)),
        )
        for capability in CAPABILITIES:
            self.assertAlmostEqual(result[capability]["roc_auc"], 0.75)
            self.assertAlmostEqual(
                result[capability]["average_precision"], 5.0 / 6.0
            )

    def test_09_existing_raw_separability_is_reported_without_flipping(self) -> None:
        b2 = raw_score_separability(self.frozen.dataset.y, self.frozen.b2_scores)
        b3 = raw_score_separability(
            self.frozen.dataset.y, self.frozen.b3_probabilities
        )
        self.assertAlmostEqual(b2["RAG"]["roc_auc"], 0.40234375)
        self.assertAlmostEqual(b2["Memory"]["roc_auc"], 0.306640625)
        self.assertAlmostEqual(b3["RAG"]["roc_auc"], 0.38671875)
        self.assertAlmostEqual(b3["Memory"]["roc_auc"], 0.3349609375)
        for result in (b2, b3):
            self.assertTrue(result["RAG"]["roc_auc_below_0_5"])
            self.assertTrue(result["Memory"]["roc_auc_below_0_5"])
            self.assertFalse(result["Planning"]["roc_auc_below_0_5"])
            self.assertTrue(
                all(
                    not result[capability]["scores_flipped_or_labels_reversed"]
                    for capability in CAPABILITIES
                )
            )

    def test_10_family_cluster_bootstrap_is_deterministic(self) -> None:
        predictions = {
            **self.baselines,
            "R2V2-B2_PROTOTYPE": self.frozen.b2_predictions,
            "R2V2-B3_OVR": self.frozen.b3_predictions,
        }
        first = family_cluster_bootstrap(
            self.frozen.dataset, predictions, seed=BOOTSTRAP_SEED, replicates=200
        )
        second = family_cluster_bootstrap(
            self.frozen.dataset, predictions, seed=BOOTSTRAP_SEED, replicates=200
        )
        for model_id in predictions:
            for metric in first["samples"][model_id]:
                np.testing.assert_array_equal(
                    first["samples"][model_id][metric],
                    second["samples"][model_id][metric],
                )
        for difference_id in first["difference_samples"]:
            np.testing.assert_array_equal(
                first["difference_samples"][difference_id],
                second["difference_samples"][difference_id],
            )

    def test_11_frozen_bootstrap_configuration_and_replicate_count(self) -> None:
        bootstrap = self.diagnostic["family_cluster_bootstrap"]
        self.assertEqual(bootstrap["seed"], BOOTSTRAP_SEED)
        self.assertEqual(bootstrap["replicates"], BOOTSTRAP_REPLICATES)
        self.assertEqual(bootstrap["resampling_unit"], "scenario_family_id")
        self.assertTrue(bootstrap["paired_resampling_across_models"])
        rows = read_csv("family_cluster_bootstrap_replicates_v1.csv")
        self.assertEqual(len(rows), BOOTSTRAP_REPLICATES)
        self.assertEqual(rows[0]["replicate_id"], "1")
        self.assertEqual(rows[-1]["replicate_id"], str(BOOTSTRAP_REPLICATES))

    def test_12_difference_intervals_do_not_claim_establishment(self) -> None:
        differences = self.diagnostic["family_cluster_bootstrap"][
            "difference_intervals"
        ]
        self.assertEqual(len(differences), 3)
        for item in differences.values():
            self.assertFalse(item["difference_statistically_established"])
            self.assertLessEqual(item["percentile_2_5"], item["point_estimate"])
            self.assertGreaterEqual(item["percentile_97_5"], item["point_estimate"])

    def test_13_zero_heldout_identifiers_and_zero_provider_calls(self) -> None:
        audit = self.diagnostic["governance_audit"]
        self.assertEqual(audit["held_out_access_count"], 0)
        self.assertEqual(audit["held_out_identifier_count"], 0)
        self.assertEqual(audit["provider_call_count"], 0)
        self.assertTrue(
            all("TEST" not in case_id for case_id in self.frozen.dataset.case_ids)
        )
        for name in (
            "d0_always_on_predictions_v1.csv",
            "d1_never_on_predictions_v1.csv",
        ):
            self.assertTrue(
                all("TEST" not in row["annotation_case_id"] for row in read_csv(name))
            )

    def test_14_new_code_contains_no_training_or_threshold_selection_call(self) -> None:
        prohibited_calls = {
            "fit_prototypes",
            "fit_ovr",
            "encode_frozen_texts",
            "nested_b2",
            "nested_b3",
            "full_dev_b2",
            "full_dev_b3",
            "select_threshold",
            "thresholds_from_scores",
        }
        observed_calls: set[str] = set()
        for name in ("diagnostic_audit.py", "run_r1_diagnostic_audit.py"):
            tree = ast.parse((PACKAGE_ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        observed_calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        observed_calls.add(node.func.attr)
        self.assertFalse(observed_calls & prohibited_calls)
        audit = self.diagnostic["governance_audit"]
        self.assertFalse(audit["b2_b3_retrained"])
        self.assertFalse(audit["b2_b3_recalibrated"])
        self.assertFalse(audit["alternative_thresholds_selected"])
        self.assertEqual(audit["new_learned_model_count"], 0)

    def test_15_r1_output_manifest_hashes(self) -> None:
        manifest = json.loads(
            (PACKAGE_ROOT / "R1_OUTPUT_SHA256_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            manifest["prior_track_h_canonical_identity_sha256"],
            EXPECTED_PRIOR_MANIFEST_SHA256,
        )
        self.assertEqual(manifest["prior_files_modified"], 0)
        self.assertEqual(manifest["learned_models_added"], 0)
        for item in manifest["files"]:
            path = PACKAGE_ROOT / item["name"]
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_size, item["size_bytes"])
            self.assertEqual(sha256_file(path), item["sha256"])


if __name__ == "__main__":
    unittest.main()
