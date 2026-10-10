"""Mock-only tests for the I0-R1 route-package and execution-integrity repair."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

from evaluation.rq3_real_c4.i0_integration import route_execution_runner_v2 as runner
from evaluation.rq3_real_c4.i0_integration.build_r1_route_packages import (
    AUDIT_FILENAMES,
    DOWNLOADS,
    ORIGINAL_PACKAGE_STATUS,
    PACKAGE_SPECS,
    R1BuildError,
    build_package_bytes,
    read_original_package,
    sha_file,
    verify_frozen_component,
    verify_i0_scientific_tree,
)
from evaluation.rq3_real_c4.i0_integration.route_package_validator_v1 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    AUTHORIZATION_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_FIELDS,
    AUTHORIZATION_SCOPE,
    MODEL,
    REQUESTS_SHA256,
    SCIENTIFIC_MEMBERS,
    PackageValidationError,
    canonical_bytes,
    validate_package_dir,
)
from evaluation.rq3_real_c4.i0_integration.validate_r1_route_packages import (
    validate_all,
)


HERE = Path(__file__).resolve().parents[1]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def output_for(component: str) -> dict[str, bool]:
    if component == "RAG":
        return {"rag_required": True}
    if component == "MEMORY":
        return {"memory_required": False}
    return {
        "rag_required": True,
        "memory_required": False,
        "planning_required": True,
    }


def response_for(
    component: str,
    *,
    content: str | None = None,
    model: str = MODEL,
    refusal: str | None = None,
    input_tokens: int = 10,
    cached_tokens: int | None = 2,
    output_tokens: int = 3,
) -> dict:
    details = None if cached_tokens is None else {"cached_tokens": cached_tokens}
    return {
        "id": "chatcmpl-mocked",
        "model": model,
        "system_fingerprint": "fp_mocked",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": content
                    if content is not None
                    else json.dumps(output_for(component), separators=(",", ":")),
                    "refusal": refusal,
                },
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "prompt_tokens_details": details,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.now_count = 0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.seconds += seconds

    def now(self) -> str:
        self.now_count += 1
        return f"2026-09-01T00:00:{self.now_count:02d}.000Z"


class Transport:
    def __init__(self, component: str, scripted: list[object] | None = None) -> None:
        self.component = component
        self.scripted = list(scripted or [])
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> object:
        self.payloads.append(payload)
        if self.scripted:
            value = self.scripted.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        return response_for(self.component)


class RateLimitError(Exception):
    status_code = 429
    code = "rate_limit"
    param = None


class AuthenticationError(Exception):
    status_code = 401
    code = "invalid_api_key"
    param = None


class R1TestCase(unittest.TestCase):
    def make_package(self, root: Path, component: str) -> Path:
        spec = PACKAGE_SPECS[component]
        verify_frozen_component(component, spec)
        scientific, _ = read_original_package(component, spec)
        archive_bytes, _, _ = build_package_bytes(component, spec, scientific)
        package_dir = root / f"package-{component}"
        package_dir.mkdir()
        with ZipFile(io.BytesIO(archive_bytes)) as archive:
            archive.extractall(package_dir)
        return package_dir

    def make_authorization(self, root: Path, component: str) -> Path:
        plan = json.loads((root / f"package-{component}" / "EXECUTION_PLAN.json").read_text())
        values = {
            "authorization_id": f"MOCK-AUTH-{component}",
            "authorization_scope": AUTHORIZATION_SCOPE,
            "authorized_by": "MOCK_TEST_ONLY",
            "authorized_at": "2026-09-01T00:00:00Z",
            "package_id": plan["package_id"],
            "component": component,
            "logical_call_count": 62,
            "maximum_physical_attempt_count": 124,
            "status": "AUTHORIZED",
        }
        authorization = {field: values[field] for field in AUTHORIZATION_FIELDS}
        path = root / f"authorization-{component}.json"
        path.write_text(json.dumps(authorization, indent=2) + "\n", encoding="utf-8")
        return path

    def run_mock(
        self,
        root: Path,
        component: str,
        transport: Transport,
        *,
        output_name: str = "output",
        clock: FakeClock | None = None,
    ) -> tuple[dict, Path, FakeClock]:
        package = self.make_package(root, component)
        authorization = self.make_authorization(root, component)
        output = root / output_name
        active_clock = clock or FakeClock()
        result = runner.execute_package(
            package_dir=package,
            authorization_record=authorization,
            output_dir=output,
            component=component,
            transport_factory=lambda: transport,
            environment={
                AUTHORIZATION_ENVIRONMENT_VARIABLE: AUTHORIZATION_ENVIRONMENT_VALUE,
                "OPENAI_API_KEY": "mock-only-not-a-real-key",
            },
            now=active_clock.now,
            monotonic=active_clock.monotonic,
            sleep=active_clock.sleep,
        )
        return result, output, active_clock


class FrozenConfigurationTests(R1TestCase):
    def test_actual_committed_component_configurations(self) -> None:
        expected = {"RAG": 32, "MEMORY": 32, "B4_PLANNING": 64}
        for component, tokens in expected.items():
            result = verify_frozen_component(component, PACKAGE_SPECS[component])
            self.assertEqual(result["model"], MODEL)
            self.assertEqual(result["temperature"], 0)
            self.assertEqual(result["max_output_tokens"], tokens)
            self.assertEqual(
                result["verification_status"],
                "PASS_ACTUAL_COMMITTED_FROZEN_CONFIGURATION",
            )

    def test_original_packages_are_exact_and_unexecuted(self) -> None:
        for component, spec in PACKAGE_SPECS.items():
            scientific, audit = read_original_package(component, spec)
            self.assertEqual(sha_file(DOWNLOADS / spec["original_filename"]), spec["original_sha256"])
            self.assertEqual(audit["status"], ORIGINAL_PACKAGE_STATUS)
            self.assertFalse(audit["executed"])
            self.assertEqual(audit["provider_calls"], 0)
            self.assertEqual(sha256(scientific["requests.jsonl"]), REQUESTS_SHA256)

    def test_i0_scientific_tracked_artifacts_match_starting_head(self) -> None:
        rows = verify_i0_scientific_tree()
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row["byte_identical"] for row in rows))

    def test_component_spec_mismatch_fails_before_build(self) -> None:
        invalid = dict(PACKAGE_SPECS["RAG"])
        invalid["max_output_tokens"] = 64
        with self.assertRaisesRegex(R1BuildError, "output-token limit mismatch"):
            verify_frozen_component("RAG", invalid)


class PackageBuilderAndValidatorTests(R1TestCase):
    def test_old_r1_scientific_members_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for component, spec in PACKAGE_SPECS.items():
                scientific, _ = read_original_package(component, spec)
                archive_bytes, plan, _ = build_package_bytes(component, spec, scientific)
                self.assertEqual(plan["max_output_tokens"], spec["max_output_tokens"])
                self.assertEqual(
                    plan["max_output_tokens_source"],
                    "COMPONENT_SPEC_VERIFIED_AGAINST_FROZEN_RQ2_CONFIGURATION",
                )
                path = root / f"{component}.zip"
                path.write_bytes(archive_bytes)
                with ZipFile(path) as archive:
                    self.assertNotIn("ATTEMPT_JOURNAL.jsonl", archive.namelist())
                    self.assertNotIn("TERMINAL_JOURNAL.jsonl", archive.namelist())
                    for name in SCIENTIFIC_MEMBERS:
                        self.assertEqual(archive.read(name), scientific[name])

    def test_package_validator_rejects_plan_token_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.make_package(root, "RAG")
            plan_path = package / "EXECUTION_PLAN.json"
            plan = json.loads(plan_path.read_text())
            plan["max_output_tokens"] = 64
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
            with self.assertRaises(PackageValidationError):
                validate_package_dir(package, expected_component="RAG")

    def test_package_allowlist_request_population_and_zero_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for component in PACKAGE_SPECS:
                package = self.make_package(root, component)
                result = validate_package_dir(package, expected_component=component)
                self.assertEqual(result["logical_call_count"], 62)
                self.assertEqual(result["maximum_physical_attempt_count"], 124)
                self.assertEqual(result["requests_sha256"], REQUESTS_SHA256)
                self.assertEqual(result["member_count"], 10)


class RunnerIntegrityTests(R1TestCase):
    def test_valid_first_attempt_and_usage_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = Transport("RAG")
            result, output, clock = self.run_mock(root, "RAG", transport)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["logical_completed"], 62)
            self.assertEqual(result["physical_attempts"], 62)
            self.assertEqual(result["retry_count"], 0)
            self.assertEqual(len(transport.payloads), 62)
            self.assertTrue(all(payload["max_tokens"] == 32 for payload in transport.payloads))
            self.assertTrue(all(payload["stream"] is False for payload in transport.payloads))
            self.assertTrue(all("tools" not in payload for payload in transport.payloads))
            self.assertEqual(len(clock.sleeps), 61)
            attempts = [
                json.loads(line)
                for line in (output / runner.ATTEMPTS_NAME).read_text().splitlines()
            ]
            initial_intervals = [
                row["initial_start_interval_seconds"]
                for row in attempts
                if row["event"] == "ATTEMPT_COMPLETED"
                and row["attempt_number"] == 1
                and row["initial_start_interval_seconds"] is not None
            ]
            self.assertEqual(initial_intervals, [2.0] * 61)
            usage = json.loads((output / runner.USAGE_NAME).read_text())
            self.assertEqual(usage["input_tokens"], 620)
            self.assertEqual(usage["cached_input_tokens"], 124)
            self.assertEqual(usage["output_tokens"], 186)
            self.assertEqual(usage["total_tokens"], 806)
            self.assertEqual(usage["approximate_cost_usd"], "0.00019530")
            self.assertFalse(usage["routing_accuracy_calculated"])
            self.assertFalse(usage["expected_labels_accessed"])

    def test_invalid_first_output_gets_one_identical_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = Transport(
                "RAG",
                scripted=[
                    response_for("RAG", content="not-json"),
                    response_for("RAG"),
                ],
            )
            result, output, _ = self.run_mock(root, "RAG", transport)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(result["physical_attempts"], 63)
            self.assertEqual(result["retry_count"], 1)
            self.assertEqual(canonical_bytes(transport.payloads[0]), canonical_bytes(transport.payloads[1]))
            errors = [json.loads(line) for line in (output / runner.ERRORS_NAME).read_text().splitlines()]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["error_class"], "INVALID_JSON")
            self.assertFalse(errors[0]["terminal"])

    def test_nonretryable_error_stops_before_later_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = Transport("MEMORY", scripted=[RateLimitError("mock rate limit")])
            result, output, _ = self.run_mock(root, "MEMORY", transport)
            self.assertEqual(result["state"], "INCOMPLETE_STOPPED")
            self.assertEqual(result["stop_reason"], "RATE_LIMIT_ERROR")
            self.assertEqual(result["provider_calls"], 1)
            self.assertEqual(len(transport.payloads), 1)
            self.assertFalse((output / runner.USAGE_NAME).exists())
            terminals = [json.loads(line) for line in (output / runner.TERMINALS_NAME).read_text().splitlines()]
            self.assertEqual(len(terminals), 1)
            self.assertEqual(terminals[0]["scenario_id"], "U001")

    def test_returned_model_mismatch_stops_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = Transport(
                "B4_PLANNING",
                scripted=[response_for("B4_PLANNING", model="gpt-4o-mini")],
            )
            result, _, _ = self.run_mock(root, "B4_PLANNING", transport)
            self.assertEqual(result["state"], "INCOMPLETE_STOPPED")
            self.assertEqual(result["stop_reason"], "RETURNED_MODEL_MISMATCH")
            self.assertEqual(result["provider_calls"], 1)

    def test_secret_redaction_and_no_environment_dump(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = "sk-" + "proj-" + "THISISNOTAREALKEY123456789"
            transport = Transport(
                "RAG", scripted=[AuthenticationError(f"bad Authorization: Bearer {secret}")]
            )
            result, output, _ = self.run_mock(root, "RAG", transport)
            self.assertEqual(result["stop_reason"], "AUTHENTICATION_ERROR")
            all_output = b"".join(path.read_bytes() for path in output.iterdir())
            self.assertNotIn(secret.encode(), all_output)
            self.assertIn(b"REDACTED", all_output)
            errors = [json.loads(line) for line in (output / runner.ERRORS_NAME).read_text().splitlines()]
            self.assertFalse(errors[0]["sanitized_provider_error"]["headers_recorded"])
            self.assertFalse(errors[0]["sanitized_provider_error"]["environment_recorded"])

    def test_output_directory_is_exclusive_and_no_resume_occurs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_transport = Transport("RAG")
            result, output, clock = self.run_mock(root, "RAG", first_transport)
            self.assertEqual(result["state"], "COMPLETED")
            plan_dir = root / "package-RAG"
            authorization = root / "authorization-RAG.json"
            factory_calls = 0

            def factory() -> Transport:
                nonlocal factory_calls
                factory_calls += 1
                return Transport("RAG")

            with self.assertRaisesRegex(runner.ExecutionBoundaryError, "already exists"):
                runner.execute_package(
                    package_dir=plan_dir,
                    authorization_record=authorization,
                    output_dir=output,
                    component="RAG",
                    transport_factory=factory,
                    environment={
                        AUTHORIZATION_ENVIRONMENT_VARIABLE: AUTHORIZATION_ENVIRONMENT_VALUE,
                        "OPENAI_API_KEY": "mock-only-not-a-real-key",
                    },
                    now=clock.now,
                    monotonic=clock.monotonic,
                    sleep=clock.sleep,
                )
            self.assertEqual(factory_calls, 0)
            status = json.loads((output / runner.STATUS_NAME).read_text())
            self.assertFalse(status["automatic_resume_permitted"])

    def test_output_directory_cannot_be_inside_extracted_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.make_package(root, "RAG")
            authorization = self.make_authorization(root, "RAG")
            factory_calls = 0

            def factory() -> Transport:
                nonlocal factory_calls
                factory_calls += 1
                return Transport("RAG")

            with self.assertRaisesRegex(
                runner.ExecutionBoundaryError, "external to the extracted package"
            ):
                runner.execute_package(
                    package_dir=package,
                    authorization_record=authorization,
                    output_dir=package / "execution-output",
                    component="RAG",
                    transport_factory=factory,
                    environment={
                        AUTHORIZATION_ENVIRONMENT_VARIABLE: AUTHORIZATION_ENVIRONMENT_VALUE,
                        "OPENAI_API_KEY": "mock-only-not-a-real-key",
                    },
                )
            self.assertEqual(factory_calls, 0)
            self.assertFalse((package / "execution-output").exists())

    def test_preflight_and_attempt_reservation_are_durable_before_mock_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.make_package(root, "RAG")
            authorization = self.make_authorization(root, "RAG")
            output = root / "observed-output"
            clock = FakeClock()
            observations = []

            def call(payload: dict) -> dict:
                self.assertTrue((output / runner.PREFLIGHT_NAME).is_file())
                rows = [json.loads(line) for line in (output / runner.ATTEMPTS_NAME).read_text().splitlines()]
                self.assertEqual(rows[-1]["event"], "ATTEMPT_RESERVED")
                observations.append(rows[-1]["scenario_id"])
                return response_for("RAG")

            original_fsync = os.fsync
            with mock.patch.object(runner.os, "fsync", side_effect=original_fsync) as fsync_mock:
                result = runner.execute_package(
                    package_dir=package,
                    authorization_record=authorization,
                    output_dir=output,
                    component="RAG",
                    transport_factory=lambda: call,
                    environment={
                        AUTHORIZATION_ENVIRONMENT_VARIABLE: AUTHORIZATION_ENVIRONMENT_VALUE,
                        "OPENAI_API_KEY": "mock-only-not-a-real-key",
                    },
                    now=clock.now,
                    monotonic=clock.monotonic,
                    sleep=clock.sleep,
                )
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(observations, [f"U{number:03d}" for number in range(1, 63)])
            self.assertGreater(fsync_mock.call_count, 300)

    def test_no_network_is_available_to_mocked_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transport = Transport("MEMORY")
            with mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
                result, _, _ = self.run_mock(root, "MEMORY", transport)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(len(transport.payloads), 62)

    def test_strict_parser_never_coerces_or_repairs(self) -> None:
        schema = {
            "type": "object",
            "properties": {"rag_required": {"type": "boolean"}},
            "required": ["rag_required"],
            "additionalProperties": False,
        }
        self.assertEqual(runner.strict_parse('{"rag_required":true}', schema)[1], "PASS")
        self.assertEqual(
            runner.strict_parse('{"rag_required":"true"}', schema)[1],
            "STRICT_SCHEMA_VALIDATION_FAILED",
        )
        self.assertEqual(runner.strict_parse("prefix {\"rag_required\":true}", schema)[1], "INVALID_JSON")


class PublishedR1ArtifactTests(unittest.TestCase):
    def test_published_packages_and_audits(self) -> None:
        result = validate_all(DOWNLOADS)
        self.assertEqual(result["status"], "PASS_ALL_R1_PACKAGES_AND_SCIENTIFIC_IDENTITIES")
        self.assertEqual(len(result["packages"]), 3)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["route_executions"], 0)
        for filename in AUDIT_FILENAMES.values():
            self.assertTrue((HERE / filename).is_file())
        supersession = json.loads(
            (HERE / AUDIT_FILENAMES["supersession"]).read_text()
        )
        self.assertEqual(supersession["status"], ORIGINAL_PACKAGE_STATUS)
        self.assertEqual(supersession["packages_executed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
