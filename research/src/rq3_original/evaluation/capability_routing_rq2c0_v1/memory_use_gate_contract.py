"""Fixed selective episodic-state candidate and freshness contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MEMORY_POLICY_IDS = (
    "M0_P1_ONLY",
    "M1_RESOLVED_STATE_DEPENDENCY",
    "M2_EXPLICIT_MEMORY_NEED_WITH_STATE",
)


@dataclass(frozen=True)
class MemoryCandidateSignals:
    p1_episodic_memory: bool = False
    resolver_is_follow_up: bool = False
    resolver_resolved: bool = False
    active_goal_present: bool = False
    active_plan_present: bool = False
    constraint_present: bool = False
    correction_present: bool = False
    completion_present: bool = False
    referenced_item_present: bool = False
    plan_memory_need: bool = False
    discrepancy_correction_need: bool = False
    missing_context: bool = False

    @property
    def state_object_present(self) -> bool:
        return any(
            (
                self.active_goal_present,
                self.active_plan_present,
                self.constraint_present,
                self.correction_present,
                self.completion_present,
                self.referenced_item_present,
            )
        )


def memory_candidate(policy_id: str, signals: MemoryCandidateSignals) -> bool:
    if policy_id not in MEMORY_POLICY_IDS:
        raise ValueError("Unknown frozen Memory candidate policy")
    m0 = signals.p1_episodic_memory
    if policy_id == "M0_P1_ONLY":
        return m0
    m1 = m0 or (
        (signals.resolver_is_follow_up or signals.resolver_resolved)
        and signals.state_object_present
    )
    if policy_id == "M1_RESOLVED_STATE_DEPENDENCY":
        return m1
    return m1 or (
        (signals.plan_memory_need or signals.discrepancy_correction_need)
        and signals.state_object_present
    )


@dataclass(frozen=True)
class StateItemStatus:
    belongs_to_current_scope: bool
    active: bool
    completed: bool
    cancelled: bool
    superseded: bool
    stale: bool
    directly_supports_current_need: bool


def state_item_admissible(
    status: StateItemStatus, *, completion_itself_queried: bool = False
) -> bool:
    return bool(
        status.belongs_to_current_scope
        and status.active
        and not status.cancelled
        and not status.superseded
        and not status.stale
        and (not status.completed or completion_itself_queried)
        and status.directly_supports_current_need
    )


def selective_memory_contract() -> dict[str, Any]:
    return {
        "schema_version": "selective-episodic-state-use-contract-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "policy_ids": list(MEMORY_POLICY_IDS),
        "policies": {
            "M0_P1_ONLY": "P1_EPISODIC_MEMORY",
            "M1_RESOLVED_STATE_DEPENDENCY": "M0_OR_RESOLVER_DEPENDENCY_WITH_REAL_STATE_OBJECT",
            "M2_EXPLICIT_MEMORY_NEED_WITH_STATE": "M1_OR_EXPLICIT_MEMORY_NEED_WITH_REAL_STATE_OBJECT",
        },
        "real_state_object_fields": [
            "active_goal",
            "active_plan",
            "constraint",
            "correction",
            "completion",
            "referenced_item",
        ],
        "missing_context_alone_triggers_memory": False,
        "gold_label_used_as_candidate": False,
        "source_role_used_as_candidate": False,
        "scenario_family_used_as_candidate": False,
        "case_id_rule_count": 0,
        "new_keyword_list_count": 0,
        "llm_gate": False,
        "learned_classifier": False,
        "admission_requirements": [
            "CURRENT_CASE_OR_STUDENT_SCOPE",
            "ACTIVE",
            "NOT_COMPLETED_UNLESS_COMPLETION_IS_QUERIED",
            "NOT_CANCELLED",
            "NOT_SUPERSEDED",
            "NOT_STALE",
            "DIRECT_SUPPORT_FOR_REFERENT_GOAL_CONSTRAINT_OR_CORRECTION",
        ],
        "long_term_vector_memory_added": False,
        "cross_student_search": False,
        "production_behavior_changed": False,
        "p2_implemented": False,
    }
