"""Derived, payload-free current-state projection and deterministic snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping

from . import canonical_json_bytes


TERMINAL_STATUS_BY_EVENT = {
    "SUPERSEDE": "SUPERSEDED",
    "COMPLETE": "COMPLETED",
    "CANCEL": "CANCELLED",
    "DELETE": "DELETED",
}


@dataclass(frozen=True)
class ProjectionItemV1:
    memory_id: str
    student_scope_hash: str
    status: str
    bundle_fingerprint: str
    last_store_revision: int


@dataclass(frozen=True)
class StoreSnapshotV1:
    student_scope_hash: str
    store_revision: int
    active_memory_ids: tuple[str, ...]
    tombstoned_memory_ids: tuple[str, ...]
    projection_hash: str
    snapshot_fingerprint: str
    status_by_memory_id: Mapping[str, str]


def projection_hash(items: Iterable[ProjectionItemV1]) -> str:
    rows = [
        {
            "memory_id": item.memory_id,
            "student_scope_hash": item.student_scope_hash,
            "status": item.status,
            "bundle_fingerprint": item.bundle_fingerprint,
            "last_store_revision": item.last_store_revision,
        }
        for item in sorted(items, key=lambda value: value.memory_id)
    ]
    return hashlib.sha256(canonical_json_bytes(rows, pretty=False)).hexdigest()


def build_snapshot(
    *, student_scope_hash: str, store_revision: int, items: Iterable[ProjectionItemV1]
) -> StoreSnapshotV1:
    scoped = tuple(
        sorted(
            (item for item in items if item.student_scope_hash == student_scope_hash),
            key=lambda value: value.memory_id,
        )
    )
    p_hash = projection_hash(scoped)
    status = {item.memory_id: item.status for item in scoped}
    body: dict[str, Any] = {
        "student_scope_hash": student_scope_hash,
        "store_revision": store_revision,
        "active_memory_ids": sorted(
            memory_id for memory_id, value in status.items() if value in {"ACTIVE", "COMPLETED"}
        ),
        "tombstoned_memory_ids": sorted(
            memory_id for memory_id, value in status.items() if value == "DELETED"
        ),
        "projection_hash": p_hash,
        "status_by_memory_id": dict(sorted(status.items())),
    }
    fingerprint = hashlib.sha256(canonical_json_bytes(body, pretty=False)).hexdigest()
    return StoreSnapshotV1(
        student_scope_hash=student_scope_hash,
        store_revision=store_revision,
        active_memory_ids=tuple(body["active_memory_ids"]),
        tombstoned_memory_ids=tuple(body["tombstoned_memory_ids"]),
        projection_hash=p_hash,
        snapshot_fingerprint=fingerprint,
        status_by_memory_id=body["status_by_memory_id"],
    )
