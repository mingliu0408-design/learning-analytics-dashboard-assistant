"""Standard-library tests for the frozen RQ1-A LR4B contract."""

from __future__ import annotations

import csv
import json
import subprocess
import unittest
from pathlib import Path

from .build_lr4b_contract import (
    analyse_contract,
    compute_protected_source_fingerprint,
    safe_output_bundle_fingerprint,
)
from .contract_schema import (
    BASELINE,
    LEDGER_FIELDS,
    LOCAL_LEDGER_PATH,
    MODEL_INPUT_FIELDS,
    QUERY_ONLY_V1,
    STRUCTURED_CONTEXT_V1,
    authorised_project_path,
    canonical_json_bytes,
    keyword_single_candidate_reciprocal_rank,
    keyword_single_candidate_ranking,
    validate_strict_scenarios,
)
from .context_representation import (
    build_query_only_representation,
    build_structured_context_representation,
    decode_utf8_with_optional_bom,
    model_input_fields_for_mode,
    normalise_source_field,
    representation_sha256,
)


ROOT = Path(__file__).resolve().parents[3]


class ContextRepresentationTests(unittest.TestCase):
    def test_query_only_serialisation_is_deterministic(self) -> None:
        value = "  Cafe\u0301?\r\nKeep  two spaces.  "
        first = build_query_only_representation(value)
        second = build_query_only_representation(value)
        self.assertEqual(first, second)
        self.assertEqual(representation_sha256(first), representation_sha256(second))

    def test_structured_context_has_fixed_field_order(self) -> None:
        value = build_structured_context_representation(
            question_anchor_for_review="anchor",
            previous_turns_for_review="turns",
            utterance_for_review="current",
        )
        self.assertEqual(
            value,
            "[QUESTION_ANCHOR]\nanchor\n[PREVIOUS_TURNS]\nturns\n"
            "[CURRENT_STUDENT_UTTERANCE]\ncurrent",
        )

    def test_unicode_nfc_and_newlines(self) -> None:
        self.assertEqual(normalise_source_field(" Cafe\u0301\r\nline\r "), "Café\nline")

    def test_internal_space_newline_punctuation_and_case_are_preserved(self) -> None:
        source = "  MiXeD,  spacing!\r\nnext  line  "
        self.assertEqual(
            normalise_source_field(source),
            "MiXeD,  spacing!\nnext  line",
        )

    def test_utf8_bom_decode(self) -> None:
        self.assertEqual(decode_utf8_with_optional_bom(b"\xef\xbb\xbfvalue"), "value")

    def test_missing_context_field_fails_closed_without_value_echo(self) -> None:
        with self.assertRaisesRegex(ValueError, "required context field is missing") as captured:
            build_structured_context_representation(
                question_anchor_for_review="anchor",
                previous_turns_for_review="   ",
                utterance_for_review="current",
            )
        self.assertNotIn("anchor", str(captured.exception))
        self.assertNotIn("current", str(captured.exception))

    def test_field_allowlist_excludes_label_fields(self) -> None:
        self.assertEqual(model_input_fields_for_mode(QUERY_ONLY_V1), ("query",))
        self.assertEqual(
            model_input_fields_for_mode(STRUCTURED_CONTEXT_V1),
            (
                "question_anchor_for_review",
                "previous_turns_for_review",
                "utterance_for_review",
            ),
        )
        forbidden = {"final_target_intent", "review_rationale", "mapping_status"}
        self.assertFalse(forbidden & set().union(*map(set, MODEL_INPUT_FIELDS.values())))


class ExperimentContractTests(unittest.TestCase):
    def test_strict_v0_v3_nesting(self) -> None:
        scenarios = {
            "V0": {"a"},
            "V1": {"a", "b"},
            "V2": {"a", "b", "c"},
            "V3": {"a", "b", "c", "d"},
        }
        self.assertTrue(validate_strict_scenarios(scenarios))
        scenarios["V2"] = set(scenarios["V1"])
        self.assertFalse(validate_strict_scenarios(scenarios))

    def test_keyword_single_candidate_mrr_contract(self) -> None:
        self.assertEqual(keyword_single_candidate_ranking("intent_a"), ("intent_a",))
        self.assertEqual(keyword_single_candidate_reciprocal_rank("intent_a", "intent_a"), 1.0)
        self.assertEqual(keyword_single_candidate_reciprocal_rank("intent_a", "intent_b"), 0.0)

    def test_final_gold_path_is_rejected_before_access(self) -> None:
        with self.assertRaises(PermissionError):
            authorised_project_path(
                ROOT,
                "evaluation/learned_intent_ranking/lr1r/primary_v3_input/forbidden.json",
            )

    def test_two_full_in_memory_builds_are_byte_identical(self) -> None:
        first_outputs, first_ledger = analyse_contract(ROOT)
        second_outputs, second_ledger = analyse_contract(ROOT)
        self.assertEqual(first_ledger, second_ledger)
        self.assertEqual(
            {name: canonical_json_bytes(value) for name, value in first_outputs.items()},
            {name: canonical_json_bytes(value) for name, value in second_outputs.items()},
        )
        self.assertEqual(
            safe_output_bundle_fingerprint(first_outputs),
            safe_output_bundle_fingerprint(second_outputs),
        )
        self.assertEqual(len(first_ledger), 318)
        self.assertTrue(all(set(row) == set(LEDGER_FIELDS) for row in first_ledger))

    def test_safe_outputs_do_not_contain_raw_natural_language(self) -> None:
        outputs, _ = analyse_contract(ROOT)
        serialised = b"".join(canonical_json_bytes(outputs[name]) for name in sorted(outputs))
        retained_path = ROOT / (
            "evaluation/learned_intent_ranking/lr4a/training_data_input/"
            "eedi_stage_e4_confirmed_candidate_subset_256.csv"
        )
        with retained_path.open("r", encoding="utf-8-sig", newline="") as handle:
            first = next(csv.DictReader(handle))
        for field in (
            "utterance_for_review",
            "previous_turns_for_review",
            "question_anchor_for_review",
            "review_rationale",
        ):
            value = first[field].encode("utf-8")
            if len(value) >= 24:
                self.assertNotIn(value, serialised)

    def test_local_ledger_path_is_ignored(self) -> None:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(LOCAL_LEDGER_PATH)],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)

    def test_protected_lr_files_match_starting_snapshot(self) -> None:
        snapshot = compute_protected_source_fingerprint(ROOT)
        self.assertEqual(
            snapshot["manifest_fingerprint"],
            BASELINE["protected_source_manifest_fingerprint"],
        )
        self.assertTrue(snapshot["final_gold_root_pruned_before_traversal"])


if __name__ == "__main__":
    unittest.main()
