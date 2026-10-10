"""Artifact-only tests for the RQ3-REAL-C4 Track D freeze."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from validate_track_d import (  # noqa: E402
    MODE_LOCKS,
    PRIMARY_COMPARISONS,
    REMOVE_ONE_COMPARISONS,
    validate,
)


class TrackDArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lineage = json.loads((HERE / "dataset_lineage_registry_v1.json").read_text())
        cls.final = json.loads((HERE / "final_62_scenario_identity_v1.json").read_text())
        cls.original = json.loads((HERE / "original_25_subset_identity_v1.json").read_text())
        cls.modes = json.loads((HERE / "c4_real_ablation_mode_registry_v1.json").read_text())
        cls.replay = [
            json.loads(line)
            for line in (HERE / "c4_real_replay_manifest_unexecuted_v1.jsonl").read_text().splitlines()
            if line.strip()
        ]
        with (HERE / "memory_scenario_registry_v1.csv").open(newline="", encoding="utf-8") as handle:
            cls.memory = list(csv.DictReader(handle))
        with (HERE / "memory_extension_writer_packet_v1.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            cls.extensions = list(csv.DictReader(handle))

    def test_full_validator_passes(self) -> None:
        self.assertGreater(validate(), 1000)

    def test_authoritative_lineage_selects_62(self) -> None:
        self.assertEqual(self.lineage["lineage_decision"]["selected"], "C4_REAL_PRIMARY_UNIFIED_DATASET_V1")
        self.assertEqual(self.lineage["versions"]["unified_62"]["overlap_with_57_by_stable_content_identity"], 57)

    def test_57_is_superseded_and_has_no_overlay(self) -> None:
        predecessor = self.lineage["canonical_sources"]["unified_57_predecessor"]
        self.assertEqual(predecessor["record_count"], 57)
        self.assertFalse(predecessor["associated_gold_or_reference_members_present"])
        self.assertEqual(self.lineage["versions"]["unified_57"]["status"], "SUPERSEDED_INCOMPLETE_PREDECESSOR")

    def test_five_additions_are_m008_to_m012(self) -> None:
        additions = self.lineage["versions"]["unified_62"]["additions_relative_to_57"]
        self.assertEqual({row["source_scenario_id"] for row in additions}, {"M008", "M009", "M010", "M011", "M012"})

    def test_final_identity_has_62_unique_rows(self) -> None:
        self.assertEqual(len(self.final["rows"]), 62)
        self.assertEqual(len({row["scenario_id"] for row in self.final["rows"]}), 62)

    def test_original_subset_maps_to_u001_u025(self) -> None:
        self.assertEqual(
            [row["unified_scenario_id"] for row in self.original["rows"]],
            [f"U{i:03d}" for i in range(1, 26)],
        )

    def test_prior_answers_are_excluded(self) -> None:
        exclusion = self.final["prior_output_exclusion"]
        self.assertFalse(exclusion["baseline_reference_response_included"])
        self.assertFalse(exclusion["generated_response_included"])
        self.assertFalse(exclusion["historical_mode_response_included"])

    def test_historical_evaluation_is_not_reported_complete(self) -> None:
        status = self.lineage["final_evaluation_status"]["unified_62"]
        self.assertEqual(status["status"], "HISTORICAL_PARTIAL_EVALUATION_NOT_A_C4_EXECUTION")
        self.assertEqual(status["human_validation"]["completed_score_or_rationale_cell_count"], 0)

    def test_memory_registry_population(self) -> None:
        self.assertEqual(len(self.memory), 15)
        self.assertEqual(sum(row["persistent_replay_eligible"] == "YES" for row in self.memory), 9)

    def test_memory_primary_class_distribution(self) -> None:
        self.assertEqual(
            Counter(row["memory_class"] for row in self.memory),
            Counter(
                {
                    "VISIBLE_HISTORY_ONLY": 5,
                    "SAME_SESSION_WORKING_MEMORY": 3,
                    "ACTIVE_PLAN_STATE": 3,
                    "UPDATE_OR_CORRECTION": 1,
                    "NO_RELEVANT_MEMORY_CONTROL": 3,
                }
            ),
        )

    def test_writer_packet_has_six_blank_human_templates(self) -> None:
        self.assertEqual(len(self.extensions), 6)
        for row in self.extensions:
            self.assertEqual(row["student_writer_setup_text"], "")
            self.assertEqual(row["student_writer_update_text"], "")
            self.assertEqual(row["student_writer_target_text"], "")
            self.assertEqual(row["human_writer_status"], "REQUIRED_NOT_COMPLETED")

    def test_nine_mode_locks(self) -> None:
        self.assertEqual(len(self.modes["modes"]), 9)
        observed = {}
        for mode in self.modes["modes"]:
            lock = mode["condition_lock"]
            observed[mode["mode_id"]] = (
                lock["evidence_synthesis"],
                lock["rag"],
                lock["memory"],
                lock["planning"],
            )
        self.assertEqual(observed, MODE_LOCKS)

    def test_common_add_one_comparisons(self) -> None:
        self.assertEqual(
            [(row["left"], row["right"]) for row in self.modes["frozen_comparisons"]["primary"]],
            PRIMARY_COMPARISONS,
        )

    def test_targeted_remove_one_comparisons(self) -> None:
        self.assertEqual(
            [
                (row["left"], row["right"])
                for row in self.modes["frozen_comparisons"]["targeted_remove_one"]
            ],
            REMOVE_ONE_COMPARISONS,
        )

    def test_evidence_is_common_baseline(self) -> None:
        self.assertIn("common add-one baseline", self.modes["design_principle"])
        self.assertTrue(
            next(row for row in self.modes["modes"] if row["mode_id"] == "C1_EVIDENCE")[
                "condition_lock"
            ]["evidence_synthesis"]
        )

    def test_replay_record_counts(self) -> None:
        self.assertEqual(len(self.replay), 558)
        self.assertEqual(Counter(row["mode_id"] for row in self.replay), Counter({mode: 62 for mode in MODE_LOCKS}))

    def test_all_replay_records_are_unexecuted(self) -> None:
        self.assertEqual(
            {row["execution_status"] for row in self.replay},
            {"UNEXECUTED_NO_RESPONSE_NO_PROVIDER_CALL"},
        )
        self.assertTrue(
            all(all(value == 0 for value in row["track_d_actual_execution_counters"].values()) for row in self.replay)
        )

    def test_primary_inputs_are_identical_across_modes(self) -> None:
        by_scenario = {}
        for row in self.replay:
            by_scenario.setdefault(row["scenario_id"], set()).add(
                json.dumps(row["provider_input"], ensure_ascii=False, sort_keys=True)
            )
        self.assertEqual(len(by_scenario), 62)
        self.assertTrue(all(len(values) == 1 for values in by_scenario.values()))

    def test_persistent_replays_have_explicit_boundary(self) -> None:
        persistent = [row for row in self.replay if row["memory_session_fixture"]["persistent_replay_eligible"]]
        self.assertEqual(len(persistent), 81)
        self.assertTrue(all(row["memory_session_fixture"]["session_boundary"]["required"] for row in persistent))
        self.assertTrue(all(row["provider_input"]["visible_conversation_history"] == [] for row in persistent))

    def test_target_query_is_never_altered(self) -> None:
        by_id = {row["scenario_id"]: row for row in self.final["rows"]}
        for row in self.replay:
            self.assertEqual(row["provider_input"]["current_query"], by_id[row["scenario_id"]]["primary_input"]["student_query"])
            self.assertEqual(row["memory_session_fixture"]["target_query"], row["provider_input"]["current_query"])

    def test_gold_and_evaluation_references_are_not_provider_input(self) -> None:
        forbidden = {"human_gold", "expected_route", "expected_memory", "expected_retrieval", "reference_chunk_ids"}
        self.assertTrue(all(not (set(row["provider_input"]) & forbidden) for row in self.replay))
        self.assertTrue(all(row["evaluation_only_reference"]["excluded_from_provider_input"] for row in self.replay))

    def test_state_reset_is_fail_closed(self) -> None:
        self.assertTrue(all(not row["state_reset"]["cross_record_reuse"] for row in self.replay))
        self.assertTrue(all(not row["state_reset"]["production_commit"] for row in self.replay))

    def test_evaluation_contract_contains_required_outcomes(self) -> None:
        contract = self.modes["evaluation_contract"]
        self.assertEqual(contract["primary_aggregate"]["name"], "OVERALL_APPLICABLE_MEAN")
        self.assertIn("EVIDENCE_FAITHFULNESS", contract["secondary_response_outcomes"])
        self.assertIn("UNSUPPORTED_CLAIM_COUNT", contract["secondary_response_outcomes"])
        self.assertTrue(contract["retrieval_metrics"])
        self.assertTrue(contract["memory_metrics"])
        self.assertTrue(contract["planner_metrics"])
        self.assertTrue(contract["efficiency_metrics"])

    def test_hard_stop_counters_are_zero(self) -> None:
        self.assertTrue(all(value == 0 for value in self.lineage["execution_boundary"].values()))


if __name__ == "__main__":
    unittest.main()
