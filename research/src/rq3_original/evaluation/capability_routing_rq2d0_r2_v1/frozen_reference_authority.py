"""No-argument loader for the exact D0-R1 contamination authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Mapping

from . import (
    BUNDLE_FILE_SHA256,
    BUNDLE_RECORD_COUNT,
    BUNDLE_RELATIVE_PATH,
    BUNDLE_SIZE_BYTES,
    MANIFEST_FILE_SHA256,
    MANIFEST_RELATIVE_PATH,
    MANIFEST_SIZE_BYTES,
    NORMALISER_CONTRACT_ID,
    PARTITION_SPECS,
    REFERENCE_CONTRACT_ID,
    ROOT,
    SOURCE_RESOLUTION_FILE_SHA256,
    SOURCE_RESOLUTION_RELATIVE_PATH,
    SOURCE_RESOLUTION_SIZE_BYTES,
)
from .exact_reference_validator import (
    ExpectedAuthorityIdentity,
    ExpectedPartition,
    ValidatedAuthorityPayload,
    validate_exact_authority_files,
)


@dataclass(frozen=True)
class FrozenContaminationReferenceAuthorityV1_1:
    manifest_relative_path: str
    manifest_file_sha256: str
    manifest_size_bytes: int
    bundle_relative_path: str
    bundle_file_sha256: str
    bundle_size_bytes: int
    bundle_record_count: int
    source_resolution_relative_path: str
    source_resolution_file_sha256: str
    source_resolution_size_bytes: int
    reference_contract_id: str
    normaliser_contract_id: str
    partition_order: tuple[str, ...]
    partition_counts: tuple[tuple[str, int], ...]
    partition_bundle_commitments: tuple[tuple[str, str], ...]
    authority_commitment: str
    _reference_rows: tuple[Mapping[str, str], ...] = field(repr=False)

    @property
    def reference_rows(self) -> tuple[Mapping[str, str], ...]:
        return self._reference_rows

    def safe_receipt(self) -> dict[str, Any]:
        return {
            "reference_authority_contract_id": self.reference_contract_id,
            "reference_authority_commitment": self.authority_commitment,
            "reference_manifest_relative_path": self.manifest_relative_path,
            "reference_manifest_file_sha256": self.manifest_file_sha256,
            "reference_manifest_size_bytes": self.manifest_size_bytes,
            "reference_bundle_relative_path": self.bundle_relative_path,
            "reference_bundle_file_sha256": self.bundle_file_sha256,
            "reference_bundle_size_bytes": self.bundle_size_bytes,
            "reference_bundle_record_count": self.bundle_record_count,
            "reference_source_resolution_relative_path": (
                self.source_resolution_relative_path
            ),
            "reference_source_resolution_file_sha256": (
                self.source_resolution_file_sha256
            ),
            "reference_source_resolution_size_bytes": (
                self.source_resolution_size_bytes
            ),
            "partition_count": len(self.partition_order),
            "partition_order": list(self.partition_order),
            "partition_counts": dict(self.partition_counts),
            "partition_commitments": dict(self.partition_bundle_commitments),
            "normaliser_contract_id": self.normaliser_contract_id,
        }

    def safe_document(self) -> dict[str, Any]:
        return {
            "schema_version": "frozen-contamination-reference-authority-v1.1",
            "status": "PASS",
            **self.safe_receipt(),
            "manifest_tracked": True,
            "bundle_tracked": False,
            "bundle_ignored": True,
            "source_resolution_tracked": True,
            "all_files_regular_non_symlink": True,
            "reference_text_emitted": False,
            "raw_track_b_accessed": False,
        }


def _git_governance_probe(path: Path) -> tuple[bool, bool]:
    relative = path.relative_to(ROOT).as_posix()
    tracked = (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )
    ignored = (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", relative],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )
    return tracked, ignored


def _expected_identity() -> ExpectedAuthorityIdentity:
    return ExpectedAuthorityIdentity(
        manifest_sha256=MANIFEST_FILE_SHA256,
        manifest_size_bytes=MANIFEST_SIZE_BYTES,
        bundle_sha256=BUNDLE_FILE_SHA256,
        bundle_size_bytes=BUNDLE_SIZE_BYTES,
        bundle_record_count=BUNDLE_RECORD_COUNT,
        source_resolution_sha256=SOURCE_RESOLUTION_FILE_SHA256,
        source_resolution_size_bytes=SOURCE_RESOLUTION_SIZE_BYTES,
        reference_contract_id=REFERENCE_CONTRACT_ID,
        normaliser_contract_id=NORMALISER_CONTRACT_ID,
        partitions=tuple(
            ExpectedPartition(
                partition_id=partition_id,
                record_count=count,
                raw_line_commitment=commitment,
                source_alias=source_alias,
                source_sha256=source_sha256,
            )
            for partition_id, count, commitment, source_alias, source_sha256 in PARTITION_SPECS
        ),
    )


def _from_validated(payload: ValidatedAuthorityPayload) -> FrozenContaminationReferenceAuthorityV1_1:
    return FrozenContaminationReferenceAuthorityV1_1(
        manifest_relative_path=MANIFEST_RELATIVE_PATH,
        manifest_file_sha256=MANIFEST_FILE_SHA256,
        manifest_size_bytes=MANIFEST_SIZE_BYTES,
        bundle_relative_path=BUNDLE_RELATIVE_PATH,
        bundle_file_sha256=BUNDLE_FILE_SHA256,
        bundle_size_bytes=BUNDLE_SIZE_BYTES,
        bundle_record_count=BUNDLE_RECORD_COUNT,
        source_resolution_relative_path=SOURCE_RESOLUTION_RELATIVE_PATH,
        source_resolution_file_sha256=SOURCE_RESOLUTION_FILE_SHA256,
        source_resolution_size_bytes=SOURCE_RESOLUTION_SIZE_BYTES,
        reference_contract_id=REFERENCE_CONTRACT_ID,
        normaliser_contract_id=NORMALISER_CONTRACT_ID,
        partition_order=tuple(row[0] for row in PARTITION_SPECS),
        partition_counts=tuple((row[0], row[1]) for row in PARTITION_SPECS),
        partition_bundle_commitments=tuple((row[0], row[2]) for row in PARTITION_SPECS),
        authority_commitment=payload.authority_commitment,
        _reference_rows=payload.reference_rows,
    )


def load_frozen_contamination_reference_authority_v1_1() -> FrozenContaminationReferenceAuthorityV1_1:
    """Load only the three fixed repository-relative authority paths.

    This real-authority function intentionally accepts no parameters.  It does
    not search for substitutes, consult Downloads, or rebuild source records.
    """

    payload = validate_exact_authority_files(
        manifest_path=ROOT / MANIFEST_RELATIVE_PATH,
        bundle_path=ROOT / BUNDLE_RELATIVE_PATH,
        source_resolution_path=ROOT / SOURCE_RESOLUTION_RELATIVE_PATH,
        expected=_expected_identity(),
        governance_probe=_git_governance_probe,
    )
    return _from_validated(payload)


def exact_reference_binding_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "exact-reference-binding-contract-v1",
        "status": "FROZEN_BEFORE_RAW_TRACK_B_ACCESS",
        "real_loader": "load_frozen_contamination_reference_authority_v1_1",
        "real_loader_parameter_count": 0,
        "caller_supplied_bundle_permitted": False,
        "caller_supplied_manifest_permitted": False,
        "caller_supplied_source_resolution_permitted": False,
        "path_override_permitted": False,
        "same_name_search_permitted": False,
        "source_record_rebuild_permitted": False,
        "byte_exact_identity_required": True,
        "raw_line_partition_commitments_recomputed": True,
        "authority_verification_before_key_or_lock_or_raw_open": True,
        "canonical_partition_commitment_encoding": (
            "partition_id ASCII + NUL + decimal_count ASCII + NUL + "
            "lowercase_sha256_ascii + LF, in frozen order"
        ),
    }
