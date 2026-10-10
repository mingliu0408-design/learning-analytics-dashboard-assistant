"""Perform the only authorised byte-level completed-packet canonicalisation."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from . import (
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_A_SIZE,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    CANONICAL_B_SIZE,
    ROOT,
    durable_write,
    sha256_bytes,
    sha256_file,
)
from .completed_packet_authority import CompletedPacketPaths


BOM = b"\xef\xbb\xbf"
OLD_DATE = b"2026/8/29"
ISO_DATE = b"2026-08-29"


class CanonicalisationError(RuntimeError):
    pass


def canonicalise_bytes(original: bytes) -> bytes:
    if (
        original.startswith(BOM)
        or original.count(b"\r\n") != 49
        or original.count(b"\n") != 49
        or not original.endswith(b"\r\n")
        or original.count(OLD_DATE) != 48
        or ISO_DATE in original
    ):
        raise CanonicalisationError("BLOCKED_RQ2_D2A_CANONICALISATION_MISMATCH")
    canonical = BOM + original.replace(OLD_DATE, ISO_DATE)
    if (
        canonical.count(ISO_DATE) != 48
        or canonical.count(OLD_DATE)
        or canonical.count(b"\r\n") != 49
        or not canonical.endswith(b"\r\n")
        or canonical[len(BOM) :].replace(ISO_DATE, OLD_DATE) != original
    ):
        raise CanonicalisationError("BLOCKED_RQ2_D2A_CANONICALISATION_MISMATCH")
    return canonical


def _assert_local_boundary(root: Path, relative: Path) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=root, check=False
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    if not ignored or tracked:
        raise CanonicalisationError("canonical packet local-only boundary mismatch")


def canonicalise_packets(
    paths: CompletedPacketPaths, root: Path = ROOT
) -> dict[str, Any]:
    specifications = (
        (
            "reviewer_a",
            paths.original_a,
            CANONICAL_A_RELATIVE,
            CANONICAL_A_SHA256,
            CANONICAL_A_SIZE,
        ),
        (
            "reviewer_b",
            paths.original_b,
            CANONICAL_B_RELATIVE,
            CANONICAL_B_SHA256,
            CANONICAL_B_SIZE,
        ),
    )
    result: dict[str, Any] = {}
    for label, source, relative, expected_sha256, expected_size in specifications:
        original = source.read_bytes()
        canonical = canonicalise_bytes(original)
        if sha256_bytes(canonical) != expected_sha256 or len(canonical) != expected_size:
            raise CanonicalisationError("BLOCKED_RQ2_D2A_CANONICALISATION_MISMATCH")
        destination = root / relative
        durable_write(destination, canonical)
        _assert_local_boundary(root, relative)
        if sha256_file(destination) != expected_sha256 or destination.stat().st_size != expected_size:
            raise CanonicalisationError("BLOCKED_RQ2_D2A_CANONICALISATION_MISMATCH")
        result[label] = {
            "relative_local_path": relative.as_posix(),
            "sha256": expected_sha256,
            "size_bytes": expected_size,
            "input_utf8_bom": False,
            "canonical_utf8_bom": True,
            "bom_bytes_added": 3,
            "old_date_replacement_count": 48,
            "canonical_date_count": 48,
            "crlf_physical_line_count": 49,
            "final_crlf_preserved": True,
            "row_order_changed": False,
            "answer_or_rationale_byte_changed": False,
            "reverse_canonicalisation_byte_identical": True,
            "ignored": True,
            "tracked": False,
        }
    return {
        "schema_version": "track-b-packet-canonicalisation-manifest-v1",
        "stage": "RQ2-D2A",
        "status": "PASS",
        "method": "PREPEND_UTF8_BOM_AND_EXACT_RAW_BYTE_DATE_REPLACEMENT",
        "date_from": "2026/8/29",
        "date_to": "2026-08-29",
        "total_date_replacement_count": 96,
        "csv_reserialisation_used": False,
        "canonical_packets": result,
        "all_other_bytes_unchanged": True,
    }
