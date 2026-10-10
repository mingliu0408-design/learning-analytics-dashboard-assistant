#!/usr/bin/env python3
"""Offline-only tests embedded in each C4 REAL generation R2 package."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validate_package import ALLOWED_FILES, validate


ROOT = Path(__file__).resolve().parent


class PackageTests(unittest.TestCase):
    def test_strict_package_and_v2_hygiene(self) -> None:
        report = validate(ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertGreater(report["request_count"], 0)
        self.assertEqual(report["exact_duplicate_provider_evidence_items"], 0)
        self.assertEqual(report["prohibited_provider_string_occurrences"], 0)

    def test_member_allowlist_has_no_execution_output_or_restricted_mapping(self) -> None:
        self.assertEqual({path.name for path in ROOT.iterdir()}, ALLOWED_FILES)
        joined = "\n".join(sorted(ALLOWED_FILES)).casefold()
        for prohibited in (
            "terminal_journal",
            "attempt_journal",
            "response_to_condition",
            "hmac_key",
            "judge",
            "sqlite",
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
        self.assertEqual(Path(identity["executable"]).resolve(), Path("/opt/anaconda3/bin/python3").resolve())

    def test_runner_requires_authorization_record_package_zip_and_execute(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(ROOT / "generation_execution_runner_v2.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--authorization-record", help_result.stdout)
        self.assertIn("--package-zip", help_result.stdout)
        self.assertIn("--execute", help_result.stdout)

    def test_runner_rejects_missing_execute_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "generation_execution_runner_v2.py"),
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
                    "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": "AUTHORIZED_C4_REAL_RESPONSE_GENERATION_R2",
                },
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Generation is not authorized", completed.stderr + completed.stdout)
            self.assertFalse(output.exists())

    def test_runner_rejects_generic_yes_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "generation_execution_runner_v2.py"),
                    "--authorization-record",
                    str(ROOT / "EXECUTION_CONTRACT.json"),
                    "--package-zip",
                    str(Path(temporary) / "absent.zip"),
                    "--output-dir",
                    str(output),
                    "--execute",
                ],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **{key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"},
                    "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": "YES",
                },
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Generation is not authorized", completed.stderr + completed.stdout)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
