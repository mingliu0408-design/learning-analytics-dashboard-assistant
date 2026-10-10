"""Result-preserving unit and contract tests for RQ2-D4."""

from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path
import subprocess
import unittest

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    evaluate_capability_predictions,
)

from . import (
    CAPABILITIES,
    COMBINED_SOURCE_RELATIVE,
    COMBINED_SOURCE_SHA256,
    FEATURE_VIEW_RELATIVE,
    GROUPING_RELATIVE,
    GROUPING_SHA256,
    HERE,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    METHODS,
    PREDICTION_RELATIVES,
    ROOT,
    START_HEAD,
    jsonl_rows_from_bytes,
    sha256_file,
)
from .error_analysis import capability_set_error_summary
from .run_capability_predictions import validate_prediction_row
from .run_rq2d4_research_evaluation import FIGURE_NAMES, PYTHON_NAMES
from .validate_rq2d4_results import validate_results


class RQ2D4ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metrics = json.loads((HERE / "rq2d4_final_metrics_v1.json").read_text())
        cls.comparisons = json.loads((HERE / "rq2d4_final_comparisons_v1.json").read_text())
        cls.errors = json.loads((HERE / "rq2d4_final_error_summary_v1.json").read_text())
        cls.runtime = json.loads((HERE / "rq2d4_runtime_report_v1.json").read_text())

    def test_01_starting_head_is_execution_base(self) -> None:
        current = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, check=True, capture_output=True
        ).stdout.strip()
        self.assertTrue(
            current == START_HEAD
            or subprocess.run(
                ["git", "merge-base", "--is-ancestor", START_HEAD, current], cwd=ROOT
            ).returncode == 0
        )

    def test_02_frozen_input_hashes(self) -> None:
        self.assertEqual(sha256_file(ROOT / LABEL_GOLD_RELATIVE), LABEL_GOLD_SHA256)
        self.assertEqual(sha256_file(ROOT / COMBINED_SOURCE_RELATIVE), COMBINED_SOURCE_SHA256)
        self.assertEqual(sha256_file(ROOT / GROUPING_RELATIVE), GROUPING_SHA256)

    def test_03_gold_and_group_shape(self) -> None:
        labels = jsonl_rows_from_bytes((ROOT / LABEL_GOLD_RELATIVE).read_bytes())
        groups = jsonl_rows_from_bytes((ROOT / GROUPING_RELATIVE).read_bytes())
        self.assertEqual(len(labels), 48)
        self.assertEqual(len(groups), 48)
        counts: dict[str, int] = {}
        for row in groups:
            counts[row["contrast_group_id"]] = counts.get(row["contrast_group_id"], 0) + 1
        self.assertEqual(len(counts), 24)
        self.assertEqual(set(counts.values()), {2})

    def test_04_new_python_ast(self) -> None:
        for name in PYTHON_NAMES:
            ast.parse((HERE / name).read_text(encoding="utf-8"), filename=name)

    def test_05_feature_view_firewall(self) -> None:
        rows = jsonl_rows_from_bytes((ROOT / FEATURE_VIEW_RELATIVE).read_bytes())
        self.assertEqual(len(rows), 48)
        self.assertTrue(all(set(row) == {
            "review_case_id", "current_query", "current_page", "necessary_conversation_history"
        } for row in rows))
        self.assertFalse(any(set(row) & set(CAPABILITIES) for row in rows))
        self.assertTrue(
            all(
                isinstance(row["necessary_conversation_history"], list)
                and all(set(item) == {"role", "content"} for item in row["necessary_conversation_history"])
                for row in rows
            )
        )

    def test_06_prediction_module_has_no_restricted_path_binding(self) -> None:
        source = (HERE / "run_capability_predictions.py").read_text(encoding="utf-8")
        for token in ("LABEL_GOLD_RELATIVE", "GROUPING_RELATIVE", "COMBINED_SOURCE_RELATIVE"):
            self.assertNotIn(token, source)

    def test_07_development_parity(self) -> None:
        parity = self.runtime["development_parity"]
        self.assertEqual(parity["status"], "PASS")
        self.assertEqual(parity["prediction_mismatch_count"], 0)
        self.assertEqual(parity["context_mismatch_count"], 0)
        self.assertEqual(parity["capability_set_mismatch_count"], 0)

    def test_08_runtime_smoke(self) -> None:
        smoke = self.runtime["runtime_smoke"]
        self.assertEqual(smoke["status"], "PASS")
        self.assertEqual(smoke["candidate_embedding_shape"], [62, 768])
        self.assertEqual(smoke["network_attempts"], 0)
        self.assertEqual(smoke["provider_calls"], 0)

    def test_09_three_distinct_processes(self) -> None:
        phases = self.runtime["phases"]
        pids = {row["process_id"] for row in phases.values()}
        self.assertEqual(len(pids), 3)
        recovery = self.runtime["pre_prediction_recovery"]
        self.assertEqual(recovery["failed_attempt_count"], 1)
        self.assertEqual(recovery["prediction_files_created"], 0)
        self.assertEqual(recovery["label_gold_open_count"], 0)

    def test_10_prediction_counts_and_identity(self) -> None:
        case_sets = []
        for method in METHODS:
            rows = jsonl_rows_from_bytes((ROOT / PREDICTION_RELATIVES[method]).read_bytes())
            self.assertEqual(len(rows), 48)
            for row in rows:
                validate_prediction_row(row, method)
            case_sets.append({row["review_case_id"] for row in rows})
        self.assertEqual(case_sets[0], case_sets[1])
        self.assertEqual(case_sets[1], case_sets[2])

    def test_11_capability_exclusivity(self) -> None:
        for method in METHODS:
            rows = jsonl_rows_from_bytes((ROOT / PREDICTION_RELATIVES[method]).read_bytes())
            for row in rows:
                caps = row["predicted_capabilities"]
                self.assertTrue(caps)
                if "clarification" in caps or "safe_direct_response" in caps:
                    self.assertEqual(len(caps), 1)

    def test_12_complete_metric_schema(self) -> None:
        required = {
            "macro_f1_all_six", "exact_set_accuracy", "micro_precision", "micro_recall",
            "micro_f1", "required_capability_recall", "unnecessary_capability_rate",
            "mean_set_jaccard", "median_set_jaccard", "forbidden_capability_violation_rate",
            "context_resolution_accuracy", "context_resolution_positive_recall",
            "clarification_precision", "clarification_recall", "unnecessary_clarification_rate",
        }
        for method in METHODS:
            self.assertTrue(required <= set(self.metrics["methods"][method]))
            self.assertEqual(set(self.metrics["methods"][method]["per_capability"]), set(CAPABILITIES))

    def test_13_frozen_statistics(self) -> None:
        self.assertEqual(set(self.comparisons["comparisons"]), {"P1_VS_B1", "B1_VS_B0", "P1_VS_B0"})
        self.assertEqual(self.comparisons["fixed_resamples"], 50000)
        self.assertEqual(self.comparisons["fixed_bootstrap_seed"], 20260828)
        self.assertEqual(self.comparisons["fixed_draws"], 100000)
        self.assertEqual(self.comparisons["fixed_sign_flip_seed"], 20260829)

    def test_14_holm_scope(self) -> None:
        self.assertEqual(set(self.comparisons["secondary_holm"]), {"B1_VS_B0", "P1_VS_B0"})
        self.assertNotIn("P1_VS_B1", self.comparisons["secondary_holm"])

    def test_15_context_subsets(self) -> None:
        self.assertEqual(self.errors["context_subsets"]["CONTEXT_RESOLUTION_REQUIRED_YES"]["record_count"], 39)
        self.assertEqual(self.errors["context_subsets"]["CONTEXT_RESOLUTION_REQUIRED_NO"]["record_count"], 9)

    def test_16_clarification_summary(self) -> None:
        self.assertEqual(self.errors["clarification"]["gold_clarification_case_count"], 4)
        self.assertEqual(set(self.errors["clarification"]["methods"]), set(METHODS))

    def test_17_error_analysis_counts(self) -> None:
        for method in METHODS:
            values = self.errors["per_method_capability_set_errors"][method]
            total = sum(values[key] for key in (
                "exact_set_correct_count", "under_prediction_count", "over_prediction_count", "mixed_error_count"
            ))
            self.assertEqual(total, 48)

    def test_18_deterministic_metric_repetition(self) -> None:
        fixture = [
            {
                "gold_capabilities": ["dashboard_evidence"],
                "predicted_capabilities": ["dashboard_evidence"],
                "forbidden_capabilities": [],
                "gold_context_resolution_required": False,
                "predicted_context_resolution_required": False,
            },
            {
                "gold_capabilities": ["clarification"],
                "predicted_capabilities": ["safe_direct_response"],
                "forbidden_capabilities": [],
                "gold_context_resolution_required": True,
                "predicted_context_resolution_required": False,
            },
        ]
        self.assertEqual(evaluate_capability_predictions(fixture), evaluate_capability_predictions(fixture))
        self.assertEqual(capability_set_error_summary(fixture), capability_set_error_summary(fixture))

    def test_19_safe_per_capability_csv(self) -> None:
        rows = list(csv.DictReader(io.StringIO((HERE / "rq2d4_per_capability_metrics_v1.csv").read_text())))
        self.assertEqual(len(rows), 18)
        self.assertFalse(any("case" in key.lower() for key in rows[0]))

    def test_20_figures_exist(self) -> None:
        for name in FIGURE_NAMES:
            path = ROOT / "docs/thesis_mainline/rq2/figures" / name
            self.assertGreater(path.stat().st_size, 1000)

    def test_21_result_freeze(self) -> None:
        freeze = json.loads((HERE / "rq2d4_result_freeze_v1.json").read_text())
        self.assertEqual(freeze["status"], "FROZEN")
        self.assertFalse(freeze["post_result_tuning"])
        self.assertFalse(freeze["policy_change"])
        self.assertFalse(freeze["threshold_change"])
        self.assertFalse(freeze["gold_change"])
        self.assertFalse(freeze["statistical_seed_change"])

    def test_22_full_validator(self) -> None:
        self.assertEqual(validate_results()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
