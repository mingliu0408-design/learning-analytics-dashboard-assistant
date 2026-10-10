"""RQ2-D2B adjudication closure, Gold identity, and isolation tests."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest

from . import (
    ADJUDICATION_HUMAN_FIELDS,
    ADJUDICATION_PACKET_FIELDS,
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    CANONICAL_ADJUDICATION_SIZE,
    CAPABILITIES,
    COMPLETED_ADJUDICATION_SHA256,
    COMPLETED_ADJUDICATION_SIZE,
    D1_GLOBAL_LOCK_RELATIVE,
    D1_GLOBAL_LOCK_SHA256,
    D2A_BLANK_ADJUDICATION_RELATIVE,
    D2A_BLANK_ADJUDICATION_SHA256,
    D2A_CANONICAL_A_RELATIVE,
    D2A_CANONICAL_A_SHA256,
    D2A_CANONICAL_B_RELATIVE,
    D2A_CANONICAL_B_SHA256,
    FULL_GOLD_RELATIVE,
    FULL_GOLD_SHA256,
    FULL_GOLD_SIZE,
    GOLD_FIELDS,
    HERE,
    LABEL_GOLD_FIELDS,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    LABEL_GOLD_SIZE,
    ORIGINAL_ADJUDICATION_RELATIVE,
    REVIEW_ZIP_NAME,
    ROOT,
    START_HEAD,
    TARGET_BRANCH,
    VISIBLE_FIELDS,
    csv_rows,
    fallback_input_path,
    primary_input_path,
    sha256_bytes,
    sha256_file,
)
from .adjudication_canonicalisation import (
    BOM,
    CANONICAL_FALSE,
    ISO_DATE,
    OLD_DATE,
    OLD_FALSE,
    canonicalise_bytes,
)
from .adjudication_input_authority import resolve_and_preserve_input
from .finalise_rq2d2b import assert_double_finalisation
from .gold_bundle_manifest import build_gold_bundle_documents
from .gold_composition_validator import validate_gold_composition
from .human_adjudicator_attestation import human_adjudicator_attestation
from .human_decision_precedence import resolve_human_decisions
from .source_blinded_gold_builder import build_gold_bytes
from .starting_state import validate_starting_state
from .validate_completed_adjudication import (
    IMMUTABLE_PACKET_FIELDS,
    validate_completed_adjudication,
)
from .validate_rq2d2b import (
    CHECKSUM_RELATIVE,
    assert_all_python_ast,
    assert_change_scope,
    assert_gitignore_contract,
    assert_local_boundaries,
    assert_no_provider_network_or_model_surface,
    assert_protected_sources_unchanged,
    assert_safe_tracked_outputs,
    expected_review_members,
    governed_text_leak_scan,
    validate_output_checksums,
)


def _json(name: str) -> dict[str, object]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


class RQ2D2BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.starting = validate_starting_state()
        cls.input_paths, cls.input_authority = resolve_and_preserve_input(ROOT)
        cls.original = (ROOT / ORIGINAL_ADJUDICATION_RELATIVE).read_bytes()
        cls.canonical = (ROOT / CANONICAL_ADJUDICATION_RELATIVE).read_bytes()
        (
            cls.completed,
            cls.reviewer_a,
            cls.reviewer_b,
            cls.completed_validation,
        ) = validate_completed_adjudication(ROOT)
        cls.decisions, cls.precedence = resolve_human_decisions(
            cls.reviewer_a, cls.reviewer_b, cls.completed
        )
        (
            cls.label_bytes,
            cls.full_bytes,
            cls.label_rows,
            cls.full_rows,
        ) = build_gold_bytes(cls.decisions)
        cls.summary = validate_gold_composition(cls.label_rows)
        cls.manifest = _json("track_b_capability_gold_manifest_v1.json")
        cls.receipt = _json("track_b_capability_gold_freeze_receipt_v1.json")

    def test_01_starting_branch_and_head(self) -> None:
        self.assertEqual(self.starting["approved_starting_head"], START_HEAD)
        self.assertEqual(self.starting["target_branch"], TARGET_BRANCH)

    def test_02_d2a_review_zip_identity(self) -> None:
        self.assertEqual(
            self.starting["d2a_review_zip_sha256"],
            "e6ccc7624a0fe3ddac3312f92583325d68ac4fd6e43c7489722c2930a4165b82",
        )

    def test_03_d2a_outputs_25_of_25(self) -> None:
        self.assertEqual(self.starting["d2a_output_checksums"], "25/25 PASS")

    def test_04_d1_review_and_outputs(self) -> None:
        self.assertEqual(
            self.starting["d1_review_zip_sha256"],
            "8be2d48a87a2ce0fc275935c2b413932993101a559cb097849647c34231bf602",
        )
        self.assertEqual(self.starting["d1_output_checksums"], "8/8 PASS")

    def test_05_d1_global_lock_completed_unchanged(self) -> None:
        lock = self.starting["d1_global_lock"]
        self.assertEqual(sha256_file(ROOT / D1_GLOBAL_LOCK_RELATIVE), D1_GLOBAL_LOCK_SHA256)
        self.assertEqual(lock["state"], "COMPLETED")
        self.assertEqual((lock["raw_open_count"], lock["raw_read_count"]), (1, 1))
        self.assertFalse(lock["retry_permitted"])
        self.assertTrue(lock["global_access_consumed"])
        self.assertFalse(lock["modified"])

    def test_06_canonical_reviewer_a_identity(self) -> None:
        self.assertEqual(sha256_file(ROOT / D2A_CANONICAL_A_RELATIVE), D2A_CANONICAL_A_SHA256)

    def test_07_canonical_reviewer_b_identity(self) -> None:
        self.assertEqual(sha256_file(ROOT / D2A_CANONICAL_B_RELATIVE), D2A_CANONICAL_B_SHA256)

    def test_08_blank_adjudication_identity(self) -> None:
        self.assertEqual(sha256_file(ROOT / D2A_BLANK_ADJUDICATION_RELATIVE), D2A_BLANK_ADJUDICATION_SHA256)

    def test_09_authorised_input_path_resolution(self) -> None:
        self.assertEqual(self.input_paths.selected_input, primary_input_path())
        self.assertFalse(fallback_input_path().exists())
        self.assertEqual(self.input_authority["existing_candidate_count"], 1)

    def test_10_completed_adjudication_original_identity(self) -> None:
        self.assertEqual(
            (sha256_bytes(self.original), len(self.original)),
            (COMPLETED_ADJUDICATION_SHA256, COMPLETED_ADJUDICATION_SIZE),
        )

    def test_11_no_broad_file_search_surface(self) -> None:
        source = (HERE / "adjudication_input_authority.py").read_text(encoding="utf-8")
        for marker in ("glob(", "rglob(", "iterdir(", "os.walk(", "find "):
            self.assertNotIn(marker, source)
        self.assertTrue(self.input_authority["broad_file_search_performed"] is False)

    def test_12_local_original_is_byte_identical(self) -> None:
        self.assertEqual(self.original, primary_input_path().read_bytes())

    def test_13_input_has_no_bom_and_is_crlf_only(self) -> None:
        self.assertFalse(self.original.startswith(BOM))
        self.assertEqual(self.original.count(b"\r\n"), 24)
        self.assertEqual(self.original.count(b"\n"), 24)
        self.assertTrue(self.original.endswith(b"\r\n"))

    def test_14_exact_date_replacements(self) -> None:
        self.assertEqual(self.original.count(OLD_DATE), 23)
        self.assertEqual(self.original.count(ISO_DATE), 0)
        self.assertEqual(self.canonical.count(ISO_DATE), 23)
        self.assertEqual(self.canonical.count(OLD_DATE), 0)

    def test_15_exact_immutable_boolean_replacements(self) -> None:
        self.assertEqual(self.original.count(OLD_FALSE), 46)
        self.assertEqual(self.original.count(CANONICAL_FALSE), 0)
        self.assertEqual(self.canonical.count(CANONICAL_FALSE), 46)
        self.assertEqual(self.canonical.count(OLD_FALSE), 0)

    def test_16_bom_addition_and_reverse_byte_identity(self) -> None:
        self.assertEqual(self.canonical, canonicalise_bytes(self.original))
        reversed_bytes = self.canonical[len(BOM) :].replace(ISO_DATE, OLD_DATE).replace(
            CANONICAL_FALSE, OLD_FALSE
        )
        self.assertEqual(reversed_bytes, self.original)

    def test_17_canonical_adjudication_identity(self) -> None:
        self.assertEqual(
            (sha256_bytes(self.canonical), len(self.canonical)),
            (CANONICAL_ADJUDICATION_SHA256, CANONICAL_ADJUDICATION_SIZE),
        )

    def test_18_canonical_packet_shape(self) -> None:
        self.assertEqual(len(self.completed), 23)
        self.assertEqual(tuple(self.completed[0]), ADJUDICATION_PACKET_FIELDS)
        self.assertEqual(len(ADJUDICATION_PACKET_FIELDS), 52)

    def test_19_exact_disagreement_id_set_and_order(self) -> None:
        self.assertTrue(self.completed_validation["same_exact_disagreement_id_set"])
        self.assertTrue(self.completed_validation["same_row_order_as_frozen_blank"])
        self.assertEqual(self.completed_validation["duplicate_review_case_id_count"], 0)

    def test_20_all_fixed_fields_unchanged(self) -> None:
        blank = csv_rows(ROOT / D2A_BLANK_ADJUDICATION_RELATIVE)
        self.assertTrue(
            all(
                observed[field] == frozen[field]
                for observed, frozen in zip(self.completed, blank)
                for field in IMMUTABLE_PACKET_FIELDS
            )
        )

    def test_21_all_reviewer_fields_and_rationales_unchanged(self) -> None:
        self.assertTrue(self.completed_validation["reviewer_a_fields_unchanged"])
        self.assertTrue(self.completed_validation["reviewer_b_fields_unchanged"])
        self.assertTrue(self.completed_validation["reviewer_rationales_unchanged"])

    def test_22_disagreement_reasons_unchanged(self) -> None:
        self.assertTrue(self.completed_validation["disagreement_reasons_unchanged"])

    def test_23_all_368_adjudication_cells_complete(self) -> None:
        self.assertEqual(
            self.completed_validation["semantic_completed_adjudication_cell_count"],
            self.completed_validation["semantic_expected_adjudication_cell_count"],
        )
        self.assertEqual(self.completed_validation["semantic_expected_adjudication_cell_count"], 368)

    def test_24_adjudicator_identity_and_date_uniform(self) -> None:
        self.assertEqual({row["adjudicator_id"] for row in self.completed}, {"C"})
        self.assertEqual({row["adjudication_date"] for row in self.completed}, {"2026-08-29"})

    def test_25_no_uncertain_or_not_applicable(self) -> None:
        self.assertEqual(self.completed_validation["uncertain_or_not_applicable_value_count"], 0)
        for row in self.completed:
            for field in ADJUDICATION_HUMAN_FIELDS:
                self.assertNotIn(row[field], {"UNCERTAIN", "NOT_APPLICABLE"})

    def test_26_capability_exclusivity(self) -> None:
        self.assertEqual(self.completed_validation["clarification_exclusivity_violation_count"], 0)
        self.assertEqual(self.completed_validation["safe_direct_exclusivity_violation_count"], 0)

    def test_27_forbidden_and_context_consistency(self) -> None:
        self.assertEqual(self.completed_validation["forbidden_required_overlap_count"], 0)
        self.assertEqual(
            self.completed_validation["context_insufficient_internal_consistency_violation_count"],
            0,
        )

    def test_28_complete_row_authority(self) -> None:
        self.assertTrue(self.precedence["complete_row_authority"])
        self.assertFalse(self.precedence["disagreement_reason_only_replacement_used"])
        self.assertFalse(self.precedence["complete_row_decision_overridden"])

    def test_29_exact_consensus_field_override(self) -> None:
        self.assertEqual(self.precedence["adjudicator_changes_a_b_consensus_field_count"], 1)
        item = self.precedence["consensus_field_overrides"][0]
        self.assertEqual(
            (item["review_case_id"], item["field"], item["reviewer_a_value"], item["reviewer_b_value"], item["adjudicated_value"]),
            ("TBV1-77302F0D863B83D5", "context_resolution_required", "NO", "NO", "YES"),
        )

    def test_30_exact_third_value_resolution(self) -> None:
        self.assertEqual(self.precedence["adjudicator_selects_value_outside_a_b_pair_count"], 1)
        item = self.precedence["third_value_resolutions"][0]
        self.assertEqual(
            (item["review_case_id"], item["field"], item["reviewer_a_value"], item["reviewer_b_value"], item["adjudicated_value"]),
            ("TBV1-901EAA6E1906DB2E", "query_naturalness_1_to_5", "5", "3", "4"),
        )

    def test_31_decision_source_composition(self) -> None:
        counts = Counter(item.gold_decision_source for item in self.decisions)
        self.assertEqual(counts, {"HUMAN_CONSENSUS": 25, "HUMAN_ADJUDICATION_COMPLETE_ROW": 23})
        self.assertEqual(self.precedence["unresolved_non_adjudicated_case_count"], 0)

    def test_32_all_48_cases_included(self) -> None:
        self.assertEqual(Counter(row["case_validity"] for row in self.label_rows), {"INCLUDE_VALID_CASE": 48})

    def test_33_label_only_exact_schema(self) -> None:
        self.assertEqual(len(self.label_rows), 48)
        self.assertTrue(all(set(row) == set(LABEL_GOLD_FIELDS) for row in self.label_rows))
        self.assertTrue(all(not (set(row) & set(VISIBLE_FIELDS[1:])) for row in self.label_rows))

    def test_34_label_only_gold_exact_identity(self) -> None:
        self.assertEqual((sha256_bytes(self.label_bytes), len(self.label_bytes)), (LABEL_GOLD_SHA256, LABEL_GOLD_SIZE))
        self.assertEqual(self.label_bytes, (ROOT / LABEL_GOLD_RELATIVE).read_bytes())

    def test_35_full_text_gold_exact_identity(self) -> None:
        self.assertEqual((sha256_bytes(self.full_bytes), len(self.full_bytes)), (FULL_GOLD_SHA256, FULL_GOLD_SIZE))
        self.assertEqual(self.full_bytes, (ROOT / FULL_GOLD_RELATIVE).read_bytes())

    def test_36_full_text_gold_has_no_rationale(self) -> None:
        prohibited = {"reviewer_rationale", "adjudicator_rationale", "rationale"}
        self.assertTrue(all(not (set(row) & prohibited) for row in self.full_rows))

    def test_37_gold_sorted_by_opaque_case_id(self) -> None:
        ids = [row["review_case_id"] for row in self.label_rows]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_38_context_distributions(self) -> None:
        expected = self.summary["categorical_distributions"]
        self.assertEqual(expected["context_sufficient"], {"YES": 44, "NO": 4})
        self.assertEqual(expected["context_resolution_required"], {"YES": 39, "NO": 9})

    def test_39_capability_distributions(self) -> None:
        self.assertEqual(
            self.summary["capability_positive_counts"],
            {"dashboard_evidence": 12, "course_retrieval": 4, "episodic_memory": 13, "planning": 10, "safe_direct_response": 15, "clarification": 4},
        )

    def test_40_capability_set_distribution(self) -> None:
        self.assertEqual(sum(self.summary["capability_set_distribution"].values()), 48)
        self.assertEqual(self.summary["multi_capability_case_count"], 9)

    def test_41_forbidden_distribution(self) -> None:
        self.assertEqual(
            self.summary["forbidden_capability_set_distribution"],
            {"empty": 37, "dashboard_evidence": 6, "course_retrieval;episodic_memory": 2, "dashboard_evidence;episodic_memory": 1, "course_retrieval;planning": 1, "planning": 1},
        )

    def test_42_context_insufficient_is_clarification_only(self) -> None:
        self.assertEqual(self.summary["context_insufficient_case_count"], 4)
        self.assertTrue(self.summary["context_insufficient_clarification_only"])

    def test_43_safe_direct_is_exclusive(self) -> None:
        self.assertEqual(self.summary["safe_direct_case_count"], 15)
        self.assertTrue(self.summary["safe_direct_response_only"])

    def test_44_gold_double_build_byte_identical(self) -> None:
        second = build_gold_bytes(self.decisions)
        self.assertEqual((self.label_bytes, self.full_bytes), second[:2])

    def test_45_bundle_manifest_and_commitment(self) -> None:
        rebuilt_manifest, rebuilt_receipt = build_gold_bundle_documents(
            attestation_sha256=sha256_file(HERE / "track_b_human_adjudicator_independence_attestation_v1.json"),
            decision_precedence_sha256=sha256_file(HERE / "track_b_human_decision_precedence_v1.json"),
            gold_summary_sha256=sha256_file(HERE / "track_b_capability_gold_summary_v1.json"),
        )
        self.assertEqual(self.manifest, rebuilt_manifest)
        self.assertEqual(self.receipt, rebuilt_receipt)
        self.assertEqual(self.manifest["gold_bundle_sha256"], self.receipt["gold_bundle_sha256"])

    def test_46_freeze_receipt_and_before_unblinding(self) -> None:
        self.assertEqual(self.receipt["state"], "TRACK_B_CAPABILITY_GOLD_FROZEN")
        self.assertTrue(self.receipt["gold_frozen_before_legacy_unblinding"])
        self.assertFalse(self.receipt["hidden_legacy_accessed"])

    def test_47_human_adjudicator_attestation(self) -> None:
        attestation = human_adjudicator_attestation()
        self.assertTrue(attestation["third_adjudicator_distinct"])
        self.assertEqual(attestation["adjudicator_id"], "C")
        self.assertFalse(attestation["ai_used_for_annotation"])

    def test_48_hidden_legacy_guard_remains_denied(self) -> None:
        self.assertEqual(self.starting["hidden_legacy_access_guard"], "DENIED")
        self.assertFalse(self.manifest["hidden_legacy_accessed"])

    def test_49_no_raw_mapping_or_model_access(self) -> None:
        preflight = _json("rq2d2b_preflight_report_v1.json")
        self.assertFalse(preflight["raw_track_b_accessed"])
        self.assertFalse(preflight["raw_mapping_accessed"])
        self.assertEqual(preflight["model_execution_count"], 0)

    def test_50_no_policy_threshold_or_final_evaluation(self) -> None:
        preflight = _json("rq2d2b_preflight_report_v1.json")
        self.assertFalse(preflight["policy_threshold_or_seed_change"])
        self.assertFalse(preflight["final_evaluation_started"])

    def test_51_local_artifacts_ignored_and_untracked(self) -> None:
        assert_local_boundaries()

    def test_52_tracked_outputs_have_no_governed_text(self) -> None:
        assert_safe_tracked_outputs()
        governed_text_leak_scan()

    def test_53_python_ast_and_no_provider_model_surface(self) -> None:
        assert_all_python_ast()
        assert_no_provider_network_or_model_surface()

    def test_54_gitignore_and_change_scope(self) -> None:
        assert_gitignore_contract()
        assert_change_scope()

    def test_55_double_finalisation_byte_identical(self) -> None:
        assert_double_finalisation()

    def test_56_output_checksums(self) -> None:
        result = validate_output_checksums()
        self.assertEqual(result["referenced_tracked_output_count"], 28)

    def test_57_review_package_completeness_contract(self) -> None:
        members = expected_review_members()
        self.assertEqual(len(members), 34)
        self.assertEqual(len(members), len(set(members)))
        self.assertNotIn(FULL_GOLD_RELATIVE.as_posix(), members)
        self.assertNotIn(CANONICAL_ADJUDICATION_RELATIVE.as_posix(), members)

    def test_58_protected_sources_unchanged(self) -> None:
        assert_protected_sources_unchanged()

    def test_59_canonical_jsonl_rules(self) -> None:
        for value in (self.label_bytes, self.full_bytes):
            self.assertFalse(value.startswith(BOM))
            self.assertNotIn(b"\r\n", value)
            self.assertTrue(value.endswith(b"\n"))

    def test_60_label_gold_fixed_governance_fields(self) -> None:
        self.assertTrue(all(row["source_role"] == "track_b_contextual_final" for row in self.label_rows))
        self.assertTrue(all(row["gold_inclusion_status"] == "TRACK_B_CAPABILITY_FINAL_GOLD" for row in self.label_rows))
        self.assertTrue(all(row["query_rewrite_performed"] is False and row["assistant_context_attached"] is False for row in self.label_rows))

    def test_61_forbidden_arrays_are_in_frozen_order(self) -> None:
        order = {name: index for index, name in enumerate(CAPABILITIES)}
        for row in self.label_rows:
            values = row["forbidden_capabilities"]
            self.assertIsInstance(values, list)
            self.assertEqual(values, sorted(values, key=order.__getitem__))

    def test_62_safe_output_file_set_is_checksum_bound(self) -> None:
        lines = (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 28)
        self.assertEqual(len({line.split("  ", 1)[1] for line in lines}), 28)


if __name__ == "__main__":
    unittest.main()
