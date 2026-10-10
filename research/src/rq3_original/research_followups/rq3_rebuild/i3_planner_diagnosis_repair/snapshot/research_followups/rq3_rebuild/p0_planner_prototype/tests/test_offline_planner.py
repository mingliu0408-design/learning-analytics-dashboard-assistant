"""Synthetic development assertions; never independent Gold or efficacy tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import hashlib
import io
import socket
import subprocess
import unittest
import zipfile

from p0planner.contracts import build_request, canonical
from p0planner.controller import run_planner
from p0planner.providers import MockProvider, ProductionProvider, ProductionTransportDisabled
from p0planner.schema import ROOT, load_schema, schema_errors
from p0planner.validator import validate_candidate, validate_input
from tools.build_fixtures import baseline, build, window
from tools.schema_definitions import schemas
from tools.verify_review_zip import ARCHIVE_ROOT, MANIFEST, verify as verify_zip


def codes(result):
    return {x["code"] for x in result["issues"]}


class FixtureAcceptance(unittest.TestCase):
    pass


def fixture_test(case):
    def test(self):
        sidecar = case["evaluation_only_sidecar"]
        provider = MockProvider(case["mock_candidates"])
        result = run_planner(case["runtime_input"], provider, max_repairs=case["max_repairs"], planning_enabled=case["planning_enabled"])
        self.assertEqual(result["status"], sidecar["expected_status"])
        self.assertTrue(set(sidecar["required_issue_codes"]) <= codes(result["encoded_check_results"]))
        self.assertEqual(schema_errors(result, load_schema("PLANNER_OUTPUT_SCHEMA_DRAFT.json")), [])
        self.assertEqual(result["provider_calls"]["real"], 0)
        self.assertLessEqual(len(provider.requests), 1 + case["max_repairs"])
        for req in provider.requests:
            self.assertEqual(req.payload["runtime_input"], case["runtime_input"])
            self.assertNotIn("evaluation_only_sidecar", req.serialized)
        if result["status"] == "PASSED_ENCODED_CHECKS":
            self.assertIsNotNone(result["plan"])
            self.assertEqual(result["semantic_entailment"], "NOT_CHECKED")
        else:
            self.assertIsNone(result["plan"])
    return test


CASES = json.loads((ROOT / "fixtures/synthetic_cases.json").read_text())["cases"]
for _case in CASES:
    setattr(FixtureAcceptance, "test_" + _case["case_id"], fixture_test(_case))


class ContractAndBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.inp, self.plan = baseline()

    def candidate_codes(self, plan=None):
        return codes(validate_candidate(self.inp, self.plan if plan is None else plan))

    def test_packaged_schema_definitions_match(self):
        for name, schema in schemas().items():
            self.assertEqual(schema, load_schema(name))

    def test_packaged_fixtures_match_declared_builder(self):
        self.assertEqual(CASES, build())

    def test_network_and_dns_blocked(self):
        for operation in (lambda: socket.socket(), lambda: socket.getaddrinfo("example.invalid", 443)):
            with self.assertRaisesRegex(PermissionError, "P0_OFFLINE_GUARD_BLOCKED"):
                operation()

    def test_subprocess_escape_blocked(self):
        with self.assertRaisesRegex(PermissionError, "P0_OFFLINE_GUARD_BLOCKED"):
            subprocess.run(["true"], check=True)

    def test_production_disabled_before_client_construction(self):
        called = []
        with self.assertRaises(ProductionTransportDisabled):
            ProductionProvider(client_factory=lambda: called.append(True))
        self.assertEqual(called, [])

    def test_runtime_gold_sidecars_rejected_at_all_input_depths(self):
        for target in (self.inp, self.inp["scope"], self.inp["hard_constraints"], self.inp["facts"][0]):
            target["expected_fact_ids"] = ["hidden-test-answer"]
            provider = MockProvider([self.plan])
            result = run_planner(self.inp, provider)
            self.assertEqual(result["status"], "INVALID_INPUT")
            self.assertEqual(len(provider.requests), 0)
            self.assertIn("UNEXPECTED_FIELD", codes(result["encoded_check_results"]))
            del target["expected_fact_ids"]

    def test_fields_present_during_proposal_construction(self):
        expected = deepcopy(self.inp)
        plan = deepcopy(self.plan)
        test = self

        class ConstructingMock:
            def propose(self, req):
                # These assertions run before the return object is constructed.
                for key in ("goals", "hard_constraints", "soft_preferences", "completed_tasks", "review_permissions", "active_plan"):
                    test.assertEqual(req.payload["runtime_input"][key], expected[key])
                test.assertEqual(req.payload["runtime_input"], expected)
                return deepcopy(plan)

        result = run_planner(self.inp, ConstructingMock())
        self.assertEqual(result["status"], "PASSED_ENCODED_CHECKS")
        names = [e["event"] for e in result["trace_events"]]
        self.assertLess(names.index("INPUT_SNAPSHOT_FROZEN"), names.index("CANDIDATE_REQUEST_BUILT"))
        self.assertLess(names.index("CANDIDATE_REQUEST_BUILT"), names.index("MOCK_PROVIDER_ENTERED"))
        self.assertLess(names.index("MOCK_PROVIDER_ENTERED"), names.index("MOCK_CANDIDATE_RETURNED"))

    def test_all_runtime_fields_retained_and_request_detached(self):
        req = build_request(self.inp, 0)
        before = req.serialized
        req.payload["runtime_input"]["hard_constraints"]["budget"]["minutes"] = 999
        self.inp["goals"][0]["text"] = "changed externally"
        self.assertEqual(req.serialized, before)
        with self.assertRaises(FrozenInstanceError):
            req.serialized = "{}"

    def test_provider_cannot_mutate_validator_constraints(self):
        inp = self.inp
        plan = deepcopy(self.plan)
        inp["hard_constraints"]["budget"]["minutes"] = 10

        class MutatingMock:
            def propose(self, req):
                req.payload["runtime_input"]["hard_constraints"]["budget"]["minutes"] = 100
                inp["hard_constraints"]["budget"]["minutes"] = 100
                return plan

        result = run_planner(inp, MutatingMock())
        self.assertEqual(result["status"], "BOUNDED_REPAIR_EXHAUSTED")
        self.assertIn("BUDGET_EXCEEDED", codes(result["encoded_check_results"]))

    def test_budget_perturbation_holds_candidate_and_other_input_fixed(self):
        changed = deepcopy(self.inp)
        changed["hard_constraints"]["budget"]["minutes"] = 10
        a, b = MockProvider([self.plan]), MockProvider([self.plan])
        ra, rb = run_planner(self.inp, a), run_planner(changed, b)
        self.assertEqual(ra["status"], "PASSED_ENCODED_CHECKS")
        self.assertEqual(rb["status"], "BOUNDED_REPAIR_EXHAUSTED")
        self.assertIn("BUDGET_EXCEEDED", codes(rb["encoded_check_results"]))
        self.assertNotEqual(a.requests[0].sha256, b.requests[0].sha256)
        self.assertEqual(ra["repair_history"][0]["candidate"], rb["repair_history"][0]["candidate"])
        changed["hard_constraints"]["budget"]["minutes"] = 30
        self.assertEqual(changed, self.inp)

    def test_availability_perturbation_holds_candidate_and_other_input_fixed(self):
        changed = deepcopy(self.inp)
        changed["hard_constraints"]["schedule"]["allowed_windows"] = [window("2026-09-07T10:00:00+02:00", "2026-09-07T11:00:00+02:00")]
        a, b = MockProvider([self.plan]), MockProvider([self.plan])
        ra, rb = run_planner(self.inp, a), run_planner(changed, b)
        self.assertEqual(ra["status"], "PASSED_ENCODED_CHECKS")
        self.assertEqual(rb["status"], "BOUNDED_REPAIR_EXHAUSTED")
        self.assertIn("SCHEDULE_OUTSIDE_ALLOWED_WINDOW", codes(rb["encoded_check_results"]))
        self.assertNotEqual(a.requests[0].sha256, b.requests[0].sha256)
        self.assertEqual(ra["repair_history"][0]["candidate"], rb["repair_history"][0]["candidate"])
        changed["hard_constraints"]["schedule"]["allowed_windows"] = self.inp["hard_constraints"]["schedule"]["allowed_windows"]
        self.assertEqual(changed, self.inp)

    def test_repair_feedback_all_candidates_and_first_pass_retained(self):
        bad = deepcopy(self.plan); bad["actions"][0]["resource_ids"] = ["bad-resource"]
        later = deepcopy(self.plan); later["plan_id"] = "must-not-be-selected"
        provider = MockProvider([bad, self.plan, later])
        result = run_planner(self.inp, provider, max_repairs=2)
        self.assertEqual(result["plan"], self.plan)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(result["provider_calls"], dict(candidate=1, repair=1, real=0))
        repair = provider.requests[1].payload
        self.assertEqual(repair["previous_candidate"], bad)
        self.assertEqual(repair["runtime_input"], self.inp)
        self.assertEqual(repair["feedback"], result["repair_history"][0]["validation"])
        self.assertIn("RESOURCE_NOT_PERMITTED", codes(repair["feedback"]))
        self.assertEqual(len(result["repair_history"]), 2)

    def test_repair_limits_zero_one_two_and_exhaustion(self):
        bad = deepcopy(self.plan); bad["actions"][0]["resource_ids"] = ["bad"]
        for limit in (0, 1, 2):
            provider = MockProvider([bad] * 4)
            result = run_planner(self.inp, provider, max_repairs=limit)
            self.assertEqual(len(provider.requests), limit + 1)
            self.assertEqual(len(result["repair_history"]), limit + 1)
            self.assertEqual(result["status"], "BOUNDED_REPAIR_EXHAUSTED")
        for invalid in (-1, 3, True, 1.0):
            with self.assertRaises(ValueError):
                run_planner(self.inp, MockProvider([]), max_repairs=invalid)

    def test_mock_exhaustion_is_explicit_failure(self):
        result = run_planner(self.inp, MockProvider([]), max_repairs=2)
        self.assertEqual(result["status"], "PROVIDER_FAILURE")
        self.assertEqual(result["provider_calls"]["candidate"], 1)

    def test_invalid_schema_feedback_can_be_repaired(self):
        bad = deepcopy(self.plan); del bad["actions"][0]["completion_check"]
        result = run_planner(self.inp, MockProvider([bad, self.plan]), max_repairs=1)
        self.assertEqual(result["status"], "PASSED_ENCODED_CHECKS")
        self.assertIn("REQUIRED_FIELD", codes(result["repair_history"][0]["validation"]))

    def test_non_finite_values_and_boolean_durations(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, "20", -1, 0):
            p = deepcopy(self.plan); p["actions"][0]["estimated_duration"]["value"] = value
            self.assertNotEqual(validate_candidate(self.inp, p)["outcome"], "PASSED_ENCODED_CHECKS")
            result = run_planner(self.inp, MockProvider([p]))
            self.assertNotEqual(result["status"], "PASSED_ENCODED_CHECKS")
            canonical(result)  # Even invalid Python objects have JSON-safe diagnostics.

    def test_units_are_not_silently_converted(self):
        self.plan["actions"][0]["estimated_duration"]["unit"] = "hours"
        self.assertIn("SCHEMA_CONST", self.candidate_codes())

    def test_exact_decimal_budget_boundary(self):
        self.inp["hard_constraints"]["budget"]["minutes"] = 0.3
        self.plan["actions"][0]["estimated_duration"]["value"] = 0.3
        self.assertEqual(validate_candidate(self.inp, self.plan)["outcome"], "PASSED_ENCODED_CHECKS")
        self.inp["hard_constraints"]["budget"]["minutes"] = 0.299
        self.assertIn("BUDGET_EXCEEDED", self.candidate_codes())

    def test_unknown_budget_not_coerced_to_zero(self):
        self.inp["hard_constraints"]["budget"]["minutes"] = None
        r = validate_candidate(self.inp, self.plan)
        self.assertEqual(r["outcome"], "NEEDS_INFORMATION")
        self.assertIn("BUDGET_UNKNOWN", codes(r))
        self.assertNotIn("BUDGET_EXCEEDED", codes(r))

    def test_invalid_time_and_naive_time_distinguished(self):
        self.plan["actions"][0]["schedule"]["start"] = "2026-09-07T09:00:00"
        self.assertIn("TIMEZONE_OFFSET_MISSING", self.candidate_codes())
        self.plan["actions"][0]["schedule"]["start"] = "invented date"
        self.assertIn("INVALID_TIME", self.candidate_codes())

    def test_unknown_timezone_blocks_scheduling(self):
        self.inp["scope"]["timezone"] = "Unknown/Zone"
        self.assertIn("INVALID_TIMEZONE", self.candidate_codes())

    def test_slot_duration_and_reverse_interval(self):
        self.plan["actions"][0]["schedule"]["end"] = "2026-09-07T09:05:00+02:00"
        self.assertIn("SLOT_SHORTER_THAN_ESTIMATE", self.candidate_codes())
        self.plan["actions"][0]["schedule"]["end"] = "2026-09-07T08:00:00+02:00"
        self.assertIn("INTERVAL_ORDER", self.candidate_codes())

    def test_half_open_intervals_adjacent_exclusion_allowed(self):
        self.inp["hard_constraints"]["schedule"]["excluded_windows"] = [window("2026-09-07T09:20:00+02:00", "2026-09-07T09:30:00+02:00")]
        self.assertEqual(validate_candidate(self.inp, self.plan)["outcome"], "PASSED_ENCODED_CHECKS")

    def test_overlap_rejected_and_explicit_overlap_permission_respected(self):
        p2 = deepcopy(self.plan["actions"][0]); p2.update(step_id="step-2", task_id="task-other")
        self.plan["actions"].append(p2); self.inp["hard_constraints"]["budget"]["minutes"] = 60
        self.assertIn("SCHEDULE_OVERLAP", self.candidate_codes())
        self.inp["hard_constraints"]["schedule"]["non_overlap"] = False
        self.assertEqual(validate_candidate(self.inp, self.plan)["outcome"], "PASSED_ENCODED_CHECKS")

    def test_schedule_dependency_finish_order(self):
        p2 = deepcopy(self.plan["actions"][0]); p2.update(step_id="step-2", task_id="task-other", dependencies=["step-1"])
        self.plan["actions"].append(p2); self.inp["hard_constraints"]["budget"]["minutes"] = 60
        self.inp["hard_constraints"]["schedule"]["non_overlap"] = False
        self.assertIn("SCHEDULE_DEPENDENCY_ORDER", self.candidate_codes())

    def test_dependency_id_and_active_task_cannot_be_deleted(self):
        self.plan["actions"][0]["dependencies"] = ["absent-step"]
        self.assertIn("DEPENDENCY_ID_MISSING", self.candidate_codes())
        self.plan["actions"][0]["task_id"] = "different-task"
        self.assertIn("ACTIVE_TASK_DROPPED", self.candidate_codes())

    def test_unpermitted_review_does_not_evade_repeat_rule(self):
        self.plan["actions"][0].update(kind="REVIEW", task_id="task-read")
        self.assertIn("REVIEW_NOT_AUTHORIZED", self.candidate_codes())

    def test_goal_id_or_goal_text_cannot_be_replaced(self):
        self.plan["goal"] = "different goal"
        self.assertIn("GOAL_BINDING_MISMATCH", self.candidate_codes())

    def test_source_existence_does_not_certify_unsupported_claim(self):
        self.plan["actions"][0]["action"] = "Guaranteed 40 percent grade improvement."
        result = run_planner(self.inp, MockProvider([self.plan]))
        self.assertEqual(result["status"], "PASSED_ENCODED_CHECKS")
        self.assertEqual(result["semantic_entailment"], "NOT_CHECKED")
        self.assertIn("NOT_IMPLEMENTED", {x["status"] for x in result["encoded_check_results"]["checks"]})

    def test_source_access_version_and_observation_time(self):
        for key, val, code in [("access", "DENIED", "SOURCE_ACCESS_DENIED"), ("access", "UNKNOWN", "SOURCE_ACCESS_UNKNOWN"),
                               ("superseded_by", "v2", "SOURCE_VERSION_STALE"), ("observed_at", "2026-09-08T00:00:00+02:00", "SOURCE_FROM_FUTURE")]:
            inp = deepcopy(self.inp); inp["facts"][0]["source_ref"][key] = val
            self.assertIn(code, codes(validate_input(inp)))
        self.inp["source_versions"] = []
        self.assertIn("SOURCE_VERSION_UNKNOWN", self.candidate_codes())

    def test_resource_expiring_before_scheduled_use(self):
        self.inp["resources"][0]["source_ref"]["valid_to"] = "2026-09-07T08:00:00+02:00"
        self.assertIn("RESOURCE_OUTSIDE_USE_VALIDITY", self.candidate_codes())

    def test_required_unknown_information_blocks_before_provider(self):
        self.inp["missing_information"] = [dict(field="goal_scope", required=True, reason="Synthetic course scope unresolved.")]
        provider = MockProvider([self.plan]); result = run_planner(self.inp, provider)
        self.assertEqual(result["status"], "NEEDS_INFORMATION")
        self.assertEqual(provider.requests, [])

    def test_no_slot_claim_requires_explicit_contradiction(self):
        self.inp["hard_constraints"]["budget"]["minutes"] = 1
        result = run_planner(self.inp, MockProvider([self.plan]))
        self.assertEqual(result["status"], "BOUNDED_REPAIR_EXHAUSTED")
        self.assertNotIn("NO_ALLOWED_TIME_EXPLICIT", codes(result["encoded_check_results"]))

    def test_cross_midnight_weekend_uses_local_calendar(self):
        self.inp["hard_constraints"]["schedule"]["allowed_windows"].append(window("2026-09-11T23:50:00+02:00", "2026-09-12T00:30:00+02:00"))
        self.plan["actions"][0]["schedule"] = window("2026-09-11T21:50:00Z", "2026-09-11T22:10:00Z")
        self.assertIn("FORBIDDEN_WEEKDAY", self.candidate_codes())

    def test_horizon_engineering_limit_is_unknown_not_unsat(self):
        self.inp["scope"]["horizon"]["end"] = "2028-09-14T00:00:00+02:00"
        self.assertEqual(validate_input(self.inp)["outcome"], "NEEDS_INFORMATION")
        self.assertIn("HORIZON_NOT_IMPLEMENTED", self.candidate_codes())

    def test_optional_schedule_cannot_be_in_the_past(self):
        self.inp["hard_constraints"]["schedule"]["required"] = False
        self.inp["hard_constraints"]["schedule"]["forbidden_weekdays"] = []
        past = window("2026-09-06T06:00:00+02:00", "2026-09-06T09:00:00+02:00")
        self.inp["scope"]["horizon"] = past
        self.inp["hard_constraints"]["schedule"]["allowed_windows"] = [past]
        self.plan["actions"][0]["schedule"] = past
        self.assertIn("SCHEDULE_BEFORE_AS_OF", self.candidate_codes())

    def test_unknown_duration_origin_blocks_admission(self):
        self.plan["actions"][0]["estimated_duration"]["origin"] = "UNKNOWN"
        self.assertIn("DURATION_UNKNOWN", self.candidate_codes())

    def test_schema_unknown_vocabulary_fails_closed(self):
        with self.assertRaises(ValueError):
            schema_errors({}, {"unknown_schema_keyword": True})


class PackagingVerificationTests(unittest.TestCase):
    def make_zip(self, mutation=None):
        path = ARCHIVE_ROOT + "/synthetic.txt"
        raw = b"synthetic archive verifier test"
        manifest = {"hash_scope": "Every member except OUTPUT_MANIFEST.json; archive bytes are hashed in the external receipt.",
                    "members": [dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())]}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            if mutation == "missing":
                pass
            elif mutation == "symlink":
                info = zipfile.ZipInfo(path); info.create_system = 3; info.external_attr = 0o120777 << 16
                z.writestr(info, raw)
            else:
                z.writestr(path, b"tampered" if mutation == "hash" else raw)
            if mutation == "traversal":
                z.writestr(ARCHIVE_ROOT + "/../escape", b"blocked")
            if mutation == "extra":
                z.writestr(ARCHIVE_ROOT + "/unexpected.txt", b"blocked")
            z.writestr(MANIFEST, json.dumps(manifest))
        buf.seek(0)
        return buf

    def test_valid_manifest_member_hash_and_crc(self):
        self.assertEqual(verify_zip(self.make_zip())["status"], "PASS")

    def test_missing_extra_and_hash_tampering_rejected(self):
        for mutation in ("missing", "extra", "hash"):
            with self.assertRaises(ValueError):
                verify_zip(self.make_zip(mutation))

    def test_traversal_and_symlinks_rejected(self):
        for mutation in ("traversal", "symlink"):
            with self.assertRaises(ValueError):
                verify_zip(self.make_zip(mutation))


if __name__ == "__main__":
    from p0planner.offline_guard import install
    install()
    unittest.main()
