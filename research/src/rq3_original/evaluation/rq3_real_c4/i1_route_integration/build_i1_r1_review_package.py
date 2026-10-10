#!/usr/bin/env python3
"""Create the post-commit, review-only I1-R1 ZIP with an explicit allowlist."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.generation_package_validator_v2 import (
    validate_zip as validate_generation_zip,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_r1_common import (
    BRANCH,
    HERE,
    NEW_PACKAGE_PATHS,
    OLD_PACKAGE_PATHS,
    OLD_PACKAGE_SHA256,
    ROOT,
    STARTING_HEAD,
    git,
    sha256_file,
)


OUTPUT = Path(
    "/Users/liuming/Downloads/RQ3_REAL_I1_R1_PAYLOAD_RUNNER_REPAIR_REVIEW_2026-09-01.zip"
)
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
PREFIX = "RQ3_REAL_I1_R1_REVIEW"
COMMIT_SUBJECT = "RQ3-REAL-I1-R1: sanitize generation payloads and add fail-closed runner"
SOURCE_ALLOWLIST = (
    "evaluation/rq3_real_c4/i1_route_integration/STATUS.md",
    "evaluation/rq3_real_c4/i1_route_integration/C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT_V2.md",
    "evaluation/rq3_real_c4/i1_route_integration/C4_REAL_PRE_GENERATION_PAYLOAD_AND_RUNNER_REPAIR.md",
    "evaluation/rq3_real_c4/i1_route_integration/build_generation_packages_v2.py",
    "evaluation/rq3_real_c4/i1_route_integration/build_i1_r1_artifacts.py",
    "evaluation/rq3_real_c4/i1_route_integration/build_i1_r1_review_package.py",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_condition_payload_rebuild_summary_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_package_manifest_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_package_supersession_v1.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_request_deduplication_summary_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_shard_summary_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_i1_r1_scientific_preservation_manifest_v1.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_i1_r1_status_v1.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_provider_evidence_projection_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_provider_payload_hygiene_audit_v1.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_provider_projection_v1_v2_diff_audit.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_restricted_mapping_metadata_v2.json",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_unique_generation_request_manifest_frozen_v2.jsonl",
    "evaluation/rq3_real_c4/i1_route_integration/generation_execution_runner_v2.py",
    "evaluation/rq3_real_c4/i1_route_integration/generation_package_offline_tests_v2.py",
    "evaluation/rq3_real_c4/i1_route_integration/generation_package_validator_v2.py",
    "evaluation/rq3_real_c4/i1_route_integration/i1_r1_common.py",
    "evaluation/rq3_real_c4/i1_route_integration/tests/test_i1_r1_repair.py",
    "utils/c4_real_adapters.py",
)
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _verify_postcommit_state() -> str:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("review builder must run from the repository root")
    if git("branch", "--show-current") != BRANCH:
        raise ValueError("review builder branch mismatch")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("review builder requires a clean tracked/untracked worktree")
    ending_head = git("rev-parse", "HEAD")
    if ending_head == STARTING_HEAD:
        raise ValueError("I1-R1 commit is missing")
    if git("rev-list", "--count", f"{STARTING_HEAD}..{ending_head}") != "1":
        raise ValueError("I1-R1 must contain exactly one additional commit")
    if git("show", "-s", "--format=%s", ending_head) != COMMIT_SUBJECT:
        raise ValueError("I1-R1 commit subject mismatch")
    changed = set(
        git("diff", "--name-only", f"{STARTING_HEAD}..{ending_head}").splitlines()
    )
    if changed != set(SOURCE_ALLOWLIST):
        raise ValueError(
            "review source allowlist does not exactly match the I1-R1 commit: "
            + repr(sorted(changed ^ set(SOURCE_ALLOWLIST)))
        )
    if any("restricted_internal/" in path for path in changed):
        raise ValueError("restricted material entered the commit")
    return ending_head


def _generation_package_inventory() -> list[Mapping[str, Any]]:
    manifest = json.loads(
        (HERE / "c4_real_generation_package_manifest_v2.json").read_text(encoding="utf-8")
    )
    by_shard = {row["shard"]: row for row in manifest["packages"]}
    inventory = []
    for shard in "ABC":
        path = NEW_PACKAGE_PATHS[shard]
        report = validate_generation_zip(path)
        observed = sha256_file(path)
        if observed != by_shard[shard]["sha256"]:
            raise ValueError(f"R2 generation package {shard} manifest mismatch")
        inventory.append(
            {
                "shard": shard,
                "path": str(path),
                "sha256": observed,
                "byte_count": path.stat().st_size,
                "request_count": report["request_count"],
                "estimated_input_tokens": report["estimated_input_tokens"],
                "maximum_physical_attempts": report["maximum_physical_attempts"],
                "validator_status": report["status"],
                "included_as_nested_zip": False,
            }
        )
    return inventory


def _old_package_inventory() -> list[Mapping[str, Any]]:
    inventory = []
    for shard in "ABC":
        path = OLD_PACKAGE_PATHS[shard]
        observed = sha256_file(path)
        if observed != OLD_PACKAGE_SHA256[shard]:
            raise ValueError(f"old R1 generation package {shard} changed")
        inventory.append(
            {
                "shard": shard,
                "path": str(path),
                "sha256": observed,
                "status": "SUPERSEDED_UNEXECUTED_BY_I1_R1",
                "included_as_nested_zip": False,
            }
        )
    return inventory


def _write_review_zip(path: Path, members: Mapping[str, bytes]) -> None:
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compresslevel=9)


def _validate_review_zip(path: Path, expected_names: set[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise ValueError("review ZIP member allowlist mismatch")
        if any(name.endswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("review ZIP contains an unsafe member")
        manifest = json.loads(archive.read(f"{PREFIX}/REVIEW_MANIFEST.json"))
        expected_hashes = manifest["member_sha256_excluding_manifest"]
        if set(expected_hashes) != expected_names - {f"{PREFIX}/REVIEW_MANIFEST.json"}:
            raise ValueError("review member hash allowlist mismatch")
        for name, expected in expected_hashes.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"review member hash mismatch: {name}")
        forbidden_names = (
            "restricted_internal",
            "hmac_key.bin",
            "response_to_condition_mapping",
            "response_to_mode_mapping",
            "response_to_scenario_mapping",
            ".sqlite",
            "generation_attempt_journal",
            "generation_terminal_journal",
        )
        if any(token in name.casefold() for name in names for token in forbidden_names):
            raise ValueError("review ZIP contains a prohibited private/execution member")
        if _SECRET.search(b"\n".join(archive.read(name) for name in names)):
            raise ValueError("review ZIP contains a credential-like value")


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite review ZIP: {OUTPUT}")
    ending_head = _verify_postcommit_state()
    generation_packages = _generation_package_inventory()
    old_packages = _old_package_inventory()
    source_members = {
        f"{PREFIX}/sources/{path}": (ROOT / path).read_bytes() for path in SOURCE_ALLOWLIST
    }
    patch = subprocess.run(
        ["git", "show", "--format=fuller", "--no-ext-diff", "--binary", ending_head],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    readme = (
        "# RQ3-REAL-C4 I1-R1 internal review package\n\n"
        "This is a review-only source and audit package. It contains no HMAC key, raw restricted mapping, "
        "generation response, execution journal, Judge output, score, database, API credential, or nested "
        "generation-package ZIP. The external R1/R2 package paths and hashes are recorded only as inventory.\n\n"
        f"Starting HEAD: `{STARTING_HEAD}`. Ending HEAD: `{ending_head}`.\n"
    ).encode("utf-8")
    members: dict[str, bytes] = {
        **source_members,
        f"{PREFIX}/README.md": readme,
        f"{PREFIX}/I1_R1_COMMIT.patch": patch,
    }
    manifest = {
        "schema_version": "c4-real-i1-r1-review-manifest-v1",
        "status": "REVIEW_ONLY_COMPLETE_NO_EXECUTION_AUTHORITY",
        "starting_head": STARTING_HEAD,
        "ending_head": ending_head,
        "branch": BRANCH,
        "commit_subject": COMMIT_SUBJECT,
        "generation_packages_r2": generation_packages,
        "original_packages_r1": old_packages,
        "source_allowlist": list(SOURCE_ALLOWLIST),
        "member_sha256_excluding_manifest": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(members.items())
        },
        "raw_hmac_key_included": False,
        "raw_restricted_mapping_included": False,
        "generation_response_or_execution_output_included": False,
        "judge_or_scoring_output_included": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }
    members[f"{PREFIX}/REVIEW_MANIFEST.json"] = _json_bytes(manifest)
    with tempfile.TemporaryDirectory(prefix=".c4-real-i1-r1-review-", dir=OUTPUT.parent) as temporary:
        staged = Path(temporary) / OUTPUT.name
        _write_review_zip(staged, members)
        _validate_review_zip(staged, set(members))
        os.link(staged, OUTPUT)
        os.chmod(OUTPUT, 0o644)
    print(
        json.dumps(
            {
                "status": "PASS_REVIEW_ONLY_ZIP_CREATED",
                "path": str(OUTPUT),
                "sha256": sha256_file(OUTPUT),
                "member_count": len(members),
                "ending_head": ending_head,
                "provider_calls": 0,
                "generation_calls": 0,
                "judge_calls": 0,
                "scoring_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
