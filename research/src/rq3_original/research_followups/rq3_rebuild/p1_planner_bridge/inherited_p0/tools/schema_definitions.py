"""Reproducible P0 schema definitions. Uses standard library only."""
import json
from pathlib import Path


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item, minimum=0, unique=False, maximum=1000):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum, "uniqueItems": unique}


def nullable(s):
    return {"anyOf": [s, {"type": "null"}]}


S = {"type": "string", "minLength": 1}
B = {"type": "boolean"}
IDS = arr(S, unique=True)
MINUTES = {"type": "number", "minimum": 0, "maximum": 1000000}
INTERVAL = obj(start=S, end=S)
REF = obj(source_id=S, version=S, learner_id=nullable(S), course_id=S,
          scope={"enum": ["LEARNER", "COURSE"], "type": "string"}, session_id=S,
          span_id=S, page=S, observed_at=nullable(S), valid_from=nullable(S), valid_to=nullable(S),
          superseded_by=nullable(S), access={"type": "string", "enum": ["GRANTED", "DENIED", "UNKNOWN"]})
DURATION = obj(value=nullable(MINUTES), unit={"const": "minutes", "type": "string"},
               origin={"type": "string", "enum": ["SYNTHETIC_ESTIMATE", "LEARNER_ESTIMATE", "SOURCE_ESTIMATE", "UNKNOWN"]},
               evidence_refs=IDS)
ACTION = obj(step_id=S, task_id=S, kind={"type": "string", "enum": ["TASK", "REVIEW"]},
             action=S, estimated_duration=DURATION, resource_ids=IDS, dependencies=IDS,
             schedule=nullable(INTERVAL), completion_check=S, evidence_refs=arr(S, minimum=1, unique=True),
             brief_rationale=S)
CANDIDATE = obj(plan_id=S, goal_id=S, goal=S, actions=arr(ACTION, minimum=1, maximum=100),
                evidence_refs=arr(S, minimum=1, unique=True), continues_plan_id=nullable(S), brief_rationale=S)
INPUT = obj(
    schema_version={"const": "P0_DRAFT_V0", "type": "string"},
    scope=obj(learner_id=S, course_id=S, session_id=S, as_of=nullable(S),
              horizon=nullable(INTERVAL), timezone=nullable(S)),
    context=obj(query=S, page=S, visible_conversation=arr(S)),
    goals=arr(obj(goal_id=S, text=S, evidence_refs=IDS), minimum=1),
    hard_constraints=obj(
        budget=obj(required=B, minutes=nullable(MINUTES)),
        schedule=obj(required=B, allowed_windows=nullable(arr(INTERVAL)), excluded_windows=arr(INTERVAL),
                     forbidden_weekdays=arr({"type": "integer", "minimum": 0, "maximum": 6}, unique=True), non_overlap=B),
        forbid_completed_repeat=B, continue_active_plan=B, required_evidence_ids=IDS,
        task_prerequisites=arr(obj(task_id=S, prerequisite_task_ids=IDS))),
    soft_preferences=arr(obj(preference_id=S, kind={"type": "string", "enum": ["PREFERRED_RESOURCE", "NOTE"]}, value=S)),
    completed_tasks=arr(obj(task_id=S, evidence_refs=IDS)),
    review_permissions=arr(obj(task_id=S, evidence_refs=IDS, rationale=S)),
    active_plan=nullable(obj(plan_id=S, goal_id=S, remaining_task_ids=IDS, completed_task_ids=IDS, evidence_refs=IDS)),
    facts=arr(obj(fact_id=S, kind={"type": "string", "enum": ["DASHBOARD", "COURSE_RAG", "LEARNER_MEMORY"]},
                  fact_type=S, value=S, source_ref=REF, available=B)),
    resources=arr(obj(resource_id=S, title=S, source_ref=REF, available=B)),
    source_versions=arr(obj(source_id=S, version=S)),
    missing_information=arr(obj(field=S, required=B, reason=S)))
ISSUE = obj(code=S, path=S, message=S, severity={"type": "string", "enum": ["ERROR", "NOT_CHECKABLE", "WARNING", "CONTRADICTION"]})
CHECK = obj(check=S, status={"type": "string", "enum": ["CHECKED", "NOT_APPLICABLE", "NOT_IMPLEMENTED", "FAILED", "NOT_CHECKABLE"]}, detail=S)
VALIDATION = obj(outcome=S, issues=arr(ISSUE), checks=arr(CHECK))
REQUEST = obj(phase={"type": "string", "enum": ["CANDIDATE", "REPAIR"]}, attempt={"type": "integer", "minimum": 0, "maximum": 2},
              runtime_input=INPUT, previous_candidate=nullable({}), feedback=nullable(VALIDATION),
              instruction=S)
HISTORY = obj(attempt={"type": "integer", "minimum": 0, "maximum": 2}, request=REQUEST,
              request_sha256=S, candidate={}, validation=VALIDATION)
EVENT = obj(sequence={"type": "integer", "minimum": 0}, event=S, at_utc=S, detail=S)
OUTPUT = obj(status=S, failure_kind=nullable(S), plan=nullable(CANDIDATE),
             encoded_check_results=VALIDATION, unresolved_information=arr(ISSUE),
             repair_history=arr(HISTORY, maximum=3),
             provider_calls=obj(candidate={"type": "integer", "minimum": 0, "maximum": 1},
                                repair={"type": "integer", "minimum": 0, "maximum": 2},
                                real={"const": 0, "type": "integer"}),
             semantic_entailment={"const": "NOT_CHECKED", "type": "string"}, limitations=arr(S), trace_events=arr(EVENT))


def schemas():
    return {name: {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": name.removesuffix('.json'), **s}
            for name, s in [("PLANNER_INPUT_SCHEMA_DRAFT.json", INPUT),
                            ("PLANNER_CANDIDATE_SCHEMA_DRAFT.json", CANDIDATE),
                            ("PLANNER_OUTPUT_SCHEMA_DRAFT.json", OUTPUT)]}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for name, schema in schemas().items():
        (root / name).write_text(json.dumps(schema, indent=2) + "\n")
