"""Deterministic fail-closed tests for RQ2-V2 Stage 4G."""

from __future__ import annotations

from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import socket
import subprocess
import unittest

from . import CAPABILITIES, PACKAGE_ROOT, PROJECT_ROOT
from .clarification_gate import ALLOWED_FIELDS, ClarificationGate
from .run_track_g import (
    B0_CODE_PATH,
    B0_CONFIG_PATH,
    C0_EMBEDDING_PATH,
    C0_INDEX_PATH,
    C0_LOADER_PATH,
    C0_ROOT,
    C0_ROUTER_PATH,
    EXPECTED_B0_HASHES,
    EXPECTED_C0_HASHES,
    EXPECTED_DEV_HASHES,
    FOLDS,
    PREDICTION_FIELDS,
    TrackGEvaluationError,
    _canonical_b0_case,
    build_b1_mapping,
    canonical_json_bytes,
    load_dev_rows,
    offline_network_guard,
    sha256_file,
    verify_c0_identity,
)


def read_json(name: str):
    return json.loads((PACKAGE_ROOT / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> list[dict[str, str]]:
    with (PACKAGE_ROOT / name).open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class TrackGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows, cls.source_hashes = load_dev_rows()
        cls.by_id = {row["annotation_case_id"]: row for row in cls.rows}
        cls.candidate_payload = read_json("clarification_candidate_configs_v1.json")
        cls.gate_frozen = read_json("clarification_gate_frozen_v1.json")
        cls.b1_intents = read_csv("b1_intent_predictions_dev_v1.csv")
        cls.c0_predictions = {
            row["annotation_case_id"]: {
                "predicted_intent": row["predicted_intent"],
                "similarity_score": float(row["similarity_score"]),
                "margin": float(row["margin"]) if row["margin"] else None,
            }
            for row in cls.b1_intents
        }

    def test_01_dev_source_hashes(self) -> None:
        self.assertEqual(self.source_hashes, EXPECTED_DEV_HASHES)

    def test_02_frozen_fold_use(self) -> None:
        for name, expected_count in (
            ("clarification_oof_predictions_v1.csv", 72),
            ("b0_core_oof_predictions_v1.csv", 64),
            ("b1_core_oof_predictions_v1.csv", 64),
        ):
            output = read_csv(name)
            self.assertEqual(len(output), expected_count)
            self.assertEqual(len({row["annotation_case_id"] for row in output}), expected_count)
            for row in output:
                self.assertEqual(row["outer_fold"], self.by_id[row["annotation_case_id"]]["outer_fold"])

    def test_03_no_family_or_component_leakage(self) -> None:
        for key in ("scenario_family_id", "dev_atomic_component_id"):
            assignments: dict[str, set[str]] = defaultdict(set)
            for row in self.rows:
                assignments[row[key]].add(row["outer_fold"])
            self.assertTrue(assignments)
            self.assertTrue(all(len(folds) == 1 for folds in assignments.values()))

    def test_04_zero_heldout_identifiers(self) -> None:
        allowed = set(self.by_id)
        observed: set[str] = set()
        for path in PACKAGE_ROOT.iterdir():
            if path.is_file() and path.suffix in {".csv", ".json", ".md"}:
                observed.update(re.findall(r"R2V2-ANN-\d+", path.read_text(encoding="utf-8")))
        self.assertTrue(observed)
        self.assertLessEqual(observed, allowed)

    def test_05_candidates_predeclared_before_scoring(self) -> None:
        payload = self.candidate_payload
        self.assertEqual(payload["candidate_status"], "FROZEN_PREDECLARED_BEFORE_DEV_SCORING")
        self.assertIs(payload["performance_metrics_calculated_at_declaration"], False)
        self.assertNotIn("metrics", payload)
        self.assertEqual(self.gate_frozen["candidate_file_sha256"], sha256_file(PACKAGE_ROOT / "clarification_candidate_configs_v1.json"))
        self.assertFalse(self.gate_frozen["candidate_mutation_after_scoring"])

    def test_06_no_annotation_specific_rule(self) -> None:
        text = (PACKAGE_ROOT / "clarification_gate.py").read_text(encoding="utf-8") + json.dumps(self.candidate_payload)
        self.assertNotRegex(text, r"R2V2-ANN-\d+")
        self.assertNotRegex(text, r"R2V2-SF-\d+")

    def test_07_no_exact_query_lookup_table(self) -> None:
        implementation = (
            (PACKAGE_ROOT / "clarification_gate.py").read_text(encoding="utf-8")
            + (PACKAGE_ROOT / "clarification_candidate_configs_v1.json").read_text(encoding="utf-8")
        ).casefold()
        for row in self.rows:
            self.assertNotIn(row["current_query"].casefold(), implementation)
        self.assertFalse(self.candidate_payload["governance"]["exact_full_query_lookup_table"])

    def test_08_b0_privileged_fields_excluded(self) -> None:
        from evaluation.capability_routing_rq2_v2_stage1.track_b_b0_b1.b0_rule_router import B0RuleRouter

        self.assertEqual(sha256_file(B0_CONFIG_PATH), EXPECTED_B0_HASHES["ruleset"])
        self.assertEqual(sha256_file(B0_CODE_PATH), EXPECTED_B0_HASHES["code"])
        source = next(row for row in self.rows if row["gold_dialogue_action"] == "ANSWER")
        first = _canonical_b0_case(source)
        second = json.loads(json.dumps(first))
        first["model_input"]["rag_context_state"] = "RETRIEVAL_AVAILABLE"
        first["model_input"]["memory_context_state"] = "LONG_TERM_MEMORY_AVAILABLE"
        second["model_input"]["rag_context_state"] = "RETRIEVAL_UNAVAILABLE"
        second["model_input"]["memory_context_state"] = "LONG_TERM_MEMORY_UNAVAILABLE"
        router = B0RuleRouter(B0_CONFIG_PATH)
        a, b = router.predict(first), router.predict(second)
        self.assertEqual((a.rag_required, a.memory_required, a.planning_required), (b.rag_required, b.memory_required, b.planning_required))
        frozen = read_json("b0_frozen_config_v1.json")
        self.assertEqual(tuple(frozen["model_visible_fields"]), ALLOWED_FIELDS)
        self.assertTrue(frozen["privileged_fields_excluded"])

    def test_09_c0_asset_identity(self) -> None:
        identity, _ = verify_c0_identity()
        self.assertEqual(identity["intent_index_sha256"], EXPECTED_C0_HASHES["intent_index"])
        self.assertEqual(identity["embedding_matrix_sha256"], EXPECTED_C0_HASHES["embedding_matrix"])
        self.assertEqual(identity["embedding_shape"], [62, 768])
        self.assertEqual(identity["embedding_dtype"], "float32")
        self.assertEqual(identity["aggregation"], "MAX")

    def test_10_c0_sixteen_intent_universe(self) -> None:
        identity = read_json("c0_identity_frozen_v1.json")
        mapping = read_json("b1_mapping_frozen_v1.json")
        intents = [row["intent_id"] for row in mapping["mappings"]]
        self.assertEqual(len(intents), 16)
        self.assertEqual(set(intents), set(identity["intent_label_universe"]))
        self.assertEqual(sum(identity["intent_label_example_counts"].values()), 62)

    def test_11_c0_unchanged(self) -> None:
        observed = {
            "loader_code": sha256_file(C0_LOADER_PATH),
            "router_code": sha256_file(C0_ROUTER_PATH),
            "runtime_config": sha256_file(C0_ROOT / "semantic_runtime/config/semantic_routing_config.json"),
            "intent_index": sha256_file(C0_INDEX_PATH),
            "embedding_matrix": sha256_file(C0_EMBEDDING_PATH),
        }
        self.assertEqual(observed, EXPECTED_C0_HASHES)
        status = subprocess.run(
            ["git", "-C", str(C0_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(status, "")

    def test_12_family_balanced_b1_mapping(self) -> None:
        answers = [row for row in self.rows if row["gold_dialogue_action"] == "ANSWER"]
        expected = build_b1_mapping(
            answers,
            self.c0_predictions,
            read_json("c0_identity_frozen_v1.json")["intent_label_universe"],
        )
        observed = read_json("b1_mapping_frozen_v1.json")["mappings"]
        self.assertEqual(canonical_json_bytes(observed), canonical_json_bytes(expected))
        self.assertTrue(all(row["weighted_observed_family_count"] == row["utterance_count"] * 0.5 for row in observed))

    def test_13_training_fold_only_mapping(self) -> None:
        answer_rows = [row for row in self.rows if row["gold_dialogue_action"] == "ANSWER"]
        universe = read_json("c0_identity_frozen_v1.json")["intent_label_universe"]
        frozen = read_json("b1_fold_mappings_v1.json")
        self.assertEqual(len(frozen["folds"]), 4)
        for fold in frozen["folds"]:
            validation_fold = fold["validation_fold"]
            training = [row for row in answer_rows if row["outer_fold"] != validation_fold]
            validation_ids = {row["annotation_case_id"] for row in answer_rows if row["outer_fold"] == validation_fold}
            training_ids = {row["annotation_case_id"] for row in training}
            self.assertTrue(training_ids.isdisjoint(validation_ids))
            self.assertEqual(len(training), 48)
            expected = build_b1_mapping(training, self.c0_predictions, universe)
            self.assertEqual(canonical_json_bytes(fold["mappings"]), canonical_json_bytes(expected))

    def test_14_exact_tie_behavior(self) -> None:
        rows = [
            {"annotation_case_id": "A", "gold_rag": True, "gold_memory": False, "gold_planning": False},
            {"annotation_case_id": "B", "gold_rag": False, "gold_memory": False, "gold_planning": False},
        ]
        predictions = {key: {"predicted_intent": "intent"} for key in ("A", "B")}
        mapping = build_b1_mapping(rows, predictions, ["intent"])[0]
        rag = mapping["capabilities"]["RAG"]
        self.assertEqual(rag["positive_prevalence"], 0.5)
        self.assertEqual(rag["mapping"], "NO")
        self.assertEqual(rag["decision_reason"], "EXACT_TIE_MINIMUM_NECESSARY_NO")

    def test_15_unseen_intent_conservative_default(self) -> None:
        rows = [{"annotation_case_id": "A", "gold_rag": True, "gold_memory": True, "gold_planning": True}]
        predictions = {"A": {"predicted_intent": "observed"}}
        mapping = build_b1_mapping(rows, predictions, ["observed", "unseen"])[1]
        self.assertEqual(mapping["observation_status"], "UNOBSERVED")
        for capability in CAPABILITIES:
            self.assertEqual(mapping["capabilities"][capability]["mapping"], "NO")
            self.assertEqual(mapping["capabilities"][capability]["decision_reason"], "UNOBSERVED_INTENT_CONSERVATIVE_NO")

    def test_16_deterministic_output(self) -> None:
        gate = ClarificationGate(self.candidate_payload)
        config_id = self.gate_frozen["selected_config_id"]
        first = [gate.predict({key: row[key] for key in ALLOWED_FIELDS}, config_id) for row in self.rows]
        second = [gate.predict({key: row[key] for key in ALLOWED_FIELDS}, config_id) for row in self.rows]
        self.assertEqual(first, second)
        answers = [row for row in self.rows if row["gold_dialogue_action"] == "ANSWER"]
        universe = read_json("c0_identity_frozen_v1.json")["intent_label_universe"]
        forward = build_b1_mapping(answers, self.c0_predictions, universe)
        reverse = build_b1_mapping(list(reversed(answers)), self.c0_predictions, universe)
        self.assertEqual(canonical_json_bytes(forward), canonical_json_bytes(reverse))

    def test_17_canonical_prediction_schema(self) -> None:
        for name, count in (
            ("b0_core_oof_predictions_v1.csv", 64),
            ("b0_end_to_end_oof_predictions_v1.csv", 72),
            ("b1_core_oof_predictions_v1.csv", 64),
            ("b1_end_to_end_oof_predictions_v1.csv", 72),
        ):
            with (PACKAGE_ROOT / name).open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                self.assertEqual(tuple(reader.fieldnames or ())[: len(PREDICTION_FIELDS)], PREDICTION_FIELDS)
            self.assertEqual(len(rows), count)
            self.assertEqual(len({row["annotation_case_id"] for row in rows}), count)
            for row in rows:
                self.assertEqual(row["schema_version"], "rq2-v2-stage4g-canonical-prediction-v1")
                if row["predicted_dialogue_action"] == "CLARIFY":
                    self.assertEqual(row["predicted_rag_required"], "NOT_APPLICABLE")
                    self.assertEqual(row["predicted_memory_required"], "NOT_APPLICABLE")
                    self.assertEqual(row["predicted_planning_required"], "NOT_APPLICABLE")

    def test_18_zero_network_access(self) -> None:
        with offline_network_guard():
            network_socket = socket.socket()
            try:
                with self.assertRaises(TrackGEvaluationError):
                    network_socket.connect(("127.0.0.1", 9))
            finally:
                network_socket.close()
        metrics = read_json("track_g_metrics_v1.json")
        self.assertFalse(metrics["governance"]["network_access"])
        self.assertEqual(metrics["governance"]["provider_call_count"], 0)


if __name__ == "__main__":
    unittest.main()
