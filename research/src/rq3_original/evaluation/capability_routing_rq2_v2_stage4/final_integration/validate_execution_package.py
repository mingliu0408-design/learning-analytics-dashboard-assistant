"""Independently validate one Stage 4N execution/review ZIP without extraction."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import PurePosixPath, Path
import zipfile


class PackageValidationError(RuntimeError):
    """Raised when a package member, allowlist, or frozen record differs."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def validate(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise PackageValidationError(f"package is missing: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(not safe_member(name) for name in names):
            raise PackageValidationError("duplicate or unsafe archive member")
        if archive.testzip() is not None:
            raise PackageValidationError("ZIP CRC verification failed")
        if "PACKAGE_MANIFEST.json" not in names:
            raise PackageValidationError("PACKAGE_MANIFEST.json is missing")
        if any("gold" in PurePosixPath(name).name.casefold() for name in names):
            raise PackageValidationError("a TEST Gold-like member name is present")
        package_manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        if not isinstance(package_manifest, dict):
            raise PackageValidationError("package manifest root is not an object")
        declared = package_manifest.get("archive_allowlist")
        if not isinstance(declared, list) or declared != names:
            raise PackageValidationError("archive member order/allowlist differs")
        described = package_manifest.get("members")
        if not isinstance(described, list) or len(described) != len(names) - 1:
            raise PackageValidationError("package member manifest count differs")
        by_name = {item.get("path"): item for item in described if isinstance(item, dict)}
        for name in names:
            if name == "PACKAGE_MANIFEST.json":
                continue
            item = by_name.get(name)
            data = archive.read(name)
            if item is None or item.get("sha256") != sha256_bytes(data) or item.get("size_bytes") != len(data):
                raise PackageValidationError(f"package member hash/size differs: {name}")

        input_csvs = [name for name in names if name.endswith("test_inputs_frozen_v1.csv")]
        for name in input_csvs:
            text = archive.read(name).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            expected = ["annotation_case_id", "current_query", "current_page", "dashboard_context", "visible_conversation_history"]
            if reader.fieldnames != expected or len(rows) != 36:
                raise PackageValidationError("packaged TEST CSV schema/count differs")

        execution_manifests = [
            name for name in names
            if name.endswith("test_execution_manifest_v1.jsonl")
        ]
        for name in execution_manifests:
            rows = [json.loads(line) for line in archive.read(name).decode("utf-8").splitlines() if line]
            if len(rows) != 36 or any(row.get("execution_status") != "NOT_EXECUTED" for row in rows):
                raise PackageValidationError(f"packaged execution manifest differs: {name}")
        return {
            "package_role": package_manifest.get("package_role"),
            "member_count": len(names),
            "sha256": sha256_bytes(path.read_bytes()),
            "crc_status": "PASS",
            "allowlist_status": "PASS",
            "TEST_Gold_member_count": 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    args = parser.parse_args()
    result = validate(args.zip_path.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
