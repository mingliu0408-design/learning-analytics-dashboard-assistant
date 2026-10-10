"""Frozen synthetic coverage gate validation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import CAPABILITIES, RQ2AR2BError


COVERAGE_THRESHOLDS = {
    "included_synthetic_cases": 20,
    "dashboard_evidence_positives": 2,
    "course_retrieval_positives": 2,
    "episodic_memory_positives": 2,
    "planning_positives": 2,
    "safe_direct_response_positives": 2,
    "clarification_positives": 2,
    "context_resolution_required_positives": 4,
    "multi_capability_cases": 4,
}


class CoverageValidationError(RQ2AR2BError):
    pass


def _observed(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "included_synthetic_cases": len(rows),
        **{
            f"{capability}_positives": sum(
                row[capability] == "YES" for row in rows
            )
            for capability in CAPABILITIES
        },
        "context_resolution_required_positives": sum(
            row["context_resolution_required"] == "YES" for row in rows
        ),
        "multi_capability_cases": sum(
            sum(row[capability] == "YES" for capability in CAPABILITIES) > 1
            for row in rows
        ),
    }


def synthetic_clarification_exception_count(
    rows: Iterable[Mapping[str, Any]],
) -> int:
    return sum(
        row["source_role"] == "synthetic"
        and row["context_sufficient"] == "NO"
        and row["capability_unambiguous"] == "YES"
        and row["context_resolution_required"] == "YES"
        and row["clarification"] == "YES"
        and all(
            row[capability] == "NO"
            for capability in CAPABILITIES
            if capability != "clarification"
        )
        for row in rows
    )


def validate_synthetic_coverage(
    synthetic_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = list(synthetic_rows)
    observed = _observed(rows)
    gates = {
        name: {
            "threshold": threshold,
            "observed": observed[name],
            "comparison": "GREATER_THAN_OR_EQUAL",
            "status": "PASS" if observed[name] >= threshold else "FAIL",
        }
        for name, threshold in COVERAGE_THRESHOLDS.items()
    }
    if any(gate["status"] != "PASS" for gate in gates.values()):
        raise CoverageValidationError("BLOCKED_RQ2_A_R2B_CALIBRATION_COVERAGE")
    return {
        "schema_version": "synthetic-coverage-validation-v1",
        "stage": "RQ2-A-R2B",
        "status": "PASS",
        "threshold_contract": "UNCHANGED_FROM_RQ2_A_R1",
        "threshold_changed": False,
        "case_generation_performed": False,
        "annotation_changed": False,
        "authentic_cases_moved_to_synthetic": False,
        "clarification_exception_expanded": False,
        "gates": gates,
        "synthetic_clarification_exception_cases": (
            synthetic_clarification_exception_count(rows)
        ),
    }
