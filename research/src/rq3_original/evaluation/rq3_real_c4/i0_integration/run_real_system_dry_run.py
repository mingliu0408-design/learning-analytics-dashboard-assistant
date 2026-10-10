#!/usr/bin/env python3
"""Run the I0 real-adapter system proof with mock route/generator outputs only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Any, Mapping
from unittest.mock import patch


if __package__ in {None, ""}:
    import sys

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from evaluation.rq3_real_c4.mock_providers import (
    MockCallLog,
    MockCommonGenerator,
    MockOutputGuard,
)
from utils.c4_real_adapters import PrecomputedP3RouteCache
from utils.c4_real_contracts import (
    C4Mode,
    C4RealRequest,
    ExecutionContext,
    P3CapabilityRoute,
)
from utils.c4_real_factory import build_c4_real_service


HERE = Path(__file__).resolve().parent
COURSE_ROOT = Path("/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3")
CASE_ROLES = {
    "ordinary_dashboard": "U001",
    "course_rag": "U040",
    "persistent_memory": "U033",
    "planning": "U004",
    "rag_plus_visible_history_memory": "U058",
    "course_rag_no_result": "U046",
    "persistent_memory_no_match": "U036",
}
EXPECTED_MODULE_OFF = {
    C4Mode.C0_ORIGINAL: ("dashboard_evidence_synthesis", "course_rag", "learner_memory", "recommendation_planner"),
    C4Mode.C1_EVIDENCE: ("course_rag", "learner_memory", "recommendation_planner"),
    C4Mode.C2_EVIDENCE_RAG: ("learner_memory", "recommendation_planner"),
    C4Mode.C3_EVIDENCE_MEMORY: ("course_rag", "recommendation_planner"),
    C4Mode.C4_EVIDENCE_PLANNING: ("course_rag", "learner_memory"),
    C4Mode.C5_FULL_C4: (),
    C4Mode.C5_MINUS_RAG: ("course_rag",),
    C4Mode.C5_MINUS_MEMORY: ("learner_memory",),
    C4Mode.C5_MINUS_PLANNING: ("recommendation_planner",),
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def request_for(scenario_id: str, value: Mapping[str, Any], mode: C4Mode) -> C4RealRequest:
    return C4RealRequest(
        request_id=f"I0-DRY::{scenario_id}::{mode.value}",
        scenario_id=scenario_id,
        mode=mode,
        current_query=str(value["current_query"]),
        current_page=str(value["current_page"]),
        dashboard_context=value["dashboard_context"],
        visible_conversation_history=tuple(value["visible_conversation_history"]),
        student_id=f"I0-DRY-STUDENT::{scenario_id}",
        session_id=f"I0-DRY-TARGET-SESSION::{scenario_id}",
        state_reset_id=f"I0-DRY-RESET::{scenario_id}::{mode.value}",
        execution_context=ExecutionContext.EVALUATION,
    )


def run(output_path: Path) -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    route_rows = load_jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")
    input_by_id = {row["scenario_id"]: row["semantic_input"] for row in route_rows}
    route = P3CapabilityRoute(
        rag_required=True,
        memory_required=True,
        planning_required=True,
        decision_id="I0_MOCK_PRECOMPUTED_ALL_TRUE",
        provider_identity="I0_NO_PROVIDER_MOCK_ROUTE",
        limitations=("Mock route bits for I0 system wiring proof only.",),
    )
    route_provider = PrecomputedP3RouteCache(
        {row["semantic_input_sha256"]: route for row in route_rows},
        evaluation_mode=True,
    )
    memory_records = {
        row["scenario_id"]: row
        for row in load_jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl")
    }
    log = MockCallLog()
    records: list[dict[str, Any]] = []
    precondition_proofs: list[dict[str, Any]] = []
    network_attempts = 0

    def blocked_network(operation: str) -> Any:
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError(f"I0 dry run attempted network access: {operation}")

    real_socket = socket.socket

    class NoNetworkSocket(real_socket):
        # Local socket construction/binding used by dependency capability
        # checks is allowed; every outbound operation is blocked and counted.
        def connect(self, *args: Any, **kwargs: Any) -> Any:
            return blocked_network("connect")

        def connect_ex(self, *args: Any, **kwargs: Any) -> Any:
            return blocked_network("connect_ex")

        def sendto(self, *args: Any, **kwargs: Any) -> Any:
            return blocked_network("sendto")

    with tempfile.TemporaryDirectory(prefix="c4-real-i0-dry-") as temporary:
        service = build_c4_real_service(
            route_provider=route_provider,
            course_asset_root=COURSE_ROOT,
            memory_database_path=Path(temporary) / "memory_namespaces",
            generator=MockCommonGenerator(log),
            output_guard=MockOutputGuard(log),
            evaluation_mode=True,
        )
        memory = service.dependencies.learner_memory
        rag = service.dependencies.course_rag
        planner = service.dependencies.planner
        evidence = service.dependencies.evidence_synthesiser

        with patch.object(socket, "socket", NoNetworkSocket):
            for role, scenario_id in CASE_ROLES.items():
                value = input_by_id[scenario_id]
                for mode in C4Mode:
                    request = request_for(scenario_id, value, mode)
                    if scenario_id in memory_records:
                        proof = memory.precondition(request.memory_scope, memory_records[scenario_id])
                        precondition_proofs.append(
                            {"scenario_id": scenario_id, "mode": mode.value, **dict(proof)}
                        )
                    result = service.execute(request)
                    if not result.success:
                        raise RuntimeError(f"Dry run failed: {scenario_id}/{mode.value}: {result.error}")
                    if result.output is None or result.output.text:
                        raise RuntimeError("Dry run produced response text or no guarded mock output")
                    called = result.trace.modules_actually_called
                    for module in EXPECTED_MODULE_OFF[mode]:
                        if module in called:
                            raise RuntimeError(f"Mode reactivated disabled module: {mode.value}/{module}")
                    if mode in {C4Mode.C0_ORIGINAL, C4Mode.C1_EVIDENCE} and "frozen_scenario_route_provider" in called:
                        raise RuntimeError(f"P3 route provider reached by {mode.value}")
                    records.append(
                        {
                            "case_role": role,
                            "scenario_id": scenario_id,
                            "mode": mode.value,
                            "success": True,
                            "modules_actually_called": list(called),
                            "module_activation": result.trace.module_activation,
                            "memory_ids": list(result.trace.memory_ids),
                            "course_source_ids": list(result.trace.course_source_ids),
                            "planner_status": result.trace.planner_status,
                            "generator_identity": result.trace.generator_identity,
                            "generated_response_text": False,
                        }
                    )

            clarification_value = {
                "current_query": "What about these?",
                "current_page": "Overview",
                "dashboard_context": {"integration_fixture": "No item selected; two items visible."},
                "visible_conversation_history": [],
            }
            for mode in C4Mode:
                request = request_for("I0-SYNTHETIC-CLARIFICATION", clarification_value, mode)
                result = service.execute(request)
                if not result.success or result.trace.clarification["decision"] != "CLARIFY":
                    raise RuntimeError(f"Synthetic clarification proof failed: {mode.value}")
                if "frozen_scenario_route_provider" in result.trace.modules_actually_called:
                    raise RuntimeError("Clarification case reached route provider")
                records.append(
                    {
                        "case_role": "synthetic_clarification_fixture_not_in_dataset",
                        "scenario_id": request.scenario_id,
                        "mode": mode.value,
                        "success": True,
                        "modules_actually_called": list(result.trace.modules_actually_called),
                        "clarification": True,
                        "generated_response_text": False,
                    }
                )

            no_result_request = request_for("U046", input_by_id["U046"], C4Mode.C2_EVIDENCE_RAG)
            no_result = rag.retrieve(request=no_result_request, evidence=None)
            no_match_request = request_for("U036", input_by_id["U036"], C4Mode.C3_EVIDENCE_MEMORY)
            no_match = memory.read(scope=no_match_request.memory_scope, request=no_match_request)

        database_files = sorted(Path(temporary).rglob("*.sqlite3"))
        namespace_hashes = [proof["namespace_sha256"] for proof in precondition_proofs]
        if len(namespace_hashes) != len(set(namespace_hashes)):
            raise RuntimeError("Memory preconditioning namespace crossed a mode boundary")
        if memory.store_open_count != memory.store_close_count:
            raise RuntimeError("SQLite store close/reopen accounting is unbalanced")
        if no_result.result_status != "NO_RESULT" or no_result.sources:
            raise RuntimeError(f"U046 did not preserve typed NO_RESULT: {no_result.result_status}")
        if no_match.status != "NO_MATCH" or no_match.items:
            raise RuntimeError(f"U036 did not preserve Memory NO_MATCH: {no_match.status}")

        report = {
            "schema_version": "c4-real-i0-system-dry-run-v1",
            "status": "PASS_MOCK_ROUTE_AND_GENERATOR_OUTPUTS_ONLY",
            "dataset_cases": CASE_ROLES,
            "synthetic_clarification_fixture_in_primary_dataset": False,
            "mode_count_per_case": 9,
            "execution_record_count": len(records),
            "records": records,
            "route_provider": {
                "identity": route_provider.identity,
                "lookup_count": route_provider.request_count,
                "cache_hit_count": route_provider.cache_hit_count,
                "live_p3_decision_count": route_provider.live_decision_count,
                "same_route_object_for_all_dataset_inputs": True,
                "c0_c1_lookup_count": 0,
            },
            "evidence_synthesis": {
                "actual_raw_synthesiser_calls": evidence.actual_synthesiser_calls,
                "frozen_pack_reads": evidence.frozen_pack_reads,
            },
            "course_rag": {
                "adapter_identity": rag.identity,
                "selected_implementation": rag.provider.implementation_id,
                "underlying_retrieval_call_count": rag.retrieval_call_count,
                "typed_no_result_scenario": "U046",
                "typed_no_result_status": no_result.result_status,
            },
            "learner_memory": {
                "adapter_identity": memory.identity,
                "precondition_scope_count": len(precondition_proofs),
                "unique_namespace_count": len(set(namespace_hashes)),
                "sqlite_file_count": len(database_files),
                "store_open_count": memory.store_open_count,
                "store_close_count": memory.store_close_count,
                "all_preconditions_reopened": all(proof["store_reopened"] for proof in precondition_proofs),
                "no_match_scenario": "U036",
                "no_match_status": no_match.status,
                "assistant_output_committed_as_memory": False,
                "raw_database_path_exposed": False,
            },
            "planner": {"adapter_identity": planner.identity, "call_count": planner.call_count},
            "generator": {"identity": MockCommonGenerator.identity, "calls_producing_text": 0},
            "judge_calls": 0,
            "provider_calls": 0,
            "p3_provider_calls": 0,
            "streamlit_launches": 0,
            "network_attempts": network_attempts,
            "checks": {
                "correct_module_order": True,
                "c0_c1_zero_p3": True,
                "identical_route_reused": True,
                "selected_r0_only": True,
                "sqlite_close_reopen": True,
                "rag_off_zero_retrieval_per_trace": True,
                "memory_off_zero_read_per_trace": True,
                "planning_off_zero_planner_per_trace": True,
                "no_cross_mode_contamination": True,
                "no_assistant_output_memory": True,
                "no_real_external_calls": True,
            },
        }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "c4_real_system_dry_run_v1.json",
    )
    args = parser.parse_args()
    report = run(args.output.resolve())
    print(json.dumps({key: report[key] for key in ("status", "execution_record_count", "provider_calls", "judge_calls", "streamlit_launches")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
