"""Create the allowlisted review ZIP for the isolated Track C package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_1_TRACK_C_R1_B2_B3_REVIEW_2026-08-30.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_1_TRACK_C_R1_B2_B3_REVIEW_2026-08-30"
ALLOWED_SUFFIXES = {".py", ".json", ".md", ".txt"}
FORBIDDEN_NAME_TOKENS = {
    "secret",
    "credential",
    "private_key",
    "local_gold",
    "student_record",
    "model.safetensors",
}
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*[A-Za-z0-9_-]{16,}",
        re.I,
    ),
)


class ReviewPackageError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ReviewPackageError(f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def collect_review_files() -> list[Path]:
    files: list[Path] = []
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
            continue
        if path.suffix not in ALLOWED_SUFFIXES:
            raise ReviewPackageError(f"unexpected Track C review file type: {path.name}")
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        lowered = relative.casefold()
        if any(token in lowered for token in FORBIDDEN_NAME_TOKENS):
            raise ReviewPackageError(f"forbidden review filename: {relative}")
        value = path.read_bytes()
        if len(value) > 1024 * 1024:
            raise ReviewPackageError(f"review file exceeds 1 MiB: {relative}")
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ReviewPackageError(f"possible secret in review file: {relative}")
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(PACKAGE_ROOT).as_posix())


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 8, 30, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(output: str | Path = DEFAULT_OUTPUT) -> dict[str, object]:
    target = Path(output)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing review ZIP: {target}")
    if _git("status", "--porcelain"):
        raise ReviewPackageError("review ZIP requires a clean committed worktree")
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    files = collect_review_files()
    members: list[dict[str, object]] = []
    with ZipFile(target, mode="x", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            value = path.read_bytes()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), value)
            members.append(
                {"path": relative, "size_bytes": len(value), "sha256": _sha256(value)}
            )
        manifest = {
            "schema_version": "rq2-v2-stage1-track-c-r1-review-manifest-v1",
            "scope": "RQ2_V2_STAGE_1_TRACK_C_R1_B2_B3_ONLY",
            "branch": branch,
            "commit_head": head,
            "primary_feature_profile": "R2V2_PRIMARY_SEMANTIC_INPUT_V1",
            "learning_curve_family_sampling_method": (
                "SEEDED_SIGNATURE_ROUND_ROBIN_V1"
            ),
            "contains_restricted_data": False,
            "contains_pii": False,
            "contains_secrets_or_api_keys": False,
            "contains_model_weights": False,
            "contains_frozen_embedding_matrix": False,
            "provider_calls": 0,
            "network_access": False,
            "real_data_training": False,
            "future_final_test_training_or_evaluation": False,
            "rq3_executed": False,
            "winner_claim": False,
            "source_file_count": len(members),
            "members": members,
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        archive.writestr(
            _zip_info(f"{ARCHIVE_ROOT}/REVIEW_MANIFEST.json"), manifest_bytes
        )
    return {
        "status": "PASS",
        "output": str(target),
        "source_file_count": len(members),
        "archive_member_count": len(members) + 1,
        "branch": branch,
        "commit_head": head,
        "sha256": _sha256(target.read_bytes()),
    }


def main() -> int:
    print(json.dumps(build_review_zip(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
