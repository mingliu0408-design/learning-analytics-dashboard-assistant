"""Synthetic-only tests for the pre-TEST final-Router selection rule."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import socket
import unittest
from unittest import mock

from ..selection_rule import (
    COVERAGE_FIELDS,
    ELIGIBLE_METHOD_IDS,
    NUMERIC_SELECTION_FIELDS,
    SelectionRuleError,
    select_final_router,
)


SELECTION_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SELECTION_DIR.parents[2]
ELIGIBILITY_PATH = SELECTION_DIR / "final_router_selection_eligibility_v1.json"
RULE_PATH = SELECTION_DIR / "final_router_selection_rule_v1.json"


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"not a JSON object: {path}")
    return value


def _toy_row(method_id: str, *, complete: bool) -> dict[str, object]:
    row: dict[str, object] = {
        "method_id": method_id,
        "core_macro_f1_gold_answer_cases": "0.50",
        "exact_capability_set_match": "0.50",
        "jaccard": "0.50",
        "under_routing_rate": "0.50",
        "over_routing_rate": "0.50",
        "family_both_utterances_correct_rate": "0.50",
        "complete_gold_pattern_contrast_match_rate": "0.50",
        "counterfactual_provider_component_call_count": "50",
        "counterfactual_token_cost": "500",
    }
    row.update({field: complete for field in COVERAGE_FIELDS})
    return row


def _toy_table(*complete_ids: str) -> list[dict[str, object]]:
    complete = set(complete_ids)
    return [_toy_row(method_id, complete=method_id in complete) for method_id in ELIGIBLE_METHOD_IDS]


class FinalRouterSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.eligibility = _read_json(ELIGIBILITY_PATH)
        cls.rule = _read_json(RULE_PATH)

    def test_01_exactly_eight_eligible_complete_routers_and_source_bindings(self) -> None:
        self.assertEqual(self.eligibility["pre_test_eligible_complete_router_method_count"], 8)
        self.assertEqual(tuple(self.eligibility["eligible_method_ids_in_frozen_order"]), ELIGIBLE_METHOD_IDS)
        candidates = [row for row in self.eligibility["methods"] if row["complete_router_selection_candidate"]]
        self.assertEqual(len(candidates), 8)
        for source_key in ("source_method_registry", "source_scoring_contract"):
            source = self.eligibility[source_key]
            path = REPOSITORY_ROOT / source["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])
        eligibility_binding = self.rule["eligibility_registry"]
        self.assertEqual(hashlib.sha256(ELIGIBILITY_PATH.read_bytes()).hexdigest(), eligibility_binding["sha256"])
        source_registry = _read_json(REPOSITORY_ROOT / self.eligibility["source_method_registry"]["path"])
        source_rows = {row["method_id"]: row for row in source_registry["methods"]}
        for row in self.eligibility["methods"]:
            source = source_rows[row["method_id"]]
            self.assertEqual(row["source_development_status"], source["development_status"])
            self.assertEqual(row["source_method_tier"], source["method_tier"])

    def test_02_p4_diagnostics_components_and_control_are_ineligible(self) -> None:
        rows = {row["method_id"]: row for row in self.eligibility["methods"]}
        expected = {
            "R2V2-D0_ALWAYS_ON": "DIAGNOSTIC_BASELINE",
            "R2V2-D1_NEVER_ON": "DIAGNOSTIC_BASELINE",
            "R2V2-CG1_CLARIFICATION_RULE": "SHARED_UPSTREAM_CONTROL_METHOD",
            "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION": "POST_DEV_EXPLORATORY_ABLATION",
            "R2V2-RAG_SPECIALIST": "COMPONENT_PREDICTOR",
            "R2V2-MEMORY_SPECIALIST": "COMPONENT_PREDICTOR",
        }
        self.assertEqual(self.eligibility["ineligible_method_count"], 6)
        for method_id, reason in expected.items():
            self.assertEqual(rows[method_id]["pre_test_selection_eligibility"], "INELIGIBLE")
            self.assertEqual(rows[method_id]["ineligibility_reason_code"], reason)
        self.assertEqual(rows["R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"]["test_reporting_status"], "REPORTABLE_BUT_NOT_SELECTABLE")

    def test_03_frozen_lexicographic_order_is_exact(self) -> None:
        criteria = self.rule["selection_order"]
        expected_labels = [
            "higher core Macro-F1 on Gold ANSWER cases",
            "higher Exact Capability Set Match",
            "higher Jaccard",
            "lower under-routing rate",
            "lower over-routing rate",
            "higher family-both-utterances-correct rate",
            "higher complete Gold-pattern contrast match",
            "lower counterfactual provider-component call count",
            "lower counterfactual token cost",
            "lower method-tier number",
            "UTF-8 method ID",
        ]
        expected_fields = [
            "core_macro_f1_gold_answer_cases",
            "exact_capability_set_match",
            "jaccard",
            "under_routing_rate",
            "over_routing_rate",
            "family_both_utterances_correct_rate",
            "complete_gold_pattern_contrast_match_rate",
            "counterfactual_provider_component_call_count",
            "counterfactual_token_cost",
            "method_tier_number",
            "method_id_utf8",
        ]
        expected_directions = [
            "HIGHER_IS_BETTER",
            "HIGHER_IS_BETTER",
            "HIGHER_IS_BETTER",
            "LOWER_IS_BETTER",
            "LOWER_IS_BETTER",
            "HIGHER_IS_BETTER",
            "HIGHER_IS_BETTER",
            "LOWER_IS_BETTER",
            "LOWER_IS_BETTER",
            "LOWER_IS_BETTER",
            "ASCENDING_UTF8_BYTES",
        ]
        self.assertEqual([row["rank"] for row in criteria], list(range(1, 12)))
        self.assertEqual([row["criterion"] for row in criteria], expected_labels)
        self.assertEqual([row["field"] for row in criteria], expected_fields)
        self.assertEqual([row["direction"] for row in criteria], expected_directions)
        requirements = self.rule["coverage_gate"]["requirements"]
        self.assertEqual(tuple(row["field"] for row in requirements), COVERAGE_FIELDS)
        self.assertTrue(all(row["required_value"] is True for row in requirements))

    def test_04_incomplete_coverage_blocks_selection_without_imputation(self) -> None:
        rows = _toy_table("R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT")
        by_id = {row["method_id"]: row for row in rows}
        by_id["R2V2-B0_RULE"]["core_macro_f1_gold_answer_cases"] = "1.00"
        by_id["R2V2-B0_RULE"]["no_prediction_was_imputed"] = False
        by_id["R2V2-B1_LEGACY_INTENT"]["core_macro_f1_gold_answer_cases"] = "0.10"
        self.assertEqual(select_final_router(rows, self.eligibility, self.rule), "R2V2-B1_LEGACY_INTENT")
        for row in rows:
            for field in COVERAGE_FIELDS:
                row[field] = False
        with self.assertRaisesRegex(SelectionRuleError, "binding must remain WAITING"):
            select_final_router(rows, self.eligibility, self.rule)
        missing_disclosure = _toy_table("R2V2-B0_RULE")
        del missing_disclosure[0]["all_required_outputs_pass_frozen_schema"]
        with self.assertRaisesRegex(SelectionRuleError, "explicit boolean coverage disclosure"):
            select_final_router(missing_disclosure, self.eligibility, self.rule)

    def test_05_toy_selection_is_deterministic_across_row_order(self) -> None:
        rows = _toy_table(*ELIGIBLE_METHOD_IDS)
        forward = select_final_router(rows, self.eligibility, self.rule)
        reverse = select_final_router(list(reversed(rows)), self.eligibility, self.rule)
        self.assertEqual(forward, reverse)
        self.assertEqual(forward, "R2V2-B0_RULE")

    def test_06_each_numeric_criterion_has_the_frozen_direction(self) -> None:
        for index, (field, direction) in enumerate(NUMERIC_SELECTION_FIELDS):
            with self.subTest(field=field):
                rows = _toy_table("R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT")
                by_id = {row["method_id"]: row for row in rows}
                by_id["R2V2-B0_RULE"][field] = "0.50"
                by_id["R2V2-B1_LEGACY_INTENT"][field] = "0.60" if direction == "HIGHER_IS_BETTER" else "0.40"
                self.assertEqual(select_final_router(rows, self.eligibility, self.rule), "R2V2-B1_LEGACY_INTENT")
                precedence_rows = _toy_table("R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT")
                precedence = {row["method_id"]: row for row in precedence_rows}
                precedence["R2V2-B0_RULE"][field] = "0.60" if direction == "HIGHER_IS_BETTER" else "0.40"
                precedence["R2V2-B1_LEGACY_INTENT"][field] = "0.50"
                for later_field, later_direction in NUMERIC_SELECTION_FIELDS[index + 1:]:
                    precedence["R2V2-B0_RULE"][later_field] = "0" if later_direction == "HIGHER_IS_BETTER" else "1"
                    precedence["R2V2-B1_LEGACY_INTENT"][later_field] = "1" if later_direction == "HIGHER_IS_BETTER" else "0"
                self.assertEqual(select_final_router(precedence_rows, self.eligibility, self.rule), "R2V2-B0_RULE")

    def test_07_method_tier_then_utf8_method_id_resolve_full_ties(self) -> None:
        tier_rows = _toy_table("R2V2-B0_RULE", "R2V2-P2_RAG_SPECIALIST_COMPOSITION")
        self.assertEqual(select_final_router(tier_rows, self.eligibility, self.rule), "R2V2-B0_RULE")
        utf8_rows = _toy_table("R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT")
        self.assertEqual(select_final_router(utf8_rows, self.eligibility, self.rule), "R2V2-B0_RULE")

    def test_08_p4_cannot_be_returned_even_with_favourable_metrics(self) -> None:
        rows = _toy_table("R2V2-B0_RULE")
        p4 = _toy_row("R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", complete=True)
        for field, direction in NUMERIC_SELECTION_FIELDS:
            p4[field] = "999999" if direction == "HIGHER_IS_BETTER" else "0"
        rows.append(p4)
        self.assertEqual(select_final_router(rows, self.eligibility, self.rule), "R2V2-B0_RULE")

    def test_09_rq3_binding_is_initially_waiting_and_result_is_absent(self) -> None:
        binding = self.rule["binding"]
        self.assertEqual(binding["name"], "RQ2_FINAL_ROUTER_FOR_RQ3")
        self.assertEqual(binding["initial_value"], "WAITING_FOR_RQ2_FINAL_SCORING")
        self.assertEqual(binding["selected_method_id_write_count_required"], 1)
        self.assertFalse(binding["overwrite_permitted"])
        self.assertFalse((SELECTION_DIR / "RQ2_FINAL_ROUTER_FOR_RQ3.json").exists())

    def test_10_disclosure_and_status_preserve_pre_test_boundary(self) -> None:
        disclosure = (SELECTION_DIR / "FINAL_ROUTER_SELECTION_DISCLOSURE.md").read_text(encoding="utf-8")
        status = (SELECTION_DIR / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("selection-conditional", disclosure)
        self.assertIn("No RQ3 observation", disclosure)
        self.assertIn("WAITING_FOR_RQ2_FINAL_SCORING", status)
        self.assertIn("TEST predictions executed: 0", status)
        self.assertIn("Provider calls made: 0", status)

    def test_11_selector_has_no_sensitive_io_or_execution_capability(self) -> None:
        source = (SELECTION_DIR / "selection_rule.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertLessEqual(imported_roots, {"__future__", "decimal", "typing"})
        forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "run", "Popen", "urlopen", "create_connection", "system"}
        called = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        self.assertTrue(forbidden_calls.isdisjoint(called))
        rows = _toy_table("R2V2-B0_RULE")
        with mock.patch("builtins.open", side_effect=AssertionError("file I/O forbidden")), mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.assertEqual(select_final_router(copy.deepcopy(rows), self.eligibility, self.rule), "R2V2-B0_RULE")


if __name__ == "__main__":
    unittest.main()
