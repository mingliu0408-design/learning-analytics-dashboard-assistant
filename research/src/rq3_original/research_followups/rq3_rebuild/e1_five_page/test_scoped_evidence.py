#!/usr/bin/env python3
"""Substantive E1 synthetic acceptance through actual final prepared requests."""
from __future__ import annotations

import argparse
import ast
import copy
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.abc
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--source-root", type=Path, default=HERE.parents[2])
parser.add_argument("--output-dir", type=Path, default=HERE)
args = parser.parse_args()
sys.path.insert(0, str(args.source_root))
BLOCKED = []


def audit(event, values):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen", "os.system"}:
        BLOCKED.append(event)
        raise RuntimeError("No network, subprocess, server or model execution in E1 acceptance")


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"openai", "anthropic", "torch", "transformers", "sentence_transformers", "streamlit"}:
            BLOCKED.append("import:" + fullname)
            raise RuntimeError("Provider/model/UI imports disabled")


sys.addaudithook(audit)
sys.meta_path.insert(0, NoModels())
from utils.c4_dashboard_scoped import PAGES, DOMAINS
from utils.c4_dashboard_scoped.scope import Scope, Snapshot, SourceSpec, Coverage, Calendar, ScopeError, ClarificationRequired, canonical
from utils.c4_dashboard_scoped.aggregate import aggregate
from utils.c4_dashboard_scoped.integration import build_scoped_request, build_scoped_evidence_service, fact_to_request_trace
from utils.c4_dashboard_scoped.loader import load_csv_snapshot
from utils.c4_dashboard_scoped.streamlit import ScopedUIBinding, scoped_evidence_enabled, render_scoped_dashboard, checked_ui_binding
from utils.c4_real_adapters import C4RealEvidenceSynthesisAdapter, C4RealEvidenceCompilerV1
from utils.c4_real_contracts import C4Mode

FIX = json.loads((HERE / "SYNTHETIC_FIXTURE.json").read_text())
EXPECTED = json.loads((HERE / "HAND_CALCULATED_EXPECTATIONS.json").read_text())
WEEKS = {1: ("2026-08-31T00:00:00+02:00", "2026-09-07T00:00:00+02:00"),
         2: ("2026-09-07T00:00:00+02:00", "2026-09-14T00:00:00+02:00")}
NOW = datetime.fromisoformat("2026-09-02T12:00:00+02:00")
HISTORY = ({"role": "user", "content": "Use recorded counts carefully."},
           {"role": "assistant", "content": "Counts describe participation, not understanding."})
METRICS = ("resource_views", "video_clicks", "video_views", "mean_view_percent", "debate_posts", "debate_replies", "debate_views", "edited_characters",
           "network_replies_sent", "network_replies_received", "network_replies_unique_sent", "network_replies_unique_received",
           "network_views_sent", "network_views_received", "network_views_unique_sent", "network_views_unique_received", "goals_record_count", "reflections_record_count")
TRACES = {}


def snapshot(tables=None, version="SYNTHETIC_SNAPSHOT_1", specs_override=None, calendars=True):
    specs = {}
    for name, columns in FIX["columns"].items():
        kind = "timestamp" if name == "moodle" else "cumulative" if name == "features" else "week"
        week_col = "Observation_week" if name == "echo" else "week" if "network" in name else "Week"
        coverage = tuple(Coverage(("SYN_A", "SYN_B"), course, WEEKS[1][0], WEEKS[2][1], METRICS, "SYNTHETIC_COMPLETE_COLLECTION") for course in ("COURSE_A", "COURSE_B"))
        specs[name] = SourceSpec(tuple(columns), course_column="Course", observation=kind,
                                time_column="Time" if name == "moodle" else None,
                                week_column=week_col, calendar_version="SYNTHETIC_CALENDAR_V1",
                                item_column="Item_ID" if name in {"echo", "moodle"} else None,
                                event_id_column="Event_ID" if "Event_ID" in columns else None,
                                coverage=coverage)
    specs.update(specs_override or {})
    cal = Calendar("SYNTHETIC_CALENDAR_V1", "Europe/Oslo", WEEKS)
    return Snapshot(version, FIX["tables"] if tables is None else tables, specs,
                    {"SYN_A": ("COURSE_A", "COURSE_B"), "SYN_B": ("COURSE_A",)},
                    {"COURSE_A": cal, "COURSE_B": cal} if calendars else {}, "SYNTHETIC")


def scope(snap, learner="SYN_A", course="COURSE_A", week=1, item=None, calendar=True):
    return Scope(learner, course, snap.version, *WEEKS[week], "Europe/Oslo",
                 "SYNTHETIC_CALENDAR_V1" if calendar else None, item)


def prepare(snap=None, query="summarise my learning this week", page="Lecture", mode=C4Mode.C1_EVIDENCE,
            scoped=None, service=None, now=NOW, messages=HISTORY, key=None, budget=12000):
    snap = snap or snapshot()
    scoped = scoped or scope(snap)
    request = build_scoped_request(snapshot=snap, scope=scoped, query=query, page=page,
                                   mode=mode, now=now, messages=messages)
    service = service or build_scoped_evidence_service(enabled=True, snapshot=snap, token_budget=budget)
    prepared = service.prepare_generation_request(request)
    assert prepared.success, prepared.error
    assert not prepared.generation_sent
    assert service.dependencies.generator.execution_authorised is False
    assert service.dependencies.generator.transport_call_count == 0
    assert prepared.route is prepared.course_rag is prepared.learner_memory is prepared.planner_result is None
    assert not any("TOKEN_BUDGET_EXCLUDED" in v for v in prepared.compiled_evidence.limitations)
    user = json.loads(prepared.provider_generation_payload["messages"][1]["content"])
    if key:
        TRACES[key] = fact_to_request_trace(snap, request, prepared)
    return user, prepared, request


def facts(user):
    result = {}
    for record in user["evidence"]["evidence"]:
        for domain, metrics in record["content"].get("activity", {}).items():
            for metric, fact in metrics.items():
                assert metric not in result, "Repeated metric across Overview/detail views: " + metric
                result[metric] = fact
    return result


def visible(user):
    return next(r["content"] for r in user["evidence"]["evidence"] if r["source"] == "current_page_context")


class Acceptance(unittest.TestCase):
    def test_hand_arithmetic_all_four_scopes(self):
        snap = snapshot()
        for learner, course, week, expected in [
            ("SYN_A", "COURSE_A", 1, "A_COURSE_A_W1"), ("SYN_A", "COURSE_A", 2, "A_COURSE_A_W2"),
            ("SYN_B", "COURSE_A", 1, "B_COURSE_A_W1"), ("SYN_A", "COURSE_B", 1, "A_COURSE_B_W1")]:
            user, _, _ = prepare(snap, query="Summarise my learning", scoped=scope(snap, learner, course, week), key=expected)
            fs = facts(user)
            for metric, value in EXPECTED[expected].items():
                self.assertEqual(fs[metric]["value"], value)
                self.assertEqual(fs[metric]["status"], "OBSERVED")

    def test_explicit_comparison_with_week_and_course_words(self):
        user, _, _ = prepare(query="Compare my Lecture and Debate activity in week 1 for this course.", key="cross_domain_week")
        fs = facts(user)
        self.assertEqual(fs["debate_posts"]["value"], 2)
        self.assertNotIn("resource_views", fs)
        self.assertNotIn("edited_characters", fs)

    def test_single_domain_questions_are_focused(self):
        for page, query, metric, value in [
            ("Resources", "How many resource views?", "resource_views", 3),
            ("Lecture", "What is my completion rate for this lecture?", "mean_view_percent", 40),
            ("Debate", "How many debate posts?", "debate_posts", 2),
            ("Reflection", "How many reflection characters?", "edited_characters", 150)]:
            snap = snapshot()
            user, _, _ = prepare(snap, query=query, page=page, scoped=scope(snap, item="V1" if page == "Lecture" else None), key="specific_" + page)
            self.assertEqual(facts(user)[metric]["value"], value)
            self.assertEqual(set(visible(user)["activity"]), {page})
            self.assertEqual(len(user["evidence"]["evidence"]), 1)

    def test_common_baseline_rows_calculations_and_history_survive(self):
        for page in PAGES:
            for query in ("Summarise my learning", "Compare all four dashboard areas", "How many lecture views?"):
                baseline, _, _ = prepare(query=query, page=page, mode=C4Mode.C0_ORIGINAL)
                cross, _, _ = prepare(query=query, page=page)
                self.assertEqual(visible(baseline), visible(cross))
                self.assertEqual(baseline["visible_conversation_history"], cross["visible_conversation_history"])
        lecture = visible(prepare(query="Summarise my learning")[0])
        self.assertEqual(lecture["recording_rows"][1]["video_views"], 4)
        self.assertEqual(lecture["view_percent_calculation"], {"numerator": 120, "denominator": 2,
            "rule": "Mean over all scoped tracked rows with valid percentages; unavailable if any value is missing."})

    def test_overview_derives_exactly_once_and_may_have_no_intervention(self):
        base, _, _ = prepare(page="Overview", mode=C4Mode.C0_ORIGINAL)
        cross, prepared, request = prepare(page="Overview", key="Overview_no_added_intervention")
        self.assertEqual(base, cross)
        self.assertEqual(set(visible(cross)["activity"]), set(DOMAINS))
        self.assertEqual(facts(cross)["video_views"]["value"], 6)
        self.assertNotIn("total_activity", facts(cross))
        self.assertFalse(fact_to_request_trace(snapshot(), request, prepared)["added_factual_intervention"])

    def test_duplicate_event_id_is_deduplicated_and_conflicts_rejected(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"].append(copy.deepcopy(tables["moodle"][0]))
        self.assertEqual(facts(prepare(snapshot(tables))[0])["resource_views"]["value"], 3)
        tables["moodle"][-1]["Event"] = "Debate_posts"
        user, _, _ = prepare(snapshot(tables), key="conflicting_event_id")
        self.assertIsNone(facts(user)["resource_views"]["value"])
        self.assertEqual(facts(user)["resource_views"]["status"], "CONFLICTING_EVENT_ID")

    def test_equal_four_fields_isolate_learners_in_one_service(self):
        snap = snapshot()
        service = build_scoped_evidence_service(enabled=True, snapshot=snap)
        a, _, ar = prepare(snap, service=service, scoped=scope(snap))
        b, _, br = prepare(snap, service=service, scoped=scope(snap, learner="SYN_B"))
        self.assertEqual(ar.primary_input.to_payload(), br.primary_input.to_payload())
        self.assertEqual(facts(a)["debate_posts"]["value"], 2)
        self.assertEqual(facts(b)["debate_posts"]["value"], 8)
        self.assertFalse(hasattr(service.dependencies.evidence_synthesiser, "_cache"))

    def test_snapshot_version_isolation_with_equal_four_fields(self):
        tables = copy.deepcopy(FIX["tables"])
        extra = dict(tables["moodle"][0], Event="Debate_posts", Activity="Debate", Event_ID="NEW_SNAPSHOT_EVENT")
        tables["moodle"].append(extra)
        first, second = snapshot(), snapshot(tables, version="SYNTHETIC_SNAPSHOT_2")
        a, _, ar = prepare(first)
        b, _, br = prepare(second)
        self.assertEqual(ar.primary_input.to_payload(), br.primary_input.to_payload())
        self.assertEqual(facts(a)["debate_posts"]["value"], 2)
        self.assertEqual(facts(b)["debate_posts"]["value"], 3)
        with self.assertRaises(ScopeError):
            build_scoped_evidence_service(enabled=True, snapshot=second).prepare_generation_request(ar)

    def test_input_mutation_cannot_change_immutable_snapshot(self):
        tables = copy.deepcopy(FIX["tables"])
        snap = snapshot(tables)
        tables["moodle"].clear()
        self.assertEqual(facts(prepare(snap)[0])["resource_views"]["value"], 3)
        with self.assertRaises(TypeError):
            snap.tables["moodle"][0]["ID"] = "OTHER"

    def test_unknown_ids_and_cross_course_authorisation_rejected(self):
        snap = snapshot()
        for learner, course in (("Display Name", "COURSE_A"), ("UNKNOWN", "COURSE_A"), ("SYN_B", "COURSE_B")):
            with self.assertRaises(ScopeError):
                prepare(snap, scoped=scope(snap, learner, course))

    def test_same_learner_other_course_or_week_perturbation_does_not_change_request(self):
        tables = copy.deepcopy(FIX["tables"])
        for row in tables["moodle"]:
            if row["Course"] == "COURSE_B" or row["Week"] == 2:
                row["Event"] = "Resources_views"
                row["Time"] = "2026-09-08T18:00:00+02:00" if row["Week"] == 2 else row["Time"]
        for row in tables["gdocs"]:
            if row["Course"] == "COURSE_B" or row["Week"] == 2:
                row["absStrCount"] = 999999
        self.assertEqual(prepare(snapshot())[0], prepare(snapshot(tables))[0])

    def test_filtering_precedes_parsing_unrelated_rows(self):
        tables = copy.deepcopy(FIX["tables"])
        for row in tables["moodle"]:
            if row["ID"] == "SYN_B" or row["Course"] == "COURSE_B":
                row["Time"] = "INVALID_UNRELATED_TIME"
        self.assertEqual(prepare(snapshot())[0], prepare(snapshot(tables))[0])

    def test_start_inclusive_end_exclusive_timestamps(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] += [dict(tables["moodle"][0], Event_ID="BOUNDARY_START", Time=WEEKS[1][0]),
                             dict(tables["moodle"][0], Event_ID="BOUNDARY_END", Time=WEEKS[1][1])]
        self.assertEqual(facts(prepare(snapshot(tables))[0])["resource_views"]["value"], 4)

    def test_missing_and_observed_zero_are_distinct_in_payload(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = None
        absent = facts(prepare(snapshot(tables))[0])["resource_views"]
        tables["moodle"] = []
        zero = facts(prepare(snapshot(tables))[0])["resource_views"]
        self.assertIsNone(absent["value"])
        self.assertEqual(zero["value"], 0)
        self.assertEqual(zero["status"], "OBSERVED_ZERO")
        self.assertNotEqual(absent, zero)

    def test_empty_without_coverage_is_not_zero(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = []
        spec = replace(snapshot().specs["moodle"], coverage=())
        f = facts(prepare(snapshot(tables, specs_override={"moodle": spec}))[0])["resource_views"]
        self.assertIsNone(f["value"])
        self.assertEqual(f["status"], "NO_OBSERVATIONS_COVERAGE_UNKNOWN")

    def test_coverage_for_another_metric_cannot_establish_zero(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = []
        old = snapshot().specs["moodle"]
        spec = replace(old, coverage=tuple(replace(c, metrics=("resource_views",)) for c in old.coverage))
        fs = facts(prepare(snapshot(tables, specs_override={"moodle": spec}))[0])
        self.assertEqual(fs["resource_views"]["value"], 0)
        self.assertIsNone(fs["debate_posts"]["value"])

    def test_cumulative_features_do_not_override_window(self):
        fs = facts(prepare()[0])
        self.assertEqual(fs["debate_posts"]["value"], 2)
        self.assertEqual(fs["edited_characters"]["value"], 150)
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = None
        self.assertIsNone(facts(prepare(snapshot(tables))[0])["debate_posts"]["value"])

    def test_matching_interval_features_can_fill_only_matching_metric(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = None
        tables["features"] = [{"ID": "SYN_A", "Course": "COURSE_A", "Resources_views": 13, "Debate_posts": 888}]
        spec = replace(snapshot().specs["features"], observation="interval", interval=WEEKS[1], metric_semantics=("resource_views",))
        fs = facts(prepare(snapshot(tables, specs_override={"features": spec}))[0])
        self.assertEqual(fs["resource_views"]["value"], 13)
        self.assertIsNone(fs["debate_posts"]["value"])

    def test_echo_content_week_cannot_be_watching_week(self):
        spec = replace(snapshot().specs["echo"], observation="content_week", time_column=None, week_column=None)
        tables = copy.deepcopy(FIX["tables"])
        # One cumulative row per recording, as in the original Echo schema;
        # do not add separate snapshot rows for the same recording.
        tables["echo"] = [r for r in tables["echo"] if r["Observation_week"] == 1]
        user, _, _ = prepare(snapshot(tables, specs_override={"echo": spec}), key="echo_cumulative_limit")
        fs = facts(user)
        self.assertEqual(fs["video_views"]["status"], "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")
        self.assertIsNone(fs["video_views"]["value"])
        self.assertEqual(fs["cumulative_video_views"]["value"], 6)
        self.assertEqual(fs["cumulative_video_views"]["time_basis"], "cumulative_snapshot")
        self.assertEqual(fs["video_clicks"]["value"], 2)

    def test_missing_calendar_for_relative_week_requests_clarification(self):
        snap = snapshot(calendars=False)
        with self.assertRaises(ClarificationRequired):
            prepare(snap, scoped=scope(snap, calendar=False))
        with self.assertRaises(ClarificationRequired):
            prepare(now=None)

    def test_query_period_conflict_requests_clarification(self):
        with self.assertRaises(ClarificationRequired):
            prepare(query="Compare Lecture and Debate in week 2")

    def test_current_lecture_requires_unambiguous_identity(self):
        with self.assertRaises(ClarificationRequired):
            prepare(query="What is my completion rate for this lecture?")
        snap = snapshot()
        with self.assertRaises(ClarificationRequired):
            prepare(snap, query="What is my completion rate for this lecture?", scoped=scope(snap, item="UNKNOWN"))
        tables = copy.deepcopy(FIX["tables"])
        tables["echo"][1]["Item_ID"] = "V1"
        with self.assertRaises(ClarificationRequired):
            prepare(snapshot(tables), query="What is my completion rate for this lecture?", scoped=scope(snap, item="V1"))

    def test_no_course_column_requires_verified_single_course_manifest(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = [{k: v for k, v in r.items() if k != "Course"} for r in tables["moodle"] if r["Course"] == "COURSE_A"]
        old = snapshot().specs["moodle"]
        spec = replace(old, columns=tuple(c for c in old.columns if c != "Course"), course_column=None)
        unknown = facts(prepare(snapshot(tables, specs_override={"moodle": spec}))[0])["resource_views"]
        self.assertIsNone(unknown["value"])
        self.assertEqual(unknown["status"], "UNVERIFIED_COURSE_SCOPE")
        spec = replace(spec, single_course="COURSE_A", course_binding_evidence="SYNTHETIC_SIGNED_COURSE_MANIFEST")
        self.assertEqual(facts(prepare(snapshot(tables, specs_override={"moodle": spec}))[0])["resource_views"]["value"], 3)

    def test_network_filtering_and_no_counterparty_identity_in_final(self):
        user, _, request = prepare()
        fs = facts(user)
        for prefix in ("network_replies_", "network_views_"):
            for metric, value in EXPECTED["A_NETWORK_COURSE_A_W1"].items():
                self.assertEqual(fs[prefix + metric]["value"], value)
        text = canonical(user)
        for private in ("SYN_A", "SYN_B", "COURSE_A", "SYNTHETIC_PRIVATE_TEXT", "source_row_spans", "fact_id", "gold", "snapshot"):
            self.assertNotIn(private, text)
        self.assertEqual(set(request.primary_input.to_payload()), {"current_query", "current_page", "dashboard_context", "visible_conversation_history"})

    def test_optional_text_scoped_before_counting_never_invented_from_chars(self):
        user, _, _ = prepare()
        fs = facts(user)
        self.assertEqual(fs["goals_record_count"]["value"], 1)
        self.assertEqual(fs["reflections_record_count"]["value"], 1)
        self.assertNotIn("SYNTHETIC_PRIVATE_TEXT", canonical(user))
        tables = copy.deepcopy(FIX["tables"])
        tables["goals"].append({"ID": "SYN_B", "Course": "COURSE_A", "Week": 1, "text": "OTHER_PERSON"})
        tables["reflections"].append({"ID": "SYN_A", "Course": "COURSE_A", "Week": 2, "text": "OTHER_WEEK"})
        self.assertEqual(user, prepare(snapshot(tables))[0])

    def test_missing_metric_values_do_not_become_zero(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["gdocs"][0]["absStrCount"] = None
        tables["echo"][0]["Video View %"] = 300
        fs = facts(prepare(snapshot(tables))[0])
        self.assertIsNone(fs["edited_characters"]["value"])
        self.assertIsNone(fs["mean_view_percent"]["value"])

    def test_strict_loader_missing_sources_and_binary_never_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = SourceSpec(("ID", "Event"))
            snap = load_csv_snapshot(version="LIVE_NO_SOURCES", paths={"moodle": Path(tmp) / "missing.csv"},
                                     specs={"moodle": spec}, roster={"SYN_A": ("COURSE_A",)}, source_root=tmp)
            user, _, _ = prepare(snap, query="Summarise my learning", scoped=scope(snap, calendar=False))
            self.assertTrue(all(f["value"] is None for f in facts(user).values()))
            binary = Path(tmp) / "untrusted.pkl"
            binary.write_bytes(b"THIS IS NOT A TRUSTED PICKLE")
            snap = load_csv_snapshot(version="LIVE_BINARY", paths={"moodle": binary}, specs={"moodle": spec},
                                     roster={"SYN_A": ("COURSE_A",)}, source_root=tmp)
            self.assertEqual(snap.specs["moodle"].status, "BINARY_SOURCE_NOT_SAFELY_READABLE")

    def test_strict_loader_verifies_hash_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.csv"
            path.write_text("ID,Course,Time,Event\nSYN_A,COURSE_A,2026-09-01T10:00:00+02:00,Resources_views\n")
            spec = SourceSpec(("ID", "Course", "Time", "Event"), course_column="Course", observation="timestamp", time_column="Time",
                              source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            kwargs = dict(version="CSV_VERSION", paths={"moodle": path}, specs={"moodle": spec},
                          roster={"SYN_A": ("COURSE_A",)}, source_root=tmp)
            snap = load_csv_snapshot(**kwargs)
            user, _, _ = prepare(snap, query="Resource views", page="Resources", scoped=scope(snap, calendar=False))
            self.assertEqual(facts(user)["resource_views"]["value"], 1)
            path.write_text(path.read_text() + "TAMPER")
            with self.assertRaises(ScopeError):
                load_csv_snapshot(**kwargs)

    def test_feature_gate_construction_transport_and_legacy_config(self):
        self.assertFalse(scoped_evidence_enabled(environ={}))
        self.assertTrue(scoped_evidence_enabled(environ={"ENABLE_C4_SCOPED_EVIDENCE_V1": "true"}))
        with self.assertRaises(ScopeError):
            build_scoped_evidence_service(enabled=False, snapshot=snapshot())
        service = build_scoped_evidence_service(enabled=True, snapshot=snapshot())
        _, _, request = prepare()
        with self.assertRaises(RuntimeError):
            service.execute(request)
        legacy = C4RealEvidenceSynthesisAdapter(dashboard_data=None)
        legacy_request = replace(request, dashboard_context={"reviewed": "pack"})
        self.assertEqual(legacy.synthesise(request=legacy_request, primary_input=legacy_request.primary_input).status, "FROZEN_OUTPUT_LEVEL_PACK")
        source = (args.source_root / "utils/c4_real_factory.py").read_text()
        self.assertIn("C4RealEvidenceSynthesisAdapter(dashboard_data=None)", source)

    def test_compiler_rejects_unsafe_injected_context_and_budget_loss(self):
        snap = snapshot()
        _, _, req = prepare(snap)
        bad = replace(req, dashboard_context={"raw_all_learners": [{"ID": "SYN_B"}]})
        service = build_scoped_evidence_service(enabled=True, snapshot=snap)
        self.assertFalse(service.prepare_generation_request(bad).success)
        small = build_scoped_evidence_service(enabled=True, snapshot=snap, token_budget=512)
        self.assertFalse(small.prepare_generation_request(req).success)

    def test_ui_five_views_share_chart_scope_and_final_request(self):
        class FakeStreamlit:
            def __init__(self, page):
                self.page, self.session_state = page, {}
            def radio(self, label, choices, **kwargs):
                assert tuple(choices) == PAGES
                return self.page
            def selectbox(self, label, choices, **kwargs):
                return 1 if label == "Activity period" else 0
            def chat_input(self, text):
                return "Summarise my learning this week"
            def __getattr__(self, name):
                return lambda *args, **kwargs: None
        for page in PAGES:
            result = render_scoped_dashboard(FakeStreamlit(page), ScopedUIBinding(snapshot(), "SYN_A"), now=NOW)
            self.assertTrue(result["prepared"].success)
            self.assertEqual(result["request"].dashboard_scope, result["scope"])
            self.assertEqual(result["request"].dashboard_context, result["visible_context"])
            user = json.loads(result["prepared"].provider_generation_payload["messages"][1]["content"])
            self.assertEqual(facts(user)["edited_characters"]["value"], 150)
        path = next((args.source_root / "pages").glob("1 - *Individual Feedback.py"))
        tree = ast.parse(path.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pull_feedback")
        self.assertIn("render_scoped_dashboard", ast.unparse(fn.body[1]))
        self.assertTrue(any(isinstance(n, ast.Return) for n in ast.walk(fn.body[1])))

    def test_no_forbidden_operations_or_model_imports(self):
        self.assertEqual(BLOCKED, [])

    def test_direct_service_cannot_bypass_query_time_checks(self):
        snap = snapshot()
        _, _, request = prepare(snap)
        changed = replace(request, current_query="Compare Lecture and Debate in week 2")
        with self.assertRaises(ClarificationRequired):
            build_scoped_evidence_service(enabled=True, snapshot=snap).prepare_generation_request(changed)

    def test_stale_or_ambiguous_ui_identity_binding_is_rejected(self):
        binding = ScopedUIBinding(snapshot(), "SYN_A")
        identities = [{"AppName": "Display A", "ID": "SYN_A"}, {"AppName": "Display B", "ID": "SYN_B"}]
        self.assertIs(checked_ui_binding(binding, "Display A", identities), binding)
        self.assertIsNone(checked_ui_binding(binding, "Display B", identities))
        self.assertIsNone(checked_ui_binding(binding, "Missing", identities))
        self.assertIsNone(checked_ui_binding(binding, "Display A", identities + [identities[0]]))

    def test_every_selected_table_and_core_metric_affects_final_request(self):
        mutations = [("moodle", "video_clicks", "Video_views"), ("moodle", "debate_replies", "Debate_replies"),
                     ("moodle", "debate_views", "Debate_views"), ("reply_network", "network_replies_sent", None),
                     ("view_network", "network_views_sent", None), ("goals", "goals_record_count", None),
                     ("reflections", "reflections_record_count", None)]
        baseline = facts(prepare()[0])
        for table, metric, event in mutations:
            tables = copy.deepcopy(FIX["tables"])
            if event:
                tables[table].append(dict(tables[table][0], Event=event, Event_ID="EXTRA_METRIC_EVENT"))
            elif "network" in table:
                tables[table][0]["count"] += 1
            else:
                tables[table].append(dict(tables[table][0]))
            user, _, _ = prepare(snapshot(tables), key="perturb_" + metric)
            self.assertEqual(facts(user)[metric]["value"], baseline[metric]["value"] + 1)
        tables = copy.deepcopy(FIX["tables"])
        tables["echo"][0]["Video View %"] += 20
        self.assertEqual(facts(prepare(snapshot(tables))[0])["mean_view_percent"]["value"], 70)

    def test_empty_bad_schema_cannot_become_observed_zero(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["gdocs"] = []
        spec = replace(snapshot().specs["gdocs"], columns=("ID", "Course", "Week"))
        f = facts(prepare(snapshot(tables, specs_override={"gdocs": spec}))[0])["edited_characters"]
        self.assertEqual(f["status"], "INVALID_METRIC_SCHEMA")
        self.assertIsNone(f["value"])

    def test_partial_coverage_and_partial_week_are_not_complete(self):
        spec = replace(snapshot().specs["moodle"], coverage=())
        user, _, _ = prepare(snapshot(specs_override={"moodle": spec}))
        self.assertEqual(facts(user)["resource_views"]["status"], "OBSERVED_PARTIAL_COVERAGE")
        self.assertEqual(next(r["content"]["coverage"]["Resources"] for r in user["evidence"]["evidence"] if "Resources" in r["content"]["coverage"]), "PARTIAL")
        snap = snapshot()
        partial = replace(scope(snap), start="2026-09-01T00:00:00+02:00")
        fs = facts(prepare(snap, query="Summarise my learning", scoped=partial)[0])
        self.assertEqual(fs["resource_views"]["value"], 3)
        self.assertEqual(fs["video_views"]["status"], "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")

    def test_duplicate_cumulative_snapshots_are_not_summed(self):
        spec = replace(snapshot().specs["echo"], observation="content_week", time_column=None, week_column=None)
        fs = facts(prepare(snapshot(specs_override={"echo": spec}))[0])
        self.assertIsNone(fs["cumulative_video_views"]["value"])
        self.assertEqual(fs["cumulative_video_views"]["status"], "AMBIGUOUS_CUMULATIVE_RECORDING")

    def test_absent_sources_each_have_final_coverage(self):
        tables = {k: None for k in FIX["tables"]}
        for page in PAGES:
            user, _, _ = prepare(snapshot(tables), page=page)
            fs = facts(user)
            self.assertTrue(all(f["value"] is None for f in fs.values()))
            coverage = {k: v for r in user["evidence"]["evidence"] for k, v in r["content"]["coverage"].items()}
            self.assertEqual(coverage, {p: "UNAVAILABLE" for p in DOMAINS})

    def test_invalid_and_timezone_ambiguous_timestamps_unavailable(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"][0]["Time"] = "2026-09-01T10:00:00"
        fs = facts(prepare(snapshot(tables))[0])
        self.assertEqual(fs["resource_views"]["status"], "UNVERIFIED_TIMESTAMP_TIMEZONE")
        tables["moodle"][0]["Time"] = "INVALID_TIME"
        fs = facts(prepare(snapshot(tables))[0])
        self.assertEqual(fs["resource_views"]["status"], "INVALID_OBSERVATION_TIME")

    def test_feature_interval_or_duplicate_identity_cannot_override(self):
        tables = copy.deepcopy(FIX["tables"])
        tables["moodle"] = None
        old = snapshot().specs["features"]
        spec = replace(old, observation="interval", interval=WEEKS[1], metric_semantics=("resource_views",))
        fs = facts(prepare(snapshot(tables, specs_override={"features": spec}))[0])
        self.assertIsNone(fs["resource_views"]["value"])
        tables["features"] = [tables["features"][0]]
        spec = replace(spec, interval=WEEKS[2])
        fs = facts(prepare(snapshot(tables, specs_override={"features": spec}))[0])
        self.assertIsNone(fs["resource_views"]["value"])

    def test_atomic_trace_points_to_actual_final_values(self):
        _, prepared, request = prepare(key="atomic_lineage")
        trace = fact_to_request_trace(snapshot(), request, prepared)
        user = json.loads(prepared.provider_generation_payload["messages"][1]["content"])
        for fact in trace["facts"]:
            value = user
            for segment in fact["final_json_pointer_inside_user_message"].split("/")[1:]:
                value = value[int(segment)] if isinstance(value, list) else value[segment]
            self.assertEqual(value["value"], fact["value"])
            self.assertTrue(fact["final_value_verified"])
            self.assertEqual(len(fact["source_table_content_sha256"]), 64)

    def test_current_page_chart_distributions_preserved_with_totals(self):
        for page, expected in (("Resources", 3), ("Lecture", 2), ("Debate", 7), ("Reflection", 150)):
            base = prepare(page=page, mode=C4Mode.C0_ORIGINAL)[0]
            cross = prepare(page=page)[0]
            records = visible(cross)["activity_patterns"]["records"]
            self.assertEqual(sum(r["value"] for r in records), expected)
            self.assertTrue(all(r["observation_week"] == 1 for r in records))
            self.assertEqual(visible(base), visible(cross))

    def test_recording_calculations_retain_denominators_and_missingness(self):
        current = visible(prepare()[0])
        calc = current["recording_calculations"]["mean_among_viewed_real_recordings"]
        self.assertEqual(calc, {"numerator": 120, "denominator": 2, "value": 60})
        tables = copy.deepcopy(FIX["tables"])
        tables["echo"][0]["Video View %"] = 300
        current = visible(prepare(snapshot(tables))[0])
        self.assertIsNone(current["recording_rows"][0]["view_percent"])
        self.assertIsNone(current["recording_calculations"]["mean_across_real_recordings"]["value"])


QUERIES = {"summary_en": "summarise my learning this week", "advice_en": "how can I improve my learning?",
           "summary_zh": "帮我总结一下本周的学习情况", "advice_zh": "我应该如何改进我的学习？"}


def broad_case(page, query):
    def test(self):
        user, _, _ = prepare(query=query, page=page, key="broad_" + page + "_" + query)
        fs = facts(user)
        for metric, value in EXPECTED["A_COURSE_A_W1"].items():
            self.assertEqual(fs[metric]["value"], value)
        coverage = {}
        for record in user["evidence"]["evidence"]:
            coverage.update(record["content"]["coverage"])
        self.assertEqual(set(coverage), set(DOMAINS))
    return test


for page in PAGES:
    for label, query in QUERIES.items():
        setattr(Acceptance, "test_broad_" + page + "_" + label, broad_case(page, query))


def perturb_case(domain, page):
    def test(self):
        tables = copy.deepcopy(FIX["tables"])
        metric = {"Resources": "resource_views", "Lecture": "video_views", "Debate": "debate_posts", "Reflection": "edited_characters"}[domain]
        if domain in {"Resources", "Debate"}:
            event = "Resources_views" if domain == "Resources" else "Debate_posts"
            tables["moodle"].append(dict(tables["moodle"][0], Event=event, Activity=domain, Event_ID="SYNTHETIC_PERTURBATION"))
        elif domain == "Lecture":
            tables["echo"][0]["Video Views"] += 1
        else:
            tables["gdocs"][0]["absStrCount"] += 1
        for query in QUERIES.values():
            before = prepare(query=query, page=page)[0]
            after = prepare(snapshot(tables), query=query, page=page)[0]
            self.assertEqual(facts(after)[metric]["value"], facts(before)[metric]["value"] + 1)
        if domain != "Lecture":
            # Relevant source changes affect broad requests but leave a focused
            # Lecture baseline and its actual complete prepared payload unchanged.
            self.assertEqual(prepare(query="How many lecture views?")[0],
                             prepare(snapshot(tables), query="How many lecture views?")[0])
    return test


for page in PAGES:
    for domain in DOMAINS:
        setattr(Acceptance, "test_perturb_" + domain + "_from_" + page, perturb_case(domain, page))


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entries = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.entries.append({"case_id": test._testMethodName, "status": "PASS"})
    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.entries.append({"case_id": test._testMethodName, "status": "FAIL", "detail": self._exc_info_to_string(error, test)})
    def addError(self, test, error):
        super().addError(test, error)
        self.entries.append({"case_id": test._testMethodName, "status": "FAIL", "detail": self._exc_info_to_string(error, test)})


if __name__ == "__main__":
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance))
    stdout = stream.getvalue()
    (output / "TEST_STDOUT.txt").write_text(stdout)
    counts = {key: sum(r["status"] == key for r in result.entries) for key in ("PASS", "FAIL", "UNKNOWN")}
    (output / "FUNCTIONAL_ACCEPTANCE_RESULTS.json").write_text(json.dumps({"source_origin": "SYNTHETIC", "counts": counts,
        "tests_run": result.testsRun, "skips": len(result.skipped), "transport_call_count": 0,
        "forbidden_attempts": BLOCKED, "requirements": result.entries}, indent=2) + "\n")
    (output / "PAGE_FACT_TO_GENERATOR_TRACE.json").write_text(json.dumps({"source_origin": "SYNTHETIC_ONLY", "cases": TRACES}, ensure_ascii=False, indent=2) + "\n")
    closure = set()
    root = args.source_root.resolve()
    for module in list(sys.modules.values()):
        file = getattr(module, "__file__", None)
        if file and Path(file).resolve().is_relative_to(root) and file.endswith(".py"):
            rel = Path(file).resolve().relative_to(root).as_posix()
            if not rel.startswith("research_followups/"):
                closure.add(rel)
    (output / "RUNTIME_SOURCE_CLOSURE.json").write_text(json.dumps({"imported_python_files": sorted(closure)}, indent=2) + "\n")
    print(stdout)
    print(json.dumps(counts))
    raise SystemExit(0 if result.wasSuccessful() and not BLOCKED else 1)
