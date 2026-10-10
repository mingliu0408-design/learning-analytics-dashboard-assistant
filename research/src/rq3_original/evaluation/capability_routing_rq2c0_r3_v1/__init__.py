"""RQ2-C0-R3 effective persistent-memory safety contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

STARTING_BRANCH = "research/rq2-c0-r2-executable-memory-contract"
STARTING_HEAD = "9d69516af5e9fcde72e0b4b5891ac0fe94afdc5a"
STARTING_PARENT = "1d4a651effeefa8cfa1470c70ab59951e970401e"
RESULT_BRANCH = "research/rq2-c0-r3-state-aware-memory-safety-repair"
COMMIT_SUBJECT = (
    "rq2-c0-r3: repair state-aware retrieval and temporal admission safety"
)

R2_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R2_EXECUTABLE_MEMORY_CONTRACT_REVIEW_2026-08-27.zip"
)
EXPECTED_R2_REVIEW_ZIP_SHA256 = (
    "91f3575fdc939a497d9d389f8cb564ff48ea42c656fac80f3a75faba6f60aeee"
)
R2_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r2_v1/rq2c0_r2_output_checksums_v1.sha256"
)
EXPECTED_R2_OUTPUT_CHECKSUM_SHA256 = (
    "55ef90d458090318452895d9cdc3f192cddd94e2227843412c18984d184df991"
)
EXPECTED_R2_OUTPUT_CHECKSUM_COUNT = 36
EXPECTED_R2_TRACKED_FILE_COUNT = 31
EXPECTED_R2_TRACKED_MANIFEST_SHA256 = (
    "be03ff16f50155a4e03134cb325670d6844c46815d933bd329a7800aefbc4bce"
)

FIXTURE_BANK_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
    "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)
FIXTURE_BANK_PATH = ROOT / FIXTURE_BANK_RELATIVE
EXPECTED_FIXTURE_BANK_SHA256 = (
    "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
)
EXPECTED_FIXTURE_BANK_SIZE = 24163
EXPECTED_FIXTURE_RECORD_COUNT = 28
EXPECTED_P1_POLICY = "P1_D05_SIGNAL_UNION"
EXPECTED_GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)
EXPECTED_PRIMARY_POLICY_ID = "PMR_HYBRID_STATE_AWARE"

EXPECTED_PROTECTED_FILE_COUNT = 502
EXPECTED_PROTECTED_MANIFEST_SHA256 = (
    "c2fd0a56242e0895656da48195b4c7ee58636ae4b86fdb8e6a53e7b6b609ba76"
)

AUTHORITY_TYPE = "USER_EXPLICIT_PRE_IMPLEMENTATION_MEMORY_SAFETY_CORRECTION"
AUTHORISATION_DATE = "2026-08-27"

SAFE_OUTPUT_FILENAMES = (
    "memory_safety_repair_authority_v1.json",
    "state_aware_candidate_ordering_amendment_v1.json",
    "temporal_admission_safety_amendment_v1.json",
    "text_only_payload_scope_amendment_v1.json",
    "effective_persistent_memory_contract_v1_2.json",
    "rq2c0_r3_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_R3_STATE_AWARE_CANDIDATE_ORDERING.md",
    "RQ2C0_R3_TEMPORAL_ADMISSION_SAFETY.md",
    "RQ2C0_R3_PAYLOAD_SCOPE_AND_EFFECTIVE_CONTRACT.md",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
