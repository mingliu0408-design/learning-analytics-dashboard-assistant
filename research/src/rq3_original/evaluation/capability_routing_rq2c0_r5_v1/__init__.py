"""RQ2-C0-R5 validated-bundle and retrieval-time integrity contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

STARTING_BRANCH = "research/rq2-c0-r4-payload-integrity-repair"
STARTING_HEAD = "4cb306a4fa5268b647f5b0e0df051a08c6381e17"
STARTING_PARENT = "f8b7d8bbb861cb079103b2c92fe799c67249e2a5"
RESULT_BRANCH = "research/rq2-c0-r5-validated-bundle-time-integrity-repair"
COMMIT_SUBJECT = "rq2-c0-r5: bind validated memory bundles and retrieval time"

R4_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R4_PAYLOAD_INTEGRITY_REPAIR_REVIEW_2026-08-27.zip"
)
EXPECTED_R4_REVIEW_ZIP_SHA256 = (
    "ee2cbddcfae415278c3d889f0824c4135042c969eab413d09852926be5a25fec"
)
R2_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r2_v1/rq2c0_r2_output_checksums_v1.sha256"
)
R3_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r3_v1/rq2c0_r3_output_checksums_v1.sha256"
)
R4_OUTPUT_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r4_v1/rq2c0_r4_output_checksums_v1.sha256"
)
EXPECTED_OUTPUT_CHECKSUMS = {
    "R2": (36, "55ef90d458090318452895d9cdc3f192cddd94e2227843412c18984d184df991"),
    "R3": (18, "eadf625b702d0493559d1dd1e1b64859b45f00644d83660a2fb1652d6bd9bd9a"),
    "R4": (22, "b5f9357ef6b9a247d10b941fbf79e0afa97c7754545e238a45e254aa07d69161"),
}
EXPECTED_TRACKED_HISTORY = {
    "R2": (31, "be03ff16f50155a4e03134cb325670d6844c46815d933bd329a7800aefbc4bce"),
    "R3": (16, "9542c583ad78dca823f1e77887f60131c38d79e34de9cf358ed5ebb9a45cdf7e"),
    "R4": (20, "bb14034de35993990853e50bb4ccd86016acccfe0c300a05a761b1e8d9f748e4"),
}

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
EXPECTED_R4_PAYLOAD_BINDING = "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3"

EXPECTED_PROTECTED_FILE_COUNT = 539
EXPECTED_PROTECTED_MANIFEST_SHA256 = (
    "208a8c6e17a706ffc91afb7fd908303077880caa31203fbd5d60a1e95a34624c"
)

AUTHORITY_TYPE = "USER_EXPLICIT_FINAL_PRE_IMPLEMENTATION_VALIDATION_AND_TEMPORAL_CORRECTION"
AUTHORISATION_DATE = "2026-08-27"
R5_VALIDATOR_ID = "PERSISTENT_MEMORY_VALIDATED_BUNDLE_V1_4"
VALIDATED_PLAN_ID = "VALIDATED_RETRIEVAL_PLAN_V1_2"
INTERVAL_CONTRACT_ID = "TIMEZONE_AWARE_RETRIEVAL_INTERVAL_V1_1"

SAFE_OUTPUT_FILENAMES = (
    "validated_bundle_time_integrity_authority_v1.json",
    "validation_time_integrity_authority_v1.json",
    "opaque_identifier_contract_v1.json",
    "retrieval_time_integrity_contract_v1_1.json",
    "validated_retrieval_plan_contract_v1_2.json",
    "validated_memory_bundle_contract_v1_4.json",
    "bundle_fingerprint_contract_v1.json",
    "downstream_bundle_guard_contract_v1_4.json",
    "effective_persistent_memory_contract_v1_4.json",
    "rq2c0_r5_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_R5_VALIDATED_BUNDLE_AND_FINGERPRINT_BINDING.md",
    "RQ2C0_R5_OPAQUE_IDENTIFIER_INTEGRITY.md",
    "RQ2C0_R5_RETRIEVAL_TIME_AND_INTERVAL_CONTRACT.md",
    "RQ2C0_R5_EFFECTIVE_RQ2C1_ENTRY_CONTRACT.md",
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
