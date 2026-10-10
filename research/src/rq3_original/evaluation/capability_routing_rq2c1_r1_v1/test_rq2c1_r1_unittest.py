"""Adversarial and end-to-end tests for the RQ2-C1-R1 correction."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from . import (
    ORIGINAL_C1_TRACKED_MANIFEST_SHA256,
    PRIMARY_PERSISTENT_POLICY,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    canonical_json_bytes,
    sha256_file,
)
from .c1_identity import (
    assert_partition_access_allowed,
    verify_original_c1_identity,
    verify_starting_preflight,
)
from .corrected_evaluation import (
    run_persistent_retrieval_v1_1,
    validated_query_plan_v1_1,
)
from .finalise_rq2c1_r1 import (
    CHECKSUM_NAME,
    expected_review_members,
    finalise_rq2c1_r1,
    parse_output_checksums,
    safe_outputs,
)
from .mechanism_metrics_v1_1 import case_scoped_admission_metrics
from .offline_memory_store_v1_1 import (
    OfflinePersistentMemoryStoreV1_1,
    StoreIntegrityError,
)
from .offline_memory_write_engine_v1_1 import (
    CorrectionTargetError,
    build_validated_bundle_v1_1,
    resolve_correction_target_v1_1,
)
from .p2_condition_runner_v1_1 import (
    ConditionIsolationError,
    execute_rag_for_condition_v1_1,
)
from .run_rq2c1_r1 import run_rq2c1_r1
from .runtime_safety_instrumentation import (
    RuntimeSafetyEventLedgerV1,
    SAFETY_EVENT_TYPES,
)
from .validate_rq2c1_r1 import (
    governed_text_leak_scan,
    protected_source_comparison,
    validate_local_artifacts_ignored,
    validate_output_checksums,
    validate_python_ast,
    validate_safe_outputs,
    validate_temporal_imports,
)
from .validated_execution_context_v1_1 import (
    ExecutionContextError,
    create_validated_execution_context_v1_1,
    verify_execution_context_v1_1,
)


class RQ2C1R1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_rq2c1_r1()
        cls.finalised = finalise_rq2c1_r1(cls.result)

    def _ledger(self, suffix: str) -> RuntimeSafetyEventLedgerV1:
        path = (
            Path(__file__).parent
            / "local_artifacts/tests"
            / f"safety_{suffix}.jsonl"
        )
        ledger = RuntimeSafetyEventLedgerV1(path)
        ledger.reset_local_file()
        return ledger

    def _store(
        self,
        *,
        memory_id: str = "memory-test-a",
        student: str = "student-test-a",
        memory_type: str = "GOAL",
        status: str = "ACTIVE",
        ledger: RuntimeSafetyEventLedgerV1 | None = None,
    ):
        bundle = build_validated_bundle_v1_1(
            memory_id=memory_id,
            student_scope_id=student,
            memory_type=memory_type,
            text=f"controlled text for {memory_id}",
            status=status,
        )
        store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
        store.write_bundle(bundle)
        return store, bundle

    def _context(self, *, status: str = "ACTIVE", targets=("GOAL",)):
        store, bundle = self._store(status=status)
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="continue my saved goal",
            target_memory_types=targets,
        )
        context = create_validated_execution_context_v1_1(
            plan=plan,
            bundle=bundle,
            snapshot=store.snapshot("student-test-a"),
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="request-test-a",
        )
        return store, bundle, plan, context

    def test_001_starting_identity_and_branch(self) -> None:
        start = verify_starting_preflight()
        self.assertEqual(start["status"], "PASS")
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=ROOT, text=True
            ).strip(),
            RESULT_BRANCH,
        )

    def test_002_c1_and_r5_output_checksums(self) -> None:
        checks = self.result.starting_preflight["output_checksums"]
        self.assertEqual(checks["C1"]["checksum_count"], 42)
        self.assertEqual(checks["R5"]["checksum_count"], 26)
        self.assertEqual(checks["C1"]["failure_count"], 0)
        self.assertEqual(checks["R5"]["failure_count"], 0)

    def test_003_fixture_p1_and_gold_identity(self) -> None:
        start = self.result.starting_preflight
        self.assertEqual(start["fixture"]["record_count"], 28)
        self.assertEqual(start["p1_policy"], "P1_D05_SIGNAL_UNION")
        self.assertEqual(
            start["gold_bundle_sha256"],
            "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c",
        )
        self.assertEqual(start["gold_counts"], {"synthetic": 35, "authentic": 22, "context_missing": 3})

    def test_004_original_c1_byte_identical(self) -> None:
        identity = verify_original_c1_identity()
        self.assertEqual(identity["tracked_file_count"], 43)
        self.assertEqual(
            identity["tracked_manifest_sha256"],
            ORIGINAL_C1_TRACKED_MANIFEST_SHA256,
        )
        self.assertTrue(identity["byte_identical_to_original_head"])

    def test_005_write_delete_complete_rejected(self) -> None:
        ledger = self._ledger("resurrection")
        store, bundle = self._store(ledger=ledger)
        store.apply_state_event(
            bundle.episode.memory_id, "DELETE", "2026-08-27T10:00:00+00:00"
        )
        with self.assertRaisesRegex(StoreIntegrityError, "INVALID_STORE_STATE_TRANSITION"):
            store.apply_state_event(
                bundle.episode.memory_id,
                "COMPLETE",
                "2026-08-27T10:01:00+00:00",
            )
        self.assertEqual(
            ledger.aggregate()["event_types"]["DELETED_MEMORY_RESURRECTION_ATTEMPT"][
                "blocked_count"
            ],
            1,
        )

    def test_006_tombstone_permanent_under_replay(self) -> None:
        store, bundle = self._store()
        store.apply_state_event(
            bundle.episode.memory_id, "DELETE", "2026-08-27T10:00:00+00:00"
        )
        first = store.snapshot("student-test-a")
        second = store.snapshot("student-test-a")
        self.assertEqual(first, second)
        self.assertIn(bundle.episode.memory_id, first.tombstoned_memory_ids)
        self.assertTrue(store.safe_event_manifest()["tombstone_replay_identical"])

    def test_007_deleted_never_returns_to_active_set(self) -> None:
        store, bundle = self._store()
        store.apply_state_event(
            bundle.episode.memory_id, "DELETE", "2026-08-27T10:00:00+00:00"
        )
        snapshot = store.snapshot("student-test-a")
        self.assertNotIn(bundle.episode.memory_id, snapshot.active_memory_ids)

    def test_008_event_before_ingested_at_rejected(self) -> None:
        store, bundle = self._store()
        with self.assertRaisesRegex(StoreIntegrityError, "BACKDATED_STORE_EVENT"):
            store.apply_state_event(
                bundle.episode.memory_id, "DELETE", "2026-01-01T00:00:01+00:00"
            )

    def test_009_event_before_previous_event_rejected(self) -> None:
        store, bundle = self._store()
        store.apply_state_event(
            bundle.episode.memory_id, "COMPLETE", "2026-08-27T10:00:00+00:00"
        )
        with self.assertRaisesRegex(StoreIntegrityError, "BACKDATED_STORE_EVENT"):
            store.apply_state_event(
                bundle.episode.memory_id, "DELETE", "2026-08-27T09:59:00+00:00"
            )

    def test_010_naive_event_time_rejected(self) -> None:
        store, bundle = self._store()
        with self.assertRaisesRegex(StoreIntegrityError, "NAIVE_STORE_EVENT_TIME"):
            store.apply_state_event(
                bundle.episode.memory_id, "DELETE", "2026-08-27T10:00:00"
            )

    def test_011_manually_forged_context_rejected(self) -> None:
        store, _bundle, _plan, context = self._context()
        forged = replace(context, _factory_token=object())
        with self.assertRaises(ExecutionContextError):
            verify_execution_context_v1_1(
                forged,
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-test-a",
            )

    def test_012_bundle_not_in_store_rejected(self) -> None:
        _store, bundle = self._store()
        other = OfflinePersistentMemoryStoreV1_1()
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="continue goal",
            target_memory_types=("GOAL",),
        )
        with self.assertRaisesRegex(ExecutionContextError, "MEMORY_NOT_IN_CURRENT_STORE"):
            create_validated_execution_context_v1_1(
                plan=plan,
                bundle=bundle,
                snapshot=other.snapshot("student-test-a"),
                store=other,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-other",
            )

    def test_013_plan_bundle_scope_mismatch_rejected(self) -> None:
        store, bundle = self._store()
        plan = validated_query_plan_v1_1(
            student_scope_id="student-other",
            original_query="continue goal",
            target_memory_types=("GOAL",),
        )
        with self.assertRaisesRegex(ExecutionContextError, "CROSS_STUDENT_SCOPE"):
            create_validated_execution_context_v1_1(
                plan=plan,
                bundle=bundle,
                snapshot=store.snapshot("student-other"),
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-cross",
            )

    def test_014_snapshot_fingerprint_tamper_rejected(self) -> None:
        store, bundle = self._store()
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="continue goal",
            target_memory_types=("GOAL",),
        )
        snapshot = replace(
            store.snapshot("student-test-a"), snapshot_fingerprint="0" * 64
        )
        with self.assertRaisesRegex(ExecutionContextError, "STALE_STORE_SNAPSHOT"):
            create_validated_execution_context_v1_1(
                plan=plan,
                bundle=bundle,
                snapshot=snapshot,
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-snapshot",
            )

    def test_015_projection_hash_tamper_rejected(self) -> None:
        store, bundle = self._store()
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="continue goal",
            target_memory_types=("GOAL",),
        )
        snapshot = replace(store.snapshot("student-test-a"), projection_hash="0" * 64)
        with self.assertRaisesRegex(ExecutionContextError, "STALE_STORE_SNAPSHOT"):
            create_validated_execution_context_v1_1(
                plan=plan,
                bundle=bundle,
                snapshot=snapshot,
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-projection",
            )

    def test_016_context_fingerprint_tamper_rejected(self) -> None:
        store, _bundle, _plan, context = self._context()
        with self.assertRaises(ExecutionContextError):
            verify_execution_context_v1_1(
                replace(context, context_fingerprint="0" * 64),
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-test-a",
            )

    def test_017_revision_change_invalidates_context(self) -> None:
        store, _bundle, _plan, context = self._context()
        extra = build_validated_bundle_v1_1(
            memory_id="memory-test-extra",
            student_scope_id="student-test-a",
            memory_type="PREFERENCE",
            text="controlled preference extra",
        )
        store.write_bundle(extra)
        with self.assertRaisesRegex(ExecutionContextError, "STALE_STORE_SNAPSHOT"):
            verify_execution_context_v1_1(
                context,
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-test-a",
            )

    def test_018_completed_target_completion_allowed(self) -> None:
        store, bundle = self._store(
            memory_type="COMPLETION", status="COMPLETED"
        )
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="show completion",
            target_memory_types=("COMPLETION",),
        )
        context = create_validated_execution_context_v1_1(
            plan=plan,
            bundle=bundle,
            snapshot=store.snapshot("student-test-a"),
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="request-completion",
        )
        verify_execution_context_v1_1(
            context,
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="request-completion",
        )
        retrieval = run_persistent_retrieval_v1_1(
            policy_id=PRIMARY_PERSISTENT_POLICY,
            plan=plan,
            store=store,
        )
        self.assertEqual(retrieval.retrieved_memory_ids, (bundle.episode.memory_id,))
        self.assertEqual(retrieval.admitted_memory_ids, (bundle.episode.memory_id,))

    def test_019_completed_noncompletion_target_rejected(self) -> None:
        store, bundle = self._store(status="COMPLETED")
        plan = validated_query_plan_v1_1(
            student_scope_id="student-test-a",
            original_query="continue goal",
            target_memory_types=("GOAL",),
        )
        with self.assertRaisesRegex(ExecutionContextError, "COMPLETED_NOT_REQUESTED"):
            create_validated_execution_context_v1_1(
                plan=plan,
                bundle=bundle,
                snapshot=store.snapshot("student-test-a"),
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
                request_fingerprint="request-not-completion",
            )

    def test_020_r5_aware_time_static_contract(self) -> None:
        self.assertEqual(validate_temporal_imports()["status"], "PASS")

    def test_021_explicit_correction_target_exact(self) -> None:
        store = OfflinePersistentMemoryStoreV1_1()
        for suffix in ("a", "b"):
            store.write_bundle(
                build_validated_bundle_v1_1(
                    memory_id=f"memory-correction-{suffix}",
                    student_scope_id="student-correction",
                    memory_type="PREFERENCE",
                    text=f"controlled preference {suffix}",
                )
            )
        target, basis = resolve_correction_target_v1_1(
            value={
                "student_scope_id": "student-correction",
                "supersedes_memory_id": "memory-correction-b",
            },
            store=store,
        )
        self.assertEqual(target, "memory-correction-b")
        self.assertEqual(basis, "EXPLICIT_MEMORY_ID")

    def test_022_ambiguous_correction_target_rejected(self) -> None:
        store = OfflinePersistentMemoryStoreV1_1()
        for suffix in ("a", "b"):
            store.write_bundle(
                build_validated_bundle_v1_1(
                    memory_id=f"memory-ambiguous-{suffix}",
                    student_scope_id="student-ambiguous",
                    memory_type="PREFERENCE",
                    text=f"controlled ambiguous {suffix}",
                )
            )
        with self.assertRaisesRegex(CorrectionTargetError, "AMBIGUOUS_CORRECTION_TARGET"):
            resolve_correction_target_v1_1(
                value={"student_scope_id": "student-ambiguous"}, store=store
            )

    def test_023_zero_correction_target_rejected(self) -> None:
        with self.assertRaisesRegex(CorrectionTargetError, "CORRECTION_TARGET_NOT_FOUND"):
            resolve_correction_target_v1_1(
                value={"student_scope_id": "student-empty"},
                store=OfflinePersistentMemoryStoreV1_1(),
            )

    def test_024_lexicographic_target_selection_not_used(self) -> None:
        contract = self.result.correction_contract
        self.assertFalse(contract["lexicographic_target_selection_used"])
        self.assertEqual(
            contract["multiple_candidate_failure"], "AMBIGUOUS_CORRECTION_TARGET"
        )

    def test_025_p1_base_actual_rag_calls_zero(self) -> None:
        for dataset in self.result.rag_isolation["datasets"].values():
            self.assertEqual(
                dataset["conditions"]["P1_BASE"]["actual_retriever_call_count"], 0
            )

    def test_026_session_only_actual_rag_calls_zero(self) -> None:
        for dataset in self.result.rag_isolation["datasets"].values():
            self.assertEqual(
                dataset["conditions"]["P2_SESSION_STATE_ONLY"][
                    "actual_retriever_call_count"
                ],
                0,
            )

    def test_027_persistent_only_actual_rag_calls_zero(self) -> None:
        for dataset in self.result.rag_isolation["datasets"].values():
            self.assertEqual(
                dataset["conditions"]["P2_PERSISTENT_MEMORY_ONLY"][
                    "actual_retriever_call_count"
                ],
                0,
            )

    def test_028_rag_only_calls_equal_candidate_count(self) -> None:
        for dataset in self.result.rag_isolation["datasets"].values():
            value = dataset["conditions"]["P2_RAG_ONLY"]
            self.assertEqual(
                value["actual_retriever_call_count"], value["candidate_gate_count"]
            )

    def test_029_full_calls_equal_candidate_count(self) -> None:
        for dataset in self.result.rag_isolation["datasets"].values():
            value = dataset["conditions"]["P2_FULL"]
            self.assertEqual(
                value["actual_retriever_call_count"], value["candidate_gate_count"]
            )

    def test_030_disabled_rag_execution_guard_records_attempt(self) -> None:
        ledger = self._ledger("disabled-rag")
        with self.assertRaisesRegex(ConditionIsolationError, "RAG_DISABLED_FOR_CONDITION"):
            execute_rag_for_condition_v1_1(
                condition_id="P1_BASE",
                candidate_allowed=True,
                effective_query="probe",
                safety_ledger=ledger,
            )
        self.assertEqual(
            ledger.aggregate()["event_types"]["RAG_EXECUTION_IN_DISABLED_CONDITION"][
                "attempt_count"
            ],
            1,
        )

    def test_031_runtime_safety_counters_are_ledger_derived(self) -> None:
        safety = self.result.runtime_safety
        self.assertTrue(safety["aggregate_runtime_derived"])
        self.assertFalse(safety["hardcoded_zero_counter_used"])
        self.assertEqual(set(safety["event_types"]), set(SAFETY_EVENT_TYPES))
        self.assertTrue(all(value["attempt_count"] >= 1 for value in safety["event_types"].values()))

    def test_032_all_safety_attempts_blocked_no_success(self) -> None:
        safety = self.result.runtime_safety
        self.assertEqual(safety["attempt_count"], safety["blocked_count"])
        self.assertEqual(safety["successful_violation_count"], 0)
        self.assertEqual(safety["hard_failure_count"], 0)

    def test_033_case_scoped_admission_identity(self) -> None:
        metrics = case_scoped_admission_metrics(
            [("fixture-a", "memory-shared"), ("fixture-b", "memory-shared")],
            [("fixture-a", "memory-shared"), ("fixture-b", "memory-shared")],
        )
        self.assertEqual(metrics["true_positive"], 2)
        self.assertEqual(metrics["identity"], "(fixture_id, memory_id)")

    def test_034_controlled_results_and_four_policies(self) -> None:
        self.assertEqual(self.result.controlled.rag_results["rag_fixture_count"], 14)
        policies = self.result.controlled.memory_results["persistent_policy_comparison"]
        self.assertEqual(len(policies["policy_results"]), 4)
        self.assertEqual(policies["primary_policy_id"], PRIMARY_PERSISTENT_POLICY)

    def test_035_primary_completed_not_requested_zero(self) -> None:
        primary = self.result.controlled.memory_results["persistent_policy_comparison"][
            "policy_results"
        ][PRIMARY_PERSISTENT_POLICY]
        self.assertEqual(
            primary["safety_counts"]["completed_not_requested_admission_count"], 0
        )
        self.assertEqual(primary["admission"]["identity"], "(fixture_id, memory_id)")

    def test_036_synthetic35_nested_oof_and_policy(self) -> None:
        session = self.result.session_results
        self.assertEqual(session["nested_oof"]["case_count"], 35)
        self.assertEqual(session["nested_oof"]["family_count"], 18)
        self.assertTrue(session["nested_oof"]["each_case_oof_exactly_once"])
        self.assertEqual(
            session["final_session_policy"]["selected_policy_id"], "M0_P1_ONLY"
        )

    def test_037_authentic22_descriptive_only(self) -> None:
        result = self.result.authentic_results
        self.assertEqual(result["record_count"], 22)
        self.assertEqual(result["evidence_role"], "DESCRIPTIVE_IN_SAMPLE_ONLY")
        self.assertEqual(result["policy_selection_use"], "NOT_USED_FOR_POLICY_SELECTION")

    def test_038_context_missing3_separate(self) -> None:
        result = self.result.context_missing_results
        self.assertEqual(result["record_count"], 3)
        self.assertFalse(result["included_in_authentic_aggregate"])
        self.assertFalse(result["memory_auto_constructed"])

    def test_039_original_vs_corrected_delta_preserves_metrics(self) -> None:
        delta = self.result.delta_results
        self.assertTrue(delta["persistent_metrics_unchanged_after_correctness_repair"])
        self.assertFalse(delta["session_policy_change"]["changed"])
        self.assertFalse(delta["original_files_overwritten"])

    def test_040_local_artifacts_ignored_untracked(self) -> None:
        self.assertEqual(validate_local_artifacts_ignored()["status"], "PASS")

    def test_041_safe_outputs_ast_checksums_and_leak_scan(self) -> None:
        self.assertEqual(validate_safe_outputs()["status"], "PASS")
        self.assertEqual(validate_python_ast()["status"], "PASS")
        self.assertEqual(validate_output_checksums()["status"], "PASS")
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_042_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["status"], "PASS")

    def test_043_double_finalisation_byte_identical(self) -> None:
        before = {relative: sha256_file(ROOT / relative) for relative in parse_output_checksums()}
        manifest_before = sha256_file(Path(__file__).parent / CHECKSUM_NAME)
        finalise_rq2c1_r1(self.result)
        after = {relative: sha256_file(ROOT / relative) for relative in parse_output_checksums()}
        self.assertEqual(before, after)
        self.assertEqual(
            manifest_before, sha256_file(Path(__file__).parent / CHECKSUM_NAME)
        )

    def test_044_corrected_double_run_byte_identical(self) -> None:
        first = hashlib.sha256(
            canonical_json_bytes(safe_outputs(self.result), pretty=False)
        ).hexdigest()
        second_result = run_rq2c1_r1()
        second = hashlib.sha256(
            canonical_json_bytes(safe_outputs(second_result), pretty=False)
        ).hexdigest()
        self.assertEqual(first, second)
        finalise_rq2c1_r1(second_result)

    def test_045_review_completeness_contract(self) -> None:
        referenced = set(parse_output_checksums())
        members = set(expected_review_members())
        self.assertTrue(referenced <= members)
        self.assertIn("REVIEW/REVIEW_CHECKSUMS.sha256", members)

    def test_046_no_track_partitions(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def test_047_no_provider_network_training_or_production(self) -> None:
        runtime = self.result.runtime_preflight
        self.assertEqual(runtime["provider_calls"], 0)
        self.assertFalse(runtime["network_access"])
        self.assertFalse(runtime["model_training"])
        validation = json.loads(
            (
                Path(__file__).parent
                / "rq2c1_r1_validation_report_v1.json"
            ).read_text()
        )
        self.assertFalse(validation["production_integration"])


if __name__ == "__main__":
    unittest.main()
