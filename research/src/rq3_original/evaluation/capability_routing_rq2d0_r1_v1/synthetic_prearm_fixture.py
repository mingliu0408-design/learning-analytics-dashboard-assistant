"""Wholly synthetic inputs for D0-R1 contract and failure-path validation."""

from __future__ import annotations

from typing import Any

from . import REFERENCE_PARTITION_COUNTS
from .contamination_reference_source import ReferenceRecord, SPECS


def synthetic_reference_partitions() -> dict[str, list[ReferenceRecord]]:
    return {
        partition: [
            ReferenceRecord(
                source_record_identity=f"SYNTHETIC::{partition}::{index:04d}",
                query=f"Synthetic reference {partition} query {index:04d}",
                history=(
                    []
                    if index % 2 == 0
                    else [{"role": "user", "content": f"Synthetic prior {index:04d}"}]
                ),
                family_or_group=f"SYNTHETIC::{partition}::GROUP::{index // 2:04d}",
            )
            for index in range(count)
        ]
        for partition, count in REFERENCE_PARTITION_COUNTS.items()
    }


def synthetic_source_resolution() -> dict[str, Any]:
    sources = [
        {
            "partition_id": partition,
            "source_alias": SPECS[partition].source_alias,
            "expected_count": count,
            "observed_count": count,
            "source_sha256": SPECS[partition].expected_sha256,
            "source_size_bytes": 1,
            "source_contract_id": SPECS[partition].source_contract_id,
            "source_role": SPECS[partition].source_role,
            "resolution_status": "PASS",
        }
        for partition, count in REFERENCE_PARTITION_COUNTS.items()
    ]
    return {
        "schema_version": "synthetic-reference-source-resolution-v1",
        "status": "PASS",
        "partition_count": 8,
        "total_record_count": sum(REFERENCE_PARTITION_COUNTS.values()),
        "sources": sources,
        "reference_text_emitted": False,
        "track_b_accessed": False,
    }
