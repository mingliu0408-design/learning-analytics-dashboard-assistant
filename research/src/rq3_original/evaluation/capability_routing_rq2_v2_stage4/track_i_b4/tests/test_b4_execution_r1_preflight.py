from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


TRACK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK_DIR))

import execute_b4_dev_r1 as execution  # noqa: E402
import finalize_b4_dev_r1 as finalizer  # noqa: E402


class B4ExecutionR1PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2 = execution.load_jsonl(execution.V2_MANIFEST_PATH)
        cls.v3 = execution.load_jsonl(execution.V3_MANIFEST_PATH)
        cls.diff = json.loads(
            execution.MANIFEST_DIFF_PATH.read_text(encoding="utf-8")
        )
        cls.schema_v1 = json.loads(
            execution.SCHEMA_V1_PATH.read_text(encoding="utf-8")
        )
        cls.schema_v2 = json.loads(
            execution.SCHEMA_V2_PATH.read_text(encoding="utf-8")
        )

    def test_01_all_historical_stage4ix_hashes_unchanged(self) -> None:
        observed = execution.verify_historical_artifacts()
        self.assertEqual(execution.HISTORICAL_STAGE4IX_SHA256, observed)
        self.assertEqual(19, len(observed))

    def test_02_historical_failure_is_separately_classified(self) -> None:
        preservation = json.loads(
            execution.HISTORICAL_PRESERVATION_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(
            "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
            preservation["historical_classification"],
        )
        self.assertFalse(preservation["historical_model_response_present"])
        self.assertFalse(preservation["historical_parsed_prediction_present"])
        self.assertFalse(preservation["historical_provider_usage_present"])
        self.assertFalse(preservation["included_in_r1_performance_metrics"])

    def test_03_schema_v1_v2_semantic_equivalence_boundary(self) -> None:
        validation = execution.schema_v1_v2_equivalence()
        normalized = dict(self.schema_v1)
        for key in execution.SCHEMA_METADATA_REMOVED:
            normalized.pop(key)
        self.assertEqual(normalized, self.schema_v2)
        self.assertTrue(validation["semantic_output_space_unchanged"])
        self.assertEqual(
            ["rag_required", "memory_required", "planning_required"],
            self.schema_v2["required"],
        )
        self.assertIs(False, self.schema_v2["additionalProperties"])

    def test_04_schema_v2_is_exact_minimal_object(self) -> None:
        self.assertEqual(
            {"type", "properties", "required", "additionalProperties"},
            set(self.schema_v2),
        )
        self.assertFalse(
            {"$schema", "title", "minProperties", "maxProperties"}
            & set(self.schema_v2)
        )
        self.assertEqual(
            {field: {"type": "boolean"} for field in execution.LABEL_FIELDS},
            self.schema_v2["properties"],
        )

    def test_05_v2_v3_exact_allowed_difference_boundary(self) -> None:
        validation = execution.validate_manifest_pair(self.v2, self.v3)
        self.assertEqual(
            sorted(execution.ALLOWED_V2_V3_DIFF_PATHS),
            validation["observed_difference_paths"],
        )
        self.assertTrue(validation["normalized_v3_equals_v2"])
        self.assertEqual(
            "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY", self.diff["status"]
        )
        self.assertEqual(
            execution.sha256_file(execution.V2_MANIFEST_PATH),
            self.diff["v2_manifest_sha256"],
        )
        self.assertEqual(
            execution.sha256_file(execution.V3_MANIFEST_PATH),
            self.diff["v3_manifest_sha256"],
        )

    def test_06_exact_64_new_logical_requests_and_order(self) -> None:
        expected = [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)]
        self.assertEqual(64, len(self.v3))
        self.assertEqual(expected, [record["logical_call_id"] for record in self.v3])
        self.assertEqual(64, len({record["annotation_case_id"] for record in self.v3}))
        self.assertEqual({"NOT_EXECUTED"}, {record["execution_status"] for record in self.v3})

    def test_07_prompt_examples_inputs_folds_and_messages_unchanged(self) -> None:
        self.assertEqual(
            execution.EXPECTED_PROMPT_SHA256,
            execution.sha256_file(TRACK_DIR / "b4_prompt_template_frozen_v1.txt"),
        )
        for old, new in zip(self.v2, self.v3, strict=True):
            self.assertEqual(old["prompt_template_sha256"], new["prompt_template_sha256"])
            self.assertEqual(old["logical_call_id"], new["logical_call_id"])
            self.assertEqual(old["annotation_case_id"], new["annotation_case_id"])
            self.assertEqual(old["outer_fold_id"], new["outer_fold_id"])
            self.assertEqual(old["validation_input"], new["validation_input"])
            self.assertEqual(old["fold_specific_example_ids"], new["fold_specific_example_ids"])
            self.assertEqual(old["fold_specific_example_set_sha256"], new["fold_specific_example_set_sha256"])
            self.assertEqual(
                old["provider_request_payload"]["messages"],
                new["provider_request_payload"]["messages"],
            )

    def test_08_model_and_api_feature_boundary(self) -> None:
        for record in self.v3:
            payload = record["provider_request_payload"]
            self.assertEqual(execution.AUTHORIZED_MODEL_SNAPSHOT, payload["model"])
            self.assertEqual(0, payload["temperature"])
            self.assertEqual(64, payload["max_tokens"])
            self.assertEqual(
                {"model", "messages", "temperature", "response_format", "max_tokens"},
                set(payload),
            )
            self.assertNotIn("stream", payload)
            self.assertNotIn("tools", payload)
            self.assertNotIn("web_search_options", payload)
            self.assertEqual("json_schema", payload["response_format"]["type"])
            self.assertIs(True, payload["response_format"]["json_schema"]["strict"])

    def test_09_client_has_zero_sdk_retries(self) -> None:
        tree = ast.parse(
            (TRACK_DIR / "execute_b4_dev_r1.py").read_text(encoding="utf-8")
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "OpenAI"
        ]
        self.assertEqual(1, len(calls))
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertIsInstance(keywords["max_retries"], ast.Name)
        self.assertEqual("CLIENT_MAX_RETRIES", keywords["max_retries"].id)
        self.assertEqual(0, execution.CLIENT_MAX_RETRIES)

    def test_10_strict_parser_rejects_without_repair(self) -> None:
        valid = '{"rag_required":true,"memory_required":false,"planning_required":true}'
        parsed, accepted, error = execution.validate_response_content(valid)
        self.assertTrue(accepted)
        self.assertIsNone(error)
        self.assertEqual(
            {
                "rag_required": True,
                "memory_required": False,
                "planning_required": True,
            },
            parsed,
        )
        invalid = (
            "prefix " + valid,
            '{"rag_required":"true","memory_required":false,"planning_required":true}',
            '{"rag_required":true,"memory_required":false}',
            '{"rag_required":true,"memory_required":false,"planning_required":true,"extra":false}',
        )
        for value in invalid:
            with self.subTest(value=value):
                _parsed, accepted, _error = execution.validate_response_content(value)
                self.assertFalse(accepted)

    def test_11_retry_is_only_for_invalid_structured_output(self) -> None:
        source = (TRACK_DIR / "execute_b4_dev_r1.py").read_text(encoding="utf-8")
        self.assertIn(
            'outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1',
            source,
        )
        self.assertNotIn("correction_message", source)
        for record in self.v3:
            self.assertEqual(
                {
                    "invalid_structured_output_retries_max": 1,
                    "sdk_transport_retries": 0,
                    "silent_repair_allowed": False,
                },
                record["execution_controls"],
            )

    def test_12_error_categories_and_safe_diagnostics(self) -> None:
        error_class = type("BadRequestError", (Exception,), {})
        error = error_class("fallback")
        error.status_code = 400
        error.request_id = "req_safe_123"
        error.body = {
            "message": "Invalid schema " + "sk-" + "proj-" + "ABCDEFGHIJKLMNOP",
            "code": "invalid_json_schema",
            "param": "response_format",
        }
        diagnostic = execution.safe_provider_error(error)
        self.assertEqual("REQUEST_CONFIGURATION_ERROR", diagnostic["category"])
        self.assertNotEqual("AUTHENTICATION_ERROR", diagnostic["category"])
        self.assertEqual(400, diagnostic["http_status"])
        self.assertEqual("invalid_json_schema", diagnostic["provider_error_code"])
        self.assertEqual("response_format", diagnostic["provider_error_param"])
        self.assertEqual("req_safe_123", diagnostic["provider_request_id"])
        self.assertIn("[REDACTED_API_KEY]", diagnostic["sanitized_error_message"])
        self.assertNotIn("sk-" + "proj-", diagnostic["sanitized_error_message"])

    def test_13_first_call_fail_closed_categories(self) -> None:
        for category in execution.FIRST_CALL_FATAL_CATEGORIES:
            terminal = {"provider_error": {"category": category}}
            self.assertEqual(
                f"FIRST_LOGICAL_CALL_{category}",
                execution.first_call_stop_reason(1, terminal),
            )
            self.assertIsNone(execution.first_call_stop_reason(2, terminal))
        self.assertIsNone(
            execution.first_call_stop_reason(
                1, {"provider_error": {"category": "RATE_LIMIT_ERROR"}}
            )
        )

    def test_14_no_test_identifiers_or_credentials_in_provider_inputs(self) -> None:
        for record in self.v3:
            payload = json.dumps(record["provider_request_payload"], ensure_ascii=False)
            self.assertNotIn("R2V2-TEST", payload.upper())
            self.assertNotIn("TEST_ESCROW", payload.upper())
            self.assertNotRegex(payload, r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")

    def test_15_offline_first_error_finalization_smoke(self) -> None:
        manifest = self.v3[0]
        request_hash = execution.canonical_sha256(
            manifest["provider_request_payload"]
        )
        attempt = {
            "schema_version": "rq2-v2-stage4-i-x-r1-b4-attempt-record-v2",
            "physical_attempt_id": "R2V2-B4-R1-PHYS-0001",
            "physical_attempt_number": 1,
            "cumulative_physical_attempt_number": 2,
            "logical_call_id": manifest["logical_call_id"],
            "annotation_case_id": manifest["annotation_case_id"],
            "fold_id": manifest["outer_fold_id"],
            "attempt_number": 1,
            "request_sha256": request_hash,
            "response_id": None,
            "requested_model": execution.AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": None,
            "system_fingerprint": None,
            "finish_reason": None,
            "response_content": None,
            "parsed_json": None,
            "schema_validation": {"valid": False, "error": "PROVIDER_ERROR"},
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "latency_seconds": 0.1,
            "provider_error": {
                "exception_type": "BadRequestError",
                "http_status": 400,
                "provider_error_code": "invalid_json_schema",
                "provider_error_param": "response_format",
                "provider_request_id": "req_safe",
                "sanitized_error_message": "Invalid schema",
                "category": "REQUEST_CONFIGURATION_ERROR",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
            },
            "started_at": "2026-08-31T00:00:00.000Z",
            "completed_at": "2026-08-31T00:00:00.100Z",
        }
        journal = [
            {
                "event": "ATTEMPT_RESERVED",
                "physical_attempt_id": "R2V2-B4-R1-PHYS-0001",
                "physical_attempt_number": 1,
                "cumulative_physical_attempt_number": 2,
                "logical_call_id": manifest["logical_call_id"],
                "request_sha256": request_hash,
            },
            {
                "event": "ATTEMPT_COMPLETED",
                "physical_attempt_id": "R2V2-B4-R1-PHYS-0001",
                "physical_attempt_number": 1,
                "cumulative_physical_attempt_number": 2,
                "logical_call_id": manifest["logical_call_id"],
                "request_sha256": request_hash,
            },
        ]
        terminal = {
            "logical_call_id": manifest["logical_call_id"],
            "annotation_case_id": manifest["annotation_case_id"],
            "fold_id": manifest["outer_fold_id"],
            "terminal_status": "PROVIDER_ERROR",
            "prediction": None,
            "attempts_used": 1,
            "request_sha256": request_hash,
            "response_id": None,
            "requested_model": execution.AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": None,
            "schema_valid": False,
            "provider_error": attempt["provider_error"],
        }
        with tempfile.TemporaryDirectory(prefix="b4_r1_finalizer_smoke_") as temp:
            root = Path(temp)
            paths = {
                "ATTEMPT_RECORDS_PATH": root / "attempts.jsonl",
                "CALL_JOURNAL_PATH": root / "journal.jsonl",
                "TERMINAL_RESULTS_PATH": root / "terminals.jsonl",
                "PREDICTIONS_PATH": root / "predictions.csv",
                "ERROR_REGISTRY_PATH": root / "errors.csv",
                "USAGE_PATH": root / "usage.json",
                "METRICS_PATH": root / "metrics.json",
                "FINAL_FREEZE_PATH": root / "freeze.json",
                "RESULTS_REPORT_PATH": root / "results.md",
                "STATUS_PATH": root / "status.md",
                "VERIFICATION_REPORT_PATH": root / "verification.md",
            }
            paths["ATTEMPT_RECORDS_PATH"].write_text(
                execution.canonical_json(attempt) + "\n", encoding="utf-8"
            )
            paths["CALL_JOURNAL_PATH"].write_text(
                "".join(execution.canonical_json(value) + "\n" for value in journal),
                encoding="utf-8",
            )
            paths["TERMINAL_RESULTS_PATH"].write_text(
                execution.canonical_json(terminal) + "\n", encoding="utf-8"
            )
            patches = [mock.patch.object(finalizer, name, path) for name, path in paths.items()]
            for patcher in patches:
                patcher.start()
            try:
                summary = finalizer.finalize(
                    stop_reason="FIRST_LOGICAL_CALL_REQUEST_CONFIGURATION_ERROR",
                    manifest_diff_report=self.diff,
                )
            finally:
                for patcher in reversed(patches):
                    patcher.stop()
            self.assertEqual("EXECUTION_INCOMPLETE_NOT_FROZEN", summary["B4_MODEL_STATUS"])
            self.assertEqual(1, summary["new_logical_calls"])
            self.assertEqual(1, summary["new_physical_attempts"])
            self.assertEqual(2, summary["cumulative_physical_attempts"])
            self.assertEqual(0, summary["valid_predictions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
