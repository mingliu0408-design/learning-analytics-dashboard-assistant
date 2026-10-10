"""Freeze source acceptance and chronology before any score/rationale parsing.

Only source metadata and byte hashes are read by this program. It does not
parse execution journals, ratings, candidates, or restricted mapping content.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from f0_common import (HERE, ROOT, BASE, PHASE_B, RESTRICTED, DOWNLOADS,
                       canonical, pretty, digest, durable_write_once, require, utc_now)

ENTRY_NAME = "F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1.json"
POLICY_NAME = "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json"
PACING_NAME = "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1.json"
PROTOCOL = ROOT / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol"


def main():
    require(not (HERE / ENTRY_NAME).exists(), "F0_ENTRY_ALREADY_EXISTS")
    start = json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())
    commits = json.loads((HERE / "F0_INTEGRATED_JUDGE_COMMIT_MAPPING_V1.json").read_bytes())
    originals = json.loads((HERE / "F0_ORIGINAL_JUDGE_COMMIT_SOURCE_MANIFEST_V1.json").read_bytes())
    require(Path.cwd() == ROOT, "WORKING_DIRECTORY_CHANGED")
    require(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() == start["state"]["branch"], "BRANCH_CHANGED")
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == commits[-1]["cherry_picked_commit"], "INTEGRATED_HEAD_CHANGED")
    sequence = subprocess.check_output(["git", "rev-list", "--reverse", start["state"]["head"] + "..HEAD"], text=True).splitlines()
    require(sequence == [r["cherry_picked_commit"] for r in commits], "INTEGRATION_ORDER_MISMATCH")
    for path, expected in start["authority_sha256"].items():
        require(digest((ROOT / path).read_bytes()) == expected, "AUTHORITY_HASH_MISMATCH")
    for name, expected in start["applicability_hashes"].items():
        require(digest((BASE / "j2d2_corrected_applicability_freeze" / name).read_bytes()) == expected, "APPLICABILITY_CHANGED")
    for source in originals:
        for file in source["files"]:
            require(digest((ROOT / file["path"]).read_bytes()) == file["sha256"], "CHERRY_PICK_SOURCE_BYTES_CHANGED")
    for item in start["retained_untracked_files"]:
        require(digest((ROOT / item["path"]).read_bytes()) == item["sha256"], "RETAINED_UNTRACKED_FILE_CHANGED")
    for name, expected in start["restricted_preservation_hashes"].items():
        require(digest((RESTRICTED / name).read_bytes()) == expected, "RESTRICTED_SOURCE_CHANGED")
    require(subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT).returncode == 0, "TRACKED_WORKTREE_CHANGED")

    catalog = {}

    def add(path, role, expected=None):
        path = Path(path).resolve(strict=True)
        require(path.is_file() and not path.is_symlink(), "SOURCE_NOT_REGULAR")
        raw = path.read_bytes()  # Hash-only; never decode a controlled source.
        value = digest(raw)
        require(expected is None or value == expected, "SOURCE_HASH_MISMATCH: " + path.name)
        record = {"path": str(path), "source_role": role, "sha256": value, "bytes": len(raw)}
        if str(path) in catalog:
            require(catalog[str(path)]["sha256"] == value, "CATALOG_CONFLICT")
        catalog[str(path)] = record

    for name, expected in start["human_source_hashes"].items():
        add(DOWNLOADS / name, "human_completed_rating" if name.endswith(".csv") else "human_completed_attestation", expected)
    for row in start["restricted_mapping_metadata"]["files"]:
        add(RESTRICTED / row["filename"], "restricted_blinded_payload" if "unique_payloads" in row["filename"] else
            "historical_human_semantic_source" if "semantic_records" in row["filename"] else "restricted_identity_projection", row["sha256"])
    meta_names = ("c4_real_corrected_judge_request_registry_v1.jsonl", "c4_real_judge_result_eligibility_after_applicability_v2.json",
                  "c4_real_human_applicability_impact_v1.json", "c4_real_human_amendment_packet_manifest_v1.json",
                  "c4_real_corrected_judge_configurations_r4.json", "c4_real_corrected_judge_package_manifest_r4_v1.json")
    for name in meta_names:
        add(PHASE_B / name, "frozen_score_free_registry")
    for name in ("rq3_human_agreement.py", "rq3_judge_request_builder.py", "__init__.py", "rq3_statistical_analysis_contract_v1.json", "RQ3_EVALUATION_METHOD.md"):
        add(PROTOCOL / name, "frozen_protocol")
    add(PHASE_B / "package_support/judge_result_parser_v3.py", "frozen_parser_v3", "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb")
    human_manifest = json.loads((BASE / "r3d1_response_integration_r2/c4_real_human_packet_manifest_r2_v1.json").read_bytes())
    for rater in "AB":
        add(BASE / f"r3d1_response_integration_r2/human_rating_packet_{rater}_R2.csv", "human_blank_packet",
            human_manifest["packages"][rater]["member_sha256"][f"human_rating_packet_{rater}.csv"])
    amendment_meta = json.loads((PHASE_B / "c4_real_human_amendment_packet_manifest_v1.json").read_bytes())
    for meta in amendment_meta["packages"].values():
        add(Path(meta["path"]), "human_blank_amendment_package", meta["sha256"])
    history_dirs = ("j2a_judge_shard_a", "j2b_judge_shard_b", "j2c_judge_shard_c", "j3b_judge_continuation_b", "j3c_judge_continuation_c",
                    "j4b_corrected_judge_shard_b", "j4c_corrected_judge_shard_c", "j4a_corrected_judge_shard_a")
    for name in history_dirs:
        for path in sorted((BASE / name).glob("execution_output_v*/JUDGE_*.json*")):
            role = "judge_attempt_journal" if "ATTEMPT" in path.name else "judge_terminal_source" if "TERMINAL" in path.name else "judge_execution_metadata"
            add(path, role)
    for source in originals:
        for file in source["files"]:
            path = ROOT / file["path"]
            if path.name.startswith("parsed_judge_"):
                add(path, "judge_parsed_result_source", file["sha256"])

    eligibility_path = PHASE_B / "c4_real_judge_result_eligibility_after_applicability_v2.json"
    eligibility = json.loads(eligibility_path.read_bytes())
    retained = [r for r in eligibility["existing_result_dispositions"] if r["corrected_primary_disposition"] == "RETAIN_UNCHANGED"]
    excluded = [r["logical_judge_request_id"] for r in eligibility["existing_result_dispositions"] if r["corrected_primary_disposition"] != "RETAIN_UNCHANGED"]
    require(len(retained) == 33 and len(excluded) == 56, "FROZEN_RETAINED_DISPOSITION_COUNTS_MISMATCH")
    require(all(not r["score_values_or_rationales_in_record"] for r in retained), "ELIGIBILITY_REGISTRY_NOT_SCORE_FREE")
    require(all(r["source_path"] in catalog for r in retained), "RETAINED_SOURCE_NOT_CATALOGUED")
    authority = {"status": start["authority_status"], "hashes": start["authority_sha256"],
                 "incident_disclosure_preserved": True, "prior_incident_erased": False,
                 "applicability_v2_hashes": start["applicability_hashes"]}
    durable_write_once(HERE / "F0_PHASE_A_B_AUTHORITY_REFERENCES_V1.json", pretty(authority))
    source_catalog = {"schema_version": "F0_SOURCE_CATALOG_V1", "content_access_before_entry": 0,
                      "pre_entry_operations": "Source existence, byte hashing, and score-free metadata only.", "sources": list(catalog.values())}
    durable_write_once(HERE / "F0_AUTHORIZED_SOURCE_CATALOG_V1.json", pretty(source_catalog))

    protocol = json.loads((PROTOCOL / "rq3_statistical_analysis_contract_v1.json").read_bytes())
    agreement_policy = {
        "schema_version": "F0_PRE_SCORE_AGREEMENT_SCOPE_V1", "frozen_at_utc": utc_now(),
        "authoritative_contract_sha256": digest((PROTOCOL / "rq3_statistical_analysis_contract_v1.json").read_bytes()),
        "implementation_sha256": digest((PROTOCOL / "rq3_human_agreement.py").read_bytes()),
        "contract_agreement_section": protocol["agreement"], "unique_item_count": 44,
        "condition_mapping_count_not_used_as_observations": 108,
        "human_human_metrics": ["quadratic_weighted_kappa", "spearman_correlation", "exact_agreement", "within_one_point_agreement"],
        "human_llm_additional_metrics": ["mean_absolute_score_difference", "criterion_level_bias_source_b_minus_source_a"],
        "human_llm_pairings": ["human_a_vs_llm_judge", "human_b_vs_llm_judge", "pooled_human_observations_vs_llm_judge"],
        "human_human_mae_and_bias": "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED",
        "pooled_bias": "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED",
        "scope_resolution": "The narrative and contract name MAE only for Human-LLM and bias only at criterion level. The generic helper also returns extra fields; those extra metrics will not be evaluated for unlisted pairings/scopes.",
        "disagreement_summaries": "Complements of the frozen exact and within-one-point numerators only; no new reliability statistic or histogram.",
        "na_rule": "Exclude jointly NA pairs; mismatched applicability fails closed.",
        "undefined_rule": protocol["agreement"]["undefined_metric_rule"],
        "human_llm_matching_rule": "Require equality of every corrected Human-visible field, including applicability, with the frozen corrected Judge payload. No score-based selection.",
        "new_metric_selection_after_access_permitted": False,
    }
    durable_write_once(HERE / "F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json", pretty(agreement_policy))

    pacing = {
        "schema_version": "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1", "frozen_at_utc": utc_now(),
        "scientific_validity_requirements": ["exact request/result identity", "exact Provider-payload identity", "correct returned model", "Parser-V3 validity", "Applicability-V2 consistency", "complete canonical terminal coverage", "no unresolved error attached to a selected result"],
        "configured_interval_seconds": 15, "pacing_role": "OPERATIONAL_RATE_LIMIT_SAFEGUARD",
        "pacing_is_experimental_treatment_or_response_quality_variable": False,
        "recorded_start_differences_measure_monotonic_reference": False,
        "recorded_start_differences_measure_http_wire_send_times": False,
        "result_integrity_status": "PASS", "pacing_evidence_status": "QUALIFIED_PACING_EVIDENCE_LIMITATION",
        "eligibility_scope": "All 38 B, 39 C, and 39 A canonical results, conditional on the frozen integrity checks; A order 39 is supplied only by execution_output_v2.",
        "rate_limit_error_count_required": 0,
        "strict_15_second_wire_send_compliance_claimed": False,
        "rerun_or_exclusion_solely_for_pacing_evidence_permitted": False,
        "original_reports_and_branch_status_artifacts_preserved": True,
        "historical_unknown_outcome_policy": "The interrupted A order-39 historical attempt is retained as unknown completion/billing history, never a canonical result; its separately authorized v2 result resolves coverage, not historical billing uncertainty.",
        "policy_change_after_score_access_permitted": False,
        "write_count": 1, "overwrite_permitted": False,
    }
    durable_write_once(HERE / PACING_NAME, pretty(pacing))
    policy = {
        "schema_version": "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1", "frozen_at_utc": utc_now(),
        "authority_references_sha256": digest(pretty(authority)),
        "phase_b_eligibility_registry_sha256": digest(eligibility_path.read_bytes()),
        "selection_rule": "Select the exact 33 RETAIN_UNCHANGED sources already frozen by Phase B, plus the specified B/C/A terminal histories. No independent retained-result reselection or score-based selection.",
        "retained_existing_sources": retained, "excluded_old_request_ids": excluded,
        "corrected_execution_sources": [{k: v for k, v in s.items() if k != "files"} for s in originals],
        "source_counts": {"retained": 33, "B": 38, "C": 39, "A_historical": 38, "A_order39_v2": 1, "total": 149},
        "model": "gpt-4.1-2025-04-14", "parser": "JUDGE_PARSER_V3",
        "pacing_policy_sha256": digest(pretty(pacing)),
        "excluded_sources": ["56 changed-applicability old results", "historical C order-40 rejected outputs", "billing or timeout attempts", "interrupted historical A order-39 attempt", "noncanonical retries", "Phase-B-ineligible results"],
        "retained_valid_v2_reparse_rule": "A frozen retained raw attempt may have been rejected by the obsolete rationale ceiling. Reparse only that exact Phase-B-selected raw output using unchanged Parser V3; do not choose a different attempt.",
        "score_transformation_permitted": False, "mode_identity_access_permitted": False,
        "write_count": 1, "overwrite_permitted": False,
    }
    durable_write_once(HERE / POLICY_NAME, pretty(policy))
    disclosure = """# Corrected Judge pacing evidence disclosure

The configured 15-second interval was an operational rate-limit safeguard. It
was not an experimental treatment or a response-quality variable. Recorded
request_started_at_utc differences do not measure the monotonic pacing reference
or actual HTTP wire-send timestamps. Strict 15-second wire-send compliance is
not claimed.

The authorized resolution retains B, C and completed A results when all frozen
identity, payload, model, Parser-V3, applicability and canonical-coverage checks
pass and no selected result has an unresolved Provider error. The integrity
status is PASS with QUALIFIED_PACING_EVIDENCE_LIMITATION. No result is rerun or
excluded solely to create different timing evidence. Original execution reports,
statuses, attempts and terminal journals remain unchanged.

The interrupted historical A order-39 attempt remains an unknown Provider
completion and billing outcome. Only execution_output_v2 supplies that canonical
result. Completing coverage does not resolve the historical billing uncertainty.

This policy was frozen before F0 score or rationale access. The Phase-A boundary
incident remains disclosed and is not erased by F0 or the clean-room supplement.
"""
    durable_write_once(HERE / "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_DISCLOSURE.md", disclosure.encode())
    entry = {
        "schema_version": "F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1", "task": "RQ3-REAL-C4-F0",
        "frozen_at_utc": utc_now(), "working_directory": str(ROOT), "branch": start["state"]["branch"],
        "starting_head": start["state"]["head"], "integrated_head": commits[-1]["cherry_picked_commit"],
        "integrated_source_commits": commits, "phase_a_and_b_authority_hashes": start["authority_sha256"],
        "authority_status": start["authority_status"], "prior_incident_disclosed": True,
        "judge_source_hashes": [{k: s[k] for k in ("source_role", "original_commit", "terminal_journal_sha256", "parsed_result_set_sha256", "valid_results")} for s in originals],
        "human_source_hashes": start["human_source_hashes"],
        "source_catalog_sha256": digest(pretty(source_catalog)),
        "source_selection_policy_sha256": digest(pretty(policy)),
        "pacing_evidence_policy_sha256": digest(pretty(pacing)),
        "agreement_scope_policy_sha256": digest(pretty(agreement_policy)),
        "starting_gates_sha256": digest((HERE / "F0_STARTING_GATES_V1.json").read_bytes()),
        "score_bearing_sources_read_before_receipt": 0, "human_rating_sources_read_before_receipt": 0,
        "mode_mapping_opened_before_receipt": 0,
        "pre_receipt_read_definition": "No decoding, parsing, or inspection of score/rationale or mode values. Required source-byte hashing and score-free metadata verification are separately disclosed and are not score-content access.",
        "prior_f0_preflight_stops": "Two earlier turns in this F0 conversation stopped on missing attestation files with no modifications or score-content access. This entry follows the renewed complete authorization and all eight successful source hash checks.",
        "controlled_access_write_ahead_required": True,
        "provider_calls": 0, "network_calls": 0, "human_rating_actions": 0, "mode_unblinding": 0,
        "write_count": 1, "overwrite_permitted": False,
        "write_enforcement": "O_EXCL; flush; fsync file and parent directory",
    }
    raw = pretty(entry)
    durable_write_once(HERE / ENTRY_NAME, raw)
    binding = '"""Write-once F0 entry commitment; created immediately after fsync."""\nENTRY_SHA256 = ' + repr(digest(raw)) + "\n"
    durable_write_once(HERE / "f0_entry_binding.py", binding.encode())
    print(json.dumps({"status": "F0_ENTRY_AND_POLICIES_DURABLY_FROZEN", "entry_receipt_sha256": digest(raw), "source_count": len(catalog), "score_content_accesses": 0}))


if __name__ == "__main__":
    main()
