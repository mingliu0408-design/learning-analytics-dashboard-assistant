#!/usr/bin/env python3
"""Self-contained tests for the extracted J2D1 review package."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import sys
import unittest


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import validate_j2d1_review_artifacts as review_validator


def load_json(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_csv(name: str):
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ReviewArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = load_json("c4_real_applicability_provenance_audit_v1.json")
        cls.scenarios = load_csv("c4_real_62_scenario_applicability_audit_v1.csv")
        cls.conditions = load_json("c4_real_558_condition_applicability_dependency_audit_v1.json")
        cls.error = load_json("c4_real_error_handling_applicability_audit_v1.json")
        cls.packet = load_csv("applicability_researcher_review_packet.csv")

    def test_01_ready_status(self):
        self.assertEqual(self.audit["status"], "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW")

    def test_02_integration_mapping(self):
        self.assertEqual([row["order"] for row in self.audit["commit_integration"]["mappings"]], [1, 2, 3, 4])

    def test_03_judge_preservation(self):
        self.assertEqual(self.audit["judge_execution_preservation"]["status"], "PASS_ALL_ORIGINAL_JUDGE_ARTIFACTS_BYTE_IDENTICAL")

    def test_04_judge_counts(self):
        self.assertEqual(self.audit["judge_execution_preservation"]["provisional_preserved_result_counts"]["total"], 89)

    def test_05_order40_reproduced(self):
        self.assertEqual(len(self.audit["order_40_reproduction"]["attempts"]), 2)
        self.assertTrue(all(row["provider_schema_valid"] for row in self.audit["order_40_reproduction"]["attempts"]))

    def test_06_order40_exact_failure(self):
        self.assertTrue(all(row["actionability_token"] == "3" and row["parser_v3_error"].endswith("actionability must be NA") for row in self.audit["order_40_reproduction"]["attempts"]))

    def test_07_scenario_population(self):
        self.assertEqual(len(self.scenarios), 62)

    def test_08_planning_disagreements(self):
        self.assertEqual(self.audit["scenario_audit_summary"]["planning_reference_disagreement_count"], 8)

    def test_09_personalisation_findings(self):
        self.assertEqual(self.audit["scenario_audit_summary"]["personalisation_draft_change_count"], 0)
        self.assertEqual(self.audit["scenario_audit_summary"]["long_term_memory_provenance_disagreement_count"], 24)
        self.assertEqual(self.audit["scenario_audit_summary"]["long_term_memory_current_true_reference_false_count"], 17)
        self.assertEqual(self.audit["scenario_audit_summary"]["long_term_memory_current_false_reference_true_count"], 7)

    def test_10_multi_page_findings(self):
        self.assertEqual(self.audit["scenario_audit_summary"]["multi_page_materiality_review_count"], 13)
        self.assertEqual(self.audit["scenario_audit_summary"]["material_page_candidate_list_match_count"], 62)

    def test_11_condition_population(self):
        self.assertEqual(len(self.conditions["records"]), 558)

    def test_12_no_corrected_maps(self):
        self.assertTrue(all(not row["corrected_map_written"] for row in self.conditions["records"]))

    def test_13_error_audit(self):
        self.assertEqual(len(self.error["records"]), 558)
        self.assertEqual((self.error["current_true_without_reason_count"], self.error["current_false_with_reason_count"]), (0, 0))

    def test_14_packet_population(self):
        self.assertEqual(len(self.packet), 62)

    def test_15_packet_ids_opaque(self):
        ids = [row["applicability_review_id"] for row in self.packet]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"APR-[A-F0-9]{24}", value) for value in ids))

    def test_16_packet_fields_blank(self):
        self.assertTrue(all(row[field] == "" for row in self.packet for field in review_validator.FINAL_FIELDS))

    def test_17_packet_identity_blind(self):
        text = (HERE / "applicability_researcher_review_packet.csv").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bU\d{3}\b", text))
        self.assertNotIn("C4J1-", text)
        self.assertNotIn("R3B-", text)

    def test_18_impact_counts(self):
        impact = self.audit["impact_assessment"]
        self.assertEqual((impact["potentially_changed_unique_judge_requests"], impact["potentially_changed_with_preserved_outputs"], impact["potentially_changed_currently_unattempted"]), (24, 9, 15))
        self.assertEqual((impact["potentially_affected_human_items"], impact["potentially_affected_human_item_criterion_pairs"]), (6, 6))

    def test_19_zero_execution(self):
        self.assertTrue(all(value == 0 for value in self.audit["execution_counters"].values()))

    def test_20_review_validator(self):
        checks = review_validator.run_checks(exact_directory=False)
        self.assertEqual(len(checks), 42)
        self.assertTrue(all(row["status"] == "PASS" for row in checks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
