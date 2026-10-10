from __future__ import annotations

import json
import os
import unittest

from ..execute_rag_specialist_dev import create_client
from ..finalize_rag_specialist_dev import usage_report
from ..rag_specialist_protocol import (
    ALLOWED_V1_V2_DIFF_PATHS,
    AUTHORIZED_MODEL_SNAPSHOT,
    AUTHORIZED_STATUS,
    CLIENT_MAX_RETRIES,
    EXPECTED_PROMPT_SHA256,
    EXPECTED_SCHEMA_SHA256,
    LOGICAL_CALL_CEILING,
    MAX_OUTPUT_TOKENS,
    PRE_EXECUTION_VERIFICATION_PATH,
    SEMANTIC_TOP_LEVEL_FIELDS,
    V1_MANIFEST_PATH,
    V2_MANIFEST_PATH,
    canonical_sha256,
    load_jsonl,
    parse_strict_rag_response,
    sanitize_provider_text,
    should_retry,
    validate_manifest_pair,
    verify_required_protocol,
    verify_worktree_boundary,
)


class RagSpecialistPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_jsonl(V1_MANIFEST_PATH)
        cls.v2 = load_jsonl(V2_MANIFEST_PATH)

    def test_01_worktree_boundary(self) -> None:
        result = verify_worktree_boundary()
        self.assertEqual(result["out_of_scope_changes"], 0)

    def test_02_all_stage4_k0_source_hashes_unchanged(self) -> None:
        protocol = verify_required_protocol()
        self.assertEqual(len(protocol["k0_source_hashes"]), 36)
        self.assertEqual(len(protocol["external_dev_source_hashes"]), 8)

    def test_03_frozen_prompt_schema_and_population(self) -> None:
        protocol = verify_required_protocol()
        self.assertEqual(protocol["prompt_sha256"], EXPECTED_PROMPT_SHA256)
        self.assertEqual(protocol["schema_sha256"], EXPECTED_SCHEMA_SHA256)
        self.assertEqual(protocol["logical_call_count"], 64)
        self.assertEqual(protocol["rag_gold_yes_count"], 32)
        self.assertEqual(protocol["rag_gold_no_count"], 32)

    def test_04_fold_and_full_dev_example_identity_and_order(self) -> None:
        protocol = verify_required_protocol()
        self.assertEqual(set(protocol["folds"]), {
            "DEV-CV-FOLD-1",
            "DEV-CV-FOLD-2",
            "DEV-CV-FOLD-3",
            "DEV-CV-FOLD-4",
        })
        for fold in protocol["folds"].values():
            self.assertEqual(len(fold["example_ids_in_order"]), 8)
        self.assertEqual(
            len(protocol["final_full_dev"]["example_ids_in_order"]), 8
        )

    def test_05_v1_v2_manifest_allowed_differences_only(self) -> None:
        result = validate_manifest_pair(self.v1, self.v2)
        self.assertTrue(result["normalized_v2_equals_v1"])
        self.assertTrue(result["semantic_request_identity_preserved"])
        self.assertEqual(
            set(result["observed_difference_paths"]), ALLOWED_V1_V2_DIFF_PATHS
        )

    def test_06_exactly_64_fixed_logical_records(self) -> None:
        expected = [
            f"R2V2-RAG-SPECIALIST-DEV-{index:04d}"
            for index in range(1, LOGICAL_CALL_CEILING + 1)
        ]
        self.assertEqual([record["logical_call_id"] for record in self.v2], expected)
        self.assertEqual(len({record["annotation_case_id"] for record in self.v2}), 64)

    def test_07_semantic_request_elements_preserved(self) -> None:
        for old, new in zip(self.v1, self.v2, strict=True):
            for field in SEMANTIC_TOP_LEVEL_FIELDS:
                self.assertEqual(old[field], new[field])
            self.assertEqual(
                old["provider_facing_request"]["messages"],
                new["provider_facing_request"]["messages"],
            )
            self.assertEqual(
                old["provider_facing_request"]["response_format"],
                new["provider_facing_request"]["response_format"],
            )

    def test_08_provider_configuration_is_exact_and_bounded(self) -> None:
        for record in self.v2:
            payload = record["provider_facing_request"]
            self.assertEqual(payload["model"], AUTHORIZED_MODEL_SNAPSHOT)
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["max_tokens"], MAX_OUTPUT_TOKENS)
            self.assertIs(payload["stream"], False)
            self.assertEqual(
                payload["response_format"]["json_schema"]["schema"],
                {
                    "type": "object",
                    "properties": {"rag_required": {"type": "boolean"}},
                    "required": ["rag_required"],
                    "additionalProperties": False,
                },
            )

    def test_09_v2_authorization_and_request_hashes(self) -> None:
        for record in self.v2:
            self.assertEqual(record["execution_authorization_status"], AUTHORIZED_STATUS)
            self.assertEqual(
                record["model_execution_authorization_status"], AUTHORIZED_STATUS
            )
            self.assertEqual(
                canonical_sha256(record["provider_facing_request"]),
                record["provider_facing_request_sha256"],
            )

    def test_10_strict_one_boolean_parser_accepts_only_boolean_object(self) -> None:
        self.assertEqual(parse_strict_rag_response('{"rag_required":true}'), {
            "rag_required": True
        })
        self.assertEqual(parse_strict_rag_response('{"rag_required":false}'), {
            "rag_required": False
        })

    def test_11_strict_parser_performs_no_silent_repair(self) -> None:
        invalid = [
            '{"rag_required":"true"}',
            '{"rag_required":1}',
            '{"rag_required":true,"explanation":"x"}',
            "answer: {\"rag_required\":true}",
            "{}",
            '{"rag_required":true,"rag_required":false}',
        ]
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    parse_strict_rag_response(content)

    def test_12_retry_only_after_first_invalid_structured_output(self) -> None:
        self.assertTrue(should_retry("INVALID_STRUCTURED_OUTPUT", 1))
        self.assertFalse(should_retry("INVALID_STRUCTURED_OUTPUT", 2))
        for outcome in (
            "PROVIDER_ERROR",
            "PROVIDER_REFUSAL",
            "RETURNED_MODEL_MISMATCH",
            "VALID_PREDICTION",
        ):
            self.assertFalse(should_retry(outcome, 1))

    def test_13_sanitized_error_handling(self) -> None:
        value = (
            "api_key="
            + "sk-"
            + "proj-"
            + "ExampleSecret123 "
            + "Bearer "
            + "token.secret.value"
        )
        sanitized = sanitize_provider_text(value)
        self.assertNotIn("ExampleSecret123", sanitized or "")
        self.assertNotIn("token.secret.value", sanitized or "")
        self.assertIn("REDACTED", sanitized or "")

    def test_14_no_test_identifiers_or_other_execution_population(self) -> None:
        text = "\n".join(json.dumps(record, sort_keys=True) for record in self.v2).upper()
        self.assertNotIn("R2V2-TEST", text)
        self.assertNotIn("TEST_ESCROW", text)
        self.assertNotIn("MEMORY-SPECIALIST", text)
        self.assertNotIn("R2V2-P1", text)
        self.assertNotIn("R2V2-P2", text)
        self.assertNotIn("R2V2-P3", text)
        self.assertNotIn("RQ3", text)

    def test_15_validation_gold_is_absent_from_provider_payloads(self) -> None:
        for record in self.v2:
            payload_text = json.dumps(record["provider_facing_request"], sort_keys=True)
            self.assertNotIn("final_rag_required", payload_text)
            self.assertNotIn("scenario_family_id", payload_text)
            self.assertIs(record["validation_gold_in_provider_request"], False)

    def test_16_pre_execution_hash_record_precedes_calls(self) -> None:
        record = json.loads(PRE_EXECUTION_VERIFICATION_PATH.read_text())
        self.assertEqual(record["status"], "PASS_PRE_EXECUTION_FROZEN_IDENTITIES")
        self.assertEqual(record["provider_calls_made_at_verification"], 0)

    def test_17_openai_client_has_zero_transport_retries(self) -> None:
        self.assertTrue(os.environ.get("OPENAI_API_KEY"))
        client = create_client()
        self.assertEqual(client.max_retries, CLIENT_MAX_RETRIES)
        client.close()

    def test_18_token_cost_arithmetic(self) -> None:
        report = usage_report([
            {"physical_attempt_id": "P1", "input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        ])
        self.assertEqual(report["actual_provider_usage"]["total_tokens"], 120)
        self.assertEqual(report["approximate_cost_usd"]["input"], "0.00001500")
        self.assertEqual(report["approximate_cost_usd"]["output"], "0.00001200")
        self.assertEqual(report["approximate_cost_usd"]["total"], "0.00002700")


if __name__ == "__main__":
    unittest.main()
