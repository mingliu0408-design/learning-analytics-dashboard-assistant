#!/usr/bin/env python3
"""Offline tests for the frozen shard C response-generation artifacts."""

from __future__ import annotations

import unittest

from validate_generation_execution_artifacts_v1 import validate


class GenerationExecutionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = validate()
        cls.checks = cls.result["checks"]

    def assert_checks(self, *names: str) -> None:
        failures = [name for name in names if not self.checks.get(name, False)]
        self.assertEqual(failures, [], failures)

    def test_package_and_manifest_identities(self) -> None:
        self.assert_checks(
            "source_manifest_schema",
            "package_zip_identity",
            "package_zip_allowlist",
            "package_member_hashes",
            "blinded_manifest_identity",
            "frozen_scientific_identity",
            "package_request_population",
            "output_file_hashes",
        )

    def test_strict_authorization_shape(self) -> None:
        self.assert_checks(
            "strict_authorization_shape",
            "authorization_binding",
            "authorization_hash",
        )

    def test_exact_request_population(self) -> None:
        self.assert_checks(
            "request_population",
            "logical_request_id_uniqueness",
            "response_blind_id_uniqueness",
            "provider_payload_hashes",
            "frozen_provider_payloads",
        )

    def test_output_directory_exclusivity(self) -> None:
        self.assert_checks("output_directory_exclusivity")

    def test_preflight_receipt(self) -> None:
        self.assert_checks("preflight_receipt", "runtime_identity")

    def test_attempt_journal_ordering(self) -> None:
        self.assert_checks(
            "attempt_count",
            "attempt_field_shape",
            "attempt_journal_order",
            "attempt_identity_binding",
            "attempt_numbering",
        )

    def test_terminal_uniqueness(self) -> None:
        self.assert_checks(
            "terminal_count",
            "terminal_field_shape",
            "terminal_order",
            "terminal_logical_id_uniqueness",
            "terminal_response_blind_id_uniqueness",
            "terminal_identity_binding",
            "terminal_statuses",
            "terminal_attempt_consistency",
            "terminal_output_consistency",
        )

    def test_strict_parsed_outputs(self) -> None:
        self.assert_checks("strict_parsed_output_shape", "raw_parsed_output_consistency")

    def test_nonempty_answer_text(self) -> None:
        self.assert_checks("nonempty_answer_text")

    def test_answer_hashes(self) -> None:
        self.assert_checks("terminal_journal_hash", "answer_text_hashes", "answer_set_hash")

    def test_returned_model(self) -> None:
        self.assert_checks("returned_model_identity", "model_error_count")

    def test_retry_rules(self) -> None:
        self.assert_checks(
            "retry_compliance",
            "retry_count",
            "strict_validation_statuses",
        )

    def test_physical_attempt_ceiling(self) -> None:
        self.assert_checks("physical_attempt_ceiling")

    def test_fail_closed_status(self) -> None:
        self.assert_checks(
            "status_complete",
            "fail_closed_contract",
            "scope_boundaries",
            "status_summary_consistency",
        )

    def test_usage_arithmetic(self) -> None:
        self.assert_checks("usage_per_attempt", "usage_aggregate", "cached_usage_detail")

    def test_secret_scan(self) -> None:
        self.assert_checks("secret_absence", "no_bytecode_residue")

    def test_prohibited_fields_absent(self) -> None:
        self.assert_checks(
            "prohibited_output_fields",
            "zero_judge_scoring",
            "error_registry_empty",
            "provider_error_count",
            "invalid_json_or_schema_count",
        )

    def test_future_response_integration_compatibility(self) -> None:
        self.assert_checks(
            "future_integration_compatibility",
            "audit_summary_consistency",
            "report_summary_consistency",
            "review_manifest_allowlist",
            "review_manifest_hashes",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
