"""Contract, reachability, safety, and governance tests for RQ2-C0."""

from __future__ import annotations

import json
import subprocess
import unittest

from utils.retrieval_v2.sufficiency import evaluate_evidence_sufficiency

from . import HERE, ROOT, SAFE_OUTPUT_FILENAMES, STARTING_HEAD, sha256_file
from .clarification_audit import build_clarification_audit
from .condition_contract import CONDITION_IDS, condition_matrix, metric_contract, validate_condition_isolation
from .episodic_memory_semantics import MechanismObservations, classify_mechanism, semantics_contract
from .memory_use_gate_contract import (
    MEMORY_POLICY_IDS,
    MemoryCandidateSignals,
    StateItemStatus,
    memory_candidate,
    selective_memory_contract,
    state_item_admissible,
)
from .rag_gate_contract import (
    assert_existing_sufficiency_interface,
    evidence_admission_allowed,
    normalise_sufficiency_status,
    retrieval_candidate_gate,
)
from .reachability_audit import build_episodic_reachability_audit
from .rq2b_identity import (
    EXPECTED_LOCAL_LEDGER_HASHES,
    EXPECTED_RESULT_HASHES,
    EXPECTED_REVIEW_ZIP_SHA256,
    RQ2B_REVIEW_ZIP,
    build_rq2b_identity,
    verify_local_ledgers,
    verify_result_hashes,
    verify_rq2b_output_checksums,
)
from .tool_gate_schema import (
    MemoryUseGateDecisionV1,
    P2ExecutionPlanV1,
    RAGGateDecisionV1,
    schema_contract,
)
from .validate_rq2c0 import (
    CHECKSUM_RELATIVE,
    assert_partition_access_allowed,
    build_all,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    validate_local_artifact_ignore,
    validate_output_checksums,
    validate_python_ast,
    validate_safe_outputs,
)


class RQ2C0ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build = build_all()
        cls.identity = json.loads(
            (HERE / "rq2b_result_identity_v1.json").read_text(encoding="utf-8")
        )
        cls.episodic = json.loads(
            (HERE / "episodic_memory_reachability_audit_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.clarification = json.loads(
            (HERE / "clarification_gate_reachability_audit_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.evaluability = json.loads(
            (HERE / "p2_mechanism_evaluability_v1.json").read_text(encoding="utf-8")
        )

    def test_01_starting_head_is_ancestor(self) -> None:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_02_rq2b_review_zip_hash(self) -> None:
        self.assertEqual(sha256_file(RQ2B_REVIEW_ZIP), EXPECTED_REVIEW_ZIP_SHA256)

    def test_03_rq2b_output_checksums_36(self) -> None:
        self.assertEqual(verify_rq2b_output_checksums(), 36)

    def test_04_final_p1_policy_hash(self) -> None:
        observed = verify_result_hashes()
        self.assertEqual(observed, dict(EXPECTED_RESULT_HASHES))

    def test_05_local_ledger_hashes(self) -> None:
        self.assertEqual(verify_local_ledgers(), dict(EXPECTED_LOCAL_LEDGER_HASHES))

    def test_06_p1_policy_immutable(self) -> None:
        self.assertEqual(self.identity["p1_final_policy"], "P1_D05_SIGNAL_UNION")
        self.assertTrue(self.identity["p1_policy_immutable"])
        self.assertFalse(self.identity["rq2b_results_modified"])

    def test_07_b0_context_metric_interpretation(self) -> None:
        value = json.loads(
            (HERE / "b0_context_metric_interpretation_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(value["b0_context_resolver_implemented"])
        self.assertEqual(value["b0_context_resolution_prediction"], "ALWAYS_FALSE")
        self.assertTrue(value["b0_numeric_context_accuracy_retained"])
        self.assertEqual(
            value["mechanism_interpretation"],
            "CONTEXT_RESOLUTION_NOT_AVAILABLE_BY_DESIGN",
        )

    def test_08_episodic_gold_support_eight(self) -> None:
        self.assertEqual(self.episodic["gold_episodic_positive_count"], 8)

    def test_09_b0_episodic_confusion(self) -> None:
        self.assertEqual(
            {key: self.episodic["confusion"]["B0"][key] for key in ("tp", "fp", "fn")},
            {"tp": 0, "fp": 0, "fn": 8},
        )

    def test_10_b1_episodic_confusion(self) -> None:
        self.assertEqual(
            {key: self.episodic["confusion"]["B1"][key] for key in ("tp", "fp", "fn")},
            {"tp": 3, "fp": 1, "fn": 5},
        )

    def test_11_p1_episodic_confusion(self) -> None:
        self.assertEqual(
            {key: self.episodic["confusion"]["P1"][key] for key in ("tp", "fp", "fn")},
            {"tp": 0, "fp": 0, "fn": 8},
        )

    def test_12_all_eight_false_negatives_have_reasons(self) -> None:
        self.assertEqual(self.episodic["p1_false_negative_count"], 8)
        self.assertTrue(self.episodic["all_false_negatives_assigned_reason"])
        self.assertEqual(
            self.episodic["p1_false_negative_reason_counts"][
                "SEMANTIC_MAP_HAS_NO_EPISODIC_SUPPORT"
            ],
            8,
        )

    def test_13_clarification_synthetic_counts(self) -> None:
        self.assertEqual(
            (
                self.clarification["synthetic_gold_positive_count"],
                self.clarification["synthetic_predicted_positive_count"],
                self.clarification["synthetic_tp"],
                self.clarification["synthetic_fp"],
                self.clarification["synthetic_fn"],
            ),
            (3, 11, 3, 8, 0),
        )

    def test_14_registry_clarification_counts(self) -> None:
        self.assertEqual(
            (
                self.clarification["registry_record_count"],
                self.clarification["registry_predicted_positive_count"],
                self.clarification["registry_execution_capability_false_positive_count"],
            ),
            (3, 1, 2),
        )

    def test_15_working_context_and_retrieval_are_distinct(self) -> None:
        contract = semantics_contract()
        self.assertFalse(
            contract["terms"]["WORKING_CONTEXT_AVAILABLE"][
                "persistent_retrieval_claim_allowed"
            ]
        )
        self.assertNotEqual(
            contract["terms"]["EPISODIC_STATE_USE_REQUIRED"]["definition"],
            contract["terms"]["EPISODIC_RETRIEVAL_REQUIRED"]["definition"],
        )

    def test_16_episodic_retrieval_not_inferred_automatically(self) -> None:
        observation = MechanismObservations(
            visible_history_present=True,
            working_state_object_present=True,
            context_missing=False,
        )
        self.assertEqual(classify_mechanism(observation), "SATISFIED_BY_WORKING_CONTEXT")

    def test_17_no_gold_fields_in_mechanism_signals(self) -> None:
        forbidden = {"gold", "source_role", "scenario_family", "case_id"}
        fields = set(MemoryCandidateSignals.__dataclass_fields__)
        self.assertFalse(fields & forbidden)

    def test_18_fixed_m0_m1_m2_family(self) -> None:
        self.assertEqual(
            MEMORY_POLICY_IDS,
            (
                "M0_P1_ONLY",
                "M1_RESOLVED_STATE_DEPENDENCY",
                "M2_EXPLICIT_MEMORY_NEED_WITH_STATE",
            ),
        )

    def test_19_missing_context_alone_does_not_trigger_memory(self) -> None:
        signals = MemoryCandidateSignals(missing_context=True)
        self.assertFalse(any(memory_candidate(policy, signals) for policy in MEMORY_POLICY_IDS))

    def test_20_state_object_required(self) -> None:
        signals = MemoryCandidateSignals(resolver_is_follow_up=True, plan_memory_need=True)
        self.assertFalse(memory_candidate("M1_RESOLVED_STATE_DEPENDENCY", signals))
        self.assertFalse(memory_candidate("M2_EXPLICIT_MEMORY_NEED_WITH_STATE", signals))

    def test_21_stale_and_superseded_state_rejected(self) -> None:
        base = dict(
            belongs_to_current_scope=True,
            active=True,
            completed=False,
            cancelled=False,
            superseded=False,
            stale=False,
            directly_supports_current_need=True,
        )
        self.assertTrue(state_item_admissible(StateItemStatus(**base)))
        self.assertFalse(
            state_item_admissible(StateItemStatus(**{**base, "stale": True}))
        )
        self.assertFalse(
            state_item_admissible(StateItemStatus(**{**base, "superseded": True}))
        )

    def test_22_rag_candidate_contract(self) -> None:
        self.assertTrue(
            retrieval_candidate_gate(
                p1_course_retrieval=True,
                p1_clarification=False,
                course_source_authorised=True,
            )
        )
        self.assertFalse(
            retrieval_candidate_gate(
                p1_course_retrieval=True,
                p1_clarification=True,
                course_source_authorised=True,
            )
        )

    def test_23_clarification_blocks_tool_execution(self) -> None:
        rag = RAGGateDecisionV1(
            candidate=False,
            retrieval_attempted=False,
            source_authorised=True,
            retrieval_status="NOT_ATTEMPTED",
            evidence_sufficiency="NO_RESULT",
            supporting_chunk_count=0,
            evidence_admitted_to_generation=False,
            clarification_required=True,
        )
        memory = MemoryUseGateDecisionV1(
            candidate=False,
            working_context_available=False,
            state_use_required=False,
            additional_retrieval_required=False,
            memory_query_attempted=False,
            candidate_item_count=0,
            relevant_item_count=0,
            stale_item_count=0,
            superseded_item_count=0,
            state_admitted_to_generation=False,
            clarification_required=True,
        )
        plan = P2ExecutionPlanV1(
            p1_plan_immutable=True,
            rag_gate=rag,
            memory_gate=memory,
            dashboard_evidence_allowed=False,
            planning_allowed=False,
            safe_direct_response=False,
            clarification=True,
        )
        self.assertTrue(plan.clarification)

    def test_24_existing_evidence_sufficiency_interface(self) -> None:
        self.assertEqual(assert_existing_sufficiency_interface()["status"], "PASS")
        self.assertTrue(callable(evaluate_evidence_sufficiency))

    def test_25_unsupported_evidence_never_admitted(self) -> None:
        for status in ("AMBIGUOUS", "UNSUPPORTED", "NO_RESULT", "NOT_APPLICABLE"):
            self.assertFalse(evidence_admission_allowed(status, 3))
        self.assertTrue(evidence_admission_allowed("SUPPORTED", 1))

    def test_26_four_p2_conditions(self) -> None:
        self.assertEqual(tuple(condition_matrix()["conditions"]), CONDITION_IDS)

    def test_27_condition_isolation(self) -> None:
        self.assertTrue(validate_condition_isolation(condition_matrix()))

    def test_28_mechanism_metric_definitions(self) -> None:
        metrics = metric_contract()
        self.assertIn("supported_evidence_admission_rate", metrics["rag_gate"])
        self.assertIn("stale_state_admission_rate", metrics["memory_gate"])
        self.assertFalse(metrics["working_context_counted_as_persistent_retrieval_success"])

    def test_29_synthetic_data_role(self) -> None:
        self.assertEqual(self.evaluability["synthetic_support"]["course_retrieval_positive_count"], 7)
        self.assertEqual(self.evaluability["synthetic_support"]["episodic_memory_positive_count"], 8)

    def test_30_authentic_selection_prohibited(self) -> None:
        self.assertTrue(self.identity["authentic_descriptive_only"])
        self.assertFalse(self.evaluability["authentic_used_for_mechanism_selection"])

    def test_31_track_a_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            assert_partition_access_allowed("TRACK_A")

    def test_32_track_b_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            assert_partition_access_allowed("TRACK_B")

    def test_33_no_p2_implementation(self) -> None:
        self.assertFalse(schema_contract()["p2_implemented"])
        self.assertFalse(selective_memory_contract()["p2_implemented"])

    def test_34_no_production_change(self) -> None:
        self.assertEqual(
            protected_source_comparison()["protected_existing_file_change_count"], 0
        )

    def test_35_no_provider_or_network(self) -> None:
        preflight = json.loads(
            (HERE / "rq2c0_preflight_report_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(preflight["provider_calls"], 0)
        self.assertFalse(preflight["network_access"])

    def test_36_no_model_training(self) -> None:
        preflight = json.loads(
            (HERE / "rq2c0_preflight_report_v1.json").read_text(encoding="utf-8")
        )
        self.assertFalse(preflight["model_training"])

    def test_37_double_build_byte_identical(self) -> None:
        first = build_all()
        paths = [ROOT / relative for relative in parse_output_checksums()]
        paths.append(ROOT / CHECKSUM_RELATIVE)
        before = {path: path.read_bytes() for path in paths}
        second = build_all()
        after = {path: path.read_bytes() for path in paths}
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_38_output_checksums(self) -> None:
        self.assertEqual(validate_output_checksums()["status"], "PASS")
        self.assertEqual(len(parse_output_checksums()), 29)

    def test_39_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_40_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["status"], "PASS")

    def test_41_python_ast_and_count(self) -> None:
        self.assertEqual(validate_python_ast(), {"status": "PASS", "python_file_count": 12})

    def test_42_safe_output_count(self) -> None:
        self.assertEqual(validate_safe_outputs()["safe_output_count"], len(SAFE_OUTPUT_FILENAMES))

    def test_43_local_artifacts_ignored(self) -> None:
        self.assertEqual(validate_local_artifact_ignore()["tracked_local_artifact_count"], 0)

    def test_44_evaluability_blocker_is_frozen(self) -> None:
        self.assertEqual(
            self.evaluability["result"],
            "INSUFFICIENT_REQUIRES_SEPARATE_MECHANISM_FIXTURES",
        )
        self.assertEqual(
            self.evaluability["entry_decision"],
            "BLOCKED_RQ2_C0_MECHANISM_EVALUATION_UNDERSPECIFIED",
        )
        self.assertIn(
            "PERSISTENT_RETRIEVAL_TARGET", self.evaluability["missing_requirements"]
        )


if __name__ == "__main__":
    unittest.main()
