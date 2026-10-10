"""Unit tests for the isolated RQ2-V2 Stage 1 Track B baselines."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.capability_routing_rq2_v2_stage0.contracts import (
    load_jsonl,
    validate_prediction,
)

from . import B0_MODEL_ID, PACKAGE_ROOT
from .b0_rule_router import B0RuleRouter
from .b1_legacy_intent_adapter import (
    B1LegacyIntentRouter,
    B1MappingError,
    IncompleteB1MappingError,
    STRICT_FINAL_INFERENCE,
    UNIT_TEST_TOY,
    UnfrozenB1MappingError,
    UnknownC0IntentError,
    frozen_c0_label_universe,
    validate_mapping_payload,
)
from .build_review_zip import build_review_zip, collect_review_files
from .runner import run_jsonl


TOY_CASES = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_cases_v1.jsonl")
TOY_BY_ID = {case["case_id"]: case for case in TOY_CASES}
TOY_MAPPING_PATH = PACKAGE_ROOT / "fixtures" / "toy_b1_mapping_v1.json"
UNFROZEN_MAPPING_PATH = (
    PACKAGE_ROOT / "config" / "b1_intent_to_capability_mapping_unfrozen_v1.json"
)


class B0RuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.router = B0RuleRouter()

    def _prediction(self, case_id: str) -> dict:
        return self.router.predict(TOY_BY_ID[case_id]).to_dict()

    def test_01_obvious_rag_request(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-RAG")
        self.assertTrue(prediction["rag_required"])
        self.assertFalse(prediction["memory_required"])
        self.assertFalse(prediction["planning_required"])

    def test_02_obvious_memory_request(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-MEMORY")
        self.assertFalse(prediction["rag_required"])
        self.assertTrue(prediction["memory_required"])
        self.assertFalse(prediction["planning_required"])

    def test_03_personal_information_visible_suppresses_long_term_memory(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-MEMORY-VISIBLE")
        self.assertFalse(prediction["memory_required"])
        self.assertIn(
            "B0_MEMORY_DETAIL_IN_VISIBLE_HISTORY",
            prediction["metadata"]["suppressed_rule_ids"],
        )

    def test_04_obvious_planning_request(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-PLANNING")
        self.assertFalse(prediction["rag_required"])
        self.assertFalse(prediction["memory_required"])
        self.assertTrue(prediction["planning_required"])

    def test_05_simultaneous_rag_and_planning(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-RAG-PLANNING")
        self.assertEqual(
            (prediction["rag_required"], prediction["memory_required"], prediction["planning_required"]),
            (True, False, True),
        )

    def test_06_simultaneous_memory_and_planning(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-MEMORY-PLANNING")
        self.assertEqual(
            (prediction["rag_required"], prediction["memory_required"], prediction["planning_required"]),
            (False, True, True),
        )

    def test_07_three_label_output(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-ALL-THREE")
        self.assertEqual(
            (prediction["rag_required"], prediction["memory_required"], prediction["planning_required"]),
            (True, True, True),
        )

    def test_08_supplied_course_content_suppresses_rag(self) -> None:
        prediction = self._prediction("TRACK-B-TOY-RAG-SUPPLIED")
        self.assertFalse(prediction["rag_required"])
        self.assertIn(
            "B0_RAG_CONTENT_ALREADY_PROVIDED",
            prediction["metadata"]["suppressed_rule_ids"],
        )

    def test_09_canonical_prediction_schema_compliance(self) -> None:
        for case in TOY_CASES:
            prediction = self.router.predict(case).to_dict()
            validate_prediction(prediction)
            self.assertEqual(prediction["model_id"], B0_MODEL_ID)
            self.assertEqual(
                prediction["metadata"]["model_visible_fields_used"],
                [
                    "current_query",
                    "current_page",
                    "dashboard_context",
                    "visible_conversation_history",
                ],
            )
            metadata_text = json.dumps(prediction["metadata"], sort_keys=True)
            self.assertNotIn("rag_context_state", metadata_text)
            self.assertNotIn("memory_context_state", metadata_text)

    def test_10_identical_input_is_deterministic(self) -> None:
        case = TOY_BY_ID["TRACK-B-TOY-ALL-THREE"]
        first = self.router.predict(case).to_dict()
        second = self.router.predict(deepcopy(case)).to_dict()
        self.assertEqual(first, second)

    def test_11_gold_values_do_not_affect_inference(self) -> None:
        case = deepcopy(TOY_BY_ID["TRACK-B-TOY-RAG"])
        changed_gold = deepcopy(case)
        changed_gold["gold"] = {
            "dialogue_action": "ANSWER",
            "rag_required": False,
            "memory_required": True,
            "planning_required": True,
        }
        self.assertEqual(
            self.router.predict(case).to_dict(),
            self.router.predict(changed_gold).to_dict(),
        )

    def test_12_rag_context_state_is_prediction_invariant(self) -> None:
        first = deepcopy(TOY_BY_ID["TRACK-B-TOY-RAG"])
        second = deepcopy(first)
        first["model_input"]["rag_context_state"] = "PROVIDED_IN_INPUT"
        second["model_input"]["rag_context_state"] = "RETRIEVAL_UNAVAILABLE"
        self.assertEqual(
            self.router.predict(first).to_dict(),
            self.router.predict(second).to_dict(),
        )

    def test_13_memory_context_state_is_prediction_invariant(self) -> None:
        first = deepcopy(TOY_BY_ID["TRACK-B-TOY-MEMORY"])
        second = deepcopy(first)
        first["model_input"]["memory_context_state"] = "LONG_TERM_MEMORY_AVAILABLE"
        second["model_input"]["memory_context_state"] = "LONG_TERM_MEMORY_UNAVAILABLE"
        self.assertEqual(
            self.router.predict(first).to_dict(),
            self.router.predict(second).to_dict(),
        )


class B1AdapterTests(unittest.TestCase):
    def _router(self, intent: str) -> B1LegacyIntentRouter:
        return B1LegacyIntentRouter(
            TOY_MAPPING_PATH,
            mapping_mode=UNIT_TEST_TOY,
            intent_predictor=lambda _visible: intent,
        )

    def test_12_adapter_accepts_valid_frozen_c0_intent(self) -> None:
        prediction = self._router("course_content_question").predict(
            TOY_BY_ID["TRACK-B-TOY-RAG"]
        ).to_dict()
        validate_prediction(prediction)
        self.assertEqual(prediction["metadata"]["legacy_intent"], "course_content_question")
        self.assertTrue(prediction["rag_required"])

    def test_13_unsupported_or_unknown_intent_is_rejected(self) -> None:
        for intent in ("memory_state_query", "ambiguous", "invented_intent"):
            with self.subTest(intent=intent):
                with self.assertRaises(UnknownC0IntentError):
                    self._router(intent).predict(TOY_BY_ID["TRACK-B-TOY-RAG"])

    def test_14_unfrozen_final_mapping_is_rejected_in_strict_mode(self) -> None:
        with self.assertRaises(UnfrozenB1MappingError):
            B1LegacyIntentRouter(
                UNFROZEN_MAPPING_PATH,
                mapping_mode=STRICT_FINAL_INFERENCE,
                intent_predictor=lambda _visible: "course_content_question",
            )

    def test_15_incomplete_final_mapping_is_rejected(self) -> None:
        payload = json.loads(TOY_MAPPING_PATH.read_text(encoding="utf-8"))
        payload["mapping_id"] = "TEST-INCOMPLETE-STRICT"
        payload["mapping_scope"] = "DEVELOPMENT_REVIEWED"
        payload["mapping_status"] = "FROZEN_DEVELOPMENT_ONLY"
        payload["development_data_review_complete"] = True
        payload["final_test_accessed_for_mapping"] = False
        payload["mappings"] = payload["mappings"][:-1]
        for entry in payload["mappings"]:
            entry["mapping_status"] = "FROZEN_DEVELOPMENT_ONLY"
        with self.assertRaises(IncompleteB1MappingError):
            validate_mapping_payload(payload, mode=STRICT_FINAL_INFERENCE)

    def test_16_unfrozen_template_lists_exact_actual_16_labels(self) -> None:
        payload = json.loads(UNFROZEN_MAPPING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["mapping_status"], "UNFROZEN")
        entries = payload["mappings"]
        self.assertEqual(
            {entry["intent_id"] for entry in entries},
            set(frozen_c0_label_universe()),
        )
        self.assertEqual(len(entries), 16)
        self.assertTrue(
            all(
                entry[field] is None
                for entry in entries
                for field in ("proposed_rag", "proposed_memory", "proposed_planning")
            )
        )

    def test_17_strict_mapping_requires_explicit_inference_authorization(self) -> None:
        payload = json.loads(TOY_MAPPING_PATH.read_text(encoding="utf-8"))
        payload["mapping_id"] = "TEST-COMPLETE-BUT-NOT-AUTHORIZED"
        payload["mapping_scope"] = "DEVELOPMENT_REVIEWED"
        payload["mapping_status"] = "FROZEN_DEVELOPMENT_ONLY"
        payload["development_data_review_complete"] = True
        payload["final_test_accessed_for_mapping"] = False
        payload["final_inference_authorized"] = False
        for entry in payload["mappings"]:
            entry["mapping_status"] = "FROZEN_DEVELOPMENT_ONLY"
        with self.assertRaises(B1MappingError):
            validate_mapping_payload(payload, mode=STRICT_FINAL_INFERENCE)

    def test_18_b1_predictor_receives_only_visible_c0_input(self) -> None:
        observed = []

        def predictor(visible):
            observed.append(visible)
            self.assertFalse(hasattr(visible, "gold"))
            self.assertEqual(visible.current_query, "Explain the Week 5 claim-evidence framework.")
            self.assertEqual(visible.current_page, "Lecture")
            return "course_content_question"

        router = B1LegacyIntentRouter(
            TOY_MAPPING_PATH,
            mapping_mode=UNIT_TEST_TOY,
            intent_predictor=predictor,
        )
        router.predict(TOY_BY_ID["TRACK-B-TOY-RAG"])
        self.assertEqual(len(observed), 1)

    def test_19_b1_is_deterministic_for_identical_input(self) -> None:
        router = self._router("planning_or_strategy")
        case = TOY_BY_ID["TRACK-B-TOY-PLANNING"]
        self.assertEqual(router.predict(case).to_dict(), router.predict(case).to_dict())


class RunnerTests(unittest.TestCase):
    def test_20_b0_runner_writes_canonical_prediction_jsonl(self) -> None:
        source = PACKAGE_ROOT / "fixtures" / "toy_cases_v1.jsonl"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "predictions.jsonl"
            report = run_jsonl(source, output, model_id=B0_MODEL_ID)
            predictions = load_jsonl(output)
        self.assertEqual(report["prediction_count"], len(TOY_CASES))
        self.assertEqual(len(predictions), len(TOY_CASES))
        for prediction in predictions:
            validate_prediction(prediction)

    def test_21_runner_refuses_to_overwrite_output(self) -> None:
        source = PACKAGE_ROOT / "fixtures" / "toy_cases_v1.jsonl"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "predictions.jsonl"
            output.write_text("existing\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_jsonl(source, output, model_id=B0_MODEL_ID)


class ReviewPackageTests(unittest.TestCase):
    def test_22_review_allowlist_is_track_b_only(self) -> None:
        files = collect_review_files()
        self.assertTrue(files)
        self.assertTrue(all(PACKAGE_ROOT in path.parents for path in files))
        self.assertFalse(
            any(path.suffix in {".npz", ".csv", ".xlsx", ".bin", ".safetensors"} for path in files)
        )

    def test_23_review_zip_manifest_preserves_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review.zip"
            report = build_review_zip(output)
            from zipfile import ZipFile

            with ZipFile(output) as archive:
                names = archive.namelist()
                manifest_name = next(name for name in names if name.endswith("/REVIEW_MANIFEST.json"))
                manifest = json.loads(archive.read(manifest_name))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(manifest["scope"], "RQ2_V2_STAGE_1_TRACK_B_R1_B0_B1_ONLY")
        self.assertEqual(
            manifest["b0_predictive_fields"],
            [
                "current_query",
                "current_page",
                "dashboard_context",
                "visible_conversation_history",
            ],
        )
        self.assertFalse(manifest["b0_privileged_context_states_used"])
        self.assertEqual(manifest["b1_mapping_status"], "UNFROZEN")
        self.assertFalse(manifest["contains_raw_restricted_student_data"])
        self.assertFalse(manifest["contains_large_model_weights"])
        self.assertFalse(manifest["contains_frozen_c0_index_or_embeddings"])


if __name__ == "__main__":
    unittest.main()
