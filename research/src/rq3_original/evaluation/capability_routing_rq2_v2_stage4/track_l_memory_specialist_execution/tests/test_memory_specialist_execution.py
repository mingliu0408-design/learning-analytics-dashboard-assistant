from __future__ import annotations

import ast
import csv
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from .. import execute_memory_specialist_dev as execution
from .. import finalize_memory_specialist_dev as finalizer
from .. import memory_specialist_common as common


class _FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.payloads: list[dict[str, object]] = []

    def create(self, **payload: object) -> object:
        self.payloads.append(payload)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(outcomes))


def _response(content: str) -> object:
    message = types.SimpleNamespace(content=content, refusal=None)
    choice = types.SimpleNamespace(finish_reason="stop", message=message)
    usage = types.SimpleNamespace(
        prompt_tokens=100, completion_tokens=5, total_tokens=105
    )
    return types.SimpleNamespace(
        id="chatcmpl-safe-fixture",
        model=common.AUTHORIZED_MODEL_SNAPSHOT,
        system_fingerprint="fp_fixture",
        choices=[choice],
        usage=usage,
    )


class MemorySpecialistExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = common.load_jsonl(common.V1_MANIFEST_PATH)
        cls.v2 = common.load_jsonl(common.V2_MANIFEST_PATH)
        cls.diff = common.load_json(common.MANIFEST_DIFF_PATH)

    def test_01_frozen_stage4k0_and_required_hashes_pass(self) -> None:
        observed = common.verify_frozen_sources()
        self.assertEqual("PASS", observed["status"])
        self.assertEqual(36, observed["k0_file_count"])
        self.assertEqual(8, observed["upstream_file_count"])
        self.assertEqual(
            common.EXPECTED_PROMPT_SHA256,
            observed["required_identities"]["prompt_sha256"],
        )
        self.assertEqual(
            common.EXPECTED_SCHEMA_SHA256,
            observed["required_identities"]["schema_sha256"],
        )

    def test_02_manifest_has_exactly_64_unique_ordered_records(self) -> None:
        expected = [
            f"R2V2-MEMORY-SPECIALIST-DEV-{index:04d}"
            for index in range(1, 65)
        ]
        self.assertEqual(64, len(self.v2))
        self.assertEqual(expected, [record["logical_call_id"] for record in self.v2])
        self.assertEqual(64, len({record["annotation_case_id"] for record in self.v2}))
        self.assertEqual(
            {f"DEV-CV-FOLD-{value}": 16 for value in range(1, 5)},
            self.diff["fold_counts"],
        )

    def test_03_v1_v2_exact_allowed_difference_boundary(self) -> None:
        validation = common.validate_manifest_pair(self.v1, self.v2)
        self.assertEqual(
            sorted(common.ALLOWED_V1_V2_DIFF_PATHS),
            validation["observed_difference_paths"],
        )
        self.assertTrue(validation["normalized_v2_equals_v1"])
        self.assertTrue(validation["all_semantic_request_elements_identical"])
        self.assertEqual("PASS_EXACT_ALLOWED_DIFFERENCES_ONLY", self.diff["status"])

    def test_04_semantic_request_elements_are_byte_value_identical(self) -> None:
        for old, new in zip(self.v1, self.v2, strict=True):
            for field in (
                "logical_call_id",
                "annotation_case_id",
                "outer_fold",
                "prompt_sha256",
                "specialist_schema_sha256",
                "fold_example_ids_in_order",
                "fold_example_id_order_sha256",
                "fold_example_set_sha256",
                "fold_prompt_package_sha256",
                "semantic_validation_inputs",
                "execution_controls",
                "validation_gold_in_provider_request",
                "model_snapshot",
            ):
                self.assertEqual(old[field], new[field], field)
            old_payload = old["provider_facing_request"]
            new_payload = new["provider_facing_request"]
            for field in ("model", "messages", "temperature", "max_tokens", "response_format"):
                self.assertEqual(old_payload[field], new_payload[field], field)

    def test_05_authorization_and_transport_fields_are_exact(self) -> None:
        for record in self.v2:
            self.assertEqual(common.AUTHORIZED_STATUS, record["execution_authorization_status"])
            self.assertEqual(common.AUTHORIZED_STATUS, record["model_execution_authorization_status"])
            self.assertEqual(common.RUN_VERSION, record["run_version"])
            payload = record["provider_facing_request"]
            self.assertIs(False, payload["stream"])
            self.assertEqual(common.AUTHORIZED_MODEL_SNAPSHOT, payload["model"])
            self.assertEqual(0, payload["temperature"])
            self.assertEqual(32, payload["max_tokens"])
            self.assertEqual(common.canonical_sha256(payload), record["provider_facing_request_sha256"])

    def test_06_provider_payload_has_only_authorized_fields(self) -> None:
        expected = {
            "model", "messages", "temperature", "max_tokens", "response_format", "stream"
        }
        for record in self.v2:
            payload = record["provider_facing_request"]
            self.assertEqual(expected, set(payload))
            serialized = json.dumps(payload, ensure_ascii=False).lower()
            for feature in ("tools", "web_search", "file_search", "retrieval", "function_call"):
                self.assertNotIn(feature, serialized)

    def test_07_strict_parser_accepts_only_one_boolean(self) -> None:
        self.assertEqual(
            {common.TARGET_FIELD: True},
            common.parse_strict_memory_response('{"memory_required":true}'),
        )
        self.assertEqual(
            {common.TARGET_FIELD: False},
            common.parse_strict_memory_response('{"memory_required":false}'),
        )

    def test_08_strict_parser_rejects_invalid_json_and_prose(self) -> None:
        for value in ("not json", 'prefix {"memory_required":true}', ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    common.parse_strict_memory_response(value)

    def test_09_strict_parser_rejects_coercion_missing_and_extra_fields(self) -> None:
        invalid = (
            '{"memory_required":"true"}',
            "{}",
            '{"memory_required":true,"explanation":"x"}',
            '{"memory_required":1}',
            "[]",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    common.parse_strict_memory_response(value)

    def test_10_openai_client_is_constructed_with_zero_retries(self) -> None:
        tree = ast.parse(Path(execution.__file__).read_text(encoding="utf-8"))
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
        self.assertEqual(0, common.CLIENT_MAX_RETRIES)

    def test_11_initial_request_pacer_enforces_two_seconds(self) -> None:
        clock = [0.0]

        def now() -> float:
            return clock[0]

        def sleep(seconds: float) -> None:
            clock[0] += seconds

        pacer = execution.InitialRequestPacer(time_fn=now, sleep_fn=sleep)
        slept, interval = pacer.before_initial_request()
        self.assertEqual(0.0, slept)
        self.assertIsNone(interval)
        clock[0] += 0.25
        slept, interval = pacer.before_initial_request()
        self.assertAlmostEqual(1.75, slept)
        self.assertEqual(2.0, interval)

    def test_12_provider_error_classification_is_fail_closed(self) -> None:
        cases = (
            ("AuthenticationError", 401, "AUTHENTICATION_ERROR"),
            ("PermissionDeniedError", 403, "PERMISSION_ERROR"),
            ("BadRequestError", 400, "REQUEST_CONFIGURATION_ERROR"),
            ("NotFoundError", 404, "MODEL_OR_ENDPOINT_NOT_FOUND"),
            ("RateLimitError", 429, "RATE_LIMIT_ERROR"),
            ("APIConnectionError", None, "TRANSPORT_ERROR"),
        )
        for name, status, expected in cases:
            error_type = type(name, (Exception,), {})
            error = error_type("fixture")
            error.status_code = status
            self.assertEqual(expected, execution.classify_provider_error(error))

    def test_13_provider_diagnostics_are_sanitized(self) -> None:
        error_type = type("BadRequestError", (Exception,), {})
        secret_shape = "sk-" + "proj-" + "ABCDEFGHIJKLMNOP"
        error = error_type("fallback")
        error.status_code = 400
        error.request_id = "req_safe_fixture"
        error.body = {
            "message": "Invalid schema " + secret_shape,
            "code": "invalid_json_schema",
            "param": "response_format",
        }
        diagnostic = execution.safe_provider_error(error)
        self.assertEqual("REQUEST_CONFIGURATION_ERROR", diagnostic["category"])
        self.assertIn("[REDACTED_API_KEY]", diagnostic["sanitized_error_message"])
        self.assertNotIn(secret_shape, diagnostic["sanitized_error_message"])
        self.assertFalse(diagnostic["authorization_headers_recorded"])

    def test_14_retry_source_guard_is_invalid_output_only(self) -> None:
        source = Path(execution.__file__).read_text(encoding="utf-8")
        self.assertIn(
            'outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1',
            source,
        )
        self.assertNotIn("correction_message", source)
        for record in self.v2:
            controls = record["execution_controls"]
            self.assertEqual(1, controls["manual_retry_max"])
            self.assertEqual("INVALID_JSON_OR_STRICT_SCHEMA_ONLY", controls["manual_retry_condition"])
            self.assertTrue(controls["retry_prompt_identical"])
            self.assertFalse(controls["correction_message_allowed"])
            self.assertFalse(controls["string_to_boolean_coercion_allowed"])

    def test_15_first_call_fatal_and_global_integrity_stop_rules(self) -> None:
        for category in execution.FIRST_CALL_FATAL_CATEGORIES:
            terminal = {"terminal_status": "PROVIDER_ERROR", "provider_error": {"category": category}}
            self.assertIsNotNone(execution.stop_reason_for_terminal(1, terminal))
        terminal = {"terminal_status": "PROVIDER_ERROR", "provider_error": {"category": "RATE_LIMIT_ERROR"}}
        self.assertIsNone(execution.stop_reason_for_terminal(1, terminal))
        terminal = {"terminal_status": "RETURNED_MODEL_MISMATCH", "provider_error": {"category": "MODEL_OR_ENDPOINT_NOT_FOUND"}}
        self.assertIsNotNone(execution.stop_reason_for_terminal(2, terminal))

    def test_16_one_attempt_records_all_required_success_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="memory_stage4l_attempt_") as temp:
            root = Path(temp)
            client = _FakeClient([_response('{"memory_required":true}')])
            with (
                mock.patch.object(execution, "ATTEMPT_RECORDS_PATH", root / "attempts.jsonl"),
                mock.patch.object(execution, "CALL_JOURNAL_PATH", root / "journal.jsonl"),
            ):
                attempt, outcome = execution._one_physical_attempt(
                    client,
                    self.v2[0],
                    1,
                    1,
                    execution.InitialRequestPacer(),
                )
            self.assertEqual("VALID_PREDICTION", outcome)
            self.assertEqual({"memory_required": True}, attempt["parsed_json"])
            self.assertTrue(attempt["schema_validation"]["valid"])
            self.assertEqual(100, attempt["input_tokens"])
            self.assertEqual(5, attempt["output_tokens"])
            self.assertEqual(105, attempt["total_tokens"])
            self.assertEqual(common.AUTHORIZED_MODEL_SNAPSHOT, attempt["returned_model"])
            self.assertEqual(2, len(common.load_jsonl(root / "journal.jsonl")))

    def test_17_invalid_attempt_is_not_silently_repaired(self) -> None:
        with tempfile.TemporaryDirectory(prefix="memory_stage4l_invalid_") as temp:
            root = Path(temp)
            invalid = _response('{"memory_required":"true"}')
            client = _FakeClient([invalid])
            with (
                mock.patch.object(execution, "ATTEMPT_RECORDS_PATH", root / "attempts.jsonl"),
                mock.patch.object(execution, "CALL_JOURNAL_PATH", root / "journal.jsonl"),
            ):
                attempt, outcome = execution._one_physical_attempt(
                    client,
                    self.v2[0],
                    1,
                    1,
                    execution.InitialRequestPacer(),
                )
            self.assertEqual("INVALID_STRUCTURED_OUTPUT", outcome)
            self.assertEqual({"memory_required": "true"}, attempt["parsed_json"])
            self.assertFalse(attempt["schema_validation"]["valid"])
            self.assertEqual("STRICT_SCHEMA_VALIDATION_FAILED", attempt["schema_validation"]["error"])

    def test_18_no_credentials_or_prohibited_partition_ids_in_inputs(self) -> None:
        for record in self.v2:
            payload = json.dumps(record["provider_facing_request"], ensure_ascii=False)
            self.assertNotRegex(payload, r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
            self.assertNotIn("R2V2-" + "TEST", payload.upper())
            self.assertNotIn("TEST_" + "ESCROW", payload.upper())
            self.assertNotIn("TEST", str(record["annotation_case_id"]).upper())

    def test_19_pre_execution_source_verification_is_recorded(self) -> None:
        report = common.load_json(common.SOURCE_VERIFICATION_PATH)
        self.assertIn(
            report["status"],
            {
                "PASS_PRE_EXECUTION_POST_EXECUTION_PENDING",
                "PASS_PRE_AND_POST_EXECUTION_BYTES_UNCHANGED",
            },
        )
        self.assertEqual("PASS", report["pre_execution"]["status"])

    def test_20_cost_arithmetic_uses_stated_reference_rates(self) -> None:
        attempts = [
            {
                "physical_attempt_id": "fixture",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "total_tokens": 2_000_000,
            }
        ]
        report = finalizer._usage_report(attempts)
        self.assertEqual("0.15000000", report["approximate_cost_usd"]["input"])
        self.assertEqual("0.60000000", report["approximate_cost_usd"]["output"])
        self.assertEqual("0.75000000", report["approximate_cost_usd"]["total"])
        self.assertEqual(Decimal("0.15"), finalizer.INPUT_PRICE_PER_MILLION)

    def test_21_binary_metric_arithmetic_is_exact(self) -> None:
        gold = {
            "a": {"final_memory_required": "YES"},
            "b": {"final_memory_required": "YES"},
            "c": {"final_memory_required": "NO"},
            "d": {"final_memory_required": "NO"},
        }
        metrics = finalizer._binary_metrics(
            ["a", "b", "c", "d"], gold, {"a": True, "b": False, "c": True, "d": False}
        )
        self.assertEqual({"tp": 1, "fp": 1, "tn": 1, "fn": 1}, metrics["confusion_matrix"])
        self.assertEqual(0.5, metrics["accuracy"])
        self.assertEqual(0.5, metrics["precision"])
        self.assertEqual(0.5, metrics["recall"])
        self.assertEqual(0.5, metrics["f1"])
        self.assertEqual(0.5, metrics["specificity"])

    def test_22_family_metrics_report_correctness_and_consistency_separately(self) -> None:
        gold = {
            "a": {"scenario_family_id": "f1", "final_memory_required": "YES"},
            "b": {"scenario_family_id": "f1", "final_memory_required": "YES"},
            "c": {"scenario_family_id": "f2", "final_memory_required": "NO"},
            "d": {"scenario_family_id": "f2", "final_memory_required": "NO"},
        }
        metrics = finalizer._family_metrics(
            gold, {"a": True, "b": True, "c": True, "d": True}
        )
        self.assertEqual(1, metrics["family_both_utterances_correct_count"])
        self.assertEqual(2, metrics["family_prediction_consistent_count"])

    def test_23_memory_contrast_metrics_match_perfect_gold_pattern(self) -> None:
        with (common.DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            gold_rows = [
                row for row in csv.DictReader(handle) if row["final_dialogue_action"] == "ANSWER"
            ]
        gold = {row["annotation_case_id"]: row for row in gold_rows}
        predictions = {
            case_id: row["final_memory_required"] == "YES" for case_id, row in gold.items()
        }
        metrics = finalizer._memory_contrast_metrics(gold, predictions)
        self.assertEqual(3, metrics["total_memory_contrast_groups"])
        self.assertEqual(3, metrics["memory_contrast_consistent_count"])
        self.assertEqual(3, metrics["memory_gold_pattern_contrast_match_count"])

    def test_24_only_memory_specialist_provider_surface_is_called(self) -> None:
        source = Path(execution.__file__).read_text(encoding="utf-8")
        self.assertEqual(1, source.count("client.chat.completions.create"))
        self.assertNotIn("rag_specialist_dev_execution_manifest", source)
        self.assertNotIn("track_i_b4", source)
        self.assertNotIn("p1_protocol", source)
        self.assertNotIn("rq3", source.lower())

    def test_25_all_new_paths_are_confined_to_track_l(self) -> None:
        for path in (
            common.V2_MANIFEST_PATH,
            common.MANIFEST_DIFF_PATH,
            common.SOURCE_VERIFICATION_PATH,
            *common.DYNAMIC_OUTPUT_PATHS,
        ):
            self.assertTrue(path.is_relative_to(common.TRACK_DIR), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
