"""Current-store-bound execution contexts with full transaction revalidation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from evaluation.capability_routing_rq2c0_r4_v1.student_scope_hash_contract import (
    derive_student_scope_hash_v1,
)
from evaluation.capability_routing_rq2c0_r5_v1.retrieval_time_integrity_v1 import (
    temporal_validity_aware_v1_1,
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
from .offline_memory_store_v1_1 import OfflinePersistentMemoryStoreV1_1
from .runtime_safety_instrumentation import RuntimeSafetyEventLedgerV1
from .store_projection_v1_1 import StoreSnapshotV1_1


EXECUTION_CONTEXT_CONTRACT_ID = "VALIDATED_MEMORY_EXECUTION_CONTEXT_V1_1"
REJECTED_PROJECTION_STATUSES = frozenset(
    {"SUPERSEDED", "CANCELLED", "STALE", "DELETED"}
)


class ExecutionContextError(PermissionError):
    pass


@dataclass(frozen=True)
class ValidatedMemoryExecutionContextV1_1:
    validated_plan: ValidatedRetrievalPlanV1_2
    validated_bundle: ValidatedPersistentMemoryBundleV1_4
    student_scope_hash: str
    snapshot_fingerprint: str
    projection_hash: str
    projected_status: str
    store_revision: int
    condition_id: str
    request_fingerprint: str
    context_fingerprint: str
    contract_id: str
    _factory_token: object = field(repr=False, compare=False)


def _record(
    ledger: RuntimeSafetyEventLedgerV1 | None,
    event_type: str,
    reason: str,
    *,
    condition_id: str | None = None,
) -> None:
    if ledger is not None:
        ledger.record(
            event_type,
            blocked=True,
            successful_violation=False,
            guard_id="EXECUTION_CONTEXT_V1_1",
            reason_code=reason,
            condition_id=condition_id,
        )


def _status_allowed(status: str, plan: ValidatedRetrievalPlanV1_2) -> bool:
    if status == "ACTIVE":
        return True
    if status == "COMPLETED":
        return "COMPLETION" in set(plan.target_memory_types)
    return False


def _context_body(
    *,
    plan: ValidatedRetrievalPlanV1_2,
    bundle: ValidatedPersistentMemoryBundleV1_4,
    student_scope_hash: str,
    snapshot: StoreSnapshotV1_1,
    projected_status: str,
    condition_id: str,
    request_fingerprint: str,
) -> dict[str, object]:
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "bundle_fingerprint": bundle.input_binding_fingerprint,
        "student_scope_hash": student_scope_hash,
        "snapshot_fingerprint": snapshot.snapshot_fingerprint,
        "projection_hash": snapshot.projection_hash,
        "projected_status": projected_status,
        "store_revision": snapshot.store_revision,
        "condition_id": condition_id,
        "request_fingerprint": request_fingerprint,
        "contract_id": EXECUTION_CONTEXT_CONTRACT_ID,
    }


def _validate_common(
    *,
    plan: ValidatedRetrievalPlanV1_2,
    bundle: ValidatedPersistentMemoryBundleV1_4,
    snapshot: StoreSnapshotV1_1,
    store: OfflinePersistentMemoryStoreV1_1,
    condition_id: str,
    request_fingerprint: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None,
) -> tuple[str, str]:
    if condition_id not in CONDITION_IDS or not isinstance(request_fingerprint, str) or not request_fingerprint:
        raise ExecutionContextError("INVALID_EXECUTION_CONTEXT_REQUEST")
    verify_validated_retrieval_plan_v1_2(plan)
    try:
        require_validated_bundle_for_interface_v1_4(
            bundle, "MEMORY_ADMISSION_BUILDER"
        )
    except Exception:
        _record(
            safety_ledger,
            "UNVALIDATED_PAYLOAD_USE_ATTEMPT",
            "UNVALIDATED_OR_STALE_BUNDLE",
            condition_id=condition_id,
        )
        raise ExecutionContextError("UNVALIDATED_OR_STALE_BUNDLE")
    episode = bundle.episode
    scope_hash = derive_student_scope_hash_v1(plan.student_scope_id)
    if (
        episode.student_scope_id != plan.student_scope_id
        or bundle.payload_ref.student_scope_hash != scope_hash
    ):
        _record(
            safety_ledger,
            "CROSS_SCOPE_EXECUTION_CONTEXT_ATTEMPT",
            "CROSS_STUDENT_SCOPE",
            condition_id=condition_id,
        )
        raise ExecutionContextError("CROSS_STUDENT_SCOPE")
    if not store.has_memory(episode.memory_id):
        raise ExecutionContextError("MEMORY_NOT_IN_CURRENT_STORE")
    current_bundle = store.bundle(episode.memory_id)
    if (
        current_bundle != bundle
        or current_bundle.input_binding_fingerprint
        != bundle.input_binding_fingerprint
    ):
        raise ExecutionContextError("STORE_BUNDLE_FINGERPRINT_MISMATCH")
    current_snapshot = store.snapshot(plan.student_scope_id)
    if snapshot != current_snapshot:
        _record(
            safety_ledger,
            "STALE_SNAPSHOT_ATTEMPT",
            "STALE_STORE_SNAPSHOT",
            condition_id=condition_id,
        )
        raise ExecutionContextError("STALE_STORE_SNAPSHOT")
    if episode.memory_id not in current_snapshot.status_by_memory_id:
        raise ExecutionContextError("MEMORY_NOT_IN_SNAPSHOT")
    if episode.memory_id in current_snapshot.tombstoned_memory_ids:
        raise ExecutionContextError("DELETED_MEMORY")
    projected = current_snapshot.status_by_memory_id[episode.memory_id]
    if projected in REJECTED_PROJECTION_STATUSES or not _status_allowed(projected, plan):
        if projected == "COMPLETED":
            raise ExecutionContextError("COMPLETED_NOT_REQUESTED")
        raise ExecutionContextError(projected if projected else "INACTIVE_STATUS")
    if not temporal_validity_aware_v1_1(
        bundle.episode.valid_from,
        bundle.episode.valid_until,
        plan.query_time_utc,
    ):
        raise ExecutionContextError("TEMPORALLY_INVALID")
    return scope_hash, projected


def create_validated_execution_context_v1_1(
    *,
    plan: ValidatedRetrievalPlanV1_2,
    bundle: ValidatedPersistentMemoryBundleV1_4,
    snapshot: StoreSnapshotV1_1,
    store: OfflinePersistentMemoryStoreV1_1,
    condition_id: str,
    request_fingerprint: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None = None,
) -> ValidatedMemoryExecutionContextV1_1:
    scope_hash, projected = _validate_common(
        plan=plan,
        bundle=bundle,
        snapshot=snapshot,
        store=store,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
        safety_ledger=safety_ledger,
    )
    body = _context_body(
        plan=plan,
        bundle=bundle,
        student_scope_hash=scope_hash,
        snapshot=snapshot,
        projected_status=projected,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
    )
    fingerprint = hashlib.sha256(
        canonical_json_bytes(body, pretty=False)
    ).hexdigest()
    context = ValidatedMemoryExecutionContextV1_1(
        validated_plan=plan,
        validated_bundle=bundle,
        student_scope_hash=scope_hash,
        snapshot_fingerprint=snapshot.snapshot_fingerprint,
        projection_hash=snapshot.projection_hash,
        projected_status=projected,
        store_revision=snapshot.store_revision,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
        context_fingerprint=fingerprint,
        contract_id=EXECUTION_CONTEXT_CONTRACT_ID,
        _factory_token=store._context_token(),
    )
    store._register_context(fingerprint)
    return context


def verify_execution_context_v1_1(
    context: ValidatedMemoryExecutionContextV1_1,
    *,
    store: OfflinePersistentMemoryStoreV1_1,
    condition_id: str,
    request_fingerprint: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None = None,
) -> None:
    if type(context) is not ValidatedMemoryExecutionContextV1_1:
        raise ExecutionContextError("UNVALIDATED_EXECUTION_CONTEXT")
    if (
        context._factory_token is not store._context_token()
        or not store._context_was_issued(context.context_fingerprint)
    ):
        _record(
            safety_ledger,
            "EXECUTION_CONTEXT_FINGERPRINT_MISMATCH",
            "UNISSUED_EXECUTION_CONTEXT",
            condition_id=condition_id,
        )
        raise ExecutionContextError("UNISSUED_EXECUTION_CONTEXT")
    if context.condition_id != condition_id:
        raise ExecutionContextError("CROSS_CONDITION_CONTEXT_REUSE")
    if context.request_fingerprint != request_fingerprint:
        raise ExecutionContextError("CROSS_QUERY_CONTEXT_REUSE")
    current_snapshot = store.snapshot(context.validated_plan.student_scope_id)
    if context.store_revision != store.store_revision:
        _record(
            safety_ledger,
            "STALE_SNAPSHOT_ATTEMPT",
            "STALE_STORE_SNAPSHOT",
            condition_id=condition_id,
        )
        raise ExecutionContextError("STALE_STORE_SNAPSHOT")
    scope_hash, projected = _validate_common(
        plan=context.validated_plan,
        bundle=context.validated_bundle,
        snapshot=current_snapshot,
        store=store,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
        safety_ledger=safety_ledger,
    )
    expected_body = _context_body(
        plan=context.validated_plan,
        bundle=context.validated_bundle,
        student_scope_hash=scope_hash,
        snapshot=current_snapshot,
        projected_status=projected,
        condition_id=condition_id,
        request_fingerprint=request_fingerprint,
    )
    expected_fingerprint = hashlib.sha256(
        canonical_json_bytes(expected_body, pretty=False)
    ).hexdigest()
    expected_fields = (
        context.student_scope_hash == scope_hash,
        context.snapshot_fingerprint == current_snapshot.snapshot_fingerprint,
        context.projection_hash == current_snapshot.projection_hash,
        context.projected_status == projected,
        context.store_revision == current_snapshot.store_revision,
        context.contract_id == EXECUTION_CONTEXT_CONTRACT_ID,
        context.context_fingerprint == expected_fingerprint,
    )
    if not all(expected_fields):
        _record(
            safety_ledger,
            "EXECUTION_CONTEXT_FINGERPRINT_MISMATCH",
            "EXECUTION_CONTEXT_FINGERPRINT_MISMATCH",
            condition_id=condition_id,
        )
        raise ExecutionContextError("EXECUTION_CONTEXT_FINGERPRINT_MISMATCH")
