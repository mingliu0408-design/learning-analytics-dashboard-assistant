"""Provider-free Episodic Memory reachability audit over frozen RQ2-B ledgers."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_rq2b_v1.gold_preflight import load_and_validate_gold

from . import ROOT, sha256_file
from .episodic_memory_semantics import MechanismObservations, classify_mechanism
from .rq2b_identity import verify_local_ledgers


B0_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "b0_predictions/b0_synthetic_v1.jsonl"
)
B1_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "b1_predictions/b1_synthetic_v1.jsonl"
)
P1_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "p1_predictions/synthetic_P1_D05_SIGNAL_UNION.jsonl"
)
ENVELOPE_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "envelopes/context_envelopes_v1.jsonl"
)
RAW_SYNTHETIC_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "synthetic_coverage_stress_gold_v1.jsonl"
)
LOCAL_ROWS_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/local_artifacts/"
    "episodic_memory_reachability_rows_v1.jsonl"
)

EXECUTION_CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
)


class ReachabilityAuditError(RuntimeError):
    pass


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _indexed(rows: Iterable[Mapping[str, Any]], *keys: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        key = next((str(row.get(name)) for name in keys if row.get(name)), "")
        if not key or key in result:
            raise ReachabilityAuditError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")
        result[key] = row
    return result


def _prediction(row: Mapping[str, Any], model: str) -> bool:
    if model == "P1":
        return "episodic_memory" in set(row.get("predicted_capabilities") or [])
    return bool((row.get("capability_projection") or {}).get("episodic_memory"))


def _confusion(gold: Mapping[str, bool], rows: Mapping[str, Mapping[str, Any]], model: str) -> dict[str, int]:
    tp = fp = fn = tn = 0
    for case_id, required in gold.items():
        predicted = _prediction(rows[case_id], model)
        if required and predicted:
            tp += 1
        elif required:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _state_flags(envelope: Mapping[str, Any], raw_history: Iterable[Mapping[str, Any]]) -> dict[str, bool]:
    history = list(raw_history)
    completion = any(
        isinstance(turn.get("explicit_goal"), Mapping)
        and str(turn["explicit_goal"].get("status") or "").lower() == "completed"
        for turn in history
    )
    flags = {
        "active_goal_present": bool(envelope.get("active_goal")),
        "active_plan_present": bool(envelope.get("active_plan")),
        "constraint_present": bool(envelope.get("explicit_constraints")),
        "latest_correction_present": bool(envelope.get("latest_correction")),
        "referenced_item_present": bool(envelope.get("referenced_items")),
        "completion_present": completion,
    }
    flags["structured_memory_present"] = any(flags.values())
    return flags


def _nested_status_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(key in value for key in ("active", "stale", "superseded", "cancelled", "status")):
            return True
        return any(_nested_status_present(item) for item in value.values())
    if isinstance(value, list):
        return any(_nested_status_present(item) for item in value)
    return False


def _nested_negative_status_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        status = str(value.get("status") or "").lower()
        if status in {"completed", "replaced", "cancelled", "superseded", "stale", "inactive"}:
            return True
        if any(value.get(name) is True for name in ("stale", "superseded", "cancelled")):
            return True
        return any(_nested_negative_status_present(item) for item in value.values())
    if isinstance(value, list):
        return any(_nested_negative_status_present(item) for item in value)
    return False


def _non_active_history_state_present(history: Iterable[Mapping[str, Any]]) -> bool:
    for turn in history:
        goal = turn.get("explicit_goal")
        if isinstance(goal, Mapping) and str(goal.get("status") or "").lower() in {
            "completed",
            "replaced",
            "cancelled",
            "superseded",
            "stale",
        }:
            return True
    return False


def build_episodic_reachability_audit(write_local: bool = True) -> dict[str, Any]:
    verify_local_ledgers()
    gold_result = load_and_validate_gold(ROOT)
    gold = {
        item.router_input.case_id: item.labels.episodic_memory
        for item in gold_result.synthetic_gold
    }
    if len(gold) != 35 or sum(gold.values()) != 8:
        raise ReachabilityAuditError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")

    b0 = _indexed(_jsonl(ROOT / B0_RELATIVE), "case_id", "review_case_id")
    b1 = _indexed(_jsonl(ROOT / B1_RELATIVE), "case_id", "review_case_id")
    p1 = _indexed(_jsonl(ROOT / P1_RELATIVE), "review_case_id", "case_id")
    envelopes = _indexed(_jsonl(ROOT / ENVELOPE_RELATIVE), "case_id")
    raw = _indexed(_jsonl(ROOT / RAW_SYNTHETIC_RELATIVE), "review_case_id")
    expected_ids = set(gold)
    if any(set(rows) != expected_ids for rows in (b0, b1, p1)) or not expected_ids <= set(envelopes):
        raise ReachabilityAuditError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")

    confusions = {
        "B0": _confusion(gold, b0, "B0"),
        "B1": _confusion(gold, b1, "B1"),
        "P1": _confusion(gold, p1, "P1"),
    }
    expected = {
        "B0": {"tp": 0, "fp": 0, "fn": 8},
        "B1": {"tp": 3, "fp": 1, "fn": 5},
        "P1": {"tp": 0, "fp": 0, "fn": 8},
    }
    for model, partial in expected.items():
        if any(confusions[model][key] != value for key, value in partial.items()):
            raise ReachabilityAuditError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")

    local_rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    mechanism_counts: Counter[str] = Counter()
    for case_id in sorted(case_id for case_id, required in gold.items() if required):
        prediction = p1[case_id]
        context = dict(prediction.get("context_status") or {})
        deterministic = dict(prediction.get("deterministic_evidence") or {})
        envelope = envelopes[case_id]
        history = list(raw[case_id].get("necessary_conversation_history") or [])
        flags = _state_flags(envelope, history)
        semantic_support = list(
            ((prediction.get("semantic_evidence") or {}).get("supporting_intents") or {}).get(
                "episodic_memory"
            )
            or []
        )
        deterministic_support = list(
            (deterministic.get("capability_evidence") or {}).get("episodic_memory") or []
        )
        episodic_before_exclusivity = bool(semantic_support or deterministic_support)
        working_dependency = bool(deterministic.get("working_memory_dependency"))
        clarification_override = bool(
            (prediction.get("capability_plan") or {}).get("clarification_required")
        )
        reasons: list[str] = []
        if not flags["structured_memory_present"]:
            reasons.append("NO_STATE_SIGNAL")
        if not bool(context.get("resolver_resolved")):
            reasons.append("RESOLVER_DID_NOT_RESOLVE")
        if not working_dependency:
            reasons.append("LEGACY_DEPENDENCY_FALSE")
        if clarification_override and episodic_before_exclusivity:
            reasons.append("CLARIFICATION_EXCLUSIVITY_SUPPRESSED")
        if flags["structured_memory_present"] and not working_dependency:
            reasons.append("STATE_PRESENT_BUT_NOT_MARKED_DEPENDENT")
        if not semantic_support:
            reasons.append("SEMANTIC_MAP_HAS_NO_EPISODIC_SUPPORT")
        if not reasons:
            reasons.append("OTHER_EXPLICITLY_REPORTED")
        reason_counts.update(reasons)

        mechanism = classify_mechanism(
            MechanismObservations(
                visible_history_present=bool(history),
                working_state_object_present=flags["structured_memory_present"],
                context_missing=context.get("status") == "MISSING_REQUIRED_CONTEXT",
                explicit_additional_retrieval_target=False,
            )
        )
        mechanism_counts[mechanism] += 1
        local_rows.append(
            {
                "case_id": case_id,
                "history_present": bool(history),
                "recent_turn_count": len(envelope.get("recent_relevant_turns") or []),
                **flags,
                "resolver_is_follow_up": bool(context.get("resolver_is_follow_up")),
                "resolver_resolved": bool(context.get("resolver_resolved")),
                "resolution_type": str(context.get("resolution_type") or ""),
                "context_status": str(context.get("status") or ""),
                "plan_memory_need": bool(
                    (deterministic.get("need_signals") or {}).get("plan_memory_need")
                ),
                "discrepancy_correction_need": bool(
                    (deterministic.get("need_signals") or {}).get(
                        "discrepancy_correction_need"
                    )
                ),
                "legacy_working_memory_dependency": working_dependency,
                "p1_clarification_override": clarification_override,
                "p1_episodic_evidence_before_exclusivity": episodic_before_exclusivity,
                "p1_final_episodic_prediction": False,
                "false_negative_reasons": sorted(set(reasons)),
                "mechanism_classification": mechanism,
                "history_contains_non_active_state": _non_active_history_state_present(history),
                "structured_state_exposes_freshness_status": any(
                    _nested_status_present(envelope.get(name))
                    for name in (
                        "active_goal",
                        "active_plan",
                        "explicit_constraints",
                        "latest_correction",
                        "referenced_items",
                    )
                ),
                "structured_state_exposes_negative_freshness_status": any(
                    _nested_negative_status_present(envelope.get(name))
                    for name in (
                        "active_goal",
                        "active_plan",
                        "explicit_constraints",
                        "latest_correction",
                        "referenced_items",
                    )
                ),
            }
        )

    unresolved = mechanism_counts["UNRESOLVED_MECHANISM_LABEL"]
    if len(local_rows) != 8 or any(not row["false_negative_reasons"] for row in local_rows):
        raise ReachabilityAuditError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")
    if unresolved:
        raise ReachabilityAuditError("BLOCKED_RQ2_C0_MEMORY_MECHANISM_LABEL_UNRESOLVED")

    local_path = ROOT / LOCAL_ROWS_RELATIVE
    if write_local:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in local_rows
            ),
            encoding="utf-8",
        )
    local_sha = sha256_file(local_path) if local_path.is_file() else ""
    return {
        "schema_version": "episodic-memory-reachability-audit-v1",
        "stage": "RQ2-C0",
        "status": "PASS",
        "gold_episodic_positive_count": 8,
        "confusion": confusions,
        "p1_false_negative_count": 8,
        "p1_false_negative_reason_counts": dict(sorted(reason_counts.items())),
        "all_false_negatives_assigned_reason": True,
        "mechanism_classification_counts": {
            name: mechanism_counts[name]
            for name in (
                "SATISFIED_BY_WORKING_CONTEXT",
                "REQUIRES_ADDITIONAL_EPISODIC_RETRIEVAL",
                "MISSING_CONTEXT_REQUIRES_CLARIFICATION",
                "UNRESOLVED_MECHANISM_LABEL",
            )
        },
        "history_with_non_active_state_count": sum(
            row["history_contains_non_active_state"] for row in local_rows
        ),
        "structured_state_with_freshness_status_count": sum(
            row["structured_state_exposes_freshness_status"] for row in local_rows
        ),
        "structured_stale_or_superseded_negative_control_count": sum(
            row["structured_state_exposes_negative_freshness_status"]
            for row in local_rows
        ),
        "local_case_audit_record_count": len(local_rows),
        "local_case_audit_sha256": local_sha,
        "local_case_audit_tracked": False,
        "query_specific_rule_count": 0,
        "gold_used_as_candidate_feature": False,
        "scenario_family_used_as_mechanism_feature": False,
        "provider_calls": 0,
        "network_access": False,
    }
