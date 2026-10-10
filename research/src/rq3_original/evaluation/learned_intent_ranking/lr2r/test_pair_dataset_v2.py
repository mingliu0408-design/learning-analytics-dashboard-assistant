"""Research-only validation tests for the LR-2R exposure repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read_jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line]


class LR2RExposureRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = json.loads((HERE / "lr2r_label_universe_v1.json").read_text())
        cls.singletons = json.loads((HERE / "lr2r_singleton_exclusion_manifest_v1.json").read_text())
        cls.spec = json.loads((HERE / "lr2r_episodic_sampling_spec_v1.json").read_text())
        cls.baseline = read_jsonl("ranker_pair_dataset_baseline_candidate_v2.jsonl")
        cls.views = json.loads((HERE / "ranker_dev_evaluation_views_v1.json").read_text())
        cls.validation = json.loads((HERE / "lr2r_validation_report_v1.json").read_text())
        cls.singleton_ids = {row["record_id"] for row in cls.singletons["records"]}
        cls.singleton_labels = set(cls.universe["singleton_retrieval_only_universe"]["labels"])
        cls.pairwise_labels = set(cls.universe["pairwise_training_universe"]["labels"])

    def test_frozen_universe_and_singletons(self):
        self.assertEqual(self.universe["production_retrieval_universe"]["label_count"], 16)
        self.assertEqual(self.universe["pairwise_training_universe"]["label_count"], 12)
        self.assertEqual(len(self.singleton_labels), 4)
        self.assertFalse(self.singleton_labels & self.pairwise_labels)
        self.assertFalse(self.universe["future_lr3_pair_artifact_authority"]["lr3_training_authorised"])

    def test_no_singleton_in_any_pairwise_role(self):
        for row in self.baseline:
            self.assertNotIn(row["anchor_record_id"], self.singleton_ids)
            self.assertNotIn(row["candidate_record_id"], self.singleton_ids)
            self.assertNotIn(row["anchor_intent"], self.singleton_labels)
            self.assertNotIn(row["candidate_intent"], self.singleton_labels)
            self.assertIn(row["anchor_intent"], self.pairwise_labels)
            self.assertIn(row["candidate_intent"], self.pairwise_labels)

    def test_baseline_balance_and_policy(self):
        self.assertEqual(len(self.baseline), 228)
        self.assertEqual(Counter(row["target"] for row in self.baseline), {0: 114, 1: 114})
        self.assertFalse(any(row["anchor_record_id"] == row["candidate_record_id"] for row in self.baseline))
        self.assertTrue(all(row["relationship_class"] == "SAFE_RANDOM_NEGATIVE" for row in self.baseline if row["target"] == 0))
        self.assertTrue(all(row["governance_status"] == "CANDIDATE_FOR_LR3_TRAINING_AFTER_LR2R_REVIEW" for row in self.baseline))

    def test_production_retrieval_records_retained(self):
        self.assertEqual(self.singletons["singleton_record_count"], 4)
        self.assertTrue(all(row["present_in_production_mpnet_retrieval_index"] for row in self.singletons["records"]))
        self.assertTrue(all(set(row["pairwise_training_roles"].values()) == {"PROHIBITED"} for row in self.singletons["records"]))

    def test_dev_views(self):
        views = self.views["views"]
        self.assertEqual(views["pairwise_seen_labels"]["label_count"], 8)
        self.assertEqual(views["pairwise_seen_labels"]["record_count"], 79)
        self.assertEqual(views["singleton_unseen_labels"]["label_count"], 4)
        self.assertEqual(views["singleton_unseen_labels"]["record_count"], 5)
        self.assertEqual(views["unsupported_by_dev_labels"]["label_count"], 7)

    def test_rotation_and_protected_freeze(self):
        rotation = self.spec["rotation_verification"]
        self.assertTrue(all(value > 0 for value in rotation.values()))
        self.assertEqual(self.validation["overall_status"], "PASS")
        self.assertTrue(self.validation["protected_files_unchanged"])
        self.assertEqual(self.validation["protected_snapshot_before"], self.validation["protected_snapshot_after"])
        for epoch in ["baseline_v2", "epoch_1_preview", "epoch_2_preview"]:
            self.assertEqual(self.validation[epoch]["singleton_record_reference_count"], 0)

    def test_checksums(self):
        for line in (HERE / "lr2r_output_checksums_v1.sha256").read_text().splitlines():
            expected, relative = line.split(None, 1)
            path = HERE / relative.strip()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_byte_identical_rebuild(self):
        result = subprocess.run(
            [sys.executable, "-B", str(HERE / "build_pair_dataset_v2.py"), "--check"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BYTE_IDENTICAL_LR2R_REBUILD_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
