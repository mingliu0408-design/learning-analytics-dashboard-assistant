#!/usr/bin/env python3
"""Self-contained validator for the extracted J2D1 review package."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import re
from typing import Any


HERE = Path(__file__).resolve().parent
EXPECTED_FILES = {
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


def load_json(name: str) -> Any:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_csv(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run_checks(*, exact_directory: bool = True) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def check(name: str, condition: bool) -> None:
        checks.append({"name": name, "status": "PASS" if condition else "FAIL"})

    existing = {path.name for path in HERE.iterdir() if path.is_file()}
    check("all_expected_files_present", EXPECTED_FILES <= existing)
    if exact_directory:
        check("exact_review_file_allowlist", existing == EXPECTED_FILES)

    audit = load_json("c4_real_applicability_provenance_audit_v1.json")
    scenarios = load_csv("c4_real_62_scenario_applicability_audit_v1.csv")
    conditions = load_json("c4_real_558_condition_applicability_dependency_audit_v1.json")
    error = load_json("c4_real_error_handling_applicability_audit_v1.json")
    packet = load_csv("applicability_researcher_review_packet.csv")
    packet_text = (HERE / "applicability_researcher_review_packet.csv").read_text(encoding="utf-8")

    check("ready_status", audit["status"] == "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW")
    check("four_integrations_recorded", len(audit["commit_integration"]["mappings"]) == 4)
    check("integration_order_recorded", [row["order"] for row in audit["commit_integration"]["mappings"]] == [1, 2, 3, 4])
    check("judge_preservation_pass", audit["judge_execution_preservation"]["status"] == "PASS_ALL_ORIGINAL_JUDGE_ARTIFACTS_BYTE_IDENTICAL")
    check("canonical_judge_counts", audit["judge_execution_preservation"]["j2d0_canonical"] == {"shard_counts": {"A": 1, "B": 38, "C": 31}, "total": 70})
    check("provisional_judge_counts", audit["judge_execution_preservation"]["provisional_preserved_result_counts"] == {"A": 1, "B": 49, "C": 39, "total": 89})

    order40 = audit["order_40_reproduction"]
    check("order40_reproduced", order40["status"] == "REPRODUCED_WITHOUT_PROVIDER_CALL_OR_CANONICAL_RESULT")
    check("order40_two_schema_valid", len(order40["attempts"]) == 2 and all(row["provider_schema_valid"] for row in order40["attempts"]))
    check("order40_exact_contract_failure", all(row["actionability_token"] == "3" and row["parser_v3_error"].endswith("actionability must be NA") for row in order40["attempts"]))
    check("order40_not_canonical", order40["canonical_result_created"] is False)

    summary = audit["scenario_audit_summary"]
    check("scenario_population_62", len(scenarios) == 62 and summary["scenario_count"] == 62)
    check("scenario_ids_complete", {row["scenario_id"] for row in scenarios} == {f"U{i:03d}" for i in range(1, 63)})
    check("planning_disagreements_8", summary["planning_reference_disagreement_count"] == 8)
    check("planning_disagreement_sets", summary["planning_false_negatives"] == ["U013", "U015", "U016", "U017", "U021", "U023", "U058"] and summary["planning_false_positives"] == ["U029"])
    check("personalisation_findings", summary["long_term_memory_provenance_disagreement_count"] == 24 and summary["long_term_memory_current_true_reference_false_count"] == 17 and summary["long_term_memory_current_false_reference_true_count"] == 7 and summary["personalisation_draft_change_count"] == 0)
    check("multi_page_findings", summary["current_multi_page_true_scenario_count"] == 13 and summary["multi_page_materiality_review_count"] == 13 and summary["material_page_candidate_list_match_count"] == 62)
    check("no_final_decisions", summary["final_discretionary_decisions_made"] is False and all(row["final_decision_status"] == "NOT_MADE_RESEARCHER_REVIEW_REQUIRED" for row in scenarios))

    check("condition_population_558", conditions["condition_count"] == 558 and len(conditions["records"]) == 558)
    check("condition_response_blind", conditions["candidate_response_accessed"] is False and conditions["judge_score_or_rationale_accessed"] is False and conditions["human_score_or_rationale_accessed"] is False)
    check("condition_no_corrected_maps", all(not row["corrected_map_written"] and not row["final_applicability_decision_made"] for row in conditions["records"]))

    check("error_population_558", error["condition_count"] == 558 and len(error["records"]) == 558)
    check("error_no_false_positive", error["current_true_without_reason_count"] == 0)
    check("error_no_false_negative", error["current_false_with_reason_count"] == 0)
    check("error_maps_unchanged", error["frozen_v1_maps_overwritten"] is False)

    check("packet_population_62", len(packet) == 62)
    check("packet_opaque_unique_ids", len({row["applicability_review_id"] for row in packet}) == 62 and all(re.fullmatch(r"APR-[A-F0-9]{24}", row["applicability_review_id"]) for row in packet))
    check("packet_final_fields_blank", all(row[field] == "" for row in packet for field in FINAL_FIELDS))
    check("packet_no_scenario_ids", re.search(r"\bU\d{3}\b", packet_text) is None)
    check("packet_no_judge_or_response_ids", "C4J1-" not in packet_text and "R3B-" not in packet_text and "response_blind_id" not in packet_text)
    check("packet_no_response_or_decision_columns", all(name not in packet[0] for name in ("candidate_response", "scenario_id", "scenario_group", "mode", "p3_route", "current_applicability", "draft_corrected_decision", "expected_winner")))

    impact = audit["impact_assessment"]
    check("impact_identity_only", impact["identity_only_analysis"] and not impact["score_values_accessed"] and not impact["rationales_accessed"])
    check("impact_judge_counts", (impact["total_unique_judge_requests"], impact["potentially_changed_unique_judge_requests"], impact["potentially_changed_with_preserved_outputs"], impact["potentially_changed_currently_unattempted"]) == (147, 24, 9, 15))
    check("impact_human_counts", (impact["total_unique_human_visible_items"], impact["potentially_affected_human_items"], impact["potentially_affected_human_item_criterion_pairs"]) == (44, 6, 6))
    check("impact_actionability_only", impact["judge_request_criterion_amendment_counts"]["ACTIONABILITY"] == 24 and sum(impact["judge_request_criterion_amendment_counts"].values()) == 24 and impact["human_item_criterion_amendment_counts"]["ACTIONABILITY"] == 6 and sum(impact["human_item_criterion_amendment_counts"].values()) == 6)

    check("human_sources_metadata_only", audit["human_source_readiness"]["completed_rating_content_imported"] is False and audit["human_source_readiness"]["completed_score_or_rationale_content_inspected"] is False and len(audit["human_source_readiness"]["sources"]) == 4)
    check("no_human_amendment_packet", audit["human_source_readiness"]["amendment_packet_created"] is False)
    check("all_execution_counters_zero", all(value == 0 for value in audit["execution_counters"].values()))
    check("repair_boundaries_preserved", not any(audit["repair_boundaries"].values()))

    policy = (HERE / "C4_REAL_APPLICABILITY_REPAIR_POLICY_DRAFT.md").read_text(encoding="utf-8")
    attestation = (HERE / "applicability_researcher_attestation.md").read_text(encoding="utf-8")
    check("repair_policy_nine_rules", len(re.findall(r"^\d+\. ", policy, flags=re.MULTILINE)) == 9)
    check("attestation_blank", "- [x]" not in attestation.casefold() and "- [ ]" in attestation)
    check("restricted_material_absent", all(not any(term in name.casefold() for term in ("restricted", "mapping", "hmac", "execution_output", "human_rating_packet")) for name in existing))

    failed = [row["name"] for row in checks if row["status"] == "FAIL"]
    if failed:
        raise RuntimeError("review validation failures: " + ", ".join(failed))
    return checks


def main() -> None:
    checks = run_checks(exact_directory=True)
    counts = Counter(row["status"] for row in checks)
    print(json.dumps({"status": "PASS", "checks_passed": counts["PASS"], "checks_failed": counts["FAIL"]}, sort_keys=True))


if __name__ == "__main__":
    main()
