"""Derive D4 hard failures and completion eligibility from cumulative evidence."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import RQ2D3R4Error


class CompletionEvidenceError(RQ2D3R4Error):
    pass


REQUIRED_WORKER_ROLES = (
    "TRACK_B_FEATURE_EXTRACTOR_V1_2",
    "TRACK_B_B0_B1_P1_PREDICTOR_V1_2",
    "TRACK_B_FINAL_METRIC_WORKER_V1_2",
)


def derive_completion_evidence_v1_2(
    state: Mapping[str, Any],
    *,
    required_stage_receipt_roles: Sequence[str],
    expected_open_read_counts: Mapping[str, int],
    artifacts_bound: bool,
    state_chain_valid: bool,
    feature_prediction_binding_valid: bool,
    method_metric_complete: bool,
    statistical_complete: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    def add(category: str, detail: str) -> None:
        events.append({"category": category, "detail": detail})

    worker_roles = state.get("worker_roles", {})
    for role in REQUIRED_WORKER_ROLES:
        status = worker_roles.get(role, {}).get("status")
        if status != "CONSUMED_SUCCESS":
            add("worker_authority_failure", f"{role}:{status or 'ABSENT'}")
    for event in state.get("hard_failure_evidence", []):
        add(str(event.get("category") or "recorded_hard_failure"), str(event.get("detail") or "unspecified"))
    for evidence in state.get("firewall_evidence", []):
        for key in ("successful_forbidden_opens", "successful_forbidden_imports"):
            if int(evidence.get(key, 0)):
                add("runtime_firewall_violation", f"{key}:{evidence.get(key)}")
    for key, expected in expected_open_read_counts.items():
        observed = state.get("open_read_counters", {}).get(key)
        if observed != expected:
            add("input_open_read_count_mismatch", f"{key}:{observed}!={expected}")
    actual_receipt_roles = {
        str(receipt.get("artifact_role")) for receipt in state.get("stage_receipts", [])
    }
    for role in required_stage_receipt_roles:
        if role not in actual_receipt_roles:
            add("artifact_receipt_verification_failure", f"missing:{role}")
    checks = {
        "artifacts_bound": artifacts_bound,
        "state_chain_valid": state_chain_valid,
        "feature_prediction_binding_valid": feature_prediction_binding_valid,
        "method_metric_complete": method_metric_complete,
        "statistical_complete": statistical_complete,
    }
    categories = {
        "artifacts_bound": "artifact_binding_failure",
        "state_chain_valid": "state_chain_failure",
        "feature_prediction_binding_valid": "feature_prediction_binding_failure",
        "method_metric_complete": "method_metric_completeness_failure",
        "statistical_complete": "statistical_completeness_failure",
    }
    for name, passed in checks.items():
        if not passed:
            add(categories[name], name)
    if state.get("current_state") != "RESULT_PERSISTED":
        add("terminal_state_violation", f"completion_from:{state.get('current_state')}")
    hard_failure_count = len(events)
    workers_complete = all(
        worker_roles.get(role, {}).get("status") == "CONSUMED_SUCCESS"
        for role in REQUIRED_WORKER_ROLES
    )
    receipts_complete = all(role in actual_receipt_roles for role in required_stage_receipt_roles)
    open_counts_exact = all(
        state.get("open_read_counters", {}).get(key) == expected
        for key, expected in expected_open_read_counts.items()
    )
    completion_eligible = all(
        (
            hard_failure_count == 0,
            workers_complete,
            receipts_complete,
            open_counts_exact,
            all(checks.values()),
            state.get("current_state") == "RESULT_PERSISTED",
        )
    )
    return {
        "schema_version": "track-b-completion-evidence-v1-2",
        "hard_failure_events": events,
        "hard_failure_count": hard_failure_count,
        "required_workers_consumed_success": workers_complete,
        "required_stage_receipts_valid": receipts_complete,
        "expected_open_read_counts_exact": open_counts_exact,
        "artifacts_bound": artifacts_bound,
        "state_chain_valid": state_chain_valid,
        "feature_prediction_binding_valid": feature_prediction_binding_valid,
        "method_metric_complete": method_metric_complete,
        "statistical_complete": statistical_complete,
        "completion_eligible": completion_eligible,
    }


def require_completion_eligible_v1_2(evidence: Mapping[str, Any]) -> None:
    if (
        evidence.get("completion_eligible") is not True
        or not isinstance(evidence.get("hard_failure_events"), list)
        or evidence.get("hard_failure_count") != len(evidence["hard_failure_events"])
        or evidence.get("hard_failure_count") != 0
    ):
        raise CompletionEvidenceError("BLOCKED_RQ2_D4_COMPLETION_EVIDENCE")


def completion_evidence_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-completion-evidence-contract-v1-2",
        "status": "FROZEN",
        "hard_failure_count_source": "len(actual cumulative hard-failure events)",
        "constant_zero_assignment_allowed": False,
        "categories": [
            "worker_authority_failure",
            "credential_reuse_or_mismatch",
            "runtime_firewall_violation",
            "artifact_publication_failure",
            "artifact_receipt_verification_failure",
            "state_chain_failure",
            "input_open_read_count_mismatch",
            "feature_prediction_binding_failure",
            "method_metric_completeness_failure",
            "statistical_completeness_failure",
            "terminal_state_violation",
        ],
        "completion_requires_zero_failures": True,
        "completion_requires_all_workers_consumed_success": True,
        "completion_requires_all_stage_receipts": True,
        "completion_requires_exact_open_read_counts": True,
        "ineligible_result": "FAILED",
    }
