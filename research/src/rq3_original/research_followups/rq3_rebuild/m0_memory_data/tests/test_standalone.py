"""Only Python standard library; can run from the extracted review package."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from common import OWNED, disable_network
from fixture_validation import validate_fixtures, assert_runtime_separation, coverage

class StandaloneTests(unittest.TestCase):
    def test_01_frozen_fixture_hashes_and_labels(self):
        runtime, evaluation = validate_fixtures()
        self.assertEqual(len(runtime), 16)

    def test_02_hidden_field_injection_rejected(self):
        with self.assertRaises(AssertionError):
            assert_runtime_separation({"target": {"expected_fact_ids": ["secret"]}})

    def test_03_blank_human_fields_are_unfilled(self):
        t = json.loads((OWNED / "EMPTY_MEMORY_EPISODE_TEMPLATE.json").read_text())
        self.assertEqual(t["runtime"]["target"]["query"], "")
        self.assertEqual(t["runtime"]["source_turns"], [])
        self.assertIsNone(t["evaluation_only"]["persistent_retrieval_needed"])
        for k in ("human_answers", "human_target_utterance", "writer_signature", "reviewer_signature", "planned_split"):
            self.assertEqual(t["evaluation_only"][k], "")

    def test_04_partial_bundle_is_not_complete(self):
        self.assertEqual(coverage(["goal", "time", "plan"], ["plan"]), ("PARTIAL", ["goal", "time"]))

    def test_05_miss_and_not_run_are_distinct(self):
        self.assertEqual(coverage(["goal"], ["unrelated"]), ("MISS", ["goal"]))
        self.assertEqual(coverage(["goal"], [], ran=False), ("NOT_RUN", ["goal"]))

    def test_06_ambiguous_selection_does_not_imply_success(self):
        self.assertEqual(coverage([], ["plan-a", "plan-b"], clarification=True)[0],
            "AMBIGUOUS_OR_UNSUPPORTED_REQUIRES_CLARIFICATION")

    def test_07_missing_source_still_needs_history(self):
        _, ev = validate_fixtures()
        self.assertTrue(ev["SYN-M0-07"]["persistent_retrieval_needed"])
        self.assertEqual(ev["SYN-M0-07"]["expected_stored_fact_ids"], [])

    def test_08_network_guard_is_enforced(self):
        disable_network()
        import socket
        with self.assertRaisesRegex(RuntimeError, "M0_NETWORK_DISABLED"):
            socket.getaddrinfo("example.invalid", 443)

if __name__ == "__main__": unittest.main()
