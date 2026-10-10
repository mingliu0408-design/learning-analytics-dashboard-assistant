"""Build deterministic, local-only hash records for the contamination authority."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d0_v1.contamination_contract import (
    normalise_query,
    query_history_commitment,
)

from . import (
    NORMALISER_CONTRACT_ID,
    REFERENCE_CONTRACT_ID,
    REFERENCE_PARTITION_COUNTS,
    REFERENCE_TOTAL_COUNT,
    canonical_json_bytes,
    sha256_bytes,
)
from .contamination_reference_source import ReferenceRecord, SPECS


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity_hash(namespace: bytes, value: str) -> str:
    return hashlib.sha256(namespace + b"\x00" + value.encode("utf-8")).hexdigest()


def build_partition_rows(
    partition_id: str, records: Sequence[ReferenceRecord]
) -> list[dict[str, Any]]:
    if partition_id not in REFERENCE_PARTITION_COUNTS:
        raise ValueError("unknown contamination partition")
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {
            "partition_id": partition_id,
            "opaque_reference_id": _identity_hash(
                b"RQ2_CONTAMINATION_REFERENCE_ID_V1",
                f"{partition_id}\x00{record.source_record_identity}",
            ),
            "exact_query_hash": _text_hash(record.query),
            "normalised_query_hash": _text_hash(normalise_query(record.query)),
            "query_history_hash": query_history_commitment(record.query, record.history),
            "source_record_identity_hash": _identity_hash(
                b"RQ2_SOURCE_RECORD_IDENTITY_V1", record.source_record_identity
            ),
        }
        if record.family_or_group:
            row["family_or_group_hash_if_available"] = _identity_hash(
                b"RQ2_FAMILY_OR_GROUP_IDENTITY_V1", record.family_or_group
            )
        rows.append(row)
    return sorted(rows, key=lambda item: item["opaque_reference_id"])


def build_bundle(
    partitions: Mapping[str, Sequence[ReferenceRecord]],
    source_resolution: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    if set(partitions) != set(REFERENCE_PARTITION_COUNTS):
        raise ValueError("complete reference partition set required")
    all_rows: list[dict[str, Any]] = []
    source_by_partition = {
        str(row["partition_id"]): row for row in source_resolution["sources"]
    }
    per_partition: list[dict[str, Any]] = []
    for partition_id, expected_count in REFERENCE_PARTITION_COUNTS.items():
        rows = build_partition_rows(partition_id, partitions[partition_id])
        if len(rows) != expected_count:
            raise ValueError("reference count mismatch")
        payload = b"".join(canonical_json_bytes(row, pretty=False) for row in rows)
        source = source_by_partition[partition_id]
        per_partition.append(
            {
                "partition_id": partition_id,
                "expected_count": expected_count,
                "observed_count": len(rows),
                "source_alias": SPECS[partition_id].source_alias,
                "source_sha256": source["source_sha256"],
                "partition_bundle_sha256": sha256_bytes(payload),
                "unique_exact_hash_count": len({row["exact_query_hash"] for row in rows}),
                "unique_normalised_hash_count": len(
                    {row["normalised_query_hash"] for row in rows}
                ),
                "unique_query_history_hash_count": len(
                    {row["query_history_hash"] for row in rows}
                ),
                "status": "PASS",
            }
        )
        all_rows.extend(rows)
    bundle = b"".join(canonical_json_bytes(row, pretty=False) for row in all_rows)
    manifest = {
        "schema_version": "track-b-contamination-reference-manifest-v1",
        "reference_contract_id": REFERENCE_CONTRACT_ID,
        "normaliser_contract_id": NORMALISER_CONTRACT_ID,
        "status": "PASS",
        "total_reference_records": len(all_rows),
        "bundle_sha256": sha256_bytes(bundle),
        "bundle_size_bytes": len(bundle),
        "per_partition": per_partition,
        "all_eight_partitions_nonempty": True,
        "all_expected_counts_exact": len(all_rows) == REFERENCE_TOTAL_COUNT,
        "local_bundle_tracked": False,
        "local_bundle_in_review_zip": False,
        "reference_text_emitted": False,
        "track_b_accessed": False,
    }
    return bundle, manifest


def parse_bundle_bytes(value: bytes) -> list[dict[str, Any]]:
    import json

    return [json.loads(line) for line in value.decode("utf-8").splitlines() if line]
