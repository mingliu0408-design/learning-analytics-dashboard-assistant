"""Fixed repository-relative output and global-lock path authority."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
)


class FixedD1PathError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedRealD1FixedPathsV1_3:
    repo_root: Path
    output_root: Path
    global_control_root: Path
    global_lock_path: Path


def validate_project_relative_posix_path_v1_3(value: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or value.startswith("~")
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
        or "\\" in value
    ):
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    if path.as_posix() != value:
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    return path


def _assert_normal_non_symlink_directory(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")


def _validate_existing_components(repo_root: Path, relative: PurePosixPath) -> None:
    current = repo_root
    for component in relative.parts[:-1]:
        current = current / component
        try:
            current.lstat()
        except FileNotFoundError:
            break
        _assert_normal_non_symlink_directory(current)


def _ensure_target_inside_repo(repo_root: Path, target: Path) -> None:
    resolved_root = repo_root.resolve(strict=True)
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise FixedD1PathError(
            "BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT"
        ) from exc


def resolve_real_d1_fixed_paths_v1_3(
    repo_root: Path,
) -> ResolvedRealD1FixedPathsV1_3:
    if not repo_root.is_absolute():
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    try:
        _assert_normal_non_symlink_directory(repo_root)
    except (FileNotFoundError, OSError) as exc:
        raise FixedD1PathError(
            "BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT"
        ) from exc
    output_relative = validate_project_relative_posix_path_v1_3(
        REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3
    )
    control_relative = validate_project_relative_posix_path_v1_3(
        REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3
    )
    lock_relative = validate_project_relative_posix_path_v1_3(
        REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3
    )
    output = repo_root.joinpath(*output_relative.parts)
    control = repo_root.joinpath(*control_relative.parts)
    lock = repo_root.joinpath(*lock_relative.parts)
    if lock.parent != control:
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    for relative, target in (
        (output_relative, output),
        (control_relative, control),
        (lock_relative, lock),
    ):
        _validate_existing_components(repo_root, relative)
        _ensure_target_inside_repo(repo_root, target)
    for directory in (output, control):
        try:
            directory.lstat()
        except FileNotFoundError:
            continue
        _assert_normal_non_symlink_directory(directory)
    try:
        mode = lock.lstat().st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None and stat.S_ISLNK(mode):
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    return ResolvedRealD1FixedPathsV1_3(
        repo_root=repo_root,
        output_root=output,
        global_control_root=control,
        global_lock_path=lock,
    )


def validate_output_root_new_or_empty_v1_3(output_root: Path) -> dict[str, Any]:
    try:
        mode = output_root.lstat().st_mode
    except FileNotFoundError:
        return {"status": "PASS", "output_root_preexisting": False}
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    with os.scandir(output_root) as entries:
        if next(entries, None) is not None:
            raise FixedD1PathError("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    return {"status": "PASS", "output_root_preexisting": True}


def fixed_path_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-fixed-output-authority-v1",
        "status": "FROZEN_BEFORE_REAL_D1",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "real_output_root_relative": REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
        "real_global_control_root_relative": (
            REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3
        ),
        "real_global_access_lock_relative": (
            REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3
        ),
        "repository_root_source": "git rev-parse --show-toplevel",
        "output_or_lock_override_permitted": False,
        "environment_path_override_permitted": False,
        "configuration_path_override_permitted": False,
        "downloads_fallback_permitted": False,
        "relative_path_validation": {
            "absolute_rejected": True,
            "dot_and_dotdot_rejected": True,
            "nul_rejected": True,
            "uri_scheme_rejected": True,
            "home_expansion_rejected": True,
            "existing_symlink_parent_rejected": True,
            "resolved_target_must_remain_inside_repo": True,
        },
        "real_directories_created_in_rq2_d0_r3": False,
        "absolute_paths_emitted": False,
    }
