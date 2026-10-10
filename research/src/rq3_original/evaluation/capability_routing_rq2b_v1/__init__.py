"""Research-only RQ2-B offline capability-routing experiment.

This package is deliberately outside the production import graph.  It uses
the frozen RQ1 cosine router and existing production functions as measured
dependencies, but it neither changes nor installs a production router.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

STARTING_BRANCH = "research/rq2-a-r2b-capability-gold-freeze"
STARTING_HEAD = "c1e630ef1a414bcc9de56cefaf58c8455bb93b3d"
STARTING_PARENT = "b9e7aa1b3ef5714223e0298512f11537d8602490"
RESULT_BRANCH = "research/rq2-b-capability-routing-development"
REVIEW_ZIP_NAME = "RQ2_B_CAPABILITY_ROUTING_DEVELOPMENT_REVIEW_2026-08-26.zip"

RQ1_FINAL_ROUTER = "C0_COSINE"
B0_IDENTITY = "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION"
B1_IDENTITY = "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE"
P1_IDENTITY = "P1_CONTEXT_ENVELOPE_C0_SCORE_VECTOR_MULTILABEL_CAPABILITY_PLAN"

CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)
EXECUTION_CAPABILITIES = CAPABILITIES[:4]
POLICY_IDS = (
    "P1_K1_SIGNAL_UNION",
    "P1_K2_SIGNAL_UNION",
    "P1_K3_SIGNAL_UNION",
    "P1_D05_SIGNAL_UNION",
    "P1_D10_SIGNAL_UNION",
)

GOLD_ROUTER_FORBIDDEN_FIELDS = frozenset(
    {
        "source_role",
        "gold_inclusion_status",
        "gold_decision_source",
        "case_validity",
        "context_sufficient",
        "capability_unambiguous",
        "context_resolution_required",
        "dashboard_evidence",
        "course_retrieval",
        "episodic_memory",
        "planning",
        "safe_direct_response",
        "clarification",
        "forbidden_capabilities",
        "naturalness",
        "query_naturalness_1_to_5",
        "scenario_family",
        "reviewer_rationale",
        "adjudicator_rationale",
    }
)

LOCAL_ARTIFACTS_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts"
)
LOCAL_ARTIFACT_SUBDIRECTORIES = (
    "envelopes",
    "c0_score_vectors",
    "b0_predictions",
    "b1_predictions",
    "p1_predictions",
    "policy_selection_traces",
    "error_ledgers",
)

SAFE_OUTPUT_FILENAMES = (
    "rq2b_gold_preflight_v1.json",
    "rq2b_runtime_preflight_v1.json",
    "rq2b_b0_contract_v1.json",
    "rq2b_b1_reproduction_v1.json",
    "rq2b_p1_policy_family_v1.json",
    "rq2b_family_split_manifest_v1.json",
    "rq2b_nested_oof_results_v1.json",
    "rq2b_final_p1_policy_v1.json",
    "rq2b_synthetic_comparison_v1.json",
    "rq2b_development_uncertainty_v1.json",
    "rq2b_authentic_descriptive_results_v1.json",
    "rq2b_context_missing_diagnostic_v1.json",
    "rq2b_error_analysis_v1.json",
    "rq2b_validation_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2B_B0_B1_P1_EXPERIMENT_PROTOCOL.md",
    "RQ2B_P1_CAPABILITY_ROUTER_DESIGN.md",
    "RQ2B_SYNTHETIC_FAMILY_GROUPED_RESULTS.md",
    "RQ2B_AUTHENTIC_DESCRIPTIVE_RESULTS.md",
    "RQ2B_LIMITATIONS_AND_FAILURE_ANALYSIS.md",
)


class RQ2BError(RuntimeError):
    """Fail-closed RQ2-B contract error with an explicit blocker code."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def canonical_jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_canonical_json(path: Path, value: Any) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def safe_distribution(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def capability_order(values: Iterable[str]) -> tuple[str, ...]:
    selected = set(values)
    unknown = selected - set(CAPABILITIES)
    if unknown:
        raise RQ2BError(f"unknown capabilities: {sorted(unknown)}")
    return tuple(name for name in CAPABILITIES if name in selected)
