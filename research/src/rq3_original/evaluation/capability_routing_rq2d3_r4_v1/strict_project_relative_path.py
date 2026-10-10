"""Strict repository-relative path and no-follow file verification."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Iterator

from . import RQ2D3R4Error


class StrictPathError(RQ2D3R4Error):
    pass


INVALID_PATH = "BLOCKED_RQ2_D4_INVALID_RECEIPT_PATH"
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def validate_project_relative_path(value: str | PurePosixPath) -> PurePosixPath:
    raw = str(value)
    if (
        not raw
        or "\x00" in raw
        or raw.startswith("/")
        or raw.startswith("~")
        or "\\" in raw
        or _URI.match(raw)
    ):
        raise StrictPathError(INVALID_PATH)
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise StrictPathError(INVALID_PATH)
    relative = PurePosixPath(raw)
    if relative.is_absolute() or relative.as_posix() != raw:
        raise StrictPathError(INVALID_PATH)
    return relative


def _normal_directory(path: Path) -> os.stat_result:
    value = os.lstat(path)
    if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
        raise StrictPathError(INVALID_PATH)
    return value


def walk_existing_parents(
    repository_root: Path,
    relative: str | PurePosixPath,
    *,
    allow_missing_tail: bool = False,
) -> Iterator[Path]:
    parsed = validate_project_relative_path(relative)
    root = repository_root.absolute()
    _normal_directory(root)
    current = root
    for component in parsed.parts[:-1]:
        current = current / component
        try:
            _normal_directory(current)
        except FileNotFoundError:
            if allow_missing_tail:
                return
            raise StrictPathError(INVALID_PATH) from None
        yield current


def project_path(
    repository_root: Path,
    relative: str | PurePosixPath,
    *,
    allow_missing_tail: bool = False,
) -> Path:
    parsed = validate_project_relative_path(relative)
    tuple(walk_existing_parents(repository_root, parsed, allow_missing_tail=allow_missing_tail))
    target = repository_root.absolute().joinpath(*parsed.parts)
    try:
        target.relative_to(repository_root.absolute())
    except ValueError as error:
        raise StrictPathError(INVALID_PATH) from error
    return target


def open_regular_nofollow(
    repository_root: Path,
    relative: str | PurePosixPath,
    *,
    expected_mode: int | None = None,
) -> tuple[int, os.stat_result]:
    target = project_path(repository_root, relative)
    before = os.lstat(target)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise StrictPathError(INVALID_PATH)
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or (expected_mode is not None and stat.S_IMODE(after.st_mode) != expected_mode)
        ):
            raise StrictPathError(INVALID_PATH)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, after


def read_regular_nofollow(
    repository_root: Path,
    relative: str | PurePosixPath,
    *,
    expected_mode: int | None = None,
) -> bytes:
    descriptor, observed = open_regular_nofollow(
        repository_root, relative, expected_mode=expected_mode
    )
    try:
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        extra = os.read(descriptor, 1)
    finally:
        os.close(descriptor)
    value = b"".join(chunks)
    if remaining or extra or len(value) != observed.st_size:
        raise StrictPathError(INVALID_PATH)
    return value
