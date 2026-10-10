"""Adversarial RQ2-D0-R3 tests, including true multiprocess reservation."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
    REFERENCE_AUTHORITY_COMMITMENT,
    ROOT,
)
from .effective_d1_entry_contract import validate_real_entry_signature_v1_3
from .fixed_d1_paths import (
    FixedD1PathError,
    resolve_real_d1_fixed_paths_v1_3,
    validate_project_relative_posix_path_v1_3,
)
from .global_one_shot_lock import (
    GLOBAL_STATE_ORDER,
    GlobalAccessAlreadyReserved,
    GlobalReservationError,
    assert_global_access_unreserved_v1_3,
    build_real_global_reservation_payload_v1_3,
    mark_global_failed_v1_3,
    read_global_lock_v1_3,
    reserve_global_track_b_access_v1_3,
    update_global_state_v1_3,
)
from .output_root_identity import (
    compute_global_lock_identity_v1_3,
    compute_output_root_identity_v1_3,
    fixed_global_lock_identity_v1_3,
    fixed_output_root_identity_v1_3,
)
from .packet_generation_state_machine_v1_3 import (
    _create_fixed_output_after_reservation,
    execute_real_d1_one_shot_v1_3,
)
from .synthetic_global_lock_harness import (
    SYNTHETIC_EXECUTION_CONTRACT_ID,
    SYNTHETIC_LOCK_NAME,
    SyntheticHarnessError,
    execute_synthetic_global_one_shot_harness_v1_3,
    synthetic_paths,
)


FIXED_TIME = "2026-08-28T00:00:00+00:00"
TEST_AUTHORITY = {"reference_authority_commitment": "c" * 64}


def _make_temp_repo(root: Path) -> None:
    package = root / "evaluation/capability_routing_rq2d1_v1"
    package.mkdir(parents=True)


def _reservation(root: Path) -> dict:
    return build_real_global_reservation_payload_v1_3(
        approved_head="d" * 40,
        safe_schema_authority_sha256="a" * 64,
        reference_authority_commitment=REFERENCE_AUTHORITY_COMMITMENT,
        reservation_created_at=FIXED_TIME,
    )


def _concurrent_worker(root_text: str, start_event, queue) -> None:
    root = Path(root_text)
    paths = resolve_real_d1_fixed_paths_v1_3(root)
    payload = _reservation(root)
    start_event.wait()
    try:
        reserve_global_track_b_access_v1_3(paths, payload)
        queue.put(
            {
                "result": "SUCCESS",
                "key_generation_count": 0,
                "raw_open_count": 0,
                "raw_read_count": 0,
            }
        )
    except GlobalAccessAlreadyReserved:
        queue.put(
            {
                "result": "ALREADY_RESERVED",
                "key_generation_count": 0,
                "raw_open_count": 0,
                "raw_read_count": 0,
            }
        )


class RQ2D0R3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="rq2d0-r3-tests-")
        cls.root = Path(cls._temporary.name)

        cls.synthetic_complete_root = cls.root / "synthetic-complete"
        cls.synthetic_complete = execute_synthetic_global_one_shot_harness_v1_3(
            cls.synthetic_complete_root,
            [{"opaque_case": 1}],
            TEST_AUTHORITY,
        )
        cls.synthetic_complete_paths = synthetic_paths(cls.synthetic_complete_root)

        cls.synthetic_failure_root = cls.root / "synthetic-failure"
        try:
            execute_synthetic_global_one_shot_harness_v1_3(
                cls.synthetic_failure_root,
                [{"opaque_case": 1}],
                TEST_AUTHORITY,
                simulate_failure_after_state="ARMED",
            )
        except SyntheticHarnessError as exc:
            cls.synthetic_failure_lock = exc.synthetic_failure_lock
        else:
            raise AssertionError("synthetic failure was not raised")
        cls.synthetic_failure_paths = synthetic_paths(cls.synthetic_failure_root)

        cls.concurrent_root = cls.root / "concurrent-repo"
        cls.concurrent_root.mkdir()
        _make_temp_repo(cls.concurrent_root)
        context = multiprocessing.get_context("fork")
        start = context.Event()
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_worker,
                args=(str(cls.concurrent_root), start, queue),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        start.set()
        cls.concurrent_results = [queue.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            if process.exitcode != 0:
                raise AssertionError(f"concurrency worker failed: {process.exitcode}")
        cls.concurrent_paths = resolve_real_d1_fixed_paths_v1_3(cls.concurrent_root)
        cls.concurrent_failed_lock = mark_global_failed_v1_3(
            cls.concurrent_paths.global_lock_path,
            failure_stage="GLOBAL_RESERVED",
            failure_code="SYNTHETIC_WINNER_FAILURE",
            failure_timestamp=FIXED_TIME,
            raw_open_count=0,
            raw_read_count=0,
        )
        try:
            reserve_global_track_b_access_v1_3(
                cls.concurrent_paths, _reservation(cls.concurrent_root)
            )
        except GlobalAccessAlreadyReserved:
            cls.third_attempt_blocked = True
        else:
            cls.third_attempt_blocked = False

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _repo(self, name: str) -> tuple[Path, object]:
        root = self.root / name
        root.mkdir()
        _make_temp_repo(root)
        return root, resolve_real_d1_fixed_paths_v1_3(root)

    def _reserved_repo(self, name: str):
        root, paths = self._repo(name)
        reserve_global_track_b_access_v1_3(paths, _reservation(root))
        return root, paths

    # Fixed paths (1-20)
    def test_01_fixed_output_root_constant(self) -> None:
        self.assertEqual(
            REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
            "evaluation/capability_routing_rq2d1_v1/local_one_shot",
        )

    def test_02_fixed_control_root_constant(self) -> None:
        self.assertEqual(
            REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
            "evaluation/capability_routing_rq2d1_v1/local_control",
        )

    def test_03_fixed_global_lock_constant(self) -> None:
        self.assertTrue(
            REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3.endswith(
                "TRACK_B_PACKET_GENERATION_GLOBAL_ACCESS_V1_3.json"
            )
        )

    def test_04_fixed_paths_are_project_relative(self) -> None:
        for value in (
            REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
            REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
            REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
        ):
            self.assertFalse(validate_project_relative_posix_path_v1_3(value).is_absolute())

    def test_05_absolute_path_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("/absolute/path")

    def test_06_dotdot_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("a/../b")

    def test_07_dot_component_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("a/./b")

    def test_08_nul_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("a/\x00/b")

    def test_09_uri_scheme_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("file://authority")

    def test_10_home_expansion_rejected(self) -> None:
        with self.assertRaises(FixedD1PathError):
            validate_project_relative_posix_path_v1_3("~/authority")

    def test_11_symlink_parent_rejected(self) -> None:
        root = self.root / "symlink-parent"
        root.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (root / "evaluation").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FixedD1PathError):
            resolve_real_d1_fixed_paths_v1_3(root)

    def test_12_resolved_targets_stay_in_repo(self) -> None:
        root, paths = self._repo("inside-repo")
        self.assertTrue(paths.output_root.is_relative_to(root))
        self.assertTrue(paths.global_lock_path.is_relative_to(root))

    def test_13_real_entry_has_no_output_parameter(self) -> None:
        self.assertNotIn("output_root", inspect.signature(execute_real_d1_one_shot_v1_3).parameters)

    def test_14_real_entry_has_no_lock_parameter(self) -> None:
        self.assertFalse(
            any("lock" in name for name in inspect.signature(execute_real_d1_one_shot_v1_3).parameters)
        )

    def test_15_real_entry_has_no_location_override(self) -> None:
        report = validate_real_entry_signature_v1_3()
        self.assertEqual(report["forbidden_location_parameter_count"], 0)

    def test_16_environment_cannot_override_fixed_paths(self) -> None:
        old = os.environ.get("RQ2_D1_OUTPUT_ROOT")
        os.environ["RQ2_D1_OUTPUT_ROOT"] = "alternative/location"
        try:
            self.assertEqual(
                REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
                "evaluation/capability_routing_rq2d1_v1/local_one_shot",
            )
        finally:
            if old is None:
                os.environ.pop("RQ2_D1_OUTPUT_ROOT", None)
            else:
                os.environ["RQ2_D1_OUTPUT_ROOT"] = old

    def _ignored(self, relative: str) -> bool:
        return subprocess.run(
            ["git", "check-ignore", "-q", "--", relative],
            cwd=ROOT,
            check=False,
        ).returncode == 0

    def test_17_future_output_root_ignored(self) -> None:
        self.assertTrue(self._ignored(REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 + "/probe"))

    def test_18_future_control_root_ignored(self) -> None:
        self.assertTrue(self._ignored(REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3 + "/probe"))

    def test_19_global_lock_cannot_enter_git(self) -> None:
        self.assertTrue(self._ignored(REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3))

    def test_20_key_and_packets_cannot_enter_git(self) -> None:
        self.assertTrue(self._ignored(REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 + "/blinding-key.bin"))
        self.assertTrue(self._ignored(REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 + "/reviewer.csv"))

    # Output identity (21-28)
    def test_21_full_relative_path_participates_in_identity(self) -> None:
        self.assertNotEqual(
            compute_output_root_identity_v1_3("C", "a/local_one_shot"),
            compute_output_root_identity_v1_3("C", "b/local_one_shot"),
        )

    def test_22_execution_contract_participates_in_identity(self) -> None:
        self.assertNotEqual(
            compute_output_root_identity_v1_3("C1", "a/output"),
            compute_output_root_identity_v1_3("C2", "a/output"),
        )

    def test_23_same_basename_different_parent_differs(self) -> None:
        self.assertNotEqual(
            compute_global_lock_identity_v1_3("C", "a/LOCK.json"),
            compute_global_lock_identity_v1_3("C", "b/LOCK.json"),
        )

    def test_24_output_identity_is_64_hex(self) -> None:
        value = fixed_output_root_identity_v1_3()
        self.assertEqual(len(value), 64)
        int(value, 16)

    def test_25_global_identity_is_lowercase_hex(self) -> None:
        value = fixed_global_lock_identity_v1_3()
        self.assertEqual(value, value.lower())
        int(value, 16)

    def test_26_identities_are_deterministic(self) -> None:
        self.assertEqual(fixed_output_root_identity_v1_3(), fixed_output_root_identity_v1_3())

    def test_27_absolute_machine_path_not_accepted(self) -> None:
        with self.assertRaises(FixedD1PathError):
            compute_output_root_identity_v1_3("C", "/machine/specific/path")

    def test_28_fixed_identity_binds_execution_contract(self) -> None:
        self.assertEqual(
            fixed_output_root_identity_v1_3(),
            compute_output_root_identity_v1_3(
                EXECUTION_CONTRACT_ID, REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3
            ),
        )

    # Reservation and durability (29-42)
    def test_29_o_excl_first_reservation_succeeds(self) -> None:
        _, paths = self._reserved_repo("exclusive-first")
        self.assertTrue(paths.global_lock_path.is_file())

    def test_30_reservation_file_mode_0600(self) -> None:
        _, paths = self._reserved_repo("mode-file")
        self.assertEqual(stat.S_IMODE(paths.global_lock_path.stat().st_mode), 0o600)

    def test_31_control_directory_mode_0700(self) -> None:
        _, paths = self._reserved_repo("mode-dir")
        self.assertEqual(stat.S_IMODE(paths.global_control_root.stat().st_mode), 0o700)

    def test_32_initial_state_is_global_reserved(self) -> None:
        _, paths = self._reserved_repo("initial-state")
        self.assertEqual(read_global_lock_v1_3(paths.global_lock_path)["state"], "GLOBAL_RESERVED")

    def test_33_reservation_durably_reverified(self) -> None:
        root, paths = self._repo("durable")
        report = reserve_global_track_b_access_v1_3(paths, _reservation(root))
        self.assertTrue(report["durably_reverified"])

    def test_33a_tampered_fixed_identity_rejected(self) -> None:
        root, paths = self._repo("tampered-fixed-identity")
        payload = _reservation(root)
        payload["output_root_identity"] = "0" * 64
        with self.assertRaises(GlobalReservationError):
            reserve_global_track_b_access_v1_3(paths, payload)

    def test_33b_created_output_root_is_mode_0700(self) -> None:
        root, paths = self._reserved_repo("created-output-mode")
        _create_fixed_output_after_reservation(paths)
        self.assertEqual(stat.S_IMODE(paths.output_root.stat().st_mode), 0o700)

    def _existing_state_blocks(self, name: str, state: str) -> None:
        root, paths = self._reserved_repo(name)
        value = read_global_lock_v1_3(paths.global_lock_path)
        value["state"] = state
        paths.global_lock_path.write_bytes(json.dumps(value).encode())
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    def test_34_existing_reserved_blocks(self) -> None:
        root, paths = self._reserved_repo("existing-reserved")
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    def test_35_existing_failed_blocks(self) -> None:
        self._existing_state_blocks("existing-failed", "FAILED")

    def test_36_existing_completed_blocks(self) -> None:
        self._existing_state_blocks("existing-completed", "COMPLETED")

    def test_37_malformed_existing_lock_blocks(self) -> None:
        root, paths = self._repo("malformed")
        paths.global_control_root.mkdir(mode=0o700)
        paths.global_lock_path.write_text("malformed", encoding="utf-8")
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    def test_38_symlink_lock_blocks(self) -> None:
        root, paths = self._repo("symlink-lock")
        paths.global_control_root.mkdir(mode=0o700)
        target = root / "target"
        target.write_text("x")
        paths.global_lock_path.symlink_to(target)
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    def test_39_reservation_occurs_before_synthetic_key(self) -> None:
        history = self.synthetic_complete["lock"]["state_history"]
        self.assertLess(history.index("GLOBAL_RESERVED"), history.index("KEY_PERSISTED"))

    def test_40_reservation_occurs_before_synthetic_open(self) -> None:
        history = self.synthetic_complete["lock"]["state_history"]
        self.assertLess(history.index("GLOBAL_RESERVED"), history.index("OPENED"))

    def test_41_reservation_failure_key_count_zero(self) -> None:
        loser = next(row for row in self.concurrent_results if row["result"] == "ALREADY_RESERVED")
        self.assertEqual(loser["key_generation_count"], 0)

    def test_42_reservation_failure_raw_counts_zero(self) -> None:
        loser = next(row for row in self.concurrent_results if row["result"] == "ALREADY_RESERVED")
        self.assertEqual((loser["raw_open_count"], loser["raw_read_count"]), (0, 0))

    # Persistence and bypass (43-51)
    def test_43_post_reservation_failure_retains_lock(self) -> None:
        self.assertTrue(self.synthetic_failure_paths[2].is_file())

    def test_44_failure_state_is_failed(self) -> None:
        self.assertEqual(self.synthetic_failure_lock["state"], "FAILED")

    def test_45_failed_lock_preserves_last_successful_state(self) -> None:
        self.assertEqual(self.synthetic_failure_lock["last_successful_state"], "ARMED")

    def test_46_retry_is_always_false(self) -> None:
        self.assertFalse(self.synthetic_failure_lock["retry_permitted"])
        self.assertFalse(self.synthetic_complete["lock"]["retry_permitted"])

    def test_47_failed_lock_cannot_retry(self) -> None:
        with self.assertRaises(GlobalAccessAlreadyReserved):
            assert_global_access_unreserved_v1_3(self.synthetic_failure_paths[2])

    def test_48_completed_lock_cannot_retry(self) -> None:
        with self.assertRaises(GlobalAccessAlreadyReserved):
            assert_global_access_unreserved_v1_3(self.synthetic_complete_paths[2])

    def test_49_deleting_output_does_not_remove_global_lock(self) -> None:
        root = self.root / "delete-output"
        result = execute_synthetic_global_one_shot_harness_v1_3(root, [{}], TEST_AUTHORITY)
        shutil.rmtree(result["synthetic_output_root"])
        self.assertTrue(synthetic_paths(root)[2].is_file())

    def test_50_alternative_output_directory_cannot_bypass(self) -> None:
        root, paths = self._reserved_repo("alternative-output")
        (root / "alternative-output").mkdir()
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    def test_51_same_basename_alternative_parent_cannot_bypass(self) -> None:
        root, paths = self._reserved_repo("same-basename")
        (root / "alternative/local_one_shot").mkdir(parents=True)
        with self.assertRaises(GlobalAccessAlreadyReserved):
            reserve_global_track_b_access_v1_3(paths, _reservation(root))

    # True concurrency (52-56)
    def test_52_two_concurrent_attempts_have_one_winner(self) -> None:
        self.assertEqual([row["result"] for row in self.concurrent_results].count("SUCCESS"), 1)

    def test_53_concurrent_loser_key_count_zero(self) -> None:
        loser = next(row for row in self.concurrent_results if row["result"] != "SUCCESS")
        self.assertEqual(loser["key_generation_count"], 0)

    def test_54_concurrent_loser_raw_counts_zero(self) -> None:
        loser = next(row for row in self.concurrent_results if row["result"] != "SUCCESS")
        self.assertEqual((loser["raw_open_count"], loser["raw_read_count"]), (0, 0))

    def test_55_winner_failure_retains_failed_lock(self) -> None:
        self.assertEqual(self.concurrent_failed_lock["state"], "FAILED")
        self.assertTrue(self.concurrent_paths.global_lock_path.is_file())

    def test_56_third_attempt_after_winner_failure_blocked(self) -> None:
        self.assertTrue(self.third_attempt_blocked)

    # Synthetic/real separation (57-63)
    def test_57_synthetic_and_real_entries_are_different(self) -> None:
        self.assertIsNot(execute_synthetic_global_one_shot_harness_v1_3, execute_real_d1_one_shot_v1_3)

    def test_58_synthetic_contract_id_differs(self) -> None:
        self.assertNotEqual(SYNTHETIC_EXECUTION_CONTRACT_ID, EXECUTION_CONTRACT_ID)

    def test_59_synthetic_uses_temporary_lock_name(self) -> None:
        self.assertEqual(self.synthetic_complete_paths[2].name, SYNTHETIC_LOCK_NAME)

    def test_60_synthetic_did_not_create_real_lock(self) -> None:
        self.assertFalse(self.synthetic_complete["real_global_lock_created"])

    def test_61_synthetic_lock_cannot_satisfy_real_fixed_lock(self) -> None:
        self.assertNotEqual(
            self.synthetic_complete_paths[2].as_posix(),
            REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
        )

    def test_62_synthetic_completion_does_not_authorise_real_d1(self) -> None:
        self.assertNotEqual(
            self.synthetic_complete["lock"]["execution_contract_id"], EXECUTION_CONTRACT_ID
        )

    def test_63_real_constants_not_overridden_by_synthetic_root(self) -> None:
        self.assertNotIn(
            REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
            self.synthetic_complete["synthetic_output_root"].as_posix(),
        )

    # State and receipts (64-72)
    def test_64_global_reserved_is_first_consuming_state(self) -> None:
        self.assertEqual(GLOBAL_STATE_ORDER[0], "GLOBAL_RESERVED")

    def test_65_global_state_order_is_strict(self) -> None:
        self.assertEqual(self.synthetic_complete["lock"]["state_history"], list(GLOBAL_STATE_ORDER))

    def test_66_illegal_state_transition_rejected(self) -> None:
        _, paths = self._reserved_repo("illegal-transition")
        with self.assertRaises(GlobalReservationError):
            update_global_state_v1_3(
                paths.global_lock_path,
                expected_state="GLOBAL_RESERVED",
                next_state="ARMED",
            )

    def test_67_failure_transition_records_failed(self) -> None:
        self.assertEqual(self.synthetic_failure_lock["state_history"][-1], "FAILED")

    def test_68_packet_manifest_binds_global_identity(self) -> None:
        packet = json.loads(
            (self.synthetic_complete_paths[0] / "synthetic_packet_manifest.json").read_text()
        )
        self.assertEqual(
            packet["global_receipt"]["global_lock_identity"],
            self.synthetic_complete["lock"]["global_lock_identity"],
        )

    def test_69_completed_lock_binds_global_identity(self) -> None:
        lock = self.synthetic_complete["lock"]
        self.assertEqual(
            lock["completed_global_receipt"]["global_lock_identity"],
            lock["global_lock_identity"],
        )

    def test_70_post_completed_write_rejected(self) -> None:
        with self.assertRaises(GlobalAccessAlreadyReserved):
            update_global_state_v1_3(
                self.synthetic_complete_paths[2],
                expected_state="COMPLETED",
                next_state="FAILED",
            )

    def test_71_case_manifest_binds_global_receipt(self) -> None:
        value = json.loads(
            (self.synthetic_complete_paths[0] / "synthetic_case_bank_manifest.json").read_text()
        )
        self.assertEqual(value["global_receipt"]["execution_contract_id"], SYNTHETIC_EXECUTION_CONTRACT_ID)

    def test_72_reviewer_manifests_bind_global_receipt(self) -> None:
        for reviewer in ("a", "b"):
            value = json.loads(
                (
                    self.synthetic_complete_paths[0]
                    / f"synthetic_reviewer_{reviewer}_manifest.json"
                ).read_text()
            )
            self.assertEqual(value["global_receipt"]["global_lock_identity"], self.synthetic_complete["lock"]["global_lock_identity"])

    # Research boundaries and determinism (73-78)
    def test_73_no_real_raw_track_b_access(self) -> None:
        self.assertEqual(self.synthetic_complete["real_raw_open_count"], 0)

    def test_74_no_real_key_or_packets(self) -> None:
        self.assertFalse(self.synthetic_complete["real_key_created"])
        self.assertFalse(self.synthetic_complete["real_packets_created"])

    def test_75_no_track_b_labels_or_model_execution(self) -> None:
        self.assertNotIn("labels", self.synthetic_complete)
        self.assertNotIn("model_output", self.synthetic_complete)

    def test_76_synthetic_double_build_byte_identical(self) -> None:
        left = self.root / "double-left"
        right = self.root / "double-right"
        execute_synthetic_global_one_shot_harness_v1_3(left, [{}], TEST_AUTHORITY)
        execute_synthetic_global_one_shot_harness_v1_3(right, [{}], TEST_AUTHORITY)
        left_files = {
            path.relative_to(left).as_posix(): path.read_bytes()
            for path in left.rglob("*")
            if path.is_file()
        }
        right_files = {
            path.relative_to(right).as_posix(): path.read_bytes()
            for path in right.rglob("*")
            if path.is_file()
        }
        self.assertEqual(left_files, right_files)

    def test_77_no_real_environment_authority_used_by_synthetic(self) -> None:
        self.assertNotIn("RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED", inspect.signature(execute_synthetic_global_one_shot_harness_v1_3).parameters)

    def test_78_no_provider_or_network_contract_fields(self) -> None:
        self.assertNotIn("provider", self.synthetic_complete)
        self.assertNotIn("network", self.synthetic_complete)


if __name__ == "__main__":
    unittest.main()
