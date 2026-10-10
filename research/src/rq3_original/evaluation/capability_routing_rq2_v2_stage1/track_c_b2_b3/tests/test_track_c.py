"""Unit tests for R2V2-B2_PROTOTYPE and R2V2-B3_OVR."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest

import numpy as np

from ..canonical_text import PRIMARY_FEATURE_PROFILE, serialize_canonical_text
from ..development import (
    LEARNING_CURVE_SAMPLING_METHOD,
    assert_family_never_crosses_folds,
    compare_core_and_synthetic_augmentation,
    evaluate_with_stage0_metrics,
    grouped_cross_validation_splits,
    run_learning_curve,
    search_per_label_thresholds,
)
from ..embeddings import FrozenMpnetEmbeddingAdapter, validated_encode
from ..errors import (
    CanonicalInputError,
    DegenerateLabelError,
    DevelopmentDataError,
    EmbeddingAdapterError,
)
from ..ovr_router import OvRLogisticRouter
from ..prototype_router import PrototypeRouter


CAPABILITIES = ("rag_required", "memory_required", "planning_required")


class ToyEmbeddingAdapter:
    model_id = "toy-sign-embedding-v1"
    dimension = 3

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _vector(query: str) -> np.ndarray:
        if query == "AXIS_RAG":
            return np.asarray([1.0, 0.0, 0.0], dtype=np.float64)
        match = re.fullmatch(r"VECTOR_([01]{3})", query)
        if not match:
            raise ValueError(f"unknown toy query: {query}")
        return np.asarray(
            [1.0 if value == "1" else -1.0 for value in match.group(1)],
            dtype=np.float64,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls.append(tuple(texts))
        vectors = []
        for text in texts:
            match = re.search(r"\[CURRENT_QUERY\]\n([^\n]+)", text)
            if not match:
                raise ValueError("canonical query marker missing")
            vectors.append(self._vector(match.group(1)))
        return np.vstack(vectors)


class WrongDimensionAdapter(ToyEmbeddingAdapter):
    dimension = 4


def _case(
    bits: str,
    *,
    prefix: str = "TRAIN",
    utterance: int = 1,
    partition: str = "DEV",
    provenance_type: str | None = None,
) -> dict:
    labels = {
        label: bits[position] == "1" for position, label in enumerate(CAPABILITIES)
    }
    value = {
        "case_id": f"{prefix}-{bits}-U{utterance}",
        "scenario_family_id": f"{prefix}-F-{bits}",
        "partition": partition,
        "model_input": {
            "current_query": f"VECTOR_{bits}",
            "current_page": "Overview",
            "dashboard_context": "Toy dashboard context.",
            "visible_conversation_history": [],
            "rag_context_state": "UNKNOWN",
            "memory_context_state": "VISIBLE_HISTORY_ONLY",
        },
        "development_labels": {"dialogue_action": "ANSWER", **labels},
    }
    if provenance_type is not None:
        value["provenance"] = {"type": provenance_type}
    return value


def _training_cases(*, prefix: str = "TRAIN", two_per_family: bool = False) -> list[dict]:
    utterances = (1, 2) if two_per_family else (1,)
    return [
        _case(f"{value:03b}", prefix=prefix, utterance=utterance)
        for value in range(8)
        for utterance in utterances
    ]


def _inference_case(query: str, *, case_id: str = "INFERENCE") -> dict:
    return {"case_id": case_id, "model_input": {"current_query": query}}


def _context_state_variants() -> list[dict]:
    base = {
        "case_id": "CONTEXT-BASE",
        "model_input": {
            "current_query": "VECTOR_101",
            "current_page": "Resources",
            "dashboard_context": "The same visible dashboard evidence.",
            "visible_conversation_history": [
                {"role": "user", "content": "Keep this visible turn fixed."},
                {"role": "assistant", "content": "This turn is also fixed."},
            ],
            "rag_context_state": "PROVIDED_IN_INPUT",
            "memory_context_state": "VISIBLE_HISTORY_ONLY",
        },
    }
    rag_variant = deepcopy(base)
    rag_variant["case_id"] = "CONTEXT-RAG-VARIANT"
    rag_variant["model_input"]["rag_context_state"] = "RETRIEVAL_UNAVAILABLE"
    memory_variant = deepcopy(base)
    memory_variant["case_id"] = "CONTEXT-MEMORY-VARIANT"
    memory_variant["model_input"][
        "memory_context_state"
    ] = "LONG_TERM_MEMORY_UNAVAILABLE"
    return [base, rag_variant, memory_variant]


def _lexically_correlated_family_cases() -> list[dict]:
    cases: list[dict] = []
    for value in range(8):
        bits = f"{value:03b}"
        for replicate in range(4):
            family_id = f"LEX-F-{bits}-{replicate:02d}"
            for utterance in (1, 2):
                case = _case(bits, prefix="LEX", utterance=utterance)
                case["case_id"] = f"LEX-{bits}-{replicate:02d}-U{utterance}"
                case["scenario_family_id"] = family_id
                cases.append(case)
    return cases


class CanonicalSerializerTests(unittest.TestCase):
    def test_01_deterministic_canonical_text_serialization(self) -> None:
        case = {
            "model_input": {
                "current_query": "  Make   a plan.  ",
                "current_page": "Debate",
                "dashboard_context": " Activity  fell.\r\n\r\n Use evidence. ",
                "visible_conversation_history": [
                    {"role": "user", "content": " My target is 70%. "},
                    {"role": "assistant", "content": "Noted."},
                ],
                "rag_context_state": "RETRIEVAL_AVAILABLE",
                "memory_context_state": "VISIBLE_HISTORY_ONLY",
            }
        }
        first = serialize_canonical_text(case)
        second = serialize_canonical_text(deepcopy(case))
        self.assertEqual(first, second)
        self.assertIn("[CURRENT_QUERY]\nMake a plan.", first)
        self.assertIn("[TURN_001_USER]\nMy target is 70%.", first)

    def test_02_hidden_gold_and_rationale_are_not_serialized(self) -> None:
        case = {
            "model_input": {"current_query": "Visible query"},
            "gold": {"hidden_note": "HIDDEN_GOLD_SENTINEL"},
            "proposed_capability_labels": "HIDDEN_LABEL_SENTINEL",
            "design_rationale": "HIDDEN_RATIONALE_SENTINEL",
        }
        text = serialize_canonical_text(case)
        self.assertEqual(text, "[CURRENT_QUERY]\nVisible query")
        self.assertNotIn("HIDDEN_", text)

    def test_03_absent_sections_are_omitted(self) -> None:
        text = serialize_canonical_text(
            {
                "model_input": {
                    "current_query": "Visible",
                    "dashboard_context": "   ",
                    "visible_conversation_history": [],
                }
            }
        )
        self.assertNotIn("DASHBOARD_CONTEXT", text)
        self.assertNotIn("CONVERSATION_HISTORY", text)

    def test_04_noncanonical_model_input_field_is_rejected(self) -> None:
        with self.assertRaises(CanonicalInputError):
            serialize_canonical_text(
                {
                    "model_input": {
                        "current_query": "Visible",
                        "gold_capability": "RAG",
                    }
                }
            )

    def test_28_context_state_metadata_is_not_serialized(self) -> None:
        texts = [serialize_canonical_text(case) for case in _context_state_variants()]
        self.assertEqual(texts, [texts[0]] * len(texts))
        self.assertNotIn("RAG_CONTEXT_STATE", texts[0])
        self.assertNotIn("MEMORY_CONTEXT_STATE", texts[0])
        self.assertNotIn("PROVIDED_IN_INPUT", texts[0])
        self.assertNotIn("VISIBLE_HISTORY_ONLY", texts[0])


class PrototypeRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ToyEmbeddingAdapter()
        self.cases = _training_cases()

    def test_05_positive_prototype_calculation(self) -> None:
        router = PrototypeRouter(self.adapter).fit(self.cases)
        np.testing.assert_allclose(
            router.positive_prototypes["rag_required"], [1.0, 0.0, 0.0]
        )

    def test_06_negative_prototype_calculation(self) -> None:
        router = PrototypeRouter(self.adapter).fit(self.cases)
        np.testing.assert_allclose(
            router.negative_prototypes["rag_required"], [-1.0, 0.0, 0.0]
        )

    def test_07_positive_minus_negative_score(self) -> None:
        router = PrototypeRouter(self.adapter).fit(self.cases)
        scores = router.predict_scores(_inference_case("AXIS_RAG"))
        self.assertAlmostEqual(scores["rag_required"], 2.0)
        self.assertAlmostEqual(scores["memory_required"], 0.0)
        self.assertAlmostEqual(scores["planning_required"], 0.0)

    def test_08_independent_threshold_behaviour(self) -> None:
        router = PrototypeRouter(
            self.adapter,
            thresholds={
                "rag_required": 1.0,
                "memory_required": 1.2,
                "planning_required": -1.2,
            },
        ).fit(self.cases)
        prediction = router.predict(_inference_case("VECTOR_110"))
        self.assertTrue(prediction["rag_required"])
        self.assertFalse(prediction["memory_required"])
        self.assertTrue(prediction["planning_required"])

    def test_09_simultaneous_multilabel_prediction(self) -> None:
        prediction = PrototypeRouter(self.adapter).fit(self.cases).predict(
            _inference_case("VECTOR_110")
        )
        self.assertTrue(prediction["rag_required"])
        self.assertTrue(prediction["memory_required"])
        self.assertFalse(prediction["planning_required"])

    def test_10_degenerate_label_detection(self) -> None:
        degenerate = deepcopy(self.cases)
        for case in degenerate:
            case["development_labels"]["rag_required"] = True
        with self.assertRaisesRegex(DegenerateLabelError, "rag_required"):
            PrototypeRouter(self.adapter).fit(degenerate)

    def test_11_prototype_save_load_reproducibility(self) -> None:
        router = PrototypeRouter(self.adapter).fit(self.cases)
        inference = _inference_case("VECTOR_101")
        before = router.predict_scores(inference)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "b2_state.json"
            router.save(state_path)
            loaded = PrototypeRouter.load(state_path, self.adapter)
            after = loaded.predict_scores(inference)
        self.assertEqual(before, after)

    def test_29_context_state_metadata_does_not_change_b2_output(self) -> None:
        router = PrototypeRouter(self.adapter).fit(self.cases)
        variants = _context_state_variants()
        scores = router.predict_scores(variants)
        self.assertEqual(scores, [scores[0]] * len(scores))
        predictions = router.predict(variants)
        for prediction in predictions:
            self.assertEqual(
                prediction["metadata"]["primary_feature_profile"],
                PRIMARY_FEATURE_PROFILE,
            )
            self.assertEqual(
                prediction["metadata"]["prototype_scores"], scores[0]
            )
        without_case_ids = [
            {key: value for key, value in prediction.items() if key != "case_id"}
            for prediction in predictions
        ]
        self.assertEqual(without_case_ids, [without_case_ids[0]] * len(without_case_ids))


class OvRRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = _training_cases()

    def test_12_ovr_fit_and_prediction(self) -> None:
        router = OvRLogisticRouter(ToyEmbeddingAdapter()).fit(self.cases)
        prediction = router.predict(_inference_case("VECTOR_110"))
        self.assertTrue(prediction["rag_required"])
        self.assertTrue(prediction["memory_required"])
        self.assertFalse(prediction["planning_required"])

    def test_13_per_label_positive_probabilities(self) -> None:
        router = OvRLogisticRouter(ToyEmbeddingAdapter()).fit(self.cases)
        probabilities = router.predict_proba(_inference_case("VECTOR_101"))
        self.assertEqual(set(probabilities), set(CAPABILITIES))
        self.assertGreater(probabilities["rag_required"], 0.5)
        self.assertLess(probabilities["memory_required"], 0.5)
        self.assertGreater(probabilities["planning_required"], 0.5)

    def test_14_ovr_independent_probability_thresholds(self) -> None:
        adapter = ToyEmbeddingAdapter()
        base = OvRLogisticRouter(adapter).fit(self.cases)
        values = base.predict_proba(_inference_case("VECTOR_110"))
        router = OvRLogisticRouter(
            ToyEmbeddingAdapter(),
            thresholds={
                "rag_required": values["rag_required"] - 0.01,
                "memory_required": values["memory_required"] + 0.01,
                "planning_required": 0.0,
            },
        ).fit(self.cases)
        prediction = router.predict(_inference_case("VECTOR_110"))
        self.assertTrue(prediction["rag_required"])
        self.assertFalse(prediction["memory_required"])
        self.assertTrue(prediction["planning_required"])

    def test_15_ovr_save_load_reproducibility(self) -> None:
        adapter = ToyEmbeddingAdapter()
        router = OvRLogisticRouter(adapter, class_weight={0: 1.0, 1: 2.0}).fit(
            self.cases
        )
        inference = _inference_case("VECTOR_011")
        before = router.predict_proba(inference)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "b3_state.json"
            router.save(state_path)
            loaded = OvRLogisticRouter.load(state_path, adapter)
            after = loaded.predict_proba(inference)
        self.assertEqual(before, after)
        self.assertEqual(loaded.class_weight, {0: 1.0, 1: 2.0})

    def test_16_identical_seed_and_configuration_are_deterministic(self) -> None:
        first = OvRLogisticRouter(ToyEmbeddingAdapter(), random_seed=17).fit(self.cases)
        second = OvRLogisticRouter(ToyEmbeddingAdapter(), random_seed=17).fit(self.cases)
        for label in CAPABILITIES:
            np.testing.assert_array_equal(
                first.coefficients[label], second.coefficients[label]
            )
            self.assertEqual(first.intercepts[label], second.intercepts[label])

    def test_17_ovr_degenerate_label_detection(self) -> None:
        degenerate = deepcopy(self.cases)
        for case in degenerate:
            case["development_labels"]["planning_required"] = False
        with self.assertRaisesRegex(DegenerateLabelError, "planning_required"):
            OvRLogisticRouter(ToyEmbeddingAdapter()).fit(degenerate)

    def test_30_context_state_metadata_does_not_change_b3_output(self) -> None:
        router = OvRLogisticRouter(ToyEmbeddingAdapter()).fit(self.cases)
        variants = _context_state_variants()
        probabilities = router.predict_proba(variants)
        self.assertEqual(probabilities, [probabilities[0]] * len(probabilities))
        predictions = router.predict(variants)
        for prediction in predictions:
            self.assertEqual(
                prediction["metadata"]["primary_feature_profile"],
                PRIMARY_FEATURE_PROFILE,
            )
            self.assertEqual(
                prediction["metadata"]["positive_probabilities"], probabilities[0]
            )
        without_case_ids = [
            {key: value for key, value in prediction.items() if key != "case_id"}
            for prediction in predictions
        ]
        self.assertEqual(without_case_ids, [without_case_ids[0]] * len(without_case_ids))


class DevelopmentUtilityTests(unittest.TestCase):
    def test_18_grouped_split_never_separates_a_family(self) -> None:
        cases = _training_cases(prefix="CV-A") + _training_cases(prefix="CV-B")
        splits = grouped_cross_validation_splits(cases, n_splits=2)
        assert_family_never_crosses_folds(cases, splits)
        for train, validation in splits:
            train_families = {cases[index]["scenario_family_id"] for index in train}
            validation_families = {
                cases[index]["scenario_family_id"] for index in validation
            }
            self.assertFalse(train_families & validation_families)

    def test_19_development_utility_rejects_test_records(self) -> None:
        cases = _training_cases()
        cases[0]["partition"] = "TEST"
        with self.assertRaisesRegex(DevelopmentDataError, "TEST"):
            grouped_cross_validation_splits(cases, n_splits=2)

    def test_20_development_utility_rejects_clarification(self) -> None:
        cases = _training_cases()
        cases[0]["development_labels"] = {
            "dialogue_action": "CLARIFY",
            "rag_required": False,
            "memory_required": False,
            "planning_required": False,
        }
        with self.assertRaisesRegex(DevelopmentDataError, "clarification"):
            grouped_cross_validation_splits(cases, n_splits=2)

    def test_21_per_label_threshold_search(self) -> None:
        cases = _training_cases()
        router = PrototypeRouter(ToyEmbeddingAdapter()).fit(cases)
        scores = router.predict_scores(cases)
        result = search_per_label_thresholds(cases, scores)
        self.assertEqual(set(result["thresholds"]), set(CAPABILITIES))
        self.assertTrue(
            all(result["per_label"][label]["f1"] == 1.0 for label in CAPABILITIES)
        )

    def test_22_existing_stage0_metrics_are_reused(self) -> None:
        cases = _training_cases()
        predictions = PrototypeRouter(ToyEmbeddingAdapter()).fit(cases).predict(cases)
        metrics = evaluate_with_stage0_metrics(cases, predictions)
        self.assertEqual(metrics["primary_metric"], "macro_f1")
        self.assertEqual(metrics["macro_f1"], 1.0)

    def test_23_core_vs_synthetic_comparison_is_dev_only(self) -> None:
        core = _training_cases(prefix="CORE")
        synthetic = _training_cases(prefix="SYN")
        for case in synthetic:
            case["provenance"] = {"type": "RESEARCHER_SYNTHETIC"}
        validation = _training_cases(prefix="VALIDATION")
        result = compare_core_and_synthetic_augmentation(
            core,
            synthetic,
            validation,
            lambda: PrototypeRouter(ToyEmbeddingAdapter()),
        )
        self.assertEqual(result["status"], "DEVELOPMENT_ONLY_NO_WINNER_CLAIM")
        self.assertEqual(result["core_metrics"]["macro_f1"], 1.0)
        self.assertEqual(result["augmented_metrics"]["macro_f1"], 1.0)

    def test_24_learning_curve_uses_nonoverlapping_grouped_folds(self) -> None:
        cases = _training_cases(prefix="LC-A") + _training_cases(prefix="LC-B")
        result = run_learning_curve(
            cases,
            lambda: PrototypeRouter(ToyEmbeddingAdapter()),
            training_family_counts=[8],
            n_splits=2,
            random_seed=17,
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(row["metrics"]["macro_f1"] == 1.0 for row in result))

    def test_31_learning_curve_stratifies_lexically_correlated_families(self) -> None:
        cases = _lexically_correlated_family_cases()
        splits = grouped_cross_validation_splits(cases, n_splits=2, random_seed=17)
        first = run_learning_curve(
            cases,
            lambda: PrototypeRouter(ToyEmbeddingAdapter()),
            training_family_counts=[8],
            n_splits=2,
            random_seed=17,
        )
        second = run_learning_curve(
            cases,
            lambda: PrototypeRouter(ToyEmbeddingAdapter()),
            training_family_counts=[8],
            n_splits=2,
            random_seed=17,
        )
        self.assertEqual(
            [row["training_family_ids"] for row in first],
            [row["training_family_ids"] for row in second],
        )
        expected_signature_counts = {f"{value:03b}": 1 for value in range(8)}
        for row in first:
            fold = row["fold"]
            eligible = sorted(
                {
                    cases[index]["scenario_family_id"]
                    for index in splits[fold][0]
                }
            )
            selected = row["training_family_ids"]
            self.assertNotEqual(set(selected), set(eligible[:8]))
            self.assertEqual(
                row["family_sampling_method"], LEARNING_CURVE_SAMPLING_METHOD
            )
            self.assertEqual(row["family_sampling_seed"], 17)
            self.assertEqual(
                row["training_signature_family_counts"], expected_signature_counts
            )
            self.assertEqual(row["training_case_count"], 16)
            for family_id in selected:
                self.assertEqual(
                    sum(
                        case["scenario_family_id"] == family_id for case in cases
                    ),
                    2,
                )

    def test_32_learning_curve_fails_on_degenerate_selected_prefix(self) -> None:
        with self.assertRaisesRegex(
            DegenerateLabelError,
            r"learning curve fold=0 family_count=1",
        ):
            run_learning_curve(
                _lexically_correlated_family_cases(),
                lambda: PrototypeRouter(ToyEmbeddingAdapter()),
                training_family_counts=[1],
                n_splits=2,
                random_seed=17,
            )


class SharedEmbeddingContractTests(unittest.TestCase):
    def test_25_b2_and_b3_receive_identical_primary_text(self) -> None:
        cases = _training_cases()
        adapter = ToyEmbeddingAdapter()
        PrototypeRouter(adapter).fit(cases)
        OvRLogisticRouter(adapter).fit(cases)
        self.assertEqual(adapter.calls[0], adapter.calls[1])

    def test_26_embedding_dimension_is_validated(self) -> None:
        with self.assertRaisesRegex(EmbeddingAdapterError, "dimension"):
            validated_encode(
                WrongDimensionAdapter(), ["[CURRENT_QUERY]\nVECTOR_000"]
            )

    def test_27_missing_frozen_assets_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(EmbeddingAdapterError, "config is unavailable"):
                FrozenMpnetEmbeddingAdapter(directory)

    def test_33_context_state_metadata_gives_identical_mock_embeddings(self) -> None:
        variants = _context_state_variants()
        texts = [serialize_canonical_text(case) for case in variants]
        embeddings = validated_encode(ToyEmbeddingAdapter(), texts)
        np.testing.assert_array_equal(
            embeddings,
            np.repeat(embeddings[0:1], len(variants), axis=0),
        )

    def test_34_feature_profile_is_saved_for_b2_and_b3(self) -> None:
        cases = _training_cases()
        routers = (
            PrototypeRouter(ToyEmbeddingAdapter()).fit(cases),
            OvRLogisticRouter(ToyEmbeddingAdapter()).fit(cases),
        )
        with tempfile.TemporaryDirectory() as directory:
            for router in routers:
                state_path = Path(directory) / f"{router.model_id}.json"
                router.save(state_path)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    state["primary_feature_profile"], PRIMARY_FEATURE_PROFILE
                )
                prediction = router.predict(_inference_case("VECTOR_010"))
                self.assertEqual(
                    prediction["metadata"]["primary_feature_profile"],
                    PRIMARY_FEATURE_PROFILE,
                )


if __name__ == "__main__":
    unittest.main()
