"""Research-only governance and determinism tests for LR-2."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pair_schema import deterministic_pair_id, validate_pair


def read_jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line]


class LR2PairDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train = read_jsonl("../lr1/ranker_train_manifest_candidate_v1.jsonl")
        cls.dev = read_jsonl("../lr1r/ranker_dev_manifest_candidate_v2.jsonl")
        cls.positive = read_jsonl("ranker_positive_pair_candidates_v1.jsonl")
        cls.safe = read_jsonl("ranker_safe_negative_pair_candidates_v1.jsonl")
        cls.hard = read_jsonl("ranker_hard_negative_candidates_v1.jsonl")
        cls.baseline = read_jsonl("ranker_pair_dataset_baseline_candidate_v1.jsonl")
        cls.universe = set(json.loads((HERE / "lr2_label_universe_v1.json").read_text())["included_labels"])
        cls.train_ids = {row["record_id"] for row in cls.train}
        cls.dev_ids = {row["record_id"] for row in cls.dev}
        policy = json.loads((HERE / "../lr1r/ranker_negative_pair_policy_candidate_v1.json").read_text())
        cls.blocked = {tuple(sorted((r["label_a"], r["label_b"]))) for r in policy["relationships"] if r["relationship_class"] == "BLOCKED_WITHOUT_REVIEW"}

    def test_no_self_pairs_and_target_semantics(self):
        for row in self.positive + self.safe + self.hard + self.baseline:
            self.assertNotEqual(row["anchor_record_id"], row["candidate_record_id"])
            validate_pair(row, baseline=row in self.baseline)
            self.assertEqual(row["target"] == 1, row["anchor_intent"] == row["candidate_intent"])

    def test_baseline_negative_policy_and_pool_isolation(self):
        hard_ids = {row["pair_id"] for row in self.hard}
        for row in self.baseline:
            self.assertNotIn(row["pair_id"], hard_ids)
            if row["target"] == 0:
                self.assertEqual(row["relationship_class"], "SAFE_RANDOM_NEGATIVE")
                self.assertNotIn(tuple(sorted((row["anchor_intent"], row["candidate_intent"]))), self.blocked)

    def test_train_resolution_dev_exclusion_and_universe(self):
        for row in self.positive + self.safe + self.hard + self.baseline:
            self.assertIn(row["anchor_record_id"], self.train_ids)
            self.assertIn(row["candidate_record_id"], self.train_ids)
            self.assertNotIn(row["anchor_record_id"], self.dev_ids)
            self.assertNotIn(row["candidate_record_id"], self.dev_ids)
            self.assertIn(row["anchor_intent"], self.universe)
            self.assertIn(row["candidate_intent"], self.universe)

    def test_pair_ids_are_deterministic(self):
        for row in self.positive + self.safe + self.hard + self.baseline:
            self.assertEqual(row["pair_id"], deterministic_pair_id(row))

    def test_source_and_output_hashes_match(self):
        for manifest, base in [
            (HERE / "../lr1/LR1_OUTPUT_HASHES.sha256", HERE / "../lr1"),
            (HERE / "../lr1r/lr1r_output_checksums_v1.sha256", HERE / "../lr1r"),
            (HERE / "lr2_output_checksums_v1.sha256", HERE),
        ]:
            for line in manifest.read_text().splitlines():
                digest, relative = line.split(None, 1)
                path = base / relative.strip().lstrip("*")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_protected_lr1_lr1r_and_production_snapshots_match(self):
        report = json.loads((HERE / "lr2_pair_validation_report_v1.json").read_text())
        self.assertTrue(report["protected_files_unchanged"])
        self.assertEqual(report["protected_snapshot_before"], report["protected_snapshot_after"])

    def test_byte_identical_reconstruction(self):
        result = subprocess.run(
            [sys.executable, str(HERE / "build_pair_dataset.py"), "--check"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BYTE_IDENTICAL_RERUN_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
