"""Contract tests for the frozen RQ2-B offline experiment."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from evaluation.capability_routing_v1.context_envelope import build_context_envelope
from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
    _working_memory_dependency,
)

from . import CAPABILITIES, HERE, POLICY_IDS, RESULT_BRANCH, ROOT, STARTING_HEAD
from .capability_metrics import evaluate_capability_predictions
from . import RQ2BError, canonical_json_bytes
from .development_uncertainty import development_uncertainty_report
from .family_grouped_calibration import _selection_key, select_policy
from .finalise_rq2b import finalise_rq2b
from .gold_preflight import (
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_MEMBERS,
    load_and_validate_gold,
    sha256_file,
)
from .p1_policy_family import policy_contract_document, validate_capability_plan
from .p1_capability_router import (
    _final_capabilities,
    _source_forbidden_capabilities,
)
from .validate_rq2b import (
    expected_review_members,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    static_feature_access_audit,
    validate_output_checksums,
)


def _json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class RQ2BContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gold = load_and_validate_gold(ROOT)
        cls.gold_preflight = _json("rq2b_gold_preflight_v1.json")
        cls.runtime = _json("rq2b_runtime_preflight_v1.json")
        cls.b0 = _json("rq2b_b0_contract_v1.json")
        cls.b1 = _json("rq2b_b1_reproduction_v1.json")
        cls.policy = _json("rq2b_p1_policy_family_v1.json")
        cls.family = _json("rq2b_family_split_manifest_v1.json")
        cls.nested = _json("rq2b_nested_oof_results_v1.json")
        cls.final_policy = _json("rq2b_final_p1_policy_v1.json")
        cls.synthetic = _json("rq2b_synthetic_comparison_v1.json")
        cls.uncertainty = _json("rq2b_development_uncertainty_v1.json")
        cls.authentic = _json("rq2b_authentic_descriptive_results_v1.json")
        cls.registry = _json("rq2b_context_missing_diagnostic_v1.json")
        cls.validation = _json("rq2b_validation_report_v1.json")
        cls.local_nested = json.loads(
            (HERE / "local_artifacts/policy_selection_traces/nested_lofo_selection_v1.json").read_text()
        )
        cls.local_metric_rows = json.loads(
            (HERE / "local_artifacts/error_ledgers/metric_join_rows_v1.json").read_text()
        )

    def test_01_starting_head_is_ancestor(self) -> None:
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=ROOT, text=True
            ).strip(),
            RESULT_BRANCH,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
                cwd=ROOT,
                check=False,
            ).returncode,
            0,
        )

    def test_02_r2b_review_zip_hash(self) -> None:
        path = ROOT.parent / "RQ2_A_R2B_CAPABILITY_GOLD_FREEZE_REVIEW_2026-08-26.zip"
        self.assertEqual(
            sha256_file(path),
            "57ee009fe4d8cdb2b41a80d03b8454ef7f44adda57950d8a009643e54e168600",
        )

    def test_03_repository_checksums_27_of_27(self) -> None:
        self.assertEqual(self.gold_preflight["output_checksum_count"], 27)

    def test_04_canonicalisation_manifest_hash(self) -> None:
        path = ROOT / "evaluation/capability_routing_v1_r2b/adjudication_canonicalisation_manifest_v1.json"
        self.assertEqual(
            sha256_file(path),
            "704631a25c023ebae063aac0c4c03362025899ceb3c472afee531f97dff3c8c5",
        )

    def test_05_gold_bundle_hash(self) -> None:
        self.assertEqual(self.gold_preflight["gold_bundle_sha256"], EXPECTED_GOLD_BUNDLE_SHA256)

    def test_06_label_only_gold_hashes(self) -> None:
        for path, (digest, _count) in EXPECTED_MEMBERS.items():
            if "/local_gold/" not in path.as_posix():
                self.assertEqual(sha256_file(ROOT / path), digest)

    def test_07_local_full_text_gold_hashes(self) -> None:
        for path, (digest, _count) in EXPECTED_MEMBERS.items():
            if "/local_gold/" in path.as_posix():
                self.assertEqual(sha256_file(ROOT / path), digest)

    def test_08_gold_composition(self) -> None:
        self.assertEqual(
            (len(self.gold.authentic_gold), len(self.gold.synthetic_gold), len(self.gold.authentic_context_missing_registry), len(self.gold.combined_gold)),
            (22, 35, 3, 57),
        )

    def test_09_c0_candidate_62_identity(self) -> None:
        self.assertEqual(self.runtime["identity"]["approved_index_record_count"], 62)

    def test_10_c0_embedding_identity(self) -> None:
        self.assertEqual(
            self.runtime["identity"]["embedding_artifact_sha256"],
            "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8",
        )

    def test_11_c0_fixed_16_label_vector(self) -> None:
        self.assertEqual(self.runtime["fixed_intent_axis_count"], 16)
        self.assertTrue(self.runtime["all_vectors_have_fixed_axis"])

    def test_12_c0_top1_production_parity(self) -> None:
        self.assertEqual(
            self.runtime["production_semantic_candidate_parity_count"],
            self.runtime["record_count"],
        )

    def test_13_b0_does_not_call_memory_resolver(self) -> None:
        self.assertEqual(self.b0["prepare_mode_cm_context_call_count"], 0)

    def test_14_b0_does_not_read_history(self) -> None:
        self.assertEqual(self.b0["conversation_history_read_count"], 0)
        self.assertEqual(self.b0["structured_memory_read_count"], 0)
        source = (HERE / "b0_original_query_adapter.py").read_text()
        self.assertIn("named_course_location_subject", source)

    def test_15_b1_ledger_exact_reproduction(self) -> None:
        self.assertTrue(self.b1["reproduced_ledger_byte_identical"])
        self.assertEqual(
            self.b1["reproduced_ledger_sha256"],
            "801efb2c4ab4b32445e6ec2e51a6bac9173d566cb8136070b557e35d62ca5e80",
        )

    def test_16_b1_aggregate_exact_reproduction(self) -> None:
        aggregate = self.b1["reproduction"]
        self.assertEqual(aggregate["capability_positive_count"], {
            "dashboard_evidence": 12, "course_retrieval": 3,
            "episodic_memory": 4, "planning": 5,
            "safe_direct_response": 0, "clarification": 16,
        })

    def test_17_context_envelope_max_four_turns(self) -> None:
        history = [
            {"role": "user", "content": "this prior item", "turn_order": index}
            for index in range(8)
        ]
        envelope = build_context_envelope(
            case_id="opaque", original_query="explain this", current_page="Overview",
            conversation_history=history,
        )
        self.assertLessEqual(len(envelope.recent_relevant_turns), 4)

    def test_18_no_gold_fields_in_p1_features(self) -> None:
        self.assertEqual(static_feature_access_audit()["gold_label_import_count"], 0)
        source = (HERE / "p1_capability_router.py").read_text()
        self.assertLess(
            source.index("_normalise_c_full_query_detailed"),
            source.index("prepare_mode_cm_context("),
        )

    def test_19_source_role_not_used_as_feature(self) -> None:
        self.assertEqual(static_feature_access_audit()["source_role_argument_count"], 0)

    def test_20_scenario_family_only_for_split(self) -> None:
        self.assertFalse(self.family["scenario_family_used_as_prediction_feature"])

    def test_21_existing_need_signals_called(self) -> None:
        self.assertTrue(self.policy["existing_need_signals_called"])

    def test_22_episodic_memory_parity_helper(self) -> None:
        context = {
            "selected_route": "memory_resolved_follow_up",
            "memory_resolution": {
                "resolved": True, "referenced_items": [{"number": "1", "text": "x"}],
                "memory_context": {}, "resolution_type": "numbered_reference",
            },
        }
        self.assertTrue(_working_memory_dependency(context))

    def test_23_semantic_uncertain_alone_does_not_clarify_p1(self) -> None:
        source = (HERE / "p1_capability_router.py").read_text()
        self.assertNotIn('semantic_uncertain" in', source)

    def test_24_clarification_exclusivity(self) -> None:
        self.assertTrue(validate_capability_plan(["clarification", "planning"])["clarification_exclusivity_violation"])

    def test_25_safe_direct_exclusivity(self) -> None:
        self.assertTrue(validate_capability_plan(["safe_direct_response", "planning"])["safe_direct_exclusivity_violation"])
        forbidden = _source_forbidden_capabilities(
            {"excluded_source_types": ["memory", "course_material"]}
        )
        self.assertEqual(forbidden, ("course_retrieval", "episodic_memory"))
        self.assertEqual(
            _final_capabilities(
                ("course_retrieval", "planning"),
                clarification_required=False,
                deterministic_forbidden=forbidden,
            ),
            ("planning",),
        )

    def test_26_no_empty_plan(self) -> None:
        self.assertTrue(validate_capability_plan([])["empty_capability_plan"])

    def test_27_fixed_five_policy_grid(self) -> None:
        self.assertEqual(tuple(self.policy["policy_ids"]), POLICY_IDS)

    def test_28_no_per_capability_threshold(self) -> None:
        self.assertFalse(self.policy["per_capability_threshold_search"])

    def test_29_eighteen_family_groups(self) -> None:
        self.assertEqual(self.family["family_count"], 18)

    def test_30_no_family_leakage(self) -> None:
        all_ids = {
            example.router_input.case_id for example in self.gold.synthetic_gold
        }
        for fold in self.local_nested["folds"]:
            outer = set(fold["outer_case_id_commitment"])
            inner = set(fold["inner_case_id_commitment"])
            self.assertFalse(outer & inner)
            self.assertEqual(outer | inner, all_ids)

    def test_31_each_synthetic_case_oof_once(self) -> None:
        ids = [row["review_case_id"] for row in self.local_nested["oof_predictions"]]
        self.assertEqual(len(ids), 35)
        self.assertEqual(len(set(ids)), 35)

    def test_32_inner_selection_excludes_outer_family(self) -> None:
        source_rows = {}
        for policy in POLICY_IDS:
            path = HERE / f"local_artifacts/p1_predictions/synthetic_{policy}.jsonl"
            source_rows[policy] = {
                row["review_case_id"]: row
                for row in (json.loads(line) for line in path.read_text().splitlines())
            }
        for row in self.local_nested["oof_predictions"]:
            policy = row["selected_inner_policy_id"]
            source = source_rows[policy][row["review_case_id"]]
            self.assertEqual(row["predicted_capabilities"], source["predicted_capabilities"])
            self.assertEqual(
                row["context_resolution_required_prediction"],
                source["context_resolution_required_prediction"],
            )

    def test_33_selection_tie_break(self) -> None:
        base = {
            "macro_f1_all_six": 0.5, "required_capability_recall": 0.5,
            "exact_set_accuracy": 0.5, "unnecessary_capability_rate": 0.5,
            "mean_set_jaccard": 0.5, "mean_predicted_capability_count": 2.0,
        }
        preferences = (
            ("macro_f1_all_six", 0.6),
            ("required_capability_recall", 0.6),
            ("exact_set_accuracy", 0.6),
            ("unnecessary_capability_rate", 0.4),
            ("mean_set_jaccard", 0.6),
            ("mean_predicted_capability_count", 1.0),
        )
        for index, (field, better) in enumerate(preferences):
            candidate = dict(base)
            candidate[field] = better
            for prior_field, _ in preferences[:index]:
                candidate[prior_field] = base[prior_field]
            self.assertLess(_selection_key("P1_K1_SIGNAL_UNION", candidate), _selection_key("P1_K2_SIGNAL_UNION", base))
        self.assertLess(
            _selection_key(sorted(POLICY_IDS)[0], base),
            _selection_key(sorted(POLICY_IDS)[1], base),
        )

    def test_34_no_unsafe_candidate_selected(self) -> None:
        labels = {"x": {"gold_capabilities": ["planning"], "forbidden_capabilities": [], "context_resolution_required": False}}
        predictions = {
            policy: [{"review_case_id": "x", "predicted_capabilities": ["clarification", "planning"], "context_resolution_required_prediction": False}]
            for policy in POLICY_IDS
        }
        predictions["P1_K1_SIGNAL_UNION"] = [{"review_case_id": "x", "predicted_capabilities": ["planning"], "context_resolution_required_prediction": False}]
        self.assertEqual(
            select_policy(predictions_by_policy=predictions, labels_by_id=labels, eligible_case_ids={"x"})["selected_policy_id"],
            "P1_K1_SIGNAL_UNION",
        )
        predictions["P1_K1_SIGNAL_UNION"] = predictions["P1_K2_SIGNAL_UNION"]
        with self.assertRaisesRegex(RQ2BError, "BLOCKED_RQ2_B_NO_SAFE_P1_POLICY"):
            select_policy(predictions_by_policy=predictions, labels_by_id=labels, eligible_case_ids={"x"})

    def test_35_final_policy_selected_on_synthetic_only(self) -> None:
        self.assertEqual(self.final_policy["selection_data_role"], "SYNTHETIC_COVERAGE_STRESS_GOLD")

    def test_36_authentic_cannot_influence_selection(self) -> None:
        self.assertFalse(self.final_policy["authentic_used_for_selection"])

    def test_37_registry_cannot_influence_selection(self) -> None:
        self.assertFalse(self.final_policy["registry_used_for_selection"])

    def test_38_synthetic_primary_metrics_present(self) -> None:
        self.assertIn("macro_f1_all_six", self.synthetic["models"]["P1"])

    def test_39_tool_trigger_metrics_present(self) -> None:
        self.assertEqual(set(self.synthetic["models"]["P1"]["tool_trigger_metrics"]), set(CAPABILITIES[:4]))

    def test_40_context_metrics_present(self) -> None:
        self.assertIn("context_resolution_positive_recall", self.synthetic["models"]["P1"])

    def test_41_forbidden_violation_metrics_present(self) -> None:
        self.assertIn("forbidden_capability_violation_rate", self.synthetic["models"]["P1"])

    def test_42_multi_capability_metrics_present(self) -> None:
        self.assertIn("multi_capability_exact_set_accuracy", self.synthetic["models"]["P1"])

    def test_43_family_bootstrap_reproducibility_contract(self) -> None:
        families = {
            example.router_input.case_id: str(example.split.scenario_family)
            for example in self.gold.synthetic_gold
        }
        rows = self.local_metric_rows["synthetic"]
        observed = development_uncertainty_report(
            p1_rows=rows["P1"], b0_rows=rows["B0"], b1_rows=rows["B1"],
            family_by_id=families,
        )
        self.assertEqual(canonical_json_bytes(observed), canonical_json_bytes(self.uncertainty))

    def test_44_authentic_after_policy_freeze(self) -> None:
        self.assertTrue(self.final_policy["frozen_before_authentic_evaluation"])
        self.assertEqual(self.authentic["frozen_p1_policy_id"], self.final_policy["selected_policy_id"])
        self.assertTrue(self.authentic["policy_bytes_unchanged_after_authentic"])
        self.assertEqual(
            self.authentic["pre_authentic_policy_file_sha256"],
            self.authentic["post_authentic_policy_file_sha256"],
        )

    def test_45_context_missing_separate_diagnostic(self) -> None:
        self.assertFalse(self.registry["included_in_authentic_aggregate"])
        self.assertEqual(self.registry["data_role"], "CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC")

    def test_46_local_ledgers_ignored(self) -> None:
        result = subprocess.check_output(
            ["git", "check-ignore", "evaluation/capability_routing_rq2b_v1/local_artifacts/probe"],
            cwd=ROOT, text=True,
        ).strip()
        self.assertTrue(result)

    def test_47_tracked_outputs_contain_no_query_history(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_48_no_track_a_access(self) -> None:
        self.assertFalse(self.validation["track_a_access"])

    def test_49_no_track_b_access(self) -> None:
        self.assertFalse(self.validation["track_b_access"])

    def test_50_no_p2_implementation(self) -> None:
        self.assertFalse(self.validation["p2_implemented"])

    def test_51_no_production_modification(self) -> None:
        self.assertEqual(protected_source_comparison()["protected_existing_file_change_count"], 0)

    def test_52_no_provider_or_network(self) -> None:
        self.assertEqual(self.validation["provider_calls"], 0)
        self.assertFalse(self.validation["network_access"])

    def test_53_no_model_training(self) -> None:
        self.assertFalse(self.validation["model_training"])

    def test_54_double_finalisation_byte_identical(self) -> None:
        first = finalise_rq2b()
        second = finalise_rq2b()
        self.assertEqual(first["commitments"], second["commitments"])

    def test_55_output_checksums_pass(self) -> None:
        self.assertEqual(validate_output_checksums()["status"], "PASS")

    def test_56_review_package_completeness_contract(self) -> None:
        checksums = parse_output_checksums()
        expected = expected_review_members()
        self.assertEqual(len(expected), len(checksums) + 5)
        self.assertTrue(set(checksums) <= expected)

    def test_57_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["status"], "PASS")

    def test_58_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_source_comparison()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
