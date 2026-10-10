"""Exact six-capability Jaccard utility and paired case outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Mapping

from . import CAPABILITIES


CAPABILITY_SET = frozenset(CAPABILITIES)


@dataclass(frozen=True)
class ExactSetUtilityV1:
    intersection_count: int
    union_count: int
    utility_numerator: int
    utility_denominator: int

    @property
    def value(self) -> Fraction:
        return Fraction(self.utility_numerator, self.utility_denominator)


def _normalise_capability_set(values: Iterable[str]) -> frozenset[str]:
    result = frozenset(str(value) for value in values)
    if not result <= CAPABILITY_SET:
        raise ValueError("capability set contains a field outside the frozen universe")
    return result


def capability_yes_set_v1(record: Mapping[str, Any]) -> frozenset[str]:
    """Project only the six frozen capability fields; all extra fields are ignored."""

    values: set[str] = set()
    for capability in CAPABILITIES:
        value = record.get(capability, "NO")
        if value is True or value == "YES":
            values.add(capability)
        elif value is False or value in {"NO", None}:
            continue
        else:
            raise ValueError(f"invalid capability value for {capability}")
    return frozenset(values)


def exact_jaccard_details_v1(
    predicted_yes_set: Iterable[str], gold_yes_set: Iterable[str]
) -> ExactSetUtilityV1:
    predicted = _normalise_capability_set(predicted_yes_set)
    gold = _normalise_capability_set(gold_yes_set)
    intersection = len(predicted & gold)
    union = len(predicted | gold)
    utility = Fraction(1, 1) if union == 0 else Fraction(intersection, union)
    return ExactSetUtilityV1(
        intersection_count=intersection,
        union_count=union,
        utility_numerator=utility.numerator,
        utility_denominator=utility.denominator,
    )


def exact_jaccard_utility_v1(
    predicted_yes_set: Iterable[str], gold_yes_set: Iterable[str]
) -> Fraction:
    return exact_jaccard_details_v1(predicted_yes_set, gold_yes_set).value


def case_utility_difference_v1(
    left_prediction: Mapping[str, Any],
    right_prediction: Mapping[str, Any],
    gold: Mapping[str, Any],
) -> Fraction:
    gold_set = capability_yes_set_v1(gold)
    return exact_jaccard_utility_v1(
        capability_yes_set_v1(left_prediction), gold_set
    ) - exact_jaccard_utility_v1(capability_yes_set_v1(right_prediction), gold_set)


def case_outcome_v1(delta: Fraction) -> str:
    exact = Fraction(delta)
    return "WIN" if exact > 0 else "LOSS" if exact < 0 else "TIE"


def summarise_case_outcomes_v1(deltas: Iterable[Fraction]) -> dict[str, Any]:
    outcomes = [case_outcome_v1(Fraction(delta)) for delta in deltas]
    wins = outcomes.count("WIN")
    ties = outcomes.count("TIE")
    losses = outcomes.count("LOSS")
    non_ties = wins + losses
    if non_ties == 0:
        effect = {
            "value": None,
            "status": "UNDEFINED_ALL_TIES",
            "numerator": 0,
            "denominator": 0,
        }
    else:
        value = Fraction(wins - losses, non_ties)
        effect = {
            "value": float(value),
            "status": "DEFINED",
            "numerator": value.numerator,
            "denominator": value.denominator,
        }
    return {
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "total": len(outcomes),
        "matched_rank_biserial": effect,
    }
