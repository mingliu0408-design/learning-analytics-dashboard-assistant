#!/opt/anaconda3/bin/python3
"""Zero-network mechanical tests for the frozen C4 REAL R3 Shard C evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "execution_output_v1"
PACKAGE_ZIP = Path(
    os.environ.get(
        "C4_R3C_PACKAGE_ZIP",
        "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_EXECUTION_PACKAGE_R3_2026-09-01.zip",
    )
)
EXPECTED_PACKAGE_SHA256 = "16215b04bb875ec8b9b9627df7fb018eff14edf46f5a294049f0dd8442952699"
EXPECTED_MANIFEST_SHA256 = "2bc12fbdf114cda1f52f3438820e2ec706bf60e1c8f0965c4ce610d9853f7ea1"
EXPECTED_AUTHORIZATION_SHA256 = "fcf1596db9dbbf04eec2dfe6a34a2cc375bc732ad7c3d6c9a2c8e16f2e9a5ec1"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_REQUEST_COUNT = 47
EXPECTED_MAXIMUM_ATTEMPTS = 94
EXPECTED_OUTPUT_FILES = {
    "GENERATION_ATTEMPT_JOURNAL.jsonl",
    "GENERATION_ERROR_REGISTRY.jsonl",
    "GENERATION_EXECUTION_REPORT.md",
    "GENERATION_EXECUTION_STATUS.json",
    "GENERATION_PREFLIGHT_RECEIPT.json",
    "GENERATION_TERMINAL_JOURNAL.jsonl",
    "GENERATION_USAGE_AND_COST.json",
}
EXPECTED_ANSWER_HASHES = {
    "C4G3-057CFF4B25B62E9A573A3C33": "4a081c22c1487dfafdca522e7b14d85016eb1a3015fbbc2f102ff7997c2e53d4",
    "C4G3-0946B976553740368895D04A": "dc57a07dc28ac2fcaebfd08a836c1fdd58efeb32c0519bf66a7624e88f1552b9",
    "C4G3-095D8ECF1316BC5899D4E68C": "5adfb27a323bf1c967587a80df06133ef5f7ce4e93a54d761ca653e57a497de9",
}
EXPECTED_ANSWER_SET_SHA256 = "0affb1b3f7f84496eccbd1e04c417dd8e3d39242c92b39c3396c15d6e289c456"
VALID = "VALID_STUDENT_FACING_RESPONSE"
RETRYABLE = {
    "INVALID_JSON",
    "STRICT_SCHEMA_VALIDATION_FAILED",
    "NON_STUDENT_FACING_FORMAT",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


class R3COfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_manifest = load_json(ROOT / "generation_execution_source_manifest_v1.json")
        cls.authorization = load_json(ROOT / "generation_execution_authorization_v1.json")
        cls.preflight = load_json(OUTPUT / "GENERATION_PREFLIGHT_RECEIPT.json")
        cls.execution_status = load_json(OUTPUT / "GENERATION_EXECUTION_STATUS.json")
        cls.usage = load_json(OUTPUT / "GENERATION_USAGE_AND_COST.json")
        cls.attempts = load_jsonl(OUTPUT / "GENERATION_ATTEMPT_JOURNAL.jsonl")
        cls.terminals = load_jsonl(OUTPUT / "GENERATION_TERMINAL_JOURNAL.jsonl")
        cls.errors = load_jsonl(OUTPUT / "GENERATION_ERROR_REGISTRY.jsonl")
        with zipfile.ZipFile(PACKAGE_ZIP) as archive:
            cls.package_names = archive.namelist()
            cls.package_bytes = {name: archive.read(name) for name in cls.package_names}
        cls.requests = [
            json.loads(line)
            for line in cls.package_bytes["BLINDED_REQUESTS.jsonl"].decode("utf-8").splitlines()
            if line
        ]
        validator_scope: dict[str, Any] = {"__name__": "offline_frozen_validator"}
        exec(
            compile(
                cls.package_bytes["c4_real_student_facing_response_validator_v1.py"],
                "c4_real_student_facing_response_validator_v1.py",
                "exec",
            ),
            validator_scope,
        )
        cls.validate_answer_text = staticmethod(validator_scope["validate_answer_text"])

    def test_01_package_zip_and_member_identities(self) -> None:
        self.assertEqual(sha256_bytes(PACKAGE_ZIP.read_bytes()), EXPECTED_PACKAGE_SHA256)
        expected_members = self.source_manifest["package_member_sha256"]
        self.assertEqual(set(self.package_names), set(expected_members))
        self.assertEqual(len(self.package_names), 12)
        self.assertEqual(len(self.package_names), len(set(self.package_names)))
        for name, expected_hash in expected_members.items():
            self.assertEqual(sha256_bytes(self.package_bytes[name]), expected_hash)

    def test_02_exact_blinded_manifest_identity(self) -> None:
        self.assertEqual(
            sha256_bytes(self.package_bytes["BLINDED_REQUESTS.jsonl"]),
            EXPECTED_MANIFEST_SHA256,
        )
        package_sources = json.loads(self.package_bytes["PACKAGE_SOURCE_HASHES.json"])
        self.assertEqual(package_sources["blinded_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(package_sources["package_id"], "C4_REAL_GENERATION_SHARD_C_R3_20260901")
        self.assertEqual(package_sources["shard"], "C")

    def test_03_strict_authorization_record_shape(self) -> None:
        expected_fields = {
            "schema_version",
            "authorization_id",
            "authorized_by",
            "authorized_at_utc",
            "package_id",
            "shard",
            "request_count",
            "maximum_physical_attempts",
            "package_sha256",
            "blinded_manifest_sha256",
            "status",
        }
        self.assertEqual(set(self.authorization), expected_fields)
        self.assertEqual(len(self.authorization), 11)
        self.assertEqual(
            sha256_bytes((ROOT / "generation_execution_authorization_v1.json").read_bytes()),
            EXPECTED_AUTHORIZATION_SHA256,
        )
        self.assertEqual(self.authorization["status"], "AUTHORIZED")
        self.assertEqual(self.authorization["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(self.authorization["maximum_physical_attempts"], EXPECTED_MAXIMUM_ATTEMPTS)

    def test_04_exact_request_population_and_payload_hashes(self) -> None:
        self.assertEqual(len(self.requests), EXPECTED_REQUEST_COUNT)
        self.assertEqual(len({row["logical_generation_request_id"] for row in self.requests}), 47)
        self.assertEqual(len({row["response_blind_id"] for row in self.requests}), 47)
        self.assertEqual(len({row["provider_payload_sha256"] for row in self.requests}), 47)
        for row in self.requests:
            self.assertEqual(
                sha256_bytes(canonical_bytes(row["provider_payload"])),
                row["provider_payload_sha256"],
            )

    def test_05_output_directory_exclusivity(self) -> None:
        actual = {path.name for path in OUTPUT.iterdir() if path.is_file()}
        self.assertEqual(actual, EXPECTED_OUTPUT_FILES)
        self.assertFalse(any(path.is_dir() for path in OUTPUT.iterdir()))

    def test_06_preflight_receipt(self) -> None:
        self.assertEqual(self.preflight["status"], "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION")
        self.assertFalse(self.preflight["runtime_constructed"])
        self.assertFalse(self.preflight["client_constructed"])
        self.assertFalse(self.preflight["automatic_resume"])
        self.assertEqual(self.preflight["judge_calls"], 0)
        self.assertEqual(self.preflight["request_count"], 47)
        self.assertEqual(self.preflight["maximum_physical_attempts"], 94)
        self.assertEqual(self.preflight["package_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(self.preflight["blinded_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(self.preflight["authorization_record_sha256"], EXPECTED_AUTHORIZATION_SHA256)

    def test_07_attempt_journal_ordering(self) -> None:
        self.assertEqual(
            [(row["logical_order"], row["attempt_number"]) for row in self.attempts],
            [(1, 1), (2, 1), (3, 1), (4, 1), (4, 2)],
        )
        grouped: dict[int, list[int]] = defaultdict(list)
        for row in self.attempts:
            grouped[row["logical_order"]].append(row["attempt_number"])
        self.assertTrue(all(numbers in ([1], [1, 2]) for numbers in grouped.values()))

    def test_08_terminal_uniqueness(self) -> None:
        self.assertEqual(len(self.terminals), 4)
        self.assertEqual(len({row["logical_generation_request_id"] for row in self.terminals}), 4)
        self.assertEqual(len({row["response_blind_id"] for row in self.terminals}), 4)
        self.assertEqual([row["logical_order"] for row in self.terminals], [1, 2, 3, 4])

    def test_09_frozen_semantic_validator_results(self) -> None:
        observed = Counter()
        for row in self.attempts:
            outer = json.loads(row["raw_response_content"])
            self.assertEqual(set(outer), {"answer_text"})
            semantic_status = self.validate_answer_text(outer["answer_text"])
            self.assertEqual(semantic_status, row["student_facing_validation_status"])
            observed[semantic_status] += 1
        self.assertEqual(observed[VALID], 3)
        self.assertEqual(observed["RAW_INTERNAL_STRUCTURE"], 2)

    def test_10_strict_parsed_output_shape(self) -> None:
        valid_attempts = [row for row in self.attempts if row["retryable_failure"] is None]
        self.assertEqual(len(valid_attempts), 3)
        for row in valid_attempts:
            self.assertEqual(set(row["parsed_output"]), {"answer_text"})
        for row in self.terminals:
            if row["terminal_status"] == VALID:
                self.assertEqual(set(row["parsed_output"]), {"answer_text"})

    def test_11_nonempty_answer_text(self) -> None:
        valid = [row for row in self.terminals if row["terminal_status"] == VALID]
        self.assertEqual(len(valid), 3)
        for row in valid:
            answer_text = row["parsed_output"]["answer_text"]
            self.assertIsInstance(answer_text, str)
            self.assertTrue(answer_text.strip())

    def test_12_answer_text_hashes_and_answer_set_hash(self) -> None:
        entries = []
        observed = {}
        for row in self.terminals:
            if row["terminal_status"] != VALID:
                continue
            answer_hash = sha256_bytes(row["parsed_output"]["answer_text"].encode("utf-8"))
            observed[row["logical_generation_request_id"]] = answer_hash
            entries.append(
                {
                    "logical_generation_request_id": row["logical_generation_request_id"],
                    "response_blind_id": row["response_blind_id"],
                    "answer_text_sha256": answer_hash,
                }
            )
        self.assertEqual(observed, EXPECTED_ANSWER_HASHES)
        self.assertEqual(sha256_bytes(canonical_bytes(entries)), EXPECTED_ANSWER_SET_SHA256)

    def test_13_returned_model_identity(self) -> None:
        self.assertEqual(len(self.attempts), 5)
        self.assertTrue(all(row["requested_model"] == EXPECTED_MODEL for row in self.attempts))
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in self.attempts))

    def test_14_retry_policy_and_byte_identity(self) -> None:
        retries = [row for row in self.attempts if row["attempt_number"] == 2]
        self.assertEqual(len(retries), 1)
        retry = retries[0]
        initial = next(
            row
            for row in self.attempts
            if row["logical_order"] == retry["logical_order"] and row["attempt_number"] == 1
        )
        self.assertIn(initial["retryable_failure"], RETRYABLE)
        self.assertEqual(initial["retryable_failure"], "NON_STUDENT_FACING_FORMAT")
        self.assertEqual(retry["retryable_failure"], "NON_STUDENT_FACING_FORMAT")
        self.assertEqual(initial["provider_payload_sha256"], retry["provider_payload_sha256"])
        frozen = self.requests[retry["logical_order"] - 1]
        self.assertEqual(retry["provider_payload_sha256"], frozen["provider_payload_sha256"])

    def test_15_physical_attempt_ceiling(self) -> None:
        self.assertEqual(len(self.attempts), 5)
        self.assertEqual(self.execution_status["physical_attempt_count"], 5)
        self.assertLessEqual(len(self.attempts), EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertTrue(all(row["attempt_number"] in (1, 2) for row in self.attempts))

    def test_16_fail_closed_incomplete_status(self) -> None:
        self.assertEqual(self.execution_status["status"], "INCOMPLETE_FAIL_CLOSED")
        self.assertEqual(self.execution_status["stop_reason"], "SECOND_INVALID_RESPONSE")
        self.assertEqual(self.execution_status["valid_response_count"], 3)
        self.assertEqual(self.execution_status["incomplete_logical_request_count"], 1)
        self.assertEqual(self.execution_status["unattempted_logical_request_count"], 43)
        self.assertTrue(self.execution_status["continuation_requires_new_direct_authorization"])
        self.assertFalse(self.execution_status["automatic_resume"])
        self.assertEqual(max(row["logical_order"] for row in self.attempts), 4)
        incomplete = [row for row in self.terminals if row["terminal_status"].startswith("INCOMPLETE")]
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["logical_order"], 4)
        self.assertEqual(incomplete[0]["terminal_invalid_category"], "NON_STUDENT_FACING_FORMAT")

    def test_17_usage_arithmetic(self) -> None:
        for row in self.attempts:
            self.assertEqual(row["prompt_tokens"] + row["completion_tokens"], row["total_tokens"])
        self.assertEqual(sum(row["prompt_tokens"] for row in self.attempts), self.usage["prompt_tokens"])
        self.assertEqual(
            sum(row["cached_input_tokens"] for row in self.attempts),
            self.usage["cached_input_tokens"],
        )
        self.assertEqual(
            sum(row["completion_tokens"] for row in self.attempts),
            self.usage["completion_tokens"],
        )
        self.assertEqual(sum(row["total_tokens"] for row in self.attempts), self.usage["total_tokens"])
        self.assertEqual(self.usage["prompt_tokens"] + self.usage["completion_tokens"], self.usage["total_tokens"])
        self.assertTrue(self.usage["usage_arithmetic_valid"])
        self.assertEqual(self.usage["provider_calls_observed"], 5)

    def test_18_secret_absence(self) -> None:
        files = [path for path in ROOT.rglob("*") if path.is_file()]
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            secret_bytes = api_key.encode("utf-8")
            for path in files:
                self.assertNotIn(secret_bytes, path.read_bytes(), "API key value found in artifact")
        key_pattern = re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")
        for path in files:
            self.assertIsNone(key_pattern.search(path.read_bytes()), f"key-like value found in {path.name}")

    def test_19_absence_of_restricted_identity_and_evaluation_fields(self) -> None:
        forbidden_parts = {
            "gold",
            "scenario",
            "mode",
            "condition",
            "route",
            "rating",
            "score",
            "hmac",
        }
        json_values = [self.preflight, self.execution_status, self.usage, *self.attempts, *self.terminals, *self.errors]
        for value in json_values:
            for key, child in walk_keys(value):
                if key in {"judge_calls", "scoring_calls"}:
                    self.assertEqual(child, 0)
                    continue
                parts = set(re.split(r"[^a-z0-9]+", key.lower())) - {""}
                self.assertTrue(parts.isdisjoint(forbidden_parts), f"forbidden field: {key}")
                self.assertNotEqual(key.lower(), "reference_answer")
                self.assertNotEqual(key.lower(), "expected_outcome")

    def test_20_future_r3_integration_compatibility_is_partial_and_blocked(self) -> None:
        valid = [row for row in self.terminals if row["terminal_status"] == VALID]
        self.assertEqual(len(valid), 3)
        for row in valid:
            self.assertIsInstance(row["logical_generation_request_id"], str)
            self.assertIsInstance(row["response_blind_id"], str)
            self.assertRegex(row["provider_payload_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(set(row["parsed_output"]), {"answer_text"})
        self.assertEqual(self.execution_status["status"], "INCOMPLETE_FAIL_CLOSED")
        self.assertGreater(self.execution_status["unattempted_logical_request_count"], 0)
        self.assertTrue(self.execution_status["continuation_requires_new_direct_authorization"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
