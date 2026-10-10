"""RQ2-A contract tests; no final-gold or held-out asset is touched."""

from __future__ import annotations

import ast
import csv
from dataclasses import replace
import inspect
import json
from pathlib import Path
import subprocess
import unittest

from . import (
    HERE,
    LOCAL_BASELINE_RELATIVE,
    LOCAL_PROPOSAL_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    MAXIMUM_RECENT_TURNS,
    ROOT,
    RQ1_FINAL_ROUTER,
    RQ1_ROUTER_MANIFEST_RELATIVE,
    RQ1_ROUTER_MANIFEST_SHA256,
    require_frozen_rq1_router,
    sha256_file,
)
from .build_capability_development_bank import (
    build_development_bank,
    build_hidden_proposal,
    write_safe_bank_summaries,
)
from .build_capability_review_packets import HUMAN_FIELDS, build_review_packets
from .capability_case_schema import CapabilityCaseV1
from .capability_schema import (
    CapabilitySchemaError,
    build_capability_plan,
    capability_schema_document,
)
from .context_envelope import (
    ContextEnvelopeError,
    build_context_envelope,
    context_envelope_schema_document,
)
from .duplicate_lineage import canonicalise_cases
from .legacy_hard_route_adapter import (
    LegacyHardRoutingCapabilityAdapterV1,
    provider_free_smoke,
)
from .source_inventory import SourceBoundaryError, assert_allowed_source
from .validate_rq2a_contract import (
    PYTHON_FILES,
    assert_all_python_ast,
    assert_change_scope,
    assert_double_build,
    assert_protected_sources_unchanged,
    assert_review_packets,
    assert_safe_json,
    assert_staged_content_safe,
    governed_text_leak_scan,
    validate_all,
    validate_output_checksums,
)


def _read_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _review_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _placeholder_case(
    case_id: str,
    *,
    page: str = "Overview",
    history: list[dict] | None = None,
) -> CapabilityCaseV1:
    return CapabilityCaseV1.from_mapping(
        {
            "case_id": case_id,
            "source_dataset": "UNIT_SYNTHETIC",
            "source_scenario_id": case_id,
            "turn_index": 0,
            "current_query": "TOKEN_CURRENT_TASK",
            "current_page": page,
            "conversation_history": history or [],
            "scenario_category": "unit",
            "scenario_family": "unit",
            "provenance": {"synthetic": True},
        }
    )


class RQ2AContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.router = require_frozen_rq1_router(ROOT)
        cls.baseline = _read_json("legacy_capability_projection_v1.json")
        cls.bank_summary = _read_json("capability_development_bank_summary_v1.json")
        cls.lineage_summary = _read_json("capability_duplicate_lineage_summary_v1.json")
        cls.review_manifest = _read_json("capability_review_packet_manifest_v1.json")
        cls.ledger = _read_jsonl(ROOT / LOCAL_BASELINE_RELATIVE)
        cls.proposals = _read_jsonl(ROOT / LOCAL_PROPOSAL_RELATIVE)
        cls.review_a = _review_rows(ROOT / LOCAL_REVIEW_A_RELATIVE)
        cls.review_b = _review_rows(ROOT / LOCAL_REVIEW_B_RELATIVE)

    def test_01_rq1_selection_manifest_hash(self) -> None:
        self.assertEqual(
            sha256_file(ROOT / RQ1_ROUTER_MANIFEST_RELATIVE),
            RQ1_ROUTER_MANIFEST_SHA256,
        )

    def test_02_frozen_router_is_c0(self) -> None:
        self.assertEqual(self.router["router"]["selected_router"], "C0_COSINE")
        self.assertEqual(self.router["router"]["frozen_selection"], "C0_REMAINS_SELECTED")

    def test_03_m64_is_rejected(self) -> None:
        plan = build_capability_plan(
            case_id="UNIT-C0", required_capabilities=("safe_direct_response",)
        )
        with self.assertRaises(CapabilitySchemaError):
            replace(plan, router_identity="M64_V0_SEED_20260815")

    def test_04_track_a_source_is_rejected_without_access(self) -> None:
        with self.assertRaises(SourceBoundaryError):
            assert_allowed_source("evaluation/final_gold/track_a.csv")

    def test_05_track_b_source_is_rejected_without_access(self) -> None:
        with self.assertRaises(SourceBoundaryError):
            assert_allowed_source("evaluation/contextual_heldout/track_b.csv")

    def test_06_context_envelope_schema(self) -> None:
        schema = context_envelope_schema_document()
        self.assertEqual(schema["envelope_schema_version"], "context-envelope-v1")
        self.assertIn("context_resolution_required", schema["fields"])

    def test_07_maximum_recent_turns_is_four(self) -> None:
        history = [
            {
                "role": "student",
                "turn_order": index,
                "source": "unit",
                "content": f"TOKEN_CURRENT_TASK_{index}",
                "relevant": True,
            }
            for index in range(7)
        ]
        envelope = build_context_envelope(
            case_id="UNIT-TURNS",
            original_query="TOKEN_CURRENT_TASK",
            current_page="Overview",
            conversation_history=history,
        )
        self.assertEqual(MAXIMUM_RECENT_TURNS, 4)
        self.assertEqual(len(envelope.recent_relevant_turns), 4)

    def test_08_latest_correction_has_precedence(self) -> None:
        envelope = build_context_envelope(
            case_id="UNIT-CORRECTION",
            original_query="TOKEN_CURRENT_TASK",
            current_page="Overview",
            structured_memory={"active_goal": {"value": "TOKEN_OLD", "status": "active"}},
            conversation_history=[
                {
                    "role": "student",
                    "content": "TOKEN_CURRENT_TASK",
                    "turn_order": 1,
                    "source": "unit",
                    "relevant": True,
                    "correction": {
                        "replacement_goal": "TOKEN_NEW",
                        "resolved_query": "TOKEN_RESOLVED",
                    },
                }
            ],
        )
        self.assertEqual(envelope.active_goal, "TOKEN_NEW")
        self.assertEqual(envelope.resolved_query, "TOKEN_RESOLVED")

    def test_09_replaced_goal_is_suppressed(self) -> None:
        envelope = build_context_envelope(
            case_id="UNIT-REPLACED",
            original_query="TOKEN_CURRENT_TASK",
            current_page="Overview",
            structured_memory={"active_goal": {"value": "TOKEN_OLD", "status": "replaced"}},
        )
        self.assertIsNone(envelope.active_goal)

    def test_10_cross_student_context_is_rejected(self) -> None:
        with self.assertRaises(ContextEnvelopeError):
            build_context_envelope(
                case_id="UNIT-BOUNDARY",
                original_query="TOKEN_CURRENT_TASK",
                current_page="Overview",
                structured_memory={"other_student_state": {"value": "TOKEN"}},
            )

    def test_11_multi_label_capability_plan(self) -> None:
        plan = build_capability_plan(
            case_id="UNIT-MULTI",
            required_capabilities=("dashboard_evidence", "course_retrieval", "planning"),
            context_resolution_required=True,
        )
        self.assertEqual(len(plan.required_capabilities), 3)
        self.assertTrue(plan.context_resolution_required)

    def test_12_empty_plan_is_rejected(self) -> None:
        with self.assertRaises(CapabilitySchemaError):
            build_capability_plan(case_id="UNIT-EMPTY", required_capabilities=())

    def test_13_clarification_is_exclusive(self) -> None:
        with self.assertRaises(CapabilitySchemaError):
            build_capability_plan(
                case_id="UNIT-CLARIFY",
                required_capabilities=("clarification", "planning"),
                clarification_reason="TOKEN_REASON",
            )

    def test_14_working_context_is_not_capability(self) -> None:
        schema = capability_schema_document()
        self.assertFalse(schema["working_context_is_capability"])
        self.assertNotIn("working_context", schema["predicted_capabilities"])

    def test_15_deterministic_guards_are_not_predicted(self) -> None:
        schema = capability_schema_document()
        self.assertFalse(schema["deterministic_guards_are_predicted_capabilities"])
        self.assertTrue(set(schema["deterministic_guards"]).isdisjoint(schema["predicted_capabilities"]))

    def test_16_legacy_adapter_calls_current_production_functions(self) -> None:
        self.assertEqual(
            LegacyHardRoutingCapabilityAdapterV1.router_identity, "C0_COSINE"
        )
        self.assertTrue(LegacyHardRoutingCapabilityAdapterV1.measurement_only)
        required = self.baseline["required_production_functions_called"]
        self.assertTrue(all(required.values()))
        source = inspect.getsource(__import__(
            "evaluation.capability_routing_v1.legacy_hard_route_adapter",
            fromlist=["measure_case"],
        ))
        self.assertIn("production_service.build_c_full_context", source)

    def test_17_legacy_router_identity_is_c0(self) -> None:
        self.assertEqual(self.baseline["router_identity"], RQ1_FINAL_ROUTER)
        self.assertFalse(self.baseline["m64_used"])

    def test_18_retrieval_capability_equals_actual_request(self) -> None:
        for row in self.ledger:
            self.assertEqual(
                row["capability_projection"]["course_retrieval"],
                row["retrieval_requested"],
            )

    def test_19_planning_capability_equals_actual_planner(self) -> None:
        for row in self.ledger:
            self.assertEqual(
                row["capability_projection"]["planning"], row["planner_requested"]
            )
            self.assertEqual(row["planner_requested"], row["recommendation_plan_present"])

    def test_20_working_context_and_episodic_memory_are_separate(self) -> None:
        self.assertGreater(self.baseline["working_context_without_episodic_memory_count"], 0)
        self.assertGreater(
            self.baseline["working_context_used_count"],
            self.baseline["episodic_memory_used_count"],
        )

    def test_21_duplicate_canonicalisation(self) -> None:
        result = canonicalise_cases((_placeholder_case("UNIT-D1"), _placeholder_case("UNIT-D2")))
        self.assertEqual(len(result.canonical_cases), 1)
        self.assertEqual(result.summary["exact_duplicate_extra_count"], 1)

    def test_22_context_variant_is_not_merged(self) -> None:
        first = _placeholder_case(
            "UNIT-V1",
            history=[{"role": "student", "content": "TOKEN_CONTEXT_ONE", "relevant": True}],
        )
        second = _placeholder_case(
            "UNIT-V2",
            history=[{"role": "student", "content": "TOKEN_CONTEXT_TWO", "relevant": True}],
        )
        result = canonicalise_cases((first, second))
        self.assertEqual(len(result.canonical_cases), 2)
        self.assertEqual(result.summary["context_variant_group_count"], 1)

    def test_23_source_lineage_is_preserved(self) -> None:
        result = canonicalise_cases((_placeholder_case("UNIT-L1"), _placeholder_case("UNIT-L2")))
        self.assertEqual(len(result.lineage_rows[0]["all_source_lineage"]), 2)
        self.assertTrue(result.summary["all_source_lineage_preserved"])

    def test_24_proposal_is_not_gold(self) -> None:
        case = _placeholder_case("UNIT-PROPOSAL")
        proposal = build_hidden_proposal(case)
        self.assertFalse(proposal["proposal_is_gold"])
        self.assertFalse(proposal["reviewer_visible"])
        self.assertTrue(all(not row["proposal_is_gold"] for row in self.proposals))

    def test_25_reviewer_human_fields_are_blank(self) -> None:
        self.assertTrue(
            all(not row[field] for row in [*self.review_a, *self.review_b] for field in HUMAN_FIELDS)
        )

    def test_26_reviewer_case_sets_are_identical(self) -> None:
        self.assertEqual(
            {row["case_id"] for row in self.review_a},
            {row["case_id"] for row in self.review_b},
        )

    def test_27_reviewer_orders_are_different(self) -> None:
        self.assertNotEqual(
            [row["case_id"] for row in self.review_a],
            [row["case_id"] for row in self.review_b],
        )

    def test_28_reviewer_packets_are_ignored(self) -> None:
        for relative in (LOCAL_REVIEW_A_RELATIVE, LOCAL_REVIEW_B_RELATIVE):
            result = subprocess.run(
                ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=ROOT
            )
            self.assertEqual(result.returncode, 0)

    def test_29_tracked_outputs_have_no_governed_query_text(self) -> None:
        self.assertEqual(governed_text_leak_scan(ROOT)["leak_count"], 0)

    def test_30_provider_and_network_are_disabled(self) -> None:
        self.assertEqual(self.baseline["provider_calls"], 0)
        self.assertEqual(self.baseline["firebase_calls"], 0)
        self.assertFalse(self.baseline["network_access"])

    def test_31_production_files_are_unchanged(self) -> None:
        assert_protected_sources_unchanged(ROOT)

    def test_32_double_build_is_byte_identical(self) -> None:
        assert_double_build(ROOT)

    def test_33_output_checksums_pass(self) -> None:
        validate_output_checksums(ROOT)

    def test_34_all_new_python_has_valid_ast(self) -> None:
        assert_all_python_ast()
        self.assertEqual(len(PYTHON_FILES), 11)

    def test_35_legacy_provider_free_smoke(self) -> None:
        smoke = provider_free_smoke(ROOT)
        self.assertEqual(smoke["status"], "PASS")
        self.assertEqual(smoke["router_identity"], "C0_COSINE")
        self.assertEqual(smoke["provider_calls"], 0)
        self.assertFalse(smoke["network_access"])

    def test_36_review_packet_validator(self) -> None:
        assert_review_packets(ROOT)

    def test_37_safe_json_and_change_scope(self) -> None:
        assert_safe_json()
        assert_change_scope(ROOT)
        assert_staged_content_safe(ROOT)

    def test_38_full_validator(self) -> None:
        validate_all(ROOT)


if __name__ == "__main__":
    unittest.main()
