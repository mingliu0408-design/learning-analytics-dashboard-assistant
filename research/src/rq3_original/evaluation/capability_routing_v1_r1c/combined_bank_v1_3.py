"""Build the corrected local-only 25-authentic plus 35-synthetic bank."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import (
    AUTHENTIC_BANK_ALIAS,
    COMBINED_BANK_ALIAS,
    HERE,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_MAPPING_RELATIVE,
    LOCAL_SYNTHETIC_BANK_RELATIVE,
    R1B_COMBINED_BANK_RELATIVE,
    R1B_COMBINED_BANK_SHA256,
    R1B_MAPPING_RELATIVE,
    R1B_MAPPING_SHA256,
    R1B_SYNTHETIC_BANK_RELATIVE,
    R1B_SYNTHETIC_BANK_SHA256,
    ROOT,
    SYNTHETIC_BANK_ALIAS,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    id_set_sha256,
    sha256_file,
)
from .authentic_context_link_correction import write_context_link_correction


class CombinedBankV13Error(RuntimeError):
    pass


def _read_verified_jsonl(
    root: Path, relative: Path, expected_sha256: str, expected_count: int
) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_sha256:
        raise CombinedBankV13Error(f"verified local input unavailable: {relative}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != expected_count:
        raise CombinedBankV13Error(f"local input count mismatch: {relative}")
    return rows


def build_combined_bank_v1_3(
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    corrected, correction = write_context_link_correction(root)
    old_combined = _read_verified_jsonl(
        root, R1B_COMBINED_BANK_RELATIVE, R1B_COMBINED_BANK_SHA256, 60
    )
    old_synthetic = _read_verified_jsonl(
        root, R1B_SYNTHETIC_BANK_RELATIVE, R1B_SYNTHETIC_BANK_SHA256, 35
    )
    mapping = _read_verified_jsonl(root, R1B_MAPPING_RELATIVE, R1B_MAPPING_SHA256, 60)
    corrected_by_id = {str(row["case_id"]): row for row in corrected}
    combined: list[dict[str, Any]] = []
    for source in old_combined:
        row = dict(source)
        if row["source_bank"] == "authentic":
            canonical_id = str(row["canonical_case_id"])
            authentic = corrected_by_id[canonical_id]
            if row["current_query"] != authentic["current_query"]:
                raise CombinedBankV13Error("authentic query changed during reconstitution")
            row["necessary_conversation_history"] = []
            row["context_link_status"] = "NOT_AVAILABLE"
            row["assistant_context_attached"] = False
        combined.append(row)
    if len(combined) != 60 or len({row["canonical_case_id"] for row in combined}) != 60:
        raise CombinedBankV13Error("combined60 membership mismatch")
    authentic_rows = [row for row in combined if row["source_bank"] == "authentic"]
    synthetic_rows = [row for row in combined if row["source_bank"] == "synthetic"]
    if len(authentic_rows) != 25 or any(
        row["necessary_conversation_history"] for row in authentic_rows
    ):
        raise CombinedBankV13Error("authentic context removal failed")
    old_synthetic_combined = [
        row for row in old_combined if row["source_bank"] == "synthetic"
    ]
    if synthetic_rows != old_synthetic_combined or len(synthetic_rows) != 35:
        raise CombinedBankV13Error("synthetic combined cases changed")

    synthetic_path = root / LOCAL_SYNTHETIC_BANK_RELATIVE
    synthetic_path.parent.mkdir(parents=True, exist_ok=True)
    synthetic_path.write_bytes((root / R1B_SYNTHETIC_BANK_RELATIVE).read_bytes())
    if sha256_file(synthetic_path) != R1B_SYNTHETIC_BANK_SHA256:
        raise CombinedBankV13Error("synthetic stress bank copy mismatch")
    combined_path = root / LOCAL_COMBINED_BANK_RELATIVE
    combined_path.write_bytes(canonical_jsonl_bytes(combined))
    mapping_path = root / LOCAL_MAPPING_RELATIVE
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_bytes((root / R1B_MAPPING_RELATIVE).read_bytes())
    if sha256_file(mapping_path) != R1B_MAPPING_SHA256:
        raise CombinedBankV13Error("source-blinded mapping copy mismatch")

    manifest = {
        "schema_version": "combined-calibration-bank-manifest-v1.3",
        "stage": "RQ2-A-R1C",
        "alias": COMBINED_BANK_ALIAS,
        "status": "READY_FOR_SOURCE_BLINDED_HUMAN_REVIEW",
        "total_case_count": 60,
        "authentic_case_count": 25,
        "synthetic_case_count": 35,
        "authentic_bank_alias": AUTHENTIC_BANK_ALIAS,
        "synthetic_bank_alias": SYNTHETIC_BANK_ALIAS,
        "combined_case_id_set_sha256": id_set_sha256(
            [str(row["canonical_case_id"]) for row in combined]
        ),
        "local_combined_bank_sha256": sha256_file(combined_path),
        "local_combined_bank_size_bytes": combined_path.stat().st_size,
        "local_authentic_bank_sha256": sha256_file(
            root / "evaluation/capability_routing_v1_r1c/local_case_bank/"
            "authentic_case_bank_v1_1.jsonl"
        ),
        "local_synthetic_bank_sha256": sha256_file(synthetic_path),
        "source_blinded_mapping_sha256": sha256_file(mapping_path),
        "authentic_history_count": 0,
        "synthetic_history_count": sum(
            bool(row["necessary_conversation_history"]) for row in synthetic_rows
        ),
        "query_text_modified": correction["query_text_modified"],
        "synthetic_membership_or_content_modified": False,
        "source_roles_preserved": True,
        "full_bank_and_mapping_local_only": True,
        "query_or_assistant_text_tracked": False,
    }
    (HERE / "combined_calibration_bank_manifest_v1_3.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return combined, mapping, manifest


def read_local_combined_bank(root: Path = ROOT) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / LOCAL_COMBINED_BANK_RELATIVE)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
