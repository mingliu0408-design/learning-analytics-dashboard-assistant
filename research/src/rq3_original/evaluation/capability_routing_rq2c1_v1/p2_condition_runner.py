"""Independent P1/P2 condition switches over frozen P1 local predictions."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2b_v1.capability_metrics import (
    evaluate_capability_predictions,
)
from evaluation.capability_routing_rq2b_v1.gold_preflight import GoldExample
from evaluation.capability_routing_rq2c0_v1.rag_gate_contract import (
    retrieval_candidate_gate,
)

from . import CONDITION_IDS, ROOT, canonical_json_bytes
from .mechanism_metrics import binary_metrics
from .offline_dual_gated_rag import run_local_course_rag
from .offline_session_state_gate import session_input_from_p1, run_session_state_gate


def load_p1_ledger(relative: Path) -> tuple[Mapping[str, Any], ...]:
    rows = tuple(
        json.loads(line)
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line
    )
    ids = [str(row["review_case_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("P1 ledger duplicate case identity")
    return rows


def _metric_rows(
    examples: Iterable[GoldExample], p1_by_id: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in examples:
        case_id = example.router_input.case_id
        p1 = p1_by_id[case_id]
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


def run_conditions(
    *,
    examples: Iterable[GoldExample],
    p1_rows: Iterable[Mapping[str, Any]],
    session_policy_id: str,
    dataset_role: str,
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    values = tuple(examples)
    p1_by_id = {str(row["review_case_id"]): row for row in p1_rows}
    if set(p1_by_id) != {item.router_input.case_id for item in values}:
        raise ValueError("P1/Gold identity mismatch")
    base_capability_metrics = evaluate_capability_predictions(
        _metric_rows(values, p1_by_id)
    )
    rag_by_id: dict[str, Any] = {}
    for example in values:
        case_id = example.router_input.case_id
        p1 = p1_by_id[case_id]
        session_input = session_input_from_p1(p1)
        source_policy = dict(
            (p1.get("capability_plan") or {}).get("source_policy") or {}
        )
        source_allowed = "course_material" in set(
            source_policy.get("allowed_source_types") or ()
        )
        candidate = retrieval_candidate_gate(
            p1_course_retrieval="course_retrieval"
            in set(p1["predicted_capabilities"]),
            p1_clarification=session_input.p1_clarification,
            course_source_authorised=source_allowed,
        )
        if candidate:
            envelope = dict(p1.get("context_envelope") or {})
            effective_query = str(
                envelope.get("resolved_query")
                or envelope.get("original_query")
                or example.router_input.current_query
            )
            rag_by_id[case_id] = run_local_course_rag(effective_query)
    local_rows: list[Mapping[str, Any]] = []
    aggregates: dict[str, Any] = {}
    plan_hashes: list[bytes] = []
    for condition_id in CONDITION_IDS:
        rag_enabled = condition_id in {"P2_RAG_ONLY", "P2_FULL"}
        session_enabled = condition_id in {"P2_SESSION_STATE_ONLY", "P2_FULL"}
        persistent_enabled = condition_id in {
            "P2_PERSISTENT_MEMORY_ONLY",
            "P2_FULL",
        }
        gold_state: list[bool] = []
        predicted_state: list[bool] = []
        rag_attempts = 0
        rag_executions = 0
        rag_admissions = 0
        rag_statuses: dict[str, int] = {}
        persistent_attempts = 0
        clarification_blocks = 0
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
                state_admitted = "episodic_memory" in set(p1["predicted_capabilities"])
            source_policy = dict((p1.get("capability_plan") or {}).get("source_policy") or {})
            source_allowed = "course_material" in set(
                source_policy.get("allowed_source_types") or ()
            )
            if rag_enabled:
                rag_attempts += int(case_id in rag_by_id)
                if case_id in rag_by_id:
                    rag_execution = rag_by_id[case_id]
                    rag_executions += 1
                    rag_admissions += len(rag_execution.admitted_ids)
                    rag_statuses[rag_execution.sufficiency_status] = (
                        rag_statuses.get(rag_execution.sufficiency_status, 0) + 1
                    )
                else:
                    rag_execution = None
            else:
                rag_execution = None
            # No governed persistent target exists in these Gold partitions.
            # Enabling the mechanism therefore must be a strict no-op.
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
                    "rag_retrieval_attempted": bool(rag_execution),
                    "rag_execution": asdict(rag_execution) if rag_execution else None,
                    "session_state_result": asdict(session) if session else None,
                    "persistent_retrieval_attempted": False,
                }
            )
        aggregates[condition_id] = {
            "record_count": len(values),
            "switches": {
                "rag": rag_enabled,
                "session_state": session_enabled,
                "persistent_memory": persistent_enabled,
            },
            "capability_metrics": base_capability_metrics,
            "episodic_state_use_metrics": binary_metrics(gold_state, predicted_state),
            "rag_retrieval_attempt_count": rag_attempts,
            "rag_local_execution_count": rag_executions,
            "rag_sufficiency_status_distribution": dict(sorted(rag_statuses.items())),
            "rag_evidence_admission_count": rag_admissions,
            "rag_provider_calls": 0,
            "rag_network_access": False,
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
            "authentic_used_for_policy_selection": False,
            "context_missing_used_for_policy_selection": False,
        },
        tuple(local_rows),
    )
