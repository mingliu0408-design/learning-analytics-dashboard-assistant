"""D4 v1.2 state order with immutable FAILED and COMPLETED terminal states."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import RQ2D3R4Error


NORMAL_STATES = (
    "GLOBAL_RESERVED",
    "INPUT_IDENTITIES_VERIFIED",
    "PARENT_EXECUTION_RECEIPT_PERSISTED",
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
STATE_INDEX = {state: index for index, state in enumerate(NORMAL_STATES)}
FAILED = "FAILED"
COMPLETED = "COMPLETED"
TERMINAL_STATES = frozenset({FAILED, COMPLETED})


class TerminalStateError(RQ2D3R4Error):
    pass


def require_transition_v1_2(previous: str, new: str) -> None:
    if previous == FAILED:
        raise TerminalStateError("ALREADY_TERMINAL_FAILED")
    if previous == COMPLETED:
        raise TerminalStateError("ALREADY_TERMINAL_COMPLETED")
    if new == FAILED:
        if previous not in STATE_INDEX:
            raise TerminalStateError("unknown predecessor state")
        return
    if previous not in STATE_INDEX or new not in STATE_INDEX:
        raise TerminalStateError("unknown D4 v1.2 state")
    if STATE_INDEX[new] != STATE_INDEX[previous] + 1:
        raise TerminalStateError("non-sequential D4 v1.2 transition")


def validate_transition_chain_v1_2(
    transitions: Sequence[Mapping[str, Any]], *, current_state: str
) -> None:
    if not transitions:
        raise TerminalStateError("state transition chain absent")
    terminal_seen = False
    for index, transition in enumerate(transitions):
        if transition.get("transition_index") != index:
            raise TerminalStateError("state transition index mismatch")
        new = str(transition.get("current_state"))
        previous = transition.get("previous_state")
        if index == 0:
            if previous is not None or new != "GLOBAL_RESERVED":
                raise TerminalStateError("invalid initial state")
        else:
            expected_previous = transitions[index - 1].get("current_state")
            if previous != expected_previous or terminal_seen:
                raise TerminalStateError("post-terminal or broken state chain")
            require_transition_v1_2(str(previous), new)
        terminal_seen = new in TERMINAL_STATES
    if transitions[-1].get("current_state") != current_state:
        raise TerminalStateError("state chain terminal mismatch")


def terminal_state_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-terminal-state-contract-v1-2",
        "status": "FROZEN",
        "normal_states": list(NORMAL_STATES),
        "terminal_states": [FAILED, COMPLETED],
        "normal_to_failed_allowed_once": True,
        "failed_to_any_rejected": True,
        "failed_rewrite_rejected": True,
        "completed_to_any_rejected": True,
        "completed_rewrite_rejected": True,
        "first_root_failure_immutable": True,
        "post_terminal_chain_rejected": True,
        "retry_permitted": False,
    }
