"""Exclusive, atomic, durable and reread-verified local artifact publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable

from . import RQ2D3R3Error, sha256_bytes


class DurableArtifactError(RQ2D3R3Error):
    pass


SchemaValidator = Callable[[bytes], None]


def _normal_directory(path: Path) -> None:
    value = os.lstat(path)
    if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
        raise DurableArtifactError("BLOCKED_RQ2_D4_UNSAFE_ARTIFACT_PARENT")


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise DurableArtifactError("short durable artifact write")
        view = view[written:]


def publish_durable_artifact_v1_1(
    target: Path,
    value: bytes,
    *,
    stage: str,
    worker_role: str,
    artifact_role: str,
    schema_id: str,
    record_count: int,
    approved_head: str,
    execution_id: str,
    effective_contract_id: str,
    code_identity: str,
    parent_state: str,
    schema_validator: SchemaValidator | None = None,
) -> dict[str, Any]:
    _normal_directory(target.parent)
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        raise DurableArtifactError("BLOCKED_RQ2_D4_PREEXISTING_LOCAL_ARTIFACT")
    temporary = target.parent / f".{target.name}.tmp.{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    published = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        _write_all(descriptor, value)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        published = True
        parent_descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not published:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    target_stat = os.lstat(target)
    if not stat.S_ISREG(target_stat.st_mode) or stat.S_ISLNK(target_stat.st_mode):
        raise DurableArtifactError("durable artifact is not a regular file")
    if stat.S_IMODE(target_stat.st_mode) != 0o600:
        raise DurableArtifactError("durable artifact mode mismatch")
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        reread = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            reread += chunk
    finally:
        os.close(descriptor)
    if reread != value:
        raise DurableArtifactError("durable artifact reread mismatch")
    if schema_validator is not None:
        schema_validator(reread)
    return {
        "stage": stage,
        "worker_role": worker_role,
        "relative_path": str(target.name),
        "artifact_role": artifact_role,
        "schema_id": schema_id,
        "sha256": sha256_bytes(reread),
        "size_bytes": len(reread),
        "record_count": int(record_count),
        "file_mode": "0600",
        "created_exclusively": True,
        "atomic_publication": True,
        "file_fsync": True,
        "directory_fsync": True,
        "reread_verified": True,
        "schema_verified": schema_validator is not None,
        "approved_head": approved_head,
        "execution_id": execution_id,
        "effective_contract_id": effective_contract_id,
        "code_identity": code_identity,
        "parent_state": parent_state,
    }


def verify_artifact_receipt_v1_1(
    target: Path, receipt: dict[str, Any], *, schema_validator: SchemaValidator | None = None
) -> None:
    value = target.read_bytes()
    if sha256_bytes(value) != receipt.get("sha256") or len(value) != receipt.get("size_bytes"):
        raise DurableArtifactError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    mode = stat.S_IMODE(os.lstat(target).st_mode)
    if mode != 0o600 or receipt.get("file_mode") != "0600":
        raise DurableArtifactError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    if schema_validator is not None:
        schema_validator(value)


def json_object_validator(schema_version: str) -> SchemaValidator:
    def validate(value: bytes) -> None:
        document = json.loads(value)
        if not isinstance(document, dict) or document.get("schema_version") != schema_version:
            raise DurableArtifactError("artifact JSON schema mismatch")

    return validate


def durable_artifact_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-durable-artifact-contract-v1-1",
        "status": "FROZEN",
        "target_absent_required": True,
        "same_directory_temporary": True,
        "flags": ["O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
        "mode": "0600",
        "atomic_publication": "os.replace",
        "file_fsync": True,
        "directory_fsync": True,
        "reread_verification": True,
        "overwrite_permitted": False,
        "partial_temporary_cleanup": True,
    }
