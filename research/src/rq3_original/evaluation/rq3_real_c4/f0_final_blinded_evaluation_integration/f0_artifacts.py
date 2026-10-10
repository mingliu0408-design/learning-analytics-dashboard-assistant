"""Serialize authorized blinded outputs; review materials contain metadata only."""
from __future__ import annotations

import json

from f0_common import HERE, ROOT, CRITERIA, FIELDS, canonical, pretty, digest, jsonl_bytes, csv_bytes, utc_now

CONDITION_FILE = "c4_real_corrected_condition_result_projection_f0_v1.jsonl"
HUMAN_MATCH_FILE = "c4_real_corrected_human_item_to_judge_result_f0_v1.jsonl"
HUMAN_AUDIT_FILE = "c4_real_human_excluded_base_pair_source_audit_f0_v1.jsonl"
JUDGE_JSONL = "c4_real_corrected_judge_results_frozen_v1.jsonl"
JUDGE_CSV = "c4_real_corrected_judge_results_frozen_v1.csv"
JUDGE_REGISTRY = "c4_real_corrected_judge_result_source_registry_v1.jsonl"
HUMAN_FILES = {r: {extension: f"c4_real_corrected_human_ratings_{r}_frozen_v1.{extension}" for extension in ("csv", "jsonl")} for r in "AB"}

# An exact, affirmative review allowlist. Raw result/rationale files and every
# restricted projection are deliberately absent. The allowlist itself is added
# by the completion freezer after all members have stable hashes.
REVIEW_FILES = (
    "F0_STARTING_GATES_V1.json", "F0_INTEGRATED_JUDGE_COMMIT_MAPPING_V1.json",
    "F0_ORIGINAL_JUDGE_COMMIT_SOURCE_MANIFEST_V1.json", "F0_PHASE_A_B_AUTHORITY_REFERENCES_V1.json",
    "F0_AUTHORIZED_SOURCE_CATALOG_V1.json", "F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json",
    "F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1.json", "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json",
    "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1.json", "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_DISCLOSURE.md",
    "F0_CONTROLLED_ACCESS_LEDGER_METADATA_V1.json", JUDGE_REGISTRY,
    "c4_real_corrected_judge_results_metadata_v1.json", "C4_REAL_CORRECTED_JUDGE_RESULTS_FREEZE_RECEIPT.json",
    "c4_real_corrected_condition_result_mapping_metadata_v1.json", "c4_real_human_source_intake_metadata_v1.json",
    "c4_real_corrected_human_ratings_metadata_v1.json", "c4_real_human_judge_match_metadata_v1.json",
    "c4_real_human_source_audit_metadata_v1.json", "C4_REAL_CORRECTED_HUMAN_RATING_FREEZE_RECEIPT.json",
    "C4_REAL_BLINDED_HUMAN_HUMAN_AGREEMENT_REPORT.md", "c4_real_blinded_human_human_agreement_v1.json",
    "C4_REAL_BLINDED_HUMAN_LLM_AGREEMENT_REPORT.md", "c4_real_blinded_human_llm_agreement_v1.json",
    "F0_JUDGE_USAGE_ACCOUNTING_V1.json", "F0_JUDGE_USAGE_ACCOUNTING_REPORT.md",
    "F0_BLINDED_INTEGRITY_AUDIT_V1.json", "F0_PRECOMPLETION_PRESERVATION_AUDIT_V1.json", "F0_RESTRICTED_OUTPUT_ENTRY_GATE_V1.json",
    "F0_TARGETED_TEST_RESULTS_V1.json", "F0_TARGETED_TEST_OUTPUT_V1.txt",
    "F0_FINAL_ARTIFACT_VERIFICATION_V1.json", "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json", "STATUS.md",
    "f0_common.py", "freeze_f0_entry.py", "f0_entry_binding.py", "f0_controlled_access_guard.py",
    "f0_blinded_integration.py", "f0_artifacts.py", "snapshot_f0_preservation.py",
    "test_f0_blinded_integration.py", "freeze_f0_results.py", "build_f0_review.py",
)


def file_meta(filename, raw, count):
    return {"filename": filename, "row_count": count, "sha256": digest(raw)}


def number(value):
    return "NOT_ESTIMABLE" if value is None else f"{value:.6f}"


def table_rows(result, human_llm):
    if human_llm:
        lines = ["| Criterion | n | Exact | Within 1 | MAE | Weighted kappa | Spearman | Judge minus Human bias |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|"]
    else:
        lines = ["| Criterion | n | Exact | Within 1 | Disagreements | Difference over 1 | Weighted kappa | Spearman |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for field, record in [*result["per_criterion"].items(), ("POOLED", result["pooled"])]:
        if record["n"] == 0:
            lines.append(f"| {field} | 0 | NOT_ESTIMABLE | NOT_ESTIMABLE | NOT_ESTIMABLE | NOT_ESTIMABLE | NOT_ESTIMABLE | NOT_ESTIMABLE |")
            continue
        exact = f'{record["exact_agreement_numerator"]}/{record["n"]} ({record["exact_agreement"]:.2%})'
        within = f'{record["within_one_point_numerator"]}/{record["n"]} ({record["within_one_point_agreement"]:.2%})'
        if human_llm:
            bias = number(record["criterion_level_bias_source_b_minus_source_a"]) if field != "POOLED" else "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED"
            lines.append(f'| {field} | {record["n"]} | {exact} | {within} | {number(record["mean_absolute_score_difference"])} | {number(record["quadratic_weighted_kappa"])} | {number(record["spearman_correlation"])} | {bias} |')
        else:
            lines.append(f'| {field} | {record["n"]} | {exact} | {within} | {record["disagreement_count"]} | {record["disagreement_over_one_point_count"]} | {number(record["quadratic_weighted_kappa"])} | {number(record["spearman_correlation"])} |')
    return "\n".join(lines)


def agreement_reports(hh, hl):
    contract = json.loads((HERE / "F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json").read_bytes())
    common = f"""The analysis uses 44 unique corrected Human-visible items. All complete visible
payloads, including corrected applicability, matched the selected Judge request.
The 108 sampled condition mappings are not independent Human observations.
Jointly NA criteria are excluded; applicability mismatches would stop validation.
Each single-rater comparison has 276 applicable and 76 NA item/criterion pairs.

Protocol: frozen rq3_statistical_analysis_contract_v1.json, SHA-256
`{contract['authoritative_contract_sha256']}`. Frozen formula implementation:
rq3_human_agreement.py, SHA-256 `{contract['implementation_sha256']}`.
The metric scope was written and fsynced before F0 score access. No scores or
rationales were rewritten and no disagreements were adjudicated. Mode identity,
system comparisons, treatment effects, and significance tests were not accessed
or computed.
"""
    human_human = "# Blinded Human-Human agreement\n\n" + common + "\n" + table_rows(hh, False) + "\n\n"
    human_human += "Human-Human MAE and bias: NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED. The contract lists those additional measures only for Human-LLM. Disagreement counts are the complements of the predeclared exact and within-one-point numerators.\n"
    human_llm = "# Blinded Human-LLM agreement\n\n" + common
    for name, title in (("human_a_vs_llm_judge", "Human A versus Judge"), ("human_b_vs_llm_judge", "Human B versus Judge"),
                        ("pooled_human_observations_vs_llm_judge", "Pooled independent Human observations versus Judge")):
        human_llm += f"\n## {title}\n\n" + table_rows(hl[name], True) + "\n"
    human_llm += "\nThe pooled Human-LLM comparison preserves two Human observations for each of the 44 unique items: 552 applicable pairs. It does not average raters or expand 108 condition mappings into observations. Criterion-level bias is mean(Judge minus Human). Pooled bias is NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED. Undefined statistics retain a NOT_ESTIMABLE reason in the machine-readable result.\n"
    return human_human.encode(), human_llm.encode()


def usage_report(usage):
    lines = ["# Judge usage accounting", "", "Each selected physical return is counted once. Usage is not multiplied by the 558 condition mappings.", "",
             "| Scope | Returned observations | Prompt tokens | Completion tokens | Total tokens | Cached input tokens |",
             "|---|---:|---:|---:|---:|---:|"]
    for key, label in (("canonical_corrected_results", "Canonical corrected results"), ("all_historical_returned_outputs", "All historical returned outputs"), ("noncanonical_returned_outputs", "Noncanonical returned outputs, included in historical total")):
        row = usage[key]
        t = row["known_token_totals"]
        lines.append(f'| {label} | {row["observations"]} | {t["prompt_tokens"]} | {t["completion_tokens"]} | {t["total_tokens"]} | {t["cached_input_tokens"]} |')
    lines += ["", f'Physical attempts started: {usage["physical_attempts_started"]}. Returned outputs: {usage["all_returned_output_count"]}.',
              f'Unknown Provider completion/billing attempts: {len(usage["unknown_provider_outcome_attempts"])}. Recorded API rejections without a Judge result: {len(usage["recorded_api_rejections_without_result"])}.', "",
              "Unknown outcomes include the historical interrupted A order-39 call and historical timeout calls. They are not Judge results; no token usage or billing is imputed. API-rejection subtype is not inferred from the durable RateLimitError category.", "",
              "The historical total includes changed-applicability excluded outputs, historical invalid outputs and redundant returns where usage is known. It remains incomplete for unobserved Provider outcomes. Machine-readable per-field unknown-observation counts and all eleven execution histories are retained.", "",
              "Cost status: " + usage["cost_status"] + ". Provider-billed cost is unavailable. F0 performed zero new Provider calls.", ""]
    return "\n".join(lines).encode()


def build_artifacts(data):
    judges, humans = data["judges"], data["humans"]
    tracked, restricted = {}, {}
    judge_rows = judges["results"]
    tracked[JUDGE_JSONL] = jsonl_bytes(judge_rows)
    flat = []
    for row in judge_rows:
        semantic = row["parsed_semantic_result"]
        flat.append({k: row[k] for k in ("logical_judge_request_id", "judge_result_blind_id", "provider_payload_sha256", "returned_model", "semantic_result_sha256", "frozen_applicability_map", "source_identity")} | {
            **{field: semantic[field] for field in FIELDS},
            **{key: semantic[key] for key in ("overall_applicable_mean", "evidence_faithfulness", "unsupported_claim_count", "criterion_rationales")}})
    tracked[JUDGE_CSV] = csv_bytes(flat, list(flat[0]))
    tracked[JUDGE_REGISTRY] = jsonl_bytes(judges["source_registry"])
    judge_meta = {"files": [file_meta(name, tracked[name], 149) for name in (JUDGE_JSONL, JUDGE_CSV, JUDGE_REGISTRY)],
                  "identity_hash_definition": "SHA256 of canonical UTF-8 JSON without a trailing newline for each semantic result or complete frozen record.",
                  "unique_judge_requests": 149, "unique_judge_results": 149,
                  "identities": [{k: row[k] for k in ("logical_judge_request_id", "judge_result_blind_id", "provider_payload_sha256", "semantic_result_sha256", "frozen_record_sha256")} for row in judges["source_registry"]]}
    tracked["c4_real_corrected_judge_results_metadata_v1.json"] = pretty(judge_meta)
    restricted[CONDITION_FILE] = jsonl_bytes(judges["condition_projection"])
    condition_meta = {"files": [file_meta(CONDITION_FILE, restricted[CONDITION_FILE], 558)]}
    tracked["c4_real_corrected_condition_result_mapping_metadata_v1.json"] = pretty(condition_meta)

    human_file_meta, human_identity_meta = [], []
    for rater in "AB":
        rows = humans["ratings"][rater]
        tracked[HUMAN_FILES[rater]["jsonl"]] = jsonl_bytes(rows)
        flat = []
        for row in rows:
            item = {k: row[k] for k in ("rater", "corrected_rating_item_id", "corrected_visible_payload_sha256", "applicability_flags")}
            for field in FIELDS:
                item[field + "_rating"] = row["criterion_scores"][field]
                item[field + "_rationale"] = row["criterion_rationales"][field]
            item["criterion_source_provenance"] = row["criterion_source_provenance"]
            flat.append(item)
            human_identity_meta.append({"rater": rater, "corrected_rating_item_id": row["corrected_rating_item_id"], "frozen_record_sha256": digest(canonical(row))})
        tracked[HUMAN_FILES[rater]["csv"]] = csv_bytes(flat, list(flat[0]))
        human_file_meta.extend(file_meta(name, tracked[name], 44) for name in HUMAN_FILES[rater].values())
    tracked["c4_real_corrected_human_ratings_metadata_v1.json"] = pretty({"files": human_file_meta, "item_identity_metadata": human_identity_meta})
    intake = {"schema_version": "c4-real-human-source-intake-f0-v1", "status": "PASS",
              "source_hashes": json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())["human_source_hashes"],
              "raters": humans["intake_metadata"], "same_opaque_item_set": True, "different_deterministic_orders": True,
              "human_rating_actions": 0, "human_amendment_actions": 0, "source_files_modified": False}
    tracked["c4_real_human_source_intake_metadata_v1.json"] = pretty(intake)
    restricted[HUMAN_MATCH_FILE] = jsonl_bytes(humans["item_matches"])
    restricted[HUMAN_AUDIT_FILE] = jsonl_bytes(humans["source_audit"])
    tracked["c4_real_human_judge_match_metadata_v1.json"] = pretty({"files": [file_meta(HUMAN_MATCH_FILE, restricted[HUMAN_MATCH_FILE], 44)]})
    tracked["c4_real_human_source_audit_metadata_v1.json"] = pretty({"files": [file_meta(HUMAN_AUDIT_FILE, restricted[HUMAN_AUDIT_FILE], 14)]})
    tracked["c4_real_blinded_human_human_agreement_v1.json"] = pretty(data["human_human"])
    tracked["c4_real_blinded_human_llm_agreement_v1.json"] = pretty(data["human_llm"])
    hh_report, hl_report = agreement_reports(data["human_human"], data["human_llm"])
    tracked["C4_REAL_BLINDED_HUMAN_HUMAN_AGREEMENT_REPORT.md"] = hh_report
    tracked["C4_REAL_BLINDED_HUMAN_LLM_AGREEMENT_REPORT.md"] = hl_report
    tracked["F0_JUDGE_USAGE_ACCOUNTING_V1.json"] = pretty(data["usage"])
    tracked["F0_JUDGE_USAGE_ACCOUNTING_REPORT.md"] = usage_report(data["usage"])
    audit = {
        "schema_version": "F0_BLINDED_INTEGRITY_AUDIT_V1", "status": "PASS",
        "judge_source_counts": {"retained": 33, "B": 38, "C": 39, "A_historical": 38, "A_order39_v2": 1},
        "canonical_result_count": 149, "unique_request_ids": 149, "unique_result_ids": 149,
        "missing_judge_results": 0, "duplicate_judge_identity": 0, "source_overlap": 0, "excluded_results_selected": 0,
        "score_transformations": 0, "corrected_execution_source_audit": judges["corrected_source_audit"],
        "retained_sources_without_historical_terminal": judges["retained_without_historical_terminal"],
        "retained_source_disclosure": "One Phase-B-retained result is materialized from the exact frozen raw attempt under unchanged Parser V3 and has no historical terminal reference. The other 32 retained sources have terminal references. No historical journal is altered or fabricated.",
        "corrected_execution_terminal_coverage": 116, "retained_registry_source_coverage": 33,
        "condition_mappings": 558, "missing_conditions": 0, "duplicate_condition_ids": 0,
        "unequal_payload_result_sharing": 0, "mode_columns_decoded": 0,
        "human_items_per_rater": 44, "human_pairs_per_rater": 352,
        "human_transition_counts_per_rater": {"retained_numeric": 270, "retained_na": 69, "old_applicable_to_na": 7, "amendments": 6},
        "corrected_numeric_per_rater": 276, "corrected_na_per_rater": 76,
        "human_item_judge_matches": 44, "complete_visible_payload_matches": 44,
        "human_condition_duplicates_treated_as_observations": 0,
        "agreement_metrics_predeclared_and_scope_frozen": True,
        "mode_level_means": 0, "system_comparisons": 0, "final_treatment_effect_statistics": 0,
        "provider_calls": 0, "network_calls": 0, "judge_executions": 0, "human_rating_actions": 0,
        "human_amendment_actions": 0, "response_generations": 0, "mode_unblinding": 0,
        "streamlit_launches": 0, "rag_memory_planning_evidence_p3_rq2_executions": 0,
    }
    tracked["F0_BLINDED_INTEGRITY_AUDIT_V1.json"] = pretty(audit)
    timestamp = utc_now()
    judge_receipt = {"schema_version": "C4_REAL_CORRECTED_JUDGE_RESULTS_FREEZE_RECEIPT", "frozen_at_utc": timestamp,
                     "status": "FROZEN_149_CORRECTED_CANONICAL_RESULTS", "source_counts": audit["judge_source_counts"],
                     "results_metadata_sha256": digest(tracked["c4_real_corrected_judge_results_metadata_v1.json"]),
                     "result_files": judge_meta["files"], "result_identity_list_sha256": digest(canonical(judge_meta["identities"])),
                     "source_registry_sha256": digest(tracked[JUDGE_REGISTRY]), "unique_request_ids": 149, "unique_result_ids": 149,
                     "result_integrity_status": "PASS", "pacing_evidence_status": "QUALIFIED_PACING_EVIDENCE_LIMITATION",
                     "missing_results": 0, "duplicate_identity": 0, "source_overlap": 0, "excluded_results": 0, "score_transformations": 0,
                     "retained_without_historical_terminal": audit["retained_sources_without_historical_terminal"],
                     "retained_source_disclosure": audit["retained_source_disclosure"],
                     "write_count": 1, "overwrite_permitted": False}
    tracked["C4_REAL_CORRECTED_JUDGE_RESULTS_FREEZE_RECEIPT.json"] = pretty(judge_receipt)
    human_receipt = {"schema_version": "C4_REAL_CORRECTED_HUMAN_RATING_FREEZE_RECEIPT", "frozen_at_utc": timestamp,
                     "status": "FROZEN_CORRECTED_HUMAN_BASE_AND_AMENDMENTS", "items_per_rater": 44,
                     "source_hashes": intake["source_hashes"], "raters": humans["intake_metadata"], "result_files": human_file_meta,
                     "human_metadata_sha256": digest(tracked["c4_real_corrected_human_ratings_metadata_v1.json"]),
                     "source_intake_metadata_sha256": digest(tracked["c4_real_human_source_intake_metadata_v1.json"]),
                     "excluded_base_pair_source_audit_metadata_sha256": digest(tracked["c4_real_human_source_audit_metadata_v1.json"]),
                     "matched_amendment_ids": humans["amendment_ids"], "disagreements_adjudicated": False,
                     "source_ratings_or_rationales_modified": False, "write_count": 1, "overwrite_permitted": False}
    tracked["C4_REAL_CORRECTED_HUMAN_RATING_FREEZE_RECEIPT.json"] = pretty(human_receipt)
    return tracked, restricted
