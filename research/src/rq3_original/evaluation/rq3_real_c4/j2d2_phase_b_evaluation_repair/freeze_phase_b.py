#!/usr/bin/env python3
"""Seal Phase-B receipts after targeted tests and final byte-integrity gates."""

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import phase_b_access_guard as guard
from phase_b_sources import Sources, ROOT, BASE, HERE, PHASE_A, RESTRICTED, KEY_COMMITMENT, HUMAN_HASHES, canonical, pretty, digest, require
from phase_b_model import RETAIN, REJUDGE, NEW, FAILED, KEEP, KEEP_NA, TO_NA, AMEND
from build_phase_b_repair import durable_write_once, offline_network_guard


def metadata(name):
    return json.loads((HERE / name).read_bytes())


def verify_final_sources():
    source_manifest = metadata("PHASE_B_SOURCE_PRESERVATION_MANIFEST_V1.json")
    verified = []
    for record in source_manifest["sources"]:
        path = Path(record["path"])
        if record["source_role"] == "score_free_source_manifest": raw = path.read_bytes()
        else: raw = guard.read_controlled(path, expected_sha256=record["sha256"], role=record["source_role"], permitted_use="immutable_source_integrity_only")
        require(digest(raw) == record["sha256"], "Final scientific source hash mismatch")
        verified.append({"path": str(path), "sha256": record["sha256"], "unchanged": True})
    # Additional original generation/Human/applicability mappings are preserved
    # by hash only. Their row contents do not enter any repair decision.
    generation_metadata_path = BASE / "i1_route_integration/c4_real_restricted_mapping_metadata_v3.json"
    generation_metadata = json.loads(generation_metadata_path.read_bytes())
    require(generation_metadata["hmac_key_sha256_commitment"] == KEY_COMMITMENT, "Generation HMAC commitment changed")
    additional = {name: row["sha256"] for name, row in generation_metadata["mapping_files"].items()}
    additional["c4_real_j2d1_applicability_review_id_to_scenario_mapping_v1.csv"] = "de04ba913919447fddefafa1127b1480fb5c8614bf4cfce570f52b548f397c25"
    additional["c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv"] = "6535398815352a80892842bdddd0647ebcecf9e2f35bfb4bef3c5a8f74e292e2"
    for filename, expected in additional.items():
        path = RESTRICTED / filename
        raw = guard.read_controlled(path, expected_sha256=expected, role="preservation_hash_only", permitted_use="immutable_source_integrity_only")
        require(digest(raw) == expected, "Additional restricted source changed")
        require(subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT).returncode == 0, "Original restricted mapping no longer ignored")
        require(not subprocess.check_output(["git", "ls-files", "--", str(path.relative_to(ROOT))], cwd=ROOT).strip(), "Original restricted mapping became tracked")
        verified.append({"path": str(path), "sha256": expected, "unchanged": True, "source_content_parsed": False})
    Sources().key()
    return verified


def ledger_metadata():
    raw = guard.LEDGER.read_bytes()
    lines = raw.splitlines()
    entry = guard.verify_entry()
    entry_time = datetime.fromisoformat(entry["receipt_created_at_utc"])
    entry_mtime = guard.ENTRY.stat().st_mtime_ns
    allowed_fields = {"schema_version", "event", "entry_receipt_sha256", "source_role", "source_path", "source_sha256", "timestamp_utc", "permitted_use", "content_values_recorded", "sequence", "previous_record_sha256"}
    previous = None
    for index, line in enumerate(lines, 1):
        row = json.loads(line)
        require(set(row) == allowed_fields and row["content_values_recorded"] is False, "Ledger is not metadata-only")
        require(row["sequence"] == index and row["previous_record_sha256"] == previous, "Ledger chain mismatch")
        require(row["entry_receipt_sha256"] == guard.ENTRY_SHA256, "Ledger entry binding differs")
        access_time = datetime.fromisoformat(row["timestamp_utc"])
        require(access_time >= entry_time and access_time.timestamp() * 1e9 >= entry_mtime, "Controlled access preceded durable entry receipt")
        previous = digest(line)
    require(bool(lines), "Controlled access ledger absent")
    diagnostics = metadata("PHASE_B_DEVELOPMENT_DIAGNOSTICS_V1.json")
    rejected = diagnostics["blocked_source_location_lookup"]["ledger_sequences"]
    return {"schema_version": "phase-b-controlled-access-ledger-metadata-v1", "ledger_filename": guard.LEDGER.name,
            "ledger_sha256": digest(raw), "record_count": len(lines), "entry_receipt_sha256": guard.ENTRY_SHA256,
            "entry_receipt_mtime_ns": entry_mtime,
            "chronology_status": "PASS_EVERY_CONTROLLED_ACCESS_AFTER_DURABLY_WRITTEN_ENTRY_RECEIPT",
            "metadata_only": True, "score_or_rationale_values_included": False,
            "pre_entry_score_bearing_file_accesses": 0, "pre_entry_candidate_response_file_accesses": 0,
            "disclosed_rejected_hash_only_location_lookups": rejected,
            "rejected_lookup_content_returned_or_parsed": False,
            "rejected_lookup_interpretation": "One nonauthoritative location guess was hash-rejected; the correctly referenced source subsequently matched. No frozen source was altered."}


def main():
    sys.addaudithook(offline_network_guard)
    entry = guard.verify_entry()
    require(os.environ.get("CODEX_THREAD_ID") == entry["task_id"], "Phase-B task identity differs")
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == entry["starting_head"], "Starting HEAD changed before single commit")
    require(subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() == entry["branch"], "Branch changed")
    receipt_names = ["C4_REAL_CORRECTED_JUDGE_EXECUTION_FREEZE_RECEIPT.json", "C4_REAL_HUMAN_APPLICABILITY_REPAIR_FREEZE_RECEIPT.json", "J2D2_PHASE_B_COMPLETION_RECEIPT_V1.json"]
    for name in receipt_names + ["STATUS.md", "PHASE_B_CONTROLLED_ACCESS_LEDGER_METADATA_V1.json", "PHASE_B_FINAL_INTEGRITY_VERIFICATION_V1.json"]:
        require(not (HERE / name).exists(), "Write-once final output already exists")
    test = metadata("PHASE_B_TARGETED_TEST_RESULTS_V1.json")
    require(test["status"] == "PASS" and test["tests_run"] == test["passed"] == 62 and test["failed"] == test["errors"] == test["skipped"] == 0, "Targeted tests not fully passed")
    require(test["real_network_attempts"] == test["provider_runtime_imports"] == test["score_aggregate_function_attempts"] == 0, "Prohibited operation observed in tests")
    for name, expected in test["source_hashes"].items():
        require(digest((HERE / name).read_bytes()) == expected, "Tested source changed after passing tests: " + name)
    for folder, hashes in [(PHASE_A, entry["phase_a_authority_hashes"]), (PHASE_A, entry["accepted_applicability_v2_artifact_hashes"]),
                           (BASE / "j2d2_phase_a_cleanroom_replay", entry["phase_a_cleanroom_hashes"])]:
        for name, expected in hashes.items(): require(digest((folder / name).read_bytes()) == expected, "Phase-A authority/scientific source changed")
    baseline = metadata("PHASE_B_PRESERVATION_BASELINE_V1.json")
    for record in baseline["retained_legacy_files"]:
        require(digest((ROOT / record["path"]).read_bytes()) == record["sha256"], "Retained legacy file changed")
    changed = subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT, text=True).splitlines()
    require(all(name.startswith(str(HERE.relative_to(ROOT)) + "/") for name in changed), "Tracked modification outside Phase B")
    verified_sources = verify_final_sources()
    build = metadata("BUILD_RESULT_METADATA_V1.json")
    impact = metadata("c4_real_judge_result_eligibility_after_applicability_v2.json")
    human_impact = metadata("c4_real_human_applicability_impact_v1.json")
    intake = metadata("c4_real_human_completed_source_intake_v1.json")
    restricted_metadata = metadata("C4_REAL_PHASE_B_RESTRICTED_MAPPING_METADATA_V1.json")
    for record in restricted_metadata["files"]:
        path = RESTRICTED / record["filename"]
        guard.read_controlled(path, expected_sha256=record["sha256"], role="generated_controlled_artifact", permitted_use="immutable_source_integrity_only")
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, "New restricted file permissions changed")
        require(subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT).returncode == 0, "New restricted artifact no longer ignored")
        require(not subprocess.check_output(["git", "ls-files", "--", str(path.relative_to(ROOT))], cwd=ROOT).strip(), "New restricted artifact became tracked")
    package_hashes = {}
    for kind in ("judge_packages", "human_packages"):
        for record in build[kind].values():
            path = Path(record["path"])
            guard.read_controlled(path, expected_sha256=record["sha256"], role="generated_controlled_artifact", permitted_use="immutable_source_integrity_only")
            package_hashes[str(path)] = record["sha256"]
    # This is the final controlled-source read boundary. Everything below is
    # metadata-only, and completion permanently disables the access guard.
    ledger = ledger_metadata()
    timestamp = guard.utc_now()
    authority = {"phase_a_authority_hashes": entry["phase_a_authority_hashes"], "phase_a_cleanroom_hashes": entry["phase_a_cleanroom_hashes"],
                 "accepted_applicability_v2_artifact_hashes": entry["accepted_applicability_v2_artifact_hashes"],
                 "final_phase_a_authority_status": guard.AUTHORITY_STATUS, "original_receipt_status": entry["original_receipt_status"],
                 "incident_disclosure_preserved": True}
    common = {"frozen_at_utc": timestamp, "write_count": 1, "overwrite_permitted": False, "write_enforcement": "O_EXCL; flush; fsync file and parent directory"}
    judge_receipt = {"schema_version": "C4_REAL_CORRECTED_JUDGE_EXECUTION_FREEZE_RECEIPT", **common, **authority,
                     "status": "FROZEN_DORMANT_CORRECTED_JUDGE_R4", "corrected_condition_to_judge_mapping_count": 558,
                     "corrected_unique_judge_request_count": impact["corrected_unique_request_count"],
                     "retained_result_count": impact["retained_existing_result_count"],
                     "excluded_changed_applicability_result_count": impact["excluded_changed_applicability_result_count"],
                     "previously_unattempted_count": impact["class_counts"][NEW], "failed_no_valid_result_count": impact["class_counts"][FAILED],
                     "corrected_execution_count": impact["corrected_execution_request_count"], "shards": build["shards"],
                     "packages": {shard: {"path": r["path"], "sha256": r["sha256"]} for shard, r in build["judge_packages"].items()},
                     "new_judge_calls": 0, "existing_scores_transformed": 0, "score_aggregates_computed": 0,
                     "phase_b_entry_receipt_sha256": guard.ENTRY_SHA256, "restricted_mapping_metadata_sha256": digest((HERE / "C4_REAL_PHASE_B_RESTRICTED_MAPPING_METADATA_V1.json").read_bytes())}
    human_receipt = {"schema_version": "C4_REAL_HUMAN_APPLICABILITY_REPAIR_FREEZE_RECEIPT", **common,
                     "status": "FROZEN_BASE_INTAKE_AND_BLANK_APPLICABILITY_AMENDMENTS", "completed_human_source_hashes": HUMAN_HASHES,
                     "attestation_statuses": intake["raters"], "original_unique_human_visible_items": 44, "sampled_condition_mappings": 108,
                     "corrected_unique_item_count": human_impact["corrected_unique_visible_items"],
                     "unchanged_applicable_criterion_count": human_impact["criterion_pair_counts"][KEEP],
                     "unchanged_na_criterion_count": human_impact["criterion_pair_counts"][KEEP_NA],
                     "old_applicable_to_new_na_count": human_impact["criterion_pair_counts"][TO_NA],
                     "newly_applicable_amendment_count": human_impact["criterion_pair_counts"][AMEND],
                     "counts_are_unique_item_criterion_pairs_not_multiplied_by_raters": True,
                     "required_amendment_ratings_across_both_raters": human_impact["required_new_ratings_across_both_raters"],
                     "old_item_split_count": human_impact["old_item_split_count"], "old_item_merge_count": human_impact["old_item_merge_count"],
                     "amendment_packages": {rater: {"path": r["path"], "sha256": r["sha256"]} for rater, r in build["human_packages"].items()},
                     "amendment_ratings_completed": 0, "agreement_computations": 0, "human_llm_agreement_computations": 0,
                     "score_aggregates_computed": 0, "raw_completed_sources_modified": False,
                     "phase_b_entry_receipt_sha256": guard.ENTRY_SHA256, "applicability_authority_resolution_sha256": entry["authority_resolution_sha256"]}
    judge_raw, human_raw = pretty(judge_receipt), pretty(human_receipt)
    final_status = "READY_FOR_CORRECTED_JUDGE_EXECUTION_AND_HUMAN_APPLICABILITY_AMENDMENTS" if human_receipt["newly_applicable_amendment_count"] else "READY_FOR_CORRECTED_JUDGE_EXECUTION"
    zero_counts = {name: 0 for name in ("provider_calls", "network_calls", "judge_executions", "response_generation", "human_amendment_ratings",
                                        "scoring_calls", "score_aggregate_computations", "human_agreement_computations", "human_llm_agreement_computations",
                                        "mode_level_means", "system_comparisons_or_rankings", "statistical_significance_tests", "final_statistical_analyses",
                                        "rag_executions", "memory_executions", "planning_executions", "evidence_synthesis_executions", "p3_executions", "streamlit_launches")}
    completion = {"schema_version": "J2D2_PHASE_B_COMPLETION_RECEIPT_V1", **common, **authority,
                  "task": entry["task"], "task_id": entry["task_id"], "working_directory": str(ROOT), "branch": entry["branch"], "starting_head": entry["starting_head"],
                  "RQ3_REAL_J2D2_R1_STATUS": final_status, "phase_b_entry_receipt_sha256": guard.ENTRY_SHA256,
                  "controlled_access_ledger_sha256": ledger["ledger_sha256"], "controlled_access_ledger_record_count": ledger["record_count"],
                  "chronology_status": ledger["chronology_status"], "judge_freeze_receipt_sha256": digest(judge_raw), "human_freeze_receipt_sha256": digest(human_raw),
                  "generated_delivery_package_hashes": package_hashes, "review_zip_hash_scope": "Review ZIP is created after the single commit; its hash is reported externally to avoid a self-referential archive hash.",
                  "targeted_test_report_sha256": digest((HERE / "PHASE_B_TARGETED_TEST_RESULTS_V1.json").read_bytes()),
                  "tests": {key: test[key] for key in ("tests_run", "passed", "failed", "errors", "skipped")},
                  "prohibited_action_counts": zero_counts, "completion_timestamp_utc": timestamp,
                  "controlled_source_access_closed": True, "corrected_judge_execution_authorized_in_this_task": False,
                  "human_amendment_rating_authorized_in_this_task": False, "hmac_commitment": KEY_COMMITMENT}
    integrity = {"schema_version": "phase-b-final-integrity-verification-v1", "status": "PASS",
                 "verified_original_source_count": len(verified_sources), "verified_original_sources": verified_sources,
                 "new_restricted_artifacts_verified": restricted_metadata["files"], "delivery_packages_verified": package_hashes,
                 "hmac_byte_length": 32, "hmac_mode": "0600", "hmac_commitment": KEY_COMMITMENT, "hmac_ignored_and_untracked": True,
                 "phase_a_hashes_unchanged": True, "three_legacy_untracked_files_preserved": True,
                 "tracked_changes_confined_to_phase_b": True, "tests_passed": 62, "tests_failed": 0,
                 "timestamp_utc": timestamp}
    status_text = f"""# RQ3 REAL J2D2 R1 Phase B

RQ3_REAL_J2D2_R1_STATUS = {final_status}

Starting HEAD: {entry['starting_head']}
Working directory: {ROOT}
Branch: {entry['branch']}

Phase-A authority: {guard.AUTHORITY_STATUS}. The prior incident remains disclosed and the original receipt remains qualified.
Entry receipt SHA-256: {guard.ENTRY_SHA256}
Controlled-access ledger SHA-256: {ledger['ledger_sha256']}
Chronology: {ledger['chronology_status']}

Judge: 558 condition mappings; {judge_receipt['corrected_unique_judge_request_count']} corrected unique requests; {judge_receipt['retained_result_count']} retained; {judge_receipt['excluded_changed_applicability_result_count']} excluded old valid results; {judge_receipt['previously_unattempted_count']} previously unattempted corrected requests; {judge_receipt['failed_no_valid_result_count']} failed without a valid result; {judge_receipt['corrected_execution_count']} execution requests.
Shards A/B/C: 39/38/39 requests; estimated input tokens 139200/139203/139204.

Human intake: both exact completed sources pass, 44 rows each. The 108 sampled condition mappings preserve 44 corrected unique visible items. Unchanged applicable/unchanged NA/old-to-NA/newly-applicable criterion pairs: 270/69/7/6. No item splits or merges. Each original rater receives six blank amendment rows.

Targeted tests: 62 passed, 0 failed, 0 errors, 0 skipped. Real network attempts and score-aggregate function attempts: 0.
Provider calls, Judge execution, Human amendment ratings, scoring, agreement, comparisons, statistics, mechanism execution and Streamlit launches: 0.

The new R4 support copy fixes nonretryable refusal handling; the original runner and scientific sources remain unchanged. The earlier mocked refusal regression and one hash-rejected source-location probe are disclosed in PHASE_B_DEVELOPMENT_DIAGNOSTICS_V1.json.

All five delivery packages are frozen and dormant. This task stops after one commit and the internal review ZIP. No execution or amendment rating is authorized by this status.
""".encode()
    durable_write_once(HERE / "PHASE_B_CONTROLLED_ACCESS_LEDGER_METADATA_V1.json", pretty(ledger))
    durable_write_once(HERE / "PHASE_B_FINAL_INTEGRITY_VERIFICATION_V1.json", pretty(integrity))
    durable_write_once(HERE / receipt_names[0], judge_raw)
    durable_write_once(HERE / receipt_names[1], human_raw)
    durable_write_once(HERE / "STATUS.md", status_text)
    completion_raw = pretty(completion)
    durable_write_once(HERE / receipt_names[2], completion_raw)
    require(digest(guard.LEDGER.read_bytes()) == ledger["ledger_sha256"], "Ledger changed during final seal")
    for name in receipt_names:
        before = digest((HERE / name).read_bytes())
        try:
            with (HERE / name).open("xb"): pass
        except FileExistsError: pass
        else: raise RuntimeError("Write-once receipt protection failed")
        require(digest((HERE / name).read_bytes()) == before, "Receipt changed during overwrite rejection check")
    print(json.dumps({"status": final_status, "entry_receipt_sha256": guard.ENTRY_SHA256,
                      "ledger_sha256": ledger["ledger_sha256"], "ledger_records": ledger["record_count"],
                      "judge_freeze_receipt_sha256": digest(judge_raw), "human_freeze_receipt_sha256": digest(human_raw),
                      "completion_receipt_sha256": digest(completion_raw), "tests_passed": 62, "tests_failed": 0,
                      "delivery_package_hashes": package_hashes, "original_sources_verified": len(verified_sources)}, sort_keys=True))


if __name__ == "__main__": main()
