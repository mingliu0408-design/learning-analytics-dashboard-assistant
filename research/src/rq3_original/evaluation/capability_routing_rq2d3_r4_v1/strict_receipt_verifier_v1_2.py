"""Full-field artifact-receipt and repository-path verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from . import RQ2D3R4Error, sha256_bytes
from .strict_project_relative_path import (
    open_regular_nofollow,
    validate_project_relative_path,
)


class StrictReceiptError(RQ2D3R4Error):
    pass


RECEIPT_MISMATCH = "BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH"
SchemaValidator = Callable[[bytes], None]

REQUIRED_RECEIPT_FIELDS = frozenset(
    {
        "approved_head",
        "execution_id",
        "effective_contract_id",
        "worker_role",
        "worker_credential_commitment",
        "code_identity",
        "parent_state",
        "stage",
        "schema_id",
        "relative_path",
        "artifact_role",
        "sha256",
        "size_bytes",
        "record_count",
        "file_mode",
        "created_exclusively",
        "atomic_no_replace_publication",
        "file_fsync",
        "directory_fsync",
        "reread_verified",
        "schema_verified",
        "open_read_counts",
        "firewall_summary",
    }
)


def _read_descriptor(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = __import__("os").read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    extra = __import__("os").read(descriptor, 1)
    value = b"".join(chunks)
    if remaining or extra or len(value) != size:
        raise StrictReceiptError(RECEIPT_MISMATCH)
    return value


def _record_count(value: bytes, schema_id: str) -> int:
    if "jsonl" in schema_id.lower() or schema_id.lower().endswith("ledger-v1-2"):
        if not value.endswith(b"\n"):
            raise StrictReceiptError(RECEIPT_MISMATCH)
        return len(value.splitlines())
    document = json.loads(value)
    if not isinstance(document, (dict, list)):
        raise StrictReceiptError(RECEIPT_MISMATCH)
    if isinstance(document, list):
        return len(document)
    if isinstance(document.get("method_metrics"), dict):
        return len(document["method_metrics"])
    statistics = document.get("statistics")
    if isinstance(statistics, dict) and isinstance(statistics.get("comparisons"), dict):
        return len(statistics["comparisons"])
    return 1


def verify_strict_artifact_receipt_v1_2(
    repository_root: Path,
    receipt: Mapping[str, Any],
    *,
    expected_bindings: Mapping[str, Any],
    schema_validator: SchemaValidator | None = None,
) -> dict[str, Any]:
    if not REQUIRED_RECEIPT_FIELDS <= set(receipt):
        raise StrictReceiptError(RECEIPT_MISMATCH)
    relative = validate_project_relative_path(str(receipt["relative_path"]))
    exact_fields = (
        "approved_head",
        "execution_id",
        "effective_contract_id",
        "worker_role",
        "worker_credential_commitment",
        "code_identity",
        "parent_state",
        "stage",
        "schema_id",
        "relative_path",
        "artifact_role",
        "open_read_counts",
        "firewall_summary",
    )
    if any(receipt.get(field) != expected_bindings.get(field) for field in exact_fields):
        raise StrictReceiptError(RECEIPT_MISMATCH)
    if (
        receipt.get("file_mode") != "0600"
        or receipt.get("created_exclusively") is not True
        or receipt.get("atomic_no_replace_publication") is not True
        or receipt.get("file_fsync") is not True
        or receipt.get("directory_fsync") is not True
        or receipt.get("reread_verified") is not True
        or receipt.get("schema_verified") is not True
        or not isinstance(receipt.get("open_read_counts"), Mapping)
        or not isinstance(receipt.get("firewall_summary"), Mapping)
    ):
        raise StrictReceiptError(RECEIPT_MISMATCH)
    descriptor, observed = open_regular_nofollow(
        repository_root, relative, expected_mode=0o600
    )
    try:
        value = _read_descriptor(descriptor, observed.st_size)
    finally:
        __import__("os").close(descriptor)
    if (
        sha256_bytes(value) != receipt.get("sha256")
        or len(value) != receipt.get("size_bytes")
        or _record_count(value, str(receipt["schema_id"])) != receipt.get("record_count")
    ):
        raise StrictReceiptError(RECEIPT_MISMATCH)
    if schema_validator is not None:
        try:
            schema_validator(value)
        except BaseException as error:
            raise StrictReceiptError(RECEIPT_MISMATCH) from error
    return {
        "status": "PASS",
        "relative_path": str(relative),
        "sha256": receipt["sha256"],
        "size_bytes": receipt["size_bytes"],
        "record_count": receipt["record_count"],
        "mode": "0600",
        "no_follow": True,
        "all_receipt_fields_verified": True,
    }


def strict_receipt_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-strict-receipt-verification-contract-v1-2",
        "status": "FROZEN",
        "required_fields": sorted(REQUIRED_RECEIPT_FIELDS),
        "absolute_path_allowed": False,
        "traversal_allowed": False,
        "dot_component_allowed": False,
        "uri_allowed": False,
        "symlink_parent_allowed": False,
        "symlink_target_allowed": False,
        "open_no_follow": True,
        "fstat_regular_file": True,
        "inode_identity_checked": True,
        "all_bindings_exact": True,
        "failure_code": RECEIPT_MISMATCH,
    }
