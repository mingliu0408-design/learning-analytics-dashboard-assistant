#!/usr/bin/env python3
"""Explicit, score-free suites. No repository test discovery or legacy imports.

Usage: python3 -I -B test_phase_a_cleanroom_replay.py pre|certification|package
The package suite runs after the one authorized commit and prints its results;
it does not modify committed files. Input mutation tests use in-memory copies.
"""

import ast
import copy
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


HERE = Path(__file__).resolve().parent
HISTORICAL = HERE.parent / "j2d2_corrected_applicability_freeze"
ZIP_PATH = Path("/Users/liuming/Downloads/RQ3_REAL_J2D2_R0_PHASE_A_CLEANROOM_REPLAY_REVIEW_2026-09-02.zip")
SUPPLEMENT = "APPLICABILITY_V2_CLEANROOM_REPLAY_SUPPLEMENT_V1.json"
AUTHORITY = "APPLICABILITY_V2_PHASE_A_AUTHORITY_RESOLUTION_V1.json"
READY = "READY_FOR_J2D2_PHASE_B_AFTER_SCORE_ISOLATED_PHASE_A_REPLAY"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def load_new_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replay = load_new_module("j2d2_score_free_replay", "phase_a_cleanroom_replay.py")
        cls.manifest = read_json(HERE / "PHASE_A_CLEANROOM_ALLOWED_INPUTS_MANIFEST.json")
        cls.entry = read_json(HERE / "PHASE_A_ENTRY_GATE_V1.json")
        cls.input_dir = Path(cls.manifest["sealed_input_directory"])
        cls.inputs = {name: (cls.input_dir / name).read_bytes() for name in cls.replay.INPUT_SPECS}
        cls.blank = cls.replay.parse_csv(cls.inputs["applicability_researcher_review_packet.csv"], cls.replay.PACKET_FIELDS)
        cls.completed = cls.replay.parse_csv(cls.inputs["applicability_researcher_review_packet_completed.csv"], cls.replay.PACKET_FIELDS)
        cls.mapping = cls.replay.parse_csv(cls.inputs["opaque_review_id_mapping.csv"], cls.replay.MAPPING_FIELDS)
        cls.v1 = cls.replay.parse_v1(cls.inputs["condition_applicability_v1.jsonl"])
        cls.scenarios = cls.replay.freeze_researcher_decisions(cls.blank, cls.completed, cls.mapping)
        cls.conditions = cls.replay.expand_conditions(cls.scenarios, cls.replay.condition_identities(cls.v1))

    def preservation(self, name):
        path = HISTORICAL / name
        expected = self.entry["original_records"][name]
        stat = path.stat()
        self.assertEqual({"sha256": sha(path.read_bytes()), "bytes": stat.st_size,
                          "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}, expected)

    def freeze(self, blank=None, completed=None, mapping=None):
        return self.replay.freeze_researcher_decisions(
            self.blank if blank is None else blank, self.completed if completed is None else completed,
            self.mapping if mapping is None else mapping)


class PreCertificationTests(Fixture):
    def test_01_original_receipt_preserved(self):
        self.preservation("APPLICABILITY_V2_PRE_OUTCOME_FREEZE_RECEIPT.json")

    def test_02_incident_preserved(self):
        self.preservation("PHASE_A_BOUNDARY_INCIDENT_REPORT.md")

    def test_03_pinned_researcher_and_identity_sources(self):
        for item in self.manifest["inputs"]:
            original = Path(item["source_path"]).read_bytes()
            self.assertEqual(sha(original), item["sha256"])
            self.assertEqual(len(original), item["byte_size"])
            self.assertTrue(original == self.inputs[item["cleanroom_filename"]])

    def test_04_exact_physical_allowlist(self):
        self.assertEqual({p.name for p in self.input_dir.iterdir()}, set(self.replay.INPUT_SPECS) | {self.replay.CODE_NAME})
        self.assertEqual({p.name for p in self.input_dir.parent.iterdir()}, {"inputs", "outputs"})
        self.assertTrue(all(p.is_file() and not p.is_symlink() for p in self.input_dir.iterdir()))
        self.assertEqual({p.name for p in (self.input_dir.parent / "outputs").iterdir()}, set(self.replay.OUTPUT_NAMES))

    def test_05_inputs_contain_only_pre_response_fields(self):
        self.assertEqual(set(self.blank[0]), set(self.replay.PACKET_FIELDS))
        self.assertEqual(set(self.completed[0]), set(self.replay.PACKET_FIELDS))
        self.assertEqual(set(self.mapping[0]), set(self.replay.MAPPING_FIELDS))
        self.assertTrue(all(set(r) == self.replay.V1_FIELDS for r in self.v1))
        self.assertTrue(all(r["candidate_response_accessed"] is False and r["gold_accessed"] is False for r in self.v1))
        self.assertEqual(self.manifest["forbidden_input_counts"], {"score_bearing": 0, "candidate_response_content": 0,
                                                                "human_rating_content": 0, "hmac_key": 0})

    def test_06_standalone_standard_library_and_no_environment_access(self):
        tree = ast.parse((HERE / "phase_a_cleanroom_replay.py").read_bytes())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                modules.append(node.module)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                self.assertNotIn(node.attr, {"environ", "getenv", "system", "popen", "execv", "spawnv"})
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "__import__"})
        self.assertEqual(set(modules), {"collections", "csv", "hashlib", "io", "json", "os", "pathlib", "sys"})

    def test_07_exactly_62_unique_review_rows(self):
        self.assertEqual(len(self.blank), 62)
        self.assertEqual(len(self.completed), 62)
        self.assertEqual(len({r["applicability_review_id"] for r in self.completed}), 62)

    def test_08_source_field_change_rejected(self):
        rows = copy.deepcopy(self.completed)
        rows[0]["student_query"] += " altered test input"
        with self.assertRaises(self.replay.ReplayFailure):
            self.freeze(completed=rows)

    def test_09_yes_no_required(self):
        for field in self.replay.DECISION_FIELDS.values():
            rows = copy.deepcopy(self.completed)
            rows[0][field] = "MAYBE"
            with self.assertRaises(self.replay.ReplayFailure):
                self.freeze(completed=rows)

    def test_10_nonempty_distinct_notes_required(self):
        for value in ("  ", self.completed[1]["researcher_notes"]):
            rows = copy.deepcopy(self.completed)
            rows[0]["researcher_notes"] = value
            with self.assertRaises(self.replay.ReplayFailure):
                self.freeze(completed=rows)

    def test_11_material_pages_validated(self):
        for value in ("NotAPage", "Debate|Debate"):
            rows = copy.deepcopy(self.completed)
            rows[0]["researcher_material_lad_pages"] = value
            with self.assertRaises(self.replay.ReplayFailure):
                self.freeze(completed=rows)
        candidates = set(self.blank[0]["pre_response_material_lad_page_candidates"].split("|"))
        outside = sorted(self.replay.PAGES - candidates)
        self.assertTrue(bool(outside))
        rows = copy.deepcopy(self.completed)
        rows[0]["researcher_material_lad_pages"] = outside[0]
        with self.assertRaises(self.replay.ReplayFailure):
            self.freeze(completed=rows)

    def test_12_mapping_completeness_and_uniqueness(self):
        for mapping in (self.mapping[:-1], self.mapping[:-1] + [self.mapping[0]]):
            with self.assertRaises(self.replay.ReplayFailure):
                self.freeze(mapping=mapping)

    def test_13_no_query_text_identity_matching(self):
        blank, completed = copy.deepcopy(self.blank), copy.deepcopy(self.completed)
        for row in blank + completed:
            row["student_query"] = "identical synthetic pre-response query"
            row["current_lad_page"] = "identical synthetic page"
        self.assertEqual(sha(self.replay.jsonl_bytes(self.freeze(blank=blank, completed=completed))),
                         sha(self.replay.jsonl_bytes(self.scenarios)))

    def test_14_row_order_independent_identity_join(self):
        result = self.freeze(blank=list(reversed(self.blank)), completed=self.completed[7:] + self.completed[:7],
                             mapping=list(reversed(self.mapping)))
        self.assertEqual(sha(self.replay.jsonl_bytes(result)), sha(self.replay.jsonl_bytes(self.scenarios)))

    def test_15_v1_decision_flags_cannot_influence_freeze_or_expansion(self):
        altered = copy.deepcopy(self.v1)
        for row in altered:
            for criterion in self.replay.RESEARCHER_CRITERIA:
                row["frozen_applicability_map"]["criteria"][criterion] = not row["frozen_applicability_map"]["criteria"][criterion]
        identities = self.replay.condition_identities(altered)
        result = self.replay.expand_conditions(self.freeze(), identities)
        self.assertEqual(sha(self.replay.jsonl_bytes(result)), sha(self.replay.jsonl_bytes(self.conditions)))

    def test_16_all_researcher_distributions(self):
        self.assertEqual(self.replay.distributions(self.scenarios), self.replay.EXPECTED_DISTRIBUTIONS)

    def test_17_558_condition_expansion_and_membership(self):
        self.assertEqual(len(self.conditions), 558)
        self.assertEqual(len({(r["scenario_id"], r["mode"]) for r in self.conditions}), 558)
        for scenario in self.scenarios:
            self.assertEqual(sum(row["scenario_id"] == scenario["scenario_id"] for row in self.conditions), 9)

    def test_18_error_handling_exact_preservation(self):
        before = {(r["scenario_id"], r["mode"]): r["frozen_applicability_map"]["criteria"]["ERROR_HANDLING"] for r in self.v1}
        self.assertEqual(sum(before[(r["scenario_id"], r["mode"])] == r["criteria"]["ERROR_HANDLING"] for r in self.conditions), 558)

    def test_19_universally_applicable_criteria(self):
        self.assertTrue(all(all(r["criteria"][c] is True for c in ("CLARITY", "CONTEXT_AWARENESS", "RELIABILITY")) for r in self.conditions))

    def test_20_v1_v2_change_counts(self):
        self.assertEqual(self.replay.mechanical_diff(self.v1, self.conditions)["summary"], self.replay.EXPECTED_CHANGES)

    def test_21_unknown_and_missing_fields_fail_closed(self):
        for key in ("unexpected_field", "scenario_id"):
            rows = copy.deepcopy(self.v1)
            if key == "unexpected_field":
                rows[0][key] = "synthetic non-outcome field"
            else:
                del rows[0][key]
            with self.assertRaises(self.replay.ReplayFailure):
                self.replay.parse_v1(self.replay.jsonl_bytes(rows))
        with self.assertRaises(self.replay.ReplayFailure):
            self.replay.parse_csv(b"unexpected_field\nsynthetic\n", self.replay.PACKET_FIELDS)

    def test_22_duplicate_json_key_and_wrong_boolean_rejected(self):
        with self.assertRaises(self.replay.ReplayFailure):
            self.replay.reject_duplicate_json_keys([("same_field", True), ("same_field", False)])
        rows = copy.deepcopy(self.v1)
        rows[0]["frozen_applicability_map"]["criteria"]["CLARITY"] = "true"
        with self.assertRaises(self.replay.ReplayFailure):
            self.replay.parse_v1(self.replay.jsonl_bytes(rows))

    def test_23_duplicate_condition_rejected(self):
        identities = self.replay.condition_identities(self.v1)
        identities[-1] = identities[0]
        with self.assertRaises(self.replay.ReplayFailure):
            self.replay.expand_conditions(self.scenarios, identities)

    def test_24_unexpected_aggregates_fail_closed(self):
        rows = copy.deepcopy(self.scenarios)
        rows[0]["criteria"]["PERSONALISATION"] = not rows[0]["criteria"]["PERSONALISATION"]
        with self.assertRaises(self.replay.ReplayFailure):
            self.replay.distributions(rows)

    def test_25_deterministic_serialization_matches_frozen_outputs(self):
        self.assertEqual(sha(self.replay.jsonl_bytes(self.scenarios)), sha((HERE / "replay_outputs/scenario_decisions_v2.jsonl").read_bytes()))
        self.assertEqual(sha(self.replay.jsonl_bytes(self.conditions)), sha((HERE / "replay_outputs/condition_applicability_v2.jsonl").read_bytes()))
        self.assertEqual(self.replay.json_bytes({"b": True, "a": False}), self.replay.json_bytes({"a": False, "b": True}))
        self.assertEqual(self.replay.csv_bytes(("field",), [{"field": "a,b\nsecond line"}]), b'field\n"a,b\nsecond line"\n')

    def test_26_access_guard_denies_simulated_forbidden_events(self):
        boundary = self.replay.FileBoundary(self.input_dir.parent.resolve())
        # These are direct policy-unit calls; no socket, subprocess or outside
        # file is opened and no real network operation is attempted.
        for event, args in (("socket.connect", ()), ("subprocess.Popen", ()),
                            ("open", (str(self.input_dir.parent.parent / "not_an_input.txt"), "r", os.O_RDONLY))):
            with self.assertRaises(self.replay.ReplayFailure):
                boundary.audit(event, args)

    def test_27_successful_replay_access_audit(self):
        audit = read_json(HERE / "replay_outputs/cleanroom_access_audit.json")
        self.assertEqual(set(audit["read_files"]), set(self.replay.INPUT_SPECS) | {self.replay.CODE_NAME})
        for key in ("unexpected_accesses", "network_calls", "provider_calls", "subprocess_calls", "environment_variable_reads", "repository_module_imports", "score_bearing_inputs", "candidate_response_inputs", "human_rating_inputs", "old_applicability_decision_inputs"):
            self.assertEqual(audit[key], 0)
        self.assertFalse(audit["phase_b_started"])

    def test_28_full_historical_scientific_equality(self):
        comparator = load_new_module("j2d2_score_free_comparison", "compare_phase_a_scientific_content.py")
        report = comparator.compare()
        self.assertTrue(report["scientific_content_equality"])
        self.assertEqual(report["checks_failed"], 0)
        self.assertEqual(report["checks_passed"], 98)

    def test_29_write_once_primitive(self):
        with tempfile.TemporaryDirectory(prefix="rq3_j2d2_r0_score_free_test_") as directory:
            path = Path(directory) / "synthetic_receipt.json"
            self.replay.write_once(path, b'{"synthetic_receipt":true}\n')
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                self.replay.write_once(path, b"replacement forbidden")
            self.assertEqual(path.read_bytes(), before)

    def test_30_restricted_pairs_and_key_absent_from_outputs(self):
        data = b"\n".join((HERE / "replay_outputs" / name).read_bytes() for name in self.replay.OUTPUT_NAMES)
        self.assertTrue(all(row["applicability_review_id"].encode() not in data for row in self.mapping))
        self.assertTrue(self.inputs["opaque_review_id_mapping.csv"] not in data)
        self.assertEqual(self.entry["hmac_key_byte_size"], 32)
        self.assertFalse(self.entry["hmac_key_content_read"])
        self.assertTrue(self.entry["restricted_mapping_and_key_ignored"])

    def test_31_original_receipt_qualification(self):
        report = read_json(HISTORICAL / "ORIGINAL_PHASE_A_RECEIPT_QUALIFICATION_V1.json")
        self.assertEqual(report["original_receipt_status"], "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT")
        self.assertTrue(report["original_receipt_historically_authentic"])
        self.assertTrue(report["boundary_incident_remains_disclosed"])
        self.assertFalse(report["sufficient_by_itself_for_zero_score_exposure_across_prior_assistant_session"])
        self.assertFalse(report["prior_session_zero_score_exposure_claimed"])

    def test_32_aborted_codec_attempt_preserved(self):
        attempts = read_json(HERE / "PHASE_A_REPLAY_ATTEMPTS_V1.json")["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["status"], "FAIL_CLOSED_BEFORE_PACKET_PARSING")
        self.assertEqual(attempts[0]["scientific_outputs_created"], 0)
        self.assertEqual(sha((HERE / "replay_attempts/attempt_001_blocked_code.py").read_bytes()), attempts[0]["code_sha256"])
        self.assertEqual(attempts[1]["status"], "CLEANROOM_REPLAY_COMPLETE")


class CertificationTests(Fixture):
    def test_01_supplement_integrity_and_scope(self):
        receipt = read_json(HISTORICAL / SUPPLEMENT)
        self.assertEqual(receipt["status"], "CLEANROOM_PHASE_A_REPLAY_CERTIFIED")
        self.assertEqual(receipt["scenario_count"], 62)
        self.assertEqual(receipt["condition_count"], 558)
        self.assertTrue(receipt["scientific_content_equality"])
        self.assertEqual(receipt["replay_code_sha256"], sha((HERE / "phase_a_cleanroom_replay.py").read_bytes()))
        self.assertEqual(receipt["cleanroom_allowed_input_manifest_sha256"], sha((HERE / "PHASE_A_CLEANROOM_ALLOWED_INPUTS_MANIFEST.json").read_bytes()))
        for key in ("score_bearing_inputs", "candidate_response_inputs", "human_rating_inputs"):
            self.assertEqual(receipt[key], 0)

    def test_02_actual_supplement_write_once(self):
        path = HISTORICAL / SUPPLEMENT
        before, stat = path.read_bytes(), path.stat()
        receipt = json.loads(before)
        self.assertEqual(receipt["write_count"], 1)
        self.assertFalse(receipt["overwrite_permitted"])
        with self.assertRaises(FileExistsError):
            self.replay.write_once(path, b"test must not overwrite")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(path.stat().st_ctime_ns, stat.st_ctime_ns)

    def test_03_authority_resolution(self):
        authority = read_json(HISTORICAL / AUTHORITY)
        self.assertEqual(authority["final_phase_a_status"], "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT")
        self.assertEqual(authority["supplement_sha256"], sha((HISTORICAL / SUPPLEMENT).read_bytes()))
        self.assertTrue(authority["original_receipt_preserved_and_qualified"])
        self.assertTrue(authority["incident_disclosure_preserved"])
        self.assertTrue(authority["scientific_content_accepted_by_independent_allowlisted_reproduction"])
        self.assertFalse(authority["prior_session_zero_score_exposure_claimed"])
        self.assertFalse(authority["phase_b_started_in_this_task"])

    def test_04_method_disclosure_and_phase_b_chronology(self):
        text = (HISTORICAL / "C4_REAL_PHASE_A_BOUNDARY_REMEDIATION_DISCLOSURE.md").read_text()
        for phrase in ("historical score literals", "predated the incident", "No researcher applicability decision",
                       "physically isolated", "ERROR_HANDLING", "matched", "remains unstarted", "does not erase"):
            self.assertIn(phrase, text)

    def test_05_status_and_zero_phase_b_artifacts(self):
        text = (HERE / "STATUS.md").read_text()
        self.assertIn("RQ3_REAL_J2D2_R0_STATUS = " + READY, text)
        self.assertIn("separate direct user authorization", text)
        self.assertIn("new Codex conversation", text)
        self.assertFalse(any("phase_b" in p.name.lower() or "amendment_packet" in p.name.lower()
                             or "corrected_judge_package" in p.name.lower() for p in HERE.rglob("*") if p.is_file()))
        self.assertFalse(read_json(HISTORICAL / SUPPLEMENT)["phase_b_started"])

    def test_06_final_historical_record_preservation(self):
        self.preservation("APPLICABILITY_V2_PRE_OUTCOME_FREEZE_RECEIPT.json")
        self.preservation("PHASE_A_BOUNDARY_INCIDENT_REPORT.md")

    def test_07_supplement_source_and_output_hashes(self):
        receipt = read_json(HISTORICAL / SUPPLEMENT)
        by_role = {item["source_role"]: item for item in self.manifest["inputs"]}
        for field, role in (("completed_researcher_packet_sha256", "completed_researcher_packet"),
                            ("completed_attestation_sha256", "completed_researcher_attestation"),
                            ("blank_packet_sha256", "frozen_blank_researcher_packet"),
                            ("opaque_mapping_sha256", "restricted_opaque_review_id_mapping")):
            self.assertEqual(receipt[field], by_role[role]["sha256"])
        for item in receipt["cleanroom_output_hashes"]:
            self.assertEqual(item["sha256"], sha((HERE / "replay_outputs" / item["filename"]).read_bytes()))
        for item in receipt["historical_phase_a_artifact_hashes"]:
            self.assertEqual(item["sha256"], sha((HISTORICAL / item["filename"]).read_bytes()))

    def test_08_test_fixtures_are_score_free(self):
        source = (HERE / "test_phase_a_cleanroom_replay.py").read_bytes()
        tree = ast.parse(source)
        forbidden = {"socket", "subprocess", "requests", "openai", "urllib"}
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse(bool(imports & forbidden))
        self.assertEqual(set(self.inputs), set(self.replay.INPUT_SPECS))
        self.assertNotIn(b"test_r3", source)
        self.assertNotIn(b"judge_execution_report", source)

    def test_09_review_allowlist_excludes_restricted_content(self):
        spec = read_json(HERE / "PHASE_A_REVIEW_PACKAGE_ALLOWLIST_V1.json")
        names = [item["archive_name"] for item in spec["entries"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all("restricted_internal/" not in n and not n.endswith(".bin") for n in names))
        self.assertTrue(all(item["content_role"] in spec["allowed_content_roles"] for item in spec["entries"]))
        self.assertTrue(spec["include_raw_inputs"] is False)

    def test_10_zero_execution_actions(self):
        receipt = read_json(HISTORICAL / SUPPLEMENT)
        for count in receipt["prohibited_action_counts"].values():
            self.assertEqual(count, 0)
        self.assertTrue(receipt["requires_new_conversation_and_direct_authorization_for_phase_b"])


class PackageTests(Fixture):
    def test_01_exact_archive_allowlist(self):
        spec = read_json(HERE / "PHASE_A_REVIEW_PACKAGE_ALLOWLIST_V1.json")
        with zipfile.ZipFile(ZIP_PATH) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(item["archive_name"] for item in spec["entries"]))
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))

    def test_02_crc_and_byte_identity(self):
        spec = read_json(HERE / "PHASE_A_REVIEW_PACKAGE_ALLOWLIST_V1.json")
        with zipfile.ZipFile(ZIP_PATH) as archive:
            self.assertIsNone(archive.testzip())
            for item in spec["entries"]:
                self.assertTrue(archive.read(item["archive_name"]) == (HERE.parent.parent.parent / item["source_relative_path"]).read_bytes())

    def test_03_no_restricted_mapping_or_opaque_join_tokens(self):
        with zipfile.ZipFile(ZIP_PATH) as archive:
            data = b"\n".join(archive.read(name) for name in archive.namelist())
            self.assertTrue(all(row["applicability_review_id"].encode() not in data for row in self.mapping))
            self.assertTrue(self.inputs["opaque_review_id_mapping.csv"] not in data)
            self.assertTrue(all("restricted_internal/" not in name and not name.endswith(".bin") for name in archive.namelist()))

    def test_04_only_review_roles_and_no_raw_inputs(self):
        spec = read_json(HERE / "PHASE_A_REVIEW_PACKAGE_ALLOWLIST_V1.json")
        with zipfile.ZipFile(ZIP_PATH) as archive:
            all_data = [archive.read(name) for name in archive.namelist()]
            self.assertTrue(all(payload not in all_data for payload in self.inputs.values()))
            self.assertTrue(all(item["content_role"] in spec["allowed_content_roles"] for item in spec["entries"]))
        self.assertFalse(self.entry["hmac_key_content_read"])


if __name__ == "__main__":
    phases = {"pre": PreCertificationTests, "certification": CertificationTests, "package": PackageTests}
    if len(sys.argv) != 2 or sys.argv[1] not in phases:
        raise SystemExit("Specify exactly one explicit suite: pre, certification, or package")
    phase = sys.argv[1]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(phases[phase])
    names = [test.id().split(".")[-1] for test in suite]
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {"schema_version": "RQ3_J2D2_R0_SCORE_FREE_TEST_RESULTS_V1", "phase": phase,
              "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "tests_run": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "test_names": names, "success": result.wasSuccessful(), "fixture_source_count": 5,
              "fixture_sources": sorted(Fixture.__dict__.get("inputs", {})) or sorted(phases[phase].inputs),
              "score_bearing_fixture_reads": 0, "actual_network_calls": 0, "provider_calls": 0,
              "legacy_test_discovery": False, "simulated_policy_events_are_not_network_calls": True}
    if phase != "package":
        name = "PHASE_A_PRE_CERTIFICATION_TEST_RESULTS_V1.json" if phase == "pre" else "PHASE_A_CERTIFICATION_TEST_RESULTS_V1.json"
        with open(HERE / name, "x", encoding="utf-8") as output:
            output.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    if not result.wasSuccessful():
        print(stream.getvalue(), file=sys.stderr)
    raise SystemExit(0 if result.wasSuccessful() else 1)
