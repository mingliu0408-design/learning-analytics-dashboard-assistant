"""User authority and historical statistical-contract binding."""

from __future__ import annotations

import json
from typing import Any

from . import BASE_CONTRACT_RELATIVE, BASE_CONTRACT_SHA256, ROOT


def statistical_completion_authority_v1() -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r1-statistical-completion-authority-v1",
        "authority_type": "USER_EXPLICIT_PRE_EVALUATION_STATISTICAL_CONTRACT_COMPLETION",
        "authority_date": "2026-08-29",
        "timing": "POST_CAPABILITY_GOLD_FREEZE_PRE_PREDICTION",
        "track_b_prediction_exists": False,
        "track_b_metric_exists": False,
        "mapping_access_authorised": False,
        "case_bank_access_authorised": False,
        "full_text_gold_access_authorised": False,
        "track_b_feature_access_authorised": False,
        "label_record_access_authorised": False,
        "grouping_ledger_access_authorised": False,
        "hidden_legacy_access_authorised": False,
        "raw_track_b_access_authorised": False,
        "blind_key_access_authorised": False,
        "model_execution_authorised": False,
        "d4_execution_authorised": False,
        "policy_change_authorised": False,
        "threshold_change_authorised": False,
        "metric_target_change_authorised": False,
        "comparison_change_authorised": False,
        "statistical_seed_change_authorised": False,
        "gold_change_authorised": False,
        "production_change_authorised": False,
    }


def historical_contract_authority_v1() -> dict[str, Any]:
    contract = json.loads((ROOT / BASE_CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    required = {
        "primary_paired_comparison": "P1_VS_B1",
        "primary_metric": "SIX_CAPABILITY_MACRO_F1",
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise RuntimeError("BLOCKED_RQ2_D3_R1_ORIGINAL_CONTRACT_IDENTITY")
    if contract.get("secondary_paired_comparisons") != ["B1_VS_B0", "P1_VS_B0"]:
        raise RuntimeError("BLOCKED_RQ2_D3_R1_ORIGINAL_CONTRACT_IDENTITY")
    bootstrap = contract.get("paired_bootstrap", {})
    sign_flip = contract.get("paired_sign_flip", {})
    if (
        bootstrap.get("resamples") != 50_000
        or bootstrap.get("seed") != 20260828
        or sign_flip.get("monte_carlo_draws") != 100_000
        or sign_flip.get("seed") != 20260829
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R1_ORIGINAL_CONTRACT_IDENTITY")
    return {
        "historical_base_contract": "RQ2 D0 rq2_final_statistical_contract_v1",
        "historical_base_sha256": BASE_CONTRACT_SHA256,
        "historical_status": contract["status"],
        "comparisons_unchanged": True,
        "metric_targets_unchanged": True,
        "seeds_unchanged": True,
    }
