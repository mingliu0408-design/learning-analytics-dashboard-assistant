"""Build the allowlisted, metadata-only RQ2-V2 Stage 0 review ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from . import PACKAGE_ROOT, PROJECT_ROOT


DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_0_CONTRACT_HARNESS_REVIEW_2026-08-30.zip"
)
DOC_ROOT = PROJECT_ROOT / "docs" / "thesis_mainline" / "rq2_v2"
ARCHIVE_ROOT = "RQ2_V2_STAGE_0_CONTRACT_HARNESS_REVIEW_2026-08-30"
ALLOWED_SUFFIXES = {".py", ".json", ".jsonl", ".md", ".sha256"}
MAX_MEMBER_SIZE = 1024 * 1024
FORBIDDEN_FILENAME_TOKENS = {
    "secret",
    "credential",
    "student_info",
    "chat_history",
    "local_gold",
    "private_key",
}
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*[A-Za-z0-9_-]{16,}", re.I),
)


class ReviewPackageError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def collect_review_files() -> list[Path]:
    files: list[Path] = []
    for root in (PACKAGE_ROOT, DOC_ROOT):
        if not root.is_dir():
            raise ReviewPackageError(f"review source directory missing: {root}")
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if "__pycache__" in path.parts or path.suffix not in ALLOWED_SUFFIXES:
                continue
            relative = path.relative_to(PROJECT_ROOT)
            lowered = relative.as_posix().casefold()
            if any(token in lowered for token in FORBIDDEN_FILENAME_TOKENS):
                raise ReviewPackageError(f"forbidden review member name: {relative}")
            if path.stat().st_size > MAX_MEMBER_SIZE:
                raise ReviewPackageError(f"review member exceeds size limit: {relative}")
            value = path.read_bytes()
            if any(pattern.search(value) for pattern in SECRET_PATTERNS):
                raise ReviewPackageError(f"possible secret in review member: {relative}")
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(PROJECT_ROOT).as_posix())


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
    members: list[dict[str, object]] = []
    with ZipFile(output, mode="x", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            value = path.read_bytes()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), value)
            members.append(
                {"path": relative, "size_bytes": len(value), "sha256": _sha256(value)}
            )
        manifest = {
            "schema_version": "rq2-v2-stage0-review-manifest-v1",
            "review_date": "2026-08-30",
            "scope": "RQ2_V2_STAGE_0_ONLY",
            "contains_raw_restricted_student_data": False,
            "contains_pii": False,
            "contains_api_keys_or_secrets": False,
            "contains_large_model_weights": False,
            "planned_benchmark_cases_included": 0,
            "file_count": len(members),
            "members": members,
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        archive.writestr(
            _zip_info(f"{ARCHIVE_ROOT}/REVIEW_MANIFEST.json"), manifest_bytes
        )
    return {
        "status": "PASS",
        "output": str(output),
        "source_file_count": len(members),
        "archive_member_count": len(members) + 1,
        "sha256": _sha256(output.read_bytes()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_review_zip(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

