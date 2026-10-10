"""Zero-provider audit tests for the incomplete frozen RAG-route execution."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unittest
from zipfile import ZipFile


EXECUTION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_ROOT = EXECUTION_ROOT / "execution_output_v1"
PACKAGE = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_P3_RAG_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip"
)
PACKAGE_SHA256 = "76636bfa936d1f8545723c1460ccf1adb15ac3d4e7dc19ab8b056cbc7063a1b5"
AUTHORIZATION_SHA256 = "4378ead57eadbee0177e5e65a5e4c4baf56647a646a94a63b7c8b6e7b18f11a7"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
REQUESTS_SHA256 = "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326"
MODEL = "gpt-4o-mini-2024-07-18"
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
        return {str(key).lower() for key in value} | set().union(
            *(recursive_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value), set())
    return set()


class PreservedIncompleteExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.authorization = load_json(EXECUTION_ROOT / "route_execution_authorization_v1.json")
        cls.audit = load_json(EXECUTION_ROOT / "rag_route_execution_audit_v1.json")
        cls.source_manifest = load_json(
            EXECUTION_ROOT / "rag_route_execution_source_manifest_v1.json"
        )
        cls.status = load_json(OUTPUT_ROOT / "route_execution_status_v1.json")
        cls.preflight = load_json(
            OUTPUT_ROOT / "route_execution_preflight_receipt_v1.json"
        )
        cls.attempts = load_jsonl(OUTPUT_ROOT / "route_attempt_records_v1.jsonl")
        cls.terminals = load_jsonl(OUTPUT_ROOT / "route_terminal_results_v1.jsonl")
        cls.errors = load_jsonl(OUTPUT_ROOT / "route_error_registry_v1.jsonl")

    def test_01_package_hash_crc_and_ten_member_allowlist(self) -> None:
        self.assertEqual(sha256(PACKAGE.read_bytes()), PACKAGE_SHA256)
        with ZipFile(PACKAGE) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ALLOWLIST)
            self.assertEqual(len(archive.infolist()), 10)

    def test_02_package_member_hashes_and_no_pycache(self) -> None:
        with ZipFile(PACKAGE) as archive:
            observed = {name: sha256(archive.read(name)) for name in archive.namelist()}
            self.assertEqual(observed, MEMBER_SHA256)
            self.assertFalse(any("__pycache__" in name for name in archive.namelist()))
        self.assertEqual(self.source_manifest["fresh_extraction"]["pycache_directory_count"], 0)
        self.assertEqual(self.source_manifest["fresh_extraction"]["additional_file_count"], 0)
        self.assertFalse(any(EXECUTION_ROOT.rglob("__pycache__")))

    def test_03_strict_authorization_fields_values_and_hash(self) -> None:
        authorization_path = EXECUTION_ROOT / "route_execution_authorization_v1.json"
        self.assertEqual(set(self.authorization), AUTHORIZATION_FIELDS)
        self.assertEqual(sha256(authorization_path.read_bytes()), AUTHORIZATION_SHA256)
        self.assertEqual(self.authorization["authorization_scope"], "RQ3_REAL_C4_P3_ROUTE_EXECUTION_R1")
        self.assertEqual(self.authorization["package_id"], "C4_REAL_P3_RAG_ROUTE_EXECUTION_R1")
        self.assertEqual(self.authorization["component"], "RAG")
        self.assertEqual(self.authorization["logical_call_count"], 62)
        self.assertEqual(self.authorization["maximum_physical_attempt_count"], 124)
        self.assertEqual(self.authorization["status"], "AUTHORIZED")
        self.assertEqual(self.preflight["authorization_record_sha256"], AUTHORIZATION_SHA256)

    def test_04_exact_62_scenario_request_set_and_order(self) -> None:
        frozen_manifest_path = (
            REPO_ROOT
            / "evaluation/rq3_real_c4/i0_integration/c4_real_p3_route_input_manifest_v1.jsonl"
        )
        with ZipFile(PACKAGE) as archive:
            requests_bytes = archive.read("requests.jsonl")
        self.assertEqual(sha256(requests_bytes), REQUESTS_SHA256)
        self.assertEqual(requests_bytes, frozen_manifest_path.read_bytes())
        requests = [json.loads(line) for line in requests_bytes.decode("utf-8").splitlines()]
        self.assertEqual(len(requests), 62)
        self.assertEqual(len({row["scenario_id"] for row in requests}), 62)
        self.assertEqual(len({row["semantic_input_sha256"] for row in requests}), 60)
        self.assertTrue(all(row["status"] == "READY_FOR_P3_ROUTE_EXECUTION" for row in requests))
        self.assertTrue(
            all(
                set(row["semantic_input"])
                == {
                    "current_query",
                    "current_page",
                    "dashboard_context",
                    "visible_conversation_history",
                }
                for row in requests
            )
        )

    def test_05_one_terminal_result_per_completed_request(self) -> None:
        successes = [row for row in self.terminals if row.get("event") == "TERMINAL_SUCCESS"]
        self.assertEqual(self.status["state"], "INCOMPLETE_STOPPED")
        self.assertEqual(self.status["logical_completed"], 0)
        self.assertEqual(len(successes), self.status["logical_completed"])
        self.assertEqual(len({row["scenario_id"] for row in successes}), len(successes))
        self.assertEqual(len(self.terminals), 0)

    def test_06_strict_one_boolean_output_shape(self) -> None:
        successes = [row for row in self.terminals if row.get("event") == "TERMINAL_SUCCESS"]
        for row in successes:
            self.assertEqual(set(row["output"]), {"rag_required"})
            self.assertIs(type(row["output"]["rag_required"]), bool)
        self.assertEqual(successes, [])
        self.assertEqual(self.audit["prediction_counts"]["status"], "NO_VALID_OUTPUTS")

    def test_07_returned_model_identity_is_fail_closed_when_absent(self) -> None:
        for row in self.terminals:
            if row.get("event") == "TERMINAL_SUCCESS":
                self.assertEqual(row.get("returned_model"), MODEL)
        self.assertIsNone(self.audit["model_audit"]["returned_model"])
        self.assertEqual(
            self.audit["model_audit"]["returned_model_identity_status"],
            "NOT_EVALUABLE_NO_PROVIDER_RESPONSE",
        )

    def test_08_retry_policy_and_payload_identity(self) -> None:
        completed = [row for row in self.attempts if row.get("event") == "ATTEMPT_COMPLETED"]
        by_request_attempt = {
            (row.get("scenario_id"), row.get("attempt_number")): row for row in completed
        }
        for row in completed:
            if row.get("attempt_number") != 2:
                continue
            first = by_request_attempt[(row.get("scenario_id"), 1)]
            self.assertIn(first.get("outcome"), RETRYABLE)
            self.assertEqual(row.get("provider_payload_sha256"), first.get("provider_payload_sha256"))
        self.assertEqual(self.status["retry_count"], 0)
        self.assertEqual(completed, [])

    def test_09_physical_attempt_ceiling_and_counts(self) -> None:
        reservations = [row for row in self.attempts if row.get("event") == "ATTEMPT_RESERVED"]
        self.assertEqual(self.status["physical_attempts"], len(reservations))
        self.assertEqual(self.status["physical_attempts"], 0)
        self.assertLessEqual(self.status["physical_attempts"], 124)
        self.assertEqual(self.status["provider_calls"], 0)

    def test_10_zero_call_token_and_cost_arithmetic(self) -> None:
        usage = self.audit["usage_and_cost"]
        self.assertEqual(
            [
                usage["input_tokens"],
                usage["cached_input_tokens"],
                usage["output_tokens"],
                usage["total_tokens"],
            ],
            [0, 0, 0, 0],
        )
        regular_input = usage["input_tokens"] - usage["cached_input_tokens"]
        calculated = (
            Decimal(regular_input) * Decimal("0.15")
            + Decimal(usage["cached_input_tokens"]) * Decimal("0.075")
            + Decimal(usage["output_tokens"]) * Decimal("0.60")
        ) / Decimal(1_000_000)
        self.assertEqual(format(calculated.quantize(Decimal("0.00000001")), "f"), usage["approximate_cost_usd"])
        self.assertEqual(usage["basis"], "ZERO_PROVIDER_CALLS")

    def test_11_duplicate_input_consistency_is_not_evaluable(self) -> None:
        with ZipFile(PACKAGE) as archive:
            requests = [
                json.loads(line)
                for line in archive.read("requests.jsonl").decode("utf-8").splitlines()
            ]
        groups: dict[str, list[str]] = {}
        for row in requests:
            groups.setdefault(row["semantic_input_sha256"], []).append(row["scenario_id"])
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
        duplicate_audit = self.audit["duplicate_semantic_input_audit"]
        self.assertIsNone(duplicate_audit["all_byte_identical_inputs_produced_identical_rag_required"])
        self.assertEqual(duplicate_audit["status"], "NOT_EVALUABLE_NO_VALID_OUTPUTS")

    def test_12_secret_absence(self) -> None:
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

    def test_13_no_gold_expected_labels_or_scoring(self) -> None:
        with ZipFile(PACKAGE) as archive:
            package_manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        self.assertFalse(package_manifest["contains_gold"])
        forbidden = {"gold", "expected_label", "expected_labels", "accuracy", "precision", "recall", "f1", "score"}
        observed_keys = recursive_keys(self.attempts + self.terminals + self.errors)
        self.assertTrue(forbidden.isdisjoint(observed_keys))
        boundaries = self.audit["scope_boundaries"]
        self.assertFalse(boundaries["gold_accessed"])
        self.assertFalse(boundaries["routing_accuracy_or_expected_label_comparison_performed"])

    def test_14_i1_merger_compatibility_fails_closed(self) -> None:
        frozen_manifest = load_jsonl(
            REPO_ROOT
            / "evaluation/rq3_real_c4/i0_integration/c4_real_p3_route_input_manifest_v1.jsonl"
        )
        expected = {
            row["scenario_id"]
            for row in frozen_manifest
            if row["status"] == "READY_FOR_P3_ROUTE_EXECUTION"
        }
        successful = {
            row["scenario_id"]
            for row in self.terminals
            if row.get("event") == "TERMINAL_SUCCESS"
        }
        merger_source = (
            REPO_ROOT / "evaluation/rq3_real_c4/i0_integration/assemble_frozen_routes.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(len(expected), 62)
        self.assertEqual(successful, set())
        self.assertNotEqual(successful, expected)
        self.assertIn("Terminal success populations do not equal", merger_source)
        compatibility = self.audit["i1_merger_compatibility"]
        self.assertFalse(compatibility["ready_for_i1_merger"])
        self.assertFalse(compatibility["merger_invoked"])
        self.assertEqual(compatibility["status"], "NOT_READY_INCOMPLETE_EXECUTION")


if __name__ == "__main__":
    unittest.main()
