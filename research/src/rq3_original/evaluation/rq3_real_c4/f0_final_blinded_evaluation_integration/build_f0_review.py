"""Build one exact-allowlist review ZIP after the single F0 artifact commit.

Reads no score/rationale or restricted-mapping content. No network or Provider
operations exist. Archive member bytes and CRCs are verified before delivery.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import zipfile

from f0_common import HERE, ROOT, RESTRICTED, DOWNLOADS, pretty, digest, durable_write_once, require, utc_now
from f0_artifacts import REVIEW_FILES, CONDITION_FILE, HUMAN_MATCH_FILE, HUMAN_AUDIT_FILE

OUTPUT_NAME = "RQ3_REAL_F0_BLINDED_EVALUATION_INTEGRATION_REVIEW_2026-09-03.zip"
FORBIDDEN_DATA_FIELDS = {"candidate_response", "provider_payload", "parsed_semantic_result", "criterion_scores",
                         "criterion_rationales", "score_record", "preserved_original_score", "preserved_original_rationale",
                         "mode_id", "scenario_id", "replay_record_id"}


def assert_score_free_metadata(value):
    if isinstance(value, dict):
        require(not set(value).intersection(FORBIDDEN_DATA_FIELDS), "REVIEW_CONTAINS_RESTRICTED_OR_RAW_SCORE_FIELD")
        for child in value.values():
            assert_score_free_metadata(child)
    elif isinstance(value, list):
        for child in value:
            assert_score_free_metadata(child)


def main():
    destination = DOWNLOADS / OUTPUT_NAME
    require(not destination.exists(), "REVIEW_ZIP_ALREADY_EXISTS")
    completion_path = HERE / "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json"
    completion_raw = completion_path.read_bytes()
    completion = json.loads(completion_raw)
    require(completion["controlled_source_access_closed"] is True, "F0_NOT_SEALED")
    require(completion["tests"] == {"tests_run": 50, "passed": 50, "failed": 0, "errors": 0, "skipped": 0}, "F0_TEST_GATE_FAILED")
    git = lambda *args: subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    head = git("rev-parse", "HEAD")
    require(git("rev-parse", "HEAD^") == completion["integrated_head"], "REVIEW_REQUIRES_EXACTLY_ONE_NEW_F0_COMMIT")
    require(git("branch", "--show-current") == completion["branch"], "REVIEW_BRANCH_CHANGED")
    require(git("status", "--short", "--untracked-files=all") == json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())["state"]["status"], "REVIEW_GIT_STATE_NOT_FROZEN")
    changed = git("diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD").splitlines()
    require(all(row.startswith("A\t" + str(HERE.relative_to(ROOT)) + "/") for row in changed), "F0_COMMIT_OUT_OF_SCOPE")
    for name in (CONDITION_FILE, HUMAN_MATCH_FILE, HUMAN_AUDIT_FILE):
        path = RESTRICTED / name
        require(subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT).returncode == 0, "RESTRICTED_OUTPUT_NOT_IGNORED")
        require(not git("ls-files", "--", str(path)), "RESTRICTED_OUTPUT_TRACKED")
    manifest_path = HERE / "F0_REVIEW_PACKAGE_ALLOWLIST_V1.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    require({row["filename"] for row in manifest["files"]} == set(REVIEW_FILES), "REVIEW_ALLOWLIST_CHANGED")
    require(len(manifest["files"]) == len(REVIEW_FILES), "REVIEW_DUPLICATE_MEMBER")
    members = {}
    for row in manifest["files"]:
        name = row["filename"]
        require("/" not in name and ".." not in name and name in REVIEW_FILES, "REVIEW_UNSAFE_MEMBER_PATH")
        raw = (HERE / name).read_bytes()
        require(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "REVIEW_MEMBER_BYTES_CHANGED: " + name)
        require(not re.search(rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", raw), "REVIEW_CREDENTIAL_PATTERN")
        if name.endswith(".json"):
            assert_score_free_metadata(json.loads(raw))
        elif name.endswith(".jsonl"):
            for line in raw.splitlines():
                if line.strip():
                    assert_score_free_metadata(json.loads(line))
        members[name] = raw
    members[manifest_path.name] = manifest_raw
    build_receipt = {"schema_version": "F0_REVIEW_PACKAGE_BUILD_RECEIPT_V1", "created_at_utc": utc_now(),
                     "working_directory": str(ROOT), "branch": completion["branch"], "starting_head": completion["starting_head"], "ending_head": head,
                     "f0_commit_count_after_required_cherry_picks": 1, "completion_receipt_sha256": digest(completion_raw),
                     "allowlist_sha256": digest(manifest_raw), "member_count": len(members) + 1,
                     "raw_human_ratings_or_rationales_included": False, "raw_judge_results_or_rationales_included": False,
                     "candidate_responses_included": False, "hmac_key_included": False, "restricted_mappings_included": False,
                     "provider_calls": 0, "network_calls": 0}
    members["REVIEW_PACKAGE_BUILD_RECEIPT_V1.json"] = pretty(build_receipt)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 3, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    raw_zip = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        require(archive.testzip() is None, "REVIEW_ZIP_CRC_FAILURE")
        require(len(archive.namelist()) == len(set(archive.namelist())) == len(members) and set(archive.namelist()) == set(members), "REVIEW_ZIP_MEMBER_SET_FAILURE")
        require(all(archive.read(name) == raw for name, raw in members.items()), "REVIEW_ZIP_MEMBER_BYTE_FAILURE")
    durable_write_once(destination, raw_zip)
    with zipfile.ZipFile(destination) as archive:
        require(archive.testzip() is None and set(archive.namelist()) == set(members), "WRITTEN_REVIEW_ZIP_INTEGRITY_FAILURE")
        require(all(archive.read(name) == raw for name, raw in members.items()), "WRITTEN_REVIEW_ZIP_BYTE_FAILURE")
    print(json.dumps({"status": "REVIEW_ZIP_VERIFIED", "path": str(destination), "sha256": digest(raw_zip), "bytes": len(raw_zip),
                      "members": len(members), "ending_head": head, "crc_failures": 0, "byte_mismatches": 0, "forbidden_members": 0}))


if __name__ == "__main__":
    main()
