"""Exact completed-packet authority and byte-preserving local copies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import subprocess
from typing import Any

from . import (
    COMPLETED_A_NAME,
    COMPLETED_A_SHA256,
    COMPLETED_A_SIZE,
    COMPLETED_B_NAME,
    COMPLETED_B_SHA256,
    COMPLETED_B_SIZE,
    ORIGINAL_A_RELATIVE,
    ORIGINAL_B_RELATIVE,
    ROOT,
    csv_rows_from_bytes,
    downloads_path,
    durable_write,
    sha256_bytes,
    sha256_file,
)


class CompletedPacketAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletedPacketPaths:
    input_a: Path
    input_b: Path
    original_a: Path
    original_b: Path


def resolve_paths(root: Path = ROOT) -> CompletedPacketPaths:
    return CompletedPacketPaths(
        input_a=downloads_path(COMPLETED_A_NAME),
        input_b=downloads_path(COMPLETED_B_NAME),
        original_a=root / ORIGINAL_A_RELATIVE,
        original_b=root / ORIGINAL_B_RELATIVE,
    )


def _is_regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def _assert_local_boundary(root: Path, relative: Path) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    if not ignored or tracked:
        raise CompletedPacketAuthorityError("completed-packet copy boundary mismatch")


def _validate_one(
    path: Path, expected_sha256: str, expected_size: int, reviewer_id: str
) -> bytes:
    if not _is_regular_non_symlink(path):
        raise CompletedPacketAuthorityError("BLOCKED_RQ2_D2A_COMPLETED_PACKET_IDENTITY")
    value = path.read_bytes()
    if len(value) != expected_size or sha256_bytes(value) != expected_sha256:
        raise CompletedPacketAuthorityError("BLOCKED_RQ2_D2A_COMPLETED_PACKET_IDENTITY")
    rows = csv_rows_from_bytes(value)
    if len(rows) != 48 or {row.get("reviewer_id") for row in rows} != {reviewer_id}:
        raise CompletedPacketAuthorityError("BLOCKED_RQ2_D2A_COMPLETED_PACKET_IDENTITY")
    return value


def validate_and_preserve_completed_packets(root: Path = ROOT) -> tuple[CompletedPacketPaths, dict[str, Any]]:
    paths = resolve_paths(root)
    value_a = _validate_one(paths.input_a, COMPLETED_A_SHA256, COMPLETED_A_SIZE, "A")
    value_b = _validate_one(paths.input_b, COMPLETED_B_SHA256, COMPLETED_B_SIZE, "B")

    durable_write(paths.original_a, value_a)
    durable_write(paths.original_b, value_b)
    _assert_local_boundary(root, ORIGINAL_A_RELATIVE)
    _assert_local_boundary(root, ORIGINAL_B_RELATIVE)

    if (
        sha256_file(paths.original_a) != COMPLETED_A_SHA256
        or paths.original_a.stat().st_size != COMPLETED_A_SIZE
        or sha256_file(paths.original_b) != COMPLETED_B_SHA256
        or paths.original_b.stat().st_size != COMPLETED_B_SIZE
        or sha256_file(paths.input_a) != COMPLETED_A_SHA256
        or sha256_file(paths.input_b) != COMPLETED_B_SHA256
    ):
        raise CompletedPacketAuthorityError("completed original preservation mismatch")

    def entry(
        filename: str,
        digest: str,
        size: int,
        reviewer: str,
        source_template: str,
        relative: Path,
    ) -> dict[str, Any]:
        return {
            "downloads_input_basename": filename,
            "sha256": digest,
            "size_bytes": size,
            "regular_non_symlink": True,
            "reviewer_identity": reviewer,
            "source_blank_template_role": source_template,
            "local_original_relative_path": relative.as_posix(),
            "local_copy_sha256": digest,
            "local_copy_size_bytes": size,
            "fsync_completed": True,
            "reread_verified": True,
            "ignored": True,
            "tracked": False,
            "input_modified": False,
        }

    return paths, {
        "schema_version": "track-b-completed-packet-authority-v1",
        "stage": "RQ2-D2A",
        "status": "PASS",
        "authority_basis": "EXACT_USER_AUTHORISED_PATH_AND_RAW_BYTE_IDENTITY",
        "alternate_path_search_performed": False,
        "reviewer_a": entry(
            COMPLETED_A_NAME,
            COMPLETED_A_SHA256,
            COMPLETED_A_SIZE,
            "A",
            "FROZEN_REVIEWER_B_TEMPLATE_ORDER",
            ORIGINAL_A_RELATIVE,
        ),
        "reviewer_b": entry(
            COMPLETED_B_NAME,
            COMPLETED_B_SHA256,
            COMPLETED_B_SIZE,
            "B",
            "FROZEN_REVIEWER_A_TEMPLATE_ORDER",
            ORIGINAL_B_RELATIVE,
        ),
        "original_downloads_inputs_preserved": True,
        "reviewer_answer_changed": False,
        "rationale_changed": False,
    }
