#!/usr/bin/env python3
"""Zero-network mechanical tests for frozen C4 REAL Judge continuation C V2."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from typing import Any
from zipfile import ZipFile


ARTIFACT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ARTIFACT_DIR / "execution_output_v2"
PACKAGE_ZIP = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_JUDGE_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip"
)
REVIEW_ZIP = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_J3C_R1_C4_JUDGE_CONTINUATION_C_EXECUTION_REVIEW_2026-09-02.zip"
)

EXPECTED_STATUS = (
    "JUDGE_C_CONTINUATION_V2_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION"
)
EXPECTED_PACKAGE_SHA256 = (
    "0107197fff3707759452aa9b8b8fc4a8408cf3a2f05273d3586ae231722c101b"
)
EXPECTED_MANIFEST_SHA256 = (
    "926f99cd45309a1bf7821c4642620e87067a02713cbf5fefbe5fb6ab0cafa69f"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "9ebfa7740bb0d4e4e54218211a4e311eeccfa847bd0ce2b1b233ceaa1beb9109"
)
EXPECTED_ATTEMPT_SHA256 = (
    "8d9877e5744b605282b367209bc8cc9fbb1f318fb863b0f4e77cb11a2268943b"
)
EXPECTED_TERMINAL_SHA256 = (
    "03560d2a8d5a9c2a39d15442eb6c2648376ffa125e375db1cd389fa7798a6de6"
)
EXPECTED_PARSED_SET_SHA256 = (
    "9f2615b5913e6fa32be3b942446440b60301c3191d3ba6db9b58224dc0e946ff"
)
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_INCOMPLETE_REQUEST_ID = "C4J1-D18499F4FEEAA0D263F5FC41"
EXPECTED_INCOMPLETE_RESULT_ID = "R3B-45C6C7B6AA40FADB6C6A"
EXPECTED_INCOMPLETE_PAYLOAD_SHA256 = (
    "6f26a1556429610a909790d10e30850eab1f1d6c1ec8ea1f0725f33f23fee39f"
)

PACKAGE_FILES = {
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
OUTPUT_FILES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl",
    "JUDGE_ERROR_REGISTRY.jsonl",
    "JUDGE_EXECUTION_STATUS.json",
    "JUDGE_PREFLIGHT_START_RECEIPT.json",
    "JUDGE_STATUS_JOURNAL.jsonl",
    "JUDGE_TERMINAL_JOURNAL.jsonl",
}
EXPECTED_OUTPUT_HASHES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl": EXPECTED_ATTEMPT_SHA256,
    "JUDGE_ERROR_REGISTRY.jsonl": "f556307feac217341bdb0bf61d5e803c8ac2702bb234c0c7f685353e7a7c4308",
    "JUDGE_EXECUTION_STATUS.json": "aabffb7abdeab8714e608b63d9a30028efb96985a3858dc43acf25d05faea86f",
    "JUDGE_PREFLIGHT_START_RECEIPT.json": "256e5faba353fede0e30ad59e9e352441013a512852492a4e670b21251d496ea",
    "JUDGE_STATUS_JOURNAL.jsonl": "cedb136f183fdcf581b9b9606d3be0efeb74518d9a45e7e7f7d4937aa20ecc9d",
    "JUDGE_TERMINAL_JOURNAL.jsonl": EXPECTED_TERMINAL_SHA256,
}
EXPECTED_HISTORICAL_V1 = {
    "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT.md": (
        "64763ffb842d5a7c6cf317b163307e5d5ebf2eada662f8cf50677694a08c427b"
    ),
    "STATUS.md": "35f6cce7e88ce6818848951d3c10383d9415b77c3a6c23094c6df877ba3290ef",
    "execution_output_v1/JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "98a3014a7538ccd757f97849175ef6ef08f0ac8b0e4413a4f71bced82a538d5c"
    ),
    "execution_output_v1/JUDGE_ERROR_REGISTRY.jsonl": (
        "9c355f3e94e1c0dd6ba27109ab518f97f181a813b49de5bbae99d3d4baf49804"
    ),
    "execution_output_v1/JUDGE_EXECUTION_STATUS.json": (
        "0b452badde407d2bec1356660d49029cd5a70440ae5725a013dbaaefd58e8e15"
    ),
    "execution_output_v1/JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "ec39500762d51e89a2ced3139e0ef0bba10935670f6c9b6ec912be23a0ec1a86"
    ),
    "execution_output_v1/JUDGE_STATUS_JOURNAL.jsonl": (
        "1fe6cc1c2660a37c0d85ec19af57e5113db29d7d1dc88d8588fef6693c62ab62"
    ),
    "execution_output_v1/JUDGE_TERMINAL_JOURNAL.jsonl": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "judge_continuation_execution_audit_v1.json": (
        "9c9e1ef26aedbc295120f52d693de3bb8cf9c3fb3bb8855dc8baa8846edf1f32"
    ),
    "judge_continuation_source_manifest_v1.json": (
        "41e9bacc365a11b4f4cdcd1410abd7ab81304cd2b51cdba674bda1b170c70fa9"
    ),
    "judge_execution_authorization_v1.json": (
        "0177a7712c7672f04ca05c09b6c3323d9ba523d3c9bc8aa1dd4d5e46fb3ba7d8"
    ),
    "review_manifest_v1.json": (
        "20054d4f54de001d7be42f6b2657ffdb908dcdd64f4384d5b2165584a255fb76"
    ),
    "test_judge_continuation_execution_v1.py": (
        "f274633cf79da269d9b07b9dd6c3999fac8eb75de3c7c7a82b195d260cb3e9a8"
    ),
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
REQUEST_FIELDS = {
    "schema_version",
    "logical_judge_request_id",
    "judge_result_blind_id",
    "provider_payload_sha256",
    "estimated_input_tokens",
    "original_logical_order",
    "source_shard_id",
    "continuation_shard_id",
    "provider_payload",
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
PRIMARY = {
    "CLARITY": "clarity",
    "PERSONALISATION": "personalisation",
    "ACTIONABILITY": "actionability",
    "CONTEXT_AWARENESS": "context_awareness",
    "MOTIVATION_AND_ENGAGEMENT": "motivation_and_engagement",
    "RELIABILITY": "reliability",
    "MULTI_PAGE_COHESIVENESS": "multi_page_cohesiveness",
    "ERROR_HANDLING": "error_handling",
}
REVIEW_FILES = {
    "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT_V2.md",
    "STATUS_V2.md",
    "execution_output_v2/JUDGE_ATTEMPT_JOURNAL.jsonl",
    "execution_output_v2/JUDGE_ERROR_REGISTRY.jsonl",
    "execution_output_v2/JUDGE_EXECUTION_STATUS.json",
    "execution_output_v2/JUDGE_PREFLIGHT_START_RECEIPT.json",
    "execution_output_v2/JUDGE_STATUS_JOURNAL.jsonl",
    "execution_output_v2/JUDGE_TERMINAL_JOURNAL.jsonl",
    "historical_v1_preservation_manifest_v2.json",
    "judge_continuation_execution_audit_v2.json",
    "judge_continuation_source_manifest_v2.json",
    "judge_execution_authorization_v2.json",
    "test_judge_continuation_execution_v2.py",
    "review_manifest_v2.json",
}
FORBIDDEN_IDENTITY_KEYS = {
    "scenario_id",
    "scenario_family_id",
    "family_id",
    "mode",
    "mode_id",
    "condition",
    "condition_id",
    "condition_name",
    "route",
    "route_id",
    "route_signature",
    "p" + "3",
    "gold",
    "expected_winner",
    "dataset_group",
    "generation_shard",
    "generation_attempt_number",
}
FORBIDDEN_IDENTITY_TOKEN_HASHES = (
    (11, "8e16e738ac1569aeeca3b5d1f98a207c1ce13bb7fd4f104ce9935c39ebf6a8c0"),
    (11, "d6fa49652fccbe5e0d251dca471559919363ca3ade28c3338b900940a5bf16b6"),
    (15, "c3f296d95125b46dc5503daaa83f8a511534b4aa61bc998380f56e88a0e952dc"),
    (18, "b99dc667ae16ea20235336f2b010e39ec88c75289a6181b4f3325aaedaafba08"),
    (20, "08f17bd9dfdd8c3cbe05b3b6841d66c7f514b01ffe921fa2d8030773b5c81d76"),
    (10, "39c53f6221e1a7715bb5422afeb017c51f803de71940546730753cae9e682ce9"),
    (12, "c197636aedbac76e4c09f798bd5e732f6bbdd2ab31111185fd329f65c6071965"),
    (15, "fc3b20cc26cfdfd559592c3bf45d2eab2c28b5249a06a5970a46e03e17a63eee"),
    (17, "aaff97b3e9c62983ab56565e98a01a3d272af9bf475a3469b4c924c874366f8f"),
    (13, "8e89f67d9fe8d74c3d28d21a44ad3ecea35b0c8b8e559440445a72287187ee0e"),
    (9, "0bf404069fa0059647006fd027690ea2307ced9139be1ef2c03988dbabc529d3"),
    (12, "794011f3cc46e88a2fdd7481186cafd52869a6d3a5dd2d90de4966c60bfe6a19"),
    (15, "c2501d3619b5ab85269ac23973ec2e748230e5727c2338a27df53c7439751f45"),
)

NETWORK_EVENTS: list[str] = []


def _network_audit_hook(event: str, _args: tuple[Any, ...]) -> None:
    if event.startswith("socket."):
        NETWORK_EVENTS.append(event)
        raise RuntimeError("network access is prohibited in offline tests")


sys.addaudithook(_network_audit_hook)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(data: bytes | str) -> Any:
    return json.loads(data, object_pairs_hook=_duplicate_guard)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [strict_json(line) for line in path.read_bytes().splitlines() if line.strip()]


def extract_embedded_request(record: dict[str, Any]) -> dict[str, Any]:
    content = record["provider_payload"]["messages"][0]["content"]
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    if content.count(begin) != 1 or content.count(end) != 1:
        raise AssertionError("embedded request boundary mismatch")
    return strict_json(content.split(begin, 1)[1].rsplit(end, 1)[0])


def walk_forbidden(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_IDENTITY_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(walk_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(walk_forbidden(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.casefold()
        for length, expected_hash in FORBIDDEN_IDENTITY_TOKEN_HASHES:
            for start in range(0, len(lowered) - length + 1):
                if sha256_bytes(lowered[start : start + length].encode()) == expected_hash:
                    hits.append(f"{path}:forbidden_identity_token")
        short_token = "P" + "3"
        pattern = rf"(?<![A-Za-z0-9]){re.escape(short_token)}(?![A-Za-z0-9])"
        if re.search(pattern, value, re.I):
            hits.append(f"{path}:forbidden_short_token")
    return hits


class JudgeContinuationV2ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with ZipFile(PACKAGE_ZIP) as archive:
            cls.zip_names = archive.namelist()
            cls.members = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
                if not info.is_dir()
            }
        cls.requests = [
            strict_json(line)
            for line in cls.members["BLINDED_JUDGE_REQUESTS.jsonl"].splitlines()
            if line.strip()
        ]
        cls.attempts = load_jsonl(OUTPUT_DIR / "JUDGE_ATTEMPT_JOURNAL.jsonl")
        cls.terminals = load_jsonl(OUTPUT_DIR / "JUDGE_TERMINAL_JOURNAL.jsonl")
        cls.errors = load_jsonl(OUTPUT_DIR / "JUDGE_ERROR_REGISTRY.jsonl")
        cls.status_events = load_jsonl(OUTPUT_DIR / "JUDGE_STATUS_JOURNAL.jsonl")
        cls.final_status = strict_json((OUTPUT_DIR / "JUDGE_EXECUTION_STATUS.json").read_bytes())
        cls.preflight = strict_json((OUTPUT_DIR / "JUDGE_PREFLIGHT_START_RECEIPT.json").read_bytes())
        cls.authorization = strict_json(
            (ARTIFACT_DIR / "judge_execution_authorization_v2.json").read_bytes()
        )
        cls.preservation = strict_json(
            (ARTIFACT_DIR / "historical_v1_preservation_manifest_v2.json").read_bytes()
        )
        cls.source = strict_json(
            (ARTIFACT_DIR / "judge_continuation_source_manifest_v2.json").read_bytes()
        )
        cls.audit = strict_json(
            (ARTIFACT_DIR / "judge_continuation_execution_audit_v2.json").read_bytes()
        )
        cls.review = strict_json((ARTIFACT_DIR / "review_manifest_v2.json").read_bytes())
        cls.by_order = {row["original_logical_order"]: row for row in cls.requests}
        cls.started = [row for row in cls.attempts if row["event"] == "ATTEMPT_STARTED"]
        cls.returned = [row for row in cls.attempts if row["event"] == "ATTEMPT_RETURNED"]
        parser_namespace: dict[str, Any] = {"__name__": "judge_result_parser_v3_offline"}
        exec(
            compile(
                cls.members["judge_result_parser_v3.py"],
                "judge_result_parser_v3.py",
                "exec",
            ),
            parser_namespace,
        )
        cls.parser = parser_namespace

    def test_01_package_zip_members_and_hashes(self) -> None:
        self.assertEqual(sha256_file(PACKAGE_ZIP), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(set(self.members), PACKAGE_FILES)
        self.assertEqual(len(self.zip_names), 13)
        actual = {name: sha256_bytes(data) for name, data in self.members.items()}
        self.assertEqual(actual, self.source["package"]["member_sha256"])
        declared = strict_json(self.members["PACKAGE_SOURCE_HASHES.json"])["member_sha256"]
        self.assertEqual(set(declared), PACKAGE_FILES - {"PACKAGE_SOURCE_HASHES.json"})
        self.assertTrue(all(actual[name] == digest for name, digest in declared.items()))
        self.assertEqual(actual["BLINDED_JUDGE_REQUESTS.jsonl"], EXPECTED_MANIFEST_SHA256)

    def test_02_frozen_configuration_identity(self) -> None:
        config = strict_json(self.members["JUDGE_CONFIGURATION.json"])
        self.assertEqual(config["model"], EXPECTED_MODEL)
        self.assertEqual(config["endpoint"], "OpenAI Chat Completions")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 2048)
        self.assertIs(config["streaming"], False)
        self.assertEqual(config["tools"], "NONE")
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertEqual(config["request_timeout_seconds"], 120.0)
        self.assertEqual(config["minimum_seconds_between_initial_request_starts"], 15.0)
        self.assertEqual(sha256_bytes(self.members["JUDGE_PROMPT.txt"]), "0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e")
        self.assertEqual(sha256_bytes(self.members["JUDGE_SCHEMA.json"]), "5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a")
        self.assertEqual(sha256_bytes(self.members["judge_result_parser_v3.py"]), "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb")
        self.assertEqual(sha256_bytes(self.members["judge_execution_runner_v3.py"]), "db013064a84004b2a7ba8eefd2061736a5e88a402403b38d28dc274d46ca5cf5")

    def test_03_strict_authorization_v2_binding(self) -> None:
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(sha256_file(ARTIFACT_DIR / "judge_execution_authorization_v2.json"), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(self.authorization["schema_version"], "c4-real-judge-execution-authorization-r3-v1")
        self.assertEqual(self.authorization["authorization_id"], "RQ3-REAL-C4-J3C-R1-BILLING-RECOVERY-20260902")
        self.assertEqual(self.authorization["authorized_by"], "Ming Liu")
        self.assertRegex(self.authorization["authorized_at_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(self.authorization["package_id"], "C4_REAL_JUDGE_SHARD_C_CONTINUATION_R3_20260902")
        self.assertEqual(self.authorization["shard_id"], "C_CONTINUATION")
        self.assertEqual(self.authorization["request_count"], 18)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 36)
        self.assertEqual(self.authorization["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(self.authorization["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(self.authorization["status"], "AUTHORIZED")

    def test_04_exact_continuation_request_population(self) -> None:
        self.assertEqual(len(self.requests), 18)
        self.assertTrue(all(set(row) == REQUEST_FIELDS for row in self.requests))
        self.assertEqual([row["original_logical_order"] for row in self.requests], list(range(32, 50)))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.requests}), 18)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.requests}), 18)
        self.assertEqual(len({row["provider_payload_sha256"] for row in self.requests}), 18)
        for row in self.requests:
            self.assertEqual(row["source_shard_id"], "C")
            self.assertEqual(row["continuation_shard_id"], "C_CONTINUATION")
            self.assertEqual(sha256_bytes(canonical_json_bytes(row["provider_payload"])), row["provider_payload_sha256"])

    def test_05_provider_payload_contract(self) -> None:
        for row in self.requests:
            payload = row["provider_payload"]
            self.assertEqual(set(payload), {"model", "messages", "temperature", "max_tokens", "stream", "response_format"})
            self.assertEqual(payload["model"], EXPECTED_MODEL)
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], 2048)
            self.assertIs(payload["stream"], False)
            self.assertEqual(payload["messages"], [payload["messages"][0]])
            self.assertEqual(payload["messages"][0]["role"], "system")
            self.assertEqual(payload["response_format"]["type"], "json_schema")

    def test_06_output_leaf_is_exact_and_immutable(self) -> None:
        self.assertEqual({path.name for path in OUTPUT_DIR.iterdir()}, OUTPUT_FILES)
        self.assertTrue(all(path.is_file() and not path.is_symlink() for path in OUTPUT_DIR.iterdir()))
        self.assertFalse(any(path.name == "__pycache__" or path.suffix == ".pyc" for path in OUTPUT_DIR.rglob("*")))
        actual = {name: sha256_file(OUTPUT_DIR / name) for name in OUTPUT_FILES}
        self.assertEqual(actual, EXPECTED_OUTPUT_HASHES)
        self.assertEqual(actual, self.source["execution_output"]["file_sha256"])

    def test_07_historical_v1_before_after_preservation(self) -> None:
        self.assertEqual(self.preservation["status"], "HISTORICAL_V1_BYTE_IDENTICAL")
        self.assertEqual(self.preservation["artifact_count"], 13)
        self.assertEqual(set(self.preservation["artifacts"]), set(EXPECTED_HISTORICAL_V1))
        for name, expected in EXPECTED_HISTORICAL_V1.items():
            record = self.preservation["artifacts"][name]
            self.assertEqual(record["before_sha256"], expected)
            self.assertEqual(record["after_sha256"], expected)
            self.assertEqual(record["before_size_bytes"], record["after_size_bytes"])
            self.assertIs(record["preserved"], True)
            self.assertEqual(sha256_file(ARTIFACT_DIR / name), expected)
            self.assertEqual((ARTIFACT_DIR / name).stat().st_size, record["after_size_bytes"])
        facts = self.preservation["historical_v1_facts"]
        self.assertEqual(facts["physical_attempts"], 1)
        self.assertEqual(facts["valid_terminal_results"], 0)
        self.assertEqual(facts["returned_provider_results"], 0)
        self.assertEqual(facts["error_class"], "RateLimitError")
        self.assertEqual(facts["provider_error_code"], "credit_balance_exhausted")

    def test_08_runner_preflight_receipt_binding(self) -> None:
        self.assertEqual(self.preflight["status"], "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION")
        self.assertEqual(self.preflight["judge_calls_at_receipt_write"], 0)
        self.assertIs(self.preflight["runtime_constructed_at_receipt_write"], False)
        self.assertIs(self.preflight["client_constructed_at_receipt_write"], False)
        self.assertEqual(self.preflight["authorization_id"], self.authorization["authorization_id"])
        self.assertEqual(self.preflight["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(self.preflight["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(self.preflight["request_count"], 18)
        self.assertEqual(self.preflight["maximum_physical_attempts"], 36)

    def test_09_runtime_retry_and_timeout_identity(self) -> None:
        self.assertEqual([row["status"] for row in self.status_events], [
            "PREFLIGHT_STARTED",
            "RUNTIME_VALIDATED",
            "CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED",
            "INCOMPLETE",
        ])
        runtime = self.status_events[1]["runtime"]
        self.assertEqual(runtime["python_executable"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertIs(runtime["api_key_presence_checked_only"], True)
        self.assertIs(runtime["api_key_value_recorded"], False)
        client = self.status_events[2]["client_configuration"]
        self.assertEqual(client["client_max_retries"], 0)
        self.assertEqual(client["request_timeout_seconds"], 120.0)
        self.assertEqual(client["timeout_components_seconds"], {"connect": 120.0, "pool": 120.0, "read": 120.0, "write": 120.0})
        self.assertIs(client["transport_configuration_verified_before_provider_call"], True)

    def test_10_durable_incomplete_status(self) -> None:
        self.assertEqual(self.final_status["status"], "INCOMPLETE")
        self.assertEqual(self.final_status["request_count"], 18)
        self.assertEqual(self.final_status["valid_terminal_count"], 8)
        self.assertEqual(self.final_status["physical_attempts"], 10)
        self.assertEqual(self.final_status["judge_calls"], 10)
        self.assertEqual(self.final_status["request_timeout_seconds"], 120.0)
        self.assertIs(self.final_status["automatic_resume"], False)
        self.assertIs(self.final_status["continuation_requires_new_direct_authorization"], True)
        self.assertEqual(self.audit["status"], EXPECTED_STATUS)
        self.assertEqual(self.source["status"], EXPECTED_STATUS)

    def test_11_attempt_lifecycle_and_exact_sequence(self) -> None:
        self.assertEqual(len(self.attempts), 20)
        self.assertEqual(len(self.started), 10)
        self.assertEqual(len(self.returned), 10)
        expected = [(order, 1) for order in range(32, 41)] + [(40, 2)]
        self.assertEqual([(row["logical_order"], row["attempt_number"]) for row in self.started], expected)
        self.assertEqual([(row["logical_order"], row["attempt_number"]) for row in self.returned], expected)
        self.assertEqual([row["judge_calls_started"] for row in self.started], list(range(1, 11)))
        self.assertTrue(all(row["request_timeout_seconds"] == 120.0 for row in self.attempts))

    def test_12_terminal_uniqueness_and_coverage(self) -> None:
        self.assertEqual(len(self.terminals), 8)
        self.assertEqual([row["logical_order"] for row in self.terminals], list(range(32, 40)))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 8)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 8)
        self.assertEqual(len({row["provider_response_id"] for row in self.terminals}), 8)
        self.assertTrue(all(set(row) == TERMINAL_FIELDS for row in self.terminals))
        self.assertTrue(all(row["terminal_status"] == "VALID_JUDGE_RESULT" for row in self.terminals))
        self.assertTrue(all(row["physical_attempts"] == 1 for row in self.terminals))

    def test_13_parser_v3_replay_matches_all_terminals(self) -> None:
        valid_returns = [row for row in self.returned if row["failure_code"] is None]
        self.assertEqual(len(valid_returns), 8)
        for returned in valid_returns:
            request = self.by_order[returned["logical_order"]]
            applicability = extract_embedded_request(request)["frozen_applicability_map"]
            parsed = self.parser["parse_judge_result"](
                returned["raw_response_content"],
                applicability,
                expected_judge_result_blind_id=returned["judge_result_blind_id"],
            )
            terminal = next(row for row in self.terminals if row["logical_order"] == returned["logical_order"])
            self.assertEqual(parsed, terminal["parsed_semantic_result"])

    def test_14_applicability_types_rationales_and_local_means(self) -> None:
        for terminal in self.terminals:
            parsed = terminal["parsed_semantic_result"]
            applicability = extract_embedded_request(self.by_order[terminal["logical_order"]])["frozen_applicability_map"]
            self.assertEqual(parsed["response_blind_id"], terminal["judge_result_blind_id"])
            self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
            self.assertIs(type(parsed["evidence_faithfulness"]), int)
            self.assertIn(parsed["evidence_faithfulness"], range(1, 6))
            self.assertIs(type(parsed["unsupported_claim_count"]), int)
            self.assertGreaterEqual(parsed["unsupported_claim_count"], 0)
            self.assertEqual(set(parsed["criterion_rationales"]), set(PRIMARY.values()))
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in parsed["criterion_rationales"].values()))
            expected_mean = self.parser["recompute_overall_applicable_mean"](parsed, applicability)
            self.assertEqual(parsed["overall_applicable_mean"], expected_mean)
            for criterion, field in PRIMARY.items():
                if applicability["criteria"][criterion]:
                    self.assertIs(type(parsed[field]), int)
                    self.assertIn(parsed[field], range(1, 6))
                else:
                    self.assertEqual(parsed[field], "NA")

    def test_15_one_identical_retry_then_applicability_stop(self) -> None:
        failed = [row for row in self.returned if row["failure_code"] is not None]
        self.assertEqual([(row["logical_order"], row["attempt_number"], row["failure_code"]) for row in failed], [
            (40, 1, "APPLICABILITY_CONTRACT_VIOLATION"),
            (40, 2, "APPLICABILITY_CONTRACT_VIOLATION"),
        ])
        self.assertTrue(all(row["logical_judge_request_id"] == EXPECTED_INCOMPLETE_REQUEST_ID for row in failed))
        self.assertTrue(all(row["judge_result_blind_id"] == EXPECTED_INCOMPLETE_RESULT_ID for row in failed))
        self.assertTrue(all(row["provider_payload_sha256"] == EXPECTED_INCOMPLETE_PAYLOAD_SHA256 for row in failed))
        for row in failed:
            request = self.by_order[40]
            applicability = extract_embedded_request(request)["frozen_applicability_map"]
            with self.assertRaises(self.parser["JudgeResultError"]) as caught:
                self.parser["parse_judge_result"](
                    row["raw_response_content"],
                    applicability,
                    expected_judge_result_blind_id=row["judge_result_blind_id"],
                )
            self.assertEqual(self.parser["retryable_failure_code"](caught.exception), "APPLICABILITY_CONTRACT_VIOLATION")
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.errors[0]["error_category"], "APPLICABILITY_CONTRACT_VIOLATION")
        self.assertEqual(self.errors[0]["attempt_number"], 2)
        self.assertEqual(self.errors[0]["terminal_policy"], "STOP_ENTIRE_SHARD")
        self.assertIs(self.errors[0]["continuation_requires_new_direct_authorization"], True)

    def test_16_retry_contract_and_timeout_nonretryability(self) -> None:
        contract = strict_json(self.members["EXECUTION_CONTRACT.json"])
        self.assertEqual(contract["manual_retry"], {
            "maximum_retries": 1,
            "byte_identical": True,
            "correction_message": False,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
        })
        for category in ("RATE_LIMIT", "TIMEOUT", "TRANSPORT", "AUTHENTICATION", "PERMISSION", "REFUSAL", "MODEL_MISMATCH", "CONFIGURATION_ERROR"):
            self.assertIn(category, contract["never_retry_after"])
        self.assertIs(contract["timeout_is_non_retryable"], True)
        self.assertEqual(self.audit["execution_summary"]["retries"], 1)
        self.assertIs(self.audit["retry_evidence"]["byte_identical_provider_payload"], True)
        self.assertIs(self.audit["retry_evidence"]["correction_message_added"], False)

    def test_17_physical_ceiling_and_unattempted_suffix(self) -> None:
        self.assertEqual(self.authorization["maximum_physical_attempts"], 36)
        self.assertEqual(self.final_status["physical_attempts"], 10)
        self.assertLessEqual(self.final_status["physical_attempts"], 36)
        started_orders = {row["logical_order"] for row in self.started}
        self.assertEqual(started_orders, set(range(32, 41)))
        self.assertEqual(set(range(41, 50)) & started_orders, set())
        self.assertEqual(self.audit["execution_summary"]["later_unattempted_requests"], 9)
        self.assertFalse(self.source["preservation"]["automatic_resume_performed"])
        self.assertEqual(self.source["preservation"]["additional_provider_calls_after_stop"], 0)

    def test_18_returned_model_exact_for_every_response(self) -> None:
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in self.returned))
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in self.terminals))
        self.assertEqual(self.audit["result_counts"]["returned_model_errors"], 0)
        self.assertEqual(self.audit["result_validation"]["returned_model"], EXPECTED_MODEL)

    def test_19_initial_request_pacing(self) -> None:
        initial = [row for row in self.started if row["attempt_number"] == 1]
        self.assertEqual([row["logical_order"] for row in initial], list(range(32, 41)))
        parse_time = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
        intervals = [
            (parse_time(right["request_started_at_utc"]) - parse_time(left["request_started_at_utc"])).total_seconds()
            for left, right in zip(initial, initial[1:])
        ]
        self.assertEqual(len(intervals), 8)
        self.assertTrue(all(value >= 15.0 for value in intervals))
        self.assertAlmostEqual(min(intervals), self.audit["pacing_evidence"]["minimum_observed_consecutive_initial_start_interval_seconds"], places=6)

    def test_20_usage_arithmetic_for_valid_and_all_returns(self) -> None:
        valid = {
            key: sum(row[key] for row in self.terminals)
            for key in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens")
        }
        all_returned = {
            key: sum(row[key] for row in self.returned)
            for key in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens")
        }
        for row in self.returned:
            self.assertEqual(row["total_tokens"], row["prompt_tokens"] + row["completion_tokens"])
            self.assertLessEqual(row["cached_input_tokens"], row["prompt_tokens"])
        self.assertEqual(valid, {"prompt_tokens": 24834, "cached_input_tokens": 0, "completion_tokens": 3186, "total_tokens": 28020})
        self.assertEqual(all_returned, {"prompt_tokens": 31216, "cached_input_tokens": 2944, "completion_tokens": 4144, "total_tokens": 35360})
        self.assertEqual(valid, self.audit["usage_for_valid_terminal_results"])
        self.assertEqual(all_returned, self.audit["usage_for_all_returned_attempts"])

    def test_21_terminal_and_parsed_set_hashes(self) -> None:
        self.assertEqual(sha256_file(OUTPUT_DIR / "JUDGE_ATTEMPT_JOURNAL.jsonl"), EXPECTED_ATTEMPT_SHA256)
        self.assertEqual(sha256_file(OUTPUT_DIR / "JUDGE_TERMINAL_JOURNAL.jsonl"), EXPECTED_TERMINAL_SHA256)
        parsed_blob = b"".join(
            canonical_json_bytes(row["parsed_semantic_result"]) + b"\n"
            for row in sorted(self.terminals, key=lambda item: item["logical_order"])
        )
        self.assertEqual(sha256_bytes(parsed_blob), EXPECTED_PARSED_SET_SHA256)
        self.assertEqual(self.source["parsed_result_set"]["terminal_record_count"], 8)
        self.assertEqual(self.source["parsed_result_set"]["sha256"], EXPECTED_PARSED_SET_SHA256)

    def test_22_secret_absence(self) -> None:
        markers = (
            b"OPENAI" + b"_API_KEY=",
            b"Bearer" + b" ",
            b"sk-" + b"proj-",
            b"-----BEGIN " + b"PRIVATE KEY-----",
            b"blinding_" + b"hmac_key.bin",
            b"restricted_" + b"internal/",
        )
        paths = [
            ARTIFACT_DIR / "judge_execution_authorization_v2.json",
            ARTIFACT_DIR / "historical_v1_preservation_manifest_v2.json",
            ARTIFACT_DIR / "judge_continuation_source_manifest_v2.json",
            ARTIFACT_DIR / "judge_continuation_execution_audit_v2.json",
            ARTIFACT_DIR / "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT_V2.md",
            ARTIFACT_DIR / "STATUS_V2.md",
            ARTIFACT_DIR / "review_manifest_v2.json",
            *sorted(OUTPUT_DIR.iterdir()),
        ]
        for path in paths:
            data = path.read_bytes().lower()
            for marker in markers:
                self.assertNotIn(marker.lower(), data, path.name)

    def test_23_no_experimental_identity_or_comparison_results(self) -> None:
        values: list[Any] = []
        values.extend(self.attempts)
        values.extend(self.terminals)
        values.extend(self.errors)
        values.extend(self.status_events)
        values.extend([self.final_status, self.preflight, self.authorization, self.preservation, self.source, self.audit, self.review])
        values.extend([
            (ARTIFACT_DIR / "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT_V2.md").read_text(),
            (ARTIFACT_DIR / "STATUS_V2.md").read_text(),
        ])
        hits: list[str] = []
        for value in values:
            hits.extend(walk_forbidden(value))
        self.assertEqual(hits, [])
        self.assertFalse(self.audit["unauthorized_continuation_performed"])

    def test_24_review_allowlist_and_integration_gate(self) -> None:
        declared = self.review["member_sha256_excluding_manifest"]
        self.assertEqual(set(declared) | {"review_manifest_v2.json"}, REVIEW_FILES)
        self.assertEqual(self.review["archive_entry_count_including_manifest"], 14)
        for name, digest in declared.items():
            self.assertEqual(sha256_file(ARTIFACT_DIR / name), digest)
            self.assertEqual((ARTIFACT_DIR / name).stat().st_size, self.review["member_size_bytes_excluding_manifest"][name])
        self.assertEqual(self.review["status"], EXPECTED_STATUS)
        self.assertEqual(self.audit["integration_gate"], "DO_NOT_INTEGRATE_INCOMPLETE_V2_WITHOUT_NEW_DIRECT_AUTHORIZATION_AND_A_COMPLETE_FROZEN_RESULT_SET")
        self.assertIn(EXPECTED_STATUS, (ARTIFACT_DIR / "STATUS_V2.md").read_text())
        self.assertIn(EXPECTED_INCOMPLETE_REQUEST_ID, (ARTIFACT_DIR / "C4_REAL_JUDGE_CONTINUATION_EXECUTION_REPORT_V2.md").read_text())
        self.assertEqual(NETWORK_EVENTS, [])
        if REVIEW_ZIP.exists():
            with ZipFile(REVIEW_ZIP) as archive:
                self.assertEqual(set(archive.namelist()), REVIEW_FILES)
                for name in REVIEW_FILES:
                    if name != "review_manifest_v2.json":
                        self.assertEqual(sha256_bytes(archive.read(name)), declared[name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
