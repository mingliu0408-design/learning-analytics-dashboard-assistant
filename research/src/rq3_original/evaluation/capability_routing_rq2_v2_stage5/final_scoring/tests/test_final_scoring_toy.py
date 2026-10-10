"""Synthetic-only pre-Gold tests for the complete Stage 5E harness."""

from __future__ import annotations

import csv
import json
import io
from pathlib import Path
import tempfile
import unittest

from evaluation.capability_routing_rq2_v2_stage4.final_router_selection.selection_rule import (
    COVERAGE_FIELDS,
    METHOD_TIER_NUMBERS,
    select_final_router,
)

from ..compositions import compose_case
from ..constants import (
    COMPLETE_METHOD_IDS,
    ELIGIBILITY_PATH,
    ELIGIBLE_METHOD_IDS,
    SELECTION_RULE_PATH,
    TEST_GOLD_FIELDS,
)
from ..metrics import (
    bootstrap_analysis,
    capability_contrast_metrics,
    clarification_metrics,
    core_basic_metrics,
    core_metrics,
    end_to_end_metrics,
)
from ..scoring import (
    Stage5EError,
    _parse_gold,
    build_normalized_records,
    cost_analysis,
    read_json,
    write_once_json,
)


def toy_row(
    case_id: str,
    family: str,
    *,
    gold=(False, False, False),
    action="ANSWER",
    group="",
    axis="",
    writer="Writer A",
    page="Overview",
):
    return {
        "annotation_case_id": case_id,
        "canonical_scenario_family_id": family,
        "utterance_id": f"U-{case_id}",
        "writer_id": writer,
        "current_page": page,
        "contrast_group_id": group,
        "contrast_axis": axis,
        "gold_dialogue_action": action,
        "gold_rag_required": gold[0] if action == "ANSWER" else None,
        "gold_memory_required": gold[1] if action == "ANSWER" else None,
        "gold_planning_required": gold[2] if action == "ANSWER" else None,
    }


class ToyHarnessTests(unittest.TestCase):
    def test_01_stage0_empty_set_convention(self) -> None:
        rows = [toy_row("a", "f1"), toy_row("b", "f1")]
        predictions = {"a": (False, False, False), "b": (False, False, False)}
        result = core_basic_metrics(rows, predictions)
        self.assertEqual(result["exact_capability_set_match"], 1.0)
        self.assertEqual(result["example_based_f1"], 1.0)
        self.assertEqual(result["jaccard"], 1.0)
        self.assertEqual(result["hamming_loss"], 0.0)

    def test_02_p1_complete_signature_switch_and_no_label_mixing(self) -> None:
        deterministic = {
            "R2V2-D0_ALWAYS_ON": {"rag_required": True, "memory_required": True, "planning_required": True},
            "R2V2-D1_NEVER_ON": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B0_RULE": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B1_LEGACY_INTENT": {"rag_required": False, "memory_required": True, "planning_required": False},
            "R2V2-B2_PROTOTYPE": {"rag_required": True, "memory_required": False, "planning_required": False},
            "R2V2-B3_OVR": {"rag_required": False, "memory_required": False, "planning_required": False},
        }
        b4 = {"rag_required": True, "memory_required": True, "planning_required": False}
        methods, metadata = compose_case(
            deterministic, b4, {"rag_required": False}, {"memory_required": False}
        )
        self.assertTrue(metadata["p1_triggered"])
        self.assertEqual(methods["R2V2-P1_HYBRID"], (True, True, False))

    def test_03_p2_p3_p4_exact_compositions(self) -> None:
        deterministic = {
            "R2V2-D0_ALWAYS_ON": {"rag_required": True, "memory_required": True, "planning_required": True},
            "R2V2-D1_NEVER_ON": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B0_RULE": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B1_LEGACY_INTENT": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B2_PROTOTYPE": {"rag_required": False, "memory_required": False, "planning_required": False},
            "R2V2-B3_OVR": {"rag_required": False, "memory_required": False, "planning_required": False},
        }
        methods, metadata = compose_case(
            deterministic,
            {"rag_required": True, "memory_required": False, "planning_required": True},
            {"rag_required": False},
            {"memory_required": True},
        )
        self.assertFalse(metadata["p1_triggered"])
        self.assertEqual(methods["R2V2-P2_RAG_SPECIALIST_COMPOSITION"], (False, False, True))
        self.assertEqual(methods["R2V2-P3_RAG_MEMORY_SPECIALISTS"], (False, True, True))
        self.assertEqual(methods["R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"], (True, True, True))

    def test_04_clarification_override(self) -> None:
        rows = [
            toy_row("a", "f1", action="CLARIFY"),
            toy_row("b", "f1", action="CLARIFY"),
        ]
        actions = {"a": "CLARIFY", "b": "CLARIFY"}
        routes = {"a": "CLARIFY", "b": "CLARIFY"}
        result = end_to_end_metrics(rows, actions, routes)
        self.assertEqual(result["full_route_signature_exact_match"], 1.0)
        self.assertEqual(result["core_executed_count"], 0)

    def test_05_family_and_contrast_definitions(self) -> None:
        rows = [
            toy_row("a1", "f1", group="g", axis="RAG"),
            toy_row("a2", "f1", group="g", axis="RAG"),
            toy_row("b1", "f2", gold=(True, False, False), group="g", axis="RAG"),
            toy_row("b2", "f2", gold=(True, False, False), group="g", axis="RAG"),
        ]
        predictions = {
            "a1": (False, False, False),
            "a2": (False, False, False),
            "b1": (True, False, False),
            "b2": (True, False, False),
        }
        result = core_metrics(rows, predictions)
        self.assertEqual(result["family_metrics"]["both_utterances_exact_correct_rate"], 1.0)
        contrast = capability_contrast_metrics(rows, predictions)
        self.assertEqual(contrast["contrast_consistency_rate"], 1.0)
        self.assertEqual(contrast["complete_gold_pattern_match_rate"], 1.0)

    def test_06_writer_and_page_stratification(self) -> None:
        rows = [
            toy_row("a1", "f1", writer="Writer A", page="Overview"),
            toy_row("a2", "f1", writer="Writer B", page="Overview"),
            toy_row("b1", "f2", writer="Writer A", page="Resources"),
            toy_row("b2", "f2", writer="Writer B", page="Resources"),
        ]
        predictions = {row["annotation_case_id"]: (False, False, False) for row in rows}
        result = core_metrics(rows, predictions)
        self.assertEqual(set(result["writer_stratified_metrics"]), {"Writer A", "Writer B"})
        self.assertEqual(set(result["page_stratified_metrics"]), {"Overview", "Resources"})

    def test_07_clarification_family_contrast(self) -> None:
        rows = [
            toy_row("a1", "f1", group="cg", axis="CLARIFICATION"),
            toy_row("a2", "f1", group="cg", axis="CLARIFICATION"),
            toy_row("b1", "f2", action="CLARIFY", group="cg", axis="CLARIFICATION"),
            toy_row("b2", "f2", action="CLARIFY", group="cg", axis="CLARIFICATION"),
        ]
        predictions = {"a1": "ANSWER", "a2": "ANSWER", "b1": "CLARIFY", "b2": "CLARIFY"}
        result = clarification_metrics(rows, predictions)
        self.assertEqual(result["clarification_contrast"]["clarification_contrast_consistency_rate"], 1.0)
        self.assertEqual(result["clarification_contrast"]["clarification_gold_pattern_match_rate"], 1.0)

    def test_08_bootstrap_determinism_and_pairs(self) -> None:
        rows = [
            toy_row("a1", "f1"),
            toy_row("a2", "f1"),
            toy_row("b1", "f2", gold=(True, False, False)),
            toy_row("b2", "f2", gold=(True, False, False)),
        ]
        base = {
            "a1": (False, False, False),
            "a2": (False, False, False),
            "b1": (True, False, False),
            "b2": (True, False, False),
        }
        predictions = {method_id: dict(base) for method_id in COMPLETE_METHOD_IDS}
        first = bootstrap_analysis(rows, predictions, replicates=25)
        second = bootstrap_analysis(rows, predictions, replicates=25)
        self.assertEqual(first, second)
        self.assertEqual(len(first["paired_difference_intervals"]), 6)

    def test_09_cost_arithmetic_and_p1_trigger(self) -> None:
        usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
        rows = []
        for case_id, action, gate in (("a", "ANSWER", "ANSWER"), ("b", "CLARIFY", "CLARIFY")):
            rows.append(
                {
                    **toy_row(case_id, f"f-{case_id}", action=action),
                    "frozen_clarification_prediction": gate,
                    "b4_per_case_usage": dict(usage),
                    "rag_specialist_per_case_usage": dict(usage),
                    "memory_specialist_per_case_usage": dict(usage),
                }
            )
        result = cost_analysis(rows, {"a": {"p1_triggered": True}, "b": {"p1_triggered": False}})
        p3 = result["counterfactual_gold_answer_core_population"]["methods"][
            "R2V2-P3_RAG_MEMORY_SPECIALISTS"
        ]
        self.assertEqual(p3["provider_component_call_count"], 3)
        self.assertEqual(p3["total_tokens"], 330)

    def test_10_frozen_selection_application(self) -> None:
        rows = []
        for index, method_id in enumerate(ELIGIBLE_METHOD_IDS):
            row = {
                "method_id": method_id,
                **{field: True for field in COVERAGE_FIELDS},
                "core_macro_f1_gold_answer_cases": 1.0 if method_id == "R2V2-B3_OVR" else 0.5,
                "exact_capability_set_match": 0.5,
                "jaccard": 0.5,
                "under_routing_rate": 0.5,
                "over_routing_rate": 0.5,
                "family_both_utterances_correct_rate": 0.5,
                "complete_gold_pattern_contrast_match_rate": 0.5,
                "counterfactual_provider_component_call_count": index,
                "counterfactual_token_cost": index,
                "method_tier_number": METHOD_TIER_NUMBERS[method_id],
                "method_id_utf8": method_id,
            }
            rows.append(row)
        selected = select_final_router(rows, read_json(ELIGIBILITY_PATH), read_json(SELECTION_RULE_PATH))
        self.assertEqual(selected, "R2V2-B3_OVR")

    def test_11_p4_is_reportable_but_cannot_enter_selection(self) -> None:
        eligibility = read_json(ELIGIBILITY_PATH)
        p4 = next(row for row in eligibility["methods"] if row["method_id"] == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION")
        self.assertEqual(p4["pre_test_selection_eligibility"], "INELIGIBLE")
        self.assertNotIn("R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", ELIGIBLE_METHOD_IDS)

    def test_12_atomic_write_once_binding_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binding.json"
            write_once_json(path, {"write_count": 1})
            self.assertEqual(json.loads(path.read_text()), {"write_count": 1})
            with self.assertRaises(Stage5EError):
                write_once_json(path, {"write_count": 2})
            self.assertEqual(json.loads(path.read_text()), {"write_count": 1})

    def test_13_exact_36_case_toy_gold_intake_and_join(self) -> None:
        signatures = ("000", "001", "010", "011", "100", "101", "110", "111", "CLARIFY")
        rows = []
        for family_index in range(18):
            signature = signatures[family_index // 2]
            for utterance_index in range(2):
                case_index = family_index * 2 + utterance_index + 1
                action = "CLARIFY" if signature == "CLARIFY" else "ANSWER"
                bits = (
                    ("NOT_APPLICABLE",) * 3
                    if action == "CLARIFY"
                    else tuple("YES" if bit == "1" else "NO" for bit in signature)
                )
                values = {
                    "annotation_case_id": f"TOY-{case_index:03d}",
                    "canonical_scenario_family_id": f"TOY-F-{family_index + 1:02d}",
                    "utterance_id": f"TOY-U-{case_index:03d}",
                    "writer_id": "Writer A" if utterance_index == 0 else "Writer B",
                    "current_page": "Overview",
                    "final_family_routing_signature": signature,
                    "atomic_component_id": f"TOY-C-{family_index + 1:02d}",
                    "contrast_group_id": "",
                    "contrast_axis": "",
                    "final_case_validity": "INCLUDE_VALID_CASE",
                    "final_naturalness": "NATURAL",
                    "final_dialogue_action": action,
                    "final_rag_required": bits[0],
                    "final_memory_required": bits[1],
                    "final_planning_required": bits[2],
                    "partition": "TEST",
                    "split_seed": "20260830",
                    "split_version": "RQ2_V2_CONTRAST_SAFE_SPLIT_V1",
                    "split_status": "FROZEN_PRE_MODEL_DEVELOPMENT_SPLIT",
                    "escrow_status": "FROZEN_NOT_FOR_MODEL_DEVELOPMENT",
                }
                rows.append({field: values[field] for field in TEST_GOLD_FIELDS})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=TEST_GOLD_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            (root / "test_gold_escrow_v1.csv").write_text(
                buffer.getvalue(), encoding="utf-8", newline=""
            )
            (root / "test_gold_escrow_v1.jsonl").write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                encoding="utf-8",
            )
            parsed, summary = _parse_gold(root)
        usage = {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}
        deterministic = {}
        b4 = {}
        rag = {}
        memory = {}
        for row in parsed:
            case_id = row["annotation_case_id"]
            direct = {
                "R2V2-CG1_CLARIFICATION_RULE": {"dialogue_action": "ANSWER", "matched_clause": "TOY"},
                "R2V2-D0_ALWAYS_ON": {"rag_required": True, "memory_required": True, "planning_required": True},
                "R2V2-D1_NEVER_ON": {"rag_required": False, "memory_required": False, "planning_required": False},
                "R2V2-B0_RULE": {"rag_required": False, "memory_required": False, "planning_required": False},
                "R2V2-B1_LEGACY_INTENT": {"rag_required": False, "memory_required": False, "planning_required": False},
                "R2V2-B2_PROTOTYPE": {"rag_required": False, "memory_required": False, "planning_required": False},
                "R2V2-B3_OVR": {"rag_required": False, "memory_required": False, "planning_required": False},
            }
            deterministic[case_id] = {"method_predictions": direct}
            attempt = {"usage": dict(usage)}
            b4[case_id] = {"prediction": {"rag_required": False, "memory_required": False, "planning_required": False}, "attempt_records": [attempt]}
            rag[case_id] = {"prediction": {"rag_required": False}, "attempt_records": [attempt]}
            memory[case_id] = {"prediction": {"memory_required": False}, "attempt_records": [attempt]}
        normalized, predictions, metadata = build_normalized_records(
            parsed, {"deterministic": deterministic, "b4": b4, "rag": rag, "memory": memory}
        )
        self.assertEqual(summary["case_count"], 36)
        self.assertEqual(summary["family_count"], 18)
        self.assertEqual(len(normalized), 36)
        self.assertEqual(set(predictions), set(COMPLETE_METHOD_IDS))
        self.assertEqual(len(metadata), 36)


if __name__ == "__main__":
    unittest.main()
