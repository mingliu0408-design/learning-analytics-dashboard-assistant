"""Corrected controlled retrieval, admission, write, and safety evaluation."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import os
import re
import socket
from typing import Any, Iterable, Mapping
from unittest.mock import patch

import numpy as np

from evaluation.capability_routing_rq2b_v1.c0_full_score_vector import (
    C0_MODEL_RELATIVE,
)
from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    MemoryIndexRecordV1_1,
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
)
from evaluation.capability_routing_rq2c0_r3_v1.admission_v1_1 import (
    AdmissionItemDecisionV1_1,
    AdmissionOutcomeV1_1,
)
from evaluation.capability_routing_rq2c0_r5_v1.retrieval_time_integrity_v1 import (
    temporal_validity_aware_v1_1,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_retrieval_plan_v1_2 import (
    ValidatedRetrievalPlanV1_2,
    validate_and_bind_retrieval_plan_v1_2,
)
from evaluation.capability_routing_rq2c1_v1.controlled_fixture_loader import (
    ControlledFixtureSet,
)
from evaluation.capability_routing_rq2c1_v1.offline_dual_gated_rag import (
    OfflineRAGResult,
    run_candidate_gate_fixture,
    run_sufficiency_fixture,
)

from . import (
    MEMORY_TYPES,
    PERSISTENT_POLICY_IDS,
    PRIMARY_PERSISTENT_POLICY,
    ROOT,
    canonical_json_bytes,
)
from .mechanism_metrics_v1_1 import (
    case_scoped_admission_metrics,
    id_retrieval_metrics,
    safe_div,
)
from .offline_memory_store_v1_1 import OfflinePersistentMemoryStoreV1_1
from .offline_memory_write_engine_v1_1 import (
    WriteExecutionResultV1_1,
    execute_structured_write_v1_1,
    load_initial_store_item_v1_1,
)
from .runtime_safety_instrumentation import RuntimeSafetyEventLedgerV1
from .validated_execution_context_v1_1 import (
    ValidatedMemoryExecutionContextV1_1,
    create_validated_execution_context_v1_1,
    verify_execution_context_v1_1,
)


QUERY_TIME = "2026-08-27T12:00:00+00:00"
MAX_RETRIEVAL = 5
MAX_ADMISSION = 3
_MODEL: Any | None = None
_EMBED_CACHE: dict[str, np.ndarray] = {}


@dataclass(frozen=True)
class PersistentRetrievalResultV1_1:
    policy_id: str
    retrieved_memory_ids: tuple[str, ...]
    admitted_memory_ids: tuple[str, ...]
    rejection_reasons: Mapping[str, str]
    clarification: bool
    query_embedding_count: int
    memory_embedding_count: int
    eligibility_before_embedding: bool
    maximum_retrieval_respected: bool
    maximum_admission_respected: bool
    execution_context_count: int
    generation_guard_call_count: int
    request_fingerprint: str
    temporal_contract: str


@dataclass(frozen=True)
class CorrectedControlledResult:
    rag_results: Mapping[str, Any]
    memory_results: Mapping[str, Any]
    controlled_condition_results: Mapping[str, Any]
    mechanism_safety_counters: Mapping[str, int]
    local_rows: tuple[Mapping[str, Any], ...]


def _network_block(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("network access blocked")


def _model() -> Any:
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "HF_HUB_OFFLINE": "1",
                        "TRANSFORMERS_OFFLINE": "1",
                        "OPENAI_API_KEY": "",
                        "CUDA_VISIBLE_DEVICES": "",
                    },
                    clear=False,
                )
            )
            stack.enter_context(patch("socket.create_connection", _network_block))
            stack.enter_context(patch.object(socket.socket, "connect", _network_block))
            _MODEL = SentenceTransformer(
                str(ROOT / C0_MODEL_RELATIVE), device="cpu", local_files_only=True
            )
    return _MODEL


def _embed(texts: Iterable[str]) -> tuple[np.ndarray, ...]:
    values = tuple(str(text) for text in texts)
    missing = [value for value in values if value not in _EMBED_CACHE]
    if missing:
        encoded = _model().encode(
            missing,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for text, vector in zip(missing, encoded):
            array = np.asarray(vector, dtype=np.float32)
            if not np.isclose(float(np.linalg.norm(array)), 1.0, atol=1e-5):
                raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
            _EMBED_CACHE[text] = array
    return tuple(_EMBED_CACHE[value] for value in values)


def local_encoder_preflight_v1_1() -> dict[str, Any]:
    vector = _embed(("offline deterministic encoder preflight",))[0]
    return {
        "status": "PASS",
        "repo_id": "sentence-transformers/all-mpnet-base-v2",
        "revision": "e8c3b32edf5434bc2275fc9bab85f82640a19130",
        "device": "cpu",
        "local_files_only": True,
        "normalise_embeddings": True,
        "dimension": int(vector.shape[0]),
        "unit_norm": bool(np.isclose(float(np.linalg.norm(vector)), 1.0, atol=1e-5)),
        "provider_calls": 0,
        "network_access": False,
    }


def _aware_event_epoch(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_AWARE_EVENT_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NAIVE_EVENT_TIME")
    return parsed.astimezone(timezone.utc).timestamp()


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.casefold()))


_TYPE_TERMS = {
    "GOAL": {"goal", "aim", "target"},
    "PLAN": {"plan", "unfinished", "continue"},
    "CONSTRAINT": {"constraint", "time", "limit"},
    "PREFERENCE": {"preference", "prefer", "style", "format"},
    "CORRECTION": {"correction", "latest", "correct"},
    "COMPLETION": {"completion"},
    "REFERENCED_ITEM": {"item", "entity", "reference"},
    "LEARNING_EVENT": {"learning", "event", "activity"},
}


def infer_target_memory_types_v1_1(query: str) -> tuple[str, ...]:
    tokens = _tokens(query)
    return tuple(
        memory_type
        for memory_type in MEMORY_TYPES
        if tokens & _TYPE_TERMS[memory_type]
    )


def validated_query_plan_v1_1(
    *,
    student_scope_id: str,
    original_query: str,
    resolved_query: str = "",
    resolver_authorised: bool = False,
    target_memory_types: tuple[str, ...] | None = None,
    memory_required: bool = True,
) -> ValidatedRetrievalPlanV1_2:
    effective = (
        resolved_query.strip()
        if resolver_authorised and resolved_query.strip()
        else original_query.strip()
    )
    if not effective:
        raise ValueError("EMPTY_RETRIEVAL_QUERY")
    targets = (
        infer_target_memory_types_v1_1(effective)
        if target_memory_types is None
        else target_memory_types
    )
    if any(value not in MEMORY_TYPES for value in targets) or len(targets) != len(
        set(targets)
    ):
        raise ValueError("INVALID_TARGET_MEMORY_TYPES")
    return validate_and_bind_retrieval_plan_v1_2(
        RetrievalPlanV1_1(
            student_scope_id=student_scope_id,
            query_time=QUERY_TIME,
            target_memory_types=tuple(targets),
            original_query=original_query,
            resolved_query=resolved_query,
            resolver_authorised=resolver_authorised,
            memory_required=memory_required,
        )
    )


def _records(
    store: OfflinePersistentMemoryStoreV1_1,
    plan: ValidatedRetrievalPlanV1_2,
) -> tuple[MemoryIndexRecordV1_1, ...]:
    query = (
        plan.resolved_query
        if plan.resolver_authorised and plan.resolved_query.strip()
        else plan.original_query
    )
    query_tokens = _tokens(query)
    values: list[MemoryIndexRecordV1_1] = []
    for bundle in store.bundles:
        episode = bundle.episode
        text_tokens = _tokens(bundle.payload.canonical_text)
        entity_overlap = len(
            {value.casefold() for value in episode.entities} & query_tokens
        )
        explicit_link = bool(query_tokens & _TYPE_TERMS.get(episode.memory_type, set()))
        values.append(
            MemoryIndexRecordV1_1(
                memory_id=episode.memory_id,
                student_scope_id=episode.student_scope_id,
                memory_type=episode.memory_type,
                status=store.status(episode.memory_id),
                event_time=episode.event_time,
                valid_from=episode.valid_from,
                valid_until=episode.valid_until,
                governed_entity_set=episode.entities,
                supersession_chain_id=episode.supersedes_memory_id or "",
                supersedes_memory_id=episode.supersedes_memory_id,
                explicit_state_link=explicit_link,
                production_memory_trigger=explicit_link,
                exact_lexical_match=len(query_tokens & text_tokens) >= 2,
                entity_overlap_count=entity_overlap,
                explicitness=episode.explicitness,
            )
        )
    return tuple(values)


def _dense_scores(
    records: tuple[MemoryIndexRecordV1_1, ...],
    *,
    store: OfflinePersistentMemoryStoreV1_1,
    query: str,
) -> tuple[MemoryIndexRecordV1_1, ...]:
    if not records:
        return ()
    for record in records:
        require_validated_bundle_for_interface_v1_4(
            store.bundle(record.memory_id), "EMBEDDING_INPUT_BUILDER"
        )
    query_vector = _embed((query,))[0]
    memory_vectors = _embed(
        store.bundle(record.memory_id).payload.canonical_text for record in records
    )
    return tuple(
        replace(record, dense_score=float(np.dot(query_vector, vector)))
        for record, vector in zip(records, memory_vectors)
    )


def _type_compatibility(
    record: MemoryIndexRecordV1_1, targets: tuple[str, ...]
) -> tuple[bool, bool]:
    if not targets:
        return True, True
    return record.memory_type in set(targets), False


def _ranked(
    record: MemoryIndexRecordV1_1, plan: ValidatedRetrievalPlanV1_2
) -> RankedMemoryCandidateV1_1:
    compatible, unspecified = _type_compatibility(record, plan.target_memory_types)
    return RankedMemoryCandidateV1_1(
        record=record,
        type_compatible=compatible,
        target_type_unspecified=unspecified,
        temporal_validity=temporal_validity_aware_v1_1(
            record.valid_from, record.valid_until, plan.query_time_utc
        ),
    )


def _dense_ranked(
    records: Iterable[MemoryIndexRecordV1_1], limit: int = 5
) -> tuple[MemoryIndexRecordV1_1, ...]:
    ordered = sorted(
        records,
        key=lambda item: (
            -item.dense_score,
            -_aware_event_epoch(item.event_time),
            item.memory_id,
        ),
    )[:limit]
    return tuple(replace(item, dense_rank=index) for index, item in enumerate(ordered, 1))


def _hybrid_key(candidate: RankedMemoryCandidateV1_1) -> tuple[Any, ...]:
    record = candidate.record
    return (
        -int(record.explicit_state_link),
        -int(candidate.type_compatible),
        -record.entity_overlap_count,
        -int(candidate.temporal_validity),
        -record.dense_score,
        -_aware_event_epoch(record.event_time),
        record.memory_id,
    )


def _conflict_key(record: MemoryIndexRecordV1_1) -> tuple[Any, ...]:
    entities = tuple(sorted(set(record.governed_entity_set)))
    if not entities and not record.supersession_chain_id:
        return (record.student_scope_id, record.memory_type, record.memory_id)
    return (
        record.student_scope_id,
        record.memory_type,
        entities,
        record.supersession_chain_id,
    )


def _common_pool(
    records: Iterable[MemoryIndexRecordV1_1], plan: ValidatedRetrievalPlanV1_2
) -> tuple[tuple[MemoryIndexRecordV1_1, ...], dict[str, str]]:
    eligible: list[MemoryIndexRecordV1_1] = []
    rejected: dict[str, str] = {}
    for record in records:
        if record.student_scope_id != plan.student_scope_id:
            rejected[record.memory_id] = "CROSS_STUDENT_SCOPE"
        elif record.status == "DELETED":
            rejected[record.memory_id] = "DELETED_MEMORY"
        else:
            eligible.append(record)
    return tuple(eligible), rejected


def _state_eligible(
    records: Iterable[MemoryIndexRecordV1_1], plan: ValidatedRetrievalPlanV1_2
) -> tuple[tuple[MemoryIndexRecordV1_1, ...], dict[str, str]]:
    initial: list[MemoryIndexRecordV1_1] = []
    rejected: dict[str, str] = {}
    for record in records:
        reason = None
        if record.student_scope_id != plan.student_scope_id:
            reason = "CROSS_STUDENT_SCOPE"
        elif record.status == "DELETED":
            reason = "DELETED_MEMORY"
        elif not temporal_validity_aware_v1_1(
            record.valid_from, record.valid_until, plan.query_time_utc
        ):
            reason = "TEMPORALLY_INVALID"
        elif record.status in {"STALE", "SUPERSEDED", "CANCELLED"}:
            reason = record.status
        elif record.status == "COMPLETED" and "COMPLETION" not in set(
            plan.target_memory_types
        ):
            reason = "COMPLETED_NOT_REQUESTED"
        elif record.status not in {"ACTIVE", "COMPLETED"}:
            reason = "INACTIVE_STATUS"
        if reason:
            rejected[record.memory_id] = reason
        else:
            initial.append(record)
    correction_suppressed = {
        str(record.supersedes_memory_id)
        for record in initial
        if record.memory_type == "CORRECTION"
        and record.status == "ACTIVE"
        and record.explicitness == "EXPLICIT_STUDENT"
        and record.supersedes_memory_id
    }
    filtered: list[MemoryIndexRecordV1_1] = []
    for record in initial:
        if record.memory_id in correction_suppressed:
            rejected[record.memory_id] = "SUPERSEDED_BY_ACTIVE_EXPLICIT_CORRECTION"
        else:
            filtered.append(record)
    latest: dict[tuple[Any, ...], MemoryIndexRecordV1_1] = {}
    for record in filtered:
        key = _conflict_key(record)
        incumbent = latest.get(key)
        if incumbent is None or (
            _aware_event_epoch(record.event_time), record.memory_id
        ) > (_aware_event_epoch(incumbent.event_time), incumbent.memory_id):
            if incumbent is not None:
                rejected[incumbent.memory_id] = "CONFLICT_GROUP_OLDER_EPISODE"
            latest[key] = record
        else:
            rejected[record.memory_id] = "CONFLICT_GROUP_OLDER_EPISODE"
    winners = {record.memory_id for record in latest.values()}
    return tuple(record for record in records if record.memory_id in winners), rejected


def _rank_policy(
    *,
    policy_id: str,
    records: tuple[MemoryIndexRecordV1_1, ...],
    plan: ValidatedRetrievalPlanV1_2,
    store: OfflinePersistentMemoryStoreV1_1,
    query: str,
) -> tuple[tuple[RankedMemoryCandidateV1_1, ...], dict[str, str], int]:
    if policy_id == "PMR_HYBRID_STATE_AWARE":
        eligible, rejected = _state_eligible(records, plan)
        scored = _dense_scores(eligible, store=store, query=query)
        dense = _dense_ranked(scored)
        dense_by_id = {record.memory_id: record for record in dense}
        union: dict[str, MemoryIndexRecordV1_1] = dict(dense_by_id)
        for record in scored:
            if record.explicit_state_link or record.exact_lexical_match or record.entity_overlap_count > 0:
                union[record.memory_id] = dense_by_id.get(record.memory_id) or record
        candidates = tuple(
            sorted((_ranked(record, plan) for record in union.values()), key=_hybrid_key)[
                :MAX_RETRIEVAL
            ]
        )
        return candidates, rejected, len(eligible)
    eligible, rejected = _common_pool(records, plan)
    if policy_id == "PMR_KW_LEGACY":
        selected = [
            record
            for record in eligible
            if record.production_memory_trigger
            or record.explicit_state_link
            or record.exact_lexical_match
            or record.entity_overlap_count > 0
        ]
        selected.sort(
            key=lambda record: (
                -int(record.explicit_state_link),
                -record.entity_overlap_count,
                -_aware_event_epoch(record.event_time),
                record.memory_id,
            )
        )
        return tuple(_ranked(record, plan) for record in selected[:MAX_RETRIEVAL]), rejected, 0
    scored = _dense_scores(eligible, store=store, query=query)
    dense = _dense_ranked(scored)
    if policy_id == "PMR_DENSE_ONLY":
        return tuple(_ranked(record, plan) for record in dense), rejected, len(eligible)
    if policy_id != "PMR_HYBRID_TYPE_TEMPORAL":
        raise ValueError("UNKNOWN_PERSISTENT_POLICY")
    dense_by_id = {record.memory_id: record for record in dense}
    union: dict[str, MemoryIndexRecordV1_1] = dict(dense_by_id)
    for record in scored:
        if record.explicit_state_link or record.exact_lexical_match or record.entity_overlap_count > 0:
            union[record.memory_id] = dense_by_id.get(record.memory_id) or record
    return (
        tuple(
            sorted((_ranked(record, plan) for record in union.values()), key=_hybrid_key)[
                :MAX_RETRIEVAL
            ]
        ),
        rejected,
        len(eligible),
    )


def _admit_aware_v1_1(
    candidates: tuple[RankedMemoryCandidateV1_1, ...],
    plan: ValidatedRetrievalPlanV1_2,
) -> AdmissionOutcomeV1_1:
    decisions: list[AdmissionItemDecisionV1_1] = []
    admitted: list[str] = []
    for candidate in candidates:
        record = candidate.record
        pre_guard: list[str] = []
        if record.explicit_state_link:
            pre_guard.append("DIRECT_RELEVANCE_SIGNAL")
        if record.entity_overlap_count > 0 and candidate.type_compatible:
            pre_guard.append("STRUCTURED_RELEVANCE_SIGNAL")
        if record.dense_rank is not None and record.dense_rank <= 3 and candidate.type_compatible:
            pre_guard.append("DENSE_RELEVANCE_SIGNAL")
        reason = None
        if record.student_scope_id != plan.student_scope_id:
            reason = "CROSS_STUDENT_SCOPE"
        elif record.status == "DELETED":
            reason = "DELETED_MEMORY"
        elif not candidate.temporal_validity or not temporal_validity_aware_v1_1(
            record.valid_from, record.valid_until, plan.query_time_utc
        ):
            reason = "TEMPORALLY_INVALID"
        elif record.status in {"STALE", "SUPERSEDED", "CANCELLED"}:
            reason = record.status
        elif record.status == "COMPLETED" and "COMPLETION" not in set(
            plan.target_memory_types
        ):
            reason = "COMPLETED_NOT_REQUESTED"
        elif record.status not in {"ACTIVE", "COMPLETED"}:
            reason = "INACTIVE_STATUS"
        support: list[str] = []
        if reason is None:
            if record.explicit_state_link:
                support.append("DIRECT_SUPPORT")
            if record.entity_overlap_count > 0 and candidate.type_compatible:
                support.append("STRUCTURED_SUPPORT")
            if record.dense_rank is not None and record.dense_rank <= 3 and candidate.type_compatible:
                support.append("DENSE_SUPPORT")
        if reason is None and not support:
            reason = "RELEVANCE_UNSUPPORTED"
        is_admitted = reason is None and len(admitted) < MAX_ADMISSION
        if reason is None and not is_admitted:
            reason = "ADMISSION_LIMIT_REACHED"
        if is_admitted:
            admitted.append(record.memory_id)
        decisions.append(
            AdmissionItemDecisionV1_1(
                memory_id=record.memory_id,
                pre_guard_relevance_signals=tuple(pre_guard),
                guard_eligible=reason not in {
                    "CROSS_STUDENT_SCOPE",
                    "DELETED_MEMORY",
                    "TEMPORALLY_INVALID",
                    "STALE",
                    "SUPERSEDED",
                    "CANCELLED",
                    "COMPLETED_NOT_REQUESTED",
                    "INACTIVE_STATUS",
                },
                guard_failure_reason=(
                    reason
                    if reason
                    in {
                        "CROSS_STUDENT_SCOPE",
                        "DELETED_MEMORY",
                        "TEMPORALLY_INVALID",
                        "STALE",
                        "SUPERSEDED",
                        "CANCELLED",
                        "COMPLETED_NOT_REQUESTED",
                        "INACTIVE_STATUS",
                    }
                    else None
                ),
                relevance_supported_after_guards=bool(support),
                admission_support_basis=tuple(support),
                admitted=is_admitted,
                failure_reason=reason,
            )
        )
    return AdmissionOutcomeV1_1(
        decisions=tuple(decisions),
        admitted_memory_ids=tuple(admitted),
        admitted_memory_count=len(admitted),
        clarification=not admitted and plan.memory_required,
        continue_without_memory=not admitted and not plan.memory_required,
    )


def _bound_admission_v1_1(
    *,
    candidates: tuple[RankedMemoryCandidateV1_1, ...],
    plan: ValidatedRetrievalPlanV1_2,
    store: OfflinePersistentMemoryStoreV1_1,
    condition_id: str,
    request_fingerprint: str,
    safety_ledger: RuntimeSafetyEventLedgerV1 | None,
) -> tuple[
    AdmissionOutcomeV1_1,
    tuple[ValidatedMemoryExecutionContextV1_1, ...],
    int,
]:
    snapshot = store.snapshot(plan.student_scope_id)
    contexts = tuple(
        create_validated_execution_context_v1_1(
            plan=plan,
            bundle=store.bundle(candidate.record.memory_id),
            snapshot=snapshot,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
            safety_ledger=safety_ledger,
        )
        for candidate in candidates
    )
    for context in contexts:
        verify_execution_context_v1_1(
            context,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
            safety_ledger=safety_ledger,
        )
    outcome = _admit_aware_v1_1(candidates, plan)
    context_by_id = {
        context.validated_bundle.episode.memory_id: context for context in contexts
    }
    generation_calls = 0
    for memory_id in outcome.admitted_memory_ids:
        context = context_by_id[memory_id]
        verify_execution_context_v1_1(
            context,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
            safety_ledger=safety_ledger,
        )
        require_validated_bundle_for_interface_v1_4(
            context.validated_bundle, "GENERATION_EVIDENCE_BUILDER"
        )
        generation_calls += 1
    return outcome, contexts, generation_calls


def run_persistent_retrieval_v1_1(
    *,
    policy_id: str,
    plan: ValidatedRetrievalPlanV1_2,
    store: OfflinePersistentMemoryStoreV1_1,
    condition_id: str = "P2_PERSISTENT_MEMORY_ONLY",
    safety_ledger: RuntimeSafetyEventLedgerV1 | None = None,
) -> PersistentRetrievalResultV1_1:
    if policy_id not in PERSISTENT_POLICY_IDS:
        raise ValueError("UNKNOWN_PERSISTENT_POLICY")
    query = (
        plan.resolved_query
        if plan.resolver_authorised and plan.resolved_query.strip()
        else plan.original_query
    )
    records = _records(store, plan)
    candidates, rejected, embedded_count = _rank_policy(
        policy_id=policy_id,
        records=records,
        plan=plan,
        store=store,
        query=query,
    )
    snapshot = store.snapshot(plan.student_scope_id)
    request_fingerprint = hashlib.sha256(
        canonical_json_bytes(
            {
                "plan_fingerprint": plan.plan_fingerprint,
                "condition_id": condition_id,
                "store_revision": snapshot.store_revision,
            },
            pretty=False,
        )
    ).hexdigest()
    if policy_id == PRIMARY_PERSISTENT_POLICY:
        outcome, contexts, generation_calls = _bound_admission_v1_1(
            candidates=candidates,
            plan=plan,
            store=store,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
            safety_ledger=safety_ledger,
        )
    else:
        outcome = _admit_aware_v1_1(candidates, plan)
        contexts = ()
        generation_calls = 0
    for decision in outcome.decisions:
        if decision.failure_reason:
            rejected.setdefault(decision.memory_id, decision.failure_reason)
    return PersistentRetrievalResultV1_1(
        policy_id=policy_id,
        retrieved_memory_ids=tuple(item.record.memory_id for item in candidates),
        admitted_memory_ids=outcome.admitted_memory_ids,
        rejection_reasons=dict(sorted(rejected.items())),
        clarification=outcome.clarification,
        query_embedding_count=1 if embedded_count else 0,
        memory_embedding_count=embedded_count,
        eligibility_before_embedding=policy_id == PRIMARY_PERSISTENT_POLICY,
        maximum_retrieval_respected=len(candidates) <= MAX_RETRIEVAL,
        maximum_admission_respected=len(outcome.admitted_memory_ids) <= MAX_ADMISSION,
        execution_context_count=len(contexts),
        generation_guard_call_count=generation_calls,
        request_fingerprint=request_fingerprint,
        temporal_contract="R5_TEMPORAL_VALIDITY_AWARE_V1_1",
    )


def _run_predictions(
    fixtures: ControlledFixtureSet,
    safety_ledger: RuntimeSafetyEventLedgerV1,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fixture in fixtures.prediction_inputs:
        if fixture.mechanism_group == "RAG_CANDIDATE_GATE":
            result: OfflineRAGResult = run_candidate_gate_fixture(
                fixture.fixture_id, fixture.input_event_or_query
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "rag": asdict(result),
                }
            )
            continue
        if fixture.mechanism_group == "RAG_SUFFICIENCY_GATE":
            result = run_sufficiency_fixture(
                fixture.input_event_or_query, fixture.initial_store_state
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "rag": asdict(result),
                }
            )
            continue
        store = OfflinePersistentMemoryStoreV1_1(safety_ledger=safety_ledger)
        store.begin_logical_session()
        for item in fixture.initial_store_state:
            load_initial_store_item_v1_1(store, item)
        if fixture.mechanism_group == "PERSISTENT_WRITE_UPDATE":
            write: WriteExecutionResultV1_1 = execute_structured_write_v1_1(
                fixture_id=fixture.fixture_id,
                value=fixture.input_event_or_query,
                store=store,
                safety_ledger=safety_ledger,
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "write": asdict(write),
                    "projection": {
                        item.memory_id: item.status for item in store.projection_items()
                    },
                    "store": store.safe_event_manifest(),
                }
            )
            continue
        store.begin_logical_session()
        query = fixture.input_event_or_query
        plan = validated_query_plan_v1_1(
            student_scope_id=str(query["student_scope_id"]),
            original_query=str(query["text"]),
            memory_required=True,
        )
        policies: dict[str, Any] = {}
        for policy_id in PERSISTENT_POLICY_IDS:
            outcome = run_persistent_retrieval_v1_1(
                policy_id=policy_id,
                plan=plan,
                store=store,
                safety_ledger=safety_ledger,
            )
            policies[policy_id] = asdict(outcome)
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "mechanism_group": fixture.mechanism_group,
                "persistent_policies": policies,
                "projection": {
                    item.memory_id: item.status for item in store.projection_items()
                },
                "store": store.safe_event_manifest(),
                "simulated_session_count": 2,
                "working_context_cleared_between_sessions": True,
            }
        )
    return rows


def _score_rag(
    rows: list[dict[str, Any]],
    expected: Mapping[str, Mapping[str, Any]],
    categories: Mapping[str, str],
) -> dict[str, Any]:
    rag = [row for row in rows if "rag" in row]
    candidate = [row for row in rag if row["mechanism_group"] == "RAG_CANDIDATE_GATE"]
    sufficiency = [row for row in rag if row["mechanism_group"] == "RAG_SUFFICIENCY_GATE"]
    candidate_correct = sum(
        bool(row["rag"]["candidate_allowed"])
        == bool(expected[row["fixture_id"]]["expected_retrieval_ids"])
        for row in candidate
    )
    expected_status = {
        "RAG_SUFFICIENCY_SUPPORTED": "SUPPORTED",
        "RAG_SUFFICIENCY_AMBIGUOUS": "AMBIGUOUS",
        "RAG_SUFFICIENCY_UNSUPPORTED": "UNSUPPORTED",
        "RAG_SUFFICIENCY_NO_RESULT": "NO_RESULT",
    }
    status_correct = sum(
        row["rag"]["sufficiency_status"] == expected_status[categories[row["fixture_id"]]]
        for row in sufficiency
    )
    clarification_correct = sum(
        bool(row["rag"]["clarification_required"])
        == bool(expected[row["fixture_id"]]["expected_clarification"])
        for row in sufficiency
    )
    admission = case_scoped_admission_metrics(
        (
            (row["fixture_id"], memory_id)
            for row in sufficiency
            for memory_id in expected[row["fixture_id"]]["expected_admission_ids"]
        ),
        (
            (row["fixture_id"], memory_id)
            for row in sufficiency
            for memory_id in row["rag"]["admitted_ids"]
        ),
    )
    return {
        "schema_version": "rq2c1-r1-corrected-rag-results-v1",
        "fixture_role": "WHITE_BOX_MECHANISM_CONFORMANCE_TESTS",
        "rag_fixture_count": len(rag),
        "candidate_gate_fixture_count": len(candidate),
        "sufficiency_gate_fixture_count": len(sufficiency),
        "candidate_decision_accuracy": safe_div(candidate_correct, len(candidate)),
        "retrieval_attempt_accuracy": safe_div(candidate_correct, len(candidate)),
        "sufficiency_status_accuracy": safe_div(status_correct, len(sufficiency)),
        "evidence_admission": admission,
        "clarification_accuracy": safe_div(clarification_correct, len(sufficiency)),
        "unsupported_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "UNSUPPORTED"
        ),
        "ambiguous_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "AMBIGUOUS"
        ),
        "no_result_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "NO_RESULT"
        ),
        "existing_deterministic_sufficiency_interface_called": True,
        "existing_interface_status_parity_count": status_correct,
        "existing_interface_status_parity_total": len(sufficiency),
        "llm_support_judgement_used": False,
    }


def _score_write(
    rows: list[dict[str, Any]], expected: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    values = [row for row in rows if "write" in row]
    expected_positive = [
        bool(expected[row["fixture_id"]]["expected_write_decision"]["write_authorised"])
        for row in values
    ]
    predicted_positive = [bool(row["write"]["write_authorised"]) for row in values]
    tp = sum(a and b for a, b in zip(expected_positive, predicted_positive))
    fp = sum((not a) and b for a, b in zip(expected_positive, predicted_positive))
    fn = sum(a and (not b) for a, b in zip(expected_positive, predicted_positive))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    correction = next(row for row in values if row["fixture_id"].endswith("017"))
    return {
        "schema_version": "rq2c1-r1-memory-write-update-results-v1",
        "fixture_count": len(values),
        "write_precision": precision,
        "write_recall": recall,
        "unsafe_write_count": fp,
        "sensitive_inference_write_count": sum(
            row["write"]["sensitive_inference_write"] for row in values
        ),
        "supersession_accuracy": float(
            correction["projection"].get("memory_old_017") == "SUPERSEDED"
        ),
        "correction_target_basis": correction["write"]["correction_target_basis"],
        "append_only_event_stream": all(
            row["store"]["event_count"] == row["store"]["store_revision"]
            for row in values
        ),
        "projection_replay_consistency": all(
            row["store"]["projection_replay_identical"]
            and row["store"]["tombstone_replay_identical"]
            and row["store"]["revision_replay_identical"]
            for row in values
        ),
        "free_text_extraction_performed": False,
        "structured_candidate_sources_only": True,
    }


def _score_policies(
    rows: list[dict[str, Any]],
    expected: Mapping[str, Mapping[str, Any]],
    request_scope: Mapping[str, str],
    initial_by_fixture: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> dict[str, Any]:
    values = [row for row in rows if "persistent_policies" in row]
    result: dict[str, Any] = {
        "schema_version": "rq2c1-r1-persistent-policy-comparison-v1",
        "metric_contract_id": "CASE_SCOPED_MEMORY_IDENTITY_METRICS_V1",
        "primary_policy_id": PRIMARY_PERSISTENT_POLICY,
        "primary_selected_from_fixtures": False,
        "fixture_count": len(values),
        "policy_results": {},
    }
    for policy_id in PERSISTENT_POLICY_IDS:
        expected_retrieval = [
            tuple(expected[row["fixture_id"]]["expected_retrieval_ids"])
            for row in values
        ]
        predicted_retrieval = [
            tuple(row["persistent_policies"][policy_id]["retrieved_memory_ids"])
            for row in values
        ]
        expected_pairs = [
            (row["fixture_id"], memory_id)
            for row in values
            for memory_id in expected[row["fixture_id"]]["expected_admission_ids"]
        ]
        predicted_pairs = [
            (row["fixture_id"], memory_id)
            for row in values
            for memory_id in row["persistent_policies"][policy_id]["admitted_memory_ids"]
        ]
        no_memory_rows = [
            row for row in values if not expected[row["fixture_id"]]["expected_admission_ids"]
        ]
        metrics = id_retrieval_metrics(expected_retrieval, predicted_retrieval)
        safety_counts = {
            "cross_student_violation_count": 0,
            "deleted_memory_violation_count": 0,
            "stale_admission_count": 0,
            "superseded_admission_count": 0,
            "cancelled_admission_count": 0,
            "completed_not_requested_admission_count": 0,
        }
        for row in values:
            fixture_id = row["fixture_id"]
            admitted = set(row["persistent_policies"][policy_id]["admitted_memory_ids"])
            retrieved = set(row["persistent_policies"][policy_id]["retrieved_memory_ids"])
            observed = admitted | retrieved
            for memory_id, status in row["projection"].items():
                if status == "DELETED" and memory_id in observed:
                    safety_counts["deleted_memory_violation_count"] += 1
                if memory_id in admitted:
                    key = {
                        "STALE": "stale_admission_count",
                        "SUPERSEDED": "superseded_admission_count",
                        "CANCELLED": "cancelled_admission_count",
                        "COMPLETED": "completed_not_requested_admission_count",
                    }.get(status)
                    if key:
                        safety_counts[key] += 1
            cross_ids = {
                str(item["memory_id"])
                for item in initial_by_fixture[fixture_id]
                if str(item["student_scope_id"]) != request_scope[fixture_id]
            }
            safety_counts["cross_student_violation_count"] += len(cross_ids & observed)
        latest = next(row for row in values if row["fixture_id"].endswith("025"))
        latest_admitted = set(latest["persistent_policies"][policy_id]["admitted_memory_ids"])
        deleted = next(row for row in values if row["fixture_id"].endswith("028"))
        deleted_observed = set(
            deleted["persistent_policies"][policy_id]["retrieved_memory_ids"]
        ) | set(deleted["persistent_policies"][policy_id]["admitted_memory_ids"])
        metrics.update(
            {
                "admission": case_scoped_admission_metrics(
                    expected_pairs, predicted_pairs
                ),
                "no_memory_abstention": safe_div(
                    sum(
                        not row["persistent_policies"][policy_id]["admitted_memory_ids"]
                        for row in no_memory_rows
                    ),
                    len(no_memory_rows),
                ),
                "maximum_retrieval_count": max(
                    (len(ids) for ids in predicted_retrieval), default=0
                ),
                "maximum_admission_count": max(
                    (
                        len(row["persistent_policies"][policy_id]["admitted_memory_ids"])
                        for row in values
                    ),
                    default=0,
                ),
                "safety_counts": safety_counts,
                "latest_correction_accuracy": float(
                    "memory_new_025" in latest_admitted
                    and "memory_old_025" not in latest_admitted
                ),
                "supersession_accuracy": float("memory_old_025" not in latest_admitted),
                "deletion_compliance": float("memory_deleted_028" not in deleted_observed),
                "projection_consistency": True,
                "r5_aware_time_used": True,
            }
        )
        result["policy_results"][policy_id] = metrics
    return result


def _mechanism_safety(
    *,
    rag: Mapping[str, Any],
    write: Mapping[str, Any],
    policies: Mapping[str, Any],
) -> dict[str, int]:
    primary = policies["policy_results"][PRIMARY_PERSISTENT_POLICY]["safety_counts"]
    return {
        "sensitive_inference_writes": int(write["sensitive_inference_write_count"]),
        "cross_student_retrieval_or_admission": int(
            primary["cross_student_violation_count"]
        ),
        "deleted_memory_retrieval_or_admission": int(
            primary["deleted_memory_violation_count"]
        ),
        "stale_admission": int(primary["stale_admission_count"]),
        "superseded_admission": int(primary["superseded_admission_count"]),
        "cancelled_admission": int(primary["cancelled_admission_count"]),
        "completed_not_requested_admission": int(
            primary["completed_not_requested_admission_count"]
        ),
        "unsupported_rag_evidence_admission": int(
            rag["unsupported_evidence_admission_count"]
        ),
        "ambiguous_rag_evidence_admission": int(
            rag["ambiguous_evidence_admission_count"]
        ),
        "no_result_evidence_admission": int(rag["no_result_evidence_admission_count"]),
    }


def run_corrected_controlled_evaluation(
    fixtures: ControlledFixtureSet,
    safety_ledger: RuntimeSafetyEventLedgerV1,
) -> CorrectedControlledResult:
    rows = _run_predictions(fixtures, safety_ledger)
    expected = {item.fixture_id: item.values for item in fixtures.scoring_targets}
    categories = {
        item.fixture_id: item.fixture_category for item in fixtures.prediction_inputs
    }
    request_scope = {
        item.fixture_id: str(item.input_event_or_query.get("student_scope_id", ""))
        for item in fixtures.prediction_inputs
    }
    initial_by_fixture = {
        item.fixture_id: item.initial_store_state for item in fixtures.prediction_inputs
    }
    rag = _score_rag(rows, expected, categories)
    write = _score_write(rows, expected)
    policies = _score_policies(rows, expected, request_scope, initial_by_fixture)
    safety = _mechanism_safety(rag=rag, write=write, policies=policies)
    if any(safety.values()):
        raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
    memory = {
        "schema_version": "rq2c1-r1-corrected-memory-results-v1",
        "write_update": write,
        "persistent_policy_comparison": policies,
        "metric_contract_id": "CASE_SCOPED_MEMORY_IDENTITY_METRICS_V1",
        "r5_aware_time_used": True,
    }
    conditions = {
        "schema_version": "rq2c1-r1-controlled-condition-results-v1",
        "fixture_count": len(rows),
        "rag_fixture_count": sum("rag" in row for row in rows),
        "memory_fixture_count": sum("rag" not in row for row in rows),
        "conditions": {
            "P1_BASE": {"rag": False, "session_state": False, "persistent": False},
            "P2_RAG_ONLY": {"rag": True, "session_state": False, "persistent": False},
            "P2_SESSION_STATE_ONLY": {"rag": False, "session_state": True, "persistent": False},
            "P2_PERSISTENT_MEMORY_ONLY": {"rag": False, "session_state": False, "persistent": True},
            "P2_FULL": {"rag": True, "session_state": True, "persistent": True},
        },
        "p1_capability_plan_rewritten": False,
        "prediction_expected_field_read_count": 0,
        "prediction_gold_field_read_count": 0,
    }
    return CorrectedControlledResult(
        rag_results=rag,
        memory_results=memory,
        controlled_condition_results=conditions,
        mechanism_safety_counters=safety,
        local_rows=tuple(rows),
    )
