"""Targeted F0 tests. Real controlled sources are accessed only through guard."""
from __future__ import annotations

import ast
import json
import unittest
from collections import Counter

import f0_controlled_access_guard as guard
from f0_blinded_integration import collect, require_blinded_structure
from f0_artifacts import (build_artifacts, REVIEW_FILES, CONDITION_FILE, HUMAN_MATCH_FILE, HUMAN_AUDIT_FILE,
                         JUDGE_JSONL, JUDGE_CSV, JUDGE_REGISTRY, HUMAN_FILES)
from f0_common import HERE, ROOT, RESTRICTED, CRITERIA, FIELDS, KEEP, KEEP_NA, TO_NA, AMEND, canonical, digest, csv_rows, jsonl_rows

DATA = None
ARTIFACTS = None


def ledger_records():
    raw = guard.LEDGER.read_bytes()
    return raw.splitlines(), jsonl_rows(raw)


class F0PreFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global DATA, ARTIFACTS
        if DATA is None:
            guard.install_offline_guard()
            DATA = collect()
        if ARTIFACTS is None:
            ARTIFACTS = build_artifacts(DATA)
        cls.data = DATA
        cls.j = DATA["judges"]
        cls.h = DATA["humans"]
        cls.hh, cls.hl = DATA["human_human"], DATA["human_llm"]
        cls.tracked, cls.restricted = ARTIFACTS
        cls.entry = guard.verify_entry()
        cls.start = json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())
        cls.preservation = json.loads((HERE / "F0_PRECOMPLETION_PRESERVATION_AUDIT_V1.json").read_bytes())
        cls.policy = json.loads((HERE / "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json").read_bytes())

    def test_01_exact_starting_directory_branch_head(self):
        self.assertEqual(self.start["state"]["head"], "9d300c1efd1575005d4673c7cb6297a1bfd6a3ca")
        self.assertEqual(self.start["state"]["pwd"], str(ROOT))
        self.assertEqual(self.start["state"]["branch"], "research/rq3-real-c4-i1-route-integration")

    def test_02_exact_three_retained_untracked_files(self):
        self.assertEqual(len(self.start["retained_untracked_files"]), 3)
        self.assertEqual(self.preservation["retained_untracked_files_unchanged"], 3)
        self.assertTrue(self.start["state"]["status"].splitlines() == self.preservation["untracked_outside_f0"])

    def test_03_four_commits_integrated_in_required_order(self):
        expected = ["5c7f1111c3296f6f6892c5b4d39555ae6835d441", "5b43c44347eeae9e13ed17210b74bbea0c17a237", "0c53592242e9e9505f87da5ee9239f23c92257b3", "df0ae6859cc5731c5004f22947ec25bbe67e73de"]
        self.assertTrue([r["original_commit"] for r in self.entry["integrated_source_commits"]] == expected)
        self.assertTrue(self.preservation["cherry_picked_commits_in_exact_order"] == self.entry["integrated_source_commits"])

    def test_04_original_execution_and_preexisting_files_preserved(self):
        self.assertEqual(self.preservation["integrated_original_files_byte_identical"], 77)
        self.assertTrue(self.preservation["all_preexisting_tracked_files_unchanged"])
        self.assertTrue(self.preservation["restricted_files_unchanged"] > 20)

    def test_05_phase_a_b_all_nine_authority_hashes(self):
        self.assertEqual(len(self.entry["phase_a_and_b_authority_hashes"]), 9)
        self.assertEqual(self.entry["authority_status"], "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT")
        self.assertTrue(self.entry["prior_incident_disclosed"])
        guard.verify_entry()

    def test_06_entry_write_once_and_no_pre_entry_score_access(self):
        self.assertEqual(self.entry["write_count"], 1)
        self.assertFalse(self.entry["overwrite_permitted"])
        self.assertTrue(all(self.entry[k] == 0 for k in ("score_bearing_sources_read_before_receipt", "human_rating_sources_read_before_receipt", "mode_mapping_opened_before_receipt")))

    def test_07_access_chronology_and_hash_chain(self):
        lines, records = ledger_records()
        self.assertTrue(bool(records))
        for index, record in enumerate(records):
            self.assertEqual(record["sequence"], index + 1)
            self.assertEqual(record["entry_receipt_sha256"], guard.ENTRY_SHA256)
            self.assertTrue(record["timestamp_utc"] >= self.entry["frozen_at_utc"])
            self.assertEqual(record["previous_record_sha256"], digest(lines[index - 1]) if index else None)

    def test_08_ledger_contains_metadata_fields_only(self):
        _, records = ledger_records()
        expected = {"schema_version", "event", "timestamp_utc", "entry_receipt_sha256", "source_role", "source_path", "source_sha256", "permitted_use", "projected_field_names", "content_values_recorded", "mode_values_decoded", "sequence", "previous_record_sha256"}
        self.assertTrue(all(set(r) == expected and r["content_values_recorded"] is False and r["mode_values_decoded"] == 0 for r in records))

    def test_09_source_and_pacing_policy_frozen_before_score_access(self):
        for name in ("C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json", "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1.json", "F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json"):
            policy = json.loads((HERE / name).read_bytes())
            self.assertTrue(policy["frozen_at_utc"] <= self.entry["frozen_at_utc"])

    def test_10_pacing_qualified_and_no_strict_wire_claim(self):
        pacing = json.loads((HERE / "C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1.json").read_bytes())
        self.assertEqual(pacing["result_integrity_status"], "PASS")
        self.assertEqual(pacing["pacing_evidence_status"], "QUALIFIED_PACING_EVIDENCE_LIMITATION")
        self.assertFalse(pacing["strict_15_second_wire_send_compliance_claimed"])
        self.assertFalse(pacing["rerun_or_exclusion_solely_for_pacing_evidence_permitted"])

    def test_11_exact_phase_b_retained_result_identities(self):
        actual = {r["logical_judge_request_id"] for r in self.j["results"] if r["source_identity"]["source_role"] == "retained"}
        expected = {r["logical_judge_request_id"] for r in self.policy["retained_existing_sources"]}
        self.assertTrue(actual == expected)
        self.assertEqual(len(actual), 33)

    def test_12_exact_b_c_a_counts(self):
        counts = Counter(r["source_identity"]["source_role"] for r in self.j["results"])
        self.assertTrue(dict(counts) == {"retained": 33, "B": 38, "C": 39, "A_historical": 38, "A_order39": 1})

    def test_13_total_149_unique_request_and_result_ids(self):
        self.assertEqual(len(self.j["results"]), 149)
        self.assertEqual(len({r["logical_judge_request_id"] for r in self.j["results"]}), 149)
        self.assertEqual(len({r["judge_result_blind_id"] for r in self.j["results"]}), 149)

    def test_14_zero_source_overlap_and_excluded_old_results(self):
        keys = {(r["source_identity"]["attempt_journal_path"], r["source_identity"]["source_line"]) for r in self.j["results"]}
        self.assertEqual(len(keys), 149)
        self.assertFalse(set(self.policy["excluded_old_request_ids"]) & {r["logical_judge_request_id"] for r in self.j["results"]})
        self.assertEqual(len(self.policy["excluded_old_request_ids"]), 56)

    def test_15_a_order39_uses_only_execution_output_v2(self):
        rows = [r for r in self.j["results"] if r["source_identity"]["source_role"] == "A_order39"]
        self.assertEqual(len(rows), 1)
        self.assertTrue("/execution_output_v2/" in rows[0]["source_identity"]["attempt_journal_path"])
        self.assertEqual(self.j["requests"][rows[0]["logical_judge_request_id"]]["logical_order"], 39)

    def test_16_retained_raw_attempt_without_terminal_is_disclosed(self):
        self.assertEqual(self.j["retained_without_historical_terminal"], 1)
        audit = json.loads(self.tracked["F0_BLINDED_INTEGRITY_AUDIT_V1.json"])
        self.assertEqual(audit["retained_sources_without_historical_terminal"], 1)
        self.assertEqual(audit["corrected_execution_terminal_coverage"], 116)

    def test_17_four_frozen_terminal_and_parsed_hashes(self):
        self.assertEqual(len(self.j["corrected_source_audit"]), 4)
        self.assertTrue(all(r["integrity_status"] == "PASS" and r["rate_limit_errors"] == 0 for r in self.j["corrected_source_audit"]))
        self.assertTrue({r["terminal_journal_sha256"] for r in self.j["corrected_source_audit"]} == {r["terminal_journal_sha256"] for r in self.entry["judge_source_hashes"]})

    def test_18_each_score_applicability_and_local_mean(self):
        for row in self.j["results"]:
            semantic, flags = row["parsed_semantic_result"], row["frozen_applicability_map"]["criteria"]
            values = []
            for criterion, field in zip(CRITERIA, FIELDS):
                value = semantic[field]
                self.assertTrue(type(value) is int and 1 <= value <= 5 if flags[criterion] else value == "NA")
                if flags[criterion]:
                    values.append(value)
            self.assertTrue(semantic["overall_applicable_mean"] == sum(values) / len(values))

    def test_19_nonempty_judge_rationales_and_auxiliary_domains(self):
        for row in self.j["results"]:
            result = row["parsed_semantic_result"]
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in result["criterion_rationales"].values()))
            self.assertTrue(type(result["evidence_faithfulness"]) is int and 1 <= result["evidence_faithfulness"] <= 5)
            self.assertTrue(type(result["unsupported_claim_count"]) is int and result["unsupported_claim_count"] >= 0)

    def test_20_result_record_hashes_and_model_identity(self):
        sources = {r["logical_judge_request_id"]: r for r in self.j["source_registry"]}
        for row in self.j["results"]:
            self.assertEqual(row["returned_model"], "gpt-4.1-2025-04-14")
            self.assertTrue(digest(canonical(row["parsed_semantic_result"])) == row["semantic_result_sha256"])
            self.assertTrue(digest(canonical(row)) == sources[row["logical_judge_request_id"]]["frozen_record_sha256"])

    def test_21_exact_558_condition_projection_schema(self):
        rows = self.j["condition_projection"]
        self.assertEqual(len(rows), 558)
        self.assertEqual(len({r["opaque_condition_id"] for r in rows}), 558)
        expected = {"opaque_condition_id", "corrected_judge_request_id", "corrected_judge_result_id", "corrected_applicability_map_sha256", "score_record", "source_identity"}
        self.assertTrue(all(set(r) == expected for r in rows))

    def test_22_shared_result_only_equal_payload_hash(self):
        hashes = {}
        for row in self.j["condition_rows"]:
            identity = row["corrected_logical_judge_request_id"]
            hashes.setdefault(identity, set()).add(row["corrected_provider_payload_sha256"])
        self.assertEqual(len(hashes), 149)
        self.assertTrue(all(len(values) == 1 for values in hashes.values()))

    def test_23_csv_projection_does_not_decode_hidden_value_bytes(self):
        raw = b'opaque_id,mode_id,allowed\r\n"x,1",\xff,"a""b"\r\n'
        result = guard.project_csv(raw, ("opaque_id", "allowed"))
        self.assertTrue(result == [{"opaque_id": "x,1", "allowed": 'a"b'}])

    def test_24_json_projection_skips_nested_and_hidden_values(self):
        raw = b'{"mode_id":"\xff","skip":{"nested":["x,}",true]},"allowed":"ok"}'
        self.assertTrue(guard.project_json_object(raw, ("allowed",)) == {"allowed": "ok"})
        with self.assertRaises(RuntimeError):
            guard.project_json_object(b'{"allowed":1,"allowed":2}', ("allowed",))

    def test_25_zero_mode_columns_decoded_and_blinded_record_fields(self):
        _, records = ledger_records()
        self.assertTrue(all(r["mode_values_decoded"] == 0 for r in records))
        for row in self.j["results"]:
            require_blinded_structure(row)
        for rater in "AB":
            for row in self.h["ratings"][rater]:
                require_blinded_structure(row)

    def test_26_all_eight_human_source_hashes_validated(self):
        self.assertEqual(len(self.entry["human_source_hashes"]), 8)
        self.assertTrue(self.entry["human_source_hashes"] == self.start["human_source_hashes"])
        self.assertEqual(self.preservation["human_sources_unchanged"], 8)

    def test_27_each_rater_has_44_unique_items_and_same_set(self):
        sets = [{r["corrected_rating_item_id"] for r in self.h["ratings"][rater]} for rater in "AB"]
        self.assertTrue(sets[0] == sets[1])
        self.assertTrue(all(len(s) == 44 for s in sets))

    def test_28_base_and_amendment_source_fields_and_orders_preserved(self):
        self.assertTrue(self.h["same_item_set"] and self.h["different_orders"])
        self.assertTrue(all(v["visible_source_fields_unchanged"] and v["only_authorized_amendment_fields_changed"] and v["base_order_preserved"] and v["amendment_order_preserved"] for v in self.h["intake_metadata"].values()))

    def test_29_human_transition_counts_270_69_7_6(self):
        expected = {KEEP: 270, KEEP_NA: 69, TO_NA: 7, AMEND: 6}
        self.assertTrue(all(v["transition_counts"] == expected for v in self.h["intake_metadata"].values()))

    def test_30_human_corrected_numeric_na_counts_276_76(self):
        for rows in self.h["ratings"].values():
            values = [v for row in rows for v in row["criterion_scores"].values()]
            self.assertEqual(len(values), 352)
            self.assertEqual(sum(type(v) is int for v in values), 276)
            self.assertEqual(sum(v == "NA" for v in values), 76)

    def test_31_six_amendment_ids_and_only_actionability(self):
        self.assertEqual(len(self.h["amendment_ids"]), 6)
        for rows in self.h["ratings"].values():
            sources = [(field, p) for row in rows for field, p in row["criterion_source_provenance"].items() if p["transition"] == AMEND]
            self.assertEqual(len(sources), 6)
            self.assertTrue(all(field == "actionability" for field, p in sources))
            self.assertTrue({p["amendment_item_id"] for field, p in sources} == set(self.h["amendment_ids"]))

    def test_32_old_scores_preserved_in_14_pair_source_audit(self):
        self.assertEqual(len(self.h["source_audit"]), 14)
        self.assertTrue(all(r["preserved_original_score"] in {"1", "2", "3", "4", "5"} and bool(r["preserved_original_rationale"].strip()) and r["corrected_semantic_value"] == "NA" and not r["source_modified"] for r in self.h["source_audit"]))

    def test_33_signed_attestations_and_accurate_administrative_ai_disclosures(self):
        for rater in "AB":
            a = self.h["intake_metadata"][rater]["attestation"]
            self.assertTrue(a["base_and_amendment_signed"])
            self.assertFalse(a["substantive_ratings_or_rationales_ai_assisted"])
            self.assertTrue("after" in a["amendment_attestation_administrative_ai"])
            self.assertEqual(a["technical_independence_verification"], "NOT_CLAIMED")
        self.assertTrue("No administrative AI use is stated" in self.h["intake_metadata"]["B"]["attestation"]["base_attestation_administrative_ai"])

    def test_34_complete_visible_payload_identity_for_44_human_judge_matches(self):
        self.assertEqual(len(self.h["item_matches"]), 44)
        self.assertTrue(all(r["complete_visible_payload_byte_identical"] for r in self.h["item_matches"]))
        self.assertEqual(len({r["corrected_rating_item_id"] for r in self.h["item_matches"]}), 44)

    def test_35_human_agreement_uses_unique_items_not_108_mappings(self):
        self.assertEqual(self.hh["unique_items"], 44)
        self.assertEqual(self.hh["pooled"]["n"], 276)
        self.assertEqual(self.hl["pooled_human_observations_vs_llm_judge"]["pooled"]["n"], 552)
        self.assertEqual(self.hh["condition_level_duplicates_counted_as_observations"], 0)

    def test_36_agreement_scope_predeclared_no_human_human_mae(self):
        policy = json.loads((HERE / "F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json").read_bytes())
        self.assertTrue(policy["frozen_at_utc"] <= self.entry["frozen_at_utc"])
        self.assertTrue(set(policy["human_human_metrics"]) == {"quadratic_weighted_kappa", "spearman_correlation", "exact_agreement", "within_one_point_agreement"})
        self.assertTrue(all("mean_absolute_score_difference" not in r and "criterion_level_bias_source_b_minus_source_a" not in r for r in [self.hh["pooled"], *self.hh["per_criterion"].values()]))
        self.assertEqual(self.hh["not_computed"]["mean_absolute_score_difference"], "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED")

    def test_37_human_llm_three_predeclared_pairings_and_metric_scope(self):
        for name in ("human_a_vs_llm_judge", "human_b_vs_llm_judge", "pooled_human_observations_vs_llm_judge"):
            result = self.hl[name]
            self.assertIn("mean_absolute_score_difference", result["pooled"])
            self.assertNotIn("criterion_level_bias_source_b_minus_source_a", result["pooled"])
            self.assertTrue(all("criterion_level_bias_source_b_minus_source_a" in v for v in result["per_criterion"].values() if v["n"]))

    def test_38_agreement_denominators_and_disagreement_complements(self):
        for bundle in (self.hh, *(self.hl[k] for k in ("human_a_vs_llm_judge", "human_b_vs_llm_judge", "pooled_human_observations_vs_llm_judge"))):
            self.assertEqual(sum(r["n"] for r in bundle["per_criterion"].values()), bundle["pooled"]["n"])
            for row in [bundle["pooled"], *bundle["per_criterion"].values()]:
                if row["n"]:
                    self.assertEqual(row["disagreement_count"] + row["exact_agreement_numerator"], row["n"])
                    self.assertEqual(row["disagreement_over_one_point_count"] + row["within_one_point_numerator"], row["n"])

    def test_39_canonical_and_historical_usage_partition(self):
        usage = self.data["usage"]
        a, b, c = (usage[k] for k in ("canonical_corrected_results", "noncanonical_returned_outputs", "all_historical_returned_outputs"))
        self.assertEqual(a["observations"], 149)
        self.assertEqual(a["observations"] + b["observations"], c["observations"])
        self.assertTrue(all(a["known_token_totals"][k] + b["known_token_totals"][k] == c["known_token_totals"][k] for k in a["known_token_totals"]))
        self.assertEqual(usage["usage_multiplier_from_condition_mappings"], 1)
        self.assertEqual(len(usage["per_execution"]), 11)

    def test_40_unknown_outcomes_not_results_and_billing_not_imputed(self):
        usage = self.data["usage"]
        self.assertEqual(len(usage["unknown_provider_outcome_attempts"]), 3)
        self.assertEqual(len(usage["recorded_api_rejections_without_result"]), 2)
        self.assertTrue(all(not r["judge_result"] and r["known_token_usage"] is None for r in usage["unknown_provider_outcome_attempts"]))
        self.assertFalse(usage["unknown_usage_imputed"])
        self.assertIsNone(usage["provider_billed_cost"])

    def test_41_zero_provider_rating_modes_system_comparison_and_launches(self):
        audit = json.loads(self.tracked["F0_BLINDED_INTEGRITY_AUDIT_V1.json"])
        zero_fields = ("mode_level_means", "system_comparisons", "final_treatment_effect_statistics", "provider_calls", "network_calls", "judge_executions", "human_rating_actions", "human_amendment_actions", "response_generations", "mode_unblinding", "streamlit_launches", "rag_memory_planning_evidence_p3_rq2_executions")
        self.assertTrue(all(audit[name] == 0 for name in zero_fields))
        self.assertFalse(guard.NETWORK_DENIALS)

    def test_42_controlled_integration_code_has_no_provider_or_network_import(self):
        for name in ("f0_blinded_integration.py", "f0_artifacts.py", "f0_common.py"):
            tree = ast.parse((HERE / name).read_text())
            imports = [alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(set(imports) & {"openai", "httpx", "requests", "socket", "streamlit", "subprocess"})

    def test_43_review_allowlist_excludes_raw_results_and_restricted_artifacts(self):
        denied = {JUDGE_JSONL, JUDGE_CSV, CONDITION_FILE, HUMAN_MATCH_FILE, HUMAN_AUDIT_FILE, "F0_CONTROLLED_ACCESS_LEDGER.jsonl", *(name for names in HUMAN_FILES.values() for name in names.values())}
        self.assertFalse(set(REVIEW_FILES) & denied)
        self.assertTrue(all("restricted_internal/" not in name and not name.endswith(".bin") for name in REVIEW_FILES))
        self.assertEqual(len(REVIEW_FILES), len(set(REVIEW_FILES)))

    def test_44_condition_and_human_mapping_metadata_only_filename_count_hash(self):
        for name in ("c4_real_corrected_condition_result_mapping_metadata_v1.json", "c4_real_human_judge_match_metadata_v1.json", "c4_real_human_source_audit_metadata_v1.json"):
            meta = json.loads(self.tracked[name])
            self.assertEqual(set(meta), {"files"})
            self.assertTrue(all(set(row) == {"filename", "row_count", "sha256"} for row in meta["files"]))


class F0WrittenArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.artifacts = DATA, ARTIFACTS

    def test_45_frozen_judge_jsonl_roundtrip_bytes_and_149_rows(self):
        raw = guard.read_generated(HERE / JUDGE_JSONL, digest(self.artifacts[0][JUDGE_JSONL]), "frozen_judge_result")
        self.assertTrue(raw == self.artifacts[0][JUDGE_JSONL])
        self.assertEqual(len(jsonl_rows(raw)), 149)

    def test_46_frozen_judge_csv_preserves_all_scores_and_rationales(self):
        raw = guard.read_generated(HERE / JUDGE_CSV, digest(self.artifacts[0][JUDGE_CSV]), "frozen_judge_result")
        rows = csv_rows(raw)
        self.assertEqual(len(rows), 149)
        for row, expected in zip(rows, self.data["judges"]["results"]):
            self.assertTrue(all(row[f] == str(expected["parsed_semantic_result"][f]) for f in FIELDS))
            self.assertTrue(json.loads(row["criterion_rationales"]) == expected["parsed_semantic_result"]["criterion_rationales"])

    def test_47_human_jsonl_csv_roundtrip_and_44_items_per_rater(self):
        for rater in "AB":
            for extension, name in HUMAN_FILES[rater].items():
                raw = guard.read_generated(HERE / name, digest(self.artifacts[0][name]), "corrected_human_rating")
                self.assertTrue(raw == self.artifacts[0][name])
                rows = csv_rows(raw) if extension == "csv" else jsonl_rows(raw)
                self.assertEqual(len(rows), 44)

    def test_48_restricted_condition_projection_exact_bytes_and_558_records(self):
        raw = guard.read_generated(RESTRICTED / CONDITION_FILE, digest(self.artifacts[1][CONDITION_FILE]), "restricted_condition_result_projection")
        self.assertTrue(raw == self.artifacts[1][CONDITION_FILE])
        self.assertEqual(len(jsonl_rows(raw)), 558)

    def test_49_restricted_human_matching_and_source_audit_preserved(self):
        for name, count, role in ((HUMAN_MATCH_FILE, 44, "restricted_condition_result_projection"), (HUMAN_AUDIT_FILE, 14, "human_transition_source_audit")):
            raw = guard.read_generated(RESTRICTED / name, digest(self.artifacts[1][name]), role)
            self.assertTrue(raw == self.artifacts[1][name])
            self.assertEqual(len(jsonl_rows(raw)), count)

    def test_50_all_new_metadata_and_reports_byte_identical_to_validated_outputs(self):
        denied = {JUDGE_JSONL, JUDGE_CSV, *(name for names in HUMAN_FILES.values() for name in names.values())}
        for name, raw in self.artifacts[0].items():
            if name not in denied:
                self.assertTrue((HERE / name).read_bytes() == raw)


if __name__ == "__main__":
    guard.install_offline_guard()
    unittest.main()
