from __future__ import annotations

import ast
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


TRACK_DIR = Path(__file__).resolve().parents[1]
STAGE4_DIR = TRACK_DIR.parent
B4_DIR = STAGE4_DIR / "track_i_b4"
DEV_PROTOCOL_DIR = STAGE4_DIR / "dev_protocol"
sys.path.insert(0, str(TRACK_DIR))

import build_specialist_protocol as protocol  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_source_fields(row: dict[str, str], include_fold: bool) -> dict[str, str]:
    fields = [
        "example_order",
        "signature",
        "annotation_case_id",
        "scenario_family_id",
        "dev_atomic_component_id",
        *protocol.SEMANTIC_FIELDS,
    ]
    value = {field: row[field] for field in fields}
    if include_fold:
        value["outer_fold"] = row["outer_fold_id"]
    return value


def normalized_specialist_fields(row: dict[str, str], include_fold: bool) -> dict[str, str]:
    fields = [
        "example_order",
        "signature",
        "annotation_case_id",
        "scenario_family_id",
        "dev_atomic_component_id",
        *protocol.SEMANTIC_FIELDS,
    ]
    value = {field: row[field] for field in fields}
    if include_fold:
        value["outer_fold"] = row["outer_fold"]
    return value


class ProviderGuard(types.ModuleType):
    def __init__(self, name: str, attempts: list[str]) -> None:
        super().__init__(name)
        self._attempts = attempts
        self.__file__ = None

    def __getattr__(self, name: str) -> object:
        self._attempts.append(f"{self.__name__}.{name}")
        raise AssertionError(f"Provider surface accessed: {self.__name__}.{name}")


class SpecialistProtocolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gold_rows = read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        cls.fold_rows = read_csv(DEV_PROTOCOL_DIR / "dev_cv_folds_v1.csv")
        cls.atomic_rows = read_csv(DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv")
        cls.b4_fold_examples = read_csv(B4_DIR / "b4_fold_examples_v1.csv")
        cls.b4_final_examples = read_csv(B4_DIR / "b4_final_dev_examples_v1.csv")
        cls.rag_fold_examples = read_csv(TRACK_DIR / "rag_specialist_fold_examples_v1.csv")
        cls.memory_fold_examples = read_csv(
            TRACK_DIR / "memory_specialist_fold_examples_v1.csv"
        )
        cls.rag_final_examples = read_csv(TRACK_DIR / "rag_specialist_final_examples_v1.csv")
        cls.memory_final_examples = read_csv(
            TRACK_DIR / "memory_specialist_final_examples_v1.csv"
        )
        cls.rag_manifest = read_jsonl(
            TRACK_DIR / "rag_specialist_dev_execution_manifest_v1.jsonl"
        )
        cls.memory_manifest = read_jsonl(
            TRACK_DIR / "memory_specialist_dev_execution_manifest_v1.jsonl"
        )
        cls.hash_index = read_json(TRACK_DIR / "specialist_fold_prompt_hashes_v1.json")
        cls.gold_by_id = {row["annotation_case_id"]: row for row in cls.gold_rows}
        cls.atomic_by_id = {row["annotation_case_id"]: row for row in cls.atomic_rows}
        cls.answer_ids = {
            row["annotation_case_id"]
            for row in cls.gold_rows
            if row["final_dialogue_action"] == "ANSWER"
        }

    def test_01_frozen_source_hashes_match(self) -> None:
        verification = protocol.verify_sources()
        self.assertEqual("PASS", verification["status"])
        observed = {
            entry["name"]: entry["sha256"]
            for entry in verification["verified_files"]
        }
        expected = {name: value[1] for name, value in protocol.SOURCE_FILES.items()}
        self.assertEqual(expected, observed)

    def test_02_dev_only_population_and_zero_test_ids(self) -> None:
        self.assertEqual({"DEV"}, {row["partition"] for row in self.gold_rows})
        self.assertEqual(64, len(self.answer_ids))
        artifact_ids = {
            record["annotation_case_id"]
            for record in self.rag_manifest + self.memory_manifest
        }
        artifact_ids.update(row["annotation_case_id"] for row in self.rag_fold_examples)
        artifact_ids.update(row["annotation_case_id"] for row in self.memory_fold_examples)
        artifact_ids.update(row["annotation_case_id"] for row in self.rag_final_examples)
        artifact_ids.update(row["annotation_case_id"] for row in self.memory_final_examples)
        self.assertLessEqual(artifact_ids, set(self.gold_by_id))
        self.assertFalse(any("TEST" in value.upper() for value in artifact_ids))
        governance = read_json(
            TRACK_DIR / "specialist_source_verification_v1.json"
        )["governance"]
        self.assertTrue(governance["dev_only"])
        for key, value in governance.items():
            if key != "dev_only":
                self.assertIs(False, value, key)

    def test_03_prompts_use_only_four_semantic_inputs_and_no_hidden_fields(self) -> None:
        forbidden = (
            "annotation_case_id",
            "scenario_family_id",
            "dev_atomic_component_id",
            "outer_fold",
            "signature",
            "validation_gold",
            "partition",
        )
        for specialist in protocol.SPECIALISTS:
            prompt = (TRACK_DIR / f"{specialist}_specialist_prompt_frozen_v1.txt").read_text(
                encoding="utf-8"
            )
            for field in protocol.SEMANTIC_FIELDS:
                self.assertIn(field, prompt)
            for field in forbidden:
                self.assertNotIn(field, prompt)

    def test_04_schemas_are_exact_strict_one_boolean_objects(self) -> None:
        expected = {
            "rag": {
                "type": "object",
                "properties": {"rag_required": {"type": "boolean"}},
                "required": ["rag_required"],
                "additionalProperties": False,
            },
            "memory": {
                "type": "object",
                "properties": {"memory_required": {"type": "boolean"}},
                "required": ["memory_required"],
                "additionalProperties": False,
            },
        }
        for specialist, value in expected.items():
            schema = read_json(TRACK_DIR / f"{specialist}_specialist_schema_v1.json")
            self.assertEqual(value, schema)
            self.assertTrue(
                {"$schema", "title", "minProperties", "maxProperties"}.isdisjoint(schema)
            )

    def test_05_rag_fold_examples_reuse_b4_identities_inputs_and_order(self) -> None:
        self.assertEqual(len(self.b4_fold_examples), len(self.rag_fold_examples))
        for source, derived in zip(
            self.b4_fold_examples, self.rag_fold_examples, strict=True
        ):
            self.assertEqual(
                normalized_source_fields(source, True),
                normalized_specialist_fields(derived, True),
            )
            self.assertEqual(
                {"outer_fold", "example_order", "signature", "annotation_case_id", "scenario_family_id", "dev_atomic_component_id", *protocol.SEMANTIC_FIELDS, "rag_required"},
                set(derived),
            )
            self.assertEqual(source["rag_required"], derived["rag_required"])

    def test_06_memory_fold_examples_reuse_b4_identities_inputs_and_order(self) -> None:
        self.assertEqual(len(self.b4_fold_examples), len(self.memory_fold_examples))
        for source, derived in zip(
            self.b4_fold_examples, self.memory_fold_examples, strict=True
        ):
            self.assertEqual(
                normalized_source_fields(source, True),
                normalized_specialist_fields(derived, True),
            )
            self.assertEqual(
                {"outer_fold", "example_order", "signature", "annotation_case_id", "scenario_family_id", "dev_atomic_component_id", *protocol.SEMANTIC_FIELDS, "memory_required"},
                set(derived),
            )
            self.assertEqual(source["memory_required"], derived["memory_required"])

    def test_07_final_examples_reuse_b4_identities_inputs_and_order(self) -> None:
        for derived, target in (
            (self.rag_final_examples, "rag_required"),
            (self.memory_final_examples, "memory_required"),
        ):
            self.assertEqual(8, len(derived))
            for source, output in zip(self.b4_final_examples, derived, strict=True):
                self.assertEqual(
                    normalized_source_fields(source, False),
                    normalized_specialist_fields(output, False),
                )
                self.assertEqual(source[target], output[target])

    def test_08_each_fold_has_eight_examples_and_all_signatures(self) -> None:
        for rows in (self.rag_fold_examples, self.memory_fold_examples):
            for fold in protocol.FOLDS:
                selected = [row for row in rows if row["outer_fold"] == fold]
                self.assertEqual(8, len(selected), fold)
                self.assertEqual(list(protocol.SIGNATURES), [row["signature"] for row in selected])
                self.assertEqual(
                    list(range(1, 9)), [int(row["example_order"]) for row in selected]
                )

    def test_09_every_fold_and_final_set_is_four_yes_four_no(self) -> None:
        for rows, target in (
            (self.rag_fold_examples, "rag_required"),
            (self.memory_fold_examples, "memory_required"),
        ):
            for fold in protocol.FOLDS:
                values = [row[target] for row in rows if row["outer_fold"] == fold]
                self.assertEqual(4, values.count("true"), (fold, target))
                self.assertEqual(4, values.count("false"), (fold, target))
        for rows, target in (
            (self.rag_final_examples, "rag_required"),
            (self.memory_final_examples, "memory_required"),
        ):
            values = [row[target] for row in rows]
            self.assertEqual(4, values.count("true"))
            self.assertEqual(4, values.count("false"))

    def test_10_no_validation_utterance_is_an_example(self) -> None:
        for fold in protocol.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            for examples in (self.rag_fold_examples, self.memory_fold_examples):
                example_ids = {
                    row["annotation_case_id"]
                    for row in examples
                    if row["outer_fold"] == fold
                }
                self.assertTrue(validation_ids.isdisjoint(example_ids), fold)

    def test_11_no_validation_family_is_an_example(self) -> None:
        for fold in protocol.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            validation_families = {
                self.gold_by_id[case_id]["scenario_family_id"] for case_id in validation_ids
            }
            for examples in (self.rag_fold_examples, self.memory_fold_examples):
                example_families = {
                    row["scenario_family_id"]
                    for row in examples
                    if row["outer_fold"] == fold
                }
                self.assertTrue(validation_families.isdisjoint(example_families), fold)

    def test_12_no_validation_atomic_component_is_an_example(self) -> None:
        for fold in protocol.FOLDS:
            validation_ids = {
                row["annotation_case_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold and row["fold_role"] == "VALIDATION"
            }
            validation_components = {
                self.atomic_by_id[case_id]["dev_atomic_component_id"]
                for case_id in validation_ids
            }
            for examples in (self.rag_fold_examples, self.memory_fold_examples):
                example_components = {
                    row["dev_atomic_component_id"]
                    for row in examples
                    if row["outer_fold"] == fold
                }
                self.assertTrue(validation_components.isdisjoint(example_components), fold)

    def test_13_fold_packages_and_hashes_are_complete_and_deterministic(self) -> None:
        for specialist in protocol.SPECIALISTS:
            index = self.hash_index["specialists"][specialist]
            self.assertEqual(
                sha256_file(TRACK_DIR / f"{specialist}_specialist_prompt_frozen_v1.txt"),
                index["prompt_template_sha256"],
            )
            self.assertEqual(
                sha256_file(TRACK_DIR / f"{specialist}_specialist_schema_v1.json"),
                index["specialist_schema_sha256"],
            )
            for fold in protocol.FOLDS:
                entry = index["folds"][fold]
                package = read_json(TRACK_DIR / entry["prompt_package_filename"])
                self.assertEqual(fold, package["outer_fold"])
                self.assertEqual(8, len(package["few_shot_examples"]))
                self.assertTrue(package["source_b4_reuse"]["identity_and_order_exact"])
                self.assertEqual(
                    protocol.canonical_sha256(package["source_b4_reuse"]["example_ids_in_order"]),
                    entry["example_id_order_sha256"],
                )
                self.assertEqual(
                    protocol.canonical_sha256(package["few_shot_examples"]),
                    entry["specialist_example_set_sha256"],
                )
                self.assertEqual(
                    protocol.canonical_sha256(package["complete_rendered_fold_package"]),
                    entry["complete_rendered_fold_package_sha256"],
                )

    def test_14_manifests_have_64_unique_logical_requests_each(self) -> None:
        for records in (self.rag_manifest, self.memory_manifest):
            self.assertEqual(64, len(records))
            self.assertEqual(64, len({record["logical_call_id"] for record in records}))
            self.assertEqual(64, len({record["annotation_case_id"] for record in records}))

    def test_15_manifests_have_same_complete_dev_answer_population_and_folds(self) -> None:
        rag_pairs = {
            (record["annotation_case_id"], record["outer_fold"])
            for record in self.rag_manifest
        }
        memory_pairs = {
            (record["annotation_case_id"], record["outer_fold"])
            for record in self.memory_manifest
        }
        self.assertEqual(rag_pairs, memory_pairs)
        self.assertEqual(self.answer_ids, {case_id for case_id, _fold in rag_pairs})
        validation_fold_by_id = {
            row["annotation_case_id"]: row["fold_id"]
            for row in self.fold_rows
            if row["fold_role"] == "VALIDATION"
        }
        for case_id, fold in rag_pairs:
            self.assertEqual(validation_fold_by_id[case_id], fold)

    def test_16_all_requests_are_unexecuted_with_frozen_model_and_controls(self) -> None:
        expected_controls = protocol.execution_controls()
        for records in (self.rag_manifest, self.memory_manifest):
            self.assertEqual({"NOT_EXECUTED"}, {record["execution_status"] for record in records})
            for record in records:
                self.assertEqual(protocol.MODEL_SNAPSHOT, record["model_snapshot"])
                self.assertEqual(expected_controls, record["execution_controls"])
                self.assertIn("REQUIRES_NEW_DIRECT_USER_AUTHORIZATION", record["model_execution_authorization_status"])

    def test_17_provider_requests_have_no_validation_gold_or_hidden_fields(self) -> None:
        forbidden = {
            "annotation_case_id",
            "scenario_family_id",
            "dev_atomic_component_id",
            "outer_fold",
            "signature",
            "validation_gold",
            "expected_output",
            "partition",
        }
        for specialist, records in (
            ("rag", self.rag_manifest),
            ("memory", self.memory_manifest),
        ):
            target = protocol.SPECIALISTS[specialist]["target_field"]
            for record in records:
                payload = record["provider_facing_request"]
                self.assertEqual(
                    {"model", "messages", "temperature", "max_tokens", "response_format"},
                    set(payload),
                )
                self.assertEqual(18, len(payload["messages"]))
                self.assertEqual(protocol.MODEL_SNAPSHOT, payload["model"])
                self.assertEqual(0, payload["temperature"])
                self.assertEqual(32, payload["max_tokens"])
                self.assertIs(False, record["validation_gold_in_provider_request"])
                self.assertEqual(
                    record["semantic_validation_inputs"],
                    json.loads(payload["messages"][-1]["content"]),
                )
                self.assertEqual("user", payload["messages"][-1]["role"])
                for message in payload["messages"][1:]:
                    content = json.loads(message["content"])
                    if message["role"] == "user":
                        self.assertEqual(set(protocol.SEMANTIC_FIELDS), set(content))
                    else:
                        self.assertEqual({target}, set(content))
                        self.assertIsInstance(content[target], bool)
                serialized = json.dumps(payload, ensure_ascii=False)
                for field in forbidden:
                    self.assertNotIn(field, serialized)

    def test_18_all_declared_hashes_and_sha256_manifest_match(self) -> None:
        for records in (self.rag_manifest, self.memory_manifest):
            for record in records:
                self.assertEqual(
                    protocol.canonical_sha256(record["provider_facing_request"]),
                    record["provider_facing_request_sha256"],
                )
        manifest = read_json(TRACK_DIR / "STAGE4_K0_SHA256_MANIFEST.json")
        self.assertEqual(manifest["file_count"], len(manifest["files"]))
        for entry in manifest["files"]:
            self.assertEqual(
                entry["sha256"], sha256_file(TRACK_DIR / entry["path"]), entry["path"]
            )

    def test_19_future_retry_policy_is_exact_and_non_coercive(self) -> None:
        policy = read_json(TRACK_DIR / "specialist_future_retry_policy_v1.json")
        self.assertEqual(protocol.RETRY_POLICY, policy)
        self.assertEqual(1, policy["manual_retries_per_logical_call_max"])
        self.assertEqual("INVALID_JSON_OR_STRICT_SCHEMA_ONLY", policy["manual_retry_condition"])
        self.assertTrue(policy["retry_uses_identical_prompt"])
        self.assertFalse(policy["correction_message_allowed"])
        self.assertFalse(policy["string_to_boolean_coercion_allowed"])
        self.assertFalse(policy["json_extraction_from_prose_allowed"])
        self.assertEqual(0, policy["sdk_transport_retries"])
        self.assertEqual(128, policy["maximum_physical_attempts_per_specialist"])

    def test_20_p2_composition_is_exact_without_fallback_or_scores(self) -> None:
        p2 = read_json(TRACK_DIR / "p2_rag_specialist_composition_contract_v1.json")
        self.assertEqual("R2V2-P2_RAG_SPECIALIST_COMPOSITION", p2["composition_id"])
        self.assertEqual(["RAG_specialist", "B4_memory", "B4_planning"], p2["formal_vector"])
        self.assertEqual("RAG_SPECIALIST_VALID_STRUCTURED_RESULT", p2["bindings"]["rag_required"]["source"])
        self.assertEqual("FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT", p2["bindings"]["memory_required"]["source"])
        self.assertEqual("FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT", p2["bindings"]["planning_required"]["source"])
        self.assertFalse(p2["b3_fallback_allowed"])
        self.assertFalse(p2["confidence_or_scores_used"])
        self.assertFalse(p2["learned_composition_model_used"])
        self.assertFalse(p2["planning_is_function_of_memory"])

    def test_21_p3_composition_is_exact_and_planning_never_comes_from_memory(self) -> None:
        p3 = read_json(TRACK_DIR / "p3_capability_specialists_composition_contract_v1.json")
        self.assertEqual("R2V2-P3_RAG_MEMORY_SPECIALISTS", p3["composition_id"])
        self.assertEqual(["RAG_specialist", "Memory_specialist", "B4_planning"], p3["formal_vector"])
        self.assertEqual("RAG_SPECIALIST_VALID_STRUCTURED_RESULT", p3["bindings"]["rag_required"]["source"])
        self.assertEqual("MEMORY_SPECIALIST_VALID_STRUCTURED_RESULT", p3["bindings"]["memory_required"]["source"])
        self.assertEqual("FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT", p3["bindings"]["planning_required"]["source"])
        self.assertEqual("planning_required", p3["bindings"]["planning_required"]["source_field"])
        self.assertFalse(p3["planning_is_function_of_memory"])
        self.assertEqual("INCOMPLETE", p3["missing_or_invalid_specialist_result"]["composition_status"])
        self.assertFalse(p3["missing_or_invalid_specialist_result"]["substitution_allowed"])

    def test_22_evaluation_protocol_predeclares_all_metrics_and_comparisons(self) -> None:
        value = read_json(TRACK_DIR / "specialist_evaluation_protocol_v1.json")
        self.assertEqual("PREDECLARED_NOT_EXECUTED_NOT_SCORED", value["status"])
        self.assertEqual(64, value["population"]["utterance_count"])
        rag_required = {
            "precision", "recall", "f1", "accuracy", "specificity", "confusion_matrix",
            "positive_prediction_rate", "family_both_utterances_correct",
            "family_prediction_consistency", "rag_contrast_consistency",
            "rag_gold_pattern_contrast_match", "page_stratified_results",
        }
        memory_required = {
            "precision", "recall", "f1", "accuracy", "specificity", "confusion_matrix",
            "positive_prediction_rate", "family_both_utterances_correct",
            "family_prediction_consistency", "memory_contrast_consistency",
            "memory_gold_pattern_contrast_match", "page_stratified_results",
        }
        self.assertEqual(rag_required, set(value["specialists"]["RAG"]["metrics"]))
        self.assertEqual(memory_required, set(value["specialists"]["Memory"]["metrics"]))
        composition_required = {
            "macro_f1", "micro_f1", "per_label_precision_recall_f1",
            "exact_capability_set_match", "example_based_f1", "jaccard",
            "hamming_loss", "under_routing", "over_routing", "family_both_correct",
            "family_prediction_consistency", "contrast_consistency",
            "gold_pattern_contrast_match", "page_metrics", "fold_metrics",
        }
        for metrics in value["compositions"].values():
            self.assertEqual(composition_required, set(metrics))
        self.assertEqual(
            {
                "RAG_SPECIALIST_VS_JOINT_B4_RAG_BIT",
                "MEMORY_SPECIALIST_VS_JOINT_B4_MEMORY_BIT",
                "P2_VS_JOINT_B4",
                "P3_VS_JOINT_B4",
                "P2_VS_P3",
            },
            set(value["comparisons"]),
        )

    def test_23_no_operational_ragate_checkpoint_or_provider_dependency(self) -> None:
        tree = ast.parse(
            (TRACK_DIR / "build_specialist_protocol.py").read_text(encoding="utf-8")
        )
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        prohibited_imports = {
            "openai", "anthropic", "requests", "httpx", "urllib", "socket", "aiohttp",
            "transformers", "torch", "huggingface_hub",
        }
        self.assertTrue(prohibited_imports.isdisjoint(imported_roots))
        for record in self.rag_manifest + self.memory_manifest:
            payload = json.dumps(record["provider_facing_request"], ensure_ascii=False).lower()
            for prohibited in ("ragate", "ketod", "huggingface", "llama"):
                self.assertNotIn(prohibited, payload)

    def test_24_offline_rebuild_is_deterministic_and_makes_zero_calls(self) -> None:
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
        with tempfile.TemporaryDirectory(prefix="rq2_v2_stage4_k0_offline_") as temp:
            output_dir = Path(temp)
            with (
                mock.patch.object(socket.socket, "connect", new=blocked_connect),
                mock.patch.object(socket.socket, "connect_ex", new=blocked_connect_ex),
                mock.patch.dict(sys.modules, provider_guards),
            ):
                summary = protocol.build(output_dir)
            self.assertEqual(0, summary["provider_calls"])
            self.assertEqual(0, summary["specialist_predictions"])
            self.assertEqual(0, summary["test_accesses"])
            for path in output_dir.iterdir():
                if not path.is_file() or path.name == "STAGE4_K0_SHA256_MANIFEST.json":
                    continue
                self.assertEqual(
                    sha256_file(TRACK_DIR / path.name), sha256_file(path), path.name
                )
        self.assertEqual([], network_attempts)
        self.assertEqual([], provider_attempts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
