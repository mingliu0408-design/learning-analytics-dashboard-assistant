"""Build the allowlisted RQ2-V2 Stage 1 Track B review ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from . import PACKAGE_ROOT, PROJECT_ROOT


DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_1_TRACK_B_R1_B0_B1_REVIEW_2026-08-30.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_1_TRACK_B_R1_B0_B1_REVIEW_2026-08-30"
ALLOWED_PACKAGING_BRANCHES = {
    "research/rq2-v2-s1-b-b0-b1",
    "research/rq2-v2-stage1-integration",
}
ALLOWED_SUFFIXES = {".py", ".json", ".jsonl", ".md"}
MAX_MEMBER_SIZE = 1024 * 1024
FORBIDDEN_FILENAME_TOKENS = {
    "secret",
    "credential",
    "private_key",
    "student_info",
    "chat_history",
    "local_gold",
}
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*[A-Za-z0-9_-]{16,}",
        re.IGNORECASE,
    ),
)
REQUIRED_RELATIVE_FILES = {
    "README.md",
    "STATUS_REPORT.md",
    "b0_rule_router.py",
    "b1_legacy_intent_adapter.py",
    "runner.py",
    "test_track_b.py",
    "config/b0_rules_v1.json",
    "config/b1_intent_to_capability_mapping_unfrozen_v1.json",
}


class ReviewPackageError(RuntimeError):
    """Raised before or during fail-closed review packaging."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def collect_review_files() -> list[Path]:
    if not PACKAGE_ROOT.is_dir():
        raise ReviewPackageError(f"Track B package is missing: {PACKAGE_ROOT}")
    files: list[Path] = []
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
            continue
        if path.suffix not in ALLOWED_SUFFIXES:
            raise ReviewPackageError(f"unexpected Track B file type: {path.name}")
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        lowered = relative.casefold()
        if any(token in lowered for token in FORBIDDEN_FILENAME_TOKENS):
            raise ReviewPackageError(f"forbidden review member name: {relative}")
        if path.stat().st_size > MAX_MEMBER_SIZE:
            raise ReviewPackageError(f"review member exceeds size limit: {relative}")
        value = path.read_bytes()
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ReviewPackageError(f"possible secret in review member: {relative}")
        files.append(path)
    observed = {path.relative_to(PACKAGE_ROOT).as_posix() for path in files}
    missing = sorted(REQUIRED_RELATIVE_FILES - observed)
    if missing:
        raise ReviewPackageError(f"required review files are missing: {missing}")
    return sorted(files, key=lambda item: item.relative_to(PACKAGE_ROOT).as_posix())


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 8, 30, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(output: str | Path = DEFAULT_OUTPUT) -> dict[str, object]:
    destination = Path(output)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing review ZIP: {destination}")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    if branch not in ALLOWED_PACKAGING_BRANCHES:
        raise ReviewPackageError(f"unexpected packaging branch: {branch}")
    files = collect_review_files()
    members: list[dict[str, object]] = []
    with ZipFile(destination, mode="x", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            value = path.read_bytes()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), value)
            members.append(
                {"path": relative, "size_bytes": len(value), "sha256": _sha256(value)}
            )
        manifest = {
            "schema_version": "rq2-v2-stage1-track-b-r1-review-manifest-v1",
            "review_date": "2026-08-30",
            "scope": "RQ2_V2_STAGE_1_TRACK_B_R1_B0_B1_ONLY",
            "git_branch": branch,
            "git_head": head,
            "b0_predictive_fields": [
                "current_query",
                "current_page",
                "dashboard_context",
                "visible_conversation_history",
            ],
            "b0_privileged_context_states_used": False,
            "b1_mapping_status": "UNFROZEN",
            "contains_only_track_b_package_files": True,
            "contains_raw_restricted_student_data": False,
            "contains_pii": False,
            "contains_api_keys_or_secrets": False,
            "contains_large_model_weights": False,
            "contains_frozen_c0_index_or_embeddings": False,
            "provider_calls": 0,
            "network_access": False,
            "training_performed": False,
            "rq3_executed": False,
            "file_count": len(members),
            "members": members,
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/REVIEW_MANIFEST.json"), manifest_bytes)
    return {
        "status": "PASS",
        "output": str(destination),
        "source_file_count": len(members),
        "archive_member_count": len(members) + 1,
        "sha256": _sha256(destination.read_bytes()),
        "git_branch": branch,
        "git_head": head,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_review_zip(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
