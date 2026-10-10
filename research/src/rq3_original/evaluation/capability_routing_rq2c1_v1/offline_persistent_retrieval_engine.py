"""Offline four-policy persistent retrieval over the frozen R2-R5 algorithms."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
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
    RetrievalPlanV1_1,
    hard_safety_filter,
    rank_candidates,
)
from evaluation.capability_routing_rq2c0_r3_v1.state_aware_eligibility import (
    state_aware_eligible_records_v1_1,
)
from evaluation.capability_routing_rq2c0_r3_v1.state_aware_retrieval_v1_1 import (
    rank_hybrid_state_aware_v1_1,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_bundle_guard_v1_4 import (
    require_validated_bundle_for_interface_v1_4,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_retrieval_plan_v1_2 import (
    ValidatedRetrievalPlanV1_2,
    validate_and_bind_retrieval_plan_v1_2,
)

from . import MEMORY_TYPES, PERSISTENT_POLICY_IDS, ROOT, canonical_json_bytes
from .offline_memory_admission_engine import BoundAdmissionResult, admit_with_transaction_binding
from .offline_memory_store import OfflinePersistentMemoryStoreV1


QUERY_TIME = "2026-08-27T12:00:00+00:00"
_MODEL: Any | None = None
_EMBED_CACHE: dict[str, np.ndarray] = {}


@dataclass(frozen=True)
class PersistentRetrievalResult:
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
                        "TOKENIZERS_PARALLELISM": "false",
                        "CUDA_VISIBLE_DEVICES": "",
                        "OPENAI_API_KEY": "",
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
            norm = float(np.linalg.norm(array))
            if not np.isclose(norm, 1.0, atol=1e-5):
                raise RuntimeError("BLOCKED_RQ2_C1_MEMORY_RETRIEVAL")
            _EMBED_CACHE[text] = array
    return tuple(_EMBED_CACHE[value] for value in values)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.casefold()))


_TYPE_TERMS = {
    "GOAL": {"goal", "aim", "target"},
    "PLAN": {"plan", "unfinished", "continue"},
    "CONSTRAINT": {"constraint", "time", "limit"},
    "PREFERENCE": {"preference", "prefer", "style", "format"},
    "CORRECTION": {"correction", "latest", "correct"},
    # A past-tense status word must not turn a request for an active plan into
    # a request for the COMPLETION record itself. Only the governed type noun
    # opts into the frozen completed-record exception.
    "COMPLETION": {"completion"},
    "REFERENCED_ITEM": {"item", "entity", "reference"},
    "LEARNING_EVENT": {"learning", "event", "activity"},
}


def infer_target_memory_types(query: str) -> tuple[str, ...]:
    tokens = _tokens(query)
    return tuple(
        memory_type
        for memory_type in MEMORY_TYPES
        if tokens & _TYPE_TERMS[memory_type]
    )


def validated_query_plan(
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
        infer_target_memory_types(effective)
        if target_memory_types is None
        else target_memory_types
    )
    if (
        any(value not in MEMORY_TYPES or not value for value in targets)
        or len(targets) != len(set(targets))
    ):
        raise ValueError("INVALID_TARGET_MEMORY_TYPES")
    raw = RetrievalPlanV1_1(
        student_scope_id=student_scope_id,
        query_time=QUERY_TIME,
        target_memory_types=tuple(targets),
        original_query=original_query,
        resolved_query=resolved_query,
        resolver_authorised=resolver_authorised,
        memory_required=memory_required,
    )
    return validate_and_bind_retrieval_plan_v1_2(raw)


def _records(store: OfflinePersistentMemoryStoreV1, plan: ValidatedRetrievalPlanV1_2) -> tuple[MemoryIndexRecordV1_1, ...]:
    query = (
        plan.resolved_query
        if plan.resolver_authorised and plan.resolved_query.strip()
        else plan.original_query
    )
    query_tokens = _tokens(query)
    records: list[MemoryIndexRecordV1_1] = []
    for bundle in store.bundles:
        episode = bundle.episode
        text_tokens = _tokens(bundle.payload.canonical_text)
        entity_overlap = len(
            set(value.casefold() for value in episode.entities) & query_tokens
        )
        type_terms = _TYPE_TERMS.get(episode.memory_type, set())
        explicit_link = bool(query_tokens & type_terms)
        records.append(
            MemoryIndexRecordV1_1(
                memory_id=episode.memory_id,
                student_scope_id=episode.student_scope_id,
                memory_type=episode.memory_type,
                status=store.status(episode.memory_id),
                event_time=episode.event_time,
                valid_from=episode.valid_from,
                valid_until=episode.valid_until,
                governed_entity_set=episode.entities,
                supersession_chain_id=(episode.supersedes_memory_id or ""),
                supersedes_memory_id=episode.supersedes_memory_id,
                explicit_state_link=explicit_link,
                production_memory_trigger=explicit_link,
                exact_lexical_match=len(query_tokens & text_tokens) >= 2,
                entity_overlap_count=entity_overlap,
                explicitness=episode.explicitness,
            )
        )
    return tuple(records)


def _add_dense_scores(
    records: tuple[MemoryIndexRecordV1_1, ...],
    *,
    store: OfflinePersistentMemoryStoreV1,
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


def run_persistent_retrieval(
    *,
    policy_id: str,
    plan: ValidatedRetrievalPlanV1_2,
    store: OfflinePersistentMemoryStoreV1,
    condition_id: str = "P2_PERSISTENT_MEMORY_ONLY",
) -> PersistentRetrievalResult:
    if policy_id not in PERSISTENT_POLICY_IDS:
        raise ValueError("unknown persistent policy")
    query = (
        plan.resolved_query
        if plan.resolver_authorised and plan.resolved_query.strip()
        else plan.original_query
    )
    records = _records(store, plan)
    rejected: dict[str, str] = {}
    eligibility_before_embedding = policy_id == "PMR_HYBRID_STATE_AWARE"
    if eligibility_before_embedding:
        eligibility = state_aware_eligible_records_v1_1(plan.original_plan, records)
        eligible = eligibility.eligible_records
        rejected.update(eligibility.rejected_record_reasons)
        rejected.update(eligibility.suppressed_record_reasons)
        scored_eligible = _add_dense_scores(eligible, store=store, query=query)
        by_id = {record.memory_id: record for record in scored_eligible}
        scored_all = tuple(by_id.get(record.memory_id, record) for record in records)
        candidates = rank_hybrid_state_aware_v1_1(plan.original_plan, scored_all)
        embedded_count = len(eligible)
    else:
        eligible, initial_rejected = hard_safety_filter(records, plan.original_plan)
        rejected.update(initial_rejected)
        scored = _add_dense_scores(eligible, store=store, query=query)
        candidates = rank_candidates(policy_id, plan.original_plan, scored)
        embedded_count = len(eligible)
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
    if policy_id == "PMR_HYBRID_STATE_AWARE":
        bound: BoundAdmissionResult = admit_with_transaction_binding(
            candidates=candidates,
            plan=plan,
            store=store,
            snapshot=snapshot,
            condition_id=condition_id,
            request_fingerprint=request_fingerprint,
        )
        outcome = bound.outcome
        contexts = len(bound.contexts)
        generation_guards = bound.generation_guard_call_count
    else:
        from evaluation.capability_routing_rq2c0_r3_v1.admission_v1_1 import (
            admit_ranked_candidates_v1_1,
        )

        outcome = admit_ranked_candidates_v1_1(candidates, plan.original_plan)
        contexts = 0
        generation_guards = 0
    for decision in outcome.decisions:
        if decision.failure_reason:
            rejected.setdefault(decision.memory_id, decision.failure_reason)
    return PersistentRetrievalResult(
        policy_id=policy_id,
        retrieved_memory_ids=tuple(item.record.memory_id for item in candidates),
        admitted_memory_ids=outcome.admitted_memory_ids,
        rejection_reasons=dict(sorted(rejected.items())),
        clarification=outcome.clarification,
        query_embedding_count=1 if embedded_count else 0,
        memory_embedding_count=embedded_count,
        eligibility_before_embedding=eligibility_before_embedding,
        maximum_retrieval_respected=len(candidates) <= 5,
        maximum_admission_respected=len(outcome.admitted_memory_ids) <= 3,
        execution_context_count=contexts,
        generation_guard_call_count=generation_guards,
        request_fingerprint=request_fingerprint,
    )


def local_encoder_preflight() -> dict[str, Any]:
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
