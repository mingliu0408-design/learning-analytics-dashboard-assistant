#!/usr/bin/env python3
"""Independently audit original and replacement I0-R1 route-package ZIPs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tempfile
from typing import Any
from zipfile import ZipFile

try:
    from .build_r1_route_packages import (
        DOWNLOADS,
        ORIGINAL_PACKAGE_STATUS,
        PACKAGE_SPECS,
        R1_PACKAGE_STATUS,
        sha_file,
        verify_frozen_component,
        verify_i0_scientific_tree,
    )
    from .route_package_validator_v1 import SCIENTIFIC_MEMBERS, validate_package_dir
except ImportError:  # pragma: no cover - standalone entrypoint
    from build_r1_route_packages import (  # type: ignore
        DOWNLOADS,
        ORIGINAL_PACKAGE_STATUS,
        PACKAGE_SPECS,
        R1_PACKAGE_STATUS,
        sha_file,
        verify_frozen_component,
        verify_i0_scientific_tree,
    )
    from route_package_validator_v1 import (  # type: ignore
        SCIENTIFIC_MEMBERS,
        validate_package_dir,
    )


class R1ValidationError(RuntimeError):
    """Raised on any independent ZIP or byte-identity failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise R1ValidationError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_scientific(path: Path) -> dict[str, bytes]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"Duplicate ZIP member: {path.name}")
        require(all(not info.flag_bits & 0x1 for info in archive.infolist()), f"Encrypted ZIP member: {path.name}")
        return {name: archive.read(name) for name in SCIENTIFIC_MEMBERS}


def _validate_r1_zip(path: Path, component: str) -> dict[str, Any]:
    data = path.read_bytes()
    with ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"Duplicate R1 ZIP member: {path.name}")
        require(all(Path(name).name == name for name in names), f"Nested/unsafe R1 ZIP member: {path.name}")
        with tempfile.TemporaryDirectory(prefix="c4-r1-independent-") as temporary:
            root = Path(temporary)
            for name in names:
                (root / name).write_bytes(archive.read(name))
            result = validate_package_dir(root, expected_component=component)
    result["zip_sha256"] = sha256(data)
    result["path"] = str(path)
    return result


def validate_all(output_dir: Path = DOWNLOADS) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    scientific_tree = verify_i0_scientific_tree()
    packages = []
    for component, spec in PACKAGE_SPECS.items():
        configuration = verify_frozen_component(component, spec)
        original = DOWNLOADS / spec["original_filename"]
        replacement = output_dir / spec["r1_filename"]
        require(sha_file(original) == spec["original_sha256"], f"{component} original package changed")
        require(replacement.is_file(), f"{component} replacement package missing")
        old_members = _read_scientific(original)
        new_members = _read_scientific(replacement)
        member_audit = {}
        for name in SCIENTIFIC_MEMBERS:
            require(old_members[name] == new_members[name], f"{component} old/R1 member differs: {name}")
            member_audit[name] = {
                "original_sha256": sha256(old_members[name]),
                "r1_sha256": sha256(new_members[name]),
                "byte_identical": True,
            }
        package_result = _validate_r1_zip(replacement, component)
        package_result.update(
            {
                "frozen_configuration": configuration,
                "original_package_path": str(original),
                "original_package_sha256": spec["original_sha256"],
                "original_package_status": ORIGINAL_PACKAGE_STATUS,
                "old_r1_scientific_member_audit": member_audit,
            }
        )
        packages.append(package_result)
    return {
        "schema_version": "c4-real-r1-route-package-independent-validation-v1",
        "status": "PASS_ALL_R1_PACKAGES_AND_SCIENTIFIC_IDENTITIES",
        "r1_package_status": R1_PACKAGE_STATUS,
        "i0_scientific_tracked_artifacts": scientific_tree,
        "packages": packages,
        "provider_calls": 0,
        "route_executions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DOWNLOADS)
    args = parser.parse_args()
    print(json.dumps(validate_all(args.output_dir), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
