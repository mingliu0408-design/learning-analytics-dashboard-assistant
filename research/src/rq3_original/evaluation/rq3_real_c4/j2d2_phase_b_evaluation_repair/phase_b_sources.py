"""Manifest-bound source intake; controlled values never enter metadata."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import stat
import subprocess
import zipfile
from pathlib import Path

import phase_b_access_guard as guard

ROOT = guard.ROOT
BASE = ROOT / "evaluation/rq3_real_c4"
HERE = guard.HERE
R1 = BASE / "r3d1_response_integration"
R2 = BASE / "r3d1_response_integration_r2"
J2D0 = BASE / "j2d0_judge_continuation_repair"
PHASE_A = BASE / "j2d2_corrected_applicability_freeze"
RESTRICTED = BASE / "i1_route_integration/restricted_internal"
DOWNLOADS = Path("/Users/liuming/Downloads")
KEY_PATH = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
KEY_COMMITMENT = "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5"
HUMAN_HASHES = {
    "human_rating_packet_A_completed.csv": "0d4195b4bfa3680cc8079a9c87b3177ee3f207dea14c9a3a7dfaaaef14a6a318",
    "human_rating_packet_B_completed.csv": "02ae76ba9866f8b7115ead815cc587e7c14c2f00c733570839364129bfeeaa46",
    "human_rater_attestation_A_completed(1).md": "dfa22955ab3aa6ea9885c7bdf0578dfed9e2bc1b83e895e2719e52eb40ba23a3",
    "human_rater_attestation_B_completed(1).md": "0146f38074a065e3fa6f3f09579a813f1f8019dad3ee1dc4575bc98d31a722c6",
}
SOURCE_METADATA_ALLOWLIST = {
    R1 / "c4_real_judge_restricted_mapping_metadata_v1.json",
    R1 / "c4_real_r3_response_mapping_metadata_v1.json",
    R1 / "c4_real_human_validation_sample_metadata_v1.json",
    R1 / "c4_real_judge_request_deduplication_audit_v1.json",
    R2 / "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT_R2.json",
    R2 / "c4_real_judge_package_manifest_r2_v1.json",
    R2 / "c4_real_human_packet_manifest_r2_v1.json",
    R2 / "c4_real_human_restricted_mapping_metadata_r2_v1.json",
    R2 / "c4_real_r3d1_r2_source_preservation_manifest_v1.json",
    J2D0 / "c4_real_judge_continuation_package_manifest_v1.json",
    J2D0 / "c4_real_existing_judge_attempt_reclassification_summary_v3.json",
    J2D0 / "C4_REAL_JUDGE_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json",
    *(BASE / name / "judge_execution_source_manifest_v1.json" for name in
      ("j2a_judge_shard_a", "j2b_judge_shard_b", "j2c_judge_shard_c")),
    *(BASE / name / f"judge_continuation_source_manifest_v{version}.json" for name in
      ("j3b_judge_continuation_b", "j3c_judge_continuation_c") for version in (1, 2)),
}


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pretty(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require(condition, message: str):
    if not condition:
        raise RuntimeError(message)


def csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def jsonl_rows(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


class Sources:
    def __init__(self):
        self.entry = guard.verify_entry()
        self.cache: dict[Path, bytes] = {}
        self.catalog: dict[str, dict] = {}

    def committed(self, path: Path):
        path = path.resolve()
        require(path.is_relative_to(ROOT), "Committed source outside checkout")
        rel = str(path.relative_to(ROOT))
        value = subprocess.check_output(["git", "ls-files", "--stage", "--", rel], cwd=ROOT, text=True).strip()
        require(bool(value), "Source is not committed: " + rel)
        require(subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode == 0,
                "Committed scientific source changed: " + rel)
        return value.split()[1]

    def metadata(self, path: Path):
        path = path.resolve()
        require(path in SOURCE_METADATA_ALLOWLIST, "Non-allowlisted metadata read")
        blob = self.committed(path)
        raw = path.read_bytes()  # This explicit allowlist contains hashes/identities/counts only.
        self.catalog[str(path)] = {"path": str(path), "sha256": digest(raw), "bytes": len(raw),
                                  "source_role": "score_free_source_manifest", "git_blob_id": blob}
        return json.loads(raw)

    def controlled(self, path: Path, expected: str, role: str, use: str, *, committed=True):
        path = path.resolve()
        blob = self.committed(path) if committed else None
        if path not in self.cache:
            self.cache[path] = guard.read_controlled(path, expected_sha256=expected, role=role, permitted_use=use)
        raw = self.cache[path]
        require(digest(raw) == expected, "Conflicting source hash declaration")
        self.catalog[str(path)] = {"path": str(path), "sha256": expected, "bytes": len(raw),
                                  "source_role": role, "git_blob_id": blob,
                                  "permitted_use": use, "restricted_contents_exported": False}
        return raw

    def key(self) -> bytes:
        # The key is not an evaluation outcome. Only this verified secret is read;
        # only its pre-existing commitment can leave this process.
        guard.verify_entry()
        require(KEY_PATH.stat().st_size == 32, "HMAC key must be 32 bytes")
        require(stat.S_IMODE(KEY_PATH.stat().st_mode) == 0o600, "HMAC key mode must be 0600")
        rel = str(KEY_PATH.relative_to(ROOT))
        require(subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 0, "HMAC key is not ignored")
        require(not subprocess.check_output(["git", "ls-files", "--", rel], cwd=ROOT).strip(), "HMAC key is tracked")
        key = KEY_PATH.read_bytes()
        require(digest(key) == KEY_COMMITMENT, "HMAC key commitment mismatch")
        return key

    def old_packages(self):
        manifest = self.metadata(R2 / "c4_real_judge_package_manifest_r2_v1.json")
        packages = {}
        for shard, record in manifest["packages"].items():
            raw = self.controlled(DOWNLOADS / record["file_name"], record["sha256"], "package_source",
                                  "payload_byte_preservation_and_applicability_replacement", committed=False)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                require(archive.testzip() is None, "Old package CRC failure")
                require(len(archive.namelist()) == len(set(archive.namelist())) == 13, "Old package member mismatch")
                members = {name: archive.read(name) for name in archive.namelist()}
            require(set(members) == set(record["member_sha256"]), "Old package allowlist mismatch")
            for name, expected in record["member_sha256"].items():
                require(digest(members[name]) == expected, "Old package member hash mismatch")
            packages[shard] = members
        return packages

    def execution_sources(self):
        output = []
        sources = [("j2a_judge_shard_a", "judge_execution_source_manifest_v1.json", "A", True),
                   ("j2b_judge_shard_b", "judge_execution_source_manifest_v1.json", "B", True),
                   ("j2c_judge_shard_c", "judge_execution_source_manifest_v1.json", "C", True),
                   ("j3b_judge_continuation_b", "judge_continuation_source_manifest_v1.json", "B", False),
                   ("j3c_judge_continuation_c", "judge_continuation_source_manifest_v1.json", "C", False),
                   ("j3b_judge_continuation_b", "judge_continuation_source_manifest_v2.json", "B", True),
                   ("j3c_judge_continuation_c", "judge_continuation_source_manifest_v2.json", "C", True)]
        for name, manifest_name, shard, scientific in sources:
            directory = BASE / name
            manifest = self.metadata(directory / manifest_name)
            details = next(manifest[k] for k in ("execution_output_v2", "execution_output", "execution", "execution_output_v1")
                           if k in manifest and ("files" in manifest[k] or "file_sha256" in manifest[k]))
            folder = details.get("path", details.get("output_path"))
            hashes = details.get("file_sha256") or {k: v["sha256"] for k, v in details["files"].items()}
            files = {}
            for filename, expected in sorted(hashes.items()):
                role = ("judge_attempt_journal" if "ATTEMPT" in filename else "judge_terminal_source" if "TERMINAL" in filename
                        else "judge_error_journal" if "ERROR" in filename else "judge_result_source")
                files[filename] = self.controlled(directory / folder / filename, expected, role,
                                                  "parser_v3_validity_and_result_eligibility_only" if scientific else "immutable_source_integrity_only")
            output.append({"directory": directory, "output_folder": folder, "shard": shard, "scientific": scientific,
                           "manifest": manifest, "files": files, "source_rank": len(output)})
        return output

    def load(self):
        protocol = self.metadata(R2 / "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT_R2.json")
        requests = jsonl_rows(self.controlled(R2 / "c4_real_unique_judge_request_manifest_frozen_r2.jsonl",
                             protocol["combined_unique_judge_manifest_sha256"], "judge_request_source",
                             "payload_byte_preservation_and_applicability_replacement"))
        judge_metadata = self.metadata(R1 / "c4_real_judge_restricted_mapping_metadata_v1.json")
        judge_mappings = csv_rows(self.controlled(RESTRICTED / judge_metadata["condition_mapping_filename"],
                                 judge_metadata["condition_mapping_sha256"], "restricted_identity_mapping",
                                 "identity_and_structure_only", committed=False))
        human_metadata = self.metadata(R2 / "c4_real_human_restricted_mapping_metadata_r2_v1.json")
        human_mappings = csv_rows(self.controlled(RESTRICTED / human_metadata["mapping_filename"], human_metadata["mapping_sha256"],
                                                 "restricted_identity_mapping", "human_applicability_impact_and_blank_amendment_construction", committed=False))
        response_metadata = self.metadata(R1 / "c4_real_r3_response_mapping_metadata_v1.json")
        response_filename = "c4_real_r3_condition_response_records_frozen_v1.jsonl"
        responses = jsonl_rows(self.controlled(RESTRICTED / response_filename,
                               response_metadata["mapping_files"][response_filename]["sha256"], "candidate_response_source",
                               "payload_byte_preservation_and_applicability_replacement", committed=False))
        phase_a_maps_path = PHASE_A / "c4_real_condition_applicability_maps_frozen_v2.jsonl"
        expected_v2 = self.entry["accepted_applicability_v2_artifact_hashes"][phase_a_maps_path.name]
        phase_a_maps_raw = phase_a_maps_path.read_bytes()
        require(digest(phase_a_maps_raw) == expected_v2, "Frozen V2 map changed")
        maps_v2 = jsonl_rows(phase_a_maps_raw)
        human_manifest = self.metadata(R2 / "c4_real_human_packet_manifest_r2_v1.json")
        human, blank, attestations = {}, {}, {}
        for rater in "AB":
            completed_name = f"human_rating_packet_{rater}_completed.csv"
            human[rater] = csv_rows(self.controlled(DOWNLOADS / completed_name, HUMAN_HASHES[completed_name], "human_completed_rating",
                                   "human_v1_structure_and_attestation_validation", committed=False))
            original_name = f"human_rating_packet_{rater}.csv"
            blank[rater] = csv_rows(self.controlled(R2 / f"human_rating_packet_{rater}_R2.csv",
                                   human_manifest["packages"][rater]["member_sha256"][original_name], "human_blank_packet",
                                   "human_v1_structure_and_attestation_validation", committed=False))
            attestation_name = f"human_rater_attestation_{rater}_completed(1).md"
            attestations[rater] = self.controlled(DOWNLOADS / attestation_name, HUMAN_HASHES[attestation_name], "human_completed_attestation",
                                                  "human_v1_structure_and_attestation_validation", committed=False).decode()
        continuation_manifest = self.metadata(J2D0 / "c4_real_judge_continuation_package_manifest_v1.json")
        support = {}
        for name in ("judge_result_parser_v3.py", "judge_execution_runner_v3.py"):
            support[name] = self.controlled(J2D0 / name, continuation_manifest["packages"]["A"]["member_sha256"][name],
                                            "historical_support_code", "offline_package_construction_or_validation")
        rule = self.metadata(J2D0 / "C4_REAL_JUDGE_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json")
        reclassification = self.metadata(J2D0 / "c4_real_existing_judge_attempt_reclassification_summary_v3.json")
        return {"requests": requests, "judge_mappings": judge_mappings, "human_mappings": human_mappings,
                "responses": responses, "maps_v2": maps_v2, "human": human, "blank_human": blank,
                "attestations": attestations, "support": support, "old_packages": self.old_packages(),
                "execution_sources": self.execution_sources(), "selection_rule": rule,
                "j2d0_reclassification_summary": reclassification, "key": self.key()}
