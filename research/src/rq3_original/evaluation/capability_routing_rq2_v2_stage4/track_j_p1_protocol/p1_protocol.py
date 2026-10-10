"""Provider-free reference semantics for the frozen P1 Hybrid protocol.

The functions in this module operate only on caller-supplied records.  They
contain no governed-data loader, provider client, TEST adapter, or production
integration.  Stage 4J-0 tests exercise them with toy records only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math
import re
from typing import Any, Mapping, Sequence


CAPABILITY_ORDER = ("rag_required", "memory_required", "planning_required")
OUTER_FOLDS = tuple(f"DEV-CV-FOLD-{index}" for index in range(1, 5))

ELIGIBLE_POLICY_IDS = (
    "P1-C00-B3-DIRECT",
    "P1-C01-MARGIN-005",
    "P1-C02-MARGIN-010",
    "P1-C03-MARGIN-020",
    "P1-C04-B2-B3-DISAGREEMENT",
    "P1-C05-B0-B3-DISAGREEMENT",
    "P1-C06-MARGIN010-OR-B2B3",
    "P1-C07-MARGIN010-OR-B0B3",
    "P1-C08-NONUNANIMOUS",
)
DIAGNOSTIC_POLICY_ID = "P1-DIAG-ALL-B4"

POLICY_SIMPLICITY_ORDER = {
    policy_id: index for index, policy_id in enumerate(ELIGIBLE_POLICY_IDS)
}
MARGIN_WIDTHS = {
    "P1-C01-MARGIN-005": Decimal("0.05"),
    "P1-C02-MARGIN-010": Decimal("0.10"),
    "P1-C03-MARGIN-020": Decimal("0.20"),
}

SELECTION_METRICS = (
    "macro_f1",
    "exact_capability_set_match",
    "jaccard",
    "under_routing_rate",
    "over_routing_rate",
    "fallback_rate",
)


class ContractError(ValueError):
    """Raised when a supplied record violates the frozen P1 contract."""


@dataclass(frozen=True)
class CapabilitySignature:
    """One complete, indivisible RAG/Memory/Planning prediction."""

    rag_required: bool
    memory_required: bool
    planning_required: bool

    def __post_init__(self) -> None:
        for field_name in CAPABILITY_ORDER:
            if type(getattr(self, field_name)) is not bool:
                raise ContractError(f"{field_name} must be a boolean")

    @property
    def bits(self) -> tuple[bool, bool, bool]:
        return (
            self.rag_required,
            self.memory_required,
            self.planning_required,
        )

    def as_dict(self) -> dict[str, bool]:
        return dict(zip(CAPABILITY_ORDER, self.bits, strict=True))


@dataclass(frozen=True)
class P1Case:
    """Normalized case consumed by the toy reference semantics.

    Gold is present only for metric calculation.  ``should_fallback`` and
    ``apply_policy`` never inspect it.
    """

    annotation_case_id: str
    outer_fold: str
    gold: CapabilitySignature
    b0: CapabilitySignature
    b2: CapabilitySignature
    b3: CapabilitySignature
    b3_probabilities: tuple[float, float, float]
    b3_thresholds: tuple[float, float, float]
    b4: CapabilitySignature | None
    b4_valid: bool
    b4_terminal_status: str
    scenario_family_id: str = "TOY-FAMILY"
    current_page: str = "TOY-PAGE"

    def __post_init__(self) -> None:
        if not self.annotation_case_id:
            raise ContractError("annotation_case_id must be non-empty")
        if re.search(r"(?:^|[-_])TEST(?:$|[-_])", self.annotation_case_id.upper()):
            raise ContractError("TEST identifiers are prohibited")
        if self.outer_fold not in OUTER_FOLDS:
            raise ContractError(f"unknown outer fold: {self.outer_fold}")
        for field_name, values in (
            ("b3_probabilities", self.b3_probabilities),
            ("b3_thresholds", self.b3_thresholds),
        ):
            if len(values) != 3:
                raise ContractError(f"{field_name} must contain exactly three values")
            if any(type(value) not in (int, float) for value in values):
                raise ContractError(f"{field_name} values must be numeric")
            if any(not math.isfinite(float(value)) for value in values):
                raise ContractError(f"{field_name} values must be finite")
            if any(not 0.0 <= float(value) <= 1.0 for value in values):
                raise ContractError(f"{field_name} values must be in [0, 1]")
        if type(self.b4_valid) is not bool:
            raise ContractError("b4_valid must be a boolean")
        if self.b4_valid and self.b4 is None:
            raise ContractError("valid B4 output requires one complete signature")
        if not self.b4_valid and self.b4 is not None:
            raise ContractError("invalid B4 outcome must not carry a prediction")
        if self.b4_valid and self.b4_terminal_status != "VALID":
            raise ContractError("valid B4 output must use terminal status VALID")
        if not self.b4_valid and self.b4_terminal_status == "VALID":
            raise ContractError("failed B4 outcome cannot use terminal status VALID")


@dataclass(frozen=True)
class RouteDecision:
    annotation_case_id: str
    policy_id: str
    fallback_triggered: bool
    selected_router: str
    output: CapabilitySignature
    fallback_outcome: str
    b4_valid_for_triggered_case: bool | None
    estimated_provider_calls: int


def _decimal_distance(left: float, right: float) -> Decimal:
    """Compare decimal CSV values without binary-float boundary drift."""

    return abs(Decimal(str(left)) - Decimal(str(right)))


def _within_margin(case: P1Case, width: Decimal) -> bool:
    return any(
        _decimal_distance(probability, threshold) <= width
        for probability, threshold in zip(
            case.b3_probabilities, case.b3_thresholds, strict=True
        )
    )


def should_fallback(policy_id: str, case: P1Case) -> bool:
    """Apply one predeclared case-level fallback trigger without using Gold."""

    if policy_id == DIAGNOSTIC_POLICY_ID:
        return True
    if policy_id not in POLICY_SIMPLICITY_ORDER:
        raise ContractError(f"unknown or non-frozen policy: {policy_id}")
    if policy_id == "P1-C00-B3-DIRECT":
        return False
    if policy_id in MARGIN_WIDTHS:
        return _within_margin(case, MARGIN_WIDTHS[policy_id])
    if policy_id == "P1-C04-B2-B3-DISAGREEMENT":
        return case.b2 != case.b3
    if policy_id == "P1-C05-B0-B3-DISAGREEMENT":
        return case.b0 != case.b3
    if policy_id == "P1-C06-MARGIN010-OR-B2B3":
        return _within_margin(case, Decimal("0.10")) or case.b2 != case.b3
    if policy_id == "P1-C07-MARGIN010-OR-B0B3":
        return _within_margin(case, Decimal("0.10")) or case.b0 != case.b3
    if policy_id == "P1-C08-NONUNANIMOUS":
        return not (case.b0 == case.b2 == case.b3)
    raise AssertionError("unreachable frozen policy branch")


def apply_policy(policy_id: str, case: P1Case) -> RouteDecision:
    """Choose the complete B3 or complete B4 signature for one case."""

    triggered = should_fallback(policy_id, case)
    if not triggered:
        return RouteDecision(
            annotation_case_id=case.annotation_case_id,
            policy_id=policy_id,
            fallback_triggered=False,
            selected_router="B3",
            output=case.b3,
            fallback_outcome="NOT_TRIGGERED_USED_B3",
            b4_valid_for_triggered_case=None,
            estimated_provider_calls=0,
        )
    if case.b4_valid:
        if case.b4 is None:  # Defensive; P1Case already enforces this invariant.
            raise ContractError("valid B4 output is missing its complete signature")
        return RouteDecision(
            annotation_case_id=case.annotation_case_id,
            policy_id=policy_id,
            fallback_triggered=True,
            selected_router="B4",
            output=case.b4,
            fallback_outcome="FALLBACK_SUCCEEDED_USED_B4",
            b4_valid_for_triggered_case=True,
            estimated_provider_calls=1,
        )
    return RouteDecision(
        annotation_case_id=case.annotation_case_id,
        policy_id=policy_id,
        fallback_triggered=True,
        selected_router="B3",
        output=case.b3,
        fallback_outcome="FALLBACK_FAILED_USED_B3",
        b4_valid_for_triggered_case=False,
        estimated_provider_calls=1,
    )


def _binary_f1(truth: Sequence[bool], prediction: Sequence[bool]) -> float:
    true_positive = sum(t and p for t, p in zip(truth, prediction, strict=True))
    false_positive = sum(not t and p for t, p in zip(truth, prediction, strict=True))
    false_negative = sum(t and not p for t, p in zip(truth, prediction, strict=True))
    denominator = 2 * true_positive + false_positive + false_negative
    return (2 * true_positive / denominator) if denominator else 0.0


def _metrics(cases: Sequence[P1Case], decisions: Sequence[RouteDecision]) -> dict[str, Any]:
    if not cases:
        raise ContractError("cannot calculate metrics for an empty case set")
    if len(cases) != len(decisions):
        raise ContractError("cases and decisions must align")
    if [case.annotation_case_id for case in cases] != [
        decision.annotation_case_id for decision in decisions
    ]:
        raise ContractError("case and decision identifiers must align in order")

    label_f1 = []
    for column in range(3):
        label_f1.append(
            _binary_f1(
                [case.gold.bits[column] for case in cases],
                [decision.output.bits[column] for decision in decisions],
            )
        )

    exact_count = 0
    jaccard_values: list[float] = []
    under_count = 0
    over_count = 0
    for case, decision in zip(cases, decisions, strict=True):
        gold_set = {index for index, value in enumerate(case.gold.bits) if value}
        predicted_set = {
            index for index, value in enumerate(decision.output.bits) if value
        }
        exact_count += gold_set == predicted_set
        union = gold_set | predicted_set
        jaccard_values.append(
            len(gold_set & predicted_set) / len(union) if union else 1.0
        )
        under_count += bool(gold_set - predicted_set)
        over_count += bool(predicted_set - gold_set)

    fallback_count = sum(decision.fallback_triggered for decision in decisions)
    valid_b4_count = sum(
        decision.b4_valid_for_triggered_case is True for decision in decisions
    )
    failed_fallback_count = sum(
        decision.fallback_outcome == "FALLBACK_FAILED_USED_B3"
        for decision in decisions
    )
    population = len(cases)
    return {
        "case_count": population,
        "macro_f1": sum(label_f1) / 3,
        "exact_capability_set_match": exact_count / population,
        "jaccard": sum(jaccard_values) / population,
        "under_routing_rate": under_count / population,
        "over_routing_rate": over_count / population,
        "fallback_rate": fallback_count / population,
        "fallback_count": fallback_count,
        "valid_b4_fallback_count": valid_b4_count,
        "valid_b4_fallback_coverage": (
            valid_b4_count / fallback_count if fallback_count else None
        ),
        "failed_fallback_count": failed_fallback_count,
        "direct_b3_count": population - fallback_count,
        "estimated_provider_calls": fallback_count,
    }


def evaluate_policy(policy_id: str, cases: Sequence[P1Case]) -> dict[str, Any]:
    """Score one policy on supplied records; Stage 4J-0 uses toy records only."""

    decisions = [apply_policy(policy_id, case) for case in cases]
    return _metrics(cases, decisions)


def policy_selection_key(policy_id: str, metrics: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the exact frozen lexicographic selection key."""

    if policy_id not in POLICY_SIMPLICITY_ORDER:
        raise ContractError("diagnostic and unknown policies are not selectable")
    missing = [name for name in SELECTION_METRICS if name not in metrics]
    if missing:
        raise ContractError(f"selection metrics missing: {missing}")
    values = [float(metrics[name]) for name in SELECTION_METRICS]
    if any(not math.isfinite(value) for value in values):
        raise ContractError("selection metrics must be finite")
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise ContractError("selection metric rates must be in [0, 1]")
    return (
        -float(metrics["macro_f1"]),
        -float(metrics["exact_capability_set_match"]),
        -float(metrics["jaccard"]),
        float(metrics["under_routing_rate"]),
        float(metrics["over_routing_rate"]),
        float(metrics["fallback_rate"]),
        POLICY_SIMPLICITY_ORDER[policy_id],
        policy_id.encode("utf-8"),
    )


def select_policy(policy_metrics: Mapping[str, Mapping[str, Any]]) -> str:
    """Select among exactly the nine eligible policies, never the diagnostic."""

    supplied_ids = set(policy_metrics)
    expected_ids = set(ELIGIBLE_POLICY_IDS)
    if supplied_ids != expected_ids:
        missing = sorted(expected_ids - supplied_ids)
        extra = sorted(supplied_ids - expected_ids)
        raise ContractError(
            f"selection requires exactly nine eligible policies; missing={missing}, extra={extra}"
        )
    return min(
        ELIGIBLE_POLICY_IDS,
        key=lambda policy_id: policy_selection_key(
            policy_id, policy_metrics[policy_id]
        ),
    )


def _validate_case_collection(cases: Sequence[P1Case]) -> None:
    if not cases:
        raise ContractError("case collection must be non-empty")
    ids = [case.annotation_case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ContractError("annotation_case_id values must be unique")
    folds = {case.outer_fold for case in cases}
    if folds != set(OUTER_FOLDS):
        raise ContractError("case collection must contain all four frozen outer folds")


def select_outer_policy(cases: Sequence[P1Case], outer_fold: str) -> dict[str, Any]:
    """Select using only the three folds outside ``outer_fold``.

    Filtering happens before any metric function receives cases, so the held-out
    fold's Gold labels and B4 predictions cannot influence its policy choice.
    """

    if outer_fold not in OUTER_FOLDS:
        raise ContractError(f"unknown outer fold: {outer_fold}")
    selection_cases = [case for case in cases if case.outer_fold != outer_fold]
    if not selection_cases:
        raise ContractError("outer selection complement must be non-empty")
    policy_metrics = {
        policy_id: evaluate_policy(policy_id, selection_cases)
        for policy_id in ELIGIBLE_POLICY_IDS
    }
    selected_policy_id = select_policy(policy_metrics)
    return {
        "outer_fold": outer_fold,
        "selection_fold_ids": [fold for fold in OUTER_FOLDS if fold != outer_fold],
        "selection_case_count": len(selection_cases),
        "selected_policy_id": selected_policy_id,
        "eligible_policy_metrics": policy_metrics,
    }


def nested_policy_evaluation(cases: Sequence[P1Case]) -> dict[str, Any]:
    """Run the frozen nested procedure on caller-supplied records.

    This is a reference harness for toy tests.  It has no real-data loader and
    does not make B4 or provider calls.
    """

    _validate_case_collection(cases)
    outer_results: list[dict[str, Any]] = []
    aggregate_cases: list[P1Case] = []
    aggregate_decisions: list[RouteDecision] = []

    for outer_fold in OUTER_FOLDS:
        selection = select_outer_policy(cases, outer_fold)
        validation_cases = [case for case in cases if case.outer_fold == outer_fold]
        selected_policy_id = str(selection["selected_policy_id"])
        validation_decisions = [
            apply_policy(selected_policy_id, case) for case in validation_cases
        ]
        outer_results.append(
            {
                **selection,
                "outer_validation_case_count": len(validation_cases),
                "outer_validation_metrics": _metrics(
                    validation_cases, validation_decisions
                ),
            }
        )
        aggregate_cases.extend(validation_cases)
        aggregate_decisions.extend(validation_decisions)

    aggregate_pairs = sorted(
        zip(aggregate_cases, aggregate_decisions, strict=True),
        key=lambda pair: pair[0].annotation_case_id.encode("utf-8"),
    )
    aggregate_cases = [pair[0] for pair in aggregate_pairs]
    aggregate_decisions = [pair[1] for pair in aggregate_pairs]

    final_policy_metrics = {
        policy_id: evaluate_policy(policy_id, cases)
        for policy_id in ELIGIBLE_POLICY_IDS
    }
    final_policy_id = select_policy(final_policy_metrics)
    return {
        "outer_fold_results": outer_results,
        "nested_primary_metrics": _metrics(
            aggregate_cases, aggregate_decisions
        ),
        "final_full_dev_policy_metrics": final_policy_metrics,
        "final_full_dev_policy_id": final_policy_id,
        "diagnostic_all_b4_metrics": evaluate_policy(
            DIAGNOSTIC_POLICY_ID, cases
        ),
    }


__all__ = [
    "CAPABILITY_ORDER",
    "DIAGNOSTIC_POLICY_ID",
    "ELIGIBLE_POLICY_IDS",
    "OUTER_FOLDS",
    "POLICY_SIMPLICITY_ORDER",
    "CapabilitySignature",
    "ContractError",
    "P1Case",
    "RouteDecision",
    "apply_policy",
    "evaluate_policy",
    "nested_policy_evaluation",
    "policy_selection_key",
    "select_outer_policy",
    "select_policy",
    "should_fallback",
]
