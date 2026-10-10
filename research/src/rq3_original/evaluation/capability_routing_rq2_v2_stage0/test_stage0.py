"""Minimal unit tests for the RQ2-V2 Stage 0 research contract."""

from __future__ import annotations

from copy import deepcopy
import unittest

from . import CAPABILITY_FIELDS, MODEL_IDS, PACKAGE_ROOT
from .build_review_zip import collect_review_files
from .contracts import (
    Stage0ContractError,
    load_json,
    load_jsonl,
    load_stage0_contracts,
    validate_b1_legacy_contract,
    validate_case,
    validate_clarification_contract,
    validate_contract,
    validate_contrast_pair,
    validate_dataset_registry,
    validate_prediction,
    validate_scenario_matrix,
)
from .interfaces import (
    DummyRouter,
    LegacyIntentCascadeInterface,
    UnfrozenLegacyMappingError,
    run_no_paid_api_dry_run,
)
from .leakage import detect_case_leakage, detect_tuning_leakage
from .metrics import evaluate_contrast_consistency, evaluate_predictions
from .validate_stage0 import run_validation


ASSETS = load_stage0_contracts()
TOY_CASES = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_cases_v1.jsonl")
TOY_PREDICTIONS = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_predictions_v1.jsonl")
TOY_CONTRASTS = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_contrast_pairs_v1.jsonl")


def _case(case_id: str, *, rag: bool, memory: bool, planning: bool) -> dict:
    value = deepcopy(TOY_CASES[0])
    value["case_id"] = case_id
    value["scenario_family_id"] = f"F-{case_id}"
    value["utterance_id"] = f"U-{case_id}"
    value["model_input"]["current_query"] = f"Toy query {case_id}"
    value["gold"] = {
        "dialogue_action": "ANSWER",
        "rag_required": rag,
        "memory_required": memory,
        "planning_required": planning,
    }
    return value


def _prediction(
    case_id: str, *, rag: bool, memory: bool, planning: bool, action: str = "ANSWER"
) -> dict:
    return {
        "schema_version": "rq2-v2-prediction-v1",
        "case_id": case_id,
        "model_id": "R2V2-B0_RULE",
        "dialogue_action": action,
        "rag_required": rag,
        "memory_required": memory,
        "planning_required": planning,
        "metadata": {
            "execution_mode": "UNIT_TEST_DUMMY",
            "provider_call_count": 0,
            "network_access": False,
            "training_performed": False,
        },
    }


class ContractAndSchemaTests(unittest.TestCase):
    def test_01_capability_contract(self) -> None:
        validate_contract(ASSETS["capability_contract"])

    def test_02_b1_identity_uses_actual_frozen_rq1(self) -> None:
        validate_b1_legacy_contract(ASSETS["b1_legacy_contract"])

    def test_03_all_toy_cases_validate(self) -> None:
        for case in TOY_CASES:
            validate_case(case)

    def test_04_all_toy_predictions_validate(self) -> None:
        for prediction in TOY_PREDICTIONS:
            validate_prediction(prediction)

    def test_05_clarify_case_cannot_route_capabilities(self) -> None:
        invalid = deepcopy(TOY_CASES[0])
        invalid["gold"]["dialogue_action"] = "CLARIFY"
        invalid["gold"]["rag_required"] = True
        with self.assertRaises(Stage0ContractError):
            validate_case(invalid)

    def test_06_clarify_prediction_cannot_route_capabilities(self) -> None:
        invalid = _prediction("X", rag=False, memory=True, planning=False, action="CLARIFY")
        with self.assertRaises(Stage0ContractError):
            validate_prediction(invalid)

    def test_07_invalid_provenance_is_rejected(self) -> None:
        invalid = deepcopy(TOY_CASES[0])
        invalid["provenance"]["type"] = "INVENTED_AUTHENTIC"
        with self.assertRaises(Stage0ContractError):
            validate_case(invalid)

    def test_08_dataset_registry_validates(self) -> None:
        validate_dataset_registry(ASSETS["dataset_registry"])

    def test_09_matrix_contains_all_eight_combinations(self) -> None:
        validate_scenario_matrix(ASSETS["scenario_matrix"])

    def test_10_matrix_duplicate_is_rejected(self) -> None:
        invalid = deepcopy(ASSETS["scenario_matrix"])
        invalid[-1]["combination_id"] = "000"
        with self.assertRaises(Stage0ContractError):
            validate_scenario_matrix(invalid)

    def test_11_clarification_contract_creates_no_cases(self) -> None:
        validate_clarification_contract(ASSETS["clarification_contract"])

    def test_12_contrast_pair_schema(self) -> None:
        for pair in TOY_CONTRASTS:
            validate_contrast_pair(pair)

    def test_13_no_existing_registry_asset_is_final_test_eligible(self) -> None:
        self.assertTrue(
            all(not entry["final_test_eligible"] for entry in ASSETS["dataset_registry"]["assets"])
        )

    def test_14_stage0_fixtures_are_dev_only_and_non_authentic(self) -> None:
        self.assertTrue(all(case["partition"] == "DEV" for case in TOY_CASES))
        self.assertTrue(all(case["governance"]["fixture_only"] for case in TOY_CASES))
        self.assertNotIn("AUTHENTIC", {case["provenance"]["type"] for case in TOY_CASES})


class LeakageGuardTests(unittest.TestCase):
    def test_15_clean_toy_fixtures_have_no_leakage(self) -> None:
        self.assertEqual(detect_case_leakage(TOY_CASES), [])

    def test_16_family_split_across_dev_test_is_rejected(self) -> None:
        extra = deepcopy(TOY_CASES[0])
        extra["case_id"] = "TOY-TEST-SAME-FAMILY"
        extra["utterance_id"] = "TOY-TEST-SAME-FAMILY-U1"
        extra["partition"] = "TEST"
        extra["provenance"]["prior_exposure_to_model_selection"] = False
        extra["governance"]["final_test_eligible"] = True
        extra["governance"]["fixture_only"] = False
        codes = {issue.code for issue in detect_case_leakage([*TOY_CASES, extra])}
        self.assertIn("SCENARIO_FAMILY_SPLIT_ACROSS_DEV_TEST", codes)

    def test_17_llm_augmentation_from_test_is_rejected(self) -> None:
        source = deepcopy(TOY_CASES[0])
        source["case_id"] = "TEST-SOURCE"
        source["scenario_family_id"] = "TEST-FAMILY"
        source["utterance_id"] = "TEST-SOURCE-U1"
        source["partition"] = "TEST"
        source["provenance"]["prior_exposure_to_model_selection"] = False
        source["governance"]["final_test_eligible"] = True
        source["governance"]["fixture_only"] = False
        augmented = deepcopy(TOY_CASES[1])
        augmented["case_id"] = "AUGMENTED-DEV"
        augmented["scenario_family_id"] = "AUGMENTED-FAMILY"
        augmented["utterance_id"] = "AUGMENTED-DEV-U1"
        augmented["provenance"] = {
            "type": "LLM_AUGMENTED",
            "source_asset_id": "FUTURE_DEV_AUGMENTATION",
            "prior_exposure_to_model_selection": True,
            "human_verified": True,
            "augmentation": {
                "source_family_id": "TEST-FAMILY",
                "source_partition": "DEV",
                "generator_model": "dummy",
                "generator_version": "dummy-v1",
                "generation_prompt_id": "dummy-prompt",
            },
        }
        codes = {issue.code for issue in detect_case_leakage([augmented, source])}
        self.assertIn("LLM_AUGMENTATION_DERIVED_FROM_TEST", codes)

    def test_18_gold_field_in_tuning_payload_is_rejected(self) -> None:
        issues = detect_tuning_leakage({"gold_thresholds": [0.4]}, TOY_CASES)
        self.assertIn("GOLD_FIELD_IN_TUNING_PAYLOAD", {issue.code for issue in issues})

    def test_19_test_case_id_in_tuning_payload_is_rejected(self) -> None:
        test_case = deepcopy(TOY_CASES[0])
        test_case["case_id"] = "TEST-ID"
        test_case["partition"] = "TEST"
        issues = detect_tuning_leakage({"selected_case_ids": ["TEST-ID"]}, [test_case])
        self.assertIn("TEST_CASE_REFERENCED_BY_TUNING", {issue.code for issue in issues})

    def test_20_legacy_pilot_in_test_is_rejected(self) -> None:
        pilot = deepcopy(TOY_CASES[0])
        pilot["case_id"] = "LEGACY-PILOT-TEST"
        pilot["partition"] = "TEST"
        pilot["provenance"]["source_asset_id"] = "RQ2_V1_AUTHENTIC_PILOT"
        pilot["provenance"]["prior_exposure_to_model_selection"] = False
        pilot["governance"]["final_test_eligible"] = True
        pilot["governance"]["fixture_only"] = False
        codes = {issue.code for issue in detect_case_leakage([pilot])}
        self.assertIn("EXPOSED_OR_INELIGIBLE_CASE_IN_TEST", codes)

    def test_21_obvious_duplicate_input_across_families_is_rejected(self) -> None:
        duplicate = deepcopy(TOY_CASES[0])
        duplicate["case_id"] = "DUPLICATE-CASE"
        duplicate["scenario_family_id"] = "OTHER-FAMILY"
        duplicate["utterance_id"] = "DUPLICATE-U1"
        codes = {issue.code for issue in detect_case_leakage([TOY_CASES[0], duplicate])}
        self.assertIn("OBVIOUS_DUPLICATE_INPUT_ACROSS_FAMILIES", codes)


class MetricTests(unittest.TestCase):
    def test_22_perfect_toy_predictions_score_one(self) -> None:
        result = evaluate_predictions(TOY_CASES, TOY_PREDICTIONS)
        self.assertEqual(result["macro_f1"], 1.0)
        self.assertEqual(result["micro_f1"], 1.0)
        self.assertEqual(result["exact_set_match"], 1.0)
        self.assertEqual(result["hamming_loss"], 0.0)

    def test_23_hand_computable_metric_example(self) -> None:
        cases = [
            _case("M1", rag=True, memory=False, planning=False),
            _case("M2", rag=False, memory=True, planning=False),
        ]
        predictions = [
            _prediction("M1", rag=True, memory=True, planning=False),
            _prediction("M2", rag=False, memory=False, planning=False),
        ]
        result = evaluate_predictions(cases, predictions)
        self.assertAlmostEqual(result["macro_f1"], 1 / 3)
        self.assertAlmostEqual(result["micro_f1"], 0.5)
        self.assertAlmostEqual(result["example_based_f1"], 1 / 3)
        self.assertAlmostEqual(result["jaccard_similarity"], 0.25)
        self.assertEqual(result["exact_set_match"], 0.0)
        self.assertAlmostEqual(result["hamming_loss"], 1 / 3)

    def test_24_under_and_over_routing_rates(self) -> None:
        cases = [
            _case("R1", rag=True, memory=False, planning=False),
            _case("R2", rag=False, memory=True, planning=False),
        ]
        predictions = [
            _prediction("R1", rag=True, memory=True, planning=False),
            _prediction("R2", rag=False, memory=False, planning=False),
        ]
        result = evaluate_predictions(cases, predictions)
        self.assertEqual(result["under_routing_rate"], 0.5)
        self.assertEqual(result["over_routing_rate"], 0.5)
        self.assertEqual(result["under_routing_assignment_rate"], 0.5)
        self.assertEqual(result["over_routing_assignment_rate"], 0.25)

    def test_25_empty_set_convention(self) -> None:
        case = _case("EMPTY", rag=False, memory=False, planning=False)
        prediction = _prediction("EMPTY", rag=False, memory=False, planning=False)
        result = evaluate_predictions([case], [prediction])
        self.assertEqual(result["example_based_f1"], 1.0)
        self.assertEqual(result["jaccard_similarity"], 1.0)
        self.assertEqual(result["exact_set_match"], 1.0)

    def test_26_answerability_is_separate(self) -> None:
        answer = _case("ANSWER", rag=False, memory=False, planning=False)
        clarify = _case("CLARIFY", rag=False, memory=False, planning=False)
        clarify["gold"]["dialogue_action"] = "CLARIFY"
        predictions = [
            _prediction("ANSWER", rag=False, memory=False, planning=False),
            _prediction("CLARIFY", rag=False, memory=False, planning=False, action="CLARIFY"),
        ]
        result = evaluate_predictions([answer, clarify], predictions)
        self.assertEqual(result["answerable_case_count"], 1)
        self.assertEqual(result["clarification_case_count"], 1)
        self.assertEqual(result["answerability_accuracy"], 1.0)

    def test_27_contrast_consistency_hook(self) -> None:
        result = evaluate_contrast_consistency(TOY_CASES, TOY_PREDICTIONS, TOY_CONTRASTS)
        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["consistency_rate"], 1.0)


class InterfaceAndDryRunTests(unittest.TestCase):
    def _assert_dummy(self, model_id: str) -> None:
        prediction = DummyRouter(model_id).predict(TOY_CASES[0]).to_dict()
        self.assertEqual(prediction["model_id"], model_id)
        self.assertEqual(prediction["metadata"]["provider_call_count"], 0)

    def test_28_b0_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-B0_RULE")

    def test_29_b1_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-B1_LEGACY_INTENT")

    def test_30_b2_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-B2_PROTOTYPE")

    def test_31_b3_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-B3_OVR")

    def test_32_b4_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-B4_LLM")

    def test_33_p1_interface_smoke(self) -> None:
        self._assert_dummy("R2V2-P1_HYBRID")

    def test_34_b1_refuses_unfrozen_mapping(self) -> None:
        labels = tuple(
            item["label"] for item in ASSETS["b1_legacy_contract"]["frozen_label_universe"]
        )
        router = LegacyIntentCascadeInterface(
            legacy_predictor=lambda _: labels[0],
            frozen_label_universe=labels,
            intent_to_capability_mapping=None,
            mapping_frozen=False,
        )
        with self.assertRaises(UnfrozenLegacyMappingError):
            router.predict(TOY_CASES[0])

    def test_35_no_paid_api_dry_run(self) -> None:
        report = run_no_paid_api_dry_run(TOY_CASES[0])
        self.assertEqual(report["model_ids"], list(MODEL_IDS))
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["network_access"])
        self.assertFalse(report["training_performed"])
        self.assertFalse(report["final_test_executed"])

    def test_36_full_stage0_validator(self) -> None:
        report = run_validation()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["check_count"], 15)
        self.assertEqual(report["pass_count"], 15)
        self.assertEqual(report["failure_count"], 0)

    def test_37_review_allowlist_excludes_governed_existing_assets(self) -> None:
        members = [path.relative_to(PACKAGE_ROOT.parents[1]).as_posix() for path in collect_review_files()]
        self.assertTrue(members)
        self.assertTrue(
            all(
                path.startswith("evaluation/capability_routing_rq2_v2_stage0/")
                or path.startswith("docs/thesis_mainline/rq2_v2/")
                for path in members
            )
        )
        forbidden_suffixes = {".npz", ".csv", ".xlsx", ".bin", ".safetensors"}
        self.assertFalse(any(any(path.endswith(suffix) for suffix in forbidden_suffixes) for path in members))


if __name__ == "__main__":
    unittest.main()

