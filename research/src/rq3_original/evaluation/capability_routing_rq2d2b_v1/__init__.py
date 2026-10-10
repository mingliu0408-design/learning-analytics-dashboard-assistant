"""RQ2-D2B source-blinded Track-B Capability Gold freeze constants."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

START_BRANCH = "research/rq2-d2a-track-b-review-agreement"
START_HEAD = "bbcbfb764023730a374e6eb3d0f4dda96e94a14f"
START_PARENT = "5de19246acad54fcceacd59b3325b06ecb68fc5a"
START_TREE_SHA256 = "c04fa35bb454734ad7b328749dfd198eeba144d92306bef7f1e777077e4b2b5c"
TARGET_BRANCH = "research/rq2-d2b-track-b-capability-gold-freeze"
FREEZE_TIMESTAMP = "2026-08-29T16:32:11Z"

D2A_REVIEW_ZIP_NAME = "RQ2_D2A_TRACK_B_REVIEW_AGREEMENT_REVIEW_2026-08-29.zip"
D2A_REVIEW_ZIP_SHA256 = "e6ccc7624a0fe3ddac3312f92583325d68ac4fd6e43c7489722c2930a4165b82"
D2A_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/rq2d2a_output_checksums_v1.sha256"
)
D2A_CHECKSUM_COUNT = 25
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

D2A_CANONICAL_A_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/local_review/canonical/"
    "reviewer_a_track_b_capability_review_v1_canonical.csv"
)
D2A_CANONICAL_A_SHA256 = "520672799dac1f7698bf736cb91d67e3355f8c16880521d7b39d6e0d749a591f"
D2A_CANONICAL_A_SIZE = 31683
D2A_CANONICAL_B_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/local_review/canonical/"
    "reviewer_b_track_b_capability_review_v1_canonical.csv"
)
D2A_CANONICAL_B_SHA256 = "4f5e9bc98bd92adb0538064c5af9860ccdebb59a00182c2aab7462d9c195fc29"
D2A_CANONICAL_B_SIZE = 31385
D2A_BLANK_ADJUDICATION_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/local_adjudication/"
    "rq2d2a_track_b_adjudication_packet_v1.csv"
)
D2A_BLANK_ADJUDICATION_SHA256 = "b68b5b122db6c919af2707e53f0387e8f2c17e692e83aaad5ac2fff84defe7c7"
D2A_BLANK_ADJUDICATION_SIZE = 23002
D2A_DISAGREEMENT_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/track_b_disagreement_manifest_v1.json"
)

PRIMARY_INPUT_PARTS = (
    "RQ2_TRACK_B_HUMAN_ADJUDICATION",
    "ADJUDICATOR_C",
    "rq2d2a_track_b_adjudication_packet_v1_completed.csv",
)
FALLBACK_INPUT_NAME = "rq2d2a_track_b_adjudication_packet_v1_completed(1).csv"
COMPLETED_ADJUDICATION_SHA256 = "aea416027064bda20b167a02d6ba8dd9cc92b51dae10c584e28c096d6ecb33e3"
COMPLETED_ADJUDICATION_SIZE = 32047

LOCAL_ADJUDICATION_ROOT = Path(
    "evaluation/capability_routing_rq2d2b_v1/local_adjudication"
)
ORIGINAL_ADJUDICATION_RELATIVE = (
    LOCAL_ADJUDICATION_ROOT
    / "original"
    / "rq2d2a_track_b_adjudication_packet_v1_completed_original.csv"
)
CANONICAL_ADJUDICATION_RELATIVE = (
    LOCAL_ADJUDICATION_ROOT
    / "canonical"
    / "rq2d2a_track_b_adjudication_packet_v1_canonical.csv"
)
CANONICAL_ADJUDICATION_SHA256 = "60c87ec4c27144519d383ab88b244ade4cdc2e9978bd72c7ab618009b82033fb"
CANONICAL_ADJUDICATION_SIZE = 32073

LABEL_GOLD_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/"
    "track_b_contextual_capability_final_gold_labels_v1.jsonl"
)
LABEL_GOLD_SHA256 = "06df1d02b1e5d11554f8be2be9b0b3daefd5097aacfab4b7822f99e8dd48be7f"
LABEL_GOLD_SIZE = 29626
FULL_GOLD_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/local_gold/"
    "track_b_contextual_capability_final_gold_v1.jsonl"
)
FULL_GOLD_SHA256 = "822ae2ed624416d97a8c36ba6678b620066d8dc703220abc30b3938980c8780e"
FULL_GOLD_SIZE = 52833

GOLD_ALIAS = "TRACK_B_CONTEXTUAL_CAPABILITY_FINAL_GOLD_V1"
GOLD_ROLE = "FINAL_HELDOUT_CAPABILITY_GOLD"
SOURCE_ROLE = "track_b_contextual_final"
GOLD_INCLUSION_STATUS = "TRACK_B_CAPABILITY_FINAL_GOLD"
REVIEW_ZIP_NAME = "RQ2_D2B_TRACK_B_CAPABILITY_GOLD_FREEZE_REVIEW_2026-08-29.zip"

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
GOLD_FIELDS = (
    "case_validity",
    "query_naturalness_1_to_5",
    "context_link_valid",
    "context_sufficient",
    "capability_unambiguous",
    "context_resolution_required",
    *CAPABILITIES,
    "forbidden_capabilities",
)
REVIEWER_FIELDS = (*GOLD_FIELDS, "reviewer_rationale")
ADJUDICATION_HUMAN_FIELDS = (
    *(f"adjudicated_{field}" for field in GOLD_FIELDS),
    "adjudicator_rationale",
    "adjudicator_id",
    "adjudication_date",
)
ADJUDICATION_PACKET_FIELDS = (
    *VISIBLE_FIELDS,
    "disagreement_reasons",
    *(f"reviewer_a_{field}" for field in REVIEWER_FIELDS),
    *(f"reviewer_b_{field}" for field in REVIEWER_FIELDS),
    *ADJUDICATION_HUMAN_FIELDS,
    "query_rewrite_performed",
    "assistant_context_attached",
)
LABEL_GOLD_FIELDS = (
    "review_case_id",
    "source_role",
    "gold_inclusion_status",
    "gold_decision_source",
    *GOLD_FIELDS,
    "query_rewrite_performed",
    "assistant_context_attached",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def canonical_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                dict(row),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows_from_bytes(value: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(value.decode("utf-8-sig"), newline="")))


def csv_rows(path: Path) -> list[dict[str, str]]:
    return csv_rows_from_bytes(path.read_bytes())


def id_set_sha256(values: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(sorted(values)) + "\n").encode("utf-8"))


def ordered_id_sha256(values: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(values) + "\n").encode("utf-8"))


def durable_write(path: Path, value: bytes, *, mode: int = 0o600) -> None:
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


def primary_input_path() -> Path:
    return downloads_path(PRIMARY_INPUT_PARTS[0]) / PRIMARY_INPUT_PARTS[1] / PRIMARY_INPUT_PARTS[2]


def fallback_input_path() -> Path:
    return downloads_path(FALLBACK_INPUT_NAME)


def normalise_forbidden(value: str) -> tuple[str, ...]:
    entries = {item.strip() for item in value.split(";") if item.strip()}
    if not entries <= set(CAPABILITIES):
        raise ValueError("unknown forbidden capability")
    order = {capability: index for index, capability in enumerate(CAPABILITIES)}
    return tuple(sorted(entries, key=order.__getitem__))
