#!/opt/anaconda3/bin/python3
"""Zero-network mechanical tests for C4 REAL Judge B continuation R3."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import types
import unittest
import zipfile


EXPECTED_PACKAGE_SHA256 = (
    "0a9e04b7646391782a49a5e09283ab7347d7d16544bfd1a0f5a71b71448e00c4"
)
EXPECTED_MANIFEST_SHA256 = (
    "e76cbf03f75487af987cba768dc2f4f128efa1f9c9b0d58168d2f7a350e943d6"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "b18501411fc256caeec899852ae1a46030837f6debbb677a57b22a67e65a39a6"
)
EXPECTED_TERMINAL_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
EXPECTED_PARSED_SET_SHA256 = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)
EXPECTED_PACKAGE_ID = "C4_REAL_JUDGE_SHARD_B_CONTINUATION_R3_20260902"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-J3B-CONTINUATION-20260902"
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_FIRST_REQUEST_ID = "C4J1-82EC5072C57932A5BB9E01DC"
EXPECTED_FIRST_RESULT_ID = "R3B-8F11552F6C1CD1326D6A"
EXPECTED_FIRST_PAYLOAD_SHA256 = (
    "178551a9ef59ec32aed0b2f508ed09c76d72c625b6b72e48fe145dc9c6c1e0fa"
)
EXPECTED_PACKAGE_MEMBERS = {
    "APPLICABILITY_CONTRACT.json",
    "BLINDED_JUDGE_REQUESTS.jsonl",
    "EXECUTION_CONTRACT.json",
    "JUDGE_CONFIGURATION.json",
    "JUDGE_PROMPT.txt",
    "JUDGE_SCHEMA.json",
    "PACKAGE_SOURCE_HASHES.json",
    "PRIMARY_RUBRIC.json",
    "README.md",
    "judge_execution_runner_v3.py",
    "judge_result_parser_v3.py",
    "test_package.py",
    "validate_package.py",
}
EXPECTED_MEMBER_HASHES = {
    "APPLICABILITY_CONTRACT.json": (
        "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e"
    ),
    "BLINDED_JUDGE_REQUESTS.jsonl": EXPECTED_MANIFEST_SHA256,
    "EXECUTION_CONTRACT.json": (
        "2c9b68aef58523f9d5b3540fd142c38e1c34d5460a4a8e1a587135a8849df6e4"
    ),
    "JUDGE_CONFIGURATION.json": (
        "c36f87d4109ce05e6549d772e16ec04afbfd4c524f494c783d5ba87d33b86e59"
    ),
    "JUDGE_PROMPT.txt": (
        "0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e"
    ),
    "JUDGE_SCHEMA.json": (
        "5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a"
    ),
    "PACKAGE_SOURCE_HASHES.json": (
        "8398e78027d0356f3cf8490908e17b1e8f40e6aecf8f2a768f7ce4edc6eaf2b3"
    ),
    "PRIMARY_RUBRIC.json": (
        "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
    ),
    "README.md": (
        "1dd40d107aa9a1a175fe5c72b03ffe057afd9475b87d82f7fd4ad99707c90b55"
    ),
    "judge_execution_runner_v3.py": (
        "db013064a84004b2a7ba8eefd2061736a5e88a402403b38d28dc274d46ca5cf5"
    ),
    "judge_result_parser_v3.py": (
        "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb"
    ),
    "test_package.py": (
        "8577c39a6b2ff32bc39b9b4bc85f2d7a615d663a6f043ea23e6459f51020df3e"
    ),
    "validate_package.py": (
        "db5e5c5ae7b8729a3401a19139fa17b5c07409779b1c735236f5fdd70b8d4598"
    ),
}
EXPECTED_OUTPUT_FILES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl",
    "JUDGE_ERROR_REGISTRY.jsonl",
    "JUDGE_EXECUTION_STATUS.json",
    "JUDGE_PREFLIGHT_START_RECEIPT.json",
    "JUDGE_STATUS_JOURNAL.jsonl",
    "JUDGE_TERMINAL_JOURNAL.jsonl",
}
EXPECTED_OUTPUT_HASHES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "14298ba378b6bf2d09068d320bfa1c6810a1bdb40852d7aa7ddf6c6f1af182be"
    ),
    "JUDGE_ERROR_REGISTRY.jsonl": (
        "ba5664313984e12a764cf95a225896c42c8d878fffa1f69491a3cb84262aa104"
    ),
    "JUDGE_EXECUTION_STATUS.json": (
        "ae8985388e0031abb7ad59ccff8c6f00aef5ed90523845d4ceda9001f8ffd18b"
    ),
    "JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "550c174f380bb9a664a0689bd3a268a4c4ee84592cce66b0ae5635bdb6c9e964"
    ),
    "JUDGE_STATUS_JOURNAL.jsonl": (
        "a343a9bab324f325eccd6ed01fa6e9588dd63439dbf5e4f8846668292312ae36"
    ),
    "JUDGE_TERMINAL_JOURNAL.jsonl": EXPECTED_TERMINAL_SHA256,
}
AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorized_by",
    "authorized_at_utc",
    "package_id",
    "shard_id",
    "request_count",
    "maximum_physical_attempts",
    "package_zip_sha256",
    "blinded_judge_manifest_sha256",
    "status",
}
PRIMARY_CRITERIA = (
    "CLARITY",
    "PERSONALISATION",
    "ACTIONABILITY",
    "CONTEXT_AWARENESS",
    "MOTIVATION_AND_ENGAGEMENT",
    "RELIABILITY",
    "MULTI_PAGE_COHESIVENESS",
    "ERROR_HANDLING",
)
SCORE_FIELDS = {
    "CLARITY": "clarity",
    "PERSONALISATION": "personalisation",
    "ACTIONABILITY": "actionability",
    "CONTEXT_AWARENESS": "context_awareness",
    "MOTIVATION_AND_ENGAGEMENT": "motivation_and_engagement",
    "RELIABILITY": "reliability",
    "MULTI_PAGE_COHESIVENESS": "multi_page_cohesiveness",
    "ERROR_HANDLING": "error_handling",
}
PARSED_FIELDS = {
    *SCORE_FIELDS.values(),
    "response_blind_id",
    "evidence_faithfulness",
    "unsupported_claim_count",
    "overall_applicable_mean",
    "criterion_rationales",
    "schema_version",
}
TERMINAL_FIELDS = {
    "schema_version",
    "terminal_status",
    "logical_order",
    "logical_judge_request_id",
    "judge_result_blind_id",
    "provider_payload_sha256",
    "physical_attempts",
    "parsed_semantic_result",
    "terminal_at_utc",
    "request_timeout_seconds",
    "provider_response_id",
    "returned_model",
    "system_fingerprint",
    "finish_reason",
    "prompt_tokens",
    "cached_input_tokens",
    "completion_tokens",
    "total_tokens",
}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def strict_json(data: str | bytes) -> dict[str, object]:
    value = json.loads(data, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value


def read_jsonl_bytes(data: bytes) -> list[dict[str, object]]:
    return [strict_json(line) for line in data.splitlines() if line.strip()]


def read_jsonl_file(path: Path) -> list[dict[str, object]]:
    return read_jsonl_bytes(path.read_bytes())


def collect_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).casefold())
            keys.update(collect_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(collect_keys(child))
    return keys


def load_parser_module(parser_bytes: bytes) -> types.ModuleType:
    module = types.ModuleType("frozen_judge_result_parser_v3")
    exec(compile(parser_bytes, "judge_result_parser_v3.py", "exec"), module.__dict__)
    return module


class JudgeContinuationBArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact_root = Path(__file__).resolve().parent
        cls.output_dir = cls.artifact_root / "execution_output_v1"
        cls.authorization_path = (
            cls.artifact_root / "judge_execution_authorization_v1.json"
        )
        cls.source_manifest_path = (
            cls.artifact_root / "judge_continuation_source_manifest_v1.json"
        )
        cls.package_zip = PACKAGE_ZIP.resolve()
        with zipfile.ZipFile(cls.package_zip) as archive:
            cls.package_infos = archive.infolist()
            cls.package_bytes = {
                info.filename: archive.read(info.filename)
                for info in cls.package_infos
                if not info.is_dir()
            }
        cls.requests = read_jsonl_bytes(
            cls.package_bytes["BLINDED_JUDGE_REQUESTS.jsonl"]
        )
        cls.request_by_order = {
            row["original_logical_order"]: row for row in cls.requests
        }
        cls.configuration = strict_json(
            cls.package_bytes["JUDGE_CONFIGURATION.json"]
        )
        cls.execution_contract = strict_json(
            cls.package_bytes["EXECUTION_CONTRACT.json"]
        )
        cls.authorization = strict_json(cls.authorization_path.read_bytes())
        cls.source_manifest = strict_json(cls.source_manifest_path.read_bytes())
        cls.attempts = read_jsonl_file(
            cls.output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl"
        )
        cls.starts = [row for row in cls.attempts if row["event"] == "ATTEMPT_STARTED"]
        cls.returns = [row for row in cls.attempts if row["event"] == "ATTEMPT_RETURNED"]
        cls.errors = read_jsonl_file(
            cls.output_dir / "JUDGE_ERROR_REGISTRY.jsonl"
        )
        cls.status_events = read_jsonl_file(
            cls.output_dir / "JUDGE_STATUS_JOURNAL.jsonl"
        )
        cls.terminals = read_jsonl_file(
            cls.output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl"
        )
        cls.status = strict_json(
            (cls.output_dir / "JUDGE_EXECUTION_STATUS.json").read_bytes()
        )
        cls.preflight = strict_json(
            (cls.output_dir / "JUDGE_PREFLIGHT_START_RECEIPT.json").read_bytes()
        )
        cls.parser = load_parser_module(
            cls.package_bytes["judge_result_parser_v3.py"]
        )

    def test_01_package_archive_identity_and_allowlist(self) -> None:
        self.assertEqual(sha256_file(self.package_zip), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(len(self.package_infos), 13)
        self.assertTrue(all(not info.is_dir() for info in self.package_infos))
        self.assertEqual(set(self.package_bytes), EXPECTED_PACKAGE_MEMBERS)
        self.assertTrue(all("/" not in name and "\\" not in name for name in self.package_bytes))

    def test_02_package_member_hashes(self) -> None:
        self.assertEqual(
            {name: sha256_bytes(data) for name, data in self.package_bytes.items()},
            EXPECTED_MEMBER_HASHES,
        )
        declared = strict_json(self.package_bytes["PACKAGE_SOURCE_HASHES.json"])
        self.assertEqual(
            declared["member_sha256"],
            {
                name: digest
                for name, digest in EXPECTED_MEMBER_HASHES.items()
                if name != "PACKAGE_SOURCE_HASHES.json"
            },
        )

    def test_03_blinded_request_population_and_identity(self) -> None:
        self.assertEqual(len(self.requests), 11)
        self.assertEqual(sorted(self.request_by_order), list(range(39, 50)))
        self.assertEqual(
            {row["continuation_shard_id"] for row in self.requests},
            {"B_CONTINUATION"},
        )
        self.assertEqual({row["source_shard_id"] for row in self.requests}, {"B"})
        self.assertEqual(
            len({row["logical_judge_request_id"] for row in self.requests}), 11
        )
        self.assertEqual(
            len({row["judge_result_blind_id"] for row in self.requests}), 11
        )
        self.assertEqual(
            sum(row["estimated_input_tokens"] for row in self.requests), 36571
        )

    def test_04_frozen_provider_payload_identity(self) -> None:
        for row in self.requests:
            payload = row["provider_payload"]
            self.assertEqual(
                set(payload),
                {
                    "model",
                    "messages",
                    "temperature",
                    "max_tokens",
                    "stream",
                    "response_format",
                },
            )
            self.assertEqual(payload["model"], EXPECTED_MODEL)
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], 2048)
            self.assertIs(payload["stream"], False)
            self.assertNotIn("tools", payload)
            self.assertEqual(
                sha256_bytes(canonical_json_bytes(payload)),
                row["provider_payload_sha256"],
            )

    def test_05_frozen_configuration_and_contract(self) -> None:
        config = self.configuration
        contract = self.execution_contract
        self.assertEqual(config["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(config["shard_id"], "B_CONTINUATION")
        self.assertEqual(config["source_shard_id"], "B")
        self.assertEqual(config["original_logical_orders"], list(range(39, 50)))
        self.assertEqual(config["model"], EXPECTED_MODEL)
        self.assertEqual(config["endpoint"], "OpenAI Chat Completions")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 2048)
        self.assertIs(config["streaming"], False)
        self.assertEqual(config["tools"], "NONE")
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertEqual(config["request_timeout_seconds"], 120.0)
        self.assertEqual(config["minimum_seconds_between_initial_request_starts"], 15.0)
        self.assertEqual(contract["maximum_physical_attempts"], 22)
        self.assertIs(contract["timeout_is_non_retryable"], True)
        self.assertIs(contract["automatic_resume"], False)

    def test_06_authorization_shape_hash_and_binding(self) -> None:
        self.assertEqual(
            sha256_file(self.authorization_path), EXPECTED_AUTHORIZATION_SHA256
        )
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(
            self.authorization["schema_version"],
            "c4-real-judge-execution-authorization-r3-v1",
        )
        self.assertEqual(
            self.authorization["authorization_id"], EXPECTED_AUTHORIZATION_ID
        )
        self.assertEqual(self.authorization["authorized_by"], "Ming Liu")
        self.assertRegex(
            self.authorization["authorized_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertEqual(self.authorization["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.authorization["shard_id"], "B_CONTINUATION")
        self.assertEqual(self.authorization["request_count"], 11)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 22)
        self.assertEqual(
            self.authorization["package_zip_sha256"], EXPECTED_PACKAGE_SHA256
        )
        self.assertEqual(
            self.authorization["blinded_judge_manifest_sha256"],
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(self.authorization["status"], "AUTHORIZED")

    def test_07_output_directory_exclusivity_and_allowlist(self) -> None:
        self.assertEqual(
            sorted(self.artifact_root.glob("execution_output_v*")),
            [self.output_dir],
        )
        self.assertEqual(
            {path.name for path in self.output_dir.iterdir() if path.is_file()},
            EXPECTED_OUTPUT_FILES,
        )
        self.assertTrue(all(path.is_file() for path in self.output_dir.iterdir()))

    def test_08_durable_output_byte_hashes(self) -> None:
        self.assertEqual(
            {
                name: sha256_file(self.output_dir / name)
                for name in EXPECTED_OUTPUT_FILES
            },
            EXPECTED_OUTPUT_HASHES,
        )

    def test_09_preflight_receipt(self) -> None:
        receipt = self.preflight
        self.assertEqual(
            receipt["status"],
            "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
        )
        self.assertEqual(receipt["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(receipt["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(receipt["shard_id"], "B_CONTINUATION")
        self.assertEqual(receipt["request_count"], 11)
        self.assertEqual(receipt["maximum_physical_attempts"], 22)
        self.assertEqual(receipt["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            receipt["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256
        )
        self.assertEqual(receipt["request_timeout_seconds"], 120.0)
        self.assertEqual(receipt["judge_calls_at_receipt_write"], 0)
        self.assertIs(receipt["runtime_constructed_at_receipt_write"], False)
        self.assertIs(receipt["client_constructed_at_receipt_write"], False)
        self.assertIs(receipt["automatic_resume"], False)

    def test_10_runtime_and_timeout_identity(self) -> None:
        runtime_events = [
            row for row in self.status_events if row["status"] == "RUNTIME_VALIDATED"
        ]
        self.assertEqual(len(runtime_events), 1)
        runtime = runtime_events[0]["runtime"]
        self.assertEqual(runtime["python_executable"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertIs(runtime["api_key_presence_checked_only"], True)
        self.assertIs(runtime["api_key_value_recorded"], False)
        client_events = [
            row
            for row in self.status_events
            if row["status"]
            == "CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED"
        ]
        self.assertEqual(len(client_events), 1)
        client = client_events[0]["client_configuration"]
        self.assertEqual(client["client_max_retries"], 0)
        self.assertEqual(client["request_timeout_seconds"], 120.0)
        self.assertEqual(
            client["timeout_components_seconds"],
            {"connect": 120.0, "pool": 120.0, "read": 120.0, "write": 120.0},
        )
        self.assertIs(
            client["transport_configuration_verified_before_provider_call"], True
        )

    def test_11_execution_status_is_fail_closed_incomplete(self) -> None:
        self.assertEqual(self.status["status"], "INCOMPLETE")
        self.assertEqual(self.status["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.status["shard_id"], "B_CONTINUATION")
        self.assertEqual(self.status["request_count"], 11)
        self.assertEqual(self.status["valid_terminal_count"], 0)
        self.assertEqual(self.status["physical_attempts"], 1)
        self.assertEqual(self.status["judge_calls"], 1)
        self.assertEqual(self.status["request_timeout_seconds"], 120.0)
        self.assertIs(self.status["automatic_resume"], False)
        self.assertIs(
            self.status["continuation_requires_new_direct_authorization"], True
        )

    def test_12_attempt_journal_is_exactly_one_start(self) -> None:
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(len(self.returns), 0)
        start = self.starts[0]
        self.assertEqual(start["logical_order"], 39)
        self.assertEqual(start["logical_judge_request_id"], EXPECTED_FIRST_REQUEST_ID)
        self.assertEqual(start["judge_result_blind_id"], EXPECTED_FIRST_RESULT_ID)
        self.assertEqual(start["attempt_number"], 1)
        self.assertEqual(start["judge_calls_started"], 1)
        self.assertEqual(start["request_timeout_seconds"], 120.0)

    def test_13_attempt_is_bound_to_first_frozen_payload(self) -> None:
        request = self.request_by_order[39]
        start = self.starts[0]
        self.assertEqual(request["logical_judge_request_id"], EXPECTED_FIRST_REQUEST_ID)
        self.assertEqual(request["judge_result_blind_id"], EXPECTED_FIRST_RESULT_ID)
        self.assertEqual(request["provider_payload_sha256"], EXPECTED_FIRST_PAYLOAD_SHA256)
        self.assertEqual(start["provider_payload_sha256"], EXPECTED_FIRST_PAYLOAD_SHA256)

    def test_14_rate_limit_error_registry_is_sanitized(self) -> None:
        self.assertEqual(len(self.errors), 1)
        error = self.errors[0]
        self.assertEqual(error["error_category"], "RateLimitError")
        self.assertEqual(error["error_code"], "credit_balance_exhausted")
        self.assertIsNone(error["error_parameter"])
        self.assertEqual(error["phase"], "PROVIDER_CALL")
        self.assertEqual(error["terminal_policy"], "STOP_ENTIRE_SHARD")
        self.assertIs(error["continuation_requires_new_direct_authorization"], True)
        self.assertIs(error["secret_or_authorization_header_recorded"], False)
        self.assertRegex(error["provider_request_id"], r"^req_[A-Za-z0-9]+$")

    def test_15_status_journal_lifecycle(self) -> None:
        self.assertEqual(
            [row["status"] for row in self.status_events],
            [
                "PREFLIGHT_STARTED",
                "RUNTIME_VALIDATED",
                "CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED",
                "INCOMPLETE",
            ],
        )
        self.assertEqual(self.status_events[-1]["failure_phase"], "PROVIDER_CALL")
        self.assertEqual(self.status_events[-1]["judge_calls"], 1)
        self.assertEqual(self.status_events[-1]["valid_terminal_count"], 0)

    def test_16_timestamp_order_is_monotonic(self) -> None:
        timestamps = [
            datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            for row in self.status_events
        ]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertLessEqual(timestamps[-1], datetime.fromisoformat(
            self.status["timestamp_utc"].replace("Z", "+00:00")
        ))

    def test_17_terminal_population_and_uniqueness(self) -> None:
        self.assertEqual(self.terminals, [])
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 0)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 0)
        self.assertEqual(
            sha256_file(self.output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl"),
            EXPECTED_TERMINAL_SHA256,
        )

    def test_18_returned_model_coverage_is_zero_not_mismatched(self) -> None:
        self.assertEqual(self.configuration["model"], EXPECTED_MODEL)
        self.assertEqual(self.execution_contract["returned_model_identity_verified"], EXPECTED_MODEL)
        self.assertEqual(self.returns, [])
        self.assertEqual(self.terminals, [])

    def test_19_rate_limit_is_nonretryable(self) -> None:
        self.assertIn("RATE_LIMIT", self.execution_contract["never_retry_after"])
        self.assertEqual(
            self.execution_contract["manual_retry"]["permitted_only_after"],
            [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
        )
        self.assertEqual(self.execution_contract["manual_retry"]["maximum_retries"], 1)
        self.assertEqual(sum(row["attempt_number"] == 2 for row in self.starts), 0)

    def test_20_physical_ceiling_and_no_later_attempts(self) -> None:
        self.assertLessEqual(len(self.starts), 22)
        self.assertEqual(len(self.starts), self.status["physical_attempts"])
        self.assertEqual({row["logical_order"] for row in self.starts}, {39})
        self.assertFalse(
            {row["logical_order"] for row in self.starts} & set(range(40, 50))
        )

    def test_21_usage_arithmetic_is_zero_for_zero_valid_terminals(self) -> None:
        totals = {
            key: sum(row[key] for row in self.terminals)
            for key in (
                "prompt_tokens",
                "cached_input_tokens",
                "completion_tokens",
                "total_tokens",
            )
        }
        self.assertEqual(
            totals,
            {
                "prompt_tokens": 0,
                "cached_input_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )

    def test_22_parser_v3_valid_result_and_long_rationale(self) -> None:
        criteria = {
            criterion: criterion in {"CLARITY", "CONTEXT_AWARENESS", "RELIABILITY"}
            for criterion in PRIMARY_CRITERIA
        }
        applicability = {
            "schema_version": "rq3-dimension-applicability-map-v1",
            "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
            "criteria": criteria,
            "applicable_primary_count": 3,
            "applicability_sha256": sha256_bytes(canonical_json_bytes(criteria)),
        }
        long_rationale = "diagnostic rationale " * 40
        raw = {
            SCORE_FIELDS[criterion]: (
                {"CLARITY": "5", "CONTEXT_AWARENESS": "4", "RELIABILITY": "3"}[criterion]
                if criteria[criterion]
                else "NA"
            )
            for criterion in PRIMARY_CRITERIA
        }
        raw.update(
            {
                "evidence_faithfulness": "5",
                "unsupported_claim_count": "0",
                "criterion_rationales": {
                    field: long_rationale for field in SCORE_FIELDS.values()
                },
                "schema_version": "rq3-judge-response-r3d1-r2-transport",
            }
        )
        parsed = self.parser.parse_judge_result(
            canonical_json_bytes(raw),
            applicability,
            expected_judge_result_blind_id=EXPECTED_FIRST_RESULT_ID,
        )
        self.assertEqual(set(parsed), PARSED_FIELDS)
        self.assertEqual(parsed["response_blind_id"], EXPECTED_FIRST_RESULT_ID)
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)
        self.assertEqual(parsed["evidence_faithfulness"], 5)
        self.assertEqual(parsed["unsupported_claim_count"], 0)
        self.assertGreater(len(parsed["criterion_rationales"]["clarity"]), 500)

    def test_23_parser_v3_retry_categories(self) -> None:
        cases = {
            "INVALID_JSON": self.parser.JudgeResultError("INVALID_JSON"),
            "STRICT_SCHEMA_VALIDATION_FAILED": self.parser.JudgeResultError(
                "STRICT_SCHEMA_VALIDATION_FAILED"
            ),
            "APPLICABILITY_CONTRACT_VIOLATION": self.parser.JudgeResultError(
                "APPLICABILITY_CONTRACT_VIOLATION"
            ),
        }
        for expected, error in cases.items():
            self.assertEqual(self.parser.retryable_failure_code(error), expected)
        self.assertIsNone(self.parser.retryable_failure_code(Exception("TIMEOUT")))
        self.assertIsNone(self.parser.retryable_failure_code(Exception("RATE_LIMIT")))

    def test_24_secret_and_restricted_identity_absence(self) -> None:
        reviewable = self.authorization_path.read_bytes() + b"".join(
            (self.output_dir / name).read_bytes() for name in sorted(EXPECTED_OUTPUT_FILES)
        )
        self.assertIsNone(re.search(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", reviewable))
        self.assertNotIn(b"Authorization:" + b" Bearer ", reviewable)
        forbidden_keys = {
            "condition_id",
            "condition_name",
            "mode",
            "mode_id",
            "mode_name",
            "route",
            "route_id",
            "route_name",
            "scenario_id",
            "scenario_family_id",
            "family_id",
            "gold",
            "gold_label",
            "expected_outcome",
            "expected_winner",
            "human_rating",
            "human_ratings",
            "hmac_key",
        }
        structured: list[object] = [
            self.authorization,
            self.preflight,
            self.status,
            *self.status_events,
            *self.errors,
            *self.attempts,
            *self.terminals,
        ]
        keys: set[str] = set()
        for value in structured:
            keys.update(collect_keys(value))
        self.assertFalse(keys & forbidden_keys)

    def test_25_source_manifest_bindings(self) -> None:
        manifest = self.source_manifest
        self.assertEqual(
            manifest["schema_version"],
            "c4-real-judge-continuation-source-manifest-r3-v1",
        )
        self.assertEqual(manifest["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(manifest["shard_id"], "B_CONTINUATION")
        self.assertEqual(manifest["source_shard_id"], "B")
        self.assertEqual(manifest["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(manifest["package_zip"]["sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            manifest["authorization_record"]["sha256"],
            EXPECTED_AUTHORIZATION_SHA256,
        )
        self.assertEqual(
            {
                name: item["sha256"]
                for name, item in manifest["execution_output"]["files"].items()
            },
            EXPECTED_OUTPUT_HASHES,
        )
        self.assertEqual(
            manifest["parsed_result_set"]["sha256"], EXPECTED_PARSED_SET_SHA256
        )

    def test_26_final_integration_structural_compatibility(self) -> None:
        projection = []
        for row in self.terminals:
            self.assertEqual(set(row), TERMINAL_FIELDS)
            self.assertEqual(set(row["parsed_semantic_result"]), PARSED_FIELDS)
            projection.append(
                {
                    "logical_order": row["logical_order"],
                    "logical_judge_request_id": row["logical_judge_request_id"],
                    "judge_result_blind_id": row["judge_result_blind_id"],
                    "parsed_semantic_result": row["parsed_semantic_result"],
                }
            )
        self.assertEqual(
            sha256_bytes(canonical_json_bytes(projection)),
            EXPECTED_PARSED_SET_SHA256,
        )
        runner_source = self.package_bytes["judge_execution_runner_v3.py"].decode("utf-8")
        self.assertIn('"schema_version": "c4-real-judge-terminal-r3-v1"', runner_source)
        for field in TERMINAL_FIELDS:
            self.assertIn(f'"{field}"', runner_source)
        self.assertEqual(self.status["status"], "INCOMPLETE")
        self.assertIs(
            self.status["continuation_requires_new_direct_authorization"], True
        )

    def test_27_no_resume_or_unauthorized_continuation_state(self) -> None:
        self.assertIs(self.preflight["automatic_resume"], False)
        self.assertIs(self.status["automatic_resume"], False)
        self.assertEqual(self.status["judge_calls"], 1)
        self.assertEqual(self.status_events[-1]["judge_calls"], 1)
        self.assertEqual(self.starts[-1]["logical_order"], 39)
        self.assertNotIn(40, {row["logical_order"] for row in self.starts})

    def test_28_frozen_runner_parser_and_scientific_hashes(self) -> None:
        self.assertEqual(
            self.configuration["execution_runner_sha256"],
            EXPECTED_MEMBER_HASHES["judge_execution_runner_v3.py"],
        )
        self.assertEqual(
            self.configuration["local_parser_sha256"],
            EXPECTED_MEMBER_HASHES["judge_result_parser_v3.py"],
        )
        self.assertEqual(
            self.configuration["judge_prompt_sha256"],
            EXPECTED_MEMBER_HASHES["JUDGE_PROMPT.txt"],
        )
        self.assertEqual(
            self.configuration["provider_schema_sha256"],
            EXPECTED_MEMBER_HASHES["JUDGE_SCHEMA.json"],
        )
        self.assertEqual(
            self.configuration["primary_rubric_sha256"],
            EXPECTED_MEMBER_HASHES["PRIMARY_RUBRIC.json"],
        )
        self.assertEqual(
            self.configuration["applicability_contract_sha256"],
            EXPECTED_MEMBER_HASHES["APPLICABILITY_CONTRACT.json"],
        )


def parse_arguments() -> tuple[Path, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--package-zip", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    return args.package_zip, remaining


if __name__ == "__main__":
    PACKAGE_ZIP, unittest_arguments = parse_arguments()
    program = unittest.main(
        argv=[sys.argv[0], *unittest_arguments],
        verbosity=2,
        exit=False,
    )
    print("OFFLINE_PROVIDER_CALLS=0")
    raise SystemExit(0 if program.result.wasSuccessful() else 1)
else:
    PACKAGE_ZIP = Path("/nonexistent/package.zip")
