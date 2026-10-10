#!/usr/bin/env python3
"""Offline regression tests for RQ3-REAL-C4-J2D1."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import validate_j2d1_artifacts as validator


def load_json(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_csv(name: str):
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class J2D1OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = load_json("c4_real_applicability_provenance_audit_v1.json")
        cls.conditions = load_json("c4_real_558_condition_applicability_dependency_audit_v1.json")
        cls.error = load_json("c4_real_error_handling_applicability_audit_v1.json")
        cls.scenarios = load_csv("c4_real_62_scenario_applicability_audit_v1.csv")
        cls.packet = load_csv("applicability_researcher_review_packet.csv")

    def test_01_status_ready(self) -> None:
        self.assertEqual(self.audit["status"], "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW")

    def test_02_exact_starting_head(self) -> None:
        self.assertEqual(self.audit["starting_head"], validator.STARTING_HEAD)

    def test_03_exact_branch(self) -> None:
        self.assertEqual(self.audit["branch"], validator.EXPECTED_BRANCH)

    def test_04_four_integrations(self) -> None:
        self.assertEqual(len(self.audit["commit_integration"]["mappings"]), 4)

    def test_05_integration_order(self) -> None:
        self.assertEqual([row["order"] for row in self.audit["commit_integration"]["mappings"]], [1, 2, 3, 4])

    def test_06_integration_patch_identity(self) -> None:
        self.assertTrue(all(row["patch_byte_identical"] for row in self.audit["commit_integration"]["mappings"]))

    def test_07_integration_no_conflicts(self) -> None:
        self.assertEqual(self.audit["commit_integration"]["conflicts"], 0)

    def test_08_judge_trees_preserved(self) -> None:
        preservation = self.audit["judge_execution_preservation"]
        self.assertTrue(all(row["byte_identical"] for row in preservation["tree_identity_checks"]))

    def test_09_j2d0_counts(self) -> None:
        self.assertEqual(self.audit["judge_execution_preservation"]["j2d0_canonical"], {"shard_counts": {"A": 1, "B": 38, "C": 31}, "total": 70})

    def test_10_judge_b_counts(self) -> None:
        self.assertEqual(self.audit["judge_execution_preservation"]["judge_b_v2"]["valid_results"], 11)

    def test_11_judge_b_hashes(self) -> None:
        value = self.audit["judge_execution_preservation"]["judge_b_v2"]
        self.assertEqual(value["terminal_journal_sha256"], "c7cdcb0124aaa1a1f2137f2e17dac48c075cc1c888fbe92305bcf6f90642a268")
        self.assertEqual(value["parsed_result_set_sha256"], "b51928e34e693464cf3dc421404108fb2ea160f2b2bff723054c704f50c9865b")

    def test_12_judge_c_counts(self) -> None:
        value = self.audit["judge_execution_preservation"]["judge_c_v2"]
        self.assertEqual((value["valid_results"], value["physical_attempts"]), (8, 10))
        self.assertEqual(value["unattempted_original_logical_orders"], "41-49")

    def test_13_judge_c_hashes(self) -> None:
        value = self.audit["judge_execution_preservation"]["judge_c_v2"]
        self.assertEqual(value["attempt_journal_sha256"], "8d9877e5744b605282b367209bc8cc9fbb1f318fb863b0f4e77cb11a2268943b")
        self.assertEqual(value["terminal_journal_sha256"], "03560d2a8d5a9c2a39d15442eb6c2648376ffa125e375db1cd389fa7798a6de6")
        self.assertEqual(value["parsed_result_set_sha256"], "9f2615b5913e6fa32be3b942446440b60301c3191d3ba6db9b58224dc0e946ff")

    def test_14_provisional_count(self) -> None:
        self.assertEqual(self.audit["judge_execution_preservation"]["provisional_preserved_result_counts"]["total"], 89)

    def test_15_order40_query(self) -> None:
        self.assertEqual(self.audit["order_40_reproduction"]["student_query"], "How can I perform better in this aspect?")

    def test_16_order40_frozen_map(self) -> None:
        criteria = self.audit["order_40_reproduction"]["frozen_applicability_criteria"]
        self.assertFalse(criteria["ACTIONABILITY"])
        self.assertEqual(sum(criteria.values()), 7)

    def test_17_order40_provider_schema(self) -> None:
        self.assertTrue(all(row["provider_schema_valid"] for row in self.audit["order_40_reproduction"]["attempts"]))

    def test_18_order40_actionability_tokens(self) -> None:
        self.assertEqual([row["actionability_token"] for row in self.audit["order_40_reproduction"]["attempts"]], ["3", "3"])

    def test_19_order40_parser_error(self) -> None:
        self.assertTrue(all(row["parser_v3_error"].endswith("actionability must be NA") for row in self.audit["order_40_reproduction"]["attempts"]))

    def test_20_order40_attempt1_other_applicable_numeric(self) -> None:
        first = self.audit["order_40_reproduction"]["attempts"][0]
        self.assertTrue(first["currently_applicable_primary_fields_numeric"])
        self.assertEqual(first["currently_applicable_primary_field_count"], 7)

    def test_21_order40_no_canonical_result(self) -> None:
        self.assertFalse(self.audit["order_40_reproduction"]["canonical_result_created"])

    def test_22_i1_code_hash(self) -> None:
        identity = self.audit["implementation_audit"]
        self.assertEqual(validator.sha256_file(ROOT / identity["path"]), identity["full_file_sha256"])

    def test_23_p3_dependency_fragments(self) -> None:
        text = (ROOT / self.audit["implementation_audit"]["path"]).read_text(encoding="utf-8")
        for fragment in ('route["memory_required"]', 'route["planning_required"]', '"gold_planning_required": False'):
            self.assertIn(fragment, text)

    def test_24_frozen_artifact_hash(self) -> None:
        self.assertEqual(self.audit["source_manifest"]["applicability_maps"]["sha256"], "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084")

    def test_25_scenario_population(self) -> None:
        self.assertEqual(len(self.scenarios), 62)
        self.assertEqual({row["scenario_id"] for row in self.scenarios}, {f"U{i:03d}" for i in range(1, 63)})

    def test_26_planning_false_negatives(self) -> None:
        self.assertEqual(self.audit["scenario_audit_summary"]["planning_false_negatives"], ["U013", "U015", "U016", "U017", "U021", "U023", "U058"])

    def test_27_planning_false_positive(self) -> None:
        self.assertEqual(self.audit["scenario_audit_summary"]["planning_false_positives"], ["U029"])

    def test_28_planning_set_complete(self) -> None:
        summary = self.audit["scenario_audit_summary"]
        self.assertTrue(summary["planning_disagreement_set_complete"])
        self.assertEqual(summary["planning_reference_disagreement_count"], 8)

    def test_29_personalisation_provenance(self) -> None:
        summary = self.audit["scenario_audit_summary"]
        self.assertEqual(summary["long_term_memory_provenance_disagreement_count"], 24)
        self.assertEqual(summary["long_term_memory_current_true_reference_false_count"], 17)
        self.assertEqual(summary["long_term_memory_current_false_reference_true_count"], 7)
        self.assertEqual(summary["student_specific_data_provenance_disagreement_count"], 0)
        self.assertEqual(summary["personalisation_draft_change_count"], 0)

    def test_30_multi_page_provenance(self) -> None:
        summary = self.audit["scenario_audit_summary"]
        self.assertEqual(summary["current_multi_page_true_scenario_count"], 13)
        self.assertEqual(summary["multi_page_materiality_review_count"], 13)
        self.assertEqual(summary["material_page_candidate_list_match_count"], 62)

    def test_31_no_final_scenario_decisions(self) -> None:
        self.assertTrue(all(row["final_decision_status"] == "NOT_MADE_RESEARCHER_REVIEW_REQUIRED" for row in self.scenarios))

    def test_32_condition_population(self) -> None:
        self.assertEqual(len(self.conditions["records"]), 558)

    def test_33_condition_sources_response_blind(self) -> None:
        self.assertFalse(self.conditions["candidate_response_accessed"])
        self.assertFalse(self.conditions["judge_score_or_rationale_accessed"])
        self.assertFalse(self.conditions["human_score_or_rationale_accessed"])

    def test_34_no_corrected_maps(self) -> None:
        self.assertTrue(all(not row["corrected_map_written"] for row in self.conditions["records"]))
        self.assertFalse(self.audit["repair_boundaries"]["corrected_applicability_maps_written"])

    def test_35_error_population(self) -> None:
        self.assertEqual(len(self.error["records"]), 558)

    def test_36_error_no_false_positive(self) -> None:
        self.assertEqual(self.error["current_true_without_reason_count"], 0)

    def test_37_error_no_false_negative(self) -> None:
        self.assertEqual(self.error["current_false_with_reason_count"], 0)

    def test_38_error_reason_counts(self) -> None:
        self.assertEqual(self.error["reason_code_counts"], {"DASHBOARD_TYPED_EMPTY": 80, "MEMORY_NO_MATCH": 68, "PLANNER_INSUFFICIENT_EVIDENCE": 6, "RAG_METADATA_OR_LINK_ONLY_BOUNDARY": 44, "RAG_NO_RESULT": 36})

    def test_39_packet_population(self) -> None:
        self.assertEqual(len(self.packet), 62)

    def test_40_packet_opaque_ids(self) -> None:
        ids = [row["applicability_review_id"] for row in self.packet]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"APR-[A-F0-9]{24}", value) for value in ids))

    def test_41_packet_final_fields_blank(self) -> None:
        self.assertTrue(all(row[field] == "" for row in self.packet for field in validator.FINAL_FIELDS))

    def test_42_packet_prohibited_columns_absent(self) -> None:
        self.assertFalse(set(self.packet[0]) & validator.PROHIBITED_PACKET_COLUMNS)

    def test_43_packet_identity_leaks_absent(self) -> None:
        text = (HERE / "applicability_researcher_review_packet.csv").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bU\d{3}\b", text))
        self.assertNotIn("C4J1-", text)
        self.assertNotIn("R3B-", text)

    def test_44_restricted_mapping_ignored(self) -> None:
        self.assertTrue(validator.RESTRICTED_MAPPING.is_file())
        self.assertTrue(validator.git("check-ignore", str(validator.RESTRICTED_MAPPING.relative_to(ROOT))))

    def test_45_restricted_mapping_matches_packet(self) -> None:
        mapping = validator.load_csv(validator.RESTRICTED_MAPPING)
        self.assertEqual({row["applicability_review_id"] for row in mapping}, {row["applicability_review_id"] for row in self.packet})

    def test_46_hmac_key_preserved(self) -> None:
        self.assertEqual(validator.HMAC_KEY.stat().st_size, 32)
        self.assertEqual(validator.sha256_file(validator.HMAC_KEY), "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5")

    def test_47_impact_judge_counts(self) -> None:
        impact = self.audit["impact_assessment"]
        self.assertEqual((impact["potentially_changed_unique_judge_requests"], impact["potentially_changed_with_preserved_outputs"], impact["potentially_changed_currently_unattempted"]), (24, 9, 15))

    def test_48_impact_human_counts(self) -> None:
        impact = self.audit["impact_assessment"]
        self.assertEqual((impact["potentially_affected_human_items"], impact["potentially_affected_human_item_criterion_pairs"]), (6, 6))

    def test_49_impact_criterion_counts(self) -> None:
        impact = self.audit["impact_assessment"]
        self.assertEqual(impact["judge_request_criterion_amendment_counts"]["ACTIONABILITY"], 24)
        self.assertEqual(sum(impact["judge_request_criterion_amendment_counts"].values()), 24)
        self.assertEqual(impact["human_item_criterion_amendment_counts"]["ACTIONABILITY"], 6)

    def test_50_impact_did_not_read_scores(self) -> None:
        impact = self.audit["impact_assessment"]
        self.assertTrue(impact["identity_only_analysis"])
        self.assertFalse(impact["score_values_accessed"])
        self.assertFalse(impact["rationales_accessed"])

    def test_51_human_sources_metadata_only(self) -> None:
        readiness = self.audit["human_source_readiness"]
        self.assertEqual(len(readiness["sources"]), 4)
        self.assertTrue(all(not row["content_imported"] and not row["rating_or_attestation_content_inspected"] for row in readiness["sources"]))

    def test_52_no_human_amendment_packet(self) -> None:
        self.assertFalse(self.audit["human_source_readiness"]["amendment_packet_created"])
        self.assertFalse(self.audit["human_source_readiness"]["full_repeat_requested"])

    def test_53_attestation_is_blank(self) -> None:
        text = (HERE / "applicability_researcher_attestation.md").read_text(encoding="utf-8")
        self.assertIn("- [ ]", text)
        self.assertNotIn("- [x]", text.casefold())

    def test_54_policy_has_nine_rules(self) -> None:
        text = (HERE / "C4_REAL_APPLICABILITY_REPAIR_POLICY_DRAFT.md").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^\d+\. ", text, flags=re.MULTILINE)), 9)

    def test_55_no_judge_package_built(self) -> None:
        self.assertFalse(self.audit["repair_boundaries"]["judge_package_rebuilt"])

    def test_56_all_execution_counters_zero(self) -> None:
        self.assertTrue(all(value == 0 for value in self.audit["execution_counters"].values()))

    def test_57_validator_ledger_passes(self) -> None:
        rows = validator.run_checks()
        self.assertEqual(len(rows), 65)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_58_identity_impact_does_not_deserialise_scores(self) -> None:
        text = (HERE / "build_j2d1_artifacts.py").read_text(encoding="utf-8")
        self.assertIn("projected_jsonl_string_field", text)
        self.assertNotIn('load_jsonl(SOURCE_PATHS["existing_canonical_judge_results"])', text)
        self.assertNotIn('load_jsonl(SOURCE_PATHS["judge_b_terminals_v2"])', text)
        self.assertNotIn('load_jsonl(SOURCE_PATHS["judge_c_terminals_v2"])', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
