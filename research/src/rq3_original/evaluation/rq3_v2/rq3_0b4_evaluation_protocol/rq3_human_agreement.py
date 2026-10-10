"""Dependency-free agreement metrics for synthetic tests and future frozen ratings."""

from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping, Sequence

from .rq3_judge_request_builder import PRIMARY_CRITERIA, SCORE_FIELDS


class AgreementError(ValueError):
    """Raised when agreement inputs are invalid or applicability diverges."""


def _validated_scores(values: Sequence[int], label: str) -> list[int]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise AgreementError(f"{label} must be a sequence")
    result = list(values)
    if not result:
        raise AgreementError(f"{label} must not be empty")
    if any(type(value) is not int or not 1 <= value <= 5 for value in result):
        raise AgreementError(f"{label} scores must be integers from 1 to 5")
    return result


def quadratic_weighted_kappa(scores_a: Sequence[int], scores_b: Sequence[int]) -> float | None:
    """Return quadratic weighted Cohen's kappa on the fixed 1--5 scale."""

    left = _validated_scores(scores_a, "scores_a")
    right = _validated_scores(scores_b, "scores_b")
    if len(left) != len(right):
        raise AgreementError("score sequences must have equal length")
    n = len(left)
    counts_a = Counter(left)
    counts_b = Counter(right)
    observed = 0.0
    expected = 0.0
    for a_score in range(1, 6):
        for b_score in range(1, 6):
            weight = ((a_score - b_score) / 4.0) ** 2
            observed += weight * sum(
                1 for a_value, b_value in zip(left, right) if a_value == a_score and b_value == b_score
            ) / n
            expected += weight * counts_a[a_score] * counts_b[b_score] / (n * n)
    if math.isclose(expected, 0.0, abs_tol=1e-15):
        return None
    return 1.0 - observed / expected


def _average_ranks(values: Sequence[int]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_rank = ((cursor + 1) + end) / 2.0
        for position in range(cursor, end):
            ranks[ordered[position][0]] = average_rank
        cursor = end
    return ranks


def spearman_correlation(scores_a: Sequence[int], scores_b: Sequence[int]) -> float | None:
    """Return Spearman's rho with average ranks; zero variance is not estimable."""

    left = _validated_scores(scores_a, "scores_a")
    right = _validated_scores(scores_b, "scores_b")
    if len(left) != len(right):
        raise AgreementError("score sequences must have equal length")
    ranks_a = _average_ranks(left)
    ranks_b = _average_ranks(right)
    mean_a = sum(ranks_a) / len(ranks_a)
    mean_b = sum(ranks_b) / len(ranks_b)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(ranks_a, ranks_b))
    variance_a = sum((a - mean_a) ** 2 for a in ranks_a)
    variance_b = sum((b - mean_b) ** 2 for b in ranks_b)
    if math.isclose(variance_a, 0.0, abs_tol=1e-15) or math.isclose(
        variance_b, 0.0, abs_tol=1e-15
    ):
        return None
    return covariance / math.sqrt(variance_a * variance_b)


def agreement_metrics(scores_a: Sequence[int], scores_b: Sequence[int]) -> dict[str, Any]:
    """Calculate the predeclared pairwise agreement metrics."""

    left = _validated_scores(scores_a, "scores_a")
    right = _validated_scores(scores_b, "scores_b")
    if len(left) != len(right):
        raise AgreementError("score sequences must have equal length")
    differences = [b - a for a, b in zip(left, right)]
    n = len(left)
    return {
        "n": n,
        "quadratic_weighted_kappa": quadratic_weighted_kappa(left, right),
        "spearman_correlation": spearman_correlation(left, right),
        "exact_agreement": sum(a == b for a, b in zip(left, right)) / n,
        "within_one_point_agreement": sum(abs(a - b) <= 1 for a, b in zip(left, right)) / n,
        "mean_absolute_score_difference": sum(abs(value) for value in differences) / n,
        "criterion_level_bias_source_b_minus_source_a": sum(differences) / n,
    }


def _index_records(records: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise AgreementError(f"{label} records must be mappings")
        blind_id = record.get("response_blind_id")
        scores = record.get("criterion_scores")
        if not isinstance(blind_id, str) or not isinstance(scores, Mapping):
            raise AgreementError(f"{label} records require response_blind_id and criterion_scores")
        if blind_id in indexed:
            raise AgreementError(f"duplicate {label} response_blind_id")
        if set(scores) != {SCORE_FIELDS[name] for name in PRIMARY_CRITERIA}:
            raise AgreementError(f"{label} record has the wrong criterion fields")
        indexed[blind_id] = record
    return indexed


def agreement_by_criterion(
    records_a: Sequence[Mapping[str, Any]],
    records_b: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute per-criterion and pooled agreement on jointly applicable scores."""

    left = _index_records(records_a, "source_a")
    right = _index_records(records_b, "source_b")
    if set(left) != set(right):
        raise AgreementError("score sources must contain identical blind response IDs")

    per_criterion: dict[str, Any] = {}
    pooled_a: list[int] = []
    pooled_b: list[int] = []
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        criterion_a: list[int] = []
        criterion_b: list[int] = []
        for blind_id in sorted(left):
            value_a = left[blind_id]["criterion_scores"][field]
            value_b = right[blind_id]["criterion_scores"][field]
            if value_a == "NA" and value_b == "NA":
                continue
            if value_a == "NA" or value_b == "NA":
                raise AgreementError(f"applicability mismatch for {field} at {blind_id}")
            if type(value_a) is not int or type(value_b) is not int:
                raise AgreementError(f"invalid applicable score for {field} at {blind_id}")
            criterion_a.append(value_a)
            criterion_b.append(value_b)
        if criterion_a:
            per_criterion[field] = agreement_metrics(criterion_a, criterion_b)
            pooled_a.extend(criterion_a)
            pooled_b.extend(criterion_b)
        else:
            per_criterion[field] = {"status": "NOT_ESTIMABLE_NO_JOINTLY_APPLICABLE_PAIRS", "n": 0}
    if not pooled_a:
        raise AgreementError("no jointly applicable score pairs")
    return {
        "per_criterion": per_criterion,
        "pooled": agreement_metrics(pooled_a, pooled_b),
        "pooling_rule": "concatenate every jointly applicable criterion-response pair once",
    }


def human_and_llm_agreement_bundle(
    human_a_records: Sequence[Mapping[str, Any]],
    human_b_records: Sequence[Mapping[str, Any]],
    llm_judge_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return every predeclared human--human and human--judge comparison.

    The pooled human-versus-judge result retains both independent human
    observations by pairing each with the unchanged judge score.  It does not
    average raters or create a replacement Gold score.
    """

    indexed_a = _index_records(human_a_records, "human_a")
    indexed_b = _index_records(human_b_records, "human_b")
    indexed_llm = _index_records(llm_judge_records, "llm_judge")
    if set(indexed_a) != set(indexed_b) or set(indexed_a) != set(indexed_llm):
        raise AgreementError("human A, human B, and judge sources must cover identical blind IDs")

    pooled_humans: list[dict[str, Any]] = []
    pooled_llm: list[dict[str, Any]] = []
    for role, indexed_human in (("A", indexed_a), ("B", indexed_b)):
        for blind_id in sorted(indexed_human):
            pooled_id = f"{blind_id}::{role}"
            pooled_humans.append(
                {
                    "response_blind_id": pooled_id,
                    "criterion_scores": dict(indexed_human[blind_id]["criterion_scores"]),
                }
            )
            pooled_llm.append(
                {
                    "response_blind_id": pooled_id,
                    "criterion_scores": dict(indexed_llm[blind_id]["criterion_scores"]),
                }
            )

    return {
        "human_a_vs_human_b": agreement_by_criterion(human_a_records, human_b_records),
        "human_a_vs_llm_judge": agreement_by_criterion(human_a_records, llm_judge_records),
        "human_b_vs_llm_judge": agreement_by_criterion(human_b_records, llm_judge_records),
        "pooled_human_observations_vs_llm_judge": agreement_by_criterion(
            pooled_humans, pooled_llm
        ),
        "score_rewriting_performed": False,
    }
