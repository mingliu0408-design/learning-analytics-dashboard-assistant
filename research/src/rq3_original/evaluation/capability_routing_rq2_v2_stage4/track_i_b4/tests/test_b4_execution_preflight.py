from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest


TRACK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK_DIR))

import build_b4_preparation as preparation  # noqa: E402
import execute_b4_dev as execution  # noqa: E402


class B4ExecutionPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = execution.load_jsonl(execution.V1_MANIFEST_PATH)
        cls.v2 = execution.load_jsonl(execution.V2_MANIFEST_PATH)
        cls.diff = json.loads(execution.MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
        cls.fold_hashes = json.loads(
            (TRACK_DIR / "b4_fold_prompt_hashes_v1.json").read_text(encoding="utf-8")
        )

    def test_01_v1_v2_exact_allowed_difference_boundary(self) -> None:
        validation = execution.validate_manifest_pair(self.v1, self.v2)
        self.assertEqual(
            sorted(execution.ALLOWED_V1_V2_DIFF_PATHS),
            validation["observed_difference_paths"],
        )
        self.assertTrue(validation["normalized_v2_equals_v1"])
        self.assertEqual(
            "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY", self.diff["status"]
        )
        self.assertEqual(execution.sha256_file(execution.V1_MANIFEST_PATH), self.diff["v1_manifest_sha256"])
        self.assertEqual(execution.sha256_file(execution.V2_MANIFEST_PATH), self.diff["v2_manifest_sha256"])

    def test_02_exact_64_logical_calls_and_deterministic_order(self) -> None:
        expected = [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)]
        self.assertEqual(64, len(self.v2))
        self.assertEqual(expected, [record["logical_call_id"] for record in self.v2])
        self.assertEqual(64, len({record["annotation_case_id"] for record in self.v2}))
        self.assertEqual({"NOT_EXECUTED"}, {record["execution_status"] for record in self.v2})

    def test_03_authorized_model_payload_and_no_extra_api_features(self) -> None:
        for record in self.v2:
            payload = record["provider_request_payload"]
            self.assertEqual(execution.AUTHORIZED_MODEL_SNAPSHOT, payload["model"])
            self.assertEqual(0, payload["temperature"])
            self.assertEqual(64, payload["max_tokens"])
            self.assertEqual(
                {"model", "messages", "temperature", "response_format", "max_tokens"},
                set(payload),
            )
            self.assertEqual("json_schema", payload["response_format"]["type"])
            self.assertIs(True, payload["response_format"]["json_schema"]["strict"])
            self.assertNotIn("stream", payload)
            self.assertNotIn("tools", payload)
            self.assertNotIn("web_search_options", payload)

    def test_04_prompt_schema_examples_and_validation_inputs_unchanged(self) -> None:
        self.assertEqual(
            execution.EXPECTED_PROMPT_SHA256,
            execution.sha256_file(TRACK_DIR / "b4_prompt_template_frozen_v1.txt"),
        )
        self.assertEqual(
            execution.EXPECTED_SCHEMA_SHA256,
            execution.sha256_file(TRACK_DIR / "b4_response_schema_v1.json"),
        )
        for v1, v2 in zip(self.v1, self.v2, strict=True):
            self.assertEqual(v1["prompt_template_sha256"], v2["prompt_template_sha256"])
            self.assertEqual(v1["strict_response_schema_sha256"], v2["strict_response_schema_sha256"])
            self.assertEqual(v1["fold_specific_example_ids"], v2["fold_specific_example_ids"])
            self.assertEqual(v1["fold_specific_example_set_sha256"], v2["fold_specific_example_set_sha256"])
            self.assertEqual(v1["validation_input"], v2["validation_input"])
            self.assertEqual(v1["provider_request_payload"]["messages"], v2["provider_request_payload"]["messages"])
            self.assertEqual(v1["provider_request_payload"]["response_format"], v2["provider_request_payload"]["response_format"])
        self.assertEqual({8}, {entry["example_count"] for entry in self.fold_hashes["folds"].values()})

    def test_05_client_has_zero_sdk_retries(self) -> None:
        self.assertEqual(0, execution.CLIENT_MAX_RETRIES)
        tree = ast.parse((TRACK_DIR / "execute_b4_dev.py").read_text(encoding="utf-8"))
        matching_calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "OpenAI":
                matching_calls.append(node)
        self.assertEqual(1, len(matching_calls))
        keywords = {keyword.arg: keyword.value for keyword in matching_calls[0].keywords}
        self.assertIn("max_retries", keywords)
        self.assertIsInstance(keywords["max_retries"], ast.Name)
        self.assertEqual("CLIENT_MAX_RETRIES", keywords["max_retries"].id)

    def test_06_strict_parser_rejects_invalid_output_without_repair(self) -> None:
        valid = '{"rag_required":true,"memory_required":false,"planning_required":true}'
        self.assertEqual(
            {
                "rag_required": True,
                "memory_required": False,
                "planning_required": True,
            },
            preparation.parse_strict_response(valid),
        )
        invalid = (
            'prefix ' + valid,
            '{"rag_required":"true","memory_required":false,"planning_required":true}',
            '{"rag_required":true,"memory_required":false}',
            '{"rag_required":true,"memory_required":false,"planning_required":true,"extra":false}',
            '{not json}',
        )
        for content in invalid:
            with self.subTest(content=content), self.assertRaises(ValueError):
                preparation.parse_strict_response(content)
        parsed, accepted, error = execution._validate_response_content("prefix " + valid)
        self.assertIsNone(parsed)
        self.assertFalse(accepted)
        self.assertEqual("INVALID_JSON", error)

    def test_07_retry_contract_is_invalid_output_only(self) -> None:
        for record in self.v2:
            controls = record["execution_controls"]
            self.assertEqual(0, controls["sdk_transport_retries"])
            self.assertEqual(1, controls["invalid_structured_output_retries_max"])
            self.assertIs(False, controls["silent_repair_allowed"])
        source = (TRACK_DIR / "execute_b4_dev.py").read_text(encoding="utf-8")
        self.assertIn(
            'outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1',
            source,
        )
        self.assertNotIn("correction message", source.lower())

    def test_08_zero_test_identifiers_and_dev_only_case_ids(self) -> None:
        case_ids = {record["annotation_case_id"] for record in self.v2}
        self.assertFalse(any("TEST" in case_id.upper() for case_id in case_ids))
        self.assertTrue(all(case_id.startswith("R2V2-ANN-") for case_id in case_ids))
        for record in self.v2:
            payload_text = json.dumps(record["provider_request_payload"], ensure_ascii=False)
            self.assertNotIn("R2V2-TEST", payload_text.upper())
            self.assertNotIn("partition", payload_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
