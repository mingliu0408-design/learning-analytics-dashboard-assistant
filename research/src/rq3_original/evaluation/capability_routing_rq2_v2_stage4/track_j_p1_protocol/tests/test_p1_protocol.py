from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import socket
import unittest
from unittest import mock

from .. import p1_protocol as p1
from ..validate_p1_protocol import run_checks


TRACK_DIR = Path(__file__).resolve().parents[1]
NONE = p1.CapabilitySignature(False, False, False)
RAG = p1.CapabilitySignature(True, False, False)
MEMORY = p1.CapabilitySignature(False, True, False)
PLANNING = p1.CapabilitySignature(False, False, True)
ALL = p1.CapabilitySignature(True, True, True)


def toy_case(
    case_id: str = "TOY-001",
    fold: str = "DEV-CV-FOLD-1",
    *,
    gold: p1.CapabilitySignature = NONE,
    b0: p1.CapabilitySignature = NONE,
    b2: p1.CapabilitySignature = NONE,
    b3: p1.CapabilitySignature = NONE,
    probabilities: tuple[float, float, float] = (0.1, 0.1, 0.1),
    thresholds: tuple[float, float, float] = (0.5, 0.5, 0.5),
    b4: p1.CapabilitySignature | None = NONE,
    b4_valid: bool = True,
    b4_terminal_status: str = "VALID",
) -> p1.P1Case:
    return p1.P1Case(
        annotation_case_id=case_id,
        outer_fold=fold,
        gold=gold,
        b0=b0,
        b2=b2,
        b3=b3,
        b3_probabilities=probabilities,
        b3_thresholds=thresholds,
        b4=b4,
        b4_valid=b4_valid,
        b4_terminal_status=b4_terminal_status,
        scenario_family_id=f"FAMILY-{case_id}",
        current_page="TOY-PAGE",
    )


def toy_nested_cases() -> list[p1.P1Case]:
    cases: list[p1.P1Case] = []
    for index, fold in enumerate(p1.OUTER_FOLDS, start=1):
        cases.append(
            toy_case(
                f"TOY-{index}-A",
                fold,
                gold=RAG,
                b4=RAG,
                probabilities=(0.49, 0.1, 0.1),
            )
        )
        cases.append(
            toy_case(
                f"TOY-{index}-B",
                fold,
                gold=NONE,
                b4=ALL,
                probabilities=(0.1, 0.1, 0.1),
            )
        )
    return cases


def metric_row(**overrides: float) -> dict[str, float]:
    row = {
        "macro_f1": 0.5,
        "exact_capability_set_match": 0.5,
        "jaccard": 0.5,
        "under_routing_rate": 0.5,
        "over_routing_rate": 0.5,
        "fallback_rate": 0.5,
        "estimated_provider_calls": 999.0,
    }
    row.update(overrides)
    return row


class P1ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = json.loads(
            (TRACK_DIR / "p1_candidate_policies_frozen_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.nested = json.loads(
            (TRACK_DIR / "p1_nested_selection_protocol_v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_01_exact_policy_inventory(self) -> None:
        eligible = self.candidates["eligible_policies"]
        self.assertEqual(9, len(eligible))
        self.assertEqual(
            list(p1.ELIGIBLE_POLICY_IDS),
            [policy["policy_id"] for policy in eligible],
        )
        self.assertEqual(1, self.candidates["diagnostic_policy_count"])
        self.assertEqual(
            p1.DIAGNOSTIC_POLICY_ID,
            self.candidates["diagnostic_policies"][0]["policy_id"],
        )
        self.assertFalse(self.candidates["diagnostic_policies"][0]["eligible"])

    def test_02_policy_file_matches_reference_semantics(self) -> None:
        eligible = self.candidates["eligible_policies"]
        self.assertEqual(
            list(range(9)), [policy["simplicity_order"] for policy in eligible]
        )
        for policy in eligible:
            self.assertEqual(
                policy["simplicity_order"],
                p1.POLICY_SIMPLICITY_ORDER[policy["policy_id"]],
            )
        self.assertTrue(self.candidates["architecture"]["case_level_switch_only"])
        self.assertTrue(
            self.candidates["architecture"]["label_level_mixing_prohibited"]
        )

    def test_03_fallback_switches_complete_case_not_individual_labels(self) -> None:
        b3 = p1.CapabilitySignature(True, False, True)
        b4 = p1.CapabilitySignature(False, True, False)
        case = toy_case(
            b3=b3,
            b4=b4,
            probabilities=(0.51, 0.1, 0.9),
        )
        decision = p1.apply_policy("P1-C01-MARGIN-005", case)
        self.assertTrue(decision.fallback_triggered)
        self.assertEqual("B4", decision.selected_router)
        self.assertEqual(b4, decision.output)
        self.assertNotEqual(
            p1.CapabilitySignature(b3.rag_required, b4.memory_required, b3.planning_required),
            decision.output,
        )

    def test_04_margin_definitions_are_any_label_and_inclusive(self) -> None:
        boundaries = [
            ("P1-C01-MARGIN-005", 0.55, 0.5501),
            ("P1-C02-MARGIN-010", 0.60, 0.6001),
            ("P1-C03-MARGIN-020", 0.70, 0.7001),
        ]
        for policy_id, inclusive, outside in boundaries:
            with self.subTest(policy_id=policy_id):
                self.assertTrue(
                    p1.should_fallback(
                        policy_id,
                        toy_case(probabilities=(0.9, inclusive, 0.9)),
                    )
                )
                self.assertFalse(
                    p1.should_fallback(
                        policy_id,
                        toy_case(probabilities=(0.9, outside, 0.9)),
                    )
                )

    def test_05_b2_b3_disagreement_uses_complete_signatures(self) -> None:
        case = toy_case(b2=MEMORY, b3=NONE)
        self.assertTrue(p1.should_fallback("P1-C04-B2-B3-DISAGREEMENT", case))
        self.assertFalse(p1.should_fallback("P1-C05-B0-B3-DISAGREEMENT", case))

    def test_06_b0_b3_disagreement_uses_complete_signatures(self) -> None:
        case = toy_case(b0=PLANNING, b2=NONE, b3=NONE)
        self.assertTrue(p1.should_fallback("P1-C05-B0-B3-DISAGREEMENT", case))
        self.assertFalse(p1.should_fallback("P1-C04-B2-B3-DISAGREEMENT", case))

    def test_07_composites_and_nonunanimous_are_frozen(self) -> None:
        margin_only = toy_case(probabilities=(0.49, 0.1, 0.1))
        b2_only = toy_case(b2=RAG)
        b0_only = toy_case(b0=RAG)
        unanimous = toy_case()
        self.assertTrue(p1.should_fallback("P1-C06-MARGIN010-OR-B2B3", margin_only))
        self.assertTrue(p1.should_fallback("P1-C06-MARGIN010-OR-B2B3", b2_only))
        self.assertTrue(p1.should_fallback("P1-C07-MARGIN010-OR-B0B3", b0_only))
        self.assertTrue(p1.should_fallback("P1-C08-NONUNANIMOUS", b2_only))
        self.assertFalse(p1.should_fallback("P1-C08-NONUNANIMOUS", unanimous))

    def test_08_invalid_b4_after_retry_uses_b3_and_reports_failure(self) -> None:
        case = toy_case(
            b3=PLANNING,
            probabilities=(0.49, 0.1, 0.1),
            b4=None,
            b4_valid=False,
            b4_terminal_status="INVALID_STRUCTURED_OUTPUT",
        )
        decision = p1.apply_policy("P1-C01-MARGIN-005", case)
        self.assertEqual("B3", decision.selected_router)
        self.assertEqual(PLANNING, decision.output)
        self.assertEqual("FALLBACK_FAILED_USED_B3", decision.fallback_outcome)
        metrics = p1.evaluate_policy("P1-C01-MARGIN-005", [case])
        self.assertEqual(1, metrics["failed_fallback_count"])
        self.assertEqual(0.0, metrics["valid_b4_fallback_coverage"])
        self.assertEqual(1, metrics["estimated_provider_calls"])

    def test_09_outer_fold_labels_are_excluded_from_that_fold_selection(self) -> None:
        original = toy_nested_cases()
        before = p1.select_outer_policy(original, "DEV-CV-FOLD-1")
        mutated = [
            replace(case, gold=ALL if case.gold != ALL else NONE)
            if case.outer_fold == "DEV-CV-FOLD-1"
            else case
            for case in original
        ]
        after = p1.select_outer_policy(mutated, "DEV-CV-FOLD-1")
        self.assertEqual(before["selected_policy_id"], after["selected_policy_id"])
        self.assertEqual(
            before["eligible_policy_metrics"], after["eligible_policy_metrics"]
        )
        self.assertNotIn(
            "DEV-CV-FOLD-1", before["selection_fold_ids"]
        )

    def test_10_frozen_tie_break_order(self) -> None:
        def select(c00: dict[str, float], c01: dict[str, float]) -> str:
            scores = {
                policy_id: metric_row(macro_f1=0.0)
                for policy_id in p1.ELIGIBLE_POLICY_IDS
            }
            scores["P1-C00-B3-DIRECT"] = c00
            scores["P1-C01-MARGIN-005"] = c01
            return p1.select_policy(scores)

        self.assertEqual(
            "P1-C00-B3-DIRECT",
            select(
                metric_row(macro_f1=0.9, exact_capability_set_match=0.0),
                metric_row(macro_f1=0.8, exact_capability_set_match=1.0),
            ),
        )
        self.assertEqual(
            "P1-C01-MARGIN-005",
            select(
                metric_row(exact_capability_set_match=0.7, jaccard=1.0),
                metric_row(exact_capability_set_match=0.8, jaccard=0.0),
            ),
        )
        self.assertEqual(
            "P1-C01-MARGIN-005",
            select(metric_row(jaccard=0.7), metric_row(jaccard=0.8)),
        )
        self.assertEqual(
            "P1-C01-MARGIN-005",
            select(
                metric_row(under_routing_rate=0.2),
                metric_row(under_routing_rate=0.1, over_routing_rate=1.0),
            ),
        )
        self.assertEqual(
            "P1-C01-MARGIN-005",
            select(
                metric_row(over_routing_rate=0.2),
                metric_row(over_routing_rate=0.1, fallback_rate=1.0),
            ),
        )
        self.assertEqual(
            "P1-C01-MARGIN-005",
            select(metric_row(fallback_rate=0.2), metric_row(fallback_rate=0.1)),
        )
        tied = {policy_id: metric_row() for policy_id in p1.ELIGIBLE_POLICY_IDS}
        self.assertEqual("P1-C00-B3-DIRECT", p1.select_policy(tied))
        key = p1.policy_selection_key("P1-C00-B3-DIRECT", metric_row())
        self.assertEqual(8, len(key))
        self.assertEqual(b"P1-C00-B3-DIRECT", key[-1])

    def test_11_final_full_dev_policy_is_deterministic(self) -> None:
        cases = toy_nested_cases()
        first = p1.nested_policy_evaluation(cases)
        second = p1.nested_policy_evaluation(list(reversed(cases)))
        self.assertEqual("P1-C01-MARGIN-005", first["final_full_dev_policy_id"])
        self.assertEqual(
            first["final_full_dev_policy_id"], second["final_full_dev_policy_id"]
        )
        self.assertEqual(
            [row["selected_policy_id"] for row in first["outer_fold_results"]],
            [row["selected_policy_id"] for row in second["outer_fold_results"]],
        )

    def test_12_all_b4_diagnostic_is_never_selectable(self) -> None:
        diagnostic_metrics = p1.evaluate_policy(
            p1.DIAGNOSTIC_POLICY_ID, toy_nested_cases()
        )
        self.assertEqual(1.0, diagnostic_metrics["fallback_rate"])
        scores = {
            policy_id: metric_row() for policy_id in p1.ELIGIBLE_POLICY_IDS
        }
        scores[p1.DIAGNOSTIC_POLICY_ID] = metric_row(macro_f1=1.0)
        with self.assertRaises(p1.ContractError):
            p1.select_policy(scores)

    def test_13_toy_reference_path_makes_zero_network_or_provider_calls(self) -> None:
        network_attempts: list[str] = []

        def blocked_connect(*_args: object, **_kwargs: object) -> None:
            network_attempts.append("connect")
            raise AssertionError("network connection attempted")

        with mock.patch.object(socket.socket, "connect", blocked_connect), mock.patch.object(
            socket.socket, "connect_ex", blocked_connect
        ):
            result = p1.nested_policy_evaluation(toy_nested_cases())
        self.assertEqual("P1-C01-MARGIN-005", result["final_full_dev_policy_id"])
        self.assertEqual([], network_attempts)

    def test_14_test_identifiers_are_rejected_and_absent_from_contracts(self) -> None:
        with self.assertRaisesRegex(p1.ContractError, "TEST identifiers"):
            toy_case("TOY-" + "TE" + "ST-PROHIBITED")
        identifier_pattern = re.compile(r"R2V2-(?:TEST|TST)-[A-Z0-9]", re.IGNORECASE)
        for name in (
            "p1_candidate_policies_frozen_v1.json",
            "p1_nested_selection_protocol_v1.json",
            "p1_input_contract_v1.json",
            "p1_output_contract_v1.json",
        ):
            with self.subTest(name=name):
                text = (TRACK_DIR / name).read_text(encoding="utf-8")
                self.assertIsNone(identifier_pattern.search(text))

    def test_15_bound_input_hashes_and_static_contracts_validate(self) -> None:
        passed = run_checks()
        self.assertGreaterEqual(len(passed), 40)
        self.assertEqual(len(passed), len(set(passed)))

    def test_16_stage4j0_records_no_execution_or_b4_result_binding(self) -> None:
        inputs = json.loads(
            (TRACK_DIR / "p1_input_contract_v1.json").read_text(encoding="utf-8")
        )
        outputs = json.loads(
            (TRACK_DIR / "p1_output_contract_v1.json").read_text(encoding="utf-8")
        )
        binding = inputs["b4_result_binding"]
        self.assertIsNone(binding["result_artifact_path"])
        self.assertIsNone(binding["result_artifact_sha256"])
        self.assertFalse(inputs["execution_gate"]["stage4j0_p1_scoring_authorized"])
        self.assertEqual(0, outputs["current_stage_execution"]["provider_calls"])
        self.assertEqual(0, outputs["current_stage_execution"]["test_records_accessed"])
        status = (TRACK_DIR / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("READY_FOR_STAGE_4J_AFTER_VALID_B4_DEV_RESULTS", status)


if __name__ == "__main__":
    unittest.main()
