"""Ordered R4 plus R5 bundle-creation validation pipeline."""

from __future__ import annotations

from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3 import (
    COMPOSITE_VALIDATOR_ID,
    validate_persistent_memory_payload_binding_v1_3,
)
from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)

from . import R5_VALIDATOR_ID
from .opaque_identifier_v1 import validate_governed_memory_identifiers_v1
from .retrieval_time_integrity_v1 import validate_episode_validity_interval_v1_1
from .validated_bundle_fingerprint_v1 import (
    component_fingerprints_v1,
    validation_contract_hash_v1_4,
)
from .validated_memory_bundle_v1_4 import (
    BundleValidationError,
    ValidatedPersistentMemoryBundleV1_4,
)


EXPECTED_VALIDATION_TRACE = (
    ("R2", 1),
    ("R3", 1),
    ("R4", 1),
    ("R5_IDENTIFIER", 1),
    ("R5_INTERVAL", 1),
    ("R5_FINGERPRINT", 1),
)


def validate_and_bind_payload_v1_4(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> ValidatedPersistentMemoryBundleV1_4:
    r4_result = validate_persistent_memory_payload_binding_v1_3(
        episode, payload_ref, payload
    )
    if (
        not r4_result.binding_valid
        or r4_result.failed_stage is not None
        or r4_result.failure_code is not None
        or dict(r4_result.stage_call_counts) != {"R2": 1, "R3": 1, "R4": 1}
    ):
        raise BundleValidationError("R4_COMPOSITE_VALIDATION_FAILED")

    validate_governed_memory_identifiers_v1(episode, payload_ref, payload)
    validate_episode_validity_interval_v1_1(episode)
    fingerprints = component_fingerprints_v1(episode, payload_ref, payload)
    return ValidatedPersistentMemoryBundleV1_4(
        episode=episode,
        payload_ref=payload_ref,
        payload=payload,
        episode_fingerprint=fingerprints.episode_fingerprint,
        payload_ref_fingerprint=fingerprints.payload_ref_fingerprint,
        payload_fingerprint=fingerprints.payload_fingerprint,
        input_binding_fingerprint=fingerprints.input_binding_fingerprint,
        r4_validator_id=COMPOSITE_VALIDATOR_ID,
        r5_validator_id=R5_VALIDATOR_ID,
        validation_trace=EXPECTED_VALIDATION_TRACE,
        validation_contract_hash=validation_contract_hash_v1_4(),
    )


def composite_validated_bundle_contract() -> dict[str, Any]:
    return {
        "validator_id": R5_VALIDATOR_ID,
        "schema_version": "composite-validated-bundle-validator-v1.4",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "ordered_stages": [
            "R4_COMPOSITE_VALIDATOR_INCLUDING_R2_R3_R4",
            "R5_OPAQUE_IDENTIFIER_VALIDATION",
            "R5_VALIDITY_INTERVAL_VALIDATION",
            "R5_CANONICAL_COMPONENT_AND_COMPOSITE_FINGERPRINTING",
            "VALIDATED_BUNDLE_CREATION",
        ],
        "creation_trace": [list(item) for item in EXPECTED_VALIDATION_TRACE],
        "r4_composite_called_exactly_once": True,
        "r5_identifier_stage_called_exactly_once": True,
        "r5_interval_stage_called_exactly_once": True,
        "r5_fingerprint_stage_called_exactly_once": True,
        "short_circuit_on_failure": True,
        "later_stage_may_override_failure": False,
        "failed_bundle_returned": False,
    }
