"""Append-only offline store with explicit lifecycle and event-time integrity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.student_scope_hash_contract import (
    derive_student_scope_hash_v1,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_memory_bundle_v1_4 import (
    ValidatedPersistentMemoryBundleV1_4,
)

from . import canonical_json_bytes
from .runtime_safety_instrumentation import RuntimeSafetyEventLedgerV1
from .store_projection_v1_1 import (
    ProjectionItemV1_1,
    StoreSnapshotV1_1,
    build_snapshot_v1_1,
    replay_projection_v1_1,
)


STORE_TRANSITION_CONTRACT_ID = "OFFLINE_MEMORY_STORE_STATE_MACHINE_V1_1"
STORE_EVENTS = ("WRITE", "SUPERSEDE", "COMPLETE", "CANCEL", "DELETE")
EVENT_STATUS = {
    "SUPERSEDE": "SUPERSEDED",
    "COMPLETE": "COMPLETED",
    "CANCEL": "CANCELLED",
    "DELETE": "DELETED",
}
ALLOWED_TRANSITIONS = {
    "ACTIVE": frozenset({"SUPERSEDED", "COMPLETED", "CANCELLED", "DELETED"}),
    "SUPERSEDED": frozenset({"DELETED"}),
    "COMPLETED": frozenset({"DELETED"}),
    "CANCELLED": frozenset({"DELETED"}),
    "STALE": frozenset({"DELETED"}),
    "DELETED": frozenset(),
}


class StoreIntegrityError(RuntimeError):
    pass


def _aware_utc(value: str) -> datetime:
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise StoreIntegrityError("INVALID_STORE_EVENT_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StoreIntegrityError("NAIVE_STORE_EVENT_TIME")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class StoreEventV1_1:
    store_event_id: str
    student_scope_hash: str
    memory_id: str
    episode_id: str
    event_type: str
    previous_status: str | None
    new_status: str
    previous_event_time: str | None
    event_time: str
    transition_contract_id: str
    store_revision: int
    source_bundle_fingerprint: str
    event_fingerprint: str


class OfflinePersistentMemoryStoreV1_1:
    """Fixture-only in-memory store; no durable or production persistence claim."""

    def __init__(
        self, *, safety_ledger: RuntimeSafetyEventLedgerV1 | None = None
    ) -> None:
        self._bundles: dict[str, ValidatedPersistentMemoryBundleV1_4] = {}
        self._payload_ids: set[str] = set()
        self._episode_ids: set[str] = set()
        self._event_ids: set[str] = set()
        self._events: list[StoreEventV1_1] = []
        self._revision = 0
        self._session_counter = 0
        self._safety = safety_ledger
        self.__context_factory_token = object()
        self._issued_contexts: set[str] = set()

    @property
    def store_revision(self) -> int:
        return self._revision

    @property
    def bundles(self) -> tuple[ValidatedPersistentMemoryBundleV1_4, ...]:
        return tuple(self._bundles[key] for key in sorted(self._bundles))

    @property
    def events(self) -> tuple[StoreEventV1_1, ...]:
        return tuple(self._events)

    def begin_logical_session(self) -> int:
        self._session_counter += 1
        return self._session_counter

    def _record_safety(
        self, event_type: str, reason: str, *, condition_id: str | None = None
    ) -> None:
        if self._safety is not None:
            self._safety.record(
                event_type,
                blocked=True,
                successful_violation=False,
                guard_id="OFFLINE_MEMORY_STORE_V1_1",
                reason_code=reason,
                condition_id=condition_id,
            )

    def _projection(self) -> tuple[dict[str, ProjectionItemV1_1], frozenset[str]]:
        projection, tombstones, revision = replay_projection_v1_1(self._events)
        if revision != self._revision:
            raise StoreIntegrityError("STORE_REPLAY_REVISION_MISMATCH")
        return projection, tombstones

    def _validate_event_time(
        self,
        *,
        bundle: ValidatedPersistentMemoryBundleV1_4,
        event_time: str,
        previous_event_time: str | None,
    ) -> None:
        try:
            observed = _aware_utc(event_time)
            ingested = _aware_utc(bundle.episode.ingested_at)
            previous = _aware_utc(previous_event_time) if previous_event_time else None
        except StoreIntegrityError as exc:
            self._record_safety("BACKDATED_STORE_EVENT_ATTEMPT", str(exc))
            raise
        if observed < ingested or (previous is not None and observed < previous):
            self._record_safety(
                "BACKDATED_STORE_EVENT_ATTEMPT", "BACKDATED_STORE_EVENT"
            )
            raise StoreIntegrityError("BACKDATED_STORE_EVENT")

    def _append_event(
        self,
        *,
        bundle: ValidatedPersistentMemoryBundleV1_4,
        event_type: str,
        previous_status: str | None,
        new_status: str,
        previous_event_time: str | None,
        event_time: str,
    ) -> StoreEventV1_1:
        self._validate_event_time(
            bundle=bundle,
            event_time=event_time,
            previous_event_time=previous_event_time,
        )
        revision = self._revision + 1
        event_id = f"store-event-{revision:06d}"
        if event_id in self._event_ids:
            raise StoreIntegrityError("DUPLICATE_STORE_EVENT_ID")
        body = {
            "store_event_id": event_id,
            "student_scope_hash": bundle.payload_ref.student_scope_hash,
            "memory_id": bundle.episode.memory_id,
            "episode_id": bundle.episode.episode_id,
            "event_type": event_type,
            "previous_status": previous_status,
            "new_status": new_status,
            "previous_event_time": previous_event_time,
            "event_time": event_time,
            "transition_contract_id": STORE_TRANSITION_CONTRACT_ID,
            "store_revision": revision,
            "source_bundle_fingerprint": bundle.input_binding_fingerprint,
        }
        event = StoreEventV1_1(
            **body,
            event_fingerprint=hashlib.sha256(
                canonical_json_bytes(body, pretty=False)
            ).hexdigest(),
        )
        self._events.append(event)
        self._event_ids.add(event_id)
        self._revision = revision
        return event

    def write_bundle(
        self, bundle: ValidatedPersistentMemoryBundleV1_4
    ) -> StoreEventV1_1:
        try:
            require_validated_bundle_for_interface_v1_4(
                bundle, "STATE_PROJECTION_BUILDER"
            )
        except Exception:
            self._record_safety(
                "UNVALIDATED_PAYLOAD_USE_ATTEMPT", "UNVALIDATED_OR_STALE_BUNDLE"
            )
            raise StoreIntegrityError("UNVALIDATED_OR_STALE_BUNDLE")
        episode = bundle.episode
        if (
            episode.memory_id in self._bundles
            or episode.episode_id in self._episode_ids
            or episode.payload_id in self._payload_ids
        ):
            raise StoreIntegrityError("DUPLICATE_MEMORY_IDENTITY")
        if episode.status not in ALLOWED_TRANSITIONS:
            raise StoreIntegrityError("INVALID_INITIAL_MEMORY_STATUS")
        self._bundles[episode.memory_id] = bundle
        self._episode_ids.add(episode.episode_id)
        self._payload_ids.add(episode.payload_id)
        try:
            return self._append_event(
                bundle=bundle,
                event_type="WRITE",
                previous_status=None,
                new_status=episode.status,
                previous_event_time=None,
                event_time=episode.ingested_at,
            )
        except Exception:
            self._bundles.pop(episode.memory_id, None)
            self._episode_ids.discard(episode.episode_id)
            self._payload_ids.discard(episode.payload_id)
            raise

    def apply_state_event(
        self, memory_id: str, event_type: str, event_time: str
    ) -> StoreEventV1_1:
        if event_type not in EVENT_STATUS or memory_id not in self._bundles:
            self._record_safety(
                "INVALID_STATE_TRANSITION_ATTEMPT", "INVALID_STORE_STATE_TRANSITION"
            )
            raise StoreIntegrityError("INVALID_STORE_STATE_TRANSITION")
        projection, tombstones = self._projection()
        current = projection[memory_id]
        new_status = EVENT_STATUS[event_type]
        if memory_id in tombstones and new_status != "DELETED":
            self._record_safety(
                "DELETED_MEMORY_RESURRECTION_ATTEMPT",
                "INVALID_STORE_STATE_TRANSITION",
            )
            raise StoreIntegrityError("INVALID_STORE_STATE_TRANSITION")
        if new_status not in ALLOWED_TRANSITIONS[current.status]:
            self._record_safety(
                "INVALID_STATE_TRANSITION_ATTEMPT",
                "INVALID_STORE_STATE_TRANSITION",
            )
            raise StoreIntegrityError("INVALID_STORE_STATE_TRANSITION")
        return self._append_event(
            bundle=self._bundles[memory_id],
            event_type=event_type,
            previous_status=current.status,
            new_status=new_status,
            previous_event_time=current.last_event_time,
            event_time=event_time,
        )

    def snapshot(self, student_scope_id: str) -> StoreSnapshotV1_1:
        return build_snapshot_v1_1(
            student_scope_hash=derive_student_scope_hash_v1(student_scope_id),
            events=self._events,
        )

    def bundle(self, memory_id: str) -> ValidatedPersistentMemoryBundleV1_4:
        return self._bundles[memory_id]

    def has_memory(self, memory_id: str) -> bool:
        return memory_id in self._bundles

    def status(self, memory_id: str) -> str:
        projection, _tombstones = self._projection()
        return projection[memory_id].status

    def is_tombstoned(self, memory_id: str) -> bool:
        _projection, tombstones = self._projection()
        return memory_id in tombstones

    def projection_items(self) -> tuple[ProjectionItemV1_1, ...]:
        projection, _tombstones = self._projection()
        return tuple(projection[key] for key in sorted(projection))

    def _context_token(self) -> object:
        return self.__context_factory_token

    def _register_context(self, context_fingerprint: str) -> None:
        self._issued_contexts.add(context_fingerprint)

    def _context_was_issued(self, context_fingerprint: str) -> bool:
        return context_fingerprint in self._issued_contexts

    def safe_event_manifest(self) -> dict[str, Any]:
        projection, tombstones = self._projection()
        replay_projection, replay_tombstones, replay_revision = replay_projection_v1_1(
            self._events
        )
        return {
            "event_count": len(self._events),
            "store_revision": self._revision,
            "event_type_counts": {
                kind: sum(event.event_type == kind for event in self._events)
                for kind in STORE_EVENTS
            },
            "event_fingerprint_chain": hashlib.sha256(
                b"".join(
                    bytes.fromhex(event.event_fingerprint) for event in self._events
                )
            ).hexdigest(),
            "projection_replay_identical": projection == replay_projection,
            "tombstone_replay_identical": tombstones == replay_tombstones,
            "revision_replay_identical": self._revision == replay_revision,
            "tombstone_count": len(tombstones),
            "payload_text_in_manifest": False,
            "event_rows_tracked": False,
        }
