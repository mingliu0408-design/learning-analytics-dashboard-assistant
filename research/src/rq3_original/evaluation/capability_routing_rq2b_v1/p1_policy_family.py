"""The five preregistered, fixed P1 semantic-union policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from . import CAPABILITIES, POLICY_IDS, capability_order


@dataclass(frozen=True)
class P1Policy:
    policy_id: str
    rank_k: int | None = None
    delta: float | None = None

    def __post_init__(self) -> None:
        if self.policy_id not in POLICY_IDS:
            raise ValueError("policy is outside the preregistered grid")
        if (self.rank_k is None) == (self.delta is None):
            raise ValueError("policy must specify exactly one fixed selection mechanism")

    def select_intents(
        self, ranked_intents: Sequence[Mapping[str, Any]]
    ) -> tuple[str, ...]:
        eligible = [row for row in ranked_intents if bool(row.get("eligible", True))]
        if not eligible:
            raise ValueError("C0 produced no eligible intents")
        if self.rank_k is not None:
            selected = eligible[: self.rank_k]
        else:
            top_score = float(eligible[0]["score"])
            selected = [
                row
                for row in eligible[:3]
                if float(row["score"]) >= top_score - float(self.delta)
            ]
            if not selected:
                selected = [eligible[0]]
        return tuple(str(row["intent_id"]) for row in selected)


POLICIES: tuple[P1Policy, ...] = (
    P1Policy("P1_K1_SIGNAL_UNION", rank_k=1),
    P1Policy("P1_K2_SIGNAL_UNION", rank_k=2),
    P1Policy("P1_K3_SIGNAL_UNION", rank_k=3),
    P1Policy("P1_D05_SIGNAL_UNION", delta=0.05),
    P1Policy("P1_D10_SIGNAL_UNION", delta=0.10),
)
POLICY_BY_ID = {policy.policy_id: policy for policy in POLICIES}


def policy_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "rq2b-p1-policy-family-v1",
        "stage": "RQ2-B",
        "status": "FROZEN_BEFORE_EVALUATION",
        "policy_ids": list(POLICY_IDS),
        "policies": [
            {
                "policy_id": policy.policy_id,
                "rank_k": policy.rank_k,
                "delta_from_top1": policy.delta,
                "candidate_window": 3 if policy.delta is not None else policy.rank_k,
                "always_include_top1": True,
                "union_deterministic_need_signals": True,
                "union_context_and_episodic_signals": True,
            }
            for policy in POLICIES
        ],
        "per_capability_threshold_search": False,
        "absolute_score_threshold": None,
        "learned_weights": False,
        "trained_classifier": False,
        "llm_router": False,
        "case_specific_rules": False,
        "source_specific_policy": False,
        "authentic_specific_policy": False,
    }


def validate_capability_plan(capabilities: Iterable[str]) -> dict[str, bool]:
    ordered = capability_order(capabilities)
    active = set(ordered)
    return {
        "clarification_exclusivity_violation": bool(
            "clarification" in active and active != {"clarification"}
        ),
        "safe_direct_exclusivity_violation": bool(
            "safe_direct_response" in active and active != {"safe_direct_response"}
        ),
        "empty_capability_plan": not active,
    }


def policy_from_id(policy_id: str) -> P1Policy:
    try:
        return POLICY_BY_ID[policy_id]
    except KeyError as exc:
        raise ValueError("policy is outside the fixed five-policy grid") from exc
