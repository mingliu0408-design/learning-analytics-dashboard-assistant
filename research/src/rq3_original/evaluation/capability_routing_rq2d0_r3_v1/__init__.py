"""RQ2-D0-R3 global one-shot and fixed-output authority contracts.

Importing this package never resolves raw Track B, creates real D1 paths,
reserves real access, generates a real key, or creates real packets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

START_BRANCH = "research/rq2-d0-r2-exact-reference-policy-repair"
START_HEAD = "6829d2904cc0d7e4d9d2792445d197ce5e9418e0"
START_PARENT = "484f90d00c69748e84945e96c7c732ba23884919"
RESULT_BRANCH = "research/rq2-d0-r3-global-one-shot-repair"

REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 = (
    "evaluation/capability_routing_rq2d1_v1/local_one_shot"
)
REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3 = (
    "evaluation/capability_routing_rq2d1_v1/local_control"
)
REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3 = (
    "evaluation/capability_routing_rq2d1_v1/local_control/"
    "TRACK_B_PACKET_GENERATION_GLOBAL_ACCESS_V1_3.json"
)
EXECUTION_CONTRACT_ID = "RQ2_TRACK_B_PACKET_GENERATION_GLOBAL_ONE_SHOT_V1_3"
REAL_D1_ENVIRONMENT_AUTHORITY = "RQ2D1_TRACK_B_PACKET_ACCESS_AUTHORISED"

TRACK_B_FILE_NAME = "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
TRACK_B_SHA256 = "52c14dbc9e79b3c211e47ffd72697ec6ed87eec0478353066eb5d2f1ab45f351"
TRACK_B_SIZE_BYTES = 65_095
TRACK_B_RECORD_COUNT = 48
TRACK_B_COLUMN_COUNT = 47

R2_REVIEW_ZIP_NAME = "RQ2_D0_R2_EXACT_REFERENCE_POLICY_REPAIR_REVIEW_2026-08-28.zip"
R2_REVIEW_ZIP_SHA256 = (
    "031bbb1a1eeb94daf9213b2b167e7f34b9f484f07f11abe9ffb949e4e16aa147"
)
R1_REVIEW_ZIP_NAME = "RQ2_D0_R1_D1_PREARM_REPAIR_REVIEW_2026-08-28.zip"
R1_REVIEW_ZIP_SHA256 = (
    "f7dc5ba36fb1c3d3a53ea85d1c7a24bba145ef528cbdce5c5ec7292c685176a5"
)
SAFE_SCHEMA_ZIP_NAME = "RQ2_TRACK_B_SAFE_SCHEMA_AUTHORITY_2026-08-27.zip"
SAFE_SCHEMA_ZIP_SHA256 = (
    "11a1bcba3b4a6589f8947a3f24ec3b227f43a57a8d5fcf4ceb5adc5c568fd30e"
)

P1_POLICY_ID = "P1_D05_SIGNAL_UNION"
GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)
FIXTURE28_SHA256 = (
    "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
)
REFERENCE_AUTHORITY_COMMITMENT = (
    "8b8bc18ab6c9ea0d2cda6c5491b3448f3b1a67c97477a0cc0b9ca9c54ec6b401"
)

SAFE_JSON_FILENAMES = (
    "rq2d0_r3_preflight_report_v1.json",
    "global_one_shot_repair_authority_v1.json",
    "track_b_fixed_output_authority_v1.json",
    "track_b_global_reservation_contract_v1_3.json",
    "track_b_packet_generation_state_machine_v1_3.json",
    "track_b_effective_d1_entry_contract_v1_3.json",
    "rq2d0_r3_synthetic_validation_v1.json",
)
DOC_FILENAMES = (
    "RQ2D0_R3_GLOBAL_ONE_SHOT_ACCESS_CONTRACT.md",
    "RQ2D0_R3_FIXED_OUTPUT_AND_LOCK_AUTHORITY.md",
    "RQ2D0_R3_FINAL_D1_EXECUTION_RUNBOOK.md",
)
CHECKSUM_NAME = "rq2d0_r3_output_checksums_v1.sha256"
REVIEW_ZIP_NAME = "RQ2_D0_R3_GLOBAL_ONE_SHOT_REPAIR_REVIEW_2026-08-28.zip"


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
