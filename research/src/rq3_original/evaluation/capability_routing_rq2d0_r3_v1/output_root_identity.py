"""Machine-independent identities for the fixed output root and global lock."""

from __future__ import annotations

import hashlib
from typing import Any

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
)
from .fixed_d1_paths import validate_project_relative_posix_path_v1_3


OUTPUT_ROOT_IDENTITY_DOMAIN = b"RQ2_TRACK_B_OUTPUT_ROOT_IDENTITY_V1_3\x00"
GLOBAL_LOCK_IDENTITY_DOMAIN = b"RQ2_TRACK_B_GLOBAL_LOCK_IDENTITY_V1_3\x00"


def compute_output_root_identity_v1_3(
    execution_contract_id: str, project_relative_output_root: str
) -> str:
    if not execution_contract_id:
        raise ValueError("execution contract ID required")
    relative = validate_project_relative_posix_path_v1_3(
        project_relative_output_root
    ).as_posix()
    return hashlib.sha256(
        OUTPUT_ROOT_IDENTITY_DOMAIN
        + execution_contract_id.encode("utf-8")
        + b"\x00"
        + relative.encode("utf-8")
    ).hexdigest()


def compute_global_lock_identity_v1_3(
    execution_contract_id: str, project_relative_global_lock: str
) -> str:
    if not execution_contract_id:
        raise ValueError("execution contract ID required")
    relative = validate_project_relative_posix_path_v1_3(
        project_relative_global_lock
    ).as_posix()
    return hashlib.sha256(
        GLOBAL_LOCK_IDENTITY_DOMAIN
        + execution_contract_id.encode("utf-8")
        + b"\x00"
        + relative.encode("utf-8")
    ).hexdigest()


def fixed_output_root_identity_v1_3() -> str:
    return compute_output_root_identity_v1_3(
        EXECUTION_CONTRACT_ID, REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3
    )


def fixed_global_lock_identity_v1_3() -> str:
    return compute_global_lock_identity_v1_3(
        EXECUTION_CONTRACT_ID, REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3
    )


def output_identity_contract_fields() -> dict[str, Any]:
    return {
        "output_root_identity": fixed_output_root_identity_v1_3(),
        "global_lock_identity": fixed_global_lock_identity_v1_3(),
        "identity_hex_length": 64,
        "lowercase_hex": True,
        "full_project_relative_path_bound": True,
        "execution_contract_id_bound": True,
        "basename_only_identity": False,
        "absolute_machine_path_bound": False,
    }
