from __future__ import annotations

import csv
from decimal import Decimal
import json
from pathlib import Path
import unittest

from .. import finalize_memory_specialist_dev as finalizer
from .. import memory_specialist_common as common


class MemorySpecialistResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = common.load_jsonl(common.V2_MANIFEST_PATH)
        cls.attempts = common.load_jsonl(common.ATTEMPT_RECORDS_PATH)
        cls.journal = common.load_jsonl(common.CALL_JOURNAL_PATH)
        cls.terminals = common.load_jsonl(common.TERMINAL_RESULTS_PATH)
        cls.metrics = common.load_json(common.METRICS_PATH)
        cls.usage = common.load_json(common.USAGE_PATH)
        cls.freeze = common.load_json(common.FROZEN_CONFIGURATION_PATH)

    def test_01_all_required_outputs_exist(self) -> None:
        for path in common.DYNAMIC_OUTPUT_PATHS:
            self.assertTrue(path.is_file(), path)

    def test_02_exactly_64_logical_terminal_records_are_ordered(self) -> None:
        expected = [
            f"R2V2-MEMORY-SPECIALIST-DEV-{index:04d}"
            for index in range(1, 65)
        ]
        self.assertEqual(64, len(self.terminals))
        self.assertEqual(expected, [record["logical_call_id"] for record in self.terminals])
        self.assertEqual(64, len({record["annotation_case_id"] for record in self.terminals}))

    def test_03_physical_attempt_count_is_bounded_and_sequential(self) -> None:
        self.assertGreaterEqual(len(self.attempts), 64)
        self.assertLessEqual(len(self.attempts), 128)
        self.assertEqual(
            list(range(1, len(self.attempts) + 1)),
            [record["physical_attempt_number"] for record in self.attempts],
        )

    def test_04_every_attempt_has_complete_durable_journal_lifecycle(self) -> None:
        ledger = finalizer._verify_call_ledger(self.attempts, self.journal, self.terminals)
        self.assertEqual("PASS", ledger["status"])
        self.assertEqual(len(self.attempts), ledger["reserved_events"])
        self.assertEqual(len(self.attempts), ledger["completed_events"])
        self.assertEqual(0, ledger["uncompleted_reservations"])

    def test_05_retries_only_follow_invalid_structured_output(self) -> None:
        by_logical: dict[str, list[dict[str, object]]] = {}
        for attempt in self.attempts:
            by_logical.setdefault(str(attempt["logical_call_id"]), []).append(attempt)
        for logical_attempts in by_logical.values():
            self.assertLessEqual(len(logical_attempts), 2)
            if len(logical_attempts) == 2:
                self.assertIn(
                    logical_attempts[0]["schema_validation"]["error"],
                    {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"},
                )
                self.assertEqual(
                    logical_attempts[0]["request_sha256"],
                    logical_attempts[1]["request_sha256"],
                )

    def test_06_every_request_hash_matches_authorized_manifest(self) -> None:
        expected = {
            record["logical_call_id"]: record["provider_facing_request_sha256"]
            for record in self.manifest
        }
        for attempt in self.attempts:
            self.assertEqual(expected[attempt["logical_call_id"]], attempt["request_sha256"])

    def test_07_strict_valid_predictions_and_freeze_status_are_consistent(self) -> None:
        valid = [record for record in self.terminals if record["terminal_status"] == "VALID_PREDICTION"]
        for record in valid:
            self.assertEqual({"memory_required"}, set(record["prediction"]))
            self.assertIs(type(record["prediction"]["memory_required"]), bool)
            self.assertTrue(record["schema_valid"])
        expected_status = (
            "FROZEN_AFTER_DEV_EXECUTION"
            if len(valid) == 64
            else "MEMORY_SPECIALIST_EXECUTION_INCOMPLETE_NOT_FROZEN"
        )
        self.assertEqual(expected_status, self.freeze["MEMORY_SPECIALIST_STATUS"])

    def test_08_requested_and_returned_models_are_exact(self) -> None:
        self.assertEqual(
            {common.AUTHORIZED_MODEL_SNAPSHOT},
            {record["requested_model"] for record in self.attempts},
        )
        returned = {record["returned_model"] for record in self.attempts if record["returned_model"]}
        self.assertLessEqual(returned, {common.AUTHORIZED_MODEL_SNAPSHOT})

    def test_09_attempt_records_have_required_audit_fields(self) -> None:
        required = {
            "logical_call_id", "annotation_case_id", "fold_id", "attempt_number",
            "request_sha256", "response_id", "requested_model", "returned_model",
            "system_fingerprint", "finish_reason", "raw_structured_content",
            "parsed_json", "schema_validation", "input_tokens", "output_tokens",
            "total_tokens", "latency_seconds", "provider_error",
        }
        for record in self.attempts:
            self.assertLessEqual(required, set(record))

    def test_10_prediction_csv_has_all_64_manifest_rows(self) -> None:
        with common.PREDICTIONS_PATH.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(64, len(rows))
        self.assertEqual(
            [record["logical_call_id"] for record in self.manifest],
            [row["logical_call_id"] for row in rows],
        )

    def test_11_error_registry_matches_nonvalid_or_unexecuted_cases(self) -> None:
        with common.ERROR_REGISTRY_PATH.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        expected = sum(record["terminal_status"] != "VALID_PREDICTION" for record in self.terminals)
        expected += 64 - len(self.terminals)
        self.assertEqual(expected, len(rows))

    def test_12_usage_and_cost_arithmetic_matches_attempts(self) -> None:
        actual = self.usage["actual_provider_usage"]
        input_tokens = sum(record["input_tokens"] or 0 for record in self.attempts)
        output_tokens = sum(record["output_tokens"] or 0 for record in self.attempts)
        total_tokens = sum(record["total_tokens"] or 0 for record in self.attempts)
        self.assertEqual(input_tokens, actual["input_tokens"])
        self.assertEqual(output_tokens, actual["output_tokens"])
        self.assertEqual(total_tokens, actual["total_tokens"])
        expected_cost = (
            Decimal(input_tokens) * Decimal("0.15")
            + Decimal(output_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)
        self.assertEqual(
            format(expected_cost, ".8f"),
            self.usage["approximate_cost_usd"]["total"],
        )

    def test_13_metrics_recompute_from_predictions_and_frozen_gold(self) -> None:
        with (common.DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            gold_rows = [
                row for row in csv.DictReader(handle) if row["final_dialogue_action"] == "ANSWER"
            ]
        gold = {row["annotation_case_id"]: row for row in gold_rows}
        predictions = {
            record["annotation_case_id"]: record["prediction"]["memory_required"]
            for record in self.terminals
            if record["terminal_status"] == "VALID_PREDICTION"
        }
        recomputed = finalizer._binary_metrics(list(gold), gold, predictions)
        self.assertEqual(recomputed, self.metrics["complete_case_metrics"])

    def test_14_family_and_contrast_denominators_are_frozen(self) -> None:
        family = self.metrics["family_metrics"]
        contrast = self.metrics["memory_contrast_metrics"]
        self.assertEqual(32, family["total_answer_families"])
        self.assertEqual(3, contrast["total_memory_contrast_groups"])
        self.assertLessEqual(family["fully_covered_families"], 32)
        self.assertLessEqual(contrast["fully_covered_memory_contrast_groups"], 3)

    def test_15_page_and_fold_metrics_cover_the_full_population(self) -> None:
        self.assertEqual(
            64,
            sum(entry["total_cases"] for entry in self.metrics["page_stratified_metrics"].values()),
        )
        self.assertEqual(
            {f"DEV-CV-FOLD-{value}": 16 for value in range(1, 5)},
            {
                name: entry["total_cases"]
                for name, entry in self.metrics["fold_stratified_metrics"].items()
            },
        )

    def test_16_frozen_sources_match_before_and_after(self) -> None:
        report = common.load_json(common.SOURCE_VERIFICATION_PATH)
        self.assertEqual("PASS_PRE_AND_POST_EXECUTION_BYTES_UNCHANGED", report["status"])
        self.assertTrue(report["bytes_unchanged"])
        self.assertEqual(report["pre_execution"], report["post_execution"])

    def test_17_no_credentials_or_prohibited_partition_ids_in_outputs(self) -> None:
        paths = [
            common.V2_MANIFEST_PATH,
            common.MANIFEST_DIFF_PATH,
            common.SOURCE_VERIFICATION_PATH,
            common.ATTEMPT_RECORDS_PATH,
            common.CALL_JOURNAL_PATH,
            common.TERMINAL_RESULTS_PATH,
            common.PREDICTIONS_PATH,
            common.ERROR_REGISTRY_PATH,
            common.USAGE_PATH,
            common.METRICS_PATH,
            common.FROZEN_CONFIGURATION_PATH,
            common.RESULTS_REPORT_PATH,
            common.VERIFICATION_REPORT_PATH,
            common.STATUS_PATH,
            common.TEST_REPORT_PATH,
            common.OUTPUT_SHA256_MANIFEST_PATH,
        ]
        self.assertEqual("PASS", common.credential_or_partition_scan(paths)["status"])

    def test_18_frozen_configuration_hashes_match_outputs(self) -> None:
        evidence = self.freeze["execution_evidence"]
        self.assertEqual(common.sha256_file(common.PREDICTIONS_PATH), evidence["dev_predictions_sha256"])
        self.assertEqual(common.sha256_file(common.ATTEMPT_RECORDS_PATH), evidence["attempt_records_sha256"])
        self.assertEqual(common.sha256_file(common.CALL_JOURNAL_PATH), evidence["call_journal_sha256"])
        self.assertEqual(common.sha256_file(common.TERMINAL_RESULTS_PATH), evidence["terminal_results_sha256"])

    def test_19_zero_out_of_scope_provider_execution_is_recorded(self) -> None:
        boundary = self.freeze["provider_call_boundary"]
        for field in (
            "rag_specialist_calls", "p2_calls_or_scoring", "p3_calls_or_scoring",
            "p1_calls_or_execution", "rq3_calls_or_execution", "future_held_out_calls_or_access",
        ):
            self.assertEqual(0, boundary[field], field)
        self.assertFalse(boundary["further_authority_inferred"])

    def test_20_output_sha256_manifest_is_complete_and_exact(self) -> None:
        manifest = common.load_json(common.OUTPUT_SHA256_MANIFEST_PATH)
        self.assertEqual(manifest["file_count"], len(manifest["files"]))
        for entry in manifest["files"]:
            path = common.TRACK_DIR / entry["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(entry["sha256"], common.sha256_file(path), entry["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
