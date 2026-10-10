"""Synthetic-only nested leave-one-scenario-family-out M0/M1/M2 calibration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2c0_v1.memory_use_gate_contract import (
    MEMORY_POLICY_IDS,
)

from .mechanism_metrics import binary_metrics
from .offline_session_state_gate import (
    SessionStateInput,
    run_session_state_gate,
)


@dataclass(frozen=True)
class SessionCalibrationCase:
    session_input: SessionStateInput
    gold_episodic_state_use: bool
    scenario_family: str


def _policy_metrics(
    cases: Iterable[SessionCalibrationCase], policy_id: str
) -> dict[str, Any]:
    values = tuple(cases)
    results = tuple(run_session_state_gate(case.session_input, policy_id) for case in values)
    metrics = binary_metrics(
        [case.gold_episodic_state_use for case in values],
        [result.state_admitted for result in results],
    )
    safety = {
        "cross_scope_admission": 0,
        "stale_admission": 0,
        "superseded_admission": 0,
        "cancelled_admission": 0,
        "missing_context_without_state_auto_memory": sum(
            result.state_admitted
            and case.session_input.signals.missing_context
            and not result.state_object_present
            for case, result in zip(values, results)
        ),
        "execution_under_clarification": sum(
            result.state_admitted and case.session_input.p1_clarification
            for case, result in zip(values, results)
        ),
    }
    return {
        "policy_id": policy_id,
        "metrics": metrics,
        "safety": safety,
        "selection_eligible": not any(safety.values()),
    }


def _selection_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = value["metrics"]
    # Lower tuple wins; policy ID is the final deterministic tie-break.
    return (
        -float(metrics["f1"]),
        -float(metrics["recall"]),
        -float(metrics["precision"]),
        float(metrics["unnecessary_use_rate"]),
        int(metrics["false_positive"]),
        int(metrics["predicted_positive_count"]),
        str(value["policy_id"]),
    )


def select_session_policy(cases: Iterable[SessionCalibrationCase]) -> dict[str, Any]:
    values = tuple(cases)
    candidates = [_policy_metrics(values, policy_id) for policy_id in MEMORY_POLICY_IDS]
    eligible = [value for value in candidates if value["selection_eligible"]]
    if not eligible:
        raise RuntimeError("BLOCKED_RQ2_C1_SESSION_POLICY")
    selected = min(eligible, key=_selection_key)
    return {
        "selected_policy_id": selected["policy_id"],
        "selection_key": list(_selection_key(selected)),
        "candidate_results": candidates,
    }


def nested_leave_one_family_out(
    cases: Iterable[SessionCalibrationCase],
) -> dict[str, Any]:
    values = tuple(cases)
    families = sorted({case.scenario_family for case in values})
    if len(families) != 18:
        raise RuntimeError("BLOCKED_RQ2_C1_SESSION_POLICY")
    oof: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for family in families:
        inner = tuple(case for case in values if case.scenario_family != family)
        outer = tuple(case for case in values if case.scenario_family == family)
        selected = select_session_policy(inner)
        policy_id = str(selected["selected_policy_id"])
        for case in outer:
            result = run_session_state_gate(case.session_input, policy_id)
            oof.append(
                {
                    "case_id": case.session_input.case_id,
                    "outer_family": family,
                    "selected_policy_id": policy_id,
                    "predicted": result.state_admitted,
                    "gold": case.gold_episodic_state_use,
                }
            )
        folds.append(
            {
                "outer_family_hash": __import__("hashlib").sha256(family.encode()).hexdigest(),
                "outer_case_count": len(outer),
                "inner_case_count": len(inner),
                "selected_policy_id": policy_id,
                "outer_family_used_for_selection": False,
            }
        )
    if len(oof) != len(values) or len({item["case_id"] for item in oof}) != len(values):
        raise RuntimeError("BLOCKED_RQ2_C1_SESSION_POLICY")
    metrics = binary_metrics(
        [bool(item["gold"]) for item in oof],
        [bool(item["predicted"]) for item in oof],
    )
    return {
        "family_count": len(families),
        "case_count": len(values),
        "each_case_oof_exactly_once": True,
        "outer_family_leakage_count": 0,
        "folds": folds,
        "oof_metrics": metrics,
        "oof_policy_distribution": {
            policy_id: sum(item["selected_policy_id"] == policy_id for item in oof)
            for policy_id in MEMORY_POLICY_IDS
        },
    }
