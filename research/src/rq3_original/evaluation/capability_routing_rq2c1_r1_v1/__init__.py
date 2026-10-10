"""RQ2-C1-R1 research-only corrected offline P2 evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
LOCAL_ROOT = HERE / "local_artifacts"

STAGE_ID = "RQ2-C1-R1_OFFLINE_P2_CORRECTED_RUN"
ORIGINAL_STAGE_ID = "RQ2-C1_ORIGINAL_OFFLINE_DEVELOPMENT_RUN"
ORIGINAL_DISPOSITION = "SUPERSEDED_FOR_TRACK_B_ENTRY"
ORIGINAL_PRESERVATION = "PRESERVED_AS_HISTORICAL_DEVELOPMENT_RUN"

STARTING_BRANCH = "research/rq2-c1-offline-p2-implementation"
STARTING_HEAD = "717c285af907ab3cd27702d96e5e0d94420f8e54"
STARTING_PARENT = "0baee6a8012d1a526306880c67b0bb671e40c306"
RESULT_BRANCH = "research/rq2-c1-r1-offline-safety-isolation-repair"
COMMIT_SUBJECT = (
    "rq2-c1-r1: repair store lifecycle transaction binding and condition isolation"
)

C1_REVIEW_ZIP = (
    Path.home() / "Downloads/RQ2_C1_OFFLINE_P2_IMPLEMENTATION_REVIEW_2026-08-27.zip"
)
C1_REVIEW_ZIP_SHA256 = (
    "43e606d08af9ecda7092d837df06d3c724147c19a9fd8b49790e368ea42e3857"
)
R5_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R5_VALIDATED_BUNDLE_TIME_INTEGRITY_REVIEW_2026-08-27.zip"
)
R5_REVIEW_ZIP_SHA256 = (
    "4f696dab44d3d09f6580b9a2785964c68f2ee330977975e8d6f6c76f852db31d"
)
REVIEW_ZIP_NAME = "RQ2_C1_R1_OFFLINE_SAFETY_ISOLATION_REPAIR_REVIEW_2026-08-27.zip"

C1_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c1_v1/rq2c1_output_checksums_v1.sha256"
)
R5_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r5_v1/rq2c0_r5_output_checksums_v1.sha256"
)
EXPECTED_C1_CHECKSUM_COUNT = 42
EXPECTED_R5_CHECKSUM_COUNT = 26
EXPECTED_R5_CHECKSUM_SHA256 = (
    "71103671d9e36060cc5a439846a86e91db75e2e27c5d3f70afaa1e4e60d61bbd"
)

FIXTURE_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
    "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)
EXPECTED_FIXTURE_SHA256 = (
    "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
)
EXPECTED_FIXTURE_SIZE = 24163
EXPECTED_FIXTURE_COUNT = 28

P1_POLICY_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/rq2b_final_p1_policy_v1.json"
)
EXPECTED_P1_POLICY_SHA256 = (
    "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942"
)
P1_POLICY_ID = "P1_D05_SIGNAL_UNION"
GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)

CONDITION_IDS = (
    "P1_BASE",
    "P2_RAG_ONLY",
    "P2_SESSION_STATE_ONLY",
    "P2_PERSISTENT_MEMORY_ONLY",
    "P2_FULL",
)
RAG_ENABLED_CONDITIONS = frozenset({"P2_RAG_ONLY", "P2_FULL"})
SESSION_ENABLED_CONDITIONS = frozenset({"P2_SESSION_STATE_ONLY", "P2_FULL"})
PERSISTENT_ENABLED_CONDITIONS = frozenset(
    {"P2_PERSISTENT_MEMORY_ONLY", "P2_FULL"}
)
PERSISTENT_POLICY_IDS = (
    "PMR_KW_LEGACY",
    "PMR_DENSE_ONLY",
    "PMR_HYBRID_TYPE_TEMPORAL",
    "PMR_HYBRID_STATE_AWARE",
)
PRIMARY_PERSISTENT_POLICY = "PMR_HYBRID_STATE_AWARE"
MEMORY_TYPES = (
    "GOAL",
    "PLAN",
    "CONSTRAINT",
    "PREFERENCE",
    "CORRECTION",
    "COMPLETION",
    "REFERENCED_ITEM",
    "LEARNING_EVENT",
)

ORIGINAL_C1_TRACKED_FILE_COUNT = 43
ORIGINAL_C1_TRACKED_MANIFEST_SHA256 = (
    "132b61821ebc3838b2993d47a381bcea762b5913534decaac8d776ffb4b95d44"
)
ORIGINAL_C1_DOCS = (
    "docs/thesis_mainline/rq2/RQ2C1_DUAL_GATED_RAG_RESULTS.md",
    "docs/thesis_mainline/rq2/RQ2C1_LIMITATIONS_AND_FAILURE_ANALYSIS.md",
    "docs/thesis_mainline/rq2/RQ2C1_OFFLINE_P2_IMPLEMENTATION_PROTOCOL.md",
    "docs/thesis_mainline/rq2/RQ2C1_P2_CONDITION_COMPARISON.md",
    "docs/thesis_mainline/rq2/RQ2C1_SESSION_STATE_AND_PERSISTENT_MEMORY_RESULTS.md",
)

SAFE_JSON_FILENAMES = (
    "rq2c1_r1_starting_preflight_v1.json",
    "rq2c1_r1_store_lifecycle_contract_v1_1.json",
    "rq2c1_r1_execution_context_contract_v1_1.json",
    "rq2c1_r1_rag_condition_isolation_v1.json",
    "rq2c1_r1_correction_target_contract_v1.json",
    "rq2c1_r1_runtime_safety_results_v1.json",
    "rq2c1_r1_corrected_rag_results_v1.json",
    "rq2c1_r1_corrected_memory_results_v1.json",
    "rq2c1_r1_corrected_session_results_v1.json",
    "rq2c1_r1_corrected_condition_results_v1.json",
    "rq2c1_r1_authentic_descriptive_results_v1.json",
    "rq2c1_r1_context_missing_diagnostic_v1.json",
    "rq2c1_r1_original_vs_corrected_delta_v1.json",
    "rq2c1_r1_validation_report_v1.json",
)
DOC_FILENAMES = (
    "RQ2C1_R1_STORE_LIFECYCLE_AND_TOMBSTONE_SAFETY.md",
    "RQ2C1_R1_EXECUTION_CONTEXT_TRANSACTION_BINDING.md",
    "RQ2C1_R1_CONDITION_ISOLATION_AND_CORRECTED_RESULTS.md",
    "RQ2C1_R1_LIMITATIONS_AND_TRACK_B_ENTRY_DECISION.md",
)


def canonical_json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    separators = None if pretty else (",", ":")
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=True,
            separators=separators,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Mapping[str, Any] | Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join(canonical_json_bytes(value, pretty=False) for value in values)
    )


class RQ2C1R1Error(RuntimeError):
    """Base fail-closed error for the corrected research stage."""
