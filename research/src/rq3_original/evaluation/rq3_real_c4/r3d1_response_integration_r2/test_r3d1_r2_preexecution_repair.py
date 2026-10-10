#!/usr/bin/env python3
"""Offline regression tests for RQ3 REAL C4 R3D1-R2."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from evaluation.rq3_real_c4.r3d1_response_integration_r2 import (
    build_r3d1_r2_artifacts as build,
)
from evaluation.rq3_real_c4.r3d1_response_integration_r2.judge_execution_runner_v2 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    AUTHORIZATION_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_SCHEMA_VERSION,
    EXPECTED_MODEL,
    RunnerError,
    execute_package,
)
from evaluation.rq3_real_c4.r3d1_response_integration_r2.judge_result_parser_v2 import (
    JudgeResultError,
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    TRANSPORT_SCHEMA_VERSION,
    canonical_json_bytes,
    parse_judge_result,
)
from evaluation.rq3_real_c4.r3d1_response_integration_r2.judge_package_validator_v2 import (
    ALLOWED_FILES,
    sha256_file,
    validate_package_zip,
)
from evaluation.rq3_real_c4.r3d1_response_integration_r2.validate_r3d1_r2_artifacts import (
    load_json,
    validate,
)


HERE = Path(__file__).resolve().parent
PACKAGE_A = (
    build.DOWNLOADS / "C4_REAL_JUDGE_SHARD_A_EXECUTION_PACKAGE_R2_2026-09-02.zip"
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def application_map(count: int) -> dict:
    criteria = {
        criterion: index < count for index, criterion in enumerate(PRIMARY_CRITERIA)
    }
    return {
        "schema_version": "rq3-dimension-applicability-map-v1",
        "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
        "criteria": criteria,
        "applicable_primary_count": count,
        "applicability_sha256": hashlib.sha256(canonical_json_bytes(criteria)).hexdigest(),
    }


def result_for_map(applicability: dict, *, first_score: int = 2) -> str:
    value: dict[str, object] = {}
    rationales: dict[str, str] = {}
    used_first = False
    for criterion, field in SCORE_FIELDS.items():
        if applicability["criteria"][criterion]:
            value[field] = str(first_score if not used_first else 1)
            used_first = True
        else:
            value[field] = "NA"
        rationales[field] = "Offline synthetic parser fixture, not a response rating."
    value.update(
        {
            "evidence_faithfulness": "5",
            "unsupported_claim_count": "9",
            "criterion_rationales": rationales,
            "schema_version": TRANSPORT_SCHEMA_VERSION,
        }
    )
    return json.dumps(value, sort_keys=True)


def extract_request(payload: dict) -> dict:
    content = payload["messages"][0]["content"]
    return json.loads(
        content.split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1].rsplit(
            "\nEND_BLIND_JUDGE_REQUEST_JSON", 1
        )[0]
    )


class MockClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class MockClient:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[bytes] = []
        self.chat = SimpleNamespace(completions=self)
        self.closed = False

    def create(self, **payload: object) -> SimpleNamespace:
        self.calls.append(canonical_json_bytes(payload))
        request = extract_request(payload)  # type: ignore[arg-type]
        outcome = self.outcomes.pop(0) if self.outcomes else result_for_map(
            request["frozen_applicability_map"], first_score=4
        )
        if isinstance(outcome, BaseException):
            raise outcome
        returned_model = EXPECTED_MODEL
        content = str(outcome)
        total_tokens = 15
        if content == "WRONG_MODEL":
            returned_model = "wrong-model"
            content = result_for_map(request["frozen_applicability_map"], first_score=4)
        if content == "BAD_USAGE":
            total_tokens = 16
            content = result_for_map(request["frozen_applicability_map"], first_score=4)
        return SimpleNamespace(
            id=f"mock-{len(self.calls)}",
            model=returned_model,
            system_fingerprint="mock-fingerprint",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=total_tokens,
                prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            ),
        )

    def close(self) -> None:
        self.closed = True


class ProviderFailure(RuntimeError):
    code = "permission_denied"
    param = "model"
    request_id = "req-offline-test"


def mocked_runtime() -> dict:
    return {
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
        "mocked_transport": True,
    }


@contextmanager
def exact_gate(enabled: bool):
    prior = os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE)
    if enabled:
        os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = AUTHORIZATION_ENVIRONMENT_VALUE
    else:
        os.environ.pop(AUTHORIZATION_ENVIRONMENT_VARIABLE, None)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(AUTHORIZATION_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = prior


def write_authorization(path: Path, **changes: object) -> dict:
    package = validate_package_zip(PACKAGE_A)
    value = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": "OFFLINE-REPOSITORY-TEST-AUTHORIZATION",
        "authorized_by": "offline-repository-test",
        "authorized_at_utc": "2026-09-02T00:00:00Z",
        "package_id": package["package_id"],
        "shard_id": package["shard_id"],
        "request_count": package["request_count"],
        "maximum_physical_attempts": package["maximum_physical_attempts"],
        "package_zip_sha256": sha256_file(PACKAGE_A),
        "blinded_judge_manifest_sha256": package["blinded_judge_manifest_sha256"],
        "status": "AUTHORIZED",
    }
    value.update(changes)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return value


class R3D1R2Tests(unittest.TestCase):
    def test_01_independent_artifact_validator(self) -> None:
        result = validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks_passed"], 109)
        self.assertEqual(result["checks_failed"], 0)

    def test_02_parser_exact_means_for_4_5_6_7_8(self) -> None:
        for count in range(4, 9):
            applicability = application_map(count)
            parsed = parse_judge_result(
                result_for_map(applicability),
                applicability,
                expected_judge_result_blind_id="R3B-00000000000000000000",
            )
            self.assertEqual(parsed["overall_applicable_mean"], (count + 1) / count)
            self.assertEqual(parsed["evidence_faithfulness"], 5)
            self.assertEqual(parsed["unsupported_claim_count"], 9)

    def test_03_parser_attaches_id_and_semantic_schema(self) -> None:
        applicability = application_map(6)
        parsed = parse_judge_result(
            result_for_map(applicability),
            applicability,
            expected_judge_result_blind_id="R3B-1234567890ABCDEF1234",
        )
        self.assertEqual(parsed["response_blind_id"], "R3B-1234567890ABCDEF1234")
        self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
        self.assertEqual(
            set(parsed),
            {
                "response_blind_id",
                *SCORE_FIELDS.values(),
                "evidence_faithfulness",
                "unsupported_claim_count",
                "overall_applicable_mean",
                "criterion_rationales",
                "schema_version",
            },
        )

    def test_04_parser_rejects_duplicate_keys_and_extra_local_fields(self) -> None:
        applicability = application_map(4)
        with self.assertRaisesRegex(JudgeResultError, "duplicate JSON key"):
            parse_judge_result(
                '{"clarity":"1","clarity":"2"}',
                applicability,
                expected_judge_result_blind_id="R3B-00000000000000000000",
            )
        value = json.loads(result_for_map(applicability))
        value["overall_applicable_mean"] = "1.25"
        with self.assertRaisesRegex(JudgeResultError, "extra"):
            parse_judge_result(
                value,
                applicability,
                expected_judge_result_blind_id="R3B-00000000000000000000",
            )

    def test_05_parser_enforces_scores_applicability_and_rationales(self) -> None:
        applicability = application_map(4)
        for mutation in ("na_applicable", "score_nonapplicable", "empty_rationale"):
            value = json.loads(result_for_map(applicability))
            if mutation == "na_applicable":
                value[SCORE_FIELDS[PRIMARY_CRITERIA[0]]] = "NA"
            elif mutation == "score_nonapplicable":
                value[SCORE_FIELDS[PRIMARY_CRITERIA[-1]]] = "3"
            else:
                value["criterion_rationales"]["clarity"] = ""
            with self.assertRaises(JudgeResultError):
                parse_judge_result(
                    value,
                    applicability,
                    expected_judge_result_blind_id="R3B-00000000000000000000",
                )

    def test_06_parser_enforces_secondary_types(self) -> None:
        applicability = application_map(5)
        for field, bad in (("evidence_faithfulness", "NA"), ("unsupported_claim_count", "01")):
            value = json.loads(result_for_map(applicability))
            value[field] = bad
            with self.assertRaises(JudgeResultError):
                parse_judge_result(
                    value,
                    applicability,
                    expected_judge_result_blind_id="R3B-00000000000000000000",
                )

    def test_07_packages_have_exact_allowlists_and_counts(self) -> None:
        manifest = load_json(HERE / "c4_real_judge_package_manifest_r2_v1.json")
        for shard in "ABC":
            path = build.DOWNLOADS / manifest["packages"][shard]["file_name"]
            result = validate_package_zip(path)
            self.assertEqual(result["request_count"], 49)
            self.assertEqual(result["regular_file_count"], len(ALLOWED_FILES))
            self.assertEqual(result["maximum_physical_attempts"], 98)

    def test_08_authorization_binding_failure_precedes_output_and_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            write_authorization(auth, request_count=48)
            client = MockClient()
            with exact_gate(True), self.assertRaises(RunnerError):
                execute_package(
                    PACKAGE_A,
                    auth,
                    root / "output",
                    runtime_probe=mocked_runtime,
                    client_factory=lambda: client,
                )
            self.assertFalse((root / "output").exists())
            self.assertEqual(client.calls, [])

    def test_09_environment_gate_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            write_authorization(auth)
            client = MockClient()
            with exact_gate(False), self.assertRaises(RunnerError):
                execute_package(
                    PACKAGE_A,
                    auth,
                    root / "output",
                    runtime_probe=mocked_runtime,
                    client_factory=lambda: client,
                )
            self.assertFalse((root / "output").exists())
            self.assertEqual(client.calls, [])

    def test_10_existing_output_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            output = root / "output"
            output.mkdir()
            write_authorization(auth)
            with exact_gate(True), self.assertRaises(RunnerError):
                execute_package(
                    PACKAGE_A,
                    auth,
                    output,
                    runtime_probe=mocked_runtime,
                    client_factory=MockClient,
                )

    def test_11_preflight_precedes_runtime_and_runtime_failure_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            output = root / "output"
            write_authorization(auth)

            def fail_runtime() -> dict:
                self.assertTrue((output / "JUDGE_PREFLIGHT_START_RECEIPT.json").is_file())
                raise RuntimeError("runtime failure")

            with exact_gate(True), self.assertRaises(RunnerError):
                execute_package(
                    PACKAGE_A,
                    auth,
                    output,
                    runtime_probe=fail_runtime,
                    client_factory=MockClient,
                    utc_now=lambda: "2026-09-02T00:00:00Z",
                )
            status = load_json(output / "JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["judge_calls"], 0)
            self.assertEqual(read_jsonl(output / "JUDGE_ERROR_REGISTRY.jsonl")[0]["phase"], "RUNTIME_VALIDATION")

    def test_12_client_construction_failure_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            output = root / "output"
            write_authorization(auth)

            def fail_client() -> object:
                self.assertTrue((output / "JUDGE_PREFLIGHT_START_RECEIPT.json").is_file())
                raise RuntimeError("client failure")

            with exact_gate(True), self.assertRaises(RunnerError):
                execute_package(
                    PACKAGE_A,
                    auth,
                    output,
                    runtime_probe=mocked_runtime,
                    client_factory=fail_client,
                    utc_now=lambda: "2026-09-02T00:00:00Z",
                )
            status = load_json(output / "JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(read_jsonl(output / "JUDGE_ERROR_REGISTRY.jsonl")[0]["phase"], "CLIENT_CONSTRUCTION")

    def _run(self, root: Path, client: MockClient, name: str) -> tuple[dict, MockClock]:
        auth = root / f"{name}-auth.json"
        write_authorization(auth)
        clock = MockClock()
        with exact_gate(True):
            status = execute_package(
                PACKAGE_A,
                auth,
                root / name,
                runtime_probe=mocked_runtime,
                client_factory=lambda: client,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
                utc_now=lambda: "2026-09-02T00:00:00Z",
            )
        return status, clock

    def test_13_invalid_then_valid_uses_one_identical_retry_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = MockClient(["{"])
            status, clock = self._run(root, client, "retry")
            self.assertEqual(status["status"], "COMPLETE")
            self.assertEqual(status["judge_calls"], 50)
            self.assertEqual(status["valid_terminal_count"], 49)
            self.assertEqual(client.calls[0], client.calls[1])
            self.assertGreaterEqual(clock.value, 48 * 15.0)
            attempts = read_jsonl(root / "retry/JUDGE_ATTEMPT_JOURNAL.jsonl")
            invalid = [row for row in attempts if row.get("failure_code") == "INVALID_JSON"]
            self.assertEqual(len(invalid), 1)
            self.assertEqual(invalid[0]["raw_response_content"], "{")
            terminal = read_jsonl(root / "retry/JUDGE_TERMINAL_JOURNAL.jsonl")
            self.assertEqual(len(terminal), 49)
            self.assertEqual(terminal[0]["prompt_tokens"], 10)
            self.assertEqual(terminal[0]["cached_input_tokens"], 2)
            self.assertEqual(terminal[0]["completion_tokens"], 5)
            self.assertEqual(terminal[0]["total_tokens"], 15)

    def test_14_second_invalid_stops_with_incomplete_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = MockClient(["{", "{"])
            with self.assertRaises(RunnerError):
                self._run(root, client, "second-invalid")
            status = load_json(root / "second-invalid/JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["judge_calls"], 2)
            self.assertTrue(status["continuation_requires_new_direct_authorization"])
            raw = [row.get("raw_response_content") for row in read_jsonl(root / "second-invalid/JUDGE_ATTEMPT_JOURNAL.jsonl")]
            self.assertEqual(raw.count("{"), 2)

    def test_15_nonretryable_provider_error_is_sanitized_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = MockClient([ProviderFailure("Authorization: Bearer SECRET")])
            with self.assertRaises(RunnerError):
                self._run(root, client, "provider-error")
            status = load_json(root / "provider-error/JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["status"], "INCOMPLETE")
            self.assertEqual(status["judge_calls"], 1)
            errors = (root / "provider-error/JUDGE_ERROR_REGISTRY.jsonl").read_text("utf-8")
            self.assertIn("permission_denied", errors)
            self.assertIn("req-offline-test", errors)
            self.assertNotIn("SECRET", errors)

    def test_16_returned_model_mismatch_stops_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = MockClient(["WRONG_MODEL"])
            with self.assertRaises(RunnerError):
                self._run(root, client, "wrong-model")
            status = load_json(root / "wrong-model/JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["judge_calls"], 1)
            self.assertEqual(status["status"], "INCOMPLETE")

    def test_17_usage_arithmetic_mismatch_stops_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = MockClient(["BAD_USAGE"])
            with self.assertRaises(RunnerError):
                self._run(root, client, "bad-usage")
            status = load_json(root / "bad-usage/JUDGE_EXECUTION_STATUS.json")
            self.assertEqual(status["judge_calls"], 1)
            self.assertEqual(status["status"], "INCOMPLETE")

    def test_18_runner_cli_requires_all_four_arguments(self) -> None:
        source = (HERE / "judge_execution_runner_v2.py").read_text("utf-8")
        for flag in ("--package-zip", "--authorization-record", "--output-dir", "--execute"):
            self.assertIn(f'parser.add_argument("{flag}"', source)
        self.assertGreaterEqual(source.count("required=True"), 4)

    def test_19_r1_r2_semantic_equivalence_is_preoutcome(self) -> None:
        audit = load_json(HERE / "c4_real_r3d1_r2_preexecution_audit_v1.json")
        semantic = audit["judge"]["r1_exact_mean_failure"]
        self.assertTrue(semantic["semantic_outputs_identical"])
        self.assertEqual(semantic["synthetic_contract_comparisons"], 147)
        self.assertTrue(semantic["fixture_values_are_not_response_ratings"])

    def test_20_zero_execution_rating_scoring_boundary(self) -> None:
        audit = load_json(HERE / "c4_real_r3d1_r2_preexecution_audit_v1.json")
        self.assertEqual(
            (
                audit["provider_calls"],
                audit["judge_calls"],
                audit["response_quality_scores"],
                audit["human_ratings"],
                audit["streamlit_launches"],
            ),
            (0, 0, 0, 0, 0),
        )

    def test_21_prompt_change_is_confined_to_version_title_and_output_procedure(self) -> None:
        r1 = (
            build.R1 / "../i1_route_integration/c4_real_judge_prompt_v2_provider_compatible.txt"
        ).resolve().read_text("utf-8")
        r2 = (HERE / "c4_real_judge_prompt_r2_provider_compatible.txt").read_text(
            "utf-8"
        )

        def preserved_sections(prompt: str) -> tuple[str, str]:
            before, remainder = prompt.split("OUTPUT PROCEDURE\n\n", 1)
            _output, after = remainder.split("\n\nThe runtime inserts", 1)
            return "\n".join(before.splitlines()[1:]), after

        self.assertEqual(preserved_sections(r1), preserved_sections(r2))

    def test_22_authorization_zip_manifest_and_exact_field_set_bindings(self) -> None:
        mutations = (
            {"package_zip_sha256": "0" * 64},
            {"blinded_judge_manifest_sha256": "1" * 64},
            {"unexpected_field": "forbidden"},
        )
        for index, mutation in enumerate(mutations):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                auth = root / "auth.json"
                write_authorization(auth, **mutation)
                client = MockClient()
                with exact_gate(True), self.assertRaises(RunnerError):
                    execute_package(
                        PACKAGE_A,
                        auth,
                        root / f"output-{index}",
                        runtime_probe=mocked_runtime,
                        client_factory=lambda: client,
                    )
                self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
