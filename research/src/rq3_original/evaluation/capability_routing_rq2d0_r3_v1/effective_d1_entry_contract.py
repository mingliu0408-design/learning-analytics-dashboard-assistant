"""Static API contract for the effective future real D1 entry point."""

from __future__ import annotations

import inspect
from typing import Any

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
)
from .packet_generation_state_machine_v1_3 import execute_real_d1_one_shot_v1_3


class EffectiveD1EntryContractError(RuntimeError):
    pass


ALLOWED_REAL_PARAMETERS = (
    "source_path",
    "approved_head",
    "schema_authority_sha256",
)
FORBIDDEN_REAL_PARAMETER_FRAGMENTS = (
    "output",
    "lock",
    "control",
    "override",
    "location",
    "reference",
    "mode",
    "synthetic",
)


def validate_real_entry_signature_v1_3() -> dict[str, Any]:
    signature = inspect.signature(execute_real_d1_one_shot_v1_3)
    names = tuple(signature.parameters)
    if names != ALLOWED_REAL_PARAMETERS or any(
        fragment in name
        for name in names
        for fragment in FORBIDDEN_REAL_PARAMETER_FRAGMENTS
    ):
        raise EffectiveD1EntryContractError(
            "BLOCKED_RQ2_D0_R3_REAL_ENTRY_SIGNATURE"
        )
    if signature.parameters["source_path"].kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ) or any(
        signature.parameters[name].kind != inspect.Parameter.KEYWORD_ONLY
        for name in ("approved_head", "schema_authority_sha256")
    ):
        raise EffectiveD1EntryContractError(
            "BLOCKED_RQ2_D0_R3_REAL_ENTRY_SIGNATURE"
        )
    return {
        "status": "PASS",
        "parameters": list(names),
        "source_path_positional": True,
        "approved_head_keyword_only": True,
        "schema_authority_sha256_keyword_only": True,
        "forbidden_location_parameter_count": 0,
    }


def effective_d1_entry_contract_document() -> dict[str, Any]:
    validation = validate_real_entry_signature_v1_3()
    return {
        "schema_version": "track-b-effective-d1-entry-contract-v1.3",
        "status": "FROZEN_BEFORE_REAL_D1",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "real_entry_point": "execute_real_d1_one_shot_v1_3",
        "signature": validation,
        "fixed_output_root_relative": REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
        "fixed_global_control_root_relative": (
            REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3
        ),
        "fixed_global_lock_relative": REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
        "repo_root_discovery": "git rev-parse --show-toplevel",
        "output_location_from_function_parameter": False,
        "output_location_from_cli_parameter": False,
        "output_location_from_environment": False,
        "output_location_from_config": False,
        "reference_authority_loaded_internally": True,
        "real_and_synthetic_entry_points_separate": True,
        "rq2_d0_r3_real_execution_performed": False,
    }


def global_repair_authority_document() -> dict[str, Any]:
    return {
        "schema_version": "global-one-shot-repair-authority-v1",
        "status": "USER_AUTHORISED_CONTRACT_ONLY_CORRECTION",
        "authority_type": "USER_EXPLICIT_FINAL_PRE_D1_GLOBAL_ONE_SHOT_CORRECTION",
        "authorisation_date": "2026-08-28",
        "authorised_corrections": [
            "FIXED_PROJECT_RELATIVE_REAL_D1_OUTPUT_ROOT",
            "FIXED_PROJECT_RELATIVE_GLOBAL_ACCESS_LOCK",
            "NO_REAL_OUTPUT_OR_LOCK_LOCATION_PARAMETERS",
            "ATOMIC_EXCLUSIVE_GLOBAL_RESERVATION",
            "GLOBAL_RESERVATION_PERSISTENCE_AFTER_FAILURE_OR_COMPLETION",
            "CONCURRENT_AND_LATER_INVOCATION_EXCLUSION",
            "FULL_PROJECT_RELATIVE_OUTPUT_IDENTITY",
            "STRICT_REAL_VS_SYNTHETIC_ENTRY_SEPARATION",
        ],
        "raw_track_b_access_authorised": False,
        "real_blinding_key_authorised": False,
        "real_global_lock_creation_authorised": False,
        "real_packet_generation_authorised": False,
        "track_b_label_formation_authorised": False,
        "model_execution_authorised": False,
        "policy_change_authorised": False,
        "threshold_change_authorised": False,
        "gold_change_authorised": False,
        "statistical_seed_change_authorised": False,
        "production_change_authorised": False,
    }
