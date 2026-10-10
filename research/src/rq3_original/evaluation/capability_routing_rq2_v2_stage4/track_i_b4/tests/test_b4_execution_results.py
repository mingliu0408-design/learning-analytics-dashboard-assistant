from __future__ import annotations

import csv
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import unittest


TRACK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK_DIR))

import execute_b4_dev as execution  # noqa: E402
import finalize_b4_dev as finalizer  # noqa: E402


class B4ExecutionResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = (
            execution.ATTEMPT_RECORDS_PATH,
            execution.TERMINAL_RESULTS_PATH,
            execution.CALL_JOURNAL_PATH,
            finalizer.PREDICTIONS_PATH,
            finalizer.ERROR_REGISTRY_PATH,
            finalizer.USAGE_PATH,
            finalizer.METRICS_PATH,
            finalizer.FINAL_FREEZE_PATH,
        )
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise unittest.SkipTest(f"Execution outputs not present yet: {missing}")
        cls.attempts = execution.load_jsonl(execution.ATTEMPT_RECORDS_PATH)
        cls.terminals = execution.load_jsonl(execution.TERMINAL_RESULTS_PATH)
        cls.journal = execution.load_jsonl(execution.CALL_JOURNAL_PATH)
        cls.usage = json.loads(finalizer.USAGE_PATH.read_text(encoding="utf-8"))
        cls.metrics = json.loads(finalizer.METRICS_PATH.read_text(encoding="utf-8"))
        cls.freeze = json.loads(finalizer.FINAL_FREEZE_PATH.read_text(encoding="utf-8"))

    def test_01_actual_call_counts_and_ceilings(self) -> None:
        self.assertLessEqual(len(self.attempts), 128)
        if self.freeze["B4_MODEL_STATUS"] == "FROZEN_AFTER_DEV_EXECUTION":
            self.assertEqual(64, len(self.terminals))
            self.assertGreaterEqual(len(self.attempts), 64)
        else:
            self.assertEqual("EXECUTION_INCOMPLETE_NOT_FROZEN", self.freeze["B4_MODEL_STATUS"])
            self.assertEqual(1, len(self.terminals))
            self.assertEqual(1, len(self.attempts))
            self.assertEqual("PROVIDER_ERROR", self.terminals[0]["terminal_status"])
            self.assertEqual(
                "AUTHENTICATION_OR_CONFIGURATION",
                self.terminals[0]["provider_error"]["category"],
            )
        self.assertEqual(
            list(range(1, len(self.attempts) + 1)),
            [record["physical_attempt_number"] for record in self.attempts],
        )
        expected_logical = [
            f"R2V2-B4-DEV-{index:04d}"
            for index in range(1, len(self.terminals) + 1)
        ]
        self.assertEqual(expected_logical, [record["logical_call_id"] for record in self.terminals])

    def test_02_retries_only_follow_invalid_structured_output(self) -> None:
        by_logical: dict[str, list[dict[str, object]]] = {}
        for attempt in self.attempts:
            by_logical.setdefault(attempt["logical_call_id"], []).append(attempt)
        for logical_id, attempts in by_logical.items():
            self.assertIn(len(attempts), {1, 2}, logical_id)
            if len(attempts) == 2:
                first, second = attempts
                self.assertFalse(first["schema_validation"]["valid"])
                self.assertIn(
                    first["schema_validation"]["error"],
                    {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"},
                )
                self.assertIsNone(first["provider_error"])
                self.assertEqual(first["request_sha256"], second["request_sha256"])
                self.assertEqual(1, first["attempt_number"])
                self.assertEqual(2, second["attempt_number"])

    def test_03_actual_call_journal_is_complete(self) -> None:
        ledger = finalizer._verify_call_ledger(self.attempts, self.journal)
        self.assertEqual("PASS", ledger["status"])
        self.assertEqual(len(self.attempts), ledger["reserved_events"])
        self.assertEqual(len(self.attempts), ledger["completed_events"])
        self.assertEqual(0, ledger["uncompleted_reservations"])
        v2 = execution.load_jsonl(execution.V2_MANIFEST_PATH)
        expected_request_hash = execution.canonical_sha256(
            v2[0]["provider_request_payload"]
        )
        self.assertEqual(expected_request_hash, self.attempts[0]["request_sha256"])
        self.assertEqual(expected_request_hash, self.journal[0]["request_sha256"])
        self.assertEqual(expected_request_hash, self.journal[1]["request_sha256"])

    def test_04_requested_and_returned_model_identity(self) -> None:
        self.assertEqual(
            {execution.AUTHORIZED_MODEL_SNAPSHOT},
            {attempt["requested_model"] for attempt in self.attempts},
        )
        returned = {
            attempt["returned_model"]
            for attempt in self.attempts
            if attempt["returned_model"] is not None
        }
        if self.freeze["B4_MODEL_STATUS"] == "FROZEN_AFTER_DEV_EXECUTION":
            self.assertEqual({execution.AUTHORIZED_MODEL_SNAPSHOT}, returned)
        else:
            self.assertEqual(set(), returned)

    def test_05_no_credentials_or_test_identifiers_in_outputs(self) -> None:
        credential_patterns = (
            re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{12,}"),
            re.compile(r"Bearer\s+[A-Za-z0-9._-]{12,}", re.IGNORECASE),
        )
        output_paths = (
            execution.ATTEMPT_RECORDS_PATH,
            execution.TERMINAL_RESULTS_PATH,
            execution.CALL_JOURNAL_PATH,
            finalizer.PREDICTIONS_PATH,
            finalizer.ERROR_REGISTRY_PATH,
            finalizer.USAGE_PATH,
            finalizer.METRICS_PATH,
            finalizer.FINAL_FREEZE_PATH,
            finalizer.RESULTS_REPORT_PATH,
            finalizer.STATUS_PATH,
        )
        for path in output_paths:
            text = path.read_text(encoding="utf-8")
            for pattern in credential_patterns:
                self.assertIsNone(pattern.search(text), path.name)
            self.assertNotIn("R2V2-TEST", text.upper(), path.name)
        case_ids = {terminal["annotation_case_id"] for terminal in self.terminals}
        self.assertFalse(any("TEST" in case_id.upper() for case_id in case_ids))

    def test_06_usage_arithmetic_and_cost(self) -> None:
        actual = self.usage["actual_provider_usage"]
        self.assertEqual([], actual["usage_arithmetic_discrepancy_attempt_ids"])
        self.assertEqual(actual["input_tokens"] + actual["output_tokens"], actual["total_tokens"])
        expected_input_cost = Decimal(actual["input_tokens"]) * Decimal("0.15") / Decimal(1_000_000)
        expected_output_cost = Decimal(actual["output_tokens"]) * Decimal("0.60") / Decimal(1_000_000)
        self.assertEqual(format(expected_input_cost, ".8f"), self.usage["approximate_cost_usd"]["input"])
        self.assertEqual(format(expected_output_cost, ".8f"), self.usage["approximate_cost_usd"]["output"])
        self.assertEqual(
            format(expected_input_cost + expected_output_cost, ".8f"),
            self.usage["approximate_cost_usd"]["total"],
        )

    def test_07_metrics_coverage_and_deterministic_prediction_order(self) -> None:
        coverage = self.metrics["coverage"]
        self.assertEqual(len(self.terminals), coverage["terminal_results"])
        self.assertEqual(len(self.attempts), coverage["physical_attempt_count"])
        with finalizer.PREDICTIONS_PATH.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(64, len(rows))
        self.assertEqual(
            [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)],
            [row["logical_call_id"] for row in rows],
        )
        if len(self.terminals) < 64:
            self.assertEqual(
                64 - len(self.terminals),
                sum(
                    row["terminal_status"] == "NOT_EXECUTED_DUE_TO_RUN_STOP"
                    for row in rows
                ),
            )
        self.assertIs(False, self.metrics["coverage_adjusted_status"]["missing_outputs_counted_as_correct"])
        self.assertEqual("NONE", self.metrics["coverage_adjusted_status"]["f1_imputation_for_missing_outputs"])

    def test_08_final_freeze_and_v1_preservation(self) -> None:
        if len(self.terminals) == 64:
            self.assertEqual("FROZEN_AFTER_DEV_EXECUTION", self.freeze["B4_MODEL_STATUS"])
        else:
            self.assertEqual("EXECUTION_INCOMPLETE_NOT_FROZEN", self.freeze["B4_MODEL_STATUS"])
        self.assertEqual(execution.AUTHORIZED_MODEL_SNAPSHOT, self.freeze["model_snapshot"])
        self.assertEqual(execution.EXPECTED_PROMPT_SHA256, self.freeze["prompt_sha256"])
        self.assertEqual(execution.EXPECTED_SCHEMA_SHA256, self.freeze["response_schema_sha256"])
        self.assertEqual(64, self.freeze["max_output_tokens"])
        self.assertEqual(0, self.freeze["sdk_transport_retries"])
        diff = json.loads(execution.MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
        self.assertEqual(execution.sha256_file(execution.V1_MANIFEST_PATH), diff["v1_manifest_sha256"])
        self.assertEqual(0, self.freeze["future_boundary"]["test_calls_made"])
        self.assertEqual(0, self.freeze["future_boundary"]["p1_calls_made"])
        self.assertEqual(0, self.freeze["future_boundary"]["rq3_calls_made"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
