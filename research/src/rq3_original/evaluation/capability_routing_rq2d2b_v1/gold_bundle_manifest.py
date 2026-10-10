"""Create the deterministic Gold bundle commitment, manifest, and freeze receipt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import (
    CANONICAL_ADJUDICATION_SHA256,
    D2A_CANONICAL_A_SHA256,
    D2A_CANONICAL_B_SHA256,
    FREEZE_TIMESTAMP,
    FULL_GOLD_RELATIVE,
    FULL_GOLD_SHA256,
    FULL_GOLD_SIZE,
    GOLD_ALIAS,
    GOLD_ROLE,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    LABEL_GOLD_SIZE,
    START_HEAD,
    canonical_json_bytes,
    sha256_bytes,
)


class GoldBundleError(RuntimeError):
    pass


def build_gold_bundle_documents(
    *,
    attestation_sha256: str,
    decision_precedence_sha256: str,
    gold_summary_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    governance = {
        "source_blinded": True,
        "human_only": True,
        "gold_frozen_before_unblinding": True,
        "hidden_legacy_accessed": False,
        "raw_mapping_accessed": False,
        "raw_track_b_accessed": False,
        "model_output_accessed": False,
        "intent_prediction_used_to_form_gold": False,
        "legacy_output_used_to_form_gold": False,
        "automatic_proposal_used_to_form_gold": False,
        "eligible_for_training": False,
        "eligible_for_threshold_selection": False,
        "eligible_for_policy_selection": False,
        "persistent_retrieval_evaluable": False,
        "rag_sufficiency_accuracy_evaluable": False,
    }
    descriptor = {
        "schema_version": "track-b-capability-gold-bundle-descriptor-v1",
        "gold_alias": GOLD_ALIAS,
        "role": GOLD_ROLE,
        "record_count": 48,
        "consensus_count": 25,
        "adjudicated_count": 23,
        "excluded_count": 0,
        "member_identities": {
            "canonical_reviewer_a_sha256": D2A_CANONICAL_A_SHA256,
            "canonical_reviewer_b_sha256": D2A_CANONICAL_B_SHA256,
            "canonical_adjudication_sha256": CANONICAL_ADJUDICATION_SHA256,
            "label_only_gold_sha256": LABEL_GOLD_SHA256,
            "label_only_gold_size_bytes": LABEL_GOLD_SIZE,
            "full_text_gold_sha256": FULL_GOLD_SHA256,
            "full_text_gold_size_bytes": FULL_GOLD_SIZE,
            "human_adjudicator_attestation_sha256": attestation_sha256,
            "decision_precedence_contract_sha256": decision_precedence_sha256,
            "gold_summary_sha256": gold_summary_sha256,
        },
        "governance": governance,
    }
    bundle_sha256 = sha256_bytes(canonical_json_bytes(descriptor))
    manifest = {
        "schema_version": "track-b-capability-gold-manifest-v1",
        "stage": "RQ2-D2B",
        "status": "TRACK_B_CAPABILITY_GOLD_FROZEN",
        "gold_alias": GOLD_ALIAS,
        "role": GOLD_ROLE,
        "source_blinded": True,
        "record_count": 48,
        "human_only": True,
        "consensus_count": 25,
        "adjudicated_count": 23,
        "excluded_count": 0,
        "canonical_reviewer_a_sha256": D2A_CANONICAL_A_SHA256,
        "canonical_reviewer_b_sha256": D2A_CANONICAL_B_SHA256,
        "canonical_adjudication_sha256": CANONICAL_ADJUDICATION_SHA256,
        "label_only_gold": {
            "relative_path": LABEL_GOLD_RELATIVE.as_posix(),
            "sha256": LABEL_GOLD_SHA256,
            "size_bytes": LABEL_GOLD_SIZE,
            "record_count": 48,
            "tracked": True,
            "contains_query_or_history": False,
        },
        "full_text_gold": {
            "relative_path": FULL_GOLD_RELATIVE.as_posix(),
            "sha256": FULL_GOLD_SHA256,
            "size_bytes": FULL_GOLD_SIZE,
            "record_count": 48,
            "tracked": False,
            "local_only": True,
        },
        "human_adjudicator_attestation_sha256": attestation_sha256,
        "decision_precedence_contract_sha256": decision_precedence_sha256,
        "gold_summary_sha256": gold_summary_sha256,
        "gold_bundle_descriptor": descriptor,
        "gold_bundle_sha256": bundle_sha256,
        **governance,
        "eligible_for_final_evaluation": True,
    }
    receipt = {
        "schema_version": "track-b-capability-gold-freeze-receipt-v1",
        "stage": "RQ2-D2B",
        "state": "TRACK_B_CAPABILITY_GOLD_FROZEN",
        "gold_alias": GOLD_ALIAS,
        "record_count": 48,
        "human_consensus_count": 25,
        "human_adjudication_count": 23,
        "source_blinded": True,
        "hidden_legacy_accessed": False,
        "hidden_legacy_access_authorised": False,
        "model_execution_count": 0,
        "policy_or_threshold_change": False,
        "final_evaluation_started": False,
        "gold_bundle_sha256": bundle_sha256,
        "freeze_timestamp": FREEZE_TIMESTAMP,
        "approved_head": START_HEAD,
        "gold_frozen_before_legacy_unblinding": True,
    }
    if manifest["gold_bundle_sha256"] != receipt["gold_bundle_sha256"]:
        raise GoldBundleError("BLOCKED_RQ2_D2B_GOLD_BUNDLE")
    return manifest, receipt
