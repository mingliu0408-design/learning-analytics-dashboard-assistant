"""Deterministic tests for the RQ2-V2 Stage 4-0 DEV protocol freeze."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import unittest

from . import (
    ANSWER_SIGNATURES,
    DEV_ALLOWED_MEMBERS,
    DEV_RELEASE_SHA256,
    FOLD_IDS,
    LAD_PAGES,
    MODEL_IDS,
    PACKAGE_ROOT,
    READY_STATUS,
    STAGE3C_RELEASE_SHA256,
)
from .build_dev_protocol import (
    DEFAULT_DEV_ZIP,
    DEFAULT_STAGE3C_ZIP,
    FOLD_FIELDS,
    GROUP_FIELDS,
    REVIEW_ARCHIVE_FILES,
    build_components,
    build_families,
    rebuild_cv_artifacts_from_frozen_files,
    sha256_file,
)
from .protocol_contract import project_model_features
from .validate_dev_protocol import validate_protocol


def _csv_rows(name: str) -> list[dict[str, str]]:
    with (PACKAGE_ROOT / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class Stage4DevProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dev_rows = _csv_rows("dev_capability_gold_v1.csv")
        cls.group_rows = _csv_rows("dev_atomic_group_map_v1.csv")
        cls.fold_rows = _csv_rows("dev_cv_folds_v1.csv")
        cls.families = build_families(cls.dev_rows, cls.group_rows)
        cls.components = build_components(cls.families)
        cls.protocol = json.loads(
            (PACKAGE_ROOT / "stage4_dev_protocol_v1.json").read_text(encoding="utf-8")
        )

    def test_01_dev_source_hash(self) -> None:
        self.assertEqual(self.protocol["dev_source"]["sha256"], DEV_RELEASE_SHA256)
        if DEFAULT_DEV_ZIP.is_file():
            self.assertEqual(sha256_file(DEFAULT_DEV_ZIP), DEV_RELEASE_SHA256)

    def test_02_stage3c_source_hash(self) -> None:
        manifest = json.loads(
            (PACKAGE_ROOT / "DEV_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["grouping_metadata_source"]["sha256"], STAGE3C_RELEASE_SHA256
        )
        if DEFAULT_STAGE3C_ZIP.is_file():
            self.assertEqual(sha256_file(DEFAULT_STAGE3C_ZIP), STAGE3C_RELEASE_SHA256)

    def test_03_dev_counts(self) -> None:
        self.assertEqual(len(self.dev_rows), 72)
        family_counts = Counter(row["scenario_family_id"] for row in self.dev_rows)
        self.assertEqual(len(family_counts), 36)
        self.assertEqual(set(family_counts.values()), {2})

    def test_04_dev_dialogue_action_counts(self) -> None:
        self.assertEqual(
            Counter(row["final_dialogue_action"] for row in self.dev_rows),
            Counter({"ANSWER": 64, "CLARIFY": 8}),
        )

    def test_05_dev_identifiers_and_family_utterances_are_unique(self) -> None:
        self.assertEqual(len({row["annotation_case_id"] for row in self.dev_rows}), 72)
        manifest = json.loads(
            (PACKAGE_ROOT / "DEV_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["verified_dev_structure"]["duplicate_family_utterance_combinations"],
            0,
        )

    def test_06_visible_history_and_final_labels(self) -> None:
        for row in self.dev_rows:
            history = json.loads(row["visible_conversation_history"])
            self.assertIsInstance(history, list)
            if row["final_dialogue_action"] == "CLARIFY":
                self.assertEqual(
                    {
                        row["final_rag_required"],
                        row["final_memory_required"],
                        row["final_planning_required"],
                    },
                    {"NOT_APPLICABLE"},
                )
            else:
                self.assertTrue(
                    {
                        row["final_rag_required"],
                        row["final_memory_required"],
                        row["final_planning_required"],
                    }
                    <= {"YES", "NO"}
                )

    def test_07_atomic_component_counts(self) -> None:
        self.assertEqual(len(self.components), 24)
        self.assertEqual(
            Counter(component.family_count for component in self.components),
            Counter({1: 12, 2: 12}),
        )

    def test_08_atomic_fold_isolation(self) -> None:
        validation_folds: dict[str, set[str]] = defaultdict(set)
        family_folds: dict[str, set[str]] = defaultdict(set)
        for row in self.fold_rows:
            if row["fold_role"] == "VALIDATION":
                validation_folds[row["dev_atomic_component_id"]].add(row["fold_id"])
                family_folds[row["scenario_family_id"]].add(row["fold_id"])
        self.assertTrue(all(len(values) == 1 for values in validation_folds.values()))
        self.assertTrue(all(len(values) == 1 for values in family_folds.values()))

    def test_09_validation_fold_sizes(self) -> None:
        for fold_id in FOLD_IDS:
            rows = [
                row
                for row in self.fold_rows
                if row["fold_id"] == fold_id and row["fold_role"] == "VALIDATION"
            ]
            self.assertEqual(len(rows), 18)
            self.assertEqual(len({row["scenario_family_id"] for row in rows}), 9)

    def test_10_one_clarify_family_per_fold(self) -> None:
        for fold_id in FOLD_IDS:
            families = {
                row["scenario_family_id"]
                for row in self.fold_rows
                if row["fold_id"] == fold_id
                and row["fold_role"] == "VALIDATION"
                and row["final_dialogue_action"] == "CLARIFY"
            }
            self.assertEqual(len(families), 1)

    def test_11_validation_label_positive_negative_coverage(self) -> None:
        for fold_id in FOLD_IDS:
            answer_rows = [
                row
                for row in self.fold_rows
                if row["fold_id"] == fold_id
                and row["fold_role"] == "VALIDATION"
                and row["final_dialogue_action"] == "ANSWER"
            ]
            for bit in range(3):
                self.assertEqual(
                    {row["final_routing_signature"][bit] for row in answer_rows},
                    {"0", "1"},
                )

    def test_12_training_complements_have_all_answer_signatures(self) -> None:
        for fold_id in FOLD_IDS:
            signatures = {
                row["final_routing_signature"]
                for row in self.fold_rows
                if row["fold_id"] == fold_id
                and row["fold_role"] == "TRAINING"
                and row["final_dialogue_action"] == "ANSWER"
            }
            self.assertEqual(signatures, set(ANSWER_SIGNATURES))

    def test_13_all_five_lad_pages_are_present(self) -> None:
        for fold_id in FOLD_IDS:
            pages = {
                row["current_page"]
                for row in self.fold_rows
                if row["fold_id"] == fold_id and row["fold_role"] == "VALIDATION"
            }
            self.assertEqual(pages, set(LAD_PAGES))

    def test_14_fixed_seed_byte_identical_folds(self) -> None:
        rebuilt, solution = rebuild_cv_artifacts_from_frozen_files(PACKAGE_ROOT)
        self.assertEqual(solution.objective, (4, 80, 2))
        for name, payload in rebuilt.items():
            self.assertEqual((PACKAGE_ROOT / name).read_bytes(), payload, name)

    def test_15_metric_contract(self) -> None:
        metrics = self.protocol["evaluation_metrics"]
        self.assertEqual(metrics["primary_core_capability_metric"]["name"], "macro_f1")
        self.assertFalse(metrics["performance_calculated_in_stage4_0"])
        self.assertEqual(len(metrics["secondary_core_capability_metrics"]), 12)
        self.assertEqual(len(metrics["shared_clarification_metrics"]), 3)
        self.assertEqual(len(metrics["end_to_end_metrics"]), 2)

    def test_16_tie_break_contract(self) -> None:
        rules = self.protocol["model_selection_tie_breaks"]["ordered_rules"]
        self.assertEqual([rule["rank"] for rule in rules], list(range(1, 8)))
        self.assertEqual(
            [rule["metric"] for rule in rules],
            [
                "macro_f1",
                "exact_capability_set_match",
                "jaccard",
                "under_routing_rate",
                "over_routing_rate",
                "predeclared_simplicity_key",
                "config_id",
            ],
        )
        self.assertFalse(self.protocol["model_selection_tie_breaks"]["test_performance_used"])

    def test_17_model_features_exclude_privileged_metadata(self) -> None:
        row = self.dev_rows[0] | self.group_rows[0] | self.fold_rows[0]
        forbidden = set(self.protocol["feature_contract"]["forbidden_model_features"])
        for model_id in MODEL_IDS:
            projected = project_model_features(row, model_id)
            self.assertFalse(set(projected) & forbidden)
            if model_id == "R2V2-B1_LEGACY_INTENT":
                self.assertEqual(set(projected), {"current_query", "current_page"})
            else:
                self.assertEqual(
                    set(projected),
                    {
                        "current_query",
                        "current_page",
                        "dashboard_context",
                        "visible_conversation_history",
                    },
                )
                self.assertIsInstance(projected["visible_conversation_history"], list)

    def test_18_zero_test_or_restricted_assignment_leakage(self) -> None:
        dev_ids = {row["annotation_case_id"] for row in self.dev_rows}
        dev_families = {row["scenario_family_id"] for row in self.dev_rows}
        self.assertEqual({row["partition"] for row in self.dev_rows}, {"DEV"})
        self.assertTrue(
            {row["annotation_case_id"] for row in self.group_rows + self.fold_rows}
            <= dev_ids
        )
        self.assertTrue(
            {row["scenario_family_id"] for row in self.group_rows + self.fold_rows}
            <= dev_families
        )
        self.assertFalse({"partition", "writer_id", "utterance_id"} & set(GROUP_FIELDS))
        self.assertNotIn("partition", FOLD_FIELDS)
        self.assertFalse((PACKAGE_ROOT / "split_assignment_restricted_v1.csv").exists())
        self.assertFalse(any(self.protocol["test_prohibition"].values()))

    def test_19_exact_artifact_allowlist_and_validator(self) -> None:
        self.assertEqual(
            {path.name for path in PACKAGE_ROOT.iterdir() if path.is_file()},
            set(REVIEW_ARCHIVE_FILES),
        )
        self.assertEqual(self.protocol["status"], READY_STATUS)
        checks = validate_protocol(PACKAGE_ROOT)
        self.assertGreaterEqual(len(checks), 35)


if __name__ == "__main__":
    unittest.main()
