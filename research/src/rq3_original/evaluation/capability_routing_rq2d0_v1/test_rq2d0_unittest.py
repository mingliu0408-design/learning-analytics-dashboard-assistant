"""Contract and synthetic one-shot tests for RQ2-D0."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import (
    CHECKSUM_NAME,
    C1_R1_REVIEW_ZIP_SHA256,
    GOLD_BUNDLE_SHA256,
    HERE,
    P1_POLICY_ID,
    RESULT_BRANCH,
    RQ1_ROUTER,
    SAFE_AUTHORITY_COPY_ROOT,
    SCHEMA_AUTHORITY_MEMBER_SHA256,
    SCHEMA_AUTHORITY_ZIP_SHA256,
    STARTING_HEAD,
    TRACK_B_COLUMN_COUNT,
    TRACK_B_FILE_NAME,
    TRACK_B_ORDER_COMMITMENT,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
)
from .blinded_packet_builder import build_blinded_packets, parse_packet_bytes
from .capability_review_schema import HUMAN_FIELDS, capability_review_schema_document
from .contamination_contract import ContaminationError, audit_contamination
from .final_scope_contract import final_scope_contract_document
from .finalise_rq2d0 import expected_review_members, parse_output_checksums
from .packet_generation_state_machine import (
    LOCK_NAME,
    PacketGenerationError,
    execute_one_shot_packet_generation,
    state_machine_contract_document,
)
from .run_rq2d0 import SYNTHETIC_BLIND_KEY
from .starting_state import assert_d0_partition_allowed, verify_starting_state
from .statistical_contract import statistical_contract_document
from .synthetic_track_b_fixture import build_synthetic_track_b_csv
from .track_b_safe_authority import verify_safe_schema_package
from .track_b_schema_contract import (
    TrackBSchemaError,
    load_schema_authority,
    ordered_id_commitment,
    parse_track_b_csv_bytes,
)
from .validate_rq2d0 import (
    governed_text_leak_scan,
    protected_source_comparison,
    validate_authority_copies,
    validate_output_checksums,
    validate_python_ast,
    validate_safe_outputs,
)


class RQ2D0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preflight = verify_starting_state()
        cls.package_report, cls.package_payloads = verify_safe_schema_package()
        cls.authority, cls.profile, cls.template = load_schema_authority()
        cls.synthetic = build_synthetic_track_b_csv()
        cls.synthetic_sha = hashlib.sha256(cls.synthetic).hexdigest()
        cls.records, cls.schema_report = parse_track_b_csv_bytes(
            cls.synthetic,
            mode="SYNTHETIC_D0",
            expected_synthetic_sha256=cls.synthetic_sha,
        )
        cls.packet_a, cls.packet_b, cls.packet_manifest, cls.mapping = (
            build_blinded_packets(cls.records, blind_key=SYNTHETIC_BLIND_KEY)
        )
        cls.rows_a = parse_packet_bytes(cls.packet_a)
        cls.rows_b = parse_packet_bytes(cls.packet_b)
        cls.temp = tempfile.TemporaryDirectory(prefix="rq2d0-unittest-")
        root = Path(cls.temp.name)
        cls.source = root / "synthetic_48.csv"
        cls.output = root / "outputs"
        cls.source.write_bytes(cls.synthetic)
        cls.lock = execute_one_shot_packet_generation(
            cls.source,
            cls.output,
            execution_stage="RQ2-D0",
            expected_source_sha256=cls.synthetic_sha,
            blind_key=SYNTHETIC_BLIND_KEY,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_01_starting_identities(self) -> None:
        self.assertEqual(self.preflight["starting_head"], STARTING_HEAD)
        self.assertEqual(self.preflight["current_branch"], RESULT_BRANCH)

    def test_02_c1_r1_zip_and_checksums(self) -> None:
        self.assertEqual(
            self.preflight["review_zip_sha256"]["rq2c1_r1"], C1_R1_REVIEW_ZIP_SHA256
        )
        result = self.preflight["output_checksums"]
        self.assertTrue(any(value["checksum_count"] == 32 for value in result.values()))

    def test_03_gold_p1_c0_fixture_identities(self) -> None:
        frozen = self.preflight["frozen_identities"]
        self.assertEqual(frozen["gold_bundle_sha256"], GOLD_BUNDLE_SHA256)
        self.assertEqual(frozen["p1_policy_id"], P1_POLICY_ID)
        self.assertEqual(frozen["rq1_router"], RQ1_ROUTER)
        self.assertEqual(frozen["fixture_record_count"], 28)

    def test_04_track_b_safe_identity(self) -> None:
        source = self.package_report["source_identity"]
        self.assertEqual(source["sha256"], TRACK_B_SHA256)
        self.assertEqual(source["record_count"], TRACK_B_RECORD_COUNT)

    def test_05_safe_package_exact_identity(self) -> None:
        self.assertEqual(self.package_report["package_sha256"], SCHEMA_AUTHORITY_ZIP_SHA256)
        self.assertEqual(set(self.package_payloads), set(SCHEMA_AUTHORITY_MEMBER_SHA256))

    def test_06_no_raw_track_b_access_guard(self) -> None:
        with self.assertRaises(PermissionError):
            assert_d0_partition_allowed(TRACK_B_FILE_NAME)

    def test_07_safe_schema_authority_complete(self) -> None:
        self.assertEqual(len(self.authority["header_contract"]["exact_column_order"]), 47)
        self.assertEqual(len(self.profile["fields"]), 47)

    def test_08_missing_schema_authority_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises((TrackBSchemaError, FileNotFoundError)):
                load_schema_authority(Path(temporary))

    def test_09_exact_column_order(self) -> None:
        text = self.synthetic.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text, newline="")))
        self.assertEqual(header, self.authority["header_contract"]["exact_column_order"])

    def test_10_raw_format_contract(self) -> None:
        self.assertTrue(self.synthetic.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(self.synthetic.endswith(b"\r\n"))
        self.assertNotIn(b"\n", self.synthetic[3:].replace(b"\r\n", b""))

    def test_11_blank_template_header_only(self) -> None:
        self.assertEqual(self.template.count(b"\r\n"), 1)

    def test_12_index_column_absent(self) -> None:
        self.assertNotIn("index", self.authority["header_contract"]["exact_column_order"])
        self.assertFalse(self.schema_report["index_column_present"])

    def test_13_effective_overlay(self) -> None:
        self.assertEqual(self.schema_report["human_revised_query_override_count"], 0)
        self.assertEqual(self.schema_report["human_revised_history_override_count"], 1)
        self.assertIn("revised", self.records[0]["effective_conversation_history"][0]["content"])

    def test_14_record_order_commitment(self) -> None:
        ids = [row["raw_case_id"] for row in self.records]
        self.assertEqual(ordered_id_commitment(ids), TRACK_B_ORDER_COMMITMENT)

    def test_15_scenario_family_not_cluster(self) -> None:
        family = self.authority["grouping_contract"]["scenario_family_id"]
        self.assertEqual(family["unique_groups"], 48)
        self.assertFalse(family["suitable_as_repeated_cluster_unit"])

    def test_16_contrast_set_grouping(self) -> None:
        contrast = self.authority["grouping_contract"]["contrast_set_id"]
        self.assertEqual(contrast["unique_groups"], 24)
        self.assertEqual(contrast["records_per_group"], 2)

    def test_17_session_id_absent(self) -> None:
        self.assertFalse(self.authority["grouping_contract"]["session_id"]["present"])

    def test_18_capability_review_schema(self) -> None:
        schema = capability_review_schema_document()
        self.assertEqual(schema["required_human_reviewer_count"], 2)
        self.assertTrue(schema["third_human_adjudicator_required_for_all_disagreements"])

    def test_19_existing_intent_hidden(self) -> None:
        self.assertNotIn("human_final_label", self.rows_a[0])

    def test_20_model_outputs_hidden(self) -> None:
        self.assertNotIn("model_output", self.rows_a[0])
        self.assertFalse(self.packet_manifest["model_output_visible"])

    def test_21_reviewer_packets_same_set(self) -> None:
        self.assertEqual(
            {row["review_case_id"] for row in self.rows_a},
            {row["review_case_id"] for row in self.rows_b},
        )

    def test_22_reviewer_packet_orders_differ(self) -> None:
        self.assertNotEqual(
            [row["review_case_id"] for row in self.rows_a],
            [row["review_case_id"] for row in self.rows_b],
        )

    def test_23_all_human_fields_blank(self) -> None:
        self.assertTrue(
            all(not row[field] for row in self.rows_a for field in HUMAN_FIELDS)
        )

    def test_24_opaque_source_ids(self) -> None:
        self.assertTrue(all(row["review_case_id"].startswith("TBV1-") for row in self.rows_a))
        self.assertTrue(all("PV3-B-" not in row["review_case_id"] for row in self.rows_a))

    def test_25_no_automatic_intent_to_capability_gold(self) -> None:
        schema = capability_review_schema_document()
        self.assertFalse(schema["intent_to_capability_map_may_form_gold"])

    def test_26_state_lifecycle(self) -> None:
        self.assertEqual(
            self.lock["state_history"],
            [
                "ARMED",
                "OPENED",
                "CASE_BANK_PERSISTED",
                "REVIEW_PACKETS_PERSISTED",
                "COMPLETED",
            ],
        )

    def test_27_raw_open_read_exactly_once(self) -> None:
        self.assertEqual(self.lock["raw_asset_open_count"], 1)
        self.assertEqual(self.lock["raw_asset_read_count"], 1)

    def test_28_atomic_persistence_before_completed(self) -> None:
        self.assertTrue(self.lock["persisted"])
        self.assertEqual(self.lock["state"], "COMPLETED")
        self.assertTrue((self.output / "track_b_packet_manifest_v1.json").is_file())

    def test_29_retry_prohibited(self) -> None:
        with self.assertRaises(PacketGenerationError):
            execute_one_shot_packet_generation(
                self.source,
                self.output,
                execution_stage="RQ2-D0",
                expected_source_sha256=self.synthetic_sha,
                blind_key=SYNTHETIC_BLIND_KEY,
            )

    def test_30_no_post_completed_write(self) -> None:
        lock_path = self.output / LOCK_NAME
        before = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        with self.assertRaises(PacketGenerationError):
            execute_one_shot_packet_generation(
                self.source,
                self.output,
                execution_stage="RQ2-D0",
                expected_source_sha256=self.synthetic_sha,
                blind_key=SYNTHETIC_BLIND_KEY,
            )
        self.assertEqual(before, hashlib.sha256(lock_path.read_bytes()).hexdigest())

    def test_31_failure_lock_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "corrupt.csv"
            output = root / "outputs"
            source.write_bytes(self.synthetic[:-2] + b"\n")
            with self.assertRaises(Exception):
                execute_one_shot_packet_generation(
                    source,
                    output,
                    execution_stage="RQ2-D0",
                    expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    blind_key=SYNTHETIC_BLIND_KEY,
                )
            lock = json.loads((output / LOCK_NAME).read_text())
            self.assertTrue(lock["failure_lock_preserved"])
            self.assertFalse(lock["retry_permitted"])

    def _assert_contamination_blocked(self, query: str, history: list[dict[str, str]]) -> None:
        with self.assertRaises(ContaminationError):
            audit_contamination(
                self.records,
                {"RQ1_TRAIN": [{"query": query, "history": history}]},
            )

    def test_32_contamination_exact_overlap(self) -> None:
        row = self.records[0]
        self._assert_contamination_blocked(
            row["effective_current_query"], row["effective_conversation_history"]
        )

    def test_33_contamination_normalised_overlap(self) -> None:
        row = self.records[0]
        self._assert_contamination_blocked(
            "  SYNTHETIC, TRACK B SHAPED QUERY 01!!!  ", []
        )

    def test_34_contamination_context_overlap(self) -> None:
        row = self.records[1]
        self._assert_contamination_blocked(
            row["effective_current_query"], row["effective_conversation_history"]
        )

    def test_35_conflicting_duplicate_blocker(self) -> None:
        left = dict(self.records[0], gold_label="A")
        right = dict(self.records[0], raw_case_id="PV3-B-X", gold_label="B")
        with self.assertRaises(ContaminationError):
            audit_contamination([left, right], {})

    def test_36_primary_b0_b1_p1_scope(self) -> None:
        scope = final_scope_contract_document()
        self.assertEqual(len(scope["primary_capability_predictors"]), 3)
        self.assertEqual(scope["primary_metric"], "SIX_CAPABILITY_MACRO_F1")

    def test_37_p2_not_capability_predictor(self) -> None:
        self.assertFalse(final_scope_contract_document()["p2_is_capability_predictor"])

    def test_38_no_chunk_sufficiency_claim(self) -> None:
        scope = final_scope_contract_document()
        self.assertFalse(scope["track_b_rag_sufficiency_accuracy_evaluable"])

    def test_39_no_persistent_claim(self) -> None:
        scope = final_scope_contract_document()
        self.assertFalse(scope["track_b_persistent_retrieval_evaluable"])
        self.assertEqual(scope["persistent_execution_rule"], "STRICT_NO_OP")

    def test_40_statistical_seeds_and_metrics(self) -> None:
        contract = statistical_contract_document()
        self.assertEqual(contract["paired_bootstrap"]["resamples"], 50000)
        self.assertEqual(contract["paired_bootstrap"]["seed"], 20260828)
        self.assertEqual(contract["paired_sign_flip"]["monte_carlo_draws"], 100000)
        self.assertEqual(contract["paired_sign_flip"]["seed"], 20260829)

    def test_41_no_threshold_tuning(self) -> None:
        contract = statistical_contract_document()
        self.assertFalse(contract["threshold_selection_permitted"])
        self.assertFalse(contract["policy_selection_permitted"])

    def test_42_track_a_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            assert_d0_partition_allowed("TRACK_A")

    def test_43_track_b_raw_rejected_in_d0(self) -> None:
        with self.assertRaises(PermissionError):
            assert_d0_partition_allowed("evaluation/sealed/track_b/final.csv")

    def test_44_no_production_change(self) -> None:
        self.assertEqual(protected_source_comparison()["invalid_changed_file_count"], 0)

    def test_45_no_provider_or_network(self) -> None:
        self.assertEqual(self.preflight["provider_calls"], 0)
        self.assertFalse(self.preflight["network_access"])

    def test_46_double_build_byte_identical(self) -> None:
        self.assertEqual(self.synthetic, build_synthetic_track_b_csv())
        again = build_blinded_packets(self.records, blind_key=SYNTHETIC_BLIND_KEY)
        self.assertEqual((self.packet_a, self.packet_b), again[:2])

    def test_47_output_checksums(self) -> None:
        self.assertEqual(validate_output_checksums()["failure_count"], 0)

    def test_48_review_package_completeness_contract(self) -> None:
        referenced = set(parse_output_checksums())
        expected = set(expected_review_members())
        self.assertTrue(referenced <= expected)
        self.assertTrue(
            all(
                f"evaluation/capability_routing_rq2d0_v1/safe_schema_authority/{name}"
                in expected
                for name in SCHEMA_AUTHORITY_MEMBER_SHA256
            )
        )

    def test_49_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_50_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["invalid_changed_file_count"], 0)

    def test_51_authority_builder_disclosure(self) -> None:
        self.assertEqual(
            self.package_report["authority_builder_access"],
            "OUT_OF_BAND_SCHEMA_AUTHORITY_EXTRACTION",
        )
        self.assertFalse(self.package_report["codex_raw_access"])

    def test_52_no_real_lock_packet_or_labels(self) -> None:
        validation = json.loads((HERE / "rq2d0_synthetic_validation_v1.json").read_text())
        self.assertFalse(validation["real_lock_created"])
        self.assertFalse(validation["real_packets_generated"])
        self.assertFalse(validation["human_labels_formed"])

    def test_53_python_ast(self) -> None:
        self.assertGreaterEqual(validate_python_ast()["python_file_count"], 13)

    def test_54_safe_outputs(self) -> None:
        self.assertEqual(validate_safe_outputs()["status"], "PASS")

    def test_55_authority_copies(self) -> None:
        self.assertEqual(validate_authority_copies()["byte_identical_count"], 6)

    def test_56_state_machine_contract(self) -> None:
        contract = state_machine_contract_document()
        self.assertFalse(contract["d0_real_lock_created"])
        self.assertFalse(contract["d0_real_packets_generated"])

    def test_57_d1_requires_explicit_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED": ""}, clear=False
        ):
            with self.assertRaises(PacketGenerationError):
                execute_one_shot_packet_generation(
                    Path(temporary) / TRACK_B_FILE_NAME,
                    Path(temporary) / "outputs",
                    execution_stage="RQ2-D1_AUTHORISED",
                    expected_source_sha256=TRACK_B_SHA256,
                    blind_key=SYNTHETIC_BLIND_KEY,
                    contamination_references={},
                )


if __name__ == "__main__":
    unittest.main()
