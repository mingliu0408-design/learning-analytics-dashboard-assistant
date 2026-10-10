"""Immutable O_EXCL one-shot reservation sentinel for real or synthetic tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import (
    EFFECTIVE_CONTRACT_ID,
    RQ2D3R4Error,
    SENTINEL_SCHEMA,
    canonical_json_bytes,
    sha256_bytes,
)


class ReservationSentinelError(RQ2D3R4Error):
    pass


ALREADY_RESERVED = "BLOCKED_RQ2_D4_GLOBAL_ACCESS_ALREADY_RESERVED"


def _normal_control_directory(path: Path) -> None:
    observed = os.lstat(path)
    if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise ReservationSentinelError("BLOCKED_RQ2_D4_UNSAFE_CONTROL_ROOT")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ReservationSentinelError("short reservation sentinel write")
        view = view[written:]


def read_reservation_sentinel_v1_2(path: Path) -> tuple[dict[str, Any], bytes]:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
    ):
        raise ReservationSentinelError(ALREADY_RESERVED)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) != (after.st_dev, after.st_ino):
            raise ReservationSentinelError(ALREADY_RESERVED)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    value = b"".join(chunks)
    try:
        document = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReservationSentinelError(ALREADY_RESERVED) from error
    required = {
        "schema_version",
        "sentinel_role",
        "execution_contract_id",
        "execution_id",
        "approved_head",
        "retry_permitted",
        "access_consumed",
        "fixed_output_root_relative",
        "fixed_control_root_relative",
        "fixed_sentinel_relative",
        "fixed_state_relative",
        "fixed_parent_receipt_relative",
        "parent_execution_nonce_commitment",
        "parent_receipt_descriptor_commitment",
        "reservation_created_at",
        "synthetic",
    }
    if (
        not required <= set(document)
        or document.get("schema_version") != SENTINEL_SCHEMA
        or document.get("sentinel_role") != "IMMUTABLE_ONE_SHOT_RESERVATION_SENTINEL"
        or document.get("retry_permitted") is not False
        or document.get("access_consumed") is not True
    ):
        raise ReservationSentinelError(ALREADY_RESERVED)
    return document, value


def create_reservation_sentinel_v1_2(
    path: Path, document: Mapping[str, Any]
) -> dict[str, Any]:
    """Create once; any existing inode, valid or not, permanently blocks retry."""

    _normal_control_directory(path.parent)
    value = canonical_json_bytes(dict(document))
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError as error:
        raise ReservationSentinelError(ALREADY_RESERVED) from error
    try:
        _write_all(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    observed_document, observed_value = read_reservation_sentinel_v1_2(path)
    if observed_value != value or observed_document != dict(document):
        raise ReservationSentinelError("reservation sentinel reread mismatch")
    return {
        "relative_name": path.name,
        "sha256": sha256_bytes(observed_value),
        "size_bytes": len(observed_value),
        "file_mode": "0600",
        "created_exclusively": True,
        "file_fsync": True,
        "directory_fsync": True,
        "reread_verified": True,
    }


def reservation_sentinel_document_v1_2(
    *,
    execution_id: str,
    approved_head: str,
    fixed_paths: Mapping[str, str],
    frozen_identity_bundle: Mapping[str, Any],
    input_identity_bundle: Mapping[str, Any],
    d3_r4_code_bundle_identity: str,
    parent_execution_nonce_commitment: str,
    parent_receipt_descriptor_commitment: str,
    reservation_created_at: str,
    synthetic: bool,
    execution_contract_id: str = EFFECTIVE_CONTRACT_ID,
) -> dict[str, Any]:
    return {
        "schema_version": SENTINEL_SCHEMA,
        "sentinel_role": "IMMUTABLE_ONE_SHOT_RESERVATION_SENTINEL",
        "execution_contract_id": execution_contract_id,
        "execution_id": execution_id,
        "approved_head": approved_head,
        "retry_permitted": False,
        "access_consumed": True,
        "fixed_output_root_relative": fixed_paths["output_root_relative"],
        "fixed_control_root_relative": fixed_paths["control_root_relative"],
        "fixed_sentinel_relative": fixed_paths["sentinel_relative"],
        "fixed_state_relative": fixed_paths["state_relative"],
        "fixed_parent_receipt_relative": fixed_paths["parent_receipt_relative"],
        "frozen_identity_bundle": dict(frozen_identity_bundle),
        "expected_input_identities": dict(input_identity_bundle),
        "d3_r4_code_bundle_identity": d3_r4_code_bundle_identity,
        "parent_execution_nonce_commitment": parent_execution_nonce_commitment,
        "parent_receipt_descriptor_commitment": parent_receipt_descriptor_commitment,
        "reservation_created_at": reservation_created_at,
        "synthetic": bool(synthetic),
    }


def immutable_reservation_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-immutable-reservation-contract-v1-2",
        "status": "FROZEN",
        "role": "IMMUTABLE_ONE_SHOT_RESERVATION_SENTINEL",
        "creation_flags": ["O_WRONLY", "O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
        "mode": "0600",
        "file_fsync": True,
        "control_directory_fsync": True,
        "reread_verified": True,
        "truncate_permitted": False,
        "rewrite_permitted": False,
        "replace_permitted": False,
        "rename_permitted": False,
        "delete_or_move_permitted": False,
        "existing_valid_or_malformed_inode_result": ALREADY_RESERVED,
        "retry_permitted": False,
    }
