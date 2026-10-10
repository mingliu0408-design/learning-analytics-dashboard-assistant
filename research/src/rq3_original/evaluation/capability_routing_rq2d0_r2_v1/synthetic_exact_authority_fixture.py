"""Synthetic exact-authority fixtures for substitution and state-machine tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from evaluation.capability_routing_rq2d0_r1_v1 import (
    NORMALISER_CONTRACT_ID,
    REFERENCE_CONTRACT_ID,
    canonical_json_bytes,
    sha256_bytes,
)
from evaluation.capability_routing_rq2d0_r1_v1.contamination_reference_builder import (
    build_bundle,
)
from evaluation.capability_routing_rq2d0_r1_v1.synthetic_prearm_fixture import (
    synthetic_reference_partitions,
    synthetic_source_resolution,
)

from .exact_reference_validator import (
    ExpectedAuthorityIdentity,
    ExpectedPartition,
    validate_exact_authority_files,
)
from .frozen_reference_authority import FrozenContaminationReferenceAuthorityV1_1


@dataclass(frozen=True)
class SyntheticExactAuthorityFixture:
    root: Path
    manifest_path: Path
    bundle_path: Path
    source_resolution_path: Path
    expected: ExpectedAuthorityIdentity
    authority: FrozenContaminationReferenceAuthorityV1_1

    def governance_probe(self, path: Path) -> tuple[bool, bool]:
        if path == self.bundle_path:
            return False, True
        if path in {self.manifest_path, self.source_resolution_path}:
            return True, False
        return False, False


def _probe_for(
    *, manifest_path: Path, bundle_path: Path, source_path: Path
):
    def probe(path: Path) -> tuple[bool, bool]:
        if path == bundle_path:
            return False, True
        if path in {manifest_path, source_path}:
            return True, False
        return False, False

    return probe


def build_synthetic_exact_authority_fixture(
    root: Path, *, query_suffix: str = ""
) -> SyntheticExactAuthorityFixture:
    partitions = synthetic_reference_partitions()
    if query_suffix:
        first = partitions["RQ1_TRAIN"][0]
        partitions["RQ1_TRAIN"][0] = type(first)(
            source_record_identity=first.source_record_identity,
            query=first.query + query_suffix,
            history=first.history,
            family_or_group=first.family_or_group,
        )
    source_resolution: dict[str, Any] = synthetic_source_resolution()
    source_resolution["reference_contract_id"] = REFERENCE_CONTRACT_ID
    bundle, manifest = build_bundle(partitions, source_resolution)

    manifest_path = root / "tracked/manifest.json"
    bundle_path = root / "ignored/reference.jsonl"
    source_path = root / "tracked/source-resolution.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = canonical_json_bytes(manifest)
    source_bytes = canonical_json_bytes(source_resolution)
    manifest_path.write_bytes(manifest_bytes)
    bundle_path.write_bytes(bundle)
    source_path.write_bytes(source_bytes)

    manifest_partitions = manifest["per_partition"]
    expected = ExpectedAuthorityIdentity(
        manifest_sha256=sha256_bytes(manifest_bytes),
        manifest_size_bytes=len(manifest_bytes),
        bundle_sha256=sha256_bytes(bundle),
        bundle_size_bytes=len(bundle),
        bundle_record_count=len(bundle.splitlines()),
        source_resolution_sha256=sha256_bytes(source_bytes),
        source_resolution_size_bytes=len(source_bytes),
        reference_contract_id=REFERENCE_CONTRACT_ID,
        normaliser_contract_id=NORMALISER_CONTRACT_ID,
        partitions=tuple(
            ExpectedPartition(
                partition_id=str(row["partition_id"]),
                record_count=int(row["observed_count"]),
                raw_line_commitment=str(row["partition_bundle_sha256"]),
                source_alias=str(row["source_alias"]),
                source_sha256=str(row["source_sha256"]),
            )
            for row in manifest_partitions
        ),
    )
    probe = _probe_for(
        manifest_path=manifest_path, bundle_path=bundle_path, source_path=source_path
    )
    validated = validate_exact_authority_files(
        manifest_path=manifest_path,
        bundle_path=bundle_path,
        source_resolution_path=source_path,
        expected=expected,
        governance_probe=probe,
    )
    partition_order = tuple(row.partition_id for row in expected.partitions)
    authority = FrozenContaminationReferenceAuthorityV1_1(
        manifest_relative_path="SYNTHETIC_TEST_ONLY/manifest.json",
        manifest_file_sha256=expected.manifest_sha256,
        manifest_size_bytes=expected.manifest_size_bytes,
        bundle_relative_path="SYNTHETIC_TEST_ONLY/reference.jsonl",
        bundle_file_sha256=expected.bundle_sha256,
        bundle_size_bytes=expected.bundle_size_bytes,
        bundle_record_count=expected.bundle_record_count,
        source_resolution_relative_path="SYNTHETIC_TEST_ONLY/source-resolution.json",
        source_resolution_file_sha256=expected.source_resolution_sha256,
        source_resolution_size_bytes=expected.source_resolution_size_bytes,
        reference_contract_id=expected.reference_contract_id,
        normaliser_contract_id=expected.normaliser_contract_id,
        partition_order=partition_order,
        partition_counts=tuple(
            (row.partition_id, row.record_count) for row in expected.partitions
        ),
        partition_bundle_commitments=tuple(
            (row.partition_id, row.raw_line_commitment)
            for row in expected.partitions
        ),
        authority_commitment=validated.authority_commitment,
        _reference_rows=validated.reference_rows,
    )
    return SyntheticExactAuthorityFixture(
        root=root,
        manifest_path=manifest_path,
        bundle_path=bundle_path,
        source_resolution_path=source_path,
        expected=expected,
        authority=authority,
    )


def mutated_receipt_authority(
    authority: FrozenContaminationReferenceAuthorityV1_1,
) -> FrozenContaminationReferenceAuthorityV1_1:
    replacement = (
        "0" * 64 if authority.authority_commitment != "0" * 64 else "1" * 64
    )
    return replace(authority, authority_commitment=replacement)


def synthetically_reserialise_manifest(path: Path) -> bytes:
    value = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(value, ensure_ascii=False, sort_keys=False).encode("utf-8")
