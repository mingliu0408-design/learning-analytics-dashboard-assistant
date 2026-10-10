"""Validate every frozen Track-B Gold composition gate."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, GOLD_ALIAS, GOLD_ROLE


class GoldCompositionError(RuntimeError):
    pass


def _capability_set(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(capability for capability in CAPABILITIES if row[capability] == "YES")


def _set_name(values: tuple[str, ...]) -> str:
    return " + ".join(values)


def _forbidden_name(values: Sequence[str]) -> str:
    return ";".join(values) if values else "empty"


def validate_gold_composition(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) != 48:
        raise GoldCompositionError("BLOCKED_RQ2_D2B_GOLD_COMPOSITION_MISMATCH")
    decision_sources = Counter(row["gold_decision_source"] for row in rows)
    expected_sources = {
        "HUMAN_CONSENSUS": 25,
        "HUMAN_ADJUDICATION_COMPLETE_ROW": 23,
    }
    categorical_expectations = {
        "case_validity": {"INCLUDE_VALID_CASE": 48},
        "query_naturalness_1_to_5": {"3": 2, "4": 15, "5": 31},
        "context_link_valid": {"YES": 48},
        "context_sufficient": {"YES": 44, "NO": 4},
        "capability_unambiguous": {"YES": 48},
        "context_resolution_required": {"YES": 39, "NO": 9},
    }
    observed_categorical = {
        field: dict(Counter(row[field] for row in rows))
        for field in categorical_expectations
    }
    capability_positives = {
        capability: sum(row[capability] == "YES" for row in rows)
        for capability in CAPABILITIES
    }
    expected_capability_positives = {
        "dashboard_evidence": 12,
        "course_retrieval": 4,
        "episodic_memory": 13,
        "planning": 10,
        "safe_direct_response": 15,
        "clarification": 4,
    }
    set_distribution = dict(Counter(_set_name(_capability_set(row)) for row in rows))
    expected_set_distribution = {
        "safe_direct_response": 15,
        "dashboard_evidence": 11,
        "episodic_memory + planning": 7,
        "episodic_memory": 6,
        "clarification": 4,
        "course_retrieval": 2,
        "planning": 1,
        "course_retrieval + planning": 1,
        "dashboard_evidence + course_retrieval + planning": 1,
    }
    forbidden_distribution = dict(
        Counter(_forbidden_name(row["forbidden_capabilities"]) for row in rows)
    )
    expected_forbidden_distribution = {
        "empty": 37,
        "dashboard_evidence": 6,
        "course_retrieval;episodic_memory": 2,
        "dashboard_evidence;episodic_memory": 1,
        "course_retrieval;planning": 1,
        "planning": 1,
    }
    forbidden_support = {
        capability: sum(capability in row["forbidden_capabilities"] for row in rows)
        for capability in CAPABILITIES
    }
    expected_forbidden_support = {
        "dashboard_evidence": 7,
        "course_retrieval": 3,
        "episodic_memory": 3,
        "planning": 2,
        "safe_direct_response": 0,
        "clarification": 0,
    }
    context_insufficient = [row for row in rows if row["context_sufficient"] == "NO"]
    safe_direct = [row for row in rows if row["safe_direct_response"] == "YES"]
    multi_capability_count = sum(len(_capability_set(row)) > 1 for row in rows)
    if (
        dict(decision_sources) != expected_sources
        or observed_categorical != categorical_expectations
        or capability_positives != expected_capability_positives
        or set_distribution != expected_set_distribution
        or forbidden_distribution != expected_forbidden_distribution
        or forbidden_support != expected_forbidden_support
        or multi_capability_count != 9
        or len(context_insufficient) != 4
        or any(_capability_set(row) != ("clarification",) for row in context_insufficient)
        or len(safe_direct) != 15
        or any(_capability_set(row) != ("safe_direct_response",) for row in safe_direct)
    ):
        raise GoldCompositionError("BLOCKED_RQ2_D2B_GOLD_COMPOSITION_MISMATCH")
    return {
        "schema_version": "track-b-capability-gold-summary-v1",
        "stage": "RQ2-D2B",
        "status": "PASS",
        "gold_alias": GOLD_ALIAS,
        "role": GOLD_ROLE,
        "record_count": 48,
        "included_count": 48,
        "excluded_count": 0,
        "human_decision_source_distribution": expected_sources,
        "categorical_distributions": categorical_expectations,
        "capability_positive_counts": expected_capability_positives,
        "capability_set_distribution": expected_set_distribution,
        "multi_capability_case_count": 9,
        "forbidden_capability_set_distribution": expected_forbidden_distribution,
        "per_capability_forbidden_support": expected_forbidden_support,
        "context_insufficient_case_count": 4,
        "context_insufficient_clarification_only": True,
        "safe_direct_case_count": 15,
        "safe_direct_response_only": True,
        "source_blinded": True,
        "human_only": True,
        "eligible_for_final_evaluation": True,
        "eligible_for_training": False,
        "eligible_for_threshold_selection": False,
        "eligible_for_policy_selection": False,
        "persistent_retrieval_evaluable": False,
        "rag_sufficiency_accuracy_evaluable": False,
    }
