"""Targeted offline F1 gates; no production/component/model execution.

Raw identity reads use the sealed guard. Failures report test names, never
condition dictionaries or candidate text. Statistical reproduction is in RAM;
existing frozen outputs are neither replaced nor regenerated on disk.
"""
from collections import Counter, defaultdict
from datetime import datetime
import ast
import csv
import io
import itertools
import json
import math
import re
import statistics
import struct
import sys
import unittest
from unittest import mock

import numpy as np
from PIL import Image
from scipy.stats import wilcoxon as scipy_wilcoxon

from f1_common import *
import f1_controlled_unblinding_guard as guard
import f1_statistics as stats
import build_f1_analysis_inputs as inputs
import analyze_f1_results as analysis
import synthesize_f1_mechanisms as mechanisms
import build_f1_figures as figures
from f1_entry_binding import ENTRY_RECEIPT_SHA256
from finalize_f1_analysis import verify_ledger
from build_f1_review_package import validate_allowlist

READER = "test_f1_final_analysis.py"


class F1TargetedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert not FINAL_RECEIPT.exists(), "Use hash-only final verification after the freeze."
        cls.entry, _ = guard.verify_entry()
        cls.gates = read_json(HERE / "F1_STARTING_GATES_V1.json")
        cls.plan = read_json(HERE / "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json")
        cls.sources = inputs.load_sources()
        cls.table = guard.controlled_jsonl(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.jsonl", "SOURCE_INTEGRITY_TEST", READER)
        cls.pairs = guard.controlled_jsonl(RI / "c4_real_f1_frozen_pair_registry_v1.jsonl", "PAIR_REGISTRY_TEST", READER)
        cls.csv_table = guard.controlled_bytes(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.csv", "SOURCE_INTEGRITY_TEST", READER)
        cls.rebuilt = inputs.build_inputs(cls.sources)
        cls.recalculated = analysis.calculate(cls.table)
        cls.mechanism_rebuilt, cls.mechanism_csv_rows = mechanisms.load_and_synthesize()
        cls.mode, cls.primary, cls.secondary = [read_json(HERE / f"C4_REAL_F1_{name}_V1.json")["records"]
                                               for name in ["MODE_SUMMARIES", "PRIMARY_CONTRAST_RESULTS", "SECONDARY_OUTCOME_RESULTS"]]
        cls.cohorts = read_json(HERE / "C4_REAL_F1_FROZEN_COHORT_SENSITIVITY_V1.json")["cohorts"]
        cls.strata = read_json(HERE / "C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1.json")["strata"]
        cls.mechanism = read_json(HERE / "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json")

    def test_01_exact_starting_worktree_branch_head(self):
        self.assertTrue(str(ROOT) == EXPECTED_ROOT == self.gates["working_directory"])
        self.assertTrue(git("branch", "--show-current") == EXPECTED_BRANCH == self.gates["branch"])
        self.assertTrue(git("rev-parse", "HEAD") == STARTING_HEAD == self.gates["starting_head"])
        self.assertTrue(self.gates["tracked_modifications"] == 0 and self.gates["new_conversation"])
        self.assertTrue(sorted(self.gates["initial_status_before_f1_preparation"]) == sorted("?? " + x for x in RETAINED))

    def test_02_three_retained_historical_files_unchanged(self):
        rows = self.gates["retained_untracked_files"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(sha(ROOT / r["path"]) == r["sha256"] and not git("ls-files", "--", r["path"]) for r in rows))

    def test_03_all_17_authority_hashes(self):
        self.assertEqual(len(EXPECTED_HASHES), 17)
        self.assertTrue(all(sha(ROOT / p) == digest for p, digest in EXPECTED_HASHES.items()), "Specified source hash mismatch")
        authority = read_json(HERE / "F1_SOURCE_AUTHORITY_METADATA_V1.json")
        self.assertEqual(authority["f0_mode_unblinding_count"], 0)
        self.assertEqual(authority["f0_treatment_effect_analysis_count"], 0)
        self.assertEqual(authority["excluded_judge_results_selected"], 0)
        self.assertEqual(authority["human_items_per_rater"], 44)

    def test_04_all_838_preexisting_source_bytes(self):
        snapshot = read_json(HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json")
        self.assertEqual(snapshot["file_count"], 838)
        self.assertEqual(len(snapshot["files"]), 838)
        self.assertTrue(all(sha(ROOT / p) == d for p, d in snapshot["files"].items()), "Pre-existing source changed")

    def test_05_entry_receipt_and_sealed_implementation(self):
        self.assertEqual(sha(RECEIPT), ENTRY_RECEIPT_SHA256)
        self.assertTrue(guard.verify_entry()[0] == self.entry)
        self.assertEqual(self.entry["write_count"], 1)
        self.assertFalse(self.entry["overwrite_permitted"])
        self.assertEqual(self.entry["mode_mappings_opened_before_receipt"], 0)
        self.assertEqual(self.entry["system_comparisons_computed_before_receipt"], 0)

    def test_06_hierarchy_precedes_mapping_access(self):
        hierarchy = read_json(HERE / "F1_ANALYSIS_CONTRACT_HIERARCHY_V1.json")
        self.assertEqual(hierarchy["contrast_or_multiplicity_conflict_resolution"], "REAL_C4_MODE_REGISTRY_CONTROLS")
        self.assertFalse(hierarchy["controlled_rq3_contrast_formulas_executable"])
        first = verify_ledger()[0][0]
        self.assertTrue(datetime.fromisoformat(hierarchy["frozen_at_utc"]) <= datetime.fromisoformat(self.entry["frozen_at_utc"]) < datetime.fromisoformat(first["timestamp_utc"]))
        self.assertTrue(datetime.fromisoformat(self.plan["frozen_at_utc"]) <= datetime.fromisoformat(self.entry["frozen_at_utc"]))

    def test_07_ledger_metadata_schema_hash_chain_order(self):
        rows, _ = verify_ledger()
        self.assertGreater(len(rows), 94)
        self.assertTrue(all(r["entry_receipt_sha256"] == ENTRY_RECEIPT_SHA256 for r in rows))

    def test_08_write_once_and_fail_closed_guards(self):
        before = sha(RECEIPT)
        with self.assertRaises(FileExistsError):
            write_once_bytes(RECEIPT, b"SYNTHETIC_OVERWRITE_ATTEMPT_REJECTED")
        self.assertEqual(sha(RECEIPT), before)
        ledger_before = sha(LEDGER)
        with self.assertRaises(RuntimeError):
            read_json(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.jsonl")
        with self.assertRaises(RuntimeError):
            guard.controlled_bytes(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.jsonl", "UNDECLARED", READER)
        with mock.patch.object(guard, "sha", return_value="0" * 64):
            with self.assertRaisesRegex(RuntimeError, "F1_ENTRY_RECEIPT_HASH_MISMATCH"):
                guard.verify_entry()
        with mock.patch.object(guard, "FINAL_RECEIPT") as final_path:
            final_path.exists.return_value = True
            with self.assertRaisesRegex(RuntimeError, "F1_ACCESS_CLOSED_BY_FINAL_FREEZE"):
                guard.controlled_bytes(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.jsonl", "SOURCE_INTEGRITY_TEST", READER)
        self.assertEqual(sha(LEDGER), ledger_before)

    def test_09_private_outputs_and_hmac_permissions(self):
        rows = read_json(HERE / "F1_RESTRICTED_ANALYSIS_METADATA_V1.json")["files"]
        self.assertEqual(len(rows), 3)
        for r in rows:
            path = RI / r["filename"]
            self.assertTrue(sha(path) == r["sha256"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(git("ls-files", "--", str(path.relative_to(ROOT))))
            self.assertTrue(git("check-ignore", "--", str(path.relative_to(ROOT))))
        key = RI / "c4_real_i1_blinding_hmac_key.bin"
        self.assertEqual(key.stat().st_size, 32)
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_10_condition_and_scenario_cardinality(self):
        self.assertEqual(len(self.table), 558)
        self.assertEqual(len({r["opaque_condition_id"] for r in self.table}), 558)
        self.assertEqual(len({r["scenario_id"] for r in self.table}), 62)
        self.assertEqual(len({r["scenario_family_id"] for r in self.table}), 62)
        self.assertTrue(all(r["scenario_id"] == r["scenario_family_id"] for r in self.table))

    def test_11_nine_modes_per_scenario_and_62_per_mode(self):
        modes = set(self.plan["mode_identities"])
        self.assertEqual(len(modes), 9)
        self.assertTrue(Counter(r["mode_id"] for r in self.table) == Counter({m: 62 for m in modes}))
        self.assertTrue(all({r["mode_id"] for r in self.table if r["scenario_id"] == sid} == modes for sid in {r["scenario_id"] for r in self.table}))

    def test_12_judge_identity_mapping_and_unequal_payload_guard(self):
        grouped = defaultdict(set)
        for r in self.table:
            grouped[r["corrected_judge_result_id"]].add(r["corrected_judge_payload_sha256"])
        self.assertEqual(len(grouped), 149)
        self.assertTrue(all(len(v) == 1 for v in grouped.values()))
        self.assertEqual(len({r["response_blind_id"] for r in self.table}), 147)
        self.assertEqual(len(self.sources["judge"]), 149)

    def test_13_exact_f0_primary_scores_no_secondary_in_mean(self):
        judge = {r["logical_judge_request_id"]: r for r in self.sources["judge"]}
        for row in self.table:
            source = judge[row["corrected_judge_request_id"]]
            values = [source["parsed_semantic_result"][c.lower()] for c in CRITERIA if source["frozen_applicability_map"]["criteria"][c]]
            self.assertTrue(row[PRIMARY_OUTCOME] == source["parsed_semantic_result"]["overall_applicable_mean"] == sum(values) / len(values))
            self.assertTrue(all(row[c] == source["parsed_semantic_result"][c.lower()] for c in SECONDARY))
        self.assertEqual(len(CRITERIA), 8)
        self.assertNotIn("EVIDENCE_FAITHFULNESS", CRITERIA)
        self.assertNotIn("UNSUPPORTED_CLAIM_COUNT", CRITERIA)

    def test_14_frozen_id_join_and_pair_registry_reproduce(self):
        table, pairs, audit, unit = self.rebuilt
        self.assertTrue(table == self.table, "Condition identity join did not reproduce")
        self.assertTrue(pairs == self.pairs, "Pair registry did not reproduce")
        self.assertTrue(audit == read_json(HERE / "F1_ANALYSIS_INPUT_INTEGRITY_V1.json"))
        self.assertTrue(unit == read_json(HERE / "F1_PAIRING_UNIT_AND_IDENTITY_AUDIT_V1.json"))

    def test_15_mode_means_use_conditions_not_unique_request_weighting(self):
        for mode in self.plan["mode_identities"]:
            rows = [r for r in self.table if r["mode_id"] == mode]
            summary = next(r for r in self.mode if r["mode_id"] == mode and r["outcome"] == PRIMARY_OUTCOME)
            self.assertEqual(len(rows), 62)
            self.assertEqual(len({r["logical_generation_request_id"] for r in rows}), 60)
            self.assertTrue(summary["mean"] == statistics.mean(r[PRIMARY_OUTCOME] for r in rows))
            self.assertEqual(summary["scenario_count"], 62)

    def test_16_exact_eight_contrasts_and_directions(self):
        registry = self.sources["mode_registry"]
        expected = [(r["comparison_id"], r["left"], r["right"], family)
                    for key, family in [("primary", "PRIMARY_ADD_ONE"), ("targeted_remove_one", "TARGETED_REMOVE_ONE")]
                    for r in registry["frozen_comparisons"][key]]
        self.assertTrue(expected == CONTRASTS)
        self.assertTrue([(r["contrast_id"], r["left_mode_id"], r["right_mode_id"], r["holm_family"]) for r in self.primary] == CONTRASTS)
        self.assertEqual(len(self.primary), 8)
        self.assertTrue(all(r["difference_direction"] == "LEFT_MINUS_RIGHT" for r in self.primary))
        self.assertFalse(any(token in r["contrast_id"] for r in self.primary for token in ["RM00", "ORACLE", "ALWAYS", "PREDICTED"]))

    def test_17_primary_pairs_are_62_families_not_558_or_149_units(self):
        self.assertEqual(len(self.pairs), 496)
        for cid, left, right, family in CONTRASTS:
            pairs = [r for r in self.pairs if r["contrast_id"] == cid]
            self.assertEqual(len(pairs), 62)
            self.assertEqual(len({r["scenario_family_id"] for r in pairs}), 62)
            self.assertTrue(all(r["left_mode_id"] == left and r["right_mode_id"] == right and r["primary_complete"] for r in pairs))
        self.assertTrue(all(r["paired_scenario_count"] == r["scenario_family_count"] == r["sign_flip"]["family_count"] == 62 for r in self.primary))
        self.assertTrue(all(r["excluded_case_count"] == r["excluded_family_count"] == 0 for r in self.primary))

    def test_18_complete_pair_rule_removes_whole_missing_pair(self):
        rows = [{"scenario_id": "SYN_A", "scenario_family_id": "F_A", "mode_id": "LEFT", "X": 3},
                {"scenario_id": "SYN_B", "scenario_family_id": "F_B", "mode_id": "LEFT", "X": 4},
                {"scenario_id": "SYN_B", "scenario_family_id": "F_B", "mode_id": "RIGHT", "X": 2}]
        pairs, excluded = analysis.complete_pairs(rows, "LEFT", "RIGHT", "X")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(excluded[0]["reason"], "MISSING_RIGHT_CONDITION")
        self.assertEqual(analysis.describe_pairs(pairs, "X")[0]["paired_mean_difference"], 2)

    def test_19_na_pairs_are_unimputed_and_reasoned(self):
        rows = []
        for sid, left, right in [("A", "NA", 2), ("B", 3, "NA"), ("C", "NA", "NA"), ("D", 4, 3)]:
            rows.extend({"scenario_id": sid, "scenario_family_id": sid, "mode_id": m, "X": value} for m, value in [("L", left), ("R", right)])
        pairs, excluded = analysis.complete_pairs(rows, "L", "R", "X")
        self.assertEqual(len(pairs), 1)
        self.assertEqual({r["reason"] for r in excluded}, {"NA_LEFT_ONLY", "NA_RIGHT_ONLY", "NA_BOTH_SIDES"})

    def test_20_route_inactive_shared_payload_zero_pairs_retained(self):
        total = 0
        for cid, left, right, _ in CONTRASTS:
            pairs, _ = analysis.complete_pairs(self.table, left, right, PRIMARY_OUTCOME)
            shared = [(l, r) for l, r in pairs if l["corrected_judge_payload_sha256"] == r["corrected_judge_payload_sha256"]
                      and l["answer_text_sha256"] == r["answer_text_sha256"]]
            self.assertTrue(all(l[PRIMARY_OUTCOME] - r[PRIMARY_OUTCOME] == 0 for l, r in shared))
            observed = next(r for r in self.primary if r["contrast_id"] == cid)
            self.assertEqual(observed["ties"], sum(abs(l[PRIMARY_OUTCOME] - r[PRIMARY_OUTCOME]) <= 1e-12 for l, r in pairs))
            self.assertEqual(observed["sign_flip"]["zero_family_differences_retained"], observed["ties"])
            total += sum(not l["rag_active"] and not l["memory_active"] and not l["planning_active"] for l, r in shared)
        self.assertGreater(total, 0)

    def test_21_bootstrap_seed_replicates_and_actual_family_counts(self):
        for r in self.primary:
            self.assertEqual(r["bootstrap"]["replicates"], 10000)
            self.assertEqual(r["bootstrap"]["seed"], 20260831)
            self.assertEqual(r["bootstrap"]["eligible_families"], 62)
            self.assertEqual(r["bootstrap"]["quantile_method"], "linear")

    def test_22_bootstrap_retains_all_members_of_sampled_families(self):
        groups = {"A": [1.0, 3.0], "B": [-2.0], "C": [5.0, 0.0, 1.0]}
        draws = np.random.Generator(np.random.PCG64(20260831)).integers(0, 3, size=(10000, 3), dtype=np.int64)
        members = [groups[k] for k in sorted(groups)]
        values = [statistics.mean([x for index in draw for x in members[index]]) for draw in draws]
        bounds = np.quantile(values, [0.025, 0.975], method="linear")
        actual = stats.cluster_bootstrap(groups)
        self.assertEqual([actual["ci_low"], actual["ci_high"]], list(bounds))
        self.assertEqual(stats.family_means(groups), [2.0, -2.0, 2.0])

    def test_23_bootstrap_insufficient_family_guard(self):
        for groups in [{}, {"A": [1.0, 2.0]}]:
            self.assertEqual(stats.cluster_bootstrap(groups)["status"], "NOT_ESTIMABLE_INSUFFICIENT_FAMILIES")
            self.assertIsNone(stats.cluster_bootstrap(groups)["ci_low"])

    def test_24_sign_flip_exact_rule_including_F20_boundary(self):
        d = [1.0, 2.0, 0.0]
        observed = abs(statistics.mean(d))
        extreme = sum(abs(statistics.mean([a * b for a, b in zip(signs, d)])) >= observed - 1e-12
                      for signs in itertools.product([-1, 1], repeat=3))
        result = stats.sign_flip(d)
        self.assertEqual(result["p_value"], extreme / 8)
        boundary = stats.sign_flip([1.0] + [0.0] * 19)
        self.assertEqual(boundary["method"], "EXACT_ENUMERATION")
        self.assertEqual(boundary["assignment_count"], 2 ** 20)
        self.assertEqual(boundary["p_value"], 1.0)
        self.assertEqual(stats.sign_flip([])["status"], "NOT_ESTIMABLE_NO_COMPLETE_FAMILIES")

    def test_25_sign_flip_mc_rule_F21_and_plus_one(self):
        d = np.array([1.0, 2.0] + [0.0] * 19)
        signs = 2 * np.random.Generator(np.random.PCG64(20260831)).integers(0, 2, size=(100000, 21), dtype=np.int64) - 1
        extreme = int(np.sum(np.abs((signs * d).mean(axis=1)) >= abs(statistics.mean(d.tolist())) - 1e-12))
        result = stats.sign_flip(d)
        self.assertEqual(result["method"], "MONTE_CARLO_SIGN_FLIP")
        self.assertEqual(result["assignment_count"], 100000)
        self.assertEqual(result["zero_family_differences_retained"], 19)
        self.assertEqual(result["p_value"], (1 + extreme) / 100001)
        self.assertTrue(all(r["raw_p_value"] == (1 + r["sign_flip"]["extreme_count"]) / 100001 for r in self.primary))

    def test_26_wilcoxon_exact_tied_rank_distribution(self):
        result = stats.wilcoxon_and_rank_biserial([1, -1, 2, 0])
        self.assertEqual(result["wilcoxon_p_value"], 0.75)
        self.assertEqual(result["positive_rank_sum"], 4.5)
        self.assertEqual(result["negative_rank_sum"], 1.5)
        self.assertEqual(result["rank_biserial"], 0.5)
        self.assertEqual(result["nonzero_family_count"], 3)
        self.assertFalse(result["wilcoxon_continuity_correction"])

    def test_27_wilcoxon_independent_scipy_exact_check(self):
        d = [1, -3, 2, 4, -5, 6]
        actual = stats.wilcoxon_and_rank_biserial(d)
        reference = scipy_wilcoxon(d, alternative="two-sided", zero_method="wilcox", correction=False, method="exact")
        self.assertEqual(actual["wilcoxon_p_value"], reference.pvalue)
        self.assertEqual(actual["wilcoxon_statistic"], reference.statistic)

    def test_28_wilcoxon_and_rank_all_zero_guards(self):
        row = stats.wilcoxon_and_rank_biserial([0, 0, 1e-13])
        self.assertEqual(row["wilcoxon_status"], "NOT_ESTIMABLE_ALL_ZERO_WITH_EXACT_AGREEMENT_REPORTED")
        self.assertEqual(row["rank_biserial_status"], "NOT_ESTIMABLE_ALL_ZERO")
        self.assertIsNone(row["wilcoxon_p_value"])
        self.assertIsNone(row["rank_biserial"])

    def test_29_paired_dz_sample_sd_and_mathematical_guards(self):
        self.assertEqual(stats.paired_dz([-1, 1, 3])["paired_dz"], 0.5)
        self.assertEqual(stats.paired_dz([-1, 1, 3])["family_difference_sample_sd"], 2)
        self.assertEqual(stats.paired_dz([2, 2])["paired_dz_status"], "NOT_ESTIMABLE_ZERO_STANDARD_DEVIATION")
        self.assertEqual(stats.paired_dz([2])["paired_dz_status"], "NOT_ESTIMABLE_INSUFFICIENT_FAMILIES")
        for row in self.primary:
            self.assertEqual(row["paired_dz"], row["family_mean_difference"] / row["family_difference_sample_sd"])
            self.assertEqual(row["rank_biserial"], (row["positive_rank_sum"] - row["negative_rank_sum"]) / (row["positive_rank_sum"] + row["negative_rank_sum"]))

    def test_30_win_tie_loss_tolerance_and_lower_count_orientation(self):
        self.assertEqual(stats.wins_ties_losses([-1, -1e-13, 0, 1e-13, 1]), {"wins": 1, "ties": 3, "losses": 1})
        self.assertEqual(stats.wins_ties_losses([-1, 0, 2, 3], higher_is_better=False), {"wins": 1, "ties": 1, "losses": 2})
        self.assertTrue(all(r["wins"] + r["ties"] + r["losses"] == 62 for r in self.primary))

    def test_31_holm_separate_five_three_families(self):
        self.assertEqual(stats.holm([0.03, 0.01, 0.04]), [0.06, 0.03, 0.06])
        for family, n in [("PRIMARY_ADD_ONE", 5), ("TARGETED_REMOVE_ONE", 3)]:
            rows = [r for r in self.primary if r["holm_family"] == family]
            self.assertEqual(len(rows), n)
            self.assertEqual(len(self.plan["holm_families"][family]), n)
            ordered = sorted(range(n), key=lambda i: rows[i]["raw_p_value"])
            for rank, i in enumerate(ordered):
                expected = min(1, max((n - j) * rows[ordered[j]]["raw_p_value"] for j in range(rank + 1)))
                self.assertEqual(rows[i]["holm_adjusted_p_value"], expected)
        with self.assertRaises(ValueError):
            stats.holm([0.01, None])

    def test_32_all_five_statistical_outputs_reproduce_exactly(self):
        actual = (self.mode, self.primary, self.secondary, self.cohorts, self.strata)
        self.assertTrue(self.recalculated == actual, "Statistical outputs differ from sealed-procedure reproduction")

    def test_33_secondary_denominators_and_no_inference(self):
        self.assertEqual(len(self.secondary), 80)
        self.assertTrue(all(r["analysis_role"] == "SECONDARY_EXPLORATORY" and not r["p_values_computed"] and r["holm_family"] is None for r in self.secondary))
        self.assertTrue(all(r["applicable_pair_count"] + r["excluded_pair_count"] == 62 for r in self.secondary))
        self.assertTrue(all(r["excluded_pair_count"] == sum(r["exclusion_reason_counts"].values()) for r in self.secondary))
        error = next(r for r in self.secondary if r["contrast_id"] == "C1_MINUS_C0" and r["outcome"] == "ERROR_HANDLING")
        self.assertEqual(error["applicable_pair_count"], 0)
        self.assertIsNone(error["paired_mean_difference"])
        self.assertEqual(error["exclusion_reason_counts"], {"NA_BOTH_SIDES": 52, "NA_RIGHT_ONLY": 10})
        self.assertTrue(all(r["applicable_pair_count"] == 6 for r in self.secondary if r["outcome"] == "MULTI_PAGE_COHESIVENESS"))

    def test_34_frozen_cohort_identity_exact_membership(self):
        original = set(self.sources["original25"]["unified_scenario_ids"])
        persistent = {r["unified_scenario_id"] for r in self.sources["memory_registry"] if r["persistent_replay_eligible"] == "YES"}
        self.assertEqual(len(original), 25)
        self.assertEqual(len(persistent), 9)
        self.assertTrue(original == {r["scenario_id"] for r in self.table if r["original_25_member"]})
        self.assertTrue(persistent == {r["scenario_id"] for r in self.table if r["persistent_memory_replay_member"]})
        for path in ["evaluation/rq3_real_c4/track_d_dataset/original_25_subset_identity_v1.json", "evaluation/rq3_real_c4/track_d_dataset/memory_scenario_registry_v1.csv"]:
            self.assertTrue(path in self.entry["dataset_identity_hashes"])
            self.assertTrue(sha(ROOT / path) == self.entry["dataset_identity_hashes"][path])
            cohort_commit = git("log", "-1", "--format=%H", "--", path)
            response_commit = git("log", "-1", "--format=%H", "--", "evaluation/rq3_real_c4/r3d1_response_integration/c4_real_r3_canonical_unique_responses_frozen_v1.jsonl")
            self.assertTrue(subprocess.run(["git", "merge-base", "--is-ancestor", cohort_commit, response_commit], cwd=ROOT, capture_output=True).returncode == 0)

    def test_35_cohort_outputs_exploratory_only(self):
        self.assertEqual([r["scenario_count"] for r in self.cohorts], [25, 9])
        self.assertTrue(all(c["analysis_role"] == "FROZEN_COHORT_SENSITIVITY_EXPLORATORY" for c in self.cohorts))
        self.assertTrue(all(len(c["contrasts"]) == 8 and c["pre_response_identity_verified"] for c in self.cohorts))
        self.assertTrue(all(not r["confirmatory_p_values_computed"] and "holm_adjusted_p_value" not in r for c in self.cohorts for r in c["contrasts"]))

    def test_36_status_strata_predeclared_reference_and_no_inference(self):
        self.assertEqual(len(self.strata), 10)
        self.assertTrue(all(r["membership_reference_mode"] == "C5_FULL_C4" and not r["inference_computed"] and not r["unbiased_component_causal_effect_claim"] for r in self.strata))
        self.assertTrue(all(r["analysis_role"] == "ROUTER_SELECTED_OR_MECHANISM_STRATIFIED_EXPLORATORY" and len(r["contrasts"]) == 8 for r in self.strata))
        self.assertTrue(all(not any("p_value" in k or "bootstrap" in k for k in c) for r in self.strata for c in r["contrasts"]))

    def test_37_frozen_mechanism_and_usage_synthesis_reproduces(self):
        self.assertTrue(self.mechanism_rebuilt == self.mechanism, "Mechanism/usage synthesis did not reproduce")
        self.assertTrue(csv_bytes(self.mechanism_csv_rows) == (HERE / "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.csv").read_bytes())

    def test_38_all_registered_metrics_and_missing_sources_explicit(self):
        coverage = self.mechanism["predeclared_metric_coverage"]
        names = {x for key, values in self.sources["mode_registry"]["evaluation_contract"].items() if key.endswith("_metrics") for x in values}
        self.assertEqual(len(names), 26)
        self.assertEqual(len(coverage), 234)
        self.assertTrue(all({r["metric"] for r in coverage if r["mode_id"] == m} == names for m in self.plan["mode_identities"]))
        missing = [r for r in coverage if r["status"] == "NOT_EVALUABLE_SOURCE_NOT_AVAILABLE"]
        self.assertTrue(missing and all(r["value"] is None and r["reason"] for r in missing))

    def test_39_all_forced_off_outputs_and_activation_masks(self):
        for kind, key in [("rag", "rag"), ("memory", "memory"), ("planner", "planning")]:
            rows = self.sources[kind]
            self.assertEqual(len(rows), 558)
            self.assertTrue(all(r["activation"] or r["result"] is None for r in rows), "Inactive module contains a result")
        self.assertEqual(sum(r["rag_active"] for r in self.table), 84)
        self.assertEqual(sum(r["memory_active"] for r in self.table), 76)
        self.assertEqual(sum(r["planning_active"] for r in self.table), 60)
        self.assertTrue(all(r["target_memory_write_count"] == 0 for r in self.table))

    def test_40_actual_and_counterfactual_provider_usage_distinguished(self):
        usage = self.mechanism["actual_and_counterfactual_usage"]
        self.assertEqual(usage["final_response_generation"]["canonical_responses"], 147)
        self.assertEqual(usage["final_response_generation"]["physical_attempts"], 149)
        self.assertEqual(usage["judge_evaluation_overhead"]["canonical_result_requests"], 149)
        self.assertEqual(usage["judge_evaluation_overhead"]["condition_usage_multiplier"], 1)
        self.assertEqual(usage["judge_evaluation_overhead"]["physical_attempts_started"], 213)
        self.assertEqual(usage["counterfactual_558_individual_interactions"]["generator_calls"], 558)
        self.assertEqual(usage["counterfactual_558_individual_interactions"]["judge_calls"], 0)
        self.assertEqual(usage["counterfactual_558_individual_interactions"]["total_tokens"], 526587)
        self.assertFalse(usage["superseded_g2_generation"]["included_in_final_responses_or_scores"])

    def test_41_unknown_usage_cost_and_timing_not_imputed(self):
        usage = self.mechanism["actual_and_counterfactual_usage"]
        self.assertEqual(usage["cost_status"], "COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY")
        self.assertIsNone(usage["exact_monetary_cost"])
        self.assertFalse(usage["judge_evaluation_overhead"]["unknown_usage_imputed"])
        self.assertEqual(usage["judge_evaluation_overhead"]["unknown_completion_and_billing_attempts"], 3)
        self.assertTrue(all(r["status"] == "NOT_EVALUABLE_SOURCE_NOT_AVAILABLE" for r in self.mechanism["predeclared_metric_coverage"] if r["metric"] == "END_TO_END_LATENCY_MS"))
        self.assertTrue(all(r["rag_retrieval_computation_count"] is None and r["rag_cache_hit_count"] is None for r in self.mechanism["modes"] if r["rag_activation_count"]))

    def test_42_human_aggregates_preserved_without_recalibration(self):
        m = read_json(HERE / "F1_FROZEN_MEASUREMENT_SUMMARY_V1.json")
        hh = read_json(F0 / "c4_real_blinded_human_human_agreement_v1.json")
        hl = read_json(F0 / "c4_real_blinded_human_llm_agreement_v1.json")
        self.assertTrue(m["human_human_pooled"] == hh["pooled"])
        self.assertTrue(m["human_llm_pooled"] == hl["pooled_human_observations_vs_llm_judge"]["pooled"])
        self.assertEqual(m["unique_human_visible_items"], 44)
        self.assertEqual(m["human_mode_effects_computed"], 0)
        self.assertEqual(m["judge_calibration_operations"], 0)
        self.assertEqual(m["human_judge_score_averaging_operations"], 0)
        for r in m["criterion_biases"]:
            frozen = hl["pooled_human_observations_vs_llm_judge"]["per_criterion"][r["criterion"].lower()]
            self.assertEqual(r["pooled_judge_minus_human"], frozen["criterion_level_bias_source_b_minus_source_a"])

    def test_43_manuscript_completeness_and_required_limits(self):
        audit = read_json(HERE / "F1_MANUSCRIPT_EVIDENCE_AND_CLAIM_AUDIT_V1.json")
        self.assertEqual(len(audit["required_manuscript_topics"]), 14)
        self.assertTrue(all(audit["required_manuscript_topics"].values()))
        draft = (HERE / "C4_REAL_FINAL_RQ3_MANUSCRIPT_RESULTS_DRAFT.md").read_text()
        for token in ["62 paired", "558", "149", "147", "OVERALL_APPLICABLE_MEAN", "Holm", "Wilcoxon", "rank-biserial", "Human mode effects", "QUALIFIED_PACING_EVIDENCE_LIMITATION", "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT", "do not support claims"]:
            self.assertIn(token, draft)
        self.assertEqual(sha(HERE / "C4_REAL_FINAL_RQ3_MANUSCRIPT_RESULTS_DRAFT.md"), audit["manuscript_sha256"])
        self.assertFalse(any(token in draft for token in ["TODO", "TBD", "INSERT RESULT"]))

    def test_44_figure_source_is_only_bound_aggregate_data(self):
        data = read_json(HERE / figures.DATA_NAME)
        self.assertTrue(data == figures.source_data())
        self.assertTrue(data["aggregate_only"] and not data["raw_condition_or_scenario_identities"])
        self.assertFalse(data["new_statistical_calculations"])
        manifest = read_json(HERE / "F1_FIGURE_EXPORT_MANIFEST_V1.json")
        self.assertEqual(manifest["plotting_script_sha256"], sha(HERE / "build_f1_figures.py"))

    def test_45_all_four_figures_reproduce_in_memory_all_formats(self):
        data = read_json(HERE / figures.DATA_NAME)
        rendered = figures.make_figures(data)
        self.assertEqual(len(rendered), 4)
        evidence = []
        for name, figure in rendered.items():
            exports = figures.export_bytes(figure, name)
            for extension, content in exports.items():
                frozen = (HERE / "figures" / f"{name}.{extension}").read_bytes()
                identical = frozen == content
                record = {"figure": name, "format": extension, "byte_identical": identical,
                          "frozen_sha256": sha_bytes(frozen), "reproduced_sha256": sha_bytes(content)}
                if extension == "tiff":
                    # libtiff may leave one unused alignment byte between the last
                    # compressed strip and the first IFD. Verify actual pixels and
                    # every TIFF tag; normalize only that proven unreferenced byte.
                    def identity(blob):
                        endian = "<" if blob[:2] == b"II" else ">"
                        ifd = struct.unpack_from(endian + "I", blob, 4)[0]
                        with Image.open(io.BytesIO(blob)) as im:
                            end = max(o + n for o, n in zip(im.tag_v2[273], im.tag_v2[279]))
                            self.assertIn(ifd - end, [0, 1])
                            self.assertEqual(ifd % 2, 0)
                            pixels = im.tobytes()
                            result = (im.mode, im.size, {k: str(v) for k, v in im.tag_v2.items()}, pixels)
                        canonical = blob[:end] + b"\x00" * (ifd - end) + blob[ifd:]
                        return result, canonical, end, ifd
                    original, original_bytes, start, stop = identity(frozen)
                    repeated, repeated_bytes, start2, stop2 = identity(content)
                    self.assertTrue(original == repeated, "TIFF pixels or metadata did not reproduce")
                    self.assertTrue(original_bytes == repeated_bytes and (start, stop) == (start2, stop2), "TIFF differs outside proven unused alignment padding")
                    record.update({"pixels_and_all_tags_identical": True, "pixel_sha256": sha_bytes(original[3]),
                                   "alignment_padding_range": [start, stop], "alignment_normalized_bytes_identical": True,
                                   "frozen_file_modified": False})
                else:
                    self.assertTrue(identical, f"Aggregate figure does not reproduce: {name}.{extension}")
                evidence.append(record)
            figures.plt.close(figure)
        type(self).figure_reproduction_evidence = evidence

    def test_46_figure_qa_and_pdf_dependency_disclosure(self):
        qa = read_json(HERE / "F1_FIGURE_VISUAL_QA_V1.json")
        self.assertEqual(qa["figures_reviewed"], 4)
        self.assertEqual(qa["pdf_glyph_audits_passed"], 4)
        self.assertEqual(qa["backend_geometry_audits_passed"], 4)
        self.assertEqual(qa["comparable_panel_alignment_audits_passed"], 1)
        self.assertEqual(qa["pdf_collision_audits_not_auditable"], 4)
        self.assertTrue(all(r["pdf_font_minimum_pt"] >= 5 and not r["pdf_collision_pass_claimed"] for r in qa["figures"]))
        alignment = read_json(HERE / "figures/figure_4_mechanism_outcomes.alignment.json")
        self.assertEqual(alignment["verdict"], "PASS")
        self.assertEqual(alignment["tolerances"]["alignment_pt"], 1.5)

    def test_47_public_files_contain_no_raw_identity_response_or_rationale(self):
        identities = {r[k] for r in self.table for k in ["opaque_condition_id", "scenario_id", "response_blind_id", "corrected_judge_result_id", "corrected_judge_request_id"]}
        raw_text = {r["answer_text"] for r in self.sources["canonical_generation"] if isinstance(r.get("answer_text"), str) and len(r["answer_text"]) >= 40}
        def collect_rationales(obj, active=False):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    collect_rationales(value, active or "rationale" in key.lower())
            elif isinstance(obj, list):
                for value in obj:
                    collect_rationales(value, active)
            elif active and isinstance(obj, str) and len(obj) >= 40:
                raw_text.add(obj)
        for r in self.sources["judge"]:
            collect_rationales(r["parsed_semantic_result"])
        forbidden = [s.encode() for s in identities | raw_text]
        for path in HERE.rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".jsonl", ".csv", ".md", ".txt", ".py", ".svg"}:
                continue
            data = path.read_bytes()
            self.assertFalse(any(value in data for value in forbidden), "Private identity or raw text found in a proposed public artifact")
            self.assertFalse(re.search(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})", data), "Credential-shaped content found")

    def test_48_public_structured_results_have_no_condition_score_records(self):
        forbidden = {"opaque_condition_id", "replay_record_id", "scenario_id", "scenario_family_id", "candidate_response", "answer_text", "rationale", "rationales", "current_query"}
        def audit(obj):
            if isinstance(obj, dict):
                self.assertFalse(forbidden.intersection(obj), "Raw condition/text field in public result")
                for value in obj.values():
                    audit(value)
            elif isinstance(obj, list):
                for value in obj:
                    audit(value)
        for obj in [self.mode, self.primary, self.secondary, self.cohorts, self.strata, self.mechanism]:
            audit(obj)

    def test_49_git_scope_and_no_preexisting_tracked_modifications(self):
        prefix = str(HERE.relative_to(ROOT)) + "/"
        self.assertTrue(all(p.startswith(prefix) for p in git("diff", "--name-only", STARTING_HEAD).splitlines()))
        status = git("status", "--short", "--untracked-files=all").splitlines()
        self.assertTrue(all(line[3:].startswith(prefix) or line[3:] in RETAINED for line in status))
        self.assertFalse(git("diff", "--cached", "--name-only"))
        self.assertFalse(any(p.name in {"__pycache__", ".DS_Store"} for p in HERE.rglob("*")))

    def test_50_review_allowlist_excludes_private_payloads(self):
        allowlist = read_json(HERE / "F1_REVIEW_PACKAGE_ALLOWLIST_V1.json")
        entries = validate_allowlist(allowlist)
        self.assertTrue("C4_REAL_FINAL_RQ3_ANALYSIS_FREEZE_RECEIPT.json" in entries)
        self.assertTrue("F1_UNBLINDING_LEDGER_METADATA_V1.json" in entries)
        self.assertFalse(LEDGER.name in entries)
        self.assertFalse(allowlist["full_project_export"])
        self.assertTrue(all(not (HERE / name).exists() or (HERE / name).resolve().is_relative_to(HERE) for name in entries))

    def test_51_zero_provider_network_judge_human_and_component_execution(self):
        self.assertTrue(all(v == 0 for v in PROHIBITED_ACTION_COUNTS.values()))
        self.assertTrue(all(v == 0 for v in self.entry["prohibited_action_counts"].values()))
        for event in ["socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"]:
            with self.assertRaisesRegex(RuntimeError, "F1_NETWORK_OPERATION_FORBIDDEN"):
                offline_audit(event, ())  # Call the audit hook directly; no socket or network action occurs.
        forbidden_imports = {"openai", "requests", "httpx", "aiohttp", "streamlit", "socket"}
        for path in HERE.glob("*.py"):
            syntax = ast.parse(path.read_text())
            imports = set()
            for node in ast.walk(syntax):
                if isinstance(node, ast.Import):
                    imports.update(n.name.split(".")[0] for n in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
            self.assertFalse(forbidden_imports & imports, "External execution client imported")
        self.assertEqual(self.mechanism["actual_and_counterfactual_usage"]["f1_new_provider_calls"], 0)

    def test_52_csv_json_consistency_and_complete_mode_profiles(self):
        private_header = next(csv.reader(io.StringIO(self.csv_table.decode())))
        self.assertTrue(self.csv_table == csv_bytes(self.table, fields=private_header), "Private CSV differs from frozen JSONL projection")
        self.assertEqual(len(self.mode), 99)
        self.assertTrue(all(r["applicable_score_count"] + r["na_count"] == 62 for r in self.mode))
        for name, rows in [("MODE_SUMMARIES", self.mode), ("PRIMARY_CONTRAST_RESULTS", self.primary), ("SECONDARY_OUTCOME_RESULTS", self.secondary)]:
            raw_csv = (HERE / f"C4_REAL_F1_{name}_V1.csv").read_bytes()
            fields = next(csv.reader(io.StringIO(raw_csv.decode())))
            self.assertTrue(raw_csv == csv_bytes(rows, fields=fields), "Public CSV differs from aggregate JSON")


class MetadataOnlyResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": test.id(), "status": "PASS"})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": test.id(), "status": "FAIL", "exception_type": err[0].__name__})
    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": test.id(), "status": "ERROR", "exception_type": err[0].__name__})


def main():
    assert not (HERE / "F1_TARGETED_TEST_REPORT_V1.json").exists(), "Final successful test report is write-once."
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(F1TargetedTests)
    result = unittest.TextTestRunner(stream=output, verbosity=2, resultclass=MetadataOnlyResult).run(suite)
    passed = sum(r["status"] == "PASS" for r in result.records)
    report = {"schema_version": "F1_TARGETED_TEST_REPORT_V1", "status": "PASS" if result.wasSuccessful() else "FAIL",
        "tests_run": result.testsRun, "passed": passed, "failed": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "tests": result.records, "timestamp_utc": now(),
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__},
        "scope": "Targeted F1 statistics, frozen-source integrity, identity pairing, aggregate figure reproduction and public export privacy only.",
        "source_hashes_checked": 838, "specified_authority_hashes_checked": 17,
        "figure_formats_reproduced_in_memory": 16, "actual_restricted_reads_guarded": True,
        "prohibited_action_counts": PROHIBITED_ACTION_COUNTS,
        "no_test_raw_record_differences_exported": True}
    report["figure_reproduction_evidence"] = getattr(F1TargetedTests, "figure_reproduction_evidence", [])
    report["prior_validation_attempts"] = [{"filename": p.name, "sha256": sha(p),
        **{k: read_json(p)[k] for k in ["passed", "failed", "errors"]}} for p in sorted(HERE.glob("F1_TARGETED_TEST_FAILURE_*.json"))]
    report["resolved_tiff_reproduction_diagnostic"] = {
        "initial_issue": "Strict TIFF byte equality detected one unused libtiff alignment byte in figures 1 and 4; every decoded pixel and TIFF tag was identical.",
        "final_rule": "PDF, SVG and PNG require exact bytes. TIFF additionally requires identical pixels/all tags and identical bytes after normalizing only the proven zero-or-one-byte unused gap between the final compressed strip and first IFD.",
        "scientific_results_or_figure_files_changed": False,
        "sealed_statistical_methods_changed": False}
    if result.wasSuccessful():
        report["tested_file_hashes"] = {str(p.relative_to(HERE)): sha(p) for p in sorted(HERE.rglob("*")) if p.is_file()}
        write_json(HERE / "F1_TARGETED_TEST_REPORT_V1.json", report)
    else:
        index = 1
        while (HERE / f"F1_TARGETED_TEST_FAILURE_{index:02d}.json").exists():
            index += 1
        write_json(HERE / f"F1_TARGETED_TEST_FAILURE_{index:02d}.json", report)
    # Logs contain method names and explicit synthetic/aggregate assertions only.
    print(output.getvalue())
    print(json.dumps({k: report[k] for k in ["status", "tests_run", "passed", "failed", "errors", "skipped"]}))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
