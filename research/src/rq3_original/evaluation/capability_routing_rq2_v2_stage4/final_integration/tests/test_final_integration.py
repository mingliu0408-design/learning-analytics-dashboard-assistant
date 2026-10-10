"""Deterministic tests for the unexecuted Stage 4N TEST harness."""

from __future__ import annotations

import ast
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
import zipfile

from ..build_final_integration import (
    build_all,
    read_json,
    sha256_file,
    verify_embedded_identities,
    verify_frozen_sources,
    verify_test_inputs,
)
from ..build_packages import package_specs
from ..constants import (
    B4_MODEL,
    DETERMINISTIC_METHOD_IDS,
    EXPECTED_SOURCE_HASHES,
    INTEGRATION_DIR,
    METHOD_IDS,
    PACKAGE_PATHS,
    PRIMARY_FIELDS,
    PROVIDER_STREAMS,
    REPORTING_TIERS,
    SOURCE_STAGE_HEAD,
    TEST_INPUT_FIELDS,
)
from ..validate_final_integration import _forbidden_keys
from ..validate_execution_package import validate as validate_zip


def load_jsonl(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (INTEGRATION_DIR / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


class Stage4NFinalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_rows, cls.external_rows = verify_frozen_sources()
        cls.identities = verify_embedded_identities()
        cls.inputs = verify_test_inputs()
        cls.registry = read_json(INTEGRATION_DIR / "final_method_registry_v1.json")
        cls.deterministic = load_jsonl("deterministic_test_execution_manifest_v1.jsonl")
        cls.provider = {
            stream: load_jsonl(spec["manifest"])
            for stream, spec in PROVIDER_STREAMS.items()
        }

    def test_01_stage4m_source_head(self) -> None:
        source = read_json(INTEGRATION_DIR / "frozen_source_hash_registry_v1.json")
        self.assertEqual(source["source_stage_head"], SOURCE_STAGE_HEAD)

    def test_02_stage4m_source_hashes(self) -> None:
        observed = {row["path"]: row["sha256"] for row in self.source_rows}
        self.assertEqual(observed, EXPECTED_SOURCE_HASHES)

    def test_03_external_c0_mpnet_hashes(self) -> None:
        self.assertEqual(len(self.external_rows), 8)
        self.assertTrue(all(row["verification_status"] == "PASS_EXACT_RAW_BYTES" for row in self.external_rows))

    def test_04_exact_final_method_universe(self) -> None:
        self.assertEqual(self.registry["method_count"], 14)
        self.assertEqual(tuple(self.registry["method_ids_in_frozen_order"]), METHOD_IDS)

    def test_05_reporting_tiers(self) -> None:
        self.assertEqual(self.registry["reporting_tiers"], REPORTING_TIERS)

    def test_06_p4_exploratory_disclosure(self) -> None:
        p4 = next(row for row in self.registry["methods"] if row["method_id"] == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION")
        self.assertEqual(p4["method_tier"], "TIER_3_POST_DEV_EXPLORATORY")
        self.assertEqual(p4["confirmatory_exploratory_role"], "EXPLORATORY_FACTORIAL_ABLATION")

    def test_07_all_frozen_model_identities(self) -> None:
        self.assertEqual(self.identities["B4"]["model_snapshot"], B4_MODEL)
        self.assertEqual(self.identities["B1"]["intent_label_count"], 16)
        self.assertEqual(self.identities["B2"]["encoder_revision"], "e8c3b32edf5434bc2275fc9bab85f82640a19130")
        self.assertEqual(self.identities["B3"]["configuration"]["random_state"], 20260831)

    def test_08_test_input_row_count(self) -> None:
        self.assertEqual(len(self.inputs), 36)

    def test_09_test_input_unique_ids(self) -> None:
        self.assertEqual(len({row["annotation_case_id"] for row in self.inputs}), 36)

    def test_10_test_input_exact_fields(self) -> None:
        self.assertTrue(all(tuple(row) == TEST_INPUT_FIELDS for row in self.inputs))

    def test_11_no_gold_or_privileged_test_fields(self) -> None:
        self.assertTrue(all(not _forbidden_keys(row) for row in self.inputs))

    def test_12_visible_history_json_valid(self) -> None:
        self.assertTrue(all(isinstance(row["visible_conversation_history"], list) for row in self.inputs))

    def test_13_deterministic_manifest_count(self) -> None:
        self.assertEqual(len(self.deterministic), 36)

    def test_14_b4_manifest_count(self) -> None:
        self.assertEqual(len(self.provider["B4"]), 36)

    def test_15_rag_specialist_manifest_count(self) -> None:
        self.assertEqual(len(self.provider["RAG_SPECIALIST"]), 36)

    def test_16_memory_specialist_manifest_count(self) -> None:
        self.assertEqual(len(self.provider["MEMORY_SPECIALIST"]), 36)

    def test_17_manifest_annotation_sets_identical(self) -> None:
        expected = {row["annotation_case_id"] for row in self.deterministic}
        self.assertTrue(all({row["annotation_case_id"] for row in rows} == expected for rows in self.provider.values()))

    def test_18_prompt_schema_hash_preservation(self) -> None:
        for stream, spec in PROVIDER_STREAMS.items():
            self.assertTrue(all(row["prompt_template_sha256"] == spec["prompt_sha256"] and row["response_schema_sha256"] == spec["schema_sha256"] for row in self.provider[stream]))

    def test_19_example_identity_and_order_preservation(self) -> None:
        for stream, spec in PROVIDER_STREAMS.items():
            self.assertTrue(all(row["final_full_dev_example_set_sha256"] == spec["example_set_sha256"] and len(row["final_full_dev_example_ids_in_order"]) == 8 for row in self.provider[stream]))

    def test_20_provider_model_and_retry_controls(self) -> None:
        for stream, spec in PROVIDER_STREAMS.items():
            self.assertTrue(all(row["model_snapshot"] == B4_MODEL and row["execution_controls"]["sdk_transport_retries"] == 0 and row["execution_controls"]["manual_retry_max"] == 1 and row["execution_controls"]["max_output_tokens"] == spec["max_output_tokens"] for row in self.provider[stream]))

    def test_21_provider_payload_test_input_exact(self) -> None:
        for rows in self.provider.values():
            for row in rows:
                current = json.loads(row["provider_request_payload"]["messages"][-1]["content"])
                self.assertEqual(set(current), set(PRIMARY_FIELDS))
                self.assertEqual(current, {field: row[field] for field in PRIMARY_FIELDS})

    def test_22_provider_payloads_have_no_test_gold(self) -> None:
        self.assertTrue(all(not _forbidden_keys(row["provider_request_payload"]) for rows in self.provider.values() for row in rows))

    def test_23_zero_predictions_in_manifests(self) -> None:
        self.assertTrue(all(row["execution_status"] == "NOT_EXECUTED" for row in self.deterministic))
        self.assertTrue(all(row["execution_status"] == "NOT_EXECUTED" and "prediction" not in row for rows in self.provider.values() for row in rows))

    def test_24_scoring_protocol_frozen(self) -> None:
        scoring = read_json(INTEGRATION_DIR / "final_test_scoring_protocol_v1.json")
        self.assertTrue(scoring["gold_access_gate"]["open_TEST_Gold_only_after_all_prediction_files_are_frozen"])
        self.assertEqual(scoring["current_scoring_status"], "NOT_EXECUTED")

    def test_25_comparison_hierarchy_frozen(self) -> None:
        hierarchy = read_json(INTEGRATION_DIR / "comparison_hierarchy_v1.json")
        self.assertEqual(hierarchy["P4_role"], "EXPLORATORY_POST_DEV_ABLATION")
        self.assertFalse(hierarchy["winner_designated"])

    def test_26_uncertainty_plan_frozen(self) -> None:
        plan = read_json(INTEGRATION_DIR / "uncertainty_reporting_plan_v1.json")
        self.assertEqual((plan["resampling_unit"], plan["seed"], plan["bootstrap_replicates"]), ("scenario_family_id", 20260831, 10000))
        self.assertFalse(plan["statistical_significance_promised"])

    def test_27_future_call_counts_and_ceilings(self) -> None:
        population = read_json(INTEGRATION_DIR / "test_execution_population_v1.json")
        self.assertEqual(population["deterministic"]["method_outputs"], 252)
        self.assertEqual(population["provider_totals"], {"logical_calls": 108, "physical_attempt_ceiling": 216})

    def test_28_zero_execution_evidence(self) -> None:
        population = read_json(INTEGRATION_DIR / "test_execution_population_v1.json")
        self.assertEqual(population["actual_stage4n"], {"predictions": 0, "provider_calls": 0, "scores": 0})

    def test_29_output_schemas_bind_all_methods(self) -> None:
        schema = read_json(INTEGRATION_DIR / "deterministic_prediction_output_schema_v1.json")
        methods = schema["properties"]["method_predictions"]["required"]
        self.assertEqual(tuple(methods), DETERMINISTIC_METHOD_IDS)

    def test_30_generated_hash_manifest(self) -> None:
        manifest = read_json(INTEGRATION_DIR / "STAGE4N_GENERATED_SHA256_MANIFEST.json")
        self.assertTrue(all(sha256_file(INTEGRATION_DIR / row["path"]) == row["sha256"] for row in manifest["files"]))

    def test_31_runners_are_future_authority_gated(self) -> None:
        for name in ("execute_provider_test.py", "execute_deterministic_test.py"):
            self.assertIn("RQ2_V2_FINAL_TEST_PREDICTION_EXECUTION_AUTHORIZED", (INTEGRATION_DIR / name).read_text(encoding="utf-8"))
        tree = ast.parse((INTEGRATION_DIR / "execute_provider_test.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module == "openai" for node in tree.body))

    def test_32_manifest_regeneration_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            build_all(output)
            names = ["deterministic_test_execution_manifest_v1.jsonl", *[spec["manifest"] for spec in PROVIDER_STREAMS.values()]]
            self.assertTrue(all((INTEGRATION_DIR / name).read_bytes() == (output / name).read_bytes() for name in names))

    def test_33_package_allowlists_and_no_gold(self) -> None:
        for role, items in package_specs().items():
            audit = validate_zip(PACKAGE_PATHS[role])
            self.assertEqual(audit["TEST_Gold_member_count"], 0)
            with zipfile.ZipFile(PACKAGE_PATHS[role]) as archive:
                self.assertEqual(archive.namelist(), [*sorted(items), "PACKAGE_MANIFEST.json"])
                self.assertTrue(all("gold" not in PurePosixPath(name).name.casefold() for name in archive.namelist()))

    def test_34_specialist_packages_are_stream_scoped(self) -> None:
        with zipfile.ZipFile(PACKAGE_PATHS["RAG_SPECIALIST"]) as archive:
            rag_names = archive.namelist()
        with zipfile.ZipFile(PACKAGE_PATHS["MEMORY_SPECIALIST"]) as archive:
            memory_names = archive.namelist()
        self.assertFalse(any("memory_specialist" in name or "track_i_b4" in name for name in rag_names))
        self.assertFalse(any("rag_specialist" in name or "track_i_b4" in name for name in memory_names))


if __name__ == "__main__":
    unittest.main()
