#!/usr/bin/env python3
"""Offline regression tests for the R3D1-R1 evaluation freeze."""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

from evaluation.rq3_real_c4.r3d1_response_integration import build_r3d1_artifacts as build
from evaluation.rq3_real_c4.r3d1_response_integration.judge_execution_runner_v1 import (
    EXPECTED_MAX_OUTPUT_TOKENS,
    EXPECTED_MODEL,
    RunnerError,
    execute_shard,
)
from evaluation.rq3_real_c4.r3d1_response_integration.judge_result_parser_v1 import (
    JudgeResultError,
    SCORE_FIELDS,
    parse_judge_result,
)
from evaluation.rq3_real_c4.r3d1_response_integration.validate_r3d1_artifacts import (
    load_csv,
    load_json,
    load_jsonl,
    sha256_file,
    validate,
)


def valid_mock_judge_result(provider_payload: dict) -> str:
    request = build._extract_blind_request(provider_payload)
    scores: dict[str, str] = {}
    rationales: dict[str, str] = {}
    numeric: list[int] = []
    for criterion, field in SCORE_FIELDS.items():
        if request["frozen_applicability_map"]["criteria"][criterion]:
            scores[field] = "4"
            numeric.append(4)
        else:
            scores[field] = "NA"
        rationales[field] = "Offline mocked-transport rationale."
    return json.dumps(
        {
            "response_blind_id": request["response_blind_id"],
            **scores,
            "evidence_faithfulness": "4",
            "unsupported_claim_count": "0",
            "overall_applicable_mean": str(sum(numeric) / len(numeric)),
            "criterion_rationales": rationales,
            "schema_version": "rq3-judge-response-v2-transport",
        },
        sort_keys=True,
    )


class MockJudgeClient:
    def __init__(self, *, invalid_json_first: bool = False) -> None:
        self.invalid_json_first = invalid_json_first
        self.calls: list[dict] = []
        self.closed = False
        self.chat = SimpleNamespace(completions=self)

    def create(self, **provider_payload: object) -> SimpleNamespace:
        self.calls.append(dict(provider_payload))
        if self.invalid_json_first and len(self.calls) == 1:
            content = "{"
        else:
            content = valid_mock_judge_result(dict(provider_payload))
        return SimpleNamespace(
            id=f"mock-response-{len(self.calls)}",
            model=EXPECTED_MODEL,
            system_fingerprint="mock-fingerprint",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )

    def close(self) -> None:
        self.closed = True


class MockClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class R3D1R1FreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.here = build.HERE
        cls.canonical = load_jsonl(
            cls.here / "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl"
        )
        cls.conditions = load_jsonl(
            build.RESTRICTED / "c4_real_r3_condition_response_records_frozen_v1.jsonl"
        )
        cls.judge = load_jsonl(
            cls.here / "c4_real_unique_judge_request_manifest_frozen_v1.jsonl"
        )
        cls.judge_mapping = load_csv(
            build.RESTRICTED / "c4_real_condition_to_unique_judge_request_mapping_v1.csv"
        )
        cls.packet_a = load_csv(cls.here / "human_rating_packet_A.csv")
        cls.packet_b = load_csv(cls.here / "human_rating_packet_B.csv")

    def test_01_continuation_commit_present_exactly_once(self) -> None:
        commits = subprocess.run(
            ["git", "rev-list", "HEAD"],
            cwd=build.REPO,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(commits.count(build.CONTINUATION_COMMIT), 1)

    def test_02_all_r3_source_hashes_unchanged(self) -> None:
        manifest = load_json(self.here / "c4_real_r3_source_preservation_manifest_v1.json")
        self.assertTrue(manifest["status"].startswith("PASS_"))
        for item in manifest["files"]:
            self.assertEqual(sha256_file(build.REPO / item["path"]), item["sha256"])

    def test_03_g2_answers_are_excluded(self) -> None:
        self.assertTrue(all("g2" not in row["selected_execution_source"].casefold() for row in self.canonical))
        self.assertTrue(load_json(self.here / "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json")["zero_g2_answer_inclusion"])

    def test_04_canonical_rule_is_frozen(self) -> None:
        rule = load_json(build.R3D0 / "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json")
        self.assertEqual(rule["rule_id"], "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1")
        self.assertIn("Select the earliest attempt", " ".join(rule["steps"]))

    def test_05_shard_a_order_40_selects_attempt_one(self) -> None:
        rows = load_jsonl(build.R3D0 / "c4_real_r3_existing_canonical_response_selection_v1.jsonl")
        row = next(row for row in rows if row["shard"] == "A" and row["logical_order"] == 40)
        self.assertEqual(row["selected_attempt_number"], 1)

    def test_06_original_shard_c_order_4_selects_attempt_one(self) -> None:
        rows = load_jsonl(build.R3D0 / "c4_real_r3_existing_canonical_response_selection_v1.jsonl")
        row = next(row for row in rows if row["shard"] == "C" and row["logical_order"] == 4)
        self.assertEqual(row["selected_attempt_number"], 1)

    def test_07_continuation_supplies_43_responses(self) -> None:
        prefix = "evaluation/rq3_real_c4/r3c1_response_continuation/"
        self.assertEqual(sum(row["selected_execution_source"].startswith(prefix) for row in self.canonical), 43)

    def test_08_canonical_response_count(self) -> None:
        self.assertEqual(len(self.canonical), 147)

    def test_09_logical_request_ids_unique(self) -> None:
        self.assertEqual(len({row["logical_generation_request_id"] for row in self.canonical}), 147)

    def test_10_response_blind_ids_unique(self) -> None:
        self.assertEqual(len({row["response_blind_id"] for row in self.canonical}), 147)

    def test_11_provider_payload_hashes_unique(self) -> None:
        self.assertEqual(len({row["provider_payload_sha256"] for row in self.canonical}), 147)

    def test_12_distinct_answer_text_hash_count(self) -> None:
        self.assertEqual(len({row["answer_text_sha256"] for row in self.canonical}), 146)

    def test_13_one_duplicate_text_group_of_two(self) -> None:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in self.canonical:
            groups[row["answer_text_sha256"]].append(row)
        duplicates = [rows for rows in groups.values() if len(rows) > 1]
        self.assertEqual([len(rows) for rows in duplicates], [2])

    def test_14_known_equal_text_requests_remain_separate(self) -> None:
        rows = [row for row in self.canonical if row["logical_generation_request_id"] in build.KNOWN_DUPLICATE_REQUEST_IDS]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["answer_text_sha256"] for row in rows}, {build.KNOWN_DUPLICATE_TEXT_SHA256})
        self.assertEqual(len({row["response_blind_id"] for row in rows}), 2)
        self.assertEqual(len({row["provider_payload_sha256"] for row in rows}), 2)

    def test_15_all_canonical_answers_pass_validator_v2(self) -> None:
        validator = build.load_module(
            "r3d1_test_validator_v2",
            build.R3D0 / "c4_real_student_facing_response_validator_v2.py",
        )
        self.assertTrue(
            all(
                validator.validate_answer_text(row["answer_text"])
                == validator.VALID_STUDENT_FACING_RESPONSE
                for row in self.canonical
            )
        )

    def test_16_answer_text_hashes_recompute(self) -> None:
        self.assertTrue(
            all(
                hashlib.sha256(row["answer_text"].encode("utf-8")).hexdigest()
                == row["answer_text_sha256"]
                for row in self.canonical
            )
        )

    def test_17_aggregate_usage_arithmetic(self) -> None:
        aggregate = load_json(self.here / "c4_real_r3_generation_usage_frozen_v1.json")["aggregate"]
        self.assertEqual(aggregate["physical_attempts"], 149)
        self.assertEqual(aggregate["historical_redundant_retries"], 2)
        self.assertEqual(aggregate["total_tokens"], 151330)

    def test_18_hmac_key_unchanged_mode_0600(self) -> None:
        path = build.RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
        self.assertEqual(sha256_file(path), build.HMAC_KEY_COMMITMENT)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_19_v3_restricted_mappings_unchanged(self) -> None:
        metadata = load_json(build.I1 / "c4_real_restricted_mapping_metadata_v3.json")
        for name, item in metadata["mapping_files"].items():
            self.assertEqual(sha256_file(build.RESTRICTED / name), item["sha256"])

    def test_20_exactly_558_condition_response_joins(self) -> None:
        self.assertEqual(len(self.conditions), 558)
        self.assertEqual(len({row["replay_record_id"] for row in self.conditions}), 558)

    def test_21_no_response_shared_across_unequal_payloads(self) -> None:
        grouped: dict[str, set[str]] = defaultdict(set)
        for row in self.conditions:
            grouped[row["response_blind_id"]].add(row["provider_payload_sha256"])
        self.assertTrue(all(len(values) == 1 for values in grouped.values()))
        self.assertEqual(558 - len(grouped), 411)

    def test_22_applicability_maps_unchanged(self) -> None:
        memory_scenarios = {
            row["scenario_id"]
            for row in self.conditions
            if row["applicability_source_metadata"]["long_term_memory_relevant"]
        }
        planning_scenarios = {
            row["scenario_id"]
            for row in self.conditions
            if row["applicability_source_metadata"]["request_requires_advice"]
        }
        for row in self.conditions:
            criteria = row["frozen_applicability_map"]["criteria"]
            self.assertTrue(criteria["CLARITY"])
            self.assertTrue(criteria["CONTEXT_AWARENESS"])
            self.assertTrue(criteria["RELIABILITY"])
            self.assertGreaterEqual(sum(criteria.values()), 3)
            if row["scenario_id"] in memory_scenarios:
                self.assertTrue(criteria["PERSONALISATION"])
            if row["scenario_id"] in planning_scenarios:
                self.assertTrue(criteria["ACTIONABILITY"])
        audit = load_json(self.here / "c4_real_r3_applicability_integrity_audit_v1.json")
        self.assertEqual(audit["memory_relevant_family_count"], len(memory_scenarios))
        self.assertEqual(audit["planning_relevant_family_count"], len(planning_scenarios))
        self.assertEqual(
            audit["memory_relevant_records_preserving_personalisation"],
            sum(row["scenario_id"] in memory_scenarios for row in self.conditions),
        )
        self.assertEqual(
            audit["planning_relevant_records_preserving_actionability"],
            sum(row["scenario_id"] in planning_scenarios for row in self.conditions),
        )

    def test_23_judge_dedup_uses_complete_payload(self) -> None:
        audit = load_json(self.here / "c4_real_judge_request_deduplication_audit_v1.json")
        self.assertEqual(audit["deduplication_key"], "COMPLETE_CANONICAL_PROVIDER_PAYLOAD_BYTES")
        self.assertFalse(audit["answer_text_sha256_used_as_deduplication_key"])
        self.assertEqual(len(self.judge), 147)

    def test_24_equal_text_unequal_judge_payloads_remain_separate(self) -> None:
        grouped: dict[str, set[str]] = defaultdict(set)
        for row in self.judge_mapping:
            grouped[row["generation_logical_request_id"]].add(row["judge_logical_request_id"])
        self.assertTrue(grouped[build.KNOWN_DUPLICATE_REQUEST_IDS[0]].isdisjoint(grouped[build.KNOWN_DUPLICATE_REQUEST_IDS[1]]))

    def test_25_judge_requests_are_blind_and_ids_opaque(self) -> None:
        for row in self.judge:
            self.assertRegex(row["logical_judge_request_id"], r"^C4J1-[A-F0-9]{24}$")
            self.assertRegex(row["judge_result_blind_id"], r"^R3B-[A-F0-9]{20}$")
            request = build._extract_blind_request(row["provider_payload"])
            build._forbid_evaluation_identity(request)

    def test_26_scenario_family_atomic_judge_shards(self) -> None:
        shards: dict[str, set[str]] = defaultdict(set)
        for row in self.judge_mapping:
            shards[row["scenario_id"]].add(row["shard_id"])
        self.assertTrue(all(len(value) == 1 for value in shards.values()))
        self.assertEqual({s: sum(row["shard_id"] == s for row in self.judge) for s in "ABC"}, {"A": 49, "B": 49, "C": 49})

    def test_27_judge_runner_and_parser_contract(self) -> None:
        self.assertEqual(EXPECTED_MAX_OUTPUT_TOKENS, 2048)
        config = load_json(self.here / "c4_real_judge_configuration_frozen_r1.json")
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertEqual(config["manual_retry"]["maximum_retries"], 1)
        self.assertFalse(config["manual_retry"]["correction_message_added"])

    def test_27a_judge_runner_full_shard_mocked_transport(self) -> None:
        manifest = load_json(self.here / "c4_real_judge_package_manifest_r1_v1.json")
        package = build.DOWNLOADS / manifest["packages"]["A"]["file_name"]
        client = MockJudgeClient()
        clock = MockClock()
        with tempfile.TemporaryDirectory(prefix="r3d1-runner-success-") as tmp:
            package_dir = Path(tmp) / "package"
            with ZipFile(package) as archive:
                archive.extractall(package_dir)
            output_dir = Path(tmp) / "output"
            status = execute_shard(
                package_dir,
                output_dir,
                client_factory=lambda: client,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
                enforce_runtime=False,
            )
            self.assertEqual(status["judge_calls"], 49)
            self.assertEqual(len(load_jsonl(output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl")), 49)
            self.assertEqual(len(load_jsonl(output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl")), 49)
            self.assertEqual(len(load_jsonl(output_dir / "JUDGE_ERROR_REGISTRY.jsonl")), 0)
            self.assertGreaterEqual(clock.value, 96.0)
        self.assertTrue(client.closed)

    def test_27b_judge_runner_single_byte_identical_retry(self) -> None:
        manifest = load_json(self.here / "c4_real_judge_package_manifest_r1_v1.json")
        package = build.DOWNLOADS / manifest["packages"]["A"]["file_name"]
        client = MockJudgeClient(invalid_json_first=True)
        clock = MockClock()
        with tempfile.TemporaryDirectory(prefix="r3d1-runner-retry-") as tmp:
            package_dir = Path(tmp) / "package"
            with ZipFile(package) as archive:
                archive.extractall(package_dir)
            output_dir = Path(tmp) / "output"
            status = execute_shard(
                package_dir,
                output_dir,
                client_factory=lambda: client,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
                enforce_runtime=False,
            )
            attempts = load_jsonl(output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl")
            self.assertEqual(status["judge_calls"], 50)
            self.assertEqual(len(attempts), 50)
            self.assertEqual(attempts[0]["failure_code"], "INVALID_JSON")
            self.assertEqual(attempts[1]["failure_code"], None)
            self.assertEqual(
                build.canonical_json_bytes(client.calls[0]),
                build.canonical_json_bytes(client.calls[1]),
            )
            self.assertEqual(len(load_jsonl(output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl")), 49)
            self.assertEqual(len(load_jsonl(output_dir / "JUDGE_ERROR_REGISTRY.jsonl")), 0)
        self.assertTrue(client.closed)

    def test_28_parser_rejects_duplicate_keys_and_wrong_applicability(self) -> None:
        request = build._extract_blind_request(self.judge[0]["provider_payload"])
        with self.assertRaises(JudgeResultError):
            parse_judge_result('{"response_blind_id":"R3B-00000000000000000000","response_blind_id":"R3B-11111111111111111111"}', request["frozen_applicability_map"])
        scores = {}
        rationales = {}
        numeric = []
        for criterion, field in SCORE_FIELDS.items():
            if request["frozen_applicability_map"]["criteria"][criterion]:
                scores[field] = "4"
                numeric.append(4)
            else:
                scores[field] = "NA"
            rationales[field] = "Offline test rationale."
        value = {
            "response_blind_id": request["response_blind_id"],
            **scores,
            "evidence_faithfulness": "4",
            "unsupported_claim_count": "0",
            "overall_applicable_mean": str(sum(numeric) / len(numeric)),
            "criterion_rationales": rationales,
            "schema_version": "rq3-judge-response-v2-transport",
        }
        parsed = parse_judge_result(value, request["frozen_applicability_map"])
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)

    def test_29_human_sample_uses_frozen_strata_only(self) -> None:
        sample = load_json(self.here / "c4_real_human_validation_sample_metadata_v1.json")
        self.assertEqual(sample["selected_family_count"], 12)
        self.assertEqual(sample["coverage"]["missing_required_tokens"], 0)
        self.assertFalse(sample["answer_quality_used_for_selection"])
        self.assertFalse(sample["duplicate_text_status_used_for_selection"])

    def test_30_human_packets_same_set_different_order_and_blank(self) -> None:
        self.assertEqual(len(self.packet_a), 108)
        self.assertEqual({row["rating_item_id"] for row in self.packet_a}, {row["rating_item_id"] for row in self.packet_b})
        self.assertNotEqual([row["rating_item_id"] for row in self.packet_a], [row["rating_item_id"] for row in self.packet_b])
        fields = [name for name in self.packet_a[0] if name.endswith(("_rating", "_rationale"))]
        self.assertTrue(all(all(row[name] == "" for name in fields) for row in [*self.packet_a, *self.packet_b]))

    def test_31_packages_and_zero_execution_boundary(self) -> None:
        judge_manifest = load_json(self.here / "c4_real_judge_package_manifest_r1_v1.json")
        for shard in "ABC":
            path = build.DOWNLOADS / judge_manifest["packages"][shard]["file_name"]
            self.assertEqual(sha256_file(path), judge_manifest["packages"][shard]["sha256"])
            with ZipFile(path) as archive:
                self.assertNotIn("c4_real_i1_blinding_hmac_key.bin", archive.namelist())
        self.assertEqual(load_json(self.here / "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT.json")["judge_calls"], 0)
        self.assertEqual(load_json(self.here / "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT.json")["completed_ratings"], 0)

    def test_32_runner_refuses_existing_output_without_transport(self) -> None:
        manifest = load_json(self.here / "c4_real_judge_package_manifest_r1_v1.json")
        package = build.DOWNLOADS / manifest["packages"]["A"]["file_name"]
        with tempfile.TemporaryDirectory(prefix="r3d1-runner-refusal-") as tmp:
            package_dir = Path(tmp) / "package"
            package_dir.mkdir()
            with ZipFile(package) as archive:
                archive.extractall(package_dir)
            existing = Path(tmp) / "existing"
            existing.mkdir()
            with self.assertRaises(RunnerError):
                execute_shard(package_dir, existing, enforce_runtime=False)

    def test_33_independent_validator_passes(self) -> None:
        result = validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks_failed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
