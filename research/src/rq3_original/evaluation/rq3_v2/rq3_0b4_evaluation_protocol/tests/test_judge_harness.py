from __future__ import annotations

import copy
import json
import unittest

from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    ApplicabilityFreezeError,
    JudgeRequestError,
    build_judge_request,
    freeze_applicability,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_response_parser import (
    JudgeResponseError,
    parse_judge_response,
    recompute_overall_applicable_mean,
)


BLIND_ID = "R3B-0123456789ABCDEFABCD"


def metadata(**overrides):
    value = {
        "applicability_metadata_version": "rq3-applicability-source-metadata-v1",
        "student_specific_data_relevant": False,
        "long_term_memory_relevant": False,
        "request_requires_advice": False,
        "gold_planning_required": False,
        "student_facing_support_appropriate": False,
        "material_lad_pages": ["TOY_PAGE_ONE"],
        "ambiguity_relevant": False,
        "missing_evidence_relevant": False,
        "insufficiency_relevant": False,
        "conflict_relevant": False,
        "boundary_handling_relevant": False,
    }
    value.update(overrides)
    return value


def valid_response(applicability, score=4):
    scores = {
        SCORE_FIELDS[name]: score if applicability["criteria"][name] else "NA"
        for name in PRIMARY_CRITERIA
    }
    applicable_scores = [value for value in scores.values() if value != "NA"]
    return {
        "response_blind_id": BLIND_ID,
        **scores,
        "evidence_faithfulness": 5,
        "unsupported_claim_count": 0,
        "overall_applicable_mean": sum(applicable_scores) / len(applicable_scores),
        "criterion_rationales": {
            SCORE_FIELDS[name]: "A short synthetic criterion-specific rationale."
            for name in PRIMARY_CRITERIA
        },
        "schema_version": "rq3-judge-response-v1",
    }


def build_request(applicability, **overrides):
    values = {
        "response_blind_id": BLIND_ID,
        "student_query": "What does this synthetic chart mean?",
        "current_lad_page": "TOY_PAGE_ONE",
        "visible_conversation_history": ["Student: Synthetic history."],
        "frozen_dashboard_evidence": {"toy_value": 3},
        "course_evidence_available_in_condition": {"availability": "EMPTY"},
        "long_term_memory_available_in_condition": {"availability": "EMPTY"},
        "planning_support_available_in_condition": {"availability": "EMPTY"},
        "candidate_response": "This is a prewritten synthetic candidate response.",
        "frozen_applicability_map": applicability,
    }
    values.update(overrides)
    return build_judge_request(**values)


class ApplicabilityAndJudgeHarnessTests(unittest.TestCase):
    def test_minimal_map_has_exact_three_always_applicable_criteria(self) -> None:
        frozen = freeze_applicability(metadata())
        self.assertEqual(frozen["applicable_primary_count"], 3)
        self.assertEqual(
            {name for name, applies in frozen["criteria"].items() if applies},
            {"CLARITY", "CONTEXT_AWARENESS", "RELIABILITY"},
        )

    def test_all_conditional_applicability_rules_can_be_true(self) -> None:
        frozen = freeze_applicability(
            metadata(
                student_specific_data_relevant=True,
                request_requires_advice=True,
                student_facing_support_appropriate=True,
                material_lad_pages=["TOY_PAGE_ONE", "TOY_PAGE_TWO"],
                ambiguity_relevant=True,
            )
        )
        self.assertEqual(tuple(frozen["criteria"]), PRIMARY_CRITERIA)
        self.assertTrue(all(frozen["criteria"].values()))
        self.assertEqual(frozen["applicable_primary_count"], 8)

    def test_personalisation_can_be_triggered_by_memory_alone(self) -> None:
        frozen = freeze_applicability(metadata(long_term_memory_relevant=True))
        self.assertTrue(frozen["criteria"]["PERSONALISATION"])

    def test_actionability_can_be_triggered_by_gold_planning_alone(self) -> None:
        frozen = freeze_applicability(metadata(gold_planning_required=True))
        self.assertTrue(frozen["criteria"]["ACTIONABILITY"])

    def test_error_handling_uses_any_frozen_boundary_flag(self) -> None:
        frozen = freeze_applicability(metadata(boundary_handling_relevant=True))
        self.assertTrue(frozen["criteria"]["ERROR_HANDLING"])

    def test_applicability_rejects_candidate_response_input(self) -> None:
        source = metadata()
        source["candidate_response"] = "A bad answer must not affect NA."
        with self.assertRaises(ApplicabilityFreezeError):
            freeze_applicability(source)

    def test_applicability_rejects_duplicate_pages(self) -> None:
        with self.assertRaises(ApplicabilityFreezeError):
            freeze_applicability(metadata(material_lad_pages=["P", "P"]))

    def test_applicability_rejects_integer_as_boolean(self) -> None:
        with self.assertRaises(ApplicabilityFreezeError):
            freeze_applicability(metadata(request_requires_advice=1))

    def test_valid_strict_response_parses(self) -> None:
        frozen = freeze_applicability(metadata())
        parsed = parse_judge_response(valid_response(frozen), frozen, expected_response_blind_id=BLIND_ID)
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)

    def test_low_score_one_remains_valid_not_na(self) -> None:
        frozen = freeze_applicability(metadata(student_specific_data_relevant=True))
        response = valid_response(frozen)
        response["personalisation"] = 1
        response["overall_applicable_mean"] = (4 + 1 + 4 + 4) / 4
        parsed = parse_judge_response(response, frozen)
        self.assertEqual(parsed["personalisation"], 1)

    def test_applicable_score_cannot_be_converted_to_na(self) -> None:
        frozen = freeze_applicability(metadata(student_specific_data_relevant=True))
        response = valid_response(frozen)
        response["personalisation"] = "NA"
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)

    def test_non_applicable_score_must_be_na(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["personalisation"] = 1
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)

    def test_json_boolean_is_not_an_integer_score(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["clarity"] = True
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)

    def test_out_of_range_score_is_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["reliability"] = 6
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)

    def test_unsupported_claim_count_rejects_negative_and_boolean(self) -> None:
        frozen = freeze_applicability(metadata())
        for invalid in (-1, True):
            response = valid_response(frozen)
            response["unsupported_claim_count"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(JudgeResponseError):
                parse_judge_response(response, frozen)

    def test_secondary_audits_do_not_change_local_primary_mean(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["evidence_faithfulness"] = 1
        response["unsupported_claim_count"] = 99
        self.assertEqual(recompute_overall_applicable_mean(response, frozen), 4.0)
        self.assertEqual(parse_judge_response(response, frozen)["overall_applicable_mean"], 4.0)

    def test_incorrect_judge_mean_is_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["overall_applicable_mean"] = 5
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)

    def test_extra_or_missing_response_fields_are_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        extra = valid_response(frozen)
        extra["condition_id"] = "hidden"
        missing = valid_response(frozen)
        missing.pop("clarity")
        for response in (extra, missing):
            with self.subTest(keys=set(response)), self.assertRaises(JudgeResponseError):
                parse_judge_response(response, frozen)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        raw = '{"response_blind_id":"%s","response_blind_id":"%s"}' % (BLIND_ID, BLIND_ID)
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(raw, frozen)

    def test_empty_or_overlong_rationale_is_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        for invalid in ("", "x" * 501):
            response = valid_response(frozen)
            response["criterion_rationales"]["clarity"] = invalid
            with self.subTest(length=len(invalid)), self.assertRaises(JudgeResponseError):
                parse_judge_response(response, frozen)

    def test_expected_blind_id_mismatch_is_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(
                valid_response(frozen),
                frozen,
                expected_response_blind_id="R3B-FFFFFFFFFFFFFFFFFFFF",
            )

    def test_tampered_applicability_hash_is_rejected(self) -> None:
        frozen = freeze_applicability(metadata())
        tampered = copy.deepcopy(frozen)
        tampered["applicability_sha256"] = "0" * 64
        with self.assertRaises(ApplicabilityFreezeError):
            parse_judge_response(valid_response(frozen), tampered)

    def test_json_object_key_order_does_not_change_validity(self) -> None:
        frozen = freeze_applicability(metadata(student_specific_data_relevant=True))
        reordered = copy.deepcopy(frozen)
        reordered["criteria"] = dict(reversed(list(reordered["criteria"].items())))
        response = valid_response(frozen)
        response["criterion_rationales"] = dict(
            reversed(list(response["criterion_rationales"].items()))
        )
        parsed = parse_judge_response(response, reordered)
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)

    def test_judge_request_contains_only_authorized_content_fields(self) -> None:
        request = build_request(freeze_applicability(metadata()))
        self.assertEqual(
            set(request),
            {
                "schema_version",
                "response_blind_id",
                "student_query",
                "current_lad_page",
                "visible_conversation_history",
                "frozen_dashboard_evidence",
                "course_evidence_available_in_condition",
                "long_term_memory_available_in_condition",
                "planning_support_available_in_condition",
                "candidate_response",
                "frozen_applicability_map",
            },
        )
        encoded = json.dumps(request, sort_keys=True)
        for token in (
            "condition_id",
            "scenario_family_id",
            "router_name",
            "RM00_BASE",
            "ORACLE_ROUTE",
            "PREDICTED_ROUTE",
        ):
            self.assertNotIn(token, encoded)

    def test_judge_request_rejects_forbidden_structural_field(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, frozen_dashboard_evidence={"condition_id": "TOY"})

    def test_judge_request_rejects_known_experimental_label_token(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, candidate_response="This leaks ORACLE_ROUTE.")

    def test_judge_request_rejects_p3_or_nested_router_name(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, candidate_response="This leaks P3.")
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, frozen_dashboard_evidence={"selected_router_name": "hidden"})

    def test_judge_request_rejects_non_finite_json_number(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, frozen_dashboard_evidence={"toy_value": float("nan")})

    def test_judge_request_rejects_invalid_blind_id(self) -> None:
        frozen = freeze_applicability(metadata())
        with self.assertRaises(JudgeRequestError):
            build_request(frozen, response_blind_id="REAL_CASE_001")

    def test_parser_rejects_lowercase_blind_id_even_when_length_matches(self) -> None:
        frozen = freeze_applicability(metadata())
        response = valid_response(frozen)
        response["response_blind_id"] = BLIND_ID.lower()
        with self.assertRaises(JudgeResponseError):
            parse_judge_response(response, frozen)


if __name__ == "__main__":
    unittest.main()
