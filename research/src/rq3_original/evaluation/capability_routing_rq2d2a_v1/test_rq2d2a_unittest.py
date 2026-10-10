"""RQ2-D2A exact-authority, agreement, isolation, and handoff tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from . import (
    ADJUDICATION_FIELDS,
    ADJUDICATION_PACKET_RELATIVE,
    AGREEMENT_FIELDS,
    BLANK_A_RELATIVE,
    BLANK_A_SHA256,
    BLANK_B_RELATIVE,
    BLANK_B_SHA256,
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    COMPLETED_A_NAME,
    COMPLETED_A_SHA256,
    COMPLETED_A_SIZE,
    COMPLETED_B_NAME,
    COMPLETED_B_SHA256,
    COMPLETED_B_SIZE,
    EXPECTED_DISAGREEMENT_IDS,
    EXPECTED_FIELD_DISAGREEMENTS,
    HERE,
    ORIGINAL_A_RELATIVE,
    ORIGINAL_B_RELATIVE,
    PACKET_FIELDS,
    ROOT,
    START_HEAD,
    TARGET_BRANCH,
    VISIBLE_FIELDS,
    csv_rows,
    downloads_path,
    sha256_file,
)
from .adjudication_packet_builder import (
    PACKET_FIELDS as ADJUDICATION_PACKET_FIELDS,
    SHUFFLE_SEED,
    adjudication_packet_bytes,
)
from .canonicalize_track_b_review_packets import BOM, ISO_DATE, OLD_DATE, canonicalise_bytes
from .disagreement_manifest import build_disagreement_manifest
from .finalise_rq2d2a import assert_double_finalisation
from .starting_state import validate_starting_state
from .track_b_agreement import calculate_agreement, validate_expected_agreement
from .validate_completed_packets import validate_completed_packets
from .validate_rq2d2a import (
    CHECKSUM_RELATIVE,
    assert_all_python_ast,
    assert_change_scope,
    assert_gitignore_contract,
    assert_local_boundaries,
    assert_no_provider_network_or_model_surface,
    assert_protected_sources_unchanged,
    assert_safe_json,
    expected_review_members,
    governed_text_leak_scan,
    validate_output_checksums,
    validate_review_zip,
)


class RQ2D2ATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.starting = validate_starting_state()
        cls.rows_a, cls.rows_b, cls.packet_validation = validate_completed_packets(ROOT)
        cls.by_a = {row["review_case_id"]: row for row in cls.rows_a}
        cls.by_b = {row["review_case_id"]: row for row in cls.rows_b}
        cls.agreement = json.loads(
            (HERE / "track_b_inter_reviewer_agreement_v1.json").read_text(encoding="utf-8")
        )
        cls.disagreement = build_disagreement_manifest(cls.rows_a, cls.rows_b)
        cls.adjudication_rows = csv_rows(ROOT / ADJUDICATION_PACKET_RELATIVE)

    def test_01_starting_head_and_branch(self) -> None:
        self.assertEqual(self.starting["approved_starting_head"], START_HEAD)
        self.assertEqual(self.starting["target_branch"], TARGET_BRANCH)

    def test_02_d1_review_zip_sha(self) -> None:
        self.assertEqual(
            self.starting["d1_review_zip_sha256"],
            "8be2d48a87a2ce0fc275935c2b413932993101a559cb097849647c34231bf602",
        )

    def test_03_d1_outputs_eight_of_eight(self) -> None:
        self.assertEqual(self.starting["d1_output_checksums"], "8/8 PASS")

    def test_04_global_lock_completed_and_unchanged(self) -> None:
        lock = self.starting["global_lock"]
        self.assertEqual(lock["state"], "COMPLETED")
        self.assertEqual((lock["raw_open_count"], lock["raw_read_count"]), (1, 1))
        self.assertFalse(lock["retry_permitted"])
        self.assertTrue(lock["global_access_consumed"])
        self.assertFalse(lock["modified"])

    def test_05_completed_a_original_identity(self) -> None:
        path = downloads_path(COMPLETED_A_NAME)
        self.assertEqual((sha256_file(path), path.stat().st_size), (COMPLETED_A_SHA256, COMPLETED_A_SIZE))

    def test_06_completed_b_original_identity(self) -> None:
        path = downloads_path(COMPLETED_B_NAME)
        self.assertEqual((sha256_file(path), path.stat().st_size), (COMPLETED_B_SHA256, COMPLETED_B_SIZE))

    def test_07_blank_a_identity(self) -> None:
        self.assertEqual(sha256_file(ROOT / BLANK_A_RELATIVE), BLANK_A_SHA256)

    def test_08_blank_b_identity(self) -> None:
        self.assertEqual(sha256_file(ROOT / BLANK_B_RELATIVE), BLANK_B_SHA256)

    def test_09_reviewer_a_identity(self) -> None:
        self.assertEqual({row["reviewer_id"] for row in self.rows_a}, {"A"})

    def test_10_reviewer_b_identity(self) -> None:
        self.assertEqual({row["reviewer_id"] for row in self.rows_b}, {"B"})

    def test_11_a_derived_from_b_template_order(self) -> None:
        blank = csv_rows(ROOT / BLANK_B_RELATIVE)
        self.assertTrue(all(all(a[field] == b[field] for field in VISIBLE_FIELDS) for a, b in zip(self.rows_a, blank)))

    def test_12_b_derived_from_a_template_order(self) -> None:
        blank = csv_rows(ROOT / BLANK_A_RELATIVE)
        self.assertTrue(all(all(a[field] == b[field] for field in VISIBLE_FIELDS) for a, b in zip(self.rows_b, blank)))

    def test_13_same_case_set_different_order(self) -> None:
        ids_a = [row["review_case_id"] for row in self.rows_a]
        ids_b = [row["review_case_id"] for row in self.rows_b]
        self.assertEqual(set(ids_a), set(ids_b))
        self.assertNotEqual(ids_a, ids_b)

    def test_14_visible_fields_unchanged_after_alignment(self) -> None:
        self.assertTrue(all(all(self.by_a[key][field] == self.by_b[key][field] for field in VISIBLE_FIELDS) for key in self.by_a))

    def test_15_original_local_copies_preserved(self) -> None:
        self.assertEqual((ROOT / ORIGINAL_A_RELATIVE).read_bytes(), downloads_path(COMPLETED_A_NAME).read_bytes())
        self.assertEqual((ROOT / ORIGINAL_B_RELATIVE).read_bytes(), downloads_path(COMPLETED_B_NAME).read_bytes())

    def test_16_no_input_bom_and_exact_old_dates(self) -> None:
        for relative in (ORIGINAL_A_RELATIVE, ORIGINAL_B_RELATIVE):
            value = (ROOT / relative).read_bytes()
            self.assertFalse(value.startswith(BOM))
            self.assertEqual(value.count(OLD_DATE), 48)

    def test_17_exact_48_date_replacements_each(self) -> None:
        for relative in (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE):
            value = (ROOT / relative).read_bytes()
            self.assertEqual(value.count(ISO_DATE), 48)
            self.assertEqual(value.count(OLD_DATE), 0)

    def test_18_bom_addition_only_and_reverse_identity(self) -> None:
        pairs = ((ORIGINAL_A_RELATIVE, CANONICAL_A_RELATIVE), (ORIGINAL_B_RELATIVE, CANONICAL_B_RELATIVE))
        for original, canonical in pairs:
            source = (ROOT / original).read_bytes()
            self.assertEqual(canonicalise_bytes(source), (ROOT / canonical).read_bytes())
            self.assertEqual((ROOT / canonical).read_bytes()[3:].replace(ISO_DATE, OLD_DATE), source)

    def test_19_canonical_hashes(self) -> None:
        self.assertEqual(sha256_file(ROOT / CANONICAL_A_RELATIVE), CANONICAL_A_SHA256)
        self.assertEqual(sha256_file(ROOT / CANONICAL_B_RELATIVE), CANONICAL_B_SHA256)

    def test_20_packet_shape_48_by_21(self) -> None:
        self.assertEqual((len(self.rows_a), len(self.rows_b)), (48, 48))
        self.assertEqual(tuple(self.rows_a[0]), PACKET_FIELDS)

    def test_21_required_human_fields_completed(self) -> None:
        self.assertTrue(self.packet_validation["all_required_human_fields_completed"])

    def test_22_rationales_nonempty(self) -> None:
        self.assertTrue(all(row["reviewer_rationale"].strip() for row in self.rows_a + self.rows_b))

    def test_23_capability_exclusivity(self) -> None:
        self.assertEqual(self.packet_validation["clarification_exclusivity_violation_count"], 0)
        self.assertEqual(self.packet_validation["safe_direct_exclusivity_violation_count"], 0)

    def test_24_forbidden_consistency(self) -> None:
        self.assertEqual(self.packet_validation["forbidden_required_overlap_count"], 0)

    def test_25_reviewer_and_date_uniformity(self) -> None:
        self.assertEqual({row["review_date"] for row in self.rows_a + self.rows_b}, {"2026-08-29"})

    def test_26_zero_variance_kappa_handling(self) -> None:
        for field in ("case_validity", "context_link_valid", "capability_unambiguous"):
            metric = self.agreement[field]["cohens_kappa"]
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["status"], "PERFECT_AGREEMENT_ZERO_VARIANCE")

    def test_27_naturalness_qwk(self) -> None:
        metric = self.agreement["query_naturalness_1_to_5"]
        self.assertEqual(metric["exact_agreement_count"], 32)
        self.assertAlmostEqual(metric["quadratic_weighted_kappa"]["value"], 0.4722222222222222, places=12)

    def test_28_context_agreement(self) -> None:
        self.assertEqual(self.agreement["context_sufficient"]["agreement_count"], 47)
        self.assertEqual(self.agreement["context_resolution_required"]["agreement_count"], 42)

    def test_29_per_capability_agreement(self) -> None:
        expected = {"dashboard_evidence": 47, "course_retrieval": 46, "episodic_memory": 47, "planning": 48, "safe_direct_response": 47, "clarification": 47}
        self.assertEqual({key: self.agreement["capabilities"][key]["agreement_count"] for key in expected}, expected)

    def test_30_capability_exact_set(self) -> None:
        self.assertEqual(self.agreement["capability_set"]["exact_set_agreement_count"], 45)
        self.assertEqual(self.agreement["capability_set"]["exact_set_agreement"], 0.9375)

    def test_31_capability_jaccard(self) -> None:
        self.assertAlmostEqual(self.agreement["capability_set"]["mean_jaccard_similarity"], 0.9479166666666666, places=12)
        self.assertEqual(self.agreement["capability_set"]["median_jaccard_similarity"], 1.0)

    def test_32_micro_agreement_and_kappa(self) -> None:
        metric = self.agreement["capability_set"]
        self.assertEqual(metric["all_capability_micro_agreement_count"], 282)
        self.assertAlmostEqual(metric["flattened_binary_cohens_kappa"]["value"], 0.9360521056916585, places=12)

    def test_33_forbidden_set_agreement(self) -> None:
        metric = self.agreement["forbidden_capability_set"]
        self.assertEqual(metric["exact_set_agreement_count"], 43)
        self.assertAlmostEqual(metric["mean_jaccard_similarity"], 0.9166666666666666, places=12)

    def test_34_expected_agreement_reproduction(self) -> None:
        validate_expected_agreement(calculate_agreement(self.rows_a, self.rows_b))

    def test_35_exact_23_disagreement_cases(self) -> None:
        self.assertEqual(self.disagreement["unique_disagreement_case_count"], 23)

    def test_36_exact_field_disagreement_counts(self) -> None:
        self.assertEqual(self.disagreement["field_level_disagreement_counts"], EXPECTED_FIELD_DISAGREEMENTS)

    def test_37_expected_opaque_id_set(self) -> None:
        self.assertEqual(tuple(case["review_case_id"] for case in self.disagreement["cases"]), EXPECTED_DISAGREEMENT_IDS)

    def test_38_nontrigger_fields_excluded(self) -> None:
        self.assertEqual(self.disagreement["excluded_non_trigger_fields"], ["reviewer_rationale", "reviewer_id", "review_date"])
        self.assertNotIn("reviewer_rationale", AGREEMENT_FIELDS)

    def test_39_adjudication_packet_23_rows(self) -> None:
        self.assertEqual(len(self.adjudication_rows), 23)
        self.assertEqual(tuple(self.adjudication_rows[0]), ADJUDICATION_PACKET_FIELDS)

    def test_40_deterministic_seed_and_order(self) -> None:
        manifest = json.loads((HERE / "track_b_adjudication_packet_manifest_v1.json").read_text())
        self.assertEqual(manifest["deterministic_shuffle_seed"], SHUFFLE_SEED)
        self.assertEqual((ROOT / ADJUDICATION_PACKET_RELATIVE).read_bytes(), adjudication_packet_bytes(self.rows_a, self.rows_b, self.disagreement))

    def test_41_reviewer_decisions_assigned_by_identity(self) -> None:
        for row in self.adjudication_rows:
            case_id = row["review_case_id"]
            for field in (*AGREEMENT_FIELDS, "reviewer_rationale"):
                self.assertEqual(row[f"reviewer_a_{field}"], self.by_a[case_id][field])
                self.assertEqual(row[f"reviewer_b_{field}"], self.by_b[case_id][field])

    def test_42_adjudication_fields_blank(self) -> None:
        self.assertTrue(all(not row[field] for row in self.adjudication_rows for field in ADJUDICATION_FIELDS))

    def test_43_immutable_booleans_lowercase_false(self) -> None:
        self.assertTrue(all(row["query_rewrite_performed"] == "false" and row["assistant_context_attached"] == "false" for row in self.adjudication_rows))

    def test_44_hidden_legacy_access_denied(self) -> None:
        self.assertEqual(self.starting["hidden_legacy_access_guard"], "DENIED")
        preflight = json.loads((HERE / "rq2d2a_preflight_report_v1.json").read_text())
        self.assertFalse(preflight["hidden_legacy_accessed"])

    def test_45_no_raw_track_b_or_model_execution(self) -> None:
        preflight = json.loads((HERE / "rq2d2a_preflight_report_v1.json").read_text())
        self.assertFalse(preflight["raw_track_b_accessed"])
        self.assertEqual(preflight["model_execution_count"], 0)

    def test_46_local_artifacts_ignored_and_untracked(self) -> None:
        assert_local_boundaries()

    def test_47_tracked_outputs_safe(self) -> None:
        assert_safe_json()
        governed_text_leak_scan()

    def test_48_all_python_ast_and_no_provider_surface(self) -> None:
        assert_all_python_ast()
        assert_no_provider_network_or_model_surface()

    def test_49_gitignore_and_change_scope(self) -> None:
        assert_gitignore_contract()
        assert_change_scope()

    def test_50_double_finalisation_byte_identical(self) -> None:
        assert_double_finalisation()

    def test_51_output_checksums(self) -> None:
        result = validate_output_checksums()
        self.assertGreater(result["referenced_tracked_output_count"], 0)

    def test_52_review_package_completeness_contract(self) -> None:
        self.assertEqual(len(expected_review_members()), len(set(expected_review_members())))
        review_path = downloads_path("RQ2_D2A_TRACK_B_REVIEW_AGREEMENT_REVIEW_2026-08-29.zip")
        if review_path.is_file():
            self.assertEqual(validate_review_zip()["referenced_output_member_count"], validate_output_checksums()["referenced_tracked_output_count"])

    def test_53_protected_sources_unchanged(self) -> None:
        assert_protected_sources_unchanged()

    def test_54_no_adjudication_or_gold(self) -> None:
        preflight = json.loads((HERE / "rq2d2a_preflight_report_v1.json").read_text())
        self.assertEqual(preflight["adjudication_decision_count"], 0)
        self.assertFalse(preflight["capability_gold_frozen"])


if __name__ == "__main__":
    unittest.main()
