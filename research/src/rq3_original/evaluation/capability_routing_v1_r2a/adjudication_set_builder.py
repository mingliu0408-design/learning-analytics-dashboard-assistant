"""Build the exact five-case human-adjudication set using frozen R1C rules."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from evaluation.capability_routing_v1_r1c.adjudication_contract_v1_3 import (
    adjudication_reasons,
)

from . import (
    CANONICAL_A_RELATIVE,
    CANONICAL_B_RELATIVE,
    EXPECTED_ADJUDICATION_CASES,
    R1C_MAPPING_RELATIVE,
    ROOT,
)


class AdjudicationSetError(RuntimeError):
    pass


def _packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_adjudication_case_summary(root: Path = ROOT) -> dict[str, Any]:
    rows_a = _packet(root / CANONICAL_A_RELATIVE)
    rows_b = _packet(root / CANONICAL_B_RELATIVE)
    by_a = {row["review_case_id"]: row for row in rows_a}
    by_b = {row["review_case_id"]: row for row in rows_b}
    mapping = [
        json.loads(line)
        for line in (root / R1C_MAPPING_RELATIVE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_by_id = {
        str(row["review_case_id"]): str(row["source_bank"]) for row in mapping
    }
    observed: dict[str, tuple[str, ...]] = {}
    for review_case_id in sorted(by_a):
        reasons = adjudication_reasons(
            by_a[review_case_id],
            by_b[review_case_id],
            source_bank=source_by_id[review_case_id],
        )
        if reasons:
            observed[review_case_id] = reasons
    expected = {case_id: (reason,) for case_id, reason in EXPECTED_ADJUDICATION_CASES}
    if observed != expected:
        raise AdjudicationSetError(
            "BLOCKED_RQ2_A_R2A_ADJUDICATION_SET_MISMATCH"
        )
    cases = [
        {
            "review_case_id": case_id,
            "source_role": source_by_id[case_id],
            "disagreement_reasons": [reason],
        }
        for case_id, reason in EXPECTED_ADJUDICATION_CASES
    ]
    return {
        "schema_version": "rq2a-r2a-adjudication-case-summary-v1",
        "stage": "RQ2-A-R2A",
        "status": "AWAITING_HUMAN_ADJUDICATION",
        "case_count": 5,
        "cases": cases,
        "adjudication_contract": (
            "evaluation.capability_routing_v1_r1c.adjudication_contract_v1_3."
            "adjudication_reasons"
        ),
        "adjudication_contract_modified": False,
        "automatic_adjudication_performed": False,
        "hidden_proposal_used": False,
    }
