#!/opt/anaconda3/bin/python3
"""Zero-network mechanical tests for successful C4 Judge-B continuation V2."""

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
EXPECTED_AUTHORIZATION_V2_SHA256 = (
    "e593a18599e7c017d359c6020e57d0017e876d9d153fe9a9224e90582f2031c9"
)
EXPECTED_TERMINAL_V2_SHA256 = (
    "c7cdcb0124aaa1a1f2137f2e17dac48c075cc1c888fbe92305bcf6f90642a268"
)
EXPECTED_PARSED_SET_V2_SHA256 = (
    "b51928e34e693464cf3dc421404108fb2ea160f2b2bff723054c704f50c9865b"
)
EXPECTED_PACKAGE_ID = "C4_REAL_JUDGE_SHARD_B_CONTINUATION_R3_20260902"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-J3B-R1-BILLING-RECOVERY-20260902"
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
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
EXPECTED_OUTPUT_V2_HASHES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "9de1dbf85e3ba42b2959ef558def3cde1af0db22245117c4fb6dfc41ab1465a5"
    ),
    "JUDGE_ERROR_REGISTRY.jsonl": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "JUDGE_EXECUTION_STATUS.json": (
        "580aa7481ad60d49e69e33cdb935408b4291bdedfcc61db15a3ad6c53bc190e0"
    ),
    "JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "5b0cc63770088917cf4666518df82ae60d1a340d6ea71a4366ab3f7b6afda055"
    ),
    "JUDGE_STATUS_JOURNAL.jsonl": (
        "2d21e6b0c81eb05b3b81566e772c837711e753f0197a160416ecf9f17cb18ca2"
    ),
    "JUDGE_TERMINAL_JOURNAL.jsonl": EXPECTED_TERMINAL_V2_SHA256,
}
EXPECTED_V1_HASHES = {
    "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT.md": (
        "57b78f27cdbcb68981f4416a12db367ccddcfdcf0357970f14c9f937b99da670"
    ),
    "STATUS.md": (
        "108249a5759913965a84472a59102141dad44e4c0ac66e702b7efd8fde8ccbe6"
    ),
    "execution_output_v1/JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "14298ba378b6bf2d09068d320bfa1c6810a1bdb40852d7aa7ddf6c6f1af182be"
    ),
    "execution_output_v1/JUDGE_ERROR_REGISTRY.jsonl": (
        "ba5664313984e12a764cf95a225896c42c8d878fffa1f69491a3cb84262aa104"
    ),
    "execution_output_v1/JUDGE_EXECUTION_STATUS.json": (
        "ae8985388e0031abb7ad59ccff8c6f00aef5ed90523845d4ceda9001f8ffd18b"
    ),
    "execution_output_v1/JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "550c174f380bb9a664a0689bd3a268a4c4ee84592cce66b0ae5635bdb6c9e964"
    ),
    "execution_output_v1/JUDGE_STATUS_JOURNAL.jsonl": (
        "a343a9bab324f325eccd6ed01fa6e9588dd63439dbf5e4f8846668292312ae36"
    ),
    "execution_output_v1/JUDGE_TERMINAL_JOURNAL.jsonl": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "judge_continuation_execution_audit_v1.json": (
        "b9e52d0b3a951e8d41c45be882eef41f56b16499ab61dc0af6ec1d931e9e88e1"
    ),
    "judge_continuation_source_manifest_v1.json": (
        "3975b50afda0787cd55c327f1e205f3e09d519b906428bb4834bfea42331f8d4"
    ),
    "judge_execution_authorization_v1.json": (
        "b18501411fc256caeec899852ae1a46030837f6debbb677a57b22a67e65a39a6"
    ),
    "review_manifest_v1.json": (
        "907eb305ba685c7c613dcd677ba25c639303c0d0ad4d83875967c68c75713563"
    ),
    "test_judge_continuation_artifacts_v1.py": (
        "10ac26a6a4abbbebc69e4a08eb4276bde0c2177c446f019656ee2eec67173b17"
    ),
}
EXPECTED_V1_MAP_SHA256 = (
    "e7a3152e2a27d17250798e9b49abb8ea03e05348c44c68fc71cc5336f2992620"
)
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
PROVIDER_FIELDS = {
    *SCORE_FIELDS.values(),
    "evidence_faithfulness",
    "unsupported_claim_count",
    "criterion_rationales",
    "schema_version",
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


def frozen_applicability(request: dict[str, object]) -> dict[str, object]:
    payload = request["provider_payload"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert isinstance(messages, list) and messages
    first = messages[0]
    assert isinstance(first, dict)
    content = first["content"]
    assert isinstance(content, str)
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    embedded = strict_json(content.split(begin, 1)[1].rsplit(end, 1)[0])
    applicability = embedded["frozen_applicability_map"]
    assert isinstance(applicability, dict)
    return applicability


def recompute_primary_mean(
    parsed: dict[str, object], applicability: dict[str, object]
) -> float:
    criteria = applicability["criteria"]
    assert isinstance(criteria, dict)
    scores: list[int] = []
    for criterion in PRIMARY_CRITERIA:
        value = parsed[SCORE_FIELDS[criterion]]
        if criteria[criterion]:
            if type(value) is not int or not 1 <= value <= 5:
                raise ValueError("applicable score is invalid")
            scores.append(value)
        elif value != "NA":
            raise ValueError("inapplicable score is not NA")
    if not 3 <= len(scores) <= 8:
        raise ValueError("applicable primary count outside frozen range")
    return sum(scores) / len(scores)


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


class JudgeContinuationBV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent
        cls.output_v1 = cls.root / "execution_output_v1"
        cls.output_v2 = cls.root / "execution_output_v2"
        cls.authorization_v1_path = cls.root / "judge_execution_authorization_v1.json"
        cls.authorization_v2_path = cls.root / "judge_execution_authorization_v2.json"
        cls.preservation_path = cls.root / "historical_v1_preservation_manifest_v2.json"
        cls.source_manifest_path = cls.root / "judge_continuation_source_manifest_v2.json"
        cls.package_zip = PACKAGE_ZIP.resolve()
        with zipfile.ZipFile(cls.package_zip) as archive:
            cls.package_infos = archive.infolist()
            cls.package_bytes = {
                info.filename: archive.read(info.filename)
                for info in cls.package_infos
                if not info.is_dir()
            }
        cls.requests = read_jsonl_bytes(cls.package_bytes["BLINDED_JUDGE_REQUESTS.jsonl"])
        cls.request_by_order = {
            row["original_logical_order"]: row for row in cls.requests
        }
        cls.configuration = strict_json(cls.package_bytes["JUDGE_CONFIGURATION.json"])
        cls.execution_contract = strict_json(cls.package_bytes["EXECUTION_CONTRACT.json"])
        cls.authorization_v1 = strict_json(cls.authorization_v1_path.read_bytes())
        cls.authorization_v2 = strict_json(cls.authorization_v2_path.read_bytes())
        cls.preservation = strict_json(cls.preservation_path.read_bytes())
        cls.source_manifest = strict_json(cls.source_manifest_path.read_bytes())
        cls.attempts = read_jsonl_file(cls.output_v2 / "JUDGE_ATTEMPT_JOURNAL.jsonl")
        cls.starts = [row for row in cls.attempts if row["event"] == "ATTEMPT_STARTED"]
        cls.returns = [row for row in cls.attempts if row["event"] == "ATTEMPT_RETURNED"]
        cls.errors = read_jsonl_file(cls.output_v2 / "JUDGE_ERROR_REGISTRY.jsonl")
        cls.status_events = read_jsonl_file(cls.output_v2 / "JUDGE_STATUS_JOURNAL.jsonl")
        cls.terminals = read_jsonl_file(cls.output_v2 / "JUDGE_TERMINAL_JOURNAL.jsonl")
        cls.status = strict_json((cls.output_v2 / "JUDGE_EXECUTION_STATUS.json").read_bytes())
        cls.preflight = strict_json((cls.output_v2 / "JUDGE_PREFLIGHT_START_RECEIPT.json").read_bytes())
        cls.parser = load_parser_module(cls.package_bytes["judge_result_parser_v3.py"])

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

    def test_03_request_population_and_original_orders(self) -> None:
        self.assertEqual(len(self.requests), 11)
        self.assertEqual(sorted(self.request_by_order), list(range(39, 50)))
        self.assertEqual({row["continuation_shard_id"] for row in self.requests}, {"B_CONTINUATION"})
        self.assertEqual({row["source_shard_id"] for row in self.requests}, {"B"})
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.requests}), 11)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.requests}), 11)
        self.assertEqual(sum(row["estimated_input_tokens"] for row in self.requests), 36571)

    def test_04_frozen_provider_payload_identity(self) -> None:
        for row in self.requests:
            payload = row["provider_payload"]
            self.assertEqual(
                set(payload),
                {"model", "messages", "temperature", "max_tokens", "stream", "response_format"},
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

    def test_05_frozen_configuration_and_execution_contract(self) -> None:
        config = self.configuration
        contract = self.execution_contract
        self.assertEqual(config["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(config["shard_id"], "B_CONTINUATION")
        self.assertEqual(config["source_shard_id"], "B")
        self.assertEqual(config["original_logical_orders"], list(range(39, 50)))
        self.assertEqual(config["model"], EXPECTED_MODEL)
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 2048)
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertEqual(config["request_timeout_seconds"], 120.0)
        self.assertEqual(config["minimum_seconds_between_initial_request_starts"], 15.0)
        self.assertEqual(contract["maximum_physical_attempts"], 22)
        self.assertIs(contract["automatic_resume"], False)
        self.assertIs(contract["timeout_is_non_retryable"], True)

    def test_06_authorization_v2_shape_hash_and_binding(self) -> None:
        self.assertEqual(sha256_file(self.authorization_v2_path), EXPECTED_AUTHORIZATION_V2_SHA256)
        self.assertEqual(set(self.authorization_v2), AUTHORIZATION_FIELDS)
        self.assertEqual(
            self.authorization_v2["schema_version"],
            "c4-real-judge-execution-authorization-r3-v1",
        )
        self.assertEqual(self.authorization_v2["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(self.authorization_v2["authorized_by"], "Ming Liu")
        self.assertRegex(
            self.authorization_v2["authorized_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertEqual(self.authorization_v2["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.authorization_v2["shard_id"], "B_CONTINUATION")
        self.assertEqual(self.authorization_v2["request_count"], 11)
        self.assertEqual(self.authorization_v2["maximum_physical_attempts"], 22)
        self.assertEqual(self.authorization_v2["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            self.authorization_v2["blinded_judge_manifest_sha256"],
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(self.authorization_v2["status"], "AUTHORIZED")

    def test_07_v1_and_v2_output_leaf_exclusivity(self) -> None:
        self.assertEqual(
            sorted(self.root.glob("execution_output_v*")),
            [self.output_v1, self.output_v2],
        )
        self.assertEqual(
            {path.name for path in self.output_v2.iterdir() if path.is_file()},
            EXPECTED_OUTPUT_FILES,
        )
        self.assertTrue(all(path.is_file() for path in self.output_v2.iterdir()))

    def test_08_v2_durable_output_byte_hashes(self) -> None:
        self.assertEqual(
            {name: sha256_file(self.output_v2 / name) for name in EXPECTED_OUTPUT_FILES},
            EXPECTED_OUTPUT_V2_HASHES,
        )
        self.assertEqual(list(self.root.rglob("__pycache__")), [])
        self.assertEqual(list(self.root.rglob("*.pyc")), [])

    def test_09_v2_preflight_receipt(self) -> None:
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
        self.assertEqual(receipt["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(receipt["judge_calls_at_receipt_write"], 0)
        self.assertIs(receipt["runtime_constructed_at_receipt_write"], False)
        self.assertIs(receipt["client_constructed_at_receipt_write"], False)
        self.assertIs(receipt["automatic_resume"], False)

    def test_10_runtime_sdk_and_timeout_identity(self) -> None:
        runtime_events = [row for row in self.status_events if row["status"] == "RUNTIME_VALIDATED"]
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
            if row["status"] == "CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED"
        ]
        self.assertEqual(len(client_events), 1)
        client = client_events[0]["client_configuration"]
        self.assertEqual(client["client_max_retries"], 0)
        self.assertEqual(client["request_timeout_seconds"], 120.0)
        self.assertEqual(
            client["timeout_components_seconds"],
            {"connect": 120.0, "pool": 120.0, "read": 120.0, "write": 120.0},
        )

    def test_11_v2_execution_status_is_complete(self) -> None:
        self.assertEqual(self.status["status"], "COMPLETE")
        self.assertEqual(self.status["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.status["shard_id"], "B_CONTINUATION")
        self.assertEqual(self.status["request_count"], 11)
        self.assertEqual(self.status["valid_terminal_count"], 11)
        self.assertEqual(self.status["physical_attempts"], 11)
        self.assertEqual(self.status["judge_calls"], 11)
        self.assertEqual(self.status["request_timeout_seconds"], 120.0)
        self.assertIs(self.status["automatic_resume"], False)
        self.assertIs(self.status["continuation_requires_new_direct_authorization"], False)

    def test_12_attempt_journal_ordering(self) -> None:
        self.assertEqual(len(self.attempts), 22)
        self.assertEqual(len(self.starts), 11)
        self.assertEqual(len(self.returns), 11)
        by_order: dict[int, list[str]] = {}
        for row in self.attempts:
            by_order.setdefault(row["logical_order"], []).append(row["event"])
        self.assertEqual(sorted(by_order), list(range(39, 50)))
        for order in range(39, 50):
            self.assertEqual(by_order[order], ["ATTEMPT_STARTED", "ATTEMPT_RETURNED"])
        self.assertEqual([row["judge_calls_started"] for row in self.starts], list(range(1, 12)))
        self.assertEqual({row["attempt_number"] for row in self.attempts}, {1})

    def test_13_initial_start_pacing(self) -> None:
        starts = [
            datetime.fromisoformat(row["request_started_at_utc"].replace("Z", "+00:00"))
            for row in self.starts
        ]
        self.assertEqual(starts, sorted(starts))
        intervals = [(right - left).total_seconds() for left, right in zip(starts, starts[1:])]
        self.assertEqual(len(intervals), 10)
        self.assertTrue(all(interval >= 14.9 for interval in intervals))

    def test_14_provider_payload_hash_binding(self) -> None:
        for row in [*self.attempts, *self.terminals]:
            request = self.request_by_order[row["logical_order"]]
            self.assertEqual(row["provider_payload_sha256"], request["provider_payload_sha256"])
            self.assertEqual(row["logical_judge_request_id"], request["logical_judge_request_id"])
            self.assertEqual(row["judge_result_blind_id"], request["judge_result_blind_id"])

    def test_15_terminal_population_and_uniqueness(self) -> None:
        self.assertEqual(len(self.terminals), 11)
        self.assertEqual([row["logical_order"] for row in self.terminals], list(range(39, 50)))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 11)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 11)
        self.assertEqual({row["terminal_status"] for row in self.terminals}, {"VALID_JUDGE_RESULT"})
        self.assertEqual({row["physical_attempts"] for row in self.terminals}, {1})
        self.assertTrue(all(set(row) == TERMINAL_FIELDS for row in self.terminals))

    def test_16_every_provider_result_passes_parser_v3(self) -> None:
        returns_by_order = {row["logical_order"]: row for row in self.returns}
        for terminal in self.terminals:
            returned = returns_by_order[terminal["logical_order"]]
            request = self.request_by_order[terminal["logical_order"]]
            parsed = self.parser.parse_judge_result(
                returned["raw_response_content"],
                frozen_applicability(request),
                expected_judge_result_blind_id=request["judge_result_blind_id"],
            )
            self.assertEqual(parsed, terminal["parsed_semantic_result"])

    def test_17_strict_provider_output_shape(self) -> None:
        for row in self.returns:
            raw = strict_json(row["raw_response_content"])
            self.assertEqual(set(raw), PROVIDER_FIELDS)
            self.assertEqual(raw["schema_version"], "rq3-judge-response-r3d1-r2-transport")
            self.assertNotIn("overall_applicable_mean", raw)
            self.assertNotIn("response_blind_id", raw)

    def test_18_applicability_is_respected(self) -> None:
        for row in self.returns:
            request = self.request_by_order[row["logical_order"]]
            applicability = frozen_applicability(request)
            criteria = applicability["criteria"]
            self.assertEqual(set(criteria), set(PRIMARY_CRITERIA))
            count = sum(criteria[name] for name in PRIMARY_CRITERIA)
            self.assertEqual(count, applicability["applicable_primary_count"])
            self.assertGreaterEqual(count, 3)
            self.assertLessEqual(count, 8)
            self.assertEqual(
                sha256_bytes(canonical_json_bytes(criteria)),
                applicability["applicability_sha256"],
            )
            raw = strict_json(row["raw_response_content"])
            for criterion in PRIMARY_CRITERIA:
                value = raw[SCORE_FIELDS[criterion]]
                if criteria[criterion]:
                    self.assertIn(value, {"1", "2", "3", "4", "5"})
                else:
                    self.assertEqual(value, "NA")

    def test_19_parsed_shape_types_and_rationales(self) -> None:
        returns_by_order = {row["logical_order"]: row for row in self.returns}
        for terminal in self.terminals:
            parsed = terminal["parsed_semantic_result"]
            self.assertEqual(set(parsed), PARSED_FIELDS)
            self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
            self.assertIs(type(parsed["evidence_faithfulness"]), int)
            self.assertGreaterEqual(parsed["evidence_faithfulness"], 1)
            self.assertLessEqual(parsed["evidence_faithfulness"], 5)
            self.assertIs(type(parsed["unsupported_claim_count"]), int)
            self.assertGreaterEqual(parsed["unsupported_claim_count"], 0)
            self.assertIs(type(parsed["overall_applicable_mean"]), float)
            rationales = parsed["criterion_rationales"]
            self.assertEqual(set(rationales), set(SCORE_FIELDS.values()))
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in rationales.values()))
            self.assertEqual(
                returns_by_order[terminal["logical_order"]]["rationale_lengths"],
                {field: len(value) for field, value in rationales.items()},
            )

    def test_20_local_result_id_attachment(self) -> None:
        for terminal in self.terminals:
            parsed = terminal["parsed_semantic_result"]
            request = self.request_by_order[terminal["logical_order"]]
            self.assertEqual(parsed["response_blind_id"], terminal["judge_result_blind_id"])
            self.assertEqual(parsed["response_blind_id"], request["judge_result_blind_id"])

    def test_21_local_primary_mean_and_secondary_exclusion(self) -> None:
        for terminal in self.terminals:
            request = self.request_by_order[terminal["logical_order"]]
            parsed = terminal["parsed_semantic_result"]
            expected = recompute_primary_mean(parsed, frozen_applicability(request))
            self.assertEqual(parsed["overall_applicable_mean"], expected)
            self.assertNotIn("evidence_faithfulness", SCORE_FIELDS.values())
            self.assertNotIn("unsupported_claim_count", SCORE_FIELDS.values())

    def test_22_unsupported_claim_conversion(self) -> None:
        returns_by_order = {row["logical_order"]: row for row in self.returns}
        for terminal in self.terminals:
            raw = strict_json(returns_by_order[terminal["logical_order"]]["raw_response_content"])
            self.assertRegex(raw["unsupported_claim_count"], r"^(?:0|[1-9][0-9]*)$")
            self.assertEqual(
                terminal["parsed_semantic_result"]["unsupported_claim_count"],
                int(raw["unsupported_claim_count"]),
            )

    def test_23_returned_model_identity(self) -> None:
        self.assertEqual({row["returned_model"] for row in self.returns}, {EXPECTED_MODEL})
        self.assertEqual({row["returned_model"] for row in self.terminals}, {EXPECTED_MODEL})

    def test_24_retry_policy_and_physical_ceiling(self) -> None:
        self.assertEqual(sum(row["attempt_number"] == 2 for row in self.starts), 0)
        self.assertTrue(all(row.get("failure_code") is None for row in self.returns))
        self.assertLessEqual(len(self.starts), 22)
        self.assertGreaterEqual(len(self.starts), 11)
        self.assertEqual(len(self.starts), self.status["physical_attempts"])
        self.assertEqual(
            self.execution_contract["manual_retry"]["permitted_only_after"],
            ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED", "APPLICABILITY_CONTRACT_VIOLATION"],
        )

    def test_25_complete_status_and_zero_errors(self) -> None:
        self.assertEqual(self.errors, [])
        self.assertEqual(
            [row["status"] for row in self.status_events],
            [
                "PREFLIGHT_STARTED",
                "RUNTIME_VALIDATED",
                "CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED",
                "COMPLETE",
            ],
        )
        self.assertEqual(self.status_events[-1]["judge_calls"], 11)
        self.assertEqual(self.status_events[-1]["valid_terminal_count"], 11)

    def test_26_usage_arithmetic_and_totals(self) -> None:
        for row in self.terminals:
            self.assertEqual(row["total_tokens"], row["prompt_tokens"] + row["completion_tokens"])
            self.assertGreaterEqual(row["prompt_tokens"], row["cached_input_tokens"])
            for key in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens"):
                self.assertIs(type(row[key]), int)
                self.assertGreaterEqual(row[key], 0)
        totals = {
            key: sum(row[key] for row in self.terminals)
            for key in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens")
        }
        self.assertEqual(
            totals,
            {
                "prompt_tokens": 30083,
                "cached_input_tokens": 0,
                "completion_tokens": 4229,
                "total_tokens": 34312,
            },
        )

    def test_27_hashes_secret_and_restricted_identity_absence(self) -> None:
        self.assertEqual(
            sha256_file(self.output_v2 / "JUDGE_TERMINAL_JOURNAL.jsonl"),
            EXPECTED_TERMINAL_V2_SHA256,
        )
        reviewable = self.authorization_v2_path.read_bytes() + b"".join(
            (self.output_v2 / name).read_bytes() for name in sorted(EXPECTED_OUTPUT_FILES)
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
            self.authorization_v2,
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
        for returned in self.returns:
            keys.update(collect_keys(strict_json(returned["raw_response_content"])))
        self.assertFalse(keys & forbidden_keys)

    def test_28_final_integration_compatibility_and_result_set_hash(self) -> None:
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
            EXPECTED_PARSED_SET_V2_SHA256,
        )
        self.assertEqual(self.status["status"], "COMPLETE")
        self.assertEqual(self.status["valid_terminal_count"], 11)

    def test_29_historical_v1_before_after_preservation(self) -> None:
        current = {name: sha256_file(self.root / name) for name in EXPECTED_V1_HASHES}
        self.assertEqual(current, EXPECTED_V1_HASHES)
        self.assertEqual(self.preservation["file_count"], 13)
        self.assertEqual(set(self.preservation["files"]), set(EXPECTED_V1_HASHES))
        for name, expected in EXPECTED_V1_HASHES.items():
            item = self.preservation["files"][name]
            self.assertEqual(item["before_sha256"], expected)
            self.assertEqual(item["after_sha256"], expected)
            self.assertEqual(item["status"], "IDENTICAL")
        aggregate = self.preservation["canonical_path_to_sha256_map"]
        self.assertEqual(aggregate["before_sha256"], EXPECTED_V1_MAP_SHA256)
        self.assertEqual(aggregate["after_sha256"], EXPECTED_V1_MAP_SHA256)
        self.assertEqual(aggregate["status"], "IDENTICAL")

    def test_30_historical_v1_facts_remain_failure_only(self) -> None:
        facts = self.preservation["historical_facts"]
        self.assertEqual(facts["error_code"], "credit_balance_exhausted")
        self.assertEqual(facts["physical_attempts"], 1)
        self.assertEqual(facts["valid_terminal_results"], 0)
        self.assertEqual(facts["returned_model_results"], 0)
        self.assertEqual(facts["recorded_tokens"], 0)
        self.assertEqual(facts["retries"], 0)
        self.assertEqual(facts["later_requests_attempted"], 0)
        v1_status = strict_json((self.output_v1 / "JUDGE_EXECUTION_STATUS.json").read_bytes())
        self.assertEqual(v1_status["status"], "INCOMPLETE")
        self.assertEqual(v1_status["valid_terminal_count"], 0)
        self.assertEqual((self.output_v1 / "JUDGE_TERMINAL_JOURNAL.jsonl").read_bytes(), b"")

    def test_31_source_manifest_bindings(self) -> None:
        manifest = self.source_manifest
        self.assertEqual(manifest["schema_version"], "c4-real-judge-continuation-source-manifest-v2")
        self.assertEqual(manifest["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(manifest["shard_id"], "B_CONTINUATION")
        self.assertEqual(manifest["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(manifest["package_zip"]["sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            manifest["authorization_record_v2"]["sha256"],
            EXPECTED_AUTHORIZATION_V2_SHA256,
        )
        self.assertEqual(
            {name: item["sha256"] for name, item in manifest["execution_output_v2"]["files"].items()},
            EXPECTED_OUTPUT_V2_HASHES,
        )
        self.assertEqual(manifest["terminal_journal_sha256"], EXPECTED_TERMINAL_V2_SHA256)
        self.assertEqual(manifest["parsed_result_set"]["sha256"], EXPECTED_PARSED_SET_V2_SHA256)
        self.assertEqual(manifest["offline_tests"]["source_sha256"], sha256_file(Path(__file__)))

    def test_32_parser_v3_long_rationale_and_retry_categories(self) -> None:
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
                "criterion_rationales": {field: long_rationale for field in SCORE_FIELDS.values()},
                "schema_version": "rq3-judge-response-r3d1-r2-transport",
            }
        )
        expected_id = self.requests[0]["judge_result_blind_id"]
        parsed = self.parser.parse_judge_result(
            canonical_json_bytes(raw),
            applicability,
            expected_judge_result_blind_id=expected_id,
        )
        self.assertEqual(parsed["response_blind_id"], expected_id)
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)
        self.assertGreater(len(parsed["criterion_rationales"]["clarity"]), 500)
        for code in (
            "INVALID_JSON",
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "APPLICABILITY_CONTRACT_VIOLATION",
        ):
            self.assertEqual(
                self.parser.retryable_failure_code(self.parser.JudgeResultError(code)),
                code,
            )
        self.assertIsNone(self.parser.retryable_failure_code(Exception("RATE_LIMIT")))

    def test_33_v1_and_v2_scientific_source_separation(self) -> None:
        self.assertNotEqual(self.authorization_v1["authorization_id"], self.authorization_v2["authorization_id"])
        self.assertEqual(self.preservation["scientific_source_binding"]["historical_v1_role"], "BILLING_FAILURE_AUDIT_SOURCE_ONLY")
        self.assertEqual(self.preservation["scientific_source_binding"]["new_v2_role"], "SCIENTIFIC_JUDGE_CONTINUATION_RESULT_SOURCE_ONLY")
        self.assertEqual(self.status["status"], "COMPLETE")
        self.assertEqual(len(self.terminals), 11)
        self.assertEqual(read_jsonl_file(self.output_v1 / "JUDGE_TERMINAL_JOURNAL.jsonl"), [])


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
