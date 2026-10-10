"""User-supplied RQ2-D3-R4 authority document."""

from __future__ import annotations


def terminality_authority_document_v1() -> dict[str, object]:
    allowed = {
        "fixed_real_worker_authority_repair": True,
        "immutable_reservation_sentinel_authorised": True,
        "atomic_mutable_state_receipt_authorised": True,
        "failed_terminality_authorised": True,
        "completed_terminality_authorised": True,
        "atomic_no_replace_artifact_publication_authorised": True,
        "strict_receipt_path_verification_authorised": True,
        "evidence_derived_completion_gate_authorised": True,
        "directory_fsync_authorised": True,
    }
    forbidden = {
        "d2b_gold_change_authorised": False,
        "d3_r1_statistical_change_authorised": False,
        "d3_r2_grouping_change_authorised": False,
        "c0_b0_b1_p1_change_authorised": False,
        "metric_change_authorised": False,
        "comparison_change_authorised": False,
        "threshold_change_authorised": False,
        "statistical_seed_change_authorised": False,
        "mapping_access_authorised": False,
        "case_bank_access_authorised": False,
        "combined_track_b_source_access_authorised": False,
        "label_gold_content_access_authorised": False,
        "real_track_b_inference_authorised": False,
        "final_metric_authorised": False,
        "hidden_legacy_access_authorised": False,
        "raw_track_b_access_authorised": False,
        "blind_key_access_authorised": False,
        "d4_execution_authorised": False,
        "rq3_authorised": False,
        "production_change_authorised": False,
    }
    return {
        "schema_version": "rq2d3-r4-terminality-authority-v1",
        "authority_type": "USER_EXPLICIT_FINAL_PRE_D4_TERMINALITY_AND_FIXED_WORKER_AUTHORITY_REPAIR",
        "authority_date": "2026-08-29",
        **allowed,
        **forbidden,
    }
