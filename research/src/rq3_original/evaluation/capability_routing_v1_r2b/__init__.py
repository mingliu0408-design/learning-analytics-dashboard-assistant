"""RQ2-A-R2B adjudication closure and source-separated Gold freeze.

This package is research-only.  It freezes human decisions and safe,
label-only metadata; it does not implement a production capability router.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ2A_R2A_HEAD = "b9e7aa1b3ef5714223e0298512f11537d8602490"
RQ2A_R2A_PARENT = "9b5b02c8729c73cd71f3a84240d1c4a052c2bb60"
TARGET_BRANCH = "research/rq2-a-r2b-capability-gold-freeze"
COMMIT_MESSAGE = "rq2-a-r2b: freeze adjudicated source-separated capability gold"

RQ2A_R2A_REVIEW_ZIP_NAME = (
    "RQ2_A_R2A_HUMAN_REVIEW_CLOSURE_REVIEW_2026-08-26.zip"
)
RQ2A_R2A_REVIEW_ZIP_SHA256 = (
    "159721681d7a3dd77ed41e6490e8c0a90f2492539ec78f5b4194c0d2740d6baf"
)
RQ2A_R2A_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2a/rq2a_r2a_output_checksums_v1.sha256"
)
RQ2A_R2A_CHECKSUM_COUNT = 19

CANONICAL_A_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2a/local_review/"
    "reviewer_a_capability_review_v1_3_canonical.csv"
)
CANONICAL_B_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2a/local_review/"
    "reviewer_b_capability_review_v1_3_canonical.csv"
)
COMPLETED_ADJUDICATION_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2a/local_adjudication/"
    "rq2a_r2a_adjudication_packet_v1.csv"
)
CANONICAL_ADJUDICATION_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_adjudication/"
    "rq2a_r2a_adjudication_packet_v1_canonical.csv"
)
SOURCE_MAPPING_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_artifacts/"
    "source_blinded_review_id_mapping_v1_3.jsonl"
)
COMBINED_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/local_case_bank/"
    "combined_calibration_review_bank_v1_3.jsonl"
)

CANONICAL_A_SHA256 = (
    "4761de149ea68c7f4d231f451b6e83a326da52866dfd198ef9c0e127f6323888"
)
CANONICAL_B_SHA256 = (
    "e7a54912dbcf194a32f24669b13996b13fb25d95d7ccb4282b79a7b0aa4bf736"
)
COMPLETED_ADJUDICATION_SHA256 = (
    "2c99695e747606537cee163b79c727428114f661fd7175606ad3884e8b7c250c"
)
BLANK_ADJUDICATION_SHA256 = (
    "acb0f6111f51e38539e187c2899f4bd4853c69fd52cf104a2dcaebf1395afbf1"
)
CANONICAL_ADJUDICATION_SHA256 = (
    "a39b2733158183c8a73dd795d90c034931cfef188fa7d2217d321895869f64e6"
)
ADJUDICATION_ID_SET_SHA256 = (
    "e98e66488d5bcc08819665bb73610b1c131251bdd1afc58e9e48086d91122518"
)
SOURCE_MAPPING_SHA256 = (
    "c7b840ebb7e8809a1f9223924db9088f75f788f650d82b1332fe5fad5aafc09e"
)
COMBINED_BANK_SHA256 = (
    "2046ee91e83feb1194544698419ec1710bd471246fa4d1f43990b28c92840f22"
)

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
GOLD_RELEVANT_FIELDS = (
    "case_validity",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
)
LABEL_ONLY_FIELDS = (
    "review_case_id",
    "source_role",
    "gold_inclusion_status",
    "gold_decision_source",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
    "missing_context_disposition",
)

MISSING_CONTEXT_CASE_IDS = (
    "RQ2CAL-46535d95359b",
    "RQ2CAL-684be91e6e87",
    "RQ2CAL-cd195aac29e9",
)
SYNTHETIC_NATURALNESS_CASE_ID = "RQ2CAL-908f0290e13b"
CONTEXT_RESOLUTION_CASE_ID = "RQ2CAL-ad7f89d171e7"

LOCAL_GOLD_DIRECTORY = Path("evaluation/capability_routing_v1_r2b/local_gold")
LOCAL_AUTHENTIC_GOLD_RELATIVE = (
    LOCAL_GOLD_DIRECTORY / "authentic_codebook_calibration_gold_v1.jsonl"
)
LOCAL_SYNTHETIC_GOLD_RELATIVE = (
    LOCAL_GOLD_DIRECTORY / "synthetic_coverage_stress_gold_v1.jsonl"
)
LOCAL_AUTHENTIC_REGISTRY_RELATIVE = (
    LOCAL_GOLD_DIRECTORY / "authentic_context_missing_qualitative_registry_v1.jsonl"
)
LOCAL_COMBINED_GOLD_RELATIVE = (
    LOCAL_GOLD_DIRECTORY / "combined_capability_development_gold_v1.jsonl"
)

AUTHENTIC_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "authentic_codebook_calibration_gold_labels_v1.jsonl"
)
SYNTHETIC_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "synthetic_coverage_stress_gold_labels_v1.jsonl"
)
AUTHENTIC_REGISTRY_LABELS_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/"
    "authentic_context_missing_registry_labels_v1.jsonl"
)

EXPECTED_AUTHENTIC_DISTRIBUTION = {
    "dashboard_evidence": 12,
    "course_retrieval": 2,
    "episodic_memory": 0,
    "planning": 7,
    "safe_direct_response": 2,
    "clarification": 0,
    "context_resolution_required": 5,
}
EXPECTED_SYNTHETIC_DISTRIBUTION = {
    "dashboard_evidence": 12,
    "course_retrieval": 7,
    "episodic_memory": 8,
    "planning": 10,
    "safe_direct_response": 7,
    "clarification": 3,
    "context_resolution_required": 15,
    "multi_capability_cases": 9,
    "synthetic_clarification_exception_cases": 3,
}


class RQ2AR2BError(RuntimeError):
    """Base error for an RQ2-A-R2B contract violation."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def canonical_jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
        for row in rows
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def id_set_sha256(values: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(sorted(values)) + "\n").encode("utf-8"))


def reject_prohibited_track_path(value: str | Path) -> None:
    """Reject prohibited held-out path markers without touching those paths."""

    normalised = str(value).replace("\\", "/").replace("-", "_").lower()
    if "track_a" in normalised or "track_b" in normalised:
        raise RQ2AR2BError("Track A/Track B access is prohibited in RQ2-A-R2B")
