"""Freeze complete-row adjudication and non-adjudicated consensus precedence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import GOLD_FIELDS, VISIBLE_FIELDS, normalise_forbidden


class HumanDecisionPrecedenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedDecision:
    review_case_id: str
    gold_decision_source: str
    labels: dict[str, str]
    visible: dict[str, str]


def _comparable(field: str, value: str) -> Any:
    return normalise_forbidden(value) if field == "forbidden_capabilities" else value


def resolve_human_decisions(
    reviewer_a: Sequence[Mapping[str, str]],
    reviewer_b: Sequence[Mapping[str, str]],
    adjudication: Sequence[Mapping[str, str]],
) -> tuple[list[ResolvedDecision], dict[str, Any]]:
    by_a = {row["review_case_id"]: row for row in reviewer_a}
    by_b = {row["review_case_id"]: row for row in reviewer_b}
    by_c = {row["review_case_id"]: row for row in adjudication}
    if len(by_a) != 48 or set(by_a) != set(by_b) or len(by_c) != 23 or not set(by_c) < set(by_a):
        raise HumanDecisionPrecedenceError("human decision case-set mismatch")
    resolved: list[ResolvedDecision] = []
    unresolved_consensus: list[str] = []
    consensus_overrides: list[dict[str, str]] = []
    third_values: list[dict[str, str]] = []
    for case_id in sorted(by_a):
        row_a, row_b = by_a[case_id], by_b[case_id]
        if any(row_a[field] != row_b[field] for field in VISIBLE_FIELDS):
            raise HumanDecisionPrecedenceError("visible A/B field mismatch")
        if case_id in by_c:
            row_c = by_c[case_id]
            labels = {field: row_c[f"adjudicated_{field}"] for field in GOLD_FIELDS}
            source = "HUMAN_ADJUDICATION_COMPLETE_ROW"
            for field in GOLD_FIELDS:
                left = _comparable(field, row_a[field])
                right = _comparable(field, row_b[field])
                final = _comparable(field, labels[field])
                if left == right and final != left:
                    consensus_overrides.append(
                        {
                            "review_case_id": case_id,
                            "field": field,
                            "reviewer_a_value": row_a[field],
                            "reviewer_b_value": row_b[field],
                            "adjudicated_value": labels[field],
                        }
                    )
                if left != right and final not in {left, right}:
                    third_values.append(
                        {
                            "review_case_id": case_id,
                            "field": field,
                            "reviewer_a_value": row_a[field],
                            "reviewer_b_value": row_b[field],
                            "adjudicated_value": labels[field],
                        }
                    )
        else:
            differing = [field for field in GOLD_FIELDS if row_a[field] != row_b[field]]
            if differing:
                unresolved_consensus.append(case_id)
                continue
            labels = {field: row_a[field] for field in GOLD_FIELDS}
            source = "HUMAN_CONSENSUS"
        resolved.append(
            ResolvedDecision(
                review_case_id=case_id,
                gold_decision_source=source,
                labels=labels,
                visible={field: row_a[field] for field in VISIBLE_FIELDS},
            )
        )
    if unresolved_consensus:
        raise HumanDecisionPrecedenceError(
            "BLOCKED_RQ2_D2B_UNRESOLVED_HUMAN_DISAGREEMENT"
        )
    expected_override = [
        {
            "review_case_id": "TBV1-77302F0D863B83D5",
            "field": "context_resolution_required",
            "reviewer_a_value": "NO",
            "reviewer_b_value": "NO",
            "adjudicated_value": "YES",
        }
    ]
    expected_third = [
        {
            "review_case_id": "TBV1-901EAA6E1906DB2E",
            "field": "query_naturalness_1_to_5",
            "reviewer_a_value": "5",
            "reviewer_b_value": "3",
            "adjudicated_value": "4",
        }
    ]
    if consensus_overrides != expected_override or third_values != expected_third:
        raise HumanDecisionPrecedenceError(
            "BLOCKED_RQ2_D2B_COMPLETE_ROW_PRECEDENCE"
        )
    counts = {
        source: sum(decision.gold_decision_source == source for decision in resolved)
        for source in ("HUMAN_CONSENSUS", "HUMAN_ADJUDICATION_COMPLETE_ROW")
    }
    if len(resolved) != 48 or counts != {
        "HUMAN_CONSENSUS": 25,
        "HUMAN_ADJUDICATION_COMPLETE_ROW": 23,
    }:
        raise HumanDecisionPrecedenceError("human decision source composition mismatch")
    return resolved, {
        "schema_version": "track-b-human-decision-precedence-v1",
        "stage": "RQ2-D2B",
        "status": "FROZEN",
        "gold_relevant_fields": list(GOLD_FIELDS),
        "adjudicated_case_rule": "HUMAN_ADJUDICATION_COMPLETE_ROW",
        "non_adjudicated_case_rule": "HUMAN_CONSENSUS",
        "adjudicated_case_count": 23,
        "consensus_case_count": 25,
        "unresolved_non_adjudicated_case_count": 0,
        "complete_row_authority": True,
        "disagreement_reason_only_replacement_used": False,
        "majority_or_nearest_value_override_used": False,
        "adjudicator_changes_a_b_consensus_field_count": len(consensus_overrides),
        "consensus_field_overrides": consensus_overrides,
        "adjudicator_selects_value_outside_a_b_pair_count": len(third_values),
        "third_value_resolutions": third_values,
        "excluded_provenance_fields": [
            "reviewer_rationale",
            "adjudicator_rationale",
            "reviewer_id",
            "review_date",
            "adjudicator_id",
            "adjudication_date",
            "disagreement_reasons",
        ],
        "human_answer_changed_by_codex": False,
        "complete_row_decision_overridden": False,
    }
