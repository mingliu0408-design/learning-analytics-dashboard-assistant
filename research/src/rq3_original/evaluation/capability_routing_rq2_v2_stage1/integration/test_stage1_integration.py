"""Focused tests for the RQ2-V2 Stage 1 integration boundary."""

from __future__ import annotations

from pathlib import Path
import unittest

from evaluation.capability_routing_rq2_v2_stage0 import (
    CAPABILITY_FIELDS,
    MODEL_IDS,
)
from evaluation.capability_routing_rq2_v2_stage1.integration.build_integration_review_zip import (
    SAFE_SUFFIXES,
    collect_review_files,
)
from evaluation.capability_routing_rq2_v2_stage1.integration.run_integration_checks import (
    PRIMARY_FIELDS,
    PRIMARY_PROFILE_NAME,
    canonical_toy_answer_case,
    run_checks,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
STAGE1_ROOT = PACKAGE_ROOT.parent


class Stage1IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_checks()
        cls.smoke = cls.report["details"]["toy_b3_to_p1_end_to_end"]

    def test_01_integration_check_report_passes(self) -> None:
        self.assertEqual(self.report["status"], "PASS", self.report["failures"])
        self.assertEqual(self.report["failure_count"], 0)
        self.assertEqual(self.report["check_count"], 10)

    def test_02_all_six_model_interfaces_coexist(self) -> None:
        detail = self.report["details"]["six_model_interfaces_coexist"]
        self.assertEqual(tuple(detail["model_ids"]), MODEL_IDS)
        self.assertEqual(detail["interface_count"], 6)

    def test_03_canonical_toy_case_is_answer_only_and_ineligible(self) -> None:
        case = canonical_toy_answer_case()
        self.assertEqual(case["gold"]["dialogue_action"], "ANSWER")
        self.assertTrue(case["governance"]["fixture_only"])
        self.assertFalse(case["governance"]["final_test_eligible"])

    def test_04_shared_primary_profile_is_exact(self) -> None:
        self.assertEqual(self.smoke["primary_feature_profile"], PRIMARY_PROFILE_NAME)
        self.assertEqual(tuple(self.smoke["primary_fields"]), PRIMARY_FIELDS)
        self.assertNotIn("rag_context_state", self.smoke["primary_fields"])
        self.assertNotIn("memory_context_state", self.smoke["primary_fields"])

    def test_05_b3_probabilities_use_the_canonical_label_axis(self) -> None:
        for key in ("direct_b3_probabilities", "uncertain_b3_probabilities"):
            values = self.smoke[key]
            self.assertEqual(set(values), set(CAPABILITY_FIELDS))
            self.assertTrue(all(0.0 <= value <= 1.0 for value in values.values()))

    def test_06_confident_case_uses_direct_b3_path(self) -> None:
        direct = self.smoke["direct_path"]
        self.assertEqual(direct["final_prediction_source"], "R2V2-B3_OVR")
        self.assertFalse(direct["fallback_triggered"])
        self.assertEqual(direct["mock_provider_calls"], 0)
        self.assertTrue(direct["canonical_prediction_schema"])

    def test_07_uncertain_case_invokes_exactly_one_b4_mock(self) -> None:
        fallback = self.smoke["uncertain_path"]
        self.assertEqual(fallback["final_prediction_source"], "R2V2-B4_LLM")
        self.assertTrue(fallback["fallback_triggered"])
        self.assertEqual(fallback["mock_provider_calls"], 1)
        self.assertTrue(fallback["canonical_prediction_schema"])

    def test_08_smoke_has_zero_external_activity(self) -> None:
        self.assertEqual(self.smoke["network_attempts"], 0)
        self.assertEqual(self.smoke["network_calls"], 0)
        self.assertEqual(self.smoke["real_provider_calls"], 0)
        self.assertEqual(self.smoke["paid_provider_calls"], 0)

    def test_09_unfrozen_choices_remain_unselected(self) -> None:
        detail = self.report["details"]["unfrozen_research_choices_preserved"]
        self.assertEqual(detail["b1_mapping_status"], "UNFROZEN")
        self.assertEqual(detail["b1_selected_capability_values"], 0)
        self.assertEqual(detail["b4_few_shot_status"], "PLACEHOLDER_ONLY_NOT_SELECTED")
        self.assertIn("NOT_FINAL_SELECTION", detail["b2_b3_threshold_status"])
        self.assertIn("NOT_FINAL_SELECTION", detail["p1_threshold_status"])

    def test_10_writer_guide_and_attestation_are_present(self) -> None:
        self.assertEqual(
            self.report["checks"]["writer_documentation_amendment"], "PASS"
        )
        self.assertTrue(
            (STAGE1_ROOT / "track_a_dataset" / "WRITER_COMPLETION_ATTESTATION.md")
            .is_file()
        )

    def test_11_review_allowlist_contains_only_small_research_files(self) -> None:
        files = collect_review_files()
        self.assertTrue(files)
        self.assertTrue(all(path.suffix in SAFE_SUFFIXES for path in files))
        self.assertFalse(any("__pycache__" in path.parts for path in files))
        names = {path.name for path in files}
        self.assertIn("scenario_blueprints.jsonl", names)
        self.assertIn("writer_packet_A.csv", names)
        self.assertIn("writer_packet_B.csv", names)
        self.assertIn("WRITER_COMPLETION_ATTESTATION.md", names)


if __name__ == "__main__":
    unittest.main()
