"""RQ2-A-R1 authority, baseline, review, and adjudication tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import unittest

from . import (
    HERE,
    NEW_REVIEW_A_RELATIVE,
    NEW_REVIEW_B_RELATIVE,
    OLD_REVIEW_PACKET_IDENTITIES,
    RAW_SYNTHETIC_SOURCE_RELATIVE,
    ROOT,
    RQ2A_HEAD,
    RQ2A_PARENT,
    require_exact_synthetic_source,
    sha256_file,
)
from .adjudication_contract import (
    AdjudicationContractError,
    adjudication_reasons,
    evaluate_coverage,
    validate_adjudication_record,
)
from .agreement_metrics import (
    binary_agreement,
    calculate_full_agreement,
    cohens_kappa,
    set_agreement,
)
from .baseline_identity_correction import (
    B0_MEASURED,
    CURRENT_MEASURED_BASELINE,
    FUTURE_UNMEASURED_B0,
    INTERPRETIVE_FIELDS,
    ORIGINAL_BASELINE_LABEL,
    ORIGINAL_PROJECTION_RELATIVE,
    build_corrected_projection,
)
from .build_reviewer_packets_v1_1 import build_reviewer_packets_v1_1
from .calibration_bank_authority import (
    EXPECTED_RAW_RECORD_COUNT,
    EXPECTED_RAW_SHA256,
    build_synthetic_authority,
)
from .human_review_schema import (
    HUMAN_FIELDS,
    HumanReviewSchemaError,
    human_review_schema_document,
    validate_annotation_row,
    validate_blank_packet,
    validate_independent_reviewer_ids,
    validate_naturalness,
)
from .validate_rq2a_r1 import (
    PYTHON_FILES,
    assert_all_python_ast,
    assert_change_scope,
    assert_double_build,
    assert_gitignore_unchanged,
    assert_new_packets,
    assert_no_provider_network_surface,
    assert_old_packets_unchanged,
    assert_original_rq2a_files_unchanged,
    assert_staged_content_safe,
    assert_starting_lineage,
    governed_text_leak_scan,
    validate_all,
    validate_output_checksums,
)


def _json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _rows(relative: Path) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _completed_row(
    case_id: str,
    reviewer_id: str,
    **overrides: str,
) -> dict[str, str]:
    row = {
        "case_id": case_id,
        "case_validity": "INCLUDE_VALID_CASE",
        "query_naturalness_1_to_5": "3",
        "context_sufficient": "YES",
        "capability_unambiguous": "YES",
        "context_resolution_required": "NO",
        "dashboard_evidence": "NO",
        "course_retrieval": "NO",
        "episodic_memory": "NO",
        "planning": "NO",
        "safe_direct_response": "YES",
        "clarification": "NO",
        "forbidden_capabilities": "",
        "reviewer_rationale": "TOKEN_RATIONALE",
        "reviewer_id": reviewer_id,
        "review_date": "2026-08-25",
    }
    row.update(overrides)
    return row


class RQ2AR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authority = _json("synthetic_calibration_bank_authority_v1.json")
        cls.corrected = _json("legacy_capability_projection_v1_1.json")
        cls.schema = _json("human_review_schema_v1_1.json")
        cls.agreement_contract = _json("human_agreement_contract_v1.json")
        cls.adjudication_contract = _json("human_adjudication_contract_v1.json")
        cls.packet_manifest = _json("reviewer_packet_manifest_v1_1.json")
        cls.rows_a = _rows(NEW_REVIEW_A_RELATIVE)
        cls.rows_b = _rows(NEW_REVIEW_B_RELATIVE)

    def test_01_rq2a_starting_head(self) -> None:
        parent = subprocess.run(
            ["git", "rev-parse", f"{RQ2A_HEAD}^"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode().strip()
        self.assertEqual(parent, RQ2A_PARENT)
        assert_starting_lineage(ROOT)

    def test_02_raw_synthetic_source_hash_frozen(self) -> None:
        self.assertEqual(self.authority["raw_source_sha256"], EXPECTED_RAW_SHA256)
        self.assertEqual(
            sha256_file(require_exact_synthetic_source(RAW_SYNTHETIC_SOURCE_RELATIVE)),
            EXPECTED_RAW_SHA256,
        )

    def test_03_raw_source_contains_36_synthetic_records(self) -> None:
        self.assertEqual(self.authority["raw_record_count"], EXPECTED_RAW_RECORD_COUNT)
        self.assertTrue(self.authority["synthetic"])
        self.assertEqual(self.authority["unique_case_id_count"], 36)

    def test_04_authentic_student_voice_is_false(self) -> None:
        self.assertFalse(self.authority["authentic_student_voice"])
        self.assertFalse(self.authority["external_student_data"])

    def test_05_final_evaluation_eligibility_is_false(self) -> None:
        self.assertFalse(self.authority["eligible_for_final_evaluation"])
        self.assertFalse(self.authority["eligible_for_student_language_generalisation_claim"])

    def test_06_old_b0_label_is_superseded(self) -> None:
        self.assertEqual(self.corrected["supersedes_baseline_label"], ORIGINAL_BASELINE_LABEL)
        self.assertNotEqual(self.corrected["baseline_identity"], ORIGINAL_BASELINE_LABEL)

    def test_07_current_measured_baseline_is_b1(self) -> None:
        self.assertEqual(self.corrected["baseline_identity"], CURRENT_MEASURED_BASELINE)
        self.assertTrue(self.corrected["context_resolution_enabled"])
        self.assertFalse(self.corrected["original_query_only"])

    def test_08_true_b0_is_marked_not_measured(self) -> None:
        self.assertFalse(B0_MEASURED)
        self.assertEqual(
            FUTURE_UNMEASURED_B0,
            "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
        )

    def test_09_original_aggregate_counts_are_unchanged(self) -> None:
        original = json.loads((ROOT / ORIGINAL_PROJECTION_RELATIVE).read_text())
        corrected = build_corrected_projection(ROOT)
        for key, value in original.items():
            if key != "baseline_identity":
                self.assertEqual(corrected[key], value, key)
        changed = {
            key
            for key in set(original) | set(corrected)
            if original.get(key) != corrected.get(key)
        }
        self.assertEqual(changed, INTERPRETIVE_FIELDS)

    def test_10_old_reviewer_packets_are_unchanged(self) -> None:
        assert_old_packets_unchanged(ROOT)
        self.assertTrue(self.packet_manifest["old_packets_unchanged"])
        self.assertEqual(
            self.packet_manifest["old_packet_identities"], OLD_REVIEW_PACKET_IDENTITIES
        )

    def test_11_new_packet_case_sets_are_identical(self) -> None:
        self.assertEqual(
            {row["case_id"] for row in self.rows_a},
            {row["case_id"] for row in self.rows_b},
        )

    def test_12_new_packet_orders_differ(self) -> None:
        self.assertNotEqual(
            [row["case_id"] for row in self.rows_a],
            [row["case_id"] for row in self.rows_b],
        )

    def test_13_all_new_human_fields_are_blank(self) -> None:
        validate_blank_packet(self.rows_a)
        validate_blank_packet(self.rows_b)
        self.assertTrue(
            all(not row[field] for row in [*self.rows_a, *self.rows_b] for field in HUMAN_FIELDS)
        )

    def test_14_accept_as_presented_is_removed(self) -> None:
        self.assertNotIn("review_decision", self.rows_a[0])
        self.assertNotIn("ACCEPT_AS_PRESENTED", self.schema["case_validity_values"])
        self.assertTrue(self.schema["accept_as_presented_removed"])

    def test_15_reviewer_ids_must_differ_at_closure(self) -> None:
        same_a = [_completed_row("UNIT-1", "HUMAN-ONE")]
        same_b = [_completed_row("UNIT-1", "HUMAN-ONE")]
        with self.assertRaises(HumanReviewSchemaError):
            validate_independent_reviewer_ids(same_a, same_b)
        different = [_completed_row("UNIT-1", "HUMAN-TWO")]
        self.assertEqual(
            validate_independent_reviewer_ids(same_a, different),
            ("HUMAN-ONE", "HUMAN-TWO"),
        )

    def test_16_naturalness_validation(self) -> None:
        self.assertEqual(validate_naturalness("1"), 1)
        self.assertEqual(validate_naturalness("5"), 5)
        for invalid in ("0", "6", "3.5", "TOKEN"):
            with self.assertRaises(HumanReviewSchemaError):
                validate_naturalness(invalid)

    def test_17_agreement_metrics_on_synthetic_fixtures(self) -> None:
        rows_a = [
            _completed_row("UNIT-1", "HUMAN-A"),
            _completed_row(
                "UNIT-2",
                "HUMAN-A",
                safe_direct_response="NO",
                planning="YES",
                query_naturalness_1_to_5="4",
            ),
        ]
        rows_b = [
            _completed_row("UNIT-1", "HUMAN-B"),
            _completed_row(
                "UNIT-2",
                "HUMAN-B",
                safe_direct_response="NO",
                planning="YES",
                query_naturalness_1_to_5="5",
            ),
        ]
        result = calculate_full_agreement(rows_a, rows_b)
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["capability_set"]["exact_set_agreement"], 1.0)
        self.assertIn("planning", result["capabilities"])

    def test_18_zero_prevalence_kappa_is_handled_safely(self) -> None:
        result = cohens_kappa([False, False], [False, False], categories=(False, True))
        self.assertIsNone(result["value"])
        self.assertEqual(result["status"], "UNDEFINED_ZERO_VARIANCE")
        self.assertIsNone(binary_agreement([], [])["cohens_kappa"]["value"])

    def test_19_exact_set_agreement(self) -> None:
        result = set_agreement([{"a"}, {"b"}], [{"a"}, {"c"}])
        self.assertEqual(result["exact_set_agreement"], 0.5)

    def test_20_jaccard_similarity(self) -> None:
        result = set_agreement([{"a", "b"}], [{"b", "c"}])
        self.assertAlmostEqual(result["mean_jaccard_similarity"], 1 / 3)
        self.assertAlmostEqual(result["median_jaccard_similarity"], 1 / 3)

    def test_21_adjudication_trigger_rules(self) -> None:
        left = _completed_row("UNIT-1", "HUMAN-A", query_naturalness_1_to_5="2")
        right = _completed_row(
            "UNIT-1",
            "HUMAN-B",
            query_naturalness_1_to_5="4",
            case_validity="UNCERTAIN",
            safe_direct_response="NO",
            clarification="YES",
        )
        reasons = adjudication_reasons(left, right)
        self.assertIn("CASE_VALIDITY_DISAGREEMENT", reasons)
        self.assertIn("NATURALNESS_DIFFERENCE_AT_LEAST_TWO", reasons)
        self.assertIn("ANY_CAPABILITY_DISAGREEMENT", reasons)
        self.assertIn("EITHER_REVIEWER_UNCERTAIN", reasons)

    def test_22_query_rewrite_is_forbidden_in_adjudication(self) -> None:
        record = {
            "case_id": "UNIT-1",
            "current_query": "TOKEN_REWRITE",
            "query_rewrite_performed": False,
            "disagreement_reasons": ["TOKEN_REASON"],
            "adjudicator_id": "HUMAN-ADJ",
            "adjudication_date": "2026-08-25",
        }
        with self.assertRaises(AdjudicationContractError):
            validate_adjudication_record(record, expected_case_id="UNIT-1")

    def test_23_coverage_gates(self) -> None:
        rows: list[dict[str, str]] = []
        executable_pairs = (
            ("dashboard_evidence", "course_retrieval"),
            ("dashboard_evidence", "planning"),
            ("course_retrieval", "episodic_memory"),
            ("episodic_memory", "planning"),
        )
        for index in range(16):
            active = executable_pairs[index % len(executable_pairs)]
            row = {capability: "NO" for capability in (
                "dashboard_evidence", "course_retrieval", "episodic_memory", "planning",
                "safe_direct_response", "clarification",
            )}
            row.update({capability: "YES" for capability in active})
            row["context_resolution_required"] = "YES" if index < 4 else "NO"
            rows.append(row)
        rows.extend(
            [{**{capability: "NO" for capability in (
                "dashboard_evidence", "course_retrieval", "episodic_memory", "planning",
                "safe_direct_response", "clarification",
            )}, "safe_direct_response": "YES", "context_resolution_required": "NO"} for _ in range(2)]
        )
        rows.extend(
            [{**{capability: "NO" for capability in (
                "dashboard_evidence", "course_retrieval", "episodic_memory", "planning",
                "safe_direct_response", "clarification",
            )}, "clarification": "YES", "context_resolution_required": "NO"} for _ in range(2)]
        )
        self.assertEqual(evaluate_coverage(rows)["status"], "PASS")
        self.assertEqual(
            evaluate_coverage([])["status"],
            "BLOCKED_RQ2_A_R2_CALIBRATION_COVERAGE",
        )

    def test_24_new_packets_are_ignored(self) -> None:
        assert_new_packets(ROOT)
        for relative in (NEW_REVIEW_A_RELATIVE, NEW_REVIEW_B_RELATIVE):
            result = subprocess.run(
                ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=ROOT
            )
            self.assertEqual(result.returncode, 0)

    def test_25_track_a_is_rejected_without_access(self) -> None:
        with self.assertRaises(ValueError):
            require_exact_synthetic_source("evaluation/final_gold/track_a.csv")

    def test_26_track_b_is_rejected_without_access(self) -> None:
        with self.assertRaises(ValueError):
            require_exact_synthetic_source("evaluation/contextual_heldout/track_b.csv")

    def test_27_no_provider_or_network_surface(self) -> None:
        assert_no_provider_network_surface()
        preflight = _json("rq2a_r1_preflight_report_v1.json")
        self.assertEqual(preflight["provider_calls"], 0)
        self.assertFalse(preflight["network_access"])

    def test_28_production_and_original_sources_unchanged(self) -> None:
        assert_original_rq2a_files_unchanged(ROOT)
        assert_gitignore_unchanged(ROOT)

    def test_29_double_build_is_byte_identical(self) -> None:
        assert_double_build(ROOT)

    def test_30_output_checksums_pass(self) -> None:
        validate_output_checksums(ROOT)

    def test_31_all_new_python_ast(self) -> None:
        assert_all_python_ast()
        self.assertEqual(len(PYTHON_FILES), 9)

    def test_32_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan(ROOT)["leak_count"], 0)

    def test_33_staged_content_and_scope(self) -> None:
        assert_change_scope(ROOT)
        assert_staged_content_safe(ROOT)

    def test_34_full_validator(self) -> None:
        validate_all(ROOT)

    def test_35_valid_case_capability_contract(self) -> None:
        validate_annotation_row(_completed_row("UNIT-1", "HUMAN-A"))
        invalid = _completed_row(
            "UNIT-1", "HUMAN-A", planning="YES", safe_direct_response="YES"
        )
        with self.assertRaises(HumanReviewSchemaError):
            validate_annotation_row(invalid)


if __name__ == "__main__":
    unittest.main()
