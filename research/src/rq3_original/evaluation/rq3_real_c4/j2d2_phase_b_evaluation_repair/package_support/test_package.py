#!/usr/bin/env python3
"""Targeted offline runner tests using synthetic metadata and mocked transport.

No delivered Judge package, candidate response, historical result, Human rating,
or score assignment is read. No real authorization record is constructed.
"""

import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import judge_execution_runner_v3 as runner
import judge_result_parser_v3 as parser
import validate_package as validator


class FakeClock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class OfflinePackageTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("REAL_NETWORK_PROHIBITED"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def authorization(self, count=1):
        return {"schema_version": runner.AUTHORIZATION_SCHEMA_VERSION, "authorization_id": "OFFLINE_SYNTHETIC_TEST_ONLY",
                "authorized_by": "OFFLINE_TEST_FIXTURE_NO_REAL_AUTHORITY", "authorized_at_utc": "2026-09-02T00:00:00Z",
                "package_id": "OFFLINE_SYNTHETIC_NOT_A_DELIVERY_PACKAGE", "shard_id": "OFFLINE",
                "request_count": count, "maximum_physical_attempts": count * 2,
                "package_zip_sha256": "1" * 64, "blinded_judge_manifest_sha256": "2" * 64, "status": "AUTHORIZED"}

    def validation(self, count=1):
        return {**{k: v for k, v in self.authorization(count).items() if k in
                   {"package_id", "shard_id", "request_count", "maximum_physical_attempts", "package_zip_sha256", "blinded_judge_manifest_sha256"}},
                "status": "PASS"}

    def run_synthetic(self, outcomes, *, requests=1, returned_model=None, refusal=False):
        """Only synthetic in-memory fixtures reach a transport stub."""
        clock = FakeClock()
        calls = []
        request_rows = []
        for index in range(requests):
            result_id = "R3B-" + format(index + 1, "020X")
            payload = {"messages": [{"role": "system", "content": validator.BEGIN +
                       json.dumps({"frozen_applicability_map": {}, "response_blind_id": result_id}) + validator.END}]}
            request_rows.append({"logical_order": index + 1, "logical_judge_request_id": "C4J4-" + format(index + 1, "024X"),
                                 "judge_result_blind_id": result_id, "provider_payload": payload,
                                 "provider_payload_sha256": validator.sha256_bytes(validator.canonical_json_bytes(payload))})
        def create(**payload):
            calls.append((clock.now, validator.canonical_json_bytes(payload)))
            next_value = outcomes[len(calls) - 1]
            if isinstance(next_value, Exception): raise next_value
            return SimpleNamespace(id="OFFLINE_RESPONSE", model=returned_model or runner.EXPECTED_MODEL,
                                   system_fingerprint=None,
                                   choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=next_value, refusal="OFFLINE_REFUSAL" if refusal else None))],
                                   usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0, prompt_tokens_details=None))
        client = SimpleNamespace(max_retries=0, timeout=120.0, chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
        def parse_stub(raw, applicability, *, expected_judge_result_blind_id):
            if raw != "OFFLINE_VALID_NO_SCORE_CONTENT":
                raise parser.JudgeResultError(raw)
            return {"response_blind_id": expected_judge_result_blind_id, "schema_version": parser.SEMANTIC_SCHEMA_VERSION}
        with tempfile.TemporaryDirectory(prefix="c4_r4_mock_only_") as name:
            directory = Path(name)
            authorization_path = directory / "SYNTHETIC_NOT_REAL_AUTHORIZATION.json"
            authorization_path.write_text(json.dumps(self.authorization(requests)))
            output = directory / "synthetic_output"
            members = {"BLINDED_JUDGE_REQUESTS.jsonl": b"".join(validator.canonical_json_bytes(row) + b"\n" for row in request_rows)}
            with patch.dict(os.environ, {runner.AUTHORIZATION_ENVIRONMENT_VARIABLE: runner.AUTHORIZATION_ENVIRONMENT_VALUE}), \
                 patch.object(runner, "validate_package_zip", return_value=self.validation(requests)), \
                 patch.object(runner, "read_package_zip", return_value=members), \
                 patch.object(runner, "sha256_file", return_value="1" * 64), \
                 patch.object(runner, "parse_judge_result", side_effect=parse_stub):
                error = None
                try:
                    runner.execute_package(directory / "NOT_A_REAL_PACKAGE.zip", authorization_path, output,
                                           runtime_probe=lambda: {"offline_fixture": True}, client_factory=lambda: client,
                                           monotonic=clock.monotonic, sleeper=clock.sleep,
                                           utc_now=lambda: "2026-09-02T00:00:00Z")
                except runner.RunnerError as exc: error = exc
            status = json.loads((output / "JUDGE_EXECUTION_STATUS.json").read_text())
            receipt = json.loads((output / "JUDGE_PREFLIGHT_START_RECEIPT.json").read_text())
            self.assertEqual(receipt["judge_calls_at_receipt_write"], 0)
            self.assertFalse(receipt["client_constructed_at_receipt_write"])
            return calls, status, error

    def test_01_exact_r4_gate(self):
        self.assertEqual(runner.AUTHORIZATION_ENVIRONMENT_VALUE, "AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4")

    def test_02_missing_gate_prevents_package_access(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(runner, "validate_package_zip") as validate:
            with self.assertRaises(runner.RunnerError): runner.execute_package(Path("absent.zip"), Path("absent.json"), Path("absent-output"))
            validate.assert_not_called()

    def test_03_external_authorization_exact_fields(self):
        value = self.authorization(); value["extra"] = True
        with self.assertRaises(runner.RunnerError): runner._validate_authorization_record(value, package_validation=self.validation(), package_zip_sha256="1" * 64)

    def test_04_external_authorization_package_hash(self):
        with self.assertRaises(runner.RunnerError): runner._validate_authorization_record(self.authorization(), package_validation=self.validation(), package_zip_sha256="0" * 64)

    def test_05_external_authorization_count_binding(self):
        value = self.authorization(); value["request_count"] = 2
        with self.assertRaises(runner.RunnerError): runner._validate_authorization_record(value, package_validation=self.validation(), package_zip_sha256="1" * 64)

    def test_06_sdk_retries_zero_required(self):
        with self.assertRaises(runner.RunnerError): runner.validate_client_transport_configuration(SimpleNamespace(max_retries=1, timeout=120.0))

    def test_07_timeout_exact_120_required(self):
        with self.assertRaises(runner.RunnerError): runner.validate_client_transport_configuration(SimpleNamespace(max_retries=0, timeout=10.0))

    def test_08_initial_pacing_15_seconds(self):
        calls, status, error = self.run_synthetic(["OFFLINE_VALID_NO_SCORE_CONTENT"] * 2, requests=2)
        self.assertIsNone(error); self.assertEqual(status["valid_terminal_count"], 2)
        self.assertGreaterEqual(calls[1][0] - calls[0][0], 15.0)

    def test_09_invalid_json_one_identical_retry(self):
        calls, status, error = self.run_synthetic(["INVALID_JSON", "OFFLINE_VALID_NO_SCORE_CONTENT"])
        self.assertIsNone(error); self.assertEqual(len(calls), 2); self.assertEqual(calls[0][1], calls[1][1])

    def test_10_schema_failure_one_identical_retry(self):
        calls, status, error = self.run_synthetic(["STRICT_SCHEMA_VALIDATION_FAILED", "OFFLINE_VALID_NO_SCORE_CONTENT"])
        self.assertIsNone(error); self.assertEqual(len(calls), 2); self.assertEqual(calls[0][1], calls[1][1])

    def test_11_applicability_failure_one_identical_retry(self):
        calls, status, error = self.run_synthetic(["APPLICABILITY_CONTRACT_VIOLATION", "OFFLINE_VALID_NO_SCORE_CONTENT"])
        self.assertIsNone(error); self.assertEqual(len(calls), 2); self.assertEqual(calls[0][1], calls[1][1])

    def test_12_second_invalid_stops_entire_shard(self):
        calls, status, error = self.run_synthetic(["INVALID_JSON", "INVALID_JSON"], requests=2)
        self.assertIsNotNone(error); self.assertEqual(len(calls), 2); self.assertEqual(status["valid_terminal_count"], 0)

    def test_13_timeout_is_nonretryable(self):
        calls, status, error = self.run_synthetic([TimeoutError("OFFLINE_TIMEOUT")])
        self.assertIsNotNone(error); self.assertEqual(len(calls), 1)

    def test_14_transport_is_nonretryable(self):
        calls, status, error = self.run_synthetic([ConnectionError("OFFLINE_TRANSPORT")])
        self.assertIsNotNone(error); self.assertEqual(len(calls), 1)

    def test_15_billing_rate_auth_permission_are_nonretryable(self):
        for code in ("insufficient_quota", "rate_limit_exceeded", "invalid_api_key", "permission_denied"):
            with self.subTest(code=code):
                error_value = RuntimeError("OFFLINE_ERROR"); error_value.code = code
                calls, status, error = self.run_synthetic([error_value])
                self.assertIsNotNone(error); self.assertEqual(len(calls), 1)

    def test_16_refusal_is_nonretryable(self):
        calls, status, error = self.run_synthetic(["OFFLINE_VALID_NO_SCORE_CONTENT"], refusal=True)
        self.assertIsNotNone(error); self.assertEqual(len(calls), 1)

    def test_17_returned_model_mismatch_is_nonretryable(self):
        calls, status, error = self.run_synthetic(["OFFLINE_VALID_NO_SCORE_CONTENT"], returned_model="OFFLINE_WRONG_MODEL")
        self.assertIsNotNone(error); self.assertEqual(len(calls), 1)

    def test_18_existing_output_cannot_resume(self):
        with tempfile.TemporaryDirectory(prefix="c4_r4_no_resume_") as name, patch.object(runner, "validate_package_zip") as validate:
            with self.assertRaises(runner.RunnerError): runner.execute_package(Path("absent.zip"), Path("absent.json"), Path(name))
            validate.assert_not_called()

    def test_19_parser_v3_duplicate_keys(self):
        with self.assertRaises(parser.JudgeResultError): parser._load_json_object('{"duplicate":null,"duplicate":null}')

    def test_20_parser_v3_invalid_json(self):
        with self.assertRaises(parser.JudgeResultError): parser._load_json_object("OFFLINE_INVALID_JSON")

    def test_21_exact_allowlist_excludes_old_results(self):
        self.assertEqual(len(validator.ALLOWED_FILES), 13)
        self.assertIn("APPLICABILITY_CONTRACT_V2.json", validator.ALLOWED_FILES)
        self.assertFalse(any("JOURNAL" in name or "RATING" in name or "KEY" in name for name in validator.ALLOWED_FILES))

    def test_22_parser_hash_pinned(self):
        self.assertEqual(validator.PARSER_SHA256, "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb")


if __name__ == "__main__":
    unittest.main(verbosity=2)
