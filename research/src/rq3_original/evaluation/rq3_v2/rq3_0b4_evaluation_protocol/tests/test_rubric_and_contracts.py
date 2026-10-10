from __future__ import annotations

import json
from pathlib import Path
import unittest

from evaluation.rq3_v2.rq3_0b4_evaluation_protocol import PRIMARY_CRITERIA


ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class RubricAndContractTests(unittest.TestCase):
    def test_required_outputs_exist(self) -> None:
        required = {
            "rq3_primary_eight_criterion_rubric_v1.json",
            "RQ3_PRIMARY_RUBRIC.md",
            "rq3_dimension_applicability_v1.json",
            "rq3_judge_prompt_frozen_v1.txt",
            "rq3_judge_response_schema_v1.json",
            "rq3_blinding_and_randomisation_protocol_v1.json",
            "rq3_statistical_analysis_contract_v1.json",
            "human_rating_packet_schema_v1.json",
            "HUMAN_RATER_GUIDE.md",
            "human_rater_attestation_A.md",
            "human_rater_attestation_B.md",
            "rq3_judge_request_builder.py",
            "rq3_judge_response_parser.py",
            "rq3_human_agreement.py",
            "RQ3_EVALUATION_METHOD.md",
            "STATUS.md",
            "RQ3_0B4_OUTPUT_SHA256_MANIFEST.sha256",
        }
        self.assertEqual({name for name in required if (ROOT / name).is_file()}, required)

    def test_exact_eight_primary_criteria_and_order(self) -> None:
        rubric = load_json("rq3_primary_eight_criterion_rubric_v1.json")
        self.assertEqual(tuple(rubric["criterion_order"]), PRIMARY_CRITERIA)
        self.assertEqual(tuple(item["criterion_name"] for item in rubric["criteria"]), PRIMARY_CRITERIA)

    def test_authoritative_source_is_identified(self) -> None:
        source = load_json("rq3_primary_eight_criterion_rubric_v1.json")["source"]
        self.assertEqual(source["doi"], "10.1145/3785022.3785028")
        self.assertEqual(source["year"], 2026)
        self.assertIn("predeclared RQ3-0B4 operationalisation", source["provenance_note"])

    def test_every_criterion_has_all_five_behavioural_anchors(self) -> None:
        criteria = load_json("rq3_primary_eight_criterion_rubric_v1.json")["criteria"]
        for item in criteria:
            self.assertEqual(set(item["behavioural_anchors"]), {"1", "2", "3", "4", "5"})
            self.assertTrue(all(item["behavioural_anchors"][str(score)] for score in range(1, 6)))

    def test_always_applicable_set_is_exact(self) -> None:
        criteria = load_json("rq3_primary_eight_criterion_rubric_v1.json")["criteria"]
        actual = {
            item["criterion_name"]
            for item in criteria
            if item["applicability_class"] == "ALWAYS_APPLICABLE"
        }
        self.assertEqual(actual, {"CLARITY", "CONTEXT_AWARENESS", "RELIABILITY"})

    def test_na_cannot_encode_poor_performance(self) -> None:
        rules = load_json("rq3_primary_eight_criterion_rubric_v1.json")["global_na_rules"]
        self.assertTrue(any("performed poorly" in rule for rule in rules))
        self.assertTrue(any("score of 1" in rule.lower() for rule in load_json("rq3_dimension_applicability_v1.json")["invariants"]))

    def test_primary_aggregate_requires_three_and_preserves_dimensions(self) -> None:
        primary = load_json("rq3_primary_eight_criterion_rubric_v1.json")["primary_outcome"]
        self.assertEqual(primary["outcome_name"], "OVERALL_APPLICABLE_MEAN")
        self.assertEqual(primary["minimum_applicable_criteria"], 3)
        self.assertTrue(primary["preserve_all_dimension_scores"])
        self.assertTrue(primary["local_recomputation_required"])

    def test_secondary_audits_are_excluded_from_primary_mean(self) -> None:
        audits = load_json("rq3_primary_eight_criterion_rubric_v1.json")["secondary_technical_audits"]
        self.assertTrue(audits["excluded_from_primary_mean"])
        self.assertEqual(audits["EVIDENCE_FAITHFULNESS"]["allowed_scores"], [1, 2, 3, 4, 5])
        self.assertEqual(audits["UNSUPPORTED_CLAIM_COUNT"]["type"], "non_negative_integer")

    def test_applicability_contract_forbids_post_response_inputs(self) -> None:
        contract = load_json("rq3_dimension_applicability_v1.json")
        self.assertIn("candidate_response", contract["forbidden_derivation_inputs"])
        self.assertIn("judge_output", contract["forbidden_derivation_inputs"])
        self.assertIn("observed_condition_result", contract["forbidden_derivation_inputs"])
        self.assertEqual(contract["output_contract"]["freeze_status"], "FROZEN_BEFORE_CANDIDATE_SCORING")

    def test_applicability_rules_match_authorization(self) -> None:
        rules = {
            row["criterion"]: row["applicable_when"]
            for row in load_json("rq3_dimension_applicability_v1.json")["derivation_rules_in_fixed_order"]
        }
        self.assertEqual(tuple(rules), PRIMARY_CRITERIA)
        self.assertEqual(rules["CLARITY"], "true")
        self.assertIn("long_term_memory_relevant", rules["PERSONALISATION"])
        self.assertIn("gold_planning_required", rules["ACTIONABILITY"])
        self.assertIn("count(distinct material_lad_pages) > 1", rules["MULTI_PAGE_COHESIVENESS"])
        self.assertIn("boundary_handling_relevant", rules["ERROR_HANDLING"])

    def test_exactly_one_judge_prompt_template(self) -> None:
        prompts = list(ROOT.glob("rq3_judge_prompt*_v*.txt"))
        self.assertEqual([path.name for path in prompts], ["rq3_judge_prompt_frozen_v1.txt"])
        self.assertEqual(prompts[0].read_text(encoding="utf-8").count("{{BLIND_JUDGE_REQUEST_JSON}}"), 1)

    def test_judge_prompt_has_frozen_behaviour(self) -> None:
        prompt = (ROOT / "rq3_judge_prompt_frozen_v1.txt").read_text(encoding="utf-8")
        for required in (
            "Do not assume missing RAG",
            "Do not reward length",
            "Do not infer or speculate about the experimental condition",
            "Penalise material fabricated",
            "short, criterion-specific rationale",
            "Do not generate an improved answer",
        ):
            self.assertIn(required, prompt)

    def test_judge_schema_is_closed_and_strict(self) -> None:
        schema = load_json("rq3_judge_response_schema_v1.json")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(len(schema["required"]), 14)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "rq3-judge-response-v1")
        self.assertEqual(schema["properties"]["unsupported_claim_count"]["minimum"], 0)
        self.assertFalse(schema["x-local-validation"]["judge_reported_overall_trusted"])

    def test_primary_score_schema_is_integer_or_exact_na(self) -> None:
        choices = load_json("rq3_judge_response_schema_v1.json")["$defs"]["primaryScore"]["oneOf"]
        self.assertEqual(choices[0], {"type": "integer", "minimum": 1, "maximum": 5})
        self.assertEqual(choices[1], {"type": "string", "const": "NA"})

    def test_blinding_seed_and_no_lexical_condition_order(self) -> None:
        protocol = load_json("rq3_blinding_and_randomisation_protocol_v1.json")
        self.assertEqual(protocol["judge_randomisation_seed"], 20260901)
        self.assertFalse(protocol["answer_order_randomisation"]["lexical_condition_order_permitted"])
        self.assertEqual(protocol["actual_blinding_key_status"], "NOT_CREATED_OR_AUTHORIZED_IN_RQ3_0B4")

    def test_human_packet_schema_has_two_roles_and_eight_scores(self) -> None:
        schema = load_json("human_rating_packet_schema_v1.json")
        self.assertEqual(schema["properties"]["rater_role"]["enum"], ["A", "B"])
        score_fields = schema["$defs"]["criterionScores"]["required"]
        self.assertEqual(len(score_fields), 8)
        self.assertFalse(schema["$defs"]["ratingItem"]["additionalProperties"])

    def test_human_attestations_are_unsigned_templates(self) -> None:
        for role in ("A", "B"):
            text = (ROOT / f"human_rater_attestation_{role}.md").read_text(encoding="utf-8")
            self.assertIn("UNSIGNED_TEMPLATE_NOT_AN_ACTUAL_ASSIGNMENT", text)
            self.assertIn("Do not sign this template in RQ3-0B4", text)

    def test_statistical_contract_has_exact_primary_contrast_counts(self) -> None:
        contrasts = load_json("rq3_statistical_analysis_contract_v1.json")["primary_contrasts"]
        self.assertEqual({key: len(value) for key, value in contrasts.items()}, {"RQ3-A": 3, "RQ3-B": 1, "RQ3-C": 4})
        formulas = [row["formula"] for group in contrasts.values() for row in group]
        self.assertIn("(RM11_RAG_MEMORY - RM01_MEMORY) - (RM10_RAG - RM00_BASE)", formulas)
        self.assertIn("PREDICTED_ROUTE - ALWAYS_ON", formulas)

    def test_statistics_use_family_cluster_bootstrap_and_holm(self) -> None:
        contract = load_json("rq3_statistical_analysis_contract_v1.json")
        self.assertEqual(contract["clustering_and_resampling_unit"], "scenario_family_id")
        self.assertEqual(contract["interval_estimation"]["replicates"], 10000)
        self.assertEqual(contract["interval_estimation"]["confidence_level"], 0.95)
        self.assertTrue(contract["multiplicity"]["method"].startswith("Holm"))
        self.assertFalse(contract["multiplicity"]["post_exposure_new_contrasts_permitted"])

    def test_oracle_gain_guard_is_frozen(self) -> None:
        guard = load_json("rq3_statistical_analysis_contract_v1.json")["oracle_gain_retention"]
        self.assertEqual(guard["near_zero_denominator_guard"]["absolute_threshold_rubric_points"], 0.05)
        self.assertEqual(guard["near_zero_denominator_guard"]["result"], "NOT_ESTIMABLE_NEAR_ZERO_ORACLE_GAIN")
        self.assertFalse(guard["clipping_permitted"])

    def test_human_sampling_is_future_deterministic_family_selection(self) -> None:
        sampling = load_json("rq3_statistical_analysis_contract_v1.json")["human_validation_sampling"]
        self.assertEqual(sampling["selection_unit"], "scenario_family_id")
        self.assertEqual(sampling["minimum_eligible_families"], 10)
        self.assertEqual(sampling["deterministic_seed"], 20260901)
        self.assertEqual(sampling["actual_response_ids_selected_in_rq3_0b4"], 0)
        self.assertIn("RAG+Memory", sampling["required_coverage_tokens"])
        self.assertIn("each distinct LAD page in the frozen cohort", sampling["required_coverage_tokens"])

    def test_model_selection_remains_directly_blocked(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        method = (ROOT / "RQ3_EVALUATION_METHOD.md").read_text(encoding="utf-8")
        self.assertIn("JUDGE_MODEL_REQUIRES_DIRECT_AUTHORIZATION", status)
        self.assertIn("JUDGE_MODEL_REQUIRES_DIRECT_AUTHORIZATION", method)
        self.assertIn("selects none", status)


if __name__ == "__main__":
    unittest.main()
