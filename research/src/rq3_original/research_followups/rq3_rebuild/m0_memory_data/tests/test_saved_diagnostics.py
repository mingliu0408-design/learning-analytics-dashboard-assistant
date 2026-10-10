"""Standalone readback of saved diagnostic evidence; does not rerun retrieval."""
import csv
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from common import OWNED

class SavedDiagnosticsTests(unittest.TestCase):
    def test_22_required_fact_misses_remain_in_table(self):
        rows = list(csv.DictReader((OWNED / "diagnostics_v2/MEMORY_FIXTURE_DIAGNOSTIC.csv").open()))
        for r in rows:
            missing = set(json.loads(r["expected_fact_ids"])) - set(json.loads(r["retrieved_fact_ids"]))
            self.assertEqual(missing, set(json.loads(r["missing_fact_ids"])))
            if missing: self.assertNotEqual(r["coverage_status"], "COMPLETE")
            self.assertEqual(r["target_state_writes"], "0")
            if r["condition"] == "GATE_OFF_STUB":
                self.assertEqual(r["retriever_calls"], "0")
                self.assertEqual(r["status"], "NOT_ACTIVATED")

    def test_23_unavailable_semantics_not_labelled_hybrid_success(self):
        identity = json.loads((OWNED / "diagnostics_v2/RUNTIME_IDENTITY.json").read_text())
        rows = list(csv.DictReader((OWNED / "diagnostics_v2/MEMORY_FIXTURE_DIAGNOSTIC.csv").open()))
        if identity["status"] == "NOT_RUN":
            self.assertEqual(identity["semantic_target_count"], 0)
            self.assertTrue(all(r["semantic_mode"] == "LEXICAL_ONLY_SEMANTIC_NOT_RUN" for r in rows))

    def test_24_receipts_and_target_state_hashes_read_back(self):
        receipts = [json.loads(x) for x in (OWNED / "diagnostics_v2/MEMORY_SETUP_AND_REOPEN_RECEIPTS.jsonl").read_text().splitlines()]
        traces = [json.loads(x) for x in (OWNED / "diagnostics_v2/MEMORY_TARGET_TRACES.jsonl").read_text().splitlines()]
        self.assertTrue(receipts and traces)
        for r in receipts:
            if "same_state" in r: self.assertTrue(r["same_state"])
            if "integrity" in r: self.assertEqual(r["integrity"]["integrity_check"], "ok")
        for t in traces:
            r = t["read"]
            self.assertEqual(r["before_logical_sha256"], r["after_logical_sha256"])

if __name__ == "__main__": unittest.main()
