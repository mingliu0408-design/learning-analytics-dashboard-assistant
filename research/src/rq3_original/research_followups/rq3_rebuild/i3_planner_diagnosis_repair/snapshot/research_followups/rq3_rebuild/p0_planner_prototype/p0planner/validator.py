"""Checks over explicit fields only; no semantic critic and no scheduler.

Intervals are half-open [start, end); weekdays use the explicit IANA timezone.
Source validity is checked at as_of, and resources also at scheduled use.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from .contracts import PlannerInput, ValidationResult
from .schema import load_schema, schema_errors

UTC = timezone.utc


class Report:
    def __init__(self):
        self.issues: list[dict] = []
        self.checks: list[dict] = []

    def add(self, code, path, message, severity="ERROR"):
        self.issues.append(dict(code=code, path=path, message=message, severity=severity))

    @contextmanager
    def group(self, name):
        start = len(self.issues)
        yield
        severities = {i["severity"] for i in self.issues[start:]}
        status = "FAILED" if severities & {"ERROR", "CONTRADICTION"} else "NOT_CHECKABLE" if "NOT_CHECKABLE" in severities else "CHECKED"
        self.checks.append(dict(check=name, status=status, detail="Explicit fields only; warnings are not hard failures."))

    def result(self) -> ValidationResult:
        severities = {i["severity"] for i in self.issues}
        outcome = ("FAILED_VALIDATION" if "ERROR" in severities else
                   "INFEASIBLE_EXPLICIT_CONSTRAINTS" if "CONTRADICTION" in severities else
                   "NEEDS_INFORMATION" if "NOT_CHECKABLE" in severities else "PASSED_ENCODED_CHECKS")
        return dict(outcome=outcome, issues=self.issues, checks=self.checks)


def moment(value, path, report, required=True):
    if value is None:
        if required:
            report.add("MISSING_TIME", path, "Explicit offset-aware time is required; no default is inferred.", "NOT_CHECKABLE")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            report.add("TIMEZONE_OFFSET_MISSING", path, "Time lacks an explicit UTC offset.", "NOT_CHECKABLE")
            return None
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        report.add("INVALID_TIME", path, "Expected an ISO-8601 datetime with an offset.")
        return None


def interval(value, path, report, required=True):
    if value is None:
        if required:
            report.add("MISSING_WINDOW", path, "A required interval is unknown.", "NOT_CHECKABLE")
        return None
    start = moment(value["start"], path + ".start", report)
    end = moment(value["end"], path + ".end", report)
    if start is None or end is None:
        return None
    if end <= start:
        report.add("INTERVAL_ORDER", path, "End must be later than start.")
        return None
    return start, end


def explicit_zone(value, report):
    if value is None:
        report.add("MISSING_TIMEZONE", "$.scope.timezone", "An explicit IANA timezone is required for scheduled checks.", "NOT_CHECKABLE")
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        report.add("INVALID_TIMEZONE", "$.scope.timezone", "Unknown IANA timezone; no timezone data is downloaded.")
        return None


def duplicate_ids(rows, key, path, report):
    seen = set()
    for i, row in enumerate(rows):
        if row[key] in seen:
            report.add("DUPLICATE_ID", f"{path}[{i}].{key}", "Identifier must be unique within its collection.")
        seen.add(row[key])


def source_check(ref, path, inp, report, at=None):
    scope = inp["scope"]
    if ref["course_id"] != scope["course_id"] or (ref["scope"] == "LEARNER" and ref["learner_id"] != scope["learner_id"]):
        report.add("SOURCE_SCOPE_MISMATCH", path, "Evidence is outside the explicit learner/course scope.")
    if ref["scope"] == "COURSE" and ref["learner_id"] is not None:
        report.add("SOURCE_SCOPE_AMBIGUOUS", path, "Course-wide source must explicitly have null learner_id.")
    if ref["access"] == "DENIED":
        report.add("SOURCE_ACCESS_DENIED", path + ".access", "Source access is denied.")
    elif ref["access"] == "UNKNOWN":
        report.add("SOURCE_ACCESS_UNKNOWN", path + ".access", "Source access is not established.", "NOT_CHECKABLE")
    versions = {s["source_id"]: s["version"] for s in inp["source_versions"]}
    if ref["source_id"] not in versions:
        report.add("SOURCE_VERSION_UNKNOWN", path + ".source_id", "No runtime current-version declaration exists.", "NOT_CHECKABLE")
    elif versions[ref["source_id"]] != ref["version"] or ref["superseded_by"] is not None:
        report.add("SOURCE_VERSION_STALE", path, "Reference is superseded or differs from the supplied current version.")
    observed = moment(ref["observed_at"], path + ".observed_at", report)
    lower = moment(ref["valid_from"], path + ".valid_from", report)
    upper = moment(ref["valid_to"], path + ".valid_to", report)
    now = moment(scope["as_of"], "$.scope.as_of", report)
    if lower and upper and lower >= upper:
        report.add("SOURCE_VALIDITY_ORDER", path, "Source valid_from must precede valid_to.")
    if now and observed and observed > now:
        report.add("SOURCE_FROM_FUTURE", path + ".observed_at", "Source was observed after the runtime as_of time.")
    if now and lower and upper and not lower <= now < upper:
        report.add("SOURCE_OUTSIDE_VALIDITY", path, "Source is not valid at the explicit as_of time.")
    if at and lower and upper and not lower <= at[0] < at[1] <= upper:
        report.add("RESOURCE_OUTSIDE_USE_VALIDITY", path, "Resource validity does not contain its scheduled use.")


def evidence_ids(ids, path, inp, report):
    facts = {f["fact_id"]: f for f in inp["facts"]}
    for i, fid in enumerate(ids):
        at = f"{path}[{i}]"
        if fid not in facts:
            report.add("EVIDENCE_ID_MISSING", at, f"Evidence ID {fid} is absent from permitted runtime facts.", "NOT_CHECKABLE")
        elif not facts[fid]["available"]:
            report.add("EVIDENCE_UNAVAILABLE", at, f"Runtime evidence {fid} is explicitly unavailable.", "NOT_CHECKABLE")


def intersects(a, b):
    return a[0] < b[1] and b[0] < a[1]


def forbidden_parts(window, weekdays, zone):
    """Enumerate local calendar days, preserving DST offsets at each midnight."""
    day = window[0].astimezone(zone).date()
    last = (window[1] - timedelta(microseconds=1)).astimezone(zone).date()
    while day <= last:
        next_day = day + timedelta(days=1)
        if day.weekday() in weekdays:
            yield (datetime.combine(day, datetime.min.time(), zone).astimezone(UTC),
                   datetime.combine(next_day, datetime.min.time(), zone).astimezone(UTC))
        day = next_day


def subtract(parts, exclusion):
    remaining = []
    for a, b in parts:
        if not intersects((a, b), exclusion):
            remaining.append((a, b))
        else:
            if a < exclusion[0]:
                remaining.append((a, exclusion[0]))
            if exclusion[1] < b:
                remaining.append((exclusion[1], b))
    return remaining


def schedule_context(inp, report):
    cfg = inp["hard_constraints"]["schedule"]
    zone = explicit_zone(inp["scope"]["timezone"], report)
    horizon = interval(inp["scope"]["horizon"], "$.scope.horizon", report)
    allowed = cfg["allowed_windows"]
    if allowed is None:
        report.add("ALLOWED_WINDOWS_UNKNOWN", "$.hard_constraints.schedule.allowed_windows", "Allowed windows are unknown, not empty.", "NOT_CHECKABLE")
    windows = [interval(w, f"$.hard_constraints.schedule.allowed_windows[{i}]", report) for i, w in enumerate(allowed or [])]
    exclusions = [interval(w, f"$.hard_constraints.schedule.excluded_windows[{i}]", report) for i, w in enumerate(cfg["excluded_windows"])]
    # Engineering bound prevents unbounded daily expansion; this is not UNSAT.
    for w in [horizon, *windows, *exclusions]:
        if w and w[1] - w[0] > timedelta(days=366):
            report.add("HORIZON_NOT_IMPLEMENTED", "$.scope.horizon", "P0 checks intervals up to 366 days only.", "NOT_CHECKABLE")
    return cfg, zone, horizon, windows, exclusions


def validate_input(inp: Any) -> ValidationResult:
    r = Report()
    with r.group("input_schema"):
        for e in schema_errors(inp, load_schema("PLANNER_INPUT_SCHEMA_DRAFT.json")):
            r.add(**e)
    if r.issues:
        return r.result()
    with r.group("runtime_identity_and_provenance"):
        for collection, key in [("goals", "goal_id"), ("facts", "fact_id"), ("resources", "resource_id"),
                                ("source_versions", "source_id"), ("completed_tasks", "task_id"),
                                ("review_permissions", "task_id"), ("soft_preferences", "preference_id")]:
            duplicate_ids(inp[collection], key, "$." + collection, r)
        duplicate_ids(inp["hard_constraints"]["task_prerequisites"], "task_id", "$.hard_constraints.task_prerequisites", r)
        moment(inp["scope"]["as_of"], "$.scope.as_of", r)
        for collection in ("facts", "resources"):
            for i, item in enumerate(inp[collection]):
                path = f"$.{collection}[{i}]"
                source_check(item["source_ref"], path + ".source_ref", inp, r)
                if collection == "facts" and item["kind"] in {"DASHBOARD", "LEARNER_MEMORY"} and item["source_ref"]["scope"] != "LEARNER":
                    r.add("PERSONAL_FACT_SCOPE_REQUIRED", path, "Dashboard/memory facts require explicit same-learner scope.")
        for collection in ("goals", "completed_tasks", "review_permissions"):
            for i, item in enumerate(inp[collection]):
                evidence_ids(item["evidence_refs"], f"$.{collection}[{i}].evidence_refs", inp, r)
        evidence_ids(inp["hard_constraints"]["required_evidence_ids"], "$.hard_constraints.required_evidence_ids", inp, r)
    with r.group("required_information_and_active_state"):
        for i, info in enumerate(inp["missing_information"]):
            r.add("DECLARED_MISSING_INFORMATION", f"$.missing_information[{i}]", info["reason"], "NOT_CHECKABLE" if info["required"] else "WARNING")
        budget = inp["hard_constraints"]["budget"]
        if budget["required"] and budget["minutes"] is None:
            r.add("BUDGET_UNKNOWN", "$.hard_constraints.budget.minutes", "Required budget is unknown.", "NOT_CHECKABLE")
        active = inp["active_plan"]
        if inp["hard_constraints"]["continue_active_plan"] and active is None:
            r.add("ACTIVE_PLAN_MISSING", "$.active_plan", "Continuation is required but the active plan is absent.", "NOT_CHECKABLE")
        if active:
            evidence_ids(active["evidence_refs"], "$.active_plan.evidence_refs", inp, r)
            if active["goal_id"] not in {g["goal_id"] for g in inp["goals"]}:
                r.add("ACTIVE_GOAL_UNKNOWN", "$.active_plan.goal_id", "Active goal is outside supplied goals.")
            completed = {x["task_id"] for x in inp["completed_tasks"]} | set(active["completed_task_ids"])
            if set(active["remaining_task_ids"]) & completed:
                r.add("ACTIVE_STATE_CONFLICT", "$.active_plan", "A task is both remaining and completed; clarify the state.")
    with r.group("explicit_scheduling_conditions"):
        if inp["hard_constraints"]["schedule"]["required"]:
            cfg, zone, horizon, windows, exclusions = schedule_context(inp, r)
            as_of = moment(inp["scope"]["as_of"], "$.scope.as_of", r)
            if horizon and as_of and horizon[0] < as_of:
                r.add("HORIZON_BEFORE_AS_OF", "$.scope.horizon", "Planning horizon begins before the runtime as_of time.")
            if not any(i["severity"] in {"ERROR", "NOT_CHECKABLE"} for i in r.issues):
                residual = []
                for w in windows:
                    clipped = max(w[0], horizon[0]), min(w[1], horizon[1])
                    if clipped[0] >= clipped[1]:
                        continue
                    parts = [clipped]
                    for ex in [*exclusions, *forbidden_parts(clipped, cfg["forbidden_weekdays"], zone)]:
                        parts = subtract(parts, ex)
                    residual.extend(parts)
                if not residual:
                    r.add("NO_ALLOWED_TIME_EXPLICIT", "$.hard_constraints.schedule", "Scheduling is required, but the encoded allowed set within the horizon is empty after explicit exclusions/weekdays.", "CONTRADICTION")
        else:
            r.checks.append(dict(check="mandatory_schedule", status="NOT_APPLICABLE", detail="Unscheduled output is allowed; supplied candidate schedules are still checked."))
    return r.result()


def validate_candidate(inp: PlannerInput, candidate: Any) -> ValidationResult:
    r = Report()
    # Direct callers cannot bypass runtime validation or pass a hidden sidecar.
    pre = validate_input(inp)
    r.issues.extend(pre["issues"])
    r.checks.extend(pre["checks"])
    if pre["outcome"] != "PASSED_ENCODED_CHECKS":
        return r.result()
    with r.group("candidate_schema"):
        for e in schema_errors(candidate, load_schema("PLANNER_CANDIDATE_SCHEMA_DRAFT.json")):
            r.add(**e)
    if any(i["severity"] == "ERROR" for i in r.issues):
        return r.result()
    actions = candidate["actions"]
    with r.group("goal_and_active_plan_binding"):
        goals = {g["goal_id"]: g for g in inp["goals"]}
        if candidate["goal_id"] not in goals or candidate["goal"] != goals[candidate["goal_id"]]["text"]:
            r.add("GOAL_BINDING_MISMATCH", "$.candidate.goal_id", "Candidate must identify and retain one supplied goal verbatim; achievement is not checked.")
        active = inp["active_plan"]
        if candidate["continues_plan_id"] is not None and (active is None or candidate["continues_plan_id"] != active["plan_id"]):
            r.add("ACTIVE_PLAN_ID_MISMATCH", "$.candidate.continues_plan_id", "Continuation ID has no matching supplied active plan.")
        if active and inp["hard_constraints"]["continue_active_plan"]:
            if candidate["continues_plan_id"] != active["plan_id"] or candidate["goal_id"] != active["goal_id"]:
                r.add("ACTIVE_PLAN_NOT_CONTINUED", "$.candidate", "Required active-plan and goal IDs must be retained.")
            tasks = {a["task_id"] for a in actions if a["kind"] == "TASK"}
            if not set(active["remaining_task_ids"]) <= tasks:
                r.add("ACTIVE_TASK_DROPPED", "$.candidate.actions", "An explicitly required remaining task is missing.")
    with r.group("evidence_and_resource_references"):
        evidence_ids(candidate["evidence_refs"], "$.candidate.evidence_refs", inp, r)
        resources = {x["resource_id"]: x for x in inp["resources"]}
        for i, action in enumerate(actions):
            at = f"$.candidate.actions[{i}]"
            evidence_ids(action["evidence_refs"], at + ".evidence_refs", inp, r)
            evidence_ids(action["estimated_duration"]["evidence_refs"], at + ".estimated_duration.evidence_refs", inp, r)
            if action["estimated_duration"]["origin"] == "SOURCE_ESTIMATE" and not action["estimated_duration"]["evidence_refs"]:
                r.add("ESTIMATE_SOURCE_MISSING", at + ".estimated_duration", "A source-origin estimate needs an evidence reference.", "NOT_CHECKABLE")
            for j, rid in enumerate(action["resource_ids"]):
                if rid not in resources or not resources[rid]["available"]:
                    r.add("RESOURCE_NOT_PERMITTED", at + f".resource_ids[{j}]", f"Resource {rid} is absent or unavailable in runtime resources.")
    with r.group("dependencies_and_completion"):
        duplicate_ids(actions, "step_id", "$.candidate.actions", r)
        duplicate_ids(actions, "task_id", "$.candidate.actions", r)
        by_step = {a["step_id"]: i for i, a in enumerate(actions)}
        by_task = {a["task_id"]: a for a in actions}
        completed = {x["task_id"] for x in inp["completed_tasks"]}
        if inp["active_plan"]:
            completed |= set(inp["active_plan"]["completed_task_ids"])
        review_allowed = {x["task_id"] for x in inp["review_permissions"]}
        graph = {a["step_id"]: a["dependencies"] for a in actions}
        state = {}

        def visit(sid):
            if state.get(sid) == 1:
                return True
            if state.get(sid) == 2:
                return False
            state[sid] = 1
            if any(visit(dep) for dep in graph.get(sid, []) if dep in graph):
                return True
            state[sid] = 2
            return False

        if any(visit(sid) for sid in graph):
            r.add("DEPENDENCY_CYCLE", "$.candidate.actions", "Dependency graph contains a directed cycle.")
        rules = {x["task_id"]: x["prerequisite_task_ids"] for x in inp["hard_constraints"]["task_prerequisites"]}
        for i, a in enumerate(actions):
            at = f"$.candidate.actions[{i}]"
            for dep in a["dependencies"]:
                if dep not in by_step:
                    r.add("DEPENDENCY_ID_MISSING", at + ".dependencies", f"Step {dep} does not exist.")
                elif by_step[dep] >= i:
                    r.add("DEPENDENCY_ORDER", at + ".dependencies", "Prerequisite must occur earlier in the declared action order.")
            for task in rules.get(a["task_id"], []):
                if task in completed:
                    continue
                if task not in by_task or by_task[task]["step_id"] not in a["dependencies"]:
                    r.add("TASK_PREREQUISITE_MISSING", at + ".dependencies", f"Explicit prerequisite task {task} must be completed or included as a dependency.")
            if a["kind"] == "REVIEW" and (a["task_id"] not in completed or a["task_id"] not in review_allowed):
                r.add("REVIEW_NOT_AUTHORIZED", at + ".kind", "Review requires an explicitly completed task and a separate supplied review permission.")
            if a["task_id"] in completed and inp["hard_constraints"]["forbid_completed_repeat"] and a["kind"] != "REVIEW":
                r.add("COMPLETED_TASK_REPEATED", at + ".task_id", "An explicitly prohibited completed task is repeated as a new task.")
    with r.group("declared_duration_and_budget"):
        durations = []
        for i, a in enumerate(actions):
            duration = a["estimated_duration"]
            at = f"$.candidate.actions[{i}].estimated_duration"
            if duration["value"] is None or duration["origin"] == "UNKNOWN":
                r.add("DURATION_UNKNOWN", at, "Duration or its origin is unknown; it is not treated as zero.", "NOT_CHECKABLE")
            elif duration["value"] <= 0:
                r.add("DURATION_NOT_POSITIVE", at, "Every action requires a positive declared estimate.")
            else:
                durations.append(Decimal(str(duration["value"])))
        budget = inp["hard_constraints"]["budget"]["minutes"]
        if budget is not None and len(durations) == len(actions) and sum(durations) > Decimal(str(budget)):
            r.add("BUDGET_EXCEEDED", "$.candidate.actions", "Sum of declared estimates exceeds the explicit budget; this is estimate arithmetic only.")
        if budget is None and not inp["hard_constraints"]["budget"]["required"]:
            r.checks.append(dict(check="budget_limit", status="NOT_APPLICABLE", detail="No budget limit supplied; no budget feasibility claim."))
    with r.group("supplied_schedule"):
        need = inp["hard_constraints"]["schedule"]["required"] or any(a["schedule"] is not None for a in actions)
        if need:
            cfg, zone, horizon, windows, exclusions = schedule_context(inp, r)
            schedule_safe = zone and horizon and all(windows) and all(exclusions) and not any(i["code"] == "HORIZON_NOT_IMPLEMENTED" for i in r.issues)
            times = {}
            for i, a in enumerate(actions):
                at = f"$.candidate.actions[{i}].schedule"
                when = interval(a["schedule"], at, r, required=cfg["required"])
                if when is None:
                    continue
                times[a["step_id"]] = when
                if horizon and not horizon[0] <= when[0] < when[1] <= horizon[1]:
                    r.add("SCHEDULE_OUTSIDE_HORIZON", at, "Scheduled interval is outside the supplied horizon.")
                as_of = moment(inp["scope"]["as_of"], "$.scope.as_of", r)
                if as_of and when[0] < as_of:
                    r.add("SCHEDULE_BEFORE_AS_OF", at, "An action cannot be scheduled before the explicit runtime as_of time.")
                if cfg["allowed_windows"] is not None and not any(w and w[0] <= when[0] < when[1] <= w[1] for w in windows):
                    r.add("SCHEDULE_OUTSIDE_ALLOWED_WINDOW", at, "Interval is not contained in any supplied allowed window.")
                if any(ex and intersects(when, ex) for ex in exclusions):
                    r.add("SCHEDULE_EXCLUDED", at, "Interval overlaps an explicit exclusion.")
                if schedule_safe and when[1] - when[0] <= timedelta(days=366) and any(intersects(when, d) for d in forbidden_parts(when, cfg["forbidden_weekdays"], zone)):
                    r.add("FORBIDDEN_WEEKDAY", at, "Interval touches an explicitly forbidden local weekday.")
                value = a["estimated_duration"]["value"]
                if value is not None and Decimal(str((when[1] - when[0]).total_seconds())) < Decimal(str(value)) * 60:
                    r.add("SLOT_SHORTER_THAN_ESTIMATE", at, "Supplied slot is shorter than its declared estimate.")
                for rid in a["resource_ids"]:
                    if rid in resources:
                        source_check(resources[rid]["source_ref"], at + ".resource[" + rid + "]", inp, r, at=when)
            for i, a in enumerate(actions):
                for dep in a["dependencies"]:
                    if a["step_id"] in times and dep in times and times[dep][1] > times[a["step_id"]][0]:
                        r.add("SCHEDULE_DEPENDENCY_ORDER", f"$.candidate.actions[{i}].schedule", "A scheduled prerequisite finishes after this action starts.")
                    elif a["step_id"] in times and dep not in times:
                        r.add("DEPENDENCY_TIME_UNKNOWN", f"$.candidate.actions[{i}].schedule", "Scheduled action has an unscheduled prerequisite.", "NOT_CHECKABLE")
            if cfg["non_overlap"]:
                ordered = sorted(times.items(), key=lambda pair: pair[1][0])
                for i, (sid, window) in enumerate(ordered):
                    for tid, other in ordered[i + 1:]:
                        if intersects(window, other):
                            r.add("SCHEDULE_OVERLAP", "$.candidate.actions", f"Steps {sid} and {tid} overlap while non-overlap is required.")
        else:
            r.checks.append(dict(check="schedule_feasibility", status="NOT_APPLICABLE", detail="Actions explicitly unscheduled; no scheduling feasibility is certified."))
    with r.group("soft_preferences_separate_from_admission"):
        used = {rid for a in actions for rid in a["resource_ids"]}
        for i, pref in enumerate(inp["soft_preferences"]):
            if pref["kind"] == "PREFERRED_RESOURCE" and pref["value"] not in used:
                r.add("SOFT_PREFERENCE_UNMET", f"$.soft_preferences[{i}]", "Preferred resource is unused; this is advisory only.", "WARNING")
            elif pref["kind"] == "NOTE":
                r.add("SOFT_PREFERENCE_NOT_CHECKED", f"$.soft_preferences[{i}]", "Free-text preference is retained but not semantically checked.", "WARNING")
    r.checks.append(dict(check="semantic_entailment_and_learning_effectiveness", status="NOT_IMPLEMENTED", detail="Valid source IDs do not establish entailment, goal achievement, pedagogical quality or student outcomes."))
    return r.result()
