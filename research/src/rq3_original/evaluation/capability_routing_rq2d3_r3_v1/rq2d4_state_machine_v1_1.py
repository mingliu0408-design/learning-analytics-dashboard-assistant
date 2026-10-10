"""Effective D4 v1.1 state order."""

from __future__ import annotations


STATES = (
    "GLOBAL_RESERVED",
    "INPUT_IDENTITIES_VERIFIED",
    "EXTRACTOR_CREDENTIAL_COMMITTED",
    "COMBINED_CASE_SOURCE_OPENED",
    "FEATURE_VIEW_PERSISTED",
    "FEATURE_FIREWALL_VERIFIED",
    "PREDICTOR_CREDENTIAL_COMMITTED",
    "B0_PREDICTIONS_PERSISTED",
    "B1_PREDICTIONS_PERSISTED",
    "P1_PREDICTIONS_PERSISTED",
    "PREDICTION_FIREWALL_VERIFIED",
    "SECONDARY_SCOPE_METADATA_PERSISTED",
    "METRIC_CREDENTIAL_COMMITTED",
    "LABEL_GOLD_OPENED",
    "GROUPING_OPENED",
    "METHOD_METRICS_PERSISTED",
    "PRIMARY_STATISTICS_PERSISTED",
    "RESULT_PERSISTED",
    "COMPLETED",
)
STATE_INDEX = {state: index for index, state in enumerate(STATES)}
FAILURE_STATE = "FAILED"


def require_successor(previous: str, new: str) -> None:
    if previous == FAILURE_STATE or new == FAILURE_STATE:
        return
    if previous not in STATE_INDEX or new not in STATE_INDEX:
        raise ValueError("unknown D4 v1.1 state")
    if STATE_INDEX[new] != STATE_INDEX[previous] + 1:
        raise ValueError("non-sequential D4 v1.1 transition")


def state_machine_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-d4-state-machine-v1-1",
        "status": "FROZEN",
        "states": list(STATES),
        "failure_state": FAILURE_STATE,
        "retry_permitted_after_reservation": False,
        "secondary_state": "SECONDARY_SCOPE_METADATA_PERSISTED",
        "superseded_state": "SECONDARY_DIAGNOSTICS_PERSISTED",
        "completion_lock_persistent": True,
        "failure_lock_persistent": True,
    }
