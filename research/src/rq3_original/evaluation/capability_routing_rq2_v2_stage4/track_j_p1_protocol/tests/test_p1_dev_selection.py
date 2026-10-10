from __future__ import annotations

import csv
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import re
import socket
import tempfile
import unittest
from unittest import mock

from .. import p1_protocol as p1
from .. import run_p1_dev_selection as runner


TRACK_DIR = Path(__file__).resolve().parents[1]


def read_csv(name: str) -> list[dict[str, str]]:
    with (TRACK_DIR / name).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class P1DevSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = runner.load_normalized_records()
        cls.nested = runner.run_nested_selection(cls.records)

    def test_01_stage4j0_hashes_unchanged(self) -> None:
        result = runner.verify_frozen_stage4j0()
        self.assertEqual("PASS", result["status"])
        self.assertEqual(5, len(result["files"]))
        self.assertEqual(
            runner.FROZEN_STAGE4J0_HASHES,
            {row["name"]: row["sha256"] for row in result["files"]},
        )

    def test_02_track_i_commits_integrated_in_exact_order(self) -> None:
        result = runner.verify_git_integration()
        self.assertEqual("PASS", result["status"])
        self.assertEqual(
            [runner.HISTORICAL_SOURCE_COMMIT, runner.SUCCESSFUL_SOURCE_COMMIT],
            [row["source_commit"] for row in result["ordered_integrations"]],
        )
        self.assertEqual(
            [runner.HISTORICAL_INTEGRATED_COMMIT, runner.SUCCESSFUL_INTEGRATED_COMMIT],
            [row["integrated_commit"] for row in result["ordered_integrations"]],
        )

    def test_03_valid_b4_artifact_binding(self) -> None:
        result = runner.verify_b4_binding()
        self.assertEqual("PASS", result["status"])
        self.assertEqual(64, result["valid_predictions"])
        self.assertEqual(0, result["invalid_structured_outputs"])
        self.assertEqual(0, result["provider_errors"])
        self.assertEqual(runner.EXPECTED_MODEL, result["model_snapshot"])
        self.assertEqual(runner.EXPECTED_B4_STATUS, result["execution_status"])
        hashes = {row["name"]: row["sha256"] for row in result["artifacts"]}
        self.assertEqual(
            {**runner.B4_REQUIRED_HASHES, **runner.B4_IMMUTABLE_CONTEXT_HASHES},
            hashes,
        )

    def test_04_identical_unique_64_case_join(self) -> None:
        self.assertEqual(64, len(self.records))
        self.assertEqual(64, len({record.annotation_case_id for record in self.records}))
        self.assertEqual(
            {fold: 16 for fold in p1.OUTER_FOLDS},
            dict(sorted(__import__("collections").Counter(r.outer_fold for r in self.records).items())),
        )

    def test_05_exactly_nine_eligible_and_one_diagnostic(self) -> None:
        frozen = json.loads(
            (TRACK_DIR / "p1_candidate_policies_frozen_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(9, len(p1.ELIGIBLE_POLICY_IDS))
        self.assertEqual(9, frozen["eligible_policy_count"])
        self.assertEqual(1, frozen["diagnostic_policy_count"])
        self.assertEqual(p1.DIAGNOSTIC_POLICY_ID, frozen["diagnostic_policies"][0]["policy_id"])
        self.assertFalse(frozen["diagnostic_policies"][0]["eligible"])

    def test_06_complete_signature_switch_never_label_mixes(self) -> None:
        for record in self.records:
            for policy_id in (*p1.ELIGIBLE_POLICY_IDS, p1.DIAGNOSTIC_POLICY_ID):
                decision = runner.analyse_policy(policy_id, record)
                expected = record.b4 if decision.fallback_triggered else record.b3
                self.assertEqual(expected, decision.output)
                self.assertIn(decision.output, {record.b3, record.b4})

    def test_07_frozen_triggers_match_independent_formulas(self) -> None:
        for record in self.records:
            margin = {
                width: any(
                    abs(Decimal(str(probability)) - Decimal(str(threshold))) <= width
                    for probability, threshold in zip(
                        record.b3_probabilities, record.b3_thresholds, strict=True
                    )
                )
                for width in (Decimal("0.05"), Decimal("0.10"), Decimal("0.20"))
            }
            expected = {
                "P1-C00-B3-DIRECT": False,
                "P1-C01-MARGIN-005": margin[Decimal("0.05")],
                "P1-C02-MARGIN-010": margin[Decimal("0.10")],
                "P1-C03-MARGIN-020": margin[Decimal("0.20")],
                "P1-C04-B2-B3-DISAGREEMENT": record.b2 != record.b3,
                "P1-C05-B0-B3-DISAGREEMENT": record.b0 != record.b3,
                "P1-C06-MARGIN010-OR-B2B3": margin[Decimal("0.10")] or record.b2 != record.b3,
                "P1-C07-MARGIN010-OR-B0B3": margin[Decimal("0.10")] or record.b0 != record.b3,
                "P1-C08-NONUNANIMOUS": not (record.b0 == record.b2 == record.b3),
                p1.DIAGNOSTIC_POLICY_ID: True,
            }
            for policy_id, value in expected.items():
                self.assertEqual(value, runner.analyse_policy(policy_id, record).fallback_triggered)

    def test_08_outer_validation_gold_and_b4_are_isolated(self) -> None:
        held_out = p1.OUTER_FOLDS[0]
        original = runner.run_nested_selection(self.records)["outer_results"][0]
        inverted = p1.CapabilitySignature(True, True, True)
        mutated = [
            replace(record, gold=inverted, b4=inverted)
            if record.outer_fold == held_out
            else record
            for record in self.records
        ]
        changed = runner.run_nested_selection(mutated)["outer_results"][0]
        self.assertEqual(original["selected_policy_id"], changed["selected_policy_id"])
        self.assertEqual(original["selected_training_metrics"], changed["selected_training_metrics"])
        self.assertFalse(original["outer_validation_gold_passed_to_selection"])
        self.assertFalse(original["outer_validation_b4_passed_to_selection"])

    def test_09_one_nested_prediction_per_case(self) -> None:
        decisions = self.nested["nested_decisions"]
        self.assertEqual(64, len(decisions))
        self.assertEqual(64, len({decision.record.annotation_case_id for decision in decisions}))
        self.assertEqual(
            {record.annotation_case_id for record in self.records},
            {decision.record.annotation_case_id for decision in decisions},
        )

    def test_10_frozen_tie_break_and_diagnostic_exclusion(self) -> None:
        equal = {
            policy_id: {
                "macro_f1": 0.5,
                "exact_capability_set_match": 0.5,
                "jaccard": 0.5,
                "under_routing_rate": 0.5,
                "over_routing_rate": 0.5,
                "fallback_rate": 0.5,
            }
            for policy_id in p1.ELIGIBLE_POLICY_IDS
        }
        self.assertEqual("P1-C00-B3-DIRECT", p1.select_policy(equal))
        with self.assertRaises(p1.ContractError):
            p1.select_policy({**equal, p1.DIAGNOSTIC_POLICY_ID: equal["P1-C00-B3-DIRECT"]})

    def test_11_final_policy_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as left_name, tempfile.TemporaryDirectory() as right_name:
            left = Path(left_name)
            right = Path(right_name)
            left_summary = runner.build(left)
            right_summary = runner.build(right)
            self.assertEqual(left_summary["final_policy_id"], right_summary["final_policy_id"])
            self.assertEqual(
                runner.GENERATED_OUTPUT_NAMES,
                tuple(path.name for path in sorted(left.iterdir(), key=lambda p: runner.GENERATED_OUTPUT_NAMES.index(p.name))),
            )
            for name in runner.GENERATED_OUTPUT_NAMES:
                self.assertEqual((left / name).read_bytes(), (right / name).read_bytes(), name)

    def test_12_token_and_cost_summation(self) -> None:
        cost = json.loads((TRACK_DIR / "p1_counterfactual_cost_v1.json").read_text(encoding="utf-8"))
        baseline = cost["all_b4_actual_historical_baseline"]
        self.assertEqual(sum(r.b4_input_tokens for r in self.records), baseline["actual_historical_input_tokens"])
        self.assertEqual(sum(r.b4_output_tokens for r in self.records), baseline["actual_historical_output_tokens"])
        self.assertEqual(
            baseline["actual_historical_input_tokens"] + baseline["actual_historical_output_tokens"],
            baseline["actual_historical_total_tokens"],
        )
        expected = sum((r.b4_cost_usd for r in self.records), Decimal("0"))
        self.assertEqual(expected, Decimal(baseline["actual_historical_approximate_cost_usd"]))

    def test_13_zero_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as output_name, mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network prohibited")
        ):
            result = runner.build(Path(output_name))
        self.assertEqual(0, result["stage4j_new_provider_calls"])
        source = (TRACK_DIR / "run_p1_dev_selection.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\b(?:OpenAI|Anthropic|requests\.(?:get|post))\b")

    def test_14_zero_test_identifiers_and_zero_rq3_access(self) -> None:
        prohibited = re.compile(r"(?:^|[-_])(?:TEST|TST)(?:$|[-_])", re.IGNORECASE)
        for name in (
            "p1_normalized_dev_records_v1.csv",
            "p1_policy_case_matrix_v1.csv",
            "p1_nested_oof_predictions_v1.csv",
            "p1_end_to_end_oof_predictions_v1.csv",
        ):
            for row in read_csv(name):
                self.assertIsNone(prohibited.search(row["annotation_case_id"]))
        manifest = json.loads((TRACK_DIR / "p1_output_manifest_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(0, manifest["test_identifier_count"])
        self.assertEqual(0, manifest["rq3_access_count"])

    def test_15_source_predictions_are_not_mutated(self) -> None:
        before = {row["name"]: row["sha256"] for row in runner.verify_source_hashes()}
        with tempfile.TemporaryDirectory() as output_name:
            runner.build(Path(output_name))
        after = {row["name"]: row["sha256"] for row in runner.verify_source_hashes()}
        self.assertEqual(before, after)
        self.assertEqual(runner.SOURCE_HASHES, after)

    def test_16_historical_failed_request_is_excluded(self) -> None:
        binding = runner.verify_b4_binding()["historical_failed_request"]
        self.assertEqual("PRE_MODEL_REQUEST_CONFIGURATION_FAILURE", binding["classification"])
        self.assertFalse(binding["counted_as_prediction"])
        self.assertFalse(binding["counted_in_metrics"])
        self.assertFalse(binding["counted_in_successful_cost"])

    def test_17_end_to_end_has_72_cases_and_clarify_is_not_applicable(self) -> None:
        rows = read_csv("p1_end_to_end_oof_predictions_v1.csv")
        self.assertEqual(72, len(rows))
        clarify = [row for row in rows if row["predicted_dialogue_action"] == "CLARIFY"]
        self.assertEqual(8, len(clarify))
        for row in clarify:
            self.assertEqual("false", row["core_p1_executed"])
            self.assertEqual("NOT_APPLICABLE", row["predicted_rag_required"])
            self.assertEqual("NOT_APPLICABLE", row["predicted_memory_required"])
            self.assertEqual("NOT_APPLICABLE", row["predicted_planning_required"])

    def test_18_required_output_counts(self) -> None:
        expected_rows = {
            "p1_normalized_dev_records_v1.csv": 64,
            "p1_policy_case_matrix_v1.csv": 640,
            "p1_outer_training_policy_metrics_v1.csv": 36,
            "p1_outer_fold_policy_selection_v1.csv": 4,
            "p1_nested_oof_predictions_v1.csv": 64,
            "p1_nested_oof_case_audit_v1.csv": 64,
            "p1_full_dev_policy_results_v1.csv": 9,
            "p1_model_comparison_v1.csv": 8,
            "p1_end_to_end_oof_predictions_v1.csv": 72,
        }
        for name, count in expected_rows.items():
            with self.subTest(name=name):
                self.assertEqual(count, len(read_csv(name)))


if __name__ == "__main__":
    unittest.main()
