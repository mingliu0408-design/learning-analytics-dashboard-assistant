"""Immutable D2B/D3-R1/D3-R2 identities without forbidden source access."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import stat
from typing import Any

from . import (
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    FULL_TEXT_GOLD_SIZE,
    LABEL_ONLY_GOLD_SIZE,
    ROOT,
    sha256_file,
)


GROUPING = ROOT / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl"
STATISTICAL = ROOT / "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json"
COMBINED = ROOT / "evaluation/capability_routing_rq2d2b_v1/local_gold/track_b_contextual_capability_final_gold_v1.jsonl"
LABELS = ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_contextual_capability_final_gold_labels_v1.jsonl"


def _lstat(path: Path, size: int) -> None:
    value = os.lstat(path)
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode) or value.st_size != size:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")


def immutable_identity_report_v1_1() -> dict[str, Any]:
    if sha256_file(STATISTICAL) != D3_R1_STATISTICAL_SHA256 or sha256_file(GROUPING) != D3_R2_GROUPING_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    rows = [json.loads(line) for line in GROUPING.read_text().splitlines() if line]
    distribution = Counter(str(row["contrast_group_id"]) for row in rows)
    if (
        len(rows) != 48
        or len(distribution) != 24
        or set(distribution.values()) != {2}
        or any(set(row) != {"review_case_id", "contrast_group_id"} for row in rows)
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    _lstat(COMBINED, FULL_TEXT_GOLD_SIZE)
    _lstat(LABELS, LABEL_ONLY_GOLD_SIZE)
    gold_manifest = json.loads(
        (ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json").read_text()
    )
    if gold_manifest["gold_bundle_sha256"] != D2B_GOLD_BUNDLE_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_STARTING_STATE_MISMATCH")
    return {
        "d2b_gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
        "d3_r1_statistical_contract_sha256": D3_R1_STATISTICAL_SHA256,
        "d3_r2_grouping_ledger_sha256": D3_R2_GROUPING_SHA256,
        "grouping_records": 48,
        "grouping_groups": 24,
        "records_per_group": 2,
        "grouping_rebuilt": False,
        "mapping_access_count": 0,
        "canonical_case_bank_access_count": 0,
        "combined_source_metadata_lstat_count": 1,
        "combined_source_content_read_count": 0,
        "label_gold_metadata_lstat_count": 1,
        "label_row_content_read_count": 0,
    }
