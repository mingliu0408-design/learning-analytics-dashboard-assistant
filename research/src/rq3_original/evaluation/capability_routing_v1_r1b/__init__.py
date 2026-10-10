"""RQ2-A-R1B authentic-dialogue calibration integration contracts.

This package is research-only.  It creates local blinded review material and
safe aggregate metadata; it does not implement a production capability router.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ2A_R1_HEAD = "e4dc39bcb5753d9601b2b9056ec68208d99562d6"
RQ2A_R1_PARENT = "e411bf8f15815c0ba28736aef7cfc84eb8fe280d"
RQ2A_R1_TREE_SHA256 = (
    "9077227d3a64c052aa490fee0dc591bb1e2f48a74f49c1e45e3ba19ab3e92994"
)
TARGET_BRANCH = "research/rq2-a-r1b-authentic-calibration-integration"

RQ2A_R1_REVIEW_ZIP_NAME = "RQ2_A_R1_REVIEW_PROTOCOL_REPAIR_2026-08-25.zip"
RQ2A_R1_REVIEW_ZIP_SHA256 = (
    "5e5df9344ee5e3afc4cccbf567dbc26c8b8bebf44a11142f238f238389ae879b"
)
AUTHORITY_ZIP_NAME = "RQ2_AUTHENTIC_DIALOGUE_CALIBRATION_AUTHORITY_2026-08-25.zip"
AUTHORITY_ZIP_SHA256 = (
    "50df97f9e8caf37007d61ab4e6536a5e2cad33c787d4bce537be78b2e8bdb36f"
)
AUTHORITY_MANIFEST_SHA256 = (
    "ab60a8951c8702ae818b0c81d1c7631ccf4c76ae026e1571994f9c29751327c7"
)
AUTHORITY_MEMBERS = (
    "RQ2_AUTHENTIC_DIALOGUE_AUTHORITY_CHECKSUMS.sha256",
    "RQ2_AUTHENTIC_DIALOGUE_CALIBRATION_AUTHORITY_V1.json",
    "RQ2_AUTHENTIC_DIALOGUE_INTEGRATION_REPORT.md",
)

PREFERRED_AUTHENTIC_SOURCE_RELATIVE = Path("System Data/Example Conversation Data.csv")
FALLBACK_AUTHENTIC_SOURCE_NAME = "Example Conversation Data(4).csv"
AUTHENTIC_SOURCE_SHA256 = (
    "6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8"
)
AUTHENTIC_SOURCE_SIZE_BYTES = 19646
AUTHENTIC_COLUMNS = ("graph", "role", "message")
AUTHENTIC_RECORD_COUNT = 50
AUTHENTIC_USER_TURN_COUNT = 25
AUTHENTIC_ASSISTANT_TURN_COUNT = 25
AUTHENTIC_PAGE_DISTRIBUTION = {
    "Debate": 4,
    "Lecture": 3,
    "Overview": 10,
    "Reflection": 5,
    "Resources": 3,
}
AUTHENTIC_BANK_ALIAS = "RQ2_AUTHENTIC_DIALOGUE_CODEBOOK_CALIBRATION_BANK_V1"
SYNTHETIC_STRESS_BANK_ALIAS = "RQ2_SYNTHETIC_CAPABILITY_COVERAGE_STRESS_BANK_V1"
COMBINED_REVIEW_BANK_ALIAS = "RQ2_SOURCE_BLINDED_COMBINED_CALIBRATION_BANK_V1_2"
HIGH_CONFIDENCE_CONTEXT_CASE_IDS = (
    "AUTH-0005",
    "AUTH-0007",
    "AUTH-0020",
    "AUTH-0022",
    "AUTH-0025",
)

SYNTHETIC_SOURCE_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "rq2a_contract_synthetic_source_v1.jsonl"
)
SYNTHETIC_CANONICAL_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "capability_development_bank_v1.jsonl"
)
SYNTHETIC_SOURCE_SHA256 = (
    "b08f690547820945a503acf61cdcd9b0e2c305a28f0262afc16b76cd10668cff"
)
SYNTHETIC_CANONICAL_BANK_SHA256 = (
    "a791a154638e59436867c50e3fcfc4d15e2d2fef47ee2c52937892b49b0092a6"
)
SYNTHETIC_CASE_ID_SET_SHA256 = (
    "ede24ea3d6b43e97f0ac108dada44419b99d937b7af4f6f60c7f5291bfa2125b"
)

LOCAL_CASE_BANK_DIRECTORY = Path("evaluation/capability_routing_v1_r1b/local_case_bank")
LOCAL_ARTIFACT_DIRECTORY = Path("evaluation/capability_routing_v1_r1b/local_artifacts")
LOCAL_REVIEW_DIRECTORY = Path("evaluation/capability_routing_v1_r1b/local_review")
LOCAL_AUTHENTIC_BANK_RELATIVE = LOCAL_CASE_BANK_DIRECTORY / "authentic_case_bank_v1.jsonl"
LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE = (
    LOCAL_CASE_BANK_DIRECTORY / "synthetic_coverage_stress_bank_v1.jsonl"
)
LOCAL_COMBINED_BANK_RELATIVE = (
    LOCAL_CASE_BANK_DIRECTORY / "combined_calibration_review_bank_v1_2.jsonl"
)
LOCAL_REVIEW_ID_MAPPING_RELATIVE = (
    LOCAL_ARTIFACT_DIRECTORY / "source_blinded_review_id_mapping_v1_2.jsonl"
)
LOCAL_REVIEW_A_RELATIVE = LOCAL_REVIEW_DIRECTORY / "reviewer_a_capability_review_v1_2.csv"
LOCAL_REVIEW_B_RELATIVE = LOCAL_REVIEW_DIRECTORY / "reviewer_b_capability_review_v1_2.csv"

OLD_PACKET_IDENTITIES = {
    "evaluation/capability_routing_v1/local_review/reviewer_a_capability_review_v1.csv": {
        "sha256": "a1837a91d99986530acae4a240510f25b7fd6692c09496f307e160dc5eefe410",
        "size_bytes": 10512,
        "record_count": 35,
    },
    "evaluation/capability_routing_v1/local_review/reviewer_b_capability_review_v1.csv": {
        "sha256": "4b595431e279daa5da96cc0d80c9fde72dced397f16f5cadcecb094eb8dcd538",
        "size_bytes": 10512,
        "record_count": 35,
    },
    "evaluation/capability_routing_v1/local_review/reviewer_a_capability_review_v1_1.csv": {
        "sha256": "761d868297415b94c1551c722afd8f57096fcb44064d7bce515bc8e2edcaa6b6",
        "size_bytes": 10787,
        "record_count": 35,
    },
    "evaluation/capability_routing_v1/local_review/reviewer_b_capability_review_v1_1.csv": {
        "sha256": "5f24b026d1ed1aba87f9c9564581b3435cb7296fcbd51969256eed5d12456774",
        "size_bytes": 10787,
        "record_count": 35,
    },
}

REFERENCE_SOURCES = {
    "candidate_62": {
        "relative_path": "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
        "sha256": "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
        "record_count": 62,
    },
    "unified_benchmark_62": {
        "relative_path": "evaluation/unified_benchmark_scenarios.jsonl",
        "sha256": "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
        "record_count": 62,
    },
    "legacy_scenarios_25": {
        "relative_path": "evaluation/scenarios.jsonl",
        "sha256": "e74f1b583c5225da4bb8b999b11c1cf72b8a8f2b89b8633da40982eb675a4d1e",
        "record_count": 25,
    },
    "rq1_expanded_train_318": {
        "relative_path": (
            "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
            "ranker_expanded_train_manifest_candidate_v2.jsonl"
        ),
        "sha256": "623bcdeaad62ae20559c616dc57aedfb22bd2d006f0beb6888da88d549c40805",
        "record_count": 318,
    },
    "rq1_dev_84": {
        "relative_path": (
            "evaluation/learned_intent_ranking/lr1r/"
            "ranker_dev_manifest_candidate_v2.jsonl"
        ),
        "sha256": "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f",
        "record_count": 84,
    },
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
