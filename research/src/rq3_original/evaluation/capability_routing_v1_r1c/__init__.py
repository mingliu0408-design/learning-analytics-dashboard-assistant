"""RQ2-A-R1C provenance closure and context-link removal contracts.

This research-only package freezes user-attested provenance and creates local,
source-blinded reviewer material.  It does not implement a capability router.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ2A_R1B_HEAD = "e98f22a5b4ea0850a7a92f1e1e1f317521454de7"
RQ2A_R1B_PARENT = "e4dc39bcb5753d9601b2b9056ec68208d99562d6"
RQ2A_R1B_TREE_SHA256 = (
    "f67408808dfaf531396139c016ebb61cd10c838dc28a94e59ce207279026fd2e"
)
TARGET_BRANCH = "research/rq2-a-r1c-authentic-provenance-closure"

RQ2A_R1B_REVIEW_ZIP_NAME = (
    "RQ2_A_R1B_AUTHENTIC_CALIBRATION_INTEGRATION_REVIEW_2026-08-25.zip"
)
RQ2A_R1B_REVIEW_ZIP_SHA256 = (
    "91d40789c201038f97a4511d44028da4596b5fdcfba5fd662eaf2c0a23cce12a"
)
AUTHENTIC_SOURCE_RELATIVE = Path("System Data/Example Conversation Data.csv")
AUTHENTIC_SOURCE_SHA256 = (
    "6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8"
)
AUTHENTIC_SOURCE_SIZE_BYTES = 19646
AUTHENTIC_RECORD_COUNT = 50
AUTHENTIC_USER_COUNT = 25
AUTHENTIC_ASSISTANT_COUNT = 25

AUTHENTIC_BANK_ALIAS = "RQ2_AUTHENTIC_DIALOGUE_CODEBOOK_CALIBRATION_BANK_V1"
SYNTHETIC_BANK_ALIAS = "RQ2_SYNTHETIC_CAPABILITY_COVERAGE_STRESS_BANK_V1"
COMBINED_BANK_ALIAS = "RQ2_SOURCE_BLINDED_COMBINED_CALIBRATION_BANK_V1_3"
PREVIOUS_CONTEXT_CASE_IDS = (
    "AUTH-0005",
    "AUTH-0007",
    "AUTH-0020",
    "AUTH-0022",
    "AUTH-0025",
)

R1B_AUTHENTIC_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1b/local_case_bank/authentic_case_bank_v1.jsonl"
)
R1B_SYNTHETIC_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1b/local_case_bank/"
    "synthetic_coverage_stress_bank_v1.jsonl"
)
R1B_COMBINED_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1b/local_case_bank/"
    "combined_calibration_review_bank_v1_2.jsonl"
)
R1B_MAPPING_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1b/local_artifacts/"
    "source_blinded_review_id_mapping_v1_2.jsonl"
)
R1B_AUTHENTIC_BANK_SHA256 = (
    "5c30a9104a8e68c091a809a46afdc9a07900208b47097181dc41af251d59fe46"
)
R1B_SYNTHETIC_BANK_SHA256 = (
    "a791a154638e59436867c50e3fcfc4d15e2d2fef47ee2c52937892b49b0092a6"
)
R1B_COMBINED_BANK_SHA256 = (
    "01cacbf057ff6c64325ab522b31322282738880d15727d5e912775e13f87951a"
)
R1B_MAPPING_SHA256 = (
    "c7b840ebb7e8809a1f9223924db9088f75f788f650d82b1332fe5fad5aafc09e"
)

LOCAL_CASE_BANK_DIRECTORY = Path("evaluation/capability_routing_v1_r1c/local_case_bank")
LOCAL_ARTIFACT_DIRECTORY = Path("evaluation/capability_routing_v1_r1c/local_artifacts")
LOCAL_REVIEW_DIRECTORY = Path("evaluation/capability_routing_v1_r1c/local_review")
LOCAL_AUTHENTIC_BANK_RELATIVE = (
    LOCAL_CASE_BANK_DIRECTORY / "authentic_case_bank_v1_1.jsonl"
)
LOCAL_SYNTHETIC_BANK_RELATIVE = (
    LOCAL_CASE_BANK_DIRECTORY / "synthetic_coverage_stress_bank_v1.jsonl"
)
LOCAL_COMBINED_BANK_RELATIVE = (
    LOCAL_CASE_BANK_DIRECTORY / "combined_calibration_review_bank_v1_3.jsonl"
)
LOCAL_MAPPING_RELATIVE = (
    LOCAL_ARTIFACT_DIRECTORY / "source_blinded_review_id_mapping_v1_3.jsonl"
)
LOCAL_REVIEW_A_RELATIVE = (
    LOCAL_REVIEW_DIRECTORY / "reviewer_a_capability_review_v1_3.csv"
)
LOCAL_REVIEW_B_RELATIVE = (
    LOCAL_REVIEW_DIRECTORY / "reviewer_b_capability_review_v1_3.csv"
)

OLD_PACKET_IDENTITIES = {
    "evaluation/capability_routing_v1/local_review/reviewer_a_capability_review_v1.csv": (
        "a1837a91d99986530acae4a240510f25b7fd6692c09496f307e160dc5eefe410",
        10512,
        35,
    ),
    "evaluation/capability_routing_v1/local_review/reviewer_b_capability_review_v1.csv": (
        "4b595431e279daa5da96cc0d80c9fde72dced397f16f5cadcecb094eb8dcd538",
        10512,
        35,
    ),
    "evaluation/capability_routing_v1/local_review/reviewer_a_capability_review_v1_1.csv": (
        "761d868297415b94c1551c722afd8f57096fcb44064d7bce515bc8e2edcaa6b6",
        10787,
        35,
    ),
    "evaluation/capability_routing_v1/local_review/reviewer_b_capability_review_v1_1.csv": (
        "5f24b026d1ed1aba87f9c9564581b3435cb7296fcbd51969256eed5d12456774",
        10787,
        35,
    ),
    "evaluation/capability_routing_v1_r1b/local_review/reviewer_a_capability_review_v1_2.csv": (
        "535fb60ef8a1d700cb95b31aa8f522cb26f9adad8c459389928a1f86bd33bdfd",
        15505,
        60,
    ),
    "evaluation/capability_routing_v1_r1b/local_review/reviewer_b_capability_review_v1_2.csv": (
        "3824067154653d550f3f4de64ff5920b7735e087df67f4fa9709920b19f27cb1",
        15505,
        60,
    ),
}

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


def canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
        for row in rows
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def id_set_sha256(values: list[str]) -> str:
    return sha256_bytes(("\n".join(sorted(values)) + "\n").encode("utf-8"))


def reject_prohibited_track_path(relative: str | Path) -> None:
    """Reject Track A/B lexically without touching either filesystem path."""

    value = str(relative).replace("-", "_").lower()
    if "track_a" in value or "track_b" in value:
        raise PermissionError("Track A/B access is prohibited in RQ2-A-R1C")
