#!/opt/anaconda3/bin/python3
"""Zero-network mechanical audit tests for frozen C4 REAL R3 Shard A."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unittest
import zipfile


ARTIFACT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ARTIFACT_DIR / "execution_output_v1"
AUTHORIZATION_RECORD = ARTIFACT_DIR / "generation_execution_authorization_v1.json"
SOURCE_MANIFEST = ARTIFACT_DIR / "generation_execution_source_manifest_v1.json"
AUDIT = ARTIFACT_DIR / "generation_execution_audit_v1.json"
PACKAGE_ZIP = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_GENERATION_SHARD_A_EXECUTION_PACKAGE_R3_2026-09-01.zip"
)

EXPECTED_PACKAGE_SHA256 = (
    "bb7419ed26ab91765437e6fad97419d8b29056ede69da85fdd75acf8c41a7696"
)
EXPECTED_MANIFEST_SHA256 = (
    "4763d891e35de587aca42b63dc1b57b69bb8a8ec5b6717411f7b5c24382a44c3"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "9a7d2219b65d85b458d0002b2fa7247e207c831890172bc2b1936d59c1ee693b"
)
EXPECTED_TERMINAL_SHA256 = (
    "bddc59c161540abafc5b287bd1e8cff00c2512417ee2390923ad6e395889ec0a"
)
EXPECTED_ANSWER_SET_SHA256 = (
    "6b78607363c4d0a0908507472b83a047a28773c3a948046bf9776ed71c1d1851"
)
EXPECTED_PACKAGE_ID = "C4_REAL_GENERATION_SHARD_A_R3_20260901"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-R3A-REGENERATION-20260901"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_REQUEST_COUNT = 50
EXPECTED_MAXIMUM_ATTEMPTS = 100
EXPECTED_PHYSICAL_ATTEMPTS = 51
EXPECTED_RETRY_COUNT = 1
EXPECTED_OUTPUT_FILES = {
    "GENERATION_ATTEMPT_JOURNAL.jsonl",
    "GENERATION_ERROR_REGISTRY.jsonl",
    "GENERATION_EXECUTION_REPORT.md",
    "GENERATION_EXECUTION_STATUS.json",
    "GENERATION_PREFLIGHT_RECEIPT.json",
    "GENERATION_TERMINAL_JOURNAL.jsonl",
    "GENERATION_USAGE_AND_COST.json",
}
EXPECTED_PACKAGE_FILES = {
    "BLINDED_REQUESTS.jsonl",
    "EXECUTION_CONTRACT.json",
    "GENERATION_CONFIGURATION.json",
    "GENERATION_PROMPT.txt",
    "GENERATION_SCHEMA.json",
    "PACKAGE_SOURCE_HASHES.json",
    "README.md",
    "STUDENT_FACING_FORMAT_CONTRACT.json",
    "c4_real_student_facing_response_validator_v1.py",
    "generation_execution_runner_v3.py",
    "test_package.py",
    "validate_package.py",
}
AUTHORIZATION_FIELDS = {
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
REQUEST_FIELDS = {
    "schema_version",
    "logical_generation_request_id",
    "response_blind_id",
    "provider_payload_sha256",
    "estimated_input_tokens",
    "provider_payload",
}
TERMINAL_FIELDS = {
    "schema_version",
    "logical_order",
    "logical_generation_request_id",
    "response_blind_id",
    "terminal_status",
    "physical_attempts",
    "provider_payload_sha256",
    "requested_model",
    "returned_model",
    "provider_response_id",
    "system_fingerprint",
    "finish_reason",
    "raw_response_content",
    "parsed_output",
    "student_facing_validation_status",
    "prompt_tokens",
    "cached_input_tokens",
    "completion_tokens",
    "total_tokens",
    "recorded_at_utc",
}
RETRYABLE_CATEGORIES = {
    "INVALID_JSON",
    "STRICT_SCHEMA_VALIDATION_FAILED",
    "NON_STUDENT_FACING_FORMAT",
}
SECRET_PATTERN = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)


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


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def package_rows() -> list[dict[str, object]]:
    with zipfile.ZipFile(PACKAGE_ZIP) as archive:
        payload = archive.read("BLINDED_REQUESTS.jsonl").decode("utf-8")
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


def terminal_rows() -> list[dict[str, object]]:
    return load_jsonl(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl")


def attempt_rows() -> list[dict[str, object]]:
    return load_jsonl(OUTPUT_DIR / "GENERATION_ATTEMPT_JOURNAL.jsonl")


def answer_set_sha256(rows: list[dict[str, object]]) -> str:
    integration_rows = [
        {
            "logical_order": row["logical_order"],
            "logical_generation_request_id": row["logical_generation_request_id"],
            "response_blind_id": row["response_blind_id"],
            "provider_payload_sha256": row["provider_payload_sha256"],
            "answer_text": row["parsed_output"]["answer_text"],
        }
        for row in rows
    ]
    return sha256_bytes(canonical_bytes(integration_rows))


def answer_hash_records(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "logical_order": row["logical_order"],
            "logical_generation_request_id": row["logical_generation_request_id"],
            "response_blind_id": row["response_blind_id"],
            "answer_text_sha256": sha256_bytes(
                row["parsed_output"]["answer_text"].encode("utf-8")
            ),
        }
        for row in rows
    ]


def validator_namespace() -> dict[str, object]:
    with zipfile.ZipFile(PACKAGE_ZIP) as archive:
        source = archive.read(
            "c4_real_student_facing_response_validator_v1.py"
        )
    expected = (
        "5b098ff2e8368a7830938ae83ea4ea5cbdcdf71fcf61b674c579118c4742fbcc"
    )
    if sha256_bytes(source) != expected:
        raise AssertionError("frozen semantic-validator identity mismatch")
    namespace: dict[str, object] = {"__name__": "frozen_validator_offline"}
    exec(compile(source, "<frozen-validator>", "exec"), namespace)
    return namespace


def iter_json_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from iter_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_keys(child)


class FrozenR3AShardMechanicalAuditTests(unittest.TestCase):
    def test_01_package_zip_and_member_identities(self) -> None:
        self.assertEqual(sha256_file(PACKAGE_ZIP), EXPECTED_PACKAGE_SHA256)
        with zipfile.ZipFile(PACKAGE_ZIP) as archive:
            self.assertEqual(set(archive.namelist()), EXPECTED_PACKAGE_FILES)
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            source_hashes = json.loads(archive.read("PACKAGE_SOURCE_HASHES.json"))
            member_hashes = source_hashes["member_sha256_excluding_self"]
            self.assertEqual(set(member_hashes), EXPECTED_PACKAGE_FILES - {"PACKAGE_SOURCE_HASHES.json"})
            for name, expected in member_hashes.items():
                self.assertEqual(sha256_bytes(archive.read(name)), expected, name)

    def test_02_blinded_manifest_identity_and_population(self) -> None:
        with zipfile.ZipFile(PACKAGE_ZIP) as archive:
            raw_manifest = archive.read("BLINDED_REQUESTS.jsonl")
        self.assertEqual(sha256_bytes(raw_manifest), EXPECTED_MANIFEST_SHA256)
        rows = package_rows()
        self.assertEqual(len(rows), EXPECTED_REQUEST_COUNT)
        self.assertTrue(all(set(row) == REQUEST_FIELDS for row in rows))
        self.assertEqual(
            len({row["logical_generation_request_id"] for row in rows}),
            EXPECTED_REQUEST_COUNT,
        )
        self.assertEqual(
            len({row["response_blind_id"] for row in rows}), EXPECTED_REQUEST_COUNT
        )
        for row in rows:
            self.assertEqual(
                sha256_bytes(canonical_bytes(row["provider_payload"])),
                row["provider_payload_sha256"],
            )

    def test_03_authorization_record_strict_shape_and_binding(self) -> None:
        authorization = load_json(AUTHORIZATION_RECORD)
        self.assertEqual(set(authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(len(authorization), 11)
        self.assertEqual(sha256_file(AUTHORIZATION_RECORD), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(authorization["schema_version"], "c4-real-response-regeneration-authorization-r3")
        self.assertEqual(authorization["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(authorization["authorized_by"], "Ming Liu")
        self.assertRegex(authorization["authorized_at_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(authorization["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(authorization["shard"], "A")
        self.assertEqual(authorization["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(authorization["maximum_physical_attempts"], EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertEqual(authorization["package_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(authorization["blinded_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(authorization["status"], "AUTHORIZED")

    def test_04_output_directory_exclusivity(self) -> None:
        entries = list(OUTPUT_DIR.iterdir())
        self.assertEqual({entry.name for entry in entries}, EXPECTED_OUTPUT_FILES)
        self.assertTrue(all(entry.is_file() and not entry.is_symlink() for entry in entries))

    def test_05_preflight_receipt_and_runtime_identity(self) -> None:
        receipt = load_json(OUTPUT_DIR / "GENERATION_PREFLIGHT_RECEIPT.json")
        status = load_json(OUTPUT_DIR / "GENERATION_EXECUTION_STATUS.json")
        self.assertEqual(receipt["status"], "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION")
        self.assertFalse(receipt["runtime_constructed"])
        self.assertFalse(receipt["client_constructed"])
        self.assertEqual(receipt["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(receipt["shard"], "A")
        self.assertEqual(receipt["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(receipt["maximum_physical_attempts"], EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertEqual(receipt["package_sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(receipt["blinded_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(receipt["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertEqual(receipt["authorization_record_sha256"], EXPECTED_AUTHORIZATION_SHA256)
        runtime = status["runtime_identity"]
        self.assertEqual(runtime["python_version"], "3.13.5")
        self.assertEqual(runtime["python_path"], "/opt/anaconda3/bin/python3")
        self.assertEqual(runtime["openai_sdk_version"], "1.109.1")
        self.assertEqual(runtime["automatic_sdk_retries"], 0)
        self.assertTrue(runtime["api_key_presence_checked_only"])
        self.assertFalse(runtime["api_key_value_recorded"])

    def test_06_execution_status_complete_and_fail_closed(self) -> None:
        status = load_json(OUTPUT_DIR / "GENERATION_EXECUTION_STATUS.json")
        self.assertEqual(status["status"], "COMPLETE_VALID_STUDENT_FACING_RESPONSES")
        self.assertIsNone(status["stop_reason"])
        self.assertEqual(status["request_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(status["valid_response_count"], EXPECTED_REQUEST_COUNT)
        self.assertEqual(status["incomplete_logical_request_count"], 0)
        self.assertEqual(status["unattempted_logical_request_count"], 0)
        self.assertEqual(status["physical_attempt_count"], EXPECTED_PHYSICAL_ATTEMPTS)
        self.assertEqual(status["maximum_physical_attempts"], EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertFalse(status["automatic_resume"])
        self.assertTrue(status["continuation_requires_new_direct_authorization"])

    def test_07_attempt_journal_ordering(self) -> None:
        attempts = attempt_rows()
        expected_order = []
        counts = Counter(row["logical_order"] for row in attempts)
        for logical_order in range(1, EXPECTED_REQUEST_COUNT + 1):
            for attempt_number in range(1, counts[logical_order] + 1):
                expected_order.append((logical_order, attempt_number))
        observed_order = [
            (row["logical_order"], row["attempt_number"]) for row in attempts
        ]
        self.assertEqual(observed_order, expected_order)
        self.assertEqual(len(attempts), EXPECTED_PHYSICAL_ATTEMPTS)
        self.assertEqual(Counter(row["attempt_number"] for row in attempts), {1: 50, 2: 1})

    def test_08_terminal_uniqueness_and_population(self) -> None:
        rows = terminal_rows()
        manifest = package_rows()
        self.assertEqual(len(rows), EXPECTED_REQUEST_COUNT)
        self.assertEqual([row["logical_order"] for row in rows], list(range(1, 51)))
        self.assertEqual(len({row["logical_generation_request_id"] for row in rows}), 50)
        self.assertEqual(len({row["response_blind_id"] for row in rows}), 50)
        self.assertEqual(
            {row["logical_generation_request_id"] for row in rows},
            {row["logical_generation_request_id"] for row in manifest},
        )
        self.assertEqual(
            {row["response_blind_id"] for row in rows},
            {row["response_blind_id"] for row in manifest},
        )
        self.assertTrue(all(set(row) == TERMINAL_FIELDS for row in rows))
        self.assertTrue(
            all(row["terminal_status"] == "VALID_STUDENT_FACING_RESPONSE" for row in rows)
        )

    def test_09_strict_outer_result_shape_and_nonempty_answer(self) -> None:
        for row in terminal_rows():
            parsed_raw = json.loads(row["raw_response_content"])
            self.assertEqual(set(parsed_raw), {"answer_text"})
            self.assertEqual(set(row["parsed_output"]), {"answer_text"})
            self.assertEqual(parsed_raw, row["parsed_output"])
            self.assertIsInstance(row["parsed_output"]["answer_text"], str)
            self.assertTrue(row["parsed_output"]["answer_text"].strip())

    def test_10_student_facing_semantic_validator_results(self) -> None:
        namespace = validator_namespace()
        validate = namespace["validate_answer_text"]
        valid_status = namespace["VALID_STUDENT_FACING_RESPONSE"]
        for row in terminal_rows():
            self.assertEqual(
                validate(row["parsed_output"]["answer_text"]), valid_status
            )
            self.assertEqual(row["student_facing_validation_status"], valid_status)

    def test_11_returned_model_and_finish_reason_identity(self) -> None:
        for row in attempt_rows() + terminal_rows():
            self.assertEqual(row["requested_model"], EXPECTED_MODEL)
            self.assertEqual(row["returned_model"], EXPECTED_MODEL)
            self.assertEqual(row["finish_reason"], "stop")

    def test_12_retry_policy_and_byte_identity(self) -> None:
        attempts_by_order: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in attempt_rows():
            attempts_by_order[row["logical_order"]].append(row)
        retried = [rows for rows in attempts_by_order.values() if len(rows) == 2]
        self.assertEqual(len(retried), EXPECTED_RETRY_COUNT)
        first, second = retried[0]
        self.assertIn(first["retryable_failure"], RETRYABLE_CATEGORIES)
        self.assertEqual(first["retryable_failure"], "NON_STUDENT_FACING_FORMAT")
        self.assertEqual(first["student_facing_validation_status"], "RAW_INTERNAL_STRUCTURE")
        self.assertIsNone(second["retryable_failure"])
        self.assertEqual(second["student_facing_validation_status"], "VALID_STUDENT_FACING_RESPONSE")
        self.assertEqual(first["attempt_number"], 1)
        self.assertEqual(second["attempt_number"], 2)
        self.assertEqual(first["logical_generation_request_id"], second["logical_generation_request_id"])
        self.assertEqual(first["response_blind_id"], second["response_blind_id"])
        self.assertEqual(first["provider_payload_sha256"], second["provider_payload_sha256"])
        manifest_row = next(
            row
            for row in package_rows()
            if row["logical_generation_request_id"] == first["logical_generation_request_id"]
        )
        self.assertEqual(
            sha256_bytes(canonical_bytes(manifest_row["provider_payload"])),
            first["provider_payload_sha256"],
        )
        self.assertIsInstance(first["raw_response_content"], str)
        self.assertTrue(first["raw_response_content"])

    def test_13_physical_attempt_ceiling(self) -> None:
        attempts = attempt_rows()
        self.assertGreaterEqual(len(attempts), EXPECTED_REQUEST_COUNT)
        self.assertLessEqual(len(attempts), EXPECTED_MAXIMUM_ATTEMPTS)
        self.assertTrue(
            all(
                Counter(row["logical_order"] for row in attempts)[logical_order] <= 2
                for logical_order in range(1, EXPECTED_REQUEST_COUNT + 1)
            )
        )

    def test_14_usage_arithmetic_and_aggregate(self) -> None:
        attempts = attempt_rows()
        usage = load_json(OUTPUT_DIR / "GENERATION_USAGE_AND_COST.json")
        for row in attempts:
            self.assertEqual(row["total_tokens"], row["prompt_tokens"] + row["completion_tokens"])
            self.assertGreaterEqual(row["cached_input_tokens"], 0)
            self.assertLessEqual(row["cached_input_tokens"], row["prompt_tokens"])
        for field in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens"):
            self.assertEqual(usage[field], sum(row[field] for row in attempts))
        self.assertEqual(usage["total_tokens"], usage["prompt_tokens"] + usage["completion_tokens"])
        self.assertTrue(usage["usage_arithmetic_valid"])
        self.assertEqual(usage["responses_without_cached_token_detail"], 0)
        self.assertEqual(usage["provider_calls_observed"], EXPECTED_PHYSICAL_ATTEMPTS)

    def test_15_answer_text_hashes_and_answer_set_hash(self) -> None:
        rows = terminal_rows()
        audit = load_json(AUDIT)
        self.assertEqual(answer_set_sha256(rows), EXPECTED_ANSWER_SET_SHA256)
        self.assertEqual(audit["answer_set_sha256"], EXPECTED_ANSWER_SET_SHA256)
        self.assertEqual(audit["answer_text_hashes"], answer_hash_records(rows))

    def test_16_terminal_journal_and_output_hashes(self) -> None:
        source_manifest = load_json(SOURCE_MANIFEST)
        self.assertEqual(
            sha256_file(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl"),
            EXPECTED_TERMINAL_SHA256,
        )
        expected_hashes = source_manifest["execution_output"]["file_sha256"]
        self.assertEqual(set(expected_hashes), EXPECTED_OUTPUT_FILES)
        for name, expected in expected_hashes.items():
            self.assertEqual(sha256_file(OUTPUT_DIR / name), expected, name)

    def test_17_error_registry_and_provider_error_absence(self) -> None:
        self.assertEqual(load_jsonl(OUTPUT_DIR / "GENERATION_ERROR_REGISTRY.jsonl"), [])
        self.assertTrue(all(row["error"] is None for row in attempt_rows()))
        audit = load_json(AUDIT)
        self.assertTrue(all(value == 0 for value in audit["error_counts"].values()))

    def test_18_secret_absence(self) -> None:
        scanned = 0
        for path in ARTIFACT_DIR.rglob("*"):
            if path.is_file() and not path.is_symlink():
                scanned += 1
                self.assertIsNone(SECRET_PATTERN.search(path.read_bytes()), path.name)
        self.assertGreaterEqual(scanned, 11)

    def test_19_restricted_identity_and_evaluation_field_absence(self) -> None:
        values: list[object] = [load_json(AUTHORIZATION_RECORD)]
        for path in OUTPUT_DIR.iterdir():
            if path.suffix == ".json":
                values.append(load_json(path))
            elif path.suffix == ".jsonl":
                values.extend(load_jsonl(path))
        forbidden_exact = {
            "g2",
            "gold",
            "scenario",
            "scenario_id",
            "mode",
            "condition",
            "route",
            "rating",
            "human_rating",
            "score",
            "reference_answer",
            "expected_outcome",
            "hmac_key",
            "restricted_mapping",
        }
        forbidden_prefixes = (
            "g2_",
            "gold_",
            "scenario_",
            "mode_",
            "condition_",
            "route_",
            "rating_",
            "score_",
            "reference_answer_",
            "expected_outcome_",
        )
        for value in values:
            for key in iter_json_keys(value):
                lowered = key.lower()
                self.assertNotIn(lowered, forbidden_exact)
                self.assertFalse(lowered.startswith(forbidden_prefixes), lowered)
                if lowered.startswith("judge_"):
                    self.assertEqual(lowered, "judge_calls")
        status = load_json(OUTPUT_DIR / "GENERATION_EXECUTION_STATUS.json")
        usage = load_json(OUTPUT_DIR / "GENERATION_USAGE_AND_COST.json")
        self.assertEqual(status["judge_calls"], 0)
        self.assertEqual(status["scoring_calls"], 0)
        self.assertEqual(usage["judge_calls"], 0)

    def test_20_future_r3_response_integration_compatibility(self) -> None:
        rows = terminal_rows()
        compatible = [
            {
                "logical_generation_request_id": row["logical_generation_request_id"],
                "response_blind_id": row["response_blind_id"],
                "provider_payload_sha256": row["provider_payload_sha256"],
                "answer_text": row["parsed_output"]["answer_text"],
            }
            for row in rows
        ]
        self.assertEqual(len(compatible), EXPECTED_REQUEST_COUNT)
        self.assertEqual(len({row["logical_generation_request_id"] for row in compatible}), 50)
        self.assertEqual(len({row["response_blind_id"] for row in compatible}), 50)
        self.assertTrue(all(row["answer_text"].strip() for row in compatible))
        self.assertTrue(
            all(re.fullmatch(r"C4G3-[A-F0-9]{24}", row["logical_generation_request_id"]) for row in compatible)
        )
        self.assertTrue(
            all(re.fullmatch(r"R3B3-[A-F0-9]{20}", row["response_blind_id"]) for row in compatible)
        )

    def test_21_source_manifest_bindings(self) -> None:
        manifest = load_json(SOURCE_MANIFEST)
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(manifest["shard"], "A")
        self.assertEqual(manifest["external_package"]["sha256"], EXPECTED_PACKAGE_SHA256)
        self.assertEqual(manifest["external_package"]["regular_file_count"], 12)
        self.assertEqual(set(manifest["external_package"]["member_sha256"]), EXPECTED_PACKAGE_FILES)
        self.assertEqual(manifest["frozen_blinded_manifest"]["sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(manifest["frozen_blinded_manifest"]["request_count"], 50)
        self.assertEqual(manifest["authorization_record"]["sha256"], EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(manifest["execution_output"]["regular_file_count"], 7)

    def test_22_audit_summary_bindings(self) -> None:
        audit = load_json(AUDIT)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["package_id"], EXPECTED_PACKAGE_ID)
        self.assertEqual(audit["shard"], "A")
        self.assertEqual(audit["authorization_id"], EXPECTED_AUTHORIZATION_ID)
        self.assertFalse(audit["qualitative_answer_review_performed"])
        self.assertEqual(audit["execution"]["logical_request_count"], 50)
        self.assertEqual(audit["execution"]["physical_attempt_count"], 51)
        self.assertEqual(audit["execution"]["valid_response_count"], 50)
        self.assertEqual(audit["execution"]["retry_count"], 1)
        self.assertEqual(audit["attempt_classification"]["invalid_json_count"], 0)
        self.assertEqual(audit["attempt_classification"]["strict_schema_validation_failed_count"], 0)
        self.assertEqual(audit["attempt_classification"]["non_student_facing_format_count"], 1)
        self.assertEqual(audit["check_summary"], {"failed": 0, "passed": 28, "total": 28})

    def test_23_cost_and_prohibited_operation_status(self) -> None:
        usage = load_json(OUTPUT_DIR / "GENERATION_USAGE_AND_COST.json")
        audit = load_json(AUDIT)
        self.assertEqual(usage["cost_status"], "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY")
        self.assertIsNone(usage["cost_amount"])
        self.assertIsNone(usage["cost_currency"])
        operations = audit["operation_call_counts"]
        self.assertEqual(operations["response_generation_logical_requests"], 50)
        self.assertEqual(operations["response_generation_physical_attempts"], 51)
        self.assertEqual(operations["judge_calls"], 0)
        self.assertEqual(operations["scoring_calls"], 0)
        self.assertEqual(operations["human_rating_actions"], 0)
        self.assertEqual(operations["rq2_calls"], 0)
        self.assertEqual(operations["streamlit_launches"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
