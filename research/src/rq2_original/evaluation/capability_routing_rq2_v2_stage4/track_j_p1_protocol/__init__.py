"""Frozen Stage 4J-0 P1 Hybrid policy protocol.

This package exposes only deterministic, provider-free reference semantics.
It does not load or score governed DEV artifacts.
"""

from .p1_protocol import (
    CAPABILITY_ORDER,
    DIAGNOSTIC_POLICY_ID,
    ELIGIBLE_POLICY_IDS,
    OUTER_FOLDS,
    CapabilitySignature,
    ContractError,
    P1Case,
    RouteDecision,
    apply_policy,
    evaluate_policy,
    nested_policy_evaluation,
    policy_selection_key,
    select_outer_policy,
    select_policy,
    should_fallback,
)

__all__ = [
    "CAPABILITY_ORDER",
    "DIAGNOSTIC_POLICY_ID",
    "ELIGIBLE_POLICY_IDS",
    "OUTER_FOLDS",
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
