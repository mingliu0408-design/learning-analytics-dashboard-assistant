"""Build the fail-closed, Track-D-only review ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_1_TRACK_D_R1_B4_P1_REVIEW_2026-08-30.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_1_TRACK_D_R1_B4_P1_REVIEW_2026-08-30"
ALLOWED_SUFFIXES = {".py", ".txt", ".json", ".md"}
MAX_MEMBER_SIZE = 1024 * 1024
REQUIRED_FILES = {
    "README.md",
    "STATUS.md",
    "__init__.py",
    "b4.py",
    "mock_provider.py",
    "p1.py",
    "prompt_template.txt",
    "test_track_d.py",
    "validate_track_d.py",
    "fixtures/toy_b4_fixture_v1.json",
}
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*[A-Za-z0-9_-]{16,}",
        re.I,
    ),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class ReviewPackageError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def collect_review_files() -> list[Path]:
    files: list[Path] = []
    observed: set[str] = set()
    for member_path in PACKAGE_ROOT.rglob("*"):
        if not member_path.is_file() or member_path.is_symlink():
            continue
        relative = member_path.relative_to(PACKAGE_ROOT).as_posix()
        if "__pycache__" in member_path.parts or member_path.suffix not in ALLOWED_SUFFIXES:
            continue
        if member_path.stat().st_size > MAX_MEMBER_SIZE:
            raise ReviewPackageError(f"review member exceeds size limit: {relative}")
        value = member_path.read_bytes()
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ReviewPackageError(f"possible secret in review member: {relative}")
        files.append(member_path)
        observed.add(relative)
    missing = REQUIRED_FILES - observed
    if missing:
        raise ReviewPackageError(f"required review members missing: {sorted(missing)}")
    return sorted(files, key=lambda item: item.relative_to(PACKAGE_ROOT).as_posix())


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 8, 30, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(output: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing review ZIP: {output}")
    files = collect_review_files()
    with ZipFile(output, mode="x", compression=ZIP_DEFLATED) as archive:
        for member_path in files:
            project_relative = member_path.relative_to(PROJECT_ROOT).as_posix()
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/{project_relative}"),
                member_path.read_bytes(),
            )
    return {
        "status": "PASS",
        "output": str(output),
        "archive_member_count": len(files),
        "sha256": _sha256_bytes(output.read_bytes()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_review_zip(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
