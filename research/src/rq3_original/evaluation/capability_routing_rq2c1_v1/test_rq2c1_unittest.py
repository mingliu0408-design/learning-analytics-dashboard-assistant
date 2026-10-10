"""Contract, mechanism, evaluation, and governance tests for RQ2-C1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import unittest

from evaluation.capability_routing_rq2c0_r2_v1.write_candidate_contract import (
    StructuredWriteCandidateV1,
    evaluate_structured_write_candidate,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)

from . import (
    EXPECTED_FIXTURE_COUNT,
    EXPECTED_FIXTURE_SHA256,
    GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY_SHA256,
    PERSISTENT_POLICY_IDS,
    PRIMARY_PERSISTENT_POLICY,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)
from .controlled_fixture_loader import expected_field_access_audit, load_controlled_fixtures
from .finalise_rq2c1 import (
    CHECKSUM_NAME,
    expected_review_members,
    finalise_rq2c1,
    parse_output_checksums,
)
from .offline_dual_gated_rag import run_candidate_gate_fixture
from .offline_memory_store import OfflinePersistentMemoryStoreV1, StoreIntegrityError
from .offline_memory_write_engine import build_validated_bundle
from .offline_persistent_retrieval_engine import (
    run_persistent_retrieval,
    validated_query_plan,
)
from .offline_session_state_gate import (
    SessionStateInput,
    run_session_state_gate,
)
from .run_rq2c1 import run_rq2c1
from .starting_state import assert_partition_access_allowed, verify_starting_state
from .validated_execution_context import (
    ExecutionContextError,
    create_validated_execution_context,
    verify_execution_context,
)
from .validate_rq2c1 import (
    governed_text_leak_scan,
    protected_source_comparison,
    validate_local_artifacts_ignored,
    validate_output_checksums,
    validate_python_ast,
    validate_safe_outputs,
)


class RQ2C1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_rq2c1()
        cls.finalised = finalise_rq2c1(cls.result)

    def test_001_starting_branch_head_parent(self) -> None:
        self.assertEqual(
            subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
            RESULT_BRANCH,
        )
        self.assertEqual(
            subprocess.check_output(["git", "rev-parse", f"{STARTING_HEAD}^"], cwd=ROOT, text=True).strip(),
            STARTING_PARENT,
        )

    def test_002_starting_r5_and_historical_checksums(self) -> None:
        start = verify_starting_state()
        self.assertEqual(start["status"], "PASS")
        self.assertEqual(
            {key: value["checksum_count"] for key, value in start["output_checksums"].items()},
            {"RQ2B": 36, "R2": 36, "R3": 18, "R4": 22, "R5": 26},
        )

    def test_003_fixture_gold_p1_c0_identities(self) -> None:
        start = self.result.starting_preflight
        self.assertEqual(start["local_inputs"]["fixture"]["sha256"], EXPECTED_FIXTURE_SHA256)
        self.assertEqual(start["local_inputs"]["fixture"]["record_count"], EXPECTED_FIXTURE_COUNT)
        self.assertEqual(start["frozen_runtime"]["gold_bundle_sha256"], GOLD_BUNDLE_SHA256)
        self.assertEqual(start["frozen_runtime"]["p1_policy_sha256"], EXPECTED_P1_POLICY_SHA256)
        self.assertEqual(start["frozen_runtime"]["candidate_record_count"], 62)
        self.assertEqual(start["frozen_runtime"]["candidate_label_count"], 16)

    def test_004_expected_and_gold_fields_excluded_from_prediction(self) -> None:
        audit = expected_field_access_audit()
        self.assertEqual(audit["expected_fields_present_in_prediction_view"], [])
        self.assertFalse(audit["gold_feature_used"])
        self.assertFalse(audit["source_role_used"])
        self.assertFalse(audit["scenario_family_used_as_feature"])

    def test_005_fixture_views_are_separate(self) -> None:
        fixtures = load_controlled_fixtures()
        self.assertEqual(len(fixtures.prediction_inputs), 28)
        self.assertEqual(len(fixtures.scoring_targets), 28)
        self.assertNotIn("expected_retrieval_ids", vars(fixtures.prediction_inputs[0]))

    def test_006_track_partitions_rejected(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def _store(self) -> tuple[OfflinePersistentMemoryStoreV1, object]:
        bundle = build_validated_bundle(
            memory_id="memory-test-a",
            student_scope_id="student-test-a",
            memory_type="GOAL",
            text="A governed saved goal for the controlled test",
            entities=("module_alpha",),
        )
        store = OfflinePersistentMemoryStoreV1()
        store.write_bundle(bundle)
        return store, bundle

    def test_007_store_append_only_unique_and_monotonic(self) -> None:
        store, bundle = self._store()
        self.assertEqual(store.store_revision, 1)
        with self.assertRaises(StoreIntegrityError):
            store.write_bundle(bundle)
        store.apply_state_event("memory-test-a", "COMPLETE", "2026-08-27T10:00:00+00:00")
        self.assertEqual(store.store_revision, 2)
        self.assertEqual([event.store_revision for event in store.events], [1, 2])

    def test_008_immutable_bundle_and_projection_status(self) -> None:
        store, bundle = self._store()
        with self.assertRaises(FrozenInstanceError):
            bundle.episode.status = "DELETED"  # type: ignore[misc]
        store.apply_state_event("memory-test-a", "CANCEL", "2026-08-27T10:00:00+00:00")
        self.assertEqual(bundle.episode.status, "ACTIVE")
        self.assertEqual(store.status("memory-test-a"), "CANCELLED")

    def test_009_supersession_completion_cancellation_deletion(self) -> None:
        for event, status in (
            ("SUPERSEDE", "SUPERSEDED"),
            ("COMPLETE", "COMPLETED"),
            ("CANCEL", "CANCELLED"),
            ("DELETE", "DELETED"),
        ):
            store, _bundle = self._store()
            store.apply_state_event("memory-test-a", event, "2026-08-27T10:00:00+00:00")
            self.assertEqual(store.status("memory-test-a"), status)
            self.assertEqual(len(store.bundles), 1)

    def test_010_snapshot_deterministic_and_tombstone(self) -> None:
        store, _bundle = self._store()
        first = store.snapshot("student-test-a")
        second = store.snapshot("student-test-a")
        self.assertEqual(first, second)
        store.apply_state_event("memory-test-a", "DELETE", "2026-08-27T10:00:00+00:00")
        self.assertIn("memory-test-a", store.snapshot("student-test-a").tombstoned_memory_ids)

    def test_011_simulated_cross_session_persistence(self) -> None:
        store, _bundle = self._store()
        self.assertEqual(store.begin_logical_session(), 1)
        self.assertEqual(store.begin_logical_session(), 2)
        self.assertEqual(len(store.bundles), 1)

    def test_012_validated_plan_and_bundle_required(self) -> None:
        store, bundle = self._store()
        plan = validated_query_plan(
            student_scope_id="student-test-a", original_query="Continue my saved goal"
        )
        snapshot = store.snapshot("student-test-a")
        context = create_validated_execution_context(
            plan=plan,
            bundle=bundle,
            snapshot=snapshot,
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="request-a",
        )
        verify_execution_context(
            context,
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="request-a",
        )
        with self.assertRaises(PermissionError):
            require_validated_bundle_for_interface_v1_4(object(), "EMBEDDING_INPUT_BUILDER")  # type: ignore[arg-type]

    def test_013_stale_snapshot_cross_query_and_condition_rejected(self) -> None:
        store, bundle = self._store()
        plan = validated_query_plan(student_scope_id="student-test-a", original_query="saved goal")
        context = create_validated_execution_context(
            plan=plan,
            bundle=bundle,
            snapshot=store.snapshot("student-test-a"),
            store=store,
            condition_id="P2_FULL",
            request_fingerprint="request-a",
        )
        with self.assertRaises(ExecutionContextError):
            verify_execution_context(context, store=store, condition_id="P2_RAG_ONLY", request_fingerprint="request-a")
        with self.assertRaises(ExecutionContextError):
            verify_execution_context(context, store=store, condition_id="P2_FULL", request_fingerprint="request-b")
        store.apply_state_event("memory-test-a", "COMPLETE", "2026-08-27T10:00:00+00:00")
        with self.assertRaisesRegex(ExecutionContextError, "STALE_STORE_SNAPSHOT"):
            verify_execution_context(context, store=store, condition_id="P2_FULL", request_fingerprint="request-a")

    def test_014_empty_query_and_invalid_target_types_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "EMPTY_RETRIEVAL_QUERY"):
            validated_query_plan(student_scope_id="student-test-a", original_query="")
        with self.assertRaisesRegex(ValueError, "INVALID_TARGET_MEMORY_TYPES"):
            validated_query_plan(student_scope_id="student-test-a", original_query="x", target_memory_types=("UNKNOWN",))

    def test_015_structured_write_boundary_rejects_inference_and_mismatch(self) -> None:
        inferred = StructuredWriteCandidateV1(
            "FREE_FORM_LLM_INFERENCE", "MODEL_INFERENCE_ONLY", "PREFERENCE", False, False, False, True
        )
        mismatch = StructuredWriteCandidateV1(
            "STRUCTURED_EXPLICIT_USER_ASSERTION", "EXPLICIT_STUDENT_GOAL", "PLAN", True, True, False, False
        )
        self.assertFalse(evaluate_structured_write_candidate(inferred).write_authorised)
        self.assertEqual(evaluate_structured_write_candidate(mismatch).failure_reason, "EVENT_MEMORY_TYPE_MISMATCH")

    def test_016_write_update_fixture_results(self) -> None:
        values = self.result.controlled.write_results
        self.assertEqual(values["fixture_count"], 4)
        self.assertEqual(values["write_precision"], 1.0)
        self.assertEqual(values["write_recall"], 1.0)
        self.assertEqual(values["unsafe_write_count"], 0)
        self.assertEqual(values["supersession_accuracy"], 1.0)

    def test_017_four_persistent_policies_and_primary_preassigned(self) -> None:
        values = self.result.controlled.persistent_policy_results
        self.assertEqual(set(values["policy_results"]), set(PERSISTENT_POLICY_IDS))
        self.assertEqual(values["primary_policy_id"], PRIMARY_PERSISTENT_POLICY)
        self.assertFalse(values["primary_selected_from_fixtures"])
        self.assertEqual(
            values["policy_results"][PRIMARY_PERSISTENT_POLICY]["safety_counts"]
            ["completed_not_requested_admission_count"],
            0,
        )

    def test_018_primary_state_eligibility_embedding_and_limits(self) -> None:
        store, _bundle = self._store()
        plan = validated_query_plan(student_scope_id="student-test-a", original_query="Continue my saved goal")
        result = run_persistent_retrieval(policy_id=PRIMARY_PERSISTENT_POLICY, plan=plan, store=store)
        self.assertTrue(result.eligibility_before_embedding)
        self.assertLessEqual(len(result.retrieved_memory_ids), 5)
        self.assertLessEqual(len(result.admitted_memory_ids), 3)
        self.assertEqual(result.execution_context_count, len(result.retrieved_memory_ids))
        self.assertEqual(result.generation_guard_call_count, len(result.admitted_memory_ids))

    def test_019_persistent_retrieval_is_deterministic(self) -> None:
        store, _bundle = self._store()
        plan = validated_query_plan(student_scope_id="student-test-a", original_query="Continue my saved goal")
        first = run_persistent_retrieval(policy_id=PRIMARY_PERSISTENT_POLICY, plan=plan, store=store)
        second = run_persistent_retrieval(policy_id=PRIMARY_PERSISTENT_POLICY, plan=plan, store=store)
        self.assertEqual(first, second)

    def test_020_rag_candidate_and_sufficiency_gates(self) -> None:
        rag = self.result.controlled.rag_results
        self.assertEqual(rag["rag_fixture_count"], 14)
        self.assertEqual(rag["candidate_decision_accuracy"], 1.0)
        self.assertEqual(rag["sufficiency_status_accuracy"], 1.0)
        self.assertEqual(rag["unsupported_evidence_admission_count"], 0)
        self.assertEqual(rag["ambiguous_evidence_admission_count"], 0)
        self.assertEqual(rag["no_result_evidence_admission_count"], 0)

    def test_021_rag_source_and_clarification_guards(self) -> None:
        blocked = run_candidate_gate_fixture(
            "fixture-test-001",
            {"p1_course_retrieval": True, "p1_clarification": True, "source_authorised": True},
        )
        restricted = run_candidate_gate_fixture(
            "fixture-test-002",
            {"p1_course_retrieval": True, "p1_clarification": False, "source_authorised": False},
        )
        self.assertFalse(blocked.retrieval_attempted)
        self.assertFalse(restricted.retrieval_attempted)

    def test_022_session_m0_m1_m2_and_missing_context_rule(self) -> None:
        from evaluation.capability_routing_rq2c0_v1.memory_use_gate_contract import MemoryCandidateSignals
        value = SessionStateInput(
            case_id="opaque-a",
            p1_clarification=False,
            signals=MemoryCandidateSignals(missing_context=True),
        )
        for policy in ("M0_P1_ONLY", "M1_RESOLVED_STATE_DEPENDENCY", "M2_EXPLICIT_MEMORY_NEED_WITH_STATE"):
            result = run_session_state_gate(value, policy)
            self.assertFalse(result.state_admitted)
            self.assertEqual(result.persistent_store_access_count, 0)

    def test_023_session_clarification_blocks_execution(self) -> None:
        from evaluation.capability_routing_rq2c0_v1.memory_use_gate_contract import MemoryCandidateSignals
        value = SessionStateInput(
            case_id="opaque-b",
            p1_clarification=True,
            signals=MemoryCandidateSignals(p1_episodic_memory=True, active_goal_present=True),
        )
        result = run_session_state_gate(value, "M0_P1_ONLY")
        self.assertTrue(result.execution_blocked_by_clarification)
        self.assertFalse(result.state_admitted)

    def test_024_nested_family_calibration_and_oof_coverage(self) -> None:
        oof = self.result.session_oof
        self.assertEqual(oof["family_count"], 18)
        self.assertEqual(oof["case_count"], 35)
        self.assertTrue(oof["each_case_oof_exactly_once"])
        self.assertEqual(oof["outer_family_leakage_count"], 0)
        self.assertTrue(all(not fold["outer_family_used_for_selection"] for fold in oof["folds"]))

    def test_025_final_session_policy_synthetic_only(self) -> None:
        policy = self.result.final_session_policy
        self.assertIn(policy["selected_policy_id"], {"M0_P1_ONLY", "M1_RESOLVED_STATE_DEPENDENCY", "M2_EXPLICIT_MEMORY_NEED_WITH_STATE"})
        self.assertTrue(policy["immutable"])
        self.assertFalse(policy["authentic_used_for_selection"])
        self.assertFalse(policy["context_missing_used_for_selection"])

    def test_026_five_condition_isolation_and_p1_immutability(self) -> None:
        conditions = self.result.controlled.controlled_condition_results["conditions"]
        self.assertEqual(set(conditions), {"P1_BASE", "P2_RAG_ONLY", "P2_SESSION_STATE_ONLY", "P2_PERSISTENT_MEMORY_ONLY", "P2_FULL"})
        self.assertEqual(conditions["P1_BASE"], {"rag": False, "session_state": False, "persistent": False})
        self.assertFalse(self.result.controlled.controlled_condition_results["p1_capability_plan_rewritten"])
        for dataset in (self.result.synthetic_results, self.result.authentic_results):
            for condition in ("P2_RAG_ONLY", "P2_FULL"):
                values = dataset["conditions"][condition]
                self.assertEqual(
                    values["rag_retrieval_attempt_count"],
                    values["rag_local_execution_count"],
                )
                self.assertEqual(values["rag_provider_calls"], 0)
                self.assertFalse(values["rag_network_access"])

    def test_027_synthetic35_and_no_persistent_target(self) -> None:
        result = self.result.synthetic_results
        self.assertEqual(result["record_count"], 35)
        self.assertTrue(result["nested_oof_reported_separately"])
        self.assertTrue(all(value["persistent_retrieval_attempt_count"] == 0 for value in result["conditions"].values()))

    def test_028_authentic22_postfreeze_descriptive_only(self) -> None:
        result = self.result.authentic_results
        self.assertEqual(result["record_count"], 22)
        self.assertEqual(result["evidence_role"], "DESCRIPTIVE_IN_SAMPLE_ONLY")
        self.assertEqual(result["policy_selection_use"], "NOT_USED_FOR_POLICY_SELECTION")
        self.assertTrue(result["mechanism_code_frozen_before_execution"])

    def test_029_context_missing3_separate_no_memory_construction(self) -> None:
        result = self.result.context_missing_results
        self.assertEqual(result["record_count"], 3)
        self.assertFalse(result["included_in_authentic_aggregate"])
        self.assertFalse(result["memory_auto_constructed"])
        self.assertFalse(result["missing_context_triggered_persistent_retrieval"])

    def test_030_hard_safety_all_zero(self) -> None:
        safety = self.result.controlled.hard_safety
        self.assertEqual(safety["status"], "PASS")
        self.assertEqual(safety["hard_failure_count"], 0)
        self.assertTrue(all(value == 0 for value in safety["hard_safety_counters"].values()))

    def test_031_offline_runtime_and_no_training(self) -> None:
        runtime = self.result.runtime_preflight
        self.assertEqual(runtime["provider_calls"], 0)
        self.assertFalse(runtime["network_access"])
        self.assertFalse(runtime["model_training"])
        self.assertEqual(runtime["encoder"]["device"], "cpu")
        self.assertTrue(runtime["encoder"]["local_files_only"])
        self.assertTrue(runtime["encoder"]["normalise_embeddings"])

    def test_032_local_artifacts_ignored_untracked(self) -> None:
        self.assertEqual(validate_local_artifacts_ignored()["status"], "PASS")

    def test_033_tracked_safe_outputs_and_governed_text_scan(self) -> None:
        self.assertEqual(validate_safe_outputs()["status"], "PASS")
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_034_python_ast_and_output_checksums(self) -> None:
        self.assertEqual(validate_python_ast()["status"], "PASS")
        self.assertEqual(validate_output_checksums()["status"], "PASS")

    def test_035_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["status"], "PASS")

    def test_036_double_finalisation_byte_identical(self) -> None:
        before = {relative: sha256_file(ROOT / relative) for relative in parse_output_checksums()}
        manifest_before = sha256_file(Path(__file__).parent / CHECKSUM_NAME)
        finalise_rq2c1(self.result)
        after = {relative: sha256_file(ROOT / relative) for relative in parse_output_checksums()}
        self.assertEqual(before, after)
        self.assertEqual(manifest_before, sha256_file(Path(__file__).parent / CHECKSUM_NAME))

    def test_037_review_package_completeness_contract(self) -> None:
        referenced = set(parse_output_checksums())
        members = set(expected_review_members())
        self.assertTrue(referenced <= members)
        self.assertIn("REVIEW/REVIEW_CHECKSUMS.sha256", members)

    def test_038_negative_results_do_not_block_or_tune(self) -> None:
        self.assertTrue(self.result.error_analysis["negative_results_permitted"])
        self.assertFalse(self.result.error_analysis["policy_changed_in_response_to_errors"])

    def test_039_no_production_integration_or_behavior_change(self) -> None:
        report = json.loads((Path(__file__).parent / "rq2c1_validation_report_v1.json").read_text())
        self.assertFalse(report["production_integration"])
        self.assertEqual(report["track_a_access_count"], 0)
        self.assertEqual(report["track_b_access_count"], 0)


if __name__ == "__main__":
    unittest.main()
