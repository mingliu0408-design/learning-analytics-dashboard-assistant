"""Requires inherited frozen utils/c4_memory, not standalone. No semantic encoding.

Explicit storage/control tests use only the newly authored synthetic episodes.
They test boundaries and evidence accounting, not hybrid factual completeness.
"""
import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from common import OWNED, sha, object_sha
from fixture_validation import validate_fixtures
from state_harness import setup_episode, ReadOnlyStore, snapshot, backup_closed, target_read, availability, C4MemoryStore

class InheritedTests(unittest.TestCase):
    def setUp(self):
        self.runtime, self.evaluation = validate_fixtures()
        root = OWNED / ".runtime"
        root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="explicit-mechanics-test-", dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def prepare(self, number):
        r = self.runtime[number - 1]
        dbs, aliases, receipts = setup_episode(r, self.directory / str(number))
        return r, dbs, aliases, receipts

    def test_09_reopen_preserves_stable_learner_across_sessions(self):
        r, dbs, aliases, receipts = self.prepare(1)
        with ReadOnlyStore(next(iter(dbs.values())), clock=lambda: r["target"]["as_of"]) as s:
            records = s.list_active_memories(r["target"]["learner_id"], at=r["target"]["as_of"])
            self.assertEqual({x.memory_id for x in records}, set(aliases.values()))
            self.assertTrue(all(x.source_session_id != r["target"]["session_id"] for x in records))

    def test_10_target_connection_rejects_sql_writes(self):
        r, dbs, _, _ = self.prepare(1)
        p = next(iter(dbs.values())); before = sha(p)
        with ReadOnlyStore(p, clock=lambda: r["target"]["as_of"]) as s:
            with self.assertRaises(sqlite3.OperationalError):
                s._connection.execute("UPDATE memories SET importance=0")
            with self.assertRaises(sqlite3.OperationalError):
                s.set_memory_enabled(r["target"]["learner_id"], False)
        self.assertEqual(sha(p), before)

    def test_11_backup_clones_equal_then_explicit_control_is_isolated(self):
        r, dbs, _, _ = self.prepare(1)
        source = next(iter(dbs.values())); before = sha(source)
        a, b = self.directory / "a.sqlite", self.directory / "b.sqlite"
        backup_closed(source, a); backup_closed(source, b)
        with ReadOnlyStore(a, clock=lambda: r["target"]["as_of"]) as x, ReadOnlyStore(b, clock=lambda: r["target"]["as_of"]) as y:
            self.assertEqual(snapshot(x), snapshot(y))
        # Separate explicit control episode, never part of the diagnostic target read.
        with C4MemoryStore(a) as s:
            s.set_memory_enabled(r["target"]["learner_id"], False, event_at="2026-08-21T10:00:00+00:00")
        with ReadOnlyStore(b, clock=lambda: r["target"]["as_of"]) as s:
            self.assertTrue(s.is_memory_enabled(r["target"]["learner_id"]))
        self.assertEqual(sha(source), before)

    def test_12_gate_off_never_enters_retriever_with_available_store(self):
        r, dbs, aliases, _ = self.prepare(1); p = next(iter(dbs.values()))
        self.assertEqual(availability(p, r["target"], aliases)["active_authorized_count"], 2)
        read = target_read(p, r["target"], None, gate="GATE_OFF_STUB")
        self.assertEqual(read["retriever_calls"], 0)
        self.assertEqual(read["envelope"]["status"], "NOT_ACTIVATED")

    def test_13_disabled_provider_and_tombstone(self):
        for n in (9, 14):
            r, dbs, aliases, _ = self.prepare(n); p = next(iter(dbs.values()))
            self.assertEqual(availability(p, r["target"], aliases)["active_authorized_count"], 0)
            self.assertEqual(target_read(p, r["target"], None, gate="FORCED_ENGINEERING_DIAGNOSTIC")["envelope"]["selected_memory_items"], [])
        with ReadOnlyStore(p, clock=lambda: r["target"]["as_of"]) as s:
            self.assertEqual(s.get_memory(r["target"]["learner_id"], aliases["f14-pref"]).content, "[DELETED]")

    def test_14_supersession_version_and_event_time(self):
        r, dbs, aliases, _ = self.prepare(4)
        with ReadOnlyStore(next(iter(dbs.values())), clock=lambda: r["target"]["as_of"]) as s:
            old = s.get_memory(r["target"]["learner_id"], aliases["f04-old"])
            new = s.get_memory(r["target"]["learner_id"], aliases["f04-new"])
            self.assertEqual(old.status, "SUPERSEDED"); self.assertEqual(new.version, 2)
            self.assertEqual(new.supersedes_memory_id, old.memory_id)
            self.assertEqual(old.valid_to, new.created_at)

    def test_15_course_partition_and_learner_filters(self):
        r, dbs, aliases, _ = self.prepare(11)
        self.assertEqual(len(dbs), 2)
        target = dbs[r["target"]["course_id"]]
        self.assertEqual(availability(target, r["target"], aliases)["active_authorized_fact_ids"], ["f11-maths"])
        r, dbs, aliases, _ = self.prepare(10)
        a = availability(next(iter(dbs.values())), r["target"], aliases)
        self.assertEqual(a["exclusions"]["f10-other"], ["OTHER_LEARNER"])

    def test_16_current_time_excludes_expired_and_future(self):
        r, dbs, aliases, _ = self.prepare(15)
        a = availability(next(iter(dbs.values())), r["target"], aliases)
        self.assertEqual(a["active_authorized_fact_ids"], ["f15-current"])
        self.assertIn("EXPIRED", a["exclusions"]["f15-expired"])
        self.assertIn("FUTURE_VALIDITY", a["exclusions"]["f15-future"])

    def test_17_assistant_and_inference_rejected_by_real_writer(self):
        r, dbs, aliases, receipts = self.prepare(16)
        rejected = {x["fact_id"]: x["outcome"]["reason_code"] for x in receipts if x["event"] == "SETUP_WRITE_POLICY"}
        self.assertEqual(rejected, self.evaluation[r["case_id"]]["expected_write_rejections"])
        self.assertEqual(aliases, {})

    def test_18_visible_history_exclusion_remains_inherited(self):
        r, dbs, _, _ = self.prepare(8)
        read = target_read(next(iter(dbs.values())), r["target"], None, gate="FORCED_ENGINEERING_DIAGNOSTIC")
        self.assertEqual(read["envelope"]["selected_memory_items"], [])
        self.assertEqual(read["public_retrieval_diagnostics"]["visible_history_excluded_count"], 1)

    def test_19_hidden_ids_rejected_by_runtime_interface(self):
        r, dbs, _, _ = self.prepare(1)
        target = copy.deepcopy(r["target"]); target["expected_fact_ids"] = ["f01-goal"]
        with self.assertRaisesRegex(ValueError, "RUNTIME_TARGET_KEYS_MISMATCH"):
            target_read(next(iter(dbs.values())), target, None, gate="FORCED_ENGINEERING_DIAGNOSTIC")

    def test_20_malformed_span_rejected_before_write(self):
        r = copy.deepcopy(self.runtime[0]); r["setup_operations"][0]["source_span_chars"] = [0, 3]
        with self.assertRaisesRegex(ValueError, "SOURCE_SPAN_OFFSET_MISMATCH"):
            setup_episode(r, self.directory / "bad-span")

    def test_21_native_worker_death_is_reported_without_crashing_parent(self):
        import io
        from unittest.mock import patch
        from types import SimpleNamespace
        from run_diagnostics import IsolatedBackend
        child = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                                wait=lambda **kwargs: -11, poll=lambda: -11)
        receipt = {}
        with patch("run_diagnostics.subprocess.Popen", return_value=child):
            with self.assertRaisesRegex(RuntimeError, "ISOLATED_NATIVE_RUNTIME_EXIT:-11"):
                IsolatedBackend(self.directory, receipt)
        self.assertEqual(receipt["worker_exit_code"], -11)
        self.assertTrue(child.stdout.closed)

if __name__ == "__main__": unittest.main()
