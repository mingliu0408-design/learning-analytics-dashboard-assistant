"""Offline integrity tests for the frozen, unscored Stage 5C RAG output."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "rag_specialist_test_terminal_results_v1.jsonl"
AUDIT = ROOT / "rag_specialist_test_execution_audit_v1.json"
SOURCE_MANIFEST = ROOT / "rag_specialist_test_execution_source_manifest_v1.json"
REPORT = ROOT / "RAG_SPECIALIST_TEST_EXECUTION_REPORT.md"
STATUS = ROOT / "STATUS.md"

EXPECTED_OUTPUT_SHA256 = "bb3cc640c61e0986acb1c664a684f6b3b476c1940a6fc2fd456871725885cf75"
EXPECTED_METHOD = "R2V2-RAG_SPECIALIST"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_STATUS = "RAG_SPECIALIST_TEST_PREDICTIONS_FROZEN_UNSCORED"
EXPECTED_TOP_LEVEL_KEYS = {
    "schema_version",
    "logical_case_id",
    "logical_call_id",
    "annotation_case_id",
    "method_id",
    "execution_status",
    "physical_attempts",
    "attempt_records",
    "prediction",
    "scoring_performed",
}
SECRET_PATTERN = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~-]{8,})",
    re.IGNORECASE,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested_keys(value: object):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from nested_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from nested_keys(nested)


class FrozenRagSpecialistTestExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_output = OUTPUT.read_text(encoding="utf-8")
        cls.rows = [json.loads(line) for line in cls.raw_output.splitlines() if line]
        cls.audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        cls.source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

    def test_01_output_hash_and_line_count(self) -> None:
        self.assertEqual(sha256(OUTPUT), EXPECTED_OUTPUT_SHA256)
        self.assertEqual(len(self.rows), 36)
        self.assertEqual(OUTPUT.stat().st_size, 25030)

    def test_02_identity_order_and_coverage(self) -> None:
        self.assertEqual(
            [row["logical_call_id"] for row in self.rows],
            [f"R2V2-RAG-SPECIALIST-TEST-{index:04d}" for index in range(1, 37)],
        )
        self.assertEqual(len({row["logical_call_id"] for row in self.rows}), 36)
        self.assertEqual(len({row["annotation_case_id"] for row in self.rows}), 36)
        self.assertEqual({row["method_id"] for row in self.rows}, {EXPECTED_METHOD})

    def test_03_attempt_ceiling_and_retry_policy(self) -> None:
        physical_attempts = 0
        for row in self.rows:
            attempts = row["attempt_records"]
            self.assertEqual(row["physical_attempts"], len(attempts))
            self.assertIn(len(attempts), {1, 2})
            physical_attempts += len(attempts)
            if len(attempts) == 2:
                self.assertIn(
                    attempts[0]["validation_error"],
                    {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"},
                )
                self.assertNotEqual(attempts[0]["outcome"], "VALID")
        self.assertEqual(physical_attempts, 36)
        self.assertLessEqual(physical_attempts, 72)

    def test_04_strict_terminal_schema_and_model(self) -> None:
        returned_models = Counter()
        for row in self.rows:
            self.assertEqual(set(row), EXPECTED_TOP_LEVEL_KEYS)
            self.assertEqual(row["execution_status"], "VALID_PREDICTION")
            self.assertEqual(set(row["prediction"]), {"rag_required"})
            self.assertIs(type(row["prediction"]["rag_required"]), bool)
            terminal = row["attempt_records"][-1]
            self.assertEqual(terminal["outcome"], "VALID")
            self.assertIsNone(terminal["validation_error"])
            self.assertEqual(json.loads(terminal["content"]), row["prediction"])
            self.assertEqual(terminal["prediction"], row["prediction"])
            for attempt in row["attempt_records"]:
                returned_models[attempt["returned_model"]] += 1
        self.assertEqual(returned_models, Counter({EXPECTED_MODEL: 36}))

    def test_05_usage_accounting(self) -> None:
        totals = Counter()
        for row in self.rows:
            for attempt in row["attempt_records"]:
                usage = attempt["usage"]
                self.assertIsNotNone(usage)
                self.assertEqual(
                    usage["input_tokens"] + usage["output_tokens"],
                    usage["total_tokens"],
                )
                totals.update(usage)
        self.assertEqual(totals["input_tokens"], 45076)
        self.assertEqual(totals["output_tokens"], 216)
        self.assertEqual(totals["total_tokens"], 45292)

    def test_06_zero_gold_scoring_credentials_and_metrics(self) -> None:
        forbidden_keys = {
            "gold",
            "score",
            "scores",
            "metric",
            "metrics",
            "accuracy",
            "precision",
            "recall",
            "f1",
        }
        for row in self.rows:
            self.assertIs(row["scoring_performed"], False)
            for key in nested_keys(row):
                normalized = key.casefold()
                self.assertFalse(normalized.startswith("gold_"))
                self.assertNotIn(normalized, forbidden_keys)
        self.assertIsNone(SECRET_PATTERN.search(self.raw_output))
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            self.assertNotIn(api_key, self.raw_output)

    def test_07_audit_and_source_manifest_consistency(self) -> None:
        self.assertEqual(self.audit["status"], EXPECTED_STATUS)
        self.assertEqual(self.audit["execution"]["logical_calls"], 36)
        self.assertEqual(self.audit["execution"]["physical_attempts"], 36)
        self.assertEqual(self.audit["execution"]["manual_retries"], 0)
        self.assertEqual(self.audit["output"]["sha256"], EXPECTED_OUTPUT_SHA256)
        self.assertIs(self.audit["boundary_confirmation"]["TEST_Gold_accessed"], False)
        self.assertIs(self.audit["boundary_confirmation"]["scoring_performed"], False)
        package = self.source_manifest["source_package"]
        self.assertEqual(package["package_role"], "RAG_SPECIALIST")
        self.assertEqual(package["package_status"], "FROZEN_UNEXECUTED")
        self.assertEqual(
            package["sha256"],
            "b65d7f3ec53d852fc8d51429353edd9aeee070c66ebe9c29d52273e91dd60374",
        )
        self.assertIs(package["TEST_Gold_included"], False)
        self.assertIs(package["predictions_included"], False)
        self.assertIs(package["scores_included"], False)
        self.assertIs(package["API_keys_included"], False)

    def test_08_status_and_report(self) -> None:
        status_text = STATUS.read_text(encoding="utf-8")
        report_text = REPORT.read_text(encoding="utf-8")
        self.assertIn(EXPECTED_STATUS, status_text)
        self.assertIn(EXPECTED_STATUS, report_text)
        self.assertIn(EXPECTED_OUTPUT_SHA256, status_text)
        self.assertIn(EXPECTED_OUTPUT_SHA256, report_text)
        self.assertIn("TEST Gold accessed: no", report_text)
        self.assertIn("TEST scoring performed: no", report_text)


if __name__ == "__main__":
    unittest.main()
