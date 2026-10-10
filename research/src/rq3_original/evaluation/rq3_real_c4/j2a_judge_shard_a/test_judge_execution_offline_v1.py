#!/usr/bin/env python3
"""Zero-network mechanical checks for the frozen C4 REAL Judge Shard A run."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import unittest
import zipfile
import zlib


ARTIFACT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ARTIFACT_DIR / "execution_output_v1"
PACKAGE_ZIP = Path(
    os.environ.get(
        "C4_REAL_JUDGE_PACKAGE_ZIP",
        "/Users/liuming/Downloads/"
        "C4_REAL_JUDGE_SHARD_A_EXECUTION_PACKAGE_R2_2026-09-02.zip",
    )
)

EXPECTED_PACKAGE_SHA256 = (
    "7e57d62a56feb2776398fd2b719a009e3eed64c8ebb6b48fc63666eaed300ff7"
)
EXPECTED_MANIFEST_SHA256 = (
    "8ada68b5e3aec8b7c6e90715aebeb65d954d5b5bf9bfc3b5fe63f10b489041ef"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "aade6aa4a1c3d9eb6b974f6d9f643ea577c166b94de02d7d3a050c59391b8c3c"
)
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_PACKAGE_ID = "C4_REAL_JUDGE_SHARD_A_R2_2026-09-02"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-J2A-JUDGE-20260902"
EXPECTED_FIRST_REQUEST_ID = "C4J1-3710B4EC97A1D5C02185C632"
EXPECTED_FIRST_RESULT_ID = "R3B-EAF3EBD895645A0906ED"
EXPECTED_FIRST_PAYLOAD_SHA256 = (
    "abd10878cd7a0d7b983922cd8df3066a536e53ad018bec1b905d5e1516bad2e3"
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

EXPECTED_MEMBER_SHA256 = {
    "APPLICABILITY_CONTRACT.json": (
        "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e"
    ),
    "BLINDED_JUDGE_REQUESTS.jsonl": EXPECTED_MANIFEST_SHA256,
    "EXECUTION_CONTRACT.json": (
        "4879a0ce178a8a24d062ef5465b67fce25fe7645d0a83965d7635cdcd9564caa"
    ),
    "JUDGE_CONFIGURATION.json": (
        "00d2778c92bfb874431a9f41e635526e0abbb9ddbe8b4fc46ed7c8afd39a64bf"
    ),
    "JUDGE_PROMPT.txt": (
        "0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e"
    ),
    "JUDGE_SCHEMA.json": (
        "5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a"
    ),
    "PACKAGE_SOURCE_HASHES.json": (
        "5289f13d536b2d8114d9fe575ab474f5bfab2da765ae3bd30092c2900759eaa5"
    ),
    "PRIMARY_RUBRIC.json": (
        "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
    ),
    "README.md": (
        "fb38f4b9dd9f22667dc1300a757d7af67590ac008db5ee9afa38ad33f083ed30"
    ),
    "judge_execution_runner_v2.py": (
        "d415556ea34d2c3cae528c90148b63f0a74f8331445fcabfc78c1244278b3b21"
    ),
    "judge_result_parser_v2.py": (
        "1e96677613423791a7c711b8b69af2c69179ca4eee66dc22635753b502c74f9a"
    ),
    "test_package.py": (
        "e3d047276db5ffa144bedfcdcaf3276508bf5e0fc973a458c47de7dcb9963804"
    ),
    "validate_package.py": (
        "ebdfeab34384c3b49d86b4e0ee489488acc739bcb7c050d5dbbdff8fe44458f6"
    ),
}

EXPECTED_OUTPUT_SHA256 = {
    "JUDGE_ATTEMPT_JOURNAL.jsonl": (
        "53fc0cd24e492ef8f585b6789c64f2e5fa0a13486298910c6e3224eaf36f0bf6"
    ),
    "JUDGE_ERROR_REGISTRY.jsonl": (
        "6546d5212f7520e2eeeaeb494e85246cd5ccd50284fad0e4b10f00f5a5a18d7c"
    ),
    "JUDGE_EXECUTION_STATUS.json": (
        "27766300e0cbf209a3972995079ed0a2f938632ccf91c3ca21c799d45b1c0c28"
    ),
    "JUDGE_PREFLIGHT_START_RECEIPT.json": (
        "88595aeb5a3ccabcf1ccb49b3e76942b5949f90ab55272d8d5272a9069ba6bae"
    ),
    "JUDGE_STATUS_JOURNAL.jsonl": (
        "3a88a80c3c7591551df19878698487aded8999b7c630a622751ce2b3fd2e5042"
    ),
    "JUDGE_TERMINAL_JOURNAL.jsonl": EMPTY_SHA256,
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AssertionError(f"Expected JSONL object: {path}")
            rows.append(value)
    return rows


def all_object_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(all_object_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(all_object_keys(child))
    return keys


class JudgeShardAOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authorization = load_json(
            ARTIFACT_DIR / "generation_execution_authorization_v1.json"
        )
        cls.source_manifest = load_json(
            ARTIFACT_DIR / "judge_execution_source_manifest_v1.json"
        )
        cls.audit = load_json(ARTIFACT_DIR / "judge_execution_audit_v1.json")
        cls.review_manifest = load_json(ARTIFACT_DIR / "REVIEW_MANIFEST.json")
        cls.status = load_json(OUTPUT_DIR / "JUDGE_EXECUTION_STATUS.json")
        cls.preflight = load_json(OUTPUT_DIR / "JUDGE_PREFLIGHT_START_RECEIPT.json")
        cls.attempts = load_jsonl(OUTPUT_DIR / "JUDGE_ATTEMPT_JOURNAL.jsonl")
        cls.terminals = load_jsonl(OUTPUT_DIR / "JUDGE_TERMINAL_JOURNAL.jsonl")
        cls.errors = load_jsonl(OUTPUT_DIR / "JUDGE_ERROR_REGISTRY.jsonl")
        cls.status_events = load_jsonl(OUTPUT_DIR / "JUDGE_STATUS_JOURNAL.jsonl")
        with zipfile.ZipFile(PACKAGE_ZIP) as archive:
            cls.package_infos = archive.infolist()
            cls.package_members = {
                info.filename: archive.read(info) for info in cls.package_infos
            }
        cls.requests = [
            json.loads(line)
            for line in cls.package_members[
                "BLINDED_JUDGE_REQUESTS.jsonl"
            ].decode("utf-8").splitlines()
            if line.strip()
        ]
        parser_namespace: dict[str, object] = {
            "__name__": "judge_result_parser_v2_offline"
        }
        exec(
            compile(
                cls.package_members["judge_result_parser_v2.py"],
                "judge_result_parser_v2.py",
                "exec",
            ),
            parser_namespace,
        )
        cls.parser = parser_namespace

    @staticmethod
    def applicability_from_request(record: dict[str, object]) -> dict[str, object]:
        payload = record["provider_payload"]
        assert isinstance(payload, dict)
        messages = payload["messages"]
        assert isinstance(messages, list)
        first = messages[0]
        assert isinstance(first, dict)
        content = first["content"]
        assert isinstance(content, str)
        embedded = json.loads(
            content.split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1].rsplit(
                "\nEND_BLIND_JUDGE_REQUEST_JSON", 1
            )[0]
        )
        return embedded["frozen_applicability_map"]

    @classmethod
    def synthetic_case(
        cls, applicable_count: int, unsupported_claim_count: str = "0"
    ) -> tuple[dict[str, object], dict[str, object], float]:
        criteria_names = cls.parser["PRIMARY_CRITERIA"]
        score_fields = cls.parser["SCORE_FIELDS"]
        assert isinstance(criteria_names, tuple)
        assert isinstance(score_fields, dict)
        flags = {
            name: index < applicable_count
            for index, name in enumerate(criteria_names)
        }
        applicability = {
            "schema_version": "rq3-dimension-applicability-map-v1",
            "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
            "criteria": flags,
            "applicable_primary_count": applicable_count,
            "applicability_sha256": sha256_bytes(canonical_json_bytes(flags)),
        }
        scores = [1, 2, 3, 4, 5, 1, 2, 3]
        payload: dict[str, object] = {
            score_fields[name]: str(scores[index]) if flags[name] else "NA"
            for index, name in enumerate(criteria_names)
        }
        payload.update(
            {
                "evidence_faithfulness": "5",
                "unsupported_claim_count": unsupported_claim_count,
                "criterion_rationales": {
                    score_fields[name]: "Offline parser contract check."
                    for name in criteria_names
                },
                "schema_version": "rq3-judge-response-r3d1-r2-transport",
            }
        )
        expected_mean = sum(scores[:applicable_count]) / applicable_count
        return payload, applicability, expected_mean

    def test_01_package_zip_identity_and_exact_allowlist(self) -> None:
        self.assertEqual(sha256_file(PACKAGE_ZIP), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(len(self.package_infos), 13)
        self.assertEqual(set(self.package_members), set(EXPECTED_MEMBER_SHA256))
        self.assertEqual(len(self.package_infos), len(set(self.package_members)))
        self.assertTrue(all(not info.is_dir() for info in self.package_infos))

    def test_02_package_member_hash_size_crc_and_internal_manifest(self) -> None:
        recorded = {
            row["name"]: row
            for row in self.source_manifest["package"]["members"]
        }
        self.assertEqual(set(recorded), set(EXPECTED_MEMBER_SHA256))
        for info in self.package_infos:
            data = self.package_members[info.filename]
            self.assertEqual(sha256_bytes(data), EXPECTED_MEMBER_SHA256[info.filename])
            self.assertEqual(recorded[info.filename]["sha256"], sha256_bytes(data))
            self.assertEqual(recorded[info.filename]["size_bytes"], len(data))
            self.assertEqual(recorded[info.filename]["crc32"], f"{zlib.crc32(data):08x}")
        internal = json.loads(
            self.package_members["PACKAGE_SOURCE_HASHES.json"].decode("utf-8")
        )
        for name, digest in internal["member_sha256"].items():
            self.assertEqual(digest, EXPECTED_MEMBER_SHA256[name])

    def test_03_blinded_manifest_and_exact_request_population(self) -> None:
        self.assertEqual(
            sha256_bytes(self.package_members["BLINDED_JUDGE_REQUESTS.jsonl"]),
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(len(self.requests), 49)
        self.assertEqual(sum(row["estimated_input_tokens"] for row in self.requests), 176759)
        for key in (
            "logical_judge_request_id",
            "judge_result_blind_id",
            "provider_payload_sha256",
        ):
            self.assertEqual(len({row[key] for row in self.requests}), 49)
        self.assertTrue(all(row["shard_id"] == "A" for row in self.requests))
        for row in self.requests:
            self.assertEqual(
                row["provider_payload_sha256"],
                sha256_bytes(canonical_json_bytes(row["provider_payload"])),
            )

    def test_04_frozen_provider_identity(self) -> None:
        expected_keys = {
            "max_tokens",
            "messages",
            "model",
            "response_format",
            "stream",
            "temperature",
        }
        for row in self.requests:
            payload = row["provider_payload"]
            self.assertEqual(set(payload), expected_keys)
            self.assertEqual(payload["model"], EXPECTED_MODEL)
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], 2048)
            self.assertIs(payload["stream"], False)
            self.assertEqual(payload["response_format"]["type"], "json_schema")

    def test_05_authorization_exact_shape_binding_and_hash(self) -> None:
        path = ARTIFACT_DIR / "generation_execution_authorization_v1.json"
        self.assertEqual(sha256_file(path), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(self.authorization["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(self.authorization["authorized_by"], "Ming Liu")
        self.assertEqual(self.authorization["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.authorization["shard_id"], "A")
        self.assertEqual(self.authorization["request_count"], 49)
        self.assertEqual(self.authorization["maximum_physical_attempts"], 98)
        self.assertEqual(self.authorization["package_zip_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            self.authorization["blinded_judge_manifest_sha256"],
            EXPECTED_MANIFEST_SHA256,
        )
        self.assertEqual(self.authorization["status"], "AUTHORIZED")
        timestamp = self.authorization["authorized_at_utc"]
        self.assertRegex(timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    def test_06_output_directory_exclusivity_and_immutable_hashes(self) -> None:
        files = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
        self.assertEqual(files, set(EXPECTED_OUTPUT_SHA256))
        self.assertTrue(all(path.is_file() for path in OUTPUT_DIR.iterdir()))
        for name, expected in EXPECTED_OUTPUT_SHA256.items():
            self.assertEqual(sha256_file(OUTPUT_DIR / name), expected)
            self.assertEqual(
                self.source_manifest["execution"]["files"][name]["sha256"],
                expected,
            )
        review_entries = {
            row["path"]: row for row in self.review_manifest["entries"]
        }
        review_self = self.review_manifest["self_entry"]
        artifact_files = {
            str(path.relative_to(ARTIFACT_DIR.parents[2]))
            for path in ARTIFACT_DIR.rglob("*")
            if path.is_file()
        }
        self.assertEqual(self.review_manifest["exact_regular_file_count"], 13)
        self.assertEqual(artifact_files, set(review_entries) | {review_self})
        for relative_path, recorded in review_entries.items():
            path = ARTIFACT_DIR.parents[2] / relative_path
            self.assertEqual(path.stat().st_size, recorded["size_bytes"])
            self.assertEqual(sha256_file(path), recorded["sha256"])

    def test_07_preflight_receipt_binding_and_zero_calls(self) -> None:
        self.assertEqual(
            self.preflight["status"],
            "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
        )
        self.assertEqual(self.preflight["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(self.preflight["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(self.preflight["shard_id"], "A")
        self.assertEqual(self.preflight["request_count"], 49)
        self.assertEqual(self.preflight["maximum_physical_attempts"], 98)
        self.assertEqual(self.preflight["judge_calls_at_receipt_write"], 0)
        self.assertIs(self.preflight["runtime_constructed_at_receipt_write"], False)
        self.assertIs(self.preflight["client_constructed_at_receipt_write"], False)

    def test_08_runtime_identity_and_client_order(self) -> None:
        statuses = [row["status"] for row in self.status_events]
        self.assertEqual(
            statuses,
            [
                "PREFLIGHT_STARTED",
                "RUNTIME_VALIDATED",
                "CLIENT_CONSTRUCTED_MAX_RETRIES_ZERO",
                "INCOMPLETE",
            ],
        )
        runtime = self.status_events[1]["runtime"]
        self.assertEqual(runtime["python_executable"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertIs(runtime["api_key_presence_checked_only"], True)
        self.assertIs(runtime["api_key_value_recorded"], False)

    def test_09_attempt_journal_ordering(self) -> None:
        sequence = [(row["event"], row["attempt_number"]) for row in self.attempts]
        self.assertEqual(
            sequence,
            [
                ("ATTEMPT_STARTED", 1),
                ("ATTEMPT_RETURNED", 1),
                ("ATTEMPT_STARTED", 2),
                ("ATTEMPT_RETURNED", 2),
            ],
        )
        self.assertEqual(
            [row["judge_calls_started"] for row in self.attempts if row["event"] == "ATTEMPT_STARTED"],
            [1, 2],
        )
        self.assertTrue(all(row["logical_order"] == 1 for row in self.attempts))

    def test_10_attempts_bind_to_first_frozen_request(self) -> None:
        first = self.requests[0]
        self.assertEqual(first["logical_judge_request_id"], EXPECTED_FIRST_REQUEST_ID)
        self.assertEqual(first["judge_result_blind_id"], EXPECTED_FIRST_RESULT_ID)
        self.assertEqual(first["provider_payload_sha256"], EXPECTED_FIRST_PAYLOAD_SHA256)
        for row in self.attempts:
            self.assertEqual(row["logical_judge_request_id"], EXPECTED_FIRST_REQUEST_ID)
            self.assertEqual(row["judge_result_blind_id"], EXPECTED_FIRST_RESULT_ID)
            self.assertEqual(row["provider_payload_sha256"], EXPECTED_FIRST_PAYLOAD_SHA256)

    def test_11_returned_model_and_response_id_identity(self) -> None:
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        self.assertEqual(len(returned), 2)
        self.assertTrue(all(row["returned_model"] == EXPECTED_MODEL for row in returned))
        self.assertTrue(all(row["finish_reason"] == "stop" for row in returned))
        self.assertEqual(len({row["provider_response_id"] for row in returned}), 2)

    def test_12_retry_policy_byte_identity_and_attempt_ceiling(self) -> None:
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        self.assertEqual([row["failure_code"] for row in returned], [
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "STRICT_SCHEMA_VALIDATION_FAILED",
        ])
        self.assertEqual({row["provider_payload_sha256"] for row in returned}, {
            EXPECTED_FIRST_PAYLOAD_SHA256
        })
        self.assertEqual(len(returned), 2)
        self.assertLessEqual(self.status["physical_attempts"], 98)
        initial_starts = [
            row for row in self.attempts
            if row["event"] == "ATTEMPT_STARTED" and row["attempt_number"] == 1
        ]
        self.assertEqual(len(initial_starts), 1)

    def test_13_returned_outputs_reproduce_strict_failure_locally(self) -> None:
        parse_result = self.parser["parse_judge_result"]
        error_type = self.parser["JudgeResultError"]
        applicability = self.applicability_from_request(self.requests[0])
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        for row in returned:
            with self.assertRaisesRegex(error_type, "STRICT_SCHEMA_VALIDATION_FAILED"):
                parse_result(
                    row["raw_response_content"],
                    applicability,
                    expected_judge_result_blind_id=EXPECTED_FIRST_RESULT_ID,
                )

    def test_14_terminal_uniqueness_and_incomplete_coverage(self) -> None:
        self.assertEqual(self.terminals, [])
        self.assertEqual(len({row["logical_judge_request_id"] for row in self.terminals}), 0)
        self.assertEqual(len({row["judge_result_blind_id"] for row in self.terminals}), 0)
        self.assertEqual(self.status["valid_terminal_count"], 0)
        self.assertEqual(self.status["request_count"], 49)

    def test_15_attempted_blind_id_and_provider_response_uniqueness(self) -> None:
        started = [row for row in self.attempts if row["event"] == "ATTEMPT_STARTED"]
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        self.assertEqual({row["judge_result_blind_id"] for row in started}, {
            EXPECTED_FIRST_RESULT_ID
        })
        self.assertEqual(len({row["provider_response_id"] for row in returned}), len(returned))

    def test_16_fail_closed_status_and_first_incomplete_request(self) -> None:
        self.assertEqual(self.status["status"], "INCOMPLETE")
        self.assertEqual(self.status["physical_attempts"], 2)
        self.assertEqual(self.status["judge_calls"], 2)
        self.assertIs(self.status["automatic_resume"], False)
        self.assertIs(self.status["continuation_requires_new_direct_authorization"], True)
        self.assertEqual(len(self.errors), 1)
        error = self.errors[0]
        self.assertEqual(error["logical_judge_request_id"], EXPECTED_FIRST_REQUEST_ID)
        self.assertEqual(error["judge_result_blind_id"], EXPECTED_FIRST_RESULT_ID)
        self.assertEqual(error["attempt_number"], 2)
        self.assertEqual(error["error_category"], "STRICT_SCHEMA_VALIDATION_FAILED")
        self.assertEqual(error["terminal_policy"], "STOP_ENTIRE_SHARD")
        self.assertTrue(error["continuation_requires_new_direct_authorization"])
        self.assertEqual({row["logical_order"] for row in self.attempts}, {1})

    def test_17_usage_arithmetic_and_totals(self) -> None:
        returned = [row for row in self.attempts if row["event"] == "ATTEMPT_RETURNED"]
        for row in returned:
            self.assertEqual(row["prompt_tokens"] + row["completion_tokens"], row["total_tokens"])
            self.assertGreaterEqual(row["cached_input_tokens"], 0)
            self.assertLessEqual(row["cached_input_tokens"], row["prompt_tokens"])
        self.assertEqual(sum(row["prompt_tokens"] for row in returned), 6932)
        self.assertEqual(sum(row["cached_input_tokens"] for row in returned), 3328)
        self.assertEqual(sum(row["completion_tokens"] for row in returned), 1188)
        self.assertEqual(sum(row["total_tokens"] for row in returned), 8120)

    def test_18_score_and_rationale_parser_contract(self) -> None:
        parse_result = self.parser["parse_judge_result"]
        error_type = self.parser["JudgeResultError"]
        payload, applicability, _ = self.synthetic_case(8)
        parsed = parse_result(
            json.dumps(payload),
            applicability,
            expected_judge_result_blind_id="R3B-AAAAAAAAAAAAAAAAAAAA",
        )
        self.assertTrue(all(1 <= parsed[field] <= 5 for field in (
            "clarity",
            "personalisation",
            "actionability",
            "context_awareness",
            "motivation_and_engagement",
            "reliability",
            "multi_page_cohesiveness",
            "error_handling",
        )))
        invalid = json.loads(json.dumps(payload))
        invalid["criterion_rationales"]["clarity"] = ""
        with self.assertRaisesRegex(error_type, "STRICT_SCHEMA_VALIDATION_FAILED"):
            parse_result(
                invalid,
                applicability,
                expected_judge_result_blind_id="R3B-AAAAAAAAAAAAAAAAAAAA",
            )

    def test_19_applicability_enforcement(self) -> None:
        parse_result = self.parser["parse_judge_result"]
        error_type = self.parser["JudgeResultError"]
        payload, applicability, _ = self.synthetic_case(4)
        payload["error_handling"] = "1"
        with self.assertRaisesRegex(error_type, "APPLICABILITY_CONTRACT_VIOLATION"):
            parse_result(
                payload,
                applicability,
                expected_judge_result_blind_id="R3B-AAAAAAAAAAAAAAAAAAAA",
            )

    def test_20_local_id_attachment_and_exact_means_for_4_to_8(self) -> None:
        parse_result = self.parser["parse_judge_result"]
        for count in range(4, 9):
            with self.subTest(applicable_count=count):
                payload, applicability, expected_mean = self.synthetic_case(count)
                parsed = parse_result(
                    payload,
                    applicability,
                    expected_judge_result_blind_id="R3B-AAAAAAAAAAAAAAAAAAAA",
                )
                self.assertEqual(parsed["response_blind_id"], "R3B-AAAAAAAAAAAAAAAAAAAA")
                self.assertEqual(parsed["overall_applicable_mean"], expected_mean)

    def test_21_unsupported_claim_conversion(self) -> None:
        parse_result = self.parser["parse_judge_result"]
        payload, applicability, _ = self.synthetic_case(8, "7")
        parsed = parse_result(
            payload,
            applicability,
            expected_judge_result_blind_id="R3B-AAAAAAAAAAAAAAAAAAAA",
        )
        self.assertEqual(parsed["unsupported_claim_count"], 7)
        self.assertIs(type(parsed["unsupported_claim_count"]), int)

    def test_22_secret_absence_scan(self) -> None:
        patterns = (
            re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
            re.compile(rb"(?i)bearer[ \t]+[A-Za-z0-9._-]{20,}"),
            re.compile(
                rb"(?i)(?:api[_-]?key|authorization)[\"']?\s*[:=]\s*"
                rb"[\"'][A-Za-z0-9._-]{16,}[\"']"
            ),
        )
        for path in ARTIFACT_DIR.rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            for pattern in patterns:
                self.assertIsNone(pattern.search(data), f"secret-like value in {path.name}")

    def test_23_restricted_identity_and_final_result_key_absence(self) -> None:
        forbidden_keys = {
            "condition",
            "condition_id",
            "condition_name",
            "mode",
            "mode_id",
            "mode_name",
            "route",
            "route_id",
            "route_name",
            "scenario_id",
            "family_id",
            "gold",
            "gold_label",
            "expected_outcome",
            "expected_winner",
            "human_rating",
            "p_value",
            "winner",
            "rank",
            "mode_level_mean",
        }
        observed_keys: set[str] = set()
        for path in ARTIFACT_DIR.rglob("*"):
            if path.suffix == ".json":
                observed_keys.update(all_object_keys(json.loads(path.read_text("utf-8"))))
            elif path.suffix == ".jsonl":
                for row in load_jsonl(path):
                    observed_keys.update(all_object_keys(row))
        self.assertEqual(observed_keys & forbidden_keys, set())
        identity_pattern = re.compile(rb"\b(?:CONDITION|MODE|ROUTE)[-_][A-Z0-9]{2,}\b")
        for path in ARTIFACT_DIR.rglob("*"):
            if path.is_file():
                self.assertIsNone(identity_pattern.search(path.read_bytes()))

    def test_24_terminal_and_parsed_result_set_hashes(self) -> None:
        terminal_path = OUTPUT_DIR / "JUDGE_TERMINAL_JOURNAL.jsonl"
        self.assertEqual(sha256_file(terminal_path), EMPTY_SHA256)
        parsed_bytes = b"".join(
            canonical_json_bytes(row["parsed_semantic_result"]) + b"\n"
            for row in sorted(self.terminals, key=lambda item: item["logical_order"])
        )
        self.assertEqual(sha256_bytes(parsed_bytes), EMPTY_SHA256)
        self.assertEqual(self.audit["hashes"]["terminal_journal_sha256"], EMPTY_SHA256)
        self.assertEqual(self.audit["hashes"]["parsed_result_set_sha256"], EMPTY_SHA256)

    def test_25_future_integration_fail_closed_compatibility(self) -> None:
        compatibility = self.audit["integration_compatibility"]
        self.assertIs(compatibility["journal_schema_mechanically_readable"], True)
        self.assertEqual(compatibility["terminal_records_available"], 0)
        self.assertEqual(
            compatibility["integration_readiness"],
            "BLOCKED_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION",
        )
        self.assertIs(compatibility["must_not_integrate_as_complete"], True)
        self.assertEqual(
            self.audit["shard_status"],
            "JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION",
        )
        status_text = (ARTIFACT_DIR / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn(
            "JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION",
            status_text,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
