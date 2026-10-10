#!/usr/bin/env python3
"""Mocked-transport offline tests embedded in the R3C1 continuation package."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from c4_real_student_facing_response_validator_v2 import (
    OTHER_NON_STUDENT_FACING_FORMAT,
    RAW_INTERNAL_STRUCTURE,
    SERIALIZED_JSON_OBJECT_OR_ARRAY,
    TRIVIAL_NONANSWER,
    VALID_STUDENT_FACING_RESPONSE,
    validate_answer_text,
)
from generation_execution_runner_v3_1 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    execute_package,
    validate_response_content,
)
from validate_package import ALLOWED_FILES, validate


ROOT = Path(__file__).resolve().parent
AUTH_ENV = "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _response(raw_content: str, response_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        model="gpt-4o-mini-2024-07-18",
        system_fingerprint="mock-fingerprint",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=raw_content, refusal=None),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )


class _MockCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.payload_bytes: list[bytes] = []

    def create(self, **kwargs: object) -> object:
        self.payload_bytes.append(
            json.dumps(
                kwargs,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if not self.outcomes:
            raise AssertionError("mock outcome population exhausted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _MockClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.completions = _MockCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)


def _runtime_identity() -> dict[str, object]:
    return {
        "python_version": "3.13.5",
        "python_path": "/opt/anaconda3/bin/python3",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def _make_package_binding(parent: Path) -> tuple[Path, Path]:
    package_zip = parent / "continuation-package.zip"
    with zipfile.ZipFile(package_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(ALLOWED_FILES):
            archive.write(ROOT / name, arcname=name)
    contract = json.loads((ROOT / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
    authorization = {
        "schema_version": "c4-real-response-regeneration-authorization-r3",
        "authorization_id": "MOCKED_OFFLINE_TEST_ONLY",
        "authorized_by": "MOCKED_OFFLINE_TEST",
        "authorized_at_utc": "2026-09-02T00:00:00Z",
        "package_id": contract["package_id"],
        "shard": contract["shard"],
        "request_count": 43,
        "maximum_physical_attempts": 86,
        "package_sha256": _sha256(package_zip),
        "blinded_manifest_sha256": _sha256(ROOT / "BLINDED_REQUESTS.jsonl"),
        "status": "AUTHORIZED",
    }
    authorization_path = parent / "mock-authorization.json"
    authorization_path.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return package_zip, authorization_path


def _execute(
    temporary: Path,
    outcomes: list[object],
    output_name: str,
) -> tuple[int, _MockClient, Path]:
    package_zip, authorization = _make_package_binding(temporary)
    output = temporary / output_name
    client = _MockClient(outcomes)
    with patch.dict(os.environ, {AUTH_ENV: AUTHORIZATION_ENVIRONMENT_VALUE}):
        code = execute_package(
            ROOT / "BLINDED_REQUESTS.jsonl",
            authorization,
            package_zip,
            output,
            package_root=ROOT,
            runtime_checker=_runtime_identity,
            client_factory=lambda: client,
            sleeper=lambda _: None,
            monotonic=lambda: 0.0,
            now=lambda: "2026-09-02T00:00:00Z",
        )
    return code, client, output


class ContinuationPackageTests(unittest.TestCase):
    def test_01_strict_package_validation(self) -> None:
        report = validate(ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["request_count"], 43)
        self.assertEqual(report["maximum_physical_attempts"], 86)

    def test_02_allowlist_excludes_prior_and_restricted_material(self) -> None:
        self.assertEqual({path.name for path in ROOT.iterdir()}, set(ALLOWED_FILES))
        prohibited = (
            "GENERATION_ATTEMPT_JOURNAL",
            "GENERATION_TERMINAL_JOURNAL",
            "HMAC",
            "restricted",
            "Judge",
            "score",
        )
        self.assertFalse(any(any(token.casefold() in name.casefold() for token in prohibited) for name in ALLOWED_FILES))

    def test_03_validator_v2_accepts_student_facing_colon_cases(self) -> None:
        accepted = (
            "Use your dashboard evidence:",
            "Review the activity evidence:",
            "Use the course evidence:",
            "The evidence:",
            "## Focus:\n\n**Debate Activity:** Review your post.",
            "**Lecture Video Activity:** Rewatch Week 2.",
        )
        self.assertTrue(
            all(validate_answer_text(value) == VALID_STUDENT_FACING_RESPONSE for value in accepted)
        )

    def test_04_validator_v2_rejects_required_structures(self) -> None:
        expected = {
            "": TRIVIAL_NONANSWER,
            "{}": SERIALIZED_JSON_OBJECT_OR_ARRAY,
            "[]": SERIALIZED_JSON_OBJECT_OR_ARRAY,
            "{'action_steps': ['Review']}": RAW_INTERNAL_STRUCTURE,
            "action_steps:\n- Review": RAW_INTERNAL_STRUCTURE,
            "```yaml\naction_steps:\n- Review\n```": RAW_INTERNAL_STRUCTURE,
            "<response>raw</response>": OTHER_NON_STUDENT_FACING_FORMAT,
        }
        self.assertEqual({value: validate_answer_text(value) for value in expected}, expected)

    def test_05_outer_schema_then_v2_retry_categories(self) -> None:
        self.assertEqual(validate_response_content("not-json")[1], "INVALID_JSON")
        self.assertEqual(
            validate_response_content('{"answer_text":"ok","extra":1}')[1],
            "STRICT_SCHEMA_VALIDATION_FAILED",
        )
        self.assertEqual(
            validate_response_content('{"answer_text":"action_steps:\\n- Review"}')[1],
            "NON_STUDENT_FACING_FORMAT",
        )
        parsed, failure, status = validate_response_content(
            '{"answer_text":"Review the dashboard evidence:"}'
        )
        self.assertEqual(parsed, {"answer_text": "Review the dashboard evidence:"})
        self.assertIsNone(failure)
        self.assertEqual(status, VALID_STUDENT_FACING_RESPONSE)

    def test_06_exact_environment_gate_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r3c1-gate-") as temporary_name:
            temporary = Path(temporary_name)
            package_zip, authorization = _make_package_binding(temporary)
            with patch.dict(os.environ, {AUTH_ENV: "WRONG_VALUE"}):
                with self.assertRaisesRegex(ValueError, "authorization"):
                    execute_package(
                        ROOT / "BLINDED_REQUESTS.jsonl",
                        authorization,
                        package_zip,
                        temporary / "output",
                        package_root=ROOT,
                        runtime_checker=_runtime_identity,
                        client_factory=lambda: _MockClient([]),
                    )

    def test_07_output_directory_exclusivity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r3c1-exclusive-") as temporary_name:
            temporary = Path(temporary_name)
            package_zip, authorization = _make_package_binding(temporary)
            output = temporary / "existing-output"
            output.mkdir()
            with patch.dict(os.environ, {AUTH_ENV: AUTHORIZATION_ENVIRONMENT_VALUE}):
                with self.assertRaisesRegex(FileExistsError, "overwrite or automatic resume"):
                    execute_package(
                        ROOT / "BLINDED_REQUESTS.jsonl",
                        authorization,
                        package_zip,
                        output,
                        package_root=ROOT,
                        runtime_checker=_runtime_identity,
                        client_factory=lambda: _MockClient([]),
                    )

    def test_08_mocked_complete_run_has_43_calls(self) -> None:
        outcomes = [
            _response('{"answer_text":"Review the lecture."}', f"mock-{index}")
            for index in range(43)
        ]
        with tempfile.TemporaryDirectory(prefix="r3c1-complete-") as temporary_name:
            code, client, output = _execute(Path(temporary_name), outcomes, "output")
            self.assertEqual(code, 0)
            self.assertEqual(len(client.completions.payload_bytes), 43)
            self.assertEqual(
                len((output / "GENERATION_ATTEMPT_JOURNAL.jsonl").read_text().splitlines()),
                43,
            )
            self.assertEqual(
                len((output / "GENERATION_TERMINAL_JOURNAL.jsonl").read_text().splitlines()),
                43,
            )

    def test_09_mocked_retry_is_byte_identical(self) -> None:
        outcomes = [
            _response('{"answer_text":"action_steps:\\n- Review"}', "mock-invalid"),
            _response('{"answer_text":"Review the dashboard evidence:"}', "mock-valid"),
            *[
                _response('{"answer_text":"Review the lecture."}', f"mock-{index}")
                for index in range(42)
            ],
        ]
        with tempfile.TemporaryDirectory(prefix="r3c1-retry-") as temporary_name:
            code, client, output = _execute(Path(temporary_name), outcomes, "output")
            self.assertEqual(code, 0)
            self.assertEqual(len(client.completions.payload_bytes), 44)
            self.assertEqual(client.completions.payload_bytes[0], client.completions.payload_bytes[1])
            attempts = [
                json.loads(line)
                for line in (output / "GENERATION_ATTEMPT_JOURNAL.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["attempt_number"] for row in attempts[:2]], [1, 2])

    def test_10_second_invalid_response_stops_package(self) -> None:
        outcomes = [
            _response('{"answer_text":"action_steps:\\n- Review"}', "mock-invalid-1"),
            _response('{"answer_text":"recommended_action: Review"}', "mock-invalid-2"),
        ]
        with tempfile.TemporaryDirectory(prefix="r3c1-second-invalid-") as temporary_name:
            code, client, output = _execute(Path(temporary_name), outcomes, "output")
            self.assertEqual(code, 2)
            self.assertEqual(len(client.completions.payload_bytes), 2)
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["stop_reason"], "SECOND_INVALID_RESPONSE")
            self.assertEqual(status["unattempted_logical_request_count"], 42)

    def test_11_nonretryable_transport_error_stops_immediately(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r3c1-transport-") as temporary_name:
            code, client, output = _execute(
                Path(temporary_name), [ConnectionError("mock transport failure")], "output"
            )
            self.assertEqual(code, 2)
            self.assertEqual(len(client.completions.payload_bytes), 1)
            errors = (output / "GENERATION_ERROR_REGISTRY.jsonl").read_text().splitlines()
            self.assertEqual(len(errors), 1)
            self.assertEqual(json.loads(errors[0])["error"]["category"], "TRANSPORT_ERROR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
