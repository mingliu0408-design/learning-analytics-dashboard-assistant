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

import execute_b4_dev_r1 as execution  # noqa: E402
import finalize_b4_dev_r1 as finalizer  # noqa: E402


class B4ExecutionR1ResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = (
            execution.ATTEMPT_RECORDS_PATH,
            execution.CALL_JOURNAL_PATH,
            execution.TERMINAL_RESULTS_PATH,
            finalizer.PREDICTIONS_PATH,
            finalizer.ERROR_REGISTRY_PATH,
            finalizer.USAGE_PATH,
            finalizer.METRICS_PATH,
            finalizer.FINAL_FREEZE_PATH,
            finalizer.RESULTS_REPORT_PATH,
            finalizer.STATUS_PATH,
            finalizer.VERIFICATION_REPORT_PATH,
        )
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise unittest.SkipTest(f"R1 execution outputs not present: {missing}")
        cls.attempts = execution.load_jsonl(execution.ATTEMPT_RECORDS_PATH)
        cls.journal = execution.load_jsonl(execution.CALL_JOURNAL_PATH)
        cls.terminals = execution.load_jsonl(execution.TERMINAL_RESULTS_PATH)
        cls.usage = json.loads(finalizer.USAGE_PATH.read_text(encoding="utf-8"))
        cls.metrics = json.loads(finalizer.METRICS_PATH.read_text(encoding="utf-8"))
        cls.freeze = json.loads(finalizer.FINAL_FREEZE_PATH.read_text(encoding="utf-8"))

    def test_01_new_and_cumulative_call_counts(self) -> None:
        self.assertLessEqual(len(self.attempts), 128)
        self.assertLessEqual(1 + len(self.attempts), 129)
        self.assertEqual(
            list(range(1, len(self.attempts) + 1)),
            [record["physical_attempt_number"] for record in self.attempts],
        )
        self.assertEqual(
            list(range(2, len(self.attempts) + 2)),
            [record["cumulative_physical_attempt_number"] for record in self.attempts],
        )
        first_category = (
            (self.terminals[0].get("provider_error") or {}).get("category")
            if self.terminals
            else None
        )
        if first_category in execution.FIRST_CALL_FATAL_CATEGORIES:
            self.assertEqual(1, len(self.terminals))
        else:
            self.assertEqual(64, len(self.terminals))

    def test_02_retries_only_follow_invalid_structured_output(self) -> None:
        grouped: dict[str, list[dict[str, object]]] = {}
        for attempt in self.attempts:
            grouped.setdefault(attempt["logical_call_id"], []).append(attempt)
        for logical_id, attempts in grouped.items():
            self.assertIn(len(attempts), {1, 2}, logical_id)
            if len(attempts) == 2:
                first, second = attempts
                self.assertIn(
                    first["schema_validation"]["error"],
                    {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"},
                )
                self.assertIsNone(first["provider_error"])
                self.assertEqual(first["request_sha256"], second["request_sha256"])
                self.assertEqual([1, 2], [first["attempt_number"], second["attempt_number"]])

    def test_03_durable_call_journal_is_complete(self) -> None:
        ledger = finalizer._verify_call_ledger(
            self.attempts, self.journal, self.terminals
        )
        self.assertEqual("PASS", ledger["status"])
        self.assertEqual(len(self.attempts), ledger["reserved_events"])
        self.assertEqual(len(self.attempts), ledger["completed_events"])
        self.assertEqual(0, ledger["uncompleted_reservations"])

    def test_04_requested_and_returned_models(self) -> None:
        self.assertEqual(
            {execution.AUTHORIZED_MODEL_SNAPSHOT},
            {record["requested_model"] for record in self.attempts},
        )
        for record in self.attempts:
            if record["returned_model"] is not None:
                self.assertEqual(
                    execution.AUTHORIZED_MODEL_SNAPSHOT, record["returned_model"]
                )

    def test_05_historical_attempt_is_excluded(self) -> None:
        self.assertFalse(self.metrics["historical_failed_attempt_included"])
        historical = self.usage["historical_failed_attempt"]
        self.assertEqual(
            "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
            historical["classification"],
        )
        self.assertFalse(historical["included_in_r1_usage_or_cost"])
        self.assertEqual(
            len(self.attempts),
            self.metrics["coverage"]["new_physical_attempt_count"],
        )

    def test_06_usage_and_cost_arithmetic(self) -> None:
        actual = self.usage["actual_provider_usage_new_r1_run_only"]
        self.assertEqual([], actual["usage_arithmetic_discrepancy_attempt_ids"])
        self.assertEqual(
            actual["input_tokens"] + actual["output_tokens"],
            actual["total_tokens"],
        )
        input_cost = Decimal(actual["input_tokens"]) * Decimal("0.15") / Decimal(1_000_000)
        output_cost = Decimal(actual["output_tokens"]) * Decimal("0.60") / Decimal(1_000_000)
        self.assertEqual(
            format(input_cost, ".8f"), self.usage["approximate_cost_usd"]["input"]
        )
        self.assertEqual(
            format(output_cost, ".8f"), self.usage["approximate_cost_usd"]["output"]
        )

    def test_07_metrics_distribution_baselines_and_order(self) -> None:
        coverage = self.metrics["coverage"]
        self.assertEqual(len(self.terminals), coverage["terminal_results"])
        self.assertEqual(len(self.attempts), coverage["new_physical_attempt_count"])
        distribution = self.metrics["predicted_capability_count_distribution"]
        self.assertEqual(
            coverage["valid_predictions"],
            sum(distribution["counts"].values()),
        )
        baselines = self.metrics[
            "frozen_sanity_baselines_same_64_answer_population"
        ]
        self.assertEqual(64, baselines["ALWAYS_ON"]["case_count"])
        self.assertEqual(64, baselines["NEVER_ON"]["case_count"])
        with finalizer.PREDICTIONS_PATH.open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(64, len(rows))
        self.assertEqual(
            [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)],
            [row["logical_call_id"] for row in rows],
        )

    def test_08_final_freeze_requires_64_valid_predictions(self) -> None:
        valid = self.metrics["coverage"]["valid_predictions"]
        if valid == 64 and len(self.terminals) == 64:
            self.assertEqual(
                "FROZEN_AFTER_DEV_EXECUTION", self.freeze["B4_MODEL_STATUS"]
            )
        else:
            self.assertEqual(
                "EXECUTION_INCOMPLETE_NOT_FROZEN", self.freeze["B4_MODEL_STATUS"]
            )
        self.assertEqual(
            execution.AUTHORIZED_MODEL_SNAPSHOT, self.freeze["model_snapshot"]
        )
        self.assertEqual(execution.EXPECTED_PROMPT_SHA256, self.freeze["prompt_sha256"])
        self.assertEqual(
            execution.sha256_file(execution.SCHEMA_V2_PATH),
            self.freeze["response_schema_v2_sha256"],
        )

    def test_09_error_registry_has_sanitized_distinct_fields(self) -> None:
        with finalizer.ERROR_REGISTRY_PATH.open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fieldnames = set(reader.fieldnames or [])
        expected_fields = {
            "provider_exception_type",
            "provider_error_category",
            "provider_http_status",
            "provider_error_code",
            "provider_error_param",
            "provider_request_id",
            "sanitized_error_message",
        }
        self.assertTrue(expected_fields <= fieldnames)
        for row in rows:
            if row["provider_exception_type"] == "BadRequestError":
                self.assertEqual(
                    "REQUEST_CONFIGURATION_ERROR",
                    row["provider_error_category"],
                )

    def test_10_no_credentials_or_test_identifiers_in_new_outputs(self) -> None:
        paths = (
            execution.ATTEMPT_RECORDS_PATH,
            execution.CALL_JOURNAL_PATH,
            execution.TERMINAL_RESULTS_PATH,
            finalizer.PREDICTIONS_PATH,
            finalizer.ERROR_REGISTRY_PATH,
            finalizer.USAGE_PATH,
            finalizer.METRICS_PATH,
            finalizer.FINAL_FREEZE_PATH,
            finalizer.RESULTS_REPORT_PATH,
            finalizer.STATUS_PATH,
            finalizer.VERIFICATION_REPORT_PATH,
        )
        patterns = (
            re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b"),
            re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE),
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), path.name)
            self.assertNotIn("R2V2-TEST", text.upper(), path.name)
            self.assertNotIn("TEST_ESCROW", text.upper(), path.name)

    def test_11_historical_hashes_remain_unchanged_after_r1(self) -> None:
        self.assertEqual(
            execution.HISTORICAL_STAGE4IX_SHA256,
            execution.verify_historical_artifacts(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
