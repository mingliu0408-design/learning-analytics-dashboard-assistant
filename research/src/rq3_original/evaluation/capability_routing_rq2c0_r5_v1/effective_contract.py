"""Safe authority records and final effective RQ2-C1 entry contract v1.4."""

from __future__ import annotations

from typing import Any

from . import (
    AUTHORISATION_DATE,
    AUTHORITY_TYPE,
    INTERVAL_CONTRACT_ID,
    R5_VALIDATOR_ID,
    VALIDATED_PLAN_ID,
)
from .composite_validated_bundle_validator_v1_4 import (
    composite_validated_bundle_contract,
)
from .opaque_identifier_v1 import opaque_identifier_contract
from .retrieval_time_integrity_v1 import retrieval_time_integrity_contract
from .validated_bundle_fingerprint_v1 import bundle_fingerprint_contract
from .validated_bundle_guard_v1_4 import downstream_bundle_guard_contract
from .validated_memory_bundle_v1_4 import validated_memory_bundle_contract
from .validated_retrieval_plan_v1_2 import validated_retrieval_plan_contract


AUTHORISED_CORRECTIONS = (
    "EXACT_INPUT_BOUND_VALIDATED_MEMORY_BUNDLE",
    "DOWNSTREAM_BUNDLE_FINGERPRINT_REVALIDATION",
    "OPAQUE_GOVERNED_IDENTIFIER_INTEGRITY",
    "TIMEZONE_AWARE_RETRIEVAL_VALIDITY_INTERVAL",
    "TIMEZONE_AWARE_RETRIEVAL_QUERY_TIME",
    "EPISODE_TIMEZONE_DESCRIPTIVE_ONLY",
)


def validation_time_integrity_authority() -> dict[str, Any]:
    return {
        "schema_version": "validated-bundle-time-integrity-authority-v1",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "authority_type": AUTHORITY_TYPE,
        "authorisation_date": AUTHORISATION_DATE,
        "authorised_corrections": list(AUTHORISED_CORRECTIONS),
        "fixture_text_change_authorised": False,
        "fixture_membership_change_authorised": False,
        "fixture_expected_decision_change_authorised": False,
        "fixture_hash_change_authorised": False,
        "P1_change_authorised": False,
        "Capability_Gold_change_authorised": False,
        "human_annotation_change_authorised": False,
        "retrieval_threshold_change_authorised": False,
        "primary_policy_identity_change_authorised": False,
        "model_output_change_authorised": False,
        "production_behaviour_change_authorised": False,
    }


def effective_persistent_memory_contract_v1_4() -> dict[str, Any]:
    return {
        "schema_version": "effective-persistent-memory-contract-v1.4",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN_FOR_FUTURE_RQ2_C1",
        "historical_base": "RQ2-C0-R2",
        "candidate_and_admission_safety_base": "RQ2-C0-R3",
        "payload_integrity_base": "RQ2-C0-R4",
        "effective_retrieval": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "effective_payload_binding": "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3",
        "effective_validated_bundle": R5_VALIDATOR_ID,
        "effective_retrieval_plan": VALIDATED_PLAN_ID,
        "effective_interval_contract": INTERVAL_CONTRACT_ID,
        "bundle_required_for_all_downstream_interfaces": True,
        "free_standing_validation_receipt_authorised": False,
        "episode_timezone_authoritative": False,
        "rq2c1_import_contract": {
            "validate_and_bind_payload": (
                "evaluation.capability_routing_rq2c0_r5_v1."
                "validated_memory_bundle_v1_4.validate_and_bind_payload_v1_4"
            ),
            "verify_validated_bundle": (
                "evaluation.capability_routing_rq2c0_r5_v1."
                "validated_memory_bundle_v1_4.verify_validated_bundle_v1_4"
            ),
            "require_validated_bundle": (
                "evaluation.capability_routing_rq2c0_r5_v1."
                "validated_bundle_guard_v1_4."
                "require_validated_bundle_for_interface_v1_4"
            ),
            "validate_and_bind_retrieval_plan": (
                "evaluation.capability_routing_rq2c0_r5_v1."
                "validated_retrieval_plan_v1_2."
                "validate_and_bind_retrieval_plan_v1_2"
            ),
            "temporal_validity": (
                "evaluation.capability_routing_rq2c0_r5_v1."
                "retrieval_time_integrity_v1.temporal_validity_aware_v1_1"
            ),
        },
        "prohibited_rq2c1_interfaces": {
            "r4_free_standing_validation_receipt": True,
            "r2_unvalidated_retrieval_plan_v1_1": True,
            "r2_naive_time_temporal_validity": True,
            "r4_standalone_downstream_guard": True,
        },
        "unchanged": {
            "retrieval_policies": True,
            "candidate_ordering": True,
            "admission_rules": True,
            "dense_encoder": True,
            "dense_top_k": True,
            "ranking_tuple": True,
            "admission_threshold": True,
            "fixtures": True,
            "P1": True,
            "Capability_Gold": True,
            "primary_policy_identity": "PMR_HYBRID_STATE_AWARE",
            "production_code": True,
        },
        "p2_implemented": False,
        "persistent_store_implemented": False,
        "actual_retrieval_executed": False,
        "production_behaviour_changed": False,
    }


def safe_contract_outputs() -> dict[str, dict[str, Any]]:
    bundle = validated_memory_bundle_contract()
    bundle["composite_creation"] = composite_validated_bundle_contract()
    authority = validation_time_integrity_authority()
    return {
        "validated_bundle_time_integrity_authority_v1.json": authority,
        "validation_time_integrity_authority_v1.json": authority,
        "opaque_identifier_contract_v1.json": opaque_identifier_contract(),
        "retrieval_time_integrity_contract_v1_1.json": (
            retrieval_time_integrity_contract()
        ),
        "validated_retrieval_plan_contract_v1_2.json": (
            validated_retrieval_plan_contract()
        ),
        "validated_memory_bundle_contract_v1_4.json": bundle,
        "bundle_fingerprint_contract_v1.json": bundle_fingerprint_contract(),
        "downstream_bundle_guard_contract_v1_4.json": (
            downstream_bundle_guard_contract()
        ),
        "effective_persistent_memory_contract_v1_4.json": (
            effective_persistent_memory_contract_v1_4()
        ),
    }
