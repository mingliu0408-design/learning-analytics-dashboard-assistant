#!/usr/bin/env python3
"""Offline-only mechanical tests for RQ3-REAL-C4-R3D0."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RQ3 = REPO / "evaluation" / "rq3_real_c4"
G2D0 = RQ3 / "g2d0_response_format_repair"
I1 = RQ3 / "i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
ORIGINAL_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_EXECUTION_PACKAGE_R3_2026-09-01.zip"
)
CONTINUATION_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3C1_2026-09-02.zip"
)
SHARDS = {
    "A": RQ3 / "r3a_response_regeneration_shard_a",
    "B": RQ3 / "r3b_response_regeneration_shard_b",
    "C": RQ3 / "r3c_response_regeneration_shard_c",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = load_module("r3d0_test_v1", G2D0 / "c4_real_student_facing_response_validator_v1.py")
V2 = load_module("r3d0_test_v2", HERE / "c4_real_student_facing_response_validator_v2.py")


class R3D0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.before = load_json(HERE / "c4_real_r3_source_preservation_manifest_before_v1.json")
        cls.reclassification = load_jsonl(
            HERE / "r3_existing_attempt_format_reclassification_v2.jsonl"
        )
        cls.reclassification_summary = load_json(
            HERE / "r3_existing_attempt_format_reclassification_summary_v2.json"
        )
        cls.canonical = load_jsonl(
            HERE / "c4_real_r3_existing_canonical_response_selection_v1.jsonl"
        )
        cls.selection_audit = load_json(
            HERE / "c4_real_r3_canonical_attempt_selection_audit_v1.json"
        )
        cls.remaining = load_jsonl(HERE / "c4_real_r3c_remaining_request_manifest_v1.jsonl")
        cls.source_audit = load_json(HERE / "c4_real_r3c_continuation_source_audit_v1.json")
        cls.boundary = load_json(HERE / "c4_real_r3_primary_response_completion_boundary_v1.json")
        cls.package_audit = load_json(
            HERE / "c4_real_r3c_continuation_package_freeze_audit_v1.json"
        )

    def test_01_three_commits_integrated_in_exact_order(self) -> None:
        expected = [
            ("cd2d9f2b285bd410420fbec4ac301c2f5bf84263", "e647bb42d270b4f24ad543f9f6010e6b43ee4ed4"),
            ("2b6d3f0cb52171c8d3db0680795089469435ce17", "cd2d9f2b285bd410420fbec4ac301c2f5bf84263"),
            ("6a9a362d280acd53aa0398b82a754360fd28d082", "2b6d3f0cb52171c8d3db0680795089469435ce17"),
        ]
        for commit, parent in expected:
            observed = subprocess.check_output(
                ["git", "rev-parse", f"{commit}^"], cwd=REPO, text=True
            ).strip()
            self.assertEqual(observed, parent)

    def test_02_original_execution_files_match_before_manifest(self) -> None:
        for identity in self.before["original_r3_files"]:
            path = REPO / identity["path"]
            self.assertEqual(path.stat().st_size, identity["bytes"])
            self.assertEqual(sha256_file(path), identity["sha256"])

    def test_03_required_historical_terminal_and_answer_set_hashes(self) -> None:
        expected = self.before["historical_execution_identity"]
        for shard, directory in SHARDS.items():
            terminal = directory / "execution_output_v1" / "GENERATION_TERMINAL_JOURNAL.jsonl"
            self.assertEqual(sha256_file(terminal), expected[shard]["terminal_journal_sha256"])
            audit = load_json(directory / "generation_execution_audit_v1.json")
            answer_set = audit["hashes"]["answer_set_sha256"] if shard == "C" else audit["answer_set_sha256"]
            self.assertEqual(answer_set, expected[shard]["answer_set_sha256"])

    def test_04_v1_false_positive_reproduced_with_synthetic_dashboard_prose(self) -> None:
        text = "Use the following dashboard evidence:\n\n- Review one lecture."
        self.assertEqual(V1.validate_answer_text(text), V1.RAW_INTERNAL_STRUCTURE)

    def test_05_v1_false_positive_reproduced_with_synthetic_activity_prose(self) -> None:
        text = "Consider this activity evidence:\n\n- Revisit Week 2."
        self.assertEqual(V1.validate_answer_text(text), V1.RAW_INTERNAL_STRUCTURE)

    def test_06_v2_accepts_dashboard_evidence_prose(self) -> None:
        self.assertEqual(
            V2.validate_answer_text("Use your dashboard evidence:\n\n- Review Week 2."),
            V2.VALID_STUDENT_FACING_RESPONSE,
        )

    def test_07_v2_accepts_activity_course_and_the_evidence_prose(self) -> None:
        values = (
            "Use your activity evidence:",
            "Use the course evidence:",
            "The evidence:",
            "This sentence ends with evidence:",
        )
        self.assertTrue(
            all(V2.validate_answer_text(value) == V2.VALID_STUDENT_FACING_RESPONSE for value in values)
        )

    def test_08_v2_accepts_markdown_headings_and_spaced_labels(self) -> None:
        value = "## Focus:\n\n**Debate Activity:** Review one post.\n\n**Lecture Video Activity:** Rewatch Week 2."
        self.assertEqual(V2.validate_answer_text(value), V2.VALID_STUDENT_FACING_RESPONSE)

    def test_09_v2_rejects_json_object_and_array_strings(self) -> None:
        for value in ('{"answer_text":"raw"}', '["raw"]'):
            self.assertEqual(V2.validate_answer_text(value), V2.SERIALIZED_JSON_OBJECT_OR_ARRAY)

    def test_10_v2_rejects_python_dict_and_list_strings(self) -> None:
        for value in ("{'action_steps': ['Review']}", "['raw']"):
            self.assertEqual(V2.validate_answer_text(value), V2.RAW_INTERNAL_STRUCTURE)

    def test_11_v2_rejects_line_start_internal_snake_case_fields(self) -> None:
        for key in V2.STRONG_INTERNAL_FIELD_KEYS:
            self.assertEqual(
                V2.validate_answer_text(f"{key}:\n- value"), V2.RAW_INTERNAL_STRUCTURE, key
            )

    def test_12_v2_does_not_reject_spaced_internal_concepts(self) -> None:
        value = "Your recommended action: review the next step and supporting evidence."
        self.assertEqual(V2.validate_answer_text(value), V2.VALID_STUDENT_FACING_RESPONSE)

    def test_13_v2_rejects_fenced_and_xml_structures(self) -> None:
        values = (
            "```\nordinary text\n```",
            "```json\n{\"answer_text\":\"raw\"}\n```",
            "<response>raw</response>",
            "<?xml version=\"1.0\"?><response/>",
        )
        self.assertTrue(all(V2.validate_answer_text(value) != V2.VALID_STUDENT_FACING_RESPONSE for value in values))

    def test_14_v2_rejects_nonstring_empty_and_punctuation_only(self) -> None:
        self.assertEqual(V2.validate_answer_text(None), V2.OTHER_NON_STUDENT_FACING_FORMAT)
        for value in ("", "   ", "{}[]!!!"):
            self.assertEqual(V2.validate_answer_text(value), V2.TRIVIAL_NONANSWER)

    def test_15_all_106_attempts_reclassified_deterministically(self) -> None:
        observed = []
        for shard, directory in SHARDS.items():
            attempts = load_jsonl(directory / "execution_output_v1" / "GENERATION_ATTEMPT_JOURNAL.jsonl")
            for attempt in attempts:
                parsed = json.loads(attempt["raw_response_content"])
                answer = parsed["answer_text"]
                observed.append(
                    (
                        shard,
                        attempt["logical_order"],
                        attempt["attempt_number"],
                        V1.validate_answer_text(answer),
                        V2.validate_answer_text(answer),
                    )
                )
        frozen = [
            (
                row["shard"],
                row["logical_order"],
                row["attempt_number"],
                row["v1_classification"],
                row["v2_classification"],
            )
            for row in self.reclassification
        ]
        self.assertEqual(len(observed), 106)
        self.assertEqual(observed, frozen)

    def test_16_only_three_expected_classifications_change(self) -> None:
        changed = {
            (row["shard"], row["logical_order"], row["attempt_number"])
            for row in self.reclassification
            if row["classification_changed"]
        }
        self.assertEqual(changed, {("A", 40, 1), ("C", 4, 1), ("C", 4, 2)})

    def test_17_reclassification_is_blind_and_precedes_mapping_access(self) -> None:
        self.assertEqual(
            self.reclassification_summary["operation_order"],
            "COMPLETED_BEFORE_ANY_CONDITION_OR_MODE_MAPPING_ACCESS",
        )
        self.assertEqual(
            self.reclassification_summary["condition_mode_route_gold_or_expected_outcome_accesses"],
            0,
        )
        prohibited = {"scenario_id", "mode", "condition", "route", "gold", "expected_capability", "page"}
        self.assertTrue(all(prohibited.isdisjoint(row) for row in self.reclassification))

    def test_18_canonical_rule_is_exact_earliest_valid_v2(self) -> None:
        rule = load_json(HERE / "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json")
        self.assertEqual(rule["status"], "FROZEN_UNIFORM_BLIND_MECHANICAL_RULE")
        self.assertEqual(len(rule["steps"]), 6)
        self.assertIn("earliest attempt", rule["steps"][3])

    def test_19_a_order_40_selects_attempt_1(self) -> None:
        row = next(row for row in self.canonical if row["shard"] == "A" and row["logical_order"] == 40)
        self.assertEqual(row["selected_attempt_number"], 1)

    def test_20_c_order_4_selects_attempt_1(self) -> None:
        row = next(row for row in self.canonical if row["shard"] == "C" and row["logical_order"] == 4)
        self.assertEqual(row["selected_attempt_number"], 1)

    def test_21_original_retry_attempts_remain_and_are_labelled_redundant(self) -> None:
        retries = {
            (row["shard"], row["logical_order"], row["attempt_number"])
            for row in self.selection_audit["redundant_retries"]
        }
        self.assertEqual(retries, {("A", 40, 2), ("C", 4, 2)})
        for shard, order, attempt_number in retries:
            source = load_jsonl(
                SHARDS[shard] / "execution_output_v1" / "GENERATION_ATTEMPT_JOURNAL.jsonl"
            )
            self.assertTrue(
                any(row["logical_order"] == order and row["attempt_number"] == attempt_number for row in source)
            )

    def test_22_exact_canonical_counts_by_shard(self) -> None:
        counts = Counter(row["shard"] for row in self.canonical)
        self.assertEqual(counts, {"A": 50, "B": 50, "C": 4})
        self.assertEqual(len(self.canonical), 104)

    def test_23_exact_remaining_count_and_orders_5_through_47(self) -> None:
        self.assertEqual(len(self.remaining), 43)
        orders = [row["original_shard_c_logical_order"] for row in self.source_audit["row_identity_audit"]]
        self.assertEqual(orders, list(range(5, 48)))

    def test_24_continuation_rows_are_byte_identical_source_slice(self) -> None:
        with zipfile.ZipFile(ORIGINAL_PACKAGE) as archive:
            lines = archive.read("BLINDED_REQUESTS.jsonl").splitlines(keepends=True)
        self.assertEqual((HERE / "c4_real_r3c_remaining_request_manifest_v1.jsonl").read_bytes(), b"".join(lines[4:]))

    def test_25_all_43_provider_payloads_and_ids_are_preserved(self) -> None:
        with zipfile.ZipFile(ORIGINAL_PACKAGE) as archive:
            source = [json.loads(line) for line in archive.read("BLINDED_REQUESTS.jsonl").splitlines()][4:]
        self.assertEqual(self.remaining, source)
        for row in self.remaining:
            self.assertEqual(sha256_bytes(canonical_bytes(row["provider_payload"])), row["provider_payload_sha256"])

    def test_26_selected_and_remaining_partition_exact_frozen_147(self) -> None:
        universe = load_jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")
        selected_ids = {row["logical_generation_request_id"] for row in self.canonical}
        remaining_ids = {row["logical_generation_request_id"] for row in self.remaining}
        universe_ids = {row["logical_generation_request_id"] for row in universe}
        self.assertTrue(selected_ids.isdisjoint(remaining_ids))
        self.assertEqual(selected_ids | remaining_ids, universe_ids)
        self.assertEqual((len(selected_ids), len(remaining_ids), len(universe_ids)), (104, 43, 147))

    def test_27_hmac_and_v3_mapping_identities_unchanged(self) -> None:
        for identity in self.before["restricted_identity_only_check"]["files"]:
            self.assertEqual(sha256_file(REPO / identity["path"]), identity["sha256"])

    def test_28_continuation_package_allowlist_and_hashes(self) -> None:
        with zipfile.ZipFile(CONTINUATION_PACKAGE) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(self.package_audit["package_member_allowlist"]))
            self.assertEqual(len(names), 12)
            for name, expected in self.package_audit["package_member_sha256"].items():
                self.assertEqual(sha256_bytes(archive.read(name)), expected)
        self.assertEqual(sha256_file(CONTINUATION_PACKAGE), self.package_audit["package_sha256"])

    def test_29_continuation_runtime_sdk_and_transport_contract(self) -> None:
        with zipfile.ZipFile(CONTINUATION_PACKAGE) as archive:
            contract = json.loads(archive.read("EXECUTION_CONTRACT.json"))
            config = json.loads(archive.read("GENERATION_CONFIGURATION.json"))
        self.assertEqual(contract["runtime"]["python_path"], "/opt/anaconda3/bin/python3")
        self.assertEqual(contract["runtime"]["python_version"], "3.13.5")
        self.assertEqual(contract["runtime"]["openai_sdk_version"], "1.109.1")
        self.assertEqual(config["model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertEqual(config["max_output_tokens"], 512)
        self.assertEqual(config["temperature"], 0)
        self.assertIs(config["streaming"], False)
        self.assertEqual(config["tools"], "NONE")

    def test_30_continuation_runner_fail_closed_markers(self) -> None:
        source = (HERE / "generation_execution_runner_v3_1.py").read_text(encoding="utf-8")
        markers = (
            "OpenAI(max_retries=0)",
            "MAX_ATTEMPTS_PER_REQUEST = 2",
            "append_fsync(attempts_path, record)",
            "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE",
            "return stop_before_or_during_requests",
            "Refusing overwrite or automatic resume",
            "AUTHORIZED_C4_REAL_SHARD_C_CONTINUATION_R3C1",
        )
        self.assertTrue(all(marker in source for marker in markers))

    def test_31_continuation_package_is_dormant_and_zero_real_calls(self) -> None:
        self.assertIs(self.package_audit["continuation_executed"], False)
        self.assertEqual(self.package_audit["real_provider_network_calls"], 0)
        self.assertEqual(self.package_audit["response_generation_calls"], 0)
        self.assertEqual(self.package_audit["judge_calls"], 0)
        self.assertEqual(self.package_audit["scoring_calls"], 0)
        self.assertEqual(self.package_audit["human_rating_actions"], 0)
        self.assertEqual(self.package_audit["condition_unblinding_actions"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
