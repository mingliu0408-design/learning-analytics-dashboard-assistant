"""Bounded candidate -> check -> feedback loop, selecting first admitted object."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .contracts import CandidateProvider, PlannerInput, PlannerOutput, build_request, canonical
from .validator import validate_candidate, validate_input

LIMITATIONS = [
    "Passed encoded checks means consistency of explicit structured fields only.",
    "No semantic entailment, goal achievement, pedagogy or student-outcome validation.",
    "Duration arithmetic uses estimates; actual completion time is unknown.",
    "P0 checks supplied schedules; it does not construct an automatic schedule.",
    "Synthetic mock behavior does not demonstrate model adaptation or select a final method."]


def failure(code, message):
    return {"outcome": "FAILED_VALIDATION", "issues": [dict(code=code, path="$", message=message, severity="ERROR")], "checks": []}


def run_planner(runtime_input: PlannerInput, provider: CandidateProvider, *,
                max_repairs: int = 0, planning_enabled: bool = True) -> PlannerOutput:
    if type(max_repairs) is not int or max_repairs not in (0, 1, 2):
        raise ValueError("P0 engineering repair limits are exactly 0, 1 or 2; no live policy is frozen.")
    if type(planning_enabled) is not bool:
        raise TypeError("planning_enabled must be explicit bool")
    events, history = [], []
    calls = {"candidate": 0, "repair": 0, "real": 0}

    def event(name, detail):
        events.append(dict(sequence=len(events), event=name, at_utc=datetime.now(timezone.utc).isoformat(), detail=detail))

    def finish(status, validation, plan=None, kind=None):
        event("TERMINAL", status)
        return dict(status=status, failure_kind=kind, plan=deepcopy(plan), encoded_check_results=validation,
                    unresolved_information=[deepcopy(i) for i in validation["issues"] if i["severity"] == "NOT_CHECKABLE"],
                    repair_history=history, provider_calls=calls, semantic_entailment="NOT_CHECKED",
                    limitations=list(LIMITATIONS), trace_events=events)

    if not planning_enabled:
        event("NO_PLANNING_BYPASS", "No input request built and no provider called.")
        return finish("BYPASSED_NO_PLANNING", {"outcome": "NOT_APPLICABLE", "issues": [], "checks": []})
    # Freeze before provider invocation. No input is appended after a proposal.
    inp = deepcopy(runtime_input)
    pre = validate_input(inp)
    event("RUNTIME_INPUT_VALIDATED", pre["outcome"])
    if pre["outcome"] != "PASSED_ENCODED_CHECKS":
        status = "INVALID_INPUT" if pre["outcome"] == "FAILED_VALIDATION" else pre["outcome"]
        return finish(status, pre, kind="RUNTIME_INPUT")
    event("INPUT_SNAPSHOT_FROZEN", "Goals, hard constraints, soft preferences, completed tasks and active plan retained before proposal.")
    previous, validation = None, None
    for attempt in range(max_repairs + 1):
        request = build_request(inp, attempt, previous, validation)
        event("CANDIDATE_REQUEST_BUILT" if attempt == 0 else "REPAIR_REQUEST_BUILT", request.sha256)
        phase = "candidate" if attempt == 0 else "repair"
        calls[phase] += 1
        event("MOCK_PROVIDER_ENTERED", f"{phase}:{attempt}; request already complete")
        try:
            candidate: Any = provider.propose(request)
        except Exception as exc:
            validation = failure("MOCK_PROVIDER_FAILURE", f"{type(exc).__name__}: {exc}")
            history.append(dict(attempt=attempt, request=request.payload, request_sha256=request.sha256,
                                candidate={"provider_exception": str(exc)}, validation=validation))
            return finish("PROVIDER_FAILURE", validation, kind="MOCK_PROVIDER")
        event("MOCK_CANDIDATE_RETURNED", f"attempt:{attempt}")
        validation = validate_candidate(inp, candidate)
        try:
            canonical(candidate)
            saved = deepcopy(candidate)
        except (ValueError, TypeError, OverflowError):
            # Preserve an explicit diagnostic representation, not repaired data.
            saved = {"non_json_candidate_representation": repr(candidate)}
            validation["issues"].append(dict(code="NON_JSON_CANDIDATE", path="$.candidate", message="Raw provider object is not finite JSON; its Python representation is retained as diagnostic text.", severity="ERROR"))
            validation["outcome"] = "FAILED_VALIDATION"
        history.append(dict(attempt=attempt, request=request.payload, request_sha256=request.sha256,
                            candidate=saved, validation=deepcopy(validation)))
        event("ENCODED_VALIDATION_COMPLETE", validation["outcome"])
        if validation["outcome"] == "PASSED_ENCODED_CHECKS":
            return finish("PASSED_ENCODED_CHECKS", validation, candidate)
        previous = saved
    kind = "NEEDS_INFORMATION" if validation["outcome"] == "NEEDS_INFORMATION" else "CONSTRAINT_VIOLATION"
    if any(i["code"] in {"REQUIRED_FIELD", "SCHEMA_TYPE", "SCHEMA_ENUM", "SCHEMA_CONST", "UNEXPECTED_FIELD", "NON_JSON_CANDIDATE", "NON_FINITE_NUMBER", "EMPTY_STRING", "ARRAY_SIZE", "NUMERIC_RANGE"} for i in validation["issues"]):
        kind = "INVALID_STRUCTURED_OUTPUT"
    return finish("BOUNDED_REPAIR_EXHAUSTED", validation, kind=kind)
