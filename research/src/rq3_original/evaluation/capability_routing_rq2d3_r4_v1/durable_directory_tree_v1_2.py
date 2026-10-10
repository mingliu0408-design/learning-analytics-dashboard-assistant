"""Durable, non-symlink directory-tree creation for future D4 local roots."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from . import RQ2D3R4Error
from .strict_project_relative_path import validate_project_relative_path


class DurableDirectoryError(RQ2D3R4Error):
    pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_normal_directory(path: Path) -> os.stat_result:
    observed = os.lstat(path)
    if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise DurableDirectoryError("BLOCKED_RQ2_D4_UNSAFE_DIRECTORY")
    return observed


def create_durable_directory_tree_v1_2(
    repository_root: Path, relative: str
) -> list[dict[str, Any]]:
    parsed = validate_project_relative_path(relative)
    root = repository_root.absolute()
    _require_normal_directory(root)
    current = root
    reports: list[dict[str, Any]] = []
    for component in parsed.parts:
        parent = current
        current = current / component
        created = False
        try:
            observed = _require_normal_directory(current)
        except FileNotFoundError:
            os.mkdir(current, 0o700)
            created = True
            observed = _require_normal_directory(current)
            if stat.S_IMODE(observed.st_mode) != 0o700:
                raise DurableDirectoryError("BLOCKED_RQ2_D4_DIRECTORY_MODE")
            _fsync_directory(current)
            _fsync_directory(parent)
        reports.append(
            {
                "relative_path": str(current.relative_to(root)),
                "directory_created": created,
                "directory_mode": f"{stat.S_IMODE(observed.st_mode):04o}",
                "directory_fsync": created,
                "parent_directory_fsync": created,
            }
        )
    return reports


def durable_directory_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-durable-directory-contract-v1-2",
        "status": "FROZEN",
        "created_mode": "0700",
        "symlink_directory_allowed": False,
        "new_directory_fsync": True,
        "parent_directory_fsync": True,
        "real_directory_creation_count_in_r4": 0,
    }
