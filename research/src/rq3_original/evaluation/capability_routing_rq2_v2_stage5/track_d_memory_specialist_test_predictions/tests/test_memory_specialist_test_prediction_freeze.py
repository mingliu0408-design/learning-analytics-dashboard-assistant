from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


TRACK_DIR = Path(__file__).resolve().parents[1]
RESULTS_PATH = TRACK_DIR / "memory_specialist_test_terminal_results_v1.jsonl"
SOURCE_MANIFEST_PATH = TRACK_DIR / "memory_specialist_test_execution_source_manifest_v1.json"
AUDIT_PATH = TRACK_DIR / "memory_specialist_test_execution_audit_v1.json"
STATUS_PATH = TRACK_DIR / "STATUS.md"

EXPECTED_OUTPUT_SHA256 = "a731107848b8816a67cd889e411ab2cf82a9c4dfbaff903dd5f4cdae15fa2cb5"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_METHOD = "R2V2-MEMORY_SPECIALIST"
EXPECTED_STATUS = "MEMORY_SPECIALIST_TEST_PREDICTIONS_FROZEN_UNSCORED"
SECRET_PATTERN = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{20,})",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def strict_prediction(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"memory_required"}
        and type(value["memory_required"]) is bool
    )


def nested_keys(value: object):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from nested_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from nested_keys(nested)


class MemorySpecialistTestPredictionFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = load_jsonl(RESULTS_PATH)
        cls.source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    def test_01_review_surface_is_exactly_allowlisted(self) -> None:
        expected = {
            "MEMORY_SPECIALIST_TEST_EXECUTION_REPORT.md",
            "STATUS.md",
            "memory_specialist_test_execution_audit_v1.json",
            "memory_specialist_test_execution_source_manifest_v1.json",
            "memory_specialist_test_terminal_results_v1.jsonl",
            "tests/test_memory_specialist_test_prediction_freeze.py",
        }
        observed = {
            path.relative_to(TRACK_DIR).as_posix()
            for path in TRACK_DIR.rglob("*")
            if path.is_file()
        }
        self.assertEqual(observed, expected)
        self.assertFalse(any(path.is_symlink() for path in TRACK_DIR.rglob("*")))
        self.assertFalse(Path(str(RESULTS_PATH) + ".partial").exists())

    def test_02_terminal_coverage_identity_and_schema(self) -> None:
        self.assertEqual(len(self.results), 36)
        self.assertEqual(len({row["annotation_case_id"] for row in self.results}), 36)
        self.assertEqual(len({row["logical_call_id"] for row in self.results}), 36)
        self.assertEqual(len({row["logical_case_id"] for row in self.results}), 36)
        for row in self.results:
            self.assertEqual(row["method_id"], EXPECTED_METHOD)
            self.assertEqual(row["execution_status"], "VALID_PREDICTION")
            self.assertIs(row["scoring_performed"], False)
            self.assertTrue(strict_prediction(row["prediction"]))

    def test_03_attempt_ceiling_retry_policy_and_model_identity(self) -> None:
        physical_attempts = sum(int(row["physical_attempts"]) for row in self.results)
        self.assertEqual(physical_attempts, 36)
        self.assertLessEqual(physical_attempts, 72)
        for row in self.results:
            attempts = row["attempt_records"]
            self.assertEqual(row["physical_attempts"], len(attempts))
            self.assertIn(len(attempts), {1, 2})
            if len(attempts) == 2:
                self.assertIn(
                    attempts[0]["validation_error"],
                    {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"},
                )
                self.assertNotEqual(attempts[0]["outcome"], "VALID")
            for attempt in attempts:
                self.assertEqual(attempt["returned_model"], EXPECTED_MODEL)
                self.assertEqual(attempt["outcome"], "VALID")
                self.assertIsNone(attempt["validation_error"])
                self.assertIsNone(attempt["provider_error"])
                self.assertTrue(strict_prediction(attempt["prediction"]))
                self.assertEqual(json.loads(attempt["content"]), attempt["prediction"])

    def test_04_zero_gold_scoring_and_credentials(self) -> None:
        raw_results = RESULTS_PATH.read_text(encoding="utf-8")
        self.assertIsNone(SECRET_PATTERN.search(raw_results))
        self.assertTrue(
            all("gold" not in key.casefold() for row in self.results for key in nested_keys(row))
        )
        self.assertTrue(all(row["scoring_performed"] is False for row in self.results))
        governance = self.audit["governance"]
        self.assertIs(governance["test_gold_accessed"], False)
        self.assertIs(governance["scoring_performed"], False)
        self.assertIs(governance["quality_metrics_calculated"], False)
        self.assertIs(governance["credentials_captured"], False)

    def test_05_usage_and_cost_are_attempt_derived(self) -> None:
        usage_rows = [attempt["usage"] for row in self.results for attempt in row["attempt_records"]]
        input_tokens = sum(int(usage["input_tokens"]) for usage in usage_rows)
        output_tokens = sum(int(usage["output_tokens"]) for usage in usage_rows)
        total_tokens = sum(int(usage["total_tokens"]) for usage in usage_rows)
        self.assertEqual((input_tokens, output_tokens, total_tokens), (45364, 216, 45580))
        usage_audit = self.audit["usage_and_cost"]
        self.assertEqual(usage_audit["input_tokens"], input_tokens)
        self.assertEqual(usage_audit["output_tokens"], output_tokens)
        self.assertEqual(usage_audit["total_tokens"], total_tokens)
        expected_cost = input_tokens * 0.15 / 1_000_000 + output_tokens * 0.60 / 1_000_000
        self.assertAlmostEqual(usage_audit["estimated_total_cost_usd_at_standard_rate"], expected_cost)

    def test_06_frozen_and_output_hashes_are_coherent(self) -> None:
        self.assertEqual(sha256_file(RESULTS_PATH), EXPECTED_OUTPUT_SHA256)
        self.assertEqual(self.source_manifest["execution"]["output_sha256"], EXPECTED_OUTPUT_SHA256)
        self.assertEqual(self.audit["output"]["sha256"], EXPECTED_OUTPUT_SHA256)
        identity = self.source_manifest["frozen_identity"]
        self.assertEqual(identity["method_id"], EXPECTED_METHOD)
        self.assertEqual(identity["model"], EXPECTED_MODEL)
        self.assertEqual(
            identity["prompt_sha256"],
            "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
        )
        self.assertEqual(
            identity["schema_sha256"],
            "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
        )

    def test_07_terminal_status_is_unscored_freeze(self) -> None:
        self.assertEqual(self.source_manifest["status"], EXPECTED_STATUS)
        self.assertEqual(self.audit["status"], EXPECTED_STATUS)
        self.assertIn(EXPECTED_STATUS, STATUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.audit["execution_coverage"]["terminal_records"], 36)
        self.assertEqual(self.audit["attempts_and_retries"]["physical_attempts"], 36)
        self.assertEqual(self.audit["provider_and_structured_output_errors"]["provider_errors"], 0)


if __name__ == "__main__":
    unittest.main()
