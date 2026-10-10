#!/usr/bin/env python3
"""Offline mechanical audit for frozen C4 REAL R3 response shard B.

This suite makes no Provider, Judge, scoring, RQ2, or Streamlit call. It does
not assess response quality. It verifies only frozen identities, execution
mechanics, student-facing format, hashes, counts, leakage boundaries, and the
future response-integration projection.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import types
import unittest
import zipfile


ARTIFACT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ARTIFACT_DIR / "execution_output_v1"
PACKAGE_ZIP = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_GENERATION_SHARD_B_EXECUTION_PACKAGE_R3_2026-09-01.zip"
)
AUTHORIZATION_PATH = ARTIFACT_DIR / "generation_execution_authorization_v1.json"
SOURCE_MANIFEST_PATH = ARTIFACT_DIR / "generation_execution_source_manifest_v1.json"
AUDIT_PATH = ARTIFACT_DIR / "generation_execution_audit_v1.json"
REVIEW_MANIFEST_PATH = ARTIFACT_DIR / "review_manifest_v1.json"

EXPECTED_PACKAGE_SHA256 = (
    "eaa6abe4a6cb63be2bf985ae68e509e042aaba20e77b5d6a739de378c38c1d07"
)
EXPECTED_BLINDED_MANIFEST_SHA256 = (
    "c178251275cd7f1edff0a4cb531fad0011bfad982234398997875d987f3ed29a"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "7147d6b2bd391f9dcdafa1e2c34e86117a182386da9c8b93f282535e09436c33"
)
EXPECTED_TERMINAL_JOURNAL_SHA256 = (
    "0a3c731fa00f596b9c80c3f463faf8f0563ca741dbe58942dbbc1bb0b36e7585"
)
EXPECTED_ANSWER_SET_SHA256 = (
    "b035aa4f18025a4d6592489b9ed94394a4872cbca31788ee31dba5574e88ac8c"
)
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_REQUEST_COUNT = 50
EXPECTED_MAXIMUM_ATTEMPTS = 100

EXPECTED_PACKAGE_MEMBERS = {
    "BLINDED_REQUESTS.jsonl": (
        "c178251275cd7f1edff0a4cb531fad0011bfad982234398997875d987f3ed29a"
    ),
    "EXECUTION_CONTRACT.json": (
        "112972b73acbbfbe305a329832848a9b1846e0c347eb5a1f0b2f592aa74b889b"
    ),
    "GENERATION_CONFIGURATION.json": (
        "8a4a4a07137336d058645820bdd9d32091afb4df3513ec6324d380015454b138"
    ),
    "GENERATION_PROMPT.txt": (
        "c72c9982899902221d1da6d67724c2058547b0641a285a7c28d9bafd12ec63cb"
    ),
    "GENERATION_SCHEMA.json": (
        "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
    ),
    "PACKAGE_SOURCE_HASHES.json": (
        "3b419e1694bb7ebf5128f9f7ef5e357eac1744c4eb7b6239f1d6544b4589096e"
    ),
    "README.md": (
        "52ad341637ba96db94f7ccf0b5f58203fe12ab1b5f978715a026ffe4ca4a851d"
    ),
    "STUDENT_FACING_FORMAT_CONTRACT.json": (
        "e68165bc78294beb490ea37ae45752ce2a41ee4232ae5127cd9d2e7ee6336319"
    ),
    "c4_real_student_facing_response_validator_v1.py": (
        "5b098ff2e8368a7830938ae83ea4ea5cbdcdf71fcf61b674c579118c4742fbcc"
    ),
    "generation_execution_runner_v3.py": (
        "679e1412ca2ed31daa02aa2bec8be81a7bc498447636820bd658eab963707a13"
    ),
    "test_package.py": (
        "4286d9de72e8c09048bca62afddbcc04ca72af89ccb061b8e62a2ac78fe25e5f"
    ),
    "validate_package.py": (
        "bf74e7022d094b321e206df2ba3162f5d606ac606874466f6b4a7183eb2fb6a0"
    ),
}

EXPECTED_OUTPUT_FILES = {
    "GENERATION_ATTEMPT_JOURNAL.jsonl": (
        132104,
        "314e61317e0a1816314cbd3c9cf18a05969b2122754e4997ea8645ff8b5618d4",
    ),
    "GENERATION_ERROR_REGISTRY.jsonl": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "GENERATION_EXECUTION_REPORT.md": (
        351,
        "0528d012ad8a74844f50725e39281f21c8dc5c366694ce91db5dd0b62613d34c",
    ),
    "GENERATION_EXECUTION_STATUS.json": (
        838,
        "73a791c5ce0b36e172d0dab5acc19e4abb06b1740abcbb8a41dbd0bf697fcb67",
    ),
    "GENERATION_PREFLIGHT_RECEIPT.json": (
        779,
        "bc43b9f9a30c9a3a9109b9b8a475cd551e68eca41e1ffe5a96afc4c7e92c27d4",
    ),
    "GENERATION_TERMINAL_JOURNAL.jsonl": (
        126967,
        EXPECTED_TERMINAL_JOURNAL_SHA256,
    ),
    "GENERATION_USAGE_AND_COST.json": (
        416,
        "c747a9b0965aab88e866dcc8dd72598b8f63da5d3460e3437f9aead15f572c7f",
    ),
}

AUTHORIZATION_FIELDS = [
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
]

RETRYABLE_CATEGORIES = {
    "INVALID_JSON",
    "STRICT_SCHEMA_VALIDATION_FAILED",
    "NON_STUDENT_FACING_FORMAT",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: object) -> bytes:
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
        raise AssertionError(f"expected JSON object: {path}")
    return value


def load_jsonl_bytes(value: bytes) -> list[dict[str, object]]:
    rows = []
    for line in value.decode("utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise AssertionError("expected JSONL object")
        rows.append(row)
    return rows


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return load_jsonl_bytes(path.read_bytes())


def answer_projection(terminal_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(terminal_rows, key=lambda row: int(row["logical_order"]))
    return [
        {
            "answer_text": row["parsed_output"]["answer_text"],
            "logical_generation_request_id": row["logical_generation_request_id"],
            "logical_order": row["logical_order"],
            "provider_payload_sha256": row["provider_payload_sha256"],
            "response_blind_id": row["response_blind_id"],
            "returned_model": row["returned_model"],
        }
        for row in ordered
    ]


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


class FrozenR3BOfflineAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authorization = load_json(AUTHORIZATION_PATH)
        cls.source_manifest = load_json(SOURCE_MANIFEST_PATH)
        cls.audit = load_json(AUDIT_PATH)
        cls.review_manifest = load_json(REVIEW_MANIFEST_PATH)
        cls.status = load_json(OUTPUT_DIR / "GENERATION_EXECUTION_STATUS.json")
        cls.preflight = load_json(OUTPUT_DIR / "GENERATION_PREFLIGHT_RECEIPT.json")
        cls.usage = load_json(OUTPUT_DIR / "GENERATION_USAGE_AND_COST.json")
        cls.attempt_rows = load_jsonl(OUTPUT_DIR / "GENERATION_ATTEMPT_JOURNAL.jsonl")
        cls.terminal_rows = load_jsonl(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl")
        cls.error_rows = load_jsonl(OUTPUT_DIR / "GENERATION_ERROR_REGISTRY.jsonl")
        with zipfile.ZipFile(PACKAGE_ZIP, "r") as package:
            cls.package_names = package.namelist()
            cls.package_bytes = {name: package.read(name) for name in cls.package_names}
        cls.request_rows = load_jsonl_bytes(cls.package_bytes["BLINDED_REQUESTS.jsonl"])
        cls.package_source_hashes = json.loads(
            cls.package_bytes["PACKAGE_SOURCE_HASHES.json"]
        )
        cls.contract = json.loads(cls.package_bytes["EXECUTION_CONTRACT.json"])
        cls.configuration = json.loads(
            cls.package_bytes["GENERATION_CONFIGURATION.json"]
        )
        cls.generation_schema = json.loads(cls.package_bytes["GENERATION_SCHEMA.json"])

    def test_01_package_zip_identity(self) -> None:
        self.assertTrue(PACKAGE_ZIP.is_file())
        self.assertEqual(sha256_file(PACKAGE_ZIP), EXPECTED_PACKAGE_SHA256)

    def test_02_package_allowlist_and_member_identities(self) -> None:
        self.assertEqual(self.package_names, list(EXPECTED_PACKAGE_MEMBERS))
        self.assertEqual(len(self.package_names), 12)
        self.assertEqual(set(self.package_bytes), set(EXPECTED_PACKAGE_MEMBERS))
        for name, expected_hash in EXPECTED_PACKAGE_MEMBERS.items():
            self.assertEqual(sha256_bytes(self.package_bytes[name]), expected_hash)

    def test_03_package_scientific_identity_and_exclusions(self) -> None:
        declared = self.package_source_hashes
        self.assertEqual(declared["package_id"], "C4_REAL_GENERATION_SHARD_B_R3_20260901")
        self.assertEqual(declared["shard"], "B")
        self.assertEqual(declared["request_count"], EXPECTED_REQUEST_COUNT)
        for field in (
            "api_key_included",
            "course_corpus_included",
            "existing_execution_results_included",
            "g2_answers_included",
            "hmac_key_included",
            "memory_database_included",
            "restricted_mapping_included",
            "scenario_mode_route_or_gold_identity_included",
        ):
            self.assertIs(declared[field], False)
        self.assertEqual(declared["provider_calls"], 0)
        self.assertEqual(declared["judge_calls"], 0)
        self.assertEqual(declared["scoring_calls"], 0)
        self.assertEqual(
            declared["member_sha256_excluding_self"],
            {
                key: value
                for key, value in EXPECTED_PACKAGE_MEMBERS.items()
                if key != "PACKAGE_SOURCE_HASHES.json"
            },
        )
        self.assertEqual(self.contract["endpoint"], "OpenAI Chat Completions")
        self.assertEqual(self.contract["model"], EXPECTED_MODEL)
        self.assertEqual(self.contract["temperature"], 0)
        self.assertEqual(self.contract["max_output_tokens"], 512)
        self.assertIs(self.contract["streaming"], False)
        self.assertEqual(self.contract["tools"], "NONE")
        self.assertEqual(self.contract["automatic_sdk_retries"], 0)
        self.assertEqual(
            set(self.contract["manual_retry_categories"]), RETRYABLE_CATEGORIES
        )
        self.assertEqual(
            self.configuration["prompt_sha256"],
            EXPECTED_PACKAGE_MEMBERS["GENERATION_PROMPT.txt"],
        )
        self.assertEqual(
            self.configuration["provider_transport_schema_sha256"],
            EXPECTED_PACKAGE_MEMBERS["GENERATION_SCHEMA.json"],
        )

    def test_04_blinded_manifest_identity(self) -> None:
        self.assertEqual(
            sha256_bytes(self.package_bytes["BLINDED_REQUESTS.jsonl"]),
            EXPECTED_BLINDED_MANIFEST_SHA256,
        )
        self.assertEqual(len(self.request_rows), EXPECTED_REQUEST_COUNT)
        logical_ids = [row["logical_generation_request_id"] for row in self.request_rows]
        blind_ids = [row["response_blind_id"] for row in self.request_rows]
        self.assertEqual(len(set(logical_ids)), EXPECTED_REQUEST_COUNT)
        self.assertEqual(len(set(blind_ids)), EXPECTED_REQUEST_COUNT)

    def test_05_authorization_record(self) -> None:
        self.assertEqual(list(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(len(self.authorization), 11)
        self.assertEqual(
            self.authorization,
            {
                "schema_version": "c4-real-response-regeneration-authorization-r3",
                "authorization_id": "RQ3-REAL-C4-R3B-REGENERATION-20260901",
                "authorized_by": "Ming Liu",
                "authorized_at_utc": "2026-09-02T04:12:34Z",
                "package_id": "C4_REAL_GENERATION_SHARD_B_R3_20260901",
                "shard": "B",
                "request_count": EXPECTED_REQUEST_COUNT,
                "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
                "package_sha256": EXPECTED_PACKAGE_SHA256,
                "blinded_manifest_sha256": EXPECTED_BLINDED_MANIFEST_SHA256,
                "status": "AUTHORIZED",
            },
        )
        self.assertEqual(sha256_file(AUTHORIZATION_PATH), EXPECTED_AUTHORIZATION_SHA256)

    def test_06_output_directory_exclusivity(self) -> None:
        actual = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
        self.assertEqual(actual, set(EXPECTED_OUTPUT_FILES))
        self.assertFalse(any(path.is_dir() for path in OUTPUT_DIR.iterdir()))
        for name, (expected_size, expected_hash) in EXPECTED_OUTPUT_FILES.items():
            path = OUTPUT_DIR / name
            self.assertEqual(path.stat().st_size, expected_size)
            self.assertEqual(sha256_file(path), expected_hash)

    def test_07_preflight_receipt(self) -> None:
        self.assertEqual(
            self.preflight["status"], "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION"
        )
        self.assertEqual(
            self.preflight["authorization_record_sha256"],
            EXPECTED_AUTHORIZATION_SHA256,
        )
        self.assertEqual(self.preflight["package_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            self.preflight["blinded_manifest_sha256"],
            EXPECTED_BLINDED_MANIFEST_SHA256,
        )
        self.assertIs(self.preflight["runtime_constructed"], False)
        self.assertIs(self.preflight["client_constructed"], False)
        self.assertIs(self.preflight["automatic_resume"], False)
        self.assertEqual(self.preflight["judge_calls"], 0)

    def test_08_execution_status_and_runtime(self) -> None:
        self.assertEqual(
            self.status["status"], "COMPLETE_VALID_STUDENT_FACING_RESPONSES"
        )
        self.assertEqual(self.status["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(self.status["valid_response_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(self.status["incomplete_logical_request_count"], 0)
        self.assertEqual(self.status["unattempted_logical_request_count"], 0)
        runtime = self.status["runtime_identity"]
        self.assertEqual(runtime["python_path"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertEqual(runtime["automatic_sdk_retries"], 0)
        self.assertIs(runtime["api_key_presence_checked_only"], True)
        self.assertIs(runtime["api_key_value_recorded"], False)

    def test_09_request_population_and_payload_hashes(self) -> None:
        expected_payload_fields = {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "stream",
            "response_format",
        }
        prompt = self.package_bytes["GENERATION_PROMPT.txt"].decode("utf-8")
        for row in self.request_rows:
            payload = row["provider_payload"]
            self.assertEqual(set(payload), expected_payload_fields)
            self.assertEqual(
                sha256_bytes(canonical_bytes(payload)), row["provider_payload_sha256"]
            )
            self.assertEqual(payload["model"], EXPECTED_MODEL)
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], 512)
            self.assertIs(payload["stream"], False)
            self.assertNotIn("tools", payload)
            self.assertEqual(payload["messages"][0], {"role": "system", "content": prompt})
            self.assertEqual(payload["messages"][1]["role"], "user")
            self.assertIsInstance(payload["messages"][1]["content"], str)
            self.assertEqual(
                payload["response_format"]["json_schema"]["schema"],
                self.generation_schema,
            )

    def test_10_attempt_journal_order(self) -> None:
        self.assertEqual(len(self.attempt_rows), EXPECTED_REQUEST_COUNT)
        self.assertEqual(
            [(row["logical_order"], row["attempt_number"]) for row in self.attempt_rows],
            [(order, 1) for order in range(1, EXPECTED_REQUEST_COUNT + 1)],
        )
        for request, attempt in zip(self.request_rows, self.attempt_rows, strict=True):
            self.assertEqual(
                attempt["logical_generation_request_id"],
                request["logical_generation_request_id"],
            )
            self.assertEqual(attempt["response_blind_id"], request["response_blind_id"])
            self.assertEqual(
                attempt["provider_payload_sha256"], request["provider_payload_sha256"]
            )

    def test_11_terminal_uniqueness_and_alignment(self) -> None:
        self.assertEqual(len(self.terminal_rows), EXPECTED_REQUEST_COUNT)
        logical_ids = [row["logical_generation_request_id"] for row in self.terminal_rows]
        blind_ids = [row["response_blind_id"] for row in self.terminal_rows]
        self.assertEqual(len(set(logical_ids)), EXPECTED_REQUEST_COUNT)
        self.assertEqual(len(set(blind_ids)), EXPECTED_REQUEST_COUNT)
        self.assertEqual(
            [row["logical_order"] for row in self.terminal_rows],
            list(range(1, EXPECTED_REQUEST_COUNT + 1)),
        )
        for request, terminal in zip(self.request_rows, self.terminal_rows, strict=True):
            self.assertEqual(
                terminal["logical_generation_request_id"],
                request["logical_generation_request_id"],
            )
            self.assertEqual(terminal["response_blind_id"], request["response_blind_id"])
            self.assertEqual(
                terminal["provider_payload_sha256"], request["provider_payload_sha256"]
            )
            self.assertEqual(terminal["terminal_status"], "VALID_STUDENT_FACING_RESPONSE")

    def test_12_strict_outer_result_shape(self) -> None:
        for attempt in self.attempt_rows:
            parsed = attempt["parsed_output"]
            self.assertEqual(set(parsed), {"answer_text"})
            self.assertEqual(attempt["outer_schema_validation_status"], "VALID")
            self.assertEqual(json.loads(attempt["raw_response_content"]), parsed)
        for terminal in self.terminal_rows:
            parsed = terminal["parsed_output"]
            self.assertEqual(set(parsed), {"answer_text"})
            self.assertEqual(json.loads(terminal["raw_response_content"]), parsed)

    def test_13_nonempty_answer_text(self) -> None:
        for row in self.terminal_rows:
            answer_text = row["parsed_output"]["answer_text"]
            self.assertIsInstance(answer_text, str)
            self.assertTrue(answer_text.strip())

    def test_14_semantic_validator_status(self) -> None:
        validator_source = self.package_bytes[
            "c4_real_student_facing_response_validator_v1.py"
        ]
        self.assertEqual(
            sha256_bytes(validator_source),
            EXPECTED_PACKAGE_MEMBERS[
                "c4_real_student_facing_response_validator_v1.py"
            ],
        )
        module = types.ModuleType("frozen_student_facing_validator")
        exec(compile(validator_source, "<frozen-validator>", "exec"), module.__dict__)
        for row in self.terminal_rows:
            self.assertEqual(
                module.validate_answer_text(row["parsed_output"]["answer_text"]),
                "VALID_STUDENT_FACING_RESPONSE",
            )
            self.assertEqual(
                row["student_facing_validation_status"],
                "VALID_STUDENT_FACING_RESPONSE",
            )

    def test_15_returned_model_identity(self) -> None:
        for row in self.attempt_rows + self.terminal_rows:
            self.assertEqual(row["requested_model"], EXPECTED_MODEL)
            self.assertEqual(row["returned_model"], EXPECTED_MODEL)

    def test_16_retry_policy_and_payload_identity(self) -> None:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for attempt in self.attempt_rows:
            grouped[str(attempt["logical_generation_request_id"])].append(attempt)
        retries = 0
        for request in self.request_rows:
            logical_id = str(request["logical_generation_request_id"])
            rows = grouped[logical_id]
            self.assertIn(len(rows), (1, 2))
            self.assertEqual(rows[0]["attempt_number"], 1)
            if len(rows) == 2:
                retries += 1
                self.assertEqual(rows[1]["attempt_number"], 2)
                self.assertIn(rows[0]["retryable_failure"], RETRYABLE_CATEGORIES)
                self.assertEqual(
                    rows[0]["provider_payload_sha256"],
                    rows[1]["provider_payload_sha256"],
                )
                self.assertIsInstance(rows[0]["raw_response_content"], str)
        self.assertEqual(retries, 0)

    def test_17_physical_attempt_ceiling_and_fail_closed_state(self) -> None:
        physical_attempts = len(self.attempt_rows)
        self.assertEqual(physical_attempts, 50)
        self.assertGreaterEqual(physical_attempts, EXPECTED_REQUEST_COUNT)
        self.assertLessEqual(physical_attempts, EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertEqual(self.status["physical_attempt_count"], physical_attempts)
        self.assertEqual(
            self.status["maximum_physical_attempts"], EXPECTED_MAXIMUM_ATTEMPTS
        )
        self.assertIs(self.status["automatic_resume"], False)
        self.assertIs(
            self.status["continuation_requires_new_direct_authorization"], True
        )

    def test_18_usage_arithmetic(self) -> None:
        prompt = sum(int(row["prompt_tokens"]) for row in self.attempt_rows)
        cached = sum(int(row["cached_input_tokens"]) for row in self.attempt_rows)
        completion = sum(int(row["completion_tokens"]) for row in self.attempt_rows)
        total = sum(int(row["total_tokens"]) for row in self.attempt_rows)
        self.assertEqual((prompt, cached, completion, total), (41178, 3584, 8896, 50074))
        self.assertEqual(total, prompt + completion)
        self.assertEqual(self.usage["prompt_tokens"], prompt)
        self.assertEqual(self.usage["cached_input_tokens"], cached)
        self.assertEqual(self.usage["completion_tokens"], completion)
        self.assertEqual(self.usage["total_tokens"], total)
        self.assertIs(self.usage["usage_arithmetic_valid"], True)
        self.assertEqual(self.usage["responses_without_cached_token_detail"], 0)
        self.assertEqual(self.usage["provider_calls_observed"], 50)
        self.assertEqual(
            self.usage["cost_status"], "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY"
        )
        self.assertIsNone(self.usage["cost_amount"])
        self.assertIsNone(self.usage["cost_currency"])

    def test_19_answer_text_hashes(self) -> None:
        expected = self.audit["answer_text_hashes"]
        actual = []
        for row in sorted(self.terminal_rows, key=lambda item: int(item["logical_order"])):
            actual.append(
                {
                    "logical_order": row["logical_order"],
                    "logical_generation_request_id": row[
                        "logical_generation_request_id"
                    ],
                    "response_blind_id": row["response_blind_id"],
                    "answer_text_sha256": sha256_bytes(
                        row["parsed_output"]["answer_text"].encode("utf-8")
                    ),
                }
            )
        self.assertEqual(actual, expected)
        self.assertEqual(len({row["answer_text_sha256"] for row in actual}), 50)

    def test_20_terminal_and_answer_set_hashes(self) -> None:
        self.assertEqual(
            sha256_file(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl"),
            EXPECTED_TERMINAL_JOURNAL_SHA256,
        )
        self.assertEqual(
            sha256_bytes(canonical_bytes(answer_projection(self.terminal_rows))),
            EXPECTED_ANSWER_SET_SHA256,
        )
        self.assertEqual(self.audit["answer_set_sha256"], EXPECTED_ANSWER_SET_SHA256)

    def test_21_secret_absence(self) -> None:
        token_pattern = re.compile(
            rb"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{20,}"
        )
        assignment_pattern = re.compile(
            rb"OPENAI_API_KEY[\"']?\s*[:=]\s*[\"'][^\"']+"
        )
        files = [path for path in ARTIFACT_DIR.rglob("*") if path.is_file()]
        for path in files:
            content = path.read_bytes()
            self.assertIsNone(token_pattern.search(content), path.name)
            self.assertIsNone(assignment_pattern.search(content), path.name)
        self.assertIs(self.status["runtime_identity"]["api_key_value_recorded"], False)

    def test_22_restricted_identity_field_absence(self) -> None:
        allowed_zero_control_fields = {"judge_calls", "scoring_calls"}

        def prohibited(key: str) -> bool:
            lowered = key.lower()
            if lowered in allowed_zero_control_fields:
                return False
            if any(
                fragment in lowered
                for fragment in (
                    "gold",
                    "scenario",
                    "condition",
                    "route",
                    "rating",
                    "reference_answer",
                    "expected_outcome",
                    "hmac",
                )
            ):
                return True
            if lowered == "mode" or lowered.startswith("mode_") or lowered.endswith("_mode"):
                return True
            if "judge" in lowered or "scor" in lowered:
                return True
            return False

        response_evidence: list[object] = [
            self.status,
            self.preflight,
            self.usage,
            self.attempt_rows,
            self.terminal_rows,
            self.error_rows,
        ]
        leaked = sorted(
            {key for evidence in response_evidence for key in walk_keys(evidence) if prohibited(key)}
        )
        self.assertEqual(leaked, [])

    def test_23_zero_error_judge_scoring_and_refusal(self) -> None:
        self.assertEqual(self.error_rows, [])
        self.assertTrue(all(row["error"] is None for row in self.attempt_rows))
        self.assertTrue(all(row["retryable_failure"] is None for row in self.attempt_rows))
        self.assertTrue(all(row["finish_reason"] == "stop" for row in self.attempt_rows))
        self.assertEqual(self.status["judge_calls"], 0)
        self.assertEqual(self.status["scoring_calls"], 0)
        self.assertEqual(self.usage["judge_calls"], 0)
        self.assertEqual(self.audit["error_counts"]["provider"], 0)
        self.assertEqual(self.audit["error_counts"]["refusal"], 0)
        self.assertEqual(self.audit["error_counts"]["model_mismatch"], 0)
        self.assertEqual(self.audit["error_counts"]["transport"], 0)

    def test_24_future_integration_compatibility(self) -> None:
        records = answer_projection(self.terminal_rows)
        required = {
            "answer_text",
            "logical_generation_request_id",
            "logical_order",
            "provider_payload_sha256",
            "response_blind_id",
            "returned_model",
        }
        self.assertEqual(len(records), EXPECTED_REQUEST_COUNT)
        self.assertTrue(all(set(record) == required for record in records))
        self.assertEqual(
            [record["logical_order"] for record in records],
            list(range(1, EXPECTED_REQUEST_COUNT + 1)),
        )
        self.assertEqual(
            sha256_bytes(canonical_bytes(records)), EXPECTED_ANSWER_SET_SHA256
        )
        self.assertEqual(self.audit["future_r3_response_integration_compatibility"], "PASS")

    def test_25_source_manifest(self) -> None:
        self.assertEqual(
            self.source_manifest["schema_version"],
            "c4-real-response-regeneration-source-manifest-v1",
        )
        self.assertEqual(self.source_manifest["shard"], "B")
        self.assertEqual(self.source_manifest["package_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(
            self.source_manifest["blinded_manifest_sha256"],
            EXPECTED_BLINDED_MANIFEST_SHA256,
        )
        self.assertEqual(
            self.source_manifest["authorization_record_sha256"],
            EXPECTED_AUTHORIZATION_SHA256,
        )
        self.assertEqual(
            self.source_manifest["package_member_sha256"], EXPECTED_PACKAGE_MEMBERS
        )
        self.assertEqual(
            self.source_manifest["execution_output_files"],
            {
                name: {"bytes": size, "sha256": digest}
                for name, (size, digest) in EXPECTED_OUTPUT_FILES.items()
            },
        )

    def test_26_mechanical_audit(self) -> None:
        self.assertEqual(
            self.audit["schema_version"],
            "c4-real-response-regeneration-mechanical-audit-v1",
        )
        self.assertEqual(self.audit["status"], "PASS")
        self.assertEqual(self.audit["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(self.audit["physical_attempt_count"], 50)
        self.assertEqual(self.audit["retry_count"], 0)
        self.assertEqual(self.audit["valid_response_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(self.audit["terminal_journal_sha256"], EXPECTED_TERMINAL_JOURNAL_SHA256)
        self.assertEqual(self.audit["answer_set_sha256"], EXPECTED_ANSWER_SET_SHA256)
        self.assertEqual(set(self.audit["mechanical_checks"].values()), {"PASS"})
        self.assertEqual(
            self.audit["offline_test_summary"],
            {"failed": 0, "passed": 27, "provider_calls": 0},
        )

    def test_27_review_manifest_allowlist(self) -> None:
        self.assertEqual(
            self.review_manifest["schema_version"],
            "c4-real-response-regeneration-review-manifest-v1",
        )
        self.assertEqual(self.review_manifest["shard"], "B")
        self.assertEqual(self.review_manifest["review_manifest_path"], "review_manifest_v1.json")
        self.assertIs(self.review_manifest["self_hash_excluded"], True)
        listed = self.review_manifest["members_excluding_manifest"]
        actual = []
        for item in listed:
            path = ARTIFACT_DIR / item["path"]
            actual.append(
                {
                    "path": item["path"],
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        self.assertEqual(actual, listed)
        self.assertEqual(
            self.review_manifest["member_count_including_manifest"], len(listed) + 1
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
