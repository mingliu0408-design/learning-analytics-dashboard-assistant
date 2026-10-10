"""One-shot, score-blind F1 authority verification and pre-unblinding seal.

Restricted source handling here is limited to byte hashing, file stat and line
counts. No opaque condition, mode or scenario mapping is decoded by this script.
"""
from __future__ import annotations

import csv
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from f1_common import *


def main():
    assert str(Path.cwd().resolve()) == EXPECTED_ROOT == str(ROOT)
    assert git("branch", "--show-current") == EXPECTED_BRANCH
    assert git("rev-parse", "HEAD") == STARTING_HEAD
    status = git("status", "--short", "--untracked-files=all").splitlines()
    f1_prefix = str(HERE.relative_to(ROOT)) + "/"
    prior_status = [x for x in status if not x.startswith("?? " + f1_prefix)]
    assert sorted(prior_status) == sorted("?? " + p for p in RETAINED)
    assert not git("diff", "--name-only") and not git("diff", "--cached", "--name-only")
    assert RI.is_dir()
    assert (RI / "c4_real_i1_blinding_hmac_key.bin").stat().st_size == 32
    assert git("ls-files", "--", str(RI)).splitlines() == [str((RI / ".gitignore").relative_to(ROOT))]
    for p in RI.iterdir():
        if p.name != ".gitignore":
            assert subprocess.run(["git", "check-ignore", "-q", "--", str(p)], cwd=ROOT).returncode == 0
    assert not list(RI.glob("c4_real_f1_*"))
    assert not REVIEW_ZIP.exists()
    for p in [RECEIPT, LEDGER, FINAL_RECEIPT, HERE / "f1_entry_binding.py"]:
        assert not p.exists()
    verified = []
    for name, digest in EXPECTED_HASHES.items():
        assert (ROOT / name).is_file()
        assert sha(ROOT / name) == digest, "AUTHORIZED_SOURCE_HASH_MISMATCH"
        verified.append({"path": name, "sha256": digest, "verification": "PASS"})
    f0 = read_json(F0 / "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json")
    integrity = read_json(F0 / "F0_BLINDED_INTEGRITY_AUDIT_V1.json")
    prior_gates = read_json(F0 / "F0_STARTING_GATES_V1.json")
    for x in prior_gates["retained_untracked_files"]:
        assert sha(ROOT / x["path"]) == x["sha256"]
    assert f0["RQ3_REAL_F0_STATUS"] == "READY_FOR_FINAL_MODE_UNBLINDING_AND_PREDECLARED_STATISTICAL_ANALYSIS"
    assert f0["judge_result_count"] == 149
    assert f0["condition_result_mapping_count"] == 558
    assert f0["human_items_per_rater"] == 44
    assert f0["prohibited_action_counts"]["mode_unblinding"] == 0
    assert f0["prohibited_action_counts"]["final_treatment_effect_analysis"] == 0
    assert f0["prohibited_action_counts"]["system_comparison"] == 0
    for k in ["excluded_results_selected", "duplicate_judge_identity", "duplicate_condition_ids",
              "missing_conditions", "missing_judge_results", "unequal_payload_result_sharing"]:
        assert integrity[k] == 0
    # Blinded identity verification only: no scores are output or aggregated.
    judge = [json.loads(x) for x in (F0 / "c4_real_corrected_judge_results_frozen_v1.jsonl").read_text().splitlines()]
    assert len(judge) == 149
    assert len({x["logical_judge_request_id"] for x in judge}) == 149
    assert len({x["judge_result_blind_id"] for x in judge}) == 149
    accepted = read_json(F0 / "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json")
    assert not ({x["logical_judge_request_id"] for x in judge} & set(accepted["excluded_old_request_ids"]))
    assert {(x["logical_judge_request_id"], x["judge_result_blind_id"], x["provider_payload_sha256"], x["semantic_result_sha256"])
            for x in judge} == {(x["logical_judge_request_id"], x["judge_result_blind_id"], x["provider_payload_sha256"], x["semantic_result_sha256"])
                                  for x in f0["judge_result_identities_and_hashes"]}
    for label in "AB":
        with (F0 / f"c4_real_corrected_human_ratings_{label}_frozen_v1.csv").open(newline="") as h:
            rows = list(csv.DictReader(h))
        assert len(rows) == len({x["corrected_rating_item_id"] for x in rows}) == 44
    # Byte-line count is metadata verification, without interpreting a mapping.
    assert len((RI / "c4_real_corrected_condition_result_projection_f0_v1.jsonl").read_bytes().splitlines()) == 558
    registry = read_json(REGISTRY)
    generic = read_json(GENERIC)
    observed = [(x["comparison_id"], x["left"], x["right"], family)
                for key, family in [("primary", "PRIMARY_ADD_ONE"), ("targeted_remove_one", "TARGETED_REMOVE_ONE")]
                for x in registry["frozen_comparisons"][key]]
    assert observed == CONTRASTS
    assert len(registry["modes"]) == 9
    assert registry["evaluation_contract"]["primary_response_quality_criteria"] == CRITERIA
    assert registry["evaluation_contract"]["primary_aggregate"]["name"] == PRIMARY_OUTCOME
    assert generic["primary_outcome"]["name"] == PRIMARY_OUTCOME
    assert generic["clustering_and_resampling_unit"] == "scenario_family_id"
    assert generic["interval_estimation"]["replicates"] == BOOTSTRAP_REPLICATES
    assert generic["interval_estimation"]["random_seed"] == SEED
    assert generic["hypothesis_tests"]["primary"]["monte_carlo_seed"] == SEED
    assert generic["paired_effect_sizes"]["wins_ties_losses"]["tie_tolerance"] == TIE_TOLERANCE
    paths = sorted(p for p in C4.rglob("*") if p.is_file() and not p.is_relative_to(HERE))
    paths.append(GENERIC)
    snapshot = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    starting = {
        "schema_version": "F1_STARTING_GATES_V1", "timestamp_utc": now(), "status": "PASS",
        "working_directory": str(ROOT), "branch": EXPECTED_BRANCH, "starting_head": STARTING_HEAD,
        "initial_status_before_f1_preparation": sorted(prior_status), "tracked_modifications": 0,
        "retained_untracked_files": prior_gates["retained_untracked_files"],
        "restricted_directory_exists": True, "restricted_data_files_ignored_and_untracked": True,
        "only_tracked_restricted_directory_file": ".gitignore", "hmac_key_bytes": 32,
        "hmac_commitment": EXPECTED_HASHES[str((RI / "c4_real_i1_blinding_hmac_key.bin").relative_to(ROOT))],
        "mode_mapping_content_accesses": 0, "system_comparisons_computed": 0,
        "pre_entry_restricted_operations": "Existence, stat, byte hashing and byte-line count only; no identity decoding.",
        "ignore_probe_note": "A directory-level check-ignore probe did not match because protection is provided by the existing internal .gitignore. File-level checks confirm every data file ignored; no ignore rule or source was changed.",
        "new_conversation": True, "prior_experimental_work_in_this_conversation": False,
        "output_paths_absent_at_original_entry": True,
    }
    hierarchy = {
        "schema_version": "F1_ANALYSIS_CONTRACT_HIERARCHY_V1", "frozen_at_utc": now(),
        "write_count": 1, "overwrite_permitted": False,
        "authority_order": [
            {"rank": 1, "path": str(REGISTRY.relative_to(ROOT)), "sha256": sha(REGISTRY),
             "controls": ["nine real-C4 mode identities", "exact eight contrasts and left-minus-right directions",
                          "primary and targeted-secondary families", "separate five/three Holm families",
                          "paired-scenario design", "predeclared mechanism and efficiency outcomes"]},
            {"rank": 2, "path": str(GENERIC.relative_to(ROOT)), "sha256": sha(GENERIC),
             "controls_only_compatible_procedures": ["complete pairs", "family-cluster bootstrap", "paired family sign-flip",
                   "Wilcoxon robustness", "paired Cohen dz", "matched rank-biserial", "wins/ties/losses", "mathematical guards"]}],
        "contrast_or_multiplicity_conflict_resolution": "REAL_C4_MODE_REGISTRY_CONTROLS",
        "controlled_rq3_contrast_formulas_executable": False,
        "forbidden_final_contrast_names": ["RM00", "RM10", "RM01", "RM11", "BASE", "ALWAYS", "ORACLE", "PREDICTED"],
        "mode_mapping_content_accesses_before_hierarchy": 0,
    }
    plan = {
        "schema_version": "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1", "frozen_at_utc": now(),
        "write_count": 1, "overwrite_permitted": False,
        "primary_outcome": PRIMARY_OUTCOME, "primary_value_source": "EXACT_F0_LOCALLY_COMPUTED_OVERALL_APPLICABLE_MEAN",
        "primary_criteria": CRITERIA, "secondary_audits_excluded_from_primary": True,
        "mode_identities": [x["mode_id"] for x in registry["modes"]],
        "contrasts": [{"contrast_id": a, "left": b, "right": c, "holm_family": d} for a,b,c,d in CONTRASTS],
        "difference_direction": "LEFT_MINUS_RIGHT", "population": "ALL_62_FROZEN_SCENARIOS_SUBJECT_ONLY_TO_COMPLETE_PAIR_RULE",
        "estimand": "System-level effect of component availability behind the frozen P3 Router on LLM-Judge-rated response quality.",
        "pair_key": "Frozen immutable scenario identity within scenario_family_id; verify its exact source field during identity join.",
        "cluster_key": "scenario_family_id", "one_scenario_one_family": "VERIFY_FROM_FROZEN_IDENTITY_SOURCES; DO_NOT_RECLUSTER",
        "multiple_cases_in_family": "Arithmetic mean of paired differences within each frozen family before sign-flip, Wilcoxon and paired effects.",
        "missing_policy": "Exclude the entire incomplete pair for that contrast and report case/family reasons; no imputation.",
        "shared_request_policy": "Project each frozen score to all of its condition IDs. Retain identical-response and route-inactive zero pairs.",
        "descriptive_denominator": "62 condition records per mode, not 149 unique Judge requests or Provider calls",
        "bootstrap": {"method": "FAMILY_CLUSTER_NONPARAMETRIC_PERCENTILE", "replicates": BOOTSTRAP_REPLICATES,
             "seed": SEED, "confidence_level": 0.95, "percentiles": [2.5,97.5], "quantile_method": "linear",
             "rng": "numpy.random.Generator(PCG64)", "rng_reset": "Per contrast and per frozen sensitivity cohort",
             "algorithm": generic["interval_estimation"]["algorithm"], "insufficient_family_guard": "NOT_ESTIMABLE_INSUFFICIENT_FAMILIES"},
        "sign_flip": {"two_sided": True, "statistic": "absolute mean family-level paired difference", "zeros_retained": True,
             "exact_when_family_count_at_most": 20, "exact_assignment_count": "2**F", "exact_p_formula": "extreme_count / (2**F)",
             "otherwise_assignments": MONTE_CARLO_ASSIGNMENTS, "seed": SEED, "rng": "numpy.random.Generator(PCG64)",
             "rng_reset": "Per contrast", "monte_carlo_p_formula": "(1 + extreme_count) / (1 + 100000)",
             "extremeness_tolerance": TIE_TOLERANCE},
        "wilcoxon": {"two_sided": True, "zero_method": "DROP_ZEROS", "tie_method": "AVERAGE_RANKS",
             "method": "EXACT_CONDITIONAL_AVERAGE_RANK_DP", "algorithm": "Double average ranks to integers; count the exact subset-sum sign distribution and both tails at least as far from the rank-sum centre.",
             "continuity_correction": False, "all_zero_status": "NOT_ESTIMABLE_ALL_ZERO_WITH_EXACT_AGREEMENT_REPORTED"},
        "paired_cohens_dz": generic["paired_effect_sizes"]["paired_cohens_dz"],
        "rank_biserial": generic["paired_effect_sizes"]["matched_rank_biserial_correlation"],
        "tie_tolerance": TIE_TOLERANCE, "numerical_rank_tie_tolerance": TIE_TOLERANCE,
        "source_score_rounding": False, "effect_size_magnitude_labels_authorized": False,
        "holm_families": {fam: [a for a,b,c,d in CONTRASTS if d==fam] for fam in ["PRIMARY_ADD_ONE","TARGETED_REMOVE_ONE"]},
        "alpha": 0.05,
        "secondary_policy": {"label": "SECONDARY_EXPLORATORY", "outcomes": SECONDARY,
             "both_sides_applicable_required": True, "criterion_pair_exclusion_reasons_reported": True,
             "p_values_computed": False, "holm_membership": False,
             "unsupported_claim_count_wins": "Lower count is better; numerical difference remains LEFT_MINUS_RIGHT."},
        "frozen_cohort_policy": {"cohorts": ["C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1", "NINE_SCENARIO_PERSISTENT_MEMORY_REPLAY_COHORT"],
             "identity_gate": "Exact IDs from pre-response frozen sources only; expected counts 25 and 9.",
             "label": "FROZEN_COHORT_SENSITIVITY_EXPLORATORY", "bootstrap": "Same frozen generic family-cluster percentile procedure, labelled exploratory.",
             "confirmatory_or_holm_p_values": False},
        "mechanism_strata_policy": {"label": "ROUTER_SELECTED_OR_MECHANISM_STRATIFIED_EXPLORATORY",
             "strata": ["P3_RAG_REQUIRED", "P3_MEMORY_REQUIRED", "P3_PLANNING_REQUIRED", "RAG_SUPPORTED", "RAG_LIMITED_EVIDENCE", "RAG_NO_RESULT",
                        "MEMORY_AVAILABLE", "MEMORY_NO_MATCH", "PLANNER_USED", "PLANNER_INSUFFICIENT_EVIDENCE"],
             "membership_reference_mode": "C5_FULL_C4 for actual mechanism status; shared frozen P3 route for route-positive strata",
             "all_eight_contrasts_descriptive": True, "inference_or_bootstrap": False,
             "selection_on_scores": False, "unbiased_component_causal_effect_claim": False},
        "mechanism_and_efficiency_outcomes": {k: v for k,v in registry["evaluation_contract"].items() if k.endswith("_metrics")},
        "usage_policy": {"actual_experimental_provider_usage": "Count distinct frozen calls and exact-request identities; include historical attempts separately from accepted canonical outputs.",
             "condition_deployment_usage": "Project generator/module request requirements to 558 separate interactions as a counterfactual accounting, not actual historical calls.",
             "judge_usage": "Separate evaluation overhead; never multiply by 558.",
             "unknown_price_status": "COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY",
             "missing_metric_source_status": "NOT_EVALUABLE_SOURCE_NOT_AVAILABLE"},
        "human_policy": {"preserve_f0_agreement": True, "recalibration": False, "human_mode_effects": False, "human_judge_score_averaging": False},
        "claim_rule": "Reliable improvement is not established if the 95% bootstrap interval includes zero or Holm-adjusted primary p is at least 0.05; report the numerical effect in all cases.",
        "figures": ["Eight-contrast forest plot", "Nine-mode mean and median", "Descriptive eight-criterion profile", "Mechanism activation and outcomes"],
        "figure_data_policy": "Aggregate frozen outputs only; no qualitative example selection and no raw response text.",
        "implementation_choices_frozen_before_identity_access": True,
    }
    authorization = Path(sys.argv[1]).read_bytes()
    write_once_bytes(HERE / "F1_DIRECT_AUTHORIZATION_V1.txt", authorization)
    write_json(HERE / "F1_STARTING_GATES_V1.json", starting)
    write_json(HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json", {
        "schema_version": "F1_SOURCE_PRESERVATION_SNAPSHOT_V1", "captured_at_utc": now(),
        "operation": "BYTE_HASH_ONLY_NO_RESTRICTED_IDENTITY_DECODING", "file_count": len(snapshot), "files": snapshot})
    write_json(HERE / "F1_SOURCE_AUTHORITY_METADATA_V1.json", {
        "schema_version": "F1_SOURCE_AUTHORITY_METADATA_V1", "verification": "PASS", "specified_hash_count": len(verified),
        "sources": verified, "f0_status": f0["RQ3_REAL_F0_STATUS"], "f0_authority_status": f0["authority_status"],
        "judge_result_count": 149, "condition_mapping_count": 558, "human_items_per_rater": 44,
        "missing_or_duplicate_identity_count": 0, "excluded_judge_results_selected": 0,
        "f0_mode_unblinding_count": 0, "f0_treatment_effect_analysis_count": 0,
        "f0_result_integrity": f0["result_integrity_status"], "pacing_evidence_status": f0["pacing_evidence_status"],
        "prior_phase_a_incident_disclosed": f0["prior_phase_a_incident_disclosed"],
        "f0_hmac_commitment": starting["hmac_commitment"],
        "original_preparation_probe_failures": 1,
        "probe_resolution": "Directory-level ignore probe was inapplicable to an internal .gitignore. All restricted data files are ignored and untracked; the existing ignore file is tracked. No starting condition or source was changed."})
    write_json(HERE / "F1_ANALYSIS_CONTRACT_HIERARCHY_V1.json", hierarchy)
    write_json(HERE / "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json", plan)
    sealed = ["f1_common.py", "f1_controlled_unblinding_guard.py", "f1_statistics.py", "freeze_f1_entry.py"]
    metadata = ["F1_DIRECT_AUTHORIZATION_V1.txt", "F1_STARTING_GATES_V1.json", "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json",
                "F1_SOURCE_AUTHORITY_METADATA_V1.json", "F1_ANALYSIS_CONTRACT_HIERARCHY_V1.json", "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json"]
    receipt = {
        "schema_version": "F1_PRE_UNBLINDING_ANALYSIS_RECEIPT_V1", "frozen_at_utc": now(),
        "working_directory": str(ROOT), "branch": EXPECTED_BRANCH, "starting_head": STARTING_HEAD,
        "f0_completion_receipt_sha256": sha(F0 / "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json"),
        "f0_entry_receipt_sha256": sha(F0 / "F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1.json"),
        "f0_judge_human_and_authority_source_hashes": EXPECTED_HASHES,
        "mode_registry_sha256": sha(REGISTRY), "generic_statistical_contract_sha256": sha(GENERIC),
        "dataset_identity_hashes": {n: h for n,h in EXPECTED_HASHES.items() if "/track_d_dataset/" in n},
        "hmac_commitment": starting["hmac_commitment"], "primary_outcome": PRIMARY_OUTCOME,
        "exact_contrasts": plan["contrasts"], "statistical_algorithms": {k:plan[k] for k in ["bootstrap","sign_flip","wilcoxon","paired_cohens_dz","rank_biserial","tie_tolerance","holm_families"]},
        "subgroup_policy": {k: plan[k] for k in ["frozen_cohort_policy","mechanism_strata_policy"]},
        "secondary_outcome_policy": plan["secondary_policy"],
        "mode_mappings_opened_before_receipt": 0, "system_comparisons_computed_before_receipt": 0,
        "pre_receipt_restricted_operations": "Metadata-only byte hashing, stat and line counting; no condition-to-mode/scenario content was decoded.",
        "sealed_implementation_hashes": {n:sha(HERE/n) for n in sealed},
        "sealed_metadata_hashes": {n:sha(HERE/n) for n in metadata},
        "statistics_runtime": {"python": sys.version, "executable": sys.executable,
                               "numpy": importlib.metadata.version("numpy")},
        "prohibited_action_counts": PROHIBITED_ACTION_COUNTS,
        "write_count": 1, "overwrite_permitted": False, "write_enforcement": "O_EXCL; flush; fsync file and parent directory",
    }
    digest = write_json(RECEIPT, receipt)
    write_once_bytes(HERE / "f1_entry_binding.py", ("\"\"\"Immutable expected SHA-256 of the pre-unblinding receipt.\"\"\"\nENTRY_RECEIPT_SHA256 = " + repr(digest) + "\n").encode())
    write_once_bytes(LEDGER, b"")
    print(json.dumps({"status": "PRE_UNBLINDING_ANALYSIS_SEALED", "entry_receipt_sha256": digest,
                      "source_snapshot_file_count": len(snapshot), "specified_hashes_verified": len(verified),
                      "mode_mapping_content_accesses": 0, "system_comparisons_computed": 0}, indent=2))


if __name__ == "__main__":
    main()
