"""Pre-registered dependency-preserving Track-B statistical contract."""

from __future__ import annotations

from typing import Any


BOOTSTRAP_RESAMPLES = 50_000
BOOTSTRAP_SEED = 20260828
SIGN_FLIP_DRAWS = 100_000
SIGN_FLIP_SEED = 20260829


def statistical_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "rq2-final-statistical-contract-v1",
        "status": "FROZEN_BEFORE_TRACK_B_GOLD_OR_MODEL_RESULTS",
        "primary_paired_comparison": "P1_VS_B1",
        "secondary_paired_comparisons": ["B1_VS_B0", "P1_VS_B0"],
        "primary_metric": "SIX_CAPABILITY_MACRO_F1",
        "reported_deltas": [
            "Delta Macro-F1",
            "Delta Exact-Set Accuracy",
            "Delta Required-Capability Recall",
            "Delta Unnecessary-Capability Rate",
        ],
        "paired_bootstrap": {
            "resampling_unit": "contrast_set_id",
            "governed_cluster_count": 24,
            "records_per_cluster": 2,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence_interval": "95_PERCENTILE",
            "scenario_family_id_not_used_as_cluster": True,
            "reason": "scenario_family_id has 48 unique one-record groups",
            "session_id_present": False,
        },
        "paired_sign_flip": {
            "unit": "contrast_set_id_cluster",
            "monte_carlo_draws": SIGN_FLIP_DRAWS,
            "seed": SIGN_FLIP_SEED,
            "choice_frozen_before_d1_raw_access": True,
        },
        "set_utility_summary": "PER_CASE_WINS_TIES_LOSSES",
        "minimum_reports": [
            "95% CI",
            "p-value",
            "wins/ties/losses on per-case set utility",
        ],
        "threshold_selection_permitted": False,
        "policy_selection_permitted": False,
        "production_keep_or_replace_gate_registered": False,
        "negative_result_is_valid": True,
        "independence_limitation": (
            "No session ID exists; contrast pairs preserve the only governed repeated grouping."
        ),
    }
