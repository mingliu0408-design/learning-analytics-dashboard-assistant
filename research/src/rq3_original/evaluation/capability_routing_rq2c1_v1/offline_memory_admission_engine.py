"""R3 admission with RQ2-C1 request/revision transaction binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    RankedMemoryCandidateV1_1,
)
from evaluation.capability_routing_rq2c0_r3_v1.admission_v1_1 import (
    AdmissionOutcomeV1_1,
    admit_ranked_candidates_v1_1,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_retrieval_plan_v1_2 import (
    ValidatedRetrievalPlanV1_2,
)

from .offline_memory_store import OfflinePersistentMemoryStoreV1
from .store_projection import StoreSnapshotV1
from .validated_execution_context import (
    ValidatedMemoryExecutionContextV1,
    create_validated_execution_context,
    verify_execution_context,
)


@dataclass(frozen=True)
class BoundAdmissionResult:
    outcome: AdmissionOutcomeV1_1
    contexts: tuple[ValidatedMemoryExecutionContextV1, ...]
    admitted_evidence_hashes: Mapping[str, str]
    generation_guard_call_count: int


def admit_with_transaction_binding(
    *,
    candidates: tuple[RankedMemoryCandidateV1_1, ...],
    plan: ValidatedRetrievalPlanV1_2,
    store: OfflinePersistentMemoryStoreV1,
    snapshot: StoreSnapshotV1,
    condition_id: str,
    request_fingerprint: str,
) -> BoundAdmissionResult:
    contexts = tuple(
        create_validated_execution_context(
            plan=plan,
            bundle=store.bundle(candidate.record.memory_id),
            snapshot=snapshot,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
        )
        for candidate in candidates
    )
    for context in contexts:
        verify_execution_context(
            context,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
        )
    outcome = admit_ranked_candidates_v1_1(candidates, plan.original_plan)
    context_by_id = {
        context.validated_bundle.episode.memory_id: context for context in contexts
    }
    hashes: dict[str, str] = {}
    calls = 0
    for memory_id in outcome.admitted_memory_ids:
        context = context_by_id[memory_id]
        verify_execution_context(
            context,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
        )
        require_validated_bundle_for_interface_v1_4(
            context.validated_bundle, "GENERATION_EVIDENCE_BUILDER"
        )
        calls += 1
        hashes[memory_id] = context.validated_bundle.payload.content_hash
    return BoundAdmissionResult(
        outcome=outcome,
        contexts=contexts,
        admitted_evidence_hashes=dict(sorted(hashes.items())),
        generation_guard_call_count=calls,
    )
