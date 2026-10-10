"""Safe R4 authority records and effective future RQ2-C1 contract."""

from __future__ import annotations

from typing import Any

from . import AUTHORISATION_DATE, AUTHORITY_TYPE
from .composite_payload_episode_validator_v1_3 import composite_validator_contract
from .payload_identity_binding import payload_identity_binding_contract
from .payload_linkage_schema import payload_linkage_schema_contract
from .payload_metadata_consistency import payload_metadata_consistency_contract
from .student_scope_hash_contract import student_scope_hash_contract
from .temporal_integrity_v1 import temporal_integrity_contract


AUTHORISED_CORRECTIONS = (
    "PSEUDONYMOUS_STUDENT_SCOPE_CRYPTOGRAPHIC_BINDING",
    "PAYLOAD_EPISODE_AND_SOURCE_TURN_STRUCTURAL_BINDING",
    "PAYLOAD_METADATA_AND_CONTENT_INTEGRITY",
    "TIMEZONE_AWARE_EVENT_CREATION_INGESTION_ORDERING",
    "COMPOSITE_R2_R3_R4_VALIDATOR",
)


def payload_integrity_repair_authority() -> dict[str, Any]:
    return {
        "schema_version": "payload-integrity-repair-authority-v1",
        "stage": "RQ2-C0-R4",
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


def effective_persistent_memory_contract_v1_3() -> dict[str, Any]:
    return {
        "schema_version": "effective-persistent-memory-contract-v1.3",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN_FOR_FUTURE_RQ2_C1",
        "historical_base": "RQ2-C0-R2",
        "safety_base": "RQ2-C0-R3",
        "effective_retrieval": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "effective_payload_binding": "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3",
        "scope_hash_contract": "RQ2_MEMORY_SCOPE_V1",
        "composite_validator_required": True,
        "rq2c1_import_contract": {
            "payload_binding": (
                "evaluation.capability_routing_rq2c0_r4_v1."
                "composite_payload_episode_validator_v1_3."
                "validate_persistent_memory_payload_binding_v1_3"
            ),
            "direct_r2_only_validation_allowed": False,
            "direct_r3_only_validation_allowed": False,
            "direct_r4_only_validation_allowed": False,
        },
        "unvalidated_payload_forbidden_before": [
            "EMBEDDING",
            "RETRIEVAL",
            "ADMISSION",
            "PROJECTION",
            "GENERATION",
        ],
        "supersedes_only": [
            "R3_INCOMPLETE_PAYLOAD_EPISODE_REFERENCE_LINKAGE_VALIDATION",
            "R3_INCOMPLETE_PROVENANCE_BINDING",
            "R3_INCOMPLETE_TIMESTAMP_ORDERING_VALIDATION",
        ],
        "unchanged": {
            "retrieval_policies": True,
            "candidate_ordering": True,
            "admission_rules": True,
            "dense_encoder": True,
            "top_k": True,
            "maximum_admitted_memories": True,
            "P1": True,
            "Capability_Gold": True,
            "fixtures": True,
            "primary_policy_identity": "PMR_HYBRID_STATE_AWARE",
            "production_code": True,
        },
        "p2_implemented": False,
        "persistent_store_implemented": False,
        "actual_retrieval_executed": False,
        "production_behaviour_changed": False,
    }


def safe_contract_outputs() -> dict[str, dict[str, Any]]:
    identity = payload_identity_binding_contract()
    identity["schemas"] = payload_linkage_schema_contract()
    return {
        "payload_integrity_repair_authority_v1.json": (
            payload_integrity_repair_authority()
        ),
        "student_scope_hash_contract_v1.json": student_scope_hash_contract(),
        "payload_identity_binding_contract_v1.json": identity,
        "payload_metadata_consistency_contract_v1.json": (
            payload_metadata_consistency_contract()
        ),
        "temporal_integrity_contract_v1.json": temporal_integrity_contract(),
        "composite_validator_contract_v1_3.json": composite_validator_contract(),
        "effective_persistent_memory_contract_v1_3.json": (
            effective_persistent_memory_contract_v1_3()
        ),
    }
