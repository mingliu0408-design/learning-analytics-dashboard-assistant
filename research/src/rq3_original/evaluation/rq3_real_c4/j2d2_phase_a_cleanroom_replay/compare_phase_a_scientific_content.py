#!/usr/bin/env python3
"""Compare only the explicitly named Phase-A artifacts, after replay completion.

This program never imports legacy repository modules or reads outcome data.
Scientific mismatches are recorded and terminate certification eligibility.
"""

import csv
import datetime
import hashlib
import io
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
HISTORICAL = HERE.parent / "j2d2_corrected_applicability_freeze"
OUTPUTS = HERE / "replay_outputs"
SCENARIO_NAME = "c4_real_researcher_scenario_applicability_decisions_frozen_v1"
CONDITION_NAME = "c4_real_condition_applicability_maps_frozen_v2"
RESEARCHER = ("PERSONALISATION", "ACTIONABILITY", "MOTIVATION_AND_ENGAGEMENT", "MULTI_PAGE_COHESIVENESS")
ALWAYS = ("CLARITY", "CONTEXT_AWARENESS", "RELIABILITY")
ALL_CRITERIA = (*RESEARCHER, *ALWAYS, "ERROR_HANDLING")
HISTORICAL_NAMES = (
    "APPLICABILITY_V2_PRE_OUTCOME_FREEZE_RECEIPT.json", "PHASE_A_BOUNDARY_INCIDENT_REPORT.md",
    SCENARIO_NAME + ".jsonl", SCENARIO_NAME + ".csv", CONDITION_NAME + ".jsonl", CONDITION_NAME + ".csv",
    "c4_real_applicability_v1_v2_diff_audit.json", "c4_real_j2d2_phase_a_source_manifest_v1.json",
    "source_intake/applicability_researcher_review_packet_completed.csv",
    "source_intake/applicability_researcher_attestation_completed.md",
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_json(path):
    return json.loads(path.read_bytes())


def load_jsonl(path):
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


def load_csv(path):
    text = path.read_bytes().decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    return list(csv.DictReader(io.StringIO(text, newline=""), strict=True))


def boolean(value):
    if value not in {"true", "false"}:
        raise ValueError("Unexpected applicability boolean representation")
    return value == "true"


def indexed(rows, fields):
    result = {tuple(row[f] for f in fields): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate scientific identity")
    return result


def differences(left, right):
    return sum(left.get(key) != right.get(key) for key in set(left) | set(right))


def normalized_changes(rows):
    return [{**row, "changed_criteria": sorted(row["changed_criteria"])} for row in rows]


def scenario_projection(rows, clean=False):
    result = []
    for row in rows:
        criteria = {**row["criteria"], **({c: True for c in ALWAYS} if clean else {})}
        if set(criteria) != set(RESEARCHER) | set(ALWAYS) or not all(type(v) is bool for v in criteria.values()):
            raise ValueError("Scenario scientific schema mismatch")
        pages = row["material_lad_pages"]
        if len(pages) != len(set(pages)):
            raise ValueError("Duplicate material page")
        result.append({"scenario_id": row["scenario_id"], "criteria": criteria,
                       "material_lad_pages": sorted(pages)})
    return sorted(result, key=lambda row: row["scenario_id"])


def condition_projection(rows, clean=False):
    result = []
    for row in rows:
        criteria = row["criteria"] if clean else row["frozen_applicability_map"]["criteria"]
        if set(criteria) != set(ALL_CRITERIA) or not all(type(v) is bool for v in criteria.values()):
            raise ValueError("Condition scientific schema mismatch")
        pages = row["material_lad_pages"] if clean else row["source_metadata"]["material_lad_pages"]
        if len(pages) != len(set(pages)):
            raise ValueError("Duplicate condition material page")
        result.append({"scenario_id": row["scenario_id"], "mode": row["mode"],
                       "criteria": criteria, "material_lad_pages": sorted(pages)})
    return sorted(result, key=lambda row: (row["scenario_id"], row["mode"]))


def compare():
    metadata = load_json(HERE / "PHASE_A_CLEANROOM_REPLAY_OUTPUT_METADATA_V1.json")
    if metadata["status"] != "CLEANROOM_REPLAY_COMPLETE":
        raise ValueError("Historical access requires a completed replay")
    manifest = load_json(HERE / "PHASE_A_CLEANROOM_ALLOWED_INPUTS_MANIFEST.json")
    entry = load_json(HERE / "PHASE_A_ENTRY_GATE_V1.json")
    inputs = Path(manifest["sealed_input_directory"])
    checks = []

    def check(name, condition, mismatch_count=0):
        checks.append({"name": name, "passed": bool(condition),
                       "mismatch_count": mismatch_count if not condition else 0})

    preservation = {}
    for name, expected in entry["original_records"].items():
        path = HISTORICAL / name
        stat = path.stat()
        actual = {"sha256": digest(path.read_bytes()), "bytes": stat.st_size,
                  "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}
        preservation[name] = actual
        check("preservation:" + name, actual == expected)
    historical_hashes = [{"filename": name, "byte_size": (HISTORICAL / name).stat().st_size,
                          "sha256": digest((HISTORICAL / name).read_bytes())} for name in HISTORICAL_NAMES]
    for record in metadata["outputs"]:
        data = (OUTPUTS / record["filename"]).read_bytes()
        check("replay_output_integrity:" + record["filename"],
              len(data) == record["byte_size"] and digest(data) == record["sha256"])
    source_copies = []
    for name in ("applicability_researcher_review_packet_completed.csv", "applicability_researcher_attestation_completed.md"):
        equal = (HISTORICAL / "source_intake" / name).read_bytes() == (inputs / name).read_bytes()
        source_copies.append({"filename": name, "byte_identical": equal})
        check("source_copy:" + name, equal)
    hs = load_jsonl(HISTORICAL / (SCENARIO_NAME + ".jsonl"))
    hc = load_jsonl(HISTORICAL / (CONDITION_NAME + ".jsonl"))
    cs = load_jsonl(OUTPUTS / "scenario_decisions_v2.jsonl")
    cc = load_jsonl(OUTPUTS / "condition_applicability_v2.jsonl")
    hs_projection, cs_projection = scenario_projection(hs), scenario_projection(cs, clean=True)
    hc_projection, cc_projection = condition_projection(hc), condition_projection(cc, clean=True)
    hs_index = indexed(hs_projection, ("scenario_id",))
    cs_index = indexed(cs_projection, ("scenario_id",))
    hc_index = indexed(hc_projection, ("scenario_id", "mode"))
    cc_index = indexed(cc_projection, ("scenario_id", "mode"))
    scenario_mismatches = differences(hs_index, cs_index)
    condition_mismatches = differences(hc_index, cc_index)
    page_mismatches = differences({k: v["material_lad_pages"] for k, v in hs_index.items()},
                                 {k: v["material_lad_pages"] for k, v in cs_index.items()})
    check("62_scenario_decisions", len(hs) == len(cs) == 62 and scenario_mismatches == 0, scenario_mismatches)
    check("558_condition_maps", len(hc) == len(cc) == 558 and condition_mismatches == 0, condition_mismatches)
    check("scenario_material_pages", page_mismatches == 0, page_mismatches)
    hscsv = load_csv(HISTORICAL / (SCENARIO_NAME + ".csv"))
    hscsv_projection = [{"scenario_id": row["scenario_id"],
                        "criteria": {c: boolean(row[c]) for c in (*RESEARCHER, *ALWAYS)},
                        "material_lad_pages": sorted(row["MATERIAL_LAD_PAGES"].split("|"))
                        if row["MATERIAL_LAD_PAGES"] else []} for row in hscsv]
    check("historical_scenario_csv", indexed(hscsv_projection, ("scenario_id",)) == cs_index)
    check("historical_csv_condition_specific_error_handling_scope", all(
        row["ERROR_HANDLING_SCOPE"] == "CONDITION_SPECIFIC_PRESERVED_FROM_V1" for row in hscsv))
    hccsv = load_csv(HISTORICAL / (CONDITION_NAME + ".csv"))
    hccsv_projection = indexed([{"scenario_id": row["scenario_id"], "mode": row["mode"],
                                 "criteria": {c: boolean(row[c]) for c in ALL_CRITERIA}} for row in hccsv],
                               ("scenario_id", "mode"))
    check("historical_condition_csv", hccsv_projection == {
        k: {f: v[f] for f in ("scenario_id", "mode", "criteria")} for k, v in cc_index.items()})
    v1 = load_jsonl(inputs / "condition_applicability_v1.jsonl")
    v1_index = indexed(v1, ("scenario_id", "mode"))
    check("condition_identity_membership", set(v1_index) == set(cc_index) == set(hc_index))
    error_mismatches = sum(v1_index[k]["frozen_applicability_map"]["criteria"]["ERROR_HANDLING"]
                           != row["criteria"]["ERROR_HANDLING"] for k, row in hc_index.items())
    check("error_handling_558_of_558", error_mismatches == 0, error_mismatches)
    check("legacy_v1_criteria_hashes", all(row["frozen_applicability_map"]["applicability_sha256"]
          == digest(canonical(row["frozen_applicability_map"]["criteria"])) for row in v1))
    check("historical_v2_criteria_hashes_and_counts", all(
        row["frozen_applicability_map"]["applicability_sha256"] == digest(canonical(row["frozen_applicability_map"]["criteria"]))
        and row["frozen_applicability_map"]["applicable_primary_count"] == sum(row["frozen_applicability_map"]["criteria"].values())
        and row["v1_applicability_sha256"] == v1_index[(row["scenario_id"], row["mode"])]["frozen_applicability_map"]["applicability_sha256"]
        for row in hc))
    check("historical_condition_metadata_researcher_criteria", all(
        row["source_metadata"]["scenario_level_researcher_criteria"] == cs_index[(row["scenario_id"],)]["criteria"] for row in hc))
    expected_changed = {}
    for key, current in cc_index.items():
        previous = v1_index[key]["frozen_applicability_map"]
        changed = sorted(c for c in ALL_CRITERIA if previous["criteria"][c] != current["criteria"][c])
        if changed:
            expected_changed[key] = {"scenario_id": key[0], "mode": key[1], "changed_criteria": changed,
                                     "v1_applicability_sha256": previous["applicability_sha256"],
                                     "v2_applicability_sha256": digest(canonical(current["criteria"]))}
    check("historical_condition_change_annotations", all(
        sorted(row["changed_criteria_from_v1"]) == expected_changed.get((row["scenario_id"], row["mode"]), {}).get("changed_criteria", [])
        and row["applicability_changed_from_v1"] == ((row["scenario_id"], row["mode"]) in expected_changed)
        and row["error_handling_preserved_from_v1"] is True for row in hc))
    check("historical_condition_csv_derived_fields", all(
        row["applicability_sha256"] == digest(canonical(cc_index[(row["scenario_id"], row["mode"])]["criteria"]))
        and int(row["applicable_primary_count"]) == sum(cc_index[(row["scenario_id"], row["mode"])]["criteria"].values())
        and (sorted(row["changed_criteria_from_v1"].split("|")) if row["changed_criteria_from_v1"] else [])
        == expected_changed.get((row["scenario_id"], row["mode"]), {}).get("changed_criteria", [])
        and boolean(row["applicability_changed_from_v1"]) == ((row["scenario_id"], row["mode"]) in expected_changed) for row in hccsv))
    historical_diff = load_json(HISTORICAL / "c4_real_applicability_v1_v2_diff_audit.json")
    clean_diff = load_json(OUTPUTS / "applicability_v1_v2_diff.json")
    check("historical_diff_condition_records", indexed(normalized_changes(historical_diff["changed_condition_identities"]), ("scenario_id", "mode")) == expected_changed)
    check("cleanroom_diff_condition_records", indexed(clean_diff["changed_conditions"], ("scenario_id", "mode")) == {
        k: {f: v[f] for f in ("scenario_id", "mode", "changed_criteria")} for k, v in expected_changed.items()})
    expected_scenario_diffs = {}
    for key, current in cs_index.items():
        variants = [{c: row["frozen_applicability_map"]["criteria"][c] for c in RESEARCHER}
                    for identity, row in v1_index.items() if identity[0] == key[0]]
        check("v1_scenario_criteria_condition_invariance", len(variants) == 9 and all(v == variants[0] for v in variants))
        old = variants[0]
        new = {c: current["criteria"][c] for c in RESEARCHER}
        changed = sorted(c for c in RESEARCHER if old[c] != new[c])
        expected_scenario_diffs[key] = {"scenario_id": key[0], "v1": old, "v2": new,
                                        "changed": bool(changed), "changed_criteria": changed}
    check("historical_diff_all_scenarios", indexed(normalized_changes(historical_diff["scenario_diffs"]), ("scenario_id",)) == expected_scenario_diffs)
    transitions = {c + "_" + direction: sum(row["v1"][c] == old and row["v2"][c] == new
                                           for row in expected_scenario_diffs.values())
                   for c in RESEARCHER for direction, old, new in (("true_to_false", True, False), ("false_to_true", False, True))}
    check("historical_diff_transition_counts", historical_diff["scenario_transition_counts"] == transitions)
    summary = clean_diff["summary"]
    check("historical_diff_summary", historical_diff["scenarios_with_one_or_more_changes"] == summary["scenarios_with_one_or_more_change"]
          and historical_diff["changed_condition_applicability_maps"] == summary["changed_condition_maps"]
          and historical_diff["unchanged_condition_applicability_maps"] == summary["unchanged_condition_maps"]
          and historical_diff["error_handling_preserved_condition_count"] == summary["error_handling_preserved"]
          and historical_diff["condition_identity_changed_count"] == 0
          and historical_diff["scenario_count"] == 62 and historical_diff["condition_map_count"] == 558)
    receipt = load_json(HISTORICAL / "APPLICABILITY_V2_PRE_OUTCOME_FREEZE_RECEIPT.json")
    distribution = load_json(OUTPUTS / "applicability_distributions.json")
    check("original_receipt_distributions", receipt["decision_distributions"] == {c: distribution[c] for c in RESEARCHER if c != "MULTI_PAGE_COHESIVENESS"}
          and receipt["material_page_count_distribution"] == {"zero": distribution["MATERIAL_LAD_PAGES"]["0"], "one": distribution["MATERIAL_LAD_PAGES"]["1"], "two": distribution["MATERIAL_LAD_PAGES"]["2"]}
          and receipt["multi_page_cohesiveness_distribution"] == distribution["MULTI_PAGE_COHESIVENESS"])
    check("original_receipt_counts", receipt["scenario_count"] == 62 and receipt["condition_map_count"] == 558
          and receipt["error_handling_preserved_condition_count"] == 558
          and receipt["v1_v2_change_counts"] == {"changed_condition_maps": 351, "unchanged_condition_maps": 207,
                                                "scenarios_with_one_or_more_changes": 39, "scenario_transitions": transitions})
    check("original_receipt_artifact_hashes", receipt["decision_map_sha256"] == digest((HISTORICAL / (SCENARIO_NAME + ".jsonl")).read_bytes())
          and receipt["condition_map_sha256"] == digest((HISTORICAL / (CONDITION_NAME + ".jsonl")).read_bytes()))
    hmanifest = load_json(HISTORICAL / "c4_real_j2d2_phase_a_source_manifest_v1.json")
    role_pairs = {"completed_researcher_packet": "completed_researcher_packet", "completed_researcher_attestation": "completed_researcher_attestation",
                  "frozen_blank_packet": "frozen_blank_researcher_packet", "restricted_review_id_mapping": "restricted_opaque_review_id_mapping",
                  "v1_condition_applicability_maps": "v1_condition_identity_error_handling_and_diff_baseline"}
    input_roles = {row["source_role"]: row for row in manifest["inputs"]}
    check("historical_source_manifest_hashes", all(hmanifest["sources"][old]["sha256"] == input_roles[new]["sha256"] for old, new in role_pairs.items()))
    hmap = hmanifest["sources"]["restricted_review_id_mapping"]
    cmap = load_json(OUTPUTS / "mapping_metadata.json")
    check("mapping_metadata", hmap["ignored"] is True and hmap["tracked"] is False
          and hmap["content_included_in_tracked_artifacts"] is False and cmap["opaque_mapping_sha256"] == hmap["sha256"]
          and receipt["source_mapping_sha256"] == hmap["sha256"]
          and cmap["mapping_rows"] == cmap["unique_review_ids"] == cmap["unique_scenarios"] == 62
          and cmap["query_text_matching"] is False and cmap["restricted_pairs_exported"] is False)
    failed = [row for row in checks if not row["passed"]]
    return {
        "schema_version": "RQ3_J2D2_R0_HISTORICAL_COMPARISON_V1",
        "status": "PASS_SCIENTIFIC_CONTENT_EQUAL" if not failed else "FAIL_SCIENTIFIC_CONTENT_MISMATCH",
        "compared_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "comparison_started_after_replay_complete": True, "scientific_content_equality": not failed,
        "scenario_count": 62, "condition_count": 558,
        "decision_mismatch_count": scenario_mismatches, "condition_map_mismatch_count": condition_mismatches,
        "error_handling_mismatch_count": error_mismatches, "scenario_material_page_mismatch_count": page_mismatches,
        "unauthorized_source_difference_count": sum(not item["byte_identical"] for item in source_copies),
        "source_copy_comparisons": source_copies, "original_record_preservation": preservation,
        "historical_artifact_hashes": historical_hashes,
        "canonical_projections": {
            "scenario_decisions": {"historical_sha256": digest(canonical(hs_projection)), "cleanroom_sha256": digest(canonical(cs_projection))},
            "condition_maps": {"historical_sha256": digest(canonical(hc_projection)), "cleanroom_sha256": digest(canonical(cc_projection))}},
        "comparison_method": "Source copies are byte identical. Independently implemented table schemas are compared using full scientific projections; historical criteria hashes, applicability counts and diff annotations are separately recomputed and checked.",
        "normalizations": ["Rows sorted by scenario or scenario/condition identity", "Material LAD page selections and changed-criterion lists treated as sets; order sorted without changing membership", "JSON object-key order and CSV column order normalized", "Three universally applicable criteria expanded in the scenario projection from the explicit task rule"],
        "excluded_administrative_fields": {
            "scenario_jsonl": ["schema_version", "decision_source", "candidate_response_dependency", "judge_or_human_outcome_dependency", "query_page_or_row_position_mapping_used", "researcher_note_status", "review_id_mapping_method", "route_or_mode_dependency"],
            "condition_jsonl": ["schema_version", "freeze_timing", "frozen_applicability_map.schema_version", "frozen_applicability_map.freeze_status", "candidate_response_used_for_decision", "human_rating_or_rationale_accessed", "judge_score_or_rationale_accessed", "mode_outcome_mapping_accessed", "source_metadata.schema_version", "source_metadata.decision_source", "source_metadata.error_handling_source", "source_metadata.mode_dependency", "source_metadata.p3_dependency", "source_metadata.route_dependency"],
            "original_receipt": ["frozen_at_utc", "administrative attestation labels", "historical session access declarations (preserved but qualified by the incident; not used as clean-session evidence)"]},
        "no_scientific_field_excluded": True, "prior_session_zero_score_exposure_claimed": False,
        "checks_passed": len(checks) - len(failed), "checks_failed": len(failed), "checks": checks,
        "phase_b_started": False, "score_bearing_or_response_inputs_read": 0,
    }


if __name__ == "__main__":
    report = compare()
    with open(HERE / "PHASE_A_HISTORICAL_COMPARISON_V1.json", "x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "scientific_content_equality", "checks_passed", "checks_failed", "decision_mismatch_count", "condition_map_mismatch_count", "error_handling_mismatch_count", "scenario_material_page_mismatch_count")}, sort_keys=True))
    raise SystemExit(0 if report["scientific_content_equality"] else 1)
