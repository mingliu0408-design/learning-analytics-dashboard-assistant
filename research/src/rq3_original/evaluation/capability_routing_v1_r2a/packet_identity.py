"""Resolve and validate only the three authorised completed packet inputs."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_v1_r1c.build_reviewer_packets_v1_3 import (
    REVIEWER_A_SEED,
    REVIEWER_B_SEED,
    _packet_row,
)
from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
)

from . import (
    BLANK_A_SHA256,
    BLANK_B_SHA256,
    COMBINED_BANK_SHA256,
    COMPLETED_B_SHA256,
    CORRECTED_A_SHA256,
    ORIGINAL_A_SHA256,
    R1C_COMBINED_BANK_RELATIVE,
    R1C_COMPLETED_B_RELATIVE,
    R1C_CORRECTED_A_RELATIVE,
    R1C_MAPPING_RELATIVE,
    R1C_ORIGINAL_A_RELATIVE,
    ROOT,
    SOURCE_MAPPING_SHA256,
    id_set_sha256,
    ordered_id_sha256,
    sha256_file,
)


class PacketIdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PacketPaths:
    original_a: Path
    corrected_a: Path
    completed_b: Path
    original_a_source: str
    corrected_a_source: str
    completed_b_source: str


def _is_exact(path: Path, expected_sha256: str) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and sha256_file(path) == expected_sha256
    )


def _resolve_one(
    candidates: Sequence[tuple[Path, str]], expected_sha256: str, label: str
) -> tuple[Path, str]:
    for path, source in candidates:
        if _is_exact(path, expected_sha256):
            return path, source
    raise PacketIdentityError(
        f"BLOCKED_RQ2_A_R2A_REVIEW_PACKET_IDENTITY: {label}"
    )


def resolve_packet_paths(root: Path = ROOT) -> PacketPaths:
    downloads = Path.home() / "Downloads"
    original_a, original_source = _resolve_one(
        (
            (root / R1C_ORIGINAL_A_RELATIVE, "R1C_LOCAL_REVIEW"),
            (downloads / "reviewer_a_capability_review_v1_3(1).csv", "DOWNLOADS_FALLBACK"),
        ),
        ORIGINAL_A_SHA256,
        "original Reviewer A",
    )
    corrected_a, corrected_source = _resolve_one(
        (
            (downloads / "reviewer_a_capability_review_v1_3_corrected_v2.csv", "DOWNLOADS"),
            (root / R1C_CORRECTED_A_RELATIVE, "R1C_LOCAL_REVIEW"),
        ),
        CORRECTED_A_SHA256,
        "corrected Reviewer A",
    )
    completed_b, completed_b_source = _resolve_one(
        (
            (root / R1C_COMPLETED_B_RELATIVE, "R1C_LOCAL_REVIEW"),
            (downloads / "reviewer_b_capability_review_v1_3(1).csv", "DOWNLOADS_FALLBACK"),
        ),
        COMPLETED_B_SHA256,
        "completed Reviewer B",
    )
    return PacketPaths(
        original_a=original_a,
        corrected_a=corrected_a,
        completed_b=completed_b,
        original_a_source=original_source,
        corrected_a_source=corrected_source,
        completed_b_source=completed_b_source,
    )


def read_packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_mapping(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / R1C_MAPPING_RELATIVE
    if not _is_exact(path, SOURCE_MAPPING_SHA256):
        raise PacketIdentityError("source-blinded mapping identity mismatch")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _expected_template_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    combined_path = root / R1C_COMBINED_BANK_RELATIVE
    if not _is_exact(combined_path, COMBINED_BANK_SHA256):
        raise PacketIdentityError("combined calibration bank identity mismatch")
    combined = [
        json.loads(line)
        for line in combined_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mapping = read_mapping(root)
    by_canonical = {
        str(row["canonical_case_id"]): str(row["review_case_id"])
        for row in mapping
    }
    source = [
        _packet_row(row, by_canonical[str(row["canonical_case_id"])])
        for row in combined
    ]
    rows_a = [dict(row) for row in source]
    rows_b = [dict(row) for row in source]
    random.Random(REVIEWER_A_SEED).shuffle(rows_a)
    random.Random(REVIEWER_B_SEED).shuffle(rows_b)
    return rows_a, rows_b


def _assert_packet_shape(
    rows: Sequence[Mapping[str, str]], *, reviewer_id: str, label: str
) -> None:
    expected_fields = (*VISIBLE_FIELDS, *HUMAN_FIELDS)
    if len(rows) != 60 or not rows or tuple(rows[0]) != expected_fields:
        raise PacketIdentityError(f"{label} row/column contract mismatch")
    if len({row["review_case_id"] for row in rows}) != 60:
        raise PacketIdentityError(f"{label} review_case_id uniqueness mismatch")
    if {row["reviewer_id"] for row in rows} != {reviewer_id}:
        raise PacketIdentityError(f"{label} reviewer_id mismatch")
    if sum(row["review_date"] == "2026/8/26" for row in rows) != 60:
        raise PacketIdentityError(f"{label} pre-canonical review_date mismatch")


def _assert_fixed_fields(
    observed: Sequence[Mapping[str, str]],
    expected: Sequence[Mapping[str, Any]],
    label: str,
) -> None:
    if len(observed) != len(expected):
        raise PacketIdentityError(f"{label} template length mismatch")
    for observed_row, expected_row in zip(observed, expected):
        if any(str(observed_row[field]) != str(expected_row[field]) for field in VISIBLE_FIELDS):
            raise PacketIdentityError(f"{label} fixed case fields differ from R1C template")


def validate_packet_identities(root: Path = ROOT) -> tuple[PacketPaths, dict[str, Any]]:
    paths = resolve_packet_paths(root)
    original = read_packet(paths.original_a)
    corrected = read_packet(paths.corrected_a)
    completed_b = read_packet(paths.completed_b)
    _assert_packet_shape(original, reviewer_id="REVIEWER_A", label="original A")
    _assert_packet_shape(corrected, reviewer_id="REVIEWER_A", label="corrected A")
    _assert_packet_shape(completed_b, reviewer_id="REVIEWER_B", label="completed B")
    expected_a, expected_b = _expected_template_rows(root)
    _assert_fixed_fields(original, expected_a, "original A")
    _assert_fixed_fields(corrected, expected_a, "corrected A")
    _assert_fixed_fields(completed_b, expected_b, "completed B")
    ids_a = [row["review_case_id"] for row in corrected]
    ids_b = [row["review_case_id"] for row in completed_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise PacketIdentityError("Reviewer A/B case-set or order contract mismatch")
    return paths, {
        "schema_version": "human-packet-identity-validation-v1",
        "row_count_per_packet": 60,
        "column_count_per_packet": len(VISIBLE_FIELDS) + len(HUMAN_FIELDS),
        "case_set_sha256": id_set_sha256(ids_a),
        "reviewer_a_order_sha256": ordered_id_sha256(ids_a),
        "reviewer_b_order_sha256": ordered_id_sha256(ids_b),
        "original_a": {
            "sha256": ORIGINAL_A_SHA256,
            "size_bytes": paths.original_a.stat().st_size,
            "source": paths.original_a_source,
        },
        "corrected_a": {
            "sha256": CORRECTED_A_SHA256,
            "size_bytes": paths.corrected_a.stat().st_size,
            "source": paths.corrected_a_source,
        },
        "completed_b": {
            "sha256": COMPLETED_B_SHA256,
            "size_bytes": paths.completed_b.stat().st_size,
            "source": paths.completed_b_source,
        },
        "r1c_blank_template_sha256": {
            "reviewer_a": BLANK_A_SHA256,
            "reviewer_b": BLANK_B_SHA256,
        },
        "fixed_case_fields_match_r1c_templates": True,
        "original_inputs_preserved": True,
    }
