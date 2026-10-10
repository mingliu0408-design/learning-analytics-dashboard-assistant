"""Build the narrow deterministic Stage 4M review ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Sequence
import zipfile

from . import run_stage4m as stage4m


DEFAULT_DESTINATION = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_4M_SPECIALIST_COMPOSITION_DEV_REVIEW_2026-08-31.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_4M_SPECIALIST_COMPOSITION_DEV_REVIEW_2026-08-31"
FIXED_TIMESTAMP = (2026, 8, 31, 0, 0, 0)


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=stage4m.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def review_files(*, require_clean: bool) -> list[Path]:
    expected_root_names = {
        "__init__.py",
        "run_stage4m.py",
        "build_review_zip.py",
        "STAGE4M_OUTPUT_SHA256_MANIFEST.json",
        *stage4m.GENERATED_OUTPUT_NAMES,
    }
    expected_relative = {
        Path(name) for name in expected_root_names
    } | {
        Path("tests/__init__.py"),
        Path("tests/test_stage4m.py"),
    }
    missing = [
        relative
        for relative in sorted(expected_relative)
        if not (stage4m.TRACK_DIR / relative).is_file()
    ]
    if missing:
        raise stage4m.Stage4MError(f"review files missing: {missing}")
    if require_clean:
        if _git("status", "--short"):
            raise stage4m.Stage4MError("review ZIP requires a clean committed tree")
        track_relative = stage4m.TRACK_DIR.relative_to(stage4m.REPO_ROOT).as_posix()
        tracked = {
            Path(line).relative_to(track_relative)
            for line in _git("ls-files", "--", track_relative).splitlines()
            if line
        }
        if tracked != expected_relative:
            raise stage4m.Stage4MError(
                f"tracked review inventory differs: missing={sorted(expected_relative - tracked)}, extra={sorted(tracked - expected_relative)}"
            )
    return [stage4m.TRACK_DIR / relative for relative in sorted(expected_relative)]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(
    destination: Path = DEFAULT_DESTINATION,
    *,
    require_clean: bool = True,
    replace: bool = False,
) -> dict[str, object]:
    files = review_files(require_clean=require_clean)
    if destination.exists() and not replace:
        raise stage4m.Stage4MError(
            f"review ZIP already exists; refusing overwrite without --replace: {destination}"
        )
    file_entries = []
    payloads = []
    for path in files:
        relative = path.relative_to(stage4m.TRACK_DIR).as_posix()
        data = path.read_bytes()
        payloads.append((relative, data))
        file_entries.append(
            {"path": relative, "sha256": _sha256(data), "size_bytes": len(data)}
        )
    metadata = {
        "schema_version": "rq2-v2-stage4m-review-package-metadata-v1",
        "status": "READY_FOR_RQ2_V2_STAGE_4_INTEGRATION_WITH_SPECIALISTS",
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "starting_head": stage4m.STAGE4M_STARTING_HEAD,
        "integrated_commits": list(stage4m.INTEGRATED_COMMITS),
        "review_scope": "TRACK_M_SPECIALIST_COMPOSITION_ONLY",
        "full_project_included": False,
        "provider_calls": 0,
        "test_executed": False,
        "rq3_access": False,
    }
    manifest = {
        "schema_version": "rq2-v2-stage4m-review-package-file-manifest-v1",
        "hash_algorithm": "SHA-256",
        "file_count": len(file_entries),
        "files": file_entries,
    }
    metadata_text = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/REVIEW_PACKAGE_METADATA.json"),
                metadata_text.encode("utf-8"),
            )
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/REVIEW_PACKAGE_FILE_MANIFEST.json"),
                manifest_text.encode("utf-8"),
            )
            for relative, data in payloads:
                archive.writestr(
                    _zip_info(f"{ARCHIVE_ROOT}/{relative}"),
                    data,
                )
        if destination.exists() and not replace:
            raise stage4m.Stage4MError("destination appeared during ZIP creation")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    archive_bytes = destination.read_bytes()
    return {
        "path": str(destination),
        "sha256": _sha256(archive_bytes),
        "size_bytes": len(archive_bytes),
        "workspace_file_count": len(files),
        "archive_member_count": len(files) + 2,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Stage 4M review ZIP.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--replace", action="store_true")
    arguments = parser.parse_args(argv)
    print(
        json.dumps(
            build_review_zip(arguments.destination, replace=arguments.replace),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
