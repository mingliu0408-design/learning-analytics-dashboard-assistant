"""RQ2-C0-R1 persistent-memory contract and controlled-fixture freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
LOCAL_FIXTURE_ROOT = HERE / "local_fixture_bank"
FIXTURE_BANK_PATH = (
    LOCAL_FIXTURE_ROOT / "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)

STARTING_BRANCH = "research/rq2-c0-tool-gate-mechanism-contract"
STARTING_HEAD = "4c611d2a0e84433f408cfb310b5ea39316384f1e"
STARTING_PARENT = "5463ec162c15b62b5c394f221b656f902a609d04"
RESULT_BRANCH = "research/rq2-c0-r1-persistent-memory-contract"
COMMIT_SUBJECT = (
    "rq2-c0-r1: freeze persistent memory contract and mechanism fixtures"
)

RQ2C0_REVIEW_ZIP = (
    Path.home() / "Downloads/RQ2_C0_P2_MECHANISM_CONTRACT_REVIEW_2026-08-26.zip"
)
EXPECTED_RQ2C0_REVIEW_ZIP_SHA256 = (
    "b4006d06d179d29b7e3b0c8e0f01129329d41daf95643a39360b29d6aff15d49"
)
RQ2C0_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/rq2c0_output_checksums_v1.sha256"
)
EXPECTED_RQ2C0_CHECKSUM_COUNT = 29
EXPECTED_P1_POLICY = "P1_D05_SIGNAL_UNION"
EXPECTED_GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)
FIXED_TIMESTAMP = "2026-08-26T12:00:00Z"

FIXTURE_ALIAS = "RQ2_P2_CONTROLLED_MECHANISM_FIXTURE_BANK_V1"
FIXTURE_ROLE = "WHITE_BOX_MECHANISM_TEST_ONLY"
FIXTURE_AUTHORING_METHOD = "CONTRACT_DERIVED_WHITE_BOX_FIXTURE_AUTHORING"

SAFE_OUTPUT_FILENAMES = (
    "rq2c0_r1_scope_authority_v1.json",
    "persistent_learner_memory_schema_v1.json",
    "memory_write_update_contract_v1.json",
    "persistent_memory_retrieval_policy_family_v1.json",
    "memory_admission_conflict_contract_v1.json",
    "controlled_mechanism_fixture_authority_v1.json",
    "controlled_mechanism_fixture_manifest_v1.json",
    "controlled_mechanism_fixture_summary_v1.json",
    "p2_condition_contract_v2.json",
    "persistent_memory_metric_contract_v1.json",
    "mechanism_evaluability_repair_v1.json",
    "rq2c0_r1_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_R1_MEMORY_LITERATURE_SYNTHESIS.md",
    "RQ2C0_R1_PERSISTENT_LEARNER_MEMORY_ARCHITECTURE.md",
    "RQ2C0_R1_MEMORY_WRITE_RETRIEVAL_AND_CONFLICT_POLICY.md",
    "RQ2C0_R1_CONTROLLED_MECHANISM_FIXTURE_PROTOCOL.md",
    "RQ2C0_R1_P2_CONDITIONS_AND_EVALUATION_LIMITS.md",
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
