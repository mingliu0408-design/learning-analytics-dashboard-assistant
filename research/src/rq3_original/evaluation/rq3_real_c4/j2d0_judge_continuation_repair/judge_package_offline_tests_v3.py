#!/usr/bin/env python3
"""Offline and mocked-transport tests embedded in every continuation Package."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from judge_execution_runner_v3 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    AUTHORIZATION_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_SCHEMA_VERSION,
    EXPECTED_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    RunnerError,
    execute_package,
    sanitized_error,
)
from judge_result_parser_v3 import (
    JudgeResultError,
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    TRANSPORT_SCHEMA_VERSION,
    canonical_json_bytes,
    parse_judge_result,
)
from validate_package import (
    ALLOWED_FILES,
    sha256_file,
    validate_package_dir,
    validate_package_zip,
)


PACKAGE_DIR = Path(__file__).resolve().parent


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def first_request() -> tuple[dict, dict]:
    row = json.loads(
        next(
            line
            for line in (PACKAGE_DIR / "BLINDED_JUDGE_REQUESTS.jsonl")
            .read_text("utf-8")
            .splitlines()
            if line
        )
    )
    content = row["provider_payload"]["messages"][0]["content"]
    request = json.loads(
        content.split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1].rsplit(
            "\nEND_BLIND_JUDGE_REQUEST_JSON", 1
        )[0]
    )
    return row, request


def applicability(count: int) -> dict:
    criteria = {
        criterion: index < count for index, criterion in enumerate(PRIMARY_CRITERIA)
    }
    digest = hashlib.sha256(canonical_json_bytes(criteria)).hexdigest()
    return {
        "schema_version": "rq3-dimension-applicability-map-v1",
        "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
        "criteria": criteria,
        "applicable_primary_count": count,
        "applicability_sha256": digest,
    }


def valid_provider_result(request: dict, *, nonuniform: bool = False) -> str:
    scores: dict[str, str] = {}
    rationales: dict[str, str] = {}
    used_special = False
    for criterion, field in SCORE_FIELDS.items():
        if request["frozen_applicability_map"]["criteria"][criterion]:
            if nonuniform and not used_special:
                scores[field] = "2"
                used_special = True
            else:
                scores[field] = "1" if nonuniform else "4"
        else:
            scores[field] = "NA"
        rationales[field] = "Offline mocked-transport criterion rationale."
    return json.dumps(
        {
            **scores,
            "evidence_faithfulness": "4",
            "unsupported_claim_count": "0",
            "criterion_rationales": rationales,
            "schema_version": TRANSPORT_SCHEMA_VERSION,
        },
        sort_keys=True,
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
    def __init__(
        self,
        outcomes: list[object] | None = None,
        *,
        max_retries: int = 0,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[bytes] = []
        self.closed = False
        self.max_retries = max_retries
        self.timeout = SimpleNamespace(
            connect=timeout,
            read=timeout,
            write=timeout,
            pool=timeout,
        )
        self.chat = SimpleNamespace(completions=self)

    def create(self, **payload: object) -> SimpleNamespace:
        frozen = canonical_json_bytes(payload)
        self.calls.append(frozen)
        request = json.loads(
            payload["messages"][0]["content"]  # type: ignore[index]
            .split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1]
            .rsplit("\nEND_BLIND_JUDGE_REQUEST_JSON", 1)[0]
        )
        outcome = self.outcomes.pop(0) if self.outcomes else valid_provider_result(request)
        if isinstance(outcome, BaseException):
            raise outcome
        content = str(outcome)
        returned_model = EXPECTED_MODEL
        if content == "__WRONG_MODEL__":
            content = valid_provider_result(request)
            returned_model = "wrong-model"
        return SimpleNamespace(
            id=f"mock-response-{len(self.calls)}",
            model=returned_model,
            system_fingerprint="mock-fingerprint",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            ),
        )

    def close(self) -> None:
        self.closed = True


class MockProviderError(RuntimeError):
    code = "rate_limit_exceeded"
    param = "messages"
    request_id = "req-mock-123"


def fake_runtime() -> dict:
    return {
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
        "mocked_transport": True,
    }


@contextmanager
def authorization_gate():
    previous = os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE)
    os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = AUTHORIZATION_ENVIRONMENT_VALUE
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(AUTHORIZATION_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = previous


def create_package_zip(target: Path) -> None:
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for name in sorted(ALLOWED_FILES):
            archive.write(PACKAGE_DIR / name, name)


def write_authorization(package_zip: Path, target: Path, **changes: object) -> dict:
    package = validate_package_zip(package_zip)
    value = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": "MOCK-OFFLINE-AUTHORIZATION",
        "authorized_by": "offline-test-fixture",
        "authorized_at_utc": "2026-09-02T00:00:00Z",
        "package_id": package["package_id"],
        "shard_id": package["shard_id"],
        "request_count": package["request_count"],
        "maximum_physical_attempts": package["maximum_physical_attempts"],
        "package_zip_sha256": sha256_file(package_zip),
        "blinded_judge_manifest_sha256": package[
            "blinded_judge_manifest_sha256"
        ],
        "status": "AUTHORIZED",
    }
    value.update(changes)
    target.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return value


class PackageOfflineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="c4-judge-r3-offline-")
        self.root = Path(self.temporary.name)
        self.package_zip = self.root / "package.zip"
        self.authorization = self.root / "authorization.json"
        create_package_zip(self.package_zip)
        write_authorization(self.package_zip, self.authorization)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def execute(self, client: MockClient, output_name: str = "output") -> tuple[dict, MockClock]:
        clock = MockClock()
        with authorization_gate():
            status = execute_package(
                self.package_zip,
                self.authorization,
                self.root / output_name,
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
                utc_now=lambda: "2026-09-02T00:00:00Z",
            )
        return status, clock

    def test_01_package_allowlist_and_validator(self) -> None:
        result = validate_package_dir(PACKAGE_DIR)
        config = json.loads((PACKAGE_DIR / "JUDGE_CONFIGURATION.json").read_text())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["request_count"], config["request_count"])
        self.assertEqual(set(path.name for path in PACKAGE_DIR.iterdir()), ALLOWED_FILES)

    def test_02_timeout_and_authorization_contract_are_exact(self) -> None:
        config = json.loads((PACKAGE_DIR / "JUDGE_CONFIGURATION.json").read_text())
        contract = json.loads((PACKAGE_DIR / "EXECUTION_CONTRACT.json").read_text())
        self.assertEqual(config["request_timeout_seconds"], 120.0)
        self.assertEqual(contract["request_timeout_seconds"], 120.0)
        self.assertEqual(
            contract["authorization_environment_value"],
            "AUTHORIZED_C4_REAL_JUDGE_CONTINUATION_R3",
        )
        self.assertTrue(contract["timeout_is_non_retryable"])

    def test_03_provider_schema_omits_local_fields(self) -> None:
        schema = json.loads((PACKAGE_DIR / "JUDGE_SCHEMA.json").read_text())
        self.assertNotIn("response_blind_id", schema["properties"])
        self.assertNotIn("overall_applicable_mean", schema["properties"])

    def test_04_parser_attaches_id_and_local_mean(self) -> None:
        row, request = first_request()
        parsed = parse_judge_result(
            valid_provider_result(request),
            request["frozen_applicability_map"],
            expected_judge_result_blind_id=row["judge_result_blind_id"],
        )
        self.assertEqual(parsed["response_blind_id"], row["judge_result_blind_id"])
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)
        self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")

    def test_05_long_rationale_is_valid_and_unmodified(self) -> None:
        row, request = first_request()
        value = json.loads(valid_provider_result(request))
        value["criterion_rationales"]["actionability"] = "x" * 900
        parsed = parse_judge_result(
            value,
            request["frozen_applicability_map"],
            expected_judge_result_blind_id=row["judge_result_blind_id"],
        )
        self.assertEqual(parsed["criterion_rationales"]["actionability"], "x" * 900)

    def test_06_empty_rationale_remains_invalid(self) -> None:
        row, request = first_request()
        value = json.loads(valid_provider_result(request))
        value["criterion_rationales"]["actionability"] = "  "
        with self.assertRaisesRegex(JudgeResultError, "actionability rationale"):
            parse_judge_result(
                value,
                request["frozen_applicability_map"],
                expected_judge_result_blind_id=row["judge_result_blind_id"],
            )

    def test_07_duplicate_keys_fail_strictly(self) -> None:
        _row, request = first_request()
        with self.assertRaisesRegex(JudgeResultError, "duplicate JSON key"):
            parse_judge_result(
                '{"clarity":"1","clarity":"2"}',
                request["frozen_applicability_map"],
                expected_judge_result_blind_id="R3B-00000000000000000000",
            )

    def test_08_exact_local_means_remain_unrounded(self) -> None:
        for count in range(4, 9):
            request = {"frozen_applicability_map": applicability(count)}
            parsed = parse_judge_result(
                valid_provider_result(request, nonuniform=True),
                request["frozen_applicability_map"],
                expected_judge_result_blind_id="R3B-00000000000000000000",
            )
            self.assertEqual(parsed["overall_applicable_mean"], (count + 1) / count)

    def test_09_applicability_is_enforced(self) -> None:
        row, request = first_request()
        value = json.loads(valid_provider_result(request))
        for criterion, field in SCORE_FIELDS.items():
            if request["frozen_applicability_map"]["criteria"][criterion]:
                value[field] = "NA"
                break
        with self.assertRaisesRegex(JudgeResultError, "APPLICABILITY_CONTRACT"):
            parse_judge_result(
                value,
                request["frozen_applicability_map"],
                expected_judge_result_blind_id=row["judge_result_blind_id"],
            )

    def test_10_environment_gate_precedes_output_and_client(self) -> None:
        client = MockClient()
        with self.assertRaises(RunnerError):
            execute_package(
                self.package_zip,
                self.authorization,
                self.root / "no-gate-output",
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
            )
        self.assertFalse((self.root / "no-gate-output").exists())
        self.assertEqual(client.calls, [])

    def test_11_authorization_binding_is_strict(self) -> None:
        package = validate_package_zip(self.package_zip)
        write_authorization(
            self.package_zip,
            self.authorization,
            request_count=package["request_count"] + 1,
        )
        client = MockClient()
        with authorization_gate(), self.assertRaises(RunnerError):
            execute_package(
                self.package_zip,
                self.authorization,
                self.root / "bad-auth-output",
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
            )
        self.assertFalse((self.root / "bad-auth-output").exists())
        self.assertEqual(client.calls, [])

    def test_12_existing_output_is_refused_without_client(self) -> None:
        output = self.root / "existing"
        output.mkdir()
        client = MockClient()
        with authorization_gate(), self.assertRaises(RunnerError):
            execute_package(
                self.package_zip,
                self.authorization,
                output,
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
            )
        self.assertEqual(client.calls, [])

    def test_13_wrong_timeout_stops_before_call(self) -> None:
        output = self.root / "bad-timeout"
        client = MockClient(timeout=10.0)
        with authorization_gate(), self.assertRaises(RunnerError):
            execute_package(
                self.package_zip,
                self.authorization,
                output,
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
                utc_now=lambda: "2026-09-02T00:00:00Z",
            )
        self.assertEqual(client.calls, [])
        status = json.loads((output / "JUDGE_EXECUTION_STATUS.json").read_text())
        self.assertEqual(status["judge_calls"], 0)

    def test_14_nonzero_sdk_retries_stop_before_call(self) -> None:
        output = self.root / "bad-retries"
        client = MockClient(max_retries=1)
        with authorization_gate(), self.assertRaises(RunnerError):
            execute_package(
                self.package_zip,
                self.authorization,
                output,
                runtime_probe=fake_runtime,
                client_factory=lambda: client,
                utc_now=lambda: "2026-09-02T00:00:00Z",
            )
        self.assertEqual(client.calls, [])

    def test_15_timeout_is_nonretryable(self) -> None:
        output = self.root / "timeout"
        client = MockClient([TimeoutError("mock transport timeout")])
        with self.assertRaises(RunnerError):
            self.execute(client, output.name)
        self.assertEqual(len(client.calls), 1)
        status = json.loads((output / "JUDGE_EXECUTION_STATUS.json").read_text())
        self.assertEqual(status["judge_calls"], 1)
        self.assertEqual(status["status"], "INCOMPLETE")

    def test_16_one_invalid_output_gets_one_identical_retry(self) -> None:
        client = MockClient(["{"])
        status, _clock = self.execute(client, "one-retry")
        request_count = validate_package_zip(self.package_zip)["request_count"]
        self.assertEqual(status["status"], "COMPLETE")
        self.assertEqual(status["judge_calls"], request_count + 1)
        self.assertEqual(client.calls[0], client.calls[1])

    def test_17_second_invalid_output_stops_and_is_retained(self) -> None:
        output = self.root / "second-invalid"
        client = MockClient(["{", "{"])
        with self.assertRaises(RunnerError):
            self.execute(client, output.name)
        self.assertEqual(len(client.calls), 2)
        attempts = read_jsonl(output / "JUDGE_ATTEMPT_JOURNAL.jsonl")
        self.assertEqual(
            len([row for row in attempts if row.get("raw_response_content") == "{"]), 2
        )

    def test_18_returned_model_mismatch_is_nonretryable(self) -> None:
        output = self.root / "wrong-model"
        client = MockClient(["__WRONG_MODEL__"])
        with self.assertRaises(RunnerError):
            self.execute(client, output.name)
        self.assertEqual(len(client.calls), 1)

    def test_19_pacing_and_original_orders_are_preserved(self) -> None:
        client = MockClient()
        status, clock = self.execute(client, "complete")
        rows = read_jsonl(PACKAGE_DIR / "BLINDED_JUDGE_REQUESTS.jsonl")
        terminals = read_jsonl(self.root / "complete" / "JUDGE_TERMINAL_JOURNAL.jsonl")
        self.assertEqual(
            [row["logical_order"] for row in terminals],
            [row["original_logical_order"] for row in rows],
        )
        self.assertEqual(len(clock.sleeps), max(0, len(rows) - 1))
        self.assertTrue(all(seconds >= 15.0 for seconds in clock.sleeps))
        self.assertEqual(status["request_timeout_seconds"], 120.0)

    def test_20_sanitizer_never_uses_exception_message(self) -> None:
        error = sanitized_error(
            MockProviderError("Authorization: Bearer TOP-SECRET"), "PROVIDER_CALL"
        )
        self.assertNotIn("TOP-SECRET", json.dumps(error))
        self.assertEqual(error["error_code"], "rate_limit_exceeded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
