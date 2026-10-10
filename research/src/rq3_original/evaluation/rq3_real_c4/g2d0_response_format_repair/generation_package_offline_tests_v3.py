#!/usr/bin/env python3
"""Offline-only tests embedded in each C4 REAL regeneration R3 package."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
import zipfile

from c4_real_student_facing_response_validator_v1 import (
    VALID_STUDENT_FACING_RESPONSE,
    validate_answer_text,
)
from generation_execution_runner_v3 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    execute_package,
    validate_response_content,
)
from validate_package import ALLOWED_FILES, validate


ROOT = Path(__file__).resolve().parent


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


class PackageTests(unittest.TestCase):
    def test_strict_package_and_plain_text_v3(self) -> None:
        report = validate(ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertGreater(report["request_count"], 0)
        self.assertEqual(report["plain_text_user_message_count"], report["request_count"])
        self.assertEqual(report["raw_json_user_message_count"], 0)

    def test_member_allowlist_excludes_restricted_and_execution_material(self) -> None:
        self.assertEqual({path.name for path in ROOT.iterdir()}, ALLOWED_FILES)
        joined = "\n".join(sorted(ALLOWED_FILES)).casefold()
        for prohibited in (
            "terminal_journal",
            "attempt_journal",
            "response_to_condition",
            "hmac_key",
            "judge",
            "sqlite",
            "g2_answer",
        ):
            self.assertNotIn(prohibited, joined)

    def test_exact_future_runtime_identity_without_provider_call(self) -> None:
        completed = subprocess.run(
            [
                "/opt/anaconda3/bin/python3",
                "-c",
                (
                    "import json, openai, sys; "
                    "print(json.dumps({'python': list(sys.version_info[:3]), "
                    "'openai': openai.__version__, 'executable': sys.executable}))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            env={key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"},
        )
        identity = json.loads(completed.stdout)
        self.assertEqual(identity["python"], [3, 13, 5])
        self.assertEqual(identity["openai"], "1.109.1")
        self.assertEqual(
            Path(identity["executable"]).resolve(), Path("/opt/anaconda3/bin/python3").resolve()
        )

    def test_semantic_validator_required_rejections_and_acceptances(self) -> None:
        rejected = (
            "{",
            "[",
            "{}",
            "[]",
            '{"action_steps":["Do this"]}',
            '["raw"]',
            "{'evidence': {'content': 'raw'}}",
        )
        accepted = (
            "Yes.",
            "Review the Week 4 lecture.",
            "- Review the lecture\n- Write one note",
        )
        for value in rejected:
            self.assertNotEqual(validate_answer_text(value), VALID_STUDENT_FACING_RESPONSE)
        for value in accepted:
            self.assertEqual(validate_answer_text(value), VALID_STUDENT_FACING_RESPONSE)

    def test_outer_schema_validation_precedes_semantic_validation(self) -> None:
        self.assertEqual(validate_response_content("not-json")[1], "INVALID_JSON")
        self.assertEqual(
            validate_response_content('{"wrong":"field"}')[1],
            "STRICT_SCHEMA_VALIDATION_FAILED",
        )
        result = validate_response_content(json.dumps({"answer_text": "{"}))
        self.assertEqual(result[1], "NON_STUDENT_FACING_FORMAT")
        self.assertIsNotNone(result[2])

    def test_runner_requires_explicit_execute_and_exact_environment(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(ROOT / "generation_execution_runner_v3.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--authorization-record", help_result.stdout)
        self.assertIn("--package-zip", help_result.stdout)
        self.assertIn("--execute", help_result.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "generation_execution_runner_v3.py"),
                    "--authorization-record",
                    str(ROOT / "EXECUTION_CONTRACT.json"),
                    "--package-zip",
                    str(Path(temporary) / "absent.zip"),
                    "--output-dir",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **{key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"},
                    "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": AUTHORIZATION_ENVIRONMENT_VALUE,
                },
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Generation is not authorized", completed.stderr + completed.stdout)
            self.assertFalse(output.exists())

    def _one_request_package(self, temporary: Path) -> tuple[Path, Path, Path]:
        package_root = temporary / "package"
        package_root.mkdir()
        for name in ALLOWED_FILES:
            shutil.copy2(ROOT / name, package_root / name)
        rows = [
            json.loads(line)
            for line in (package_root / "BLINDED_REQUESTS.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manifest = (json.dumps(rows[0], ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        (package_root / "BLINDED_REQUESTS.jsonl").write_bytes(manifest)
        contract = json.loads((package_root / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
        contract["request_count"] = 1
        contract["maximum_physical_attempts"] = 2
        contract["estimated_input_tokens"] = rows[0]["estimated_input_tokens"]
        (package_root / "EXECUTION_CONTRACT.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        source_hashes = json.loads(
            (package_root / "PACKAGE_SOURCE_HASHES.json").read_text(encoding="utf-8")
        )
        source_hashes["request_count"] = 1
        source_hashes["estimated_input_tokens"] = rows[0]["estimated_input_tokens"]
        source_hashes["blinded_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        source_hashes["member_sha256_excluding_self"] = {
            name: _sha256(package_root / name)
            for name in sorted(ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"})
        }
        (package_root / "PACKAGE_SOURCE_HASHES.json").write_text(
            json.dumps(source_hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        package_zip = temporary / "package.zip"
        with zipfile.ZipFile(package_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(ALLOWED_FILES):
                archive.write(package_root / name, arcname=name)
        authorization = {
            "schema_version": "c4-real-response-regeneration-authorization-r3",
            "authorization_id": "OFFLINE-MOCK-ONLY",
            "authorized_by": "offline-test",
            "authorized_at_utc": "2026-09-01T00:00:00Z",
            "package_id": contract["package_id"],
            "shard": contract["shard"],
            "request_count": 1,
            "maximum_physical_attempts": 2,
            "package_sha256": _sha256(package_zip),
            "blinded_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "status": "AUTHORIZED",
        }
        authorization_path = temporary / "authorization.json"
        authorization_path.write_text(
            json.dumps(authorization, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return package_root, package_zip, authorization_path

    def _execute_mock(self, outcomes: list[object]) -> tuple[int, _MockClient, Path, tempfile.TemporaryDirectory[str]]:
        temporary_context: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        temporary = Path(temporary_context.name)
        package_root, package_zip, authorization_path = self._one_request_package(temporary)
        output = temporary / "output"
        client = _MockClient(outcomes)
        previous = os.environ.get("C4_REAL_RESPONSE_GENERATION_AUTHORIZATION")
        os.environ["C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"] = AUTHORIZATION_ENVIRONMENT_VALUE
        try:
            result = execute_package(
                package_root / "BLINDED_REQUESTS.jsonl",
                authorization_path,
                package_zip,
                output,
                package_root=package_root,
                runtime_checker=_runtime_identity,
                client_factory=lambda: client,
                sleeper=lambda _seconds: None,
                monotonic=lambda: 0.0,
                now=lambda: "2026-09-01T00:00:00Z",
            )
        finally:
            if previous is None:
                os.environ.pop("C4_REAL_RESPONSE_GENERATION_AUTHORIZATION", None)
            else:
                os.environ["C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"] = previous
        return result, client, output, temporary_context

    def test_each_retryable_category_gets_one_byte_identical_retry(self) -> None:
        invalid_outputs = (
            "not-json",
            '{"wrong":"field"}',
            json.dumps({"answer_text": "{"}),
        )
        for invalid in invalid_outputs:
            with self.subTest(invalid=invalid):
                result, client, output, context = self._execute_mock(
                    [_response(invalid, "first"), _response(json.dumps({"answer_text": "Yes."}), "second")]
                )
                try:
                    self.assertEqual(result, 0)
                    self.assertEqual(len(client.completions.payload_bytes), 2)
                    self.assertEqual(client.completions.payload_bytes[0], client.completions.payload_bytes[1])
                    attempts = [
                        json.loads(line)
                        for line in (output / "GENERATION_ATTEMPT_JOURNAL.jsonl").read_text().splitlines()
                    ]
                    self.assertEqual(attempts[0]["raw_response_content"], invalid)
                    self.assertEqual(attempts[1]["retryable_failure"], None)
                finally:
                    context.cleanup()

    def test_second_invalid_response_stops_shard_and_keeps_first_raw(self) -> None:
        first = json.dumps({"answer_text": "{"})
        second = json.dumps({"answer_text": '{"evidence":"raw"}'})
        result, client, output, context = self._execute_mock(
            [_response(first, "first"), _response(second, "second")]
        )
        try:
            self.assertEqual(result, 2)
            self.assertEqual(len(client.completions.payload_bytes), 2)
            attempts = [json.loads(line) for line in (output / "GENERATION_ATTEMPT_JOURNAL.jsonl").read_text().splitlines()]
            self.assertEqual(attempts[0]["raw_response_content"], first)
            terminal = json.loads((output / "GENERATION_TERMINAL_JOURNAL.jsonl").read_text().strip())
            self.assertEqual(terminal["terminal_status"], "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE")
        finally:
            context.cleanup()

    def test_non_retryable_error_stops_after_one_attempt(self) -> None:
        result, client, output, context = self._execute_mock([ConnectionError("mock network failure")])
        try:
            self.assertEqual(result, 2)
            self.assertEqual(len(client.completions.payload_bytes), 1)
            attempts = (output / "GENERATION_ATTEMPT_JOURNAL.jsonl").read_text().splitlines()
            self.assertEqual(len(attempts), 1)
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["status"], "INCOMPLETE_FAIL_CLOSED")
        finally:
            context.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
