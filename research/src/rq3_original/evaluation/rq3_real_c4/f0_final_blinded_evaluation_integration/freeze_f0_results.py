"""Validate, write once, test serialized artifacts, and seal F0 controlled access."""
from __future__ import annotations

import io
import json
import unittest
from collections import Counter

import f0_controlled_access_guard as guard
import test_f0_blinded_integration as tests
from f0_blinded_integration import collect
from f0_artifacts import build_artifacts, REVIEW_FILES, JUDGE_REGISTRY, JUDGE_JSONL, JUDGE_CSV, HUMAN_FILES
from f0_common import HERE, ROOT, RESTRICTED, pretty, canonical, digest, durable_write_once, require, utc_now, jsonl_rows

FINAL_STATUS = "READY_FOR_FINAL_MODE_UNBLINDING_AND_PREDECLARED_STATISTICAL_ANALYSIS"


def run_suite(case, stream):
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
    names = [test.id() for test in suite]
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result, names


def seal_ledger():
    raw = guard.LEDGER.read_bytes()
    lines, records = raw.splitlines(), jsonl_rows(raw)
    allowed = {"schema_version", "event", "timestamp_utc", "entry_receipt_sha256", "source_role", "source_path", "source_sha256", "permitted_use", "projected_field_names", "content_values_recorded", "mode_values_decoded", "sequence", "previous_record_sha256"}
    entry = guard.verify_entry()
    for index, record in enumerate(records):
        require(set(record) == allowed and record["content_values_recorded"] is False, "LEDGER_HAS_NON_METADATA_CONTENT")
        require(record["sequence"] == index + 1 and record["entry_receipt_sha256"] == guard.ENTRY_SHA256, "LEDGER_SEQUENCE_OR_ENTRY_MISMATCH")
        require(record["previous_record_sha256"] == (digest(lines[index - 1]) if index else None), "LEDGER_HASH_CHAIN_BROKEN")
        require(record["timestamp_utc"] >= entry["frozen_at_utc"] and record["mode_values_decoded"] == 0, "LEDGER_CHRONOLOGY_OR_BLINDING_FAILURE")
    meta = {"schema_version": "F0_CONTROLLED_ACCESS_LEDGER_METADATA_V1", "filename": guard.LEDGER.name,
            "row_count": len(records), "sha256": digest(raw), "source_role_counts": dict(Counter(r["source_role"] for r in records)),
            "first_access_at_utc": records[0]["timestamp_utc"], "last_access_at_utc": records[-1]["timestamp_utc"],
            "entry_receipt_sha256": guard.ENTRY_SHA256, "all_access_after_fsynced_entry": True,
            "write_ahead_record_per_content_open": True, "score_or_rationale_values_in_ledger": 0,
            "mode_values_decoded": 0, "hash_chain_valid": True,
            "source_hashing_disclosure": "Immutable preservation reads stream bytes only into SHA-256; mode, score and rationale values are not decoded by those operations."}
    durable_write_once(HERE / "F0_CONTROLLED_ACCESS_LEDGER_METADATA_V1.json", pretty(meta))
    return meta


def main():
    require(not guard.COMPLETION.exists(), "F0_ALREADY_FROZEN")
    require(not (HERE / JUDGE_JSONL).exists(), "FROZEN_RESULT_OUTPUT_ALREADY_EXISTS")
    gate = json.loads((HERE / "F0_RESTRICTED_OUTPUT_ENTRY_GATE_V1.json").read_bytes())
    require(gate["status"] == "PASS" and all(r["ignored"] and not r["tracked"] and not r["existed"] for r in gate["files"]), "RESTRICTED_OUTPUT_GATE_FAILED")
    guard.install_offline_guard()
    data = collect()
    artifacts = build_artifacts(data)
    tests.DATA, tests.ARTIFACTS = data, artifacts
    stream = io.StringIO()
    before, before_names = run_suite(tests.F0PreFreezeTests, stream)
    if not before.wasSuccessful():
        durable_write_once(HERE / "F0_PRE_FREEZE_TEST_FAILURE.txt", stream.getvalue().encode())
        raise RuntimeError("F0_TARGETED_PRE_FREEZE_TEST_FAILURE; NO_RESULT_ARTIFACTS_WRITTEN")
    tracked, restricted = artifacts
    require(set(restricted) == {r["filename"] for r in gate["files"]}, "RESTRICTED_OUTPUT_FILENAME_SCOPE_CHANGED")
    for name, raw in tracked.items():
        durable_write_once(HERE / name, raw)
    for name, raw in restricted.items():
        durable_write_once(RESTRICTED / name, raw, mode=0o600)
    after, after_names = run_suite(tests.F0WrittenArtifactTests, stream)
    if not after.wasSuccessful():
        durable_write_once(HERE / "F0_WRITTEN_ARTIFACT_TEST_FAILURE.txt", stream.getvalue().encode())
        raise RuntimeError("F0_WRITTEN_ARTIFACT_TEST_FAILURE; COMPLETION_NOT_FROZEN")
    require(before.testsRun == 44 and after.testsRun == 6, "TARGETED_TEST_INVENTORY_CHANGED")
    test_report = {"schema_version": "F0_TARGETED_TEST_RESULTS_V1", "status": "PASS", "tests_run": 50,
                   "passed": 50, "failed": 0, "errors": 0, "skipped": 0,
                   "pre_freeze_tests": 44, "written_artifact_tests": 6, "test_ids": before_names + after_names,
                   "network_calls": 0, "provider_calls": 0, "human_rating_actions": 0, "mode_unblinding": 0}
    durable_write_once(HERE / "F0_TARGETED_TEST_RESULTS_V1.json", pretty(test_report))
    durable_write_once(HERE / "F0_TARGETED_TEST_OUTPUT_V1.txt", stream.getvalue().encode())
    restricted_checks = []
    for name, raw in restricted.items():
        path = RESTRICTED / name
        require(path.stat().st_mode & 0o777 == 0o600, "RESTRICTED_OUTPUT_PERMISSION_MISMATCH")
        restricted_checks.append({"filename": name, "row_count": len(raw.splitlines()), "sha256": digest(raw)})
    verification = {"schema_version": "F0_FINAL_ARTIFACT_VERIFICATION_V1", "status": "PASS",
                    "frozen_tracked_outputs": [{"filename": name, "sha256": digest(raw)} for name, raw in sorted(tracked.items())],
                    "restricted_outputs": restricted_checks, "restricted_output_permissions": "0600",
                    "restricted_output_entry_gate_sha256": digest((HERE / "F0_RESTRICTED_OUTPUT_ENTRY_GATE_V1.json").read_bytes()),
                    "all_serialized_results_identical_to_validated_content": True,
                    "test_report_sha256": digest(pretty(test_report)), "tests_passed": 50,
                    "score_transformations": 0, "mode_identity_accesses": 0, "network_calls": 0}
    durable_write_once(HERE / "F0_FINAL_ARTIFACT_VERIFICATION_V1.json", pretty(verification))
    # This is the last operation that inspects the access ledger. Subsequent
    # steps read score-free metadata and reports only, so its hash stays final.
    ledger_meta = seal_ledger()
    entry = guard.verify_entry()
    judge_meta = json.loads(tracked["c4_real_corrected_judge_results_metadata_v1.json"])
    human_meta = json.loads(tracked["c4_real_corrected_human_ratings_metadata_v1.json"])
    agreement_files = ("c4_real_blinded_human_human_agreement_v1.json", "C4_REAL_BLINDED_HUMAN_HUMAN_AGREEMENT_REPORT.md",
                       "c4_real_blinded_human_llm_agreement_v1.json", "C4_REAL_BLINDED_HUMAN_LLM_AGREEMENT_REPORT.md")
    completion = {
        "schema_version": "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT", "RQ3_REAL_F0_STATUS": FINAL_STATUS,
        "completed_at_utc": utc_now(), "working_directory": str(ROOT), "branch": entry["branch"],
        "starting_head": entry["starting_head"], "integrated_head": entry["integrated_head"],
        "integrated_source_commits": entry["integrated_source_commits"],
        "phase_a_and_b_authority_hashes": entry["phase_a_and_b_authority_hashes"], "authority_status": entry["authority_status"],
        "prior_phase_a_incident_disclosed": True, "applicability_v2_unchanged": True,
        "f0_entry_receipt_sha256": guard.ENTRY_SHA256, "controlled_access_ledger_sha256": ledger_meta["sha256"],
        "controlled_access_record_count": ledger_meta["row_count"], "controlled_access_metadata_sha256": digest(pretty(ledger_meta)),
        "pacing_resolution_sha256": entry["pacing_evidence_policy_sha256"],
        "result_integrity_status": "PASS", "pacing_evidence_status": "QUALIFIED_PACING_EVIDENCE_LIMITATION",
        "strict_wire_send_compliance_claimed": False, "judge_result_count": 149,
        "judge_source_counts": {"retained": 33, "B": 38, "C": 39, "A": 39},
        "judge_result_identities_and_hashes": judge_meta["identities"], "judge_result_files": judge_meta["files"],
        "judge_freeze_receipt_sha256": digest(tracked["C4_REAL_CORRECTED_JUDGE_RESULTS_FREEZE_RECEIPT.json"]),
        "condition_result_mapping_metadata": json.loads(tracked["c4_real_corrected_condition_result_mapping_metadata_v1.json"]),
        "condition_result_mapping_metadata_sha256": digest(tracked["c4_real_corrected_condition_result_mapping_metadata_v1.json"]),
        "condition_result_mapping_count": 558, "missing_conditions": 0, "duplicate_condition_ids": 0, "unequal_payload_result_sharing": 0,
        "human_base_and_amendment_source_hashes": entry["human_source_hashes"], "corrected_human_result_files": human_meta["files"],
        "human_freeze_receipt_sha256": digest(tracked["C4_REAL_CORRECTED_HUMAN_RATING_FREEZE_RECEIPT.json"]),
        "human_items_per_rater": 44, "human_numeric_pairs_per_rater": 276, "human_na_pairs_per_rater": 76,
        "human_judge_match_metadata_sha256": digest(tracked["c4_real_human_judge_match_metadata_v1.json"]),
        "agreement_output_hashes": {name: digest(tracked[name]) for name in agreement_files},
        "agreement_scope_policy_sha256": entry["agreement_scope_policy_sha256"],
        "usage_accounting_sha256": digest(tracked["F0_JUDGE_USAGE_ACCOUNTING_V1.json"]),
        "tests": {k: test_report[k] for k in ("tests_run", "passed", "failed", "errors", "skipped")},
        "test_report_sha256": digest(pretty(test_report)), "artifact_verification_sha256": digest(pretty(verification)),
        "controlled_source_access_closed": True,
        "prohibited_action_counts": {name: 0 for name in ("mode_level_analysis", "system_comparison", "mode_unblinding", "final_treatment_effect_analysis", "treatment_significance_tests", "provider_calls", "network_calls", "judge_execution", "response_generation", "human_rating_actions", "human_amendment_actions", "rag", "memory", "planning", "evidence_synthesis", "p3", "rq2", "streamlit_launch")},
        "commit_scope": "Four explicitly requested cherry-picks, followed by exactly one new F0 artifact commit; no branch operation.",
        "write_count": 1, "overwrite_permitted": False, "write_enforcement": "O_EXCL; flush; fsync file and parent directory",
        "next_stage_started": False,
    }
    completion_raw = pretty(completion)
    durable_write_once(guard.COMPLETION, completion_raw)
    hh = data["human_human"]["pooled"]
    hl = data["human_llm"]["pooled_human_observations_vs_llm_judge"]["pooled"]
    status = f"""# RQ3-REAL-C4-F0

RQ3_REAL_F0_STATUS = {FINAL_STATUS}

Working directory: `{ROOT}`  
Branch: `{entry['branch']}`  
Starting HEAD: `{entry['starting_head']}`  
Integrated HEAD before the one F0 result commit: `{entry['integrated_head']}`

All four requested Judge commits were cherry-picked in order; all 77 original
execution files and pre-existing tracked artifacts remain unchanged. The three
retained untracked J2D2 files, existing HMAC key, and prior restricted mappings
are preserved. The final F0 commit hash is recorded by the review ZIP build
receipt and the completion message to avoid a commit self-reference.

Phase-A and Phase-B: all nine authority hashes pass. Applicability V2 is unchanged
and the prior Phase-A incident remains disclosed.

F0 entry receipt SHA-256: `{guard.ENTRY_SHA256}`  
Access ledger SHA-256: `{ledger_meta['sha256']}` ({ledger_meta['row_count']} metadata-only records)  
Completion receipt SHA-256: `{digest(completion_raw)}`

Judge results: retained 33 + B 38 + C 39 + A 39 = 149 unique request/result
identities. A order 39 uses execution_output_v2 only. One retained result has no
historical terminal and is materialized from the exact raw attempt already
selected by Phase B under Parser V3; no terminal history was invented. The
condition projection contains 558 unique opaque IDs with no missing or duplicate
condition and no sharing across unequal Provider payloads.

Result integrity: PASS. Pacing evidence: QUALIFIED_PACING_EVIDENCE_LIMITATION.
Strict 15-second HTTP wire-send compliance is not claimed. Original execution
reports and statuses remain unchanged.

Human intake: all eight source hashes pass. Each rater has 44 items and 352
criterion pairs: 270 retained numeric, 69 retained NA, 7 corrected to NA, and 6
completed Actionability amendments; corrected totals are 276 numeric and 76 NA.
Both raters' later administrative AI disclosures are retained separately from
their self-attested independent substantive ratings. No disagreement was
adjudicated.

Human-Human pooled exact agreement: {hh['exact_agreement_numerator']}/{hh['n']}
({hh['exact_agreement']:.6%}); weighted kappa {hh['quadratic_weighted_kappa']};
Spearman {hh['spearman_correlation']}. Human-Human MAE/bias were not computed
because that pairing's additional metrics were not explicitly declared.

Pooled Human-LLM exact agreement: {hl['exact_agreement_numerator']}/{hl['n']}
({hl['exact_agreement']:.6%}); MAE {hl['mean_absolute_score_difference']}; weighted
kappa {hl['quadratic_weighted_kappa']}; Spearman {hl['spearman_correlation']}.
This pooling preserves two Human observations on 44 items, not 108 condition
mappings. Per-rater and per-criterion results are in the blinded reports.

Usage is counted separately for 149 selected returns and every historical
physical return. Three Provider completion/billing outcomes remain unknown;
two API rejections have no Judge result. Unknown usage is not imputed and usage
is not multiplied by 558. See F0_JUDGE_USAGE_ACCOUNTING_REPORT.md.

Targeted offline tests: 50 passed, 0 failed, 0 errors, 0 skipped. Six of these
tests verify the serialized frozen artifacts after their write-once creation.
Provider, network, Judge execution, Human rating/amendment, mode unblinding,
mode analysis, system comparison, treatment-effect analysis, and Streamlit
launch counts are all zero.

Controlled score access is sealed. The tests were executed before this seal;
rerunning their real-data intake now intentionally fails closed. Review-package
validation reads only allowlisted metadata, reports, and code. The ZIP excludes
all raw ratings/rationales, candidates, keys, and restricted mappings.

STOP. Final mode unblinding and treatment-effect analysis have not begun.
"""
    durable_write_once(HERE / "STATUS.md", status.encode())
    members = []
    for name in REVIEW_FILES:
        path = HERE / name
        require(path.is_file(), "REVIEW_MEMBER_MISSING: " + name)
        raw = path.read_bytes()
        members.append({"filename": name, "sha256": digest(raw), "bytes": len(raw)})
    allowlist = {"schema_version": "F0_REVIEW_PACKAGE_ALLOWLIST_V1", "files": members,
                 "additional_generated_members": ["F0_REVIEW_PACKAGE_ALLOWLIST_V1.json", "REVIEW_PACKAGE_BUILD_RECEIPT_V1.json"],
                 "excluded": ["raw Human ratings/rationales", "raw Judge scores/rationales", "candidate responses", "HMAC key", "restricted mappings", "credentials", "mode comparisons"],
                 "source_access_sealed": True}
    durable_write_once(HERE / "F0_REVIEW_PACKAGE_ALLOWLIST_V1.json", pretty(allowlist))
    print(json.dumps({"status": FINAL_STATUS, "completion_receipt_sha256": digest(completion_raw),
                      "access_ledger_sha256": ledger_meta["sha256"], "access_records": ledger_meta["row_count"],
                      "tests": completion["tests"], "review_allowlist_members": len(members) + 2}))


if __name__ == "__main__":
    main()
