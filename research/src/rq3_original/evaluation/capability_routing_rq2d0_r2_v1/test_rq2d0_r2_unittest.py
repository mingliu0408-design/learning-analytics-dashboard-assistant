"""Adversarial tests for all 47 required RQ2-D0-R2 contract properties."""

from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from evaluation.capability_routing_rq2d0_v1.synthetic_track_b_fixture import (
    build_synthetic_track_b_csv,
)
from evaluation.capability_routing_rq2d0_v1.track_b_schema_contract import (
    parse_track_b_csv_bytes,
)

from . import canonical_json_bytes, sha256_bytes
from .contamination_policy_v1_2 import (
    GROUPING_OVERLAP_FIELD,
    IDENTITY_OVERLAP_FIELDS,
    audit_hash_identities_v1_2,
)
from .exact_reference_validator import (
    ExactReferenceAuthorityError,
    validate_exact_authority_files,
)
from .frozen_reference_authority import (
    load_frozen_contamination_reference_authority_v1_1,
)
from .packet_generation_state_machine_v1_2 import (
    LOCK_NAME,
    StateMachineV1_2Error,
    execute_real_d1_one_shot_v1_2,
    execute_synthetic_d1_harness_v1_2,
    verify_synthetic_completed_authority_receipt_v1_2,
)
from .synthetic_exact_authority_fixture import (
    build_synthetic_exact_authority_fixture,
    mutated_receipt_authority,
    synthetically_reserialise_manifest,
)
from .track_b_grouping_identity import (
    SCENARIO_FAMILY_CLUSTER_ROLE,
    contrast_set_grouping_hash,
    grouping_hash_from_track_b_record,
    validate_track_b_contrast_groups,
)


class RQ2D0R2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="rq2d0-r2-tests-")
        cls.root = Path(cls._temporary.name)
        cls.fixture = build_synthetic_exact_authority_fixture(cls.root / "authority")
        cls.real_authority = load_frozen_contamination_reference_authority_v1_1()
        cls.raw = build_synthetic_track_b_csv()
        cls.source = cls.root / "synthetic-track-b.csv"
        cls.source.write_bytes(cls.raw)
        cls.output = cls.root / "synthetic-output"
        cls.lock = execute_synthetic_d1_harness_v1_2(
            cls.source,
            cls.output,
            expected_source_sha256=sha256_bytes(cls.raw),
            expected_source_size_bytes=len(cls.raw),
            synthetic_reference_authority=cls.fixture.authority,
            synthetic_key=sha256_bytes(b"RQ2-D0-R2-SYNTHETIC-KEY").encode("ascii")[:32],
        )
        cls.packet_manifest = json.loads(
            (cls.output / "track_b_packet_manifest_v1_2.json").read_text(
                encoding="utf-8"
            )
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _clone(self, name: str) -> tuple[Path, Path, Path]:
        root = self.root / name
        root.mkdir(parents=True, exist_ok=True)
        manifest = root / "manifest.json"
        bundle = root / "bundle.jsonl"
        source = root / "source.json"
        manifest.write_bytes(self.fixture.manifest_path.read_bytes())
        bundle.write_bytes(self.fixture.bundle_path.read_bytes())
        source.write_bytes(self.fixture.source_resolution_path.read_bytes())
        return manifest, bundle, source

    @staticmethod
    def _probe(manifest: Path, bundle: Path, source: Path):
        def probe(path: Path) -> tuple[bool, bool]:
            if path == bundle:
                return False, True
            if path in {manifest, source}:
                return True, False
            return False, False

        return probe

    def _validate(
        self,
        paths: tuple[Path, Path, Path],
        *,
        expected=None,
        probe=None,
    ):
        manifest, bundle, source = paths
        return validate_exact_authority_files(
            manifest_path=manifest,
            bundle_path=bundle,
            source_resolution_path=source,
            expected=expected or self.fixture.expected,
            governance_probe=probe or self._probe(manifest, bundle, source),
        )

    def _reference(self, partition: str):
        return next(
            row
            for row in self.fixture.authority.reference_rows
            if row["partition_id"] == partition
        )

    @staticmethod
    def _blank_track() -> dict[str, str]:
        return {
            "exact_query_hash": "f" * 64,
            "normalised_query_hash": "e" * 64,
            "query_history_hash": "d" * 64,
            "source_record_identity_hash": "c" * 64,
            "family_or_group_hash_if_available": "b" * 64,
        }

    # 1
    def test_01_frozen_manifest_bundle_and_source_pass(self) -> None:
        authority = load_frozen_contamination_reference_authority_v1_1()
        self.assertEqual(authority.bundle_record_count, 680)
        self.assertEqual(len(authority.partition_order), 8)

    # 2
    def test_02_exact_manifest_sha_mismatch_fails(self) -> None:
        paths = self._clone("t02")
        paths[0].write_bytes(paths[0].read_bytes() + b" ")
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 3
    def test_03_semantically_same_manifest_reserialisation_fails(self) -> None:
        paths = self._clone("t03")
        paths[0].write_bytes(synthetically_reserialise_manifest(paths[0]))
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 4
    def test_04_exact_bundle_sha_mismatch_fails(self) -> None:
        paths = self._clone("t04")
        payload = bytearray(paths[1].read_bytes())
        payload[10] ^= 1
        paths[1].write_bytes(bytes(payload))
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 5
    def test_05_structurally_valid_alternative_680_bundle_fails(self) -> None:
        alternative = build_synthetic_exact_authority_fixture(
            self.root / "t05-alt", query_suffix=" altered"
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            validate_exact_authority_files(
                manifest_path=alternative.manifest_path,
                bundle_path=alternative.bundle_path,
                source_resolution_path=alternative.source_resolution_path,
                expected=self.fixture.expected,
                governance_probe=alternative.governance_probe,
            )

    # 6
    def test_06_self_consistent_alternative_manifest_still_fails(self) -> None:
        alternative = build_synthetic_exact_authority_fixture(
            self.root / "t06-alt", query_suffix=" self-consistent"
        )
        self.assertEqual(len(alternative.authority.reference_rows), 680)
        with self.assertRaises(ExactReferenceAuthorityError):
            validate_exact_authority_files(
                manifest_path=alternative.manifest_path,
                bundle_path=alternative.bundle_path,
                source_resolution_path=alternative.source_resolution_path,
                expected=self.fixture.expected,
                governance_probe=alternative.governance_probe,
            )

    # 7
    def test_07_bundle_size_mismatch_fails(self) -> None:
        paths = self._clone("t07")
        paths[1].write_bytes(paths[1].read_bytes()[:-1])
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 8
    def test_08_total_count_mismatch_fails(self) -> None:
        paths = self._clone("t08")
        value = json.loads(paths[0].read_text())
        value["total_reference_records"] = 679
        payload = canonical_json_bytes(value)
        paths[0].write_bytes(payload)
        expected = replace(
            self.fixture.expected,
            manifest_sha256=sha256_bytes(payload),
            manifest_size_bytes=len(payload),
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, expected=expected)

    # 9
    def test_09_single_partition_count_mismatch_fails(self) -> None:
        paths = self._clone("t09")
        value = json.loads(paths[0].read_text())
        value["per_partition"][0]["observed_count"] = 317
        payload = canonical_json_bytes(value)
        paths[0].write_bytes(payload)
        expected = replace(
            self.fixture.expected,
            manifest_sha256=sha256_bytes(payload),
            manifest_size_bytes=len(payload),
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, expected=expected)

    # 10
    def test_10_single_partition_commitment_mismatch_fails(self) -> None:
        paths = self._clone("t10")
        fake = "0" * 64
        value = json.loads(paths[0].read_text())
        value["per_partition"][0]["partition_bundle_sha256"] = fake
        payload = canonical_json_bytes(value)
        paths[0].write_bytes(payload)
        parts = list(self.fixture.expected.partitions)
        parts[0] = replace(parts[0], raw_line_commitment=fake)
        expected = replace(
            self.fixture.expected,
            manifest_sha256=sha256_bytes(payload),
            manifest_size_bytes=len(payload),
            partitions=tuple(parts),
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, expected=expected)

    # 11
    def test_11_source_resolution_sha_mismatch_fails(self) -> None:
        paths = self._clone("t11")
        paths[2].write_bytes(paths[2].read_bytes() + b" ")
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 12
    def test_12_source_alias_mismatch_fails(self) -> None:
        paths = self._clone("t12")
        manifest = json.loads(paths[0].read_text())
        source = json.loads(paths[2].read_text())
        manifest["per_partition"][0]["source_alias"] = "SUBSTITUTE"
        source["sources"][0]["source_alias"] = "SUBSTITUTE"
        mb = canonical_json_bytes(manifest)
        sb = canonical_json_bytes(source)
        paths[0].write_bytes(mb)
        paths[2].write_bytes(sb)
        expected = replace(
            self.fixture.expected,
            manifest_sha256=sha256_bytes(mb),
            manifest_size_bytes=len(mb),
            source_resolution_sha256=sha256_bytes(sb),
            source_resolution_size_bytes=len(sb),
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, expected=expected)

    # 13
    def test_13_source_sha_mismatch_fails(self) -> None:
        paths = self._clone("t13")
        manifest = json.loads(paths[0].read_text())
        source = json.loads(paths[2].read_text())
        manifest["per_partition"][0]["source_sha256"] = "0" * 64
        source["sources"][0]["source_sha256"] = "0" * 64
        mb = canonical_json_bytes(manifest)
        sb = canonical_json_bytes(source)
        paths[0].write_bytes(mb)
        paths[2].write_bytes(sb)
        expected = replace(
            self.fixture.expected,
            manifest_sha256=sha256_bytes(mb),
            manifest_size_bytes=len(mb),
            source_resolution_sha256=sha256_bytes(sb),
            source_resolution_size_bytes=len(sb),
        )
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, expected=expected)

    def _symlink_rejected(self, index: int, name: str) -> None:
        paths = self._clone(name)
        target = paths[index].with_suffix(".target")
        target.write_bytes(paths[index].read_bytes())
        paths[index].unlink()
        paths[index].symlink_to(target)
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths)

    # 14-16
    def test_14_bundle_symlink_fails(self) -> None:
        self._symlink_rejected(1, "t14")

    def test_15_manifest_symlink_fails(self) -> None:
        self._symlink_rejected(0, "t15")

    def test_16_source_resolution_symlink_fails(self) -> None:
        self._symlink_rejected(2, "t16")

    # 17-20
    def test_17_bundle_tracked_fails(self) -> None:
        paths = self._clone("t17")
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, probe=lambda _path: (True, False))

    def test_18_bundle_not_ignored_fails(self) -> None:
        paths = self._clone("t18")
        manifest, bundle, source = paths
        probe = lambda path: (path in {manifest, source}, False)
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, probe=probe)

    def test_19_manifest_not_tracked_fails(self) -> None:
        paths = self._clone("t19")
        manifest, bundle, source = paths
        probe = lambda path: (path == source, path == bundle)
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, probe=probe)

    def test_20_source_resolution_not_tracked_fails(self) -> None:
        paths = self._clone("t20")
        manifest, bundle, _source = paths
        probe = lambda path: (path == manifest, path == bundle)
        with self.assertRaises(ExactReferenceAuthorityError):
            self._validate(paths, probe=probe)

    # 21-22
    def test_21_authority_failure_generates_no_key(self) -> None:
        module = "evaluation.capability_routing_rq2d0_r2_v1.packet_generation_state_machine_v1_2"
        with mock.patch(f"{module}._verify_real_prearm_before_authority", return_value={"status": "PASS"}), mock.patch(
            f"{module}.load_frozen_contamination_reference_authority_v1_1",
            side_effect=ExactReferenceAuthorityError("synthetic failure"),
        ), mock.patch(f"{module}.generate_fresh_key") as key_generator:
            with self.assertRaises(ExactReferenceAuthorityError):
                execute_real_d1_one_shot_v1_2(
                    Path("never-opened.csv"),
                    self.root / "never-output",
                    approved_head="SYNTHETIC",
                    schema_authority_sha256="SYNTHETIC",
                )
        key_generator.assert_not_called()
        self.assertFalse((self.root / "never-output").exists())

    def test_22_authority_failure_opens_no_raw_source(self) -> None:
        module = "evaluation.capability_routing_rq2d0_r2_v1.packet_generation_state_machine_v1_2"
        with mock.patch(f"{module}._verify_real_prearm_before_authority", return_value={"status": "PASS"}), mock.patch(
            f"{module}.load_frozen_contamination_reference_authority_v1_1",
            side_effect=ExactReferenceAuthorityError("synthetic failure"),
        ), mock.patch.object(Path, "open") as open_mock:
            with self.assertRaises(ExactReferenceAuthorityError):
                execute_real_d1_one_shot_v1_2(
                    Path("never-opened.csv"),
                    self.root / "never-output-2",
                    approved_head="SYNTHETIC",
                    schema_authority_sha256="SYNTHETIC",
                )
        open_mock.assert_not_called()

    # 23
    def test_23_real_signature_has_no_reference_injection(self) -> None:
        names = tuple(inspect.signature(execute_real_d1_one_shot_v1_2).parameters)
        self.assertEqual(
            names,
            ("source_path", "output_root", "approved_head", "schema_authority_sha256"),
        )
        self.assertFalse(any("reference" in name for name in names))
        self.assertNotIn("mode", names)

    def _single_field_audit(self, partition: str, field: str):
        target = self._blank_track()
        target[field] = self._reference(partition)[field]
        return audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )

    # 24-27
    def test_24_hard_exact_overlap_invalidates(self) -> None:
        result = self._single_field_audit("RQ1_TRAIN", "exact_query_hash")
        self.assertEqual(result["status"], "TRACK_B_FINAL_EVALUATION_INVALID")

    def test_25_hard_normalised_overlap_invalidates(self) -> None:
        result = self._single_field_audit("RQ1_TRAIN", "normalised_query_hash")
        self.assertEqual(result["hard_conflict_count"], 1)

    def test_26_hard_query_history_overlap_invalidates(self) -> None:
        result = self._single_field_audit("RQ1_TRAIN", "query_history_hash")
        self.assertEqual(result["hard_conflict_count"], 1)

    def test_27_hard_source_record_overlap_invalidates(self) -> None:
        result = self._single_field_audit(
            "RQ1_TRAIN", "source_record_identity_hash"
        )
        self.assertEqual(result["hard_conflict_count"], 1)

    # 28-29
    def test_28_hard_grouping_only_overlap_remains_pass(self) -> None:
        target = self._blank_track()
        target[GROUPING_OVERLAP_FIELD[1]] = self._reference("RQ1_TRAIN")[
            GROUPING_OVERLAP_FIELD[1]
        ]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(result["status"], "PASS")

    def test_29_hard_grouping_only_does_not_increment_hard_conflict(self) -> None:
        target = self._blank_track()
        target[GROUPING_OVERLAP_FIELD[1]] = self._reference("RQ1_TRAIN")[
            GROUPING_OVERLAP_FIELD[1]
        ]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(result["hard_conflict_count"], 0)
        self.assertEqual(result["grouping_overlap_case_count"], 1)

    # 30-32
    def test_30_sensitivity_identity_overlap_retained(self) -> None:
        result = self._single_field_audit("AUTHENTIC22", "exact_query_hash")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sensitivity_identity_overlap_case_count"], 1)

    def test_31_sensitivity_grouping_only_overlap_separate(self) -> None:
        target = self._blank_track()
        target[GROUPING_OVERLAP_FIELD[1]] = self._reference("AUTHENTIC22")[
            GROUPING_OVERLAP_FIELD[1]
        ]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(result["sensitivity_overlap_count"], 0)
        self.assertEqual(
            result["sensitivity_registry"][0]["overlap_class"],
            "GROUPING_ONLY_OVERLAP",
        )

    def test_32_identity_and_grouping_classification(self) -> None:
        reference = self._reference("AUTHENTIC22")
        target = self._blank_track()
        target["exact_query_hash"] = reference["exact_query_hash"]
        target[GROUPING_OVERLAP_FIELD[1]] = reference[GROUPING_OVERLAP_FIELD[1]]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(
            result["sensitivity_registry"][0]["overlap_class"],
            "IDENTITY_AND_GROUPING_OVERLAP",
        )

    # 33-34
    def test_33_same_track_case_in_two_hard_partitions_counts_once(self) -> None:
        target = self._blank_track()
        target["exact_query_hash"] = self._reference("RQ1_TRAIN")[
            "exact_query_hash"
        ]
        target["normalised_query_hash"] = self._reference("RQ1_DEV")[
            "normalised_query_hash"
        ]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(result["hard_conflict_count"], 1)

    def test_34_partition_level_hard_events_preserve_two(self) -> None:
        target = self._blank_track()
        target["exact_query_hash"] = self._reference("RQ1_TRAIN")[
            "exact_query_hash"
        ]
        target["normalised_query_hash"] = self._reference("RQ1_DEV")[
            "normalised_query_hash"
        ]
        result = audit_hash_identities_v1_2(
            [target], self.fixture.authority.reference_rows
        )
        self.assertEqual(result["hard_identity_overlap_event_count"], 2)

    # 35-38
    def test_35_scenario_family_change_does_not_change_group_hash(self) -> None:
        left = {"contrast_set_id": "CS-1", "scenario_family_id": "SF-1"}
        right = {"contrast_set_id": "CS-1", "scenario_family_id": "SF-2"}
        self.assertEqual(
            grouping_hash_from_track_b_record(left),
            grouping_hash_from_track_b_record(right),
        )

    def test_36_contrast_set_change_changes_group_hash(self) -> None:
        self.assertNotEqual(
            contrast_set_grouping_hash("CS-1"), contrast_set_grouping_hash("CS-2")
        )

    def test_37_twenty_four_contrast_groups_of_two(self) -> None:
        records, _ = parse_track_b_csv_bytes(
            self.raw,
            mode="SYNTHETIC_D0",
            expected_synthetic_sha256=sha256_bytes(self.raw),
        )
        report = validate_track_b_contrast_groups(records)
        self.assertEqual(report["contrast_set_group_count"], 24)
        self.assertEqual(report["records_per_contrast_set"], 2)

    def test_38_scenario_family_cannot_be_bootstrap_cluster(self) -> None:
        self.assertEqual(
            SCENARIO_FAMILY_CLUSTER_ROLE, "NOT_ELIGIBLE_UNIQUE_PER_RECORD"
        )

    # 39-43
    def test_39_armed_completed_receipt_has_manifest_sha(self) -> None:
        self.assertEqual(
            self.lock["reference_manifest_file_sha256"],
            self.fixture.authority.manifest_file_sha256,
        )

    def test_40_armed_completed_receipt_has_bundle_sha(self) -> None:
        self.assertEqual(
            self.lock["reference_bundle_file_sha256"],
            self.fixture.authority.bundle_file_sha256,
        )

    def test_41_armed_completed_receipt_has_source_resolution_sha(self) -> None:
        self.assertEqual(
            self.lock["reference_source_resolution_file_sha256"],
            self.fixture.authority.source_resolution_file_sha256,
        )

    def test_42_armed_completed_receipt_has_eight_partition_commitments(self) -> None:
        self.assertEqual(len(self.lock["partition_commitments"]), 8)

    def test_43_armed_completed_receipt_has_combined_commitment(self) -> None:
        self.assertEqual(
            self.lock["reference_authority_commitment"],
            self.fixture.authority.authority_commitment,
        )

    # 44-45
    def test_44_packet_manifest_copies_same_authority_receipt(self) -> None:
        self.assertEqual(
            self.packet_manifest["reference_authority_receipt"],
            self.fixture.authority.safe_receipt(),
        )

    def test_45_completed_lock_copies_same_authority_receipt(self) -> None:
        receipt = self.fixture.authority.safe_receipt()
        self.assertTrue(all(self.lock[key] == value for key, value in receipt.items()))
        self.assertEqual(self.lock["state"], "COMPLETED")

    # 46-47
    def test_46_synthetic_authority_cannot_enter_real_receipt(self) -> None:
        real_parameters = inspect.signature(
            execute_real_d1_one_shot_v1_2
        ).parameters
        self.assertNotIn("synthetic_reference_authority", real_parameters)
        self.assertEqual(self.lock["execution_mode"], "SYNTHETIC_D0_R2_ONLY")
        self.assertTrue(
            self.lock["reference_bundle_relative_path"].startswith(
                "SYNTHETIC_TEST_ONLY/"
            )
        )

    def test_47_post_completed_authority_mutation_rejected(self) -> None:
        with self.assertRaises(StateMachineV1_2Error):
            verify_synthetic_completed_authority_receipt_v1_2(
                self.output,
                mutated_receipt_authority(self.fixture.authority),
            )

    # Additional explicit contract checks used by final validation.
    def test_48_identity_fields_are_exactly_four(self) -> None:
        self.assertEqual(
            tuple(IDENTITY_OVERLAP_FIELDS.values()),
            (
                "exact_query_hash",
                "normalised_query_hash",
                "query_history_hash",
                "source_record_identity_hash",
            ),
        )

    def test_49_grouping_field_is_not_an_identity_field(self) -> None:
        self.assertNotIn(
            GROUPING_OVERLAP_FIELD[1], set(IDENTITY_OVERLAP_FIELDS.values())
        )

    def test_50_real_authority_combined_commitment_is_stable(self) -> None:
        again = load_frozen_contamination_reference_authority_v1_1()
        self.assertEqual(
            again.authority_commitment, self.real_authority.authority_commitment
        )

    def test_51_synthetic_double_run_byte_identical(self) -> None:
        second = self.root / "second-run" / "synthetic-output"
        execute_synthetic_d1_harness_v1_2(
            self.source,
            second,
            expected_source_sha256=sha256_bytes(self.raw),
            expected_source_size_bytes=len(self.raw),
            synthetic_reference_authority=self.fixture.authority,
            synthetic_key=sha256_bytes(b"RQ2-D0-R2-SYNTHETIC-KEY").encode("ascii")[:32],
        )
        names_a = sorted(path.name for path in self.output.iterdir())
        names_b = sorted(path.name for path in second.iterdir())
        self.assertEqual(names_a, names_b)
        self.assertTrue(
            all(
                (self.output / name).read_bytes() == (second / name).read_bytes()
                for name in names_a
            )
        )


if __name__ == "__main__":
    unittest.main()
