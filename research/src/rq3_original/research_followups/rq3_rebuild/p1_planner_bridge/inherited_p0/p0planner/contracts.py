"""Typed API and immutable request snapshot; JSON Schemas define nested fields."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal, Protocol, TypedDict

JSON = dict[str, Any]


class PlannerInput(TypedDict):
    schema_version: Literal["P0_DRAFT_V0"]
    scope: JSON
    context: JSON
    goals: list[JSON]
    hard_constraints: JSON
    soft_preferences: list[JSON]
    completed_tasks: list[JSON]
    review_permissions: list[JSON]
    active_plan: JSON | None
    facts: list[JSON]
    resources: list[JSON]
    source_versions: list[JSON]
    missing_information: list[JSON]


class CandidatePlan(TypedDict):
    plan_id: str
    goal_id: str
    goal: str
    actions: list[JSON]
    evidence_refs: list[str]
    continues_plan_id: str | None
    brief_rationale: str


class ValidationResult(TypedDict):
    outcome: str
    issues: list[JSON]
    checks: list[JSON]


class PlannerOutput(TypedDict):
    status: str
    failure_kind: str | None
    plan: CandidatePlan | None
    encoded_check_results: ValidationResult
    unresolved_information: list[JSON]
    repair_history: list[JSON]
    provider_calls: JSON
    semantic_entailment: Literal["NOT_CHECKED"]
    limitations: list[str]
    trace_events: list[JSON]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class CandidateRequest:
    """Providers receive only this JSON snapshot, never a testing sidecar.

    Each payload read returns a separate copy. Constraints cannot be silently
    deleted by mutating a request during candidate construction or repair.
    """

    serialized: str

    @property
    def payload(self) -> JSON:
        return json.loads(self.serialized)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.serialized.encode()).hexdigest()


def build_request(runtime_input: PlannerInput, attempt: int,
                  previous_candidate: Any = None, feedback: ValidationResult | None = None) -> CandidateRequest:
    return CandidateRequest(canonical({
        "phase": "CANDIDATE" if attempt == 0 else "REPAIR", "attempt": attempt,
        "runtime_input": runtime_input, "previous_candidate": previous_candidate,
        "feedback": feedback,
        "instruction": "Return one explicit synthetic structured candidate. Use the supplied goals, hard constraints, completion state and active plan before constructing steps. Keep hard constraints unchanged; explain briefly using evidence links. Do not provide hidden chain of thought. No natural-language model generation is enabled."}))


class CandidateProvider(Protocol):
    def propose(self, request: CandidateRequest) -> Any:
        """Return a mock/hand-constructed JSON object, not a model response."""
