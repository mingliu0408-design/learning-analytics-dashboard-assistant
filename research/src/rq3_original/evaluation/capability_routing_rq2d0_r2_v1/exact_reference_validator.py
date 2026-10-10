"""Byte-exact validation primitives for the frozen contamination authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Callable, Mapping, Sequence

from . import canonical_json_bytes
from .authority_commitment import reference_authority_commitment


class ExactReferenceAuthorityError(RuntimeError):
    """Fail-closed exact-authority validation error."""


GovernanceProbe = Callable[[Path], tuple[bool, bool]]


@dataclass(frozen=True)
class ExpectedPartition:
    partition_id: str
    record_count: int
    raw_line_commitment: str
    source_alias: str
    source_sha256: str


@dataclass(frozen=True)
class ExpectedAuthorityIdentity:
    manifest_sha256: str
    manifest_size_bytes: int
    bundle_sha256: str
    bundle_size_bytes: int
    bundle_record_count: int
    source_resolution_sha256: str
    source_resolution_size_bytes: int
    reference_contract_id: str
    normaliser_contract_id: str
    partitions: tuple[ExpectedPartition, ...]


@dataclass(frozen=True)
class ValidatedAuthorityPayload:
    manifest: Mapping[str, Any]
    source_resolution: Mapping[str, Any]
    reference_rows: tuple[Mapping[str, str], ...]
    authority_commitment: str


_REQUIRED_ROW_FIELDS = frozenset(
    {
        "partition_id",
        "opaque_reference_id",
        "exact_query_hash",
        "normalised_query_hash",
        "query_history_hash",
        "source_record_identity_hash",
    }
)
_OPTIONAL_ROW_FIELDS = frozenset({"family_or_group_hash_if_available"})
_HASH_FIELDS = (
    "opaque_reference_id",
    "exact_query_hash",
    "normalised_query_hash",
    "query_history_hash",
    "source_record_identity_hash",
)


def _fail(detail: str) -> None:
    raise ExactReferenceAuthorityError(
        f"BLOCKED_RQ2_D0_R2_EXACT_REFERENCE_AUTHORITY:{detail}"
    )


def _is_sha256(value: object) -> bool:
    text = str(value)
    return (
        len(text) == 64
        and text == text.lower()
        and all(ch in "0123456789abcdef" for ch in text)
    )


def _read_regular_non_symlink(path: Path, *, role: str) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError:
        _fail(f"{role}_missing")
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        _fail(f"{role}_not_regular_non_symlink")
    try:
        return path.read_bytes()
    except OSError:
        _fail(f"{role}_unreadable")
    raise AssertionError("unreachable")


def _assert_file_identity(
    payload: bytes, *, expected_sha256: str, expected_size: int, role: str
) -> None:
    if len(payload) != expected_size:
        _fail(f"{role}_size_mismatch")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        _fail(f"{role}_sha256_mismatch")


def _parse_json(payload: bytes, *, role: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(f"{role}_invalid_json")
    if not isinstance(value, dict):
        _fail(f"{role}_not_object")
    return value


def _validate_governance(
    *,
    manifest_path: Path,
    bundle_path: Path,
    source_resolution_path: Path,
    governance_probe: GovernanceProbe,
) -> None:
    manifest_tracked, manifest_ignored = governance_probe(manifest_path)
    bundle_tracked, bundle_ignored = governance_probe(bundle_path)
    source_tracked, source_ignored = governance_probe(source_resolution_path)
    if not manifest_tracked or manifest_ignored:
        _fail("manifest_tracking_mismatch")
    if bundle_tracked or not bundle_ignored:
        _fail("bundle_tracking_mismatch")
    if not source_tracked or source_ignored:
        _fail("source_resolution_tracking_mismatch")


def _validate_bundle_lines(
    payload: bytes, expected: ExpectedAuthorityIdentity
) -> tuple[tuple[Mapping[str, str], ...], tuple[tuple[str, int, str], ...]]:
    if not payload.endswith(b"\n"):
        _fail("bundle_final_lf_missing")
    lines = payload.splitlines(keepends=True)
    if len(lines) != expected.bundle_record_count or any(
        not line or line == b"\n" or not line.endswith(b"\n") for line in lines
    ):
        _fail("bundle_line_count_or_blank_line")
    rows: list[Mapping[str, str]] = []
    for line in lines:
        if b"\r" in line:
            _fail("bundle_non_lf_line_ending")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _fail("bundle_invalid_json_line")
        if not isinstance(value, dict):
            _fail("bundle_row_not_object")
        fields = frozenset(value)
        if not _REQUIRED_ROW_FIELDS <= fields or not fields <= (
            _REQUIRED_ROW_FIELDS | _OPTIONAL_ROW_FIELDS
        ):
            _fail("bundle_row_field_set_mismatch")
        if line != canonical_json_bytes(value, pretty=False):
            _fail("bundle_row_not_canonical_single_line_json")
        if any(not _is_sha256(value.get(field)) for field in _HASH_FIELDS):
            _fail("bundle_required_hash_invalid")
        group = value.get("family_or_group_hash_if_available")
        if group is not None and not _is_sha256(group):
            _fail("bundle_group_hash_invalid")
        rows.append({str(k): str(v) for k, v in value.items()})

    ordered_commitments: list[tuple[str, int, str]] = []
    offset = 0
    all_opaque_ids: list[str] = []
    for partition in expected.partitions:
        end = offset + partition.record_count
        partition_rows = rows[offset:end]
        partition_lines = lines[offset:end]
        if len(partition_rows) != partition.record_count or any(
            row.get("partition_id") != partition.partition_id
            for row in partition_rows
        ):
            _fail(f"partition_order_or_count:{partition.partition_id}")
        opaque_ids = [row["opaque_reference_id"] for row in partition_rows]
        if opaque_ids != sorted(opaque_ids) or any(
            left >= right for left, right in zip(opaque_ids, opaque_ids[1:])
        ):
            _fail(f"opaque_id_order:{partition.partition_id}")
        all_opaque_ids.extend(opaque_ids)
        commitment = hashlib.sha256(b"".join(partition_lines)).hexdigest()
        if commitment != partition.raw_line_commitment:
            _fail(f"partition_commitment:{partition.partition_id}")
        ordered_commitments.append(
            (partition.partition_id, partition.record_count, commitment)
        )
        offset = end
    if offset != len(rows):
        _fail("bundle_unassigned_rows")
    if len(set(all_opaque_ids)) != len(all_opaque_ids):
        _fail("opaque_reference_id_not_globally_unique")
    return tuple(rows), tuple(ordered_commitments)


def _validate_safe_manifests(
    manifest: Mapping[str, Any],
    source_resolution: Mapping[str, Any],
    expected: ExpectedAuthorityIdentity,
) -> None:
    if (
        manifest.get("reference_contract_id") != expected.reference_contract_id
        or manifest.get("normaliser_contract_id") != expected.normaliser_contract_id
        or manifest.get("bundle_sha256") != expected.bundle_sha256
        or manifest.get("bundle_size_bytes") != expected.bundle_size_bytes
        or manifest.get("total_reference_records") != expected.bundle_record_count
        or manifest.get("status") != "PASS"
    ):
        _fail("manifest_contract_or_bundle_binding")
    if (
        source_resolution.get("reference_contract_id")
        != expected.reference_contract_id
        or source_resolution.get("total_record_count")
        != expected.bundle_record_count
        or source_resolution.get("partition_count") != len(expected.partitions)
        or source_resolution.get("status") != "PASS"
    ):
        _fail("source_resolution_contract")

    manifest_rows = manifest.get("per_partition")
    source_rows = source_resolution.get("sources")
    if not isinstance(manifest_rows, list) or not isinstance(source_rows, list):
        _fail("partition_metadata_not_lists")
    if len(manifest_rows) != len(expected.partitions) or len(source_rows) != len(
        expected.partitions
    ):
        _fail("partition_metadata_count")
    for index, partition in enumerate(expected.partitions):
        safe = manifest_rows[index]
        source = source_rows[index]
        if not isinstance(safe, dict) or not isinstance(source, dict):
            _fail("partition_metadata_not_object")
        if (
            safe.get("partition_id") != partition.partition_id
            or safe.get("expected_count") != partition.record_count
            or safe.get("observed_count") != partition.record_count
            or safe.get("partition_bundle_sha256")
            != partition.raw_line_commitment
            or safe.get("source_alias") != partition.source_alias
            or safe.get("source_sha256") != partition.source_sha256
            or safe.get("status") != "PASS"
        ):
            _fail(f"manifest_partition:{partition.partition_id}")
        if (
            source.get("partition_id") != partition.partition_id
            or source.get("expected_count") != partition.record_count
            or source.get("observed_count") != partition.record_count
            or source.get("source_alias") != partition.source_alias
            or source.get("source_sha256") != partition.source_sha256
            or source.get("resolution_status") != "PASS"
        ):
            _fail(f"source_resolution_partition:{partition.partition_id}")


def validate_exact_authority_files(
    *,
    manifest_path: Path,
    bundle_path: Path,
    source_resolution_path: Path,
    expected: ExpectedAuthorityIdentity,
    governance_probe: GovernanceProbe,
) -> ValidatedAuthorityPayload:
    """Validate exact bytes, file governance, content, and raw-line commitments.

    This parameterised primitive exists for adversarial synthetic fixtures.  The
    real D1 loader exposes no path or expected-identity parameters.
    """

    manifest_bytes = _read_regular_non_symlink(manifest_path, role="manifest")
    bundle_bytes = _read_regular_non_symlink(bundle_path, role="bundle")
    source_bytes = _read_regular_non_symlink(
        source_resolution_path, role="source_resolution"
    )
    _validate_governance(
        manifest_path=manifest_path,
        bundle_path=bundle_path,
        source_resolution_path=source_resolution_path,
        governance_probe=governance_probe,
    )
    _assert_file_identity(
        manifest_bytes,
        expected_sha256=expected.manifest_sha256,
        expected_size=expected.manifest_size_bytes,
        role="manifest",
    )
    _assert_file_identity(
        bundle_bytes,
        expected_sha256=expected.bundle_sha256,
        expected_size=expected.bundle_size_bytes,
        role="bundle",
    )
    _assert_file_identity(
        source_bytes,
        expected_sha256=expected.source_resolution_sha256,
        expected_size=expected.source_resolution_size_bytes,
        role="source_resolution",
    )
    manifest = _parse_json(manifest_bytes, role="manifest")
    source_resolution = _parse_json(source_bytes, role="source_resolution")
    _validate_safe_manifests(manifest, source_resolution, expected)
    rows, ordered = _validate_bundle_lines(bundle_bytes, expected)
    commitment = reference_authority_commitment(
        manifest_file_sha256=expected.manifest_sha256,
        bundle_file_sha256=expected.bundle_sha256,
        source_resolution_file_sha256=expected.source_resolution_sha256,
        ordered_partitions=ordered,
    )
    return ValidatedAuthorityPayload(
        manifest=manifest,
        source_resolution=source_resolution,
        reference_rows=rows,
        authority_commitment=commitment,
    )
