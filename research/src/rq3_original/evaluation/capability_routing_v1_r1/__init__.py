"""RQ2-A-R1 contract repair for calibration and human review.

This research-only package does not implement a capability router.  It repairs
the authority, baseline identity, and human-review protocol frozen by RQ2-A.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ2A_HEAD = "e411bf8f15815c0ba28736aef7cfc84eb8fe280d"
RQ2A_PARENT = "d54776424acde3a54f829cfc7ddb291e497489f6"
RQ2A_STARTING_TREE_SHA256 = (
    "6b04f3385691e0ddb9e6086c5bae55ec50a9a98b78934ddba3f53132e85870e0"
)
RQ2A_REVIEW_ZIP_SHA256 = (
    "bfa459c781bc28fb8942ffdb8ccc694c3682d412a23f5ae455b1d61d733cda0c"
)

RAW_SYNTHETIC_SOURCE_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "rq2a_contract_synthetic_source_v1.jsonl"
)
LOCAL_CANONICAL_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "capability_development_bank_v1.jsonl"
)
LOCAL_REVIEW_DIRECTORY_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_review"
)
OLD_REVIEW_A_RELATIVE = LOCAL_REVIEW_DIRECTORY_RELATIVE / (
    "reviewer_a_capability_review_v1.csv"
)
OLD_REVIEW_B_RELATIVE = LOCAL_REVIEW_DIRECTORY_RELATIVE / (
    "reviewer_b_capability_review_v1.csv"
)
NEW_REVIEW_A_RELATIVE = LOCAL_REVIEW_DIRECTORY_RELATIVE / (
    "reviewer_a_capability_review_v1_1.csv"
)
NEW_REVIEW_B_RELATIVE = LOCAL_REVIEW_DIRECTORY_RELATIVE / (
    "reviewer_b_capability_review_v1_1.csv"
)
OLD_REVIEW_PACKET_IDENTITIES = {
    OLD_REVIEW_A_RELATIVE.as_posix(): {
        "sha256": "a1837a91d99986530acae4a240510f25b7fd6692c09496f307e160dc5eefe410",
        "size_bytes": 10512,
        "record_count": 35,
    },
    OLD_REVIEW_B_RELATIVE.as_posix(): {
        "sha256": "4b595431e279daa5da96cc0d80c9fde72dced397f16f5cadcecb094eb8dcd538",
        "size_bytes": 10512,
        "record_count": 35,
    },
}

CALIBRATION_BANK_ALIAS = "RQ2_SYNTHETIC_CAPABILITY_CALIBRATION_BANK_V1"
PREDICTED_CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_exact_synthetic_source(relative: str | Path) -> Path:
    """Resolve only the authorised local synthetic source, never a search."""

    candidate = Path(relative)
    if candidate.as_posix() != RAW_SYNTHETIC_SOURCE_RELATIVE.as_posix():
        raise ValueError("source is outside the RQ2-A-R1 synthetic authority")
    return ROOT / RAW_SYNTHETIC_SOURCE_RELATIVE
