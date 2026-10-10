"""RQ2-A-R2A packet-freeze and human-adjudication preparation constants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ2A_R1C_HEAD = "9b5b02c8729c73cd71f3a84240d1c4a052c2bb60"
RQ2A_R1C_PARENT = "e98f22a5b4ea0850a7a92f1e1e1f317521454de7"
RQ2A_R1C_TREE_SHA256 = (
    "15a0ba42ad523719a531ae6beaf08ba2d3b6c66005cbcd9dc3e387526bc00061"
)
TARGET_BRANCH = "research/rq2-a-r2a-human-review-closure"

RQ2A_R1C_REVIEW_ZIP_NAME = (
    "RQ2_A_R1C_AUTHENTIC_PROVENANCE_CLOSURE_REVIEW_2026-08-26.zip"
)
RQ2A_R1C_REVIEW_ZIP_SHA256 = (
    "3f647074d38a334932c0c2768b2c62adfc09e99c7e7eef4e11593df45f5b62a3"
)
RQ2A_R1C_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/rq2a_r1c_output_checksums_v1.sha256"
)
RQ2A_R1C_CHECKSUM_COUNT = 22

ORIGINAL_A_SHA256 = (
    "17ef20990c2bf76a84e7ed4c5d021dbcb79f0ef7de8d91b335c5458c6f1c7b87"
)
CORRECTED_A_SHA256 = (
    "847a192283752547ee242c8e65184a2a4d776d74ef817ae925c715fe8a483df9"
)
COMPLETED_B_SHA256 = (
    "b87de072e2ef1a0bdab874dcd7d59bf45451ea974d8b1067149a45236cb8d4cc"
)
CANONICAL_A_SHA256 = (
    "4761de149ea68c7f4d231f451b6e83a326da52866dfd198ef9c0e127f6323888"
)
CANONICAL_B_SHA256 = (
    "e7a54912dbcf194a32f24669b13996b13fb25d95d7ccb4282b79a7b0aa4bf736"
)
BLANK_A_SHA256 = (
    "94aebdb33758e3ea5729e2234f864215bccb6c4e574fb4f84465db663253f3cf"
)
BLANK_B_SHA256 = (
    "30cab031c5c6697b976b16d862cb19c4c7fb37c7f3a38b7b31a7767243381532"
)
SOURCE_MAPPING_SHA256 = (
    "c7b840ebb7e8809a1f9223924db9088f75f788f650d82b1332fe5fad5aafc09e"
)
COMBINED_BANK_SHA256 = (
    "2046ee91e83feb1194544698419ec1710bd471246fa4d1f43990b28c92840f22"
)

R1C_LOCAL_REVIEW = Path("evaluation/capability_routing_v1_r1c/local_review")
R1C_ORIGINAL_A_RELATIVE = R1C_LOCAL_REVIEW / "reviewer_a_capability_review_v1_3.csv"
R1C_CORRECTED_A_RELATIVE = (
    R1C_LOCAL_REVIEW / "reviewer_a_capability_review_v1_3_corrected_v2.csv"
)
R1C_COMPLETED_B_RELATIVE = R1C_LOCAL_REVIEW / "reviewer_b_capability_review_v1_3.csv"
R1C_MAPPING_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_artifacts/"
    "source_blinded_review_id_mapping_v1_3.jsonl"
)
R1C_COMBINED_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_case_bank/"
    "combined_calibration_review_bank_v1_3.jsonl"
)

R2A_LOCAL_REVIEW = Path("evaluation/capability_routing_v1_r2a/local_review")
R2A_LOCAL_ADJUDICATION = Path(
    "evaluation/capability_routing_v1_r2a/local_adjudication"
)
R2A_LOCAL_ARTIFACTS = Path("evaluation/capability_routing_v1_r2a/local_artifacts")
CANONICAL_A_RELATIVE = (
    R2A_LOCAL_REVIEW / "reviewer_a_capability_review_v1_3_canonical.csv"
)
CANONICAL_B_RELATIVE = (
    R2A_LOCAL_REVIEW / "reviewer_b_capability_review_v1_3_canonical.csv"
)
ADJUDICATION_PACKET_RELATIVE = (
    R2A_LOCAL_ADJUDICATION / "rq2a_r2a_adjudication_packet_v1.csv"
)

EXPECTED_CORRECTED_CASE_IDS = (
    "RQ2CAL-880e3f0fd7f0",
    "RQ2CAL-c3aa6922fcb1",
    "RQ2CAL-12c362e21314",
    "RQ2CAL-39b5d301ec03",
    "RQ2CAL-dfc19ec65698",
    "RQ2CAL-7e0b2a5d6a1e",
    "RQ2CAL-ff7858da6978",
)
EXPECTED_ADJUDICATION_CASES = (
    ("RQ2CAL-46535d95359b", "AUTHENTIC_CONTEXT_INSUFFICIENT"),
    ("RQ2CAL-684be91e6e87", "AUTHENTIC_CONTEXT_INSUFFICIENT"),
    ("RQ2CAL-cd195aac29e9", "AUTHENTIC_CONTEXT_INSUFFICIENT"),
    ("RQ2CAL-908f0290e13b", "NATURALNESS_DIFFERENCE_AT_LEAST_TWO"),
    ("RQ2CAL-ad7f89d171e7", "CONTEXT_RESOLUTION_DISAGREEMENT"),
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordered_id_sha256(values: list[str]) -> str:
    return sha256_bytes(("\n".join(values) + "\n").encode("utf-8"))


def id_set_sha256(values: list[str]) -> str:
    return ordered_id_sha256(sorted(values))


def reject_prohibited_track_path(value: str | Path) -> None:
    normalised = str(value).replace("\\", "/").lower()
    prohibited = (
        "track_a",
        "track_b",
        "local_final_gold",
        "final_gold",
        "heldout",
    )
    if any(marker in normalised for marker in prohibited):
        raise ValueError("Track A/Track B paths are outside RQ2-A-R2A authority")
