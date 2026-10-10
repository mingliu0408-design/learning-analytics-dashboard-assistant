#!/usr/bin/env python3
"""Offline tests for the frozen C4 REAL shard-B generation artifacts."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import unittest

from validate_generation_execution_v1 import CHECK_NAMES, collect_audit


TEST_ARGUMENTS: argparse.Namespace | None = None


class GenerationExecutionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if TEST_ARGUMENTS is None:
            raise RuntimeError("test arguments were not initialized")
        cls.artifact_dir = TEST_ARGUMENTS.artifact_dir.resolve()
        cls.package_zip = TEST_ARGUMENTS.package_zip.resolve()
        cls.extracted_package = TEST_ARGUMENTS.extracted_package.resolve()
        cls.persisted_audit = json.loads(
            (cls.artifact_dir / "generation_execution_audit_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.recomputed_audit = collect_audit(
            cls.artifact_dir,
            cls.package_zip,
            cls.extracted_package,
            audited_at_utc=cls.persisted_audit["audited_at_utc"],
        )

    def test_frozen_audit_exact_reproduction(self) -> None:
        self.assertEqual(self.persisted_audit, self.recomputed_audit)

    def test_offline_validator_import_graph(self) -> None:
        validator_path = self.artifact_dir / "validate_generation_execution_v1.py"
        tree = ast.parse(validator_path.read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(
            imported_roots.isdisjoint(
                {"openai", "httpx", "requests", "urllib", "socket", "aiohttp"}
            )
        )

    def test_offline_validator_has_no_provider_call_site(self) -> None:
        source = (
            self.artifact_dir / "validate_generation_execution_v1.py"
        ).read_text(encoding="utf-8")
        for prohibited in (
            "chat.completions.create(",
            "OpenAI(",
            "urlopen(",
            "requests.get(",
            "requests.post(",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, source)


def make_check_test(check_name: str):
    def test(self: GenerationExecutionAuditTests) -> None:
        self.assertEqual(self.recomputed_audit["checks"][check_name], "PASS")

    test.__name__ = f"test_check_{check_name}"
    test.__doc__ = f"Require the {check_name} mechanical check to pass."
    return test


for _check_name in CHECK_NAMES:
    setattr(
        GenerationExecutionAuditTests,
        f"test_check_{_check_name}",
        make_check_test(_check_name),
    )


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--extracted-package", type=Path, required=True)
    return parser.parse_known_args()


def main() -> int:
    global TEST_ARGUMENTS
    TEST_ARGUMENTS, unittest_args = parse_args()
    program = unittest.main(
        argv=[sys.argv[0], *unittest_args],
        verbosity=2,
        exit=False,
    )
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
