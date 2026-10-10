"""Deterministic fail-closed tests for RQ2-V2 Stage 4M."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from .. import build_review_zip
from .. import run_stage4m as stage4m


class Stage4MTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_verification = stage4m.verify_sources()
        cls.records, cls.join = stage4m.load_records()
        cls.predictions = stage4m.build_prediction_maps(cls.records)
        cls.metrics = stage4m.build_metrics(cls.records, cls.predictions)
        cls.cost_report, cls.cost_rows = stage4m.build_cost_report(cls.records)
        cls.track_dir = stage4m.TRACK_DIR

    def test_01_k0_k_l_commits_are_integrated_in_exact_order(self) -> None:
        binding = self.source_verification["git_integration"]
        self.assertEqual(
            [row["source_commit"] for row in binding["ordered_integrations"]],
            list(stage4m.SOURCE_COMMITS),
        )
        self.assertEqual(
            [row["integrated_commit"] for row in binding["ordered_integrations"]],
            list(stage4m.INTEGRATED_COMMITS),
        )

    def test_02_all_frozen_source_hashes_match(self) -> None:
        observed = {
            row["role"]: row["sha256"]
            for row in self.source_verification["artifacts"]
        }
        self.assertEqual(set(observed), set(stage4m.SOURCE_ARTIFACTS))
        self.assertEqual(
            observed,
            {role: values[1] for role, values in stage4m.SOURCE_ARTIFACTS.items()},
        )

    def test_03_all_required_sources_have_identical_64_case_joins(self) -> None:
        self.assertEqual(self.join["case_count"], 64)
        self.assertEqual(len(self.records), 64)
        self.assertEqual(len({row.annotation_case_id for row in self.records}), 64)
        self.assertEqual(
            set(self.join["outer_fold_counts"].values()),
            {16},
        )

    def test_04_exactly_one_specialist_value_exists_per_case(self) -> None:
        self.assertTrue(all(type(row.rag_specialist) is bool for row in self.records))
        self.assertTrue(
            all(type(row.memory_specialist) is bool for row in self.records)
        )

    def test_05_p2_composition_is_exact(self) -> None:
        for row in self.records:
            output = self.predictions["P2"][row.annotation_case_id]
            self.assertEqual(
                output.bits,
                (
                    row.rag_specialist,
                    row.base.b4.memory_required,
                    row.base.b4.planning_required,
                ),
            )

    def test_06_p3_composition_is_exact(self) -> None:
        for row in self.records:
            output = self.predictions["P3"][row.annotation_case_id]
            self.assertEqual(
                output.bits,
                (
                    row.rag_specialist,
                    row.memory_specialist,
                    row.base.b4.planning_required,
                ),
            )

    def test_07_p4_composition_is_exact(self) -> None:
        for row in self.records:
            output = self.predictions["P4"][row.annotation_case_id]
            self.assertEqual(
                output.bits,
                (
                    row.base.b4.rag_required,
                    row.memory_specialist,
                    row.base.b4.planning_required,
                ),
            )

    def test_08_no_additional_specialist_composition_exists(self) -> None:
        extension_ids = {
            stage4m.METHOD_SPECS[name]["method_id"] for name in ("P2", "P3", "P4")
        }
        self.assertEqual(extension_ids, {stage4m.P2_ID, stage4m.P3_ID, stage4m.P4_ID})
        self.assertEqual(set(self.predictions), set(stage4m.METHOD_ORDER))

    def test_09_planning_always_comes_from_frozen_b4(self) -> None:
        for method in ("P2", "P3", "P4"):
            for row in self.records:
                self.assertEqual(
                    self.predictions[method][row.annotation_case_id].planning_required,
                    row.base.b4.planning_required,
                )

    def test_10_missing_output_is_incomplete_without_substitution(self) -> None:
        b4 = self.records[0].base.b4
        self.assertIsNone(
            stage4m.compose_signature(
                "P2", b4=b4, rag_specialist=None, memory_specialist=True
            )
        )
        self.assertIsNone(
            stage4m.compose_signature(
                "P3", b4=b4, rag_specialist=True, memory_specialist=None
            )
        )
        self.assertIsNone(
            stage4m.compose_signature(
                "P4", b4=None, rag_specialist=True, memory_specialist=True
            )
        )

    def test_11_stage4j_metric_definitions_are_reproduced(self) -> None:
        base = [row.base for row in self.records]
        for method in stage4m.METHOD_ORDER:
            recomputed = stage4m.stage4j.core_metrics(base, self.predictions[method])
            for name in (
                "macro_f1",
                "micro_f1",
                "exact_capability_set_match",
                "example_based_f1",
                "jaccard",
                "hamming_loss",
            ):
                self.assertEqual(recomputed[name], self.metrics["methods"][method][name])

    def test_12_family_metrics_are_reproducible(self) -> None:
        base = [row.base for row in self.records]
        for method in stage4m.METHOD_ORDER:
            self.assertEqual(
                stage4m.stage4j.family_metrics(base, self.predictions[method]),
                self.metrics["methods"][method]["family_metrics"],
            )

    def test_13_contrast_metrics_cover_exactly_eight_groups_by_axis(self) -> None:
        for method in stage4m.METHOD_ORDER:
            contrast = self.metrics["methods"][method]["contrast_metrics"]
            self.assertEqual(contrast["eligible_contrast_groups"], 8)
            by_axis = self.metrics["methods"][method]["contrast_metrics_by_axis"]
            self.assertEqual(
                {
                    axis: value["eligible_contrast_groups"]
                    for axis, value in by_axis.items()
                },
                {"RAG": 2, "MEMORY": 3, "PLANNING": 3},
            )

    def test_14_actual_component_token_and_cost_arithmetic_matches(self) -> None:
        actual = self.cost_report["actual_historical_experimental_calls_already_made"]
        self.assertEqual(actual["successful_logical_calls_total"], 192)
        self.assertEqual(actual["input_tokens_total"], 247462)
        self.assertEqual(actual["output_tokens_total"], 1792)
        self.assertEqual(actual["total_tokens"], 249254)
        self.assertEqual(actual["approximate_cost_usd_total"], "0.03819450")

    def test_15_counterfactual_call_counts_are_exact(self) -> None:
        values = self.cost_report["counterfactual_deployment_component_calls"]
        self.assertEqual(values["B4"]["logical_component_calls"], 64)
        self.assertEqual(values["P2"]["logical_component_calls"], 128)
        self.assertEqual(values["P4"]["logical_component_calls"], 128)
        self.assertEqual(values["P3"]["logical_component_calls"], 192)
        self.assertEqual(self.cost_report["stage4m_new_provider_calls"], 0)

    def test_16_bootstrap_is_seeded_and_deterministic(self) -> None:
        first = stage4m.build_bootstrap(
            self.records, self.predictions, self.metrics, replicates=50
        )
        second = stage4m.build_bootstrap(
            self.records, self.predictions, self.metrics, replicates=50
        )
        self.assertEqual(first, second)
        self.assertEqual(first["seed"], 20260831)
        frozen = json.loads(
            (self.track_dir / "specialist_composition_bootstrap_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(frozen["replicates"], 10_000)

    def test_17_p4_disclosure_is_present_and_explicit(self) -> None:
        text = (self.track_dir / "P4_POST_DEV_EXTENSION_DISCLOSURE.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "added only after the RAG and Memory Specialist DEV component results",
            "complete the 2x2 factorial comparison",
            "requires no new model call or prompt",
            "must not be represented as a Stage 4K-0 predeclared primary method",
            "frozen before any TEST execution",
        ):
            self.assertIn(required, text)

    def test_18_implementation_has_no_provider_or_network_path(self) -> None:
        result = stage4m.verify_offline_implementation()
        self.assertEqual(result["status"], "PASS_OFFLINE_IMPLEMENTATION")
        self.assertFalse(result["provider_client_present"])
        self.assertFalse(result["network_path_present"])
        self.assertEqual(self.cost_report["stage4m_new_provider_calls"], 0)

    def test_19_no_test_identifier_occurs_in_case_ids(self) -> None:
        for name in (
            "specialist_composition_normalized_dev_v1.csv",
            "p2_core_oof_predictions_v1.csv",
            "p3_core_oof_predictions_v1.csv",
            "p4_core_oof_predictions_v1.csv",
            "b4_end_to_end_oof_predictions_v1.csv",
            "p1_end_to_end_oof_predictions_v1.csv",
            "p2_end_to_end_oof_predictions_v1.csv",
            "p3_end_to_end_oof_predictions_v1.csv",
            "p4_end_to_end_oof_predictions_v1.csv",
        ):
            rows = list(
                csv.DictReader(io.StringIO((self.track_dir / name).read_text(encoding="utf-8")))
            )
            self.assertFalse(
                any(
                    stage4m.TEST_IDENTIFIER_PATTERN.search(row["annotation_case_id"])
                    for row in rows
                ),
                name,
            )

    def test_20_source_predictions_and_gold_remain_immutable(self) -> None:
        for relative, expected in stage4m.SOURCE_ARTIFACTS.values():
            self.assertEqual(stage4m.sha256_file(stage4m.STAGE4_DIR / relative), expected)

    def test_21_p2_p3_p4_freeze_statuses_are_exact(self) -> None:
        cases = (
            (
                "p2_rag_specialist_composition_frozen_v1.json",
                "P2_STATUS",
                "FROZEN_AFTER_DEV_COMPOSITION_EVALUATION",
            ),
            (
                "p3_rag_memory_specialists_frozen_v1.json",
                "P3_STATUS",
                "FROZEN_AFTER_DEV_COMPOSITION_EVALUATION",
            ),
            (
                "p4_memory_specialist_composition_frozen_v1.json",
                "P4_STATUS",
                "FROZEN_POST_DEV_EXPLORATORY_ABLATION_BEFORE_TEST",
            ),
        )
        for name, key, expected in cases:
            value = json.loads((self.track_dir / name).read_text(encoding="utf-8"))
            self.assertEqual(value[key], expected)
            self.assertEqual(value["TEST_STATUS"], "NOT_EXECUTED")
            self.assertFalse(value["test_winner_designated"])

    def test_22_end_to_end_uses_the_unchanged_shared_gate(self) -> None:
        metrics = json.loads(
            (self.track_dir / "specialist_end_to_end_metrics_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            metrics["shared_clarification_gate_sha256"],
            stage4m.SOURCE_ARTIFACTS["clarification_gate"][1],
        )
        self.assertFalse(metrics["clarification_gate_modified"])
        for method in stage4m.METHOD_ORDER:
            value = metrics["methods"][method]
            self.assertEqual(value["population_count"], 72)
            self.assertEqual(value["dialogue_action"]["accuracy"], 1.0)
            self.assertEqual(value["predicted_clarify_count"], 8)
            self.assertEqual(value["core_composition_applied_count"], 64)

    def test_23_full_generated_output_rebuild_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = stage4m.build(output)
            self.assertEqual(summary["generated_file_count"], 28)
            expected_names = {
                *stage4m.GENERATED_OUTPUT_NAMES,
                "STAGE4M_OUTPUT_SHA256_MANIFEST.json",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected_names)
            for name in expected_names:
                self.assertEqual(
                    (output / name).read_bytes(),
                    (self.track_dir / name).read_bytes(),
                    name,
                )

    def test_24_review_zip_is_narrow_and_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.zip"
            second = Path(directory) / "second.zip"
            first_result = build_review_zip.build_review_zip(
                first, require_clean=False
            )
            second_result = build_review_zip.build_review_zip(
                second, require_clean=False
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result["sha256"], second_result["sha256"])
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
            self.assertFalse(any("/.git/" in name for name in names))
            self.assertFalse(any("__pycache__" in name for name in names))
            self.assertTrue(
                all(name.startswith(f"{build_review_zip.ARCHIVE_ROOT}/") for name in names)
            )


if __name__ == "__main__":
    unittest.main()
