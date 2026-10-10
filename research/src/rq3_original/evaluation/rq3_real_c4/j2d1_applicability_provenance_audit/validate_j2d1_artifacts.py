#!/usr/bin/env python3
"""Offline validator for the RQ3-REAL-C4-J2D1 audit artifacts."""

from __future__ import annotations

from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STARTING_HEAD = "3e125353993ad4813e96ed6690e708f932da0d29"
AUDIT_PARENT_HEAD = "8de7c8c37be6bbeac31d0047c3da7a0bd67fad3f"
EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
RESTRICTED_MAPPING = (
    ROOT
    / "evaluation/rq3_real_c4/i1_route_integration/restricted_internal/"
    "c4_real_j2d1_applicability_review_id_to_scenario_mapping_v1.csv"
)
HMAC_KEY = (
    ROOT
    / "evaluation/rq3_real_c4/i1_route_integration/restricted_internal/"
    "c4_real_i1_blinding_hmac_key.bin"
)
AUDIT_JSON = HERE / "c4_real_applicability_provenance_audit_v1.json"
SCENARIO_CSV = HERE / "c4_real_62_scenario_applicability_audit_v1.csv"
CONDITION_JSON = HERE / "c4_real_558_condition_applicability_dependency_audit_v1.json"
ERROR_JSON = HERE / "c4_real_error_handling_applicability_audit_v1.json"
PACKET_CSV = HERE / "applicability_researcher_review_packet.csv"

REQUIRED_ARTIFACTS = {
    "APPLICABILITY_REVIEWER_GUIDE.md",
    "C4_REAL_APPLICABILITY_PROVENANCE_AUDIT.md",
    "C4_REAL_APPLICABILITY_REPAIR_IMPACT_PREVIEW.md",
    "C4_REAL_APPLICABILITY_REPAIR_POLICY_DRAFT.md",
    "C4_REAL_ORDER40_APPLICABILITY_FAILURE_ANALYSIS.md",
    "STATUS.md",
    "applicability_researcher_attestation.md",
    "applicability_researcher_review_packet.csv",
    "c4_real_558_condition_applicability_dependency_audit_v1.json",
    "c4_real_62_scenario_applicability_audit_v1.csv",
    "c4_real_applicability_provenance_audit_v1.json",
    "c4_real_error_handling_applicability_audit_v1.json",
}
PACKAGE_FILES = REQUIRED_ARTIFACTS | {
    "validate_j2d1_review_artifacts.py",
    "test_j2d1_review_artifacts.py",
}
FINAL_FIELDS = (
    "researcher_personalisation_applicable",
    "researcher_actionability_applicable",
    "researcher_motivation_and_engagement_applicable",
    "researcher_material_lad_pages",
    "researcher_notes",
)
PROHIBITED_PACKET_COLUMNS = {
    "scenario_id",
    "scenario_group",
    "mode",
    "mode_id",
    "p3_route",
    "current_applicability",
    "draft_corrected_decision",
    "candidate_response",
    "judge_request_id",
    "judge_result_id",
    "human_rating",
    "expected_winner",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Ledger:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def check(self, name: str, condition: bool) -> None:
        self.rows.append({"name": name, "status": "PASS" if condition else "FAIL"})

    def require_all(self) -> None:
        failed = [row["name"] for row in self.rows if row["status"] == "FAIL"]
        if failed:
            raise RuntimeError("validation failures: " + ", ".join(failed))


def run_checks(zip_path: Path | None = None) -> list[dict[str, str]]:
    ledger = Ledger()
    audit = load_json(AUDIT_JSON)
    scenario_rows = load_csv(SCENARIO_CSV)
    condition = load_json(CONDITION_JSON)
    error = load_json(ERROR_JSON)
    packet = load_csv(PACKET_CSV)

    ledger.check("exact_working_directory", ROOT == Path("/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-c4-i1-route-integration"))
    ledger.check("exact_branch", git("branch", "--show-current") == EXPECTED_BRANCH)
    ledger.check("starting_head_recorded", audit["starting_head"] == STARTING_HEAD)
    ledger.check("integration_parent_ancestor", subprocess.run(["git", "merge-base", "--is-ancestor", AUDIT_PARENT_HEAD, "HEAD"], cwd=ROOT).returncode == 0)
    ledger.check("required_artifacts_present", REQUIRED_ARTIFACTS <= {path.name for path in HERE.iterdir() if path.is_file()})

    mappings = audit["commit_integration"]["mappings"]
    ledger.check("four_commits_integrated", len(mappings) == 4)
    ledger.check("integration_exact_order", [row["order"] for row in mappings] == [1, 2, 3, 4])
    ledger.check("integration_exact_originals", [row["original_commit"] for row in mappings] == [
        "ace2cf9bc8874808050380e529afb7af80a0865c",
        "3751ea31f9dadf716063235088320f7d307628e9",
        "53f33526ad51b08af7d4af35160a98bf5c009671",
        "90cc2059c1cbe7a2205077ff1cb7ffb97689603f",
    ])
    ledger.check("integration_no_conflicts", audit["commit_integration"]["conflicts"] == 0 and all(row["conflict_resolution"] == "NONE" for row in mappings))
    ledger.check("integration_patch_identity", all(row["patch_byte_identical"] for row in mappings))

    preservation = audit["judge_execution_preservation"]
    ledger.check("judge_tree_byte_identity", preservation["status"] == "PASS_ALL_ORIGINAL_JUDGE_ARTIFACTS_BYTE_IDENTICAL" and all(row["byte_identical"] for row in preservation["tree_identity_checks"]))
    ledger.check("j2d0_counts", preservation["j2d0_canonical"] == {"shard_counts": {"A": 1, "B": 38, "C": 31}, "total": 70})
    ledger.check("judge_b_counts", preservation["judge_b_v2"]["valid_results"] == 11 and preservation["judge_b_v2"]["request_count"] == 11)
    ledger.check("judge_b_hashes", preservation["judge_b_v2"]["terminal_journal_sha256"] == "c7cdcb0124aaa1a1f2137f2e17dac48c075cc1c888fbe92305bcf6f90642a268" and preservation["judge_b_v2"]["parsed_result_set_sha256"] == "b51928e34e693464cf3dc421404108fb2ea160f2b2bff723054c704f50c9865b")
    ledger.check("judge_c_counts", preservation["judge_c_v2"]["valid_results"] == 8 and preservation["judge_c_v2"]["physical_attempts"] == 10 and preservation["judge_c_v2"]["unattempted_original_logical_orders"] == "41-49")
    ledger.check("judge_c_hashes", preservation["judge_c_v2"]["attempt_journal_sha256"] == "8d9877e5744b605282b367209bc8cc9fbb1f318fb863b0f4e77cb11a2268943b" and preservation["judge_c_v2"]["terminal_journal_sha256"] == "03560d2a8d5a9c2a39d15442eb6c2648376ffa125e375db1cd389fa7798a6de6" and preservation["judge_c_v2"]["parsed_result_set_sha256"] == "9f2615b5913e6fa32be3b942446440b60301c3191d3ba6db9b58224dc0e946ff")
    ledger.check("provisional_count_89", preservation["provisional_preserved_result_counts"] == {"A": 1, "B": 49, "C": 39, "total": 89})

    order40 = audit["order_40_reproduction"]
    ledger.check("order40_query_and_map", order40["student_query"] == "How can I perform better in this aspect?" and order40["frozen_applicability_criteria"]["ACTIONABILITY"] is False and sum(order40["frozen_applicability_criteria"].values()) == 7)
    ledger.check("order40_two_schema_valid_outputs", len(order40["attempts"]) == 2 and all(row["provider_schema_json_valid"] and row["provider_schema_valid"] for row in order40["attempts"]))
    ledger.check("order40_actionability_tokens", [row["actionability_token"] for row in order40["attempts"]] == ["3", "3"])
    ledger.check("order40_exact_parser_errors", all(row["parser_v3_error"] == "APPLICABILITY_CONTRACT_VIOLATION: actionability must be NA" for row in order40["attempts"]))
    ledger.check("order40_attempt1_other_fields", order40["attempts"][0]["currently_applicable_primary_fields_numeric"] is True and order40["attempts"][0]["currently_applicable_primary_field_count"] == 7)
    ledger.check("order40_no_other_error", all(order40["absence_of_other_failure_classes"].values()))
    ledger.check("order40_no_canonical_result", order40["canonical_result_created"] is False and order40["score_preference_evaluated"] is False)

    implementation = audit["implementation_audit"]
    source_text = (ROOT / implementation["path"]).read_text(encoding="utf-8")
    ledger.check("i1_code_hash", sha256_file(ROOT / implementation["path"]) == implementation["full_file_sha256"])
    ledger.check("p3_dependency_detected", all(fragment in source_text for fragment in (
        'bool(dashboard_context) or route["memory_required"]',
        '"long_term_memory_relevant": route["memory_required"]',
        '"request_requires_advice": route["planning_required"]',
        '"gold_planning_required": False',
    )))
    ledger.check("frozen_map_hash", audit["source_manifest"]["applicability_maps"]["sha256"] == "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084")

    summary = audit["scenario_audit_summary"]
    ledger.check("scenario_rows_62", len(scenario_rows) == 62 and summary["scenario_count"] == 62)
    ledger.check("scenario_ids_exact", {row["scenario_id"] for row in scenario_rows} == {f"U{i:03d}" for i in range(1, 63)})
    ledger.check("planning_disagreements_exact", summary["planning_false_negatives"] == ["U013", "U015", "U016", "U017", "U021", "U023", "U058"] and summary["planning_false_positives"] == ["U029"] and summary["planning_reference_disagreement_count"] == 8)
    ledger.check("personalisation_findings", summary["long_term_memory_provenance_disagreement_count"] == 24 and summary["long_term_memory_current_true_reference_false_count"] == 17 and summary["long_term_memory_current_false_reference_true_count"] == 7 and summary["student_specific_data_provenance_disagreement_count"] == 0 and summary["personalisation_draft_change_count"] == 0 and summary["current_personalisation_true_scenario_count"] == 52)
    ledger.check("multi_page_findings", summary["current_multi_page_true_scenario_count"] == 13 and summary["multi_page_materiality_review_count"] == 13 and summary["material_page_candidate_list_match_count"] == 62)
    ledger.check("no_final_scenario_decisions", all(row["final_decision_status"] == "NOT_MADE_RESEARCHER_REVIEW_REQUIRED" for row in scenario_rows) and summary["final_discretionary_decisions_made"] is False)

    ledger.check("condition_rows_558", condition["condition_count"] == 558 and len(condition["records"]) == 558)
    ledger.check("condition_response_blind_sources", condition["candidate_response_accessed"] is False and condition["judge_score_or_rationale_accessed"] is False and condition["human_score_or_rationale_accessed"] is False)
    ledger.check("no_corrected_condition_maps", condition["status"] == "DRAFT_DEPENDENCY_AUDIT_ONLY_NO_CORRECTED_MAP" and all(row["corrected_map_written"] is False and row["final_applicability_decision_made"] is False for row in condition["records"]))

    ledger.check("error_rows_558", error["condition_count"] == 558 and len(error["records"]) == 558)
    ledger.check("error_deterministic_draft", error["status"] == "DRAFT_MECHANICAL_AUDIT_ONLY_FROZEN_V1_UNCHANGED" and error["frozen_v1_maps_overwritten"] is False)
    ledger.check("error_no_false_positives", error["current_true_without_reason_count"] == 0)
    ledger.check("error_no_false_negatives", error["current_false_with_reason_count"] == 0)
    ledger.check("error_reason_counts", error["reason_code_counts"] == {"DASHBOARD_TYPED_EMPTY": 80, "MEMORY_NO_MATCH": 68, "PLANNER_INSUFFICIENT_EVIDENCE": 6, "RAG_METADATA_OR_LINK_ONLY_BOUNDARY": 44, "RAG_NO_RESULT": 36})

    packet_headers = set(packet[0])
    ledger.check("packet_rows_62", len(packet) == 62)
    ledger.check("packet_opaque_ids", len({row["applicability_review_id"] for row in packet}) == 62 and all(re.fullmatch(r"APR-[A-F0-9]{24}", row["applicability_review_id"]) for row in packet))
    ledger.check("packet_required_fields_blank", all(row[field] == "" for row in packet for field in FINAL_FIELDS))
    ledger.check("packet_no_prohibited_columns", not (packet_headers & PROHIBITED_PACKET_COLUMNS))
    packet_text = PACKET_CSV.read_text(encoding="utf-8")
    ledger.check("packet_no_scenario_or_mode_ids", re.search(r"\bU\d{3}\b", packet_text) is None and re.search(r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_)\b", packet_text) is None)
    ledger.check("packet_no_judge_or_response_ids", "C4J1-" not in packet_text and "R3B-" not in packet_text and "response_blind_id" not in packet_text)
    ledger.check("packet_no_candidate_or_current_decisions", "candidate_response" not in packet_text and "current_applicability" not in packet_text and "expected_winner" not in packet_text)

    ledger.check("restricted_mapping_present", RESTRICTED_MAPPING.is_file() and len(load_csv(RESTRICTED_MAPPING)) == 62)
    ledger.check("restricted_mapping_ignored", bool(git("check-ignore", str(RESTRICTED_MAPPING.relative_to(ROOT)))))
    ledger.check(
        "restricted_mapping_untracked",
        git("ls-files", "--", str(RESTRICTED_MAPPING.relative_to(ROOT))) == "",
    )
    mapping = load_csv(RESTRICTED_MAPPING)
    ledger.check("restricted_mapping_matches_packet", {row["applicability_review_id"] for row in mapping} == {row["applicability_review_id"] for row in packet})
    ledger.check("hmac_key_preserved", HMAC_KEY.stat().st_size == 32 and sha256_file(HMAC_KEY) == "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5")

    impact = audit["impact_assessment"]
    ledger.check("impact_identity_only", impact["identity_only_analysis"] is True and impact["score_values_accessed"] is False and impact["rationales_accessed"] is False)
    ledger.check("impact_judge_counts", impact["total_unique_judge_requests"] == 147 and impact["potentially_changed_unique_judge_requests"] == 24 and impact["potentially_changed_currently_unattempted"] == 15 and impact["potentially_changed_with_preserved_outputs"] == 9 and impact["preserved_outputs_requiring_rejudge_if_draft_changes_are_confirmed"] == 9)
    ledger.check("impact_human_counts", impact["total_unique_human_visible_items"] == 44 and impact["potentially_affected_human_items"] == 6 and impact["potentially_affected_human_item_criterion_pairs"] == 6)
    ledger.check("impact_criterion_counts", impact["judge_request_criterion_amendment_counts"] == {"ACTIONABILITY": 24, "ERROR_HANDLING": 0, "MOTIVATION_AND_ENGAGEMENT": 0, "MULTI_PAGE_COHESIVENESS": 0, "PERSONALISATION": 0} and impact["human_item_criterion_amendment_counts"] == {"ACTIONABILITY": 6, "ERROR_HANDLING": 0, "MOTIVATION_AND_ENGAGEMENT": 0, "MULTI_PAGE_COHESIVENESS": 0, "PERSONALISATION": 0})
    builder_text = (HERE / "build_j2d1_artifacts.py").read_text(encoding="utf-8")
    ledger.check(
        "impact_projects_judge_identity_fields_only",
        "projected_jsonl_string_field" in builder_text
        and 'load_jsonl(SOURCE_PATHS["existing_canonical_judge_results"])' not in builder_text
        and 'load_jsonl(SOURCE_PATHS["judge_b_terminals_v2"])' not in builder_text
        and 'load_jsonl(SOURCE_PATHS["judge_c_terminals_v2"])' not in builder_text,
    )

    readiness = audit["human_source_readiness"]
    ledger.check("human_sources_metadata_only", readiness["status"] == "READY_EXTERNAL_COMPLETED_SOURCES_PRESENT_HASHED_ONLY" and len(readiness["sources"]) == 4 and all(row["present"] and not row["content_imported"] and not row["rating_or_attestation_content_inspected"] for row in readiness["sources"]))
    ledger.check("human_no_amendment_or_repeat", readiness["amendment_packet_created"] is False and readiness["full_repeat_requested"] is False)
    ledger.check("all_execution_counters_zero", all(value == 0 for value in audit["execution_counters"].values()))
    ledger.check("repair_boundaries_preserved", not any(audit["repair_boundaries"].values()))
    ledger.check("status_ready", audit["status"] == "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW" and "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW" in (HERE / "STATUS.md").read_text(encoding="utf-8"))

    changed = git("diff", "--name-only", f"{STARTING_HEAD}..HEAD").splitlines()
    allowed_prefixes = (
        "evaluation/rq3_real_c4/j3b_judge_continuation_b/",
        "evaluation/rq3_real_c4/j3c_judge_continuation_c/",
        "evaluation/rq3_real_c4/j2d1_applicability_provenance_audit/",
    )
    ledger.check("committed_scope_confined", all(name.startswith(allowed_prefixes) for name in changed))
    status_lines = git("status", "--porcelain", "--untracked-files=all").splitlines()
    ledger.check("working_changes_confined", all(line[3:].startswith("evaluation/rq3_real_c4/j2d1_applicability_provenance_audit/") for line in status_lines))

    if zip_path is not None:
        ledger.check("review_zip_exists", zip_path.is_file())
        if zip_path.is_file():
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
                basename_by_name = {name: Path(name).name for name in names}
                ledger.check("review_zip_exact_allowlist", len(names) == len(PACKAGE_FILES) and set(basename_by_name.values()) == PACKAGE_FILES)
                ledger.check("review_zip_crc", archive.testzip() is None)
                ledger.check("review_zip_source_byte_identity", all(archive.read(name) == (HERE / basename).read_bytes() for name, basename in basename_by_name.items()))
                ledger.check("review_zip_no_restricted_paths", all("restricted" not in name.casefold() and "mapping" not in name.casefold() and "hmac" not in name.casefold() for name in names))
                key = HMAC_KEY.read_bytes()
                ledger.check("review_zip_no_hmac_key_bytes", all(key not in archive.read(name) for name in names))
                ledger.check("review_zip_no_provider_or_human_outputs", all(not any(fragment in name.casefold() for fragment in ("execution_output", "judge_terminal", "judge_attempt", "human_rating_packet_a_completed", "human_rating_packet_b_completed")) for name in names))

    ledger.require_all()
    return ledger.rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=None)
    args = parser.parse_args()
    rows = run_checks(args.zip)
    counts = Counter(row["status"] for row in rows)
    print(json.dumps({"status": "PASS", "checks_passed": counts["PASS"], "checks_failed": counts["FAIL"]}, sort_keys=True))


if __name__ == "__main__":
    main()
