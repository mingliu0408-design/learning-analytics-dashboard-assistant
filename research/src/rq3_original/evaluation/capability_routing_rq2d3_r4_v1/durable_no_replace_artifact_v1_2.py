"""Atomic hard-link publication that can never replace an existing target."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Callable, Mapping

from . import RQ2D3R4Error, sha256_bytes
from .strict_project_relative_path import validate_project_relative_path


class NoReplaceArtifactError(RQ2D3R4Error):
    pass


SchemaValidator = Callable[[bytes], None]
PublicationHook = Callable[[Path, Path], None]


def _normal_directory(path: Path) -> None:
    observed = os.lstat(path)
    if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise NoReplaceArtifactError("BLOCKED_RQ2_D4_UNSAFE_ARTIFACT_PARENT")


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
            raise NoReplaceArtifactError("short no-replace artifact write")
        view = view[written:]


def _read_target_nofollow(target: Path) -> bytes:
    before = os.lstat(target)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise NoReplaceArtifactError("BLOCKED_RQ2_D4_UNSAFE_ARTIFACT_TARGET")
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise NoReplaceArtifactError("BLOCKED_RQ2_D4_UNSAFE_ARTIFACT_TARGET")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def publish_no_replace_artifact_v1_2(
    target: Path,
    value: bytes,
    *,
    relative_path: str,
    stage: str,
    worker_role: str,
    worker_credential_commitment: str | None,
    artifact_role: str,
    schema_id: str,
    record_count: int,
    approved_head: str,
    execution_id: str,
    effective_contract_id: str,
    code_identity: str,
    parent_state: str,
    open_read_counts: Mapping[str, int] | None = None,
    firewall_summary: Mapping[str, Any] | None = None,
    schema_validator: SchemaValidator | None = None,
    before_publication: PublicationHook | None = None,
) -> dict[str, Any]:
    validate_project_relative_path(relative_path)
    _normal_directory(target.parent)
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        raise NoReplaceArtifactError("BLOCKED_RQ2_D4_PREEXISTING_LOCAL_ARTIFACT")
    temporary = target.parent / f".{target.name}.tmp.{secrets.token_hex(16)}"
    descriptor: int | None = None
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        _write_all(descriptor, value)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if before_publication is not None:
            before_publication(temporary, target)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as error:
            raise NoReplaceArtifactError(
                "BLOCKED_RQ2_D4_PREEXISTING_LOCAL_ARTIFACT"
            ) from error
        except (AttributeError, NotImplementedError, TypeError) as error:
            raise NoReplaceArtifactError(
                "BLOCKED_RQ2_D3_R4_NO_REPLACE_UNAVAILABLE"
            ) from error
        except OSError as error:
            if error.errno == errno.EEXIST:
                raise NoReplaceArtifactError(
                    "BLOCKED_RQ2_D4_PREEXISTING_LOCAL_ARTIFACT"
                ) from error
            if error.errno in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV}:
                raise NoReplaceArtifactError(
                    "BLOCKED_RQ2_D3_R4_NO_REPLACE_UNAVAILABLE"
                ) from error
            raise
        linked = True
        reread = _read_target_nofollow(target)
        if reread != value:
            raise NoReplaceArtifactError("no-replace artifact reread mismatch")
        target_stat = os.lstat(target)
        if stat.S_IMODE(target_stat.st_mode) != 0o600:
            raise NoReplaceArtifactError("no-replace artifact mode mismatch")
        if schema_validator is not None:
            schema_validator(reread)
        _fsync_directory(target.parent)
        os.unlink(temporary)
        _fsync_directory(target.parent)
        temporary = Path()
        final_reread = _read_target_nofollow(target)
        if final_reread != value:
            raise NoReplaceArtifactError("no-replace final reread mismatch")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary != Path():
            try:
                os.unlink(temporary)
                _fsync_directory(target.parent)
            except FileNotFoundError:
                pass
    return {
        "approved_head": approved_head,
        "execution_id": execution_id,
        "effective_contract_id": effective_contract_id,
        "worker_role": worker_role,
        "worker_credential_commitment": worker_credential_commitment,
        "code_identity": code_identity,
        "parent_state": parent_state,
        "stage": stage,
        "schema_id": schema_id,
        "relative_path": relative_path,
        "artifact_role": artifact_role,
        "sha256": sha256_bytes(value),
        "size_bytes": len(value),
        "record_count": int(record_count),
        "file_mode": "0600",
        "created_exclusively": True,
        "atomic_no_replace_publication": True,
        "hard_link_publication": linked,
        "file_fsync": True,
        "directory_fsync": True,
        "temporary_unlink_directory_fsync": True,
        "reread_verified": True,
        "schema_verified": schema_validator is not None,
        "open_read_counts": dict(open_read_counts or {}),
        "firewall_summary": dict(firewall_summary or {}),
    }


def json_object_validator(schema_version: str) -> SchemaValidator:
    def validate(value: bytes) -> None:
        document = json.loads(value)
        if not isinstance(document, dict) or document.get("schema_version") != schema_version:
            raise NoReplaceArtifactError("artifact JSON schema mismatch")

    return validate


def no_replace_artifact_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-no-replace-artifact-contract-v1-2",
        "status": "FROZEN",
        "same_directory_random_temporary": True,
        "temporary_flags": ["O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
        "mode": "0600",
        "publication": "os.link(temp,target,follow_symlinks=False)",
        "os_replace_for_final_artifacts": False,
        "precheck_only_exclusivity": False,
        "existing_target_result": "FAIL_WITHOUT_OVERWRITE",
        "file_fsync": True,
        "directory_fsync_after_link": True,
        "directory_fsync_after_temp_unlink": True,
        "reread_verification": True,
        "unsupported_platform_result": "BLOCKED_RQ2_D3_R4_NO_REPLACE_UNAVAILABLE",
    }
