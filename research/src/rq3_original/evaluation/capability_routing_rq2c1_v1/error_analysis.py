"""Aggregate-only failure analysis; never exports governed natural language."""

from __future__ import annotations

from typing import Any, Mapping


def build_error_analysis(
    *,
    controlled: Mapping[str, Any],
    oof: Mapping[str, Any],
    synthetic: Mapping[str, Any],
    authentic: Mapping[str, Any],
) -> dict[str, Any]:
    primary = controlled["policy_results"]["PMR_HYBRID_STATE_AWARE"]
    session = oof["oof_metrics"]
    return {
        "schema_version": "rq2c1-error-analysis-v1",
        "analysis_role": "AGGREGATE_FAILURE_DIAGNOSTIC",
        "negative_results_permitted": True,
        "controlled_primary_persistent": {
            "recall_at_1_error": 1.0 - float(primary["recall_at_1"]),
            "recall_at_3_error": 1.0 - float(primary["recall_at_3"]),
            "no_memory_non_abstention_rate": 1.0
            - float(primary["no_memory_abstention"]),
        },
        "synthetic_session_oof": {
            "false_negative_count": int(session["false_negative"]),
            "false_positive_count": int(session["false_positive"]),
            "precision": session["precision"],
            "recall": session["recall"],
        },
        "synthetic_full_selected_policy": synthetic["conditions"][
            "P2_SESSION_STATE_ONLY"
        ]["episodic_state_use_metrics"],
        "authentic_full_descriptive": authentic["conditions"]["P2_FULL"][
            "episodic_state_use_metrics"
        ],
        "case_text_included": False,
        "student_scope_value_included": False,
        "policy_changed_in_response_to_errors": False,
        "production_readiness_claimed": False,
        "educational_effectiveness_claimed": False,
    }
