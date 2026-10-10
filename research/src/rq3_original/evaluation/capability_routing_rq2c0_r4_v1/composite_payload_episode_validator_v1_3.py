"""Non-bypassable ordered R2 + R3 + R4 payload-binding validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evaluation.capability_routing_rq2c0_r2_v1.episode_schema_v1_1 import (
    MemoryEpisodeV1_1,
    validate_episode_payload_consistency,
)
from evaluation.capability_routing_rq2c0_r2_v1.payload_schema import (
    validate_payload_reference,
)
from evaluation.capability_routing_rq2c0_r3_v1.payload_scope_v1_1 import (
    validate_text_only_payload_scope_v1_1,
)

from .payload_identity_binding import (
    PayloadIntegrityError,
    validate_payload_identity_binding_v1_2,
)
from .payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)
from .payload_metadata_consistency import (
    validate_payload_metadata_consistency_v1_2,
)
from .temporal_integrity_v1 import validate_temporal_integrity_v1


COMPOSITE_VALIDATOR_ID = "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3"
R2_FROZEN_MEMORY_STATUSES = frozenset(
    {"ACTIVE", "STALE", "SUPERSEDED", "COMPLETED", "CANCELLED", "DELETED"}
)
GUARDED_INTERFACES = (
    "EMBEDDING_INPUT_BUILDER",
    "PERSISTENT_RETRIEVAL_CANDIDATE_BUILDER",
    "MEMORY_ADMISSION_BUILDER",
    "STATE_PROJECTION_BUILDER",
    "GENERATION_EVIDENCE_BUILDER",
)


@dataclass(frozen=True)
class PayloadBindingValidationV1_3:
    binding_valid: bool
    failed_stage: str | None
    failure_code: str | None
    stage_call_counts: tuple[tuple[str, int], ...]


def _validate_r2_stage(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> None:
    if not isinstance(episode, MemoryEpisodeV1_1):
        raise ValueError("R2_EPISODE_SCHEMA_INVALID")
    if episode.status not in R2_FROZEN_MEMORY_STATUSES:
        raise ValueError("R2_EPISODE_STATUS_INVALID")
    validate_payload_reference(payload_ref)
    validate_episode_payload_consistency(episode, payload_ref, payload)


def _validate_r3_stage(payload: MemoryPayloadV1_2) -> None:
    validate_text_only_payload_scope_v1_1(payload)


def _validate_r4_stage(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> None:
    validate_payload_identity_binding_v1_2(episode, payload_ref, payload)
    validate_payload_metadata_consistency_v1_2(episode, payload_ref, payload)
    validate_temporal_integrity_v1(episode, payload_ref)


def _failure_code(exc: Exception, stage: str) -> str:
    if isinstance(exc, PayloadIntegrityError):
        return exc.code
    text = str(exc)
    if text.startswith("BLOCKED_RQ2_C0_R3_STRUCTURED_PAYLOAD_OUT_OF_SCOPE"):
        return "R3_STRUCTURED_PAYLOAD_OUT_OF_SCOPE"
    if text in {"R2_EPISODE_SCHEMA_INVALID", "R2_EPISODE_STATUS_INVALID"}:
        return text
    return f"{stage}_VALIDATION_FAILED"


def validate_persistent_memory_payload_binding_v1_3(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> PayloadBindingValidationV1_3:
    counts = {"R2": 0, "R3": 0, "R4": 0}
    stages = (
        ("R2", lambda: _validate_r2_stage(episode, payload_ref, payload)),
        ("R3", lambda: _validate_r3_stage(payload)),
        ("R4", lambda: _validate_r4_stage(episode, payload_ref, payload)),
    )
    for stage, validator in stages:
        counts[stage] += 1
        try:
            validator()
        except Exception as exc:
            return PayloadBindingValidationV1_3(
                binding_valid=False,
                failed_stage=stage,
                failure_code=_failure_code(exc, stage),
                stage_call_counts=tuple(counts.items()),
            )
    return PayloadBindingValidationV1_3(
        binding_valid=True,
        failed_stage=None,
        failure_code=None,
        stage_call_counts=tuple(counts.items()),
    )


def require_validated_payload_for_interface_v1_3(
    validation: PayloadBindingValidationV1_3, interface: str
) -> None:
    if interface not in GUARDED_INTERFACES:
        raise ValueError("UNKNOWN_GUARDED_INTERFACE")
    complete_trace = dict(validation.stage_call_counts) == {"R2": 1, "R3": 1, "R4": 1}
    if (
        not validation.binding_valid
        or validation.failed_stage is not None
        or validation.failure_code is not None
        or not complete_trace
    ):
        raise PermissionError(f"UNVALIDATED_PAYLOAD_BLOCKED:{interface}")


def composite_validator_contract() -> dict[str, Any]:
    return {
        "schema_version": "composite-payload-episode-validator-v1.3",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "validator_id": COMPOSITE_VALIDATOR_ID,
        "callable": (
            "evaluation.capability_routing_rq2c0_r4_v1."
            "composite_payload_episode_validator_v1_3."
            "validate_persistent_memory_payload_binding_v1_3"
        ),
        "ordered_stages": [
            "R2_EPISODE_REFERENCE_AND_BASE_CONSISTENCY",
            "R3_TEXT_ONLY_PAYLOAD_SCOPE",
            "R4_SCOPE_IDENTITY_PROVENANCE_METADATA_AND_TEMPORAL_INTEGRITY",
        ],
        "each_stage_invoked_exactly_once_on_valid_binding": True,
        "short_circuit_on_failure": True,
        "later_stage_may_override_failure": False,
        "binding_valid_requires_all_stages": True,
        "guarded_interfaces": list(GUARDED_INTERFACES),
        "unvalidated_payload_allowed": False,
        "guard_requires_complete_three_stage_trace": True,
        "persistent_store_implemented": False,
        "production_interfaces_implemented": False,
    }
