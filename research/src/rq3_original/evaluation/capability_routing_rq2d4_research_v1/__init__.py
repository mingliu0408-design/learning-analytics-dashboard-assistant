"""RQ2-D4 research-only Track-B capability-routing evaluation.

The package is deliberately isolated from production integration.  It binds
the already-frozen B0, B1, P1, metric, and statistical implementations and
persists governed text only below Git-ignored local directories.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d3-r4-terminal-state-fixed-worker-repair"
START_HEAD = "7d9b51f3d5859ca72db704b66fcede636364c94d"
TARGET_BRANCH = "research/rq2-d4-track-b-final-evaluation"

GOLD_BUNDLE_SHA256 = (
    "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5"
)
LABEL_GOLD_SHA256 = (
    "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
)
COMBINED_SOURCE_SHA256 = (
    "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
)
GROUPING_SHA256 = (
    "41bb7a1617b8428bb7c02dadb186ba8650b745cc870fc277bee1b86037fbe35a"
)
STATISTICAL_CONTRACT_SHA256 = (
    "90210630b81d2995db78cbe6d64d4ca07877241e77f2b417b77cc2d9f6d49307"
)
METRIC_IMPLEMENTATION_SHA256 = (
    "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138"
)
C0_INDEX_SHA256 = (
    "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
)
C0_EMBEDDINGS_SHA256 = (
    "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
)
P1_POLICY_SHA256 = (
    "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942"
)
MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
P1_POLICY_ID = "P1_D05_SIGNAL_UNION"

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
METHODS = ("B0", "B1", "P1")
COMPARISONS = ("P1_VS_B1", "B1_VS_B0", "P1_VS_B0")

LABEL_GOLD_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/"
    "track_b_contextual_capability_final_gold_labels_v1.jsonl"
)
COMBINED_SOURCE_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/local_gold/"
    "track_b_contextual_capability_final_gold_v1.jsonl"
)
GROUPING_RELATIVE = Path(
    "evaluation/capability_routing_rq2d3_r2_v1/"
    "track_b_source_blinded_contrast_groups_v1.jsonl"
)
STATISTICAL_CONTRACT_RELATIVE = Path(
    "evaluation/capability_routing_rq2d3_r1_v1/"
    "rq2_final_statistical_contract_v1_1.json"
)
METRIC_IMPLEMENTATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/capability_metrics.py"
)
C0_INDEX_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
)
C0_EMBEDDINGS_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"
)
P1_POLICY_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/rq2b_final_p1_policy_v1.json"
)
MODEL_RELATIVE = Path(
    "semantic_runtime/models/all-mpnet-base-v2/" + MPNET_REVISION
)

LOCAL_RELATIVE = Path("evaluation/capability_routing_rq2d4_research_v1/local")
LOCAL_RESULTS_RELATIVE = Path(
    "evaluation/capability_routing_rq2d4_research_v1/local_results"
)
FEATURE_VIEW_RELATIVE = LOCAL_RELATIVE / "track_b_feature_view_v1.jsonl"
PREDICTION_RELATIVES = {
    method: LOCAL_RELATIVE / f"track_b_{method.lower()}_predictions_v1.jsonl"
    for method in METHODS
}

SAFE_OUTPUT_NAMES = (
    "rq2d4_final_metrics_v1.json",
    "rq2d4_final_comparisons_v1.json",
    "rq2d4_final_error_summary_v1.json",
    "rq2d4_result_freeze_v1.json",
    "rq2d4_runtime_report_v1.json",
    "rq2d4_per_capability_metrics_v1.csv",
    "rq2d4_output_checksums_v1.sha256",
)

OFFLINE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


class RQ2D4Error(RuntimeError):
    """Fail-closed scientific evaluation error."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
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


def regular_non_symlink(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def jsonl_rows_from_bytes(value: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in value.decode("utf-8").splitlines()
        if line.strip()
    ]


def write_new(path: Path, value: bytes, *, mode: int = 0o600) -> str:
    """Write a new evaluation artifact without replacing an earlier result."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if path.exists():
            path.unlink()
        raise
    return sha256_bytes(value)


def yes(value: Any) -> bool:
    if value in (True, "YES"):
        return True
    if value in (False, "NO"):
        return False
    raise ValueError(f"expected frozen YES/NO value, received {value!r}")


def capability_order(values: Iterable[str]) -> list[str]:
    selected = set(values)
    if not selected <= set(CAPABILITIES):
        raise ValueError("unknown capability")
    return [name for name in CAPABILITIES if name in selected]
