"""Targeted integration checks. Actual controlled sources use the entry guard."""

import copy
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import re
import stat
import subprocess
import sys
import unittest
from zipfile import ZipFile

import phase_b_access_guard as guard
from phase_b_sources import Sources, ROOT, BASE, HERE, PHASE_A, RESTRICTED, KEY_PATH, KEY_COMMITMENT, HUMAN_HASHES, canonical, digest, csv_rows, jsonl_rows
from phase_b_model import historical_judge_eligibility, embedded, RETAIN, REJUDGE, NEW, FAILED, KEEP, KEEP_NA, TO_NA, AMEND, CRITERIA, VISIBLE_FIELDS, JUDGE_DOMAIN, HUMAN_DOMAIN, opaque, human_transition

sys.path.insert(0, str(HERE / "package_support"))
import validate_package as package_validator


def metadata(name):
    return json.loads((HERE / name).read_bytes())


class PhaseBIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = Sources(); cls.data = cls.sources.load()
        cls.history = historical_judge_eligibility(cls.data)
        cls.build = metadata("BUILD_RESULT_METADATA_V1.json")
        cls.impact = metadata("c4_real_judge_result_eligibility_after_applicability_v2.json")
        cls.human_impact = metadata("c4_real_human_applicability_impact_v1.json")
        cls.registry = jsonl_rows((HERE / "c4_real_corrected_judge_request_registry_v1.jsonl").read_bytes())
        cls.restricted_meta = metadata("C4_REAL_PHASE_B_RESTRICTED_MAPPING_METADATA_V1.json")
        cls.restricted = {}
        for record in cls.restricted_meta["files"]:
            raw = guard.read_controlled(RESTRICTED / record["filename"], expected_sha256=record["sha256"],
                                        role="generated_controlled_artifact", permitted_use="targeted_offline_test_inspection")
            cls.restricted[record["filename"]] = csv_rows(raw) if record["filename"].endswith(".csv") else jsonl_rows(raw)
        cls.mapping = cls.restricted["c4_real_condition_to_corrected_judge_request_mapping_r4_v1.csv"]
        cls.corrected = {r["logical_judge_request_id"]: r for r in cls.restricted["c4_real_corrected_judge_unique_payloads_r4_v1.jsonl"]}
        cls.old = {r["logical_judge_request_id"]: r for r in cls.data["requests"]}
        cls.v2 = {(r["scenario_id"], r["mode"]): r["frozen_applicability_map"] for r in cls.data["maps_v2"]}
        cls.judge_packages, cls.human_packages = {}, {}
        for kind, target in (("judge_packages", cls.judge_packages), ("human_packages", cls.human_packages)):
            for shard, record in cls.build[kind].items():
                raw = guard.read_controlled(Path(record["path"]), expected_sha256=record["sha256"], role="generated_controlled_artifact",
                                            permitted_use="targeted_offline_test_inspection")
                with ZipFile(io.BytesIO(raw)) as archive:
                    if archive.testzip() is not None: raise AssertionError("Delivery ZIP CRC failure")
                    target[shard] = {name: archive.read(name) for name in archive.namelist()}
        cls.semantic = cls.restricted["c4_real_corrected_human_semantic_records_v2.jsonl"]

    def test_01_starting_head_and_branch(self):
        entry = guard.verify_entry()
        self.assertEqual(entry["starting_head"], "cc66a6050be995cfdf6e13ca12135d09c20537f9")
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), entry["starting_head"])
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(), entry["branch"])
        self.assertEqual(str(ROOT), entry["working_directory"])

    def test_02_exact_retained_legacy_untracked_files(self):
        entry = guard.verify_entry()
        prefix = str(HERE.relative_to(ROOT)) + "/"
        lines = subprocess.check_output(["git", "status", "--short", "--untracked-files=all"], cwd=ROOT, text=True).splitlines()
        outside = [line for line in lines if not line[3:].startswith(prefix)]
        self.assertEqual(outside, entry["initial_git_status"])
        for record in metadata("PHASE_B_PRESERVATION_BASELINE_V1.json")["retained_legacy_files"]:
            self.assertEqual(digest((ROOT / record["path"]).read_bytes()), record["sha256"])

    def test_03_all_phase_a_authority_hashes_preserved(self):
        entry = guard.verify_entry()
        for folder, values in ((PHASE_A, entry["phase_a_authority_hashes"]),
                               (PHASE_A, entry["accepted_applicability_v2_artifact_hashes"]),
                               (BASE / "j2d2_phase_a_cleanroom_replay", entry["phase_a_cleanroom_hashes"])):
            for name, expected in values.items(): self.assertEqual(digest((folder / name).read_bytes()), expected)

    def test_04_authority_incident_qualification_not_removed(self):
        authority = json.loads(guard.AUTHORITY.read_bytes())
        self.assertEqual(authority["final_phase_a_status"], guard.AUTHORITY_STATUS)
        self.assertEqual(authority["original_receipt_status"], "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT")
        self.assertFalse(authority["phase_b_started_in_this_task"])
        self.assertTrue(authority["incident_disclosure_preserved"])

    def test_05_frozen_v2_population_and_changes(self):
        self.assertEqual(len(self.v2), 558)
        rows = self.data["maps_v2"]
        self.assertEqual(sum(row["applicability_changed_from_v1"] for row in rows), 351)
        self.assertTrue(all(row["error_handling_preserved_from_v1"] for row in rows))

    def test_06_exact_558_condition_mappings(self):
        self.assertEqual(len(self.mapping), 558)
        self.assertEqual(len({r["replay_record_id"] for r in self.mapping}), 558)
        self.assertTrue({(r["scenario_id"], r["mode_id"]) for r in self.mapping} == set(self.v2))

    def test_07_independent_complete_payload_reconstruction_and_dedup(self):
        independently_rebuilt = set()
        for mapping in self.mapping:
            old = self.old[mapping["original_logical_judge_request_id"]]
            expected = copy.deepcopy(old["provider_payload"])
            blind = embedded(old["provider_payload"])
            blind["frozen_applicability_map"] = self.v2[(mapping["scenario_id"], mapping["mode_id"])]
            blind["response_blind_id"] = mapping["corrected_judge_result_blind_id"]
            prompt = self.data["old_packages"]["A"]["JUDGE_PROMPT.txt"].decode()
            expected["messages"][0]["content"] = prompt.replace("{{BLIND_JUDGE_REQUEST_JSON}}", canonical(blind).decode())
            actual = self.corrected[mapping["corrected_logical_judge_request_id"]]
            self.assertTrue(canonical(expected) == canonical(actual["provider_payload"]), "Complete reconstructed payload differs")
            self.assertEqual(digest(canonical(expected)), mapping["corrected_provider_payload_sha256"])
            independently_rebuilt.add(canonical(expected))
        self.assertEqual(len(independently_rebuilt), len(self.corrected))
        self.assertEqual(len(independently_rebuilt), 149)

    def test_08_only_applicability_and_authorized_opaque_label_change(self):
        excluded = {"frozen_applicability_map", "response_blind_id"}
        for mapping in self.mapping:
            old = embedded(self.old[mapping["original_logical_judge_request_id"]]["provider_payload"])
            new = embedded(self.corrected[mapping["corrected_logical_judge_request_id"]]["provider_payload"])
            self.assertTrue({k: v for k, v in old.items() if k not in excluded} == {k: v for k, v in new.items() if k not in excluded})

    def test_09_current_judge_universe_exact(self):
        self.assertEqual(self.history["canonical_counts"], {"A": 1, "B": 49, "C": 39})
        self.assertEqual(len(self.history["canonical"]), 89)

    def test_10_retention_requires_exact_bytes_ids_hashes_and_parser_v3(self):
        retained = [r for r in self.registry if r["eligibility_class"] == RETAIN]
        self.assertEqual(len(retained), 33)
        for row in retained:
            old = self.old[row["logical_judge_request_id"]]
            actual = self.corrected[row["logical_judge_request_id"]]
            self.assertTrue(canonical(old["provider_payload"]) == canonical(actual["provider_payload"]))
            self.assertTrue(canonical(embedded(old["provider_payload"])["frozen_applicability_map"]) == canonical(embedded(actual["provider_payload"])["frozen_applicability_map"]))
            self.assertEqual(old["judge_result_blind_id"], row["judge_result_blind_id"])
            self.assertEqual(old["provider_payload_sha256"], row["provider_payload_sha256"])
            self.assertTrue(self.history["canonical"][row["logical_judge_request_id"]]["parser_v3_passed"])

    def test_11_changed_results_excluded_without_transformation(self):
        dispositions = self.impact["existing_result_dispositions"]
        self.assertEqual(sum(row["corrected_primary_disposition"] == "EXCLUDE_CHANGED_APPLICABILITY_PRESERVE_ORIGINAL" for row in dispositions), 56)
        self.assertTrue(all(row["scores_transformed"] is False for row in dispositions))
        self.assertFalse(self.impact["existing_results_rewritten"])

    def test_12_exact_four_way_classification(self):
        self.assertEqual(self.impact["class_counts"], {RETAIN: 33, REJUDGE: 56, NEW: 59, FAILED: 1})
        self.assertEqual(len(self.registry), 149)
        self.assertTrue(all(row["eligibility_class"] in {RETAIN, REJUDGE, NEW, FAILED} for row in self.registry))

    def test_13_c_order_40_two_outputs_preserved_and_corrected(self):
        identity = self.history["c_order_40_id"]
        self.assertNotIn(identity, self.history["canonical"])
        self.assertEqual(len([r for r in self.history["invalid"] if r["logical_judge_request_id"] == identity]), 2)
        related = [r for r in self.mapping if r["original_logical_judge_request_id"] == identity]
        self.assertTrue(bool(related) and all(r["eligibility_class"] == FAILED for r in related))
        self.assertEqual(len({r["corrected_logical_judge_request_id"] for r in related}), 1)

    def test_14_unattempted_a_c_requests_all_represented(self):
        old_unattempted = set(self.old) - self.history["attempted"]
        self.assertEqual(len(old_unattempted), 57)
        self.assertTrue(all(any(row["original_logical_judge_request_id"] == identity and row["eligibility_class"] == NEW for row in self.mapping) for identity in old_unattempted))
        self.assertEqual(self.impact["original_request_split_count"], 2)

    def test_15_new_ids_only_for_nonretained_requests(self):
        old_results = {r["judge_result_blind_id"] for r in self.old.values()}
        for row in self.registry:
            if row["eligibility_class"] == RETAIN: continue
            self.assertNotIn(row["logical_judge_request_id"], self.old)
            self.assertNotIn(row["judge_result_blind_id"], old_results)
            self.assertEqual(embedded(self.corrected[row["logical_judge_request_id"]]["provider_payload"])["response_blind_id"], row["judge_result_blind_id"])

    def test_16_hmac_domain_identity_reproducibility(self):
        for row in self.registry:
            if row["eligibility_class"] == RETAIN: continue
            payload = copy.deepcopy(self.corrected[row["logical_judge_request_id"]]["provider_payload"])
            blind = embedded(payload); blind["response_blind_id"] = "R3B-" + "0" * 20
            payload["messages"][0]["content"] = self.data["old_packages"]["A"]["JUDGE_PROMPT.txt"].decode().replace("{{BLIND_JUDGE_REQUEST_JSON}}", canonical(blind).decode())
            basis = canonical(payload)
            self.assertEqual(opaque(self.data["key"], JUDGE_DOMAIN, "logical-request-id", basis, "C4J4-", 24), row["logical_judge_request_id"])
            self.assertEqual(opaque(self.data["key"], JUDGE_DOMAIN, "result-blind-id", basis, "R3B-", 20), row["judge_result_blind_id"])

    def test_17_hmac_key_unchanged_0600_ignored_untracked(self):
        self.assertEqual(KEY_PATH.stat().st_size, 32)
        self.assertEqual(stat.S_IMODE(KEY_PATH.stat().st_mode), 0o600)
        self.assertEqual(digest(self.sources.key()), KEY_COMMITMENT)

    def test_18_execution_universe_exact_excludes_retained(self):
        actual = {row["logical_judge_request_id"] for members in self.judge_packages.values() for row in jsonl_rows(members["BLINDED_JUDGE_REQUESTS.jsonl"])}
        expected = {row["logical_judge_request_id"] for row in self.registry if row["eligibility_class"] != RETAIN}
        self.assertTrue(actual == expected)
        self.assertEqual(len(actual), 116)

    def test_19_scenario_family_atomic_shards(self):
        by_scenario = {}
        for mapping in self.mapping:
            record = self.corrected[mapping["corrected_logical_judge_request_id"]]
            if record["eligibility_class"] == RETAIN: continue
            by_scenario.setdefault(mapping["scenario_id"], set()).add(record["shard_id"])
        self.assertTrue(all(len(values) == 1 for values in by_scenario.values()))
        self.assertEqual(metadata("c4_real_corrected_judge_shard_metadata_v1.json")["seed"], 20260902)

    def test_20_shard_counts_token_estimates_and_coverage(self):
        for shard, expected_count, expected_tokens in (("A", 39, 139200), ("B", 38, 139203), ("C", 39, 139204)):
            rows = jsonl_rows(self.judge_packages[shard]["BLINDED_JUDGE_REQUESTS.jsonl"])
            self.assertEqual(len(rows), expected_count)
            estimates = [math.ceil((sum(len(canonical(m)) for m in row["provider_payload"]["messages"]) + len(canonical(row["provider_payload"]["response_format"])) + 16) / 4) for row in rows]
            self.assertEqual(sum(estimates), expected_tokens)
            self.assertEqual(len({embedded(row["provider_payload"])["current_lad_page"] for row in rows}), 5)

    def test_21_package_allowlists_and_all_member_hashes(self):
        for shard, members in self.judge_packages.items():
            self.assertEqual(set(members), set(package_validator.ALLOWED_FILES))
            expected = self.build["judge_packages"][shard]["members"]
            self.assertTrue(all(digest(raw) == expected[name] for name, raw in members.items()))
            self.assertEqual(package_validator.validate_members(members)["status"], "PASS")

    def test_22_prompt_schema_rubric_parser_preserved(self):
        for members in self.judge_packages.values():
            for name in ("JUDGE_PROMPT.txt", "JUDGE_SCHEMA.json", "PRIMARY_RUBRIC.json"):
                self.assertTrue(members[name] == self.data["old_packages"]["A"][name])
            self.assertTrue(members["judge_result_parser_v3.py"] == self.data["support"]["judge_result_parser_v3.py"])

    def test_23_r4_environment_and_timeout_contract(self):
        for members in self.judge_packages.values():
            config = json.loads(members["JUDGE_CONFIGURATION.json"]); contract = json.loads(members["EXECUTION_CONTRACT.json"])
            self.assertEqual(config["request_timeout_seconds"], 120.0)
            self.assertEqual(config["sdk_retries"], 0)
            self.assertEqual(config["minimum_initial_start_interval_seconds"], 15.0)
            self.assertEqual(contract["authorization_environment_value"], "AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4")
            self.assertFalse(contract["execution_authorized"])

    def test_24_no_historical_judge_output_or_identity_in_packages(self):
        raw_outputs = [row["raw_response_content"].encode() for source in self.data["execution_sources"]
                       for row in jsonl_rows(source["files"]["JUDGE_ATTEMPT_JOURNAL.jsonl"]) if row["event"] == "ATTEMPT_RETURNED"]
        old_ids = [value.encode() for record in self.old.values() for value in (record["logical_judge_request_id"], record["judge_result_blind_id"])]
        for members in self.judge_packages.values():
            self.assertTrue(all(not any(value in raw for value in raw_outputs) for raw in members.values()))
            self.assertTrue(all(not any(value in raw for value in old_ids) for raw in members.values()))

    def test_25_human_exact_sources_and_structural_intake(self):
        intake = metadata("c4_real_human_completed_source_intake_v1.json")
        self.assertEqual(intake["status"], "PASS_COMPLETED_HUMAN_BASE_INTAKE")
        self.assertEqual({Path(r["path"]).name: r["sha256"] for r in intake["sources"]}, HUMAN_HASHES)
        for rater in "AB":
            self.assertEqual(intake["raters"][rater]["rows"], 44)
            self.assertTrue(intake["raters"][rater]["attestation_present_and_signed"])
            self.assertTrue(intake["raters"][rater]["visible_source_fields_unchanged"])

    def test_26_attestation_declarations_not_overstated(self):
        intake = metadata("c4_real_human_completed_source_intake_v1.json")
        self.assertIn("later attestation wording", intake["raters"]["A"]["ai_use_declaration"])
        self.assertIn("reference template", intake["raters"]["B"]["ai_use_declaration"])
        self.assertTrue(all(intake["raters"][r]["technical_independence_verification"] == "NOT_CLAIMED" for r in "AB"))

    def test_27_human_108_mappings_44_items_no_splits_merges(self):
        mapping = self.restricted["c4_real_corrected_human_item_to_condition_mapping_v2.jsonl"]
        self.assertEqual(len(mapping), 108)
        self.assertEqual(len({row["corrected_rating_item_id"] for row in mapping}), 44)
        self.assertEqual(self.human_impact["old_item_split_count"], 0)
        self.assertEqual(self.human_impact["old_item_merge_count"], 0)

    def test_28_independent_human_transition_classification(self):
        original = {row["rating_item_id"]: json.loads(row["applicability_flags"]) for row in self.data["human"]["A"]}
        pair_lookup = {(row["corrected_rating_item_id"], row["criterion"]): row for row in self.human_impact["criterion_pair_classifications"]}
        for mapping in self.restricted["c4_real_corrected_human_item_to_condition_mapping_v2.jsonl"]:
            old = original[mapping["original_rating_item_id"]]
            new = self.v2[(mapping["scenario_id"], mapping["mode_id"])]["criteria"]
            for criterion in CRITERIA:
                expected = {(True, True): KEEP, (False, False): KEEP_NA, (True, False): TO_NA, (False, True): AMEND}[(old[criterion], new[criterion])]
                self.assertEqual(pair_lookup[(mapping["corrected_rating_item_id"], criterion)]["classification"], expected)

    def test_29_exact_human_criterion_pair_counts(self):
        self.assertEqual(self.human_impact["criterion_pair_counts"], {KEEP: 270, KEEP_NA: 69, TO_NA: 7, AMEND: 6})
        self.assertEqual(self.human_impact["corrected_criterion_pair_count"], 352)

    def test_30_old_applicable_to_na_no_new_rating(self):
        rows = [row for row in self.semantic if row["classification"] == TO_NA]
        self.assertEqual(len(rows), 14)
        self.assertTrue(all(row["corrected_semantic_value"] == "NA" and row["retained_source_rationale"] is None and not row["new_rating_generated"] for row in rows))

    def test_31_newly_applicable_values_remain_blank(self):
        rows = [row for row in self.semantic if row["classification"] == AMEND]
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row["corrected_semantic_value"] is None and row["retained_source_rationale"] is None for row in rows))

    def test_32_unchanged_human_ratings_preserved_exactly(self):
        original = {(rater, row["rating_item_id"]): row for rater in "AB" for row in self.data["human"][rater]}
        for row in self.semantic:
            if row["classification"] not in {KEEP, KEEP_NA}: continue
            source = original[(row["rater"], row["original_rating_item_id"])]
            self.assertTrue(row["corrected_semantic_value"] == source[row["criterion"].lower() + "_rating"])
            self.assertTrue(row["retained_source_rationale"] == source[row["criterion"].lower() + "_rationale"])

    def test_33_amendment_same_items_different_order_all_blank(self):
        packets = {rater: csv_rows(self.human_packages[rater][f"human_applicability_amendment_packet_{rater}.csv"]) for rater in "AB"}
        ids = {rater: [row["amendment_item_id"] for row in packets[rater]] for rater in "AB"}
        self.assertEqual(len(ids["A"]), 6); self.assertTrue(set(ids["A"]) == set(ids["B"])); self.assertNotEqual(ids["A"], ids["B"])
        self.assertTrue(all(row["amendment_rating"] == row["criterion_specific_rationale"] == "" and row["corrected_applicability"] == "true" for rows in packets.values() for row in rows))

    def test_34_amendments_expose_only_needed_criterion_and_context(self):
        allowed = {"amendment_item_id", *VISIBLE_FIELDS, "newly_applicable_criterion", "criterion_definition", "criterion_anchors_1_to_5", "corrected_applicability", "amendment_rating", "criterion_specific_rationale"}
        source_items = {row["rating_item_id"]: row for row in self.data["human"]["A"]}
        links = self.restricted["c4_real_human_applicability_amendment_to_condition_mapping_r1.jsonl"]
        pair_classes = {(p["corrected_rating_item_id"], p["criterion"]): p["classification"] for p in self.human_impact["criterion_pair_classifications"]}
        definitions = {row["criterion_name"]: row for row in json.loads(self.data["old_packages"]["A"]["PRIMARY_RUBRIC.json"])["criteria"]}
        for rater, members in self.human_packages.items():
            for row in csv_rows(members[f"human_applicability_amendment_packet_{rater}.csv"]):
                self.assertEqual(set(row), allowed)
                matching = [link for link in links if link["amendment_item_id"] == row["amendment_item_id"]]
                self.assertTrue(bool(matching))
                for link in matching:
                    self.assertEqual(pair_classes[(link["corrected_rating_item_id"], link["criterion"])], AMEND)
                    self.assertTrue(all(row[field] == source_items[link["original_rating_item_id"]][field] for field in VISIBLE_FIELDS))
                definition = definitions[row["newly_applicable_criterion"]]
                self.assertEqual(row["criterion_definition"], definition["original_meaning_preserved"])
                self.assertTrue(json.loads(row["criterion_anchors_1_to_5"]) == definition["behavioural_anchors"])

    def test_35_restricted_outputs_ignored_untracked_0600(self):
        for row in self.restricted_meta["files"]:
            path = RESTRICTED / row["filename"]
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT).returncode, 0)
            self.assertFalse(subprocess.check_output(["git", "ls-files", "--", str(path.relative_to(ROOT))], cwd=ROOT).strip())

    def test_36_key_and_restricted_mappings_excluded_from_zips(self):
        for packages in (self.judge_packages, self.human_packages):
            for members in packages.values():
                self.assertTrue(all(self.data["key"] not in raw for raw in members.values()))
                self.assertTrue(all("restricted" not in name.lower() and "mapping" not in name.lower() and "key.bin" not in name.lower() for name in members))

    def test_37_every_manifest_bound_source_remains_unchanged(self):
        for source in self.sources.catalog.values():
            if source["source_role"] == "score_free_source_manifest": raw = Path(source["path"]).read_bytes()
            else: raw = guard.read_controlled(Path(source["path"]), expected_sha256=source["sha256"], role=source["source_role"], permitted_use="immutable_source_integrity_only")
            self.assertEqual(digest(raw), source["sha256"])

    def test_38_entry_receipt_precedes_every_controlled_access(self):
        entry = guard.verify_entry()
        timestamp = datetime.fromisoformat(entry["receipt_created_at_utc"])
        rows = [json.loads(line) for line in guard.LEDGER.read_text().splitlines()]
        self.assertGreater(len(rows), 0)
        previous = None
        for index, row in enumerate(rows, 1):
            self.assertEqual(row["sequence"], index)
            self.assertEqual(row["entry_receipt_sha256"], guard.ENTRY_SHA256)
            self.assertGreaterEqual(datetime.fromisoformat(row["timestamp_utc"]), timestamp)
            self.assertEqual(row["previous_record_sha256"], previous)
            previous = digest(canonical(row))
        self.assertEqual(entry["score_bearing_files_opened_before_receipt"], 0)
        self.assertEqual(entry["candidate_response_files_opened_before_receipt"], 0)

    def test_39_access_ledger_contains_only_metadata(self):
        allowed = {"schema_version", "event", "entry_receipt_sha256", "source_role", "source_path", "source_sha256", "timestamp_utc", "permitted_use", "content_values_recorded", "sequence", "previous_record_sha256"}
        for row in jsonl_rows(guard.LEDGER.read_bytes()):
            self.assertEqual(set(row), allowed)
            self.assertFalse(row["content_values_recorded"])
            self.assertTrue(bool(re.fullmatch("[a-f0-9]{64}", row["source_sha256"])))
        diagnostics = metadata("PHASE_B_DEVELOPMENT_DIAGNOSTICS_V1.json")
        self.assertEqual(diagnostics["blocked_source_location_lookup"]["count"], 1)

    def test_40_zero_evaluation_scoring_agreement_statistics_and_launches(self):
        for field in ("provider_calls", "judge_executions", "human_amendment_ratings", "score_aggregates", "agreement_calculations", "statistical_analyses"):
            self.assertEqual(self.build[field], 0)
        self.assertEqual(self.impact["score_aggregates_computed"], 0)
        self.assertTrue(all(not row["score_aggregate_computed"] for row in self.history["canonical"].values()))
        self.assertFalse(any((HERE / name).exists() for name in ("execution_output_v1", "execution_output_v2")))


if __name__ == "__main__": unittest.main(verbosity=2)
