"""Contract tests for the RQ2-D3-R3 D4 execution-integrity repair."""

from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from evaluation.capability_routing_rq2d3_r2_v1 import rq2d4_global_one_shot_contract as legacy

from . import (
    CAPABILITIES,
    EFFECTIVE_CONTRACT_ID,
    HERE,
    PREDICTOR_CONTRACT_ID,
    ROOT,
    START_HEAD,
    START_PARENT,
    TARGET_BRANCH,
    sha256_file,
)
from .bound_prediction_v1_1 import (
    bind_prediction_v1_1,
    validate_bound_prediction_v1_1,
)
from .development_reexecution_parity_v1_1 import (
    require_prediction_level_authority_v1_1,
)
from .durable_local_artifact import (
    DurableArtifactError,
    json_object_validator,
    publish_durable_artifact_v1_1,
    verify_artifact_receipt_v1_1,
)
from .effective_d4_contract_v1_1 import (
    EffectiveD4AuthorityError,
    _verify_gold_metadata_manifest,
    _verify_r3_code_and_contract_checksums,
    effective_d4_contract_document_v1_1,
    execute_real_rq2d4_one_shot_v1_1,
)
from .feature_fingerprint_v1_1 import build_feature_row_v1_1
from .fixed_rq2d4_paths_v1_1 import fixed_path_contract_document_v1_1
from .fixed_statistical_execution_v1_1 import (
    fixed_statistical_contract_document_v1_1,
    run_fixed_track_b_statistics_v1_1,
)
from .frozen_capability_predictor_core_v1_1 import CoreRoutingContentV1_1
from .frozen_complete_metric_binding_v1_1 import (
    load_frozen_complete_track_b_metric_binding_v1_1,
)
from .global_lock_receipt_v1_1 import (
    GlobalLockError,
    fail_global_lock_v1_1,
    read_global_lock_v1_1,
    reserve_global_lock_v1_1,
    verify_global_lock_chain_v1_1,
)
from .legacy_entrypoint_revocation import (
    AFTER_SHA256,
    BEFORE_SHA256,
    ENTRYPOINTS,
    legacy_entrypoint_inventory_v1,
)
from .p2_secondary_scope_decision import p2_secondary_scope_document_v1_1
from .rq2d4_state_machine_v1_1 import STATES, require_successor
from .starting_state import validate_starting_state_v1
from .synthetic_d4_integrity_fixture import synthetic_core_prediction_v1_1
from .track_b_feature_extractor_worker_v1_1 import main as extractor_main
from .track_b_metric_worker_v1_1 import main as metric_main
from .track_b_predictor_worker_v1_1 import main as predictor_main
from .validate_rq2d3_r3 import (
    CHECKSUM_PATH,
    DOC_NAMES,
    OUTPUT_NAMES,
    PYTHON_NAMES,
    REVIEW_ZIP_NAME,
    checksum_targets,
)
from .worker_execution_authority_v1_1 import (
    FEATURE_ROLE,
    METRIC_ROLE,
    PREDICTOR_ROLE,
    ROLES,
    WorkerDescriptorV1_1,
    credential_commitment_v1_1,
    read_credential_once_v1_1,
)


class RQ2D3R3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.start = validate_starting_state_v1()
        cls.inventory = legacy_entrypoint_inventory_v1()
        cls.authority = json.loads(
            (HERE / "rq2d3_r3_execution_integrity_authority_v1.json").read_text()
        )
        cls.effective = json.loads(
            (HERE / "track_b_effective_d4_contract_v1_1.json").read_text()
        )
        cls.worker = json.loads(
            (HERE / "track_b_worker_authority_contract_v1_1.json").read_text()
        )
        cls.durable = json.loads(
            (HERE / "track_b_durable_artifact_contract_v1_1.json").read_text()
        )
        cls.receipt = json.loads(
            (HERE / "track_b_stage_receipt_contract_v1_1.json").read_text()
        )
        cls.global_lock = json.loads(
            (HERE / "track_b_global_lock_receipt_contract_v1_1.json").read_text()
        )
        cls.fingerprint = json.loads(
            (HERE / "track_b_feature_fingerprint_contract_v1_1.json").read_text()
        )
        cls.bound = json.loads(
            (HERE / "track_b_bound_prediction_contract_v1_1.json").read_text()
        )
        cls.firewall = json.loads(
            (HERE / "track_b_runtime_firewall_contract_v1_1.json").read_text()
        )
        cls.metric = json.loads(
            (HERE / "track_b_complete_metric_binding_contract_v1_1.json").read_text()
        )
        cls.statistics = json.loads(
            (HERE / "track_b_fixed_statistical_execution_contract_v1_1.json").read_text()
        )
        cls.parity = json.loads(
            (HERE / "rq2d3_r3_development_reexecution_parity_v1.json").read_text()
        )
        cls.smoke = json.loads(
            (HERE / "rq2d3_r3_prearm_runtime_smoke_v1.json").read_text()
        )
        cls.synthetic = json.loads(
            (HERE / "rq2d3_r3_synthetic_validation_v1.json").read_text()
        )
        cls.validation = json.loads(
            (HERE / "rq2d3_r3_validation_report_v1.json").read_text()
        )
        cls.p2 = p2_secondary_scope_document_v1_1()

    # Starting identities and immutable authorities.
    def test_001_starting_head(self):
        self.assertEqual(self.start["starting_head"], START_HEAD)

    def test_002_starting_parent(self):
        self.assertEqual(self.start["starting_parent"], START_PARENT)

    def test_003_target_branch(self):
        self.assertEqual(self.start["target_branch"], TARGET_BRANCH)

    def test_004_r2_review_and_checksums(self):
        self.assertEqual(self.start["r2_unchanged_checksum_entries"], "40/40 PASS")

    def test_005_r1_review_and_checksums(self):
        self.assertEqual(self.start["r1_output_checksums"], "20/20 PASS")

    def test_006_gold_bundle_unchanged(self):
        self.assertTrue(self.validation["d2b_gold_unchanged"])

    def test_007_grouping_unchanged(self):
        self.assertTrue(self.validation["d3_r2_grouping_unchanged"])

    def test_008_statistics_unchanged(self):
        self.assertTrue(self.validation["d3_r1_statistics_unchanged"])

    def test_009_metric_identity(self):
        self.assertEqual(
            self.metric["implementation_sha256"],
            "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138",
        )

    def test_010_user_authority(self):
        self.assertEqual(
            self.authority["authority_type"],
            "USER_EXPLICIT_FINAL_PRE_D4_EXECUTION_INTEGRITY_REPAIR",
        )

    # Legacy-entry revocation.
    def test_011_legacy_inventory_complete(self):
        self.assertEqual(
            {row["entrypoint"] for row in self.inventory["entrypoints"]}, set(ENTRYPOINTS)
        )

    def test_012_legacy_before_after_hash(self):
        self.assertEqual(
            (self.inventory["before_sha256"], self.inventory["after_sha256"]),
            (BEFORE_SHA256, AFTER_SHA256),
        )

    def test_013_legacy_parent_blocked_before_open(self):
        with mock.patch("os.open", side_effect=AssertionError("unexpected open")):
            with self.assertRaises(legacy.D4ExecutionAuthorityError):
                legacy.execute_real_rq2d4_one_shot_v1(approved_head="x")

    def test_014_legacy_extractor_blocked_before_open(self):
        with mock.patch("os.open", side_effect=AssertionError("unexpected open")):
            with self.assertRaises(legacy.D4ExecutionAuthorityError):
                legacy._real_extractor_worker()

    def test_015_legacy_predictor_blocked_before_open(self):
        with mock.patch("os.open", side_effect=AssertionError("unexpected open")):
            with self.assertRaises(legacy.D4ExecutionAuthorityError):
                legacy._real_predictor_worker()

    def test_016_legacy_metric_blocked_before_open(self):
        with mock.patch("os.open", side_effect=AssertionError("unexpected open")):
            with self.assertRaises(legacy.D4ExecutionAuthorityError):
                legacy._real_metric_worker()

    def test_017_legacy_fixed_worker_blocked(self):
        with self.assertRaises(legacy.D4ExecutionAuthorityError):
            legacy._run_fixed_worker("extractor")

    def test_018_legacy_cli_blocked(self):
        with self.assertRaises(legacy.D4ExecutionAuthorityError):
            legacy.main()

    def test_018a_legacy_synthetic_utility_preserved(self):
        from evaluation.capability_routing_rq2d3_r2_v1.synthetic_final_harness import (
            run_synthetic_final_harness_v1,
        )

        self.assertTrue(callable(run_synthetic_final_harness_v1))

    # Effective contract and pre-arm runtime.
    def test_019_effective_entry_signature(self):
        self.assertEqual(
            tuple(inspect.signature(execute_real_rq2d4_one_shot_v1_1).parameters),
            ("approved_head",),
        )

    def test_020_effective_contract_identity(self):
        self.assertEqual(self.effective["execution_contract_id"], EFFECTIVE_CONTRACT_ID)

    def test_021_no_path_or_stat_override(self):
        self.assertIn("input_path", self.effective["forbidden_parameters"])
        self.assertIn("seed", self.effective["forbidden_parameters"])

    def test_022_real_entry_not_authorised_now(self):
        with mock.patch.dict(os.environ, {"RQ2D4_TRACK_B_FINAL_EVALUATION_AUTHORISED": ""}):
            with self.assertRaises(EffectiveD4AuthorityError):
                execute_real_rq2d4_one_shot_v1_1(approved_head="x")

    def test_023_fixed_paths_no_override(self):
        contract = fixed_path_contract_document_v1_1()
        self.assertFalse(contract["caller_override_allowed"])
        self.assertFalse(contract["environment_override_allowed"])

    def test_024_real_targets_not_created(self):
        self.assertFalse((ROOT / "evaluation/capability_routing_rq2d4_v1/local_one_shot").exists())
        self.assertFalse((ROOT / "evaluation/capability_routing_rq2d4_v1/local_control").exists())

    def test_025_prearm_model_tokenizer_loaded(self):
        self.assertTrue(self.smoke["model_loaded"] and self.smoke["tokenizer_loaded"])

    def test_026_prearm_embeddings(self):
        self.assertEqual(self.smoke["candidate_embedding_shape"], [62, 768])

    def test_027_prearm_adapters(self):
        self.assertTrue(
            self.smoke["b0_adapter_constructed"]
            and self.smoke["b1_adapter_constructed"]
            and self.smoke["p1_adapter_constructed"]
        )

    def test_028_prearm_synthetic_query(self):
        self.assertTrue(self.smoke["synthetic_smoke_output_valid"])

    def test_029_prearm_offline(self):
        self.assertEqual(
            (self.smoke["network_attempts"], self.smoke["provider_calls"], self.smoke["model_downloads"]),
            (0, 0, 0),
        )

    def test_030_prearm_lstat_only(self):
        self.assertEqual(self.smoke["pre_reservation_content_read_count"], 0)
        self.assertFalse(self.smoke["global_reservation_created"])

    def test_030a_future_prearm_verifies_r3_and_gold_metadata(self):
        self.assertTrue(self.effective["r3_output_checksums_verified_before_reservation"])
        self.assertTrue(self.effective["d2b_gold_metadata_verified_before_reservation"])

    def test_030b_future_prearm_checksum_gate_is_executable(self):
        self.assertEqual(_verify_r3_code_and_contract_checksums(), 53)
        self.assertEqual(_verify_gold_metadata_manifest()["record_count"], 48)

    # Worker credentials and direct invocation.
    def test_031_worker_roles(self):
        self.assertEqual(tuple(self.worker["roles"]), ROLES)

    def test_032_role_specific_credential_commitment(self):
        descriptor = WorkerDescriptorV1_1(
            FEATURE_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED", "e", "h", "l", "c"
        )
        first = credential_commitment_v1_1(b"a" * 32, descriptor)
        second = credential_commitment_v1_1(
            b"a" * 32,
            WorkerDescriptorV1_1(PREDICTOR_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED", "e", "h", "l", "c"),
        )
        self.assertNotEqual(first, second)

    def test_033_credential_fd_exact_read(self):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"z" * 32)
        os.close(write_fd)
        self.assertEqual(read_credential_once_v1_1(read_fd), b"z" * 32)

    def test_034_absent_credential_rejected(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with self.assertRaises(PermissionError):
            read_credential_once_v1_1(read_fd)

    def test_035_authority_adversarial_matrix(self):
        self.assertEqual(
            self.synthetic["worker_authority"],
            {"blocked_count": 7, "restricted_open_count": 0, "scenario_count": 7},
        )

    def test_036_reuse_blocked(self):
        self.assertFalse(self.global_lock["retry_permitted"])
        self.assertEqual(self.synthetic["worker_authority"]["blocked_count"], 7)

    def test_037_direct_new_extractor_blocked(self):
        with self.assertRaises(SystemExit):
            extractor_main()

    def test_038_direct_new_predictor_blocked(self):
        with self.assertRaises(SystemExit):
            predictor_main()

    def test_039_direct_new_metric_blocked(self):
        with self.assertRaises(SystemExit):
            metric_main()

    def test_040_credentials_not_persisted(self):
        self.assertFalse(self.worker["credential_file"])
        self.assertFalse(self.worker["credential_in_cli"])
        self.assertFalse(self.worker["credential_in_environment"])

    # Durable artifacts, receipts, and global lock.
    def _publish_fixture(self, directory: Path):
        return publish_durable_artifact_v1_1(
            directory / "artifact.json",
            b'{"schema_version":"fixture-v1"}\n',
            stage="TEST",
            worker_role=FEATURE_ROLE,
            artifact_role="TEST_ARTIFACT",
            schema_id="fixture-v1",
            record_count=1,
            approved_head="h",
            execution_id="e",
            effective_contract_id="c",
            code_identity="i",
            parent_state="GLOBAL_RESERVED",
            schema_validator=json_object_validator("fixture-v1"),
        )

    def test_041_durable_mode_atomic_fsync(self):
        with tempfile.TemporaryDirectory() as name:
            receipt = self._publish_fixture(Path(name))
            self.assertEqual(stat.S_IMODE(os.lstat(Path(name) / "artifact.json").st_mode), 0o600)
            self.assertTrue(receipt["atomic_publication"] and receipt["file_fsync"] and receipt["directory_fsync"])

    def test_042_existing_target_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self._publish_fixture(directory)
            with self.assertRaises(DurableArtifactError):
                self._publish_fixture(directory)

    def test_043_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            normal = root / "normal"
            normal.mkdir()
            link = root / "link"
            link.symlink_to(normal, target_is_directory=True)
            with self.assertRaises(DurableArtifactError):
                self._publish_fixture(link)

    def test_044_tampered_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            receipt = self._publish_fixture(directory)
            target = directory / "artifact.json"
            target.write_bytes(b"tampered")
            with self.assertRaises(DurableArtifactError):
                verify_artifact_receipt_v1_1(target, receipt)

    def test_045_stage_receipt_fields(self):
        required = set(self.receipt["required_fields"])
        self.assertTrue({"stage", "worker_role", "artifact_receipts", "parent_state"} <= required)

    def test_046_receipt_bound_to_global_lock(self):
        self.assertTrue(self.receipt["receipt_sha_bound_to_global_lock"])
        self.assertTrue(self.global_lock["cumulative_bundle_commitment"])

    def test_047_global_lock_chain_and_mode(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "lock.json"
            document = reserve_global_lock_v1_1(
                path,
                approved_head="h",
                execution_id="e",
                effective_contract_id="c",
                lock_identity="l",
                fixed_identity_bundle={"x": 1},
                prearm_runtime_smoke_receipt={"sha256": "0" * 64},
                synthetic=True,
            )
            verify_global_lock_chain_v1_1(document)
            self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o600)

    def test_048_global_lock_exclusive(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "lock.json"
            kwargs = dict(
                approved_head="h", execution_id="e", effective_contract_id="c",
                lock_identity="l", fixed_identity_bundle={},
                prearm_runtime_smoke_receipt={"sha256": "0" * 64}, synthetic=True,
            )
            reserve_global_lock_v1_1(path, **kwargs)
            with self.assertRaises(FileExistsError):
                reserve_global_lock_v1_1(path, **kwargs)

    def test_049_global_lock_tamper_detected(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "lock.json"
            reserve_global_lock_v1_1(
                path, approved_head="h", execution_id="e", effective_contract_id="c",
                lock_identity="l", fixed_identity_bundle={},
                prearm_runtime_smoke_receipt={"sha256": "0" * 64}, synthetic=True,
            )
            document = json.loads(path.read_text())
            document["fixed_identity_bundle"] = {"tampered": True}
            path.write_text(json.dumps(document))
            os.chmod(path, 0o600)
            with self.assertRaises(GlobalLockError):
                read_global_lock_v1_1(path)

    def test_050_failure_persistent_no_retry(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "lock.json"
            reserve_global_lock_v1_1(
                path, approved_head="h", execution_id="e", effective_contract_id="c",
                lock_identity="l", fixed_identity_bundle={},
                prearm_runtime_smoke_receipt={"sha256": "0" * 64}, synthetic=True,
            )
            failed = fail_global_lock_v1_1(path, reason="TEST")
            self.assertEqual(failed["state"], "FAILED")
            self.assertFalse(failed["retry_permitted"])
            self.assertEqual(
                failed["transitions"][-1]["stage_receipt_identities"][0]["artifact_role"],
                "FAILURE_RECEIPT",
            )

    def test_051_state_machine_order(self):
        self.assertEqual((STATES[0], STATES[-1]), ("GLOBAL_RESERVED", "COMPLETED"))
        self.assertEqual(len(STATES), 19)

    def test_052_state_machine_rejects_skip(self):
        with self.assertRaises(ValueError):
            require_successor("GLOBAL_RESERVED", "FEATURE_VIEW_PERSISTED")

    # Feature and prediction binding.
    @staticmethod
    def _feature(case_id: str = "CASE-A", query: str = "SYNTHETIC_FEATURE_000", page: str = "Overview", history=()):
        return build_feature_row_v1_1(
            {
                "review_case_id": case_id,
                "current_query": query,
                "current_page": page,
                "necessary_conversation_history": list(history),
            }
        )

    def test_053_content_fingerprint_deterministic(self):
        self.assertEqual(self._feature(), self._feature())

    def test_054_id_excluded_from_content_fingerprint(self):
        self.assertEqual(
            self._feature("A")["feature_content_fingerprint"],
            self._feature("B")["feature_content_fingerprint"],
        )

    def test_055_id_included_in_record_fingerprint(self):
        self.assertNotEqual(
            self._feature("A")["feature_record_fingerprint"],
            self._feature("B")["feature_record_fingerprint"],
        )

    def test_056_query_mutation_changes_fingerprints(self):
        left, right = self._feature(), self._feature(query="SYNTHETIC_FEATURE_001")
        self.assertNotEqual(left["feature_content_fingerprint"], right["feature_content_fingerprint"])
        self.assertNotEqual(left["feature_record_fingerprint"], right["feature_record_fingerprint"])

    def test_057_page_mutation_changes_fingerprints(self):
        self.assertNotEqual(
            self._feature()["feature_content_fingerprint"],
            self._feature(page="Resources")["feature_content_fingerprint"],
        )

    def test_058_history_mutation_changes_fingerprints(self):
        self.assertNotEqual(
            self._feature()["feature_content_fingerprint"],
            self._feature(history=({"role": "user", "content": "synthetic"},))["feature_content_fingerprint"],
        )

    def test_059_core_input_excludes_identifiers(self):
        self.assertEqual(
            tuple(CoreRoutingContentV1_1.__dataclass_fields__),
            ("current_query", "current_page", "necessary_conversation_history"),
        )

    def test_060_id_only_metamorphic_core_invariant(self):
        left, right = self._feature("A"), self._feature("B")
        for method in ("B0", "B1", "P1"):
            self.assertEqual(
                synthetic_core_prediction_v1_1(method, left),
                synthetic_core_prediction_v1_1(method, right),
            )

    def test_061_bound_hash_changes_with_id(self):
        left, right = self._feature("A"), self._feature("B")
        core = synthetic_core_prediction_v1_1("P1", left)
        self.assertNotEqual(
            bind_prediction_v1_1(left, "P1", core)["bound_prediction_hash"],
            bind_prediction_v1_1(right, "P1", core)["bound_prediction_hash"],
        )

    def test_062_case_swap_blocked(self):
        left, right = self._feature("A"), self._feature("B")
        prediction = bind_prediction_v1_1(left, "P1", synthetic_core_prediction_v1_1("P1", left))
        with self.assertRaises(ValueError):
            validate_bound_prediction_v1_1(prediction, right)

    def test_063_feature_mutation_blocked(self):
        left = self._feature("A")
        changed = self._feature("A", page="Resources")
        prediction = bind_prediction_v1_1(left, "B0", synthetic_core_prediction_v1_1("B0", left))
        with self.assertRaises(ValueError):
            validate_bound_prediction_v1_1(prediction, changed)

    def test_064_prediction_contract_counts(self):
        self.assertEqual((self.bound["predictions_per_method"], self.bound["total_predictions"]), (48, 144))

    def test_065_prediction_exclusivity(self):
        feature = self._feature()
        bad = {
            "context_resolution_required_prediction": False,
            "predicted_capabilities": ["clarification", "planning"],
            "core_prediction_trace_hash": "0" * 64,
        }
        with self.assertRaises(ValueError):
            bind_prediction_v1_1(feature, "P1", bad)

    # Runtime firewall, complete metrics, and fixed statistics.
    def test_066_runtime_firewall_actual_hook(self):
        self.assertEqual(self.firewall["implementation"], "sys.addaudithook")
        self.assertTrue(self.firewall["actual_attempt_counters"])

    def test_067_runtime_firewall_adversarial(self):
        result = self.synthetic["runtime_firewall_adversarial"]
        self.assertTrue(result["open_blocked"] and result["import_blocked"])
        self.assertTrue(result["open_attempt_recorded"] and result["import_attempt_recorded"])
        self.assertEqual(result["successful_forbidden_opens"], 0)

    def test_068_formal_firewall_zero_attempts(self):
        self.assertEqual(self.synthetic["formal_worker_firewall_attempts"], 0)

    def test_069_complete_metric_factory_signature(self):
        self.assertEqual(
            tuple(inspect.signature(load_frozen_complete_track_b_metric_binding_v1_1).parameters),
            (),
        )

    def test_070_complete_metric_fixture(self):
        rows = [
            {
                "gold_capabilities": ["planning"],
                "predicted_capabilities": ["planning"],
                "forbidden_capabilities": [],
                "gold_context_resolution_required": True,
                "predicted_context_resolution_required": True,
            },
            {
                "gold_capabilities": ["safe_direct_response"],
                "predicted_capabilities": ["clarification"],
                "forbidden_capabilities": ["clarification"],
                "gold_context_resolution_required": False,
                "predicted_context_resolution_required": True,
            },
        ]
        result = load_frozen_complete_track_b_metric_binding_v1_1().evaluate(rows)
        self.assertEqual(set(result["per_capability"]), set(CAPABILITIES))
        for key in self.metric["method_level_metric_keys"]:
            self.assertIn(key, result)

    def test_071_per_capability_metric_fields(self):
        self.assertEqual(self.metric["per_capability_metrics"], ["precision", "recall", "f1", "support"])

    def test_072_statistical_interface_noninjectable(self):
        self.assertEqual(
            tuple(inspect.signature(run_fixed_track_b_statistics_v1_1).parameters),
            ("ordered_groups", "predictions_by_method", "gold_by_id", "method_metrics"),
        )
        self.assertEqual(self.statistics["caller_overridable_parameters"], [])

    def test_073_fixed_statistical_counts(self):
        self.assertEqual(
            (self.statistics["sign_flip_draws"], self.statistics["bootstrap_resamples"]),
            (100000, 50000),
        )

    def test_074_fixed_statistical_seeds(self):
        self.assertEqual(
            (self.statistics["sign_flip_seed"], self.statistics["bootstrap_seed"]),
            (20260829, 20260828),
        )

    def test_075_fixed_holm_family(self):
        self.assertEqual(self.statistics["primary"], "P1_VS_B1")
        self.assertEqual(self.statistics["secondary_holm"], ["B1_VS_B0", "P1_VS_B0"])

    def test_076_synthetic_complete_metrics_and_statistics(self):
        self.assertTrue(self.synthetic["complete_method_metrics"])
        self.assertEqual(self.synthetic["sign_flip"], "3 x 100000 PASS")
        self.assertEqual(self.synthetic["bootstrap"], "3 x 50000 PASS")
        self.assertEqual(self.synthetic["holm_secondary_count"], 2)

    # Actual development re-execution parity.
    def test_077_development_actual_not_hash_only(self):
        self.assertTrue(self.parity["actual_reexecution"])
        self.assertFalse(self.parity["hash_only_parity"])

    def test_078_development_nine_runs(self):
        self.assertEqual(self.parity["dataset_method_run_count"], 9)
        self.assertEqual(len(self.parity["datasets"]), 9)

    def test_079_development_dataset_counts(self):
        self.assertEqual(
            self.parity["dataset_record_counts"],
            {"authentic": 22, "context_missing": 3, "synthetic": 35},
        )

    def test_080_each_development_method_passes(self):
        expected = {
            (dataset, method)
            for dataset in ("synthetic", "authentic", "context_missing")
            for method in ("B0", "B1", "P1")
        }
        self.assertEqual(
            {(row["dataset"], row["method"]) for row in self.parity["datasets"]},
            expected,
        )
        self.assertTrue(all(row["status"] == "PASS" for row in self.parity["datasets"]))

    def test_081_development_zero_mismatches(self):
        for key in (
            "prediction_mismatch_count",
            "context_mismatch_count",
            "capability_set_mismatch_count",
            "core_trace_mismatch_count",
        ):
            self.assertEqual(self.parity[key], 0)

    def test_082_hash_only_authority_rejected(self):
        with self.assertRaises(RuntimeError):
            require_prediction_level_authority_v1_1({"sha256": "0" * 64})

    def test_082a_development_paths_are_manifest_authorised(self):
        self.assertEqual(
            self.parity["development_input_authority_manifest_sha256"],
            "1c41fd4f81d41fde15dcf10981b242ce7615071e1177ce555f7e1aebae85c831",
        )
        self.assertEqual(
            self.parity["prediction_ledger_authority_manifest_sha256"],
            "83bd1f3c26d866cdf449512b180a2e5e265bd86483634cea31870882843daca2",
        )
        self.assertEqual(
            (self.parity["mapping_access_count"], self.parity["canonical_case_bank_access_count"]),
            (0, 0),
        )

    # P2 and synthetic one-shot integrity.
    def test_083_p2_deferred(self):
        self.assertEqual(self.p2["status"], "DEFERRED_NOT_EXECUTED")
        self.assertEqual(self.p2["state_name"], "SECONDARY_SCOPE_METADATA_PERSISTED")

    def test_084_p2_zero_execution(self):
        self.assertEqual(self.p2["execution_count"], 0)
        self.assertFalse(self.p2["performance_claims"])

    def test_085_p2_no_tool_metrics(self):
        self.assertFalse(self.p2["persistent_retrieval_metric_present"])
        self.assertFalse(self.p2["rag_sufficiency_metric_present"])

    def test_086_synthetic_fixture_shape(self):
        self.assertEqual(
            self.synthetic["fixture"],
            {"group_count": 24, "record_count": 48, "records_per_group": 2},
        )

    def test_087_three_fresh_processes(self):
        self.assertEqual(self.synthetic["fresh_worker_process_count"], 3)
        self.assertTrue(self.synthetic["all_worker_process_ids_distinct"])

    def test_088_synthetic_prediction_binding(self):
        self.assertEqual(self.synthetic["prediction_binding"]["total_predictions"], 144)
        self.assertTrue(self.synthetic["prediction_binding"]["case_and_feature_bound"])

    def test_089_synthetic_durable_persistence(self):
        self.assertTrue(all(self.synthetic["durable_artifacts"].values()))

    def test_090_synthetic_global_completed(self):
        lock = self.synthetic["global_one_shot"]
        self.assertEqual(lock["state"], "COMPLETED")
        self.assertEqual(lock["transition_count"], 19)
        self.assertTrue(lock["all_transitions_carry_receipts"])

    def test_091_synthetic_failure_and_concurrency(self):
        lock = self.synthetic["global_one_shot"]
        self.assertTrue(lock["failure_persistent"] and lock["concurrent_exclusion"])
        self.assertFalse(lock["retry_permitted"])

    # Governance, reproducibility, and review completeness contract.
    def test_092_no_governed_access(self):
        for key in (
            "mapping_access_count",
            "canonical_case_bank_access_count",
            "full_text_track_b_gold_content_access_count",
            "hidden_legacy_access_count",
            "raw_track_b_access_count",
            "blind_key_access_count",
        ):
            self.assertEqual(self.validation[key], 0)

    def test_093_no_real_track_b_evaluation(self):
        self.assertEqual(
            (
                self.validation["real_track_b_inference_count"],
                self.validation["real_track_b_prediction_count"],
                self.validation["real_track_b_metric_count"],
            ),
            (0, 0, 0),
        )

    def test_094_no_policy_gold_or_production_change(self):
        self.assertEqual(self.validation["policy_threshold_metric_comparison_seed_change_count"], 0)
        self.assertEqual(self.validation["gold_change_count"], 0)
        self.assertEqual(self.validation["production_integration_count"], 0)

    def test_095_no_d4_p2_provider_network(self):
        self.assertEqual((self.validation["d4_execution_count"], self.validation["p2_execution_count"]), (0, 0))
        self.assertEqual(self.validation["provider_calls"], 0)
        self.assertFalse(self.validation["network_access"])

    def test_096_all_python_ast(self):
        for name in PYTHON_NAMES:
            ast.parse((HERE / name).read_text(encoding="utf-8"), filename=name)

    def test_097_all_docs_and_outputs_present(self):
        self.assertTrue(
            all((ROOT / "docs/thesis_mainline/rq2" / name).is_file() for name in DOC_NAMES)
        )
        self.assertTrue(all((HERE / name).is_file() for name in OUTPUT_NAMES))

    def test_098_output_checksums(self):
        lines = [line for line in CHECKSUM_PATH.read_text().splitlines() if line]
        self.assertEqual(len(lines), len(checksum_targets()))
        for line in lines:
            expected, relative = line.split("  ", 1)
            self.assertEqual(sha256_file(ROOT / relative), expected)

    def test_099_double_finalisation_declared(self):
        self.assertTrue(self.validation["double_finalisation_byte_identical"])

    def test_100_review_completeness_contract(self):
        referenced = {
            line.split("  ", 1)[1]
            for line in CHECKSUM_PATH.read_text().splitlines()
            if line
        }
        self.assertEqual(referenced, {_path.relative_to(ROOT).as_posix() for _path in checksum_targets()})
        self.assertEqual(
            REVIEW_ZIP_NAME,
            "RQ2_D3_R3_D4_EXECUTION_INTEGRITY_REPAIR_REVIEW_2026-08-29.zip",
        )


if __name__ == "__main__":
    unittest.main()
