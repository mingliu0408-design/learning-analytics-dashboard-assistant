"""Exact-input-bound validated persistent-memory bundle and full revalidation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)

from . import R5_VALIDATOR_ID
from .validated_bundle_fingerprint_v1 import validation_contract_hash_v1_4


class BundleValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ValidatedPersistentMemoryBundleV1_4:
    episode: MemoryEpisodeV1_2
    payload_ref: MemoryPayloadRefV1_2
    payload: MemoryPayloadV1_2
    episode_fingerprint: str
    payload_ref_fingerprint: str
    payload_fingerprint: str
    input_binding_fingerprint: str
    r4_validator_id: str
    r5_validator_id: str
    validation_trace: tuple[tuple[str, int], ...]
    validation_contract_hash: str


def validate_and_bind_payload_v1_4(
    episode: MemoryEpisodeV1_2,
    payload_ref: MemoryPayloadRefV1_2,
    payload: MemoryPayloadV1_2,
) -> ValidatedPersistentMemoryBundleV1_4:
    from .composite_validated_bundle_validator_v1_4 import (
        validate_and_bind_payload_v1_4 as _validate_and_bind,
    )

    return _validate_and_bind(episode, payload_ref, payload)


def verify_validated_bundle_v1_4(
    bundle: ValidatedPersistentMemoryBundleV1_4,
) -> None:
    if type(bundle) is not ValidatedPersistentMemoryBundleV1_4:
        raise BundleValidationError("INVALID_VALIDATED_BUNDLE_SCHEMA")
    if bundle.r5_validator_id != R5_VALIDATOR_ID:
        raise BundleValidationError("VALIDATOR_ID_MISMATCH")
    if bundle.validation_contract_hash != validation_contract_hash_v1_4():
        raise BundleValidationError("VALIDATION_CONTRACT_HASH_MISMATCH")
    expected = validate_and_bind_payload_v1_4(
        bundle.episode, bundle.payload_ref, bundle.payload
    )
    if bundle != expected:
        raise BundleValidationError("STALE_OR_MUTATED_VALIDATED_BUNDLE")


def validated_memory_bundle_contract() -> dict[str, Any]:
    return {
        "schema_version": "validated-memory-bundle-contract-v1.4",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "bundle_schema": "ValidatedPersistentMemoryBundleV1_4",
        "r5_validator_id": R5_VALIDATOR_ID,
        "validation_contract_hash": validation_contract_hash_v1_4(),
        "creation_callable": (
            "evaluation.capability_routing_rq2c0_r5_v1."
            "validated_memory_bundle_v1_4.validate_and_bind_payload_v1_4"
        ),
        "verification_callable": (
            "evaluation.capability_routing_rq2c0_r5_v1."
            "validated_memory_bundle_v1_4.verify_validated_bundle_v1_4"
        ),
        "exact_input_objects_retained": True,
        "free_standing_r4_receipt_is_authorisation": False,
        "bundle_with_failed_validation_constructible": False,
        "verification_recomputes_all_component_fingerprints": True,
        "verification_recomputes_composite_fingerprint": True,
        "verification_reruns_r4_composite": True,
        "verification_reruns_r5_identifier_and_interval_checks": True,
        "verification_checks_validator_ids": True,
        "verification_checks_contract_hash": True,
        "verification_checks_complete_trace": True,
        "manually_constructed_fully_valid_bundle_may_pass": True,
        "caller_identity_authentication_claim": False,
        "persistent_store_implemented": False,
    }
