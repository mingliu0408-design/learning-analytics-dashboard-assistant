"""Full completion bundle contract; never a final-result-hash-only receipt."""

from __future__ import annotations

from typing import Any, Mapping

from . import RQ2D3R4Error, canonical_json_bytes, sha256_bytes


class CompletionBundleError(RQ2D3R4Error):
    pass


REQUIRED_COMPLETION_FIELDS = frozenset(
    {
        "immutable_sentinel_identity",
        "parent_execution_receipt_identity",
        "state_chain_commitment",
        "combined_source_observed_identity",
        "feature_view_identity",
        "extractor_report_identity",
        "b0_prediction_identity",
        "b1_prediction_identity",
        "p1_prediction_identity",
        "predictor_report_identity",
        "runtime_firewall_report_identities",
        "p2_deferred_scope_metadata_identity",
        "label_gold_observed_identity",
        "grouping_observed_identity",
        "complete_method_metrics_identity",
        "pairwise_statistics_identity",
        "metric_report_identity",
        "per_case_metric_ledger_identity",
        "final_result_identity",
        "result_manifest_identity",
        "all_stage_receipts",
        "worker_credential_commitments",
        "worker_role_terminal_states",
        "evidence_derived_hard_failure_count",
    }
)


def build_completion_bundle_v1_2(**values: Any) -> dict[str, Any]:
    if not REQUIRED_COMPLETION_FIELDS <= set(values):
        missing = sorted(REQUIRED_COMPLETION_FIELDS - set(values))
        raise CompletionBundleError(f"completion bundle missing: {missing}")
    document = {
        "schema_version": "track-b-completion-bundle-v1-2",
        "status": "COMPLETE",
        **values,
    }
    if document.get("evidence_derived_hard_failure_count") != 0:
        raise CompletionBundleError("completion bundle contains hard failure")
    if not document.get("all_stage_receipts"):
        raise CompletionBundleError("completion bundle stage receipts absent")
    document["completion_bundle_commitment"] = sha256_bytes(canonical_json_bytes(document))
    return document


def validate_completion_bundle_v1_2(document: Mapping[str, Any]) -> None:
    if (
        document.get("schema_version") != "track-b-completion-bundle-v1-2"
        or document.get("status") != "COMPLETE"
        or not REQUIRED_COMPLETION_FIELDS <= set(document)
        or document.get("evidence_derived_hard_failure_count") != 0
    ):
        raise CompletionBundleError("BLOCKED_RQ2_D4_COMPLETION_BUNDLE")
    payload = {key: value for key, value in document.items() if key != "completion_bundle_commitment"}
    if document.get("completion_bundle_commitment") != sha256_bytes(canonical_json_bytes(payload)):
        raise CompletionBundleError("BLOCKED_RQ2_D4_COMPLETION_BUNDLE")


def completion_bundle_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-completion-bundle-contract-v1-2",
        "status": "FROZEN",
        "required_fields": sorted(REQUIRED_COMPLETION_FIELDS),
        "final_result_sha_only_sufficient": False,
        "all_stage_receipts_required": True,
        "all_worker_terminal_states_required": True,
        "evidence_derived_hard_failure_count_required": True,
        "hard_failure_count_required_value": 0,
        "cumulative_bundle_commitment": True,
    }
