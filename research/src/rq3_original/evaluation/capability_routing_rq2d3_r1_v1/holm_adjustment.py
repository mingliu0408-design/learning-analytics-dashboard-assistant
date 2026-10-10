"""Exact Holm adjustment for the two frozen secondary comparisons."""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping

from . import PRIMARY_COMPARISON, SECONDARY_COMPARISONS


def _fraction(value: Fraction | int | float | str) -> Fraction:
    result = value if isinstance(value, Fraction) else Fraction(str(value))
    if result < 0 or result > 1:
        raise ValueError("p-values must be in [0,1]")
    return result


def holm_adjust_secondary_pvalues_v1(
    raw_pvalues_by_comparison: Mapping[str, Fraction | int | float | str],
) -> dict[str, dict[str, Any]]:
    if PRIMARY_COMPARISON in raw_pvalues_by_comparison:
        raise ValueError("the primary comparison must not enter the Holm family")
    if set(raw_pvalues_by_comparison) != set(SECONDARY_COMPARISONS):
        raise ValueError("Holm family must contain exactly the two secondary comparisons")
    raw = {comparison: _fraction(value) for comparison, value in raw_pvalues_by_comparison.items()}
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    first_id, first_raw = ordered[0]
    second_id, second_raw = ordered[1]
    first_untruncated = 2 * first_raw
    second_untruncated = max(first_untruncated, second_raw)
    adjusted = {
        first_id: min(Fraction(1, 1), first_untruncated),
        second_id: min(Fraction(1, 1), second_untruncated),
    }
    result: dict[str, dict[str, Any]] = {}
    for comparison in SECONDARY_COMPARISONS:
        raw_value = raw[comparison]
        adjusted_value = adjusted[comparison]
        if adjusted_value < raw_value or adjusted_value > 1:
            raise RuntimeError("Holm invariant failure")
        result[comparison] = {
            "raw_numerator": raw_value.numerator,
            "raw_denominator": raw_value.denominator,
            "raw_p_value": float(raw_value),
            "adjusted_numerator": adjusted_value.numerator,
            "adjusted_denominator": adjusted_value.denominator,
            "adjusted_p_value": float(adjusted_value),
        }
    return result
