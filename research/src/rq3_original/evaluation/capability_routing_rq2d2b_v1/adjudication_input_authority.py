"""Resolve only the two authorised completed-adjudication candidate paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import subprocess
from typing import Any

from . import (
    COMPLETED_ADJUDICATION_SHA256,
    COMPLETED_ADJUDICATION_SIZE,
    ORIGINAL_ADJUDICATION_RELATIVE,
    ROOT,
    durable_write,
    fallback_input_path,
    primary_input_path,
    sha256_bytes,
    sha256_file,
)


class AdjudicationInputAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdjudicationInputPaths:
    selected_input: Path
    selected_role: str
    original_copy: Path


def _regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def _candidate(path: Path, role: str) -> tuple[str, Path, bytes] | None:
    if not path.exists():
        return None
    if not _regular_non_symlink(path):
        raise AdjudicationInputAuthorityError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_PACKET_IDENTITY"
        )
    value = path.read_bytes()
    if (
        len(value) != COMPLETED_ADJUDICATION_SIZE
        or sha256_bytes(value) != COMPLETED_ADJUDICATION_SHA256
    ):
        raise AdjudicationInputAuthorityError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_PACKET_IDENTITY"
        )
    return role, path, value


def resolve_and_preserve_input(
    root: Path = ROOT,
) -> tuple[AdjudicationInputPaths, dict[str, Any]]:
    primary = _candidate(primary_input_path(), "PRIMARY")
    fallback = _candidate(fallback_input_path(), "AUTHORISED_FALLBACK")
    present = [candidate for candidate in (primary, fallback) if candidate is not None]
    if not present or (len(present) == 2 and present[0][2] != present[1][2]):
        raise AdjudicationInputAuthorityError(
            "BLOCKED_RQ2_D2B_ADJUDICATION_PACKET_IDENTITY"
        )
    role, selected, value = present[0]
    original = root / ORIGINAL_ADJUDICATION_RELATIVE
    durable_write(original, value)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", ORIGINAL_ADJUDICATION_RELATIVE.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ORIGINAL_ADJUDICATION_RELATIVE.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    if (
        not ignored
        or tracked
        or sha256_file(original) != COMPLETED_ADJUDICATION_SHA256
        or original.stat().st_size != COMPLETED_ADJUDICATION_SIZE
        or sha256_file(selected) != COMPLETED_ADJUDICATION_SHA256
    ):
        raise AdjudicationInputAuthorityError("completed adjudication preservation mismatch")
    paths = AdjudicationInputPaths(selected, role, original)
    return paths, {
        "schema_version": "track-b-adjudication-packet-authority-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "authority_basis": "EXACT_TWO_PATH_FAIL_CLOSED_USER_AUTHORITY",
        "primary_candidate_present": primary is not None,
        "fallback_candidate_present": fallback is not None,
        "selected_candidate_role": role,
        "existing_candidate_count": len(present),
        "both_candidates_byte_identical_if_present": len(present) < 2 or present[0][2] == present[1][2],
        "broad_file_search_performed": False,
        "sha256": COMPLETED_ADJUDICATION_SHA256,
        "size_bytes": COMPLETED_ADJUDICATION_SIZE,
        "record_count": 23,
        "column_count": 52,
        "regular_non_symlink": True,
        "local_original_relative_path": ORIGINAL_ADJUDICATION_RELATIVE.as_posix(),
        "local_copy_sha256": COMPLETED_ADJUDICATION_SHA256,
        "local_copy_size_bytes": COMPLETED_ADJUDICATION_SIZE,
        "exclusive_temporary_write": True,
        "file_fsync": True,
        "os_replace": True,
        "parent_directory_fsync": True,
        "reread_verified": True,
        "ignored": True,
        "tracked": False,
        "downloads_input_modified": False,
    }
