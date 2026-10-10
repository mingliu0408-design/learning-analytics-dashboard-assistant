"""Structured-only write/update engine over frozen R2-R5 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Mapping

from evaluation.capability_routing_rq2c0_r2_v1.event_type_compatibility import (
    EVENT_TO_MEMORY_TYPE,
)
from evaluation.capability_routing_rq2c0_r2_v1.text_normalisation import (
    normalise_text_for_hash,
)
from evaluation.capability_routing_rq2c0_r2_v1.write_candidate_contract import (
    StructuredWriteCandidateV1,
    evaluate_structured_write_candidate,
)
from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)
from evaluation.capability_routing_rq2c0_r4_v1.student_scope_hash_contract import (
    derive_storage_namespace_v1,
    derive_student_scope_hash_v1,
)
from evaluation.capability_routing_rq2c0_r5_v1.validated_memory_bundle_v1_4 import (
    ValidatedPersistentMemoryBundleV1_4,
    validate_and_bind_payload_v1_4,
)

from .offline_memory_store import OfflinePersistentMemoryStoreV1


FIXED_QUERY_TIME = "2026-08-27T12:00:00+00:00"


@dataclass(frozen=True)
class WriteExecutionResult:
    candidate: bool
    write_authorised: bool
    memory_type: str | None
    memory_id: str | None
    supersedes: str | None
    failure_reason: str | None
    sensitive_inference_write: bool
    store_revision: int


def _iso_add(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds)).astimezone(timezone.utc).isoformat()


def build_validated_bundle(
    *,
    memory_id: str,
    student_scope_id: str,
    memory_type: str,
    text: str,
    status: str = "ACTIVE",
    entities: tuple[str, ...] = (),
    supersedes_memory_id: str | None = None,
    event_time: str = "2026-01-01T00:00:00+00:00",
    valid_from: str | None = None,
    valid_until: str | None = None,
    explicitness: str = "EXPLICIT_STUDENT",
    source_kind: str = "STRUCTURED_EXPLICIT_USER_ASSERTION",
) -> ValidatedPersistentMemoryBundleV1_4:
    canonical = normalise_text_for_hash(str(text))
    if not canonical:
        raise ValueError("EMPTY_CANONICAL_PAYLOAD")
    content_bytes = canonical.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    suffix = hashlib.sha256(memory_id.encode("utf-8")).hexdigest()[:16]
    episode_id = f"episode-{suffix}"
    payload_id = f"payload-{suffix}"
    turn_id = f"turn-{suffix}"
    created_at = _iso_add(event_time, 1)
    ingested_at = _iso_add(event_time, 2)
    scope_hash = derive_student_scope_hash_v1(student_scope_id)
    namespace = derive_storage_namespace_v1(scope_hash)
    payload = MemoryPayloadV1_2(
        payload_id=payload_id,
        memory_id=memory_id,
        student_scope_hash=scope_hash,
        storage_namespace=namespace,
        canonical_text=canonical,
        structured_value=None,
        content_type="text/plain",
        locale="und",
        encoding="UTF-8",
        source_episode_id=episode_id,
        source_turn_id=turn_id,
        content_hash=content_hash,
    )
    payload_ref = MemoryPayloadRefV1_2(
        payload_id=payload_id,
        memory_id=memory_id,
        student_scope_hash=scope_hash,
        content_hash=content_hash,
        content_length=len(content_bytes),
        content_type="text/plain",
        locale="und",
        encoding="UTF-8",
        storage_namespace=namespace,
        local_only=True,
        encrypted_at_rest_required=True,
        created_at=ingested_at,
    )
    episode = MemoryEpisodeV1_2(
        memory_id=memory_id,
        student_scope_id=student_scope_id,
        episode_id=episode_id,
        source_turn_id=turn_id,
        memory_type=memory_type,
        raw_content_hash=content_hash,
        created_at=created_at,
        valid_from=valid_from or event_time,
        valid_until=valid_until,
        status=status,
        explicitness=explicitness,
        confidence=1.0,
        entities=entities,
        supersedes_memory_id=supersedes_memory_id,
        provenance={"stage": "RQ2-C1", "mode": "CONTROLLED_FIXTURE"},
        embedding_hash=None,
        payload_id=payload_id,
        event_time=event_time,
        ingested_at=ingested_at,
        timezone="UTC",
        status_reason="CONTROLLED_INITIAL_STATE" if status != "ACTIVE" else "CREATED",
        source_kind=source_kind,
        projection_eligible=status != "DELETED",
    )
    return validate_and_bind_payload_v1_4(episode, payload_ref, payload)


def load_initial_store_item(
    store: OfflinePersistentMemoryStoreV1, item: Mapping[str, Any]
) -> ValidatedPersistentMemoryBundleV1_4:
    status = str(item.get("status", "ACTIVE"))
    valid_until = item.get("valid_until")
    event_time = str(item.get("created_at") or "2026-01-01T00:00:00+00:00")
    if valid_until:
        event_time = "2025-01-01T00:00:00+00:00"
    bundle = build_validated_bundle(
        memory_id=str(item["memory_id"]),
        student_scope_id=str(item["student_scope_id"]),
        memory_type=str(item["memory_type"]),
        text=str(item.get("raw_content") or item["memory_id"]),
        status="ACTIVE" if status == "DELETED" else status,
        entities=tuple(str(value) for value in item.get("entities", ())),
        supersedes_memory_id=(
            str(item["supersedes_memory_id"])
            if item.get("supersedes_memory_id")
            else None
        ),
        event_time=event_time,
        valid_until=str(valid_until) if valid_until else None,
        explicitness="EXPLICIT_STUDENT",
    )
    store.write_bundle(bundle)
    if status == "DELETED":
        store.apply_state_event(
            bundle.episode.memory_id, "DELETE", "2026-08-27T09:00:00+00:00"
        )
    return bundle


def _candidate_from_input(value: Mapping[str, Any]) -> StructuredWriteCandidateV1:
    kind = str(value.get("kind", ""))
    memory_type = EVENT_TO_MEMORY_TYPE.get(kind)
    if kind == "MODEL_INFERENCE_ONLY":
        return StructuredWriteCandidateV1(
            candidate_source="FREE_FORM_LLM_INFERENCE",
            event_type=kind,
            supplied_memory_type="INFERRED_MENTAL_HEALTH",
            source_structured=False,
            explicit_user_source=False,
            verified_system_event=False,
            sensitive_inference=True,
        )
    return StructuredWriteCandidateV1(
        candidate_source="STRUCTURED_EXPLICIT_USER_ASSERTION",
        event_type=kind,
        supplied_memory_type=memory_type,
        source_structured=True,
        explicit_user_source=True,
        verified_system_event=False,
        sensitive_inference=False,
    )


def execute_structured_write(
    *,
    fixture_id: str,
    value: Mapping[str, Any],
    store: OfflinePersistentMemoryStoreV1,
) -> WriteExecutionResult:
    candidate = _candidate_from_input(value)
    decision = evaluate_structured_write_candidate(candidate)
    if not decision.write_authorised:
        return WriteExecutionResult(
            candidate=True,
            write_authorised=False,
            memory_type=candidate.supplied_memory_type,
            memory_id=None,
            supersedes=None,
            failure_reason=(
                "SENSITIVE_PROFILE_INFERENCE"
                if candidate.sensitive_inference
                else decision.failure_reason
            ),
            sensitive_inference_write=False,
            store_revision=store.store_revision,
        )
    memory_id = "memory-write-" + hashlib.sha256(
        fixture_id.encode("utf-8")
    ).hexdigest()[:16]
    supersedes = None
    if candidate.supplied_memory_type == "CORRECTION":
        active = [
            bundle.episode.memory_id
            for bundle in store.bundles
            if store.status(bundle.episode.memory_id) == "ACTIVE"
            and bundle.episode.student_scope_id == str(value["student_scope_id"])
        ]
        supersedes = sorted(active)[0] if active else None
    bundle = build_validated_bundle(
        memory_id=memory_id,
        student_scope_id=str(value["student_scope_id"]),
        memory_type=str(candidate.supplied_memory_type),
        text=str(value["text"]),
        supersedes_memory_id=supersedes,
        event_time="2026-08-27T10:00:00+00:00",
        source_kind=candidate.candidate_source,
    )
    store.write_bundle(bundle)
    if supersedes:
        store.apply_state_event(
            supersedes, "SUPERSEDE", "2026-08-27T10:00:03+00:00"
        )
    return WriteExecutionResult(
        candidate=True,
        write_authorised=True,
        memory_type=candidate.supplied_memory_type,
        memory_id=memory_id,
        supersedes=supersedes,
        failure_reason=None,
        sensitive_inference_write=False,
        store_revision=store.store_revision,
    )
