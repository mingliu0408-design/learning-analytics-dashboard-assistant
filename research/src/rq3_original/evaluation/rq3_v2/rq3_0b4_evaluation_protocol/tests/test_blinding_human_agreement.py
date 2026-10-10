from __future__ import annotations

import copy
import json
import math
import unittest

from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_human_agreement import (
    AgreementError,
    agreement_by_criterion,
    agreement_metrics,
    human_and_llm_agreement_bundle,
    quadratic_weighted_kappa,
    spearman_correlation,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_human_packet_builder import (
    HumanPacketError,
    build_blank_human_rating_packet,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    BlindingError,
    blind_ids_only,
    build_judge_request,
    deterministic_response_order,
    freeze_applicability,
    make_response_blind_id,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.run_toy_harness import run_toy_harness


KEY = b"synthetic-only-blinding-key-for-unit-tests"


def all_applicable_map():
    return freeze_applicability(
        {
            "applicability_metadata_version": "rq3-applicability-source-metadata-v1",
            "student_specific_data_relevant": True,
            "long_term_memory_relevant": True,
            "request_requires_advice": True,
            "gold_planning_required": True,
            "student_facing_support_appropriate": True,
            "material_lad_pages": ["TOY_PAGE_A", "TOY_PAGE_B"],
            "ambiguity_relevant": True,
            "missing_evidence_relevant": False,
            "insufficiency_relevant": False,
            "conflict_relevant": False,
            "boundary_handling_relevant": False,
        }
    )


def toy_request(blind_id):
    return build_judge_request(
        response_blind_id=blind_id,
        student_query="Synthetic query",
        current_lad_page="TOY_PAGE_A",
        visible_conversation_history=["Synthetic history"],
        frozen_dashboard_evidence={"toy": True},
        course_evidence_available_in_condition={"availability": "TOY"},
        long_term_memory_available_in_condition={"availability": "TOY"},
        planning_support_available_in_condition={"availability": "TOY"},
        candidate_response="Prewritten synthetic candidate.",
        frozen_applicability_map=all_applicable_map(),
    )


def rating_record(blind_id, values):
    return {
        "response_blind_id": blind_id,
        "criterion_scores": {
            SCORE_FIELDS[name]: value for name, value in zip(PRIMARY_CRITERIA, values)
        },
    }


class BlindingAndAgreementTests(unittest.TestCase):
    def test_blind_id_is_deterministic_and_opaque_format(self) -> None:
        first = make_response_blind_id(KEY, "TOY_FAMILY", "TOY_SOURCE")
        second = make_response_blind_id(KEY, "TOY_FAMILY", "TOY_SOURCE")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^R3B-[A-F0-9]{20}$")
        self.assertNotIn("TOY_FAMILY", first)
        self.assertNotIn("TOY_SOURCE", first)

    def test_blind_id_changes_with_key_family_or_source(self) -> None:
        baseline = make_response_blind_id(KEY, "F1", "S1")
        alternatives = {
            make_response_blind_id(b"another-synthetic-key-value", "F1", "S1"),
            make_response_blind_id(KEY, "F2", "S1"),
            make_response_blind_id(KEY, "F1", "S2"),
        }
        self.assertEqual(len(alternatives), 3)
        self.assertNotIn(baseline, alternatives)

    def test_blind_id_rejects_short_key(self) -> None:
        with self.assertRaises(BlindingError):
            make_response_blind_id(b"short", "F", "S")

    def test_schedule_is_deterministic_and_input_order_invariant(self) -> None:
        records = [
            {"scenario_family_id": family, "response_source_key": f"{family}-{index}"}
            for family in ("FAMILY_C", "FAMILY_A", "FAMILY_B")
            for index in (1, 2, 3)
        ]
        forward = deterministic_response_order(records, KEY)
        reverse = deterministic_response_order(list(reversed(records)), KEY)
        self.assertEqual(forward, reverse)

    def test_schedule_ids_are_unique(self) -> None:
        records = [
            {"scenario_family_id": "F1", "response_source_key": "S1"},
            {"scenario_family_id": "F1", "response_source_key": "S2"},
            {"scenario_family_id": "F2", "response_source_key": "S3"},
        ]
        schedule = deterministic_response_order(records, KEY)
        self.assertEqual(len(blind_ids_only(schedule)), 3)
        self.assertEqual(len(set(blind_ids_only(schedule))), 3)

    def test_schedule_interleaves_families_while_multiple_are_active(self) -> None:
        records = [
            {"scenario_family_id": family, "response_source_key": f"{family}-{index}"}
            for family in ("F1", "F2", "F3")
            for index in range(3)
        ]
        families = [row["scenario_family_id"] for row in deterministic_response_order(records, KEY)]
        self.assertTrue(all(left != right for left, right in zip(families, families[1:])))

    def test_schedule_does_not_use_lexical_source_order(self) -> None:
        records = [
            {"scenario_family_id": "F1", "response_source_key": source}
            for source in ("ANSWER_A", "ANSWER_B", "ANSWER_C", "ANSWER_D")
        ]
        sources = [row["response_source_key"] for row in deterministic_response_order(records, KEY)]
        self.assertNotEqual(sources, sorted(sources))

    def test_schedule_rejects_duplicate_sources(self) -> None:
        records = [
            {"scenario_family_id": "F1", "response_source_key": "SAME"},
            {"scenario_family_id": "F2", "response_source_key": "SAME"},
        ]
        with self.assertRaises(BlindingError):
            deterministic_response_order(records, KEY)

    def test_blank_human_packet_contains_no_restricted_mapping_fields(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        packet = build_blank_human_rating_packet(
            packet_blind_id="HRP-TOY-A",
            rater_role="A",
            judge_requests=[toy_request(blind_id)],
        )
        encoded = json.dumps(packet, sort_keys=True)
        for forbidden in (
            "condition_id",
            "scenario_family_id",
            "router_name",
            "expected_winner",
            "ORACLE_ROUTE",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(packet["packet_status"], "UNRATED_TEMPLATE")

    def test_blank_human_packet_has_all_null_scores_and_blank_notes(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        packet = build_blank_human_rating_packet(
            packet_blind_id="HRP-TOY-B",
            rater_role="B",
            judge_requests=[toy_request(blind_id)],
        )
        item = packet["items"][0]
        self.assertTrue(all(value is None for value in item["criterion_scores"].values()))
        self.assertTrue(all(value == "" for value in item["criterion_notes"].values()))
        self.assertTrue(all(value is None for value in packet["attestation"].values()))

    def test_two_packet_roles_remain_separate(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        request = toy_request(blind_id)
        packet_a = build_blank_human_rating_packet(
            packet_blind_id="HRP-TOY-A", rater_role="A", judge_requests=[request]
        )
        packet_b = build_blank_human_rating_packet(
            packet_blind_id="HRP-TOY-B", rater_role="B", judge_requests=[request]
        )
        self.assertEqual(packet_a["items"], packet_b["items"])
        self.assertNotEqual(packet_a["rater_role"], packet_b["rater_role"])

    def test_human_packet_rejects_duplicate_response_ids(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        request = toy_request(blind_id)
        with self.assertRaises(HumanPacketError):
            build_blank_human_rating_packet(
                packet_blind_id="HRP-TOY-A",
                rater_role="A",
                judge_requests=[request, copy.deepcopy(request)],
            )

    def test_human_packet_revalidates_blinding_of_loaded_request(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        forged = toy_request(blind_id)
        forged["frozen_dashboard_evidence"] = {"condition_name": "hidden"}
        with self.assertRaises(HumanPacketError):
            build_blank_human_rating_packet(
                packet_blind_id="HRP-TOY-A", rater_role="A", judge_requests=[forged]
            )

    def test_perfect_agreement_toy_example(self) -> None:
        values = [1, 2, 3, 4, 5]
        metrics = agreement_metrics(values, values)
        self.assertAlmostEqual(metrics["quadratic_weighted_kappa"], 1.0)
        self.assertAlmostEqual(metrics["spearman_correlation"], 1.0)
        self.assertEqual(metrics["exact_agreement"], 1.0)
        self.assertEqual(metrics["within_one_point_agreement"], 1.0)
        self.assertEqual(metrics["mean_absolute_score_difference"], 0.0)

    def test_reverse_rank_toy_example(self) -> None:
        self.assertAlmostEqual(spearman_correlation([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)
        self.assertAlmostEqual(quadratic_weighted_kappa([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)

    def test_exact_within_one_mae_and_bias_toy_example(self) -> None:
        metrics = agreement_metrics([1, 2, 4, 5], [2, 2, 5, 3])
        self.assertEqual(metrics["exact_agreement"], 0.25)
        self.assertEqual(metrics["within_one_point_agreement"], 0.75)
        self.assertEqual(metrics["mean_absolute_score_difference"], 1.0)
        self.assertEqual(metrics["criterion_level_bias_source_b_minus_source_a"], 0.0)

    def test_zero_variance_metrics_are_not_estimable(self) -> None:
        self.assertIsNone(quadratic_weighted_kappa([3, 3, 3], [3, 3, 3]))
        self.assertIsNone(spearman_correlation([3, 3, 3], [3, 3, 3]))

    def test_agreement_rejects_invalid_or_unequal_scores(self) -> None:
        with self.assertRaises(AgreementError):
            agreement_metrics([1, 2], [1])
        with self.assertRaises(AgreementError):
            agreement_metrics([1, True], [1, 2])

    def test_per_criterion_and_pooled_agreement_excludes_joint_na(self) -> None:
        blind_1 = make_response_blind_id(KEY, "F1", "S1")
        blind_2 = make_response_blind_id(KEY, "F2", "S2")
        left = [
            rating_record(blind_1, [5, "NA", 4, 5, "NA", 5, "NA", 4]),
            rating_record(blind_2, [4, "NA", 3, 4, "NA", 4, "NA", 3]),
        ]
        right = [
            rating_record(blind_1, [5, "NA", 5, 4, "NA", 5, "NA", 4]),
            rating_record(blind_2, [4, "NA", 3, 4, "NA", 3, "NA", 3]),
        ]
        result = agreement_by_criterion(left, right)
        self.assertEqual(result["per_criterion"]["clarity"]["n"], 2)
        self.assertEqual(result["per_criterion"]["personalisation"]["n"], 0)
        self.assertEqual(result["pooled"]["n"], 10)

    def test_per_criterion_agreement_rejects_applicability_mismatch(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        left = [rating_record(blind_id, [5, "NA", 4, 5, "NA", 5, "NA", 4])]
        right = [rating_record(blind_id, [5, 3, 4, 5, "NA", 5, "NA", 4])]
        with self.assertRaises(AgreementError):
            agreement_by_criterion(left, right)

    def test_human_llm_bundle_retains_both_human_sources(self) -> None:
        blind_id = make_response_blind_id(KEY, "F1", "S1")
        human_a = [rating_record(blind_id, [5, 4, 4, 5, 4, 5, 4, 4])]
        human_b = [rating_record(blind_id, [4, 4, 5, 5, 4, 5, 4, 3])]
        llm = [rating_record(blind_id, [5, 5, 5, 5, 4, 5, 5, 4])]
        result = human_and_llm_agreement_bundle(human_a, human_b, llm)
        self.assertEqual(result["human_a_vs_llm_judge"]["pooled"]["n"], 8)
        self.assertEqual(result["human_b_vs_llm_judge"]["pooled"]["n"], 8)
        self.assertEqual(
            result["pooled_human_observations_vs_llm_judge"]["pooled"]["n"], 16
        )
        self.assertFalse(result["score_rewriting_performed"])

    def test_toy_harness_exercises_all_offline_components(self) -> None:
        result = run_toy_harness()
        self.assertEqual(result["harness_status"], "PASS_SYNTHETIC_TOY_ONLY")
        self.assertTrue(result["blind_ids_unique"])
        self.assertEqual(result["judge_requests_built"], 1)
        self.assertEqual(result["synthetic_judge_records_locally_validated"], 1)
        self.assertEqual(result["blank_toy_human_packets_built"], 2)
        self.assertGreater(result["toy_human_human_pooled_n"], 0)

    def test_toy_harness_confirms_zero_live_actions(self) -> None:
        result = run_toy_harness()
        for field in (
            "student_facing_responses_generated",
            "llm_judge_calls",
            "provider_calls",
            "human_ratings_collected",
            "real_rq3_scores_read_or_computed",
        ):
            self.assertEqual(result[field], 0, field)


if __name__ == "__main__":
    unittest.main()
