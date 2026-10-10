#!/usr/bin/env python3
"""Read-only independent validator for the R3D1-R1 frozen artifacts."""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.rq3_real_c4.r3d1_response_integration import build_r3d1_artifacts as build
from evaluation.rq3_real_c4.r3d1_response_integration.judge_package_validator_v1 import (
    validate_package_dir,
)


class ValidationError(RuntimeError):
    """Raised on the first validation failure."""


class Ledger:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, condition: bool, message: str) -> None:
        if condition:
            self.passed += 1
            return
        self.failed += 1
        raise ValidationError(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive_path: Path, destination: Path, ledger: Ledger) -> None:
    with ZipFile(archive_path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            ledger.check(
                not member.is_absolute() and ".." not in member.parts,
                f"unsafe ZIP member in {archive_path.name}",
            )
            ledger.check(not info.is_dir(), f"directory member in {archive_path.name}")
            target = destination / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def validate() -> dict[str, Any]:
    ledger = Ledger()
    here = build.HERE
    repo = build.REPO
    restricted = build.RESTRICTED
    downloads = build.DOWNLOADS
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    ledger.check(branch == build.EXPECTED_BRANCH, "branch mismatch")
    history = subprocess.run(
        ["git", "rev-list", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    ledger.check(history.count(build.CONTINUATION_COMMIT) == 1, "continuation commit count mismatch")
    ledger.check(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", build.START_HEAD, "HEAD"], cwd=repo
        ).returncode
        == 0,
        "starting HEAD is not an ancestor",
    )

    protected = [*build.R3_SOURCE_DIRS.values(), build.R3D0]
    ledger.check(
        subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                build.START_HEAD,
                "--",
                *[str(path.relative_to(repo)) for path in protected],
            ],
            cwd=repo,
        ).returncode
        == 0,
        "immutable R3 source differs",
    )
    source_manifest = load_json(here / "c4_real_r3_source_preservation_manifest_v1.json")
    ledger.check(source_manifest["status"].startswith("PASS_"), "source manifest status")
    ledger.check(source_manifest["starting_head"] == build.START_HEAD, "source manifest HEAD")
    for item in source_manifest["files"]:
        path = repo / item["path"]
        ledger.check(path.is_file(), f"missing immutable source: {item['path']}")
        ledger.check(path.stat().st_size == item["bytes"], f"source size mismatch: {item['path']}")
        ledger.check(sha256_file(path) == item["sha256"], f"source hash mismatch: {item['path']}")

    key_path = restricted / "c4_real_i1_blinding_hmac_key.bin"
    ledger.check(key_path.stat().st_size == 32, "HMAC key size")
    ledger.check(stat.S_IMODE(key_path.stat().st_mode) == 0o600, "HMAC key mode")
    ledger.check(sha256_file(key_path) == build.HMAC_KEY_COMMITMENT, "HMAC key commitment")
    ledger.check(
        subprocess.run(
            ["git", "check-ignore", "-q", str(key_path.relative_to(repo))], cwd=repo
        ).returncode
        == 0,
        "HMAC key ignored status",
    )
    v3_metadata = load_json(build.I1 / "c4_real_restricted_mapping_metadata_v3.json")
    ledger.check(v3_metadata["hmac_key_sha256_commitment"] == build.HMAC_KEY_COMMITMENT, "tracked commitment")
    for name, expected in v3_metadata["mapping_files"].items():
        path = restricted / name
        ledger.check(sha256_file(path) == expected["sha256"], f"V3 restricted hash: {name}")
        ledger.check(stat.S_IMODE(path.stat().st_mode) == 0o600, f"V3 restricted mode: {name}")

    receipt = load_json(here / "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json")
    canonical_path = here / "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl"
    canonical_csv_path = here / "c4_real_r3_canonical_unique_responses_frozen_v1.csv"
    source_registry_path = here / "c4_real_r3_response_source_registry_v1.jsonl"
    canonical = load_jsonl(canonical_path)
    canonical_csv = load_csv(canonical_csv_path)
    source_registry = load_jsonl(source_registry_path)
    ledger.check(len(canonical) == len(canonical_csv) == len(source_registry) == 147, "canonical record counts")
    ledger.check(len({row["logical_generation_request_id"] for row in canonical}) == 147, "request-ID uniqueness")
    ledger.check(len({row["response_blind_id"] for row in canonical}) == 147, "response-ID uniqueness")
    ledger.check(len({row["provider_payload_sha256"] for row in canonical}) == 147, "payload identity uniqueness")
    validator = build.load_module(
        "r3d1_read_only_validator_v2",
        build.R3D0 / "c4_real_student_facing_response_validator_v2.py",
    )
    by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in canonical:
        ledger.check(
            hashlib.sha256(row["answer_text"].encode("utf-8")).hexdigest()
            == row["answer_text_sha256"],
            "answer-text hash mismatch",
        )
        ledger.check(
            validator.validate_answer_text(row["answer_text"])
            == validator.VALID_STUDENT_FACING_RESPONSE,
            "Validator V2 failure",
        )
        ledger.check(row["generation_status"] == "VALID_STUDENT_FACING_RESPONSE", "generation status")
        ledger.check("g2" not in row["selected_execution_source"].casefold(), "G2 source included")
        by_text[row["answer_text_sha256"]].append(row)
    duplicates = [rows for rows in by_text.values() if len(rows) > 1]
    ledger.check(len(by_text) == 146, "distinct answer-text hash count")
    ledger.check(len(duplicates) == 1 and len(duplicates[0]) == 2, "duplicate-text group structure")
    ledger.check(duplicates[0][0]["answer_text_sha256"] == build.KNOWN_DUPLICATE_TEXT_SHA256, "known shared text hash")
    ledger.check(
        {row["logical_generation_request_id"] for row in duplicates[0]}
        == set(build.KNOWN_DUPLICATE_REQUEST_IDS),
        "known duplicate request IDs",
    )
    ledger.check(len({row["response_blind_id"] for row in duplicates[0]}) == 2, "duplicate response IDs distinct")
    ledger.check(len({row["provider_payload_sha256"] for row in duplicates[0]}) == 2, "duplicate payload IDs distinct")
    ledger.check(sha256_file(canonical_path) == receipt["canonical_response_jsonl_sha256"], "canonical JSONL receipt hash")
    ledger.check(sha256_file(canonical_csv_path) == receipt["canonical_response_csv_sha256"], "canonical CSV receipt hash")
    ledger.check(sha256_file(source_registry_path) == receipt["response_source_registry_sha256"], "source registry receipt hash")
    ledger.check(receipt["write_count"] == 1 and receipt["overwrite_permitted"] is False, "write-once receipt")
    ledger.check(receipt["zero_g2_answer_inclusion"] is True, "G2 exclusion receipt")

    duplicate_audit = load_json(here / "c4_real_r3_duplicate_text_identity_audit_v1.json")
    ledger.check(duplicate_audit["duplicate_groups"][0]["group_size"] == 2, "duplicate audit size")
    format_audit = load_json(here / "c4_real_r3_final_response_format_audit_v1.json")
    ledger.check(format_audit["status"].startswith("PASS_"), "format audit status")
    ledger.check(format_audit["response_counts"]["validator_v2_valid_student_facing_response"] == 147, "format pass count")
    ledger.check(format_audit["literal_leakage_scan"]["total_occurrences"] == 0, "leakage count")
    usage = load_json(here / "c4_real_r3_generation_usage_frozen_v1.json")
    ledger.check(
        usage["aggregate"]
        == {
            "frozen_logical_request_universe": 147,
            "physical_attempts": 149,
            "historical_redundant_retries": 2,
            "prompt_tokens": 127762,
            "cached_input_tokens": 14720,
            "completion_tokens": 23568,
            "total_tokens": 151330,
        },
        "aggregate generation usage",
    )
    ledger.check(usage["cost_status"] == "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY", "cost boundary")

    mapping_metadata = load_json(here / "c4_real_r3_response_mapping_metadata_v1.json")
    for name, expected in mapping_metadata["mapping_files"].items():
        path = restricted / name
        ledger.check(path.is_file(), f"restricted response mapping absent: {name}")
        ledger.check(sha256_file(path) == expected["sha256"], f"restricted response mapping hash: {name}")
        ledger.check(stat.S_IMODE(path.stat().st_mode) == 0o600, f"restricted response mapping mode: {name}")
        ledger.check(
            subprocess.run(
                ["git", "check-ignore", "-q", str(path.relative_to(repo))], cwd=repo
            ).returncode
            == 0,
            f"restricted response mapping ignored: {name}",
        )
    condition_records = load_jsonl(
        restricted / "c4_real_r3_condition_response_records_frozen_v1.jsonl"
    )
    ledger.check(len(condition_records) == 558, "condition-response record count")
    ledger.check(len({row["replay_record_id"] for row in condition_records}) == 558, "condition-ID uniqueness")
    payloads_by_response: dict[str, set[str]] = defaultdict(set)
    for row in condition_records:
        payloads_by_response[row["response_blind_id"]].add(row["provider_payload_sha256"])
        ledger.check(row["generation_status"] == "VALID_STUDENT_FACING_RESPONSE", "mapped generation status")
    ledger.check(len(payloads_by_response) == 147, "mapped response count")
    ledger.check(all(len(values) == 1 for values in payloads_by_response.values()), "response shared across unequal payloads")
    ledger.check(558 - len(payloads_by_response) == 411, "duplicate mapping count")
    applicability_audit = load_json(here / "c4_real_r3_applicability_integrity_audit_v1.json")
    ledger.check(applicability_audit["status"].startswith("PASS_"), "applicability audit status")
    memory_scenarios = {
        row["scenario_id"]
        for row in condition_records
        if row["applicability_source_metadata"]["long_term_memory_relevant"]
    }
    planning_scenarios = {
        row["scenario_id"]
        for row in condition_records
        if row["applicability_source_metadata"]["request_requires_advice"]
    }
    ledger.check(
        applicability_audit["memory_relevant_family_count"] == len(memory_scenarios),
        "Memory-relevant family audit count",
    )
    ledger.check(
        applicability_audit["planning_relevant_family_count"] == len(planning_scenarios),
        "Planning-relevant family audit count",
    )
    ledger.check(
        applicability_audit["memory_relevant_records_preserving_personalisation"]
        == sum(row["scenario_id"] in memory_scenarios for row in condition_records),
        "Memory-relevant record audit count",
    )
    ledger.check(
        applicability_audit["planning_relevant_records_preserving_actionability"]
        == sum(row["scenario_id"] in planning_scenarios for row in condition_records),
        "Planning-relevant record audit count",
    )
    for row in condition_records:
        criteria = row["frozen_applicability_map"]["criteria"]
        ledger.check(criteria["CLARITY"] is True, "CLARITY applicability")
        ledger.check(criteria["CONTEXT_AWARENESS"] is True, "CONTEXT applicability")
        ledger.check(criteria["RELIABILITY"] is True, "RELIABILITY applicability")
        ledger.check(sum(criteria.values()) >= 3, "minimum applicability")
        if row["scenario_id"] in memory_scenarios:
            ledger.check(criteria["PERSONALISATION"] is True, "Memory-on/off PERSONALISATION applicability")
        if row["scenario_id"] in planning_scenarios:
            ledger.check(criteria["ACTIONABILITY"] is True, "Planning-on/off ACTIONABILITY applicability")

    judge_receipt = load_json(here / "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT.json")
    judge_records = load_jsonl(here / "c4_real_unique_judge_request_manifest_frozen_v1.jsonl")
    ledger.check(len(judge_records) == judge_receipt["unique_judge_request_count"] == 147, "unique Judge count")
    ledger.check(len({row["logical_judge_request_id"] for row in judge_records}) == len(judge_records), "Judge logical ID uniqueness")
    ledger.check(len({row["judge_result_blind_id"] for row in judge_records}) == len(judge_records), "Judge result ID uniqueness")
    ledger.check(len({row["provider_payload_sha256"] for row in judge_records}) == len(judge_records), "Judge payload uniqueness")
    for row in judge_records:
        ledger.check(bool(re.fullmatch(r"C4J1-[A-F0-9]{24}", row["logical_judge_request_id"])), "opaque Judge logical ID")
        ledger.check(bool(re.fullmatch(r"R3B-[A-F0-9]{20}", row["judge_result_blind_id"])), "opaque Judge result ID")
        ledger.check(
            hashlib.sha256(build.canonical_json_bytes(row["provider_payload"])).hexdigest()
            == row["provider_payload_sha256"],
            "Judge payload hash",
        )
        request = build._extract_blind_request(row["provider_payload"])
        build._forbid_evaluation_identity(request)
        ledger.check(request["response_blind_id"] == row["judge_result_blind_id"], "embedded Judge ID")
    ledger.check(sha256_file(here / "c4_real_unique_judge_request_manifest_frozen_v1.jsonl") == judge_receipt["unique_judge_manifest_sha256"], "Judge manifest receipt hash")
    ledger.check(judge_receipt["judge_model"] == build.JUDGE_MODEL, "Judge model")
    ledger.check(judge_receipt["maximum_output_tokens"] == 2048, "Judge maximum output tokens")
    ledger.check(judge_receipt["judge_calls"] == 0, "zero Judge calls")
    ledger.check(judge_receipt["maximum_physical_attempts"] == 294, "maximum future Judge attempts")

    judge_mapping_meta = load_json(here / "c4_real_judge_restricted_mapping_metadata_v1.json")
    judge_mapping_path = restricted / judge_mapping_meta["condition_mapping_filename"]
    ledger.check(sha256_file(judge_mapping_path) == judge_mapping_meta["condition_mapping_sha256"], "Judge mapping hash")
    judge_mapping = load_csv(judge_mapping_path)
    ledger.check(len(judge_mapping) == 558, "Judge mapping count")
    family_shards: dict[str, set[str]] = defaultdict(set)
    generation_to_judge: dict[str, set[str]] = defaultdict(set)
    for row in judge_mapping:
        family_shards[row["scenario_id"]].add(row["shard_id"])
        generation_to_judge[row["generation_logical_request_id"]].add(row["judge_logical_request_id"])
    ledger.check(all(len(shards) == 1 for shards in family_shards.values()), "family-atomic Judge Shards")
    ledger.check(generation_to_judge[build.KNOWN_DUPLICATE_REQUEST_IDS[0]].isdisjoint(generation_to_judge[build.KNOWN_DUPLICATE_REQUEST_IDS[1]]), "equal-text Judge separation")
    ledger.check({row["shard_id"] for row in judge_records} == {"A", "B", "C"}, "three Judge Shards")
    ledger.check(
        {shard: sum(row["shard_id"] == shard for row in judge_records) for shard in ("A", "B", "C")}
        == {"A": 49, "B": 49, "C": 49},
        "Judge Shard request balance",
    )

    package_manifest = load_json(here / "c4_real_judge_package_manifest_r1_v1.json")
    raw_key = key_path.read_bytes()
    for shard in ("A", "B", "C"):
        meta = package_manifest["packages"][shard]
        archive_path = downloads / meta["file_name"]
        ledger.check(archive_path.is_file(), f"Judge Package {shard} absent")
        ledger.check(sha256_file(archive_path) == meta["sha256"], f"Judge Package {shard} hash")
        ledger.check(raw_key not in archive_path.read_bytes(), f"raw HMAC key in Judge Package {shard}")
        with tempfile.TemporaryDirectory(prefix=f"r3d1-validate-judge-{shard.lower()}-") as tmp:
            destination = Path(tmp)
            _safe_extract(archive_path, destination, ledger)
            result = validate_package_dir(destination)
            ledger.check(result["status"] == "PASS", f"Judge Package {shard} validator")
            ledger.check(result["request_count"] == 49, f"Judge Package {shard} request count")

    human_receipt = load_json(here / "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT.json")
    human_manifest = load_json(here / "c4_real_human_packet_manifest_v1.json")
    packet_a = load_csv(here / "human_rating_packet_A.csv")
    packet_b = load_csv(here / "human_rating_packet_B.csv")
    ids_a = [row["rating_item_id"] for row in packet_a]
    ids_b = [row["rating_item_id"] for row in packet_b]
    ledger.check(len(packet_a) == len(packet_b) == 108, "human packet item count")
    ledger.check(set(ids_a) == set(ids_b), "human packet same item set")
    ledger.check(ids_a != ids_b, "human packet different order")
    ledger.check(sha256_file(here / "human_rating_packet_A.csv") == human_manifest["packet_csv_sha256"]["A"], "human A CSV hash")
    ledger.check(sha256_file(here / "human_rating_packet_B.csv") == human_manifest["packet_csv_sha256"]["B"], "human B CSV hash")
    forbidden_headers = {"scenario_id", "scenario_family_id", "mode_id", "condition_id", "route", "p3", "gold", "judge_result_blind_id", "judge_logical_request_id"}
    ledger.check(not forbidden_headers.intersection(packet_a[0]), "human packet identity headers")
    rating_fields = [name for name in packet_a[0] if name.endswith("_rating")]
    rationale_fields = [name for name in packet_a[0] if name.endswith("_rationale")]
    ledger.check(len(rating_fields) == len(rationale_fields) == 8, "human rating/rationale field count")
    for row in [*packet_a, *packet_b]:
        ledger.check(all(row[name] == "" for name in rating_fields), "prefilled human rating")
        ledger.check(all(row[name] == "" for name in rationale_fields), "prefilled human rationale")
    ledger.check(human_receipt["selected_family_count"] == 12, "human selected family count")
    ledger.check(human_receipt["rating_item_count"] == 108, "human receipt item count")
    ledger.check(human_receipt["completed_ratings"] == 0, "zero completed human ratings")
    human_map_meta = load_json(here / "c4_real_human_restricted_mapping_metadata_v1.json")
    human_map_path = restricted / human_map_meta["mapping_filename"]
    ledger.check(sha256_file(human_map_path) == human_map_meta["mapping_sha256"], "human restricted mapping hash")
    ledger.check(len(load_csv(human_map_path)) == 108, "human restricted mapping count")
    for role in ("A", "B"):
        meta = human_manifest["archives"][role]
        archive_path = downloads / meta["file_name"]
        ledger.check(archive_path.is_file(), f"human {role} archive absent")
        ledger.check(sha256_file(archive_path) == meta["sha256"], f"human {role} archive hash")
        ledger.check(raw_key not in archive_path.read_bytes(), f"raw HMAC key in human {role} archive")
        with ZipFile(archive_path) as archive:
            ledger.check(
                set(archive.namelist())
                == {
                    "HUMAN_RATER_GUIDE.md",
                    f"human_rating_packet_{role}.csv",
                    f"human_rater_attestation_{role}.md",
                    "PACKET_MANIFEST.json",
                },
                f"human {role} archive allowlist",
            )

    for path in restricted.iterdir():
        if path.name.startswith(("c4_real_r3_", "c4_real_condition_to_unique_judge_", "c4_real_human_rating_")):
            ledger.check(
                subprocess.run(
                    ["git", "check-ignore", "-q", str(path.relative_to(repo))], cwd=repo
                ).returncode
                == 0,
                f"derived restricted file not ignored: {path.name}",
            )
    ledger.check(not list(here.glob("JUDGE_*JOURNAL*.jsonl")), "Judge outputs present in tracked freeze")
    ledger.check(not list(here.glob("*completed*rating*")), "completed rating artifact present")
    status = (here / "STATUS.md").read_text(encoding="utf-8")
    ledger.check(
        "READY_FOR_PARALLEL_C4_REAL_JUDGE_EXECUTION_AND_INDEPENDENT_HUMAN_REVIEW" in status,
        "final status marker",
    )
    ledger.check(
        all(
            value == 0
            for value in (
                judge_receipt["judge_calls"],
                human_receipt["completed_ratings"],
            )
        ),
        "zero execution/rating boundary",
    )
    return {
        "status": "PASS",
        "checks_passed": ledger.passed,
        "checks_failed": ledger.failed,
        "canonical_responses": len(canonical),
        "condition_response_records": len(condition_records),
        "unique_judge_requests": len(judge_records),
        "human_rating_items": len(packet_a),
    }


def main() -> int:
    print(json.dumps(validate(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
