#!/usr/bin/env python3
"""Offline package tests; these tests never import or call the provider SDK."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from validate_package import validate


class PackageTests(unittest.TestCase):
    def test_strict_package(self) -> None:
        report = validate(Path(__file__).resolve().parent)
        self.assertEqual(report["status"], "PASS")
        self.assertGreater(report["request_count"], 0)

    def test_runner_is_generation_only_and_unexecuted(self) -> None:
        source = (Path(__file__).resolve().parent / "generation_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("Judge", source.replace("no Judge", ""))
        self.assertNotIn("streamlit", source.casefold())
        self.assertIn("max_retries=0", source)
        self.assertIn("Refusing overwrite or automatic resume", source)

    def test_future_runtime_identity_is_available_without_a_provider_call(self) -> None:
        command = [
            "/opt/anaconda3/bin/python3",
            "-c",
            (
                "import json, openai, sys; "
                "print(json.dumps({'python': list(sys.version_info[:3]), "
                "'openai': openai.__version__, 'executable': sys.executable}))"
            ),
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        identity = json.loads(completed.stdout)
        self.assertEqual(identity["python"], [3, 13, 5])
        self.assertEqual(identity["openai"], "1.109.1")
        self.assertEqual(Path(identity["executable"]).resolve(), Path(command[0]).resolve())

    def test_runner_refuses_execution_without_explicit_later_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "generation_runner.py"),
                    "--request-manifest",
                    str(Path(__file__).resolve().parent / "BLINDED_REQUESTS.jsonl"),
                    "--output-dir",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Generation is not authorised", completed.stderr + completed.stdout)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
