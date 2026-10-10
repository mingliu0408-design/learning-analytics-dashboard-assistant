"""RQ2-D3-R1 exact statistical contract and isolation tests."""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import unittest

from . import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CAPABILITIES,
    COMPARISONS,
    HERE,
    METRIC_IMPLEMENTATION_SHA256,
    PRIMARY_COMPARISON,
    REGISTERED_BOOTSTRAP_METRICS,
    ROOT,
    SECONDARY_COMPARISONS,
    SIGN_FLIP_DRAWS,
    SIGN_FLIP_SEED,
    START_HEAD,
    TARGET_BRANCH,
)
from .cluster_bootstrap import (
    MetricCallbackBindingV1,
    run_whole_cluster_bootstrap_v1,
    type7_quantile_v1,
    validate_metric_binding_v1,
)
from .clustered_sign_flip import (
    cluster_mean_delta_v1,
    exhaustive_sign_flip_fixture_v1,
    ordered_cluster_deltas_v1,
    run_clustered_sign_flip_v1,
)
from .effective_statistical_contract import effective_statistical_contract_v1_1
from .exact_set_utility import (
    capability_yes_set_v1,
    case_outcome_v1,
    case_utility_difference_v1,
    exact_jaccard_details_v1,
    exact_jaccard_utility_v1,
    summarise_case_outcomes_v1,
)
from .holm_adjustment import holm_adjust_secondary_pvalues_v1
from .restricted_access_firewall import (
    RestrictedAccessError,
    assert_lexical_path_allowed_v1,
    restricted_access_audit_v1,
    synthetic_deny_checks_v1,
)
from .starting_state import git, validate_starting_state
from .statistical_contract_authority import (
    historical_contract_authority_v1,
    statistical_completion_authority_v1,
)
from .synthetic_statistical_fixture import (
    all_tie_fixture_v1,
    frozen_metric_binding_v1,
    synthetic_24x2_fixture_v1,
    synthetic_metric_binding_v1,
)
from .validate_rq2d3_r1 import (
    CHECKSUM_NAME,
    assert_change_scope,
    assert_double_finalisation,
    assert_python_ast,
    assert_restricted_access_static_firewall,
    assert_safe_outputs,
    expected_review_members,
    governed_text_leak_scan,
    validate_output_checksums,
)


def _json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class D3R1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.starting = validate_starting_state()
        cls.authority = statistical_completion_authority_v1()
        cls.historical = historical_contract_authority_v1()
        cls.contract = _json("rq2_final_statistical_contract_v1_1.json")
        cls.synthetic = _json("rq2d3_r1_synthetic_validation_v1.json")
        cls.fixture = synthetic_24x2_fixture_v1()

    def test_01_starting_branch_head_and_zero_or_one_commit(self) -> None:
        self.assertEqual(self.starting["approved_starting_head"], START_HEAD)
        self.assertEqual(self.starting["target_branch"], TARGET_BRANCH)
        self.assertIn(self.starting["relative_commits_from_d2b"], {0, 1})

    def test_02_original_d3_branch_remains_empty(self) -> None:
        value = git("rev-parse", "research/rq2-d3-track-b-final-evaluation-harness").stdout.decode().strip()
        self.assertEqual(value, START_HEAD)

    def test_03_blocker_zip_identity(self) -> None:
        self.assertEqual(self.starting["blocker_review_zip_sha256"], "8f541d3ce821a16cae3cde8f8a221787631355f5530faf18f87c52395e0b35c8")
        self.assertEqual((self.starting["blocker_review_zip_size_bytes"], self.starting["blocker_review_zip_member_count"]), (2030, 2))

    def test_04_d2b_zip_and_checksums(self) -> None:
        self.assertEqual(self.starting["d2b_review_zip_sha256"], "89b0590923555d788783b623f6ad91c9258f1223ff8cd79a52003569444905a6")
        self.assertEqual(self.starting["d2b_output_checksum_manifest"], "28/28 PASS")

    def test_05_gold_bundle_metadata(self) -> None:
        self.assertEqual(self.starting["d2b_gold_bundle_sha256"], "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5")

    def test_06_original_statistical_contract_identity(self) -> None:
        self.assertEqual(self.starting["original_statistical_contract_sha256"], "60543ca8cf55eb200c567e787c0bcf0fbec8d7341d5e972d8ec091cda9880bf3")
        self.assertEqual(self.starting["original_statistical_contract_size_bytes"], 1435)

    def test_07_timing_post_gold_pre_prediction(self) -> None:
        self.assertEqual(self.authority["timing"], "POST_CAPABILITY_GOLD_FREEZE_PRE_PREDICTION")
        self.assertFalse(self.authority["track_b_prediction_exists"])
        self.assertFalse(self.authority["track_b_metric_exists"])

    def test_08_effective_contract_identity(self) -> None:
        self.assertEqual(self.contract, effective_statistical_contract_v1_1())
        self.assertEqual(self.contract["schema_version"], "rq2-final-statistical-contract-v1.1")
        self.assertEqual(self.contract["contract_id"], "RQ2_TRACK_B_FINAL_STATISTICAL_CONTRACT_V1_1")

    def test_09_historical_targets_comparisons_seeds_unchanged(self) -> None:
        self.assertTrue(self.historical["comparisons_unchanged"])
        self.assertTrue(self.historical["metric_targets_unchanged"])
        self.assertTrue(self.historical["seeds_unchanged"])

    def test_10_exact_six_capability_universe(self) -> None:
        self.assertEqual(tuple(self.contract["capability_universe"]["ordered_capabilities"]), CAPABILITIES)

    def test_11_extra_fields_are_ignored(self) -> None:
        record = {"planning": "YES", "context_resolution_required": "YES", "source_role": "ignored"}
        self.assertEqual(capability_yes_set_v1(record), {"planning"})

    def test_12_perfect_set_match(self) -> None:
        self.assertEqual(exact_jaccard_utility_v1({"planning"}, {"planning"}), Fraction(1, 1))

    def test_13_disjoint_nonempty_sets(self) -> None:
        self.assertEqual(exact_jaccard_utility_v1({"planning"}, {"clarification"}), Fraction(0, 1))

    def test_14_partial_overlap_exact_fraction(self) -> None:
        details = exact_jaccard_details_v1({"planning", "episodic_memory"}, {"planning", "course_retrieval"})
        self.assertEqual((details.intersection_count, details.union_count, details.value), (1, 3, Fraction(1, 3)))

    def test_15_both_empty_is_one(self) -> None:
        self.assertEqual(exact_jaccard_utility_v1(set(), set()), 1)

    def test_16_one_empty_is_zero(self) -> None:
        self.assertEqual(exact_jaccard_utility_v1(set(), {"planning"}), 0)

    def test_17_exact_cross_multiplication_tie(self) -> None:
        self.assertEqual(case_outcome_v1(Fraction(1, 3) - Fraction(2, 6)), "TIE")

    def test_18_comparison_direction_left_minus_right(self) -> None:
        delta = case_utility_difference_v1({"planning": "YES"}, {"clarification": "YES"}, {"planning": "YES"})
        self.assertGreater(delta, 0)
        self.assertEqual(case_outcome_v1(delta), "WIN")

    def test_19_win_tie_loss(self) -> None:
        self.assertEqual([case_outcome_v1(value) for value in (Fraction(1), Fraction(0), Fraction(-1))], ["WIN", "TIE", "LOSS"])

    def test_20_wins_ties_losses_total_and_effect(self) -> None:
        result = summarise_case_outcomes_v1([Fraction(1), Fraction(1), Fraction(0), Fraction(-1)])
        self.assertEqual((result["wins"], result["ties"], result["losses"], result["total"]), (2, 1, 1, 4))
        self.assertEqual((result["matched_rank_biserial"]["numerator"], result["matched_rank_biserial"]["denominator"]), (1, 3))

    def test_21_all_ties_effect_is_null(self) -> None:
        result = summarise_case_outcomes_v1([Fraction(0), Fraction(0)])
        self.assertIsNone(result["matched_rank_biserial"]["value"])
        self.assertEqual(result["matched_rank_biserial"]["status"], "UNDEFINED_ALL_TIES")

    def test_22_cluster_exactly_two_cases(self) -> None:
        with self.assertRaises(ValueError):
            cluster_mean_delta_v1((Fraction(1),))  # type: ignore[arg-type]

    def test_23_cluster_arithmetic_mean_exact(self) -> None:
        self.assertEqual(cluster_mean_delta_v1((Fraction(1, 3), Fraction(1, 6))), Fraction(1, 4))

    def test_24_group_and_case_order_canonical(self) -> None:
        rows = []
        for group_id, cases in reversed(self.fixture["groups"]):
            rows.append((group_id, tuple((case_id, Fraction(0)) for case_id in reversed(cases))))
        result = ordered_cluster_deltas_v1(rows)
        self.assertEqual([group_id for group_id, _ in result], sorted(group_id for group_id, _ in result))

    def test_25_zero_cluster_retained(self) -> None:
        ordered = tuple((f"SYN-GROUP-{i+1:04d}", Fraction(0)) for i in range(24))
        result = run_clustered_sign_flip_v1(ordered, draws=20)
        self.assertEqual((result["cluster_count"], result["zero_cluster_count"], result["denominator_cluster_count"]), (24, 24, 24))

    def test_26_sign_flip_is_two_sided_absolute(self) -> None:
        self.assertEqual(self.contract["clustered_sign_flip"]["direction"], "TWO_SIDED")
        self.assertIn("ABS", self.contract["clustered_sign_flip"]["observed_statistic"])

    def test_27_zero_groups_consume_no_rng_bit(self) -> None:
        ordered = tuple((f"SYN-GROUP-{i+1:04d}", Fraction(0)) for i in range(24))
        result = run_clustered_sign_flip_v1(ordered, draws=17)
        self.assertEqual(result["rng_bit_draw_count"], 0)

    def test_28_one_nonzero_group_consumes_one_bit_per_draw(self) -> None:
        ordered = [(f"SYN-GROUP-{i+1:04d}", Fraction(0)) for i in range(24)]
        ordered[0] = (ordered[0][0], Fraction(1, 2))
        result = run_clustered_sign_flip_v1(tuple(ordered), draws=17)
        self.assertEqual(result["rng_bit_draw_count"], 17)

    def test_29_extreme_rule_and_plus_one(self) -> None:
        ordered = tuple((f"SYN-GROUP-{i+1:04d}", Fraction(0)) for i in range(24))
        result = run_clustered_sign_flip_v1(ordered, draws=11)
        self.assertEqual(result["extreme_rule"], "T_DRAW_GTE_T_OBSERVED")
        self.assertEqual((result["p_numerator"], result["p_denominator"], result["p_value"]), (1, 1, 1.0))

    def test_30_minimum_p_cannot_be_zero(self) -> None:
        minimum = Fraction(1, SIGN_FLIP_DRAWS + 1)
        self.assertGreater(minimum, 0)
        self.assertEqual(self.contract["clustered_sign_flip"]["minimum_p_value"], "1/100001")

    def test_31_all_zero_full_draw_p_is_one(self) -> None:
        self.assertEqual(self.synthetic["sign_flip"]["all_zero_p_value"], 1.0)
        self.assertEqual(self.synthetic["sign_flip"]["all_zero_rng_bits"], 0)

    def test_32_sign_flip_seed_and_draw_count_fixed(self) -> None:
        self.assertEqual((self.synthetic["sign_flip"]["draw_count"], self.synthetic["sign_flip"]["seed"]), (SIGN_FLIP_DRAWS, SIGN_FLIP_SEED))

    def test_33_sign_flip_deterministic_double_run(self) -> None:
        self.assertTrue(self.synthetic["sign_flip"]["deterministic_double_run"])

    def test_34_small_exhaustive_fixture(self) -> None:
        result = self.synthetic["sign_flip"]["small_exhaustive_fixture"]
        self.assertEqual(result["pattern_count"], 4)
        self.assertGreaterEqual(result["extreme_count"], 0)

    def test_35_wrong_sign_flip_group_order_rejected(self) -> None:
        ordered = tuple((f"SYN-GROUP-{i+1:04d}", Fraction(0)) for i in range(24))
        with self.assertRaises(ValueError):
            run_clustered_sign_flip_v1(tuple(reversed(ordered)), draws=2)

    def test_36_synthetic_fixture_shape(self) -> None:
        self.assertEqual((len(self.fixture["groups"]), len(self.fixture["gold"])), (24, 48))
        self.assertTrue(all(len(cases) == 2 for _, cases in self.fixture["groups"]))

    def test_37_bootstrap_whole_group_counts(self) -> None:
        result = self.synthetic["bootstrap"]
        self.assertEqual(result["full_group_selection_count"], BOOTSTRAP_RESAMPLES * 24)
        self.assertEqual(result["full_case_slot_count"], BOOTSTRAP_RESAMPLES * 48)

    def test_38_bootstrap_duplicate_groups_retained(self) -> None:
        self.assertTrue(self.synthetic["bootstrap"]["duplicate_group_draws_retained"])
        self.assertGreater(self.synthetic["bootstrap"]["repeated_group_draw_count"], 0)

    def test_39_no_case_level_sampling(self) -> None:
        self.assertFalse(self.synthetic["bootstrap"]["case_level_sampling_used"])

    def test_40_bootstrap_seed_and_resamples_fixed(self) -> None:
        self.assertEqual((self.synthetic["bootstrap"]["resamples"], self.synthetic["bootstrap"]["seed"]), (BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED))

    def test_41_bootstrap_deterministic_double_run(self) -> None:
        self.assertTrue(self.synthetic["bootstrap"]["deterministic_double_run"])

    def test_42_four_registered_metrics_only(self) -> None:
        self.assertEqual(set(self.synthetic["bootstrap"]["metrics"]), set(REGISTERED_BOOTSTRAP_METRICS))
        self.assertEqual(tuple(self.contract["whole_cluster_bootstrap"]["metrics"]), REGISTERED_BOOTSTRAP_METRICS)

    def test_43_metric_callback_identity_required(self) -> None:
        binding = frozen_metric_binding_v1()
        validate_metric_binding_v1(binding)
        self.assertEqual(binding.implementation_sha256, METRIC_IMPLEMENTATION_SHA256)
        bad = MetricCallbackBindingV1("BAD", "BAD", binding.callbacks)
        with self.assertRaises(ValueError):
            validate_metric_binding_v1(bad)

    def test_44_bootstrap_comparison_direction(self) -> None:
        self.assertEqual(self.synthetic["bootstrap"]["comparison_direction"], "LEFT_MINUS_RIGHT")

    def test_45_type7_known_example(self) -> None:
        self.assertAlmostEqual(type7_quantile_v1([0, 1, 2, 3], 0.25), 0.75)

    def test_46_type7_boundaries_and_singleton(self) -> None:
        self.assertEqual(type7_quantile_v1([0, 1, 2, 3], 0), 0)
        self.assertEqual(type7_quantile_v1([0, 1, 2, 3], 1), 3)
        self.assertEqual(type7_quantile_v1([7], 0.025), 7)

    def test_47_type7_tail_examples(self) -> None:
        self.assertAlmostEqual(type7_quantile_v1([0, 1, 2, 3], 0.025), 0.075)
        self.assertAlmostEqual(type7_quantile_v1([0, 1, 2, 3], 0.975), 2.925)

    def test_48_type7_requires_sorted_input(self) -> None:
        with self.assertRaises(ValueError):
            type7_quantile_v1([1, 0], 0.5)
        self.assertFalse(self.synthetic["type7"]["third_party_quantile_used"])

    def test_49_primary_scope_unadjusted_and_excluded(self) -> None:
        scope = self.contract["p_value_scope"]
        self.assertEqual(scope["primary_comparison"], PRIMARY_COMPARISON)
        self.assertEqual(scope["primary_p_value"], "UNADJUSTED")
        self.assertFalse(scope["primary_in_holm_family"])

    def test_50_secondary_scope_exact(self) -> None:
        self.assertEqual(tuple(self.contract["p_value_scope"]["secondary_comparisons"]), SECONDARY_COMPARISONS)

    def test_51_holm_exactly_two_and_primary_rejected(self) -> None:
        with self.assertRaises(ValueError):
            holm_adjust_secondary_pvalues_v1({PRIMARY_COMPARISON: Fraction(1, 2), "B1_VS_B0": Fraction(1, 2)})

    def test_52_holm_stepdown_and_mapping(self) -> None:
        result = holm_adjust_secondary_pvalues_v1({"B1_VS_B0": Fraction(1, 20), "P1_VS_B0": Fraction(1, 10)})
        self.assertEqual(result["B1_VS_B0"]["adjusted_p_value"], 0.1)
        self.assertEqual(result["P1_VS_B0"]["adjusted_p_value"], 0.1)

    def test_53_holm_cap_at_one(self) -> None:
        result = holm_adjust_secondary_pvalues_v1({"B1_VS_B0": Fraction(4, 5), "P1_VS_B0": Fraction(9, 10)})
        self.assertTrue(all(item["adjusted_p_value"] <= 1 for item in result.values()))

    def test_54_holm_adjusted_not_below_raw(self) -> None:
        result = holm_adjust_secondary_pvalues_v1({"B1_VS_B0": Fraction(1, 5), "P1_VS_B0": Fraction(1, 4)})
        self.assertTrue(all(item["adjusted_p_value"] >= item["raw_p_value"] for item in result.values()))

    def test_55_holm_tie_deterministic(self) -> None:
        self.assertTrue(self.synthetic["holm"]["deterministic_tie_fixture"])

    def test_56_fixed_comparisons_and_rng(self) -> None:
        self.assertEqual(COMPARISONS, ("P1_VS_B1", "B1_VS_B0", "P1_VS_B0"))
        self.assertIn("getrandbits", self.contract["clustered_sign_flip"]["rng"])
        self.assertIn("randrange", self.contract["whole_cluster_bootstrap"]["rng"])

    def test_57_restricted_lexical_deny_checks(self) -> None:
        self.assertEqual(synthetic_deny_checks_v1(), 7)
        assert_lexical_path_allowed_v1("evaluation/capability_routing_rq2d3_r1_v1/synthetic.json")

    def test_58_restricted_access_counts_zero(self) -> None:
        audit = restricted_access_audit_v1()
        self.assertTrue(all(value == 0 for key, value in audit.items() if key.endswith("_count") and key != "restricted_path_class_count"))

    def test_59_no_models_predictions_metrics_or_d4(self) -> None:
        audit = restricted_access_audit_v1()
        self.assertEqual((audit["model_execution_count"], audit["d4_execution_count"]), (0, 0))
        self.assertEqual((self.synthetic["track_b_prediction_count"], self.synthetic["track_b_metric_count"]), (0, 0))

    def test_60_no_policy_threshold_metric_comparison_seed_change(self) -> None:
        scope = self.contract["completion_scope"]
        self.assertFalse(scope["metric_targets_changed"])
        self.assertFalse(scope["comparisons_changed"])
        self.assertFalse(scope["seeds_changed"])
        self.assertFalse(self.authority["policy_change_authorised"])
        self.assertFalse(self.authority["threshold_change_authorised"])

    def test_61_no_gold_or_production_change(self) -> None:
        self.assertFalse(self.authority["gold_change_authorised"])
        self.assertFalse(self.authority["production_change_authorised"])

    def test_62_no_provider_or_network(self) -> None:
        self.assertEqual(self.synthetic["provider_calls"], 0)
        self.assertFalse(self.synthetic["network_access"])

    def test_63_all_new_python_ast_and_static_firewall(self) -> None:
        assert_python_ast()
        assert_restricted_access_static_firewall()

    def test_64_safe_outputs_and_governed_text_scan(self) -> None:
        assert_safe_outputs()
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_65_protected_source_comparison(self) -> None:
        assert_change_scope()

    def test_66_double_finalisation_byte_identical(self) -> None:
        assert_double_finalisation()

    def test_67_output_checksums(self) -> None:
        result = validate_output_checksums()
        self.assertEqual(result["referenced_tracked_output_count"], 20)

    def test_68_review_package_completeness_contract(self) -> None:
        members = expected_review_members()
        self.assertEqual((len(members), len(set(members))), (24, 24))

    def test_69_original_d0_contract_unmodified(self) -> None:
        self.assertEqual(self.historical["historical_base_sha256"], "60543ca8cf55eb200c567e787c0bcf0fbec8d7341d5e972d8ec091cda9880bf3")

    def test_70_complete_d3_not_started(self) -> None:
        self.assertFalse((ROOT / "evaluation/capability_routing_rq2d3_v1").exists())


if __name__ == "__main__":
    unittest.main()
