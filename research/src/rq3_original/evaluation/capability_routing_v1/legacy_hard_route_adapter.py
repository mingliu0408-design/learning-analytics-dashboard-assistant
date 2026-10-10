"""Provider-free measurement of the frozen production hard-routing path.

This research adapter calls the current production functions and projects
their observed decisions onto the CapabilityPlan vocabulary.  It never changes
those decisions and is not a candidate production router.
"""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
from typing import Any, Iterable, Iterator, Mapping
from unittest.mock import patch

from evaluation.packaged_dashboard_fixture import build_packaged_dashboard_frames
from utils.evidence_synthesiser import DashboardData
import utils.c_full_service as production_service
import utils.production_intent_router as production_router

from . import (
    LOCAL_BANK_RELATIVE,
    LOCAL_BASELINE_RELATIVE,
    PREDICTED_CAPABILITIES,
    ROOT,
    RQ1_FINAL_ROUTER,
    canonical_json_bytes,
    require_frozen_rq1_router,
    safe_count_distribution,
    sha256_file,
)
from .capability_case_schema import CapabilityCaseV1


PRODUCTION_FUNCTIONS = (
    "build_c_full_context",
    "prepare_mode_cm_context",
    "route_production_intent",
    "authoritative_c_full_query_type",
    "decide_c_full_source_scope",
    "build_recommendation_plan",
)
CLARIFICATION_ROUTES = frozenset(
    {
        "ambiguous",
        "semantic_uncertain",
        "course_reference_clarification",
        "follow_up_without_context",
    }
)
OFFLINE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


def _blocked_network(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("RQ2-A baseline forbids network access")


@contextmanager
def provider_free_environment() -> Iterator[None]:
    """Fail closed on socket use while keeping model/provider settings offline."""

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, OFFLINE_ENVIRONMENT, clear=False))
        stack.enter_context(patch("socket.create_connection", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect_ex", _blocked_network))
        yield


def _hash_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _dashboard_fixture() -> DashboardData:
    return DashboardData(**build_packaged_dashboard_frames())


def _load_cases(root: Path) -> list[CapabilityCaseV1]:
    return [
        CapabilityCaseV1.from_mapping(json.loads(line))
        for line in (root / LOCAL_BANK_RELATIVE)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def _working_memory_dependency(context: Mapping[str, Any]) -> bool:
    memory = dict(context.get("memory_resolution") or {})
    if bool(memory.get("resolved")) and (
        memory.get("referenced_items")
        or memory.get("memory_context")
        or str(memory.get("resolution_type") or "") not in {"", "none", "not_follow_up"}
    ):
        return True
    if context.get("selected_route") == "memory_state_direct_answer":
        state = dict(memory.get("structured_state") or {})
        return any(
            state.get(name)
            for name in (
                "active_goal",
                "active_plan",
                "constraints",
                "completed_actions",
                "corrections",
            )
        )
    return False


def _project_capabilities(
    context: Mapping[str, Any], call_counts: Mapping[str, int]
) -> dict[str, bool]:
    retrieval_requested = bool(context.get("retrieval_requested"))
    planner_requested = call_counts.get("build_recommendation_plan", 0) > 0
    episodic_memory = _working_memory_dependency(context)
    selected_route = str(context.get("selected_route") or "")
    selected_intent = str(
        (context.get("intent_routing") or {}).get("selected_intent") or ""
    )
    clarification = bool(
        selected_route in CLARIFICATION_ROUTES
        or selected_intent in {"ambiguous", "semantic_uncertain"}
    )
    evidence = dict(context.get("rq1_evidence_summary") or {})
    allowed_sources = set(context.get("allowed_source_types") or [])
    dashboard_evidence = bool(
        not clarification
        and "dashboard" in allowed_sources
        and (
            context.get("rq1_selected_sources")
            or evidence.get("selected_sources")
            or evidence.get("selected_evidence")
        )
    )
    projection = {
        "dashboard_evidence": dashboard_evidence,
        "course_retrieval": retrieval_requested and not clarification,
        "episodic_memory": episodic_memory and not clarification,
        "planning": planner_requested and not clarification,
        "safe_direct_response": False,
        "clarification": clarification,
    }
    if clarification:
        for name in PREDICTED_CAPABILITIES:
            projection[name] = name == "clarification"
    elif not any(projection[name] for name in PREDICTED_CAPABILITIES):
        projection["safe_direct_response"] = True
    return projection


def _deterministic_guards(context: Mapping[str, Any]) -> list[str]:
    routing = dict(context.get("intent_routing") or {})
    guards = [str(value) for value in routing.get("protected_guard_reasons") or []]
    if context.get("selected_route") == "source_boundary_capability":
        guards.append("explicit_source_restriction")
    if context.get("source_scope") == "no_supported_source":
        guards.append("unsupported_operation")
    return sorted(set(guards))


def measure_case(
    case: CapabilityCaseV1,
    *,
    semantic_runtime: Any,
    dashboard_data: DashboardData | None = None,
) -> dict[str, Any]:
    """Measure one case through the current production implementation."""

    fixture = dashboard_data or _dashboard_fixture()
    mocks: dict[str, Any] = {}
    with ExitStack() as stack:
        for name in PRODUCTION_FUNCTIONS:
            mocks[name] = stack.enter_context(
                patch.object(
                    production_service,
                    name,
                    wraps=getattr(production_service, name),
                )
            )
        context = production_service.build_c_full_context(
            student_query=case.current_query,
            student_id="301127",
            current_page=case.current_page,
            conversation_history=list(case.conversation_history),
            existing_session_memory=None,
            dashboard_data=fixture,
            retrieval_backend="v2_4",
            retrieval_context={"v2_4_retriever_error": "RQ2A_PROVIDER_FREE_NOOP"},
            allow_retrieval_v1_fallback=False,
            intent_router_mode="semantic_enhanced",
            intent_router_runtime=semantic_runtime,
        )
    call_counts = {name: int(mock.call_count) for name, mock in mocks.items()}
    projection = _project_capabilities(context, call_counts)
    intent_routing = dict(context.get("intent_routing") or {})
    selected_intent = str(
        intent_routing.get("adapter_selected_intent")
        or intent_routing.get("selected_intent")
        or context.get("query_type")
        or ""
    )
    recommendation_present = bool(context.get("rq2_recommendation_plan"))
    planner_requested = call_counts["build_recommendation_plan"] > 0
    if projection["course_retrieval"] != bool(context.get("retrieval_requested")):
        raise AssertionError("legacy course capability diverged from actual request")
    if projection["planning"] != planner_requested:
        raise AssertionError("legacy planning capability diverged from actual Planner call")
    if planner_requested != recommendation_present:
        raise AssertionError("Planner call and recommendation-plan presence diverged")
    return {
        "schema_version": "legacy-hard-routing-ledger-v1",
        "case_id": case.case_id,
        "original_query_hash": _hash_text(case.current_query),
        "resolved_query_hash": _hash_text(
            context.get("effective_query") or case.current_query
        ),
        "selected_intent": selected_intent,
        "selected_route": str(context.get("selected_route") or ""),
        "source_scope": str(context.get("source_scope") or ""),
        "retrieval_requested": bool(context.get("retrieval_requested")),
        "retrieval_used": bool(context.get("retrieval_used")),
        "planner_requested": planner_requested,
        "recommendation_plan_present": recommendation_present,
        "working_context_used": call_counts["prepare_mode_cm_context"] > 0,
        "episodic_memory_used": projection["episodic_memory"],
        "clarification_triggered": projection["clarification"],
        "deterministic_guard": _deterministic_guards(context),
        "capability_projection": projection,
        "production_call_counts": call_counts,
        "router_identity": RQ1_FINAL_ROUTER,
    }


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
        for row in rows
    )


def _aggregate(rows: list[dict[str, Any]], ledger_path: Path) -> dict[str, Any]:
    calls: Counter[str] = Counter()
    capability_counts: Counter[str] = Counter()
    for row in rows:
        calls.update(row["production_call_counts"])
        capability_counts.update(
            name for name, active in row["capability_projection"].items() if active
        )
    required_calls = {
        name: calls.get(name, 0) > 0
        for name in PRODUCTION_FUNCTIONS
        if name != "build_recommendation_plan"
    }
    if not all(required_calls.values()):
        raise AssertionError("legacy adapter did not exercise all required production functions")
    return {
        "schema_version": "legacy-capability-projection-v1",
        "stage": "RQ2-A",
        "status": "PASS",
        "baseline_identity": "B0_FROZEN_C0_TOP1_HARD_ROUTE",
        "router_identity": RQ1_FINAL_ROUTER,
        "m64_used": False,
        "measurement_only": True,
        "production_behavior_changed": False,
        "record_count": len(rows),
        "ledger_storage": "LOCAL_ONLY_IGNORED",
        "ledger_sha256": sha256_file(ledger_path),
        "selected_intent_distribution": safe_count_distribution(
            [row["selected_intent"] for row in rows]
        ),
        "selected_route_distribution": safe_count_distribution(
            [row["selected_route"] for row in rows]
        ),
        "source_scope_distribution": safe_count_distribution(
            [row["source_scope"] for row in rows]
        ),
        "capability_positive_count": {
            name: capability_counts.get(name, 0) for name in PREDICTED_CAPABILITIES
        },
        "retrieval_requested_count": sum(row["retrieval_requested"] for row in rows),
        "retrieval_used_count": sum(row["retrieval_used"] for row in rows),
        "planner_requested_count": sum(row["planner_requested"] for row in rows),
        "recommendation_plan_present_count": sum(
            row["recommendation_plan_present"] for row in rows
        ),
        "working_context_used_count": sum(row["working_context_used"] for row in rows),
        "episodic_memory_used_count": sum(row["episodic_memory_used"] for row in rows),
        "working_context_without_episodic_memory_count": sum(
            row["working_context_used"] and not row["episodic_memory_used"]
            for row in rows
        ),
        "production_function_call_counts": dict(sorted(calls.items())),
        "required_production_functions_called": required_calls,
        "retrieval_projection_equals_actual_request": True,
        "planning_projection_equals_actual_planner_condition": True,
        "working_context_and_episodic_memory_separated": True,
        "synthetic_packaged_dashboard_fixture": True,
        "retrieval_adapter": "V2_4_PROVIDER_FREE_NOOP_PRESERVING_REQUEST",
        "provider_calls": 0,
        "firebase_calls": 0,
        "network_access": False,
        "training_performed": False,
        "checkpoint_modified": False,
        "threshold_modified": False,
    }


class LegacyHardRoutingCapabilityAdapterV1:
    """Named measurement adapter for the frozen C0 production path.

    The class owns no routing rules.  Its only operation delegates each case
    to :func:`measure_case`, which in turn calls ``build_c_full_context`` and
    observes the current production decisions.
    """

    schema_version = "legacy-hard-routing-capability-adapter-v1"
    router_identity = RQ1_FINAL_ROUTER
    measurement_only = True

    def __init__(self, *, semantic_runtime: Any, dashboard_data: DashboardData) -> None:
        self._semantic_runtime = semantic_runtime
        self._dashboard_data = dashboard_data

    def measure(self, case: CapabilityCaseV1) -> dict[str, Any]:
        return measure_case(
            case,
            semantic_runtime=self._semantic_runtime,
            dashboard_data=self._dashboard_data,
        )


def build_legacy_baseline(root: Path = ROOT) -> dict[str, Any]:
    """Measure the full canonical bank and persist only a safe aggregate."""

    require_frozen_rq1_router(root)
    cases = _load_cases(root)
    if len(cases) < 20:
        raise RuntimeError("BLOCKED_RQ2_A_INSUFFICIENT_DEVELOPMENT_CASES")
    with provider_free_environment():
        runtime = production_router.load_production_semantic_router()
        dashboard = _dashboard_fixture()
        adapter = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=runtime, dashboard_data=dashboard
        )
        rows = [adapter.measure(case) for case in cases]
    ledger_path = root / LOCAL_BASELINE_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_bytes(_jsonl_bytes(rows))
    aggregate = _aggregate(rows, ledger_path)
    output = root / "evaluation/capability_routing_v1/legacy_capability_projection_v1.json"
    output.write_bytes(canonical_json_bytes(aggregate))
    return aggregate


def provider_free_smoke(root: Path = ROOT) -> dict[str, Any]:
    """Run one real production-path case without exposing its natural language."""

    require_frozen_rq1_router(root)
    case = _load_cases(root)[0]
    with provider_free_environment():
        runtime = production_router.load_production_semantic_router()
        row = measure_case(case, semantic_runtime=runtime)
    return {
        "status": "PASS",
        "case_id_hash": _hash_text(row["case_id"]),
        "router_identity": row["router_identity"],
        "build_c_full_context_calls": row["production_call_counts"][
            "build_c_full_context"
        ],
        "provider_calls": 0,
        "network_access": False,
    }


if __name__ == "__main__":
    value = build_legacy_baseline()
    print(
        json.dumps(
            {
                "status": value["status"],
                "record_count": value["record_count"],
                "router_identity": value["router_identity"],
                "provider_calls": value["provider_calls"],
                "network_access": value["network_access"],
            },
            sort_keys=True,
        )
    )
