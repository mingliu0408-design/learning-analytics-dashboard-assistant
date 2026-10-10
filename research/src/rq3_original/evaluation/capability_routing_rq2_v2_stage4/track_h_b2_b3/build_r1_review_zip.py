"""Build the deterministic review-only ZIP for the committed R1 amendment."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
TRACK_RELATIVE = Path(
    "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3"
)
STARTING_HEAD = "7be7abd4cb72ee08a4bfacea0301e648c298b3cd"
EXPECTED_BRANCH = "research/rq2-v2-stage4-h-b2-b3"
EXPECTED_SUBJECT = "RQ2-V2 Stage 4H-R1: add routing sanity and separability audit"
PRIOR_IDENTITY_SHA256 = (
    "8b2e1142f6ab68947a18c3f4698ce9956d8876d85b8ad7d4cf320c2c05de0aca"
)
ZIP_PATH = Path(
    "/Users/liuming/Downloads/"
    "RQ2_V2_STAGE_4H_R1_SANITY_AUDIT_REVIEW_2026-08-31.zip"
)
ZIP_ROOT = "RQ2_V2_STAGE_4H_R1_SANITY_AUDIT_REVIEW_2026-08-31"
FIXED_TIMESTAMP = (2026, 8, 31, 0, 0, 0)


class ReviewZipError(RuntimeError):
    pass


def run_git(arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReviewZipError(
            f"git {' '.join(arguments)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def main() -> None:
    if Path.cwd().resolve() != REPO_ROOT:
        raise ReviewZipError(f"wrong cwd: {Path.cwd()} != {REPO_ROOT}")
    branch = run_git(["branch", "--show-current"])
    head = run_git(["rev-parse", "HEAD"])
    parent = run_git(["rev-parse", "HEAD^"])
    subject = run_git(["show", "-s", "--format=%s", "HEAD"])
    status = run_git(["status", "--short"])
    commit_count = run_git(["rev-list", "--count", f"{STARTING_HEAD}..HEAD"])
    if branch != EXPECTED_BRANCH:
        raise ReviewZipError(f"unexpected branch: {branch}")
    if parent != STARTING_HEAD or commit_count != "1":
        raise ReviewZipError(
            f"review HEAD is not exactly one commit after {STARTING_HEAD}"
        )
    if subject != EXPECTED_SUBJECT:
        raise ReviewZipError(f"unexpected commit subject: {subject}")
    if status:
        raise ReviewZipError(f"worktree is not clean:\n{status}")
    if ZIP_PATH.exists():
        raise ReviewZipError(f"refusing to overwrite existing review ZIP: {ZIP_PATH}")

    name_status = run_git(
        ["diff", "--name-status", f"{STARTING_HEAD}..{head}", "--"]
    ).splitlines()
    if not name_status:
        raise ReviewZipError("R1 commit contains no files")
    changed: list[str] = []
    prefix = TRACK_RELATIVE.as_posix() + "/"
    for line in name_status:
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] != "A":
            raise ReviewZipError(
                "R1 commit must add new files only; prior artifacts are immutable"
            )
        relative = parts[1]
        if not relative.startswith(prefix):
            raise ReviewZipError(f"R1 path is outside authorized Track H scope: {relative}")
        changed.append(relative)

    prior_paths = set(
        run_git(
            [
                "ls-tree",
                "-r",
                "--name-only",
                STARTING_HEAD,
                "--",
                TRACK_RELATIVE.as_posix(),
            ]
        ).splitlines()
    )
    if len(prior_paths) != 25 or prior_paths.intersection(changed):
        raise ReviewZipError("R1 changed set overlaps immutable prior Track H files")

    entries: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for relative in sorted(changed, key=lambda value: value.encode("utf-8")):
        path = REPO_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ReviewZipError(f"review member is not a regular file: {relative}")
        data = path.read_bytes()
        payloads[relative] = data
        entries.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )

    manifest = {
        "schema_version": "rq2-v2-stage4h-r1-sanity-audit-review-zip-v1",
        "status": "READY_FOR_STAGE_4H_DEV_REVIEW_WITH_SANITY_AUDIT",
        "working_directory": str(REPO_ROOT),
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "ending_head": head,
        "commit_subject": subject,
        "commit_count_from_start": 1,
        "change_mode": "ADDITIONS_ONLY",
        "prior_track_h_file_count": 25,
        "prior_track_h_canonical_identity_sha256": PRIOR_IDENTITY_SHA256,
        "prior_track_h_files_modified": 0,
        "review_file_count": len(entries),
        "files": entries,
        "verification": {
            "stage4h_r1_diagnostic_tests": "15/15 PASS",
            "original_stage4h_tests": "24/24 PASS",
            "stage4_dev_protocol_validator": "43/43 PASS",
            "stage4_dev_protocol_tests": "19/19 PASS",
        },
        "boundaries": {
            "b2_b3_retraining_or_recalibration": False,
            "model_threshold_prediction_or_prior_metric_changes": 0,
            "held_out_access_count": 0,
            "provider_call_count": 0,
            "new_learned_model_count": 0,
            "p1_or_rq3_work_performed": False,
        },
        "interpretation_boundary": (
            "Descriptive DEV-only diagnostic amendment; no held-out evaluation, "
            "model repair, final generalization claim, or follow-on authorization."
        ),
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    expected_members = {
        f"{ZIP_ROOT}/{relative}" for relative in payloads
    } | {f"{ZIP_ROOT}/REVIEW_ZIP_MANIFEST.json"}

    with ZIP_PATH.open("xb") as output_handle:
        with zipfile.ZipFile(
            output_handle,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(
                zip_info(f"{ZIP_ROOT}/REVIEW_ZIP_MANIFEST.json"), manifest_bytes
            )
            for relative in sorted(payloads, key=lambda value: value.encode("utf-8")):
                member = str(PurePosixPath(ZIP_ROOT) / PurePosixPath(relative))
                archive.writestr(zip_info(member), payloads[relative])

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        if set(archive.namelist()) != expected_members:
            raise ReviewZipError("review ZIP member allowlist mismatch")
        if archive.testzip() is not None:
            raise ReviewZipError("review ZIP CRC verification failed")
        if json.loads(
            archive.read(f"{ZIP_ROOT}/REVIEW_ZIP_MANIFEST.json")
        ) != manifest:
            raise ReviewZipError("review ZIP manifest round-trip mismatch")
        for entry in entries:
            member = f"{ZIP_ROOT}/{entry['path']}"
            if sha256_bytes(archive.read(member)) != entry["sha256"]:
                raise ReviewZipError(f"review ZIP member hash mismatch: {member}")

    print(
        json.dumps(
            {
                "status": manifest["status"],
                "zip_path": str(ZIP_PATH),
                "zip_sha256": sha256_file(ZIP_PATH),
                "zip_size_bytes": ZIP_PATH.stat().st_size,
                "member_count": len(expected_members),
                "starting_head": STARTING_HEAD,
                "ending_head": head,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
