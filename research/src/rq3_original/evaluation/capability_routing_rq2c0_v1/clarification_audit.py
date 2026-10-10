"""Aggregate-only audit of frozen P1 clarification reachability."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from . import ROOT, sha256_file
from .rq2b_identity import verify_local_ledgers


SYNTHETIC_GOLD_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "synthetic_coverage_stress_gold_v1.jsonl"
)
REGISTRY_GOLD_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2b/local_gold/"
    "authentic_context_missing_qualitative_registry_v1.jsonl"
)
SYNTHETIC_P1_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "p1_predictions/synthetic_P1_D05_SIGNAL_UNION.jsonl"
)
REGISTRY_P1_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "p1_predictions/registry_final_policy_v1.jsonl"
)
LOCAL_ROWS_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/local_artifacts/"
    "clarification_reachability_rows_v1.jsonl"
)
EXECUTION_CAPABILITIES = {
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
}


class ClarificationAuditError(RuntimeError):
    pass


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {str(row.get("review_case_id")): row for row in rows}
    if len(result) != len(rows) or "" in result:
        raise ClarificationAuditError("BLOCKED_RQ2_C0_CLARIFICATION_AUDIT_MISMATCH")
    return result


def trace_reason(row: Mapping[str, Any]) -> str:
    context = dict(row.get("context_status") or {})
    if context.get("status") == "MISSING_REQUIRED_CONTEXT":
        if context.get("resolution_type") == "no_active_plan":
            return "NO_ACTIVE_PLAN"
        if context.get("resolver_is_follow_up") and not context.get("resolver_resolved"):
            return "FOLLOW_UP_WITHOUT_CONTEXT"
        return "MISSING_REQUIRED_CONTEXT"
    if context.get("deterministic_ambiguity_guard"):
        return "DETERMINISTIC_AMBIGUITY"
    return "OTHER_EXISTING_REASON"


def build_clarification_audit(write_local: bool = True) -> dict[str, Any]:
    verify_local_ledgers()
    synthetic_gold = _by_id(_rows(ROOT / SYNTHETIC_GOLD_RELATIVE))
    registry_gold = _by_id(_rows(ROOT / REGISTRY_GOLD_RELATIVE))
    synthetic = _by_id(_rows(ROOT / SYNTHETIC_P1_RELATIVE))
    registry = _by_id(_rows(ROOT / REGISTRY_P1_RELATIVE))
    if set(synthetic) != set(synthetic_gold) or set(registry) != set(registry_gold):
        raise ClarificationAuditError("BLOCKED_RQ2_C0_CLARIFICATION_AUDIT_MISMATCH")

    local_rows: list[dict[str, Any]] = []
    predicted = [
        row for row in synthetic.values()
        if "clarification" in set(row.get("predicted_capabilities") or [])
    ]
    true_positive = [
        row for row in predicted
        if synthetic_gold[str(row["review_case_id"])].get("clarification") == "YES"
    ]
    false_positive = [row for row in predicted if row not in true_positive]
    suppressed: Counter[str] = Counter()
    for row in predicted:
        capabilities = set(
            (row.get("semantic_evidence") or {}).get("selected_capabilities") or []
        ) | set((row.get("deterministic_evidence") or {}).get("capabilities") or [])
        for capability in capabilities & EXECUTION_CAPABILITIES:
            suppressed[capability] += 1
        local_rows.append(
            {
                "source_partition": "SYNTHETIC35",
                "case_id": row["review_case_id"],
                "gold_clarification": synthetic_gold[str(row["review_case_id"])][
                    "clarification"
                ],
                "predicted_clarification": True,
                "trace_reason": trace_reason(row),
                "suppressed_execution_capabilities": sorted(
                    capabilities & EXECUTION_CAPABILITIES
                ),
            }
        )

    registry_predicted = [
        row for row in registry.values()
        if "clarification" in set(row.get("predicted_capabilities") or [])
    ]
    unsafe = [
        row for row in registry.values()
        if "clarification" not in set(row.get("predicted_capabilities") or [])
        and bool(set(row.get("predicted_capabilities") or []) & EXECUTION_CAPABILITIES)
    ]
    unsafe_caps = Counter(
        capability
        for row in unsafe
        for capability in set(row.get("predicted_capabilities") or []) & EXECUTION_CAPABILITIES
    )
    for row in registry.values():
        local_rows.append(
            {
                "source_partition": "AUTHENTIC_CONTEXT_MISSING3",
                "case_id": row["review_case_id"],
                "gold_clarification": registry_gold[str(row["review_case_id"])][
                    "clarification"
                ],
                "predicted_clarification": "clarification"
                in set(row.get("predicted_capabilities") or []),
                "trace_reason": (
                    trace_reason(row)
                    if "clarification" in set(row.get("predicted_capabilities") or [])
                    else "RESOLVER_DID_NOT_DETECT_CONTEXT_DEPENDENCY"
                ),
                "unsafe_execution_capabilities": sorted(
                    set(row.get("predicted_capabilities") or []) & EXECUTION_CAPABILITIES
                ),
            }
        )

    synthetic_gold_positive = sum(
        row.get("clarification") == "YES" for row in synthetic_gold.values()
    )
    registry_gold_positive = sum(
        row.get("clarification") == "YES" for row in registry_gold.values()
    )
    counts = {
        "synthetic_gold_positive_count": synthetic_gold_positive,
        "synthetic_predicted_positive_count": len(predicted),
        "synthetic_tp": len(true_positive),
        "synthetic_fp": len(false_positive),
        "synthetic_fn": synthetic_gold_positive - len(true_positive),
        "registry_record_count": len(registry),
        "registry_gold_positive_count": registry_gold_positive,
        "registry_predicted_positive_count": len(registry_predicted),
        "registry_tp": len(registry_predicted),
        "registry_fn": registry_gold_positive - len(registry_predicted),
        "registry_execution_capability_false_positive_count": len(unsafe),
    }
    expected = {
        "synthetic_gold_positive_count": 3,
        "synthetic_predicted_positive_count": 11,
        "synthetic_tp": 3,
        "synthetic_fp": 8,
        "synthetic_fn": 0,
        "registry_record_count": 3,
        "registry_gold_positive_count": 3,
        "registry_predicted_positive_count": 1,
        "registry_tp": 1,
        "registry_fn": 2,
        "registry_execution_capability_false_positive_count": 2,
    }
    if counts != expected:
        raise ClarificationAuditError("BLOCKED_RQ2_C0_CLARIFICATION_AUDIT_MISMATCH")

    local_rows.sort(key=lambda row: (row["source_partition"], row["case_id"]))
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
    return {
        "schema_version": "clarification-gate-reachability-audit-v1",
        "stage": "RQ2-C0",
        "status": "PASS",
        **counts,
        "synthetic_prediction_reason_distribution": dict(
            sorted(Counter(trace_reason(row) for row in predicted).items())
        ),
        "synthetic_false_positive_reason_distribution": dict(
            sorted(Counter(trace_reason(row) for row in false_positive).items())
        ),
        "clarification_exclusivity_suppressed_execution_capabilities": dict(
            sorted(suppressed.items())
        ),
        "registry_unsafe_continuation_reason_distribution": {
            "RESOLVER_DID_NOT_DETECT_CONTEXT_DEPENDENCY": len(unsafe)
        },
        "registry_unsafe_execution_capability_distribution": dict(
            sorted(unsafe_caps.items())
        ),
        "case_specific_fix_proposed": False,
        "local_case_audit_record_count": len(local_rows),
        "local_case_audit_sha256": sha256_file(local_path) if local_path.is_file() else "",
        "local_case_audit_tracked": False,
        "provider_calls": 0,
        "network_access": False,
    }
