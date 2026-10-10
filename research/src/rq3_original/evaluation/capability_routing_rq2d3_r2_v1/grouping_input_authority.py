"""Exactly-once real grouping input authority and safe projection receipt."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from . import HERE, ROOT, canonical_json_bytes, durable_write, sha256_bytes
from .source_blinded_grouping_builder import build_source_blinded_grouping_v1, project_jsonl_fields_v1


MAPPING_RELATIVE = Path("evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl")
MAPPING_SHA256 = "fddd6effcfe5a2b9ddf6aeea1ff6c371a3d65ec613ab9391b01f6478cc0a1acc"
MAPPING_SIZE = 3552
CASE_BANK_RELATIVE = Path("evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl")
CASE_BANK_SHA256 = "0dd9ea2a55c4978d37fbed5be69f1fc61d0aebd5be9ad03ff81c6cbbb7d814ad"
CASE_BANK_SIZE = 28142
LEDGER_PATH = HERE / "track_b_source_blinded_contrast_groups_v1.jsonl"
MANIFEST_PATH = HERE / "track_b_source_blinded_grouping_manifest_v1.json"


class GroupingInputIdentityError(RuntimeError):
    pass


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _validate_path(path: Path, relative: Path, size: int) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise GroupingInputIdentityError("BLOCKED_RQ2_D3_R2_GROUPING_INPUT_IDENTITY") from exc
    if not stat.S_ISREG(mode) or path.is_symlink() or path.stat().st_size != size:
        raise GroupingInputIdentityError("BLOCKED_RQ2_D3_R2_GROUPING_INPUT_IDENTITY")
    if _git("check-ignore", "-q", str(relative)).returncode != 0:
        raise GroupingInputIdentityError("BLOCKED_RQ2_D3_R2_GROUPING_INPUT_IDENTITY")
    if _git("ls-files", "--error-unmatch", str(relative)).returncode == 0:
        raise GroupingInputIdentityError("BLOCKED_RQ2_D3_R2_GROUPING_INPUT_IDENTITY")


def _single_open_single_read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            return handle.read()
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def consume_grouping_inputs_once_v1() -> dict[str, Any]:
    if LEDGER_PATH.exists() or MANIFEST_PATH.exists():
        raise GroupingInputIdentityError("grouping inputs already consumed for this stage")
    mapping_path = ROOT / MAPPING_RELATIVE
    case_bank_path = ROOT / CASE_BANK_RELATIVE
    _validate_path(mapping_path, MAPPING_RELATIVE, MAPPING_SIZE)
    _validate_path(case_bank_path, CASE_BANK_RELATIVE, CASE_BANK_SIZE)
    mapping_bytes = _single_open_single_read(mapping_path)
    case_bank_bytes = _single_open_single_read(case_bank_path)
    if hashlib.sha256(mapping_bytes).hexdigest() != MAPPING_SHA256 or hashlib.sha256(case_bank_bytes).hexdigest() != CASE_BANK_SHA256:
        raise GroupingInputIdentityError("BLOCKED_RQ2_D3_R2_GROUPING_INPUT_IDENTITY")
    mapping_rows, mapping_projection = project_jsonl_fields_v1(
        mapping_bytes, ("raw_scenario_id", "review_case_id")
    )
    case_rows, case_projection = project_jsonl_fields_v1(
        case_bank_bytes, ("raw_case_id", "contrast_set_id")
    )
    ledger, structure = build_source_blinded_grouping_v1(mapping_rows, case_rows)
    manifest = {
        "schema_version": "track-b-source-blinded-grouping-manifest-v1",
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "algorithm_contract_id": "RQ2_TRACK_B_SOURCE_BLINDED_CONTRAST_GROUP_V1",
        "inputs": {
            "mapping": {"relative_path": str(MAPPING_RELATIVE), "sha256": MAPPING_SHA256, "size_bytes": MAPPING_SIZE, "record_count": 48, "open_count": 1, "read_count": 1, "regular_non_symlink": True, "ignored": True, "tracked": False},
            "canonical_case_bank": {"relative_path": str(CASE_BANK_RELATIVE), "sha256": CASE_BANK_SHA256, "size_bytes": CASE_BANK_SIZE, "record_count": 48, "open_count": 1, "read_count": 1, "regular_non_symlink": True, "ignored": True, "tracked": False},
        },
        "projection": {
            "mapping_allowed_fields": ["raw_scenario_id", "review_case_id"],
            "case_bank_allowed_fields": ["raw_case_id", "contrast_set_id"],
            "mapping": mapping_projection,
            "canonical_case_bank": case_projection,
            "forbidden_field_value_access_count": 0,
            "raw_text_retained": False,
        },
        "join_and_grouping": structure,
        "ledger": {
            "relative_path": "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl",
            "sha256": sha256_bytes(ledger),
            "size_bytes": len(ledger),
            "record_count": 48,
            "group_count": 24,
            "records_per_group": 2,
            "schema": ["review_case_id", "contrast_group_id"],
            "canonical_jsonl": True,
            "utf8_no_bom": True,
            "lf_only": True,
            "final_lf": True,
        },
        "full_text_gold_content_open_count": 0,
        "label_row_open_count": 0,
        "raw_track_b_access_count": 0,
        "hidden_legacy_access_count": 0,
        "blind_key_access_count": 0,
    }
    durable_write(LEDGER_PATH, ledger)
    durable_write(MANIFEST_PATH, canonical_json_bytes(manifest))
    return manifest
