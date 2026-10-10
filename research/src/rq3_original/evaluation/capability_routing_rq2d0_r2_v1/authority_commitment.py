"""Canonical combined commitment for the three exact authority files."""

from __future__ import annotations

import hashlib
from typing import Iterable

from . import AUTHORITY_COMMITMENT_DOMAIN


def canonical_partition_commitment_bytes(
    partitions: Iterable[tuple[str, int, str]],
) -> bytes:
    """Encode ordered partition commitments without JSON ambiguity.

    Each record is ``partition_id NUL decimal_count NUL lowercase_hex LF``.
    Partition order is semantically significant and is therefore preserved.
    """

    payload = bytearray()
    seen: set[str] = set()
    for partition_id, count, commitment in partitions:
        if (
            not partition_id
            or partition_id in seen
            or count < 1
            or len(commitment) != 64
            or commitment.lower() != commitment
            or any(ch not in "0123456789abcdef" for ch in commitment)
        ):
            raise ValueError("invalid canonical partition commitment input")
        seen.add(partition_id)
        payload.extend(partition_id.encode("ascii"))
        payload.extend(b"\x00")
        payload.extend(str(count).encode("ascii"))
        payload.extend(b"\x00")
        payload.extend(commitment.encode("ascii"))
        payload.extend(b"\n")
    if not payload:
        raise ValueError("at least one partition commitment is required")
    return bytes(payload)


def reference_authority_commitment(
    *,
    manifest_file_sha256: str,
    bundle_file_sha256: str,
    source_resolution_file_sha256: str,
    ordered_partitions: Iterable[tuple[str, int, str]],
) -> str:
    fields = (
        manifest_file_sha256,
        bundle_file_sha256,
        source_resolution_file_sha256,
    )
    if any(
        len(value) != 64
        or value.lower() != value
        or any(ch not in "0123456789abcdef" for ch in value)
        for value in fields
    ):
        raise ValueError("file commitments must be lowercase SHA-256 hex")
    payload = (
        AUTHORITY_COMMITMENT_DOMAIN
        + fields[0].encode("ascii")
        + b"\x00"
        + fields[1].encode("ascii")
        + b"\x00"
        + fields[2].encode("ascii")
        + b"\x00"
        + canonical_partition_commitment_bytes(ordered_partitions)
    )
    return hashlib.sha256(payload).hexdigest()
