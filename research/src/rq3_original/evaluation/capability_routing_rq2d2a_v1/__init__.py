"""RQ2-D2A source-blinded human-review closure constants and safe helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d1-track-b-mapping-packets"
START_HEAD = "5de19246acad54fcceacd59b3325b06ecb68fc5a"
START_PARENT = "d284c390a0000dc383bd160932b5faaa01f8cddb"
START_TREE_SHA256 = "9bcb6ddf013b34acb5e58c70686ee3532201070b7b903d08e23466b2f03c800d"
TARGET_BRANCH = "research/rq2-d2a-track-b-review-agreement"

D1_REVIEW_ZIP_NAME = "RQ2_D1_TRACK_B_MAPPING_PACKET_GENERATION_REVIEW_2026-08-28.zip"
D1_REVIEW_ZIP_SHA256 = "8be2d48a87a2ce0fc275935c2b413932993101a559cb097849647c34231bf602"
D1_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2d1_v1/rq2d1_output_checksums_v1.sha256"
)
D1_CHECKSUM_COUNT = 8
D1_GLOBAL_LOCK_RELATIVE = Path(
    "evaluation/capability_routing_rq2d1_v1/local_control/"
    "TRACK_B_PACKET_GENERATION_GLOBAL_ACCESS_V1_3.json"
)
D1_GLOBAL_LOCK_SHA256 = "0d90be776c210df83e61cff0f7c2ee5eec9408c3f6c20cbea587d75d54b3bd75"
D1_VALIDATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2d1_v1/rq2d1_validation_report_v1.json"
)

COMPLETED_A_NAME = "reviewer_a_track_b_capability_review_v1_completed(2).csv"
COMPLETED_B_NAME = "reviewer_b_track_b_capability_review_v1_completed(2).csv"
COMPLETED_A_SHA256 = "ac3f6e1b5c04207567cc1a25bbf3b547be39ba270b53a88267a2ca7e9cdb9e07"
COMPLETED_B_SHA256 = "4d88f503fbb0e7698b01b10dfeb8984cbc12ba3da96b1c8674c53dad17cac2ec"
COMPLETED_A_SIZE = 31632
COMPLETED_B_SIZE = 31334

D1_LOCAL_PACKET_ROOT = Path("evaluation/capability_routing_rq2d1_v1/local_one_shot")
BLANK_A_RELATIVE = D1_LOCAL_PACKET_ROOT / "reviewer_a_track_b_capability_review_v1.csv"
BLANK_B_RELATIVE = D1_LOCAL_PACKET_ROOT / "reviewer_b_track_b_capability_review_v1.csv"
BLANK_A_SHA256 = "78e4feb6c15e87c89d2a30b6bfa465be2b1fa50eaba1eb6a09a5ee217bf51a86"
BLANK_B_SHA256 = "fec4b3f79e641f346d10a7c11c32136632842dae2b840c3b7fb1c91b2d7299bb"

LOCAL_REVIEW_ROOT = Path("evaluation/capability_routing_rq2d2a_v1/local_review")
LOCAL_ORIGINAL_ROOT = LOCAL_REVIEW_ROOT / "original"
LOCAL_CANONICAL_ROOT = LOCAL_REVIEW_ROOT / "canonical"
ORIGINAL_A_RELATIVE = (
    LOCAL_ORIGINAL_ROOT / "reviewer_a_track_b_capability_review_v1_completed_original.csv"
)
ORIGINAL_B_RELATIVE = (
    LOCAL_ORIGINAL_ROOT / "reviewer_b_track_b_capability_review_v1_completed_original.csv"
)
CANONICAL_A_RELATIVE = (
    LOCAL_CANONICAL_ROOT / "reviewer_a_track_b_capability_review_v1_canonical.csv"
)
CANONICAL_B_RELATIVE = (
    LOCAL_CANONICAL_ROOT / "reviewer_b_track_b_capability_review_v1_canonical.csv"
)
CANONICAL_A_SHA256 = "520672799dac1f7698bf736cb91d67e3355f8c16880521d7b39d6e0d749a591f"
CANONICAL_B_SHA256 = "4f5e9bc98bd92adb0538064c5af9860ccdebb59a00182c2aab7462d9c195fc29"
CANONICAL_A_SIZE = 31683
CANONICAL_B_SIZE = 31385

ADJUDICATION_PACKET_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/local_adjudication/"
    "rq2d2a_track_b_adjudication_packet_v1.csv"
)
REVIEW_ZIP_NAME = "RQ2_D2A_TRACK_B_REVIEW_AGREEMENT_REVIEW_2026-08-29.zip"

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
VISIBLE_FIELDS = (
    "review_case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "capability_definition_reference",
)
PACKET_FIELDS = (
    *VISIBLE_FIELDS,
    "case_validity",
    "query_naturalness_1_to_5",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
    "reviewer_rationale",
    "reviewer_id",
    "review_date",
)
AGREEMENT_FIELDS = (
    "case_validity",
    "query_naturalness_1_to_5",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
)
ADJUDICATION_FIELDS = (
    "adjudicated_case_validity",
    "adjudicated_query_naturalness_1_to_5",
    "adjudicated_context_link_valid",
    "adjudicated_context_sufficient",
    "adjudicated_capability_unambiguous",
    "adjudicated_context_resolution_required",
    *(f"adjudicated_{capability}" for capability in CAPABILITIES),
    "adjudicated_forbidden_capabilities",
    "adjudicator_rationale",
    "adjudicator_id",
    "adjudication_date",
)

EXPECTED_DISAGREEMENT_IDS = (
    "TBV1-02EBA3610400336B",
    "TBV1-0B8F7F36209FB132",
    "TBV1-2B383FF85C408799",
    "TBV1-36BB0400123F4062",
    "TBV1-3B07EED34B324EBC",
    "TBV1-5F68A8806ED76598",
    "TBV1-612FACCA95EAFD65",
    "TBV1-61D85D9DDA87B605",
    "TBV1-6C027EBA1BCE6948",
    "TBV1-77302F0D863B83D5",
    "TBV1-7D0FAB72C42EA85F",
    "TBV1-8C5BC1E4E5612AD4",
    "TBV1-901EAA6E1906DB2E",
    "TBV1-92447C36C38F10C1",
    "TBV1-A6605F869BBD6046",
    "TBV1-B429193E1A4F479F",
    "TBV1-BC7630111C1B25F4",
    "TBV1-CD05C037BF8FF867",
    "TBV1-D2156CD853CCF10D",
    "TBV1-D2E45F1F712299D1",
    "TBV1-D5B69D875E5FB777",
    "TBV1-D7EF69502FD272D6",
    "TBV1-F82BBA108FA9C469",
)
EXPECTED_FIELD_DISAGREEMENTS = {
    "case_validity": 0,
    "query_naturalness_1_to_5": 16,
    "context_link_valid": 0,
    "context_sufficient": 1,
    "capability_unambiguous": 0,
    "context_resolution_required": 6,
    "dashboard_evidence": 1,
    "course_retrieval": 2,
    "episodic_memory": 1,
    "planning": 0,
    "safe_direct_response": 1,
    "clarification": 1,
    "forbidden_capabilities": 5,
}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows_from_bytes(value: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(value.decode("utf-8-sig"), newline="")))


def csv_rows(path: Path) -> list[dict[str, str]]:
    return csv_rows_from_bytes(path.read_bytes())


def ordered_id_sha256(values: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(values) + "\n").encode("utf-8"))


def id_set_sha256(values: Iterable[str]) -> str:
    return ordered_id_sha256(sorted(values))


def durable_write(path: Path, value: bytes, *, mode: int = 0o600) -> None:
    """Atomically persist bytes with file and parent-directory fsync."""

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
        raise RuntimeError(f"durable reread mismatch: {path.name}")


def downloads_path(name: str) -> Path:
    return Path.home() / "Downloads" / name
