"""Executable multi-hop completeness and missing-memory response contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .executable_retrieval_contract import RankedMemoryCandidateV1_1


@dataclass(frozen=True)
class MultiHopOutcomeV1:
    multi_hop_request: bool
    required_memory_types: tuple[str, ...]
    admitted_memory_types: tuple[str, ...]
    missing_memory_types: tuple[str, ...]
    multi_hop_complete: bool
    clarification: bool
    safe_partial_response: bool
    explicit_missing_evidence_statement_required: bool
    personalisation_complete_claim_allowed: bool


def evaluate_multi_hop_completeness(
    target_memory_types: Sequence[str],
    admitted_candidates: Iterable[RankedMemoryCandidateV1_1],
    *,
    task_requires_complete_memory: bool,
) -> MultiHopOutcomeV1:
    required = tuple(dict.fromkeys(target_memory_types))
    admitted_types = tuple(
        dict.fromkeys(item.record.memory_type for item in admitted_candidates)
    )
    missing = tuple(value for value in required if value not in set(admitted_types))
    multi_hop = len(required) > 1
    complete = not missing
    clarification = multi_hop and not complete and task_requires_complete_memory
    safe_partial = multi_hop and not complete and not task_requires_complete_memory
    return MultiHopOutcomeV1(
        multi_hop_request=multi_hop,
        required_memory_types=required,
        admitted_memory_types=admitted_types,
        missing_memory_types=missing,
        multi_hop_complete=complete,
        clarification=clarification,
        safe_partial_response=safe_partial,
        explicit_missing_evidence_statement_required=safe_partial,
        personalisation_complete_claim_allowed=complete,
    )


def multi_hop_contract() -> dict[str, Any]:
    return {
        "schema_version": "multi-hop-memory-contract-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN_EXECUTABLE_NOT_RUN",
        "multi_hop_definition": "MORE_THAN_ONE_DISTINCT_TARGET_MEMORY_TYPE",
        "success_requirement": "AT_LEAST_ONE_ADMITTED_MEMORY_PER_REQUIRED_TYPE",
        "missing_required_type_means_complete": False,
        "allowed_incomplete_responses": [
            "CLARIFY_IF_TASK_REQUIRES_COMPLETE_MEMORY",
            "SAFE_PARTIAL_WITH_EXPLICIT_MISSING_EVIDENCE_STATEMENT",
        ],
        "fabricate_missing_memory": False,
        "claim_complete_personalisation_when_incomplete": False,
        "evaluation_executed": False,
    }
