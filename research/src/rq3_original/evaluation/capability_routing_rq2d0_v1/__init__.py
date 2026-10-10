"""RQ2-D0 Track-B mapping and final-evaluation contract freeze.

This namespace is contract-only.  It may consume safe metadata and synthetic
fixtures, but it must never inspect the raw Track-B asset in D0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
SAFE_AUTHORITY_COPY_ROOT = HERE / "safe_schema_authority"

STAGE_ID = "RQ2-D0_TRACK_B_FINAL_CONTRACT"
STARTING_BRANCH = "research/rq2-c1-r1-offline-safety-isolation-repair"
STARTING_HEAD = "c911b08e4f68e14b51e0db56369969f41a3ade9b"
STARTING_PARENT = "717c285af907ab3cd27702d96e5e0d94420f8e54"
RESULT_BRANCH = "research/rq2-d0-track-b-final-contract"
COMMIT_SUBJECT = (
    "rq2-d0: freeze track-b capability mapping and final evaluation contract"
)

C1_R1_REVIEW_ZIP = Path.home() / (
    "Downloads/RQ2_C1_R1_OFFLINE_SAFETY_ISOLATION_REPAIR_REVIEW_2026-08-27.zip"
)
C1_R1_REVIEW_ZIP_SHA256 = (
    "571168da5c1f6a42401542a5fe3d8f6c6121cab8717295bbd19a71e5fdbc713a"
)
C1_REVIEW_ZIP = Path.home() / (
    "Downloads/RQ2_C1_OFFLINE_P2_IMPLEMENTATION_REVIEW_2026-08-27.zip"
)
C1_REVIEW_ZIP_SHA256 = (
    "43e606d08af9ecda7092d837df06d3c724147c19a9fd8b49790e368ea42e3857"
)
R5_REVIEW_ZIP = Path.home() / (
    "Downloads/RQ2_C0_R5_VALIDATED_BUNDLE_TIME_INTEGRITY_REVIEW_2026-08-27.zip"
)
R5_REVIEW_ZIP_SHA256 = (
    "4f696dab44d3d09f6580b9a2785964c68f2ee330977975e8d6f6c76f852db31d"
)

SCHEMA_AUTHORITY_ZIP = Path.home() / (
    "Downloads/RQ2_TRACK_B_SAFE_SCHEMA_AUTHORITY_2026-08-27.zip"
)
SCHEMA_AUTHORITY_ZIP_SHA256 = (
    "11a1bcba3b4a6589f8947a3f24ec3b227f43a57a8d5fcf4ceb5adc5c568fd30e"
)
SCHEMA_AUTHORITY_MEMBER_SHA256 = {
    "TRACK_B_BLANK_SCHEMA_TEMPLATE_V1.csv": (
        "bf9bc3df7b1800d9f4f87672afd0e6eafd274a7dea5dd4b5da9ac8a800a7e5d1"
    ),
    "TRACK_B_SCHEMA_AUTHORITY_CHECKSUMS.sha256": (
        "d76273421065310cf4604054034e66868b66c3b62789c5b1eae44ef81d489db9"
    ),
    "TRACK_B_SCHEMA_AUTHORITY_PROVENANCE_V1.json": (
        "04a12648f444e72100e2730e333658dcce09e95c8ee44ca29db53d486a7c3932"
    ),
    "TRACK_B_SCHEMA_AUTHORITY_REPORT.md": (
        "22b1955dc66b22095ae9fc7a7db92274624706416d54d8ab48e015561f4d00bf"
    ),
    "TRACK_B_SCHEMA_AUTHORITY_V1.json": (
        "ec145e5729762a968ac796aed792703617e161370143e4e29137750da3a3f56d"
    ),
    "TRACK_B_SCHEMA_FIELD_PROFILE_V1.json": (
        "42c49fc380f2768855d2402aa3cc4389e9df688eb83852fe49a6249e56bddfa6"
    ),
}

TRACK_B_FILE_NAME = "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
TRACK_B_SHA256 = "52c14dbc9e79b3c211e47ffd72697ec6ed87eec0478353066eb5d2f1ab45f351"
TRACK_B_SIZE_BYTES = 65_095
TRACK_B_RECORD_COUNT = 48
TRACK_B_COLUMN_COUNT = 47
TRACK_B_ORDER_COMMITMENT = (
    "f848379a4b464ea789f9c918487f6f5b16efaf6ce237f2b68ac01be4930e0104"
)

C1_R1_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c1_r1_v1/rq2c1_r1_output_checksums_v1.sha256"
)
C1_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c1_v1/rq2c1_output_checksums_v1.sha256"
)
R5_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r5_v1/rq2c0_r5_output_checksums_v1.sha256"
)
EXPECTED_CHECKSUM_COUNTS = {
    C1_R1_CHECKSUM_RELATIVE: 32,
    C1_CHECKSUM_RELATIVE: 42,
    R5_CHECKSUM_RELATIVE: 26,
}

FIXTURE_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
    "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)
FIXTURE_SHA256 = "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
P1_POLICY_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/rq2b_final_p1_policy_v1.json"
)
P1_POLICY_SHA256 = "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942"
P1_POLICY_ID = "P1_D05_SIGNAL_UNION"
GOLD_BUNDLE_SHA256 = "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
RQ1_ROUTER = "C0_COSINE"

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)

SAFE_JSON_FILENAMES = (
    "track_b_safe_authority_contract_v1.json",
    "track_b_schema_authority_v1.json",
    "track_b_capability_review_schema_v1.json",
    "track_b_blinding_contract_v1.json",
    "track_b_contamination_contract_v1.json",
    "track_b_packet_generation_state_machine_v1.json",
    "rq2_final_scope_contract_v1.json",
    "rq2_final_statistical_contract_v1.json",
    "rq2d0_synthetic_validation_v1.json",
    "rq2d0_preflight_report_v1.json",
)
DOC_FILENAMES = (
    "RQ2D0_TRACK_B_AUTHORITY_AND_SCHEMA.md",
    "RQ2D0_TRACK_B_CAPABILITY_MAPPING_PROTOCOL.md",
    "RQ2D0_RQ2_FINAL_EVALUATION_SCOPE.md",
    "RQ2D0_ONE_SHOT_PACKET_GENERATION_RUNBOOK.md",
    "RQ2D0_STATISTICAL_AND_CONTAMINATION_CONTRACT.md",
)
CHECKSUM_NAME = "rq2d0_output_checksums_v1.sha256"
REVIEW_ZIP_NAME = "RQ2_D0_TRACK_B_FINAL_CONTRACT_REVIEW_2026-08-27.zip"


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


def write_json(path: Path, value: Mapping[str, Any] | Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
