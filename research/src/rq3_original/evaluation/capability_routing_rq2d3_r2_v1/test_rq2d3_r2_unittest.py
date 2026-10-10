"""Contract tests for the RQ2-D3-R2 source-blinded D4 harness freeze."""

from __future__ import annotations

from fractions import Fraction
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from . import HERE, ROOT, START_HEAD, sha256_file
from .fixed_rq2d4_paths import fixed_d4_path_contract_document_v1, resolve_fixed_rq2d4_paths_v1
from .fixed_statistical_execution import fixed_statistical_execution_contract_document_v1, run_fixed_primary_and_secondary_statistics_v1
from .frozen_metric_binding import load_frozen_track_b_metric_binding_v1, load_synthetic_metric_binding_v1
from .grouping_manifest import validate_persisted_grouping_v1
from .model_identity_contract import build_model_identity_contract_v1
from .p2_secondary_scope import p2_secondary_scope_document_v1
from .prediction_contract import PREDICTION_FIELDS, prediction_contract_document_v1, prediction_trace_hash_v1, validate_prediction_rows_v1
from .rq2d4_global_one_shot_contract import D4ExecutionAuthorityError, execute_real_rq2d4_one_shot_v1, global_one_shot_contract_document_v1
from .rq2d4_state_machine import GLOBAL_STATE_ORDER, GlobalOneShotConsumedError, reserve_global_lock_v1, transition_global_lock_v1
from .source_blinded_grouping_builder import build_source_blinded_grouping_v1, opaque_group_id_v1, project_json_object_fields_v1
from .starting_state import validate_starting_state_v1
from .synthetic_track_b_final_fixture import build_synthetic_track_b_final_fixture_v1
from .track_b_feature_label_process_firewall import FEATURE_FIELDS, extract_feature_view_v1, feature_label_firewall_contract_document_v1
from .validate_rq2d3_r2 import CHECKSUM_PATH, DOC_NAMES, OUTPUT_NAMES, PYTHON_NAMES, checksum_targets


class RQ2D3R2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.start = validate_starting_state_v1()
        cls.grouping = validate_persisted_grouping_v1()
        cls.model = build_model_identity_contract_v1()
        cls.metric = json.loads((HERE / "track_b_frozen_metric_binding_contract_v1.json").read_text())
        cls.statistics = json.loads((HERE / "track_b_fixed_statistical_execution_contract_v1.json").read_text())
        cls.firewall = json.loads((HERE / "track_b_feature_label_process_firewall_contract_v1.json").read_text())
        cls.parity = json.loads((HERE / "rq2d3_r2_development_parity_v1.json").read_text())
        cls.synthetic = json.loads((HERE / "rq2d3_r2_synthetic_validation_v1.json").read_text())
        cls.validation = json.loads((HERE / "rq2d3_r2_validation_report_v1.json").read_text())

    def test_01_starting_head(self): self.assertEqual(self.start["starting_head"], START_HEAD)
    def test_02_starting_parent(self): self.assertEqual(self.start["starting_parent"], "60730fd6b4dde52ddc0ea3d377bc4fed2eefee56")
    def test_03_empty_d3_branch(self): self.assertEqual(self.start["original_empty_d3_branch_head"], self.start["starting_parent"])
    def test_04_r1_zip(self): self.assertEqual(self.start["r1_output_checksums"], "20/20 PASS")
    def test_05_d2b_checksums(self): self.assertEqual(self.start["d2b_output_checksums"], "28/28 PASS")
    def test_06_gold_bundle(self): self.assertEqual(self.start["gold_bundle_sha256"], "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5")
    def test_07_no_full_text_open(self): self.assertEqual(self.start["full_text_gold_content_open_count"], 0)
    def test_08_grouping_open_counts(self): self.assertEqual((self.grouping["mapping_open_read"], self.grouping["case_bank_open_read"]), ("1/1", "1/1"))
    def test_09_grouping_projection(self): self.assertEqual(self.grouping["forbidden_field_value_access_count"], 0)
    def test_10_grouping_join(self): self.assertEqual((self.grouping["record_count"], self.grouping["group_count"], self.grouping["records_per_group"]), (48,24,2))
    def test_11_opaque_group_deterministic(self): self.assertEqual(opaque_group_id_v1(["B","A"]), opaque_group_id_v1(["A","B"]))
    def test_12_opaque_group_prefix(self): self.assertRegex(opaque_group_id_v1(["A","B"]), r"^TBCG-[0-9A-F]{16}$")
    def test_13_projector_skips_forbidden(self):
        projected, skipped = project_json_object_fields_v1('{"raw_scenario_id":"R","review_case_id":"C","query":"X"}', ("raw_scenario_id","review_case_id"))
        self.assertEqual(projected, {"raw_scenario_id":"R","review_case_id":"C"}); self.assertEqual(skipped,1)
    def test_14_synthetic_group_build(self):
        mapping=[{"raw_scenario_id":f"R{i:02d}","review_case_id":f"C{i:02d}"} for i in range(48)]
        cases=[{"raw_case_id":f"R{i:02d}","contrast_set_id":f"G{i//2:02d}"} for i in range(48)]
        ledger, report=build_source_blinded_grouping_v1(mapping,cases); self.assertEqual(report["unique_contrast_group_id_count"],24); self.assertTrue(ledger.endswith(b"\n"))
    def test_15_ledger_hash(self): self.assertEqual(self.grouping["ledger_sha256"], "41bb7a1617b8428bb7c02dadb186ba8650b745cc870fc277bee1b86037fbe35a")
    def test_16_c0_identity(self): self.assertEqual(self.model["c0"]["identity"], "C0_COSINE")
    def test_17_c0_candidates(self): self.assertEqual((self.model["c0"]["candidate_record_count"],self.model["c0"]["label_count"]),(62,16))
    def test_18_c0_aggregation(self): self.assertEqual(self.model["c0"]["aggregation"], "MAX")
    def test_19_b0_identity(self): self.assertTrue(self.model["b0"]["identity"].startswith("B0_ORIGINAL_QUERY"))
    def test_20_b0_no_context(self): self.assertEqual((self.model["b0"]["history_read_count"],self.model["b0"]["context_resolver_call_count"]),(0,0))
    def test_21_b1_identity(self): self.assertTrue(self.model["b1"]["identity"].startswith("B1_CURRENT_PRODUCTION"))
    def test_22_b1_reproduction(self): self.assertEqual(self.model["b1"]["frozen_development_ledger_sha256"], "801efb2c4ab4b32445e6ec2e51a6bac9173d566cb8136070b557e35d62ca5e80")
    def test_23_p1_identity(self): self.assertEqual(self.model["p1"]["identity"], "P1_D05_SIGNAL_UNION")
    def test_24_p1_unchanged(self): self.assertFalse(any(self.model["p1"][key] for key in ("intent_map_changed","need_signals_changed","threshold_changed","weights_changed","guards_changed")))
    def test_25_real_metric_factory_signature(self): self.assertEqual(tuple(inspect.signature(load_frozen_track_b_metric_binding_v1).parameters), ())
    def test_26_real_metric_hash(self): self.assertEqual(self.metric["implementation_sha256"], "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138")
    def test_27_metric_keys(self): self.assertEqual(len(self.metric["metric_keys"]),4)
    def test_28_synthetic_factory_separate(self): self.assertTrue(load_synthetic_metric_binding_v1().synthetic_test_only)
    def test_29_real_wrapper_signature(self): self.assertEqual(tuple(inspect.signature(run_fixed_primary_and_secondary_statistics_v1).parameters), ("ordered_groups","predictions_by_method","gold_by_id"))
    def test_30_no_stat_overrides(self): self.assertEqual(self.statistics["caller_overridable_parameters"], [])
    def test_31_fixed_draws(self): self.assertEqual((self.statistics["sign_flip_draws"],self.statistics["sign_flip_seed"]),(100000,20260829))
    def test_32_fixed_bootstrap(self): self.assertEqual((self.statistics["bootstrap_resamples"],self.statistics["bootstrap_seed"]),(50000,20260828))
    def test_33_fixed_primary(self): self.assertEqual(self.statistics["primary"], "P1_VS_B1")
    def test_34_fixed_secondary(self): self.assertEqual(self.statistics["secondary"], ["B1_VS_B0","P1_VS_B0"])
    def test_35_combined_source_role(self): self.assertEqual(self.firewall["combined_source_role"], "SEALED_COMBINED_CASE_SOURCE")
    def test_36_combined_not_label_free(self): self.assertFalse(self.firewall["combined_source_is_label_free"])
    def test_37_feature_schema(self): self.assertEqual(tuple(self.firewall["feature_fields"]), FEATURE_FIELDS)
    def test_38_fresh_predictor(self): self.assertTrue(self.firewall["predictor_process"]["fresh_process"])
    def test_39_metric_ordering(self): self.assertTrue(self.firewall["metric_process"]["starts_after_prediction_firewall"])
    def test_40_prediction_contract(self): self.assertEqual(prediction_contract_document_v1()["total_predictions"],144)
    def test_41_prediction_schema(self): self.assertEqual(tuple(prediction_contract_document_v1()["fields"]),PREDICTION_FIELDS)
    def test_42_prediction_trace(self):
        row={"method_id":"B0","context_resolution_required_prediction":False,"predicted_capabilities":["safe_direct_response"]}; self.assertRegex(prediction_trace_hash_v1(row),r"^[0-9a-f]{64}$")
    def test_43_prediction_fixture_validation(self):
        fixture=build_synthetic_track_b_final_fixture_v1(); rows=[]
        for method in ("B0","B1","P1"):
            for item in fixture["combined"]:
                row={"review_case_id":item["review_case_id"],"method_id":method,"context_resolution_required_prediction":False,"predicted_capabilities":["safe_direct_response"],"prediction_trace_hash":""}; row["prediction_trace_hash"]=prediction_trace_hash_v1(row); rows.append(row)
        self.assertEqual(validate_prediction_rows_v1(rows)["prediction_count"],144)
    def test_44_feature_extraction(self):
        features,report=extract_feature_view_v1(build_synthetic_track_b_final_fixture_v1()["combined"]); self.assertEqual(len(features),48); self.assertEqual(report["forbidden_keys_exported"],0)
    def test_45_p2_not_predictor(self): self.assertFalse(p2_secondary_scope_document_v1()["p2_is_capability_predictor"])
    def test_46_p2_noop(self): self.assertEqual(p2_secondary_scope_document_v1()["persistent_component"],"STRICT_NO_OP")
    def test_47_dev84_ranking(self): self.assertEqual(self.parity["c0_dev84"]["ranking_identity_match_count"],84)
    def test_48_dev84_scores(self): self.assertLessEqual(self.parity["c0_dev84"]["maximum_absolute_score_delta"],1e-12)
    def test_49_dev84_metrics(self): self.assertLessEqual(self.parity["c0_dev84"]["maximum_absolute_metric_delta"],1e-12)
    def test_50_rq2_parity(self): self.assertEqual(self.parity["rq2_development"]["verified_local_ledger_count"],18)
    def test_51_synthetic_fixture_shape(self): self.assertEqual((self.synthetic["fixture"]["combined_record_count"],self.synthetic["fixture"]["group_count"]),(48,24))
    def test_52_process_isolation(self): self.assertEqual(self.synthetic["process_isolation"]["fresh_process_count"],3)
    def test_53_predictor_no_labels(self): self.assertEqual(self.synthetic["process_isolation"]["predictor"]["label_gold_open_count"],0)
    def test_54_metric_after_predictions(self): self.assertTrue(self.synthetic["process_isolation"]["metric"]["predictions_persisted_before_label_open"])
    def test_55_synthetic_stats(self): self.assertEqual((self.synthetic["fixed_statistics"]["sign_flip_draws"],self.synthetic["fixed_statistics"]["bootstrap_resamples"]),(100000,50000))
    def test_56_holm(self): self.assertEqual(self.synthetic["fixed_statistics"]["secondary_holm_count"],2)
    def test_57_global_complete(self): self.assertEqual(self.synthetic["global_one_shot"]["complete_state"],"COMPLETED")
    def test_58_global_failure(self): self.assertEqual(self.synthetic["global_one_shot"]["failed_state"],"FAILED")
    def test_59_global_retry_blocked(self): self.assertTrue(self.synthetic["global_one_shot"]["completion_retry_blocked"] and self.synthetic["global_one_shot"]["failure_retry_blocked"])
    def test_60_concurrent_exclusion(self): self.assertEqual(self.synthetic["global_one_shot"]["concurrent_outcomes"],["EXCLUDED","RESERVED"])
    def test_61_state_order(self): self.assertEqual((GLOBAL_STATE_ORDER[0],GLOBAL_STATE_ORDER[-1]),("GLOBAL_RESERVED","COMPLETED"))
    def test_62_lock_mode_and_retry(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/"lock.json"; reserve_global_lock_v1(path,execution_id="x",synthetic=True); self.assertEqual(path.stat().st_mode&0o777,0o600); self.assertRaises(GlobalOneShotConsumedError,reserve_global_lock_v1,path,execution_id="y",synthetic=True)
    def test_63_failure_persistence(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/"lock.json"; reserve_global_lock_v1(path,execution_id="x",synthetic=True); self.assertEqual(transition_global_lock_v1(path,"FAILED")["state"],"FAILED")
    def test_64_fixed_paths(self): self.assertIn("capability_routing_rq2d4_v1/local_one_shot",fixed_d4_path_contract_document_v1()["output_root_relative"])
    def test_65_real_entry_signature(self): self.assertEqual(tuple(inspect.signature(execute_real_rq2d4_one_shot_v1).parameters),("approved_head",))
    def test_66_real_entry_not_executed(self):
        with mock.patch.dict(os.environ,{"RQ2D4_TRACK_B_FINAL_EVALUATION_AUTHORISED":""}): self.assertRaises(D4ExecutionAuthorityError,execute_real_rq2d4_one_shot_v1,approved_head="x")
    def test_67_output_checksums(self):
        lines=[line for line in CHECKSUM_PATH.read_text().splitlines() if line]; self.assertEqual(len(lines),len(checksum_targets()));
        for line in lines:
            expected,relative=line.split("  ",1); self.assertEqual(sha256_file(ROOT/relative),expected)
    def test_68_ast(self):
        import ast
        for name in PYTHON_NAMES: ast.parse((HERE/name).read_text(),filename=name)
    def test_69_docs(self): self.assertTrue(all((ROOT/"docs/thesis_mainline/rq2"/name).is_file() for name in DOC_NAMES))
    def test_70_safe_outputs(self): self.assertTrue(all((HERE/name).is_file() for name in OUTPUT_NAMES))
    def test_71_protected_sources(self): self.assertEqual(self.validation["protected_source_change_count"],0)
    def test_72_no_real_evaluation(self): self.assertEqual((self.validation["real_track_b_prediction_count"],self.validation["real_track_b_metric_count"]),(0,0))
    def test_73_no_hidden_or_raw(self): self.assertEqual((self.validation["hidden_legacy_access_count"],self.validation["raw_track_b_access_count"],self.validation["blind_key_access_count"]),(0,0,0))
    def test_74_no_d4(self): self.assertEqual(self.validation["d4_execution_count"],0)
    def test_75_no_network(self): self.assertFalse(self.validation["network_access"])
    def test_76_real_pipeline_executable(self): self.assertTrue(global_one_shot_contract_document_v1()["real_pipeline_executable"])


if __name__ == "__main__":
    unittest.main()
