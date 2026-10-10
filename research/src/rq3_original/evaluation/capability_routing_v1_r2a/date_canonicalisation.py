"""Canonicalise review dates using a byte-only replacement."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from . import (
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    ROOT,
    sha256_bytes,
    sha256_file,
)
from .packet_identity import PacketPaths, validate_packet_identities


OLD_DATE = b"2026/8/26"
ISO_DATE = b"2026-08-26"


class DateCanonicalisationError(RuntimeError):
    pass


def canonicalise_date_bytes(value: bytes) -> bytes:
    if value.count(OLD_DATE) != 60:
        raise DateCanonicalisationError("input must contain exactly 60 old dates")
    if ISO_DATE in value:
        raise DateCanonicalisationError("input already contains canonical date")
    result = value.replace(OLD_DATE, ISO_DATE)
    if result.count(ISO_DATE) != 60 or OLD_DATE in result:
        raise DateCanonicalisationError("date replacement count mismatch")
    if result.replace(ISO_DATE, OLD_DATE) != value:
        raise DateCanonicalisationError("canonicalisation changed non-date bytes")
    return result


def _assert_ignored(root: Path, relative: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()],
        cwd=root,
        check=False,
    )
    if result.returncode:
        raise DateCanonicalisationError(f"canonical packet is not ignored: {relative}")


def write_canonical_packets(
    paths: PacketPaths | None = None, root: Path = ROOT
) -> dict[str, Any]:
    if paths is None:
        paths, _ = validate_packet_identities(root)
    outputs = (
        ("reviewer_a", paths.corrected_a, CANONICAL_A_RELATIVE, CANONICAL_A_SHA256),
        ("reviewer_b", paths.completed_b, CANONICAL_B_RELATIVE, CANONICAL_B_SHA256),
    )
    manifest: dict[str, Any] = {}
    for label, source, relative, expected_sha256 in outputs:
        canonical = canonicalise_date_bytes(source.read_bytes())
        if sha256_bytes(canonical) != expected_sha256:
            raise DateCanonicalisationError(
                "BLOCKED_RQ2_A_R2A_DATE_CANONICALISATION_MISMATCH"
            )
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical)
        _assert_ignored(root, relative)
        if sha256_file(destination) != expected_sha256:
            raise DateCanonicalisationError("persisted canonical packet mismatch")
        manifest[label] = {
            "sha256": expected_sha256,
            "size_bytes": destination.stat().st_size,
            "review_date": "2026-08-26",
            "old_date_replacement_count": 60,
            "non_date_bytes_modified": False,
            "ignored": True,
            "tracked": False,
        }
    return manifest
