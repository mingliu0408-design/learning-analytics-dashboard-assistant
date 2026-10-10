"""Build the deterministic review-only ZIP after the single Stage 4H commit."""

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
STARTING_HEAD = "1838a5d85db2dcaeba481c7404c36cbfbc94215e"
EXPECTED_BRANCH = "research/rq2-v2-stage4-h-b2-b3"
EXPECTED_SUBJECT = "RQ2-V2 Stage 4H: calibrate prototype and OvR routers on DEV"
ZIP_PATH = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_4H_B2_B3_DEV_REVIEW_2026-08-31.zip"
)
ZIP_ROOT = "RQ2_V2_STAGE_4H_B2_B3_DEV_REVIEW_2026-08-31"
FIXED_TIMESTAMP = (2026, 8, 31, 0, 0, 0)


class ReviewZipError(RuntimeError):
    pass


def run_git(arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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

    changed = run_git(
        ["diff", "--name-only", f"{STARTING_HEAD}..{head}", "--"]
    ).splitlines()
    track_prefix = TRACK_RELATIVE.as_posix() + "/"
    if not changed or any(not path.startswith(track_prefix) for path in changed):
        raise ReviewZipError("commit changes are not confined to the authorized Track H path")

    tracked = run_git(
        ["ls-tree", "-r", "--name-only", "HEAD", "--", TRACK_RELATIVE.as_posix()]
    ).splitlines()
    if not tracked:
        raise ReviewZipError("no committed Track H review files found")
    if set(changed) != set(tracked):
        raise ReviewZipError("review scope differs from the one-commit Track H change set")
    prohibited_suffixes = {".safetensors", ".bin", ".pt", ".pth", ".ckpt"}
    if any(Path(path).suffix.lower() in prohibited_suffixes for path in tracked):
        raise ReviewZipError("review scope contains a prohibited model-weight suffix")

    entries: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for relative in sorted(tracked, key=lambda value: value.encode("utf-8")):
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
        "schema_version": "rq2-v2-stage4h-b2-b3-dev-review-zip-manifest-v1",
        "status": "READY_FOR_STAGE_4H_DEV_REVIEW",
        "working_directory": str(REPO_ROOT),
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "ending_head": head,
        "commit_subject": subject,
        "commit_count_from_start": 1,
        "scope": TRACK_RELATIVE.as_posix(),
        "review_file_count": len(entries),
        "files": entries,
        "verification": {
            "stage4h_unit_tests": "24/24 PASS",
            "stage4_dev_protocol_validator": "43/43 PASS",
            "stage4_dev_protocol_unit_tests": "19/19 PASS",
        },
        "boundaries": {
            "held_out_access_count": 0,
            "provider_call_count": 0,
            "network_call_count": 0,
            "model_download_count": 0,
            "mpnet_weight_files_included": 0,
            "p1_or_rq3_work_performed": False,
        },
        "interpretation_boundary": (
            "DEV-only technical review package; no held-out evaluation, final "
            "generalization, deployment, or follow-on authorization is implied."
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
        observed_members = set(archive.namelist())
        if observed_members != expected_members:
            raise ReviewZipError("review ZIP member allowlist mismatch")
        if archive.testzip() is not None:
            raise ReviewZipError("review ZIP CRC verification failed")
        loaded_manifest = json.loads(
            archive.read(f"{ZIP_ROOT}/REVIEW_ZIP_MANIFEST.json")
        )
        if loaded_manifest != manifest:
            raise ReviewZipError("review ZIP manifest round-trip mismatch")
        for entry in entries:
            member = f"{ZIP_ROOT}/{entry['path']}"
            if sha256_bytes(archive.read(member)) != entry["sha256"]:
                raise ReviewZipError(f"review ZIP member hash mismatch: {member}")

    print(
        json.dumps(
            {
                "status": "READY_FOR_STAGE_4H_DEV_REVIEW",
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
