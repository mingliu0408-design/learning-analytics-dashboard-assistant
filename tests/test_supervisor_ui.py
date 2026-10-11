"""Independent checks for author-confirmed Supervisor charts + restored core.

No paid calls: only the provider transport is replaced in LIVE integration.
The original UI/data and preserved research tests are never modified.
"""
from contextlib import ExitStack
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/dashboard/input"


class SupervisorUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lad-supervisor-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"LAD_SESSION_STORAGE": self.tmp.name, "OPENAI_API_KEY": ""}))
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection", "socket.getaddrinfo"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("Networking denied in supervisor UI tests")))
        from streamlit.testing.v1 import AppTest
        self.AppTest = AppTest

    @staticmethod
    def labeled(elements, label):
        return next(element for element in elements if element.label == label)

    def healthy(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        return app

    def app(self):
        return self.healthy(self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run())

    def page(self, app, page):
        self.labeled(app.radio, "学习页面").set_value(page).run()
        return self.healthy(app)

    def profile(self, app, profile):
        self.labeled(app.selectbox, "运行 profile").set_value(profile).run()
        return self.healthy(app)

    @staticmethod
    def specs(app):
        return [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]

    def selected_rows(self, app, relative):
        uid = int(self.labeled(app.selectbox, "匿名学习者").value)
        low, high = self.labeled(app.slider, "观察周范围").value
        frame = pd.read_csv(DATA / relative)
        frame = frame[frame.ID == uid]
        week = "Content_week" if relative.startswith("echo/") else "Week"
        return frame[frame[week].between(low, high)]

    def selection(self, result):
        source = result.get("source") or result["core"]["source"]
        self.assertEqual(source["scope"]["snapshot"], source["dashboard_selection"]["source_version"])
        self.assertEqual(source["scope"]["learner_id"], source["dashboard_selection"]["learner_id"])
        from public_runtime.dashboard import SOURCES
        self.assertEqual(set(source["source_hashes"]), set(SOURCES))
        self.assertEqual(len(source["source_hashes"]), 8)
        for name, relative in SOURCES.items():
            self.assertEqual(source["source_hashes"][name], hashlib.sha256((ROOT / "data/dashboard" / relative).read_bytes()).hexdigest())
        self.assertIn("timezone is unknown", source["temporal_boundary"])
        self.assertEqual(set(source["primary"]), {"current_query", "current_page", "dashboard_context", "visible_conversation_history"})
        return source["dashboard_selection"]

    def test_six_views_have_original_chart_forms_and_no_network(self):
        app = self.app()
        radio = self.labeled(app.radio, "学习页面")
        pages = ["Overview", "Resources", "Lecture", "Debate", "Reflection", "Next Steps"]
        self.assertEqual(len(radio.options), len(pages))
        self.assertEqual(len(set(radio.options)), len(pages))
        for page in pages:
            self.page(app, page)
            specs = self.specs(app)
            kinds = [t.get("type") for s in specs for t in s["data"]]
            if page == "Resources":
                self.assertGreaterEqual(len(specs), 2)
                self.assertIn("scatter", kinds)
                self.assertIn("heatmap", kinds)
            elif page == "Lecture":
                bars = [t for s in specs for t in s["data"] if t.get("type") == "bar"]
                self.assertTrue(bars)
                self.assertTrue(all(t.get("orientation") == "h" for t in bars))
            elif page == "Debate":
                self.assertTrue(app.get("component_instance") or specs, "Actual network component or Plotly network must render")
                self.assertGreaterEqual(len(app.metric), 5)
            elif page == "Reflection":
                self.assertGreaterEqual(len(specs), 2)
                self.assertIn("scatter", kinds)
            elif page == "Next Steps":
                self.labeled(app.text_area, "你明确声明的内容")
                self.labeled(app.checkbox, "同意在当前session保存这条学习信息")

    def test_lecture_bars_keep_actual_views_classes_and_percent(self):
        app = self.page(self.app(), "Lecture")
        expected = self.selected_rows(app, "echo/echo_logs.csv")
        actual = [t for s in self.specs(app) for t in s["data"] if t.get("type") == "bar"]
        observed = []
        for trace in actual:
            self.assertEqual(trace["orientation"], "h")
            values = trace["marker"]["color"]
            self.assertTrue(all(0 <= float(v) <= 100 for v in values))
            observed += list(zip(trace["y"], trace["x"], values))
        wanted = list(zip(expected["Class"], expected["Video Views"], expected["Video View %"]))
        self.assertEqual(sorted(observed), sorted(wanted))

    def test_resources_heatmap_uses_content_x_and_engagement_y(self):
        app = self.page(self.app(), "Resources")
        rows = self.selected_rows(app, "moodle/moodle_logs.csv")
        rows = rows[rows.Event == "Resources_views"]
        heat = next(t for s in self.specs(app) for t in s["data"] if t.get("type") == "heatmap")
        x, y, z = list(heat["x"]), list(heat["y"]), np.asarray(heat["z"])
        self.assertEqual(z.shape, (len(y), len(x)))
        for i, engaged in enumerate(y):
            for j, content in enumerate(x):
                count = len(rows[(rows.Week == int(engaged)) & (rows.Content_week == int(content))])
                self.assertEqual(float(z[i, j]), count)
        self.assertEqual(float(z.sum()), len(rows[rows.Content_week.isin([int(v) for v in x]) & rows.Week.isin([int(v) for v in y])]))
        # Fixture is deliberately nonsymmetric; swapped axes cannot pass.
        if len(rows):
            self.assertTrue(rows.Week.ne(rows.Content_week).any())

    def test_reflection_series_align_to_actual_day_and_public_cohorts(self):
        app = self.page(self.app(), "Reflection")
        cohorts = pd.read_csv(DATA / "gdocs/ts_cohorts.csv")
        days = list(cohorts.day)
        curves = [t for spec in self.specs(app) for t in spec["data"]
                  if t.get("type") == "scatter" and list(t.get("x", [])) == days]
        self.assertGreaterEqual(len(curves), 3)
        previous = list(cohorts.previousCohorts)
        current = list(cohorts.currentCohort)
        matching_previous = [t for t in curves if t.get("y") == previous]
        matching_current = [t for t in curves if t.get("y") == current]
        self.assertTrue(matching_previous)
        self.assertTrue(matching_current)
        learner_curve = next(t for t in curves if t not in matching_previous + matching_current)
        rows = self.selected_rows(app, "gdocs/activities.csv")
        counts = rows.groupby("day").absStrCount.sum().to_dict()
        self.assertEqual(len(learner_curve["y"]), len(days))
        for day, value in zip(days, learner_curve["y"]):
            if day in counts:
                self.assertEqual(float(value), float(counts[day]))
            else:
                # No observed editing is a chart gap or zero; generation-side
                # coverage remains unknown and is checked by the core tests.
                self.assertIn(value, (0, None))

    def test_reflection_cohort_source_matches_rendered_window_and_personal_gaps(self):
        app = self.page(self.profile(self.app(), "COMPONENTS"), "Reflection")
        roster = pd.read_csv(DATA / "student_info.csv")
        first = str(self.labeled(app.selectbox, "匿名学习者").value)
        second = next(str(int(v)) for v in roster.ID if str(int(v)) != first)
        raw = pd.read_csv(DATA / "gdocs/activities.csv")
        cohorts = pd.read_csv(DATA / "gdocs/ts_cohorts.csv")
        with (DATA / "gdocs/ts_cohorts.csv").open(newline="") as handle:
            raw_cohorts = {int(row["day"]): row for row in csv.DictReader(handle)}
        mapping = raw[["day", "Week"]].drop_duplicates()
        self.assertFalse(mapping.day.duplicated().any(), "Actual source day provenance must be unambiguous")
        for learner, window in ((first, (0, 10)), (first, (2, 4)), (second, (8, 10))):
            self.labeled(app.selectbox, "匿名学习者").set_value(learner).run()
            self.labeled(app.slider, "观察周范围").set_value(window).run()
            self.labeled(app.button, "执行本地组件").click().run()
            self.healthy(app)
            result = app.session_state.last_result
            chosen = self.selection(result)
            self.assertEqual(chosen["learner_id"], learner)
            source = result["source"]
            primary = source["primary"]
            self.assertEqual(primary["current_page"], "Reflection")
            context = primary["dashboard_context"]["cohort_comparison"]
            self.assertEqual(context["source_sha256"], source["source_hashes"]["cohorts"])
            self.assertEqual(context["source_path"], "input/gdocs/ts_cohorts.csv")
            self.assertEqual(context["source_kind"], "HISTORICAL_COHORT_CHART_CONTEXT")
            self.assertEqual(context["coverage_status"], "NOT_ASSERTED_COMPLETE")
            self.assertEqual(context["observation_weeks"], list(window))
            self.assertNotIn("cohort_comparison", primary["dashboard_context"]["activity"]["Reflection"])
            expected = cohorts.merge(mapping, on="day", validate="one_to_one")
            expected = expected[expected.Week.between(*window)].sort_values("day")
            records = context["records"]
            self.assertEqual([r["day"] for r in records], list(expected.day))
            self.assertEqual([r["observation_week"] for r in records], list(expected.Week))
            self.assertEqual([r["previous_cohort"] for r in records], [float(raw_cohorts[day]["previousCohorts"]) for day in expected.day])
            self.assertEqual([r["current_cohort"] for r in records], [float(raw_cohorts[day]["currentCohort"]) for day in expected.day])
            daily = raw[(raw.ID == int(learner)) & raw.Week.between(*window)].groupby("day").absStrCount.sum().to_dict()
            for record in records:
                day = record["day"]
                if day in daily:
                    self.assertEqual(record["learner_recorded_edits"], float(daily[day]))
                    self.assertEqual(record["learner_source_status"], "RECORDED_VALUE_PARTIAL_COVERAGE")
                else:
                    self.assertIsNone(record["learner_recorded_edits"])
                    self.assertEqual(record["learner_source_status"], "NO_OBSERVATIONS_OR_INVALID_VALUE_COVERAGE_UNKNOWN")
                    self.assertEqual(record["learner_chart_display_value"], 0.0)
            traces = [t for spec in self.specs(app) for t in spec["data"]
                      if t.get("type") == "scatter" and list(t.get("x", [])) == list(expected.day)]
            self.assertGreaterEqual(len(traces), 3)
            for name, field in (("Previous Cohorts", "previous_cohort"), ("Your Cohort", "current_cohort")):
                trace = next(t for t in traces if t.get("name") == name)
                # Python CSV float and pandas CSV fast parsing can differ by one
                # ULP for saved repeating decimals. Source bytes/hash and raw
                # Python float values above remain exact; plotted values agree
                # within 1e-15 relative precision, with no absolute tolerance.
                np.testing.assert_allclose(trace["y"], [r[field] for r in records], rtol=1e-15, atol=0)
            learner_trace = next(t for t in traces if t.get("name") not in ("Previous Cohorts", "Your Cohort"))
            self.assertEqual(learner_trace["y"], [r["learner_chart_display_value"] for r in records])

    def test_components_scope_rebinds_learner_and_window(self):
        app = self.profile(self.app(), "COMPONENTS")
        learner = self.labeled(app.selectbox, "匿名学习者")
        first_id = str(learner.value)
        self.labeled(app.button, "执行本地组件").click().run()
        self.healthy(app)
        first = app.session_state.last_result
        selected = self.selection(first)
        self.assertEqual(str(selected["learner_id"]), first_id)
        self.assertEqual(first["rag_calls"], 1)
        self.assertEqual(first["memory_calls"], 1)
        self.assertTrue(first["prepared"]["trace"]["dashboard_raw_fact_trace"])
        self.assertEqual(first["route"]["provider_identity"], "PUBLIC_EXPLICIT_COMPONENT_GATE_NO_P3")
        next_id = next(str(int(v)) for v in pd.read_csv(DATA / "student_info.csv").ID if str(int(v)) != first_id)
        learner.set_value(next_id).run()
        self.labeled(app.slider, "观察周范围").set_value((2, 4)).run()
        self.labeled(app.button, "执行本地组件").click().run()
        self.healthy(app)
        changed = app.session_state.last_result
        selected = self.selection(changed)
        self.assertEqual(str(selected["learner_id"]), next_id)
        self.assertEqual((selected["week_start"], selected["week_end"]), (2, 4))
        self.assertNotEqual(first["source"]["primary_sha256"], changed["source"]["primary_sha256"])
        self.assertEqual(app.session_state.engine.active_task_id, "dashboard-" + next_id)

    def test_replay_keeps_historical_identity_independent_of_chart_learner(self):
        app = self.app()
        historical = self.labeled(app.selectbox, "研究任务 / source context").value
        mode = self.labeled(app.selectbox, "保存的研究模式").value
        self.labeled(app.button, "回放保存回答").click().run()
        self.healthy(app)
        result = app.session_state.last_result
        self.assertEqual((result["task_id"], result["mode"]), (historical, mode))
        self.assertFalse(result["task_id"].startswith("dashboard-"))
        self.assertEqual(result["generation"], "SAVED_HISTORICAL_ANSWER_NO_NEW_MODEL_CALL")
        self.assertEqual(hashlib.sha256(result["answer"].encode()).hexdigest(), result["answer_sha256"])

    def test_dashboard_ui_to_mock_p3_complete_m1_planner_and_final(self):
        from public_runtime.core import PublicAssistant
        from test_runtime import ExactMock
        provider = ExactMock(planning=True, memory=True)
        original = PublicAssistant.live
        def mocked_live(engine, query, **kwargs):
            return original(engine, query, transport=provider, memory_backend="LEXICAL", **kwargs)
        with patch.object(PublicAssistant, "live", mocked_live):
            app = self.profile(self.app(), "LIVE")
            self.labeled(app.selectbox, "显式任务类型").set_value("ORDINARY_ACTION_ADVICE").run()
            self.labeled(app.text_area, "当前问题").set_value("Give me an action plan without dates to study learning analytics.").run()
            self.labeled(app.button, "实时发送到 OpenAI").click().run()
            self.healthy(app)
        result = app.session_state.last_result
        self.assertEqual([r["role"] for r in result["provider_trace"]], ["RAG", "MEMORY", "B4_PLANNING", "CANDIDATE", "FINAL"])
        self.assertFalse(result["live_model_call"])
        self.assertEqual(result["generation"], "MOCK_EXACT_CORE_NO_PAID_CALL")
        self.assertIsNotNone(result["accepted_plan"])
        self.assertEqual(str(self.selection(result)["learner_id"]), str(self.labeled(app.selectbox, "匿名学习者").value))
        self.assertTrue(result["core"]["readonly_state_unchanged"])
        self.assertEqual(app.session_state.engine.memory_list(app.session_state.engine.active_task_id), [], "Generated advice is not an accepted learner commitment")
        for payload in provider.payloads:
            self.assertNotIn('"gold"', json.dumps(payload).lower())

    def test_next_steps_memory_requires_consent_and_isolates_sessions(self):
        app = self.page(self.profile(self.app(), "COMPONENTS"), "Next Steps")
        engine = app.session_state.engine
        task = engine.active_task_id
        self.assertEqual(engine.memory_list(task), [])
        self.labeled(app.text_area, "Reflection").set_value("This reflection is a session draft, not a long-term commitment.")
        self.labeled(app.button, "Save reflection").click().run()
        self.healthy(app)
        self.assertEqual(len(app.session_state["reflections_" + task]), 1)
        self.assertEqual(list(app.session_state["goal_drafts_" + task].columns), ["Goal", "Due", "Status", "Progress", "Notes"])
        self.assertEqual(engine.memory_list(task), [])
        self.labeled(app.text_area, "你明确声明的内容").set_value("My learning goal is understanding learning analytics.")
        self.labeled(app.button, "保存原生Memory").click().run()
        self.healthy(app)
        self.assertEqual(engine.memory_list(task), [])
        self.labeled(app.checkbox, "同意在当前session保存这条学习信息").set_value(True)
        self.labeled(app.button, "保存原生Memory").click().run()
        self.healthy(app)
        self.assertEqual(len(engine.memory_list(task)), 1)
        other_app = self.page(self.profile(self.app(), "COMPONENTS"), "Next Steps")
        other = other_app.session_state.engine
        self.assertNotEqual(engine.workspace, other.workspace)
        self.assertEqual(other.memory_list(other.active_task_id), [])
        self.assertEqual(other_app.session_state["reflections_" + other.active_task_id], [])
        self.assertEqual(len(other_app.session_state["goal_drafts_" + other.active_task_id]), 0)
        self.assertEqual(other.history, [])
        self.assertIsNone(other._api_key)

    def test_missing_hybrid_resource_is_explicit_in_component_ui(self):
        with patch.dict(os.environ, {"LAD_MPNET_PATH": ""}):
            app = self.profile(self.app(), "COMPONENTS")
            self.labeled(app.selectbox, "Memory 检索").set_value("HYBRID").run()
            self.labeled(app.button, "执行本地组件").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.error)
        self.assertTrue(any("Hybrid" in element.value and "MPNet" in element.value for element in app.error))
        self.assertNotIn("last_result", app.session_state)
        self.assertEqual(app.session_state.engine.history, [])

    def test_live_without_visitor_key_never_constructs_provider_client(self):
        with patch("openai.OpenAI", side_effect=AssertionError("Provider must not be created without a visitor key")) as client:
            app = self.profile(self.app(), "LIVE")
            self.labeled(app.selectbox, "显式任务类型").set_value("ORDINARY_ACTION_ADVICE").run()
            self.labeled(app.text_area, "当前问题").set_value("Give me an action plan without dates to study learning analytics.").run()
            source = app.session_state.engine.call("source", query=self.labeled(app.text_area, "当前问题").value, page="Overview", controls={"task_intent": "ORDINARY_ACTION_ADVICE"})
            self.assertFalse(source["clarification"], "This negative test must reach the visitor-key boundary, not the valid local clarification gate")
            self.labeled(app.button, "实时发送到 OpenAI").click().run()
            client.assert_not_called()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.error)
        self.assertTrue(any("PermissionError" in element.value for element in app.error))
        self.assertIsNone(app.session_state.engine._api_key)
        self.assertEqual(app.session_state.engine.history, [])
        self.assertNotIn("last_result", app.session_state)

    def test_mock_ui_plan_adoption_completion_native_relations_and_visitor_isolation(self):
        from public_runtime.core import PublicAssistant
        from test_runtime import ExactMock
        provider = ExactMock(planning=True, memory=True)
        original = PublicAssistant.live
        def mocked_live(engine, query, **kwargs):
            return original(engine, query, transport=provider, memory_backend="LEXICAL", **kwargs)
        with patch.object(PublicAssistant, "live", mocked_live):
            app = self.profile(self.app(), "LIVE")
            self.labeled(app.selectbox, "显式任务类型").set_value("ORDINARY_ACTION_ADVICE").run()
            self.labeled(app.text_area, "当前问题").set_value("Give me an action plan without dates to study learning analytics.").run()
            self.labeled(app.button, "实时发送到 OpenAI").click().run()
            self.healthy(app)
            engine = app.session_state.engine
            task = engine.active_task_id
            self.assertTrue(app.session_state.last_result["plan_registration"]["registered"])
            self.assertEqual(engine.memory_list(task), [])
            self.labeled(app.button, "采纳已检查计划").click().run()
            self.healthy(app)
            self.assertEqual(engine.memory_task_state(task)["plans"], [])
            self.assertEqual(engine.memory_list(task), [])
            self.labeled(app.checkbox, "我选择采纳这个行动计划，并同意保存到当前学习者的会话 Memory").set_value(True)
            self.labeled(app.button, "采纳已检查计划").click().run()
            self.healthy(app)
            adopted = engine.memory_task_state(task)["plans"]
            self.assertEqual(len(adopted), 1)
            self.assertEqual(adopted[0]["origin"], "USER")
            self.assertEqual(adopted[0]["adoption_basis"], "EXPLICIT_UI_CONSENT")
            self.assertFalse(adopted[0]["actions"][0]["completed"])
            self.page(app, "Next Steps")
            self.labeled(app.button, "报告行动完成").click().run()
            self.healthy(app)
            self.assertFalse(engine.memory_task_state(task)["plans"][0]["actions"][0]["completed"])
            self.labeled(app.checkbox, "我确认已完成所选行动，并同意保存这条自报完成记录").set_value(True)
            self.labeled(app.button, "报告行动完成").click().run()
            self.healthy(app)
        plan = engine.memory_task_state(task)["plans"][0]
        action = plan["actions"][0]
        self.assertTrue(action["completed"])
        self.assertEqual(action["completion_basis"], "EXPLICIT_USER_SELF_REPORT")
        records = {record["memory_id"]: record for record in engine.memory_list(task)}
        for memory_id in (plan["plan_memory_id"], action["action_memory_id"], action["completion_memory_id"]):
            self.assertIn(memory_id, records)
            self.assertEqual(records[memory_id]["student_id"], engine._dashboard_context["learner_id"])
            self.assertEqual(records[memory_id]["status"], "ACTIVE")
        graphs = list(engine.workspace.rglob("visitor_graph.json"))
        self.assertEqual(len(graphs), 1)
        graph = json.loads(graphs[0].read_text())
        edges = {(edge["relation_type"], edge["from_id"], edge["to_id"]) for edge in graph["edges"]}
        self.assertIn(("ACCEPTED_ACTION_BELONGS_TO_PLAN", action["action_memory_id"], plan["plan_memory_id"]), edges)
        self.assertIn(("COMPLETION_BELONGS_TO_PLAN", action["completion_memory_id"], plan["plan_memory_id"]), edges)
        self.assertIn(("COMPLETION_OF_ACTION", action["completion_memory_id"], action["action_memory_id"]), edges)
        other_app = self.page(self.profile(self.app(), "COMPONENTS"), "Next Steps")
        other = other_app.session_state.engine
        self.assertNotEqual(engine.workspace, other.workspace)
        self.assertEqual(other.memory_task_state(other.active_task_id)["plans"], [])
        self.assertEqual(other.memory_list(other.active_task_id), [])
        self.assertEqual(len(provider.payloads), 5)

    def test_mode_change_removes_old_plan_and_replay_result_without_new_calls(self):
        from public_runtime.core import PublicAssistant
        from test_runtime import ExactMock
        provider = ExactMock(planning=True, memory=True)
        original = PublicAssistant.live
        def mocked_live(engine, query, **kwargs):
            return original(engine, query, transport=provider, memory_backend="LEXICAL", **kwargs)
        with patch.object(PublicAssistant, "live", mocked_live):
            app = self.profile(self.app(), "LIVE")
            self.labeled(app.selectbox, "显式任务类型").set_value("ORDINARY_ACTION_ADVICE").run()
            self.labeled(app.text_area, "当前问题").set_value("Give me an action plan without dates to study learning analytics.").run()
            self.labeled(app.button, "实时发送到 OpenAI").click().run()
            self.healthy(app)
            self.assertIsNotNone(app.session_state.last_result["accepted_plan"])
            self.labeled(app.button, "采纳已检查计划")
            calls = len(provider.payloads)
            self.assertEqual(calls, 5)
            self.labeled(app.selectbox, "系统能力模式").set_value("S0_PAGE_ONLY").run()
            self.healthy(app)
            self.assertNotIn("last_result", app.session_state)
            self.assertFalse(any(button.label == "采纳已检查计划" for button in app.button))
            self.assertEqual(len(provider.payloads), calls)
            self.assertEqual(app.session_state.engine.memory_list(), [])
            self.labeled(app.selectbox, "系统能力模式").set_value("S5_FULL").run()
            self.healthy(app)
            self.assertNotIn("last_result", app.session_state, "Returning to the former mode cannot resurrect an earlier result")
            self.assertEqual(len(provider.payloads), calls)
        replay = self.app()
        self.labeled(replay.button, "回放保存回答").click().run()
        self.healthy(replay)
        old_mode = replay.session_state.last_result["mode"]
        new_mode = next(mode for mode in ("S0_PAGE_ONLY", "S5_FULL") if mode != old_mode)
        self.labeled(replay.selectbox, "保存的研究模式").set_value(new_mode).run()
        self.healthy(replay)
        self.assertNotIn("last_result", replay.session_state)
        self.assertEqual(len(provider.payloads), calls)

    def test_chart_loaded_bytes_mismatch_stops_before_render_or_worker(self):
        import public_runtime.dashboard as dashboard
        import public_runtime.dashboard_charts as charts
        import public_runtime.supervisor_ui as supervisor
        from public_runtime.core import PublicAssistant
        with tempfile.TemporaryDirectory(prefix="lad-chart-source-copy-") as tmp:
            copy_root = Path(tmp)
            for relative in dashboard.SOURCES.values():
                destination = copy_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "data/dashboard" / relative, destination)
            with patch.object(charts, "INPUT", copy_root / "input"), patch.object(dashboard, "DATA", copy_root):
                old_data = charts.load_dashboard_data()
                old_version = charts.chart_source_version(old_data)
                self.assertEqual(old_version, dashboard.build_context("301101")["source_version"])
                for key, (relative, _) in charts.SOURCES.items():
                    self.assertEqual(old_data[key].attrs["source_sha256"], hashlib.sha256((copy_root / "input" / relative).read_bytes()).hexdigest())
                changed_path = copy_root / "input/gdocs/ts_cohorts.csv"
                changed = pd.read_csv(changed_path)
                changed.loc[0, "previousCohorts"] = float(changed.loc[0, "previousCohorts"]) + 1
                changed.to_csv(changed_path, index=False)
                new_context = dashboard.build_context("301101")
                self.assertNotEqual(old_version, new_context["source_version"])
                fresh_data = charts.load_dashboard_data()
                self.assertEqual(charts.chart_source_version(fresh_data), new_context["source_version"])
                self.assertNotEqual(old_data["cohorts"].attrs["source_sha256"], fresh_data["cohorts"].attrs["source_sha256"])
                self.assertNotEqual(old_data["cohorts"].iloc[0].previousCohorts, fresh_data["cohorts"].iloc[0].previousCohorts)
                with patch.object(supervisor, "load_dashboard_data", return_value=old_data), \
                     patch.object(supervisor, "render_dashboard") as render, \
                     patch.object(PublicAssistant, "call", side_effect=AssertionError("Mismatched chart bytes must stop before worker use")) as worker:
                    app = self.AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
                    self.assertEqual(len(app.exception), 0)
                    self.assertTrue(any("来源在读取期间发生变化" in element.value for element in app.error))
                    self.assertFalse(app.get("plotly_chart"))
                    self.assertFalse(app.get("component_instance"))
                    self.assertNotIn("latest_source", app.session_state)
                    self.assertNotIn("last_result", app.session_state)
                    render.assert_not_called()
                    worker.assert_not_called()

    def test_cached_dashboard_frames_do_not_share_mutations_between_visitors(self):
        from public_runtime.dashboard_charts import load_dashboard_data
        first = load_dashboard_data()
        second = load_dashboard_data()
        original = first["student_info"].copy(deep=True)
        first["student_info"].loc[first["student_info"].index[0], "ID"] = -999
        first["echo"]["synthetic_visitor_marker"] = True
        pd.testing.assert_frame_equal(second["student_info"], original)
        self.assertNotIn("synthetic_visitor_marker", second["echo"])
        third = load_dashboard_data()
        pd.testing.assert_frame_equal(third["student_info"], original)
        self.assertNotIn("synthetic_visitor_marker", third["echo"])

    def test_public_chart_sources_stay_unchanged_across_sessions(self):
        paths = list(DATA.rglob("*.csv"))
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        first, second = self.app(), self.app()
        for page in ("Resources", "Lecture", "Debate", "Reflection"):
            self.page(first, page)
            self.page(second, page)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


if __name__ == "__main__":
    unittest.main()
