"""Offline audit of whether frozen data can evaluate the proposed P2 mechanisms."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from evaluation.capability_routing_rq2b_v1.gold_preflight import load_and_validate_gold
from utils.c_full_retrieval_adapter import (
    retrieve_course_evidence,
    validate_generation_isolation,
)

from . import ROOT, sha256_file
from .rag_gate_contract import normalise_sufficiency_status
from .reachability_audit import build_episodic_reachability_audit


LOCAL_ROWS_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/local_artifacts/"
    "rag_fixture_evaluability_rows_v1.jsonl"
)


def build_mechanism_evaluability(write_local: bool = True) -> dict[str, Any]:
    gold = load_and_validate_gold(ROOT)
    episodic = build_episodic_reachability_audit(write_local=write_local)
    course_cases = [item for item in gold.synthetic_gold if item.labels.course_retrieval]
    if len(course_cases) != 7:
        raise RuntimeError("BLOCKED_RQ2_C0_MECHANISM_EVALUATION_UNDERSPECIFIED")

    existing_statuses: Counter[str] = Counter()
    normalised_statuses: Counter[str] = Counter()
    local_rows: list[dict[str, Any]] = []
    runnable = 0
    generation_isolation_pass = 0
    for item in course_cases:
        result = retrieve_course_evidence(
            item.router_input.current_query,
            backend="v2_4",
            top_k=5,
            context={"retrieval_needed": True, "allow_v1_fallback": False},
        )
        existing = str(result.evidence_sufficiency.get("status") or "")
        normalised = normalise_sufficiency_status(existing)
        existing_statuses[existing] += 1
        normalised_statuses[normalised] += 1
        runnable += int(
            result.retrieval_available and result.retrieval_backend_used == "v2_4"
        )
        validate_generation_isolation(result)
        generation_isolation_pass += 1
        local_rows.append(
            {
                "case_id": item.router_input.case_id,
                "existing_sufficiency_status": existing,
                "normalised_sufficiency_status": normalised,
                "retrieval_available": bool(result.retrieval_available),
                "retrieval_backend_used": result.retrieval_backend_used,
                "supporting_chunk_count": len(result.supporting_chunk_ids),
                "generation_isolation_pass": True,
            }
        )

    local_rows.sort(key=lambda row: row["case_id"])
    local_path = ROOT / LOCAL_ROWS_RELATIVE
    if write_local:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in local_rows
            ),
            encoding="utf-8",
        )

    mechanisms = episodic["mechanism_classification_counts"]
    supported = normalised_statuses["SUPPORTED"]
    rag_negative = sum(
        normalised_statuses[name] for name in ("AMBIGUOUS", "UNSUPPORTED", "NO_RESULT")
    )
    persistent_target = mechanisms["REQUIRES_ADDITIONAL_EPISODIC_RETRIEVAL"]
    unresolved = mechanisms["UNRESOLVED_MECHANISM_LABEL"]
    structured_freshness = episodic["structured_state_with_freshness_status_count"]
    structured_negative = episodic[
        "structured_stale_or_superseded_negative_control_count"
    ]
    sufficient = bool(
        runnable == 7
        and supported > 0
        and rag_negative > 0
        and persistent_target > 0
        and structured_negative > 0
        and unresolved == 0
    )
    missing: list[str] = []
    if rag_negative == 0:
        missing.append("COURSE_EVIDENCE_SUFFICIENCY_NEGATIVE_FIXTURES")
    if persistent_target == 0:
        missing.append("PERSISTENT_RETRIEVAL_TARGET")
    if structured_negative == 0:
        missing.append("STALE_OR_SUPERSEDED_STRUCTURED_STATE_NEGATIVE_CONTROL")

    result = (
        "SUFFICIENT_FOR_OFFLINE_P2"
        if sufficient
        else "INSUFFICIENT_REQUIRES_SEPARATE_MECHANISM_FIXTURES"
    )
    return {
        "schema_version": "p2-mechanism-evaluability-v1",
        "stage": "RQ2-C0",
        "status": "PASS" if sufficient else "BLOCKED_FOR_P2_IMPLEMENTATION",
        "result": result,
        "entry_decision": (
            "READY_FOR_RQ2_C1_OFFLINE_P2_IMPLEMENTATION"
            if sufficient
            else "BLOCKED_RQ2_C0_MECHANISM_EVALUATION_UNDERSPECIFIED"
        ),
        "synthetic_support": {
            "course_retrieval_positive_count": 7,
            "episodic_memory_positive_count": 8,
            "clarification_positive_count": 3,
        },
        "rag_fixture_audit": {
            "local_fixture_runnable_count": runnable,
            "generation_isolation_pass_count": generation_isolation_pass,
            "existing_sufficiency_status_counts": dict(sorted(existing_statuses.items())),
            "normalised_sufficiency_status_counts": dict(
                sorted(normalised_statuses.items())
            ),
            "supported_fixture_count": supported,
            "ambiguous_unsupported_or_no_result_fixture_count": rag_negative,
            "dual_gate_discrimination_evaluable": rag_negative > 0,
        },
        "memory_fixture_audit": {
            "working_context_satisfied_count": mechanisms[
                "SATISFIED_BY_WORKING_CONTEXT"
            ],
            "additional_retrieval_target_count": persistent_target,
            "missing_context_clarification_target_count": mechanisms[
                "MISSING_CONTEXT_REQUIRES_CLARIFICATION"
            ],
            "unresolved_mechanism_label_count": unresolved,
            "episodic_state_use_target": "AVAILABLE_WORKING_CONTEXT_ONLY",
            "persistent_retrieval_target_available": persistent_target > 0,
            "history_non_active_state_example_count": episodic[
                "history_with_non_active_state_count"
            ],
            "structured_freshness_status_example_count": structured_freshness,
            "structured_stale_or_superseded_negative_control_count": structured_negative,
            "freshness_gate_evaluable": structured_negative > 0,
        },
        "missing_requirements": missing,
        "separate_mechanism_fixtures_auto_generated": False,
        "separate_mechanism_labels_auto_assigned": False,
        "local_rag_audit_record_count": len(local_rows),
        "local_rag_audit_sha256": sha256_file(local_path) if local_path.is_file() else "",
        "local_rag_audit_tracked": False,
        "authentic_used_for_mechanism_selection": False,
        "track_b_used": False,
        "provider_calls": 0,
        "network_access": False,
    }
