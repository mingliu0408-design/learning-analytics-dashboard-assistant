"""RQ2-D3-R2 source-blinded grouping and D4 harness freeze."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d3-r1-statistical-contract-completion"
START_HEAD = "2542b0b334fcb1234139786a403c7437b69f0b2c"
START_PARENT = "60730fd6b4dde52ddc0ea3d377bc4fed2eefee56"
EMPTY_D3_BRANCH = "research/rq2-d3-track-b-final-evaluation-harness"
TARGET_BRANCH = "research/rq2-d3-r2-track-b-final-evaluation-harness"

R1_REVIEW_ZIP_NAMES = (
    "RQ2_D3_R1_STATISTICAL_CONTRACT_COMPLETION_REVIEW_2026-08-29.zip",
    "RQ2_D3_R1_STATISTICAL_CONTRACT_COMPLETION_REVIEW_2026-08-29 (2).zip",
)
R1_REVIEW_ZIP_SHA256 = "767628838ca221435f0cdc8097755185953d141ba64015b4f17d54d9050bc229"
R1_REVIEW_ZIP_SIZE = 41604
R1_REVIEW_ZIP_MEMBERS = 24
D2B_REVIEW_ZIP_NAME = "RQ2_D2B_TRACK_B_CAPABILITY_GOLD_FREEZE_REVIEW_2026-08-29.zip"
D2B_REVIEW_ZIP_SHA256 = "89b0590923555d788783b623f6ad91c9258f1223ff8cd79a52003569444905a6"
GOLD_BUNDLE_SHA256 = "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5"
LABEL_ONLY_GOLD_SHA256 = "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
FULL_TEXT_GOLD_SHA256 = "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
FULL_TEXT_GOLD_SIZE = 52833

EFFECTIVE_STATISTICAL_CONTRACT_RELATIVE = Path(
    "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json"
)
EFFECTIVE_STATISTICAL_CONTRACT_SHA256 = "90210630b81d2995db78cbe6d64d4ca07877241e77f2b417b77cc2d9f6d49307"
ORIGINAL_STATISTICAL_CONTRACT_RELATIVE = Path(
    "evaluation/capability_routing_rq2d0_v1/rq2_final_statistical_contract_v1.json"
)
ORIGINAL_STATISTICAL_CONTRACT_SHA256 = "60543ca8cf55eb200c567e787c0bcf0fbec8d7341d5e972d8ec091cda9880bf3"
METRIC_IMPLEMENTATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/capability_metrics.py"
)
METRIC_IMPLEMENTATION_SHA256 = "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138"

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
METHOD_IDS = ("B0", "B1", "P1")
COMPARISONS = ("P1_VS_B1", "B1_VS_B0", "P1_VS_B0")
PRIMARY_COMPARISON = "P1_VS_B1"
SECONDARY_COMPARISONS = ("B1_VS_B0", "P1_VS_B0")

REVIEW_ZIP_NAME = "RQ2_D3_R2_TRACK_B_FINAL_EVALUATION_HARNESS_REVIEW_2026-08-29.zip"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
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


def utf8_key(value: str) -> bytes:
    return value.encode("utf-8")


def downloads_path(name: str) -> Path:
    return Path.home() / "Downloads" / name
