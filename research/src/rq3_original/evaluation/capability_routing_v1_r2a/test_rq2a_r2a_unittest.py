"""RQ2-A-R2A contract, agreement, and adjudication-packet tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    validate_independent_reviewer_ids,
)

from . import (
    ADJUDICATION_PACKET_RELATIVE,
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    COMPLETED_B_SHA256,
    CORRECTED_A_SHA256,
    EXPECTED_ADJUDICATION_CASES,
    EXPECTED_CORRECTED_CASE_IDS,
    HERE,
    ORIGINAL_A_SHA256,
    R1C_MAPPING_RELATIVE,
    ROOT,
    RQ2A_R1C_HEAD,
    SOURCE_MAPPING_SHA256,
    reject_prohibited_track_path,
    sha256_file,
)
from .adjudication_packet_builder import BLANK_DECISION_FIELDS, FORBIDDEN_COLUMNS
from .adjudication_set_builder import build_adjudication_case_summary
from .agreement_runner import run_agreement
from .date_canonicalisation import ISO_DATE, OLD_DATE, canonicalise_date_bytes
from .independence_attestation import independence_attestation_document
from .limited_correction_validator import validate_limited_correction
from .packet_identity import read_mapping, read_packet, validate_packet_identities
from .validate_rq2a_r2a import (
    assert_all_python_ast,
    assert_change_scope,
    assert_double_build,
    assert_gitignore_contract,
    assert_no_provider_network_surface,
    assert_protected_sources_unchanged,
    assert_r1c_artifacts,
    assert_starting_lineage,
    governed_text_leak_scan,
    validate_output_checksums,
)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class RQ2AR2ATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths, cls.identity = validate_packet_identities(ROOT)
        cls.correction = validate_limited_correction(cls.paths, ROOT)
        cls.rows_a = _csv(ROOT / CANONICAL_A_RELATIVE)
        cls.rows_b = _csv(ROOT / CANONICAL_B_RELATIVE)
        cls.agreement = json.loads(
            (HERE / "human_agreement_results_v1.json").read_text(encoding="utf-8")
        )
        cls.summary = build_adjudication_case_summary(ROOT)
        cls.adjudication_rows = _csv(ROOT / ADJUDICATION_PACKET_RELATIVE)

    def test_01_starting_head(self) -> None:
        assert_starting_lineage()
        self.assertEqual(RQ2A_R1C_HEAD, "9b5b02c8729c73cd71f3a84240d1c4a052c2bb60")

    def test_02_r1c_review_zip_hash(self) -> None:
        assert_r1c_artifacts()

    def test_03_original_a_hash(self) -> None:
        self.assertEqual(sha256_file(self.paths.original_a), ORIGINAL_A_SHA256)

    def test_04_corrected_a_hash(self) -> None:
        self.assertEqual(sha256_file(self.paths.corrected_a), CORRECTED_A_SHA256)

    def test_05_completed_b_hash(self) -> None:
        self.assertEqual(sha256_file(self.paths.completed_b), COMPLETED_B_SHA256)

    def test_06_a_correction_exactly_seven_cells(self) -> None:
        self.assertEqual(self.correction["changed_cell_count"], 7)

    def test_07_a_changed_column_only_context_sufficient(self) -> None:
        self.assertEqual(self.correction["changed_column"], "context_sufficient")

    def test_08_a_exact_seven_ids(self) -> None:
        self.assertEqual(
            tuple(self.correction["changed_review_case_ids"]),
            EXPECTED_CORRECTED_CASE_IDS,
        )

    def test_09_reviewer_id_unchanged(self) -> None:
        self.assertTrue(self.correction["reviewer_id_unchanged"])

    def test_10_dates_unchanged_before_canonicalisation(self) -> None:
        self.assertEqual(self.paths.corrected_a.read_bytes().count(OLD_DATE), 60)
        self.assertEqual(self.paths.completed_b.read_bytes().count(OLD_DATE), 60)

    def test_11_a_canonical_hash(self) -> None:
        self.assertEqual(sha256_file(ROOT / CANONICAL_A_RELATIVE), CANONICAL_A_SHA256)

    def test_12_b_canonical_hash(self) -> None:
        self.assertEqual(sha256_file(ROOT / CANONICAL_B_RELATIVE), CANONICAL_B_SHA256)

    def test_13_canonical_date_only_diff(self) -> None:
        self.assertEqual(
            canonicalise_date_bytes(self.paths.corrected_a.read_bytes()),
            (ROOT / CANONICAL_A_RELATIVE).read_bytes(),
        )
        self.assertEqual((ROOT / CANONICAL_A_RELATIVE).read_bytes().count(ISO_DATE), 60)

    def test_14_two_different_reviewer_ids(self) -> None:
        self.assertEqual(
            validate_independent_reviewer_ids(self.rows_a, self.rows_b),
            ("REVIEWER_A", "REVIEWER_B"),
        )

    def test_15_independence_attestation(self) -> None:
        value = independence_attestation_document()
        self.assertTrue(value["reviewers_are_different_humans"])
        self.assertTrue(value["completed_independently"])
        self.assertFalse(value["used_ai_annotation_tools"])

    def test_16_canonical_schema_validation(self) -> None:
        self.assertEqual(len(self.rows_a), 60)
        self.assertEqual(len(self.rows_b), 60)
        validate_independent_reviewer_ids(self.rows_a, self.rows_b)

    def test_17_source_mapping_hash(self) -> None:
        self.assertEqual(sha256_file(ROOT / R1C_MAPPING_RELATIVE), SOURCE_MAPPING_SHA256)

    def test_18_source_split_25_35(self) -> None:
        rows = read_mapping(ROOT)
        counts = {source: sum(row["source_bank"] == source for row in rows) for source in ("authentic", "synthetic")}
        self.assertEqual(counts, {"authentic": 25, "synthetic": 35})

    def test_19_overall_agreement(self) -> None:
        overall = self.agreement["overall_60"]
        self.assertEqual(overall["record_count"], 60)
        self.assertEqual(overall["context_sufficient"]["percent_agreement"], 1.0)

    def test_20_source_stratified_agreement(self) -> None:
        self.assertEqual(self.agreement["by_source"]["authentic"]["record_count"], 25)
        self.assertEqual(self.agreement["by_source"]["synthetic"]["record_count"], 35)

    def test_21_capability_exact_set_one(self) -> None:
        self.assertEqual(
            self.agreement["overall_60"]["capability_set"]["exact_set_agreement"],
            1.0,
        )

    def test_22_naturalness_metrics(self) -> None:
        self.assertAlmostEqual(
            self.agreement["overall_60"]["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
            0.5302491103202847,
            places=12,
        )
        self.assertAlmostEqual(
            self.agreement["by_source"]["authentic"]["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
            0.576271186440678,
            places=12,
        )
        self.assertAlmostEqual(
            self.agreement["by_source"]["synthetic"]["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
            0.49397590361445787,
            places=12,
        )

    def test_23_context_resolution_agreement(self) -> None:
        self.assertAlmostEqual(
            self.agreement["overall_60"]["context_resolution_required"]["percent_agreement"],
            59 / 60,
            places=12,
        )

    def test_24_authentic_missing_context_counts(self) -> None:
        value = self.agreement["authentic_missing_context_by_reviewer"]
        self.assertEqual(value["reviewer_a"]["context_sufficient_no_count"], 3)
        self.assertEqual(value["reviewer_b"]["context_sufficient_no_count"], 3)

    def test_25_expected_five_adjudication_cases(self) -> None:
        self.assertEqual(self.summary["case_count"], 5)
        self.assertEqual(
            [row["review_case_id"] for row in self.summary["cases"]],
            [case_id for case_id, _ in EXPECTED_ADJUDICATION_CASES],
        )

    def test_26_exact_adjudication_reasons(self) -> None:
        self.assertEqual(
            [row["disagreement_reasons"] for row in self.summary["cases"]],
            [[reason] for _, reason in EXPECTED_ADJUDICATION_CASES],
        )

    def test_27_adjudication_final_fields_blank(self) -> None:
        self.assertTrue(
            all(not row[field] for row in self.adjudication_rows for field in BLANK_DECISION_FIELDS)
        )

    def test_28_no_hidden_proposal(self) -> None:
        self.assertFalse(set(self.adjudication_rows[0]) & FORBIDDEN_COLUMNS)

    def test_29_no_model_outputs(self) -> None:
        fields = set(self.adjudication_rows[0])
        self.assertFalse({"c0_score", "legacy_output", "intent_prediction"} & fields)

    def test_30_local_packets_ignored(self) -> None:
        assert_gitignore_contract()
        for relative in (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE, ADJUDICATION_PACKET_RELATIVE):
            result = __import__("subprocess").run(["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=ROOT)
            self.assertEqual(result.returncode, 0)

    def test_31_old_packets_unchanged(self) -> None:
        self.assertEqual(sha256_file(self.paths.original_a), ORIGINAL_A_SHA256)
        self.assertEqual(sha256_file(self.paths.corrected_a), CORRECTED_A_SHA256)
        self.assertEqual(sha256_file(self.paths.completed_b), COMPLETED_B_SHA256)

    def test_32_track_a_rejected(self) -> None:
        with self.assertRaises(ValueError):
            reject_prohibited_track_path("evaluation/track_a/final.csv")

    def test_33_track_b_rejected(self) -> None:
        with self.assertRaises(ValueError):
            reject_prohibited_track_path("evaluation/track_b/final.csv")

    def test_34_no_production_change(self) -> None:
        assert_change_scope()

    def test_35_no_provider_network(self) -> None:
        assert_no_provider_network_surface()
        assert_all_python_ast()

    def test_36_double_build_byte_identical(self) -> None:
        result = assert_double_build()
        self.assertEqual(result["case_summary"]["case_count"], 5)

    def test_37_output_checksums(self) -> None:
        validate_output_checksums()

    def test_38_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_39_protected_sources_unchanged(self) -> None:
        assert_protected_sources_unchanged()


if __name__ == "__main__":
    unittest.main()
