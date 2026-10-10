"""MODEL_AUTHORED / SYNTHETIC_DEVELOPMENT_FIXTURE / NOT_FOR_INDEPENDENT_TEST.

These objects are invented engineering cases. Expectations stay in a test-only
sidecar and are never passed to candidate/repair/validator APIs.
"""
from copy import deepcopy
import json
from pathlib import Path

LABELS = ["MODEL_AUTHORED", "SYNTHETIC_DEVELOPMENT_FIXTURE", "NOT_FOR_INDEPENDENT_TEST"]


def window(start="2026-09-07T09:00:00+02:00", end="2026-09-07T10:00:00+02:00"):
    return dict(start=start, end=end)


def source(personal=True):
    return dict(source_id="source-demo", version="v1", learner_id="learner-synthetic" if personal else None,
                course_id="course-synthetic", scope="LEARNER" if personal else "COURSE",
                session_id="prior-synthetic-session", span_id="synthetic-span-1", page="synthetic-course-page",
                observed_at="2026-09-06T08:00:00+02:00", valid_from="2026-09-01T00:00:00+02:00",
                valid_to="2026-09-30T00:00:00+02:00", superseded_by=None, access="GRANTED")


def baseline():
    inp = dict(schema_version="P0_DRAFT_V0",
        scope=dict(learner_id="learner-synthetic", course_id="course-synthetic", session_id="target-synthetic-session",
                   as_of="2026-09-06T10:00:00+02:00", timezone="Europe/Oslo",
                   horizon=window("2026-09-07T00:00:00+02:00", "2026-09-14T00:00:00+02:00")),
        context=dict(query="Prepare the synthetic practice task within the supplied time limits.", page="synthetic-course-page", visible_conversation=["Synthetic learner statement: continue my practice plan."]),
        goals=[dict(goal_id="goal-practice", text="Complete one synthetic practice exercise.", evidence_refs=["fact-goal"])],
        hard_constraints=dict(budget=dict(required=True, minutes=30),
            schedule=dict(required=True, allowed_windows=[window()], excluded_windows=[], forbidden_weekdays=[5, 6], non_overlap=True),
            forbid_completed_repeat=True, continue_active_plan=True, required_evidence_ids=["fact-goal"],
            task_prerequisites=[dict(task_id="task-practice", prerequisite_task_ids=["task-read"])]),
        soft_preferences=[dict(preference_id="prefer-sheet", kind="PREFERRED_RESOURCE", value="resource-sheet")],
        completed_tasks=[dict(task_id="task-read", evidence_refs=["fact-completion"])], review_permissions=[],
        active_plan=dict(plan_id="active-demo", goal_id="goal-practice", remaining_task_ids=["task-practice"], completed_task_ids=["task-read"], evidence_refs=["fact-goal"]),
        facts=[dict(fact_id="fact-goal", kind="LEARNER_MEMORY", fact_type="GOAL", value="Synthetic learner requested a practice exercise.", source_ref=source(), available=True),
               dict(fact_id="fact-completion", kind="DASHBOARD", fact_type="ACTIVITY", value="Synthetic task-read is explicitly marked completed; this is not mastery.", source_ref=source(), available=True)],
        resources=[dict(resource_id="resource-sheet", title="Synthetic permitted worksheet", source_ref=source(False), available=True)],
        source_versions=[dict(source_id="source-demo", version="v1")], missing_information=[])
    plan = dict(plan_id="plan-synthetic-1", goal_id="goal-practice", goal=inp["goals"][0]["text"],
        evidence_refs=["fact-goal"], continues_plan_id="active-demo", brief_rationale="Continue the supplied active practice task under explicit limits.",
        actions=[dict(step_id="step-1", task_id="task-practice", kind="TASK", action="Attempt the synthetic worksheet exercise.",
            estimated_duration=dict(value=20, unit="minutes", origin="SYNTHETIC_ESTIMATE", evidence_refs=[]),
            resource_ids=["resource-sheet"], dependencies=[], schedule=window("2026-09-07T09:00:00+02:00", "2026-09-07T09:20:00+02:00"),
            completion_check="Record a worked attempt and mark any unresolved question.", evidence_refs=["fact-goal", "fact-completion"], brief_rationale="The supplied state records the reading task as completed.")])
    return inp, plan


def build():
    cases = []

    def case(name, mutate=None, status="BOUNDED_REPAIR_EXHAUSTED", codes=(), repairs=0, candidates=None, enabled=True):
        inp, plan = baseline()
        if mutate:
            mutate(inp, plan)
        cases.append(dict(case_id=name, labels=LABELS, runtime_input=inp,
            mock_candidates=candidates if candidates is not None else [plan], max_repairs=repairs, planning_enabled=enabled,
            evaluation_only_sidecar=dict(expected_status=status, required_issue_codes=list(codes))))

    case("valid_plan", status="PASSED_ENCODED_CHECKS")
    case("budget_exceedance", lambda i,p: i["hard_constraints"]["budget"].update(minutes=10), codes=["BUDGET_EXCEEDED"])
    def weekend(i,p):
        i["hard_constraints"]["schedule"]["allowed_windows"].append(window("2026-09-12T09:00:00+02:00", "2026-09-12T10:00:00+02:00"))
        p["actions"][0]["schedule"] = window("2026-09-12T09:00:00+02:00", "2026-09-12T09:20:00+02:00")
    case("disallowed_weekend", weekend, codes=["FORBIDDEN_WEEKDAY"])
    case("missing_timezone", lambda i,p: i["scope"].update(timezone=None), status="NEEDS_INFORMATION", codes=["MISSING_TIMEZONE"])
    case("missing_duration", lambda i,p: p["actions"][0]["estimated_duration"].update(value=None), codes=["DURATION_UNKNOWN"])
    case("missing_budget", lambda i,p: i["hard_constraints"]["budget"].update(minutes=None), status="NEEDS_INFORMATION", codes=["BUDGET_UNKNOWN"])
    case("missing_windows", lambda i,p: i["hard_constraints"]["schedule"].update(allowed_windows=None), status="NEEDS_INFORMATION", codes=["ALLOWED_WINDOWS_UNKNOWN"])
    case("illegal_resource", lambda i,p: p["actions"][0].update(resource_ids=["resource-unpermitted"]), codes=["RESOURCE_NOT_PERMITTED"])
    case("evidence_scope_mismatch", lambda i,p: i["facts"][0]["source_ref"].update(learner_id="other-learner"), status="INVALID_INPUT", codes=["SOURCE_SCOPE_MISMATCH"])
    case("course_scope_mismatch", lambda i,p: i["resources"][0]["source_ref"].update(course_id="other-course"), status="INVALID_INPUT", codes=["SOURCE_SCOPE_MISMATCH"])
    def cycle(i,p):
        second=deepcopy(p["actions"][0]); second.update(step_id="step-2",task_id="task-extra",dependencies=["step-1"],schedule=window("2026-09-07T09:20:00+02:00","2026-09-07T09:40:00+02:00"))
        p["actions"][0]["dependencies"]=["step-2"]; p["actions"].append(second)
        i["hard_constraints"]["budget"]["minutes"]=60
    case("dependency_cycle", cycle, codes=["DEPENDENCY_CYCLE", "DEPENDENCY_ORDER"])
    def repeat(i,p):
        i["active_plan"]=None; i["hard_constraints"]["continue_active_plan"]=False
        p["continues_plan_id"]=None; p["actions"][0]["task_id"]="task-read"
    case("prohibited_completed_repeat", repeat, codes=["COMPLETED_TASK_REPEATED"])
    def review(i,p):
        repeat(i,p); p["actions"][0]["kind"]="REVIEW"
        i["review_permissions"]=[dict(task_id="task-read",evidence_refs=["fact-completion"],rationale="Synthetic learner explicitly permits review.")]
    case("legitimate_review", review, status="PASSED_ENCODED_CHECKS")
    case("soft_preference_unmet", lambda i,p: p["actions"][0].update(resource_ids=[]), status="PASSED_ENCODED_CHECKS", codes=["SOFT_PREFERENCE_UNMET"])
    case("no_explicit_slot", lambda i,p: i["hard_constraints"]["schedule"].update(allowed_windows=[]), status="INFEASIBLE_EXPLICIT_CONSTRAINTS", codes=["NO_ALLOWED_TIME_EXPLICIT"])
    case("all_slots_excluded", lambda i,p: i["hard_constraints"]["schedule"].update(excluded_windows=[window()]), status="INFEASIBLE_EXPLICIT_CONSTRAINTS", codes=["NO_ALLOWED_TIME_EXPLICIT"])
    case("missing_required_evidence", lambda i,p: i["hard_constraints"].update(required_evidence_ids=["absent-runtime-fact"]), status="NEEDS_INFORMATION", codes=["EVIDENCE_ID_MISSING"])
    _, valid=baseline(); invalid=deepcopy(valid); invalid["actions"][0]["resource_ids"]=["bad"]
    still_invalid=deepcopy(valid); still_invalid["actions"][0]["estimated_duration"]["value"]=50
    case("failed_repair_then_valid_repair", status="PASSED_ENCODED_CHECKS", repairs=2, candidates=[invalid,still_invalid,valid])
    case("one_repair_success", status="PASSED_ENCODED_CHECKS", repairs=1, candidates=[invalid,valid])
    case("repair_exhaustion", repairs=2, candidates=[invalid,still_invalid,invalid], codes=["RESOURCE_NOT_PERMITTED"])
    case("no_planning_bypass", status="BYPASSED_NO_PLANNING", enabled=False, candidates=[])
    case("valid_source_unsupported_claim", lambda i,p: p["actions"][0].update(action="This worksheet is guaranteed to raise the learner's final grade by 40 percent."), status="PASSED_ENCODED_CHECKS")
    case("source_version_stale", lambda i,p: i["facts"][0]["source_ref"].update(version="v0"), status="INVALID_INPUT", codes=["SOURCE_VERSION_STALE"])
    case("source_time_expired", lambda i,p: i["facts"][0]["source_ref"].update(valid_to="2026-09-05T00:00:00+02:00"), status="INVALID_INPUT", codes=["SOURCE_OUTSIDE_VALIDITY"])
    case("duplicate_step_id", lambda i,p: p["actions"].append(deepcopy(p["actions"][0])), codes=["DUPLICATE_ID"])
    case("missing_prerequisite", lambda i,p: i["hard_constraints"]["task_prerequisites"][0].update(prerequisite_task_ids=["unknown-task"]), codes=["TASK_PREREQUISITE_MISSING"])
    case("partial_exclusion", lambda i,p: i["hard_constraints"]["schedule"].update(excluded_windows=[window("2026-09-07T09:10:00+02:00","2026-09-07T09:15:00+02:00")]), codes=["SCHEDULE_EXCLUDED"])
    case("missing_required_field", lambda i,p: p["actions"][0].pop("completion_check"), codes=["REQUIRED_FIELD"])
    def unscheduled(i,p):
        i["hard_constraints"]["schedule"]["required"]=False
        i["hard_constraints"]["schedule"]["allowed_windows"]=None
        i["scope"]["timezone"]=None; i["scope"]["horizon"]=None
        p["actions"][0]["schedule"]=None
    case("explicit_unscheduled_output", unscheduled, status="PASSED_ENCODED_CHECKS")
    return cases


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_cases.json"
    target.write_text(json.dumps(dict(labels=LABELS, cases=build()), ensure_ascii=False, indent=2) + "\n")
