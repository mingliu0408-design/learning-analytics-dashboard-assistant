#!/usr/bin/env python3
"""Offline integration tests for the governed G2D0 repair and R3 package freeze."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import unittest
import zipfile

from evaluation.rq3_real_c4.g2d0_response_format_repair.c4_real_generation_request_renderer_v3 import (
    render_generation_request_v3,
)
from evaluation.rq3_real_c4.g2d0_response_format_repair.c4_real_student_facing_response_validator_v1 import (
    VALID_STUDENT_FACING_RESPONSE,
    validate_answer_text,
)
from evaluation.rq3_real_c4.g2d0_response_format_repair.generation_execution_runner_v3 import (
    validate_response_content,
)
from evaluation.rq3_real_c4.g2d0_response_format_repair.generation_package_validator_v3 import (
    ALLOWED_FILES,
    validate_zip,
)


ROOT = Path(__file__).resolve().parents[3]
REPAIR = Path(__file__).resolve().parent
I1 = ROOT / "evaluation/rq3_real_c4/i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
DOWNLOADS = Path("/Users/liuming/Downloads")
BASE = "2fd113d7c2d64442bb939cbd7aee80cab0ab4178"
ORIGINAL_COMMITS = (
    "cfd169dd6773a0eabec611c6324b757326da7ef4",
    "4038bd44eaabaf5ec99f5164494ddad16f6981f6",
    "000f5e9cd88413967811f005944b60a5aa29d761",
)
INTEGRATED_COMMITS = (
    "4602f1d092e90e3a2ca44f22e2b24905ffa72a8c",
    "61a94b7926f2da83764fbccc6159bbcd1a23d39d",
    "2c1094d6486d5db8d01d8a4ef02e11f15d1813e9",
)
JOURNALS = (
    (
        "A",
        ROOT / "evaluation/rq3_real_c4/g2a_generation_shard_a/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "a106e593a6cbb1b886634c4b349af50d072afa5d30801e469158fd38449979eb",
        73,
    ),
    (
        "B",
        ROOT / "evaluation/rq3_real_c4/g2b_generation_shard_b/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "5ab86bb3a440ff907894c0b3afc6e1c0f985ac55ea5e2fcdcaffae3bff9d4858",
        62,
    ),
    (
        "C",
        ROOT / "evaluation/rq3_real_c4/g2c_generation_shard_c/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "d91c60aebdcde9103b9bfec62ae0b8d387b79e7d1a275dc22c8ee034168786ef",
        62,
    ),
)
PACKAGE_PATHS = {
    shard: DOWNLOADS / f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R3_2026-09-01.zip"
    for shard in "ABC"
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, capture_output=True, text=True
    )


class G2D0RepairTests(unittest.TestCase):
    maxDiff = None

    def test_01_three_generation_commits_integrated_in_exact_order(self) -> None:
        for commit in ORIGINAL_COMMITS:
            self.assertEqual(git("rev-parse", f"{commit}^").stdout.strip(), BASE)
        expected_parents = (BASE, INTEGRATED_COMMITS[0], INTEGRATED_COMMITS[1])
        for commit, parent in zip(INTEGRATED_COMMITS, expected_parents):
            self.assertEqual(git("rev-parse", f"{commit}^").stdout.strip(), parent)
        source_manifest = json.loads(
            (REPAIR / "c4_real_g2_response_source_manifest_v1.json").read_text()
        )
        mappings = source_manifest["original_to_cherry_picked_commit_mapping"]
        self.assertEqual(
            [(row["original_generation_commit"], row["cherry_picked_commit"]) for row in mappings],
            list(zip(ORIGINAL_COMMITS, INTEGRATED_COMMITS)),
        )

    def test_02_g2_journals_answers_population_model_and_usage_immutable(self) -> None:
        records: list[dict[str, object]] = []
        for shard, path, expected_hash, expected_count in JOURNALS:
            self.assertEqual(sha256(path), expected_hash)
            shard_records = jsonl(path)
            self.assertEqual(len(shard_records), expected_count)
            original = subprocess.check_output(
                ["git", "show", f"{ORIGINAL_COMMITS['ABC'.index(shard)]}:{path.relative_to(ROOT)}"],
                cwd=ROOT,
            )
            self.assertEqual(path.read_bytes(), original)
            records.extend(shard_records)
        self.assertEqual(len(records), 197)
        self.assertEqual(len({row["logical_generation_request_id"] for row in records}), 197)
        self.assertEqual(len({row["response_blind_id"] for row in records}), 197)
        self.assertEqual({row["returned_model"] for row in records}, {"gpt-4o-mini-2024-07-18"})
        self.assertTrue(all(row["physical_attempts"] == 1 for row in records))
        self.assertTrue(all(row["terminal_status"] == "VALID_RESPONSE" for row in records))
        usage = {
            field: sum(int(row[field]) for row in records)
            for field in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens")
        }
        self.assertEqual(
            usage,
            {
                "prompt_tokens": 120366,
                "cached_input_tokens": 5120,
                "completion_tokens": 25597,
                "total_tokens": 145963,
            },
        )

    def test_03_blind_audit_is_deterministic_frozen_and_unscored(self) -> None:
        completed = subprocess.run(
            [
                "/opt/anaconda3/bin/python3",
                str(REPAIR / "build_g2_blind_format_audit.py"),
                "--verify-only",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertIn("BLIND_G2_FORMAT_AUDIT_VERIFIED", completed.stdout)
        audit = json.loads((REPAIR / "c4_real_g2_prejudge_format_audit_v1.json").read_text())
        self.assertEqual(
            audit["classification_counts"],
            {
                "NATURAL_LANGUAGE_RESPONSE": 153,
                "RAW_EVIDENCE_OR_PLANNING_DUMP": 1,
                "SERIALIZED_JSON_OBJECT_OR_ARRAY": 27,
                "TRIVIAL_NONANSWER": 16,
            },
        )
        self.assertEqual(audit["non_student_facing_response_count"], 44)
        self.assertFalse(audit["restricted_mapping_accessed"])
        self.assertTrue(all("score" not in key.casefold() for row in audit["records"] for key in row))
        receipt = json.loads(
            (REPAIR / "c4_real_g2_blind_format_audit_freeze_receipt_v1.json").read_text()
        )
        self.assertTrue(receipt["classification_frozen_before_restricted_mapping_access"])
        for name, expected_hash in receipt["frozen_artifact_sha256"].items():
            self.assertEqual(sha256(REPAIR / name), expected_hash)

    def test_04_aggregate_unblinding_did_not_change_classifications(self) -> None:
        before = sha256(REPAIR / "c4_real_g2_prejudge_format_audit_v1.json")
        completed = subprocess.run(
            ["/opt/anaconda3/bin/python3", str(REPAIR / "build_g2_restricted_aggregate_audit.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertIn("G2_RESTRICTED_AGGREGATE_AUDIT_FROZEN", completed.stdout)
        self.assertEqual(sha256(REPAIR / "c4_real_g2_prejudge_format_audit_v1.json"), before)
        aggregate = json.loads(
            (REPAIR / "c4_real_g2_restricted_aggregate_format_bias_audit_v1.json").read_text()
        )
        self.assertEqual(aggregate["overall"]["affected_unique_request_count"], 44)
        self.assertEqual(aggregate["overall"]["affected_condition_mapping_count"], 100)
        self.assertEqual(aggregate["overall"]["condition_mapping_count"], 558)
        self.assertEqual(
            aggregate["by_planning_support"]["PRESENT"]["affected_unique_request_count"], 22
        )
        self.assertEqual(aggregate["by_planning_support"]["PRESENT"]["unique_request_count"], 26)
        self.assertTrue(aggregate["independent_observation_check"]["verified"])
        self.assertFalse(aggregate["classification_changed_after_unblinding"])
        self.assertFalse(aggregate["quality_scores_calculated"])

    def test_05_format_validator_required_cases(self) -> None:
        rejected = (
            "{",
            "[",
            "{}",
            "[]",
            '{"action_steps":["Do this"]}',
            '["raw array"]',
            "{'evidence': {'content': 'raw'}}",
        )
        accepted = (
            "Yes.",
            "Review the Week 4 lecture.",
            "- Review the lecture\n- Write one note",
            "1. Review the lecture\n2. Write one note",
        )
        for value in rejected:
            self.assertNotEqual(validate_answer_text(value), VALID_STUDENT_FACING_RESPONSE)
        for value in accepted:
            self.assertEqual(validate_answer_text(value), VALID_STUDENT_FACING_RESPONSE)
        self.assertEqual(validate_response_content("not-json")[1], "INVALID_JSON")
        self.assertEqual(
            validate_response_content('{"wrong":"field"}')[1],
            "STRICT_SCHEMA_VALIDATION_FAILED",
        )
        self.assertEqual(
            validate_response_content(json.dumps({"answer_text": "{"}))[1],
            "NON_STUDENT_FACING_FORMAT",
        )

    def test_06_g2_excluded_before_judge_and_no_g2_judge_manifest(self) -> None:
        disclosure = (
            REPAIR / "C4_REAL_G2_PREJUDGE_EXCLUSION_AND_REGENERATION_DISCLOSURE.md"
        ).read_text()
        self.assertIn(
            "COMPLETE_PROVIDER_EXECUTION_EXCLUDED_FROM_PRIMARY_EVALUATION_BEFORE_JUDGING",
            disclosure,
        )
        self.assertIn("No Judge manifest", disclosure)
        for shard_dir in (
            ROOT / "evaluation/rq3_real_c4/g2a_generation_shard_a",
            ROOT / "evaluation/rq3_real_c4/g2b_generation_shard_b",
            ROOT / "evaluation/rq3_real_c4/g2c_generation_shard_c",
        ):
            self.assertFalse(any("judge" in path.name.casefold() for path in shard_dir.rglob("*")))

    def test_07_v3_prompt_renderer_and_zero_substantive_mismatch(self) -> None:
        prompt = (REPAIR / "c4_real_generation_prompt_frozen_v3.txt").read_text()
        for phrase in (
            "complete natural-language reply addressed to the student",
            "Do not begin answer_text with \"{\" or \"[\"",
            "ordinary prose or concise Markdown bullets",
            "short complete sentence",
        ):
            self.assertIn(phrase, prompt)
        diff = json.loads(
            (REPAIR / "c4_real_generation_renderer_v2_v3_diff_audit.json").read_text()
        )
        self.assertEqual(diff["condition_count"], 558)
        self.assertEqual(diff["substantive_evidence_mismatch_count"], 0)
        self.assertEqual(diff["planning_content_mismatch_count"], 0)
        self.assertEqual(diff["v3_raw_json_object_or_array_user_message_count"], 0)
        self.assertEqual(
            diff["source_substantive_fact_occurrence_count"],
            diff["rendered_substantive_fact_occurrence_count"],
        )
        for row in jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl"):
            user_message = row["provider_payload"]["messages"][1]["content"]
            with self.assertRaises(json.JSONDecodeError):
                json.loads(user_message)
            self.assertIn("CURRENT LAD PAGE\n", user_message)
            self.assertIn("STUDENT REQUEST\n", user_message)

    def test_08_outer_schema_bytes_and_provider_configuration_preserved(self) -> None:
        schema_path = I1 / "c4_real_generation_schema_v2_provider_compatible.json"
        self.assertEqual(
            sha256(schema_path),
            "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873",
        )
        config = json.loads((I1 / "c4_real_generation_configuration_frozen_v3.json").read_text())
        self.assertEqual(config["model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 512)
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertFalse(config["streaming"])
        self.assertEqual(config["tools"], "NONE")
        source = (REPAIR / "generation_execution_runner_v3.py").read_text()
        self.assertLess(
            source.index("parsed = json.loads(raw_content)"),
            source.index("semantic_status = validate_answer_text(answer_text)"),
        )

    def test_09_all_558_conditions_rebuilt_and_v3_dedup_is_deterministic(self) -> None:
        completed = subprocess.run(
            [
                "/opt/anaconda3/bin/python3",
                str(REPAIR / "build_v3_regeneration_artifacts.py"),
                "--verify-only",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertIn("V3_REGENERATION_ARTIFACTS_VERIFIED", completed.stdout)
        summary = json.loads(
            (I1 / "c4_real_generation_request_deduplication_summary_v3.json").read_text()
        )
        self.assertEqual(summary["condition_mapping_count"], 558)
        self.assertEqual(summary["v3_unique_request_count"], 147)
        self.assertEqual(summary["v3_duplicate_mapping_count"], 411)
        self.assertFalse(summary["unique_request_count_forced_to_197"])
        self.assertEqual(len(jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")), 147)

    def test_10_hmac_commitment_v3_mapping_integrity_and_no_id_reuse(self) -> None:
        key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
        self.assertEqual(
            sha256(key_path),
            "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5",
        )
        self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
        self.assertNotEqual(
            git("check-ignore", "-q", str(key_path.relative_to(ROOT)), check=False).returncode,
            1,
        )
        metadata = json.loads((I1 / "c4_real_restricted_mapping_metadata_v3.json").read_text())
        self.assertEqual(metadata["hmac_key_sha256_commitment"], sha256(key_path))
        for name, entry in metadata["mapping_files"].items():
            path = RESTRICTED / name
            self.assertEqual(sha256(path), entry["sha256"])
            self.assertEqual(entry["row_count"], 558)
            self.assertNotEqual(
                git("check-ignore", "-q", str(path.relative_to(ROOT)), check=False).returncode,
                1,
            )
            self.assertNotEqual(
                git("ls-files", "--error-unmatch", str(path.relative_to(ROOT)), check=False).returncode,
                0,
            )
        g2_ids = {
            row["opaque_response_blind_id"]
            for row in json.loads((REPAIR / "c4_real_g2_prejudge_format_audit_v1.json").read_text())[
                "records"
            ]
        }
        v3_ids = {
            row["response_blind_id"]
            for row in jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")
        }
        self.assertFalse(g2_ids & v3_ids)

    def test_11_scenario_atomic_three_shard_assignment(self) -> None:
        rows = csv_rows(RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v3.csv")
        self.assertEqual(len(rows), 558)
        by_scenario: dict[str, set[str]] = defaultdict(set)
        by_request: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            by_scenario[row["scenario_id"]].add(row["shard_id"])
            by_request[row["logical_generation_request_id"]].add(row["shard_id"])
        self.assertTrue(all(len(shards) == 1 for shards in by_scenario.values()))
        self.assertTrue(all(len(shards) == 1 for shards in by_request.values()))
        summary = json.loads((I1 / "c4_real_generation_shard_summary_v3.json").read_text())
        self.assertEqual({row["shard_id"] for row in summary["shards"]}, {"A", "B", "C"})
        self.assertEqual(sum(row["unique_request_count"] for row in summary["shards"]), 147)
        self.assertEqual(sum(row["maximum_physical_attempt_count"] for row in summary["shards"]), 294)

    def test_12_r3_packages_exact_allowlist_hashes_and_no_restricted_content(self) -> None:
        manifest = json.loads((I1 / "c4_real_generation_package_manifest_v3.json").read_text())
        self.assertEqual(manifest["package_count"], 3)
        self.assertEqual(manifest["unique_request_count"], 147)
        self.assertEqual(manifest["maximum_physical_attempts"], 294)
        for report in manifest["packages"]:
            path = Path(report["path"])
            self.assertEqual(sha256(path), report["sha256"])
            validated = validate_zip(path)
            self.assertEqual(validated["status"], "PASS")
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), ALLOWED_FILES)
                joined_names = "\n".join(archive.namelist()).casefold()
                for prohibited in (
                    "response_to_condition",
                    "hmac_key",
                    "terminal_journal",
                    "judge",
                    "sqlite",
                ):
                    self.assertNotIn(prohibited, joined_names)

    def test_13_runner_retry_contract_is_frozen_and_mock_tested(self) -> None:
        manifest = json.loads((I1 / "c4_real_generation_package_manifest_v3.json").read_text())
        self.assertTrue(all(row["offline_test_count"] == 9 for row in manifest["packages"]))
        source = (REPAIR / "generation_execution_runner_v3.py").read_text()
        for marker in (
            "INVALID_JSON",
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "NON_STUDENT_FACING_FORMAT",
            "RETRY_PAYLOAD_BYTES_CHANGED",
            "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE",
            "append_fsync(attempts_path, record)",
        ):
            self.assertIn(marker, source)

    def test_14_zero_provider_regeneration_judge_scoring_or_streamlit_calls(self) -> None:
        for path in (
            I1 / "c4_real_condition_payload_rebuild_summary_v3.json",
            I1 / "c4_real_generation_package_manifest_v3.json",
            REPAIR / "c4_real_generation_renderer_v2_v3_diff_audit.json",
        ):
            value = json.loads(path.read_text())
            self.assertEqual(value.get("provider_calls"), 0)
            self.assertEqual(value.get("generation_calls", 0), 0)
            self.assertEqual(value.get("judge_calls", 0), 0)
            self.assertEqual(value.get("scoring_calls", 0), 0)
            self.assertEqual(value.get("streamlit_launches", 0), 0)
        self.assertFalse(any(REPAIR.rglob("GENERATION_TERMINAL_JOURNAL.jsonl")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
