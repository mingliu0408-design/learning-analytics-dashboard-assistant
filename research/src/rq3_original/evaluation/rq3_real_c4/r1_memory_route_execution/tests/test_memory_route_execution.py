"""Artifact-only tests for RQ3-REAL-R1B Memory routing."""

from __future__ import annotations

import unittest

from evaluation.rq3_real_c4.r1_memory_route_execution import (
    validate_memory_route_execution_v1 as validator,
)


class MemoryRouteExecutionTests(unittest.TestCase):
    def test_package_identity_and_ten_member_allowlist(self) -> None:
        self.assertEqual(validator.validate_package_identity_and_allowlist()["status"], "PASS")

    def test_no_bytecode_residue(self) -> None:
        self.assertEqual(validator.validate_no_bytecode_residue()["residue_count"], 0)

    def test_strict_authorization_record_shape(self) -> None:
        self.assertEqual(validator.validate_authorization_record()["status"], "PASS")

    def test_exact_request_population_and_order(self) -> None:
        result = validator.validate_request_population_and_order()
        self.assertEqual((result["logical_requests"], result["unique_semantic_inputs"]), (62, 60))

    def test_completed_state_and_sealed_output_hashes(self) -> None:
        self.assertEqual(validator.validate_completion_and_output_hashes()["state"], "COMPLETED")

    def test_retry_rules_and_physical_attempt_ceiling(self) -> None:
        result = validator.validate_retry_policy_and_physical_ceiling()
        self.assertEqual((result["physical_attempts"], result["retries"]), (62, 0))
        self.assertLessEqual(result["physical_attempts"], result["maximum_physical_attempts"])

    def test_terminal_uniqueness_and_strict_one_boolean_output(self) -> None:
        result = validator.validate_strict_terminal_outputs_and_uniqueness()
        self.assertEqual((result["valid_terminal_results"], result["strict_boolean_fields"]), (62, 62))

    def test_exact_returned_model_and_zero_errors(self) -> None:
        result = validator.validate_returned_model_and_errors()
        self.assertEqual(result["returned_model"], validator.MODEL)
        self.assertEqual(sum(result[key] for key in ("provider_errors", "json_errors", "schema_errors", "model_errors")), 0)

    def test_duplicate_input_consistency(self) -> None:
        result = validator.validate_duplicate_input_consistency()
        self.assertTrue(result["consistent"])
        self.assertEqual(result["scenario_count"], 3)

    def test_usage_and_approximate_cost_arithmetic(self) -> None:
        result = validator.validate_usage_arithmetic()
        self.assertEqual(result["total_tokens"], 96143)
        self.assertEqual(result["approximate_cost_usd"], "0.00939525")

    def test_no_credentials(self) -> None:
        self.assertEqual(validator.validate_no_secrets()["credential_values_found"], 0)

    def test_zero_gold_and_zero_scoring(self) -> None:
        result = validator.validate_zero_gold_and_scoring()
        self.assertEqual((result["gold_fields"], result["scoring_fields"]), (0, 0))
        self.assertFalse(result["accuracy_calculated"])

    def test_zero_memory_io_and_prohibited_execution_scope(self) -> None:
        result = validator.validate_zero_memory_io_and_scope()
        self.assertEqual(
            sum(
                result[key]
                for key in (
                    "learner_memory_retrievals",
                    "learner_memory_writes",
                    "generated_answers",
                    "judge_calls",
                    "rag_route_calls",
                    "b4_planning_route_calls",
                    "streamlit_launches",
                )
            ),
            0,
        )

    def test_i1_consumer_compatibility_without_assembly(self) -> None:
        result = validator.validate_i1_compatibility()
        self.assertEqual(result["status"], "PASS_I1_COMPATIBLE")
        self.assertFalse(result["assembly_executed"])

    def test_source_manifest_and_audit_consistency(self) -> None:
        self.assertEqual(validator.validate_derived_audit_artifacts()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
