"""RQ2-C0-R4 persistent-memory payload-integrity contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

STARTING_BRANCH = "research/rq2-c0-r3-state-aware-memory-safety-repair"
STARTING_HEAD = "f8b7d8bbb861cb079103b2c92fe799c67249e2a5"
STARTING_PARENT = "9d69516af5e9fcde72e0b4b5891ac0fe94afdc5a"
RESULT_BRANCH = "research/rq2-c0-r4-payload-integrity-repair"
COMMIT_SUBJECT = "rq2-c0-r4: bind persistent payload identity and provenance"

R3_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R3_MEMORY_SAFETY_REPAIR_REVIEW_2026-08-27.zip"
)
EXPECTED_R3_REVIEW_ZIP_SHA256 = (
    "c860ee1cd1cd05b490fbc6b2b000d86faa131e98587514c0aabd71bdfb96e7ba"
)
R2_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r2_v1/rq2c0_r2_output_checksums_v1.sha256"
)
R3_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r3_v1/rq2c0_r3_output_checksums_v1.sha256"
)
EXPECTED_R2_OUTPUT_CHECKSUM_COUNT = 36
EXPECTED_R3_OUTPUT_CHECKSUM_COUNT = 18
EXPECTED_R2_OUTPUT_CHECKSUM_SHA256 = (
    "55ef90d458090318452895d9cdc3f192cddd94e2227843412c18984d184df991"
)
EXPECTED_R3_OUTPUT_CHECKSUM_SHA256 = (
    "eadf625b702d0493559d1dd1e1b64859b45f00644d83660a2fb1652d6bd9bd9a"
)
EXPECTED_R2_TRACKED_FILE_COUNT = 31
EXPECTED_R2_TRACKED_MANIFEST_SHA256 = (
    "be03ff16f50155a4e03134cb325670d6844c46815d933bd329a7800aefbc4bce"
)
EXPECTED_R3_TRACKED_FILE_COUNT = 16
EXPECTED_R3_TRACKED_MANIFEST_SHA256 = (
    "9542c583ad78dca823f1e77887f60131c38d79e34de9cf358ed5ebb9a45cdf7e"
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
EXPECTED_EFFECTIVE_RETRIEVAL = "PMR_HYBRID_STATE_AWARE_V1_1"
EXPECTED_EFFECTIVE_ADMISSION = "MEMORY_ADMISSION_V1_1"
EXPECTED_PAYLOAD_SCOPE = "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1"

EXPECTED_PROTECTED_FILE_COUNT = 516
EXPECTED_PROTECTED_MANIFEST_SHA256 = (
    "a51c2dd2c59b6f216e659634ef3c34bed45f30d460d3f6b0213da69f4f83ae96"
)

AUTHORITY_TYPE = "USER_EXPLICIT_PRE_IMPLEMENTATION_PAYLOAD_INTEGRITY_CORRECTION"
AUTHORISATION_DATE = "2026-08-27"

SAFE_OUTPUT_FILENAMES = (
    "payload_integrity_repair_authority_v1.json",
    "student_scope_hash_contract_v1.json",
    "payload_identity_binding_contract_v1.json",
    "payload_metadata_consistency_contract_v1.json",
    "temporal_integrity_contract_v1.json",
    "composite_validator_contract_v1_3.json",
    "effective_persistent_memory_contract_v1_3.json",
    "rq2c0_r4_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_R4_PAYLOAD_IDENTITY_AND_SCOPE_BINDING.md",
    "RQ2C0_R4_PROVENANCE_AND_TEMPORAL_INTEGRITY.md",
    "RQ2C0_R4_COMPOSITE_VALIDATION_AND_EFFECTIVE_CONTRACT.md",
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
