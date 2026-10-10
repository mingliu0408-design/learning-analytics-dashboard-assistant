"""Execute the P2-A functional QA set through the production C_FULL service.

Layer 1 uses the real routing, evidence, retrieval, planner, guard, and memory
commit paths with a local deterministic completion stub. Layer 2 uses the same
service with the configured OpenAI client when a credential is available.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.assistant_modes import load_dashboard_data
from utils.c_full_service import generate_c_full_chat_turn


QA_DIR = Path(__file__).resolve().parent
CASES_PATH = QA_DIR / "functional_qa_cases_v1.jsonl"
CONTAMINATION_PATH = QA_DIR / "functional_qa_contamination_audit_v1.json"
RESULTS_DIR = QA_DIR / "results"
FAILURE_DIFF_PATH = RESULTS_DIR / "functional_qa_failure_diff_v1.csv"
SAFE_FALLBACK_DIFF_PATH = RESULTS_DIR / "functional_qa_safe_fallback_diff_v3.csv"
EXPLICIT_SAFETY_DIFF_PATH = RESULTS_DIR / "functional_qa_explicit_safety_diff_v4.csv"
QA_STUDENT_ID = "301127"
RESULT_PATHS = {
    "baseline": RESULTS_DIR / "functional_qa_baseline_v1.json",
    "after_repair": RESULTS_DIR / "functional_qa_after_repair_v1.json",
    "after_stabilisation": RESULTS_DIR / "functional_qa_after_stabilisation_v2.json",
    "after_safe_fallback": RESULTS_DIR / "functional_qa_after_safe_fallback_v3.json",
    "after_explicit_safety": RESULTS_DIR / "functional_qa_after_explicit_safety_v4.json",
}
FULL_RESPONSE_CASES = {
    "FQA-SOC-001", "FQA-SOC-002", "FQA-SOC-005", "FQA-SOC-007",
    "FQA-DASH-001", "FQA-DASH-004",
    "FQA-MET-001", "FQA-MET-005",
    "FQA-PLAN-001", "FQA-PLAN-004", "FQA-PLAN-008",
    "FQA-IMP-001", "FQA-IMP-004",
    "FQA-RAG-001", "FQA-RAG-002", "FQA-RAG-004", "FQA-RAG-007",
    "FQA-XPG-001", "FQA-XPG-006",
    "FQA-MEM-001", "FQA-MEM-002", "FQA-MEM-004", "FQA-MEM-006",
    "FQA-SRC-001", "FQA-SRC-003", "FQA-SRC-004",
    "FQA-GRD-001", "FQA-GRD-004",
    "FQA-AMB-001", "FQA-AMB-003",
    "FQA-OOS-001", "FQA-OOS-002",
}


class LocalQACompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="QA deterministic response."))]
        )


class LocalQAClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=LocalQACompletions())


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_openai_client() -> tuple[Any | None, str]:
    key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    source = "environment"
    if not key:
        secrets_path = PROJECT_ROOT / ".streamlit/secrets.toml"
        if secrets_path.is_file():
            secrets = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
            key = str(secrets.get("openai_api_key") or "").strip()
            source = "streamlit_secrets"
    if not key:
        return None, "unavailable"
    try:
        from openai import OpenAI
    except Exception:
        return None, "client_library_unavailable"
    return OpenAI(api_key=key), source


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def selected_domains(sources: list[str]) -> list[str]:
    return list(dict.fromkeys(source.split(".", 1)[0] for source in sources if "." in source))


def source_forbidden(forbidden: str, context: Mapping[str, Any]) -> bool:
    selected = list(context.get("rq1_selected_sources") or [])
    retrieval = bool(context.get("retrieval_requested") or context.get("retrieval_used"))
    allowed = list(context.get("allowed_source_types") or [])
    if forbidden == "course_material":
        return retrieval or "course_material" in allowed
    if forbidden == "dashboard":
        return bool(selected) or "dashboard" in allowed
    if forbidden == "memory":
        return bool((context.get("memory_resolution") or {}).get("resolved")) or "memory" in allowed
    if forbidden.startswith("dashboard:"):
        domain = forbidden.split(":", 1)[1]
        return any(source.startswith(domain + ".") for source in selected)
    return False


def evaluate_memory(expectation: Mapping[str, Any], context: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    metadata = context.get("memory_metadata") or {}
    plan = state.get("active_plan") or {}
    if expectation.get("active_plan_updated") is True and not metadata.get("active_plan_updated"):
        failures.append("memory:active_plan_not_updated")
    if expectation.get("active_plan_present") is True and not plan:
        failures.append("memory:active_plan_absent")
    if expectation.get("active_goal_present") is True and not state.get("active_goal"):
        failures.append("memory:active_goal_absent")
    if expectation.get("active_course_item_present") is True and not state.get("active_course_item"):
        failures.append("memory:active_course_item_absent")
    if expectation.get("numbered_referents_updated") is True and not metadata.get("numbered_referents_updated"):
        failures.append("memory:numbered_referents_not_updated")
    if expectation.get("corrections_applied") is True and not metadata.get("corrections_applied"):
        failures.append("memory:correction_not_applied")
    expected_number = str(expectation.get("referenced_item_number") or "")
    if expected_number and expected_number not in [str(item.get("number")) for item in metadata.get("referenced_items", [])]:
        failures.append("memory:numbered_reference_not_resolved")
    expected_week = str(expectation.get("active_course_week") or "")
    if expected_week and str((state.get("active_course_item") or {}).get("week")) != expected_week:
        failures.append("memory:course_week_not_updated")
    completed_step = expectation.get("completed_step")
    if completed_step is not None and int(completed_step) not in [int(item.get("index")) for item in plan.get("completed_steps", [])]:
        failures.append("memory:completed_step_not_recorded")
    next_step = expectation.get("next_pending_step")
    if next_step is not None and int((plan.get("next_pending_step") or {}).get("index", -1)) != int(next_step):
        failures.append("memory:next_pending_step_wrong")
    return failures


def evaluate_turn(expected: Mapping[str, Any], context: Mapping[str, Any], state: Mapping[str, Any], response: str, *, response_layer: bool) -> dict[str, Any]:
    intent = str(context.get("query_type") or "")
    route = str(context.get("selected_route") or "")
    selected = list(context.get("rq1_selected_sources") or [])
    dashboard = bool(selected)
    rag = bool(context.get("retrieval_requested") or context.get("retrieval_used"))
    planner = bool(context.get("rq2_recommendation_plan"))
    memory = bool((context.get("memory_resolution") or {}).get("resolved"))
    scope = str(context.get("source_scope") or "")
    failures: list[str] = []
    if expected.get("acceptable_intents") and intent not in expected["acceptable_intents"]:
        failures.append(f"routing:intent={intent}")
    if intent in expected.get("forbidden_intents", []):
        failures.append(f"routing:forbidden_intent={intent}")
    if expected.get("acceptable_routes") and route not in expected["acceptable_routes"]:
        failures.append(f"routing:route={route}")
    for field, actual in (("should_use_dashboard", dashboard), ("should_use_course_rag", rag),
                          ("should_use_planner", planner), ("should_use_memory", memory)):
        wanted = expected.get(field)
        if wanted is not None and bool(wanted) != actual:
            kind = "memory" if field == "should_use_memory" else "mechanism"
            failures.append(f"{kind}:{field}={actual}")
    if expected.get("acceptable_source_scopes") and scope not in expected["acceptable_source_scopes"]:
        failures.append(f"mechanism:source_scope={scope}")
    domain = str(context.get("primary_evidence_domain") or "")
    if expected.get("expected_primary_domain") and domain != expected["expected_primary_domain"]:
        failures.append(f"mechanism:primary_domain={domain}")
    for forbidden in expected.get("forbidden_source_types", []):
        if source_forbidden(forbidden, context):
            failures.append(f"guard:forbidden_source_used={forbidden}")
    failures.extend(evaluate_memory(expected.get("memory_expectation") or {}, context, state))

    invariants = expected.get("response_invariants") or {}
    if response_layer:
        if invariants.get("must_be_brief") and len(response.split()) > 45:
            failures.append("response:too_long")
        if invariants.get("must_request_clarification") and not any(
            token in response.casefold() for token in ("which", "what you mean", "clarify", "more context")
        ):
            failures.append("response:no_clarification")
        if invariants.get("must_not_include_dashboard_statistics") and any(char.isdigit() for char in response):
            failures.append("response:dashboard_statistics_present")
        if invariants.get("must_contain_actionable_steps") and planner and not any(
            marker in response for marker in ("1.", "- ")
        ):
            failures.append("response:no_visible_steps")
        if invariants.get("must_not_claim_causality") and "caused" in response.casefold() and "not" not in response.casefold():
            failures.append("response:causal_overclaim")
    categories = sorted(set(item.split(":", 1)[0] for item in failures))
    return {
        "passed": not failures,
        "failures": failures,
        "failure_categories": categories,
        "actual": {
            "intent": intent, "route": route, "dashboard_used": dashboard,
            "course_rag_requested_or_used": rag, "planner_used": planner,
            "memory_used": memory, "source_scope": scope,
        },
    }


def semantic_contribution(intent_routing: Mapping[str, Any], expected: Mapping[str, Any]) -> str:
    """Classify semantic contribution against the case oracle, not just router agreement."""
    keyword = str(intent_routing.get("keyword_intent") or "")
    candidate = str(intent_routing.get("semantic_candidate") or "")
    selected = str(intent_routing.get("selected_intent") or "")
    source = str(intent_routing.get("routing_source") or "")
    fallback_reason = str(intent_routing.get("fallback_reason") or "")
    accepted = bool(intent_routing.get("semantic_accepted"))
    acceptable = set(expected.get("acceptable_intents") or [])
    keyword_correct = keyword in acceptable
    candidate_correct = candidate in acceptable
    selected_correct = selected in acceptable
    guard = bool(intent_routing.get("protected_guard_reasons")) or source == "deterministic_guard"
    if guard and selected_correct:
        return "DETERMINISTIC_GUARD_CORRECTLY_WINS"
    if accepted and not candidate_correct:
        return "SEMANTIC_WRONGLY_OVERRIDES"
    if accepted and candidate_correct and (candidate == keyword or keyword_correct):
        return "SEMANTIC_AND_KEYWORD_AGREE"
    if accepted and candidate_correct:
        return "SEMANTIC_CORRECTS_KEYWORD"
    policy_rejected = fallback_reason.startswith((
        "semantic_score_below_threshold",
        "semantic_margin_below_threshold",
    ))
    if fallback_reason.startswith("special_semantic_outcome:out_of_scope"):
        score = float(intent_routing.get("semantic_score") or 0.0)
        margin = float(intent_routing.get("semantic_margin") or 0.0)
        policy_rejected = score < 0.323827 or margin < 0.134525
    if candidate_correct and not selected_correct and not policy_rejected:
        return "SEMANTIC_CORRECT_BUT_INTEGRATION_REJECTS"
    if not candidate_correct and not selected_correct:
        return "SEMANTIC_MODEL_ERROR"
    return "SEMANTIC_REJECTED_CORRECTLY"


def product_safety_outcome(assessment: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    """Classify safety/usability separately from strict intent correctness."""

    failures = list(assessment.get("failures") or [])
    if any(item.startswith("guard:") for item in failures):
        return "GUARD_FAILURE"
    if assessment.get("passed"):
        return "CORRECT_ROUTE"
    route = str(context.get("selected_route") or "")
    no_sources = not list(context.get("rq1_selected_sources") or [])
    no_rag = not bool(context.get("retrieval_requested") or context.get("retrieval_used"))
    no_plan = not bool(context.get("rq2_recommendation_plan"))
    if route in {"semantic_uncertain", "ambiguous_clarification", "follow_up_without_context"}:
        if no_sources and no_rag and no_plan:
            return "SAFE_CLARIFICATION"
    if route in {"out_of_scope", "unsupported_task", "source_boundary_capability"}:
        if no_sources and no_rag and no_plan:
            return "SAFE_CAPABILITY_RESPONSE"
    return "MISLEADING_ROUTE"


def diagnostic_record(case_id: str, family: str, turn_index: int, expected: Mapping[str, Any], outcome: Any,
                      before_state: Mapping[str, Any], layer: str) -> dict[str, Any]:
    runtime = outcome.runtime_result
    if runtime is None:
        return {"case_id": case_id, "family": family, "turn_index": turn_index,
                "query": expected["query"], "passed": False,
                "failures": ["mechanism:chat_turn_failed"],
                "failure_categories": ["mechanism"],
                "product_safety_outcome": "SYSTEM_ERROR",
                "final_response": outcome.response}
    context = runtime.context
    state = outcome.structured_memory
    routing = context.get("intent_routing") or {}
    assessment = evaluate_turn(expected, context, state, outcome.response, response_layer=layer == "full_response")
    memory_resolution = context.get("memory_resolution") or {}
    memory_metadata = context.get("memory_metadata") or {}
    record = {
        "case_id": case_id,
        "family": family,
        "turn_index": turn_index,
        "layer": layer,
        "original_query": context.get("original_student_query", expected["query"]),
        "effective_query": context.get("effective_query", ""),
        "routing_mode": routing.get("routing_mode"),
        "keyword_intent": routing.get("keyword_intent"),
        "keyword_rule_id": routing.get("keyword_rule_id"),
        "semantic_status": routing.get("semantic_status"),
        "semantic_candidate": routing.get("semantic_candidate"),
        "semantic_score": routing.get("semantic_score"),
        "semantic_margin": routing.get("semantic_margin"),
        "semantic_accepted": routing.get("semantic_accepted"),
        "selected_intent": context.get("query_type"),
        "adapter_selected_intent": routing.get("adapter_selected_intent"),
        "routing_source": routing.get("routing_source"),
        "fallback_reason": routing.get("fallback_reason"),
        "protected_guard_reasons": routing.get("protected_guard_reasons", []),
        "uncertainty_fallback_used": bool(routing.get("uncertainty_fallback_used")),
        "uncertainty_reason": routing.get("uncertainty_reason", ""),
        "clarification_hint_intent": routing.get("clarification_hint_intent"),
        "clarification_hint_score": routing.get("clarification_hint_score"),
        "semantic_contribution": semantic_contribution(routing, expected),
        "selected_route": context.get("selected_route"),
        "source_scope": context.get("source_scope"),
        "source_scope_reason": context.get("source_scope_reason"),
        "selected_evidence_sources": context.get("rq1_selected_sources", []),
        "evidence_domains_used": selected_domains(context.get("rq1_selected_sources", [])),
        "retrieval_requested": bool(context.get("retrieval_requested")),
        "retrieval_used": bool(context.get("retrieval_used")),
        "course_chunks_used": list(context.get("supporting_chunk_ids") or []),
        "recommendation_plan_used": bool(context.get("rq2_recommendation_plan")),
        "memory_triggered": bool(memory_metadata.get("memory_triggered") or memory_resolution.get("is_follow_up")),
        "memory_resolved": bool(memory_resolution.get("resolved")),
        "memory_used": bool(memory_metadata.get("memory_used") or memory_resolution.get("resolved")),
        "active_plan_updated": bool(memory_metadata.get("active_plan_updated")),
        "memory_fields_changed": changed_fields(before_state, state),
        "memory_state_before": deepcopy(before_state),
        "memory_state_after": deepcopy(state),
        "final_response": outcome.response,
        "expected": dict(expected),
        **assessment,
    }
    record["product_safety_outcome"] = product_safety_outcome(assessment, context)
    return record


def run_layer(cases: list[dict[str, Any]], *, layer: str, client: Any, model: str) -> list[dict[str, Any]]:
    dashboard_data = load_dashboard_data()
    records: list[dict[str, Any]] = []
    for case in cases:
        history: list[Any] = []
        memory: dict[str, Any] = {}
        for turn_index, expected in enumerate(case["turns"], 1):
            before = deepcopy(memory)
            outcome = generate_c_full_chat_turn(
                student_query=expected["query"], student_id=QA_STUDENT_ID, current_page=expected["page"],
                conversation_history=history, existing_session_memory=memory,
                dashboard_data=dashboard_data, openai_client=client, model=model,
                retrieval_backend="v2_4", intent_router_mode="semantic_enhanced",
            )
            records.append(diagnostic_record(case["case_id"], case["family"], turn_index,
                                             expected, outcome, before, layer))
            if outcome.succeeded:
                history = list(outcome.memory_turns)
                memory = dict(outcome.structured_memory)
    return records


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["family"]].append(record)
    for family, rows in sorted(grouped.items()):
        failed = [row for row in rows if not row.get("passed")]
        counts = Counter(category for row in failed for category in row.get("failure_categories", []))
        by_family[family] = {
            "total_turns": len(rows), "passed": len(rows) - len(failed), "failed": len(failed),
            "routing_failures": counts["routing"], "mechanism_failures": counts["mechanism"],
            "memory_failures": counts["memory"], "guard_failures": counts["guard"],
            "response_invariant_failures": counts["response"],
        }
    contributions = Counter(row.get("semantic_contribution") for row in records if row.get("semantic_contribution"))
    safety = Counter(row.get("product_safety_outcome", "SYSTEM_ERROR") for row in records)
    return {
        "total_turns": len(records),
        "passed": sum(bool(row.get("passed")) for row in records),
        "failed": sum(not bool(row.get("passed")) for row in records),
        "by_family": by_family,
        "semantic_contribution": dict(sorted(contributions.items())),
        "product_safety": {
            name: safety.get(name, 0)
            for name in (
                "CORRECT_ROUTE", "SAFE_CLARIFICATION", "SAFE_CAPABILITY_RESPONSE",
                "MISLEADING_ROUTE", "GUARD_FAILURE", "SYSTEM_ERROR",
            )
        },
    }


def write_failure_diff() -> None:
    """Write a compact, reviewable family-level baseline/after comparison."""
    baseline_path = RESULT_PATHS["baseline"]
    after_path = RESULT_PATHS["after_repair"]
    if not baseline_path.is_file() or not after_path.is_file():
        return
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["layers"]["mechanism"]["summary"]
    after = json.loads(after_path.read_text(encoding="utf-8"))["layers"]["mechanism"]["summary"]
    fields = (
        "routing_failures", "mechanism_failures", "memory_failures",
        "guard_failures", "response_invariant_failures",
    )
    families = sorted(set(baseline["by_family"]) | set(after["by_family"]))
    with FAILURE_DIFF_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "family", "baseline_total", "baseline_passed", "baseline_failed",
            "after_total", "after_passed", "after_failed", "failure_delta",
            *[f"baseline_{field}" for field in fields],
            *[f"after_{field}" for field in fields],
        ])
        writer.writeheader()
        for family in families:
            before = baseline["by_family"].get(family, {})
            final = after["by_family"].get(family, {})
            row = {
                "family": family,
                "baseline_total": before.get("total_turns", 0),
                "baseline_passed": before.get("passed", 0),
                "baseline_failed": before.get("failed", 0),
                "after_total": final.get("total_turns", 0),
                "after_passed": final.get("passed", 0),
                "after_failed": final.get("failed", 0),
                "failure_delta": final.get("failed", 0) - before.get("failed", 0),
            }
            row.update({f"baseline_{field}": before.get(field, 0) for field in fields})
            row.update({f"after_{field}": final.get(field, 0) for field in fields})
            writer.writerow(row)


def write_safe_fallback_diff() -> None:
    """Compare frozen P2-B strict results with P2-C strict and safety outcomes."""

    before_path = RESULT_PATHS["after_stabilisation"]
    after_path = RESULT_PATHS["after_safe_fallback"]
    if not before_path.is_file() or not after_path.is_file():
        return
    before = json.loads(before_path.read_text(encoding="utf-8"))["layers"]["mechanism"]
    after = json.loads(after_path.read_text(encoding="utf-8"))["layers"]["mechanism"]
    before_families = before["summary"]["by_family"]
    after_families = after["summary"]["by_family"]
    safety_by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for record in after["records"]:
        safety_by_family[record["family"]][record["product_safety_outcome"]] += 1
    safety_names = (
        "CORRECT_ROUTE", "SAFE_CLARIFICATION", "SAFE_CAPABILITY_RESPONSE",
        "MISLEADING_ROUTE", "GUARD_FAILURE", "SYSTEM_ERROR",
    )
    fields = [
        "family", "total_turns", "strict_before_passed", "strict_after_passed",
        "strict_before_failed", "strict_after_failed", "strict_failure_delta",
        *[name.casefold() for name in safety_names],
    ]
    with SAFE_FALLBACK_DIFF_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for family in sorted(set(before_families) | set(after_families)):
            old = before_families.get(family, {})
            new = after_families.get(family, {})
            counts = safety_by_family[family]
            writer.writerow({
                "family": family,
                "total_turns": new.get("total_turns", 0),
                "strict_before_passed": old.get("passed", 0),
                "strict_after_passed": new.get("passed", 0),
                "strict_before_failed": old.get("failed", 0),
                "strict_after_failed": new.get("failed", 0),
                "strict_failure_delta": new.get("failed", 0) - old.get("failed", 0),
                **{name.casefold(): counts.get(name, 0) for name in safety_names},
            })


def write_explicit_safety_diff() -> None:
    """Compare P2-C with the final explicit-heuristic safety closure."""

    before_path = RESULT_PATHS["after_safe_fallback"]
    after_path = RESULT_PATHS["after_explicit_safety"]
    if not before_path.is_file() or not after_path.is_file():
        return
    before = json.loads(before_path.read_text(encoding="utf-8"))["layers"]["mechanism"]
    after = json.loads(after_path.read_text(encoding="utf-8"))["layers"]["mechanism"]
    before_by_key = {
        (row["case_id"], row["turn_index"]): row for row in before["records"]
    }
    fields = [
        "case_id", "family", "turn_index", "query", "strict_before_passed",
        "strict_after_passed", "product_before", "product_after", "route_before",
        "route_after", "keyword_rule_id", "semantic_candidate", "semantic_score",
        "semantic_margin", "uncertainty_reason",
    ]
    changed = []
    for row in after["records"]:
        old = before_by_key[(row["case_id"], row["turn_index"])]
        if (
            old.get("product_safety_outcome") == row.get("product_safety_outcome")
            and old.get("selected_route") == row.get("selected_route")
        ):
            continue
        changed.append({
            "case_id": row["case_id"], "family": row["family"],
            "turn_index": row["turn_index"], "query": row["original_query"],
            "strict_before_passed": bool(old.get("passed")),
            "strict_after_passed": bool(row.get("passed")),
            "product_before": old.get("product_safety_outcome"),
            "product_after": row.get("product_safety_outcome"),
            "route_before": old.get("selected_route"),
            "route_after": row.get("selected_route"),
            "keyword_rule_id": row.get("keyword_rule_id"),
            "semantic_candidate": row.get("semantic_candidate"),
            "semantic_score": row.get("semantic_score"),
            "semantic_margin": row.get("semantic_margin"),
            "uncertainty_reason": row.get("uncertainty_reason"),
        })
    with EXPLICIT_SAFETY_DIFF_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(changed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=sorted(RESULT_PATHS), required=True)
    parser.add_argument("--layer", choices=("mechanism", "full", "all"), default="mechanism")
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()
    cases = load_cases()
    contamination = json.loads(CONTAMINATION_PATH.read_text(encoding="utf-8"))
    if contamination["exact_matches"] or contamination["normalised_matches"]:
        raise SystemExit("Contamination audit failed; regenerate the development QA set.")
    prior_result: dict[str, Any] = {}
    if RESULT_PATHS[args.phase].is_file():
        prior_result = json.loads(RESULT_PATHS[args.phase].read_text(encoding="utf-8"))
    layers: dict[str, Any] = dict(prior_result.get("layers") or {})
    # Keep persisted live-response records compatible when diagnostic
    # categorisation improves; this does not repeat hosted generation.
    for layer_value in layers.values():
        prior_records = layer_value.get("records") or []
        for record in prior_records:
            routing = {
                "keyword_intent": record.get("keyword_intent"),
                "semantic_candidate": record.get("semantic_candidate"),
                "selected_intent": record.get("selected_intent"),
                "routing_source": record.get("routing_source"),
                "fallback_reason": record.get("fallback_reason"),
                "semantic_score": record.get("semantic_score"),
                "semantic_margin": record.get("semantic_margin"),
                "semantic_accepted": record.get("semantic_accepted"),
                "protected_guard_reasons": record.get("protected_guard_reasons"),
            }
            record["semantic_contribution"] = semantic_contribution(routing, record.get("expected") or {})
        if prior_records:
            layer_value["summary"] = summarise(prior_records)
    if args.layer in {"mechanism", "all"}:
        records = run_layer(cases, layer="mechanism", client=LocalQAClient(), model="local-qa-stub")
        layers["mechanism"] = {"summary": summarise(records), "records": records}
    if args.layer in {"full", "all"}:
        client, credential_status = load_openai_client()
        selected = [case for case in cases if case["case_id"] in FULL_RESPONSE_CASES]
        if client is None:
            layers["full_response"] = {
                "executed": False, "reason": credential_status,
                "selected_cases": len(selected), "records": [],
            }
        else:
            try:
                # Fail once, before the suite, when the configured API is unreachable.
                # This avoids turning infrastructure unavailability into dozens of false
                # product failures while still exercising the real configured client.
                client.chat.completions.create(
                    model=args.model,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                    temperature=0,
                    max_tokens=3,
                )
            except Exception as exc:
                layers["full_response"] = {
                    "executed": False,
                    "reason": f"configured_api_unreachable:{type(exc).__name__}",
                    "credential_source": credential_status,
                    "selected_cases": len(selected),
                    "records": [],
                }
            else:
                records = run_layer(selected, layer="full_response", client=client, model=args.model)
                layers["full_response"] = {
                    "executed": True, "credential_source": credential_status,
                    "selected_cases": len(selected), "summary": summarise(records), "records": records,
                }
    result = {
        "schema_version": "p2-a-functional-qa-results-v1",
        "development_functional_qa_only": True,
        "not_formal_evaluation": True,
        "phase": args.phase,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "routing_mode": "semantic_enhanced",
        "retrieval_backend": "v2_4",
        "dataset": {
            "path": str(CASES_PATH.relative_to(PROJECT_ROOT)),
            "total_cases": len(cases),
            "single_turn_cases": sum(len(case["turns"]) == 1 for case in cases),
            "multi_turn_sequences": sum(len(case["turns"]) > 1 for case in cases),
            "families": sorted(set(case["family"] for case in cases)),
        },
        "contamination_audit": contamination,
        "layers": layers,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_PATHS[args.phase]
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_failure_diff()
    if args.phase == "after_safe_fallback":
        write_safe_fallback_diff()
    if args.phase == "after_explicit_safety":
        write_explicit_safety_diff()
    print(json.dumps({name: value.get("summary", value) for name, value in layers.items()}, indent=2))
    print(path)


if __name__ == "__main__":
    main()
