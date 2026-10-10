#!/usr/bin/env python3
"""Zero-network mechanical tests for the preserved C4 REAL Judge Shard C run."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unittest
from typing import Any
from zipfile import ZipFile


ARTIFACT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ARTIFACT_DIR / "execution_output_v1"
PACKAGE_ZIP = Path(
    os.environ.get(
        "C4_REAL_JUDGE_PACKAGE_ZIP",
        "/Users/liuming/Downloads/"
        "C4_REAL_JUDGE_SHARD_C_EXECUTION_PACKAGE_R2_2026-09-02.zip",
    )
)

EXPECTED_STATUS = "JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION"
EXPECTED_PACKAGE_SHA256 = (
    "7f7863a5dd399ae62136bd5bf7541f6d5fc7347eafb275d22b435b25821639cd"
)
EXPECTED_MANIFEST_SHA256 = (
    "dc65e44ef70298c68f7d70c5123b897388bdcab00a4deaeb0e3a80dececb0f10"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "37ea6b7f59060becfd100e6625e36c5b19d436263466e6fd7a7adf104cddd57f"
)
EXPECTED_TERMINAL_SHA256 = (
    "8d5af59458e65a90b38c363204fd71dea6ee30dad00fd245929e7b26aa151a28"
)
EXPECTED_PARSED_SET_SHA256 = (
    "80c94a06ebe14f8cbf7cb8f63fc7caab95ad59938ebe5b9792e6113dc7140816"
)
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_FIRST_INCOMPLETE_ID = "C4J1-F1E290641A54D4CA04002A97"

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
    "judge_execution_runner_v2.py",
    "judge_result_parser_v2.py",
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
    "shard_id",
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
PROVIDER_FIELDS = {
    *PRIMARY.values(),
    "evidence_faithfulness",
    "unsupported_claim_count",
    "criterion_rationales",
    "schema_version",
}
PARSED_FIELDS = PROVIDER_FIELDS | {"response_blind_id", "overall_applicable_mean"}
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
                candidate = lowered[start : start + length].encode("utf-8")
                if sha256_bytes(candidate) == expected_hash:
                    hits.append(f"{path}:forbidden_identity_token")
        short_token = "P" + "3"
        pattern = rf"(?<![A-Za-z0-9]){re.escape(short_token)}(?![A-Za-z0-9])"
        if re.search(pattern, value, re.I):
            hits.append(f"{path}:forbidden_short_token")
    return hits


class JudgeExecutionArtifactTests(unittest.TestCase):
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
            (ARTIFACT_DIR / "generation_execution_authorization_v1.json").read_bytes()
        )
        cls.source = strict_json(
            (ARTIFACT_DIR / "judge_execution_source_manifest_v1.json").read_bytes()
        )
        cls.audit = strict_json(
            (ARTIFACT_DIR / "judge_execution_audit_v1.json").read_bytes()
        )
        cls.by_order = {index: row for index, row in enumerate(cls.requests, 1)}
        cls.returned_by = {
            (row["logical_order"], row["attempt_number"]): row
            for row in cls.attempts
            if row["event"] == "ATTEMPT_RETURNED"
        }

    def test_01_package_and_manifest_identity(self) -> None:
        self.assertEqual(sha256_file(PACKAGE_ZIP), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(set(self.members), PACKAGE_FILES)
        self.assertEqual(len(self.zip_names), 13)
        actual = {name: sha256_bytes(data) for name, data in self.members.items()}
        self.assertEqual(actual, self.source["package"]["member_sha256"])
        declared = strict_json(self.members["PACKAGE_SOURCE_HASHES.json"])["member_sha256"]
        self.assertEqual(set(declared), PACKAGE_FILES - {"PACKAGE_SOURCE_HASHES.json"})
        self.assertTrue(all(actual[name] == digest for name, digest in declared.items()))
        self.assertEqual(actual["BLINDED_JUDGE_REQUESTS.jsonl"], EXPECTED_MANIFEST_SHA256)

    def test_02_strict_authorization_record_shape(self) -> None:
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(sha256_file(ARTIFACT_DIR / "generation_execution_authorization_v1.json"), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(self.authorization["schema_version"], "c4-real-judge-execution-authorization-r2-v1")
        self.assertEqual(self.authorization["authorization_id"], "RQ3-REAL-C4-J2C-JUDGE-20260902")
        self.assertEqual(self.authorization["authorized_by"], "Ming Liu")
        self.assertRegex(self.authorization["authorized_at_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(self.authorization["package_id"], "C4_REAL_JUDGE_SHARD_C_R2_2026-09-02")
        self.assertEqual(self.authorization["shard_id"], "C")
        self.assertEqual(self.authorization["request_count"], 49)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 98)
        self.assertEqual(self.authorization["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(self.authorization["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(self.authorization["status"], "AUTHORIZED")

    def test_03_exact_request_population(self) -> None:
        self.assertEqual(len(self.requests), 49)
        self.assertTrue(all(set(row) == REQUEST_FIELDS for row in self.requests))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.requests}), 49)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.requests}), 49)
        self.assertEqual(len({row["provider_payload_sha256"] for row in self.requests}), 49)
        for row in self.requests:
            self.assertEqual(row["schema_version"], "c4-real-unique-judge-request-frozen-r2")
            self.assertEqual(row["shard_id"], "C")
            self.assertRegex(row["logical_judge_request_id"], r"^C4J1-[A-F0-9]{24}$")
            self.assertRegex(row["judge_result_blind_id"], r"^R3B-[A-F0-9]{20}$")
            self.assertEqual(sha256_bytes(canonical_json_bytes(row["provider_payload"])), row["provider_payload_sha256"])

    def test_04_output_directory_exclusivity(self) -> None:
        self.assertEqual({path.name for path in OUTPUT_DIR.iterdir()}, OUTPUT_FILES)
        self.assertTrue(all(path.is_file() and not path.is_symlink() for path in OUTPUT_DIR.iterdir()))
        self.assertFalse(any(path.name == "__pycache__" or path.suffix == ".pyc" for path in OUTPUT_DIR.rglob("*")))
        declared = self.source["execution_output"]["file_sha256"]
        self.assertEqual(set(declared), OUTPUT_FILES)
        self.assertTrue(all(sha256_file(OUTPUT_DIR / name) == digest for name, digest in declared.items()))

    def test_05_preflight_receipt(self) -> None:
        self.assertEqual(self.preflight["status"], "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION")
        self.assertEqual(self.preflight["judge_calls_at_receipt_write"], 0)
        self.assertIs(self.preflight["runtime_constructed_at_receipt_write"], False)
        self.assertIs(self.preflight["client_constructed_at_receipt_write"], False)
        self.assertEqual(self.preflight["authorization_id"], self.authorization["authorization_id"])
        self.assertEqual(self.preflight["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(self.preflight["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual([row["status"] for row in self.status_events], [
            "PREFLIGHT_STARTED", "RUNTIME_VALIDATED", "CLIENT_CONSTRUCTED_MAX_RETRIES_ZERO", "INCOMPLETE"
        ])
        runtime = self.status_events[1]["runtime"]
        self.assertEqual(runtime["python_executable"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertIs(runtime["api_key_presence_checked_only"], True)
        self.assertIs(runtime["api_key_value_recorded"], False)

    def test_06_attempt_journal_ordering(self) -> None:
        started = [row for row in self.attempts if row["event"] == "ATTEMPT_STARTED"]
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        self.assertEqual([row["logical_order"] for row in started], list(range(1, 33)))
        self.assertEqual([row["logical_order"] for row in returned], list(range(1, 32)))
        self.assertEqual([row["judge_calls_started"] for row in started], list(range(1, 33)))
        self.assertTrue(all(row["attempt_number"] == 1 for row in self.attempts))
        expected_events = [event for order in range(1, 32) for event in ((order, "ATTEMPT_STARTED"), (order, "ATTEMPT_RETURNED"))]
        expected_events.append((32, "ATTEMPT_STARTED"))
        self.assertEqual([(row["logical_order"], row["event"]) for row in self.attempts], expected_events)

    def test_07_terminal_result_uniqueness(self) -> None:
        self.assertEqual(len(self.terminals), 31)
        self.assertEqual([row["logical_order"] for row in self.terminals], list(range(1, 32)))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 31)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 31)
        self.assertTrue(all(row["terminal_status"] == "VALID_JUDGE_RESULT" for row in self.terminals))

    def test_08_returned_model_identity(self) -> None:
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in returned))
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in self.terminals))
        self.assertFalse(any(row.get("error_category") == "RETURNED_MODEL_MISMATCH" for row in self.errors))

    def test_09_score_and_rationale_parsing(self) -> None:
        for terminal in self.terminals:
            parsed = terminal["parsed_semantic_result"]
            raw = strict_json(self.returned_by[(terminal["logical_order"], terminal["physical_attempts"])]["raw_response_content"])
            self.assertEqual(set(raw), PROVIDER_FIELDS)
            self.assertEqual(set(parsed), PARSED_FIELDS)
            self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
            self.assertIn(parsed["evidence_faithfulness"], range(1, 6))
            self.assertEqual(set(parsed["criterion_rationales"]), set(PRIMARY.values()))
            self.assertTrue(all(isinstance(text, str) and text.strip() and len(text) <= 500 for text in parsed["criterion_rationales"].values()))

    def test_10_applicability_enforcement(self) -> None:
        for terminal in self.terminals:
            embedded = extract_embedded_request(self.by_order[terminal["logical_order"]])
            applicability = embedded["frozen_applicability_map"]
            criteria = applicability["criteria"]
            self.assertEqual(set(criteria), set(PRIMARY))
            self.assertTrue(all(type(criteria[name]) is bool for name in PRIMARY))
            self.assertEqual(applicability["applicable_primary_count"], sum(criteria.values()))
            self.assertEqual(applicability["applicability_sha256"], sha256_bytes(canonical_json_bytes({name: criteria[name] for name in PRIMARY})))
            parsed = terminal["parsed_semantic_result"]
            for criterion, field in PRIMARY.items():
                if criteria[criterion]:
                    self.assertIs(type(parsed[field]), int)
                    self.assertIn(parsed[field], range(1, 6))
                else:
                    self.assertEqual(parsed[field], "NA")

    def test_11_local_result_id_attachment(self) -> None:
        for terminal in self.terminals:
            request = self.by_order[terminal["logical_order"]]
            returned = self.returned_by[(terminal["logical_order"], terminal["physical_attempts"])]
            raw = strict_json(returned["raw_response_content"])
            self.assertNotIn("response_blind_id", raw)
            self.assertEqual(terminal["logical_judge_request_id"], request["logical_judge_request_id"])
            self.assertEqual(terminal["judge_result_blind_id"], request["judge_result_blind_id"])
            self.assertEqual(terminal["parsed_semantic_result"]["response_blind_id"], request["judge_result_blind_id"])

    def test_12_local_exact_mean_for_4_through_8_criteria(self) -> None:
        counts: Counter[int] = Counter()
        for terminal in self.terminals:
            applicability = extract_embedded_request(self.by_order[terminal["logical_order"]])["frozen_applicability_map"]["criteria"]
            parsed = terminal["parsed_semantic_result"]
            scores = [parsed[field] for criterion, field in PRIMARY.items() if applicability[criterion]]
            counts[len(scores)] += 1
            self.assertEqual(parsed["overall_applicable_mean"], sum(scores) / len(scores))
        self.assertEqual(dict(counts), {4: 3, 5: 11, 6: 11, 7: 2, 8: 4})

    def test_13_unsupported_claim_conversion(self) -> None:
        for terminal in self.terminals:
            returned = self.returned_by[(terminal["logical_order"], terminal["physical_attempts"])]
            raw = strict_json(returned["raw_response_content"])
            parsed = terminal["parsed_semantic_result"]
            self.assertRegex(raw["unsupported_claim_count"], r"^(?:0|[1-9][0-9]*)$")
            self.assertIs(type(parsed["unsupported_claim_count"]), int)
            self.assertGreaterEqual(parsed["unsupported_claim_count"], 0)
            self.assertEqual(parsed["unsupported_claim_count"], int(raw["unsupported_claim_count"]))

    def test_14_retry_policy(self) -> None:
        contract = strict_json(self.members["EXECUTION_CONTRACT.json"])
        self.assertEqual(contract["manual_retry"], {
            "maximum_retries": 1,
            "byte_identical": True,
            "correction_message": False,
            "permitted_only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED", "APPLICABILITY_CONTRACT_VIOLATION"],
        })
        self.assertFalse(any(row["attempt_number"] == 2 for row in self.attempts))
        self.assertFalse(any(row.get("failure_code") for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"))
        self.assertEqual(self.errors[0]["error_category"], "APITimeoutError")
        for row in self.attempts:
            self.assertEqual(row["provider_payload_sha256"], self.by_order[row["logical_order"]]["provider_payload_sha256"])

    def test_15_physical_attempt_ceiling(self) -> None:
        started = [row for row in self.attempts if row["event"] == "ATTEMPT_STARTED"]
        self.assertEqual(len(started), 32)
        self.assertEqual(self.final_status["physical_attempts"], 32)
        self.assertEqual(self.final_status["judge_calls"], 32)
        self.assertLessEqual(self.final_status["physical_attempts"], 98)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 98)

    def test_16_fail_closed_state(self) -> None:
        self.assertEqual(self.final_status["status"], "INCOMPLETE")
        self.assertEqual(self.final_status["valid_terminal_count"], 31)
        self.assertIs(self.final_status["automatic_resume"], False)
        self.assertIs(self.final_status["continuation_requires_new_direct_authorization"], True)
        self.assertEqual(len(self.errors), 1)
        error = self.errors[0]
        self.assertEqual(error["phase"], "PROVIDER_CALL")
        self.assertEqual(error["terminal_policy"], "STOP_ENTIRE_SHARD")
        self.assertIs(error["secret_or_authorization_header_recorded"], False)
        self.assertIs(error["continuation_requires_new_direct_authorization"], True)
        self.assertEqual(max(row["logical_order"] for row in self.attempts), 32)
        self.assertEqual(49 - len([row for row in self.attempts if row["event"] == "ATTEMPT_STARTED"]), 17)
        self.assertEqual(self.audit["status"], EXPECTED_STATUS)

    def test_17_usage_arithmetic(self) -> None:
        for terminal in self.terminals:
            self.assertEqual(terminal["total_tokens"], terminal["prompt_tokens"] + terminal["completion_tokens"])
            self.assertGreaterEqual(terminal["prompt_tokens"], 0)
            self.assertGreaterEqual(terminal["completion_tokens"], 0)
            self.assertGreaterEqual(terminal["cached_input_tokens"], 0)
            self.assertLessEqual(terminal["cached_input_tokens"], terminal["prompt_tokens"])
        totals = {
            "prompt_tokens": sum(row["prompt_tokens"] for row in self.terminals),
            "cached_input_tokens": sum(row["cached_input_tokens"] for row in self.terminals),
            "completion_tokens": sum(row["completion_tokens"] for row in self.terminals),
            "total_tokens": sum(row["total_tokens"] for row in self.terminals),
        }
        self.assertEqual(totals, {"prompt_tokens": 91212, "cached_input_tokens": 1536, "completion_tokens": 11833, "total_tokens": 103045})
        self.assertEqual(totals, self.audit["usage_for_valid_terminal_results"])

    def test_18_secret_scan(self) -> None:
        markers = (
            b"OPENAI" + b"_API_KEY=",
            b"Bearer" + b" ",
            b"sk-" + b"proj-",
            b"-----BEGIN " + b"PRIVATE KEY-----",
            b"c4_real_i1_" + b"blinding_hmac_key.bin",
            b"restricted_" + b"internal/",
        )
        paths = [
            ARTIFACT_DIR / "generation_execution_authorization_v1.json",
            ARTIFACT_DIR / "judge_execution_source_manifest_v1.json",
            ARTIFACT_DIR / "judge_execution_audit_v1.json",
            ARTIFACT_DIR / "C4_REAL_JUDGE_SHARD_EXECUTION_REPORT.md",
            ARTIFACT_DIR / "STATUS.md",
            *sorted(OUTPUT_DIR.iterdir()),
        ]
        for path in paths:
            data = path.read_bytes().lower()
            for marker in markers:
                self.assertNotIn(marker.lower(), data, path.name)

    def test_19_absence_of_blinded_identities_and_final_results(self) -> None:
        values: list[Any] = [extract_embedded_request(row) for row in self.requests]
        values.extend(self.attempts)
        values.extend(self.terminals)
        values.extend(self.errors)
        values.extend(self.status_events)
        values.extend([self.final_status, self.preflight, self.authorization, self.source, self.audit])
        hits: list[str] = []
        for value in values:
            hits.extend(walk_forbidden(value))
        self.assertEqual(hits, [])

    def test_20_future_integration_compatibility(self) -> None:
        self.assertEqual(sha256_file(OUTPUT_DIR / "JUDGE_TERMINAL_JOURNAL.jsonl"), EXPECTED_TERMINAL_SHA256)
        parsed_blob = b"".join(
            canonical_json_bytes(row["parsed_semantic_result"]) + b"\n"
            for row in sorted(self.terminals, key=lambda item: item["logical_order"])
        )
        self.assertEqual(sha256_bytes(parsed_blob), EXPECTED_PARSED_SET_SHA256)
        for row in self.terminals:
            self.assertEqual(set(row), TERMINAL_FIELDS)
            self.assertEqual(row["schema_version"], "c4-real-judge-terminal-r2-v1")
            self.assertEqual(row["parsed_semantic_result"]["schema_version"], "rq3-judge-response-v1")
        self.assertEqual(self.source["status"], EXPECTED_STATUS)
        self.assertEqual(self.audit["integration_gate"], "DO_NOT_INTEGRATE_INCOMPLETE_SHARD_WITHOUT_NEW_DIRECT_AUTHORIZATION_AND_A_COMPLETE_FROZEN_RESULT_SET")
        self.assertIn(EXPECTED_STATUS, (ARTIFACT_DIR / "STATUS.md").read_text())
        self.assertIn(EXPECTED_FIRST_INCOMPLETE_ID, (ARTIFACT_DIR / "C4_REAL_JUDGE_SHARD_EXECUTION_REPORT.md").read_text())
        self.assertEqual(NETWORK_EVENTS, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
