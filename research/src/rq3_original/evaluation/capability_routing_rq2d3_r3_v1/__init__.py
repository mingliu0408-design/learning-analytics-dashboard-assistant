"""RQ2-D3-R3 execution-integrity contracts for the future D4 one-shot run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d3-r2-track-b-final-evaluation-harness"
START_HEAD = "45c4e5f5891f0454950a0730eb683877c251d4e2"
START_PARENT = "2542b0b334fcb1234139786a403c7437b69f0b2c"
TARGET_BRANCH = "research/rq2-d3-r3-d4-execution-integrity-repair"

EFFECTIVE_CONTRACT_ID = (
    "RQ2_TRACK_B_B0_B1_P1_FINAL_EVALUATION_GLOBAL_ONE_SHOT_V1_1"
)
SYNTHETIC_CONTRACT_ID = "RQ2_D3_R3_SYNTHETIC_D4_INTEGRITY_V1_1"
GLOBAL_LOCK_SCHEMA = "TRACK_B_FINAL_EVALUATION_GLOBAL_LOCK_V1_1"
PREDICTOR_CONTRACT_ID = "RQ2_TRACK_B_FROZEN_CAPABILITY_PREDICTOR_CORE_V1_1"

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

D2B_GOLD_BUNDLE_SHA256 = (
    "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5"
)
D3_R1_STATISTICAL_SHA256 = (
    "90210630b81d2995db78cbe6d64d4ca07877241e77f2b417b77cc2d9f6d49307"
)
D3_R2_GROUPING_SHA256 = (
    "41bb7a1617b8428bb7c02dadb186ba8650b745cc870fc277bee1b86037fbe35a"
)
METRIC_IMPLEMENTATION_SHA256 = (
    "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138"
)
FULL_TEXT_GOLD_SHA256 = (
    "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
)
FULL_TEXT_GOLD_SIZE = 52833
LABEL_ONLY_GOLD_SHA256 = (
    "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
)
LABEL_ONLY_GOLD_SIZE = 29626


class RQ2D3R3Error(RuntimeError):
    """Fail-closed RQ2-D3-R3 contract error."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    return str(path.relative_to(ROOT))
