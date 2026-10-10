"""RQ2-C1 research-only offline P2 mechanism implementation and evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
LOCAL_ROOT = HERE / "local_artifacts"

STARTING_BRANCH = "research/rq2-c0-r5-validated-bundle-time-integrity-repair"
STARTING_HEAD = "0baee6a8012d1a526306880c67b0bb671e40c306"
STARTING_PARENT = "4cb306a4fa5268b647f5b0e0df051a08c6381e17"
RESULT_BRANCH = "research/rq2-c1-offline-p2-implementation"
COMMIT_SUBJECT = "rq2-c1: implement and evaluate offline p2 tool gates"

R5_REVIEW_ZIP = (
    Path.home()
    / "Downloads/RQ2_C0_R5_VALIDATED_BUNDLE_TIME_INTEGRITY_REVIEW_2026-08-27.zip"
)
EXPECTED_R5_REVIEW_ZIP_SHA256 = (
    "4f696dab44d3d09f6580b9a2785964c68f2ee330977975e8d6f6c76f852db31d"
)
REVIEW_ZIP_NAME = "RQ2_C1_OFFLINE_P2_IMPLEMENTATION_REVIEW_2026-08-27.zip"

EXPECTED_CHECKSUM_MANIFESTS = {
    "RQ2B": (
        Path("evaluation/capability_routing_rq2b_v1/rq2b_output_checksums_v1.sha256"),
        36,
        "8c25bd72d531a33a352b0a378bfbbf2b0d6180a9f35d8166a7128d5c3c5f95e4",
    ),
    "R2": (
        Path("evaluation/capability_routing_rq2c0_r2_v1/rq2c0_r2_output_checksums_v1.sha256"),
        36,
        "55ef90d458090318452895d9cdc3f192cddd94e2227843412c18984d184df991",
    ),
    "R3": (
        Path("evaluation/capability_routing_rq2c0_r3_v1/rq2c0_r3_output_checksums_v1.sha256"),
        18,
        "eadf625b702d0493559d1dd1e1b64859b45f00644d83660a2fb1652d6bd9bd9a",
    ),
    "R4": (
        Path("evaluation/capability_routing_rq2c0_r4_v1/rq2c0_r4_output_checksums_v1.sha256"),
        22,
        "b5f9357ef6b9a247d10b941fbf79e0afa97c7754545e238a45e254aa07d69161",
    ),
    "R5": (
        Path("evaluation/capability_routing_rq2c0_r5_v1/rq2c0_r5_output_checksums_v1.sha256"),
        26,
        "71103671d9e36060cc5a439846a86e91db75e2e27c5d3f70afaa1e4e60d61bbd",
    ),
}

FIXTURE_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
    "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
)
EXPECTED_FIXTURE_SHA256 = (
    "eb2210162a810a4e733af03218117f783a28ca8d52214231ae4fcd20cc956c5e"
)
EXPECTED_FIXTURE_SIZE = 24163
EXPECTED_FIXTURE_COUNT = 28

GOLD_INPUTS = {
    "authentic": (
        Path(
            "evaluation/capability_routing_v1_r2b/local_gold/"
            "authentic_codebook_calibration_gold_v1.jsonl"
        ),
        "96e23f1131c14e5fb627d711a19295594a56bd3daaaef4cdf0ebce71a7af0346",
        22,
    ),
    "synthetic": (
        Path(
            "evaluation/capability_routing_v1_r2b/local_gold/"
            "synthetic_coverage_stress_gold_v1.jsonl"
        ),
        "9e01b400a6daf9fed13e6cca2bdfe2d714785741b34f2266bbf6c36e8ca08399",
        35,
    ),
    "context_missing": (
        Path(
            "evaluation/capability_routing_v1_r2b/local_gold/"
            "authentic_context_missing_qualitative_registry_v1.jsonl"
        ),
        "2f89ccaec37b890ec97a415b76169996d2ae0a6d8f20ebb910410f1c5801c412",
        3,
    ),
    "combined": (
        Path(
            "evaluation/capability_routing_v1_r2b/local_gold/"
            "combined_capability_development_gold_v1.jsonl"
        ),
        "7ce41b4c6691cdcbfe16bf5669b1fd00fe98eca6eb3ec792e4b609aa47be8541",
        57,
    ),
}

LOCAL_LEDGER_INPUTS = {
    "p1_synthetic": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
            "synthetic_P1_D05_SIGNAL_UNION.jsonl"
        ),
        "75ab3d6c1ff4d58b652d5b089ff6f2b289ada756cfc4640cb1cc2df8040916ae",
    ),
    "p1_authentic": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
            "authentic_final_policy_v1.jsonl"
        ),
        "070c034bf8de35f6dd9465e1a858916c6fc39dfeffaecbfd16ceed10cff7951f",
    ),
    "p1_context_missing": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
            "registry_final_policy_v1.jsonl"
        ),
        "82a42f1b3a48c10efe8a193ad273560c5141fc6a3e542219f8a8efcfff453e4e",
    ),
    "context_envelopes": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/envelopes/"
            "context_envelopes_v1.jsonl"
        ),
        "63a458712cfd6cf16e60d114a601617168703919fd5e8cc5d2207ae9d860a6a0",
    ),
    "c0_score_vectors": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/c0_score_vectors/"
            "c0_full_score_vectors_v1.jsonl"
        ),
        "0f418a12c3a5f1a0fcbf473ae718022ab3d7a4efeca52acc739b240c36629342",
    ),
    "metric_join": (
        Path(
            "evaluation/capability_routing_rq2b_v1/local_artifacts/error_ledgers/"
            "metric_join_rows_v1.json"
        ),
        "497919bf72d32eb23666ca989de748b201a75aaf4f2c7ba2c8527fe7615bd1a9",
    ),
}

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
C0_INDEX_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
)
C0_INDEX_SHA256 = (
    "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
)
C0_EMBEDDINGS_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"
)
C0_EMBEDDINGS_SHA256 = (
    "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
)
MODEL_RELATIVE = Path(
    "semantic_runtime/models/all-mpnet-base-v2/"
    "e8c3b32edf5434bc2275fc9bab85f82640a19130"
)
MODEL_REPO_ID = "sentence-transformers/all-mpnet-base-v2"
MODEL_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"

PERSISTENT_POLICY_IDS = (
    "PMR_KW_LEGACY",
    "PMR_DENSE_ONLY",
    "PMR_HYBRID_TYPE_TEMPORAL",
    "PMR_HYBRID_STATE_AWARE",
)
PRIMARY_PERSISTENT_POLICY = "PMR_HYBRID_STATE_AWARE"
EFFECTIVE_RETRIEVAL = "PMR_HYBRID_STATE_AWARE_V1_1"
EFFECTIVE_ADMISSION = "MEMORY_ADMISSION_V1_1"
SESSION_POLICY_IDS = (
    "M0_P1_ONLY",
    "M1_RESOLVED_STATE_DEPENDENCY",
    "M2_EXPLICIT_MEMORY_NEED_WITH_STATE",
)
CONDITION_IDS = (
    "P1_BASE",
    "P2_RAG_ONLY",
    "P2_SESSION_STATE_ONLY",
    "P2_PERSISTENT_MEMORY_ONLY",
    "P2_FULL",
)
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

EXPECTED_HISTORY = {
    "RQ2B": (32, "905ea5297406ed68e19d463492d7077c711871c7f698e9d58a5f40b08ffd835c"),
    "R2": (31, "be03ff16f50155a4e03134cb325670d6844c46815d933bd329a7800aefbc4bce"),
    "R3": (16, "9542c583ad78dca823f1e77887f60131c38d79e34de9cf358ed5ebb9a45cdf7e"),
    "R4": (20, "bb14034de35993990853e50bb4ccd86016acccfe0c300a05a761b1e8d9f748e4"),
    "R5": (23, "495b66828a57c35cb8e3212f29ff00e7bec504ec0af45a0c51527aa37296dd74"),
}
EXPECTED_PROTECTED_COUNT = 571
EXPECTED_PROTECTED_SHA256 = (
    "3006663fe123602a69375175e5dc3fafbf59a0c80df11aab69888b10f78d5943"
)
ORIGINAL_GITIGNORE_SHA256 = (
    "342b1a7d30c8e35c8b0640561f0c8c4fc52ec0a671ca96b5a3e511de9100882d"
)

LOCAL_SUBDIRECTORIES = (
    "fixture_runs",
    "store_events",
    "store_snapshots",
    "private_payloads",
    "memory_embeddings",
    "query_embeddings",
    "retrieval_traces",
    "admission_traces",
    "rag_traces",
    "session_state_traces",
    "condition_predictions",
    "error_ledgers",
)

SAFE_JSON_FILENAMES = (
    "rq2c1_starting_preflight_v1.json",
    "rq2c1_runtime_preflight_v1.json",
    "offline_memory_store_contract_v1.json",
    "store_snapshot_and_transaction_contract_v1.json",
    "rq2c1_rag_execution_results_v1.json",
    "rq2c1_memory_write_update_results_v1.json",
    "rq2c1_persistent_policy_comparison_v1.json",
    "rq2c1_session_policy_oof_results_v1.json",
    "rq2c1_final_session_policy_v1.json",
    "rq2c1_controlled_condition_results_v1.json",
    "rq2c1_synthetic_session_results_v1.json",
    "rq2c1_authentic_descriptive_results_v1.json",
    "rq2c1_context_missing_diagnostic_v1.json",
    "rq2c1_hard_safety_validation_v1.json",
    "rq2c1_error_analysis_v1.json",
    "rq2c1_validation_report_v1.json",
)
DOC_FILENAMES = (
    "RQ2C1_OFFLINE_P2_IMPLEMENTATION_PROTOCOL.md",
    "RQ2C1_DUAL_GATED_RAG_RESULTS.md",
    "RQ2C1_SESSION_STATE_AND_PERSISTENT_MEMORY_RESULTS.md",
    "RQ2C1_P2_CONDITION_COMPARISON.md",
    "RQ2C1_LIMITATIONS_AND_FAILURE_ANALYSIS.md",
)


class RQ2C1Error(RuntimeError):
    """Fail-closed RQ2-C1 implementation or governance failure."""


def canonical_json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    options = {
        "sort_keys": True,
        "ensure_ascii": False,
        "allow_nan": False,
    }
    if pretty:
        text = json.dumps(value, indent=2, **options) + "\n"
    else:
        text = json.dumps(value, separators=(",", ":"), **options)
    return text.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical_json_bytes(row, pretty=False) + b"\n" for row in rows))


def safe_distribution(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))
