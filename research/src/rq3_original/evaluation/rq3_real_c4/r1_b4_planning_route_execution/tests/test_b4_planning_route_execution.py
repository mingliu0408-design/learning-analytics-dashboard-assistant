from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "evaluation/rq3_real_c4/r1_b4_planning_route_execution"
OUTPUT = BASE / "execution_output_v1"
PACKAGE = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip"
)
I1_INPUTS = (
    ROOT
    / "evaluation/rq3_real_c4/i0_integration/"
    "c4_real_p3_route_input_manifest_v1.jsonl"
)
EXPECTED_PACKAGE_SHA256 = (
    "56acb70b6ff16f346f5f0b14b18c22b7eeb7853b0bff11db546841aba03b7de0"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "f63ddde61c2d87192d96252272f826e9971d88c2a49a399d614d491f17cd2b52"
)
EXPECTED_TERMINAL_SHA256 = (
    "7f6e64597fbc85d506c70f950115cfabd90adfa470fb24fe7038454def0adfb9"
)
MODEL = "gpt-4o-mini-2024-07-18"
OUTPUT_FIELDS = {"rag_required", "memory_required", "planning_required"}
SEMANTIC_INPUT_FIELDS = {
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
}
RETRYABLE = {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}
EXPECTED_MEMBER_SHA256 = {
    "EXECUTION_CONTRACT.json": "2c0b10dca3932634f267e30ba13a4cf85395bc86219ba2fa6762fc810d4c8fc6",
    "EXECUTION_PLAN.json": "b2465813d055f581d2bde92d1dae4a0cdfa010410438ff57ae219753a453b1c1",
    "PACKAGE_MANIFEST.json": "b2b0524a76be0fdebffd723182d97a2542992ef964f64138d94354d0bc7db360",
    "README.md": "ba4a1aff3528daddfaff59347cc033a7dd42dcc16fa2b0fbb54729105bd2cd56",
    "execute_route_package_v2.py": "3c09ee70b92609f5ea6b21490b198170e198a8af1db721ef1d9b1c7720a85ae2",
    "few_shot_examples.json": "76c1bd755a9ea6d794932c203d639c03594c38a5c99dafd4357104b7bdd6ebb7",
    "prompt.txt": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
    "requests.jsonl": "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326",
    "schema.json": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
    "validate_route_package_v1.py": "0ffb88d64f778de61fedd9db269e7c5aa0ae7db40cbc9e2016eb1f308c42f7d2",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        raise AssertionError(f"Expected object: {path}")
    return value


def load_jsonl_bytes(data: bytes) -> list[dict[str, object]]:
    rows = []
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AssertionError("Expected JSONL object")
            rows.append(value)
    return rows


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return load_jsonl_bytes(path.read_bytes())


class TestB4PlanningRouteExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.package_bytes = PACKAGE.read_bytes()
        with ZipFile(io.BytesIO(cls.package_bytes)) as archive:
            cls.package_members = {
                name: archive.read(name) for name in archive.namelist()
            }
        cls.package_manifest = json.loads(
            cls.package_members["PACKAGE_MANIFEST.json"]
        )
        cls.plan = json.loads(cls.package_members["EXECUTION_PLAN.json"])
        cls.contract = json.loads(cls.package_members["EXECUTION_CONTRACT.json"])
        cls.requests = load_jsonl_bytes(cls.package_members["requests.jsonl"])
        cls.authorization = load_json(BASE / "route_execution_authorization_v1.json")
        cls.preflight = load_json(
            OUTPUT / "route_execution_preflight_receipt_v1.json"
        )
        cls.status = load_json(OUTPUT / "route_execution_status_v1.json")
        cls.usage = load_json(OUTPUT / "route_usage_and_cost_v1.json")
        cls.attempt_rows = load_jsonl(OUTPUT / "route_attempt_records_v1.jsonl")
        cls.reserved = [
            row for row in cls.attempt_rows if row.get("event") == "ATTEMPT_RESERVED"
        ]
        cls.completed = [
            row for row in cls.attempt_rows if row.get("event") == "ATTEMPT_COMPLETED"
        ]
        cls.terminals = load_jsonl(OUTPUT / "route_terminal_results_v1.jsonl")
        cls.errors = load_jsonl(OUTPUT / "route_error_registry_v1.jsonl")
        cls.audit = load_json(BASE / "b4_planning_route_execution_audit_v1.json")
        cls.source_manifest = load_json(
            BASE / "b4_planning_route_execution_source_manifest_v1.json"
        )
        cls.i1_inputs = load_jsonl(I1_INPUTS)

    def test_01_package_integrity_and_identity(self) -> None:
        self.assertEqual(sha256(self.package_bytes), EXPECTED_PACKAGE_SHA256)
        self.assertEqual(set(self.package_members), set(EXPECTED_MEMBER_SHA256))
        self.assertEqual(
            {name: sha256(data) for name, data in self.package_members.items()},
            EXPECTED_MEMBER_SHA256,
        )
        self.assertEqual(
            self.package_manifest["strict_allowlist"],
            sorted(EXPECTED_MEMBER_SHA256),
        )
        self.assertEqual(
            self.package_manifest["package_id"],
            "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_R1",
        )
        self.assertEqual(self.package_manifest["route_component"], "B4_PLANNING")
        self.assertFalse(self.package_manifest["contains_credentials"])
        self.assertFalse(self.package_manifest["contains_gold"])

    def test_02_bytecode_free_fresh_extraction(self) -> None:
        for name in self.package_members:
            path = Path(name)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
        with tempfile.TemporaryDirectory(prefix="rq3-real-r1c-b4-test-") as temp:
            with ZipFile(io.BytesIO(self.package_bytes)) as archive:
                archive.extractall(temp)
            extracted = Path(temp)
            self.assertEqual(
                len([path for path in extracted.rglob("*") if path.is_file()]), 10
            )
            self.assertEqual(list(extracted.rglob("__pycache__")), [])
            self.assertEqual(list(extracted.rglob("*.pyc")), [])
            self.assertEqual(list(extracted.rglob("*.pyo")), [])

    def test_03_authorization_shape_and_hash(self) -> None:
        expected_fields = [
            "authorization_id",
            "authorization_scope",
            "authorized_by",
            "authorized_at",
            "package_id",
            "component",
            "logical_call_count",
            "maximum_physical_attempt_count",
            "status",
        ]
        auth_path = BASE / "route_execution_authorization_v1.json"
        self.assertEqual(sha256(auth_path.read_bytes()), EXPECTED_AUTHORIZATION_SHA256)
        self.assertEqual(list(self.authorization), expected_fields)
        self.assertEqual(set(self.authorization), set(self.contract["strict_authorization_record_fields"]))
        self.assertEqual(self.authorization["status"], "AUTHORIZED")
        self.assertRegex(
            str(self.authorization["authorized_at"]),
            r"^2026-09-01T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertEqual(self.authorization["logical_call_count"], 62)
        self.assertEqual(self.authorization["maximum_physical_attempt_count"], 124)

    def test_04_authorization_preflight_binding(self) -> None:
        self.assertEqual(
            self.preflight["status"], "PASS_CREATED_BEFORE_FIRST_PROVIDER_CALL"
        )
        self.assertEqual(
            self.preflight["authorization_record_sha256"],
            EXPECTED_AUTHORIZATION_SHA256,
        )
        self.assertEqual(
            self.preflight["authorization_id"],
            self.authorization["authorization_id"],
        )
        self.assertEqual(self.preflight["environment_gate"], "PASS_EXACT_R1_VALUE")
        self.assertEqual(self.preflight["provider_calls_before_receipt"], 0)
        self.assertTrue(self.preflight["api_key_present_not_recorded"])

    def test_05_exact_request_population_and_semantic_hashes(self) -> None:
        self.assertEqual(len(self.requests), 62)
        self.assertEqual(
            [row["scenario_id"] for row in self.requests],
            [f"U{number:03d}" for number in range(1, 63)],
        )
        self.assertEqual(len({row["scenario_id"] for row in self.requests}), 62)
        self.assertEqual(
            len({row["semantic_input_sha256"] for row in self.requests}), 60
        )
        for row in self.requests:
            self.assertEqual(set(row["semantic_input"]), SEMANTIC_INPUT_FIELDS)
            self.assertEqual(
                sha256(canonical_bytes(row["semantic_input"])),
                row["semantic_input_sha256"],
            )

    def test_06_request_order_and_i1_population(self) -> None:
        self.assertEqual(self.package_members["requests.jsonl"], I1_INPUTS.read_bytes())
        expected = [
            (row["scenario_id"], row["semantic_input_sha256"])
            for row in self.requests
        ]
        actual = [
            (row["scenario_id"], row["semantic_input_sha256"])
            for row in self.terminals
        ]
        i1 = [
            (row["scenario_id"], row["semantic_input_sha256"])
            for row in self.i1_inputs
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(actual, i1)

    def test_07_strict_three_boolean_outputs_no_imputation(self) -> None:
        for row in self.terminals:
            self.assertEqual(row["event"], "TERMINAL_SUCCESS")
            self.assertEqual(row["terminal_status"], "VALID_OUTPUT")
            self.assertIsInstance(row["output"], dict)
            self.assertEqual(set(row["output"]), OUTPUT_FIELDS)
            self.assertTrue(all(type(value) is bool for value in row["output"].values()))
            self.assertEqual(json.loads(row["raw_response_content"]), row["output"])
        self.assertEqual(self.audit["coverage"]["missing_outputs"], 0)
        self.assertEqual(self.audit["coverage"]["imputed_outputs"], 0)

    def test_08_terminal_uniqueness_and_coverage(self) -> None:
        self.assertEqual(len(self.terminals), 62)
        self.assertEqual(len({row["scenario_id"] for row in self.terminals}), 62)
        self.assertEqual(self.status["state"], "COMPLETED")
        self.assertEqual(self.status["logical_requests"], 62)
        self.assertEqual(self.status["logical_completed"], 62)
        self.assertEqual(self.status["logical_failed"], 0)
        self.assertEqual(self.usage["valid_outputs"], 62)

    def test_09_returned_model_identity(self) -> None:
        self.assertEqual(self.plan["model"], MODEL)
        self.assertEqual({row["returned_model"] for row in self.completed}, {MODEL})
        self.assertEqual({row["returned_model"] for row in self.terminals}, {MODEL})
        self.assertEqual(self.usage["requested_model"], MODEL)
        self.assertEqual(self.usage["returned_model_identity_required"], MODEL)

    def test_10_retry_policy(self) -> None:
        self.assertEqual(self.plan["manual_retry_maximum"], 1)
        self.assertEqual(set(self.plan["manual_retry_only_after"]), RETRYABLE)
        self.assertTrue(self.plan["retry_payload_must_be_identical"])
        completed_by_scenario: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in self.completed:
            completed_by_scenario[str(row["scenario_id"])].append(row)
        for rows in completed_by_scenario.values():
            rows.sort(key=lambda row: int(row["attempt_number"]))
            self.assertIn(len(rows), {1, 2})
            self.assertEqual([row["attempt_number"] for row in rows], list(range(1, len(rows) + 1)))
            self.assertEqual(len({row["provider_payload_sha256"] for row in rows}), 1)
            if len(rows) == 2:
                self.assertIn(rows[0]["outcome"], RETRYABLE)
        self.assertEqual(Counter(row["attempt_number"] for row in self.completed), {1: 62})
        self.assertEqual(self.status["retry_count"], 0)

    def test_11_physical_attempt_ceiling_and_pacing(self) -> None:
        self.assertEqual(len(self.reserved), 62)
        self.assertEqual(len(self.completed), 62)
        self.assertEqual(len(self.attempt_rows), 124)
        self.assertEqual(self.status["physical_attempts"], 62)
        self.assertEqual(self.status["provider_calls"], 62)
        self.assertLessEqual(self.status["physical_attempts"], 124)
        intervals = [
            row["initial_start_interval_seconds"]
            for row in self.completed
            if row["initial_start_interval_seconds"] is not None
        ]
        self.assertEqual(len(intervals), 61)
        self.assertGreaterEqual(min(intervals), 2.0)

    def test_12_duplicate_semantic_input_consistency(self) -> None:
        by_hash: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in self.terminals:
            by_hash[str(row["semantic_input_sha256"])].append(row)
        duplicate_groups = {
            digest: rows for digest, rows in by_hash.items() if len(rows) > 1
        }
        self.assertEqual(set(duplicate_groups), {
            "df61c962d9637495a56badc89f86ced0dc5bcd42f8f7c3a223f0c427299677c9"
        })
        rows = next(iter(duplicate_groups.values()))
        self.assertEqual([row["scenario_id"] for row in rows], ["U022", "U026", "U031"])
        self.assertEqual(
            len({canonical_bytes(row["output"]) for row in rows}),
            1,
        )
        for rows in by_hash.values():
            self.assertEqual(len({canonical_bytes(row["output"]) for row in rows}), 1)

    def test_13_usage_arithmetic_and_cost(self) -> None:
        input_tokens = sum(int(row["input_tokens"]) for row in self.completed)
        cached_tokens = sum(int(row["cached_input_tokens"]) for row in self.completed)
        output_tokens = sum(int(row["output_tokens"]) for row in self.completed)
        total_tokens = sum(int(row["total_tokens"]) for row in self.completed)
        self.assertEqual((input_tokens, cached_tokens, output_tokens, total_tokens), (102157, 67840, 992, 103149))
        self.assertEqual(input_tokens + output_tokens, total_tokens)
        self.assertTrue(all(int(row["cached_input_tokens"]) <= int(row["input_tokens"]) for row in self.completed))
        cost = (
            Decimal(input_tokens - cached_tokens) * Decimal("0.15")
            + Decimal(cached_tokens) * Decimal("0.075")
            + Decimal(output_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)
        self.assertEqual(format(cost.quantize(Decimal("0.00000001")), "f"), "0.01083075")
        self.assertEqual(self.usage["approximate_cost_usd"], "0.01083075")
        self.assertTrue(self.usage["usage_complete"])

    def test_14_durable_output_hashes(self) -> None:
        expected = self.source_manifest["durable_execution_outputs"]["file_sha256"]
        self.assertEqual(set(expected), {path.name for path in OUTPUT.iterdir() if path.is_file()})
        for name, digest in expected.items():
            self.assertEqual(sha256((OUTPUT / name).read_bytes()), digest)
        self.assertEqual(
            sha256((OUTPUT / "route_terminal_results_v1.jsonl").read_bytes()),
            EXPECTED_TERMINAL_SHA256,
        )
        for name, digest in self.status["output_sha256_excluding_status"].items():
            self.assertEqual(sha256((OUTPUT / name).read_bytes()), digest)

    def test_15_error_registry_and_error_counts(self) -> None:
        self.assertEqual(self.errors, [])
        self.assertEqual(Counter(row["outcome"] for row in self.completed), {"VALID": 62})
        self.assertEqual(self.status["stop_reason"], None)
        error_audit = self.audit["errors"]
        self.assertTrue(all(value == 0 for value in error_audit.values()))

    def test_16_no_secrets(self) -> None:
        secret = re.compile(
            rb"(?:s[k]-(?:proj-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})",
            re.IGNORECASE,
        )
        matches = [
            path.relative_to(ROOT).as_posix()
            for path in BASE.rglob("*")
            if path.is_file() and secret.search(path.read_bytes())
        ]
        self.assertEqual(matches, [])
        self.assertTrue(self.preflight["api_key_present_not_recorded"])
        self.assertFalse(self.source_manifest["provenance_boundaries"]["credential_value_recorded"])

    def test_17_no_gold_or_scoring(self) -> None:
        self.assertFalse(self.package_manifest["contains_gold"])
        self.assertFalse(self.plan["route_accuracy_or_expected_label_comparison"])
        self.assertFalse(self.status["expected_labels_accessed"])
        self.assertFalse(self.status["routing_accuracy_calculated"])
        self.assertFalse(self.usage["expected_labels_accessed"])
        self.assertFalse(self.usage["routing_accuracy_calculated"])
        boundary = self.audit["boundary_evidence"]
        self.assertEqual(boundary["gold_access_count"], 0)
        self.assertEqual(boundary["expected_label_access_count"], 0)
        self.assertEqual(boundary["accuracy_or_route_scoring_count"], 0)

    def test_18_i1_planning_bit_compatibility_and_retention(self) -> None:
        expected = {
            row["scenario_id"]: row["semantic_input_sha256"]
            for row in self.i1_inputs
            if row["status"] == "READY_FOR_P3_ROUTE_EXECUTION"
        }
        actual = {row["scenario_id"]: row for row in self.terminals}
        self.assertEqual(set(actual), set(expected))
        for scenario_id, semantic_hash in expected.items():
            self.assertEqual(actual[scenario_id]["semantic_input_sha256"], semantic_hash)
            self.assertEqual(set(actual[scenario_id]["output"]), OUTPUT_FIELDS)
            self.assertIs(type(actual[scenario_id]["output"]["planning_required"]), bool)
        compatibility = self.audit["i1_compatibility"]
        self.assertTrue(compatibility["planning_required_available_for_all_62"])
        self.assertTrue(compatibility["b4_rag_and_memory_bits_retained_for_all_62"])
        self.assertFalse(compatibility["route_integration_executed"])

    def test_19_descriptive_count_freeze(self) -> None:
        counts = {
            field: Counter(row["output"][field] for row in self.terminals)
            for field in OUTPUT_FIELDS
        }
        self.assertEqual(counts["planning_required"], {True: 15, False: 47})
        self.assertEqual(counts["rag_required"], {True: 28, False: 34})
        self.assertEqual(counts["memory_required"], {True: 15, False: 47})
        frozen = self.audit["descriptive_output_counts"]
        self.assertEqual(frozen["planning_required"], {"YES": 15, "NO": 47})
        self.assertEqual(frozen["retained_b4_rag_required"], {"YES": 28, "NO": 34})
        self.assertEqual(frozen["retained_b4_memory_required"], {"YES": 15, "NO": 47})

    def test_20_prohibited_call_boundary(self) -> None:
        boundary = self.audit["boundary_evidence"]
        prohibited = {
            "rag_specialist_calls",
            "memory_specialist_calls",
            "recommendation_planner_calls",
            "course_rag_calls",
            "learner_memory_calls",
            "response_generator_calls",
            "judge_calls",
            "streamlit_calls",
            "route_integration_calls",
        }
        self.assertTrue(all(boundary[name] == 0 for name in prohibited))
        self.assertEqual(self.audit["execution"]["provider_calls"], 62)
        self.assertEqual(self.audit["execution"]["logical_requests"], 62)


if __name__ == "__main__":
    unittest.main()
