"""Close the controlled ledger and write the one final analysis receipt.

This finalization reads hashes and aggregate metadata only. It does not decode
restricted mappings or scores and must follow the successful targeted tests.
"""
from collections import Counter
from datetime import datetime
import json
import os

from f1_common import *
from f1_controlled_unblinding_guard import verify_entry
from f1_entry_binding import ENTRY_RECEIPT_SHA256

FINAL_STATUS = "FINAL_RQ3_REAL_C4_ANALYSIS_COMPLETE"
LEDGER_KEYS = {"schema_version", "access_sequence", "timestamp_utc", "entry_receipt_sha256", "source_path",
               "source_sha256", "purpose", "reader_script", "access_operation", "previous_record_sha256"}
LATE_PACKAGE_FILES = ["F1_REVIEW_PACKAGE_MANIFEST_V1.json", "F1_REVIEW_PACKAGE_AUDIT_V1.json"]


def verify_ledger():
    entry, digest = verify_entry()
    raw_lines = LEDGER.read_bytes().splitlines()
    rows = [json.loads(line) for line in raw_lines]
    previous = None
    timestamp = datetime.fromisoformat(entry["frozen_at_utc"])
    assert rows, "EMPTY_UNBLINDING_LEDGER"
    snapshot = read_json(HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json")["files"]
    raw_meta = read_json(HERE / "F1_RESTRICTED_ANALYSIS_METADATA_V1.json")["files"]
    additions = {str((RI / r["filename"]).relative_to(ROOT)): r["sha256"] for r in raw_meta}
    known = snapshot | additions
    for number, (line, row) in enumerate(zip(raw_lines, rows), 1):
        assert set(row) == LEDGER_KEYS, "LEDGER_NOT_METADATA_ONLY"
        assert row["access_sequence"] == number and row["previous_record_sha256"] == previous
        assert row["entry_receipt_sha256"] == digest
        assert row["source_sha256"] == known[row["source_path"]]
        current = datetime.fromisoformat(row["timestamp_utc"])
        assert current >= timestamp, "LEDGER_ACCESS_ORDER_VIOLATION"
        timestamp = current
        previous = sha_bytes(line)
    return rows, previous


def source_preservation():
    snapshot_path = HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json"
    snapshot = read_json(snapshot_path)
    assert all(sha(ROOT / p) == digest for p, digest in snapshot["files"].items()), "FROZEN_SOURCE_CHANGED"
    assert all(sha(ROOT / p) == digest for p, digest in EXPECTED_HASHES.items()), "AUTHORITY_SOURCE_CHANGED"
    gates = read_json(HERE / "F1_STARTING_GATES_V1.json")
    for row in gates["retained_untracked_files"]:
        assert sha(ROOT / row["path"]) == row["sha256"]
        assert not git("ls-files", "--", row["path"])
    metadata = read_json(HERE / "F1_RESTRICTED_ANALYSIS_METADATA_V1.json")
    for row in metadata["files"]:
        path = RI / row["filename"]
        assert sha(path) == row["sha256"] and (path.stat().st_mode & 0o777) == 0o600
        assert not git("ls-files", "--", str(path.relative_to(ROOT)))
        assert git("check-ignore", "--", str(path.relative_to(ROOT)))
    key = RI / "c4_real_i1_blinding_hmac_key.bin"
    assert key.stat().st_size == 32 and (key.stat().st_mode & 0o777) == 0o600
    changed = git("diff", "--name-only", STARTING_HEAD).splitlines()
    assert all(p.startswith(str(HERE.relative_to(ROOT)) + "/") for p in changed)
    return {"schema_version": "F1_SOURCE_PRESERVATION_FINAL_AUDIT_V1", "status": "PASS",
        "snapshot_sha256": sha(snapshot_path), "pre_existing_files_verified": len(snapshot["files"]),
        "changed_or_missing_pre_existing_files": 0, "specified_authority_hashes_verified": len(EXPECTED_HASHES),
        "retained_untracked_files_verified": len(gates["retained_untracked_files"]),
        "restricted_analysis_outputs_verified": len(metadata["files"]),
        "restricted_output_permissions": "0600", "restricted_outputs_ignored_and_untracked": True,
        "hmac_key_size": 32, "hmac_key_commitment": EXPECTED_HASHES[str(key.relative_to(ROOT))],
        "restricted_identity_or_score_decoding_in_finalizer": False,
        "previous_tracked_artifacts_modified": 0, "timestamp_utc": now()}


def main():
    assert str(ROOT.resolve()) == EXPECTED_ROOT
    assert git("branch", "--show-current") == EXPECTED_BRANCH
    assert git("rev-parse", "HEAD") == STARTING_HEAD
    assert not FINAL_RECEIPT.exists(), "FINAL_RECEIPT_ALREADY_EXISTS"
    entry, digest = verify_entry()
    tests = read_json(HERE / "F1_TARGETED_TEST_REPORT_V1.json")
    assert tests["status"] == "PASS" and tests["failed"] == tests["errors"] == tests["skipped"] == 0
    for path, expected in tests["tested_file_hashes"].items():
        assert sha(HERE / path) == expected, "FILE_CHANGED_SINCE_FINAL_TESTS"
    visual = read_json(HERE / "F1_FIGURE_VISUAL_QA_V1.json")
    assert visual["figures_reviewed"] == 4 and visual["pdf_glyph_audits_passed"] == 4
    assert visual["comparable_panel_alignment_audits_passed"] == 1
    assert visual["status"] == "PASS_WITH_DISCLOSED_PDF_COLLISION_TOOL_LIMITATION"
    rows, tail = verify_ledger()
    ledger_digest = sha(LEDGER)
    write_json(HERE / "F1_UNBLINDING_LEDGER_METADATA_V1.json", {
        "schema_version": "F1_UNBLINDING_LEDGER_METADATA_V1", "status": "PASS",
        "ledger_filename": LEDGER.name, "ledger_sha256": ledger_digest,
        "record_count": len(rows), "last_record_sha256": tail,
        "entry_receipt_sha256": digest, "entry_frozen_at_utc": entry["frozen_at_utc"],
        "first_access_at_utc": rows[0]["timestamp_utc"], "last_access_at_utc": rows[-1]["timestamp_utc"],
        "per_reader_counts": dict(sorted(Counter(r["reader_script"] for r in rows).items())),
        "per_purpose_counts": dict(sorted(Counter(r["purpose"] for r in rows).items())),
        "metadata_only_schema_keys": sorted(LEDGER_KEYS), "score_or_rationale_values_present": False,
        "hash_chain_verified": True, "entry_precedes_all_mode_access": True,
        "further_identity_access_closed_by_final_receipt": True})
    preservation = source_preservation()
    write_json(HERE / "F1_SOURCE_PRESERVATION_FINAL_AUDIT_V1.json", preservation)
    status = f"""# RQ3-REAL-C4-F1

RQ3_REAL_F1_STATUS = {FINAL_STATUS}

All eight predeclared paired analyses are complete over 62 scenarios, with 558 condition records and 149 corrected Judge identities. No primary pair was excluded. The five add-one contrasts did not establish a reliable improvement after Holm correction; the targeted Planning removal comparison supports a higher Judge-rated primary outcome with Planning available. This does not establish a reliable full-C4 improvement over Evidence.

The final receipt binds unchanged F0 authority, the sealed F1 entry, the closed metadata-only unblinding ledger, restricted-table hashes, statistical results, mechanism/efficiency summaries, Human measurement interpretation, four figures and the manuscript draft. Original Phase-A incident and qualified Judge pacing evidence remain disclosed. The PDF collision tool is unavailable because PyMuPDF is not installed; the disclosed backend geometry, PDF glyph, alignment and visual checks are complete.

Targeted offline tests: {tests['passed']} passed, 0 failed, 0 errors, 0 skipped. All {preservation['pre_existing_files_verified']} pre-existing snapshot files and {preservation['specified_authority_hashes_verified']} specified authority hashes are unchanged. Human and Judge scores, rationales, applicability and mode definitions are unchanged. F1 Provider/network/Judge/generation/Human-rating/Streamlit/component execution counts are zero.

Completion packaging consists of the directly authorized strict-allowlist ZIP and one local Git commit. Their resulting hashes are recorded in the package audit and final task response. These packaging operations do not reopen restricted identities or perform scientific/model execution. Do not rerun the frozen producers or start another experimental stage under this authorization.
"""
    write_once_bytes(HERE / "STATUS.md", status.encode())
    files = {str(p.relative_to(HERE)): sha(p) for p in sorted(HERE.rglob("*"))
             if p.is_file() and p != FINAL_RECEIPT and p.name not in LATE_PACKAGE_FILES}
    primary_files = [f"C4_REAL_F1_{kind}_V1.{ext}" for kind in
        ["MODE_SUMMARIES", "PRIMARY_CONTRAST_RESULTS", "SECONDARY_OUTCOME_RESULTS"] for ext in ["json", "csv"]]
    mechanism_files = ["C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json", "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.csv",
                       "C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1.json", "C4_REAL_F1_FROZEN_COHORT_SENSITIVITY_V1.json"]
    receipt = {"schema_version": "C4_REAL_FINAL_RQ3_ANALYSIS_FREEZE_RECEIPT_V1", "status": FINAL_STATUS,
        "frozen_at_utc": now(), "working_directory": EXPECTED_ROOT, "branch": EXPECTED_BRANCH, "starting_head": STARTING_HEAD,
        "f0_completion_receipt_sha256": entry["f0_completion_receipt_sha256"],
        "f0_authority_status": "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT",
        "pacing_evidence_status": "QUALIFIED_PACING_EVIDENCE_LIMITATION",
        "f1_pre_unblinding_receipt_sha256": digest, "f1_unblinding_ledger_sha256": ledger_digest,
        "f1_unblinding_ledger_records": len(rows), "mode_registry_sha256": sha(REGISTRY),
        "generic_statistical_contract_sha256": sha(GENERIC), "analysis_hierarchy_sha256": files["F1_ANALYSIS_CONTRACT_HIERARCHY_V1.json"],
        "restricted_analysis_files": read_json(HERE / "F1_RESTRICTED_ANALYSIS_METADATA_V1.json")["files"],
        "primary_outcome": PRIMARY_OUTCOME, "condition_rows": 558, "paired_scenarios": 62, "scenario_families": 62,
        "modes": 9, "corrected_judge_results": 149, "canonical_generated_responses": 147,
        "exact_contrasts": entry["exact_contrasts"], "statistical_algorithms": entry["statistical_algorithms"],
        "bootstrap_replicates": BOOTSTRAP_REPLICATES, "bootstrap_seed": SEED,
        "sign_flip_seed": SEED, "sign_flip_monte_carlo_assignments": MONTE_CARLO_ASSIGNMENTS,
        "sign_flip_rule": "Enumerate 2^F for F<=20; otherwise exactly 100000 assignments and plus-one p correction; retain zeros.",
        "holm_families": read_json(HERE / "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json")["holm_families"],
        "effect_size_formulas": {"paired_dz": "mean(family_mean_differences)/sample_sd(family_mean_differences)",
            "rank_biserial": "(positive_average_rank_sum-negative_average_rank_sum)/(positive_average_rank_sum+negative_average_rank_sum)",
            "zero_and_insufficient_data_guards": "Exact sealed f1_statistics.py guards retained."},
        "primary_and_secondary_result_hashes": {p: files[p] for p in primary_files},
        "mechanism_and_sensitivity_hashes": {p: files[p] for p in mechanism_files},
        "figure_hashes": {p: digest for p, digest in files.items() if p.startswith("figures/")},
        "manuscript_draft_sha256": files["C4_REAL_FINAL_RQ3_MANUSCRIPT_RESULTS_DRAFT.md"],
        "targeted_tests": {k: tests[k] for k in ["passed", "failed", "errors", "skipped"]},
        "source_preservation": preservation, "prohibited_action_counts": PROHIBITED_ACTION_COUNTS,
        "judge_recalibration_operations": 0, "human_treatment_effects_computed": 0,
        "figure_qa_status": visual["status"], "all_frozen_f1_file_hashes": files,
        "late_packaging_metadata_only_files": LATE_PACKAGE_FILES,
        "write_count": 1, "overwrite_permitted": False,
        "write_enforcement": "O_EXCL; file flush and fsync; parent directory fsync; guard closes on receipt existence.",
        "further_unblinding_authorized": False}
    assert sha(LEDGER) == ledger_digest
    final_hash = write_json(FINAL_RECEIPT, receipt)
    print(json.dumps({"status": FINAL_STATUS, "final_receipt_sha256": final_hash,
                      "ledger_sha256": ledger_digest, "ledger_records": len(rows),
                      "frozen_f1_files": len(files)}, indent=2))


if __name__ == "__main__":
    main()
