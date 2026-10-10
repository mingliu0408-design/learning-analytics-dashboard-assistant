"""Fail-closed validation for the hash-only reference bundle and manifest."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from . import (
    NORMALISER_CONTRACT_ID,
    REFERENCE_CONTRACT_ID,
    REFERENCE_PARTITION_COUNTS,
    REFERENCE_TOTAL_COUNT,
    sha256_bytes,
)
from .contamination_reference_builder import parse_bundle_bytes
from .contamination_reference_source import SPECS


class ReferenceValidationError(RuntimeError):
    pass


ALLOWED_ROW_FIELDS = {
    "partition_id",
    "opaque_reference_id",
    "exact_query_hash",
    "normalised_query_hash",
    "query_history_hash",
    "source_record_identity_hash",
    "family_or_group_hash_if_available",
}


def validate_reference_bundle(bundle: bytes, manifest: Mapping[str, Any]) -> dict[str, Any]:
    rows = parse_bundle_bytes(bundle)
    if (
        manifest.get("reference_contract_id") != REFERENCE_CONTRACT_ID
        or manifest.get("normaliser_contract_id") != NORMALISER_CONTRACT_ID
        or manifest.get("bundle_sha256") != sha256_bytes(bundle)
        or manifest.get("bundle_size_bytes") != len(bundle)
        or len(rows) != REFERENCE_TOTAL_COUNT
    ):
        raise ReferenceValidationError(
            "BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE"
        )
    counts = Counter(str(row.get("partition_id")) for row in rows)
    if dict(counts) != REFERENCE_PARTITION_COUNTS:
        raise ReferenceValidationError(
            "BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE"
        )
    opaque_ids = [str(row.get("opaque_reference_id") or "") for row in rows]
    if not all(opaque_ids) or len(set(opaque_ids)) != len(opaque_ids):
        raise ReferenceValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    manifest_rows = {row["partition_id"]: row for row in manifest["per_partition"]}
    if set(manifest_rows) != set(REFERENCE_PARTITION_COUNTS):
        raise ReferenceValidationError(
            "BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE"
        )
    for partition_id, expected in REFERENCE_PARTITION_COUNTS.items():
        subset = [row for row in rows if row["partition_id"] == partition_id]
        if (
            len(subset) != expected
            or any(not set(row) <= ALLOWED_ROW_FIELDS for row in subset)
            or any(
                not str(row.get(field) or "")
                for row in subset
                for field in (
                    "exact_query_hash",
                    "normalised_query_hash",
                    "query_history_hash",
                    "source_record_identity_hash",
                )
            )
        ):
            raise ReferenceValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
        for field in (
            "exact_query_hash",
            "normalised_query_hash",
            "query_history_hash",
            "source_record_identity_hash",
        ):
            if len({row[field] for row in subset}) == 1 and expected > 1:
                raise ReferenceValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
        safe = manifest_rows[partition_id]
        if (
            safe["expected_count"] != expected
            or safe["observed_count"] != expected
            or safe["source_alias"] != SPECS[partition_id].source_alias
            or safe["source_sha256"] != SPECS[partition_id].expected_sha256
            or safe["status"] != "PASS"
        ):
            raise ReferenceValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    return {
        "status": "PASS",
        "partition_count": len(counts),
        "record_count": len(rows),
        "unique_opaque_reference_count": len(set(opaque_ids)),
        "all_counts_exact": True,
        "reference_text_present": False,
    }
