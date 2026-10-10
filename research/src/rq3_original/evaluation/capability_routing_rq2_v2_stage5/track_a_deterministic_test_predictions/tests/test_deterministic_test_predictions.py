from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import unittest
import zipfile


TRACK_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = TRACK_DIR.parents[2]
PACKAGE_PATH = Path(
    "/Users/liuming/Downloads/"
    "RQ2_V2_FINAL_TEST_DETERMINISTIC_EXECUTION_PACKAGE_2026-08-31.zip"
)
C0_ROOT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
OUTPUT_PATH = TRACK_DIR / "deterministic_test_terminal_results_v1.jsonl"
SOURCE_MANIFEST_PATH = TRACK_DIR / "deterministic_test_execution_source_manifest_v1.json"
AUDIT_PATH = TRACK_DIR / "deterministic_test_execution_audit_v1.json"
STATUS_PATH = TRACK_DIR / "STATUS.md"
REPORT_PATH = TRACK_DIR / "DETERMINISTIC_TEST_EXECUTION_REPORT.md"

PACKAGE_SHA256 = "c869b2fc613d8ec8a7b3aa555e3de9e33c394dcd28725eae65c3ae72572d8222"
OUTPUT_SHA256 = "3f0cad65e0d08a011e7514ddcce10fda4ac4fcb4b2d104ed6ae4e0c0e2b67f90"
RUNNER_SHA256 = "075aaf135bd8ee0244158cd81470b1e01042a70668bd7ce1dfc8762a17d24026"
INPUT_HASHES = {
    "manifests/deterministic_test_execution_manifest_v1.jsonl":
        "a26878e3871a3b0828271aa8c976a61096ec5680155a8428c735ca829da8d471",
    "test_inputs/test_inputs_frozen_v1.jsonl":
        "284e332dab6f91051960f84a717f8742283166db587d5b544eeb894a5b907cd8",
    "test_inputs/test_inputs_frozen_v1.csv":
        "96e5926a1c3165d3d28378fd5302c76c43867a7a8e7e47006fd0f54d745f5b78",
}
PRIMARY_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
METHOD_IDS = (
    "R2V2-CG1_CLARIFICATION_RULE",
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
)
TOP_LEVEL_FIELDS = {
    "schema_version",
    "logical_case_id",
    "annotation_case_id",
    "execution_status",
    "method_predictions",
    "provider_calls",
    "scoring_performed",
}
EXPECTED_PREDICTION_FIELDS = {
    "R2V2-CG1_CLARIFICATION_RULE": {"dialogue_action", "matched_clause"},
    "R2V2-D0_ALWAYS_ON": {
        "rag_required", "memory_required", "planning_required"
    },
    "R2V2-D1_NEVER_ON": {
        "rag_required", "memory_required", "planning_required"
    },
    "R2V2-B0_RULE": {
        "rag_required", "memory_required", "planning_required"
    },
    "R2V2-B1_LEGACY_INTENT": {
        "rag_required", "memory_required", "planning_required",
        "legacy_intent", "legacy_top1_score", "legacy_top1_margin",
    },
    "R2V2-B2_PROTOTYPE": {
        "rag_required", "memory_required", "planning_required", "scores"
    },
    "R2V2-B3_OVR": {
        "rag_required", "memory_required", "planning_required", "probabilities"
    },
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl_bytes(value: bytes) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in value.decode("utf-8").splitlines()
        if line
    ]


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_keys(nested)


def normalize_input(field: str, value: object) -> object:
    if field == "visible_conversation_history" and isinstance(value, str):
        return json.loads(value)
    return value


class DeterministicTestPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_bytes = OUTPUT_PATH.read_bytes()
        cls.output_lines = cls.output_bytes.decode("utf-8").splitlines()
        cls.rows = [json.loads(line) for line in cls.output_lines]
        cls.source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

        with zipfile.ZipFile(PACKAGE_PATH) as archive:
            cls.archive_names = archive.namelist()
            cls.archive_crc_error = archive.testzip()
            cls.archive_members = {
                name: archive.read(name) for name in cls.archive_names
            }

        cls.package_manifest = json.loads(
            cls.archive_members["PACKAGE_MANIFEST.json"]
        )
        cls.registry = json.loads(
            cls.archive_members[
                "configuration/deterministic_source_hash_registry_v1.json"
            ]
        )
        cls.config = json.loads(
            cls.archive_members[
                "configuration/deterministic_test_execution_config_v1.json"
            ]
        )
        cls.schema = json.loads(
            cls.archive_members[
                "schemas/deterministic_prediction_output_schema_v1.json"
            ]
        )
        cls.manifest = jsonl_bytes(
            cls.archive_members[
                "manifests/deterministic_test_execution_manifest_v1.jsonl"
            ]
        )

    def test_01_authoritative_package_hash(self) -> None:
        self.assertEqual(sha256_file(PACKAGE_PATH), PACKAGE_SHA256)

    def test_02_package_allowlist_crc_and_frozen_status(self) -> None:
        names = self.archive_names
        self.assertEqual(len(names), len(set(names)))
        self.assertIsNone(self.archive_crc_error)
        self.assertTrue(all(
            name
            and not PurePosixPath(name).is_absolute()
            and ".." not in PurePosixPath(name).parts
            and "\\" not in name
            for name in names
        ))
        self.assertEqual(self.package_manifest["archive_allowlist"], names)
        self.assertEqual(self.package_manifest["package_role"], "DETERMINISTIC")
        self.assertEqual(
            self.package_manifest["package_status"], "FROZEN_UNEXECUTED"
        )
        for field in (
            "TEST_Gold_included", "predictions_included", "scores_included"
        ):
            self.assertIs(self.package_manifest[field], False)
        described = {
            item["path"]: item for item in self.package_manifest["members"]
        }
        for name in names:
            if name == "PACKAGE_MANIFEST.json":
                continue
            self.assertEqual(
                sha256_bytes(self.archive_members[name]),
                described[name]["sha256"],
            )
            self.assertEqual(
                len(self.archive_members[name]), described[name]["size_bytes"]
            )
        self.assertFalse(any(
            "gold" in PurePosixPath(name).name.casefold() for name in names
        ))

    def test_03_exact_repository_packaged_and_external_source_identities(self) -> None:
        self.assertEqual(
            self.registry["registry_status"],
            "PASS_ALL_FROZEN_SOURCE_BINDINGS",
        )
        self.assertEqual(tuple(self.registry["method_ids"]), METHOD_IDS)
        self.assertEqual(len(self.registry["source_files"]), 20)
        self.assertEqual(len(self.registry["external_files"]), 8)
        for item in self.registry["source_files"]:
            repository_path = REPOSITORY_ROOT / item["path"]
            packaged_name = "frozen_sources/" + item["path"]
            self.assertEqual(repository_path.stat().st_size, item["size_bytes"])
            self.assertEqual(sha256_file(repository_path), item["sha256"])
            self.assertEqual(
                len(self.archive_members[packaged_name]), item["size_bytes"]
            )
            self.assertEqual(
                sha256_bytes(self.archive_members[packaged_name]),
                item["sha256"],
            )
        c0_root = C0_ROOT.resolve()
        for item in self.registry["external_files"]:
            path = Path(item["path"]).resolve()
            self.assertTrue(path == c0_root or c0_root in path.parents)
            self.assertEqual(path.stat().st_size, item["size_bytes"])
            self.assertEqual(sha256_file(path), item["sha256"])

    def test_04_exact_36_case_unexecuted_manifest(self) -> None:
        expected_fields = {
            "logical_case_id",
            "annotation_case_id",
            *PRIMARY_FIELDS,
            "execution_status",
        }
        self.assertEqual(len(self.manifest), 36)
        self.assertEqual(
            len({row["annotation_case_id"] for row in self.manifest}), 36
        )
        self.assertTrue(all(
            set(row) == expected_fields
            and row["execution_status"] == "NOT_EXECUTED"
            for row in self.manifest
        ))

    def test_05_frozen_input_representations_unchanged_and_equivalent(self) -> None:
        for name, expected_hash in INPUT_HASHES.items():
            self.assertEqual(
                sha256_bytes(self.archive_members[name]), expected_hash
            )
        json_rows = jsonl_bytes(
            self.archive_members["test_inputs/test_inputs_frozen_v1.jsonl"]
        )
        csv_text = self.archive_members[
            "test_inputs/test_inputs_frozen_v1.csv"
        ].decode("utf-8-sig")
        csv_rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len(json_rows), 36)
        self.assertEqual(len(csv_rows), 36)
        for manifest_row, json_row, csv_row in zip(
            self.manifest, json_rows, csv_rows
        ):
            for field in ("annotation_case_id", *PRIMARY_FIELDS):
                self.assertEqual(
                    normalize_input(field, manifest_row[field]),
                    normalize_input(field, json_row[field]),
                )
                self.assertEqual(
                    normalize_input(field, manifest_row[field]),
                    normalize_input(field, csv_row[field]),
                )

    def test_06_every_terminal_record_matches_packaged_output_schema(self) -> None:
        schema = self.schema
        self.assertEqual(schema["type"], "object")
        self.assertIs(schema["additionalProperties"], False)
        for row in self.rows:
            self.assertEqual(set(row), set(schema["required"]))
            for field, definition in schema["properties"].items():
                if "const" in definition:
                    self.assertEqual(row[field], definition["const"])
                if definition.get("type") == "string":
                    self.assertIsInstance(row[field], str)
                if definition.get("type") == "object":
                    self.assertIsInstance(row[field], dict)
            methods_schema = schema["properties"]["method_predictions"]
            self.assertEqual(
                set(row["method_predictions"]), set(methods_schema["required"])
            )
            self.assertIs(methods_schema["additionalProperties"], False)
            self.assertTrue(all(
                isinstance(value, dict)
                for value in row["method_predictions"].values()
            ))

    def test_07_exact_terminal_count_unique_ids_and_manifest_order(self) -> None:
        self.assertEqual(len(self.rows), 36)
        self.assertEqual(
            len({row["annotation_case_id"] for row in self.rows}), 36
        )
        self.assertEqual(
            [row["annotation_case_id"] for row in self.rows],
            [row["annotation_case_id"] for row in self.manifest],
        )
        self.assertEqual(
            [row["logical_case_id"] for row in self.rows],
            [row["logical_case_id"] for row in self.manifest],
        )

    def test_08_identical_seven_method_universe_and_252_outputs(self) -> None:
        self.assertEqual(tuple(self.config["methods_per_case"]), METHOD_IDS)
        self.assertTrue(all(
            set(row["method_predictions"]) == set(METHOD_IDS)
            for row in self.rows
        ))
        self.assertEqual(
            sum(len(row["method_predictions"]) for row in self.rows), 252
        )

    def test_09_no_missing_deterministic_prediction(self) -> None:
        for row in self.rows:
            self.assertEqual(set(row), TOP_LEVEL_FIELDS)
            for method, expected_fields in EXPECTED_PREDICTION_FIELDS.items():
                prediction = row["method_predictions"][method]
                self.assertEqual(set(prediction), expected_fields)
                for field in (
                    "rag_required", "memory_required", "planning_required"
                ):
                    if field in prediction:
                        self.assertIs(type(prediction[field]), bool)
            self.assertEqual(
                set(row["method_predictions"]["R2V2-B2_PROTOTYPE"]["scores"]),
                {"RAG", "Memory", "Planning"},
            )
            self.assertEqual(
                set(row["method_predictions"]["R2V2-B3_OVR"]["probabilities"]),
                {"RAG", "Memory", "Planning"},
            )

    def test_10_zero_provider_calls_and_no_scoring(self) -> None:
        self.assertTrue(all(
            row["provider_calls"] == 0
            and row["scoring_performed"] is False
            for row in self.rows
        ))
        self.assertEqual(sum(row["provider_calls"] for row in self.rows), 0)

    def test_11_no_gold_or_test_performance_metric_fields(self) -> None:
        keys = {
            key.casefold() for row in self.rows for key in walk_keys(row)
        }
        self.assertFalse(any("gold" in key for key in keys))
        performance_fields = {
            "accuracy", "f1", "macro_f1", "micro_f1", "exact_match",
            "precision", "recall", "confusion_matrix", "correct",
            "ground_truth", "target_label", "metric", "metrics",
        }
        self.assertTrue(performance_fields.isdisjoint(keys))

    def test_12_no_query_fields_in_output_and_input_order_preserved(self) -> None:
        keys = {
            key.casefold() for row in self.rows for key in walk_keys(row)
        }
        self.assertTrue(set(PRIMARY_FIELDS).isdisjoint(keys))
        self.assertEqual(
            [row["annotation_case_id"] for row in self.rows],
            [row["annotation_case_id"] for row in self.manifest],
        )

    def test_13_deterministic_terminal_serialization_and_output_hash(self) -> None:
        self.assertTrue(self.output_bytes.endswith(b"\n"))
        for raw_line, row in zip(self.output_lines, self.rows):
            expected = json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.assertEqual(raw_line, expected)
        self.assertEqual(sha256_bytes(self.output_bytes), OUTPUT_SHA256)

    def test_14_static_offline_guard_and_no_provider_sdk_path(self) -> None:
        runner_bytes = self.archive_members[
            "runner/execute_deterministic_test.py"
        ]
        self.assertEqual(sha256_bytes(runner_bytes), RUNNER_SHA256)
        source = runner_bytes.decode("utf-8")
        for required in (
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "HF_DATASETS_OFFLINE",
            'patch("socket.create_connection", _blocked)',
            'patch.object(socket.socket, "connect", _blocked)',
            'patch.object(socket.socket, "connect_ex", _blocked)',
        ):
            self.assertIn(required, source)
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            {"openai", "requests", "httpx", "urllib3"}.isdisjoint(
                imported_roots
            )
        )

    def test_15_pre_post_frozen_input_identity_is_recorded(self) -> None:
        source = self.audit["source_validation"]
        self.assertEqual(
            source["pre_execution_status"], "PASS_EXACT_RAW_BYTES"
        )
        self.assertEqual(
            source["post_execution_status"], "PASS_EXACT_RAW_BYTES"
        )
        self.assertIs(source["frozen_inputs_unchanged"], True)
        package = self.audit["package_validation"]
        self.assertEqual(
            package["observed_sha256_before_execution"], PACKAGE_SHA256
        )
        self.assertEqual(
            package["observed_sha256_after_execution"], PACKAGE_SHA256
        )

    def test_16_audit_and_source_manifest_bind_terminal_freeze(self) -> None:
        expected_status = "FROZEN_UNSCORED_DETERMINISTIC_TEST_PREDICTIONS"
        self.assertEqual(self.audit["status"], expected_status)
        self.assertEqual(
            self.source_manifest["freeze_status"], expected_status
        )
        self.assertEqual(
            self.source_manifest["frozen_source_registry"], self.registry
        )
        for payload in (
            self.audit["output_validation"],
            self.source_manifest["terminal_output"],
        ):
            self.assertEqual(payload["sha256"], OUTPUT_SHA256)
            self.assertEqual(payload.get(
                "terminal_case_records", payload.get("record_count")
            ), 36)
            self.assertEqual(payload.get(
                "method_outputs", payload.get("total_method_outputs")
            ), 252)
            self.assertEqual(payload["provider_calls"], 0)
            self.assertIs(payload["scoring_performed"], False)

    def test_17_generated_artifacts_contain_no_credentials(self) -> None:
        secret_patterns = (
            re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b"),
            re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.I),
        )
        for path in (
            OUTPUT_PATH,
            SOURCE_MANIFEST_PATH,
            AUDIT_PATH,
            STATUS_PATH,
            REPORT_PATH,
        ):
            text = path.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                self.assertIsNone(pattern.search(text), path.name)

    def test_18_one_shot_success_boundary_and_final_status(self) -> None:
        self.assertTrue(OUTPUT_PATH.is_file())
        self.assertFalse(
            OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".partial").exists()
        )
        execution = self.audit["execution"]
        self.assertEqual(execution["execution_attempt_count"], 1)
        self.assertIs(execution["successful_output_created"], True)
        self.assertIs(execution["rerun_performed"], False)
        self.assertEqual(self.audit["tests"]["tests_run"], 18)
        self.assertEqual(self.audit["tests"]["status"], "PASS")
        status_text = STATUS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "FROZEN_UNSCORED_DETERMINISTIC_TEST_PREDICTIONS", status_text
        )
        self.assertIn("STOP_AFTER_PREDICTION_FREEZE", status_text)


if __name__ == "__main__":
    unittest.main()
