"""Unit tests for the offline RQ2-V2 Stage 1D B4/P1 harnesses."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from .b4 import (
    B4OfflineHarness,
    B4ResponseParseError,
    FEW_SHOT_PLACEHOLDER,
    OfflineProviderRequiredError,
    PRIMARY_SEMANTIC_INPUT_FIELDS,
    PRIMARY_SEMANTIC_INPUT_PROFILE,
    PromptInputError,
    build_b4_prompt,
    extract_primary_semantic_input,
    parse_b4_response,
)
from .mock_provider import DeterministicMockProvider
from .p1 import P1HybridRouter


PACKAGE_ROOT = Path(__file__).resolve().parent
FIXTURE = json.loads(
    (PACKAGE_ROOT / "fixtures" / "toy_b4_fixture_v1.json").read_text(
        encoding="utf-8"
    )
)
MODEL_INPUT = FIXTURE["model_input"]
VALID_RESPONSE = FIXTURE["mock_responses"]["valid"]
CAPABILITIES = ("rag_required", "memory_required", "planning_required")


def _thresholds(value: float = 0.5) -> dict[str, float]:
    return {field: value for field in CAPABILITIES}


def _margins(value: float = 0.05) -> dict[str, float]:
    return {field: value for field in CAPABILITIES}


def _confident_probabilities() -> dict[str, float]:
    return {
        "rag_required": 0.9,
        "memory_required": 0.1,
        "planning_required": 0.9,
    }


class PromptAndParserTests(unittest.TestCase):
    def test_01_prompt_contains_required_task_definitions_and_fields(self) -> None:
        prompt = build_b4_prompt(MODEL_INPUT)
        semantic_input = extract_primary_semantic_input(MODEL_INPUT)
        self.assertEqual(
            tuple(semantic_input),
            PRIMARY_SEMANTIC_INPUT_FIELDS,
        )
        self.assertEqual(
            build_b4_prompt(semantic_input),
            prompt,
        )
        self.assertIn("Route one DUTE educational-chatbot turn", prompt)
        self.assertIn("Long-term Memory", prompt)
        self.assertIn("Visible conversation history", prompt)
        self.assertIn("Planning", prompt)
        self.assertIn(FEW_SHOT_PLACEHOLDER, prompt)
        for field in (
            "current_query",
            "current_page",
            "dashboard_context",
            "visible_conversation_history",
        ):
            self.assertIn(field, prompt)
        self.assertNotIn("rag_context_state", prompt)
        self.assertNotIn("memory_context_state", prompt)
        self.assertIn("Return exactly one JSON object and no prose", prompt)

    def test_02_hidden_gold_and_unknown_fields_cannot_enter_prompt(self) -> None:
        prompt = build_b4_prompt(MODEL_INPUT)
        self.assertNotIn("gold", prompt.casefold())
        self.assertNotIn("proposed_label", prompt.casefold())
        hidden = deepcopy(MODEL_INPUT)
        hidden["gold"] = {"rag_required": False}
        with self.assertRaises(PromptInputError):
            build_b4_prompt(hidden)

    def test_03_valid_b4_json_parses(self) -> None:
        parsed = parse_b4_response(VALID_RESPONSE)
        self.assertEqual(
            parsed.capabilities(),
            {
                "rag_required": True,
                "memory_required": False,
                "planning_required": True,
            },
        )

    def test_04_optional_short_reason_code_parses(self) -> None:
        self.assertEqual(parse_b4_response(VALID_RESPONSE).reason_code, "TOY_RAG_PLAN")

    def test_05_invalid_json_is_rejected(self) -> None:
        with self.assertRaises(B4ResponseParseError) as context:
            parse_b4_response(FIXTURE["mock_responses"]["invalid_json"])
        self.assertEqual(context.exception.code, "INVALID_JSON")

    def test_06_missing_field_is_rejected(self) -> None:
        with self.assertRaises(B4ResponseParseError) as context:
            parse_b4_response(FIXTURE["mock_responses"]["missing_field"])
        self.assertEqual(context.exception.code, "MISSING_REQUIRED_FIELD")

    def test_07_invalid_boolean_types_are_rejected_without_coercion(self) -> None:
        invalid_values = (
            FIXTURE["mock_responses"]["invalid_type"],
            '{"rag_required":1,"memory_required":false,"planning_required":true}',
        )
        for response in invalid_values:
            with self.subTest(response=response):
                with self.assertRaises(B4ResponseParseError) as context:
                    parse_b4_response(response)
                self.assertEqual(context.exception.code, "INVALID_BOOLEAN_TYPE")

    def test_08_unknown_capability_or_response_field_is_rejected(self) -> None:
        response = (
            '{"rag_required":true,"memory_required":false,'
            '"planning_required":true,"tool_required":true}'
        )
        with self.assertRaises(B4ResponseParseError) as context:
            parse_b4_response(response)
        self.assertEqual(context.exception.code, "UNKNOWN_RESPONSE_FIELD")

    def test_09_extra_text_is_rejected_conservatively(self) -> None:
        with self.assertRaises(B4ResponseParseError) as context:
            parse_b4_response(VALID_RESPONSE + " trailing explanation")
        self.assertEqual(context.exception.code, "EXTRA_TEXT")

    def test_10_duplicate_fields_are_rejected(self) -> None:
        response = (
            '{"rag_required":true,"rag_required":false,'
            '"memory_required":false,"planning_required":true}'
        )
        with self.assertRaises(B4ResponseParseError) as context:
            parse_b4_response(response)
        self.assertEqual(context.exception.code, "DUPLICATE_FIELD")

    def test_25_context_state_changes_do_not_change_rendered_prompt(self) -> None:
        baseline_prompt = build_b4_prompt(MODEL_INPUT)
        variants = {
            "rag_context_state": "PROVIDED_IN_INPUT",
            "memory_context_state": "LONG_TERM_MEMORY_AVAILABLE",
        }
        for field, replacement in variants.items():
            with self.subTest(field=field):
                variant = deepcopy(MODEL_INPUT)
                variant[field] = replacement
                changed = {
                    key for key in MODEL_INPUT if MODEL_INPUT[key] != variant[key]
                }
                self.assertEqual(changed, {field})
                self.assertEqual(build_b4_prompt(variant), baseline_prompt)


class MockAndB4Tests(unittest.TestCase):
    def test_11_mock_returns_configured_responses_deterministically(self) -> None:
        provider = DeterministicMockProvider(("first", "second"))
        self.assertEqual(provider.complete("prompt-1"), "first")
        self.assertEqual(provider.complete("prompt-2"), "second")
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(provider.received_prompts, ("prompt-1", "prompt-2"))

    def test_12_mock_supports_configured_invalid_response(self) -> None:
        provider = DeterministicMockProvider(FIXTURE["mock_responses"]["invalid_json"])
        router = B4OfflineHarness(provider)
        with self.assertRaises(B4ResponseParseError):
            router.predict(case_id="INVALID-MOCK", model_input=MODEL_INPUT)
        self.assertEqual(provider.call_count, 1)

    def test_13_b4_produces_canonical_prediction(self) -> None:
        provider = DeterministicMockProvider(VALID_RESPONSE)
        prediction = B4OfflineHarness(provider).predict(
            case_id="B4-CANONICAL", model_input=MODEL_INPUT
        ).to_dict()
        self.assertEqual(prediction["model_id"], "R2V2-B4_LLM")
        self.assertTrue(prediction["rag_required"])
        self.assertFalse(prediction["memory_required"])
        self.assertTrue(prediction["planning_required"])
        self.assertEqual(prediction["metadata"]["provider_call_count"], 1)

    def test_14_b4_rejects_any_non_mock_provider(self) -> None:
        class NonMockProvider:
            offline_only = True
            provider_name = "NOT_THE_AUTHORISED_MOCK"
            call_count = 0
            network_call_count = 0
            real_provider_call_count = 0

            def complete(self, prompt: str) -> str:
                return VALID_RESPONSE

        with self.assertRaises(OfflineProviderRequiredError):
            B4OfflineHarness(NonMockProvider())

    def test_26_context_state_changes_do_not_change_mock_prediction(self) -> None:
        variants = {
            "rag_context_state": "PROVIDED_IN_INPUT",
            "memory_context_state": "LONG_TERM_MEMORY_AVAILABLE",
        }
        for field, replacement in variants.items():
            with self.subTest(field=field):
                variant = deepcopy(MODEL_INPUT)
                variant[field] = replacement
                outputs = []
                prompts = []
                for model_input in (MODEL_INPUT, variant):
                    provider = DeterministicMockProvider(VALID_RESPONSE)
                    outputs.append(
                        B4OfflineHarness(provider).predict(
                            case_id="B4-STATE-INVARIANCE",
                            model_input=model_input,
                        ).to_dict()
                    )
                    prompts.append(provider.received_prompts)
                self.assertEqual(prompts[0], prompts[1])
                self.assertEqual(outputs[0], outputs[1])
                prediction_text = json.dumps(outputs[0], sort_keys=True)
                self.assertNotIn("rag_context_state", prediction_text)
                self.assertNotIn("memory_context_state", prediction_text)


class HybridTests(unittest.TestCase):
    def _hybrid(self) -> tuple[P1HybridRouter, DeterministicMockProvider]:
        provider = DeterministicMockProvider(VALID_RESPONSE)
        return P1HybridRouter(B4OfflineHarness(provider)), provider

    def test_15_confident_path_makes_zero_provider_calls(self) -> None:
        router, provider = self._hybrid()
        prediction = router.predict(
            case_id="P1-CONFIDENT",
            model_input=MODEL_INPUT,
            base_probabilities=_confident_probabilities(),
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
        ).to_dict()
        self.assertFalse(prediction["metadata"]["fallback_triggered"])
        self.assertEqual(prediction["metadata"]["routing_source"], "DIRECT_BASE_ROUTE")
        self.assertEqual(prediction["metadata"]["provider_call_count"], 0)
        self.assertEqual(provider.call_count, 0)

    def test_16_uncertain_probability_triggers_fallback(self) -> None:
        router, provider = self._hybrid()
        probabilities = _confident_probabilities()
        probabilities["rag_required"] = 0.51
        prediction = router.predict(
            case_id="P1-MARGIN",
            model_input=MODEL_INPUT,
            base_probabilities=probabilities,
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
        ).to_dict()
        self.assertTrue(prediction["metadata"]["fallback_triggered"])
        self.assertIn(
            "THRESHOLD_MARGIN:rag_required",
            prediction["metadata"]["fallback_reasons"],
        )
        self.assertEqual(provider.call_count, 1)

    def test_17_disagreement_triggers_fallback(self) -> None:
        router, provider = self._hybrid()
        prediction = router.predict(
            case_id="P1-DISAGREEMENT",
            model_input=MODEL_INPUT,
            base_probabilities=_confident_probabilities(),
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
            secondary_disagreement_flags={"memory_required": True},
        ).to_dict()
        self.assertIn(
            "SECONDARY_DISAGREEMENT:memory_required",
            prediction["metadata"]["fallback_reasons"],
        )
        self.assertEqual(provider.call_count, 1)

    def test_18_ood_flag_triggers_fallback(self) -> None:
        router, provider = self._hybrid()
        prediction = router.predict(
            case_id="P1-OOD",
            model_input=MODEL_INPUT,
            base_probabilities=_confident_probabilities(),
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
            low_confidence_or_ood=True,
        ).to_dict()
        self.assertIn("LOW_CONFIDENCE_OR_OOD", prediction["metadata"]["fallback_reasons"])
        self.assertEqual(provider.call_count, 1)

    def test_19_multiple_uncertainty_reasons_are_recorded(self) -> None:
        router, _ = self._hybrid()
        probabilities = _confident_probabilities()
        probabilities["rag_required"] = 0.51
        prediction = router.predict(
            case_id="P1-MULTIPLE",
            model_input=MODEL_INPUT,
            base_probabilities=probabilities,
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
            secondary_disagreement_flags={"memory_required": True},
            low_confidence_or_ood=True,
        ).to_dict()
        self.assertEqual(
            prediction["metadata"]["fallback_reasons"],
            [
                "THRESHOLD_MARGIN:rag_required",
                "SECONDARY_DISAGREEMENT:memory_required",
                "LOW_CONFIDENCE_OR_OOD",
            ],
        )

    def test_20_invalid_intermediate_state_triggers_fallback(self) -> None:
        router, provider = self._hybrid()
        invalid = _confident_probabilities()
        del invalid["planning_required"]
        prediction = router.predict(
            case_id="P1-INVALID-BASE",
            model_input=MODEL_INPUT,
            base_probabilities=invalid,
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
        ).to_dict()
        self.assertIn(
            "INVALID_OR_CONFLICTING_INTERMEDIATE_STATE",
            prediction["metadata"]["fallback_reasons"],
        )
        self.assertEqual(provider.call_count, 1)

    def test_21_fallback_produces_canonical_p1_prediction(self) -> None:
        router, _ = self._hybrid()
        prediction = router.predict(
            case_id="P1-CANONICAL",
            model_input=MODEL_INPUT,
            base_probabilities=_confident_probabilities(),
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
            low_confidence_or_ood=True,
        ).to_dict()
        self.assertEqual(prediction["model_id"], "R2V2-P1_HYBRID")
        self.assertEqual(prediction["metadata"]["routing_source"], "LLM_FALLBACK")
        self.assertEqual(prediction["metadata"]["final_prediction_source"], "R2V2-B4_LLM")
        self.assertEqual(
            [prediction[field] for field in CAPABILITIES], [True, False, True]
        )

    def test_22_identical_configuration_is_deterministic(self) -> None:
        outputs = []
        for _ in range(2):
            router, _provider = self._hybrid()
            outputs.append(
                router.predict(
                    case_id="P1-DETERMINISTIC",
                    model_input=MODEL_INPUT,
                    base_probabilities=_confident_probabilities(),
                    thresholds=_thresholds(),
                    uncertainty_margins=_margins(),
                    low_confidence_or_ood=True,
                ).to_dict()
            )
        self.assertEqual(outputs[0], outputs[1])

    def test_23_total_real_external_provider_calls_remain_zero(self) -> None:
        router, provider = self._hybrid()
        with patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network access is forbidden"),
        ) as network_call:
            router.predict(
                case_id="P1-ZERO-EXTERNAL",
                model_input=MODEL_INPUT,
                base_probabilities=_confident_probabilities(),
                thresholds=_thresholds(),
                uncertainty_margins=_margins(),
                low_confidence_or_ood=True,
            ).to_dict()
        network_call.assert_not_called()
        self.assertEqual(provider.network_call_count, 0)
        self.assertEqual(provider.real_provider_call_count, 0)

    def test_24_diagnostics_do_not_fabricate_cost_or_latency(self) -> None:
        router, _ = self._hybrid()
        prediction = router.predict(
            case_id="P1-DIAGNOSTICS",
            model_input=MODEL_INPUT,
            base_probabilities=_confident_probabilities(),
            thresholds=_thresholds(),
            uncertainty_margins=_margins(),
        ).to_dict()
        metadata = prediction["metadata"]
        self.assertEqual(metadata["base_probabilities"], _confident_probabilities())
        self.assertEqual(metadata["thresholds"], _thresholds())
        self.assertIsNone(metadata["token_count"])
        self.assertIsNone(metadata["estimated_cost"])
        self.assertIsNone(metadata["latency"])

    def test_27_p1_passes_only_primary_semantic_fields_to_b4(self) -> None:
        provider = DeterministicMockProvider(VALID_RESPONSE)
        b4 = B4OfflineHarness(provider)
        router = P1HybridRouter(b4)
        with patch.object(b4, "predict", wraps=b4.predict) as fallback_call:
            prediction = router.predict(
                case_id="P1-FOUR-FIELD-HANDOFF",
                model_input=MODEL_INPUT,
                base_probabilities=_confident_probabilities(),
                thresholds=_thresholds(),
                uncertainty_margins=_margins(),
                low_confidence_or_ood=True,
            ).to_dict()
        forwarded = fallback_call.call_args.kwargs["model_input"]
        self.assertEqual(tuple(forwarded), PRIMARY_SEMANTIC_INPUT_FIELDS)
        self.assertEqual(
            prediction["metadata"]["input_profile"],
            PRIMARY_SEMANTIC_INPUT_PROFILE,
        )
        prediction_text = json.dumps(prediction, sort_keys=True)
        self.assertNotIn("rag_context_state", prediction_text)
        self.assertNotIn("memory_context_state", prediction_text)


if __name__ == "__main__":
    unittest.main()
