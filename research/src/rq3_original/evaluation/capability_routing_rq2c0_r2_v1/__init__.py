"""RQ2-C0-R2 executable persistent-memory contracts without runtime implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

STARTING_BRANCH = "research/rq2-c0-r1-persistent-memory-contract"
STARTING_HEAD = "1d4a651effeefa8cfa1470c70ab59951e970401e"
STARTING_PARENT = "4c611d2a0e84433f408cfb310b5ea39316384f1e"
RESULT_BRANCH = "research/rq2-c0-r2-executable-memory-contract"
COMMIT_SUBJECT = "rq2-c0-r2: freeze executable persistent memory contract"

R1_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R1_PERSISTENT_MEMORY_CONTRACT_REVIEW_2026-08-26.zip"
)
EXPECTED_R1_REVIEW_ZIP_SHA256 = (
    "e714f6f373a5802d37aa669d0f059099e5f7d2ac350f5ab63ac81438f522703e"
)
R1_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/rq2c0_r1_output_checksums_v1.sha256"
)
EXPECTED_R1_CHECKSUM_COUNT = 30
R1_SCOPE_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/rq2c0_r1_scope_authority_v1.json"
)
R1_FIXTURE_BANK_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
    "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)
R1_FIXTURE_BANK_PATH = ROOT / R1_FIXTURE_BANK_RELATIVE
EXPECTED_FIXTURE_BANK_SHA256 = (
    "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
)
EXPECTED_FIXTURE_BANK_SIZE = 24163
EXPECTED_FIXTURE_RECORD_COUNT = 28
EXPECTED_P1_POLICY = "P1_D05_SIGNAL_UNION"
EXPECTED_GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)

AMENDMENT_CONTRACT_ID = "RQ2C0_R2_FIXTURE_FIELD_SEMANTICS_V1_1"
AMENDMENT_AUTHORITY_TYPE = (
    "USER_EXPLICIT_MECHANISM_SPECIFIC_FIXTURE_VALIDATION_AUTHORISATION"
)

SAFE_OUTPUT_FILENAMES = (
    "persistent_learner_memory_schema_v1_1.json",
    "private_memory_payload_boundary_v1.json",
    "structured_write_candidate_contract_v1.json",
    "event_memory_type_compatibility_v1.json",
    "executable_persistent_retrieval_contract_v1.json",
    "memory_admission_contract_v1.json",
    "multi_hop_memory_contract_v1.json",
    "p2_condition_semantics_v2_1.json",
    "controlled_mechanism_fixture_semantic_commitment_v1.jsonl",
    "controlled_mechanism_fixture_semantic_validation_v1.json",
    "controlled_mechanism_fixture_semantic_validation_v1_1.json",
    "persistent_memory_literature_evidence_v1.json",
    "fixture_semantic_validation_amendment_v1.json",
    "mechanism_specific_fixture_field_semantics_v1_1.json",
    "rq2c0_r2_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_R2_EXECUTABLE_MEMORY_ALGORITHM.md",
    "RQ2C0_R2_PRIVATE_PAYLOAD_AND_WRITE_BOUNDARY.md",
    "RQ2C0_R2_FIXTURE_SEMANTIC_VALIDATION.md",
    "RQ2C0_R2_P2_CONDITION_SEMANTICS.md",
    "RQ2C0_R2_LITERATURE_TO_ARCHITECTURE_TRACEABILITY.md",
    "RQ2C0_R2_FIXTURE_SEMANTIC_VALIDATION_AMENDMENT.md",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def canonical_json_line(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
