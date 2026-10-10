"""Event-replayed projection, permanent tombstones, and deterministic snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping, Protocol

from . import canonical_json_bytes


class EventLike(Protocol):
    memory_id: str
    student_scope_hash: str
    previous_status: str | None
    new_status: str
    event_type: str
    event_time: str
    store_revision: int
    source_bundle_fingerprint: str


@dataclass(frozen=True)
class ProjectionItemV1_1:
    memory_id: str
    student_scope_hash: str
    status: str
    bundle_fingerprint: str
    last_store_revision: int
    last_event_time: str


@dataclass(frozen=True)
class StoreSnapshotV1_1:
    student_scope_hash: str
    store_revision: int
    active_memory_ids: tuple[str, ...]
    tombstoned_memory_ids: tuple[str, ...]
    projection_hash: str
    snapshot_fingerprint: str
    status_by_memory_id: Mapping[str, str]
    bundle_fingerprint_by_memory_id: Mapping[str, str]


def replay_projection_v1_1(
    events: Iterable[EventLike],
) -> tuple[dict[str, ProjectionItemV1_1], frozenset[str], int]:
    projection: dict[str, ProjectionItemV1_1] = {}
    tombstones: set[str] = set()
    revision = 0
    for event in events:
        if event.store_revision != revision + 1:
            raise ValueError("NON_MONOTONIC_STORE_REVISION")
        current = projection.get(event.memory_id)
        current_status = current.status if current else None
        if current_status != event.previous_status:
            raise ValueError("EVENT_REPLAY_PREVIOUS_STATUS_MISMATCH")
        if event.memory_id in tombstones and event.new_status != "DELETED":
            raise ValueError("DELETED_MEMORY_RESURRECTION")
        projection[event.memory_id] = ProjectionItemV1_1(
            memory_id=event.memory_id,
            student_scope_hash=event.student_scope_hash,
            status=event.new_status,
            bundle_fingerprint=event.source_bundle_fingerprint,
            last_store_revision=event.store_revision,
            last_event_time=event.event_time,
        )
        if event.event_type == "DELETE":
            tombstones.add(event.memory_id)
        revision = event.store_revision
    return projection, frozenset(tombstones), revision


def projection_hash_v1_1(items: Iterable[ProjectionItemV1_1]) -> str:
    rows = [
        {
            "memory_id": item.memory_id,
            "student_scope_hash": item.student_scope_hash,
            "status": item.status,
            "bundle_fingerprint": item.bundle_fingerprint,
            "last_store_revision": item.last_store_revision,
            "last_event_time": item.last_event_time,
        }
        for item in sorted(items, key=lambda value: value.memory_id)
    ]
    return hashlib.sha256(canonical_json_bytes(rows, pretty=False)).hexdigest()


def build_snapshot_v1_1(
    *,
    student_scope_hash: str,
    events: Iterable[EventLike],
) -> StoreSnapshotV1_1:
    event_values = tuple(events)
    projection, all_tombstones, revision = replay_projection_v1_1(event_values)
    scoped = tuple(
        sorted(
            (
                item
                for item in projection.values()
                if item.student_scope_hash == student_scope_hash
            ),
            key=lambda item: item.memory_id,
        )
    )
    status = {item.memory_id: item.status for item in scoped}
    bundles = {item.memory_id: item.bundle_fingerprint for item in scoped}
    tombstones = tuple(
        sorted(
            item.memory_id for item in scoped if item.memory_id in all_tombstones
        )
    )
    active = tuple(
        sorted(
            item.memory_id
            for item in scoped
            if item.status in {"ACTIVE", "COMPLETED"}
            and item.memory_id not in all_tombstones
        )
    )
    p_hash = projection_hash_v1_1(scoped)
    body: dict[str, Any] = {
        "student_scope_hash": student_scope_hash,
        "store_revision": revision,
        "active_memory_ids": list(active),
        "tombstoned_memory_ids": list(tombstones),
        "projection_hash": p_hash,
        "status_by_memory_id": dict(sorted(status.items())),
        "bundle_fingerprint_by_memory_id": dict(sorted(bundles.items())),
    }
    return StoreSnapshotV1_1(
        student_scope_hash=student_scope_hash,
        store_revision=revision,
        active_memory_ids=active,
        tombstoned_memory_ids=tombstones,
        projection_hash=p_hash,
        snapshot_fingerprint=hashlib.sha256(
            canonical_json_bytes(body, pretty=False)
        ).hexdigest(),
        status_by_memory_id=body["status_by_memory_id"],
        bundle_fingerprint_by_memory_id=body["bundle_fingerprint_by_memory_id"],
    )
