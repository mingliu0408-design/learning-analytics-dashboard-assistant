"""Contract, adversarial and governance tests for RQ2-D3-R4."""

from __future__ import annotations

from dataclasses import replace
import ast
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from . import (
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_SHA256,
    COMBINED_SHA256,
    COMBINED_SIZE,
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    EFFECTIVE_CONTRACT_ID,
    GROUPING_SIZE,
    HERE,
    LABEL_SHA256,
    LABEL_SIZE,
    METRIC_IMPLEMENTATION_SHA256,
    P1_POLICY_SHA256,
    RECORD_COUNT,
    ROOT,
    START_HEAD,
    SYNTHETIC_CONTRACT_ID,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .atomic_execution_state_v1_2 import (
    AtomicStateError,
    atomic_mutate_execution_state_v1_2,
    fail_execution_state_v1_2,
    initial_execution_state_document_v1_2,
    initialise_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .completion_bundle_v1_2 import (
    REQUIRED_COMPLETION_FIELDS,
    CompletionBundleError,
    build_completion_bundle_v1_2,
    validate_completion_bundle_v1_2,
)
from .completion_evidence_v1_2 import (
    REQUIRED_WORKER_ROLES,
    derive_completion_evidence_v1_2,
    require_completion_eligible_v1_2,
)
from .d3_r3_identity import AUTHORISED_LEGACY_FILES
from .d3_r3_legacy_entrypoint_revocation import (
    SUPERSESSION,
    legacy_entrypoint_inventory_document_v1,
)
from .durable_directory_tree_v1_2 import (
    DurableDirectoryError,
    create_durable_directory_tree_v1_2,
)
from .durable_no_replace_artifact_v1_2 import (
    NoReplaceArtifactError,
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .effective_d4_contract_v1_2 import (
    effective_d4_contract_document_v1_2,
    execute_real_rq2d4_one_shot_v1_2,
)
from .fixed_real_d4_paths_v1_2 import (
    CONTROL_ROOT_RELATIVE,
    OUTPUT_ROOT_RELATIVE,
    PARENT_RECEIPT_RELATIVE,
    SENTINEL_RELATIVE,
    STATE_RELATIVE,
    _paths_for_root,
    fixed_real_path_contract_document_v1_2,
)
from .fixed_real_worker_authority_v1_2 import (
    FEATURE_ROLE,
    FixedWorkerAuthorityError,
    claim_fixed_real_worker_authority_v1_2,
    fixed_real_code_bundle_identity_v1_2,
    issue_fixed_real_worker_credential_v1_2,
)
from .immutable_reservation_sentinel_v1_2 import (
    ALREADY_RESERVED,
    ReservationSentinelError,
    create_reservation_sentinel_v1_2,
    reservation_sentinel_document_v1_2,
)
from .parent_execution_receipt_v1_2 import (
    parent_execution_receipt_document_v1_2,
    parent_receipt_descriptor_commitment_v1_2,
    persist_parent_execution_receipt_v1_2,
)
from .real_feature_worker_v1_2 import run_real_feature_extractor_worker_v1_2
from .real_metric_worker_v1_2 import run_real_metric_worker_v1_2
from .real_predictor_worker_v1_2 import run_real_predictor_worker_v1_2
from .starting_state import validate_starting_state_v1
from .strict_project_relative_path import (
    StrictPathError,
    open_regular_nofollow,
    validate_project_relative_path,
)
from .strict_receipt_verifier_v1_2 import (
    RECEIPT_MISMATCH,
    StrictReceiptError,
    verify_strict_artifact_receipt_v1_2,
)
from .synthetic_r4_integrity_fixture import (
    build_synthetic_authority_fixture_v1_2,
    synthetic_paths_v1_2,
)
from .synthetic_r4_integrity_harness import run_synthetic_r4_integrity_harness_v1_2
from .terminal_state_machine_v1_2 import (
    NORMAL_STATES,
    TerminalStateError,
    require_transition_v1_2,
    validate_transition_chain_v1_2,
)
from .validate_rq2d3_r4 import (
    CHECKSUM_RELATIVE,
    _protected_source_check,
    _review_members,
    build_outputs,
    checksum_targets,
    validate_outputs,
)


def _sentinel_document(*, synthetic: bool = True, contract: str = SYNTHETIC_CONTRACT_ID):
    fixed = {
        "output_root_relative": "output",
        "control_root_relative": "control",
        "sentinel_relative": "control/sentinel.json",
        "state_relative": "control/state.json",
        "parent_receipt_relative": "control/parent.json",
    }
    return reservation_sentinel_document_v1_2(
        execution_id="e" * 64,
        approved_head="a" * 40,
        fixed_paths=fixed,
        frozen_identity_bundle={"fixture": "SAFE"},
        input_identity_bundle={"fixture": "SAFE"},
        d3_r4_code_bundle_identity="safe-code",
        parent_execution_nonce_commitment="n" * 64,
        parent_receipt_descriptor_commitment="d" * 64,
        reservation_created_at="2026-08-29T00:00:00Z",
        synthetic=synthetic,
        execution_contract_id=contract,
    )


def _publish_kwargs(relative: str = "artifacts/item.json"):
    return {
        "relative_path": relative,
        "stage": "RESULT_PERSISTED",
        "worker_role": "TEST_WORKER",
        "worker_credential_commitment": "c" * 64,
        "artifact_role": "TEST_ARTIFACT",
        "schema_id": "test-artifact-v1-2",
        "record_count": 1,
        "approved_head": "a" * 40,
        "execution_id": "e" * 64,
        "effective_contract_id": SYNTHETIC_CONTRACT_ID,
        "code_identity": "test-code",
        "parent_state": "PRIMARY_STATISTICS_PERSISTED",
        "open_read_counts": {"open": 0},
        "firewall_summary": {"successful_forbidden_opens": 0},
        "schema_validator": json_object_validator("test-artifact-v1-2"),
    }


def _init_git_repository(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "RQ2 Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "rq2@example.invalid"], cwd=root, check=True)
    (root / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    subprocess.run(["git", "add", "anchor.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "anchor"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _build_real_authority_fixture(root: Path):
    approved_head = _init_git_repository(root)
    paths = _paths_for_root(root)
    create_durable_directory_tree_v1_2(root, CONTROL_ROOT_RELATIVE)
    fixed = {
        "output_root_relative": OUTPUT_ROOT_RELATIVE,
        "control_root_relative": CONTROL_ROOT_RELATIVE,
        "sentinel_relative": SENTINEL_RELATIVE,
        "state_relative": STATE_RELATIVE,
        "parent_receipt_relative": PARENT_RECEIPT_RELATIVE,
    }
    descriptor = parent_receipt_descriptor_commitment_v1_2(
        relative_path=PARENT_RECEIPT_RELATIVE,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        approved_head=approved_head,
    )
    code_bundle_identity = fixed_real_code_bundle_identity_v1_2()
    sentinel_document = reservation_sentinel_document_v1_2(
        execution_id="1" * 64,
        approved_head=approved_head,
        fixed_paths=fixed,
        frozen_identity_bundle={
            "d2b_gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
            "d3_r1_statistical_contract_sha256": D3_R1_STATISTICAL_SHA256,
            "d3_r2_grouping_sha256": D3_R2_GROUPING_SHA256,
            "metric_implementation_sha256": METRIC_IMPLEMENTATION_SHA256,
            "c0_index_sha256": C0_INDEX_SHA256,
            "c0_embeddings_sha256": C0_EMBEDDINGS_SHA256,
            "p1_policy_sha256": P1_POLICY_SHA256,
            "d3_r4_code_bundle_identity": code_bundle_identity,
        },
        input_identity_bundle={
            "combined_source": {
                "sha256": COMBINED_SHA256,
                "size_bytes": COMBINED_SIZE,
                "record_count": RECORD_COUNT,
            },
            "label_gold": {
                "sha256": LABEL_SHA256,
                "size_bytes": LABEL_SIZE,
                "record_count": RECORD_COUNT,
            },
            "grouping": {
                "sha256": D3_R2_GROUPING_SHA256,
                "size_bytes": GROUPING_SIZE,
                "record_count": RECORD_COUNT,
                "group_count": 24,
                "group_size": 2,
            },
        },
        d3_r4_code_bundle_identity=code_bundle_identity,
        parent_execution_nonce_commitment="2" * 64,
        parent_receipt_descriptor_commitment=descriptor,
        reservation_created_at="2026-08-29T00:00:00Z",
        synthetic=False,
    )
    sentinel_identity = create_reservation_sentinel_v1_2(paths.sentinel, sentinel_document)
    state = initial_execution_state_document_v1_2(
        execution_id="1" * 64,
        approved_head=approved_head,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        sentinel_sha256=sentinel_identity["sha256"],
        synthetic=False,
    )
    initialise_execution_state_v1_2(
        paths.state, paths.sentinel, state, state_relative_path=STATE_RELATIVE
    )
    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        "INPUT_IDENTITIES_VERIFIED",
        stage_receipts=[{"artifact_role": "FIXED_INPUT_IDENTITY_BUNDLE", "sha256": "3" * 64}],
    )
    parent_document = parent_execution_receipt_document_v1_2(
        execution_id="1" * 64,
        approved_head=approved_head,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        sentinel_identity=sentinel_identity,
        sentinel_relative=SENTINEL_RELATIVE,
        state_relative=STATE_RELATIVE,
        parent_receipt_relative=PARENT_RECEIPT_RELATIVE,
        parent_nonce_commitment="2" * 64,
        parent_code_identity=sha256_file(HERE / "effective_d4_contract_v1_2.py"),
        fixed_real_paths=fixed,
        input_identity_commitments=sentinel_document["expected_input_identities"],
        created_at="2026-08-29T00:00:01Z",
        synthetic=False,
    )
    parent_receipt = persist_parent_execution_receipt_v1_2(
        paths.parent_receipt,
        parent_document,
        relative_path=PARENT_RECEIPT_RELATIVE,
        sentinel_sha256=sentinel_identity["sha256"],
    )

    def bind(document):
        document["parent_receipt_sha256"] = parent_receipt["sha256"]

    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        "PARENT_EXECUTION_RECEIPT_PERSISTED",
        stage_receipts=[parent_receipt],
        mutation=bind,
    )
    return paths, approved_head


class StartingAndLegacyTests(unittest.TestCase):
    def test_001_starting_identities(self):
        report = validate_starting_state_v1()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["r3_output_checksums_at_frozen_head"], "53/53 PASS")
        self.assertEqual(report["r2_output_checksums_at_frozen_head"], "41/41 PASS")

    def test_002_governed_inputs_are_lstat_only(self):
        rows = validate_starting_state_v1()["governed_input_preflight"]
        self.assertTrue(all(row["content_read_count"] == 0 for row in rows))
        self.assertTrue(all(row["lstat_count"] == 1 for row in rows))

    def test_003_legacy_inventory(self):
        inventory = legacy_entrypoint_inventory_document_v1()
        self.assertEqual(inventory["status"], "PASS")
        self.assertEqual(inventory["file_count"], 6)
        self.assertEqual(inventory["entry_count"], 6)

    def test_004_old_parent_blocked(self):
        from evaluation.capability_routing_rq2d3_r3_v1.effective_d4_contract_v1_1 import execute_real_rq2d4_one_shot_v1_1

        with self.assertRaisesRegex(RuntimeError, SUPERSESSION):
            execute_real_rq2d4_one_shot_v1_1(approved_head="unused")

    def test_005_old_workers_blocked_before_inputs(self):
        from evaluation.capability_routing_rq2d3_r3_v1.track_b_feature_extractor_worker_v1_1 import run_feature_extractor_worker_v1_1
        from evaluation.capability_routing_rq2d3_r3_v1.track_b_predictor_worker_v1_1 import run_predictor_worker_v1_1
        from evaluation.capability_routing_rq2d3_r3_v1.track_b_metric_worker_v1_1 import run_metric_worker_v1_1

        calls = (
            lambda: run_feature_extractor_worker_v1_1(paths=None, descriptor_fd=-1, worker_descriptor=None, expected_combined_sha256="", expected_combined_size=0, expected_record_count=0),
            lambda: run_predictor_worker_v1_1(paths=None, descriptor_fd=-1, worker_descriptor=None, expected_feature_count=0),
            lambda: run_metric_worker_v1_1(paths=None, descriptor_fd=-1, worker_descriptor=None, expected_label_sha256="", expected_label_size=0, expected_grouping_sha256="", expected_grouping_size=0, expected_record_count=0, expected_group_count=0),
        )
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(RuntimeError, SUPERSESSION):
                call()

    def test_006_old_issuer_blocked(self):
        from evaluation.capability_routing_rq2d3_r3_v1.worker_execution_authority_v1_1 import issue_worker_credential_v1_1

        with self.assertRaisesRegex(PermissionError, SUPERSESSION):
            issue_worker_credential_v1_1(Path("unused"), descriptor=None, commit_state="unused")

    def test_006b_old_mutable_lock_updater_blocked(self):
        from evaluation.capability_routing_rq2d3_r3_v1.global_lock_receipt_v1_1 import locked_update_v1_1

        with self.assertRaisesRegex(RuntimeError, SUPERSESSION):
            locked_update_v1_1(Path("unused"), lambda document: None)

    def test_007_historical_safe_outputs_unchanged(self):
        manifest = ROOT / "evaluation/capability_routing_rq2d3_r3_v1/rq2d3_r3_output_checksums_v1.sha256"
        unchanged = 0
        for line in manifest.read_text().splitlines():
            expected, relative = line.split("  ", 1)
            if relative in AUTHORISED_LEGACY_FILES:
                continue
            self.assertEqual(__import__("hashlib").sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
            unchanged += 1
        self.assertEqual(unchanged, 47)


class ContractAndWorkerAuthorityTests(unittest.TestCase):
    def test_010_parent_signature_is_fixed(self):
        self.assertEqual(tuple(inspect.signature(execute_real_rq2d4_one_shot_v1_2).parameters), ("approved_head",))

    def test_011_worker_signatures_are_fd_only(self):
        for worker in (
            run_real_feature_extractor_worker_v1_2,
            run_real_predictor_worker_v1_2,
            run_real_metric_worker_v1_2,
        ):
            with self.subTest(worker=worker.__name__):
                signature = inspect.signature(worker)
                self.assertEqual(tuple(signature.parameters), ("credential_fd",))
                self.assertEqual(signature.parameters["credential_fd"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_012_contract_forbids_caller_authority_fields(self):
        document = effective_d4_contract_document_v1_2()
        self.assertEqual(document["entry_parameters"], ["approved_head"])
        self.assertIn("path", document["forbidden_parameters"])
        self.assertIn("synthetic_flag", document["forbidden_parameters"])

    def test_013_fixed_paths(self):
        document = fixed_real_path_contract_document_v1_2()
        self.assertFalse(document["caller_override_allowed"])
        self.assertFalse(document["environment_override_allowed"])
        self.assertEqual(document["sentinel_relative"], SENTINEL_RELATIVE)

    def test_014_valid_real_authority_claim_and_reuse_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=paths):
                secret, commitment = issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)
                read_fd, write_fd = os.pipe()
                os.write(write_fd, secret)
                os.close(write_fd)
                context = claim_fixed_real_worker_authority_v1_2(FEATURE_ROLE, credential_fd=read_fd)
                self.assertEqual(context.credential_commitment, commitment)
                read_fd, write_fd = os.pipe()
                os.write(write_fd, secret)
                os.close(write_fd)
                with self.assertRaises(FixedWorkerAuthorityError):
                    claim_fixed_real_worker_authority_v1_2(FEATURE_ROLE, credential_fd=read_fd)
                try:
                    os.close(read_fd)
                except OSError:
                    pass

    def test_015_wrong_real_credential_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=paths):
                issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)
                read_fd, write_fd = os.pipe()
                os.write(write_fd, b"wrong".ljust(32, b"x"))
                os.close(write_fd)
                with self.assertRaises(FixedWorkerAuthorityError):
                    claim_fixed_real_worker_authority_v1_2(FEATURE_ROLE, credential_fd=read_fd)

    def test_016_wrong_head_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "second.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=root, check=True)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=paths), self.assertRaises(FixedWorkerAuthorityError):
                issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)

    def test_017_alternative_state_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            alternative = paths.control_root / "alternative.json"
            alternative.write_bytes(paths.state.read_bytes())
            os.chmod(alternative, 0o600)
            altered = replace(paths, state=alternative)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=altered), self.assertRaises(FixedWorkerAuthorityError):
                issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)

    def test_018_wrong_role_predecessor_rejected(self):
        from .fixed_real_worker_authority_v1_2 import PREDICTOR_ROLE

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=paths), self.assertRaises(FixedWorkerAuthorityError):
                issue_fixed_real_worker_credential_v1_2(PREDICTOR_ROLE)

    def test_019_wrong_parent_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            document = json.loads(paths.parent_receipt.read_text())
            document["parent_nonce_commitment"] = "wrong"
            paths.parent_receipt.write_bytes(canonical_json_bytes(document))
            os.chmod(paths.parent_receipt, 0o600)
            patch_target = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            with mock.patch(patch_target, return_value=paths), self.assertRaises(FixedWorkerAuthorityError):
                issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)

    def test_019b_wrong_code_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _ = _build_real_authority_fixture(root)
            path_patch = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.resolve_fixed_real_d4_paths_v1_2"
            code_patch = "evaluation.capability_routing_rq2d3_r4_v1.fixed_real_worker_authority_v1_2.fixed_real_code_bundle_identity_v1_2"
            with (
                mock.patch(path_patch, return_value=paths),
                mock.patch(code_patch, return_value="0" * 64),
                self.assertRaises(FixedWorkerAuthorityError),
            ):
                issue_fixed_real_worker_credential_v1_2(FEATURE_ROLE)


class SentinelStateAndTerminalTests(unittest.TestCase):
    def test_020_sentinel_exclusive_mode_and_reread(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "control").mkdir(mode=0o700)
            target = root / "control/sentinel.json"
            receipt = create_reservation_sentinel_v1_2(target, _sentinel_document())
            self.assertTrue(receipt["created_exclusively"])
            self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode), 0o600)
            self.assertTrue(receipt["reread_verified"])

    def test_021_existing_valid_or_malformed_sentinel_blocks(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "control").mkdir(mode=0o700)
                target = root / "control/sentinel.json"
                if malformed:
                    target.write_bytes(b"malformed")
                    os.chmod(target, 0o600)
                else:
                    create_reservation_sentinel_v1_2(target, _sentinel_document())
                with self.assertRaisesRegex(ReservationSentinelError, ALREADY_RESERVED):
                    create_reservation_sentinel_v1_2(target, _sentinel_document())

    def test_022_symlink_sentinel_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "control").mkdir(mode=0o700)
            backing = root / "backing"
            backing.write_text("safe")
            target = root / "control/sentinel.json"
            target.symlink_to(backing)
            with self.assertRaisesRegex(ReservationSentinelError, ALREADY_RESERVED):
                create_reservation_sentinel_v1_2(target, _sentinel_document())

    def test_023_state_is_separate_and_initial_no_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "control").mkdir(mode=0o700)
            sentinel = root / "control/sentinel.json"
            identity = create_reservation_sentinel_v1_2(sentinel, _sentinel_document())
            state = root / "control/state.json"
            document = initial_execution_state_document_v1_2(
                execution_id="e" * 64,
                approved_head="a" * 40,
                effective_contract_id=SYNTHETIC_CONTRACT_ID,
                sentinel_sha256=identity["sha256"],
                synthetic=True,
            )
            initialise_execution_state_v1_2(state, sentinel, document, state_relative_path="control/state.json")
            self.assertNotEqual(state, sentinel)
            with self.assertRaises(NoReplaceArtifactError):
                initialise_execution_state_v1_2(state, sentinel, document, state_relative_path="control/state.json")

    def test_024_state_atomic_replace_and_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_synthetic_authority_fixture_v1_2(root)
            paths = synthetic_paths_v1_2(root)
            before, before_bytes = read_execution_state_v1_2(paths.state)
            updated = atomic_mutate_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                lambda document: document["administrative_events"].append({"event": "TEST"}),
            )
            self.assertEqual(updated["state_version"], before["state_version"] + 1)
            self.assertEqual(updated["previous_state_sha256"], sha256_bytes(before_bytes))
            self.assertEqual(updated["state_file_chain"][-1], sha256_bytes(before_bytes))

    def test_025_failed_and_completed_are_terminal(self):
        for previous, new, marker in (
            ("FAILED", "GLOBAL_RESERVED", "ALREADY_TERMINAL_FAILED"),
            ("FAILED", "FAILED", "ALREADY_TERMINAL_FAILED"),
            ("COMPLETED", "FAILED", "ALREADY_TERMINAL_COMPLETED"),
            ("COMPLETED", "COMPLETED", "ALREADY_TERMINAL_COMPLETED"),
        ):
            with self.subTest(previous=previous, new=new), self.assertRaisesRegex(TerminalStateError, marker):
                require_transition_v1_2(previous, new)

    def test_026_normal_to_failed_allowed_once_and_root_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_synthetic_authority_fixture_v1_2(root)
            paths = synthetic_paths_v1_2(root)
            failed = fail_execution_state_v1_2(
                paths.state, paths.sentinel, failure_code="FIRST", failure_stage="PARENT"
            )
            root_fields = tuple(failed[name] for name in ("root_failure_code", "root_failure_stage", "root_failure_timestamp", "root_failure_receipt"))
            with self.assertRaisesRegex(AtomicStateError, "ALREADY_TERMINAL_FAILED"):
                fail_execution_state_v1_2(paths.state, paths.sentinel, failure_code="SECOND", failure_stage="FAILED")
            with self.assertRaisesRegex(AtomicStateError, "ALREADY_TERMINAL_FAILED"):
                atomic_mutate_execution_state_v1_2(
                    paths.state,
                    paths.sentinel,
                    lambda document: document.update(root_failure_code="OVERWRITE"),
                )
            after, _ = read_execution_state_v1_2(paths.state)
            self.assertEqual(root_fields, tuple(after[name] for name in ("root_failure_code", "root_failure_stage", "root_failure_timestamp", "root_failure_receipt")))

    def test_027_chain_rejects_post_terminal(self):
        transitions = [
            {"previous_state": None, "current_state": "GLOBAL_RESERVED", "transition_index": 0},
            {"previous_state": "GLOBAL_RESERVED", "current_state": "FAILED", "transition_index": 1},
            {"previous_state": "FAILED", "current_state": "INPUT_IDENTITIES_VERIFIED", "transition_index": 2},
        ]
        with self.assertRaises(TerminalStateError):
            validate_transition_chain_v1_2(transitions, current_state="INPUT_IDENTITIES_VERIFIED")

    def test_028_state_loss_does_not_allow_reservation_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_synthetic_authority_fixture_v1_2(root)
            paths = synthetic_paths_v1_2(root)
            os.unlink(paths.state)
            with self.assertRaisesRegex(ReservationSentinelError, ALREADY_RESERVED):
                create_reservation_sentinel_v1_2(paths.sentinel, _sentinel_document())

    def test_029_completed_state_requires_full_completion_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_synthetic_authority_fixture_v1_2(root)
            paths = synthetic_paths_v1_2(root)
            current, _ = read_execution_state_v1_2(paths.state)
            start = NORMAL_STATES.index(current["current_state"]) + 1
            stop = NORMAL_STATES.index("RESULT_PERSISTED") + 1
            for state in NORMAL_STATES[start:stop]:
                transition_execution_state_v1_2(paths.state, paths.sentinel, state)
            with self.assertRaisesRegex(AtomicStateError, "COMPLETION_EVIDENCE"):
                transition_execution_state_v1_2(
                    paths.state,
                    paths.sentinel,
                    "COMPLETED",
                    evidence_summary={"completion_evidence": {"hard_failure_count": 0}},
                )

    def test_029b_completed_state_rejects_administrative_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_synthetic_authority_fixture_v1_2(root)
            paths = synthetic_paths_v1_2(root)
            current, _ = read_execution_state_v1_2(paths.state)
            start = NORMAL_STATES.index(current["current_state"]) + 1
            stop = NORMAL_STATES.index("RESULT_PERSISTED") + 1
            for state in NORMAL_STATES[start:stop]:
                transition_execution_state_v1_2(paths.state, paths.sentinel, state)
            completion_evidence = {
                "completion_eligible": True,
                "hard_failure_count": 0,
                "hard_failure_events": [],
                "required_workers_consumed_success": True,
                "required_stage_receipts_valid": True,
                "expected_open_read_counts_exact": True,
                "artifacts_bound": True,
                "state_chain_valid": True,
                "feature_prediction_binding_valid": True,
                "method_metric_complete": True,
                "statistical_complete": True,
            }
            transition_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                "COMPLETED",
                evidence_summary={"completion_evidence": completion_evidence},
            )
            before = paths.state.read_bytes()
            with self.assertRaisesRegex(AtomicStateError, "ALREADY_TERMINAL_COMPLETED"):
                atomic_mutate_execution_state_v1_2(
                    paths.state,
                    paths.sentinel,
                    lambda document: document["administrative_events"].append(
                        {"event": "POST_TERMINAL"}
                    ),
                )
            self.assertEqual(paths.state.read_bytes(), before)


class NoReplacePathReceiptAndDirectoryTests(unittest.TestCase):
    def test_030_no_replace_success_and_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir(mode=0o700)
            target = root / "artifacts/item.json"
            value = canonical_json_bytes({"schema_version": "test-artifact-v1-2"})
            receipt = publish_no_replace_artifact_v1_2(target, value, **_publish_kwargs())
            self.assertEqual(target.read_bytes(), value)
            self.assertEqual(stat.S_IMODE(os.lstat(target).st_mode), 0o600)
            self.assertTrue(receipt["atomic_no_replace_publication"])
            self.assertTrue(receipt["hard_link_publication"])

    def test_031_preexisting_target_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir(mode=0o700)
            target = root / "artifacts/item.json"
            target.write_bytes(b"owner\n")
            os.chmod(target, 0o600)
            with self.assertRaises(NoReplaceArtifactError):
                publish_no_replace_artifact_v1_2(target, canonical_json_bytes({"schema_version": "test-artifact-v1-2"}), **_publish_kwargs())
            self.assertEqual(target.read_bytes(), b"owner\n")

    def test_032_unsupported_no_replace_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir(mode=0o700)
            target = root / "artifacts/item.json"
            with mock.patch("os.link", side_effect=NotImplementedError), self.assertRaisesRegex(NoReplaceArtifactError, "NO_REPLACE_UNAVAILABLE"):
                publish_no_replace_artifact_v1_2(target, canonical_json_bytes({"schema_version": "test-artifact-v1-2"}), **_publish_kwargs())

    def test_033_path_validator_rejects_absolute_traversal_dot_uri_nul(self):
        invalid = ("/absolute", "a/../b", "a/./b", "file:///tmp/a", "a\x00b", "a//b", "~/a", "a\\b")
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(StrictPathError):
                validate_project_relative_path(value)

    def test_034_symlink_parent_and_target_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            (real / "item").write_text("safe")
            (root / "link").symlink_to(real, target_is_directory=True)
            with self.assertRaises(StrictPathError):
                open_regular_nofollow(root, "link/item")
            (root / "target_link").symlink_to(real / "item")
            with self.assertRaises(StrictPathError):
                open_regular_nofollow(root, "target_link")

    def test_035_strict_receipt_full_binding_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir(mode=0o700)
            target = root / "artifacts/item.json"
            value = canonical_json_bytes({"schema_version": "test-artifact-v1-2"})
            receipt = publish_no_replace_artifact_v1_2(target, value, **_publish_kwargs())
            expected = {key: receipt[key] for key in (
                "approved_head", "execution_id", "effective_contract_id", "worker_role",
                "worker_credential_commitment", "code_identity", "parent_state", "stage",
                "schema_id", "relative_path", "artifact_role", "open_read_counts",
                "firewall_summary",
            )}
            result = verify_strict_artifact_receipt_v1_2(root, receipt, expected_bindings=expected, schema_validator=json_object_validator("test-artifact-v1-2"))
            self.assertEqual(result["status"], "PASS")
            for field in expected:
                damaged = dict(receipt)
                damaged[field] = "wrong"
                with self.subTest(field=field), self.assertRaisesRegex(StrictReceiptError, RECEIPT_MISMATCH):
                    verify_strict_artifact_receipt_v1_2(root, damaged, expected_bindings=expected, schema_validator=json_object_validator("test-artifact-v1-2"))
            damaged = dict(receipt)
            damaged.pop("file_fsync")
            with self.assertRaisesRegex(StrictReceiptError, RECEIPT_MISMATCH):
                verify_strict_artifact_receipt_v1_2(root, damaged, expected_bindings=expected)

    def test_036_durable_directory_chain_and_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = create_durable_directory_tree_v1_2(root, "a/b/c")
            self.assertEqual(len(reports), 3)
            self.assertTrue(all(report["directory_created"] for report in reports))
            self.assertTrue(all(report["directory_mode"] == "0700" for report in reports))
            self.assertTrue(all(report["directory_fsync"] and report["parent_directory_fsync"] for report in reports))

    def test_037_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            (root / "link").symlink_to(real, target_is_directory=True)
            with self.assertRaises(DurableDirectoryError):
                create_durable_directory_tree_v1_2(root, "link/child")

    def test_038_receipt_sha_size_count_and_mode_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir(mode=0o700)
            target = root / "artifacts/item.json"
            receipt = publish_no_replace_artifact_v1_2(
                target,
                canonical_json_bytes({"schema_version": "test-artifact-v1-2"}),
                **_publish_kwargs(),
            )
            expected = {key: receipt[key] for key in (
                "approved_head", "execution_id", "effective_contract_id", "worker_role",
                "worker_credential_commitment", "code_identity", "parent_state", "stage",
                "schema_id", "relative_path", "artifact_role", "open_read_counts",
                "firewall_summary",
            )}
            for field, value in (
                ("sha256", "0" * 64),
                ("size_bytes", receipt["size_bytes"] + 1),
                ("record_count", 2),
                ("file_mode", "0644"),
            ):
                damaged = dict(receipt)
                damaged[field] = value
                with self.subTest(field=field), self.assertRaises(StrictReceiptError):
                    verify_strict_artifact_receipt_v1_2(root, damaged, expected_bindings=expected)

    def test_039_concurrent_race_forces_terminal_failed(self):
        result = run_synthetic_r4_integrity_harness_v1_2()["no_replace_race"]
        self.assertEqual(result["global_synthetic_execution_state"], "FAILED")
        self.assertEqual(result["root_failure_code"], "ARTIFACT_TARGET_RACE")
        self.assertFalse(result["retry_permitted"])


def _completion_state():
    required_receipts = [
        "FEATURE_ONLY_VIEW",
        "METHOD_LEVEL_METRICS",
        "FIXED_STATISTICAL_STATE",
    ]
    state = {
        "current_state": "RESULT_PERSISTED",
        "worker_roles": {
            role: {"status": "CONSUMED_SUCCESS"} for role in REQUIRED_WORKER_ROLES
        },
        "hard_failure_evidence": [],
        "firewall_evidence": [
            {"successful_forbidden_opens": 0, "successful_forbidden_imports": 0}
        ],
        "open_read_counters": {"combined_open": 1, "label_open": 1},
        "stage_receipts": [
            {"artifact_role": role} for role in required_receipts
        ],
    }
    return state, required_receipts


class CompletionAndSyntheticTests(unittest.TestCase):
    def test_040_completion_count_is_derived_and_zero_allows(self):
        state, roles = _completion_state()
        evidence = derive_completion_evidence_v1_2(
            state,
            required_stage_receipt_roles=roles,
            expected_open_read_counts={"combined_open": 1, "label_open": 1},
            artifacts_bound=True,
            state_chain_valid=True,
            feature_prediction_binding_valid=True,
            method_metric_complete=True,
            statistical_complete=True,
        )
        self.assertEqual(evidence["hard_failure_count"], len(evidence["hard_failure_events"]))
        self.assertTrue(evidence["completion_eligible"])
        require_completion_eligible_v1_2(evidence)

    def test_041_each_failure_category_blocks_completion(self):
        scenarios = []
        state, roles = _completion_state()
        broken_worker = json.loads(json.dumps(state))
        broken_worker["worker_roles"][REQUIRED_WORKER_ROLES[0]]["status"] = "FAILED"
        scenarios.append((broken_worker, roles, {}, {}))
        firewall = json.loads(json.dumps(state))
        firewall["firewall_evidence"][0]["successful_forbidden_opens"] = 1
        scenarios.append((firewall, roles, {}, {}))
        missing_receipt = json.loads(json.dumps(state))
        scenarios.append((missing_receipt, roles + ["MISSING"], {}, {}))
        open_mismatch = json.loads(json.dumps(state))
        scenarios.append((open_mismatch, roles, {"combined_open": 2}, {}))
        for index, (candidate, required, expected_override, check_override) in enumerate(scenarios):
            expected = {"combined_open": 1, "label_open": 1, **expected_override}
            evidence = derive_completion_evidence_v1_2(
                candidate,
                required_stage_receipt_roles=required,
                expected_open_read_counts=expected,
                artifacts_bound=True,
                state_chain_valid=True,
                feature_prediction_binding_valid=True,
                method_metric_complete=True,
                statistical_complete=True,
            )
            with self.subTest(index=index):
                self.assertGreater(evidence["hard_failure_count"], 0)
                self.assertFalse(evidence["completion_eligible"])

    def test_042_binding_metric_statistics_and_terminal_failures_counted(self):
        for key in (
            "artifacts_bound",
            "state_chain_valid",
            "feature_prediction_binding_valid",
            "method_metric_complete",
            "statistical_complete",
        ):
            state, roles = _completion_state()
            kwargs = {name: True for name in (
                "artifacts_bound", "state_chain_valid", "feature_prediction_binding_valid",
                "method_metric_complete", "statistical_complete",
            )}
            kwargs[key] = False
            evidence = derive_completion_evidence_v1_2(
                state,
                required_stage_receipt_roles=roles,
                expected_open_read_counts={"combined_open": 1, "label_open": 1},
                **kwargs,
            )
            with self.subTest(key=key):
                self.assertGreater(evidence["hard_failure_count"], 0)
        state, roles = _completion_state()
        state["current_state"] = "PRIMARY_STATISTICS_PERSISTED"
        evidence = derive_completion_evidence_v1_2(
            state,
            required_stage_receipt_roles=roles,
            expected_open_read_counts={"combined_open": 1, "label_open": 1},
            artifacts_bound=True, state_chain_valid=True, feature_prediction_binding_valid=True,
            method_metric_complete=True, statistical_complete=True,
        )
        self.assertTrue(any(event["category"] == "terminal_state_violation" for event in evidence["hard_failure_events"]))

    def test_043_no_constant_zero_assignment(self):
        source = (HERE / "completion_evidence_v1_2.py").read_text()
        tree = ast.parse(source)
        constant_zero = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "hard_failure_count" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and node.value.value == 0
        ]
        self.assertEqual(constant_zero, [])

    def test_044_completion_bundle_is_complete(self):
        values = {field: ({"status": "PASS"} if field not in {"all_stage_receipts", "worker_credential_commitments", "worker_role_terminal_states", "runtime_firewall_report_identities", "evidence_derived_hard_failure_count"} else None) for field in REQUIRED_COMPLETION_FIELDS}
        values["all_stage_receipts"] = [{"artifact_role": "SAFE"}]
        values["worker_credential_commitments"] = {"role": "c" * 64}
        values["worker_role_terminal_states"] = {"role": "CONSUMED_SUCCESS"}
        values["runtime_firewall_report_identities"] = [{"sha256": "f" * 64}]
        values["evidence_derived_hard_failure_count"] = 0
        bundle = build_completion_bundle_v1_2(**values)
        validate_completion_bundle_v1_2(bundle)
        values.pop("final_result_identity")
        with self.assertRaises(CompletionBundleError):
            build_completion_bundle_v1_2(**values)

    def test_045_synthetic_harness_three_processes_and_races(self):
        result = run_synthetic_r4_integrity_harness_v1_2()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["separate_worker_process_count"], 3)
        self.assertEqual(result["concurrent_sentinel"]["winner_count"], 1)
        self.assertTrue(result["no_replace_race"]["racer_target_preserved"])
        self.assertFalse(result["no_replace_race"]["false_receipt_generated"])
        self.assertTrue(result["state_crash_and_failed_terminality"]["root_failure_immutable"])

    def test_046_synthetic_harness_deterministic(self):
        first = run_synthetic_r4_integrity_harness_v1_2()
        second = run_synthetic_r4_integrity_harness_v1_2()
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))

    def test_047_synthetic_workers_do_not_import_real_entries(self):
        for name in (
            "synthetic_feature_worker_v1_2.py",
            "synthetic_predictor_worker_v1_2.py",
            "synthetic_metric_worker_v1_2.py",
        ):
            tree = ast.parse((HERE / name).read_text())
            imports = [
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            ]
            self.assertFalse(any("real_" in module for module in imports))

    def test_048_temp_lock_bypass_and_synthetic_authority_rejected(self):
        result = run_synthetic_r4_integrity_harness_v1_2()
        self.assertTrue(result["real_worker_temp_lock_bypass"]["caller_temp_lock_rejected"])
        self.assertTrue(result["real_worker_temp_lock_bypass"]["synthetic_credential_rejected"])
        self.assertTrue(result["real_worker_temp_lock_bypass"]["self_consistent_synthetic_authority_used"])
        self.assertEqual(result["real_worker_temp_lock_bypass"]["restricted_input_open_count"], 0)
        self.assertEqual(result["restricted_track_b_open_count"], 0)

    def test_049_failure_and_completion_retain_sentinel(self):
        result = run_synthetic_r4_integrity_harness_v1_2()
        self.assertTrue(result["sentinel_retained_and_unchanged"])
        self.assertTrue(result["state_crash_and_failed_terminality"]["sentinel_unchanged"])


class GovernanceAndFinalisationTests(unittest.TestCase):
    def test_050_all_new_python_ast(self):
        for path in HERE.glob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path))

    def test_051_no_real_d4_paths_created(self):
        self.assertFalse((ROOT / CONTROL_ROOT_RELATIVE).exists())
        self.assertFalse((ROOT / OUTPUT_ROOT_RELATIVE).exists())

    def test_052_validation_report_boundaries(self):
        report = json.loads((HERE / "rq2d3_r4_validation_report_v1.json").read_text())
        zero_fields = (
            "mapping_access_count", "canonical_case_bank_access_count",
            "combined_source_content_read_count", "label_gold_content_read_count",
            "real_track_b_inference_count", "real_track_b_prediction_count",
            "real_track_b_metric_count", "hidden_legacy_access_count", "raw_track_b_access_count",
            "blind_key_access_count", "d4_execution_count", "p2_execution_count",
            "provider_calls", "production_change_count",
        )
        self.assertTrue(all(report[field] == 0 for field in zero_fields))
        self.assertFalse(report["network_access"])

    def test_053_final_artifact_writer_does_not_use_replace(self):
        source = (HERE / "durable_no_replace_artifact_v1_2.py").read_text()
        self.assertNotIn("os.replace(", source)
        self.assertIn("os.link(", source)

    def test_054_only_state_module_uses_replace_in_harness(self):
        uses = []
        for path in HERE.glob("*.py"):
            tree = ast.parse(path.read_text())
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                for node in ast.walk(tree)
            ):
                uses.append(path.name)
        self.assertEqual(set(uses), {"atomic_execution_state_v1_2.py", "validate_rq2d3_r4.py"})

    def test_055_protected_sources(self):
        _protected_source_check()

    def test_056_output_checksums(self):
        result = validate_outputs()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checksum_count"], len(checksum_targets()))

    def test_057_review_package_completeness_projection(self):
        members = _review_members()
        referenced = {
            line.split("  ", 1)[1]
            for line in (ROOT / CHECKSUM_RELATIVE).read_text().splitlines()
            if line
        }
        self.assertTrue(referenced <= set(members))
        self.assertEqual(len(referenced), len(checksum_targets()))

    def test_058_double_finalisation_byte_identical(self):
        tracked = [path for path in checksum_targets() if path.suffix in {".json", ".sha256"}]
        before = {str(path): path.read_bytes() for path in tracked}
        build_outputs()
        after = {str(path): path.read_bytes() for path in tracked}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
