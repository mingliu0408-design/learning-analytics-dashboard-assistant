"""Contract, synthetic failure-path, and safe-output tests for RQ2-D0-R1."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import (
    C1_R1_REVIEW_ZIP_SHA256,
    D0_HEAD,
    D0_REVIEW_ZIP_SHA256,
    HARD_PARTITIONS,
    HERE,
    LOCAL_REFERENCE_BUNDLE,
    NORMALISER_CONTRACT_ID,
    REFERENCE_PARTITION_COUNTS,
    REFERENCE_TOTAL_COUNT,
    RESULT_BRANCH,
    ROOT,
    SAFE_SCHEMA_ZIP_SHA256,
)
from .blinding_key_governance import (
    BlindingKeyError,
    assert_real_mode_key_input,
    build_opaque_ids,
    generate_fresh_key,
    key_commitment,
    persist_key,
)
from .contamination_reference_builder import parse_bundle_bytes
from .contamination_reference_source import SPECS
from .contamination_reference_validator import validate_reference_bundle
from .durable_atomic_persistence import atomic_write_durable, verify_durable_payload
from .legacy_escrow_access_guard import EscrowAccessDenied, assert_escrow_access_authorised
from .legacy_escrow_contract import HIDDEN_LEGACY_FIELDS
from .packet_generation_state_machine_v1_1 import STATE_ORDER
from .prearm_output_guard import PrearmOutputError, assert_output_root_empty
from .validate_rq2d0_r1 import (
    expected_review_members,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    validate_local_bundle,
    validate_output_checksums,
    validate_python_ast,
    validate_safe_outputs,
)


class RQ2D0R1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preflight = json.loads(
            (HERE / "rq2d0_r1_preflight_report_v1.json").read_text(encoding="utf-8")
        )
        cls.sources = json.loads(
            (HERE / "contamination_reference_source_resolution_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.manifest = json.loads(
            (HERE / "track_b_contamination_reference_manifest_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.policy = json.loads(
            (HERE / "track_b_contamination_policy_v1_1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.escrow = json.loads(
            (HERE / "track_b_legacy_escrow_contract_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.key_contract = json.loads(
            (HERE / "track_b_blinding_key_contract_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.prearm = json.loads(
            (HERE / "track_b_prearm_output_contract_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.state = json.loads(
            (HERE / "track_b_packet_generation_state_machine_v1_1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.receipt = json.loads(
            (HERE / "track_b_durable_receipt_contract_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.synthetic = json.loads(
            (HERE / "rq2d0_r1_synthetic_validation_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.bundle = LOCAL_REFERENCE_BUNDLE.read_bytes()
        cls.bundle_rows = parse_bundle_bytes(cls.bundle)

    def test_01_starting_identities(self) -> None:
        self.assertEqual(self.preflight["starting_head"], D0_HEAD)
        self.assertEqual(self.preflight["target_branch"], RESULT_BRANCH)
        self.assertTrue(self.preflight["starting_worktree_clean"])

    def test_02_d0_zip_and_checksums(self) -> None:
        self.assertEqual(
            self.preflight["review_zip_sha256"]["rq2d0"], D0_REVIEW_ZIP_SHA256
        )
        self.assertEqual(
            self.preflight["output_checksums"]["rq2d0"]["checksum_count"], 36
        )

    def test_03_c1_r1_and_schema_identities(self) -> None:
        zips = self.preflight["review_zip_sha256"]
        self.assertEqual(zips["rq2c1_r1"], C1_R1_REVIEW_ZIP_SHA256)
        self.assertEqual(zips["safe_schema"], SAFE_SCHEMA_ZIP_SHA256)
        self.assertEqual(
            self.preflight["output_checksums"]["rq2c1_r1"]["checksum_count"], 32
        )

    def test_04_eight_partitions_complete(self) -> None:
        self.assertEqual(self.sources["partition_count"], 8)
        self.assertEqual(self.sources["total_record_count"], REFERENCE_TOTAL_COUNT)
        self.assertTrue(all(row["resolution_status"] == "PASS" for row in self.sources["sources"]))

    def test_05_expected_partition_counts(self) -> None:
        observed = {
            row["partition_id"]: row["observed_count"] for row in self.sources["sources"]
        }
        self.assertEqual(observed, REFERENCE_PARTITION_COUNTS)

    def test_06_source_hashes(self) -> None:
        for row in self.sources["sources"]:
            self.assertEqual(row["source_sha256"], SPECS[row["partition_id"]].expected_sha256)

    def test_07_normaliser_identity(self) -> None:
        self.assertEqual(self.manifest["normaliser_contract_id"], NORMALISER_CONTRACT_ID)

    def test_08_reference_bundle_validation(self) -> None:
        report = validate_reference_bundle(self.bundle, self.manifest)
        self.assertEqual(report["record_count"], 680)
        self.assertEqual(report["unique_opaque_reference_count"], 680)

    def test_09_reference_bundle_is_hash_only(self) -> None:
        allowed = {
            "partition_id",
            "opaque_reference_id",
            "exact_query_hash",
            "normalised_query_hash",
            "query_history_hash",
            "source_record_identity_hash",
            "family_or_group_hash_if_available",
        }
        self.assertTrue(all(set(row) <= allowed for row in self.bundle_rows))

    def test_10_reference_bundle_ignored_untracked(self) -> None:
        report = validate_local_bundle()
        self.assertTrue(report["ignored"])
        self.assertFalse(report["tracked"])

    def test_11_empty_reference_rejection(self) -> None:
        self.assertTrue(self.synthetic["empty_all_reference_rejected"])
        self.assertTrue(self.synthetic["single_empty_reference_rejected"])

    def test_12_count_and_source_hash_rejection(self) -> None:
        self.assertTrue(self.synthetic["wrong_reference_count_rejected"])
        self.assertTrue(self.synthetic["source_hash_mismatch_rejected"])

    def test_13_hard_partition_exact_overlap(self) -> None:
        self.assertTrue(self.synthetic["hard_exact"])

    def test_14_hard_partition_normalised_overlap(self) -> None:
        self.assertTrue(self.synthetic["hard_normalised"])

    def test_15_hard_partition_query_history_overlap(self) -> None:
        self.assertTrue(self.synthetic["hard_query_history"])

    def test_16_sensitivity_overlap_retained(self) -> None:
        self.assertTrue(self.synthetic["sensitivity_retained"])
        self.assertEqual(set(self.policy["hard_final_independence_partitions"]), set(HARD_PARTITIONS))

    def test_17_output_directory_empty_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outputs"
            self.assertEqual(assert_output_root_empty(path)["output_root_state"], "ABSENT")
            path.mkdir()
            (path / ".hidden").write_text("x")
            with self.assertRaises(PrearmOutputError):
                assert_output_root_empty(path)
        self.assertEqual(self.synthetic["output_directory_rejection_raw_open_count"], 0)

    def test_18_fresh_key_generation(self) -> None:
        self.assertEqual(len(generate_fresh_key()), 32)
        self.assertEqual(self.synthetic["fresh_key_length_bytes"], 32)

    def test_19_key_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "key.bin"
            persist_key(path, b"K" * 32)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(self.synthetic["fresh_key_file_mode_octal"], "0600")

    def test_20_key_commitment(self) -> None:
        self.assertEqual(key_commitment(b"K" * 32), key_commitment(b"K" * 32))
        self.assertTrue(self.synthetic["fresh_key_commitment_reproducible"])
        self.assertFalse(self.synthetic["raw_key_in_safe_output"])

    def test_21_fixed_key_rejected_in_real_mode(self) -> None:
        with self.assertRaises(BlindingKeyError):
            assert_real_mode_key_input(supplied_key=b"K" * 32)
        self.assertFalse(self.key_contract["fixed_key_permitted_in_real_mode"])

    def test_22_opaque_ids_no_collision(self) -> None:
        values = build_opaque_ids([f"ID-{index}" for index in range(48)], b"Z" * 32)
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(self.synthetic["opaque_id_unique_count"], 48)

    def test_23_legacy_escrow_schema(self) -> None:
        self.assertEqual(self.escrow["record_count"], 48)
        self.assertEqual(set(self.escrow["hidden_fields"]), set(HIDDEN_LEGACY_FIELDS))
        self.assertEqual(self.synthetic["escrow_record_count"], 48)

    def test_24_legacy_escrow_access_guard(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EscrowAccessDenied):
                assert_escrow_access_authorised()
        with patch.dict(os.environ, {"TRACK_B_CAPABILITY_GOLD_FROZEN": "true"}, clear=True):
            assert_escrow_access_authorised()
        self.assertTrue(self.synthetic["escrow_pre_gold_read_rejected"])

    def test_25_durable_state_transitions(self) -> None:
        self.assertEqual(tuple(self.state["state_order"]), STATE_ORDER)
        self.assertEqual(tuple(self.synthetic["state_history"]), STATE_ORDER)
        self.assertEqual(self.synthetic["state"], "COMPLETED")

    def test_26_atomic_durable_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.json"
            receipt = atomic_write_durable(path, b"{}\n")
            self.assertEqual(verify_durable_payload(path, receipt), b"{}\n")

    def test_27_lock_receipt_contents(self) -> None:
        self.assertTrue(self.synthetic["all_required_output_receipts"])
        self.assertIn("hidden_legacy_escrow", self.synthetic["output_receipt_roles"])
        self.assertIn("contamination_audit_summary", self.synthetic["output_receipt_roles"])

    def test_28_escrow_and_audit_before_packets(self) -> None:
        self.assertTrue(self.synthetic["escrow_persisted_before_packets"])
        self.assertTrue(self.synthetic["audit_persisted_before_packets"])
        self.assertTrue(self.synthetic["packet_legacy_fields_hidden"])

    def test_29_failure_lock_preservation(self) -> None:
        self.assertTrue(self.synthetic["failure_observed"])
        self.assertTrue(self.synthetic["failure_lock_preserved"])
        self.assertFalse(self.synthetic["failure_retry_permitted"])

    def test_30_retry_and_post_completed_write_rejected(self) -> None:
        self.assertTrue(self.synthetic["retry_rejected"])
        self.assertTrue(self.synthetic["post_completed_lock_unchanged"])

    def test_31_no_raw_track_b_access_or_real_outputs(self) -> None:
        self.assertEqual(self.synthetic["real_track_b_access_count"], 0)
        self.assertFalse(self.synthetic["real_d1_lock_created"])
        self.assertFalse(self.synthetic["real_packets_created"])
        self.assertFalse(self.synthetic["human_labels_formed"])

    def test_32_no_provider_or_network(self) -> None:
        self.assertEqual(self.synthetic["provider_calls"], 0)
        self.assertFalse(self.synthetic["network_access"])

    def test_33_double_build_byte_identical(self) -> None:
        self.assertTrue(self.synthetic["double_build_byte_identical"])

    def test_34_python_ast(self) -> None:
        self.assertGreaterEqual(validate_python_ast()["python_file_count"], 16)

    def test_35_safe_outputs(self) -> None:
        self.assertEqual(validate_safe_outputs()["status"], "PASS")

    def test_36_output_checksums(self) -> None:
        self.assertEqual(validate_output_checksums()["failure_count"], 0)

    def test_37_review_package_completeness_contract(self) -> None:
        expected = set(expected_review_members())
        self.assertTrue(set(parse_output_checksums()) <= expected)
        self.assertNotIn(str(LOCAL_REFERENCE_BUNDLE.relative_to(ROOT)), expected)

    def test_38_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_39_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["invalid_changed_file_count"], 0)

    def test_40_reference_manifest_and_bundle_bound(self) -> None:
        self.assertTrue(self.synthetic["reference_manifest_hash_bound_in_lock"])
        self.assertTrue(self.synthetic["reference_bundle_hash_bound_in_lock"])

    def test_41_audit_and_escrow_receipts_bound(self) -> None:
        self.assertTrue(self.synthetic["audit_summary_hash_bound_in_completed_lock"])
        self.assertTrue(self.synthetic["escrow_receipt_bound_in_completed_lock"])

    def test_42_real_reference_double_build(self) -> None:
        self.assertTrue(self.sources["double_build_byte_identical"])


if __name__ == "__main__":
    unittest.main()
