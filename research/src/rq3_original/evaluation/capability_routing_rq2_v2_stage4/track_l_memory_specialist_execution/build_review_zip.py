"""Build the strict review-only ZIP after the single Stage 4L commit."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from .memory_specialist_common import (
    EXPECTED_BRANCH,
    EXPECTED_STARTING_HEAD,
    OUTPUT_SHA256_MANIFEST_PATH,
    REPO_ROOT,
    TRACK_DIR,
    TRACK_RELATIVE_PREFIX,
    canonical_json,
    load_json,
    sha256_file,
)


ZIP_PATH = Path(
    "/Users/liuming/Downloads/"
    "RQ2_V2_STAGE_4L_MEMORY_SPECIALIST_DEV_EXECUTION_REVIEW_2026-08-31.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_4L_MEMORY_SPECIALIST_DEV_EXECUTION_REVIEW_2026-08-31"


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 31, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def build() -> dict[str, object]:
    if ZIP_PATH.exists():
        raise RuntimeError(f"Review ZIP already exists; refusing overwrite: {ZIP_PATH}")
    branch = _git("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"Unexpected branch: {branch}")
    ending_head = _git("rev-parse", "HEAD")
    if ending_head == EXPECTED_STARTING_HEAD:
        raise RuntimeError("Stage 4L commit has not been created")
    if _git("rev-list", "--count", f"{EXPECTED_STARTING_HEAD}..{ending_head}") != "1":
        raise RuntimeError("Stage 4L ending HEAD is not exactly one commit beyond start")
    if _git("rev-parse", f"{ending_head}^") != EXPECTED_STARTING_HEAD:
        raise RuntimeError("Stage 4L commit parent differs from starting HEAD")
    if _git("status", "--short", "--untracked-files=all"):
        raise RuntimeError("Worktree must be clean before review ZIP creation")

    changed = _git(
        "diff", "--name-only", EXPECTED_STARTING_HEAD, ending_head
    ).splitlines()
    if not changed or any(not path.startswith(TRACK_RELATIVE_PREFIX) for path in changed):
        raise RuntimeError("Committed paths are not confined exactly to Track L")

    output_manifest = load_json(OUTPUT_SHA256_MANIFEST_PATH)
    entries = list(output_manifest["files"])
    tracked_relative = {str(entry["path"]) for entry in entries}
    tracked_relative.add(OUTPUT_SHA256_MANIFEST_PATH.name)
    committed_relative = {
        Path(path).relative_to(TRACK_RELATIVE_PREFIX).as_posix() for path in changed
    }
    if committed_relative != tracked_relative:
        missing = sorted(committed_relative - tracked_relative)
        extra = sorted(tracked_relative - committed_relative)
        raise RuntimeError(
            f"Output manifest/commit file set differs; missing={missing}, extra={extra}"
        )

    archive_files: list[dict[str, str]] = []
    for relative in sorted(tracked_relative):
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise RuntimeError(f"Unsafe review path: {relative}")
        path = TRACK_DIR / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Review file missing or unsafe: {relative}")
        archive_files.append({"path": relative, "sha256": sha256_file(path)})

    review_manifest = {
        "schema_version": "rq2-v2-stage4-l-review-zip-manifest-v1",
        "review_only": True,
        "starting_head": EXPECTED_STARTING_HEAD,
        "ending_head": ending_head,
        "branch": branch,
        "file_count": len(archive_files),
        "files": archive_files,
        "scope": "TRACK_L_MEMORY_SPECIALIST_EXECUTION_ONLY",
        "excluded": [
            "full_project",
            "credentials",
            "future_held_out_inputs_or_gold",
            "rag_specialist_execution",
            "joint_b4_case_predictions_and_errors",
            "composition_outputs",
        ],
    }
    temporary = ZIP_PATH.with_name(ZIP_PATH.name + ".tmp")
    if temporary.exists():
        raise RuntimeError(f"Temporary review ZIP already exists: {temporary}")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in archive_files:
            relative = entry["path"]
            data = (TRACK_DIR / relative).read_bytes()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), data)
        manifest_bytes = (
            json.dumps(review_manifest, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
        archive.writestr(
            _zip_info(f"{ARCHIVE_ROOT}/REVIEW_ZIP_CONTENTS.json"),
            manifest_bytes,
        )
    temporary.replace(ZIP_PATH)
    return {
        "status": "PASS_REVIEW_ZIP_CREATED",
        "zip_path": str(ZIP_PATH),
        "zip_sha256": sha256_file(ZIP_PATH),
        "review_file_count": len(archive_files),
        "starting_head": EXPECTED_STARTING_HEAD,
        "ending_head": ending_head,
        "branch": branch,
    }


def main() -> int:
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
