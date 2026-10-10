"""Run the unmodified frozen R1C source-stratified agreement function."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from evaluation.capability_routing_v1_r1c.agreement_contract_v1_3 import (
    calculate_source_stratified_agreement,
)
from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    validate_independent_reviewer_ids,
)

from . import (
    CANONICAL_A_RELATIVE,
    CANONICAL_B_RELATIVE,
    R1C_MAPPING_RELATIVE,
    ROOT,
    SOURCE_MAPPING_SHA256,
    sha256_file,
)


class AgreementResultError(RuntimeError):
    pass


def _read_packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _mapping(root: Path) -> list[dict[str, Any]]:
    path = root / R1C_MAPPING_RELATIVE
    if (
        not path.is_file()
        or path.is_symlink()
        or sha256_file(path) != SOURCE_MAPPING_SHA256
    ):
        raise AgreementResultError("source mapping identity mismatch")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 60 or len({row["review_case_id"] for row in rows}) != 60:
        raise AgreementResultError("source mapping record identity mismatch")
    counts = {
        source: sum(row["source_bank"] == source for row in rows)
        for source in ("authentic", "synthetic")
    }
    if counts != {"authentic": 25, "synthetic": 35}:
        raise AgreementResultError("source mapping split mismatch")
    return rows


def _assert_close(observed: float | None, expected: float) -> None:
    if observed is None or not math.isclose(observed, expected, abs_tol=1e-12):
        raise AgreementResultError(
            "BLOCKED_RQ2_A_R2A_AGREEMENT_RESULT_MISMATCH"
        )


def validate_expected_agreement(result: dict[str, Any]) -> None:
    overall = result["overall_60"]
    authentic = result["by_source"]["authentic"]
    synthetic = result["by_source"]["synthetic"]
    _assert_close(overall["capability_set"]["exact_set_agreement"], 1.0)
    _assert_close(overall["capability_set"]["all_capability_micro_agreement"], 1.0)
    _assert_close(overall["context_sufficient"]["percent_agreement"], 1.0)
    _assert_close(
        overall["context_resolution_required"]["percent_agreement"], 59 / 60
    )
    _assert_close(
        overall["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
        0.5302491103202847,
    )
    _assert_close(
        authentic["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
        0.576271186440678,
    )
    _assert_close(
        synthetic["query_naturalness_1_to_5"]["quadratic_weighted_kappa"]["value"],
        0.49397590361445787,
    )
    if (
        synthetic["context_link_valid"]["applicable_case_count"] != 11
        or synthetic["context_link_valid"]["percent_agreement"] != 1.0
    ):
        raise AgreementResultError(
            "BLOCKED_RQ2_A_R2A_AGREEMENT_RESULT_MISMATCH"
        )


def run_agreement(root: Path = ROOT) -> dict[str, Any]:
    rows_a = _read_packet(root / CANONICAL_A_RELATIVE)
    rows_b = _read_packet(root / CANONICAL_B_RELATIVE)
    reviewer_ids = validate_independent_reviewer_ids(rows_a, rows_b)
    mapping = _mapping(root)
    result = calculate_source_stratified_agreement(rows_a, rows_b, mapping)
    validate_expected_agreement(result)
    result["stage"] = "RQ2-A-R2A"
    result["calculation_contract"] = (
        "evaluation.capability_routing_v1_r1c.agreement_contract_v1_3."
        "calculate_source_stratified_agreement"
    )
    result["calculation_contract_modified"] = False
    result["source_mapping_sha256"] = SOURCE_MAPPING_SHA256
    result["source_counts"] = {"authentic": 25, "synthetic": 35, "overall": 60}
    result["reviewer_ids"] = list(reviewer_ids)
    result["contains_query_history_or_rationale"] = False
    return result
