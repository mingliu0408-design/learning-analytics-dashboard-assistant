#!/usr/bin/env python3
"""Independent offline validator for the complete R3D1-R2 freeze."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Callable, Mapping
from zipfile import ZipFile

try:
    from build_r3d1_r2_artifacts import (
        APPLICABILITY_SHA256,
        DOWNLOADS,
        HMAC_KEY_COMMITMENT,
        HUMAN_DOMAIN,
        REPO,
        RESTRICTED,
        RESTRICTED_R2_MAPPING_NAME,
        RESPONSE_SET_RECEIPT_SHA256,
        R1,
        R1_PACKAGE_HASHES,
        RUBRIC_SHA256,
        START_HEAD,
        VISIBLE_FIELDS,
        canonical_human_payload,
        extract_blind_request,
        load_csv,
        r2_rating_id,
        sha256_bytes,
        sha256_file,
    )
    from judge_package_validator_v2 import ALLOWED_FILES, validate_package_zip
except ImportError:  # pragma: no cover - repository package import
    from .build_r3d1_r2_artifacts import (
        APPLICABILITY_SHA256,
        DOWNLOADS,
        HMAC_KEY_COMMITMENT,
        HUMAN_DOMAIN,
        REPO,
        RESTRICTED,
        RESTRICTED_R2_MAPPING_NAME,
        RESPONSE_SET_RECEIPT_SHA256,
        R1,
        R1_PACKAGE_HASHES,
        RUBRIC_SHA256,
        START_HEAD,
        VISIBLE_FIELDS,
        canonical_human_payload,
        extract_blind_request,
        load_csv,
        r2_rating_id,
        sha256_bytes,
        sha256_file,
    )
    from .judge_package_validator_v2 import ALLOWED_FILES, validate_package_zip


HERE = Path(__file__).resolve().parent


class ValidationError(RuntimeError):
    """Raised on the first failed immutable R2 check."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def zip_members(path: Path) -> dict[str, bytes]:
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def csv_rows(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


def validate() -> dict[str, Any]:
    passed: list[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise ValidationError(name)
        passed.append(name)

    check("exact_response_set_receipt_hash", sha256_file(R1 / "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json") == RESPONSE_SET_RECEIPT_SHA256)
    check("r1_tracked_directory_unchanged", subprocess.run(["git", "diff", "--quiet", START_HEAD, "--", str(R1.relative_to(REPO))], cwd=REPO).returncode == 0)
    source = load_json(HERE / "c4_real_r3d1_r2_source_preservation_manifest_v1.json")
    check("source_preservation_status", source["status"].startswith("PASS_"))
    check("canonical_response_count", source["canonical_response_identities"] == 147)
    check("distinct_answer_text_hashes", source["distinct_answer_text_hashes"] == 146)
    check("duplicate_text_group_count", source["permitted_duplicate_text_groups"] == 1)
    check("duplicate_text_record_count", source["permitted_duplicate_text_records"] == 2)
    check("condition_response_mapping_count", source["condition_response_mappings"] == 558)
    check("exact_payload_duplicate_mapping_count", source["exact_payload_duplicate_condition_mappings"] == 411)
    check("validator_v2_valid_count", source["validator_v2_valid_responses"] == 147)
    check("g2_response_count_zero", source["g2_responses_included"] == 0)
    check("canonical_jsonl_hash", sha256_file(R1 / "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl") == source["canonical_response_jsonl_sha256"])
    check("canonical_csv_hash", sha256_file(R1 / "c4_real_r3_canonical_unique_responses_frozen_v1.csv") == source["canonical_response_csv_sha256"])
    check("condition_jsonl_hash", sha256_file(RESTRICTED / "c4_real_r3_condition_response_records_frozen_v1.jsonl") == source["condition_response_jsonl_sha256"])
    check("condition_csv_hash", sha256_file(RESTRICTED / "c4_real_r3_condition_response_records_frozen_v1.csv") == source["condition_response_csv_sha256"])

    supersession = load_json(HERE / "c4_real_r3d1_r1_package_supersession_r2_v1.json")
    check("five_r1_supersession_records", len(supersession["records"]) == 5)
    check("r1_supersession_label", all(row["r3d1_r2_status"] == "SUPERSEDED_UNEXECUTED_OR_UNRATED_BY_R3D1_R2" for row in supersession["records"]))
    for name, digest in R1_PACKAGE_HASHES.items():
        check(f"r1_package_preserved_{name}", sha256_file(DOWNLOADS / name) == digest)

    audit = load_json(HERE / "c4_real_r3d1_r2_preexecution_audit_v1.json")
    check("preexecution_audit_status", audit["status"] == "PASS_INDEPENDENT_PREEXECUTION_AUDIT")
    check("judge_audit_request_count", audit["judge"]["requests_inspected"] == 147)
    check("applicability_distribution", audit["judge"]["applicable_primary_count_distribution"] == {"4": 8, "5": 49, "6": 43, "7": 33, "8": 14})
    check("old_mean_6_failure_reproduced", audit["judge"]["r1_exact_mean_failure"]["r1_normally_rounded_failure_examples"]["6"]["r1_rejected"] is True)
    check("old_mean_7_failure_reproduced", audit["judge"]["r1_exact_mean_failure"]["r1_normally_rounded_failure_examples"]["7"]["r1_rejected"] is True)
    check("semantic_equivalence_147", audit["judge"]["r1_exact_mean_failure"]["synthetic_contract_comparisons"] == 147 and audit["judge"]["r1_exact_mean_failure"]["semantic_outputs_identical"] is True)
    check("human_audit_condition_rows", audit["human"]["condition_level_rows"] == 108)
    check("human_audit_unique_payloads", audit["human"]["distinct_payloads"] == 44)
    check("human_audit_duplicate_mappings", audit["human"]["duplicate_extra_rows"] == 64)
    check("human_audit_max_group", audit["human"]["maximum_group_size"] == 8)

    prompt = (HERE / "c4_real_judge_prompt_r2_provider_compatible.txt").read_text("utf-8")
    schema = load_json(HERE / "c4_real_judge_schema_r2_provider_compatible.json")
    check("provider_schema_strict", schema["additionalProperties"] is False)
    check("provider_schema_no_result_id", "response_blind_id" not in schema["properties"])
    check("provider_schema_no_mean", "overall_applicable_mean" not in schema["properties"])
    check("provider_prompt_no_echo_instruction", "Do not return or echo the opaque result ID" in prompt)
    check("provider_prompt_no_mean_instruction", "Do not calculate or return overall_applicable_mean" in prompt)
    check("provider_prompt_single_placeholder", prompt.count("{{BLIND_JUDGE_REQUEST_JSON}}") == 1)
    check("rubric_hash_frozen", RUBRIC_SHA256 == sha256_file(REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_primary_eight_criterion_rubric_v1.json"))
    check("applicability_contract_hash_frozen", APPLICABILITY_SHA256 == sha256_file(REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_dimension_applicability_v1.json"))

    r1_judge = load_jsonl(R1 / "c4_real_unique_judge_request_manifest_frozen_v1.jsonl")
    r2_judge = load_jsonl(HERE / "c4_real_unique_judge_request_manifest_frozen_r2.jsonl")
    check("r2_judge_request_count", len(r2_judge) == 147)
    check("r2_shard_counts", {shard: sum(row["shard_id"] == shard for row in r2_judge) for shard in "ABC"} == {"A": 49, "B": 49, "C": 49})
    check("judge_ids_preserved", [(row["logical_judge_request_id"], row["judge_result_blind_id"], row["shard_id"]) for row in r1_judge] == [(row["logical_judge_request_id"], row["judge_result_blind_id"], row["shard_id"]) for row in r2_judge])
    check("substantive_judge_inputs_preserved", all(extract_blind_request(old["provider_payload"]) == extract_blind_request(new["provider_payload"]) for old, new in zip(r1_judge, r2_judge)))
    check("provider_payload_hashes_recompute", all(sha256_bytes(json.dumps(row["provider_payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) == row["provider_payload_sha256"] for row in r2_judge))

    judge_manifest = load_json(HERE / "c4_real_judge_package_manifest_r2_v1.json")
    for shard in "ABC":
        item = judge_manifest["packages"][shard]
        path = DOWNLOADS / item["file_name"]
        result = validate_package_zip(path)
        check(f"judge_r2_package_hash_{shard}", sha256_file(path) == item["sha256"])
        check(f"judge_r2_package_allowlist_{shard}", set(zip_members(path)) == ALLOWED_FILES)
        check(f"judge_r2_package_requests_{shard}", result["request_count"] == 49)
        check(f"judge_r2_package_attempt_cap_{shard}", result["maximum_physical_attempts"] == 98)
        check(f"judge_r2_package_tests_{shard}", item["offline_package_tests_passed"] == 16 and item["offline_package_tests_failed"] == 0)
    check("judge_r2_calls_zero", judge_manifest["judge_calls"] == 0)
    check("judge_r2_no_credentials", judge_manifest["credentials_included"] is False)
    check("judge_r2_no_restricted_mapping", judge_manifest["restricted_mapping_or_hmac_key_included"] is False)
    check("judge_r2_no_condition_identity", judge_manifest["scenario_family_mode_condition_identity_included"] is False)
    check("judge_r2_no_existing_outputs", judge_manifest["existing_judge_outputs_included"] is False)

    rubric = load_json(REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_primary_eight_criterion_rubric_v1.json")
    guide = (HERE / "HUMAN_RATER_GUIDE_R2.md").read_text("utf-8")
    check("human_guide_all_40_anchors", all(text in guide for criterion in rubric["criteria"] for text in criterion["behavioural_anchors"].values()))
    check("human_guide_all_8_na_rules", all(criterion["na_rule"] in guide for criterion in rubric["criteria"]))
    check("human_guide_no_verbosity_reward", "Do not reward length" in guide and "verbosity by itself" in guide)
    check("human_guide_supplied_evidence_only", "Evaluate only supplied evidence" in guide)
    check("human_guide_poor_is_low_not_na", "receives a low score, not `NA`" in guide)
    check("human_guide_short_rationales", "short, criterion-specific rationale" in guide)
    check("human_guide_wrap_instructions", "enable text wrapping" in guide)

    human_manifest = load_json(HERE / "c4_real_human_packet_manifest_r2_v1.json")
    human_rows: dict[str, list[dict[str, str]]] = {}
    for role in "AB":
        item = human_manifest["packages"][role]
        path = DOWNLOADS / item["file_name"]
        members = zip_members(path)
        expected_names = {"HUMAN_RATER_GUIDE_R2.md", "PRIMARY_RUBRIC.json", f"human_rating_packet_{role}.csv", f"human_rater_attestation_{role}.md", "PACKET_MANIFEST.json"}
        check(f"human_r2_package_hash_{role}", sha256_file(path) == item["sha256"])
        check(f"human_r2_package_allowlist_{role}", set(members) == expected_names)
        check(f"human_r2_rubric_hash_{role}", sha256_bytes(members["PRIMARY_RUBRIC.json"]) == RUBRIC_SHA256)
        rows = csv_rows(members[f"human_rating_packet_{role}.csv"])
        human_rows[role] = rows
        check(f"human_r2_item_count_{role}", len(rows) == 44)
        blank = [field for field in rows[0] if field.endswith("_rating") or field.endswith("_rationale")]
        check(f"human_r2_blank_ratings_{role}", all(not row[field] for row in rows for field in blank))
        check(f"human_r2_unique_payloads_{role}", len({sha256_bytes(canonical_human_payload(row)[0]) for row in rows}) == 44)
        joined = b"".join(members.values())
        check(f"human_r2_no_hmac_key_{role}", b"c4_real_i1_blinding_hmac_key.bin" not in joined)
        check(f"human_r2_no_restricted_mapping_{role}", RESTRICTED_R2_MAPPING_NAME.encode() not in joined)
    ids = {role: [row["rating_item_id"] for row in human_rows[role]] for role in "AB"}
    check("human_r2_same_item_set", set(ids["A"]) == set(ids["B"]))
    check("human_r2_different_order", ids["A"] != ids["B"])

    restricted_path = RESTRICTED / RESTRICTED_R2_MAPPING_NAME
    restricted_metadata = load_json(HERE / "c4_real_human_restricted_mapping_metadata_r2_v1.json")
    restricted_rows = load_csv(restricted_path)
    check("restricted_r2_mapping_hash", sha256_file(restricted_path) == restricted_metadata["mapping_sha256"])
    check("restricted_r2_mapping_mode", stat.S_IMODE(restricted_path.stat().st_mode) == 0o600)
    check("restricted_r2_mapping_ignored", subprocess.run(["git", "check-ignore", "-q", str(restricted_path.relative_to(REPO))], cwd=REPO).returncode == 0)
    check("restricted_r2_mapping_rows", len(restricted_rows) == 108)
    check("restricted_r2_unique_ids", len({row["r2_rating_item_id"] for row in restricted_rows}) == 44)
    check("restricted_r2_selected_families", len({row["scenario_id"] for row in restricted_rows}) == 12)
    r1_mapping = load_csv(RESTRICTED / "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv")
    check("r1_human_mapping_set_preserved", {row["r1_rating_item_id"] for row in restricted_rows} == {row["rating_item_id"] for row in r1_mapping})
    r1_mapping_by_id = {row["rating_item_id"]: row for row in r1_mapping}
    preserved_mapping_fields = (
        "replay_record_id",
        "scenario_id",
        "mode_id",
        "generation_logical_request_id",
        "generation_response_blind_id",
        "judge_logical_request_id",
        "judge_result_blind_id",
    )
    check(
        "r1_condition_mapping_values_preserved",
        all(
            all(
                row[field] == r1_mapping_by_id[row["r1_rating_item_id"]][field]
                for field in preserved_mapping_fields
            )
            for row in restricted_rows
        ),
    )
    r1_human_a_members = zip_members(
        DOWNLOADS / "C4_REAL_HUMAN_RATER_A_PACKET_2026-09-02.zip"
    )
    r1_human_a_rows = csv_rows(r1_human_a_members["human_rating_packet_A.csv"])
    r1_payload_hash_by_id = {
        row["rating_item_id"]: sha256_bytes(canonical_human_payload(row)[0])
        for row in r1_human_a_rows
    }
    check(
        "r1_to_r2_complete_visible_payload_binding",
        all(
            row["human_visible_payload_sha256"]
            == r1_payload_hash_by_id[row["r1_rating_item_id"]]
            for row in restricted_rows
        ),
    )
    public_hash_by_id = {row["rating_item_id"]: sha256_bytes(canonical_human_payload(row)[0]) for row in human_rows["A"]}
    check("restricted_payload_hash_binding", all(public_hash_by_id[row["r2_rating_item_id"]] == row["human_visible_payload_sha256"] for row in restricted_rows))
    key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
    key = key_path.read_bytes()
    check("hmac_key_commitment", sha256_bytes(key) == HMAC_KEY_COMMITMENT)
    check("hmac_key_mode", stat.S_IMODE(key_path.stat().st_mode) == 0o600)
    check("hmac_domain_recorded", restricted_metadata["hmac_domain_separation"] == HUMAN_DOMAIN)
    check("r2_hmac_ids_recompute", all(r2_rating_id(key, canonical_human_payload(row)[0]) == row["rating_item_id"] for row in human_rows["A"]))

    judge_receipt = load_json(HERE / "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT_R2.json")
    human_receipt = load_json(HERE / "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT_R2.json")
    status_text = (HERE / "STATUS.md").read_text("utf-8")
    check("judge_receipt_zero_calls", judge_receipt["judge_calls"] == 0)
    check("human_receipt_zero_ratings", human_receipt["ratings_completed"] == 0 and human_receipt["rationales_completed"] == 0)
    check("human_receipt_counts", (human_receipt["condition_level_sample_mappings"], human_receipt["unique_human_visible_item_count"], human_receipt["duplicate_mapping_count"]) == (108, 44, 64))
    check("ready_status_exact", "RQ3_REAL_R3D1_R2_STATUS = READY_FOR_C4_REAL_JUDGE_EXECUTION_AND_INDEPENDENT_HUMAN_REVIEW_R2" in status_text)
    check("zero_action_audit", (audit["provider_calls"], audit["judge_calls"], audit["response_quality_scores"], audit["human_ratings"], audit["streamlit_launches"]) == (0, 0, 0, 0, 0))

    return {
        "schema_version": "c4-real-r3d1-r2-validation-result-v1",
        "status": "PASS",
        "checks_passed": len(passed),
        "checks_failed": 0,
        "check_names": passed,
    }


def main() -> int:
    print(json.dumps(validate(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
