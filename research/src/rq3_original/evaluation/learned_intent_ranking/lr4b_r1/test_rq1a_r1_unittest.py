"""Standard-library tests for the RQ1-A-R1 effective contract."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from unittest import mock

from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
    analyse_contract as analyse_v1_contract,
)
from evaluation.learned_intent_ranking.lr4b.contract_schema import (
    authorised_project_path,
    canonical_json_bytes,
    sha256_file,
)

from .build_rq1a_r1_supplement import (
    EXPECTED_SCENARIOS,
    R1_ROOT,
    SAFE_JSON_FILENAMES,
    V1_EXPERIMENT_CONTRACT_SHA256,
    V1_EXPERIMENT_CONTRACT_PATH,
    V1_GITIGNORE_SHA256,
    V1_OUTPUT_CHECKSUM_PATH,
    V1_OUTPUT_CHECKSUM_SHA256,
    _build_duplicate_audit,
    _build_scenario_composition,
    build_supplement,
    supplement_bundle_fingerprint,
)
from .keyword_baseline_adapter import (
    FIXTURE_RECORD_COUNT,
    FIXTURE_SHA256,
    SemanticRuntimeForbidden,
    execute_keyword_parity,
    execute_keyword_parity_records,
    load_approved_fixture,
    summarise_keyword_parity,
)
from .statistical_decision_contract import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    FIVE_SEEDS,
    RANDOMISATION_MONTE_CARLO_RESAMPLES,
    RANDOMISATION_SEED,
    final_selection_gate,
    holm_adjusted_p_values,
    paired_approximate_randomisation_test,
    paired_bootstrap_ci,
    paired_effect_size,
    primary_statistical_gate,
    seed_robustness_gate,
    select_representative_seed,
    top1_macro_f1_gate,
    weak_class_gate,
)


ROOT = Path(__file__).resolve().parents[3]


class RQ1AR1ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outputs = build_supplement(ROOT)
        cls.v1_outputs, cls.ledger = analyse_v1_contract(ROOT)

    def test_01_real_keyword_parity_is_62_of_62(self) -> None:
        report = execute_keyword_parity(ROOT)
        self.assertEqual(report["fixture_sha256"], FIXTURE_SHA256)
        self.assertEqual(report["record_count"], FIXTURE_RECORD_COUNT)
        self.assertEqual(report["match_count"], 62)
        self.assertEqual(report["mismatch_count"], 0)

    def test_02_semantic_loader_mock_is_never_called(self) -> None:
        fixture = load_approved_fixture(ROOT)

        def forbidden_loader(*_args: object, **_kwargs: object) -> object:
            raise SemanticRuntimeForbidden("semantic runtime called")

        with mock.patch(
            "utils.production_intent_router.load_production_semantic_router",
            side_effect=forbidden_loader,
        ) as semantic_loader:
            results = execute_keyword_parity_records(fixture)
            loader_calls = semantic_loader.call_count
        report = summarise_keyword_parity(
            results,
            semantic_loader_call_count=loader_calls,
        )
        self.assertEqual(len(results), 62)
        self.assertEqual(loader_calls, 0)
        self.assertFalse(report["semantic_runtime_called"])

    def test_03_k0_ranking_length_is_one(self) -> None:
        fixture = load_approved_fixture(ROOT)
        with mock.patch(
            "utils.production_intent_router.load_production_semantic_router",
            side_effect=SemanticRuntimeForbidden("semantic runtime called"),
        ):
            results = execute_keyword_parity_records(fixture)
        self.assertTrue(all(len(result.ranking) == 1 for result in results))
        self.assertTrue(all(result.ranking[0] == result.production_selected_intent for result in results))

    def test_04_parity_output_contains_no_fixture_query_text(self) -> None:
        report = self.outputs["rq1a_r1_keyword_parity_v1.json"]
        serialised = canonical_json_bytes(report)
        for row in load_approved_fixture(ROOT):
            value = row["query"].encode("utf-8")
            if len(value) >= 24 and value in serialised:
                self.fail("governed fixture text appeared in parity output")

    def test_05_scenario_membership_matches_rq1a(self) -> None:
        report = _build_scenario_composition(self.ledger, self.v1_outputs)
        prior = {
            row["scenario_id"]: (row["record_count"], row["membership_sha256"])
            for row in self.v1_outputs["lr4b_data_scenario_summary_v1.json"]["scenarios"]
        }
        current = {
            row["scenario_id"]: (row["record_count"], row["membership_sha256"])
            for row in report["scenarios"]
        }
        self.assertEqual(current, prior)
        self.assertEqual({key: value[0] for key, value in current.items()}, EXPECTED_SCENARIOS)

    def test_06_pure_data_volume_flag_is_false(self) -> None:
        report = self.outputs["rq1a_r1_scenario_composition_v1.json"]
        self.assertIs(report["pure_data_volume_causal_interpretation"], False)
        self.assertEqual(
            report["scenario_method"],
            "CUMULATIVE_GOVERNED_TRAINING_EVIDENCE_EXPANSION",
        )

    def test_07_duplicate_aggregate_matches_expected(self) -> None:
        report = _build_duplicate_audit(self.ledger)
        self.assertEqual(report["total_record_count"], 318)
        self.assertEqual(report["unique_representation_count"], 297)
        self.assertEqual(report["duplicate_group_count"], 10)
        self.assertEqual(report["records_in_duplicate_groups"], 31)
        self.assertEqual(report["duplicate_extra_row_count"], 21)
        self.assertEqual(report["maximum_group_size"], 6)
        self.assertEqual(report["group_size_frequency"], {"2": 5, "3": 2, "4": 1, "5": 1, "6": 1})

    def test_08_cross_label_duplicate_count_is_zero(self) -> None:
        report = self.outputs["rq1a_r1_duplicate_representation_audit_v1.json"]
        self.assertEqual(report["same_label_duplicate_group_count"], 10)
        self.assertEqual(report["cross_label_duplicate_group_count"], 0)
        self.assertEqual(
            {key: value["duplicate_extra_row_count"] for key, value in report["per_scenario_duplicate_counts"].items()},
            {"V0": 0, "V1": 21, "V2": 21, "V3": 21},
        )

    def test_09_representative_seed_is_nearest_to_mean(self) -> None:
        rows = [
            {"seed": seed, "view_a_mrr": mrr, "view_a_top1": 0.5, "view_a_macro_f1": 0.5}
            for seed, mrr in zip(FIVE_SEEDS, (0.1, 0.2, 0.3, 0.4, 0.9), strict=True)
        ]
        self.assertEqual(select_representative_seed(rows), 20260816)

    def test_10_representative_seed_tie_break_sequence(self) -> None:
        mrrs = (0.05, 0.15, 0.3, 0.5, 1.0)
        rows = [
            {"seed": seed, "view_a_mrr": mrr, "view_a_top1": 0.4, "view_a_macro_f1": 0.4}
            for seed, mrr in zip(FIVE_SEEDS, mrrs, strict=True)
        ]
        rows[2]["view_a_top1"] = 0.6
        rows[3]["view_a_top1"] = 0.7
        self.assertEqual(select_representative_seed(rows), 20260816)
        rows[2]["view_a_top1"] = rows[3]["view_a_top1"] = 0.7
        rows[2]["view_a_macro_f1"] = 0.8
        rows[3]["view_a_macro_f1"] = 0.7
        self.assertEqual(select_representative_seed(rows), 20260815)
        rows[2]["view_a_macro_f1"] = rows[3]["view_a_macro_f1"] = 0.8
        self.assertEqual(select_representative_seed(rows), 20260815)

    def test_11_exact_sign_flip_synthetic_fixture(self) -> None:
        result = paired_approximate_randomisation_test((1.0, 1.0), (0.0, 0.0))
        self.assertEqual(result["method"], "EXACT_SIGN_FLIP_ENUMERATION")
        self.assertEqual(result["resample_count"], 4)
        self.assertEqual(result["extreme_count"], 2)
        self.assertAlmostEqual(result["p_value"], 0.6)

    def test_12_monte_carlo_randomisation_is_reproducible(self) -> None:
        m64 = (1.0,) * 21
        c0 = (0.0,) * 21
        first = paired_approximate_randomisation_test(
            m64, c0, monte_carlo_resamples=2500, random_seed=RANDOMISATION_SEED
        )
        second = paired_approximate_randomisation_test(
            m64, c0, monte_carlo_resamples=2500, random_seed=RANDOMISATION_SEED
        )
        self.assertEqual(first, second)
        self.assertEqual(first["method"], "MONTE_CARLO_SIGN_FLIP")

    def test_13_bootstrap_ci_is_reproducible(self) -> None:
        first = paired_bootstrap_ci(
            (1.0, 0.5, 0.25), (0.0, 0.25, 0.5), resamples=1000, random_seed=BOOTSTRAP_SEED
        )
        second = paired_bootstrap_ci(
            (1.0, 0.5, 0.25), (0.0, 0.25, 0.5), resamples=1000, random_seed=BOOTSTRAP_SEED
        )
        self.assertEqual(first, second)

    def test_14_all_tie_rank_biserial_is_undefined(self) -> None:
        effect = paired_effect_size((1.0, 0.5), (1.0, 0.5))
        self.assertIsNone(effect["matched_rank_biserial_correlation"])
        self.assertEqual(effect["matched_rank_biserial_status"], "UNDEFINED_ALL_TIES")

    def test_15_macro_f1_tolerance_gate(self) -> None:
        self.assertTrue(top1_macro_f1_gate(
            representative_m64_top1=0.7,
            c0_top1=0.7,
            representative_m64_macro_f1=0.69,
            c0_macro_f1=0.70,
        ))
        self.assertFalse(top1_macro_f1_gate(
            representative_m64_top1=0.7,
            c0_top1=0.7,
            representative_m64_macro_f1=0.689,
            c0_macro_f1=0.70,
        ))

    def test_16_weak_class_gate(self) -> None:
        self.assertTrue(weak_class_gate({
            "A": {"support": 5, "c0_f1": 0.8, "m64_f1": 0.65},
            "B": {"support": 4, "c0_f1": 0.9, "m64_f1": 0.0},
        }))
        self.assertFalse(weak_class_gate({
            "A": {"support": 5, "c0_f1": 0.8, "m64_f1": 0.649},
        }))
        self.assertFalse(weak_class_gate({
            "A": {"support": 5, "c0_f1": 0.1, "m64_f1": 0.0},
        }))

    def test_17_final_gold_path_is_rejected_before_access(self) -> None:
        with self.assertRaises(PermissionError):
            authorised_project_path(
                ROOT,
                "evaluation/learned_intent_ranking/lr1r/primary_v3_input/rejected.json",
            )

    def test_18_safe_outputs_contain_no_governed_natural_language(self) -> None:
        serialised = b"".join(
            canonical_json_bytes(self.outputs[name]) for name in sorted(self.outputs)
        )
        for row in load_approved_fixture(ROOT):
            value = row["query"].encode("utf-8")
            if len(value) >= 24 and value in serialised:
                self.fail("governed fixture text appeared in safe output")
        retained_path = ROOT / (
            "evaluation/learned_intent_ranking/lr4a/training_data_input/"
            "eedi_stage_e4_confirmed_candidate_subset_256.csv"
        )
        with retained_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                for field in (
                    "utterance_for_review",
                    "previous_turns_for_review",
                    "question_anchor_for_review",
                ):
                    value = row[field].encode("utf-8")
                    if len(value) >= 24 and value in serialised:
                        self.fail("governed source text appeared in safe output")

    def test_19_original_rq1a_artifact_hashes_are_unchanged(self) -> None:
        self.assertEqual(sha256_file(ROOT / ".gitignore"), V1_GITIGNORE_SHA256)
        self.assertEqual(
            sha256_file(ROOT / V1_EXPERIMENT_CONTRACT_PATH),
            V1_EXPERIMENT_CONTRACT_SHA256,
        )
        manifest = ROOT / V1_OUTPUT_CHECKSUM_PATH
        self.assertEqual(sha256_file(manifest), V1_OUTPUT_CHECKSUM_SHA256)
        lines = [line for line in manifest.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(lines), 14)
        for line in lines:
            expected, relative_path = line.split("  ", 1)
            self.assertEqual(sha256_file(ROOT / relative_path), expected)

    def test_20_two_supplement_builds_are_byte_identical(self) -> None:
        first = build_supplement(ROOT)
        second = build_supplement(ROOT)
        self.assertEqual(
            {name: canonical_json_bytes(value) for name, value in first.items()},
            {name: canonical_json_bytes(value) for name, value in second.items()},
        )
        self.assertEqual(
            supplement_bundle_fingerprint(first),
            supplement_bundle_fingerprint(second),
        )

    def test_21_frozen_statistical_parameters(self) -> None:
        report = self.outputs["rq1a_r1_statistical_decision_contract_v1.json"]
        self.assertEqual(RANDOMISATION_MONTE_CARLO_RESAMPLES, 100000)
        self.assertEqual(RANDOMISATION_SEED, 20260825)
        self.assertEqual(BOOTSTRAP_RESAMPLES, 50000)
        self.assertEqual(BOOTSTRAP_SEED, 20260826)
        self.assertEqual(report["paired_bootstrap_ci"]["resamples"], 50000)

    def test_22_primary_and_seed_robustness_gates(self) -> None:
        self.assertTrue(primary_statistical_gate(
            representative_m64_mrr=0.6,
            c0_mrr=0.5,
            mean_delta_rr=0.1,
            bootstrap_lower_bound=0.01,
            paired_randomisation_p_value=0.049,
        ))
        self.assertFalse(primary_statistical_gate(
            representative_m64_mrr=0.6,
            c0_mrr=0.5,
            mean_delta_rr=0.1,
            bootstrap_lower_bound=0.0,
            paired_randomisation_p_value=0.049,
        ))
        self.assertTrue(seed_robustness_gate((0.6, 0.6, 0.6, 0.6, 0.4), 0.5))
        self.assertFalse(seed_robustness_gate((0.6, 0.6, 0.6, 0.4, 0.4), 0.5))

    def test_23_holm_and_final_selection(self) -> None:
        self.assertEqual(holm_adjusted_p_values((0.01, 0.04, 0.03)), (0.03, 0.06, 0.06))
        self.assertEqual(final_selection_gate(
            primary_mrr_significance=True,
            top1_direction=True,
            macro_f1_tolerance=True,
            weak_class=True,
            seed_robustness=True,
            no_final_gold_tuning=True,
            no_taxonomy_change=True,
        ), "M64_REPLACES_C0")
        self.assertEqual(final_selection_gate(
            primary_mrr_significance=True,
            top1_direction=True,
            macro_f1_tolerance=False,
            weak_class=True,
            seed_robustness=True,
            no_final_gold_tuning=True,
            no_taxonomy_change=True,
        ), "C0_REMAINS_SELECTED")

    def test_24_safe_json_filename_set_is_exact(self) -> None:
        self.assertEqual(set(self.outputs), set(SAFE_JSON_FILENAMES))
        self.assertEqual(R1_ROOT.as_posix(), "evaluation/learned_intent_ranking/lr4b_r1")


if __name__ == "__main__":
    unittest.main()
