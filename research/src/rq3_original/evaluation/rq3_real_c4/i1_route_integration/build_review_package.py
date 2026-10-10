#!/usr/bin/env python3
"""Build the explicit, review-only RQ3-REAL-C4 I1 handoff ZIP."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any, Mapping
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.i1_common import (
    BRANCH,
    COMMIT_MAPPING,
    HERE,
    ROOT,
    STARTING_HEAD,
    sha256_file,
)


OUTPUT = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_I1_ROUTE_INTEGRATION_MECHANISM_REPLAY_REVIEW_2026-09-01.zip"
)
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
I1_PREFIX = Path("evaluation/rq3_real_c4/i1_route_integration")
REVIEW_FILES = (
    Path("utils/c4_real_adapters.py"),
    Path("utils/c4_real_contracts.py"),
    Path("utils/c4_real_service.py"),
    I1_PREFIX / "STATUS.md",
    I1_PREFIX / "c4_real_i1_status_v1.json",
    I1_PREFIX / "c4_real_i1_source_manifest_v1.json",
    I1_PREFIX / "c4_real_p3_route_source_manifest_v1.json",
    I1_PREFIX / "c4_real_p3_routes_frozen_v1.csv",
    I1_PREFIX / "c4_real_p3_routes_frozen_v1.jsonl",
    I1_PREFIX / "c4_real_precomputed_p3_route_cache_frozen_v1.json",
    I1_PREFIX / "c4_real_b4_unused_route_bits_source_audit_v1.json",
    I1_PREFIX / "c4_real_memory_preconditioning_summary_v1.json",
    I1_PREFIX / "c4_real_condition_mechanism_records_frozen_v1.jsonl",
    I1_PREFIX / "c4_real_condition_execution_traces_frozen_v1.jsonl",
    I1_PREFIX / "c4_real_mechanism_replay_summary_v1.json",
    I1_PREFIX / "C4_REAL_MECHANISM_REPLAY_REPORT.md",
    I1_PREFIX / "c4_real_condition_applicability_maps_frozen_v1.jsonl",
    I1_PREFIX / "c4_real_provider_evidence_projection_v1.json",
    I1_PREFIX / "c4_real_provider_payload_privacy_and_leakage_audit_v1.json",
    I1_PREFIX / "C4_REAL_PROVIDER_PAYLOAD_PRIVACY_AND_LEAKAGE_AUDIT.md",
    I1_PREFIX / "c4_real_generation_schema_v2_provider_compatible.json",
    I1_PREFIX / "c4_real_generation_configuration_frozen_v2.json",
    I1_PREFIX / "C4_REAL_GENERATION_SCHEMA_COMPATIBILITY_NOTE.md",
    I1_PREFIX / "c4_real_generation_request_deduplication_summary_v1.json",
    I1_PREFIX / "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT.md",
    I1_PREFIX / "c4_real_generation_shard_summary_v1.json",
    I1_PREFIX / "c4_real_restricted_mapping_metadata_v1.json",
    I1_PREFIX / "c4_real_generation_package_manifest_v1.json",
    I1_PREFIX / "c4_real_judge_schema_v2_provider_compatible.json",
    I1_PREFIX / "c4_real_judge_prompt_v2_provider_compatible.txt",
    I1_PREFIX / "c4_real_judge_configuration_frozen_v2.json",
    I1_PREFIX / "C4_REAL_JUDGE_SCHEMA_COMPATIBILITY_NOTE.md",
    I1_PREFIX / "judge_transport.py",
    I1_PREFIX / "i1_common.py",
    I1_PREFIX / "build_i1_artifacts.py",
    I1_PREFIX / "build_generation_packages.py",
    I1_PREFIX / "build_review_package.py",
    I1_PREFIX / "generation_execution_runner_v1.py",
    I1_PREFIX / "generation_package_validator_v1.py",
    I1_PREFIX / "generation_package_offline_tests_v1.py",
    I1_PREFIX / "tests/__init__.py",
    I1_PREFIX / "tests/test_i1_route_integration.py",
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.create_system = 3
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _verify_repository_state() -> str:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("review builder must run from the repository root")
    if _git("branch", "--show-current") != BRANCH:
        raise ValueError("review branch mismatch")
    if _git("status", "--short"):
        raise ValueError("review ZIP requires a clean committed worktree")
    history = _git("rev-list", "--reverse", f"{STARTING_HEAD}..HEAD").splitlines()
    if history[:4] != [cherry for _, cherry in COMMIT_MAPPING] or len(history) != 5:
        raise ValueError("review ZIP requires exactly four integrations plus one I1 commit")
    return _git("rev-parse", "HEAD")


def _tracked_file_bytes() -> dict[str, bytes]:
    tracked = set(_git("ls-files").splitlines())
    expected = {path.as_posix() for path in REVIEW_FILES}
    missing = sorted(expected - tracked)
    if missing:
        raise ValueError(f"review allowlist contains untracked files: {missing}")
    restricted_tracked = sorted(
        name
        for name in tracked
        if name.startswith((I1_PREFIX / "restricted_internal").as_posix() + "/")
        and not name.endswith("/.gitignore")
    )
    if restricted_tracked:
        raise ValueError("restricted mapping or key is tracked")
    output: dict[str, bytes] = {}
    for relative in REVIEW_FILES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"review source is not a regular file: {relative}")
        output[relative.as_posix()] = path.read_bytes()
    return output


def _validate_member_names(names: set[str]) -> None:
    for name in names:
        pure = PurePosixPath(name)
        folded = name.casefold()
        if pure.is_absolute() or ".." in pure.parts or name.endswith("/"):
            raise ValueError("review ZIP contains an unsafe member name")
        if "restricted_internal" in pure.parts:
            raise ValueError("review ZIP contains restricted internal material")
        if folded.endswith((".sqlite", ".sqlite3", ".db")):
            raise ValueError("review ZIP contains a database")
        if "generation_terminal" in folded or "generation_attempt" in folded:
            raise ValueError("review ZIP contains generation execution results")
        if "judge_output" in folded or "judge_terminal" in folded:
            raise ValueError("review ZIP contains Judge output")


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite review ZIP: {OUTPUT}")
    ending_head = _verify_repository_state()
    members = _tracked_file_bytes()
    key_path = HERE / "restricted_internal/c4_real_i1_blinding_hmac_key.bin"
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("restricted HMAC key is unavailable or malformed")
    if any(key in content for content in members.values()):
        raise ValueError("raw HMAC key leaked into a tracked review member")

    package_manifest = json.loads(
        (HERE / "c4_real_generation_package_manifest_v1.json").read_text(encoding="utf-8")
    )
    review_readme = (
        "# RQ3-REAL-C4 I1 internal review handoff\n\n"
        "This ZIP is review-only. It does not authorize response generation, Judge execution, scoring, or deployment.\n\n"
        f"Final committed I1 HEAD: `{ending_head}`. The raw HMAC key, restricted mappings, SQLite files, "
        "course source documents, credentials, generated responses, and Judge outputs are excluded.\n"
    ).encode("utf-8")
    members["REVIEW_README.md"] = review_readme
    manifest: Mapping[str, Any] = {
        "schema_version": "c4-real-i1-review-package-manifest-v1",
        "status": "PASS_REVIEW_ONLY_ALLOWLIST",
        "branch": BRANCH,
        "starting_head": STARTING_HEAD,
        "ending_head": ending_head,
        "integrated_commit_mapping": [
            {
                "order": index,
                "original_commit": original,
                "cherry_picked_commit": cherry,
            }
            for index, (original, cherry) in enumerate(COMMIT_MAPPING, 1)
        ],
        "generation_packages": package_manifest["packages"],
        "member_sha256_excluding_manifest": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(members.items())
        },
        "raw_hmac_key_included": False,
        "restricted_mapping_included": False,
        "sqlite_database_included": False,
        "course_source_document_included": False,
        "api_credential_included": False,
        "generated_response_included": False,
        "judge_output_included": False,
    }
    members["REVIEW_MANIFEST.json"] = _json_bytes(manifest)
    expected_names = set(members)
    _validate_member_names(expected_names)

    with tempfile.TemporaryDirectory(prefix=".c4-real-review-", dir=OUTPUT.parent) as temporary:
        staged = Path(temporary) / OUTPUT.name
        with zipfile.ZipFile(
            staged,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for name, content in sorted(members.items()):
                archive.writestr(_zip_info(name), content, compresslevel=9)
        with zipfile.ZipFile(staged) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected_names:
                raise ValueError("review ZIP member allowlist mismatch")
            _validate_member_names(set(names))
            for name, expected in members.items():
                if archive.read(name) != expected:
                    raise ValueError(f"review ZIP byte mismatch: {name}")
        if key in staged.read_bytes():
            raise ValueError("raw HMAC key leaked into the review ZIP")
        os.link(staged, OUTPUT)
        os.chmod(OUTPUT, 0o644)

    result = {
        "status": "PASS_REVIEW_ONLY_ALLOWLIST",
        "path": str(OUTPUT),
        "sha256": sha256_file(OUTPUT),
        "byte_count": OUTPUT.stat().st_size,
        "member_count": len(expected_names),
        "ending_head": ending_head,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
