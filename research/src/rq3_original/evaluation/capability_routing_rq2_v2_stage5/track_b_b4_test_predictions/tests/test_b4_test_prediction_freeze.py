from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "b4_test_terminal_results_v1.jsonl"
SOURCE_PATH = ROOT / "b4_test_execution_source_manifest_v1.json"
AUDIT_PATH = ROOT / "b4_test_execution_audit_v1.json"
FROZEN_MODEL = "gpt-4o-mini-2024-07-18"
FROZEN_METHOD = "R2V2-B4_JOINT_LLM"
RETRYABLE_OUTCOMES = {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}
PREDICTION_FIELDS = {"planning_required", "rag_required", "memory_required"}
SECRET_PATTERN = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~-]{8,})",
    re.IGNORECASE,
)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.name} must contain one JSON object")
    return value


def load_jsonl(path: Path) -> list[dict]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise AssertionError(f"{path.name} must contain only JSON objects")
    return rows


def recursive_keys(value: object):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from recursive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from recursive_keys(nested)


class B4TestPredictionFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_bytes = OUTPUT_PATH.read_bytes()
        cls.rows = load_jsonl(OUTPUT_PATH)
        cls.source = load_json(SOURCE_PATH)
        cls.audit = load_json(AUDIT_PATH)

    def test_source_commitments_are_exact(self) -> None:
        package = self.source["source_package"]
        identity = self.source["frozen_identity"]
        hashes = self.source["authoritative_member_hashes"]
        records = self.source["records"]
        self.assertEqual(
            package["sha256"],
            "96305a3c51d468514e3d4465ddb40100cc53e68e0f5abf2f700e6c71e78fba62",
        )
        self.assertEqual((package["package_role"], package["package_status"]), ("B4", "FROZEN_UNEXECUTED"))
        self.assertEqual(package["test_gold_member_count"], 0)
        self.assertFalse(package["predictions_included"])
        self.assertFalse(package["scores_included"])
        self.assertFalse(package["api_keys_included"])
        self.assertEqual(identity["method_id"], FROZEN_METHOD)
        self.assertEqual(identity["model"], FROZEN_MODEL)
        self.assertEqual(identity["temperature"], 0)
        self.assertEqual(identity["max_tokens"], 64)
        self.assertEqual(identity["sdk_transport_retries"], 0)
        self.assertEqual(identity["manual_retry_maximum"], 1)
        self.assertEqual(
            hashes["prompt_sha256"],
            "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
        )
        self.assertEqual(
            hashes["response_schema_sha256"],
            "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
        )
        self.assertEqual(len(records), 36)
        self.assertEqual([record["ordinal"] for record in records], list(range(1, 37)))
        self.assertEqual(len({record["provider_request_payload_sha256"] for record in records}), 36)
        self.assertEqual(self.source["provider_payload_hash_validation"]["mismatch_count"], 0)
        self.assertFalse(self.source["provider_payload_hash_validation"]["payloads_modified"])

    def test_terminal_record_count_identity_and_order(self) -> None:
        records = self.source["records"]
        self.assertEqual(len(self.rows), 36)
        self.assertEqual(
            [row["annotation_case_id"] for row in self.rows],
            [record["annotation_case_id"] for record in records],
        )
        self.assertEqual(
            [row["logical_case_id"] for row in self.rows],
            [record["logical_case_id"] for record in records],
        )
        self.assertEqual(
            [row["logical_call_id"] for row in self.rows],
            [record["logical_call_id"] for record in records],
        )
        self.assertEqual(len({row["annotation_case_id"] for row in self.rows}), 36)
        self.assertEqual(len({row["logical_call_id"] for row in self.rows}), 36)
        self.assertEqual({row["method_id"] for row in self.rows}, {FROZEN_METHOD})

    def test_all_predictions_are_strict_schema_valid(self) -> None:
        terminal_counts = Counter(row["execution_status"] for row in self.rows)
        self.assertEqual(terminal_counts, Counter({"VALID_PREDICTION": 36}))
        for row in self.rows:
            self.assertIsInstance(row["prediction"], dict)
            self.assertEqual(set(row["prediction"]), PREDICTION_FIELDS)
            self.assertTrue(all(type(value) is bool for value in row["prediction"].values()))

    def test_attempt_limits_retry_policy_and_returned_model(self) -> None:
        physical_attempts = 0
        for row in self.rows:
            attempts = row["attempt_records"]
            self.assertEqual(row["physical_attempts"], len(attempts))
            self.assertIn(len(attempts), (1, 2))
            if len(attempts) == 2:
                self.assertIn(attempts[0]["outcome"], RETRYABLE_OUTCOMES)
            for attempt in attempts:
                if attempt["outcome"] == "VALID":
                    self.assertEqual(attempt["returned_model"], FROZEN_MODEL)
            physical_attempts += len(attempts)
        self.assertLessEqual(physical_attempts, 72)
        self.assertEqual(physical_attempts, self.audit["execution"]["physical_attempts"])
        self.assertEqual(physical_attempts, 36)
        self.assertEqual(self.audit["execution"]["retry_count"], 0)

    def test_output_hash_usage_and_cost_audit(self) -> None:
        output_hash = hashlib.sha256(self.output_bytes).hexdigest()
        self.assertEqual(output_hash, self.audit["output"]["sha256"])
        usages = [
            attempt["usage"]
            for row in self.rows
            for attempt in row["attempt_records"]
            if attempt["usage"] is not None
        ]
        input_tokens = sum(usage["input_tokens"] for usage in usages)
        output_tokens = sum(usage["output_tokens"] for usage in usages)
        total_tokens = sum(usage["total_tokens"] for usage in usages)
        self.assertEqual(
            self.audit["token_accounting"],
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
        )
        self.assertEqual(input_tokens + output_tokens, total_tokens)
        expected_cost = (
            Decimal(input_tokens) * Decimal("0.15")
            + Decimal(output_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)
        self.assertEqual(
            Decimal(str(self.audit["approximate_cost"]["total_cost"])),
            expected_cost,
        )

    def test_zero_gold_zero_scoring_and_no_credentials(self) -> None:
        self.assertTrue(all(row["scoring_performed"] is False for row in self.rows))
        self.assertFalse(self.audit["boundary_confirmation"]["test_gold_accessed"])
        self.assertFalse(self.audit["boundary_confirmation"]["scoring_performed"])
        self.assertFalse(self.audit["boundary_confirmation"]["quality_metrics_calculated"])
        self.assertFalse(self.audit["boundary_confirmation"]["prediction_quality_reviewed"])
        self.assertIsNone(SECRET_PATTERN.search(self.output_bytes))
        output_keys = [key.casefold() for row in self.rows for key in recursive_keys(row)]
        self.assertFalse(any(key == "gold" or key.startswith("gold_") for key in output_keys))


if __name__ == "__main__":
    unittest.main()
