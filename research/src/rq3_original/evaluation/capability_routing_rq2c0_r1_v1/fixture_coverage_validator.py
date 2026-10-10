"""Mechanism-coverage gates for the 28 controlled fixtures."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .fixture_schema import ControlledMechanismFixtureV1


RAG_REQUIREMENTS = {
    "AMBIGUOUS": 2,
    "NO_RESULT": 2,
    "SUPPORTED": 2,
    "UNSUPPORTED": 2,
}

PERSISTENT_REQUIREMENTS = {
    "ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED": 4,
    "COMPLETED_CANCELLED_REJECTION": 1,
    "CROSS_STUDENT_REJECTION": 1,
    "DELETED_MEMORY_REJECTION": 1,
    "MULTI_HOP_RETRIEVAL": 1,
    "NO_RELEVANT_MEMORY_ABSTENTION": 1,
    "STALE_REJECTION": 1,
    "SUPERSEDED_REJECTION": 1,
    "WRITE_AUTHORISED": 2,
    "WRITE_REJECTED": 1,
}


class FixtureCoverageError(RuntimeError):
    pass


def _gate_rows(observed: Counter[str], required: dict[str, int]) -> dict[str, Any]:
    return {
        key: {
            "observed": observed[key],
            "required_minimum": minimum,
            "pass": observed[key] >= minimum,
        }
        for key, minimum in sorted(required.items())
    }


def validate_fixture_coverage(
    fixtures: Iterable[ControlledMechanismFixtureV1],
) -> dict[str, Any]:
    values = tuple(fixtures)
    rag_observed: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for item in values:
        if item.fixture_category.startswith("RAG_SUFFICIENCY_"):
            rag_observed[item.fixture_category.removeprefix("RAG_SUFFICIENCY_")] += 1
        tags.update(set(item.coverage_tags))
    rag = _gate_rows(rag_observed, RAG_REQUIREMENTS)
    persistent = _gate_rows(tags, PERSISTENT_REQUIREMENTS)
    all_pass = all(row["pass"] for row in (*rag.values(), *persistent.values()))
    report = {
        "schema_version": "mechanism-evaluability-repair-v1",
        "stage": "RQ2-C0-R1",
        "status": "PASS" if all_pass else "FAIL",
        "fixture_count": len(values),
        "rag_gates": rag,
        "persistent_memory_gates": persistent,
        "all_gates_pass": all_pass,
        "evaluability_status": (
            "SUFFICIENT_FOR_OFFLINE_P2_RAG_AND_PERSISTENT_MEMORY"
            if all_pass
            else "BLOCKED_RQ2_C0_R1_FIXTURE_COVERAGE"
        ),
        "thresholds_lowered": False,
        "p2_executed": False,
    }
    if not all_pass:
        raise FixtureCoverageError("BLOCKED_RQ2_C0_R1_FIXTURE_COVERAGE")
    return report
