"""Single-process, fixture-only, append-only offline persistent-memory store."""

from __future__ import annotations

from dataclasses import dataclass
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
from .store_projection import ProjectionItemV1, StoreSnapshotV1, build_snapshot


STORE_EVENTS = ("WRITE", "SUPERSEDE", "COMPLETE", "CANCEL", "DELETE")
EVENT_STATUS = {
    "SUPERSEDE": "SUPERSEDED",
    "COMPLETE": "COMPLETED",
    "CANCEL": "CANCELLED",
    "DELETE": "DELETED",
}


@dataclass(frozen=True)
class StoreEventV1:
    store_event_id: str
    student_scope_hash: str
    memory_id: str
    episode_id: str
    event_type: str
    event_time: str
    store_revision: int
    source_bundle_fingerprint: str
    event_fingerprint: str


class StoreIntegrityError(RuntimeError):
    pass


class OfflinePersistentMemoryStoreV1:
    """Research-only in-memory simulation; it is not a durable database."""

    def __init__(self) -> None:
        self._bundles: dict[str, ValidatedPersistentMemoryBundleV1_4] = {}
        self._payload_ids: set[str] = set()
        self._episode_ids: set[str] = set()
        self._event_ids: set[str] = set()
        self._events: list[StoreEventV1] = []
        self._projection: dict[str, ProjectionItemV1] = {}
        self._revision = 0
        self._session_counter = 0

    @property
    def store_revision(self) -> int:
        return self._revision

    @property
    def bundles(self) -> tuple[ValidatedPersistentMemoryBundleV1_4, ...]:
        return tuple(self._bundles[key] for key in sorted(self._bundles))

    @property
    def events(self) -> tuple[StoreEventV1, ...]:
        return tuple(self._events)

    def begin_logical_session(self) -> int:
        self._session_counter += 1
        return self._session_counter

    def _append_event(
        self,
        *,
        bundle: ValidatedPersistentMemoryBundleV1_4,
        event_type: str,
        event_time: str,
    ) -> StoreEventV1:
        if event_type not in STORE_EVENTS:
            raise StoreIntegrityError("BLOCKED_RQ2_C1_STORE_INTEGRITY")
        revision = self._revision + 1
        event_id = f"store-event-{revision:06d}"
        if event_id in self._event_ids:
            raise StoreIntegrityError("BLOCKED_RQ2_C1_STORE_INTEGRITY")
        body = {
            "store_event_id": event_id,
            "student_scope_hash": bundle.payload_ref.student_scope_hash,
            "memory_id": bundle.episode.memory_id,
            "episode_id": bundle.episode.episode_id,
            "event_type": event_type,
            "event_time": event_time,
            "store_revision": revision,
            "source_bundle_fingerprint": bundle.input_binding_fingerprint,
        }
        fingerprint = hashlib.sha256(canonical_json_bytes(body, pretty=False)).hexdigest()
        event = StoreEventV1(**body, event_fingerprint=fingerprint)
        self._events.append(event)
        self._event_ids.add(event_id)
        self._revision = revision
        return event

    def write_bundle(self, bundle: ValidatedPersistentMemoryBundleV1_4) -> StoreEventV1:
        require_validated_bundle_for_interface_v1_4(bundle, "STATE_PROJECTION_BUILDER")
        episode = bundle.episode
        if (
            episode.memory_id in self._bundles
            or episode.episode_id in self._episode_ids
            or episode.payload_id in self._payload_ids
        ):
            raise StoreIntegrityError("BLOCKED_RQ2_C1_STORE_INTEGRITY")
        self._bundles[episode.memory_id] = bundle
        self._episode_ids.add(episode.episode_id)
        self._payload_ids.add(episode.payload_id)
        event = self._append_event(
            bundle=bundle, event_type="WRITE", event_time=episode.ingested_at
        )
        self._projection[episode.memory_id] = ProjectionItemV1(
            memory_id=episode.memory_id,
            student_scope_hash=bundle.payload_ref.student_scope_hash,
            status=episode.status,
            bundle_fingerprint=bundle.input_binding_fingerprint,
            last_store_revision=event.store_revision,
        )
        return event

    def apply_state_event(
        self, memory_id: str, event_type: str, event_time: str
    ) -> StoreEventV1:
        if event_type not in EVENT_STATUS or memory_id not in self._bundles:
            raise StoreIntegrityError("BLOCKED_RQ2_C1_STORE_INTEGRITY")
        bundle = self._bundles[memory_id]
        current = self._projection[memory_id]
        event = self._append_event(
            bundle=bundle, event_type=event_type, event_time=event_time
        )
        self._projection[memory_id] = ProjectionItemV1(
            memory_id=memory_id,
            student_scope_hash=current.student_scope_hash,
            status=EVENT_STATUS[event_type],
            bundle_fingerprint=current.bundle_fingerprint,
            last_store_revision=event.store_revision,
        )
        return event

    def snapshot(self, student_scope_id: str) -> StoreSnapshotV1:
        scope_hash = derive_student_scope_hash_v1(student_scope_id)
        return build_snapshot(
            student_scope_hash=scope_hash,
            store_revision=self._revision,
            items=self._projection.values(),
        )

    def bundle(self, memory_id: str) -> ValidatedPersistentMemoryBundleV1_4:
        return self._bundles[memory_id]

    def status(self, memory_id: str) -> str:
        return self._projection[memory_id].status

    def projection_items(self) -> tuple[ProjectionItemV1, ...]:
        return tuple(self._projection[key] for key in sorted(self._projection))

    def safe_event_manifest(self) -> dict[str, Any]:
        return {
            "event_count": len(self._events),
            "store_revision": self._revision,
            "event_type_counts": {
                kind: sum(event.event_type == kind for event in self._events)
                for kind in STORE_EVENTS
            },
            "event_fingerprint_chain": hashlib.sha256(
                b"".join(bytes.fromhex(event.event_fingerprint) for event in self._events)
            ).hexdigest(),
            "payload_text_in_manifest": False,
        }
