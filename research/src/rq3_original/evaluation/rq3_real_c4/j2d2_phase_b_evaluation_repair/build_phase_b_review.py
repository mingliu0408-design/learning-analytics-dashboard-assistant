#!/usr/bin/env python3
"""Export only score-free review artifacts after the single Phase-B commit."""

import csv
import io
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

from phase_b_sources import ROOT, HERE, DOWNLOADS, KEY_PATH, KEY_COMMITMENT, pretty, digest, require
from build_phase_b_repair import durable_write_once, zip_bytes

REVIEW_FILENAME = "RQ3_REAL_J2D2_R1_PHASE_B_EVALUATION_REPAIR_REVIEW_2026-09-02.zip"
ALLOWED = frozenset({
    "J2D2_PHASE_B_ENTRY_RECEIPT_V1.json", "J2D2_PHASE_B_COMPLETION_RECEIPT_V1.json",
    "PHASE_A_AUTHORITY_REFERENCES_V1.json", "PHASE_B_CONTROLLED_ACCESS_LEDGER.jsonl",
    "PHASE_B_CONTROLLED_ACCESS_LEDGER_METADATA_V1.json", "PHASE_B_SOURCE_PRESERVATION_MANIFEST_V1.json",
    "PHASE_B_PRESERVATION_BASELINE_V1.json", "PHASE_B_FINAL_INTEGRITY_VERIFICATION_V1.json",
    "PHASE_B_DEVELOPMENT_DIAGNOSTICS_V1.json", "PHASE_B_TARGETED_TEST_RESULTS_V1.json", "PHASE_B_TARGETED_TEST_OUTPUT_V1.txt",
    "C4_REAL_CORRECTED_JUDGE_EXECUTION_FREEZE_RECEIPT.json", "C4_REAL_HUMAN_APPLICABILITY_REPAIR_FREEZE_RECEIPT.json",
    "C4_REAL_PHASE_B_RESTRICTED_MAPPING_METADATA_V1.json", "BUILD_RESULT_METADATA_V1.json",
    "c4_real_judge_result_eligibility_after_applicability_v2.json", "c4_real_corrected_judge_request_registry_v1.jsonl",
    "c4_real_corrected_judge_shard_metadata_v1.json", "c4_real_corrected_judge_package_manifest_r4_v1.json",
    "c4_real_corrected_judge_configurations_r4.json", "c4_real_corrected_judge_execution_contracts_r4.json",
    "C4_REAL_JUDGE_REPAIR_IMPACT_REPORT.md", "c4_real_human_completed_source_intake_v1.json",
    "c4_real_human_applicability_impact_v1.json", "C4_REAL_HUMAN_APPLICABILITY_IMPACT_REPORT.md",
    "c4_real_human_amendment_packet_manifest_v1.json", "HUMAN_APPLICABILITY_AMENDMENT_GUIDE.md",
    "human_amendment_attestation_A.md", "human_amendment_attestation_B.md",
    "human_applicability_amendment_blank_template.csv", "STATUS.md",
    "phase_b_access_guard.py", "phase_b_sources.py", "phase_b_model.py", "build_phase_b_repair.py",
    "freeze_phase_b.py", "run_targeted_tests.py", "test_phase_b_repair.py", "build_phase_b_review.py",
    "package_support/validate_package.py", "package_support/test_package.py",
    "package_support/judge_execution_runner_v3.py", "package_support/judge_result_parser_v3.py",
    "package_support/APPLICABILITY_CONTRACT_V2.json",
})
FORBIDDEN_DATA_FIELDS = {"provider_payload", "candidate_response", "parsed_semantic_result", "raw_response_content",
                         "corrected_semantic_value", "retained_source_rationale", "scenario_id", "mode_id", "family_id", "route_signature"}


def metadata_only(value):
    if isinstance(value, dict):
        require(not (set(value) & FORBIDDEN_DATA_FIELDS), "Review JSON contains controlled data fields")
        for item in value.values(): metadata_only(item)
    elif isinstance(value, list):
        for item in value: metadata_only(item)


def main():
    completion = json.loads((HERE / "J2D2_PHASE_B_COMPLETION_RECEIPT_V1.json").read_bytes())
    entry = json.loads((HERE / "J2D2_PHASE_B_ENTRY_RECEIPT_V1.json").read_bytes())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    parent = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True).strip()
    require(parent == entry["starting_head"], "Review requires exactly the single Phase-B commit")
    require(subprocess.check_output(["git", "rev-list", "--count", entry["starting_head"] + "..HEAD"], cwd=ROOT, text=True).strip() == "1", "Phase B has more than one commit")
    require(subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() == entry["branch"], "Review branch mismatch")
    status = subprocess.check_output(["git", "status", "--short", "--untracked-files=all"], cwd=ROOT, text=True).splitlines()
    require(status == entry["initial_git_status"], "Review requires clean tracked tree and the exact three retained legacy files")
    changes = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", head], cwd=ROOT, text=True).splitlines()
    prefix = str(HERE.relative_to(ROOT)) + "/"
    require(all(line.startswith("A\t" + prefix) for line in changes), "Commit is not confined to new Phase-B tracked files")
    require(completion["controlled_source_access_closed"] is True, "Phase B not sealed")
    require(digest((HERE / "PHASE_B_CONTROLLED_ACCESS_LEDGER.jsonl").read_bytes()) == completion["controlled_access_ledger_sha256"], "Sealed ledger changed")
    members = {}
    key = KEY_PATH.read_bytes()  # Secret integrity/exclusion check only; never logged.
    require(len(key) == 32 and digest(key) == KEY_COMMITMENT, "HMAC commitment changed")
    for name in sorted(ALLOWED):
        path = HERE / name
        require(path.is_file() and not path.is_symlink(), "Review allowlist source missing or symlinked")
        require(bool(subprocess.check_output(["git", "ls-files", "--", str(path.relative_to(ROOT))], cwd=ROOT).strip()), "Review source is not committed")
        raw = path.read_bytes()
        require(key not in raw, "HMAC key found in review source")
        if name.endswith(".json"): metadata_only(json.loads(raw))
        elif name.endswith(".jsonl"):
            for line in raw.splitlines(): metadata_only(json.loads(line))
        elif name.endswith(".csv"):
            require(name == "human_applicability_amendment_blank_template.csv" and len(list(csv.DictReader(io.StringIO(raw.decode())))) == 0,
                    "Review CSV is not the header-only blank template")
        members[name] = raw
    manifest = {"schema_version": "rq3-real-j2d2-r1-phase-b-review-manifest-v1", "scope": "REVIEW_ONLY_NO_RAW_OUTCOMES_OR_CANDIDATE_RESPONSES",
                "starting_head": entry["starting_head"], "ending_head": head, "phase_b_commit_count": 1,
                "status": completion["RQ3_REAL_J2D2_R1_STATUS"],
                "completion_receipt_sha256": digest((HERE / "J2D2_PHASE_B_COMPLETION_RECEIPT_V1.json").read_bytes()),
                "included_files": {name: digest(raw) for name, raw in members.items()},
                "regular_file_count_including_this_manifest": len(members) + 1,
                "excluded": ["raw Judge outputs and scores", "raw Human ratings and rationales", "candidate responses", "HMAC key",
                             "restricted identity mappings", "condition/mode outcome mappings", "credentials", "system comparisons"],
                "delivery_package_hashes": completion["generated_delivery_package_hashes"], "tests": completion["tests"]}
    members["REVIEW_MANIFEST.json"] = pretty(manifest)
    raw = zip_bytes(members)
    require(key not in raw, "HMAC key found in review archive")
    with ZipFile(io.BytesIO(raw)) as archive:
        require(set(archive.namelist()) == ALLOWED | {"REVIEW_MANIFEST.json"}, "Review ZIP allowlist mismatch")
        require(archive.testzip() is None, "Review ZIP CRC failure")
        require(all(archive.read(name) == value for name, value in members.items()), "Review ZIP byte mismatch")
    path = DOWNLOADS / REVIEW_FILENAME
    durable_write_once(path, raw)
    require(digest(path.read_bytes()) == digest(raw), "Review ZIP on-disk hash mismatch")
    print(json.dumps({"path": str(path), "sha256": digest(raw), "bytes": len(raw), "regular_file_count": len(members),
                      "allowlist_byte_crc_checks": "PASS", "starting_head": entry["starting_head"], "ending_head": head,
                      "single_commit_verified": True, "raw_outcomes_or_candidate_responses_included": False}, sort_keys=True))


if __name__ == "__main__": main()
