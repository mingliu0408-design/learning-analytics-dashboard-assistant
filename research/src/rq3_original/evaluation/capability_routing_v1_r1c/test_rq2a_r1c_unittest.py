"""Contract tests for RQ2-A-R1C provenance and context-link repair."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

from evaluation.capability_routing_v1_r1b.authentic_source_authority import (
    load_authentic_rows,
)

from . import (
    AUTHENTIC_SOURCE_SHA256,
    HERE,
    LOCAL_AUTHENTIC_BANK_RELATIVE,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_MAPPING_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    LOCAL_SYNTHETIC_BANK_RELATIVE,
    PREVIOUS_CONTEXT_CASE_IDS,
    R1B_AUTHENTIC_BANK_RELATIVE,
    R1B_SYNTHETIC_BANK_SHA256,
    ROOT,
    RQ2A_R1B_HEAD,
    TARGET_BRANCH,
    reject_prohibited_track_path,
    sha256_file,
)
from .adjudication_contract_v1_3 import (
    AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS,
    adjudication_reasons,
    validate_adjudication_record,
)
from .agreement_contract_v1_3 import calculate_source_stratified_agreement
from .authentic_context_link_correction import build_corrected_authentic_cases
from .human_review_schema_v1_3 import HUMAN_FIELDS, VISIBLE_FIELDS, validate_blank_packet
from .provenance_attestation import build_provenance_attestation
from .validate_rq2a_r1c import (
    PYTHON_FILES,
    assert_all_python_ast,
    assert_change_scope,
    assert_double_build,
    assert_gitignore_contract,
    assert_local_outputs,
    assert_no_provider_network_surface,
    assert_old_packets_unchanged,
    assert_starting_lineage,
    build_all,
    governed_text_leak_scan,
    output_checksum_targets,
    validate_output_checksums,
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _packet(relative: Path) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _completed_fixture(row: dict[str, str], reviewer_id: str) -> dict[str, str]:
    value = dict(row)
    has_history = bool(value["necessary_conversation_history"])
    value.update(
        {
            "case_validity": "INCLUDE_VALID_CASE",
            "query_naturalness_1_to_5": "4",
            "context_link_valid": "YES" if has_history else "NOT_APPLICABLE",
            "context_sufficient": "YES" if has_history else "NOT_APPLICABLE",
            "capability_unambiguous": "YES",
            "context_resolution_required": "NO",
            "dashboard_evidence": "YES",
            "course_retrieval": "NO",
            "episodic_memory": "NO",
            "planning": "NO",
            "safe_direct_response": "NO",
            "clarification": "NO",
            "forbidden_capabilities": "",
            "reviewer_rationale": "fixture rationale",
            "reviewer_id": reviewer_id,
            "review_date": "2026-08-26",
        }
    )
    return value


class RQ2AR1CTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build_all()
        cls.source_rows, cls.source_identity = load_authentic_rows(ROOT)
        cls.attestation = build_provenance_attestation(ROOT)
        cls.authentic = _jsonl(ROOT / LOCAL_AUTHENTIC_BANK_RELATIVE)
        cls.synthetic = _jsonl(ROOT / LOCAL_SYNTHETIC_BANK_RELATIVE)
        cls.combined = _jsonl(ROOT / LOCAL_COMBINED_BANK_RELATIVE)
        cls.mapping = _jsonl(ROOT / LOCAL_MAPPING_RELATIVE)
        cls.rows_a = _packet(LOCAL_REVIEW_A_RELATIVE)
        cls.rows_b = _packet(LOCAL_REVIEW_B_RELATIVE)

    def test_01_starting_head(self) -> None:
        assert_starting_lineage()
        import subprocess

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(branch, TARGET_BRANCH)
        self.assertTrue(RQ2A_R1B_HEAD)

    def test_02_authentic_csv_hash(self) -> None:
        self.assertEqual(self.source_identity["sha256"], AUTHENTIC_SOURCE_SHA256)

    def test_03_twenty_five_user_turns(self) -> None:
        self.assertEqual(sum(row["role"] == "user" for row in self.source_rows), 25)

    def test_04_twenty_five_assistant_outputs(self) -> None:
        self.assertEqual(sum(row["role"] == "assistant" for row in self.source_rows), 25)

    def test_05_authentic_student_origin_true(self) -> None:
        role = json.loads((HERE / "authentic_bank_role_v1_1.json").read_text())
        self.assertTrue(role["authentic_student_origin"])
        self.assertEqual(role["student_origin_confirmation"], "USER_EXPLICIT_ATTESTATION")

    def test_06_assistant_original_gpt4_true(self) -> None:
        self.assertEqual(self.attestation["role_assistant_origin"], "ORIGINAL_DEPLOYMENT_GPT4_OUTPUTS")
        role = json.loads((HERE / "authentic_bank_role_v1_1.json").read_text())
        self.assertTrue(role["assistant_outputs_original"])

    def test_07_researcher_rewriting_false(self) -> None:
        self.assertFalse(self.attestation["researcher_rewriting"])
        self.assertFalse(self.attestation["researcher_splicing"])

    def test_08_few_shot_reconstruction_false(self) -> None:
        self.assertFalse(self.attestation["few_shot_reconstruction"])

    def test_09_adjacency_linkage_false(self) -> None:
        self.assertEqual(self.attestation["adjacent_row_conversation_linkage"], "not_confirmed")
        self.assertFalse(self.attestation["all_adjacent_pairs_confirmed"])

    def test_10_previous_five_links_removed(self) -> None:
        correction = json.loads((HERE / "authentic_context_link_correction_v1.json").read_text())
        self.assertEqual(correction["previous_candidate_link_count"], len(PREVIOUS_CONTEXT_CASE_IDS))
        self.assertEqual(correction["links_removed"], 5)
        self.assertEqual(correction["remaining_link_count"], 0)

    def test_11_authentic_assistant_context_zero(self) -> None:
        self.assertTrue(all(not row["candidate_conversation_history"] for row in self.authentic))
        self.assertTrue(all(row["assistant_context_attached"] is False for row in self.authentic))

    def test_12_authentic_query_text_unchanged(self) -> None:
        old = _jsonl(ROOT / R1B_AUTHENTIC_BANK_RELATIVE)
        self.assertEqual(
            [row["current_query"] for row in self.authentic],
            [row["current_query"] for row in old],
        )
        self.assertEqual(len(build_corrected_authentic_cases(ROOT)), 25)

    def test_13_synthetic_35_unchanged(self) -> None:
        self.assertEqual(len(self.synthetic), 35)
        self.assertEqual(sha256_file(ROOT / LOCAL_SYNTHETIC_BANK_RELATIVE), R1B_SYNTHETIC_BANK_SHA256)

    def test_14_combined_60_unchanged(self) -> None:
        self.assertEqual(len(self.combined), 60)
        self.assertEqual({row["source_bank"] for row in self.combined}, {"authentic", "synthetic"})

    def test_15_v13_same_case_set(self) -> None:
        self.assertEqual(
            {row["review_case_id"] for row in self.rows_a},
            {row["review_case_id"] for row in self.rows_b},
        )

    def test_16_v13_different_order(self) -> None:
        self.assertNotEqual(
            [row["review_case_id"] for row in self.rows_a],
            [row["review_case_id"] for row in self.rows_b],
        )

    def test_17_source_hidden(self) -> None:
        forbidden = {"source_bank", "source_dataset", "canonical_case_id", "c0_score", "legacy_prediction"}
        self.assertFalse(forbidden & set(self.rows_a[0]))
        self.assertEqual(tuple(self.rows_a[0]), (*VISIBLE_FIELDS, *HUMAN_FIELDS))

    def test_18_authentic_histories_blank(self) -> None:
        source_by_id = {row["review_case_id"]: row["source_bank"] for row in self.mapping}
        rows = [row for row in self.rows_a if source_by_id[row["review_case_id"]] == "authentic"]
        self.assertEqual(len(rows), 25)
        self.assertTrue(all(not row["necessary_conversation_history"] for row in rows))

    def test_19_synthetic_contexts_retained(self) -> None:
        source_by_id = {row["review_case_id"]: row["source_bank"] for row in self.mapping}
        rows = [row for row in self.rows_a if source_by_id[row["review_case_id"]] == "synthetic"]
        self.assertEqual(sum(bool(row["necessary_conversation_history"]) for row in rows), 11)

    def test_20_all_human_fields_blank(self) -> None:
        validate_blank_packet(self.rows_a)
        validate_blank_packet(self.rows_b)

    def test_21_context_link_agreement_excludes_authentic(self) -> None:
        rows_a = [_completed_fixture(row, "Human-A") for row in self.rows_a]
        rows_b = [_completed_fixture(row, "Human-B") for row in self.rows_b]
        result = calculate_source_stratified_agreement(rows_a, rows_b, self.mapping)
        self.assertEqual(result["overall_60"]["context_link_valid"]["applicable_case_count"], 11)
        authentic = result["by_source"]["authentic"]["context_link_valid"]
        self.assertEqual(authentic["status"], "NOT_APPLICABLE")
        self.assertEqual(authentic["applicable_case_count"], 0)

    def test_22_missing_context_adjudication_rule(self) -> None:
        base = _completed_fixture(self.rows_a[0], "Human-A")
        base.update({"context_sufficient": "NO", "context_resolution_required": "YES"})
        other = {**base, "reviewer_id": "Human-B"}
        reasons = adjudication_reasons(base, other, source_bank="authentic")
        self.assertIn("AUTHENTIC_CONTEXT_INSUFFICIENT", reasons)
        record = {
            "review_case_id": base["review_case_id"],
            "context_sufficient": "NO",
            "missing_context_disposition": AUTHENTIC_MISSING_CONTEXT_DISPOSITIONS[0],
            "query_rewrite_performed": False,
            "assistant_context_attached": False,
            "disagreement_reasons": list(reasons),
            "adjudicator_id": "Human-Adjudicator",
            "adjudication_date": "2026-08-26",
        }
        validate_adjudication_record(
            record,
            expected_review_case_id=base["review_case_id"],
            source_bank="authentic",
        )

    def test_23_old_packets_unchanged(self) -> None:
        assert_old_packets_unchanged()

    def test_24_new_packets_ignored(self) -> None:
        import subprocess

        for relative in (LOCAL_REVIEW_A_RELATIVE, LOCAL_REVIEW_B_RELATIVE):
            result = subprocess.run(["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=ROOT)
            self.assertEqual(result.returncode, 0)

    def test_25_track_a_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            reject_prohibited_track_path("evaluation/private/track_a/example.csv")

    def test_26_track_b_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            reject_prohibited_track_path("evaluation/private/track_b/example.csv")

    def test_27_no_production_change(self) -> None:
        assert_change_scope()
        assert_gitignore_contract()

    def test_28_no_provider_network(self) -> None:
        assert_no_provider_network_surface()

    def test_29_double_build_byte_identical(self) -> None:
        self.assertEqual(assert_double_build()["packets"]["row_count"], 60)

    def test_30_output_checksums(self) -> None:
        validate_output_checksums()
        self.assertEqual(len(output_checksum_targets()), 22)

    def test_31_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_32_protected_sources_unchanged(self) -> None:
        assert_local_outputs()
        assert_change_scope()
        assert_all_python_ast()
        self.assertEqual(len(PYTHON_FILES), 10)


if __name__ == "__main__":
    unittest.main()
