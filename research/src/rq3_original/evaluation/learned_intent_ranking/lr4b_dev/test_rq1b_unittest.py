"""Standard-library regression suite for all frozen RQ1-B gates."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from transformers import AutoTokenizer

from . import (
    HERE,
    LOCAL_MODEL_RELATIVE,
    ROOT,
    SAFE_JSON_FILENAMES,
    SCENARIO_COUNTS,
    SCENARIO_ORDER,
    STARTING_HEAD,
    TRAINING_SEEDS,
    VIEW_A,
)
from .finalise_rq1b_results import RUN_BUNDLE_PATH, build_artifacts
from .governed_data_loader import (
    FinalGoldBoundaryError,
    load_governed_bundle,
    reject_final_gold_path,
    sha256_file,
    verify_protected_sources_unchanged,
)
from .model import EXPECTED_TRAINABLE_PARAMETERS, build_m64_model
from .pair_builder import build_all_scenario_pair_inputs, generate_epoch_pairs
from .token_budget import truncate_previous_turns_oldest_edge
from .validate_rq1b_results import (
    scan_for_governed_text,
    verify_local_artifact_boundaries,
    verify_output_checksums,
)


class RQ1BContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_governed_bundle()
        cls.pairs = build_all_scenario_pair_inputs(cls.bundle)
        cls.run_bundle = json.loads(RUN_BUNDLE_PATH.read_text(encoding="utf-8"))
        cls.outputs = {
            name: json.loads((HERE / name).read_text(encoding="utf-8"))
            for name in SAFE_JSON_FILENAMES
        }

    def test_01_starting_head_and_contract_hashes(self) -> None:
        self.assertEqual(self.run_bundle["starting_state"]["starting_head"], STARTING_HEAD)
        self.assertTrue(self.run_bundle["input_contract"]["all_hashes_match"])
        self.assertEqual(
            self.run_bundle["input_contract"]["contract_schema"],
            "lr4b-experiment-contract-v1.1",
        )

    def test_02_final_gold_rejected_before_filesystem_access(self) -> None:
        with patch.object(Path, "stat") as stat_call, patch.object(Path, "open") as open_call:
            with self.assertRaises(FinalGoldBoundaryError):
                reject_final_gold_path(
                    "evaluation/learned_intent_ranking/lr1r/primary_v3_input/opaque"
                )
            stat_call.assert_not_called()
            open_call.assert_not_called()

    def test_03_tokenizer_and_model_local_only(self) -> None:
        runtime = self.outputs["rq1b_runtime_preflight_v1.json"]
        self.assertTrue(runtime["local_files_only"])
        self.assertTrue(runtime["network_access_disabled"])
        self.assertEqual(runtime["network_attempt_count"], 0)
        self.assertEqual(runtime["model"]["local_path"], LOCAL_MODEL_RELATIVE.as_posix())

    def test_04_mpnet_frozen_and_optimizer_exclusion(self) -> None:
        model = self.outputs["rq1b_runtime_preflight_v1.json"]["model"]
        self.assertEqual(model["trainable_parameter_count"], 0)
        self.assertEqual(model["parameters_in_optimizer"], 0)
        self.assertEqual(sum(p.numel() for p in build_m64_model().parameters()), EXPECTED_TRAINABLE_PARAMETERS)

    def test_05_actual_token_counts_and_zero_truncation(self) -> None:
        report = self.outputs["rq1b_token_budget_summary_v1.json"]
        self.assertEqual(report["logical_record_counts"], {
            "approved_candidate": 62,
            "dev_query": 84,
            "governed_train": 318,
            "total": 464,
        })
        self.assertEqual(report["actual_over_384_count"], 0)
        self.assertEqual(report["actual_truncation_count"], 0)

    def test_06_synthetic_oldest_edge_truncation(self) -> None:
        tokenizer = AutoTokenizer.from_pretrained(
            str(ROOT / LOCAL_MODEL_RELATIVE), local_files_only=True
        )
        previous = [f"turn {index} " + "token " * 45 for index in range(14)]
        result = truncate_previous_turns_oldest_edge(
            tokenizer,
            question_anchor="immutable synthetic anchor",
            previous_turns=previous,
            current_student_utterance="immutable synthetic current utterance",
        )
        self.assertGreater(result["removed_previous_turn_count"], 0)
        self.assertLessEqual(result["final_token_count"], 384)
        self.assertEqual(
            result["retained_previous_turns"],
            tuple(previous[result["removed_previous_turn_count"] :]),
        )
        self.assertTrue(result["current_student_utterance_preserved"])
        self.assertTrue(result["question_anchor_preserved"])
        self.assertTrue(result["headers_preserved"])

    def test_07_representation_ledger_fingerprint(self) -> None:
        self.assertEqual(
            self.run_bundle["representation_ledger_fingerprint"],
            "d33d9badd56edca675c48d865dbec5a0d19f2b9e6328e785243dd7cef3317007",
        )

    def test_08_candidate_universe_and_eedi_exclusion(self) -> None:
        identity = self.run_bundle["frozen_evaluation_identity"]
        self.assertEqual(identity["candidate_example_count"], 62)
        self.assertEqual(identity["candidate_label_count"], 16)
        self.assertEqual(identity["eedi_candidate_count"], 0)
        self.assertEqual(identity["aggregation"], "MAX")

    def test_09_frozen_dev_views(self) -> None:
        self.assertEqual(
            self.run_bundle["frozen_evaluation_identity"]["view_counts"],
            {
                "VIEW_A_PAIRWISE_SEEN": 79,
                "VIEW_B_SINGLETON_UNSEEN": 5,
                "VIEW_C_MIXED": 84,
            },
        )

    def test_10_scenario_membership_and_duplicates_retained(self) -> None:
        self.assertEqual(
            {name: len(ids) for name, ids in self.bundle["scenario_ids"].items()},
            SCENARIO_COUNTS,
        )
        sets = [set(self.bundle["scenario_ids"][name]) for name in SCENARIO_ORDER]
        self.assertTrue(sets[0] < sets[1] < sets[2] < sets[3])
        concentration = self.outputs["rq1b_data_concentration_v1.json"]
        self.assertTrue(concentration["duplicates_retained"])
        self.assertEqual(concentration["governed_duplicate_extra_row_count"], 21)

    def test_11_positive_safe_negative_and_d0_policy(self) -> None:
        for sampler in self.pairs["samplers"].values():
            epoch = generate_epoch_pairs(sampler, 0)
            self.assertTrue(all(row["target"] == 1 for row in sampler["positive_pool"]))
            self.assertTrue(
                all(row["relationship_class"] == "SAFE_RANDOM_NEGATIVE" for row in sampler["negative_pool"])
            )
            self.assertTrue(all(row["anchor_record_id"] != row["candidate_record_id"] for row in epoch))
        audit = self.outputs["rq1b_pair_construction_audit_v1.json"]
        for row in audit["scenarios"].values():
            self.assertEqual(row["hard_negative_selected_count"], 0)
            self.assertEqual(row["blocked_relationship_selected_count"], 0)
            self.assertEqual(row["unique_row_weight_values"], [1.0])

    def test_12_pair_sampling_determinism_and_v0_parity(self) -> None:
        for sampler in self.pairs["samplers"].values():
            self.assertEqual(generate_epoch_pairs(sampler, 3), generate_epoch_pairs(sampler, 3))
        self.assertEqual(
            self.outputs["rq1b_pair_construction_audit_v1.json"][
                "v0_lr2r_epoch_identity_parity_count"
            ],
            50,
        )

    def test_13_c0_and_v0_reproduction(self) -> None:
        self.assertEqual(self.outputs["rq1b_c0_reproduction_v1.json"]["status"], "PASS")
        self.assertEqual(
            self.outputs["rq1b_c0_reproduction_v1.json"]["view_a_ranking_identity_match_count"],
            79,
        )
        self.assertEqual(self.outputs["rq1b_v0_reproduction_v1.json"]["status"], "PASS")
        self.assertTrue(
            all(row["pass"] for row in self.outputs["rq1b_v0_reproduction_v1.json"]["per_seed_parity"])
        )

    def test_14_complete_20_run_matrix(self) -> None:
        expected = {(scenario, seed) for scenario in SCENARIO_ORDER for seed in TRAINING_SEEDS}
        actual = {(row["scenario"], row["seed"]) for row in self.run_bundle["runs"]}
        self.assertEqual(self.run_bundle["run_count"], 20)
        self.assertEqual(actual, expected)

    def test_15_scenario_selection_rule(self) -> None:
        selection = self.outputs["rq1b_scenario_selection_v1.json"]
        traces = selection["selection_criterion_trace"]
        ordered = sorted(
            traces,
            key=lambda row: (
                -row["five_seed_mean_view_a_mrr"],
                -row["five_seed_mean_view_a_top1"],
                -row["five_seed_mean_view_a_macro_f1"],
                row["five_seed_view_a_mrr_population_std"],
                row["anchor_count"],
            ),
        )
        self.assertEqual(selection["selected_scenario"], ordered[0]["scenario"])
        self.assertFalse(selection["view_b_used"])
        self.assertFalse(selection["view_c_used"])

    def test_16_representative_seed_rule(self) -> None:
        manifest = self.outputs["rq1b_representative_checkpoint_manifest_v1.json"]
        trace = manifest["tie_break_trace"]
        selected = min(
            trace,
            key=lambda row: (
                row["absolute_distance_to_five_seed_mean_view_a_mrr"],
                -row["view_a_top1"],
                -row["view_a_macro_f1"],
                row["seed"],
            ),
        )
        self.assertEqual(manifest["representative_seed"], selected["seed"])
        self.assertTrue(manifest["selected_before_final_gold"])

    def test_17_local_checkpoint_and_embedding_are_ignored(self) -> None:
        boundary = verify_local_artifact_boundaries()
        self.assertTrue(boundary["all_ignored"])
        self.assertEqual(boundary["tracked_file_count"], 0)

    def test_18_tracked_outputs_contain_no_governed_text(self) -> None:
        result = scan_for_governed_text(self.bundle)
        self.assertEqual(result["governed_text_leak_count"], 0)

    def test_19_finalisation_is_byte_identical(self) -> None:
        first = build_artifacts(self.run_bundle)
        second = build_artifacts(self.run_bundle)
        self.assertEqual(first, second)
        for path, content in first.items():
            self.assertEqual(path.read_bytes(), content)

    def test_20_protected_sources_unchanged_and_checksums(self) -> None:
        self.assertTrue(verify_protected_sources_unchanged()["protected_sources_unchanged"])
        self.assertTrue(verify_output_checksums()["all_match"])


if __name__ == "__main__":
    unittest.main()
