"""Public demo checks: synthetic inputs, temporary SQLite and no hosted calls.

Run from the repository root with ``python -m unittest discover -s tests -v``.
These tests verify the public adaptation, not dissertation performance.
"""

from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from demo.core import DemoAssistant


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for target in (
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "socket.create_connection",
            "socket.getaddrinfo",
        ):
            self.patches.enter_context(
                patch(target, side_effect=AssertionError("Network denied in demo tests"))
            )
        self.temporary = tempfile.TemporaryDirectory(prefix="lad-demo-test-")
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "memory.sqlite"
        self.engine = DemoAssistant(self.database)

    def test_default_answer_never_uses_online_completion(self):
        with patch("demo.core._online_completion") as completion:
            result = self.engine.answer("What does my dashboard show?", page="Overview")
        completion.assert_not_called()
        self.assertTrue(result["answer"].strip())
        self.assertTrue(result["trace"])
        self.assertTrue(result["limitations"])
        self.assertFalse(result.get("error"))

    def test_actual_r0_retrieval_has_source_spans_and_no_dense_scores(self):
        result = self.engine.retrieve("How should I write an evidence-based reflection?")
        self.assertEqual(result["implementation_id"], "C4_RAG_R0_LEXICAL")
        self.assertTrue(result["selected_chunks"])
        self.assertLessEqual(len(result["selected_chunks"]), 5)
        for chunk in result["selected_chunks"]:
            self.assertTrue(chunk["chunk_id"])
            self.assertTrue(chunk["text"].strip())
            self.assertTrue(chunk["document_title"])
            self.assertIsNone(chunk.get("dense_score"))

    def test_offline_course_answer_cites_retrieved_evidence(self):
        question = "How should I write an evidence-based reflection?"
        retrieval = self.engine.retrieve(question)
        result = self.engine.answer(question, page="Resources")
        self.assertTrue(result["answer"].strip())
        self.assertTrue(result["citations"])
        expected_ids = {chunk["chunk_id"] for chunk in retrieval["selected_chunks"]}
        actual_citations = str(result["citations"])
        self.assertTrue(any(chunk_id in actual_citations for chunk_id in expected_ids))
        self.assertFalse(result.get("error"))

    def test_memory_requires_explicit_consent(self):
        result = self.engine.memory_write("I want to practise evidence-based reflection.")
        self.assertFalse(result["accepted"])
        self.assertEqual(self.engine.memory_list(), [])

    def test_memory_persists_with_source_in_real_sqlite(self):
        text = "I want to practise evidence-based reflection."
        written = self.engine.memory_write(text, consent=True)
        self.assertTrue(written["accepted"])
        self.assertEqual(written["record"]["source_session_id"], "demo-session")
        self.assertTrue(written["record"]["source_turn_id"])
        self.assertEqual(written["record"]["version"], 1)
        self.assertEqual(self.database.read_bytes()[:16], b"SQLite format 3\x00")
        with closing(sqlite3.connect(f"file:{self.database}?mode=ro", uri=True)) as connection:
            fts_schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'memory_fts'"
            ).fetchone()
        self.assertIsNotNone(fts_schema)
        self.assertIn("USING fts5", fts_schema[0])
        reopened = DemoAssistant(self.database, session_id="another-demo-session")
        records = reopened.memory_list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["memory_id"], written["memory_id"])
        self.assertEqual(records[0]["content"], text)
        queried = reopened.memory_query("evidence-based reflection")
        self.assertTrue(queried["selected"])
        self.assertIn(written["memory_id"], str(queried["selected"]))

    def test_memory_isolated_by_learner_and_course(self):
        written = self.engine.memory_write("I want to practise algebra examples.", consent=True)
        self.assertTrue(written["accepted"])
        other_learner = DemoAssistant(self.database, learner_id="other-demo-learner")
        other_course = DemoAssistant(self.database, course_id="other-demo-course")
        for other in (other_learner, other_course):
            with self.subTest(scope=other):
                self.assertEqual(other.memory_list(), [])
                self.assertEqual(other.memory_query("algebra examples")["selected"], [])

    def test_memory_update_supersedes_old_record_and_increments_version(self):
        original = self.engine.memory_write("I want to practise algebra examples.", consent=True)
        self.assertTrue(original["accepted"])
        updated = self.engine.memory_write(
            "I want to practise reflection examples.",
            consent=True,
            target_memory_id=original["memory_id"],
        )
        self.assertTrue(updated["accepted"])
        self.assertNotEqual(updated["memory_id"], original["memory_id"])
        current = self.engine.memory_list()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["memory_id"], updated["memory_id"])
        self.assertEqual(current[0]["version"], 2)
        self.assertEqual(current[0]["supersedes_memory_id"], original["memory_id"])
        all_records = {item["memory_id"]: item for item in self.engine.memory_list(include_inactive=True)}
        self.assertEqual(all_records[original["memory_id"]]["status"], "SUPERSEDED")
        self.assertIsNotNone(all_records[original["memory_id"]]["valid_to"])

    def test_other_learner_cannot_update_existing_memory(self):
        original = self.engine.memory_write("I want to practise algebra examples.", consent=True)
        other = DemoAssistant(self.database, learner_id="other-demo-learner")
        result = other.memory_write(
            "I want to practise reflection examples.", consent=True,
            target_memory_id=original["memory_id"],
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(self.engine.memory_list()[0]["memory_id"], original["memory_id"])
        self.assertEqual(other.memory_list(), [])

    def test_visible_history_does_not_duplicate_memory_evidence(self):
        text = "I want to practise algebra examples."
        self.assertTrue(self.engine.memory_write(text, consent=True)["accepted"])
        result = self.engine.memory_query(
            "algebra examples", history=[{"role": "user", "content": text}]
        )
        self.assertEqual(result["selected"], [])

    def test_planning_runs_original_encoded_validation_without_auto_memory_write(self):
        result = self.engine.answer(
            "Create a reflection study plan", page="Reflection", budget_minutes=30
        )
        plan = result["plan"]
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["validation"]["outcome"], "PASSED_ENCODED_CHECKS")
        self.assertEqual(plan["implementation"], "DEMO_RULE_CANDIDATE_WITH_ORIGINAL_P0_VALIDATOR")
        self.assertEqual(plan["semantic_correctness"], "NOT_CHECKED")
        self.assertEqual(self.engine.memory_list(), [])

    def test_one_minute_plan_has_at_most_one_repair_and_respects_budget(self):
        result = self.engine.answer(
            "Create a reflection study plan", page="Reflection", budget_minutes=1
        )
        plan = result["plan"]
        self.assertTrue(plan["passed"])
        self.assertEqual(plan["repair_attempts"], 1)
        actions = plan["candidate"]["actions"]
        self.assertEqual(len(actions), 1)
        self.assertLessEqual(sum(row["estimated_duration"]["value"] for row in actions), 1)

    def test_saved_explicit_time_constraint_applies_to_plan(self):
        self.assertTrue(self.engine.memory_write(
            "I have 12 minutes for reflection study.", "CONSTRAINT", consent=True
        )["accepted"])
        result = self.engine.answer(
            "Create a reflection study plan", page="Reflection", budget_minutes=30
        )
        plan = result["plan"]
        self.assertTrue(plan["passed"])
        self.assertLessEqual(plan["budget_minutes"], 12)
        self.assertLessEqual(
            sum(row["estimated_duration"]["value"] for row in plan["candidate"]["actions"]), 12
        )
        self.assertEqual(len(self.engine.memory_list()), 1)

    def test_saved_chinese_goal_and_constraint_apply_to_explicit_plan_budget(self):
        goal = "我希望提升学习反思写作能力。"
        self.assertTrue(self.engine.memory_write(goal, "GOAL", consent=True)["accepted"])
        self.assertTrue(self.engine.memory_write(
            "我最多有10分钟时间", "CONSTRAINT", consent=True
        )["accepted"])
        result = self.engine.answer(
            "根据我保存的目标，制定30分钟的学习反思计划", page="Reflection", budget_minutes=30
        )
        self.assertTrue(result["plan"]["passed"])
        self.assertEqual(result["plan"]["candidate"]["goal"], goal)
        self.assertLessEqual(result["plan"]["budget_minutes"], 10)
        self.assertLessEqual(
            sum(row["estimated_duration"]["value"] for row in result["plan"]["candidate"]["actions"]), 10
        )
        self.assertEqual(len(self.engine.memory_list()), 2)

    def test_streamlit_offline_chat_memory_form_and_visitor_isolation(self):
        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parents[1] / "demo" / "legacy_app.py"
        with patch.dict("os.environ", {"DEMO_MEMORY_ROOT": str(Path(self.temporary.name) / "ui")}):
            app = AppTest.from_file(str(app_path), default_timeout=30).run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(next(widget for widget in app.checkbox if widget.label == "开启 OpenAI 在线生成").value)
            app.chat_input[0].set_value("怎样写一篇有证据的学习反思？").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.session_state.messages), 2)
            self.assertEqual(app.session_state.last_result["mode"], "offline")
            next(widget for widget in app.checkbox if widget.label.startswith("我同意")).set_value(True)
            next(button for button in app.button if button.label == "保存学习记忆").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.warning)
            app.text_area[0].set_value("I want to practise evidence-based reflection.")
            next(widget for widget in app.checkbox if widget.label.startswith("我同意")).set_value(True)
            next(button for button in app.button if button.label == "保存学习记忆").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.session_state.demo_engine.memory_list()), 1)
            second = AppTest.from_file(str(app_path), default_timeout=30).run()
            self.assertEqual(len(second.exception), 0)
            self.assertNotEqual(
                app.session_state.demo_engine.database_path,
                second.session_state.demo_engine.database_path,
            )
            self.assertEqual(second.session_state.demo_engine.memory_list(), [])

    def test_online_error_is_bounded_and_does_not_expose_exception_details(self):
        private_detail = "mock-credential-value-that-must-not-be-shown"
        with patch("demo.core._online_completion", side_effect=RuntimeError(private_detail)) as completion:
            result = self.engine.answer(
                "What does my dashboard show?", online=True, api_key="synthetic-test-key"
            )
        completion.assert_called_once()
        self.assertTrue(result.get("error"))
        self.assertTrue(result["answer"].strip())
        self.assertNotIn(private_detail, str(result))
        self.assertEqual(self.engine.memory_list(), [])

    def test_online_without_key_never_calls_provider(self):
        with patch("demo.core._online_completion") as completion:
            result = self.engine.answer("What does my dashboard show?", online=True, api_key="")
        completion.assert_not_called()
        self.assertTrue(result.get("error"))

    def test_online_mock_valid_schema_and_known_citation(self):
        citation_id = "dashboard-overview-resource_views"
        payload = json.dumps({
            "answer": f"活动记录 [{citation_id}]", "cited_evidence_ids": [citation_id]
        })
        with patch("demo.core._online_completion", return_value=payload) as completion:
            result = self.engine.answer("What does my dashboard show?", online=True, api_key="synthetic-test-key")
        completion.assert_called_once()
        self.assertEqual(result["mode"], "online")
        self.assertFalse(result.get("error"))
        self.assertIn(citation_id, result["answer"])
        self.assertEqual(self.engine.memory_list(), [])

    def test_online_mock_invalid_json_is_corrected_once(self):
        payload = json.dumps({
            "answer": "合成活动记录 [dashboard-overview-resource_views]",
            "cited_evidence_ids": ["dashboard-overview-resource_views"],
        })
        with patch("demo.core._online_completion", side_effect=["not-json", payload]) as completion:
            result = self.engine.answer("What does my dashboard show?", online=True, api_key="synthetic-test-key")
        self.assertEqual(completion.call_count, 2)
        self.assertEqual(result["mode"], "online")
        self.assertFalse(result.get("error"))
        self.assertEqual(self.engine.memory_list(), [])

    def test_online_mock_unknown_citations_fail_after_one_correction(self):
        payload = json.dumps({
            "answer": "Unsupported answer [invented-evidence-id]",
            "cited_evidence_ids": ["invented-evidence-id"],
        })
        with patch("demo.core._online_completion", return_value=payload) as completion:
            result = self.engine.answer("What does my dashboard show?", online=True, api_key="synthetic-test-key")
        self.assertEqual(completion.call_count, 2)
        self.assertEqual(result["mode"], "offline_fallback")
        self.assertTrue(result.get("error"))
        self.assertNotIn("invented-evidence-id", result["answer"])
        self.assertEqual(self.engine.memory_list(), [])


if __name__ == "__main__":
    unittest.main()
