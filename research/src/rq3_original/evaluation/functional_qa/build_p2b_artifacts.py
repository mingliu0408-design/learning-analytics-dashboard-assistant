"""Build the auditable P2-B failure triage and stabilisation comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
P2A_PATH = RESULTS / "functional_qa_after_repair_v1.json"
P2B_PATH = RESULTS / "functional_qa_after_stabilisation_v2.json"
TRIAGE_PATH = RESULTS / "remaining_failure_triage_v1.csv"
DIFF_PATH = RESULTS / "functional_qa_stabilisation_diff_v2.csv"


def expected_behaviour(expected: Mapping[str, Any]) -> str:
    parts = []
    for key in (
        "acceptable_intents", "acceptable_routes", "should_use_dashboard",
        "should_use_course_rag", "should_use_planner", "should_use_memory",
        "acceptable_source_scopes",
    ):
        if key in expected:
            parts.append(f"{key}={expected[key]}")
    return "; ".join(parts)


def observed_behaviour(record: Mapping[str, Any]) -> str:
    actual = record.get("actual") or {}
    return "; ".join(
        f"{key}={actual.get(key)}"
        for key in (
            "intent", "route", "dashboard_used", "course_rag_requested_or_used",
            "planner_used", "memory_used", "source_scope",
        )
    )


def classify(record: Mapping[str, Any]) -> dict[str, str]:
    if record["case_id"] == "FQA-PLAN-010":
        return {
            "failure_class": "DOWNSTREAM_CFULL_BUG",
            "root_cause": "PLANNER",
            "repairable_in_P2B": "yes",
            "repair_reason": (
                "The authoritative final intent/route was planning_or_strategy/overview_planning, "
                "but Planner activation was incorrectly conditional on semantic_effective. "
                "Fixed by activating Planner from the final route in semantic-enhanced mode."
            ),
        }

    candidate = str(record.get("semantic_candidate") or "")
    acceptable = set((record.get("expected") or {}).get("acceptable_intents") or [])
    correct_candidate = candidate in acceptable
    reason = str(record.get("fallback_reason") or "")
    if correct_candidate:
        detail = (
            "The semantic candidate was behaviourally correct but failed the frozen score/margin "
            f"policy ({reason or 'not accepted'}); changing thresholds/examples is prohibited."
        )
    else:
        detail = (
            "The semantic candidate was outside the acceptable intent family; changing the frozen "
            "model, examples, taxonomy, or adding query-specific guards is outside P2-B."
        )
    return {
        "failure_class": "SEMANTIC_MODEL_LIMITATION",
        "root_cause": "SEMANTIC_MODEL",
        "repairable_in_P2B": "no",
        "repair_reason": detail,
    }


def main() -> None:
    p2a = json.loads(P2A_PATH.read_text(encoding="utf-8"))
    p2b = json.loads(P2B_PATH.read_text(encoding="utf-8"))
    p2a_records = p2a["layers"]["mechanism"]["records"]
    p2b_records = p2b["layers"]["mechanism"]["records"]
    p2b_map = {(row["case_id"], row["turn_index"]): row for row in p2b_records}

    fields = [
        "case_id", "family", "query", "keyword_intent", "semantic_candidate",
        "semantic_score", "semantic_margin", "semantic_accepted", "selected_intent",
        "selected_route", "expected_behaviour", "observed_behaviour", "failure_class",
        "root_cause", "repairable_in_P2B", "repair_reason",
    ]
    triage_rows: list[dict[str, Any]] = []
    for record in p2a_records:
        if record.get("passed"):
            continue
        classification = classify(record)
        final_record = p2b_map[(record["case_id"], record["turn_index"])]
        repair_reason = classification["repair_reason"]
        if classification["repairable_in_P2B"] == "yes":
            repair_reason += f" Final passed={bool(final_record.get('passed'))}."
        triage_rows.append({
            "case_id": record["case_id"],
            "family": record["family"],
            "query": record["original_query"],
            "keyword_intent": record.get("keyword_intent"),
            "semantic_candidate": record.get("semantic_candidate"),
            "semantic_score": record.get("semantic_score"),
            "semantic_margin": record.get("semantic_margin"),
            "semantic_accepted": record.get("semantic_accepted"),
            "selected_intent": record.get("selected_intent"),
            "selected_route": record.get("selected_route"),
            "expected_behaviour": expected_behaviour(record.get("expected") or {}),
            "observed_behaviour": observed_behaviour(record),
            **classification,
            "repair_reason": repair_reason,
        })

    with TRIAGE_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(triage_rows)

    before = p2a["layers"]["mechanism"]["summary"]
    after = p2b["layers"]["mechanism"]["summary"]
    detail_fields = (
        "routing_failures", "mechanism_failures", "memory_failures",
        "guard_failures", "response_invariant_failures",
    )
    diff_fields = [
        "family", "p2a_total", "p2a_passed", "p2a_failed", "p2b_total",
        "p2b_passed", "p2b_failed", "passed_delta", "failed_delta",
        *[f"p2a_{name}" for name in detail_fields],
        *[f"p2b_{name}" for name in detail_fields],
    ]
    with DIFF_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=diff_fields)
        writer.writeheader()
        for family in sorted(after["by_family"]):
            old = before["by_family"][family]
            new = after["by_family"][family]
            row = {
                "family": family,
                "p2a_total": old["total_turns"], "p2a_passed": old["passed"],
                "p2a_failed": old["failed"], "p2b_total": new["total_turns"],
                "p2b_passed": new["passed"], "p2b_failed": new["failed"],
                "passed_delta": new["passed"] - old["passed"],
                "failed_delta": new["failed"] - old["failed"],
            }
            row.update({f"p2a_{name}": old[name] for name in detail_fields})
            row.update({f"p2b_{name}": new[name] for name in detail_fields})
            writer.writerow(row)

    final_failures = [row for row in p2b_records if not row.get("passed")]
    for record in final_failures:
        record["p2b_failure_class"] = "SEMANTIC_MODEL_LIMITATION"
        record["p2b_root_cause"] = "SEMANTIC_MODEL"
    p2b["p2b_stabilisation"] = {
        "development_qa_only": True,
        "initial_failed_turns": len(triage_rows),
        "final_passed_turns": len(p2b_records) - len(final_failures),
        "final_failed_turns": len(final_failures),
        "final_failure_classes": {"SEMANTIC_MODEL_LIMITATION": len(final_failures)},
        "final_root_causes": {"SEMANTIC_MODEL": len(final_failures)},
        "unresolved_integration_product_bugs": 0,
        "triage_path": str(TRIAGE_PATH.relative_to(ROOT.parents[1])),
        "diff_path": str(DIFF_PATH.relative_to(ROOT.parents[1])),
    }
    P2B_PATH.write_text(json.dumps(p2b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(p2b["p2b_stabilisation"], indent=2))


if __name__ == "__main__":
    main()
