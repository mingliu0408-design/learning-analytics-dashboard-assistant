"""Frozen-artifact checks and small synthetic filtering/serialization tests only."""
import ast
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT)]
import audit_offline as audit


class FrozenAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads((HERE / "OFFLINE_AUDIT_RESULTS.json").read_text())
        cls.sources = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())

    def test_sources_unchanged_and_expected_versions_match(self):
        for entry in self.sources["files"]:
            with self.subTest(path=entry["path"]):
                data = Path(entry["path"]).read_bytes()
                self.assertEqual(audit.digest(data), entry["sha256"])
                self.assertEqual(len(data), entry["bytes"])
                self.assertIsNot(entry.get("expected_hash_matches"), False)

    def test_handoff_join_and_population(self):
        self.assertEqual((self.result["conditions"], self.result["full_scenarios"]), (558, 62))
        self.assertTrue(all(r["byte_identical"] for r in self.result["handoff_csv_reconciliation"].values()))
        self.assertTrue(all(r["manifest_matches"] for r in self.sources["handoff_members"]))

    def test_gate_and_retrieval_are_distinct(self):
        rows = self.result["memory_case_evidence"]
        self.assertEqual(len(rows), 26)
        gated = {r["scenario_id"] for r in rows if r["design_control"].startswith("POSITIVE_MEMORY") and not r["p3_memory_required"]}
        self.assertEqual(gated, {"U026", "U027", "U029", "U033", "U034"})
        misses = [r for r in rows if r["memory_status"] == "NO_MATCH"]
        self.assertEqual(len(misses), 17)
        self.assertTrue(all("NO_ELIGIBLE_ACTIVE_MEMORY" in r["limitation_codes"] for r in misses))
        self.assertTrue(all(r["snapshot_active_count"] is None for r in misses))
        self.assertIn(["U022", "U026", "U031"], self.result["duplicate_four_field_inputs"])
        migration = self.result["native_setup_migration"]
        self.assertEqual(len(migration), 9)
        self.assertTrue(all(r["original_history_turns"] == 2 and r["setup_equals_original_history"]
                            and r["target_query_equals_original"] and r["target_visible_history_empty"] for r in migration))

    def test_available_does_not_mean_all_setup_types_returned(self):
        row = next(r for r in self.result["memory_case_evidence"] if r["scenario_id"] == "U037")
        self.assertEqual(row["snapshot_active_count"], 3)
        self.assertEqual(row["setup_types"], ["GOAL", "CONSTRAINT", "ACTIVE_PLAN"])
        self.assertEqual(row["selected_types"], ["ACTIVE_PLAN"])

    def test_second_rag_gate_is_not_ranking_failure(self):
        reasons = self.result["full_rag_no_result_reasons"]
        gate = {k for k, v in reasons.items() if "Course-material retrieval was not needed for this query." in v}
        self.assertEqual(gate, {"U004", "U005", "U006", "U007", "U016", "U034", "U054"})
        self.assertEqual(set(reasons) - gate, {"U017", "U046"})

    def test_compiler_renderer_and_actual_response_identity_bridge(self):
        r = self.result["compiler_and_renderer"]
        self.assertEqual(r["token_budget_exclusions"], [])
        self.assertEqual(r["retrieved_items_missing_compiler"], [])
        self.assertLess(r["max_stored_tokens"], 3200)
        self.assertEqual(r["conditions_matching_frozen_v2_payloads"], 558)
        self.assertEqual(r["conditions_matching_frozen_v3_payloads"], 558)
        self.assertEqual(r["unique_reconstructed_v3_payload_hashes"], 147)
        self.assertTrue(self.result["response_identity_bridge"]["payload_set_equals_frozen_v3"])
        self.assertEqual(self.result["baseline"]["same_final_v3_payload"], 52)

    def test_stored_arithmetic_is_not_new_scoring(self):
        metrics = self.result["stored_retrieval_metrics_arithmetic"]
        self.assertAlmostEqual(metrics["r0"]["mean_of_frozen_recall_at_5"], 12 / 13)
        self.assertAlmostEqual(metrics["r1"]["mean_of_frozen_recall_at_5"], 7 / 13)
        self.assertEqual(metrics["r1"]["stored_per_case_recall_at_5"]["U023"], "0.5")
        self.assertEqual(self.result["quality_or_relevance_scores_recomputed"], 0)

    def test_inventory_is_chunks_not_paths(self):
        c = self.result["corpus"]
        self.assertEqual((c["registered_paths"], c["registered_unique_file_hashes"], c["runtime_source_document_count"]), (346, 23, 6))
        self.assertEqual((c["chunk_count"], c["unique_chunk_ids"], c["unique_text_sha256_count"]), (624, 624, 610))
        self.assertEqual(c["rule_assigned_strength_counts"]["TITLE_AND_METADATA_ONLY"] + c["rule_assigned_strength_counts"]["LINK_ONLY"], 370)
        self.assertEqual(self.result["network_attempts"], 0)
        self.assertEqual(self.result["prohibited_model_modules_loaded"], [])


class SyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.c4_memory.c4_memory_retriever import C4MemoryRetriever
        cls.Retriever = C4MemoryRetriever

    def record(self, content="Need a quiet place for study", **changes):
        fields = dict(memory_id="synthetic-1", student_id="synthetic-learner", memory_type="CONSTRAINT",
                      content=content, conflict_key=None, version=1, last_confirmed_at="2026-01-01T00:00:00+00:00",
                      created_at="2026-01-01T00:00:00+00:00", confidence=1.0, importance=0.5)
        return SimpleNamespace(**{**fields, **changes})

    def retriever(self, records):
        store = SimpleNamespace(list_active_memories=lambda *a, **k: records, fts_search=lambda *a, **k: [])
        return self.Retriever(store, semantic_backend=None, clock=lambda: "2026-09-01T00:00:00+00:00")

    def test_no_candidate_and_low_relevance_have_different_reasons(self):
        empty = self.retriever([]).retrieve("synthetic", "zebra", [])
        low = self.retriever([self.record()]).retrieve("synthetic", "zebra", [])
        self.assertIn("NO_ELIGIBLE_ACTIVE_MEMORY", empty.limitations)
        self.assertIn("NO_RELEVANCE_SUPPORTED", low.limitations)
        self.assertEqual((empty.active_candidate_count, low.active_candidate_count), (0, 1))

    def test_visible_history_filter_is_recorded(self):
        r = self.record()
        result = self.retriever([r]).retrieve("synthetic", "study", [{"role": "user", "content": r.content}])
        self.assertEqual(result.visible_history_excluded_count, 1)
        self.assertIn("NO_ELIGIBLE_ACTIVE_MEMORY", result.limitations)

    def test_conflict_precedence_uses_version(self):
        old = self.record(conflict_key="synthetic-conflict", version=1)
        new = self.record(conflict_key="synthetic-conflict", version=2, memory_id="synthetic-2")
        kept, removed = self.Retriever._resolve_active_conflicts([old, new])
        self.assertEqual(kept, [new]); self.assertEqual(removed, 1)

    def test_sql_scope_consent_temporal_and_active_filters(self):
        # Execute the literal frozen SELECT against tiny in-memory rows only.
        tree = ast.parse((ROOT / "utils/c4_memory/c4_memory_store.py").read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "list_active_memories")
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute")
        query = ast.literal_eval(call.args[0])
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE memories(memory_id, student_id, status, consent_status, valid_from, valid_to, created_at)")
        rows = [("ok", "s", "ACTIVE", "GRANTED", "2026-01-01", None, "2026-01-01"),
                ("scope", "other", "ACTIVE", "GRANTED", "2026-01-01", None, "2026-01-01"),
                ("consent", "s", "ACTIVE", "DENIED", "2026-01-01", None, "2026-01-01"),
                ("future", "s", "ACTIVE", "GRANTED", "2027-01-01", None, "2026-01-01"),
                ("expired", "s", "ACTIVE", "GRANTED", "2026-01-01", "2026-02-01", "2026-01-01"),
                ("superseded", "s", "SUPERSEDED", "GRANTED", "2026-01-01", None, "2026-01-01")]
        db.executemany("INSERT INTO memories VALUES(?,?,?,?,?,?,?)", rows)
        self.assertEqual([r[0] for r in db.execute(query, ("s", "2026-09-01", "2026-09-01"))], ["ok"])
        db.close()

    def test_planner_constructor_does_not_receive_memory_constraint(self):
        from utils.c4_real_adapters import C4RecommendationPlannerAdapter
        req = SimpleNamespace(current_query="Make a study plan", current_page="Lecture", student_id="synthetic")
        compiled = SimpleNamespace(compiled_evidence_sha256="synthetic-hash", content={"selected_evidence": [
            {"evidence_id": "synthetic-memory", "source_kind": "LEARNER_MEMORY", "memory_type": "CONSTRAINT", "content": "Only ten minutes"}]})
        fake_module = SimpleNamespace(classify_query=lambda q: "improvement_recommendation")
        with patch.dict(sys.modules, {"utils.evidence_synthesiser": fake_module}):
            with patch("utils.c4_real_adapters.build_recommendation_plan", return_value={"action_steps": ["Synthetic step"]}) as constructor:
                result = C4RecommendationPlannerAdapter().plan(request=req, compiled_evidence=compiled)
        self.assertNotIn("Only ten minutes", str(constructor.call_args))
        self.assertEqual(result.plan["learner_constraints"], ["Only ten minutes"])

    def test_empty_note_changes_rendering_without_factual_material(self):
        from evaluation.rq3_real_c4.g2d0_response_format_repair.c4_real_generation_request_renderer_v3 import render_generation_request_v3
        a = {"current_page": "Lecture", "current_query": "Synthetic request", "visible_conversation_history": [],
             "evidence": {"evidence": [{"source": "current_page_context", "content": {}}], "availability_notes": []}, "planning_support": None}
        b = {**a, "evidence": {"evidence": [], "availability_notes": ["No student activity evidence was available for this page."]}}
        left, right = render_generation_request_v3(a), render_generation_request_v3(b)
        self.assertNotEqual(left, right)
        self.assertTrue(right.startswith(left))
        self.assertNotIn("DASHBOARD EVIDENCE", left)

    def test_duplicate_identity_fails_instead_of_overwriting(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SOURCE_IDENTITY"):
            audit.unique_index([{"id": "s"}, {"id": "s"}], lambda r: r["id"])


if __name__ == "__main__":
    with patch.object(audit.socket, "socket", audit.BlockNetwork):
        unittest.main(verbosity=2)
