"""Build the local-only 25-authentic plus 35-synthetic review bank."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import (
    AUTHENTIC_BANK_ALIAS,
    COMBINED_REVIEW_BANK_ALIAS,
    HERE,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE,
    ROOT,
    SYNTHETIC_CANONICAL_BANK_RELATIVE,
    SYNTHETIC_CANONICAL_BANK_SHA256,
    SYNTHETIC_CASE_ID_SET_SHA256,
    SYNTHETIC_STRESS_BANK_ALIAS,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    id_set_sha256,
    sha256_file,
)
from .authentic_case_builder import write_authentic_case_bank


class CombinedBankBuildError(RuntimeError):
    pass


def _load_synthetic_cases(root: Path) -> list[dict[str, Any]]:
    source = root / SYNTHETIC_CANONICAL_BANK_RELATIVE
    if not source.is_file() or source.is_symlink():
        raise CombinedBankBuildError("synthetic canonical bank unavailable")
    if sha256_file(source) != SYNTHETIC_CANONICAL_BANK_SHA256:
        raise CombinedBankBuildError("synthetic canonical bank hash mismatch")
    rows = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [str(row["case_id"]) for row in rows]
    if len(rows) != 35 or len(set(ids)) != 35:
        raise CombinedBankBuildError("synthetic membership count mismatch")
    if id_set_sha256(ids) != SYNTHETIC_CASE_ID_SET_SHA256:
        raise CombinedBankBuildError("synthetic membership identity mismatch")
    return rows


def build_combined_bank(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authentic, authentic_summary = write_authentic_case_bank(root)
    synthetic = _load_synthetic_cases(root)
    stress_path = root / LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE
    stress_path.parent.mkdir(parents=True, exist_ok=True)
    stress_path.write_bytes((root / SYNTHETIC_CANONICAL_BANK_RELATIVE).read_bytes())
    combined: list[dict[str, Any]] = []
    for row in authentic:
        combined.append(
            {
                "canonical_case_id": row["case_id"],
                "source_bank": "authentic",
                "source_bank_alias": AUTHENTIC_BANK_ALIAS,
                "current_query": row["current_query"],
                "current_page": row["current_page"],
                "necessary_conversation_history": row[
                    "candidate_conversation_history"
                ],
                "turn_index": row["current_user_turn_index"],
                "context_link_status": row["context_link_status"],
            }
        )
    for row in synthetic:
        combined.append(
            {
                "canonical_case_id": str(row["case_id"]),
                "source_bank": "synthetic",
                "source_bank_alias": SYNTHETIC_STRESS_BANK_ALIAS,
                "current_query": str(row["current_query"]),
                "current_page": str(row.get("current_page") or "Overview"),
                "necessary_conversation_history": list(
                    row.get("conversation_history") or []
                ),
                "turn_index": int(row.get("turn_index", 0)),
                "context_link_status": (
                    "HUMAN_CONFIRMATION_REQUIRED"
                    if row.get("conversation_history")
                    else "NOT_APPLICABLE"
                ),
            }
        )
    ids = [row["canonical_case_id"] for row in combined]
    if len(combined) != 60 or len(set(ids)) != 60:
        raise CombinedBankBuildError("combined bank count or identity mismatch")
    path = root / LOCAL_COMBINED_BANK_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(combined))
    synthetic_role = {
        "schema_version": "synthetic-stress-bank-role-v1",
        "stage": "RQ2-A-R1B",
        "status": "ROLE_CORRECTED",
        "prior_alias": "RQ2_SYNTHETIC_CAPABILITY_CALIBRATION_BANK_V1",
        "current_alias": SYNTHETIC_STRESS_BANK_ALIAS,
        "canonical_case_count": 35,
        "membership_unchanged": True,
        "content_unchanged": True,
        "canonical_source_sha256": SYNTHETIC_CANONICAL_BANK_SHA256,
        "case_id_set_sha256": SYNTHETIC_CASE_ID_SET_SHA256,
        "authentic_student_voice": False,
        "uses": [
            "RARE_CAPABILITY_COVERAGE",
            "CLARIFICATION",
            "SAFE_DIRECT_RESPONSE",
            "FORBIDDEN_CAPABILITY",
            "STALE_OR_CONFLICTING_CONTEXT",
            "MULTI_CAPABILITY_COMBINATIONS",
            "CONTROLLED_THRESHOLD_AND_MECHANISM_DEVELOPMENT",
        ],
        "eligible_for_final_evaluation": False,
        "query_text_tracked": False,
    }
    (HERE / "synthetic_stress_bank_role_v1.json").write_bytes(
        canonical_json_bytes(synthetic_role)
    )
    manifest = {
        "schema_version": "combined-calibration-bank-manifest-v1.2",
        "stage": "RQ2-A-R1B",
        "status": "READY_FOR_SOURCE_BLINDED_HUMAN_REVIEW",
        "alias": COMBINED_REVIEW_BANK_ALIAS,
        "total_case_count": len(combined),
        "authentic_case_count": len(authentic),
        "synthetic_case_count": len(synthetic),
        "source_count": 2,
        "source_roles_preserved": True,
        "authentic_bank_alias": AUTHENTIC_BANK_ALIAS,
        "synthetic_bank_alias": SYNTHETIC_STRESS_BANK_ALIAS,
        "combined_case_id_set_sha256": id_set_sha256(ids),
        "authentic_case_id_set_sha256": authentic_summary["case_id_set_sha256"],
        "synthetic_case_id_set_sha256": SYNTHETIC_CASE_ID_SET_SHA256,
        "local_combined_bank_sha256": sha256_file(path),
        "local_combined_bank_size_bytes": path.stat().st_size,
        "local_synthetic_stress_bank_sha256": sha256_file(stress_path),
        "all_authentic_cases_included": True,
        "all_synthetic_cases_included": True,
        "case_filtering_performed": False,
        "selected_by_c0_result": False,
        "selected_by_legacy_error": False,
        "selected_by_hidden_proposal": False,
        "selected_by_naturalness_prejudgement": False,
        "selected_by_future_model_performance": False,
        "full_combined_bank_local_only": True,
        "query_text_tracked": False,
        "assistant_text_tracked": False,
    }
    (HERE / "combined_calibration_bank_manifest_v1_2.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return combined, manifest


def read_local_combined_bank(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / LOCAL_COMBINED_BANK_RELATIVE
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
