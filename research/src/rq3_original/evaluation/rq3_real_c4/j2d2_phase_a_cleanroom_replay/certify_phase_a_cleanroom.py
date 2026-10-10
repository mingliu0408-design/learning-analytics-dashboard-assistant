#!/usr/bin/env python3
"""Write the supplemental certificate once, after all score-free gates pass."""

import datetime
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
HISTORICAL = HERE.parent / "j2d2_corrected_applicability_freeze"
SUPPLEMENT = "APPLICABILITY_V2_CLEANROOM_REPLAY_SUPPLEMENT_V1.json"
AUTHORITY = "APPLICABILITY_V2_PHASE_A_AUTHORITY_RESOLUTION_V1.json"
DISCLOSURE = "C4_REAL_PHASE_A_BOUNDARY_REMEDIATION_DISCLOSURE.md"
FINAL_AUTHORITY = "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT"
READY = "READY_FOR_J2D2_PHASE_B_AFTER_SCORE_ISOLATED_PHASE_A_REPLAY"


def read(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exclusive_write(path, data):
    with open(path, "xb") as stream:
        stream.write(data)


def certify():
    targets = [HISTORICAL / SUPPLEMENT, HISTORICAL / AUTHORITY, HISTORICAL / DISCLOSURE, HERE / "STATUS.md"]
    require(all(not path.exists() for path in targets), "Certification target already exists; no overwrite permitted")
    manifest_path = HERE / "PHASE_A_CLEANROOM_ALLOWED_INPUTS_MANIFEST.json"
    manifest = read(manifest_path)
    metadata = read(HERE / "PHASE_A_CLEANROOM_REPLAY_OUTPUT_METADATA_V1.json")
    comparison = read(HERE / "PHASE_A_HISTORICAL_COMPARISON_V1.json")
    tests = read(HERE / "PHASE_A_PRE_CERTIFICATION_TEST_RESULTS_V1.json")
    entry = read(HERE / "PHASE_A_ENTRY_GATE_V1.json")
    require(metadata["status"] == "CLEANROOM_REPLAY_COMPLETE", "Replay is incomplete")
    require(comparison["status"] == "PASS_SCIENTIFIC_CONTENT_EQUAL" and comparison["scientific_content_equality"]
            and comparison["checks_failed"] == 0, "Scientific comparison failed")
    require(tests["success"] and tests["passed"] == tests["tests_run"] == 32
            and tests["failed"] == tests["errors"] == tests["skipped"] == 0, "Pre-certification tests failed")
    require(metadata["scenario_count"] == 62 and metadata["condition_count"] == 558, "Cardinality mismatch")
    for name, expected in entry["original_records"].items():
        path = HISTORICAL / name
        stat = path.stat()
        require({"sha256": sha(path.read_bytes()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                 "ctime_ns": stat.st_ctime_ns} == expected, "Original incident evidence changed")
    inputs = Path(manifest["sealed_input_directory"])
    require({p.name for p in inputs.iterdir()} == set(manifest["allowed_input_directory_entries"]), "Input allowlist changed")
    require({p.name for p in inputs.parent.iterdir()} == {"inputs", "outputs"}, "Unexpected clean-room entry")
    for item in manifest["inputs"]:
        data = (inputs / item["cleanroom_filename"]).read_bytes()
        require(len(data) == item["byte_size"] and sha(data) == item["sha256"], "Clean-room source changed")
        require(Path(item["source_path"]).read_bytes() == data, "Authoritative source changed")
    code = (HERE / "phase_a_cleanroom_replay.py").read_bytes()
    require((inputs / "phase_a_cleanroom_replay.py").read_bytes() == code, "Copied replay code differs")
    require(sha(code) == metadata["code_sha256"], "Replay code hash differs from completed execution")
    for item in metadata["outputs"]:
        local = (HERE / "replay_outputs" / item["filename"]).read_bytes()
        private = (Path(manifest["generated_output_directory"]) / item["filename"]).read_bytes()
        require(local == private and sha(local) == item["sha256"], "Replay output changed")
    for item in comparison["historical_artifact_hashes"]:
        require(sha((HISTORICAL / item["filename"]).read_bytes()) == item["sha256"], "Historical Phase-A artifact changed")
    audit = read(HERE / "replay_outputs/cleanroom_access_audit.json")
    for key in ("unexpected_accesses", "score_bearing_inputs", "candidate_response_inputs", "human_rating_inputs",
                "network_calls", "provider_calls", "subprocess_calls", "environment_variable_reads", "repository_module_imports"):
        require(audit[key] == 0, "Clean-room access audit failed")
    qualification = read(HISTORICAL / "ORIGINAL_PHASE_A_RECEIPT_QUALIFICATION_V1.json")
    require(qualification["original_receipt_status"] == "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT"
            and not qualification["prior_session_zero_score_exposure_claimed"], "Original receipt qualification missing")
    sources = {item["source_role"]: item for item in manifest["inputs"]}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    prohibited = {key: 0 for key in (
        "phase_b_executions", "provider_calls", "network_calls", "judge_executions", "judge_score_reads",
        "judge_rationale_reads", "human_rating_reads", "human_rationale_reads", "candidate_response_reads",
        "response_quality_analyses", "mode_or_condition_outcome_comparisons", "agreement_calculations",
        "final_statistics", "rag_executions", "memory_executions", "planning_executions",
        "evidence_synthesis_executions", "p3_executions", "generation_executions", "streamlit_executions")}
    supplement = {
        "schema_version": "APPLICABILITY_V2_CLEANROOM_REPLAY_SUPPLEMENT_V1", "task": "RQ3-REAL-C4-J2D2-R0",
        "status": "CLEANROOM_PHASE_A_REPLAY_CERTIFIED", "timestamp_utc": now,
        "write_count": 1, "overwrite_permitted": False, "write_enforcement": "exclusive file creation (xb / O_EXCL)",
        "original_receipt_sha256": entry["original_records"]["APPLICABILITY_V2_PRE_OUTCOME_FREEZE_RECEIPT.json"]["sha256"],
        "incident_report_sha256": entry["original_records"]["PHASE_A_BOUNDARY_INCIDENT_REPORT.md"]["sha256"],
        "original_receipt_qualification_sha256": sha((HISTORICAL / "ORIGINAL_PHASE_A_RECEIPT_QUALIFICATION_V1.json").read_bytes()),
        "completed_researcher_packet_sha256": sources["completed_researcher_packet"]["sha256"],
        "completed_attestation_sha256": sources["completed_researcher_attestation"]["sha256"],
        "blank_packet_sha256": sources["frozen_blank_researcher_packet"]["sha256"],
        "opaque_mapping_sha256": sources["restricted_opaque_review_id_mapping"]["sha256"],
        "v1_condition_applicability_source_sha256": sources["v1_condition_identity_error_handling_and_diff_baseline"]["sha256"],
        "cleanroom_allowed_input_manifest_sha256": sha(manifest_path.read_bytes()),
        "replay_code_sha256": sha(code), "comparison_code_sha256": sha((HERE / "compare_phase_a_scientific_content.py").read_bytes()),
        "certification_code_sha256": sha(Path(__file__).read_bytes()),
        "cleanroom_output_hashes": metadata["outputs"],
        "historical_phase_a_artifact_hashes": comparison["historical_artifact_hashes"],
        "comparison_report_sha256": sha((HERE / "PHASE_A_HISTORICAL_COMPARISON_V1.json").read_bytes()),
        "pre_certification_test_report_sha256": sha((HERE / "PHASE_A_PRE_CERTIFICATION_TEST_RESULTS_V1.json").read_bytes()),
        "replay_attempt_record_sha256": sha((HERE / "PHASE_A_REPLAY_ATTEMPTS_V1.json").read_bytes()),
        "certifying_replay_attempt": 2,
        "earlier_attempt_in_this_task": "A standard-library BOM codec import was denied before packet parsing; no scientific output was generated. Its code and manifest remain preserved.",
        "scientific_content_equality": True, "scientific_projection_hashes": comparison["canonical_projections"],
        "scientific_comparison_checks_passed": comparison["checks_passed"], "scientific_comparison_checks_failed": 0,
        "scenario_count": 62, "condition_count": 558, "decision_distributions": metadata["distributions"],
        "v1_v2_change_counts": metadata["change_counts"],
        "score_bearing_inputs": 0, "candidate_response_inputs": 0, "human_rating_inputs": 0,
        "score_isolation_scope": "This new conversation's allowlisted clean-room replay and the comparison of Phase-A applicability artifacts; no outcome source was opened or parsed.",
        "prior_session_zero_score_exposure_claimed": False,
        "retained_negative_marker": "The exact-byte V1 input contains candidate_response_accessed=false as a boolean audit marker, not candidate-response content.",
        "v1_decision_flags_usage": "Mechanical diff only, after independent researcher decisions and V2 conditions were frozen.",
        "mode_usage": "Condition identity only; no mode-level outcomes or comparisons.",
        "replay_completed_at_utc": metadata["completed_at_utc"], "comparison_completed_at_utc": comparison["compared_at_utc"],
        "pre_certification_tests_completed_at_utc": tests["timestamp_utc"],
        "phase_b_started": False, "prohibited_action_counts": prohibited,
        "requires_new_conversation_and_direct_authorization_for_phase_b": True,
    }
    supplement_data = encoded(supplement)
    authority = {
        "schema_version": "APPLICABILITY_V2_PHASE_A_AUTHORITY_RESOLUTION_V1", "timestamp_utc": now,
        "final_phase_a_status": FINAL_AUTHORITY,
        "original_receipt_preserved_and_qualified": True,
        "original_receipt_status": "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT",
        "original_receipt_sha256": supplement["original_receipt_sha256"],
        "incident_disclosure_preserved": True, "incident_report_sha256": supplement["incident_report_sha256"],
        "supplement_path": str(HISTORICAL / SUPPLEMENT), "supplement_sha256": sha(supplement_data),
        "authoritative_evidence": "The clean-room supplement is the authoritative evidence for score-isolated artifact reproducibility.",
        "prior_session_zero_score_exposure_claimed": False,
        "prior_session_statement": "No claim is made that the earlier assistant session had zero score exposure. The original receipt is historically authentic, is qualified by the retained incident, and is not sufficient alone to certify the entire prior session.",
        "scientific_content_accepted_by_independent_allowlisted_reproduction": True,
        "acceptance_basis": "Final Applicability V2 scientific content is accepted because it was independently reproduced from allowlisted pre-response researcher decisions, opaque identity mapping, condition identity and preserved ERROR_HANDLING, and matched the historical Phase-A scientific artifacts.",
        "accepted_historical_scientific_artifacts": [item for item in comparison["historical_artifact_hashes"]
                                                    if item["filename"].startswith(("c4_real_researcher_scenario", "c4_real_condition_applicability", "c4_real_applicability_v1_v2"))],
        "scientific_comparison_report_sha256": supplement["comparison_report_sha256"],
        "phase_b_started_in_this_task": False,
        "phase_b_boundary": "Phase B remains unstarted. A separate direct user authorization and a new Codex conversation are required.",
        "remediation_erases_prior_incident": False,
    }
    disclosure = """# C4 Real Phase-A Boundary Remediation Disclosure

A prior tooling session accessed source code containing historical score literals before the original Phase-A receipt was written. This is a disclosed boundary incident. No historical Judge score values are reproduced here.

The independent researcher decisions predated the incident. No researcher applicability decision was made or changed from those values. The completed researcher packet and completion attestation are the authoritative researcher sources: their specified hashes were verified, the historical intake copies were byte-identical, all 62 rows contained YES/NO decisions and nonempty distinct notes, and no source field outside the five permitted researcher fields had changed. The replay validates and freezes these supplied decisions; it does not make researcher judgments. The independence statement is the researcher's completed attestation, not an inference of identity beyond the supplied document.

The original receipt and incident report were retained byte-for-byte, with their modification and change timestamps unchanged. ORIGINAL_PHASE_A_RECEIPT_QUALIFICATION_V1.json preserves the original receipt as historically authentic while recording that it cannot, by itself, certify zero score exposure across the entire prior assistant session. The incident disclosure has not been removed or softened.

The authoritative Applicability V2 scientific artifacts were subsequently reproduced in a physically isolated clean-room replay outside the Git worktree. Its sealed input directory contained five exact-byte pre-response source copies and standalone Python standard-library code. The only decision inputs were the completed researcher decisions, the blank packet for source-field validation, the completion attestation, and the opaque review-ID mapping for identity. V1 condition records supplied condition identity and preserved condition-specific ERROR_HANDLING. Their old Personalisation, Actionability, Motivation and Multi-page applicability flags were used only for the mechanical diff after the new researcher decisions were frozen. The V1 mode field supplied condition identity only. The false candidate_response_accessed marker in that exact-byte source is an audit boolean, not response content. The HMAC key was checked for presence and 32-byte size without reading or copying its contents.

The runtime boundary admitted only the five source files and replay code for reading and a fixed set of generated output files for exclusive creation within the isolated root. It denied additional imports, out-of-bound data access, subprocesses and network operations. An initial attempt stopped before packet parsing when Python requested a lazy standard-library BOM codec import. That failure and its code were preserved. BOM handling was changed to use the already loaded UTF-8 codec, and the certifying replay ran in a separate fresh directory. No researcher decision was altered by this implementation correction.

The successful replay produced 62 scenario decisions and 558 condition records. Personalisation was YES/NO = 37/25; Actionability = 28/34; Motivation and Engagement = 40/22. Material-page counts were zero/one/two = 1/55/6, and Multi-page Cohesiveness was applicable for 6 scenarios. The V1/V2 diff identified 39 changed scenarios, 351 changed condition maps and 207 unchanged maps; ERROR_HANDLING was preserved in all 558 conditions. These are applicability and provenance counts, not response-quality statistics.

The replay outputs matched the historical Phase-A scientific artifacts with zero decision, condition-map, material-page or ERROR_HANDLING mismatch. Researcher source copies were byte-identical. For separately implemented table schemas, comparisons normalized row order, JSON/CSV representation, material-page set order and changed-criterion order. Every scientific criterion, page membership, applicability hash/count and diff annotation was checked. Excluded administrative fields are enumerated in PHASE_A_HISTORICAL_COMPARISON_V1.json; historical session-access declarations were preserved but were not treated as clean-session evidence. All 98 comparison checks and all 32 pre-certification tests passed before the supplement was written.

APPLICABILITY_V2_CLEANROOM_REPLAY_SUPPLEMENT_V1.json was then exclusively created once. It is the authoritative evidence for score-isolated artifact reproducibility; the accompanying authority resolution accepts the independently reproduced Applicability V2 scientific content while retaining the prior incident qualification.

Phase B had not begun before the supplemental certification and remains unstarted in this task. It can begin only after certification, with separate direct user authorization in a new Codex conversation. This remediation task performed no Provider call, Judge execution, Judge-score or Human-rating parsing, candidate-response reading, response-quality analysis, mode or condition outcome comparison, agreement calculation, final statistics, RAG, Memory, Planning, Evidence-Synthesis, P3, generation or Streamlit execution.

The remediation does not erase the original incident, and it makes no claim that the prior assistant session had zero score exposure.
"""
    status = f"""# RQ3-REAL-C4-J2D2-R0 Phase-A status

RQ3_REAL_J2D2_R0_STATUS = {READY}

Final Phase-A authority: {FINAL_AUTHORITY}

The original receipt is preserved and qualified by the retained boundary-incident report. The clean-room supplement certifies reproducible Applicability V2 scientific content from the five allowlisted inputs. It does not certify zero score exposure in the prior assistant session.

Scenario decisions: 62. Condition records: 558. Scientific comparison: 98 passed, 0 failed. Pre-certification tests: 32 passed, 0 failed, 0 errors, 0 skipped. Subsequent certificate and package checks are recorded by the explicit new score-free test suites.

Phase B remains unstarted. A separate direct user authorization and a new Codex conversation are required for Phase B. No Judge results or completed Human ratings were opened. All Provider, Judge, Human-rating, response-quality, agreement, outcome-comparison, final-statistics, component execution and Streamlit actions were zero.

The first replay attempt stopped at the import boundary before packet parsing and produced no scientific output. Its evidence is preserved under replay_attempts/. The successful certifying attempt used a separate fresh physical clean-room.

Starting HEAD: {entry['starting_head']}
Working directory: {entry['working_directory']}
Branch: {entry['branch']}

The authorized delivery contains one commit and a strictly allowlisted review ZIP. STOP: do not enter Phase B.
"""
    payloads = [supplement_data, encoded(authority), disclosure.encode(), status.encode()]
    for path, payload in zip(targets, payloads):
        exclusive_write(path, payload)
    print(json.dumps({"status": "CLEANROOM_PHASE_A_REPLAY_CERTIFIED", "supplement_path": str(targets[0]),
                      "supplement_sha256": sha(payloads[0]), "authority_resolution_path": str(targets[1]),
                      "authority_resolution_sha256": sha(payloads[1]), "phase_b_started": False,
                      "write_count": 1}, sort_keys=True))


if __name__ == "__main__":
    certify()
