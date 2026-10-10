"""Contract, fixture, privacy, and governance tests for RQ2-C0-R1."""

from __future__ import annotations

from collections import Counter
import json
import subprocess
import unittest

from . import (
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_RQ2C0_REVIEW_ZIP_SHA256,
    FIXTURE_BANK_PATH,
    HERE,
    ROOT,
    RQ2C0_REVIEW_ZIP,
    SAFE_OUTPUT_FILENAMES,
    STARTING_HEAD,
    sha256_file,
)
from .fixture_bank_builder import load_fixture_bank
from .fixture_coverage_validator import validate_fixture_coverage
from .fixture_schema import FIXTURE_CATEGORY_COUNTS, MECHANISM_GROUP_COUNTS
from .mechanism_metric_contract import metric_contract
from .memory_admission_policy import decide_admission
from .memory_retrieval_policy_family import POLICIES, POLICY_IDS, policy_family_contract
from .memory_write_policy import decide_write, deletion_transition, supersession_transition
from .p2_condition_contract import CONDITION_IDS, condition_contract, validate_condition_isolation
from .persistent_memory_schema import (
    ALLOWED_MEMORY_TYPES,
    FORBIDDEN_AUTOMATIC_MEMORY_TYPES,
)
from .validate_rq2c0_r1 import (
    CHECKSUM_RELATIVE,
    PRODUCTION_MEMORY_RELATIVE,
    SUFFICIENCY_RELATIVE,
    assert_partition_access_allowed,
    build_all,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    validate_local_fixture_ignore,
    validate_no_implementation,
    validate_output_checksums,
    validate_review_package_contract,
    validate_safe_outputs,
    verify_rq2c0_output_checksums,
)


class RQ2C0R1ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.build = build_all()
        cls.fixtures = load_fixture_bank()
        cls.coverage = validate_fixture_coverage(cls.fixtures)
        cls.scope = json.loads(
            (HERE / "rq2c0_r1_scope_authority_v1.json").read_text(encoding="utf-8")
        )
        cls.schema = json.loads(
            (HERE / "persistent_learner_memory_schema_v1.json").read_text(encoding="utf-8")
        )

    def test_01_starting_head_is_ancestor(self) -> None:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_02_rq2c0_review_zip_hash(self) -> None:
        self.assertEqual(sha256_file(RQ2C0_REVIEW_ZIP), EXPECTED_RQ2C0_REVIEW_ZIP_SHA256)

    def test_03_rq2c0_output_checksums_29(self) -> None:
        self.assertEqual(verify_rq2c0_output_checksums(), 29)

    def test_04_p1_policy_immutable(self) -> None:
        authority = self.scope["starting_authority"]
        self.assertEqual(authority["p1_policy"], EXPECTED_P1_POLICY)
        self.assertTrue(authority["p1_policy_immutable"])
        self.assertFalse(self.scope["p1_changed"])

    def test_05_gold_immutable(self) -> None:
        self.assertEqual(
            self.scope["starting_authority"]["gold_bundle_sha256"],
            EXPECTED_GOLD_BUNDLE_SHA256,
        )
        self.assertFalse(self.scope["gold_changed"])

    def test_06_memory_schema_fields(self) -> None:
        expected = {
            "MemoryEpisodeV1": {
                "memory_id", "student_scope_id", "episode_id", "source_turn_id",
                "memory_type", "raw_content_hash", "created_at", "valid_from",
                "valid_until", "status", "explicitness", "confidence", "entities",
                "supersedes_memory_id", "provenance", "embedding_hash",
            },
            "MemoryStateProjectionV1": {
                "student_scope_id", "active_goal", "active_plan", "active_constraints",
                "active_preferences", "latest_corrections", "completed_steps",
                "referenced_items", "source_memory_ids", "projection_version", "updated_at",
            },
            "MemoryWriteDecisionV1": {
                "candidate", "write_authorised", "memory_type", "explicit_student_source",
                "verified_system_event", "sensitive_inference", "duplicate_of",
                "supersedes", "failure_reason", "decision_trace",
            },
            "MemoryRetrievalPlanV1": {
                "query_hash", "context_status", "capability_evidence", "unresolved_referents",
                "target_memory_types", "entity_constraints", "temporal_constraints",
                "candidate_policy_id", "top_k", "decision_trace",
            },
            "MemoryCandidateV1": {
                "memory_id", "dense_rank", "lexical_entity_match", "type_compatibility",
                "temporal_validity", "status_validity", "scope_validity",
                "source_confidence", "retrieval_evidence",
            },
            "MemoryAdmissionDecisionV1": {
                "memory_id", "admitted", "relevance_supported", "active", "stale",
                "superseded", "cancelled", "deleted", "cross_scope", "conflict_status",
                "failure_reason",
            },
        }
        observed = {
            name: set(fields) for name, fields in self.schema["schema_fields"].items()
        }
        self.assertEqual(observed, expected)

    def test_07_allowed_memory_types(self) -> None:
        self.assertEqual(len(ALLOWED_MEMORY_TYPES), 8)
        self.assertEqual(tuple(self.schema["allowed_memory_types"]), ALLOWED_MEMORY_TYPES)

    def test_08_forbidden_inference_types(self) -> None:
        self.assertEqual(len(FORBIDDEN_AUTOMATIC_MEMORY_TYPES), 5)
        self.assertEqual(
            tuple(self.schema["forbidden_automatic_memory_types"]),
            FORBIDDEN_AUTOMATIC_MEMORY_TYPES,
        )

    def test_09_explicit_write_authorised(self) -> None:
        value = decide_write(
            event_type="EXPLICIT_STUDENT_PREFERENCE",
            memory_type="PREFERENCE",
            explicit_student_source=True,
            verified_system_event=False,
        )
        self.assertTrue(value.write_authorised)
        self.assertEqual(value.failure_reason, None)

    def test_10_inferred_profile_rejected(self) -> None:
        value = decide_write(
            event_type="SENSITIVE_PROFILE_INFERENCE",
            memory_type="INFERRED_MENTAL_HEALTH",
            explicit_student_source=False,
            verified_system_event=False,
            sensitive_inference=True,
        )
        self.assertFalse(value.write_authorised)
        self.assertIn("SENSITIVE_INFERENCE", value.decision_trace)

    def test_11_supersession_append_only(self) -> None:
        value = supersession_transition("memory_old", "memory_new")
        self.assertEqual(value["operation"], "APPEND_NEW_EPISODE")
        self.assertEqual(value["old_status"], "SUPERSEDED")
        self.assertFalse(value["old_episode_deleted"])
        self.assertTrue(value["history_preserved"])

    def test_12_deletion_tombstone(self) -> None:
        value = deletion_transition("memory_delete", "a" * 64)
        self.assertEqual(value["new_status"], "DELETED")
        self.assertTrue(value["tombstone_created"])
        self.assertFalse(value["retrieval_eligible"])

    def test_13_four_retrieval_policies(self) -> None:
        self.assertEqual(POLICY_IDS, (
            "PMR_KW_LEGACY", "PMR_DENSE_ONLY",
            "PMR_HYBRID_TYPE_TEMPORAL", "PMR_HYBRID_STATE_AWARE",
        ))

    def test_14_keyword_only_baseline(self) -> None:
        policy = next(item for item in POLICIES if item.policy_id == "PMR_KW_LEGACY")
        self.assertTrue(policy.keyword_signal)
        self.assertFalse(policy.dense_signal)
        self.assertTrue(policy_family_contract()["keyword_only_is_baseline"])

    def test_15_dense_only_policy(self) -> None:
        policy = next(item for item in POLICIES if item.policy_id == "PMR_DENSE_ONLY")
        self.assertTrue(policy.dense_signal)
        self.assertFalse(policy.keyword_signal)
        self.assertFalse(policy.active_status_filter)

    def test_16_hybrid_type_temporal_policy(self) -> None:
        policy = next(
            item for item in POLICIES if item.policy_id == "PMR_HYBRID_TYPE_TEMPORAL"
        )
        self.assertTrue(policy.dense_signal and policy.lexical_entity_signal)
        self.assertTrue(policy.type_compatibility and policy.temporal_validity)
        self.assertFalse(policy.active_status_filter)

    def test_17_state_aware_rejection(self) -> None:
        for kwargs in (
            {"stale": True}, {"superseded": True}, {"cancelled": True},
            {"deleted": True}, {"cross_scope": True},
        ):
            value = decide_admission(
                memory_id="memory_controlled",
                relevance_supported=True,
                active=True,
                **kwargs,
            )
            self.assertFalse(value.admitted)

    def test_18_no_gold_feature(self) -> None:
        contract = policy_family_contract()
        self.assertFalse(contract["gold_label_as_feature"])
        self.assertNotIn("gold", " ".join(self.schema["schema_fields"]["MemoryRetrievalPlanV1"]).lower())

    def test_19_no_source_role_feature(self) -> None:
        contract = policy_family_contract()
        self.assertFalse(contract["source_role_as_feature"])
        self.assertNotIn("source_role", self.schema["schema_fields"]["MemoryRetrievalPlanV1"])

    def test_20_fixture_total_28(self) -> None:
        self.assertEqual(len(self.fixtures), 28)

    def test_21_rag_fixture_count_14(self) -> None:
        self.assertEqual(sum(item.mechanism_group.startswith("RAG_") for item in self.fixtures), 14)

    def test_22_persistent_memory_fixture_count_14(self) -> None:
        self.assertEqual(
            sum(item.mechanism_group.startswith("PERSISTENT_") for item in self.fixtures),
            14,
        )

    def test_23_exact_fixture_category_counts(self) -> None:
        groups = Counter(item.mechanism_group for item in self.fixtures)
        categories = Counter(item.fixture_category for item in self.fixtures)
        self.assertEqual(dict(groups), MECHANISM_GROUP_COUNTS)
        self.assertEqual(dict(categories), FIXTURE_CATEGORY_COUNTS)

    def test_24_persistent_retrieval_target_count(self) -> None:
        observed = self.coverage["persistent_memory_gates"][
            "ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED"
        ]["observed"]
        self.assertEqual(observed, 4)

    def test_25_multi_hop_case(self) -> None:
        self.assertEqual(
            self.coverage["persistent_memory_gates"]["MULTI_HOP_RETRIEVAL"]["observed"],
            1,
        )

    def test_26_stale_case(self) -> None:
        self.assertEqual(
            self.coverage["persistent_memory_gates"]["STALE_REJECTION"]["observed"], 1
        )

    def test_27_superseded_case(self) -> None:
        self.assertGreaterEqual(
            self.coverage["persistent_memory_gates"]["SUPERSEDED_REJECTION"]["observed"],
            1,
        )

    def test_28_cross_student_case(self) -> None:
        self.assertEqual(
            self.coverage["persistent_memory_gates"]["CROSS_STUDENT_REJECTION"]["observed"],
            1,
        )

    def test_29_deletion_case(self) -> None:
        self.assertEqual(
            self.coverage["persistent_memory_gates"]["DELETED_MEMORY_REJECTION"]["observed"],
            1,
        )

    def test_30_all_evaluability_gates_pass(self) -> None:
        self.assertTrue(self.coverage["all_gates_pass"])
        self.assertEqual(
            self.coverage["evaluability_status"],
            "SUFFICIENT_FOR_OFFLINE_P2_RAG_AND_PERSISTENT_MEMORY",
        )

    def test_31_five_p2_conditions(self) -> None:
        value = condition_contract()
        self.assertEqual(tuple(value["conditions"]), CONDITION_IDS)
        self.assertTrue(validate_condition_isolation(value))

    def test_32_metrics_contract(self) -> None:
        value = metric_contract()
        self.assertIn("write_precision", value["memory_write"])
        self.assertIn("recall_at_3", value["retrieval"])
        self.assertIn("deleted_memory_violation_rate", value["admission"])
        self.assertIn("latest_correction_accuracy", value["conflict_update"])
        self.assertFalse(value["fixture_result_is_student_outcome_evidence"])

    def test_33_local_fixture_bank_ignored(self) -> None:
        value = validate_local_fixture_ignore()
        self.assertEqual(value["tracked_local_fixture_count"], 0)
        self.assertEqual(value["local_fixture_record_count"], 28)

    def test_34_tracked_outputs_contain_no_fixture_text(self) -> None:
        value = validate_safe_outputs()
        self.assertEqual(value["raw_text_key_count"], 0)
        self.assertEqual(value["safe_output_count"], len(SAFE_OUTPUT_FILENAMES))

    def test_35_track_a_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            assert_partition_access_allowed("TRACK_A")

    def test_36_track_b_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            assert_partition_access_allowed("TRACK_B")

    def test_37_no_p2_or_persistent_memory_implementation(self) -> None:
        self.assertEqual(validate_no_implementation()["implementation_count"], 0)
        self.assertFalse(self.schema["store_implemented"])
        self.assertFalse(self.schema["embedding_retrieval_implemented"])
        self.assertFalse(self.schema["p2_router_implemented"])

    def test_38_no_production_modification(self) -> None:
        self.assertEqual(
            self.scope["production_memory_source_sha256"],
            sha256_file(ROOT / PRODUCTION_MEMORY_RELATIVE),
        )
        self.assertEqual(
            self.scope["retrieval_sufficiency_source_sha256"],
            sha256_file(ROOT / SUFFICIENCY_RELATIVE),
        )
        self.assertFalse(self.scope["production_routing_changed"])

    def test_39_no_provider_or_network(self) -> None:
        self.assertEqual(self.scope["provider_calls"], 0)
        self.assertFalse(self.scope["network_access"])

    def test_40_no_model_training(self) -> None:
        self.assertFalse(self.scope["model_training"])

    def test_41_double_build_byte_identical(self) -> None:
        first = build_all()
        paths = [ROOT / relative for relative in parse_output_checksums()]
        paths.extend((ROOT / CHECKSUM_RELATIVE, FIXTURE_BANK_PATH))
        before = {path: path.read_bytes() for path in paths}
        second = build_all()
        after = {path: path.read_bytes() for path in paths}
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_42_output_checksums(self) -> None:
        value = validate_output_checksums()
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(len(parse_output_checksums()), 30)

    def test_43_review_package_completeness_contract(self) -> None:
        value = validate_review_package_contract()
        self.assertEqual(value["referenced_output_member_count"], 30)
        self.assertEqual(value["local_fixture_member_count"], 0)

    def test_44_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_45_protected_sources_unchanged(self) -> None:
        value = protected_source_comparison()
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(value["protected_existing_file_change_count"], 0)


if __name__ == "__main__":
    unittest.main()
