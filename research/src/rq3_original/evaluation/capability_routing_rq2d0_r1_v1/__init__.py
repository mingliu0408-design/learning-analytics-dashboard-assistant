"""RQ2-D0-R1 contract-only D1 pre-arm hardening.

This package may build governed hash-only contamination references and exercise
synthetic state-machine fixtures.  It must never inspect raw Track B or create a
real D1 lock, packet, case bank, escrow, or label.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
LOCAL_CONTAMINATION_ROOT = HERE / "local_contamination"
LOCAL_REFERENCE_BUNDLE = (
    LOCAL_CONTAMINATION_ROOT / "track_b_contamination_reference_bundle_v1.jsonl"
)

D0_BRANCH = "research/rq2-d0-track-b-final-contract"
D0_HEAD = "efe00bdee99c99f02b48db99f3880dfc9bee8761"
D0_PARENT = "c911b08e4f68e14b51e0db56369969f41a3ade9b"
RESULT_BRANCH = "research/rq2-d0-r1-d1-prearm-repair"

D0_REVIEW_ZIP = ROOT.parent / "RQ2_D0_TRACK_B_FINAL_CONTRACT_REVIEW_2026-08-27.zip"
D0_REVIEW_ZIP_SHA256 = (
    "fe2870e5fb47f17a34f1adf768c005043dff457a7941dee2ae95e9ab937c0ed7"
)
C1_R1_REVIEW_ZIP = (
    ROOT.parent / "RQ2_C1_R1_OFFLINE_SAFETY_ISOLATION_REPAIR_REVIEW_2026-08-27.zip"
)
C1_R1_REVIEW_ZIP_SHA256 = (
    "571168da5c1f6a42401542a5fe3d8f6c6121cab8717295bbd19a71e5fdbc713a"
)
SAFE_SCHEMA_ZIP = ROOT.parent / "RQ2_TRACK_B_SAFE_SCHEMA_AUTHORITY_2026-08-27.zip"
SAFE_SCHEMA_ZIP_SHA256 = (
    "11a1bcba3b4a6589f8947a3f24ec3b227f43a57a8d5fcf4ceb5adc5c568fd30e"
)

TRACK_B_FILE_NAME = "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
TRACK_B_SHA256 = "52c14dbc9e79b3c211e47ffd72697ec6ed87eec0478353066eb5d2f1ab45f351"
TRACK_B_SIZE_BYTES = 65_095
TRACK_B_RECORD_COUNT = 48
TRACK_B_COLUMN_COUNT = 47
P1_POLICY_ID = "P1_D05_SIGNAL_UNION"
GOLD_BUNDLE_SHA256 = "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
FIXTURE28_SHA256 = "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"

REFERENCE_CONTRACT_ID = "RQ2_TRACK_B_CONTAMINATION_REFERENCE_AUTHORITY_V1"
NORMALISER_CONTRACT_ID = (
    "RQ2D0_V1_NFKC_CASEFOLD_REMOVE_UNICODE_PUNCTUATION_COLLAPSE_WHITESPACE_"
    "CANONICAL_JSON_HISTORY_V1"
)
REFERENCE_PARTITION_COUNTS = {
    "RQ1_TRAIN": 318,
    "RQ1_DEV": 84,
    "C0_FROZEN_62_CANDIDATES": 62,
    "TRACK_A_SAFE_IDENTITIES": 128,
    "AUTHENTIC22": 22,
    "SYNTHETIC35": 35,
    "CONTEXT_MISSING3": 3,
    "CONTROLLED_MECHANISM_FIXTURE28": 28,
}
REFERENCE_TOTAL_COUNT = sum(REFERENCE_PARTITION_COUNTS.values())
HARD_PARTITIONS = (
    "RQ1_TRAIN",
    "RQ1_DEV",
    "C0_FROZEN_62_CANDIDATES",
    "TRACK_A_SAFE_IDENTITIES",
    "SYNTHETIC35",
)
SENSITIVITY_PARTITIONS = (
    "AUTHENTIC22",
    "CONTEXT_MISSING3",
    "CONTROLLED_MECHANISM_FIXTURE28",
)

SAFE_JSON_FILENAMES = (
    "rq2d0_r1_preflight_report_v1.json",
    "contamination_reference_source_resolution_v1.json",
    "track_b_contamination_reference_manifest_v1.json",
    "track_b_contamination_policy_v1_1.json",
    "track_b_legacy_escrow_contract_v1.json",
    "track_b_blinding_key_contract_v1.json",
    "track_b_prearm_output_contract_v1.json",
    "track_b_packet_generation_state_machine_v1_1.json",
    "track_b_durable_receipt_contract_v1.json",
    "rq2d0_r1_synthetic_validation_v1.json",
)
DOC_FILENAMES = (
    "RQ2D0_R1_CONTAMINATION_REFERENCE_AUTHORITY.md",
    "RQ2D0_R1_HIDDEN_LEGACY_ESCROW_AND_BLINDING.md",
    "RQ2D0_R1_DURABLE_ONE_SHOT_RECEIPT.md",
    "RQ2D0_R1_D1_PREARM_RUNBOOK.md",
)
CHECKSUM_NAME = "rq2d0_r1_output_checksums_v1.sha256"
REVIEW_ZIP_NAME = "RQ2_D0_R1_D1_PREARM_REPAIR_REVIEW_2026-08-28.zip"


def canonical_json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=True,
            separators=None if pretty else (",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
