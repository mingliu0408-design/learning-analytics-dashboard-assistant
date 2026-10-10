#!/usr/bin/env python3
"""Build explicit E0 comparisons, source maps and pre-commit integrity receipts."""
from pathlib import Path
import ast
import csv
import hashlib
import json
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E0 = HERE.parent / "e0_crosspage_functional_check"
START = "4765e066bd512611cd7157098aa50a86d25e7ea8"
ORIGINAL_E0 = "79c3cb27bb8f4f888aa661c7b731483223c4aaa8"
CHERRY = "fdc58a8ca672a2ddb9a5c381fd7f73a38a2e2924"
PACKET = Path("/Users/liuming/Downloads/RQ3_REBUILD_E1_CODEX_TASK_PACKET_2026-09-06.zip")


def git(*argv):
    return subprocess.check_output(["git", *argv], cwd=ROOT).decode().strip()


def write_csv(name, fields, rows):
    with (HERE / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def reports():
    assert git("branch", "--show-current") == "research/rq3-rebuild-e1-five-page"
    assert git("rev-parse", "HEAD") == CHERRY
    assert git("rev-parse", "HEAD^") == START
    original = git("rev-parse", ORIGINAL_E0 + ":research_followups/rq3_rebuild/e0_crosspage_functional_check")
    cherry = git("rev-parse", CHERRY + ":research_followups/rq3_rebuild/e0_crosspage_functional_check")
    assert original == cherry
    with zipfile.ZipFile(PACKET) as z:
        assert z.testzip() is None
        manifest = json.loads(z.read("MANIFEST.json"))
        assert all(hashlib.sha256(z.read(m["path"])).hexdigest() == m["sha256"] and len(z.read(m["path"])) == m["bytes"] for m in manifest["members"])
    preflight = {"working_directory": str(ROOT), "branch": git("branch", "--show-current"),
                 "starting_head": START, "initial_tracked_and_untracked_status": "CLEAN_VERIFIED_BEFORE_ANY_WRITES",
                 "original_E0_commit": ORIGINAL_E0, "cherry_picked_E0_commit": CHERRY,
                 "E0_original_and_cherry_subtree": original, "E0_changes": "81 additions; output-only",
                 "input_zip_sha256": hashlib.sha256(PACKET.read_bytes()).hexdigest(),
                 "input_members_checked": len(manifest["members"]), "input_crc_and_hashes": "PASS",
                 "instruction_authority": "User directly requested execution of the two named attachment specifications; REFERENCES used as read-only evidence."}
    (HERE / "PREFLIGHT.json").write_text(json.dumps(preflight, indent=2) + "\n")

    trace = json.loads((HERE / "PAGE_FACT_TO_GENERATOR_TRACE.json").read_text())
    sample = trace["cases"]["A_COURSE_A_W1"]["facts"]
    profile = json.loads((HERE / "DATA_COVERAGE_PROFILE.json").read_text())
    legacy = {r["binding_field"]: r for r in profile["sources"] if r.get("location") == "known_legacy"}
    provenance = []
    for fact in sample:
        source = legacy.get(fact["table"], {})
        for view in (fact["domain"], "Overview"):
            provenance.append({"view": view, "metric": fact["metric"], "source_domain": fact["domain"],
                "source_table": fact["table"], "definition": fact["definition"],
                "time_basis": fact["time_basis"], "source_locator": source.get("path", "OPTIONAL_DI_ONLY"),
                "source_status": source.get("status", "NOT_BOUND"),
                "schema_authority": source.get("schema_authority", "EXPLICIT_SYNTHETIC_CONTRACT"),
                "local_profile_completed": source.get("actual_local_profiling", False),
                "scope_requirement": "Verified learner/course plus start-inclusive end-exclusive interval; complete metric coverage needed for empty-source zero.",
                "deduplication": "Derived alias; never added again" if view == "Overview" else "Event-ID deduplication within source/scope; no sum across systems",
                "implementation": "utils/c4_dashboard_scoped/aggregate.py::Aggregator." + fact["domain"].lower(),
                "live_binding": "LIVE_CONFIGURATION_UNCONFIRMED"})
    provenance += [
        {"view": "Lecture", "metric": "recording_rows / view_percent_calculation", "source_domain": "Lecture", "source_table": "echo",
         "definition": "All legally scoped recording row views/percentages/material weeks; arithmetic numerator and denominator retained in both modes.", "time_basis": "activity_window",
         "source_locator": legacy["echo"]["path"], "source_status": legacy["echo"]["status"], "schema_authority": "LOCAL_HEADERS_PLUS_SCOPED_CONTRACT",
         "local_profile_completed": True, "scope_requirement": "Observation window and unique requested item binding required", "deduplication": "Visible baseline item reused unchanged",
         "implementation": "utils/c4_dashboard_scoped/aggregate.py::Bundle.visible", "live_binding": "LIVE_CONFIGURATION_UNCONFIRMED"},
        {"view": "Reflection", "metric": "cohort comparison", "source_domain": "COHORT_CONTEXT", "source_table": "gdocs_ts",
         "definition": "Previous/current cohort series in legacy UI; not same-learner evidence and not bound in new raw mode.", "time_basis": "COHORT_DAY_INDEX",
         "source_locator": legacy["gdocs_ts"]["path"], "source_status": "EXCLUDED_FROM_PERSONAL_FACTS", "schema_authority": "VERIFIED_HEADERS",
         "local_profile_completed": True, "scope_requirement": "Separate authorised cohort manifest required; cannot be renamed learner progress", "deduplication": "Not included",
         "implementation": "Legacy pull_feedback only", "live_binding": "LIVE_CONFIGURATION_UNCONFIRMED"}]
    for domain in ("Resources", "Lecture", "Debate", "Reflection"):
        table = "gdocs" if domain == "Reflection" else "moodle"
        source = legacy[table]
        provenance.append({"view": domain, "metric": "activity_patterns", "source_domain": domain,
            "source_table": table, "definition": "Scoped event/character distributions by observed week/day/material week; no zero padding.",
            "time_basis": "activity_window", "source_locator": source["path"], "source_status": source["status"],
            "schema_authority": source.get("schema_authority", "COMMITTED_CODE_CONTRACT_ONLY"), "local_profile_completed": source["actual_local_profiling"],
            "scope_requirement": "Same Snapshot/Scope as totals and request", "deduplication": "A distribution of the same events, not an additional total",
            "implementation": "utils/c4_dashboard_scoped/aggregate.py::Bundle.visible", "live_binding": "LIVE_CONFIGURATION_UNCONFIRMED"})
    for view in ("Lecture", "Overview"):
        provenance.append({"view": view, "metric": "cumulative_video_views", "source_domain": "Lecture", "source_table": "echo",
            "definition": "Cumulative recording snapshot; not viewing activity in the requested window; repeated recording identity is unavailable.",
            "time_basis": "cumulative_snapshot", "source_locator": legacy["echo"]["path"], "source_status": "CONDITIONAL_CUMULATIVE_ONLY",
            "schema_authority": "VERIFIED_HEADERS", "local_profile_completed": True,
            "scope_requirement": "Validated learner/course/source snapshot; cannot support weekly viewing claims",
            "deduplication": "Never added to activity-window counts", "implementation": "utils/c4_dashboard_scoped/aggregate.py::Aggregator.lecture",
            "live_binding": "LIVE_CONFIGURATION_UNCONFIRMED"})
    write_csv("FIVE_VIEW_DATA_PROVENANCE.csv", list(provenance[0]), provenance)

    # Exact legacy UI mappings, including differences from synthesiser labels.
    legacy_ui = [
        ("Navigation", "Introduction / Resources / Lecture / Debate / Reflection / Next Steps", "pull_feedback", "Legacy UI has six labels; no Overview navigation. E1 opt-in has exactly five requested views."),
        ("Resources", "Total resource views", "features.Resources_views", "Cumulative feature; E1 uses scoped Moodle Resources_views event count."),
        ("Resources", "Daily-by-week line chart", "moodle.Event / Week / Day_of_week; compute_ped", "Legacy pads empty cells without explicit coverage; E1 does not infer missing zero."),
        ("Resources", "Content-week versus engaged-week heatmap", "moodle.Time / Week / Content_week; compute_delay", "Observation Week and Content_week differ; Time.count excludes missing time."),
        ("Resources", "Active weeks / event total / late weeks in feedback", "moodle.Resources_views; calculate_delay", "Legacy late labels also mark missing content as late; not defensible without coverage."),
        ("Lecture", "Total video views", "features.Video_views_sum", "Cumulative; only interval-equivalent features accepted in E1."),
        ("Lecture", "Recording bar x / colour / y", "echo.Video Views / Video View % / Class", "Content_week is material week, not time watched; current item needs identity."),
        ("Lecture", "Unique viewed / missed list / mean viewed percent in feedback", "echo grouped by Content_week; excludes week 3 for missed", "Legacy mixes row/week units and hard-coded exclusion; E1 states scoped per-row arithmetic instead."),
        ("Lecture", "Moodle video-click preparation", "moodle.Event == Video_views", "Separate from Echo view events; never added to Echo total."),
        ("Debate", "Network nodes / links / edge counts", "reply_network or view_network.From / To / count / week", "E1 exports only scoped counts; counterparty identities withheld."),
        ("Debate", "#posts", "reply_network.To == learner -> week.nunique in get_metrics", "Legacy label is weeks receiving edges, not posts; E1 counts Moodle Debate_posts and labels network metrics separately."),
        ("Debate", "#replies", "reply_network.count for outgoing non-self edges", "Separate network measurement; scoped before summing."),
        ("Debate", "#views", "view_network.count for outgoing edges", "Legacy includes self edges; E1 explicitly labels non-self network counts."),
        ("Debate", "#student replies / #student views", "distinct incoming From IDs in networks", "E1 scope then distinct positive non-self counterparties; no identities in model input."),
        ("Debate", "Feedback posts / replies / unique students / late list", "Moodle Event counts plus cumulative features and calculate_delay", "Legacy uses different bases than metric cards; E1 does not sum or silently relabel them."),
        ("Reflection", "Total strings in reflection", "features.Total_chars", "Characters, not strings/content or reflection quality."),
        ("Reflection", "Daily-by-week character chart", "gdocs.Week / dayOfWeek / absStrCount", "Original binary not safely read; code schema only; E1 synthetics explicitly cover it."),
        ("Reflection", "Personal daily curve", "gdocs.groupby(day).absStrCount.sum", "Code-derived definition; missing source cannot mean zero."),
        ("Reflection", "Previous cohorts / Your Cohort curves", "gdocs_ts.day / previousCohorts / currentCohort", "Independent cohort context; excluded from same-learner facts."),
        ("Overview", "Four compressed activity summaries", "evidence_synthesiser._summarise_overview -> four _summarise_* functions", "Synthesiser capability, not legacy UI navigation; E1 reuses the four scoped components once."),
    ]
    write_csv("ACTUAL_UI_METRIC_SOURCE_MAP.csv", ["view", "displayed_metric", "actual_source_and_calculation", "E1_handling"],
              [dict(zip(("view", "displayed_metric", "actual_source_and_calculation", "E1_handling"), r)) for r in legacy_ui])

    mapping = {
        "E01": "hand_arithmetic_all_four_scopes", "E02_broad_weekly": "broad_Lecture_summary_en", "E02_broad_improvement": "broad_Lecture_advice_en",
        "E02_lecture_metric": "single_domain_questions_are_focused", "E02_comparison": "explicit_comparison_with_week_and_course_words", "E02_all_pages": "overview_derives_exactly_once_and_may_have_no_intervention",
        "E03": "same_learner_other_course_or_week_perturbation_does_not_change_request", "E04_route": "explicit_comparison_with_week_and_course_words", "E04": "hand_arithmetic_all_four_scopes",
        "E05_student": "unknown_ids_and_cross_course_authorisation_rejected", "E05_week": "missing_calendar_for_relative_week_requests_clarification",
        "E06_activity": "missing_and_observed_zero_are_distinct_in_payload", "E06_feature": "cumulative_features_do_not_override_window", "E06_preparation": "absent_sources_each_have_final_coverage",
        "E07_broad_weekly": "perturb_Debate_from_Lecture", "E07_broad_improvement": "perturb_Debate_from_Lecture", "E07_lecture_metric": "perturb_Debate_from_Lecture", "E07_comparison": "every_selected_table_and_core_metric_affects_final_request",
        "E08": "equal_four_fields_isolate_learners_in_one_service", "E09": "snapshot_version_isolation_with_equal_four_fields", "E10_course": "no_course_column_requires_verified_single_course_manifest",
        "E10_text": "optional_text_scoped_before_counting_never_invented_from_chars", "E11": "cumulative_features_do_not_override_window", "E12": "ui_five_views_share_chart_scope_and_final_request",
        "E13_current_comparison": "common_baseline_rows_calculations_and_history_survive", "E13_current_all_pages": "common_baseline_rows_calculations_and_history_survive",
        "E13_current_lecture_metric": "common_baseline_rows_calculations_and_history_survive", "E13_proposed": "common_baseline_rows_calculations_and_history_survive",
        "E14_broad_weekly": "broad_Lecture_summary_en", "E14_broad_improvement": "broad_Lecture_advice_en", "E14_lecture_metric": "single_domain_questions_are_focused",
        "E14_comparison": "explicit_comparison_with_week_and_course_words", "E14_all_pages": "overview_derives_exactly_once_and_may_have_no_intervention"}
    acceptance = json.loads((HERE / "FUNCTIONAL_ACCEPTANCE_RESULTS.json").read_text())
    outcomes = {r["case_id"]: r["status"] for r in acceptance["requirements"]}
    comparisons = []
    for old in json.loads((E0 / "FUNCTIONAL_ACCEPTANCE_RESULTS.json").read_text())["requirements"]:
        case = "test_" + mapping[old["case_id"]]
        legacy_path = old["case_id"].startswith("E14")
        comparisons.append({"E0_case": old["case_id"], "requirement": old["requirement"], "E0_recorded_status": old["status"],
            "E0_rerun_in_E1": "NO", "original_path_after_E1": "LEGACY_UNCHANGED_NOT_RETESTED" if legacy_path else "ORIGINAL_ADAPTER_UNCHANGED; OPT_IN_SUCCESSOR_ADDED",
            "E1_versioned_path_status": outcomes[case], "E1_test": case,
            "boundary": "Ordinary C_FULL remains legacy; new scoped UI bypasses it for C0/C1 preparation" if legacy_path else "Synthetic final prepared-request acceptance only"})
    write_csv("BEFORE_AFTER_E0_REQUIREMENTS.csv", list(comparisons[0]), comparisons)

    # Hash evidence sources and protected baseline files without printing contents.
    referenced = set(json.loads((HERE / "RUNTIME_SOURCE_CLOSURE.json").read_text())["imported_python_files"])
    referenced.update(["utils/c4_real_factory.py", "utils/evidence_synthesiser.py", "utils/helper.py", "evaluation/assistant_modes.py"])
    referenced.update(str(p.relative_to(ROOT)) for p in (ROOT / "pages").glob("1 - *Individual Feedback.py"))
    sources = []
    for relative in sorted(referenced):
        if relative.startswith("utils/c4_dashboard_scoped/"):
            continue
        raw = (ROOT / relative).read_bytes()
        old = subprocess.check_output(["git", "show", START + ":" + relative], cwd=ROOT)
        sources.append({"path": relative, "starting_sha256": hashlib.sha256(old).hexdigest(),
                        "current_sha256": hashlib.sha256(raw).hexdigest(), "unchanged": raw == old})
    (HERE / "SOURCE_MANIFEST.json").write_text(json.dumps({"starting_head": START, "input_zip": preflight["input_zip_sha256"],
        "read_code_sources": sources, "raw_source_manifest": "DATA_COVERAGE_PROFILE.json", "E0_references": "Read-only committed subtree " + original}, indent=2) + "\n")
    changed_symbols = []
    for path in sorted((ROOT / "utils/c4_dashboard_scoped").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                changed_symbols.append({"file": str(path.relative_to(ROOT)), "symbol": node.name, "line": node.lineno})
    changed_symbols.append({"file": next((ROOT / "pages").glob("1 - *Individual Feedback.py")).relative_to(ROOT).as_posix(), "symbol": "pull_feedback", "line": 1226})
    (HERE / "CHANGED_SYMBOLS.json").write_text(json.dumps(changed_symbols, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"E0_subtree_identical": True, "provenance_rows": len(provenance), "legacy_UI_mapping_rows": len(legacy_ui),
                      "E0_comparison_rows": len(comparisons), "source_files_checked": len(sources), "E1_tests": acceptance["counts"]}))


if __name__ == "__main__":
    reports()
