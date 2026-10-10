"""Zero-provider integrity tests for the fresh compatible-runtime V2 execution."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import unittest
from unittest import mock
from zipfile import ZipFile


EXECUTION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_V1 = EXECUTION_ROOT / "execution_output_v1"
OUTPUT_V2 = EXECUTION_ROOT / "execution_output_v2"
PACKAGE = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_P3_RAG_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip"
)
EXPECTED_EXECUTABLE = Path("/opt/anaconda3/bin/python3")
MODEL = "gpt-4o-mini-2024-07-18"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
PACKAGE_SHA256 = "76636bfa936d1f8545723c1460ccf1adb15ac3d4e7dc19ab8b056cbc7063a1b5"
REQUESTS_SHA256 = "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326"
AUTHORIZATION_V2_SHA256 = "8d971782726bd48930da90158d47e7799e36de3f59cdd0aea222955b3b9cffda"
HISTORICAL_STATUS_SHA256 = "9ba9064ab18fd6973deb1266a3a0323056d67ce1da94cfc4182ba8d3682dac6c"
HISTORICAL_STATUS_LENGTH = 750
ALLOWLIST = [
    "EXECUTION_CONTRACT.json",
    "EXECUTION_PLAN.json",
    "PACKAGE_MANIFEST.json",
    "README.md",
    "execute_route_package_v2.py",
    "few_shot_examples.json",
    "prompt.txt",
    "requests.jsonl",
    "schema.json",
    "validate_route_package_v1.py",
]
MEMBER_SHA256 = {
    "EXECUTION_CONTRACT.json": "e0550acb93922d21797b1210f0846ce060df342cf08144a7d25ef78eae1972b1",
    "EXECUTION_PLAN.json": "f3d864d377aa283b952c188e9cbf4a9ff1bea77b7f1c5400aa3e0364f43ca055",
    "PACKAGE_MANIFEST.json": "bd01dff151fc2eda698a6a411994a5b700bd6586cfa64d6ca4fb0d60b2b8f375",
    "README.md": "a07c02ec7cbe89942ae411c92d030052d383ac439bca4586056f57488b1d18b2",
    "execute_route_package_v2.py": "3c09ee70b92609f5ea6b21490b198170e198a8af1db721ef1d9b1c7720a85ae2",
    "few_shot_examples.json": "39c5bfcfba2f4b91e61bdc05af358798ba72cb32741f699801fd6f4985250fb5",
    "prompt.txt": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
    "requests.jsonl": REQUESTS_SHA256,
    "schema.json": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
    "validate_route_package_v1.py": "0ffb88d64f778de61fedd9db269e7c5aa0ae7db40cbc9e2016eb1f308c42f7d2",
}
V1_IMMUTABLE_SHA256 = {
    "RAG_ROUTE_EXECUTION_REPORT.md": "a914f5d7ce02888eb0eba1e0217e8a076c6833b599663cd2b95d4239fb5cdc31",
    "execution_output_v1/route_attempt_records_v1.jsonl": EMPTY_SHA256,
    "execution_output_v1/route_error_registry_v1.jsonl": EMPTY_SHA256,
    "execution_output_v1/route_execution_preflight_receipt_v1.json": "f7355581eb77e5abfd0f747eacbc13ddd249bb71633bfe01dff24b29b745d8f2",
    "execution_output_v1/route_execution_status_v1.json": "b2c64be0182c9e3ac0a805fd8ecd9ab24901afbe16c1344362d7905e6ec77b18",
    "execution_output_v1/route_terminal_results_v1.jsonl": EMPTY_SHA256,
    "rag_route_execution_audit_v1.json": "0fec683afddc82469c92b734fc4cf364a4683c1a26bbff6460f37c63109da331",
    "rag_route_execution_source_manifest_v1.json": "491ba30a976a2cfb325d4172869ef77f03ba7ec394417ab5ecea9547193f2386",
    "route_execution_authorization_v1.json": "4378ead57eadbee0177e5e65a5e4c4baf56647a646a94a63b7c8b6e7b18f11a7",
}
AUTHORIZATION_FIELDS = {
    "authorization_id",
    "authorization_scope",
    "authorized_by",
    "authorized_at",
    "package_id",
    "component",
    "logical_call_count",
    "maximum_physical_attempt_count",
    "status",
}
RETRYABLE = {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError(f"Expected JSON object: {path}:{number}")
        rows.append(value)
    return rows


def recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for item in value.values():
            keys.update(recursive_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(recursive_keys(item))
        return keys
    return set()


class FreshCompatibleRuntimeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = load_json(EXECUTION_ROOT / "runtime_compatibility_preflight_v2.json")
        cls.authorization = load_json(EXECUTION_ROOT / "route_execution_authorization_v2.json")
        cls.audit = load_json(EXECUTION_ROOT / "rag_route_execution_audit_v2.json")
        cls.source_manifest = load_json(
            EXECUTION_ROOT / "rag_route_execution_source_manifest_v2.json"
        )
        cls.history = load_json(
            EXECUTION_ROOT / "historical_v1_identity_manifest_v2.json"
        )
        cls.preflight = load_json(OUTPUT_V2 / "route_execution_preflight_receipt_v1.json")
        cls.status = load_json(OUTPUT_V2 / "route_execution_status_v1.json")
        cls.usage = load_json(OUTPUT_V2 / "route_usage_and_cost_v1.json")
        cls.attempts = load_jsonl(OUTPUT_V2 / "route_attempt_records_v1.jsonl")
        cls.terminals = load_jsonl(OUTPUT_V2 / "route_terminal_results_v1.jsonl")
        cls.errors = load_jsonl(OUTPUT_V2 / "route_error_registry_v1.jsonl")
        with ZipFile(PACKAGE) as archive:
            cls.requests_bytes = archive.read("requests.jsonl")
            cls.requests = [
                json.loads(line)
                for line in cls.requests_bytes.decode("utf-8").splitlines()
                if line.strip()
            ]

    def test_01_historical_v1_hashes_and_status_content_unchanged(self) -> None:
        for relative, expected in V1_IMMUTABLE_SHA256.items():
            self.assertEqual(sha256((EXECUTION_ROOT / relative).read_bytes()), expected)
        status_bytes = (EXECUTION_ROOT / "STATUS.md").read_bytes()
        self.assertGreater(len(status_bytes), HISTORICAL_STATUS_LENGTH)
        self.assertEqual(sha256(status_bytes[:HISTORICAL_STATUS_LENGTH]), HISTORICAL_STATUS_SHA256)
        self.assertEqual(self.history["status"], "PASS_HISTORICAL_V1_PRESERVED")
        self.assertTrue(self.history["historical_status_content"]["historical_content_byte_identical"])

    def test_02_package_hash_crc_allowlist_and_member_hashes_unchanged(self) -> None:
        self.assertEqual(sha256(PACKAGE.read_bytes()), PACKAGE_SHA256)
        with ZipFile(PACKAGE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ALLOWLIST)
            observed = {name: sha256(archive.read(name)) for name in archive.namelist()}
        self.assertEqual(observed, MEMBER_SHA256)

    def test_03_exact_compatible_python_executable(self) -> None:
        self.assertTrue(Path(sys.executable).samefile(EXPECTED_EXECUTABLE))
        self.assertEqual(self.runtime["executable_path"], str(EXPECTED_EXECUTABLE))

    def test_04_exact_python_version(self) -> None:
        observed = ".".join(str(value) for value in sys.version_info[:3])
        self.assertEqual(observed, "3.13.5")
        self.assertEqual(self.runtime["python_version"], "3.13.5")

    def test_05_exact_openai_sdk_version(self) -> None:
        import openai

        self.assertEqual(openai.__version__, "1.109.1")
        self.assertEqual(self.runtime["openai_sdk_version"], "1.109.1")

    def test_06_modern_client_constructs_and_closes_with_network_blocked(self) -> None:
        from openai import OpenAI

        network_attempts = 0

        def blocked(*args: object, **kwargs: object) -> None:
            nonlocal network_attempts
            network_attempts += 1
            raise AssertionError("Network access is forbidden in offline tests")

        with mock.patch.object(socket.socket, "connect", blocked), mock.patch.object(
            socket, "create_connection", blocked
        ):
            client = OpenAI(
                api_key="offline-test-placeholder-not-a-credential",
                max_retries=0,
            )
            client.close()
        self.assertEqual(network_attempts, 0)

    def test_07_runtime_preflight_records_zero_provider_calls(self) -> None:
        self.assertEqual(self.runtime["provider_calls"], 0)
        self.assertTrue(self.runtime["api_key_present_not_recorded"])
        self.assertEqual(self.runtime["modern_client_import_status"], "PASS")
        self.assertEqual(self.runtime["client_construction_status"], "PASS_CLOSED_CLEANLY")
        self.assertEqual(self.runtime["status"], "PASS_COMPATIBLE_RUNTIME_ZERO_NETWORK")

    def test_08_authorization_v2_has_only_strict_fields(self) -> None:
        path = EXECUTION_ROOT / "route_execution_authorization_v2.json"
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(sha256(path.read_bytes()), AUTHORIZATION_V2_SHA256)
        self.assertEqual(self.authorization["authorization_id"], "RQ3-REAL-R1A-R1-RAG-ROUTE-20260901")
        self.assertEqual(self.authorization["authorization_scope"], "RQ3_REAL_C4_P3_ROUTE_EXECUTION_R1")
        self.assertEqual(self.authorization["component"], "RAG")
        self.assertEqual(self.authorization["logical_call_count"], 62)
        self.assertEqual(self.authorization["maximum_physical_attempt_count"], 124)
        self.assertEqual(self.authorization["status"], "AUTHORIZED")
        self.assertEqual(self.preflight["authorization_record_sha256"], AUTHORIZATION_V2_SHA256)

    def test_09_v2_output_is_exclusive_and_distinct_from_v1(self) -> None:
        self.assertNotEqual(OUTPUT_V1.resolve(), OUTPUT_V2.resolve())
        self.assertEqual(Path(self.preflight["output_directory"]).resolve(), OUTPUT_V2.resolve())
        self.assertTrue(self.preflight["output_directory_exclusive_creation"])
        self.assertEqual(load_json(OUTPUT_V1 / "route_execution_status_v1.json")["state"], "INCOMPLETE_STOPPED")
        self.assertEqual(self.status["state"], "COMPLETED")
        self.assertEqual(sha256((OUTPUT_V1 / "route_terminal_results_v1.jsonl").read_bytes()), EMPTY_SHA256)
        self.assertNotEqual(sha256((OUTPUT_V2 / "route_terminal_results_v1.jsonl").read_bytes()), EMPTY_SHA256)

    def test_10_exact_62_request_population_and_order(self) -> None:
        frozen_manifest = (
            REPO_ROOT
            / "evaluation/rq3_real_c4/i0_integration/c4_real_p3_route_input_manifest_v1.jsonl"
        ).read_bytes()
        self.assertEqual(sha256(self.requests_bytes), REQUESTS_SHA256)
        self.assertEqual(self.requests_bytes, frozen_manifest)
        self.assertEqual(len(self.requests), 62)
        self.assertEqual(len({row["scenario_id"] for row in self.requests}), 62)
        self.assertEqual(len({row["semantic_input_sha256"] for row in self.requests}), 60)

    def test_11_all_v2_outputs_are_exactly_one_boolean(self) -> None:
        self.assertEqual(len(self.terminals), 62)
        for row in self.terminals:
            self.assertEqual(row["event"], "TERMINAL_SUCCESS")
            self.assertEqual(set(row["output"]), {"rag_required"})
            self.assertIs(type(row["output"]["rag_required"]), bool)

    def test_12_terminal_scenario_ids_are_complete_and_unique(self) -> None:
        expected_ids = [row["scenario_id"] for row in self.requests]
        observed_ids = [row["scenario_id"] for row in self.terminals]
        self.assertEqual(observed_ids, expected_ids)
        self.assertEqual(len(set(observed_ids)), 62)
        self.assertEqual(self.status["logical_completed"], 62)
        self.assertEqual(self.status["logical_failed"], 0)

    def test_13_all_returned_models_match_exact_identity(self) -> None:
        self.assertEqual({row["returned_model"] for row in self.terminals}, {MODEL})
        self.assertTrue(self.audit["new_v2"]["model_audit"]["all_returned_models_exact"])

    def test_14_retry_policy_and_payload_identity(self) -> None:
        completed = [row for row in self.attempts if row.get("event") == "ATTEMPT_COMPLETED"]
        by_attempt = {
            (row["scenario_id"], row["attempt_number"]): row for row in completed
        }
        retry_rows = [row for row in completed if row["attempt_number"] == 2]
        for retry in retry_rows:
            first = by_attempt[(retry["scenario_id"], 1)]
            self.assertIn(first["outcome"], RETRYABLE)
            self.assertEqual(retry["provider_payload_sha256"], first["provider_payload_sha256"])
        self.assertEqual(retry_rows, [])
        self.assertEqual(self.status["retry_count"], 0)

    def test_15_physical_attempt_count_and_ceiling(self) -> None:
        reserved = [row for row in self.attempts if row.get("event") == "ATTEMPT_RESERVED"]
        completed = [row for row in self.attempts if row.get("event") == "ATTEMPT_COMPLETED"]
        self.assertEqual(len(reserved), 62)
        self.assertEqual(len(completed), 62)
        self.assertEqual(self.status["physical_attempts"], 62)
        self.assertEqual(self.status["provider_calls"], 62)
        self.assertLessEqual(self.status["physical_attempts"], 124)
        self.assertEqual(Counter(row["outcome"] for row in completed), {"VALID": 62})

    def test_16_duplicate_semantic_inputs_have_identical_outputs(self) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for row in self.requests:
            groups[row["semantic_input_sha256"]].append(row["scenario_id"])
        repeated = {key: ids for key, ids in groups.items() if len(ids) > 1}
        self.assertEqual(
            repeated,
            {
                "df61c962d9637495a56badc89f86ced0dc5bcd42f8f7c3a223f0c427299677c9": [
                    "U022",
                    "U026",
                    "U031",
                ]
            },
        )
        output_by_id = {row["scenario_id"]: row["output"]["rag_required"] for row in self.terminals}
        self.assertEqual({output_by_id[scenario_id] for scenario_id in repeated.popitem()[1]}, {False})
        self.assertTrue(
            self.audit["new_v2"]["duplicate_semantic_input_audit"]
            ["all_byte_identical_inputs_produced_identical_rag_required"]
        )

    def test_17_token_and_cost_arithmetic(self) -> None:
        completed = [row for row in self.attempts if row.get("event") == "ATTEMPT_COMPLETED"]
        input_tokens = sum(row["input_tokens"] for row in completed)
        cached_tokens = sum(row["cached_input_tokens"] for row in completed)
        output_tokens = sum(row["output_tokens"] for row in completed)
        total_tokens = sum(row["total_tokens"] for row in completed)
        self.assertEqual((input_tokens, cached_tokens, output_tokens, total_tokens), (95275, 68992, 372, 95647))
        self.assertEqual(total_tokens, input_tokens + output_tokens)
        regular_input = input_tokens - cached_tokens
        cost = (
            Decimal(regular_input) * Decimal("0.15")
            + Decimal(cached_tokens) * Decimal("0.075")
            + Decimal(output_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)
        self.assertEqual(format(cost.quantize(Decimal("0.00000001")), "f"), "0.00934005")
        self.assertEqual(self.usage["approximate_cost_usd"], "0.00934005")

    def test_18_no_credentials_in_package_or_execution_artifacts(self) -> None:
        secret_patterns = [
            re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", re.IGNORECASE),
            re.compile(rb"Bearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE),
        ]
        blobs = [path.read_bytes() for path in EXECUTION_ROOT.rglob("*") if path.is_file()]
        with ZipFile(PACKAGE) as archive:
            blobs.extend(archive.read(name) for name in archive.namelist())
        for blob in blobs:
            self.assertFalse(any(pattern.search(blob) for pattern in secret_patterns))
        self.assertTrue(self.preflight["api_key_present_not_recorded"])

    def test_19_no_gold_or_expected_labels_in_scientific_results(self) -> None:
        with ZipFile(PACKAGE) as archive:
            package_manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        self.assertFalse(package_manifest["contains_gold"])
        result_keys = recursive_keys(self.attempts + self.terminals + self.errors)
        self.assertTrue({"gold", "expected_label", "expected_labels"}.isdisjoint(result_keys))
        self.assertFalse(self.audit["scope_boundaries"]["gold_accessed"])
        self.assertFalse(self.status["expected_labels_accessed"])

    def test_20_no_route_scoring_fields_or_calculation(self) -> None:
        result_keys = recursive_keys(self.terminals)
        scoring_keys = {"accuracy", "precision", "recall", "f1", "score", "route_score"}
        self.assertTrue(scoring_keys.isdisjoint(result_keys))
        self.assertFalse(self.status["routing_accuracy_calculated"])
        self.assertFalse(self.usage["routing_accuracy_calculated"])
        self.assertFalse(
            self.audit["scope_boundaries"]
            ["routing_accuracy_or_expected_label_comparison_performed"]
        )

    def test_21_i1_rag_input_compatibility_uses_v2_only(self) -> None:
        expected = {row["scenario_id"]: row for row in self.requests}
        v2 = {row["scenario_id"]: row for row in self.terminals if row["event"] == "TERMINAL_SUCCESS"}
        self.assertEqual(set(v2), set(expected))
        for scenario_id, terminal in v2.items():
            self.assertEqual(
                terminal["semantic_input_sha256"],
                expected[scenario_id]["semantic_input_sha256"],
            )
            self.assertEqual(set(terminal["output"]), {"rag_required"})
        self.assertEqual(load_jsonl(OUTPUT_V1 / "route_terminal_results_v1.jsonl"), [])
        compatibility = self.audit["new_v2"]["i1_merger_compatibility"]
        self.assertTrue(compatibility["ready_as_rag_input_for_i1_merger"])
        self.assertFalse(compatibility["merger_invoked"])
        self.assertEqual(self.audit["new_v2"]["scientific_result_source"], "execution_output_v2_ONLY")


if __name__ == "__main__":
    unittest.main()
