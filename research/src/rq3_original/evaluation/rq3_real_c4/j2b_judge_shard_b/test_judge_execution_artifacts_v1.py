#!/opt/anaconda3/bin/python3
"""Zero-network mechanical tests for the frozen C4 REAL Judge Shard B result."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
import sys
import unittest
import zipfile


EXPECTED_PACKAGE_SHA256 = (
    "decc499163089e467ae6ec0e5d4f4e46a410f3670a99b17cf0c6396031ffb68b"
)
EXPECTED_MANIFEST_SHA256 = (
    "e6a20b1bc2b0b980c514e74db37a9791bd15eaa0e69cdf07f6d1f56ff6a5a1f3"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "e4392851e9949955e6c834ddbfe04d1d827ce0251b7cf48876101f4387c5ff28"
)
EXPECTED_TERMINAL_SHA256 = (
    "ec90b7e4994f0ace2dcbfed2965066e790fe720affc7d155cc374c88148c5a44"
)
EXPECTED_PARSED_SET_SHA256 = (
    "93c8c3f106a59e697612bf2751f534ea1fb58e00f1f7d184a945d2cf5f6889bc"
)
EXPECTED_PACKAGE_ID = "C4_REAL_JUDGE_SHARD_B_R2_2026-09-02"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-J2B-JUDGE-20260902"
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
    "judge_execution_runner_v2.py",
    "judge_result_parser_v2.py",
    "test_package.py",
    "validate_package.py",
}
EXPECTED_OUTPUT_FILES = {
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
    "provider_response_id",
    "returned_model",
    "system_fingerprint",
    "finish_reason",
    "prompt_tokens",
    "cached_input_tokens",
    "completion_tokens",
    "total_tokens",
}
EXPECTED_OUTPUT_HASHES = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "fa34d09149e4874c6380445836ba28f5e8f3ab47363619add1a2f8684c3500ca"
    ),
    "JUDGE_ERROR_REGISTRY.jsonl": (
        "f344c71d9950641aaa0882fe35c1202e9d85740cefabdc8237eb85814a15904f"
    ),
    "JUDGE_EXECUTION_STATUS.json": (
        "ab411e39f38691eff16630439ed31419675511f9a2a0675ad032048157c3b69b"
    ),
    "JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "32e82641b5fafbd94470beb42bad3ed3cd2c8e4358c3befbeb0626ed2cc2c35e"
    ),
    "JUDGE_STATUS_JOURNAL.jsonl": (
        "76bfe9200c9bc49103c5e4884effc893bd90fccf2b3bafe9b161c79afdcc832b"
    ),
    "JUDGE_TERMINAL_JOURNAL.jsonl": EXPECTED_TERMINAL_SHA256,
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
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


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
    provider_payload = request["provider_payload"]
    assert isinstance(provider_payload, dict)
    messages = provider_payload["messages"]
    assert isinstance(messages, list) and messages
    first_message = messages[0]
    assert isinstance(first_message, dict)
    content = first_message["content"]
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
                raise ValueError("applicable primary score is invalid")
            scores.append(value)
        elif value != "NA":
            raise ValueError("inapplicable primary score is not NA")
    if not 4 <= len(scores) <= 8:
        raise ValueError("applicable primary count is outside the frozen range")
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


class JudgeShardBArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact_root = Path(__file__).resolve().parent
        cls.output_dir = cls.artifact_root / "execution_output_v1"
        cls.package_zip = PACKAGE_ZIP.resolve()
        cls.authorization_path = (
            cls.artifact_root / "generation_execution_authorization_v1.json"
        )
        cls.source_manifest_path = (
            cls.artifact_root / "judge_execution_source_manifest_v1.json"
        )
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
        cls.authorization = strict_json(cls.authorization_path.read_bytes())
        cls.source_manifest = strict_json(cls.source_manifest_path.read_bytes())
        cls.attempts = read_jsonl_file(
            cls.output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl"
        )
        cls.starts = [row for row in cls.attempts if row["event"] == "ATTEMPT_STARTED"]
        cls.returns = [
            row for row in cls.attempts if row["event"] == "ATTEMPT_RETURNED"
        ]
        cls.terminals = read_jsonl_file(
            cls.output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl"
        )
        cls.errors = read_jsonl_file(
            cls.output_dir / "JUDGE_ERROR_REGISTRY.jsonl"
        )
        cls.status_events = read_jsonl_file(
            cls.output_dir / "JUDGE_STATUS_JOURNAL.jsonl"
        )
        cls.status = strict_json(
            (cls.output_dir / "JUDGE_EXECUTION_STATUS.json").read_bytes()
        )
        cls.preflight = strict_json(
            (cls.output_dir / "JUDGE_PREFLIGHT_START_RECEIPT.json").read_bytes()
        )

    def test_01_package_archive_identity_and_allowlist(self) -> None:
        self.assertEqual(sha256_file(self.package_zip), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(len(self.package_infos), 13)
        self.assertTrue(all(not info.is_dir() for info in self.package_infos))
        self.assertEqual(
            {info.filename for info in self.package_infos}, EXPECTED_PACKAGE_MEMBERS
        )
        self.assertEqual(len({info.filename for info in self.package_infos}), 13)

    def test_02_package_member_hashes(self) -> None:
        declared = strict_json(self.package_bytes["PACKAGE_SOURCE_HASHES.json"])
        member_hashes = declared["member_sha256"]
        self.assertIsInstance(member_hashes, dict)
        self.assertEqual(set(member_hashes), EXPECTED_PACKAGE_MEMBERS - {
            "PACKAGE_SOURCE_HASHES.json"
        })
        for name, expected in member_hashes.items():
            self.assertEqual(sha256_bytes(self.package_bytes[name]), expected)
        self.assertEqual(
            sha256_bytes(self.package_bytes["PACKAGE_SOURCE_HASHES.json"]),
            "61a7d9277efef07ed7c06607a4dbb930ec3af53f713ea01339611b4e333f169b",
        )

    def test_03_blinded_request_population_and_identity(self) -> None:
        self.assertEqual(
            sha256_bytes(self.package_bytes["BLINDED_JUDGE_REQUESTS.jsonl"]),
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(len(self.requests), 49)
        self.assertEqual({row["shard_id"] for row in self.requests}, {"B"})
        self.assertEqual(
            len({row["logical_judge_request_id"] for row in self.requests}), 49
        )
        self.assertEqual(
            len({row["judge_result_blind_id"] for row in self.requests}), 49
        )
        self.assertEqual(sum(row["estimated_input_tokens"] for row in self.requests), 176712)

    def test_04_frozen_provider_identity(self) -> None:
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

    def test_05_authorization_record_shape_and_binding(self) -> None:
        self.assertEqual(sha256_file(self.authorization_path), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(
            self.authorization["schema_version"],
            "c4-real-judge-execution-authorization-r2-v1",
        )
        self.assertEqual(self.authorization["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(self.authorization["authorized_by"], "Ming Liu")
        self.assertRegex(
            self.authorization["authorized_at_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertEqual(self.authorization["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.authorization["shard_id"], "B")
        self.assertEqual(self.authorization["request_count"], 49)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 98)
        self.assertEqual(self.authorization["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            self.authorization["blinded_judge_manifest_sha256"],
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(self.authorization["status"], "AUTHORIZED")

    def test_06_output_directory_exclusivity_and_allowlist(self) -> None:
        execution_leaves = sorted(self.artifact_root.glob("execution_output_v*"))
        self.assertEqual(execution_leaves, [self.output_dir])
        self.assertEqual(
            {path.name for path in self.output_dir.iterdir() if path.is_file()},
            EXPECTED_OUTPUT_FILES,
        )
        self.assertTrue(all(path.is_file() for path in self.output_dir.iterdir()))

    def test_07_preflight_receipt(self) -> None:
        receipt = self.preflight
        self.assertEqual(
            receipt["status"],
            "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
        )
        self.assertEqual(receipt["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(receipt["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(receipt["shard_id"], "B")
        self.assertEqual(receipt["request_count"], 49)
        self.assertEqual(receipt["maximum_physical_attempts"], 98)
        self.assertEqual(receipt["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(receipt["blinded_judge_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(receipt["judge_calls_at_receipt_write"], 0)
        self.assertIs(receipt["runtime_constructed_at_receipt_write"], False)
        self.assertIs(receipt["client_constructed_at_receipt_write"], False)
        self.assertIs(receipt["automatic_resume"], False)

    def test_08_runtime_identity(self) -> None:
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
            if row["status"] == "CLIENT_CONSTRUCTED_MAX_RETRIES_ZERO"
        ]
        self.assertEqual(len(client_events), 1)
        self.assertEqual(client_events[0]["judge_calls"], 0)

    def test_09_execution_status_and_counts(self) -> None:
        self.assertEqual(self.status["status"], "INCOMPLETE")
        self.assertEqual(self.status["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.status["shard_id"], "B")
        self.assertEqual(self.status["request_count"], 49)
        self.assertEqual(self.status["valid_terminal_count"], 38)
        self.assertEqual(self.status["physical_attempts"], 39)
        self.assertEqual(self.status["judge_calls"], 39)
        self.assertIs(self.status["automatic_resume"], False)
        self.assertIs(self.status["continuation_requires_new_direct_authorization"], True)

    def test_10_attempt_journal_ordering(self) -> None:
        self.assertEqual(len(self.attempts), 77)
        self.assertEqual(len(self.starts), 39)
        self.assertEqual(len(self.returns), 38)
        by_order: dict[int, list[str]] = {}
        for row in self.attempts:
            by_order.setdefault(row["logical_order"], []).append(row["event"])
        self.assertEqual(sorted(by_order), list(range(1, 40)))
        for order in range(1, 39):
            self.assertEqual(by_order[order], ["ATTEMPT_STARTED", "ATTEMPT_RETURNED"])
        self.assertEqual(by_order[39], ["ATTEMPT_STARTED"])
        self.assertEqual([row["judge_calls_started"] for row in self.starts], list(range(1, 40)))
        self.assertEqual({row["attempt_number"] for row in self.attempts}, {1})

    def test_11_provider_payload_hash_binding(self) -> None:
        for order, request in enumerate(self.requests, 1):
            self.assertEqual(
                sha256_bytes(canonical_json_bytes(request["provider_payload"])),
                request["provider_payload_sha256"],
            )
            for row in self.attempts:
                if row["logical_order"] == order:
                    self.assertEqual(
                        row["provider_payload_sha256"], request["provider_payload_sha256"]
                    )
            for row in self.terminals:
                if row["logical_order"] == order:
                    self.assertEqual(
                        row["provider_payload_sha256"], request["provider_payload_sha256"]
                    )

    def test_12_terminal_uniqueness_and_population(self) -> None:
        self.assertEqual(len(self.terminals), 38)
        self.assertEqual([row["logical_order"] for row in self.terminals], list(range(1, 39)))
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 38)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 38)
        self.assertEqual({row["terminal_status"] for row in self.terminals}, {"VALID_JUDGE_RESULT"})
        for row in self.terminals:
            request = self.requests[row["logical_order"] - 1]
            self.assertEqual(row["logical_judge_request_id"], request["logical_judge_request_id"])
            self.assertEqual(row["judge_result_blind_id"], request["judge_result_blind_id"])

    def test_13_returned_model_identity(self) -> None:
        self.assertEqual({row["returned_model"] for row in self.returns}, {EXPECTED_MODEL})
        self.assertEqual({row["returned_model"] for row in self.terminals}, {EXPECTED_MODEL})

    def test_14_strict_provider_output_shape(self) -> None:
        for row in self.returns:
            raw = strict_json(row["raw_response_content"])
            self.assertEqual(set(raw), PROVIDER_FIELDS)
            self.assertEqual(raw["schema_version"], "rq3-judge-response-r3d1-r2-transport")
            self.assertNotIn("overall_applicable_mean", raw)
            self.assertNotIn("response_blind_id", raw)

    def test_15_applicability_enforcement(self) -> None:
        observed_counts: list[int] = []
        for row in self.returns:
            request = self.requests[row["logical_order"] - 1]
            applicability = frozen_applicability(request)
            self.assertEqual(
                set(applicability),
                {"schema_version", "freeze_status", "criteria", "applicable_primary_count", "applicability_sha256"},
            )
            self.assertEqual(applicability["schema_version"], "rq3-dimension-applicability-map-v1")
            self.assertEqual(applicability["freeze_status"], "FROZEN_BEFORE_CANDIDATE_SCORING")
            criteria = applicability["criteria"]
            self.assertEqual(set(criteria), set(PRIMARY_CRITERIA))
            count = sum(criteria[name] for name in PRIMARY_CRITERIA)
            self.assertEqual(count, applicability["applicable_primary_count"])
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
            observed_counts.append(count)
        self.assertGreaterEqual(min(observed_counts), 4)
        self.assertLessEqual(max(observed_counts), 8)

    def test_16_parsed_result_shape_and_types(self) -> None:
        for row in self.terminals:
            parsed = row["parsed_semantic_result"]
            self.assertEqual(set(parsed), PARSED_FIELDS)
            self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
            self.assertIs(type(parsed["evidence_faithfulness"]), int)
            self.assertGreaterEqual(parsed["evidence_faithfulness"], 1)
            self.assertLessEqual(parsed["evidence_faithfulness"], 5)
            self.assertIs(type(parsed["unsupported_claim_count"]), int)
            self.assertGreaterEqual(parsed["unsupported_claim_count"], 0)
            self.assertIs(type(parsed["overall_applicable_mean"]), float)

    def test_17_rationale_contract(self) -> None:
        for row in self.terminals:
            rationales = row["parsed_semantic_result"]["criterion_rationales"]
            self.assertEqual(set(rationales), set(SCORE_FIELDS.values()))
            for rationale in rationales.values():
                self.assertIsInstance(rationale, str)
                self.assertTrue(rationale.strip())
                self.assertLessEqual(len(rationale), 500)

    def test_18_local_result_id_attachment(self) -> None:
        for row in self.terminals:
            parsed = row["parsed_semantic_result"]
            self.assertEqual(parsed["response_blind_id"], row["judge_result_blind_id"])
            request = self.requests[row["logical_order"] - 1]
            self.assertEqual(parsed["response_blind_id"], request["judge_result_blind_id"])

    def test_19_local_exact_mean_and_secondary_exclusion(self) -> None:
        for row in self.terminals:
            request = self.requests[row["logical_order"] - 1]
            applicability = frozen_applicability(request)
            parsed = row["parsed_semantic_result"]
            scores = [
                parsed[SCORE_FIELDS[criterion]]
                for criterion in PRIMARY_CRITERIA
                if applicability["criteria"][criterion]
            ]
            self.assertEqual(parsed["overall_applicable_mean"], sum(scores) / len(scores))
            self.assertEqual(
                parsed["overall_applicable_mean"],
                recompute_primary_mean(parsed, applicability),
            )
            self.assertNotIn("evidence_faithfulness", SCORE_FIELDS.values())
            self.assertNotIn("unsupported_claim_count", SCORE_FIELDS.values())

    def test_20_synthetic_exact_means_for_4_through_8_criteria(self) -> None:
        for count in range(4, 9):
            criteria = {
                criterion: index < count
                for index, criterion in enumerate(PRIMARY_CRITERIA)
            }
            parsed = {
                SCORE_FIELDS[criterion]: ((index % 5) + 1) if index < count else "NA"
                for index, criterion in enumerate(PRIMARY_CRITERIA)
            }
            scores = [parsed[SCORE_FIELDS[criterion]] for criterion in PRIMARY_CRITERIA[:count]]
            applicability = {"criteria": criteria}
            self.assertEqual(recompute_primary_mean(parsed, applicability), sum(scores) / count)

    def test_21_unsupported_claim_conversion(self) -> None:
        returns_by_order = {row["logical_order"]: row for row in self.returns}
        for terminal in self.terminals:
            raw = strict_json(returns_by_order[terminal["logical_order"]]["raw_response_content"])
            self.assertRegex(raw["unsupported_claim_count"], r"^(?:0|[1-9][0-9]*)$")
            self.assertEqual(
                terminal["parsed_semantic_result"]["unsupported_claim_count"],
                int(raw["unsupported_claim_count"]),
            )

    def test_22_retry_policy_and_physical_attempt_ceiling(self) -> None:
        allowed = {
            "INVALID_JSON",
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "APPLICABILITY_CONTRACT_VIOLATION",
        }
        self.assertEqual(sum(row["attempt_number"] == 2 for row in self.starts), 0)
        self.assertTrue(all(row.get("failure_code") is None for row in self.returns))
        self.assertTrue(
            all(row.get("failure_code") in allowed | {None} for row in self.returns)
        )
        self.assertLessEqual(len(self.starts), 98)
        self.assertEqual(len(self.starts), self.status["physical_attempts"])

    def test_23_fail_closed_incomplete_state(self) -> None:
        self.assertEqual(len(self.errors), 1)
        error = self.errors[0]
        self.assertEqual(error["error_category"], "APITimeoutError")
        self.assertEqual(error["phase"], "PROVIDER_CALL")
        self.assertEqual(error["terminal_policy"], "STOP_ENTIRE_SHARD")
        self.assertIs(error["continuation_requires_new_direct_authorization"], True)
        self.assertIs(error["secret_or_authorization_header_recorded"], False)
        self.assertEqual(self.starts[-1]["logical_order"], 39)
        self.assertEqual(
            self.starts[-1]["logical_judge_request_id"],
            "C4J1-82EC5072C57932A5BB9E01DC",
        )
        self.assertNotIn(39, {row["logical_order"] for row in self.terminals})
        self.assertEqual(self.status_events[-1]["status"], "INCOMPLETE")
        self.assertEqual(self.status_events[-1]["failure_phase"], "PROVIDER_CALL")
        self.assertEqual(self.status_events[-1]["valid_terminal_count"], 38)

    def test_24_usage_arithmetic_and_totals(self) -> None:
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
                "prompt_tokens": 115712,
                "cached_input_tokens": 6144,
                "completion_tokens": 15771,
                "total_tokens": 131483,
            },
        )

    def test_25_hashes_secret_scan_and_restricted_field_absence(self) -> None:
        self.assertEqual(sha256_file(self.output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl"), EXPECTED_TERMINAL_SHA256)
        for name, expected_hash in EXPECTED_OUTPUT_HASHES.items():
            self.assertEqual(sha256_file(self.output_dir / name), expected_hash)
        reviewable_bytes = self.authorization_path.read_bytes() + b"".join(
            (self.output_dir / name).read_bytes() for name in sorted(EXPECTED_OUTPUT_FILES)
        )
        self.assertIsNone(re.search(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", reviewable_bytes))
        authorization_bearer_marker = b"Authorization:" + b" Bearer "
        self.assertNotIn(authorization_bearer_marker, reviewable_bytes)
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
        for returned in self.returns:
            keys.update(collect_keys(strict_json(returned["raw_response_content"])))
        self.assertFalse(keys & forbidden_keys)

    def test_26_future_integration_compatibility_and_result_set_hash(self) -> None:
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
        self.assertEqual(sha256_bytes(canonical_json_bytes(projection)), EXPECTED_PARSED_SET_SHA256)
        self.assertEqual(self.source_manifest["terminal_journal_sha256"], EXPECTED_TERMINAL_SHA256)
        self.assertEqual(self.source_manifest["parsed_result_set"]["sha256"], EXPECTED_PARSED_SET_SHA256)
        self.assertEqual(self.status["status"], "INCOMPLETE")
        self.assertIs(self.status["continuation_requires_new_direct_authorization"], True)


def parse_arguments() -> tuple[Path, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--package-zip", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    return args.package_zip, remaining


if __name__ == "__main__":
    PACKAGE_ZIP, unittest_arguments = parse_arguments()
    unittest.main(argv=[sys.argv[0], *unittest_arguments], verbosity=2)
else:
    PACKAGE_ZIP = Path("/nonexistent/package.zip")
