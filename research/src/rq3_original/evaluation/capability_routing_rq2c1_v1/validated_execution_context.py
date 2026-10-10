"""Request-, condition-, revision-, and snapshot-bound Memory execution context."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    MemoryIndexRecordV1_1,
    temporal_validity,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_memory_bundle_v1_4 import (
    ValidatedPersistentMemoryBundleV1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_retrieval_plan_v1_2 import (
    ValidatedRetrievalPlanV1_2,
    verify_validated_retrieval_plan_v1_2,
)

from . import CONDITION_IDS, canonical_json_bytes
from .offline_memory_store import OfflinePersistentMemoryStoreV1
from .store_projection import StoreSnapshotV1


class ExecutionContextError(PermissionError):
    pass


@dataclass(frozen=True)
class ValidatedMemoryExecutionContextV1:
    validated_plan: ValidatedRetrievalPlanV1_2
    validated_bundle: ValidatedPersistentMemoryBundleV1_4
    snapshot_fingerprint: str
    store_revision: int
    condition_id: str
    request_fingerprint: str
    context_fingerprint: str


def _temporal_record(bundle: ValidatedPersistentMemoryBundleV1_4) -> MemoryIndexRecordV1_1:
    episode = bundle.episode
    return MemoryIndexRecordV1_1(
        memory_id=episode.memory_id,
        student_scope_id=episode.student_scope_id,
        memory_type=episode.memory_type,
        status=episode.status,
        event_time=episode.event_time,
        valid_from=episode.valid_from,
        valid_until=episode.valid_until,
    )


def create_validated_execution_context(
    *,
    plan: ValidatedRetrievalPlanV1_2,
    bundle: ValidatedPersistentMemoryBundleV1_4,
    snapshot: StoreSnapshotV1,
    store: OfflinePersistentMemoryStoreV1,
    condition_id: str,
    request_fingerprint: str,
) -> ValidatedMemoryExecutionContextV1:
    verify_validated_retrieval_plan_v1_2(plan)
    require_validated_bundle_for_interface_v1_4(bundle, "MEMORY_ADMISSION_BUILDER")
    if condition_id not in CONDITION_IDS or not request_fingerprint:
        raise ExecutionContextError("INVALID_EXECUTION_CONTEXT")
    episode = bundle.episode
    if episode.student_scope_id != plan.student_scope_id:
        raise ExecutionContextError("CROSS_STUDENT_SCOPE")
    if snapshot.store_revision != store.store_revision:
        raise ExecutionContextError("STALE_STORE_SNAPSHOT")
    if episode.memory_id not in snapshot.status_by_memory_id:
        raise ExecutionContextError("MEMORY_NOT_IN_SNAPSHOT")
    projected = snapshot.status_by_memory_id[episode.memory_id]
    if projected == "DELETED" or episode.memory_id in snapshot.tombstoned_memory_ids:
        raise ExecutionContextError("DELETED_MEMORY")
    if projected != episode.status:
        raise ExecutionContextError("STALE_BUNDLE_PROJECTION_STATE")
    if not temporal_validity(_temporal_record(bundle), plan.query_time_utc):
        raise ExecutionContextError("TEMPORALLY_INVALID")
    body = {
        "plan_fingerprint": plan.plan_fingerprint,
        "bundle_fingerprint": bundle.input_binding_fingerprint,
        "snapshot_fingerprint": snapshot.snapshot_fingerprint,
        "store_revision": snapshot.store_revision,
        "condition_id": condition_id,
        "request_fingerprint": request_fingerprint,
    }
    fingerprint = hashlib.sha256(canonical_json_bytes(body, pretty=False)).hexdigest()
    return ValidatedMemoryExecutionContextV1(
        validated_plan=plan,
        validated_bundle=bundle,
        snapshot_fingerprint=snapshot.snapshot_fingerprint,
        store_revision=snapshot.store_revision,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
        context_fingerprint=fingerprint,
    )


def verify_execution_context(
    context: ValidatedMemoryExecutionContextV1,
    *,
    store: OfflinePersistentMemoryStoreV1,
    condition_id: str,
    request_fingerprint: str,
) -> None:
    if context.store_revision != store.store_revision:
        raise ExecutionContextError("STALE_STORE_SNAPSHOT")
    if context.condition_id != condition_id:
        raise ExecutionContextError("CROSS_CONDITION_CONTEXT_REUSE")
    if context.request_fingerprint != request_fingerprint:
        raise ExecutionContextError("CROSS_QUERY_CONTEXT_REUSE")
    verify_validated_retrieval_plan_v1_2(context.validated_plan)
    require_validated_bundle_for_interface_v1_4(
        context.validated_bundle, "MEMORY_ADMISSION_BUILDER"
    )
