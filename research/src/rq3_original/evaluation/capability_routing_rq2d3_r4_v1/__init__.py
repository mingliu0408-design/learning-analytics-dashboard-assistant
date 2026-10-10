"""RQ2-D3-R4 terminal, fixed-authority D4 v1.2 contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

START_BRANCH = "research/rq2-d3-r3-d4-execution-integrity-repair"
START_HEAD = "9a9bc809fbe55392637ef25d7030eaeea4c1c492"
START_PARENT = "45c4e5f5891f0454950a0730eb683877c251d4e2"
TARGET_BRANCH = "research/rq2-d3-r4-terminal-state-fixed-worker-repair"

EFFECTIVE_CONTRACT_ID = "RQ2_TRACK_B_B0_B1_P1_FINAL_EVALUATION_GLOBAL_ONE_SHOT_V1_2"
SYNTHETIC_CONTRACT_ID = "RQ2_D3_R4_SYNTHETIC_INTEGRITY_V1_2"
SENTINEL_SCHEMA = "TRACK_B_FINAL_EVALUATION_IMMUTABLE_RESERVATION_V1_2"
STATE_SCHEMA = "TRACK_B_FINAL_EVALUATION_EXECUTION_STATE_V1_2"
PARENT_RECEIPT_SCHEMA = "TRACK_B_FINAL_EVALUATION_PARENT_EXECUTION_RECEIPT_V1_2"

D2B_GOLD_BUNDLE_SHA256 = "5c2ee1722594e9e3d4fb40cf5e21ef9a6dc6a833f2704191c9b3fd056ad92fc5"
D3_R1_STATISTICAL_SHA256 = "90210630b81d2995db78cbe6d64d4ca07877241e77f2b417b77cc2d9f6d49307"
D3_R2_GROUPING_SHA256 = "41bb7a1617b8428bb7c02dadb186ba8650b745cc870fc277bee1b86037fbe35a"
D3_R3_CHECKSUM_MANIFEST_SHA256 = "5bd6958120a2cb8a3d70c2b750eb3c1755471d6820d864c9195eede77f30ee6c"
METRIC_IMPLEMENTATION_SHA256 = "697f8f84d8658275e8034da4e24839d3dca9f40a8e7f3409b0f659ba55b8b138"
COMBINED_SHA256 = "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
COMBINED_SIZE = 52833
LABEL_SHA256 = "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
LABEL_SIZE = 29626
GROUPING_SIZE = 4176
RECORD_COUNT = 48
GROUP_COUNT = 24

C0_INDEX_SHA256 = "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
C0_EMBEDDINGS_SHA256 = "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
P1_POLICY = "P1_D05_SIGNAL_UNION"
P1_POLICY_SHA256 = "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942"

METHODS = ("B0", "B1", "P1")
CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)


class RQ2D3R4Error(RuntimeError):
    """Fail-closed RQ2-D3-R4 error."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) for row in rows)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
