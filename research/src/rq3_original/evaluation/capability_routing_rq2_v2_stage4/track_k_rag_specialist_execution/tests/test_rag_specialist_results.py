from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import unittest

from ..finalize_rag_specialist_dev import verify_call_ledger
from ..rag_specialist_protocol import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    ERROR_REGISTRY_PATH,
    FROZEN_CONFIGURATION_PATH,
    LOGICAL_CALL_CEILING,
    METRICS_PATH,
    PHYSICAL_ATTEMPT_CEILING,
    PREDICTIONS_PATH,
    STATUS_PATH,
    TERMINAL_RESULTS_PATH,
    TRACK_DIR,
    USAGE_AND_COST_PATH,
    V2_MANIFEST_PATH,
    canonical_sha256,
    load_jsonl,
    sha256_file,
)


class RagSpecialistResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_jsonl(V2_MANIFEST_PATH)
        cls.attempts = load_jsonl(ATTEMPT_RECORDS_PATH)
        cls.journal = load_jsonl(CALL_JOURNAL_PATH)
        cls.terminals = load_jsonl(TERMINAL_RESULTS_PATH)
        cls.metrics = json.loads(METRICS_PATH.read_text())
        cls.usage = json.loads(USAGE_AND_COST_PATH.read_text())
        cls.config = json.loads(FROZEN_CONFIGURATION_PATH.read_text())

    def test_01_all_required_execution_outputs_exist(self) -> None:
        for path in (
            ATTEMPT_RECORDS_PATH,
            CALL_JOURNAL_PATH,
            TERMINAL_RESULTS_PATH,
            PREDICTIONS_PATH,
            ERROR_REGISTRY_PATH,
            METRICS_PATH,
            USAGE_AND_COST_PATH,
            FROZEN_CONFIGURATION_PATH,
            STATUS_PATH,
        ):
            self.assertTrue(path.is_file(), path.name)

    def test_02_exactly_64_logical_records_and_bounded_attempts(self) -> None:
        self.assertEqual(len(self.terminals), LOGICAL_CALL_CEILING)
        self.assertLessEqual(len(self.attempts), PHYSICAL_ATTEMPT_CEILING)
        self.assertGreaterEqual(len(self.attempts), LOGICAL_CALL_CEILING)

    def test_03_durable_call_journal_is_complete(self) -> None:
        result = verify_call_ledger(self.attempts, self.journal, self.terminals)
        self.assertEqual(result["status"], "PASS_DURABLE_BOUNDED_CALL_LEDGER")
        self.assertEqual(result["uncompleted_reservations"], 0)

    def test_04_every_attempt_request_hash_matches_frozen_v2(self) -> None:
        by_logical = {record["logical_call_id"]: record for record in self.manifest}
        for attempt in self.attempts:
            record = by_logical[attempt["logical_call_id"]]
            self.assertEqual(
                attempt["request_sha256"],
                canonical_sha256(record["provider_facing_request"]),
            )

    def test_05_retries_are_identical_and_only_after_invalid_output(self) -> None:
        completions = {
            event["physical_attempt_id"]: event["outcome"]
            for event in self.journal
            if event["event"] == "ATTEMPT_COMPLETED"
        }
        grouped: dict[str, list[dict[str, object]]] = {}
        for attempt in self.attempts:
            grouped.setdefault(attempt["logical_call_id"], []).append(attempt)
        for attempts in grouped.values():
            if len(attempts) == 2:
                self.assertEqual(
                    completions[attempts[0]["physical_attempt_id"]],
                    "INVALID_STRUCTURED_OUTPUT",
                )
                self.assertEqual(attempts[0]["request_sha256"], attempts[1]["request_sha256"])

    def test_06_initial_request_pacing_is_at_least_two_seconds(self) -> None:
        initials = [attempt for attempt in self.attempts if attempt["attempt_number"] == 1]
        self.assertEqual(len(initials), 64)
        for attempt in initials[1:]:
            self.assertGreaterEqual(
                float(attempt["initial_request_interval_seconds"]), 2.0
            )

    def test_07_exactly_64_prediction_rows(self) -> None:
        with PREDICTIONS_PATH.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 64)
        self.assertEqual(
            [row["logical_call_id"] for row in rows],
            [record["logical_call_id"] for record in self.manifest],
        )

    def test_08_valid_results_are_strict_booleans(self) -> None:
        for terminal in self.terminals:
            if terminal["terminal_status"] == "VALID_PREDICTION":
                self.assertEqual(set(terminal["prediction"]), {"rag_required"})
                self.assertIs(type(terminal["prediction"]["rag_required"]), bool)

    def test_09_returned_model_identity_is_frozen_snapshot(self) -> None:
        returned = {
            attempt["returned_model"]
            for attempt in self.attempts
            if attempt["returned_model"] is not None
        }
        self.assertEqual(returned, {AUTHORIZED_MODEL_SNAPSHOT})

    def test_10_metrics_report_coverage_and_no_imputation(self) -> None:
        coverage = self.metrics["coverage"]
        self.assertEqual(coverage["total_authorized_dev_answer_cases"], 64)
        self.assertFalse(
            self.metrics["coverage_adjusted_status"]["missing_outputs_imputed"]
        )
        self.assertIn("complete_case_metrics", self.metrics)
        self.assertIn("family_metrics", self.metrics)
        self.assertIn("rag_contrast_metrics", self.metrics)

    def test_11_page_and_fold_strata_are_complete(self) -> None:
        self.assertEqual(
            set(self.metrics["page_stratified_metrics"]),
            {"Debate", "Lecture", "Overview", "Reflection", "Resources"},
        )
        self.assertEqual(
            set(self.metrics["fold_stratified_metrics"]),
            {"DEV-CV-FOLD-1", "DEV-CV-FOLD-2", "DEV-CV-FOLD-3", "DEV-CV-FOLD-4"},
        )

    def test_12_token_and_cost_arithmetic_from_returned_usage(self) -> None:
        actual = self.usage["actual_provider_usage"]
        self.assertEqual(actual["input_tokens"] + actual["output_tokens"], actual["total_tokens"])
        expected = (
            actual["input_tokens"] * 0.15 / 1_000_000
            + actual["output_tokens"] * 0.60 / 1_000_000
        )
        self.assertAlmostEqual(
            float(self.usage["approximate_cost_usd"]["total"]), expected, places=8
        )

    def test_13_frozen_source_hashes_match_before_and_after(self) -> None:
        self.assertTrue(self.config["pre_post_source_hashes_identical"])
        self.assertEqual(
            self.config["pre_execution_k0_source_hashes"],
            self.config["post_execution_k0_source_hashes"],
        )
        self.assertEqual(
            self.config["pre_execution_external_dev_source_hashes"],
            self.config["post_execution_external_dev_source_hashes"],
        )

    def test_14_freeze_status_requires_complete_valid_coverage(self) -> None:
        valid = self.metrics["coverage"]["valid_predictions"]
        expected = (
            "FROZEN_AFTER_DEV_EXECUTION"
            if valid == 64
            else "RAG_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
        )
        self.assertEqual(self.config["RAG_SPECIALIST_STATUS"], expected)

    def test_15_zero_test_memory_composition_p1_and_rq3_execution(self) -> None:
        scope = self.config["execution_scope_assertions"]
        for field in (
            "test_calls",
            "test_inputs_accessed",
            "memory_specialist_calls",
            "p2_calls_or_scoring",
            "p3_calls_or_scoring",
            "p1_calls",
            "rq3_calls",
            "joint_b4_calls",
        ):
            self.assertEqual(scope[field], 0)
        self.assertFalse(scope["final_full_dev_prompt_executed_on_test"])

    def test_16_no_credentials_in_generated_outputs(self) -> None:
        key_pattern = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
        bearer_pattern = re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.I)
        generated = [
            V2_MANIFEST_PATH,
            ATTEMPT_RECORDS_PATH,
            CALL_JOURNAL_PATH,
            TERMINAL_RESULTS_PATH,
            PREDICTIONS_PATH,
            ERROR_REGISTRY_PATH,
            METRICS_PATH,
            USAGE_AND_COST_PATH,
            FROZEN_CONFIGURATION_PATH,
            STATUS_PATH,
        ]
        for path in generated:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(key_pattern.search(text), path.name)
            self.assertIsNone(bearer_pattern.search(text), path.name)

    def test_17_no_test_identifiers_in_execution_outputs(self) -> None:
        for path in (
            V2_MANIFEST_PATH,
            ATTEMPT_RECORDS_PATH,
            CALL_JOURNAL_PATH,
            TERMINAL_RESULTS_PATH,
            PREDICTIONS_PATH,
        ):
            text = path.read_text(encoding="utf-8").upper()
            self.assertNotIn("R2V2-TEST", text)
            self.assertNotIn("TEST_ESCROW", text)


if __name__ == "__main__":
    unittest.main()
