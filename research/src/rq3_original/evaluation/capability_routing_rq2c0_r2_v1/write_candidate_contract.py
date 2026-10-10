"""Structured write-candidate source boundary for future RQ2-C1 conformance work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .event_type_compatibility import (
    EventTypeCompatibilityDecision,
    evaluate_event_type_compatibility,
)


ALLOWED_CANDIDATE_SOURCES = (
    "STRUCTURED_EXPLICIT_USER_ASSERTION",
    "VERIFIED_PLAN_EVENT",
    "VERIFIED_COMPLETION_EVENT",
    "EXPLICIT_USER_CONFIRMATION",
)

FORBIDDEN_CANDIDATE_SOURCES = (
    "FREE_FORM_LLM_INFERENCE",
    "UNCONFIRMED_ASSISTANT_SUGGESTION",
    "MODEL_DERIVED_PERSONALITY",
    "MODEL_DERIVED_SRL",
    "MODEL_DERIVED_ABILITY",
    "UNVERIFIED_DASHBOARD_INTERPRETATION",
)


@dataclass(frozen=True)
class StructuredWriteCandidateV1:
    candidate_source: str
    event_type: str
    supplied_memory_type: str | None
    source_structured: bool
    explicit_user_source: bool
    verified_system_event: bool
    sensitive_inference: bool


@dataclass(frozen=True)
class StructuredWriteBoundaryDecisionV1:
    candidate_source_allowed: bool
    event_type_compatible: bool
    write_authorised: bool
    failure_reason: str | None
    event_decision: EventTypeCompatibilityDecision


def evaluate_structured_write_candidate(
    candidate: StructuredWriteCandidateV1,
) -> StructuredWriteBoundaryDecisionV1:
    event_decision = evaluate_event_type_compatibility(
        candidate.event_type, candidate.supplied_memory_type
    )
    source_allowed = (
        candidate.candidate_source in ALLOWED_CANDIDATE_SOURCES
        and candidate.source_structured
        and not candidate.sensitive_inference
        and (candidate.explicit_user_source or candidate.verified_system_event)
    )
    failure_reason: str | None = None
    if candidate.candidate_source not in ALLOWED_CANDIDATE_SOURCES:
        failure_reason = "UNSUPPORTED_CANDIDATE_SOURCE"
    elif not candidate.source_structured:
        failure_reason = "UNSTRUCTURED_CANDIDATE_REJECTED"
    elif candidate.sensitive_inference:
        failure_reason = "SENSITIVE_INFERENCE_REJECTED"
    elif not (candidate.explicit_user_source or candidate.verified_system_event):
        failure_reason = "NO_EXPLICIT_OR_VERIFIED_SOURCE"
    elif not event_decision.write_authorised:
        failure_reason = event_decision.failure_reason
    return StructuredWriteBoundaryDecisionV1(
        candidate_source_allowed=source_allowed,
        event_type_compatible=event_decision.write_authorised,
        write_authorised=source_allowed and event_decision.write_authorised,
        failure_reason=failure_reason,
        event_decision=event_decision,
    )


def write_candidate_boundary_contract() -> dict[str, Any]:
    return {
        "schema_version": "structured-write-candidate-contract-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "allowed_candidate_sources": list(ALLOWED_CANDIDATE_SOURCES),
        "forbidden_candidate_sources": list(FORBIDDEN_CANDIDATE_SOURCES),
        "source_must_be_structured": True,
        "source_must_be_explicit_user_or_verified_event": True,
        "open_ended_free_text_memory_candidate_extraction_evaluated_in_rq2c1": False,
        "rq2c1_evaluable_operations": [
            "STORE",
            "UPDATE",
            "RETRIEVAL",
            "ADMISSION",
            "CONFLICT",
            "PRIVACY",
        ],
        "persistent_store_implemented": False,
    }
