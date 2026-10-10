"""Build the complete local-only RQ2-A capability development bank.

The natural-language bank, duplicate lineage, and proposal ledger are all
ignored.  Only aggregate, query-free summaries are suitable for Git.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from . import (
    LOCAL_BANK_RELATIVE,
    LOCAL_LINEAGE_RELATIVE,
    LOCAL_PROPOSAL_RELATIVE,
    LOCAL_SYNTHETIC_SOURCE_RELATIVE,
    PREDICTED_CAPABILITIES,
    ROOT,
    canonical_json_bytes,
    safe_count_distribution,
    sha256_file,
)
from .capability_case_schema import CapabilityCaseV1
from .duplicate_lineage import CanonicalisationResult, canonicalise_cases
from .source_inventory import build_source_inventory, load_allowlisted_cases


MINIMUM_CANONICAL_CASE_COUNT = 20
INTENT_CAPABILITY_SEED_MAP: dict[str, tuple[str, ...]] = {
    "dashboard_interpretation": ("dashboard_evidence",),
    "quantitative_metric_query": ("dashboard_evidence",),
    "metric_clarification": ("dashboard_evidence",),
    "technical_data_question": ("dashboard_evidence",),
    "reflection_structure_question": ("dashboard_evidence",),
    "cross_page_relationship": ("dashboard_evidence",),
    "course_content_question": ("course_retrieval",),
    "hybrid_course_and_planning": (
        "dashboard_evidence",
        "course_retrieval",
        "planning",
    ),
    "planning_or_strategy": ("planning",),
    "improvement_recommendation": ("planning",),
    "memory_state_query": ("episodic_memory",),
    "social_interaction": ("safe_direct_response",),
    "emotional_or_justification": ("safe_direct_response",),
    "access_or_capability_question": ("safe_direct_response",),
}

ROUTE_CAPABILITY_SEED_MAP: dict[str, tuple[str, ...]] = {
    "dashboard_interpretation": ("dashboard_evidence",),
    "technical_data": ("dashboard_evidence",),
    "cross_page_relationship": ("dashboard_evidence",),
    "course_content": ("course_retrieval",),
    "course_only_planning": ("course_retrieval", "planning"),
    "hybrid_course_and_planning": (
        "dashboard_evidence",
        "course_retrieval",
        "planning",
    ),
    "rq2_recommendation": ("dashboard_evidence", "planning"),
    "memory_state_direct_answer": ("episodic_memory",),
    "memory_resolved_follow_up": ("episodic_memory",),
    "memory_plan_revision": ("episodic_memory", "planning"),
    "course_reference_clarification": ("clarification",),
    "follow_up_without_context": ("clarification",),
    "access_or_capability": ("safe_direct_response",),
}


@dataclass(frozen=True)
class DevelopmentBankBuild:
    cases: tuple[CapabilityCaseV1, ...]
    canonicalisation: CanonicalisationResult
    source_inventory: dict[str, Any]
    bank_summary: dict[str, Any]
    duplicate_summary: dict[str, Any]


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
        for row in rows
    )


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def load_local_synthetic_cases(root: Path = ROOT) -> list[CapabilityCaseV1]:
    """Read the one explicitly governed local synthetic source, not a search."""

    source = root / LOCAL_SYNTHETIC_SOURCE_RELATIVE
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("the explicit RQ2-A local synthetic source is unavailable")
    cases: list[CapabilityCaseV1] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"local synthetic line {line_number} is not an object")
        provenance = dict(value.get("provenance") or {})
        if provenance.get("synthetic") is not True:
            raise RuntimeError("local development records must be explicitly synthetic")
        if value.get("source_dataset") != "RQ2A_CONTRACT_SYNTHETIC":
            raise RuntimeError("unexpected local development source identity")
        cases.append(CapabilityCaseV1.from_mapping(value))
    return cases


def _capability_order(values: Iterable[str]) -> tuple[str, ...]:
    selected = set(values)
    return tuple(name for name in PREDICTED_CAPABILITIES if name in selected)


def _metadata_signal(case: CapabilityCaseV1) -> tuple[str, ...]:
    values: list[str] = []
    if case.existing_expected_retrieval is True:
        values.append("course_retrieval")
    if case.existing_expected_memory is True:
        values.append("episodic_memory")
    if case.provenance.get("existing_expected_planning") is True:
        values.append("planning")
    return _capability_order(values)


def _scope_signal(case: CapabilityCaseV1) -> tuple[str, ...]:
    return _capability_order(
        {
            "dashboard_only": ("dashboard_evidence",),
            "course_only": ("course_retrieval",),
            "hybrid": ("dashboard_evidence", "course_retrieval"),
            "memory_only": ("episodic_memory",),
        }.get(case.existing_expected_source_scope, ())
    )


def build_hidden_proposal(case: CapabilityCaseV1) -> dict[str, Any]:
    """Create a non-gold proposal using the frozen metadata priority."""

    signals = [
        ("explicit_required_capabilities", _capability_order(case.existing_required_capabilities)),
        ("expected_need_fields", _metadata_signal(case)),
        ("expected_source_scope", _scope_signal(case)),
        (
            "expected_route",
            _capability_order(ROUTE_CAPABILITY_SEED_MAP.get(case.existing_expected_route, ())),
        ),
        (
            "intent_seed_map",
            _capability_order(
                INTENT_CAPABILITY_SEED_MAP.get(case.existing_expected_intent, ())
            ),
        ),
    ]
    non_empty = [(name, value) for name, value in signals if value]
    selected_source, selected = non_empty[0] if non_empty else ("manual_review_required", ())
    distinct = {value for _, value in non_empty}
    context_resolution = case.existing_expected_intent == "discrepancy_or_correction"
    return {
        "schema_version": "capability-proposal-ledger-v1",
        "case_id": case.case_id,
        **case.hashes(),
        "proposal_source": selected_source,
        "proposed_capabilities": list(selected),
        "context_resolution_required_proposal": context_resolution,
        "proposal_conflict": len(distinct) > 1,
        "proposal_is_gold": False,
        "reviewer_visible": False,
        "manual_review_required": True,
    }


def build_development_bank(root: Path = ROOT) -> DevelopmentBankBuild:
    """Build every canonical case; never select by baseline/model behaviour."""

    inventory = build_source_inventory(root)
    all_cases = [*load_allowlisted_cases(root), *load_local_synthetic_cases(root)]
    canonicalisation = canonicalise_cases(all_cases)
    canonical = canonicalisation.canonical_cases
    if len(canonical) < MINIMUM_CANONICAL_CASE_COUNT:
        raise RuntimeError("BLOCKED_RQ2_A_INSUFFICIENT_DEVELOPMENT_CASES")

    bank_path = root / LOCAL_BANK_RELATIVE
    lineage_path = root / LOCAL_LINEAGE_RELATIVE
    proposal_path = root / LOCAL_PROPOSAL_RELATIVE
    _write_bytes(bank_path, _jsonl_bytes(case.to_dict() for case in canonical))
    _write_bytes(lineage_path, _jsonl_bytes(canonicalisation.lineage_rows))
    _write_bytes(proposal_path, _jsonl_bytes(build_hidden_proposal(case) for case in canonical))

    categories = safe_count_distribution([case.scenario_category for case in canonical])
    sources = safe_count_distribution([case.source_dataset for case in canonical])
    families = safe_count_distribution([case.scenario_family for case in canonical])
    required_coverage = (
        "single-capability",
        "multi-capability",
        "context-dependent",
        "query-only",
        "negative-control",
        "safety-boundary",
        "clarification-required",
        "no-clarification",
    )
    missing_coverage = [name for name in required_coverage if categories.get(name, 0) == 0]
    if missing_coverage:
        raise RuntimeError(f"development coverage missing: {missing_coverage}")

    summary = {
        "schema_version": "capability-development-bank-summary-v1",
        "stage": "RQ2-A",
        "status": "PASS",
        "storage_policy": "FULL_CASES_LOCAL_ONLY_IGNORED",
        "raw_case_count": canonicalisation.summary["raw_case_count"],
        "canonical_case_count": len(canonical),
        "minimum_canonical_case_count": MINIMUM_CANONICAL_CASE_COUNT,
        "minimum_count_gate_passed": True,
        "source_count": len(sources),
        "source_distribution": sources,
        "scenario_category_distribution": categories,
        "scenario_family_count": len(families),
        "required_coverage": list(required_coverage),
        "coverage_gate_passed": True,
        "canonical_bank_sha256": sha256_file(bank_path),
        "canonical_lineage_sha256": sha256_file(lineage_path),
        "hidden_proposal_ledger_sha256": sha256_file(proposal_path),
        "hidden_proposal_record_count": len(canonical),
        "proposal_is_gold": False,
        "proposal_visible_to_reviewers": False,
        "selected_by_legacy_baseline_error": False,
        "selected_by_future_model_performance": False,
        "sampling_performed": False,
        "all_canonical_cases_enter_review": True,
        "natural_language_in_tracked_summary": False,
    }
    return DevelopmentBankBuild(
        cases=canonical,
        canonicalisation=canonicalisation,
        source_inventory=inventory,
        bank_summary=summary,
        duplicate_summary=canonicalisation.summary,
    )


def write_safe_bank_summaries(root: Path = ROOT) -> DevelopmentBankBuild:
    result = build_development_bank(root)
    target = root / "evaluation/capability_routing_v1"
    (target / "capability_source_inventory_v1.json").write_bytes(
        canonical_json_bytes(result.source_inventory)
    )
    (target / "capability_development_bank_summary_v1.json").write_bytes(
        canonical_json_bytes(result.bank_summary)
    )
    (target / "capability_duplicate_lineage_summary_v1.json").write_bytes(
        canonical_json_bytes(result.duplicate_summary)
    )
    return result


if __name__ == "__main__":
    built = write_safe_bank_summaries()
    print(
        json.dumps(
            {
                "status": "PASS",
                "canonical_case_count": len(built.cases),
                "tracked_natural_language": False,
            },
            sort_keys=True,
        )
    )
