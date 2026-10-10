"""Contract tests for RQ2-A-R1B authentic calibration integration."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

from . import (
    AUTHENTIC_PAGE_DISTRIBUTION,
    AUTHENTIC_SOURCE_SHA256,
    AUTHORITY_ZIP_SHA256,
    HIGH_CONFIDENCE_CONTEXT_CASE_IDS,
    HERE,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    LOCAL_REVIEW_ID_MAPPING_RELATIVE,
    LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE,
    OLD_PACKET_IDENTITIES,
    ROOT,
    RQ2A_R1_HEAD,
    SYNTHETIC_CANONICAL_BANK_SHA256,
    TARGET_BRANCH,
    sha256_file,
)
from .adjudication_contract_v1_2 import adjudication_reasons
from .agreement_contract_v1_2 import (
    calculate_source_stratified_agreement,
    human_agreement_contract_document,
)
from .authentic_case_builder import build_authentic_cases
from .authentic_overlap_audit import (
    EXPECTED_OVERLAPS,
    build_overlap_audit,
    reject_prohibited_track_path,
)
from .authentic_source_authority import (
    build_authentic_source_authority,
    load_authentic_rows,
    validate_authority_package,
)
from .human_review_schema_v1_2 import (
    CONTEXT_LINK_VALUES,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    human_review_schema_document,
    validate_blank_packet,
)
from .validate_rq2a_r1b import (
    PYTHON_FILES,
    assert_all_python_ast,
    assert_change_scope,
    assert_double_build,
    assert_gitignore_contract,
    assert_no_provider_network_surface,
    assert_old_packets_unchanged,
    assert_starting_lineage,
    build_all,
    governed_text_leak_scan,
    output_checksum_targets,
    validate_output_checksums,
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _packet(relative: Path) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class RQ2AR1BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build_all()
        cls.source_rows, cls.source_identity = load_authentic_rows(ROOT)
        cls.authentic_cases = build_authentic_cases(ROOT)
        cls.overlap = build_overlap_audit(ROOT)
        cls.rows_a = _packet(LOCAL_REVIEW_A_RELATIVE)
        cls.rows_b = _packet(LOCAL_REVIEW_B_RELATIVE)

    def test_01_starting_head(self) -> None:
        assert_starting_lineage()
        self.assertEqual(
            __import__("subprocess").run(
                ["git", "branch", "--show-current"],
                cwd=ROOT,
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip(),
            TARGET_BRANCH,
        )
        self.assertTrue(RQ2A_R1_HEAD)

    def test_02_authority_zip_hash(self) -> None:
        value = validate_authority_package()
        self.assertEqual(value["zip_sha256"], AUTHORITY_ZIP_SHA256)
        self.assertEqual(value["zip_member_count"], 3)

    def test_03_raw_csv_hash(self) -> None:
        self.assertEqual(self.source_identity["sha256"], AUTHENTIC_SOURCE_SHA256)

    def test_04_fifty_total_records(self) -> None:
        self.assertEqual(len(self.source_rows), 50)

    def test_05_twenty_five_user_turns(self) -> None:
        self.assertEqual(sum(row["role"] == "user" for row in self.source_rows), 25)

    def test_06_twenty_five_assistant_turns(self) -> None:
        self.assertEqual(sum(row["role"] == "assistant" for row in self.source_rows), 25)

    def test_07_five_page_distribution(self) -> None:
        self.assertEqual(self.source_identity["user_page_distribution"], AUTHENTIC_PAGE_DISTRIBUTION)
        self.assertEqual(len(AUTHENTIC_PAGE_DISTRIBUTION), 5)

    def test_08_assistant_turns_never_become_current_query(self) -> None:
        self.assertTrue(all(row["source_role"] == "user" for row in self.authentic_cases))
        self.assertTrue(all(row["assistant_generated"] is False for row in self.authentic_cases))

    def test_09_authentic_ids_are_unique(self) -> None:
        ids = [row["case_id"] for row in self.authentic_cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "AUTH-0001")
        self.assertEqual(ids[-1], "AUTH-0025")

    def test_10_five_context_link_candidates(self) -> None:
        ids = {
            row["case_id"]
            for row in self.authentic_cases
            if row["candidate_conversation_history"]
        }
        self.assertEqual(ids, set(HIGH_CONFIDENCE_CONTEXT_CASE_IDS))

    def test_11_no_automatic_session_inference(self) -> None:
        self.assertTrue(all(not row["session_inference_performed"] for row in self.authentic_cases))

    def test_12_exact_overlap_counts(self) -> None:
        observed = self.overlap["observed_overlap"]
        self.assertEqual(observed["candidate_62"]["exact"], 20)
        self.assertEqual(observed["unified_benchmark_62"]["exact"], 21)
        self.assertEqual(observed["legacy_scenarios_25"]["exact"], 21)
        self.assertEqual(observed["rq1_expanded_train_318"]["exact_query_hash"], 20)

    def test_13_normalised_overlap_counts(self) -> None:
        self.assertEqual(self.overlap["observed_overlap"], EXPECTED_OVERLAPS)

    def test_14_rq1_dev_overlap_zero(self) -> None:
        self.assertEqual(set(self.overlap["observed_overlap"]["rq1_dev_84"].values()), {0})

    def test_15_track_b_rejection(self) -> None:
        with self.assertRaises(PermissionError):
            reject_prohibited_track_path("evaluation/private/track_b/example.jsonl")

    def test_16_authentic_threshold_eligibility_false(self) -> None:
        authority = build_authentic_source_authority(ROOT)
        self.assertFalse(authority["research_role"]["eligible_for_threshold_selection"])

    def test_17_synthetic_role_renamed_stress_bank(self) -> None:
        value = json.loads((HERE / "synthetic_stress_bank_role_v1.json").read_text())
        self.assertEqual(value["current_alias"], "RQ2_SYNTHETIC_CAPABILITY_COVERAGE_STRESS_BANK_V1")
        self.assertFalse(value["authentic_student_voice"])

    def test_18_synthetic_membership_unchanged_35(self) -> None:
        path = ROOT / LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE
        self.assertEqual(len(_jsonl(path)), 35)
        self.assertEqual(sha256_file(path), SYNTHETIC_CANONICAL_BANK_SHA256)

    def test_19_combined_case_count_60(self) -> None:
        combined = _jsonl(ROOT / LOCAL_COMBINED_BANK_RELATIVE)
        self.assertEqual(len(combined), 60)

    def test_20_source_blinded_review_ids(self) -> None:
        mapping = _jsonl(ROOT / LOCAL_REVIEW_ID_MAPPING_RELATIVE)
        ids = [str(row["review_case_id"]) for row in mapping]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(value.startswith("RQ2CAL-") for value in ids))
        self.assertTrue(all("AUTH" not in value and "SYN" not in value for value in ids))

    def test_21_source_identity_hidden_from_packet(self) -> None:
        forbidden = {"source_dataset", "source_bank", "canonical_case_id", "overlap_status"}
        self.assertFalse(forbidden & set(self.rows_a[0]))
        self.assertEqual(tuple(self.rows_a[0]), (*VISIBLE_FIELDS, *HUMAN_FIELDS))

    def test_22_ab_same_case_set(self) -> None:
        self.assertEqual(
            {row["review_case_id"] for row in self.rows_a},
            {row["review_case_id"] for row in self.rows_b},
        )

    def test_23_ab_different_order(self) -> None:
        self.assertNotEqual(
            [row["review_case_id"] for row in self.rows_a],
            [row["review_case_id"] for row in self.rows_b],
        )

    def test_24_all_human_fields_blank(self) -> None:
        validate_blank_packet(self.rows_a)
        validate_blank_packet(self.rows_b)

    def test_25_context_link_valid_enum(self) -> None:
        self.assertEqual(CONTEXT_LINK_VALUES, ("YES", "NO", "NOT_APPLICABLE", "UNCERTAIN"))
        self.assertIn("context_link_valid", human_review_schema_document()["human_fields"])

    def test_26_agreement_metrics_separated_by_source(self) -> None:
        contract = human_agreement_contract_document()
        self.assertIn("authentic_25_metrics", contract)
        self.assertIn("synthetic_35_metrics", contract)
        self.assertIn("overall_60_metrics", contract)
        mapping = _jsonl(ROOT / LOCAL_REVIEW_ID_MAPPING_RELATIVE)

        def fixture(review_case_id: str, reviewer_id: str) -> dict[str, str]:
            row = {field: "" for field in (*VISIBLE_FIELDS, *HUMAN_FIELDS)}
            row.update(
                {
                    "review_case_id": review_case_id,
                    "current_query": "fixture-only",
                    "current_page": "Overview",
                    "necessary_conversation_history": "",
                    "turn_index": "0",
                    "capability_definition_reference": "fixture",
                    "case_validity": "INCLUDE_VALID_CASE",
                    "query_naturalness_1_to_5": "4",
                    "context_link_valid": "NOT_APPLICABLE",
                    "context_sufficient": "YES",
                    "capability_unambiguous": "YES",
                    "context_resolution_required": "NO",
                    "dashboard_evidence": "YES",
                    "course_retrieval": "NO",
                    "episodic_memory": "NO",
                    "planning": "NO",
                    "safe_direct_response": "NO",
                    "clarification": "NO",
                    "forbidden_capabilities": "",
                    "reviewer_rationale": "fixture",
                    "reviewer_id": reviewer_id,
                    "review_date": "2026-08-25",
                }
            )
            return row

        rows_a = [fixture(str(row["review_case_id"]), "Human-A") for row in mapping]
        rows_b = [fixture(str(row["review_case_id"]), "Human-B") for row in mapping]
        result = calculate_source_stratified_agreement(rows_a, rows_b, mapping)
        self.assertEqual(result["overall_60"]["record_count"], 60)
        self.assertEqual(result["by_source"]["authentic"]["record_count"], 25)
        self.assertEqual(result["by_source"]["synthetic"]["record_count"], 35)

    def test_27_adjudication_context_link_trigger(self) -> None:
        base = {
            "case_validity": "INCLUDE_VALID_CASE",
            "query_naturalness_1_to_5": "4",
            "context_link_valid": "YES",
            "context_sufficient": "YES",
            "capability_unambiguous": "YES",
            "context_resolution_required": "NO",
            "dashboard_evidence": "YES",
            "course_retrieval": "NO",
            "episodic_memory": "NO",
            "planning": "NO",
            "safe_direct_response": "NO",
            "clarification": "NO",
            "forbidden_capabilities": "",
        }
        other = {**base, "context_link_valid": "NO"}
        reasons = adjudication_reasons(base, other)
        self.assertIn("CONTEXT_LINK_VALID_DISAGREEMENT", reasons)
        self.assertIn("EITHER_REVIEWER_REJECTS_CONTEXT_LINK", reasons)

    def test_28_old_packets_unchanged(self) -> None:
        assert_old_packets_unchanged()
        self.assertEqual(len(OLD_PACKET_IDENTITIES), 4)

    def test_29_new_packets_ignored(self) -> None:
        for relative in (LOCAL_REVIEW_A_RELATIVE, LOCAL_REVIEW_B_RELATIVE):
            result = __import__("subprocess").run(
                ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=ROOT
            )
            self.assertEqual(result.returncode, 0)

    def test_30_tracked_outputs_contain_no_query(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_31_no_production_change(self) -> None:
        assert_change_scope()
        assert_gitignore_contract()

    def test_32_no_provider_or_network(self) -> None:
        assert_no_provider_network_surface()

    def test_33_double_build_byte_identical(self) -> None:
        result = assert_double_build()
        self.assertEqual(result["packets"]["combined_case_count"], 60)

    def test_34_output_checksums(self) -> None:
        validate_output_checksums()
        self.assertEqual(len(output_checksum_targets()), 26)

    def test_35_protected_sources_unchanged(self) -> None:
        assert_change_scope()
        assert_all_python_ast()
        self.assertEqual(len(PYTHON_FILES), 12)


if __name__ == "__main__":
    unittest.main()
