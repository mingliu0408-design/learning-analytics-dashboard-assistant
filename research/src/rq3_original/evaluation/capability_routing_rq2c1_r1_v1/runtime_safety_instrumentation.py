"""Append-only local runtime safety event instrumentation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from . import LOCAL_ROOT, canonical_json_bytes


SAFETY_EVENT_TYPES = (
    "UNVALIDATED_PAYLOAD_USE_ATTEMPT",
    "STALE_SNAPSHOT_ATTEMPT",
    "INVALID_STATE_TRANSITION_ATTEMPT",
    "DELETED_MEMORY_RESURRECTION_ATTEMPT",
    "BACKDATED_STORE_EVENT_ATTEMPT",
    "RAG_EXECUTION_IN_DISABLED_CONDITION",
    "CROSS_SCOPE_EXECUTION_CONTEXT_ATTEMPT",
    "EXECUTION_CONTEXT_FINGERPRINT_MISMATCH",
    "AMBIGUOUS_CORRECTION_TARGET_ATTEMPT",
)
LEDGER_CONTRACT_ID = "RUNTIME_SAFETY_EVENT_LEDGER_V1"


@dataclass(frozen=True)
class RuntimeSafetyEventV1:
    sequence: int
    event_type: str
    blocked: bool
    successful_violation: bool
    guard_id: str
    condition_id: str | None
    reason_code: str
    event_fingerprint: str


class RuntimeSafetyEventLedgerV1:
    """Process-local append-only ledger; only aggregates may be tracked."""

    def __init__(self, path: Path | None = None) -> None:
        self._events: list[RuntimeSafetyEventV1] = []
        self.path = path or (LOCAL_ROOT / "runtime_safety/runtime_safety_events_v1.jsonl")

    @property
    def events(self) -> tuple[RuntimeSafetyEventV1, ...]:
        return tuple(self._events)

    def reset_local_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"")

    def record(
        self,
        event_type: str,
        *,
        blocked: bool,
        successful_violation: bool,
        guard_id: str,
        reason_code: str,
        condition_id: str | None = None,
    ) -> RuntimeSafetyEventV1:
        if event_type not in SAFETY_EVENT_TYPES:
            raise ValueError("UNKNOWN_RUNTIME_SAFETY_EVENT")
        sequence = len(self._events) + 1
        body: Mapping[str, Any] = {
            "sequence": sequence,
            "event_type": event_type,
            "blocked": blocked,
            "successful_violation": successful_violation,
            "guard_id": guard_id,
            "condition_id": condition_id,
            "reason_code": reason_code,
        }
        event = RuntimeSafetyEventV1(
            **body,
            event_fingerprint=hashlib.sha256(
                canonical_json_bytes(body, pretty=False)
            ).hexdigest(),
        )
        self._events.append(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(canonical_json_bytes(asdict(event), pretty=False))
        return event

    def aggregate(self) -> dict[str, Any]:
        by_type: dict[str, dict[str, int]] = {}
        for event_type in SAFETY_EVENT_TYPES:
            selected = [event for event in self._events if event.event_type == event_type]
            by_type[event_type] = {
                "attempt_count": len(selected),
                "blocked_count": sum(event.blocked for event in selected),
                "successful_violation_count": sum(
                    event.successful_violation for event in selected
                ),
            }
        successful = sum(
            value["successful_violation_count"] for value in by_type.values()
        )
        attempts = sum(value["attempt_count"] for value in by_type.values())
        blocked = sum(value["blocked_count"] for value in by_type.values())
        return {
            "schema_version": "runtime-safety-results-v1",
            "ledger_contract_id": LEDGER_CONTRACT_ID,
            "event_types": by_type,
            "attempt_count": attempts,
            "blocked_count": blocked,
            "successful_violation_count": successful,
            "all_attempts_blocked": attempts == blocked,
            "status": "PASS" if successful == 0 and attempts == blocked else "FAIL",
            "aggregate_runtime_derived": True,
            "hardcoded_zero_counter_used": False,
            "local_event_rows_tracked": False,
        }
