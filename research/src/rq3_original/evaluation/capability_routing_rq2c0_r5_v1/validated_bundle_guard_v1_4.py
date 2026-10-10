"""Research-only downstream guards that fully revalidate bound bundles."""

from __future__ import annotations

from typing import Any

from .validated_memory_bundle_v1_4 import (
    ValidatedPersistentMemoryBundleV1_4,
    verify_validated_bundle_v1_4,
)


GUARDED_INTERFACES_V1_4 = (
    "EMBEDDING_INPUT_BUILDER",
    "PERSISTENT_RETRIEVAL_CANDIDATE_BUILDER",
    "MEMORY_ADMISSION_BUILDER",
    "STATE_PROJECTION_BUILDER",
    "GENERATION_EVIDENCE_BUILDER",
)


def require_validated_bundle_for_interface_v1_4(
    bundle: ValidatedPersistentMemoryBundleV1_4, interface: str
) -> None:
    if interface not in GUARDED_INTERFACES_V1_4:
        raise ValueError("UNKNOWN_GUARDED_INTERFACE")
    try:
        if type(bundle) is not ValidatedPersistentMemoryBundleV1_4:
            raise TypeError("validated bundle required")
        verify_validated_bundle_v1_4(bundle)
    except Exception as exc:
        raise PermissionError(
            f"UNVALIDATED_OR_STALE_BUNDLE_BLOCKED:{interface}"
        ) from exc


def downstream_bundle_guard_contract() -> dict[str, Any]:
    return {
        "schema_version": "downstream-bundle-guard-contract-v1.4",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "guard_callable": (
            "evaluation.capability_routing_rq2c0_r5_v1."
            "validated_bundle_guard_v1_4."
            "require_validated_bundle_for_interface_v1_4"
        ),
        "allowed_interfaces": list(GUARDED_INTERFACES_V1_4),
        "accepted_authorisation_object": "ValidatedPersistentMemoryBundleV1_4",
        "full_bundle_revalidation_required": True,
        "free_standing_r4_receipt_accepted": False,
        "boolean_receipt_accepted": False,
        "dictionary_receipt_accepted": False,
        "payload_plus_separate_receipt_accepted": False,
        "fingerprint_only_token_accepted": False,
        "failure_prefix": "UNVALIDATED_OR_STALE_BUNDLE_BLOCKED:<interface>",
        "production_interface_implemented": False,
    }
