from __future__ import annotations

import ast
import collections
import csv
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


TRACK_DIR = Path(__file__).resolve().parents[1]
DEV_PROTOCOL_DIR = TRACK_DIR.parent / "dev_protocol"
sys.path.insert(0, str(TRACK_DIR))

import build_b4_preparation as b4  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_example_from_csv(row: dict[str, str]) -> dict[str, object]:
    return {
        "input": {
            "current_query": row["current_query"],
            "current_page": row["current_page"],
            "dashboard_context": row["dashboard_context"],
            "visible_conversation_history": json.loads(
                row["visible_conversation_history"]
            ),
        },
        "output": {
            "rag_required": json.loads(row["rag_required"]),
            "memory_required": json.loads(row["memory_required"]),
            "planning_required": json.loads(row["planning_required"]),
        },
    }


class ProviderGuard(types.ModuleType):
    def __init__(self, name: str, attempts: list[str]) -> None:
        super().__init__(name)
        self._attempts = attempts
        self.__file__ = None

    def __getattr__(self, name: str) -> object:
        self._attempts.append(f"{self.__name__}.{name}")
        raise AssertionError(f"Provider surface accessed: {self.__name__}.{name}")


class B4PreparationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gold_rows = read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        cls.atomic_rows = read_csv(
            DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv"
        )
        cls.fold_rows = read_csv(DEV_PROTOCOL_DIR / "dev_cv_folds_v1.csv")
        cls.fold_examples = read_csv(TRACK_DIR / "b4_fold_examples_v1.csv")
        cls.final_examples = read_csv(TRACK_DIR / "b4_final_dev_examples_v1.csv")
        cls.manifest = read_jsonl(TRACK_DIR / "b4_dev_execution_manifest_v1.jsonl")
        cls.fold_hashes = json.loads(
            (TRACK_DIR / "b4_fold_prompt_hashes_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.schema = json.loads(
            (TRACK_DIR / "b4_response_schema_v1.json").read_text(encoding="utf-8")
        )
        cls.package = json.loads(
            (TRACK_DIR / "b4_final_full_dev_prompt_package_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.gold_by_id = {
            row["annotation_case_id"]: row for row in cls.gold_rows
        }
        cls.atomic_by_id = {
            row["annotation_case_id"]: row for row in cls.atomic_rows
        }
        cls.answer_ids = {
            row["annotation_case_id"]
            for row in cls.gold_rows
            if row["final_dialogue_action"] == "ANSWER"
        }

    def test_01_frozen_dev_source_hashes_match(self) -> None:
        verification = b4.verify_dev_sources()
        self.assertEqual("PASS", verification["status"])
        observed = {
            entry["name"]: entry["sha256"]
            for entry in verification["verified_files"]
        }
        self.assertEqual(b4.EXPECTED_DEV_INPUT_HASHES, observed)
        self.assertEqual(
            b4.DEV_SOURCE_PACKAGE_SHA256,
            verification["dev_source_package_sha256"],
        )

    def test_02_no_test_identifiers_or_non_dev_cases(self) -> None:
        self.assertEqual({"DEV"}, {row["partition"] for row in self.gold_rows})
        artifact_case_ids = {
            record["annotation_case_id"] for record in self.manifest
        }
        artifact_case_ids.update(
            row["annotation_case_id"] for row in self.fold_examples
        )
        artifact_case_ids.update(
            row["annotation_case_id"] for row in self.final_examples
        )
        for entry in self.fold_hashes["folds"].values():
            artifact_case_ids.update(entry["example_ids"])
        artifact_case_ids.update(self.fold_hashes["full_dev"]["example_ids"])
        self.assertLessEqual(artifact_case_ids, set(self.gold_by_id))
        self.assertFalse(any("TEST" in case_id.upper() for case_id in artifact_case_ids))
        source_governance = json.loads(
            (TRACK_DIR / "b4_dev_source_verification_v1.json").read_text(
                encoding="utf-8"
            )
        )["governance"]
        self.assertEqual(
            {
                "test_identifier_retained": False,
                "test_query_or_gold_accessed": False,
                "test_record_retained": False,
            },
            source_governance,
        )

    def test_03_manifest_has_64_unique_unexecuted_logical_requests(self) -> None:
        self.assertEqual(64, len(self.manifest))
        self.assertEqual(
            64, len({record["logical_call_id"] for record in self.manifest})
        )
        self.assertEqual(
            {"NOT_EXECUTED"},
            {record["execution_status"] for record in self.manifest},
        )
        self.assertTrue(
            all(
                record["execution_controls"]
                == {
                    "sdk_transport_retries": 0,
                    "invalid_structured_output_retries_max": 1,
                    "silent_repair_allowed": False,
                }
                for record in self.manifest
            )
        )

    def test_04_every_answer_dev_case_appears_exactly_once(self) -> None:
        observed = collections.Counter(
            record["annotation_case_id"] for record in self.manifest
        )
        self.assertEqual(self.answer_ids, set(observed))
        self.assertEqual({1}, set(observed.values()))
        validation_fold_by_id = {
            row["annotation_case_id"]: row["fold_id"]
            for row in self.fold_rows
            if row["fold_role"] == "VALIDATION"
        }
        for record in self.manifest:
            self.assertEqual(
                validation_fold_by_id[record["annotation_case_id"]],
                record["outer_fold_id"],
            )

    def test_05_each_fold_prompt_has_exactly_eight_signatures(self) -> None:
        for fold in b4.FOLDS:
            rows = [row for row in self.fold_examples if row["outer_fold_id"] == fold]
            self.assertEqual(8, len(rows), fold)
            self.assertEqual(list(b4.SIGNATURES), [row["signature"] for row in rows])
            entry = self.fold_hashes["folds"][fold]
            self.assertEqual(8, entry["example_count"])
            self.assertEqual(list(b4.SIGNATURES), entry["signatures"])

    def test_06_validation_utterances_never_examples(self) -> None:
        for fold in b4.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            example_ids = {
                row["annotation_case_id"]
                for row in self.fold_examples
                if row["outer_fold_id"] == fold
            }
            self.assertTrue(validation_ids.isdisjoint(example_ids), fold)

    def test_07_validation_families_never_examples(self) -> None:
        for fold in b4.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            validation_families = {
                self.gold_by_id[case_id]["scenario_family_id"]
                for case_id in validation_ids
            }
            example_families = {
                row["scenario_family_id"]
                for row in self.fold_examples
                if row["outer_fold_id"] == fold
            }
            self.assertTrue(validation_families.isdisjoint(example_families), fold)

    def test_08_validation_atomic_components_never_examples(self) -> None:
        for fold in b4.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            validation_components = {
                self.atomic_by_id[case_id]["dev_atomic_component_id"]
                for case_id in validation_ids
            }
            example_components = {
                row["dev_atomic_component_id"]
                for row in self.fold_examples
                if row["outer_fold_id"] == fold
            }
            self.assertTrue(
                validation_components.isdisjoint(example_components), fold
            )

    def test_09_provider_prompts_contain_only_permitted_semantic_fields(self) -> None:
        permitted_input_keys = set(b4.SEMANTIC_FIELDS)
        for record in self.manifest:
            payload = record["provider_request_payload"]
            messages = payload["messages"]
            self.assertEqual(18, len(messages))
            self.assertEqual("system", messages[0]["role"])
            self.assertEqual("user", messages[-1]["role"])
            provider_text = json.dumps(payload, ensure_ascii=False)
            for field in b4.PROHIBITED_PROMPT_FIELD_NAMES:
                self.assertNotIn(field, provider_text)
            for message in messages[1:]:
                value = json.loads(message["content"])
                if message["role"] == "user":
                    self.assertEqual(permitted_input_keys, set(value))
                else:
                    self.assertEqual(set(b4.LABEL_FIELDS), set(value))

    def test_10_validation_gold_absent_from_provider_payloads(self) -> None:
        for record in self.manifest:
            self.assertNotIn("validation_gold", record)
            self.assertNotIn("expected_output", record)
            self.assertEqual(set(b4.SEMANTIC_FIELDS), set(record["validation_input"]))
            self.assertTrue(set(b4.LABEL_FIELDS).isdisjoint(record["validation_input"]))
            messages = record["provider_request_payload"]["messages"]
            self.assertEqual(
                record["validation_input"], json.loads(messages[-1]["content"])
            )
            self.assertEqual("user", messages[-1]["role"])

    def test_11_response_schema_and_parser_are_strict(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual("object", self.schema["type"])
        self.assertIs(False, self.schema["additionalProperties"])
        self.assertEqual(set(b4.LABEL_FIELDS), set(self.schema["required"]))
        self.assertEqual(set(b4.LABEL_FIELDS), set(self.schema["properties"]))
        self.assertTrue(
            all(
                definition == {"type": "boolean"}
                for definition in self.schema["properties"].values()
            )
        )
        valid = {
            "rag_required": True,
            "memory_required": False,
            "planning_required": True,
        }
        self.assertEqual(valid, b4.parse_strict_response(b4.rendered_json(valid)))
        invalid = (
            '{"rag_required":true,"memory_required":false}',
            '{"rag_required":"true","memory_required":false,"planning_required":true}',
            '{"rag_required":true,"memory_required":false,"planning_required":true,"extra":false}',
            'answer: {"rag_required":true,"memory_required":false,"planning_required":true}',
            '{invalid json}',
            '[true,false,true]',
            '{"rag_required":1,"memory_required":false,"planning_required":true}',
            '{"rag_required":true,"rag_required":false,"memory_required":false,"planning_required":true}',
        )
        for raw_text in invalid:
            with self.subTest(raw_text=raw_text), self.assertRaises(ValueError):
                b4.parse_strict_response(raw_text)

    def test_12_full_dev_package_has_eight_signatures_and_no_hidden_fields(self) -> None:
        self.assertEqual(8, len(self.final_examples))
        self.assertEqual(
            list(b4.SIGNATURES), [row["signature"] for row in self.final_examples]
        )
        self.assertEqual(8, len(self.package["few_shot_examples"]))
        for example in self.package["few_shot_examples"]:
            self.assertEqual(set(b4.SEMANTIC_FIELDS), set(example["input"]))
            self.assertEqual(set(b4.LABEL_FIELDS), set(example["output"]))
        package_text = json.dumps(self.package["few_shot_examples"], ensure_ascii=False)
        for field in b4.PROHIBITED_PROMPT_FIELD_NAMES:
            self.assertNotIn(field, package_text)
        identity = self.package["encoder_identity"]
        self.assertEqual(b4.ENCODER_REPO_ID, identity["repo_id"])
        self.assertEqual(b4.ENCODER_REVISION, identity["revision"])
        self.assertEqual("B4_PREDICTION", identity["prohibited_purpose"])

    def test_13_prompt_and_example_hashes_are_deterministic(self) -> None:
        self.assertEqual(
            sha256_file(TRACK_DIR / "b4_prompt_template_frozen_v1.txt"),
            self.fold_hashes["prompt_template_sha256"],
        )
        self.assertEqual(
            sha256_file(TRACK_DIR / "b4_response_schema_v1.json"),
            self.fold_hashes["strict_response_schema_sha256"],
        )
        for fold in b4.FOLDS:
            rows = [
                row for row in self.fold_examples if row["outer_fold_id"] == fold
            ]
            examples = [public_example_from_csv(row) for row in rows]
            entry = self.fold_hashes["folds"][fold]
            self.assertEqual(
                b4.canonical_sha256(examples), entry["example_set_sha256"]
            )
            self.assertEqual(
                b4.prompt_package_hash(examples),
                entry["fold_prompt_package_sha256"],
            )
            for record in self.manifest:
                if record["outer_fold_id"] == fold:
                    self.assertEqual(
                        entry["example_set_sha256"],
                        record["fold_specific_example_set_sha256"],
                    )
                    self.assertEqual(
                        entry["fold_prompt_package_sha256"],
                        record["fold_prompt_package_sha256"],
                    )

    def test_14_offline_rebuild_is_deterministic_and_makes_zero_calls(self) -> None:
        network_attempts: list[str] = []
        provider_attempts: list[str] = []

        def blocked_connect(*_args: object, **_kwargs: object) -> None:
            network_attempts.append("socket.connect")
            raise AssertionError("Network connection attempted")

        def blocked_connect_ex(*_args: object, **_kwargs: object) -> int:
            network_attempts.append("socket.connect_ex")
            raise AssertionError("Network connection attempted")

        provider_guards = {
            name: ProviderGuard(name, provider_attempts)
            for name in ("openai", "anthropic", "google.generativeai")
        }
        with tempfile.TemporaryDirectory(prefix="rq2_v2_b4_offline_rebuild_") as temp:
            output_dir = Path(temp)
            with (
                mock.patch.object(socket.socket, "connect", new=blocked_connect),
                mock.patch.object(socket.socket, "connect_ex", new=blocked_connect_ex),
                mock.patch.dict(sys.modules, provider_guards),
            ):
                summary = b4.build(output_dir)
            self.assertEqual(0, summary["network_calls"])
            self.assertEqual(0, summary["provider_calls"])
            deterministic_artifacts = (
                "b4_prompt_template_frozen_v1.txt",
                "b4_response_schema_v1.json",
                "b4_fold_examples_v1.csv",
                "b4_final_dev_examples_v1.csv",
                "b4_fold_prompt_hashes_v1.json",
                "b4_dev_execution_manifest_v1.jsonl",
                "b4_final_full_dev_prompt_package_v1.json",
                "b4_encoder_identity_v1.json",
                "b4_dev_source_verification_v1.json",
                "b4_token_estimate_v1.json",
            )
            for name in deterministic_artifacts:
                self.assertEqual(
                    sha256_file(TRACK_DIR / name),
                    sha256_file(output_dir / name),
                    name,
                )
        self.assertEqual([], network_attempts)
        self.assertEqual([], provider_attempts)

    def test_15_builder_has_no_provider_or_network_client_calls(self) -> None:
        source_path = TRACK_DIR / "build_b4_preparation.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        prohibited_import_roots = {
            "openai",
            "anthropic",
            "requests",
            "httpx",
            "urllib",
            "socket",
            "aiohttp",
        }
        imported_roots: set[str] = set()
        call_chains: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                parts: list[str] = []
                current = node.func
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                    call_chains.append(".".join(reversed(parts)))
        self.assertTrue(prohibited_import_roots.isdisjoint(imported_roots))
        prohibited_calls = {
            "openai.OpenAI",
            "openai.Client",
            "client.chat.completions.create",
            "client.responses.create",
            "requests.get",
            "requests.post",
            "urllib.request.urlopen",
        }
        self.assertTrue(prohibited_calls.isdisjoint(call_chains))


if __name__ == "__main__":
    unittest.main(verbosity=2)
