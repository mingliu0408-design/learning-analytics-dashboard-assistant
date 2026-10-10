"""Unit tests for the RQ2-V2 Stage 1 Track A packet contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from build_writer_packets import expected_packet_rows, load_master
from validate_track_a import (
    TrackAValidationError,
    validate_course_evidence_and_rag_cues,
    validate_contrasts,
    validate_counts_and_combinations,
    validate_memory_payload_separation,
    validate_no_split_or_final_utterances,
    validate_pages_and_distinctness,
    validate_required_fields,
    validate_stage0_clarification_contract,
    validate_writer_packets,
    run_validation,
)


ROWS = load_master()


class TrackAContractTests(unittest.TestCase):
    def test_01_required_fields_and_provisional_labels(self) -> None:
        validate_required_fields(ROWS)

    def test_02_exact_family_and_combination_counts(self) -> None:
        validate_counts_and_combinations(ROWS)

    def test_03_clarifications_follow_stage0_contract(self) -> None:
        validate_stage0_clarification_contract(ROWS)

    def test_04_pages_are_balanced_and_scenarios_distinct(self) -> None:
        validate_pages_and_distinctness(ROWS)

    def test_05_controlled_contrasts_validate(self) -> None:
        validate_contrasts(ROWS)

    def test_06_no_split_or_final_utterance_exists(self) -> None:
        validate_no_split_or_final_utterances(ROWS)

    def test_07_hidden_memory_payloads_are_separated(self) -> None:
        validate_memory_payload_separation(ROWS)

    def test_08_course_evidence_and_rag_cues_validate(self) -> None:
        validate_course_evidence_and_rag_cues(ROWS)

    def test_09_writer_packets_are_exact_blinded_exports(self) -> None:
        validate_writer_packets(ROWS)

    def test_10_packet_ids_and_orders_are_writer_specific(self) -> None:
        packet_a = expected_packet_rows("A", ROWS)
        packet_b = expected_packet_rows("B", ROWS)
        order_a = [row["review_case_id"] for row in packet_a]
        order_b = [row["review_case_id"] for row in packet_b]
        self.assertEqual(set(order_a), set(order_b))
        self.assertNotEqual(order_a, order_b)
        by_review_a = {row["review_case_id"]: row for row in packet_a}
        by_review_b = {row["review_case_id"]: row for row in packet_b}
        self.assertEqual(len({row["utterance_id"] for row in packet_a}), 54)
        self.assertEqual(len({row["utterance_id"] for row in packet_b}), 54)
        for review_case_id in by_review_a:
            self.assertEqual(
                by_review_a[review_case_id]["scenario_family_id"],
                by_review_b[review_case_id]["scenario_family_id"],
            )
            self.assertNotEqual(
                by_review_a[review_case_id]["utterance_id"],
                by_review_b[review_case_id]["utterance_id"],
            )

    def test_11_duplicate_family_id_is_rejected(self) -> None:
        invalid = deepcopy(ROWS)
        invalid[-1]["scenario_family_id"] = invalid[0]["scenario_family_id"]
        with self.assertRaises(TrackAValidationError):
            validate_counts_and_combinations(invalid)

    def test_12_clarify_capability_route_is_rejected(self) -> None:
        invalid = deepcopy(ROWS)
        clarification = next(row for row in invalid if row["proposed_dialogue_action"] == "CLARIFY")
        clarification["proposed_rag_required"] = True
        with self.assertRaises(TrackAValidationError):
            validate_stage0_clarification_contract(invalid)

    def test_13_split_assignment_is_rejected(self) -> None:
        invalid = deepcopy(ROWS)
        invalid[0]["partition"] = "DEV"
        with self.assertRaises(TrackAValidationError):
            validate_no_split_or_final_utterances(invalid)

    def test_14_hidden_memory_payload_leak_is_rejected(self) -> None:
        invalid = deepcopy(ROWS)
        memory_row = next(row for row in invalid if row["proposed_memory_required"])
        memory_row["writer_facing_student_background"] = memory_row["hidden_memory_payload"]
        with self.assertRaises(TrackAValidationError):
            validate_memory_payload_separation(invalid)

    def test_15_rag_meta_cue_is_rejected(self) -> None:
        invalid = deepcopy(ROWS)
        rag_row = next(row for row in invalid if row["proposed_rag_required"])
        rag_row["controlled_dashboard_context"] += " The framework is absent."
        with self.assertRaises(TrackAValidationError):
            validate_course_evidence_and_rag_cues(invalid)

    def test_16_full_validator_passes_all_checks(self) -> None:
        report = run_validation()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["check_count"], 10)
        self.assertEqual(report["pass_count"], 10)
        self.assertEqual(report["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
