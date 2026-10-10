"""Perform the only authorised byte-level adjudication canonicalisation."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from . import (
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    CANONICAL_ADJUDICATION_SIZE,
    ROOT,
    durable_write,
    sha256_bytes,
    sha256_file,
)
from .adjudication_input_authority import AdjudicationInputPaths


BOM = b"\xef\xbb\xbf"
OLD_DATE = b"2026/8/29"
ISO_DATE = b"2026-08-29"
OLD_FALSE = b"FALSE"
CANONICAL_FALSE = b"false"


class AdjudicationCanonicalisationError(RuntimeError):
    pass


def canonicalise_bytes(original: bytes) -> bytes:
    if (
        original.startswith(BOM)
        or original.count(b"\r\n") != 24
        or original.count(b"\n") != 24
        or not original.endswith(b"\r\n")
        or original.count(OLD_DATE) != 23
        or original.count(ISO_DATE) != 0
        or original.count(OLD_FALSE) != 46
        or original.count(CANONICAL_FALSE) != 0
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_CANONICALISATION"
        )
    canonical = BOM + original.replace(OLD_DATE, ISO_DATE).replace(
        OLD_FALSE, CANONICAL_FALSE
    )
    if (
        canonical.count(ISO_DATE) != 23
        or canonical.count(CANONICAL_FALSE) != 46
        or canonical.count(b"\r\n") != 24
        or not canonical.endswith(b"\r\n")
        or canonical[len(BOM) :]
        .replace(ISO_DATE, OLD_DATE)
        .replace(CANONICAL_FALSE, OLD_FALSE)
        != original
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_CANONICALISATION"
        )
    return canonical


def canonicalise_adjudication(
    paths: AdjudicationInputPaths, root: Path = ROOT
) -> dict[str, Any]:
    original = paths.original_copy.read_bytes()
    canonical = canonicalise_bytes(original)
    if (
        sha256_bytes(canonical) != CANONICAL_ADJUDICATION_SHA256
        or len(canonical) != CANONICAL_ADJUDICATION_SIZE
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_CANONICALISATION"
        )
    destination = root / CANONICAL_ADJUDICATION_RELATIVE
    durable_write(destination, canonical)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", CANONICAL_ADJUDICATION_RELATIVE.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", CANONICAL_ADJUDICATION_RELATIVE.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    if (
        not ignored
        or tracked
        or sha256_file(destination) != CANONICAL_ADJUDICATION_SHA256
        or destination.stat().st_size != CANONICAL_ADJUDICATION_SIZE
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_CANONICALISATION"
        )
    return {
        "schema_version": "track-b-adjudication-canonicalisation-manifest-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "method": "PREPEND_UTF8_BOM_THEN_EXACT_DATE_AND_IMMUTABLE_BOOLEAN_REPLACEMENT",
        "csv_reserialisation_used": False,
        "input_sha256": sha256_bytes(original),
        "input_size_bytes": len(original),
        "input_utf8_bom": False,
        "crlf_physical_line_count": 24,
        "final_crlf_preserved": True,
        "date_replacement_count": 23,
        "immutable_boolean_replacement_count": 46,
        "bom_bytes_added": 3,
        "all_other_bytes_unchanged": True,
        "row_order_changed": False,
        "answer_or_rationale_changed": False,
        "reverse_canonicalisation_byte_identical": True,
        "canonical_relative_local_path": CANONICAL_ADJUDICATION_RELATIVE.as_posix(),
        "canonical_sha256": CANONICAL_ADJUDICATION_SHA256,
        "canonical_size_bytes": CANONICAL_ADJUDICATION_SIZE,
        "ignored": True,
        "tracked": False,
        "local_only": True,
    }
