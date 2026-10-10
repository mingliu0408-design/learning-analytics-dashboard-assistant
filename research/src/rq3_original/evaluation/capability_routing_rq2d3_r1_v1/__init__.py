"""RQ2-D3-R1 pre-evaluation statistical-contract completion."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d3-track-b-final-evaluation-harness"
START_HEAD = "60730fd6b4dde52ddc0ea3d377bc4fed2eefee56"
START_PARENT = "bbcbfb764023730a374e6eb3d0f4dda96e94a14f"
TARGET_BRANCH = "research/rq2-d3-r1-statistical-contract-completion"

BLOCKER_ZIP_NAME = (
    "RQ2_D3_STATISTICAL_CONTRACT_UNDERSPECIFIED_BLOCKER_REVIEW_2026-08-29.zip"
)
BLOCKER_ZIP_SHA256 = (
    "8f541d3ce821a16cae3cde8f8a221787631355f5530faf18f87c52395e0b35c8"
)
BLOCKER_ZIP_SIZE = 2030
D2B_ZIP_NAME = "RQ2_D2B_TRACK_B_CAPABILITY_GOLD_FREEZE_REVIEW_2026-08-29.zip"
D2B_ZIP_SHA256 = (
    "89b0590923555d788783b623f6ad91c9258f1223ff8cd79a52003569444905a6"
)
D2B_GOLD_BUNDLE_SHA256 = (
    "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5"
)
D2B_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/rq2d2b_output_checksums_v1.sha256"
)
D2B_VALIDATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/rq2d2b_validation_report_v1.json"
)
D2B_MANIFEST_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json"
)
BASE_CONTRACT_RELATIVE = Path(
    "evaluation/capability_routing_rq2d0_v1/rq2_final_statistical_contract_v1.json"
)
BASE_CONTRACT_SHA256 = (
    "60543ca8cf55eb200c567e787c0bcf0fbec8d7341d5e972d8ec091cda9880bf3"
)
BASE_CONTRACT_SIZE = 1435
METRIC_IMPLEMENTATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/capability_metrics.py"
)
METRIC_IMPLEMENTATION_SHA256 = (
    "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138"
)

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
COMPARISONS = ("P1_VS_B1", "B1_VS_B0", "P1_VS_B0")
PRIMARY_COMPARISON = "P1_VS_B1"
SECONDARY_COMPARISONS = ("B1_VS_B0", "P1_VS_B0")
REGISTERED_BOOTSTRAP_METRICS = (
    "SIX_CAPABILITY_MACRO_F1",
    "EXACT_SET_ACCURACY",
    "REQUIRED_CAPABILITY_RECALL",
    "UNNECESSARY_CAPABILITY_RATE",
)
BOOTSTRAP_GROUP_COUNT = 24
CASES_PER_GROUP = 2
BOOTSTRAP_RESAMPLES = 50_000
BOOTSTRAP_SEED = 20260828
SIGN_FLIP_DRAWS = 100_000
SIGN_FLIP_SEED = 20260829
REVIEW_ZIP_NAME = "RQ2_D3_R1_STATISTICAL_CONTRACT_COMPLETION_REVIEW_2026-08-29.zip"


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def durable_write(path: Path, value: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    if path.read_bytes() != value:
        raise RuntimeError(f"durable write reread mismatch: {path.name}")


def downloads_path(name: str) -> Path:
    return Path.home() / "Downloads" / name
