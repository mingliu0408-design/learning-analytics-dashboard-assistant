"""Require a new or completely empty D1 output root before key generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class PrearmOutputError(RuntimeError):
    pass


def assert_output_root_empty(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise PrearmOutputError("BLOCKED_RQ2_D1_OUTPUT_DIRECTORY_NOT_EMPTY")
    if not path.exists():
        return {
            "status": "PASS",
            "output_root_state": "ABSENT",
            "entry_count": 0,
            "raw_open_count": 0,
        }
    if not path.is_dir():
        raise PrearmOutputError("BLOCKED_RQ2_D1_OUTPUT_DIRECTORY_NOT_EMPTY")
    entries = list(path.iterdir())
    if entries:
        raise PrearmOutputError("BLOCKED_RQ2_D1_OUTPUT_DIRECTORY_NOT_EMPTY")
    return {
        "status": "PASS",
        "output_root_state": "EXISTING_EMPTY_DIRECTORY",
        "entry_count": 0,
        "raw_open_count": 0,
    }


def prearm_output_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-prearm-output-contract-v1",
        "status": "FROZEN_BEFORE_D1",
        "accepted_initial_states": ["ABSENT", "EXISTING_COMPLETELY_EMPTY_DIRECTORY"],
        "rejected_entries": [
            "old lock",
            "old packet",
            "old mapping",
            "old case bank",
            "old escrow",
            "old key",
            "old audit",
            "temporary file",
            "hidden file",
            "symlink",
        ],
        "failure_status": "BLOCKED_RQ2_D1_OUTPUT_DIRECTORY_NOT_EMPTY",
        "must_run_before_key_generation": True,
        "must_run_before_armed_lock": True,
        "must_run_before_raw_open": True,
        "overwrite_permitted": False,
    }
