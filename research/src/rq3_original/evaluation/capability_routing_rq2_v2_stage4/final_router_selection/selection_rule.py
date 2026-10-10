"""Pure implementation of the frozen Stage 4N-R1 selection rule.

This module accepts an already-produced final scoring table as in-memory data.
It performs no file, TEST-artifact, Router, provider, scoring, or RQ3 I/O.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class SelectionRuleError(ValueError):
    """Raised when the frozen contract or supplied table is incomplete."""


ELIGIBLE_METHOD_IDS = (
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_JOINT_LLM",
    "R2V2-P1_HYBRID",
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
    "R2V2-P3_RAG_MEMORY_SPECIALISTS",
)

COVERAGE_FIELDS = (
    "predictions_exist_for_every_required_test_input",
    "all_required_outputs_pass_frozen_schema",
    "no_prediction_was_imputed",
    "no_unresolved_execution_failure_exists",
    "end_to_end_composition_is_complete",
)

NUMERIC_SELECTION_FIELDS = (
    ("core_macro_f1_gold_answer_cases", "HIGHER_IS_BETTER"),
    ("exact_capability_set_match", "HIGHER_IS_BETTER"),
    ("jaccard", "HIGHER_IS_BETTER"),
    ("under_routing_rate", "LOWER_IS_BETTER"),
    ("over_routing_rate", "LOWER_IS_BETTER"),
    ("family_both_utterances_correct_rate", "HIGHER_IS_BETTER"),
    ("complete_gold_pattern_contrast_match_rate", "HIGHER_IS_BETTER"),
    ("counterfactual_provider_component_call_count", "LOWER_IS_BETTER"),
    ("counterfactual_token_cost", "LOWER_IS_BETTER"),
)

METHOD_TIER_NUMBERS = {
    "R2V2-B0_RULE": 1,
    "R2V2-B1_LEGACY_INTENT": 1,
    "R2V2-B2_PROTOTYPE": 1,
    "R2V2-B3_OVR": 1,
    "R2V2-B4_JOINT_LLM": 1,
    "R2V2-P1_HYBRID": 1,
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION": 2,
    "R2V2-P3_RAG_MEMORY_SPECIALISTS": 2,
}

EXPECTED_SELECTION_FIELDS = (
    *(field for field, _direction in NUMERIC_SELECTION_FIELDS),
    "method_tier_number",
    "method_id_utf8",
)

EXPECTED_SELECTION_DIRECTIONS = (
    *(direction for _field, direction in NUMERIC_SELECTION_FIELDS),
    "LOWER_IS_BETTER",
    "ASCENDING_UTF8_BYTES",
)


def _finite_decimal(value: Any, *, field: str, method_id: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SelectionRuleError(f"{method_id}: {field} must be a finite numeric value")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SelectionRuleError(f"{method_id}: {field} is not numeric") from exc
    if not parsed.is_finite():
        raise SelectionRuleError(f"{method_id}: {field} must be finite")
    return parsed


def _validate_contract(
    eligibility_registry: Mapping[str, Any],
    selection_rule: Mapping[str, Any],
) -> None:
    eligible = tuple(eligibility_registry.get("eligible_method_ids_in_frozen_order", ()))
    if eligible != ELIGIBLE_METHOD_IDS:
        raise SelectionRuleError("eligibility registry differs from the frozen eight-method set")

    method_rows = eligibility_registry.get("methods")
    if not isinstance(method_rows, list):
        raise SelectionRuleError("eligibility registry methods must be a list")
    method_map = {row.get("method_id"): row for row in method_rows if isinstance(row, Mapping)}
    if len(method_map) != 14:
        raise SelectionRuleError("eligibility registry must contain 14 unique methods")
    for method_id in ELIGIBLE_METHOD_IDS:
        if method_map[method_id].get("complete_router_selection_candidate") is not True:
            raise SelectionRuleError(f"{method_id}: frozen candidate flag differs")
    p4 = method_map.get("R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", {})
    if p4.get("pre_test_selection_eligibility") != "INELIGIBLE":
        raise SelectionRuleError("P4 must remain explicitly ineligible")

    if tuple(selection_rule.get("eligible_complete_method_ids", ())) != ELIGIBLE_METHOD_IDS:
        raise SelectionRuleError("selection rule differs from the frozen eight-method set")
    coverage_gate = selection_rule.get("coverage_gate", {})
    coverage_requirements = coverage_gate.get("requirements")
    if not isinstance(coverage_requirements, list):
        raise SelectionRuleError("coverage requirements must be a list")
    coverage_fields = tuple(item.get("field") for item in coverage_requirements)
    coverage_values = tuple(item.get("required_value") for item in coverage_requirements)
    if coverage_gate.get("combination") != "ALL_TRUE":
        raise SelectionRuleError("coverage requirements must be combined with ALL_TRUE")
    if coverage_fields != COVERAGE_FIELDS or coverage_values != (True,) * len(COVERAGE_FIELDS):
        raise SelectionRuleError("coverage requirements differ from the frozen five-field gate")
    if coverage_gate.get("imputation_permitted") is not False:
        raise SelectionRuleError("prediction imputation must remain prohibited")
    criteria = selection_rule.get("selection_order")
    if not isinstance(criteria, list) or len(criteria) != 11:
        raise SelectionRuleError("selection rule must contain exactly 11 criteria")
    ranks = tuple(item.get("rank") for item in criteria)
    fields = tuple(item.get("field") for item in criteria)
    directions = tuple(item.get("direction") for item in criteria)
    if ranks != tuple(range(1, 12)):
        raise SelectionRuleError("selection ranks must be exactly 1 through 11")
    if fields != EXPECTED_SELECTION_FIELDS or directions != EXPECTED_SELECTION_DIRECTIONS:
        raise SelectionRuleError("selection fields or directions differ from the frozen order")
    if selection_rule.get("method_tier_number_by_method_id") != METHOD_TIER_NUMBERS:
        raise SelectionRuleError("method-tier mapping differs from the frozen source tiers")
    binding = selection_rule.get("binding", {})
    if binding.get("initial_value") != "WAITING_FOR_RQ2_FINAL_SCORING":
        raise SelectionRuleError("initial RQ3 binding is not WAITING")
    if selection_rule.get("p4_can_be_selected") is not False:
        raise SelectionRuleError("P4 selection prohibition differs")


def coverage_is_complete(row: Mapping[str, Any]) -> bool:
    """Return true only when all five frozen coverage requirements are true."""

    return all(row.get(field) is True for field in COVERAGE_FIELDS)


def _selection_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    method_id = row["method_id"]
    numeric_key: list[Decimal] = []
    for field, direction in NUMERIC_SELECTION_FIELDS:
        value = _finite_decimal(row.get(field), field=field, method_id=method_id)
        numeric_key.append(-value if direction == "HIGHER_IS_BETTER" else value)
    return (*numeric_key, METHOD_TIER_NUMBERS[method_id], method_id.encode("utf-8"))


def select_final_router(
    metric_rows: Sequence[Mapping[str, Any]],
    eligibility_registry: Mapping[str, Any],
    selection_rule: Mapping[str, Any],
) -> str:
    """Select one Router from a future final scoring table.

    All eight pre-TEST candidates must have explicit rows. A row failing any
    coverage requirement stays reportable but is filtered from selection.
    Missing metrics on a coverage-complete candidate fail closed; no value is
    imputed. Ineligible methods, including P4, are never considered.
    """

    _validate_contract(eligibility_registry, selection_rule)

    by_method: dict[str, Mapping[str, Any]] = {}
    known_method_ids = {
        row["method_id"]
        for row in eligibility_registry["methods"]
        if isinstance(row, Mapping) and isinstance(row.get("method_id"), str)
    }
    for row in metric_rows:
        method_id = row.get("method_id")
        if not isinstance(method_id, str) or method_id not in known_method_ids:
            raise SelectionRuleError("scoring table contains an unknown or invalid method ID")
        if method_id in by_method:
            raise SelectionRuleError(f"duplicate scoring row: {method_id}")
        by_method[method_id] = row

    missing = [method_id for method_id in ELIGIBLE_METHOD_IDS if method_id not in by_method]
    if missing:
        raise SelectionRuleError(f"missing explicit candidate rows: {', '.join(missing)}")

    for method_id in ELIGIBLE_METHOD_IDS:
        row = by_method[method_id]
        for field in COVERAGE_FIELDS:
            if field not in row or not isinstance(row[field], bool):
                raise SelectionRuleError(
                    f"{method_id}: {field} requires an explicit boolean coverage disclosure"
                )

    selectable = [
        by_method[method_id]
        for method_id in ELIGIBLE_METHOD_IDS
        if coverage_is_complete(by_method[method_id])
    ]
    if not selectable:
        raise SelectionRuleError("no coverage-complete eligible method; binding must remain WAITING")

    return min(selectable, key=_selection_key)["method_id"]
