"""Condition-local P2 execution with measured RAG tool-call isolation."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    evaluate_capability_predictions,
)
from evaluation.capability_routing_rq2b_v1.gold_preflight import GoldExample
from evaluation.capability_routing_rq2c0_v1.rag_gate_contract import (
    retrieval_candidate_gate,
)
from evaluation.capability_routing_rq2c1_v1.offline_dual_gated_rag import (
    LocalCourseRAGExecution,
    run_local_course_rag,
)
from evaluation.capability_routing_rq2c1_v1.offline_session_state_gate import (
    run_session_state_gate,
    session_input_from_p1,
)

from . import (
    CONDITION_IDS,
    PERSISTENT_ENABLED_CONDITIONS,
    RAG_ENABLED_CONDITIONS,
    ROOT,
    SESSION_ENABLED_CONDITIONS,
    canonical_json_bytes,
)
from .mechanism_metrics_v1_1 import binary_metrics
from .runtime_safety_instrumentation import RuntimeSafetyEventLedgerV1


class ConditionIsolationError(RuntimeError):
    pass


def load_p1_ledger_v1_1(relative: Path) -> tuple[Mapping[str, Any], ...]:
    rows = tuple(
        json.loads(line)
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line
    )
    ids = [str(row["review_case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("P1 ledger duplicate case identity")
    return rows


def execute_rag_for_condition_v1_1(
    *,
    condition_id: str,
    candidate_allowed: bool,
    effective_query: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None,
    rag_runner: Callable[[str], LocalCourseRAGExecution] = run_local_course_rag,
) -> LocalCourseRAGExecution | None:
    if condition_id not in CONDITION_IDS:
        raise ConditionIsolationError("UNKNOWN_P2_CONDITION")
    if condition_id not in RAG_ENABLED_CONDITIONS:
        if safety_ledger is not None:
            safety_ledger.record(
                "RAG_EXECUTION_IN_DISABLED_CONDITION",
                blocked=True,
                successful_violation=False,
                guard_id="P2_CONDITION_RAG_ISOLATION_V1",
                reason_code="RAG_DISABLED_FOR_CONDITION",
                condition_id=condition_id,
            )
        raise ConditionIsolationError("RAG_DISABLED_FOR_CONDITION")
    if not candidate_allowed:
        return None
    return rag_runner(effective_query)


def _metric_rows(
    examples: Iterable[GoldExample], p1_by_id: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in examples:
        p1 = p1_by_id[example.router_input.case_id]
        rows.append(
            {
                "gold_capabilities": list(example.labels.required_capabilities),
                "predicted_capabilities": list(p1["predicted_capabilities"]),
                "forbidden_capabilities": list(example.labels.forbidden_capabilities),
                "gold_context_resolution_required": example.labels.context_resolution_required,
                "predicted_context_resolution_required": bool(
                    p1["context_resolution_required_prediction"]
                ),
            }
        )
    return rows


def _candidate(p1: Mapping[str, Any]) -> tuple[bool, str]:
    session_input = session_input_from_p1(p1)
    source_policy = dict((p1.get("capability_plan") or {}).get("source_policy") or {})
    source_allowed = "course_material" in set(
        source_policy.get("allowed_source_types") or ()
    )
    allowed = retrieval_candidate_gate(
        p1_course_retrieval="course_retrieval"
        in set(p1["predicted_capabilities"]),
        p1_clarification=session_input.p1_clarification,
        course_source_authorised=source_allowed,
    )
    envelope = dict(p1.get("context_envelope") or {})
    query = str(
        envelope.get("resolved_query")
        or envelope.get("original_query")
        or ""
    )
    return allowed, query


def run_conditions_v1_1(
    *,
    examples: Iterable[GoldExample],
    p1_rows: Iterable[Mapping[str, Any]],
    session_policy_id: str,
    dataset_role: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None = None,
    rag_runner: Callable[[str], LocalCourseRAGExecution] = run_local_course_rag,
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    values = tuple(examples)
    p1_by_id = {str(row["review_case_id"]): row for row in p1_rows}
    if set(p1_by_id) != {item.router_input.case_id for item in values}:
        raise ValueError("P1/Gold identity mismatch")
    base_capability_metrics = evaluate_capability_predictions(
        _metric_rows(values, p1_by_id)
    )
    local_rows: list[Mapping[str, Any]] = []
    aggregates: dict[str, Any] = {}
    plan_hashes: list[bytes] = []
    for condition_id in CONDITION_IDS:
        rag_enabled = condition_id in RAG_ENABLED_CONDITIONS
        session_enabled = condition_id in SESSION_ENABLED_CONDITIONS
        persistent_enabled = condition_id in PERSISTENT_ENABLED_CONDITIONS
        gold_state: list[bool] = []
        predicted_state: list[bool] = []
        candidate_count = 0
        actual_calls = 0
        sufficiency_calls = 0
        admissions = 0
        rag_statuses: dict[str, int] = {}
        provider_calls = 0
        network_calls = 0
        persistent_attempts = 0
        clarification_blocks = 0
        receipt_hashes: list[bytes] = []
        for example in values:
            case_id = example.router_input.case_id
            p1 = p1_by_id[case_id]
            session_input = session_input_from_p1(p1)
            if session_enabled:
                session = run_session_state_gate(session_input, session_policy_id)
                state_admitted = session.state_admitted
                clarification_blocks += int(session.execution_blocked_by_clarification)
            else:
                session = None
                # Frozen condition semantics v2.1: P1_BASE and non-session
                # ablations do not admit new session-state evidence.
                state_admitted = False
            candidate_allowed, effective_query = _candidate(p1)
            candidate_count += int(candidate_allowed)
            rag_execution = None
            if rag_enabled and candidate_allowed:
                rag_execution = execute_rag_for_condition_v1_1(
                    condition_id=condition_id,
                    candidate_allowed=True,
                    effective_query=effective_query or example.router_input.current_query,
                    safety_ledger=safety_ledger,
                    rag_runner=rag_runner,
                )
                if rag_execution is None:
                    raise ConditionIsolationError("CANDIDATE_RAG_CALL_MISSING")
                actual_calls += 1
                sufficiency_calls += 1
                admissions += len(rag_execution.admitted_ids)
                provider_calls += int(rag_execution.provider_calls)
                network_calls += int(rag_execution.network_access)
                rag_statuses[rag_execution.sufficiency_status] = (
                    rag_statuses.get(rag_execution.sufficiency_status, 0) + 1
                )
                receipt = {
                    "condition_id": condition_id,
                    "condition_call_sequence": actual_calls,
                    "sufficiency_status": rag_execution.sufficiency_status,
                    "retrieved_count": rag_execution.retrieved_count,
                    "supporting_count": rag_execution.supporting_count,
                    "admission_count": len(rag_execution.admitted_ids),
                }
                receipt_hashes.append(
                    hashlib.sha256(canonical_json_bytes(receipt, pretty=False)).digest()
                )
            # No governed persistent target exists in the three Gold partitions.
            # Persistent-enabled conditions therefore remain strict no-ops.
            if persistent_enabled:
                persistent_attempts += 0
            gold_state.append(example.labels.episodic_memory)
            predicted_state.append(state_admitted)
            plan_bytes = canonical_json_bytes(p1["capability_plan"], pretty=False)
            plan_hashes.append(hashlib.sha256(plan_bytes).digest())
            local_rows.append(
                {
                    "review_case_id": case_id,
                    "dataset_role": dataset_role,
                    "condition_id": condition_id,
                    "p1_capability_plan": p1["capability_plan"],
                    "p1_plan_rewritten": False,
                    "rag_candidate_allowed": candidate_allowed,
                    "rag_retrieval_attempted": rag_execution is not None,
                    "rag_execution": asdict(rag_execution) if rag_execution else None,
                    "session_state_result": asdict(session) if session else None,
                    "persistent_retrieval_attempted": False,
                }
            )
        if not rag_enabled and actual_calls:
            raise ConditionIsolationError("BLOCKED_RQ2_C1_R1_CONDITION_ISOLATION")
        if rag_enabled and actual_calls != candidate_count:
            raise ConditionIsolationError("BLOCKED_RQ2_C1_R1_CONDITION_ISOLATION")
        aggregates[condition_id] = {
            "record_count": len(values),
            "switches": {
                "rag": rag_enabled,
                "session_state": session_enabled,
                "persistent_memory": persistent_enabled,
            },
            "capability_metrics": base_capability_metrics,
            "episodic_state_use_metrics": binary_metrics(
                gold_state, predicted_state
            ),
            "candidate_gate_count": candidate_count,
            "actual_retriever_call_count": actual_calls,
            "sufficiency_call_count": sufficiency_calls,
            "admission_count": admissions,
            "provider_call_count": provider_calls,
            "network_call_count": network_calls,
            "rag_retrieval_attempt_count": actual_calls,
            "rag_local_execution_count": actual_calls,
            "rag_sufficiency_status_distribution": dict(sorted(rag_statuses.items())),
            "rag_evidence_admission_count": admissions,
            "rag_provider_calls": provider_calls,
            "rag_network_access": bool(network_calls),
            "condition_local_receipt_hash_chain": hashlib.sha256(
                b"".join(receipt_hashes)
            ).hexdigest(),
            "retrieval_result_reused_across_conditions": False,
            "sufficiency_result_reused_across_conditions": False,
            "admission_result_reused_across_conditions": False,
            "session_clarification_block_count": clarification_blocks,
            "persistent_retrieval_attempt_count": persistent_attempts,
            "persistent_mechanism_noop_without_governed_target": True,
            "p1_capability_plan_rewritten": False,
        }
    return (
        {
            "dataset_role": dataset_role,
            "record_count": len(values),
            "session_policy_id": session_policy_id,
            "conditions": aggregates,
            "p1_plan_hash_chain": hashlib.sha256(b"".join(plan_hashes)).hexdigest(),
            "condition_execution_order": list(CONDITION_IDS),
            "rag_precomputed_before_condition_loop": False,
            "authentic_used_for_policy_selection": False,
            "context_missing_used_for_policy_selection": False,
        },
        tuple(local_rows),
    )
