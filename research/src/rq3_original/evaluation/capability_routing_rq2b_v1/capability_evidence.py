"""Evidence composition for the research-only P1 capability router.

This module deliberately reuses the frozen RQ2-A Intent seed map, the current
production C_FULL Need Signals, and the Legacy adapter's exact working-Memory
dependency predicate.  It contains no new lexical detector, trained weight,
per-case exception, or Capability-Gold field access.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from evaluation.capability_routing_v1.build_capability_development_bank import (
    INTENT_CAPABILITY_SEED_MAP,
)
from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
    _working_memory_dependency,
)
from utils.c_full_service import CFullNeedSignals, detect_c_full_need_signals
from utils.conversation_memory import MemoryRuntimeResult

from . import CAPABILITIES, RQ2BError, capability_order


FROZEN_INTENT_CAPABILITY_SEED_MAP: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        str(intent): tuple(capabilities)
        for intent, capabilities in INTENT_CAPABILITY_SEED_MAP.items()
    }
)


@dataclass(frozen=True)
class SemanticCapabilityEvidence:
    policy_id: str
    selected_intents: tuple[str, ...]
    selected_capabilities: tuple[str, ...]
    maximum_mapped_intent_score: Mapping[str, float | None]
    supporting_intents: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "selected_intents": list(self.selected_intents),
            "selected_capabilities": list(self.selected_capabilities),
            "maximum_mapped_intent_score": dict(
                self.maximum_mapped_intent_score
            ),
            "supporting_intents": {
                name: list(values) for name, values in self.supporting_intents.items()
            },
        }


@dataclass(frozen=True)
class DeterministicCapabilityEvidence:
    capabilities: tuple[str, ...]
    capability_evidence: Mapping[str, tuple[str, ...]]
    working_memory_dependency: bool
    discrepancy_correction_need: bool
    explicit_source_restriction: bool
    need_signals: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "capability_evidence": {
                name: list(values) for name, values in self.capability_evidence.items()
            },
            "working_memory_dependency": self.working_memory_dependency,
            "discrepancy_correction_need": self.discrepancy_correction_need,
            "explicit_source_restriction": self.explicit_source_restriction,
            "need_signals": dict(self.need_signals),
        }


def detect_existing_need_signals(
    effective_query: str,
    *,
    current_page: str,
    structured_memory: Mapping[str, Any] | None = None,
) -> CFullNeedSignals:
    """Call the production signal detector with existing active state only."""

    state = dict(structured_memory or {})
    active_course_item = state.get("active_course_item")
    if active_course_item is not None and not isinstance(active_course_item, Mapping):
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: active course item is not a mapping"
        )
    return detect_c_full_need_signals(
        str(effective_query or ""),
        current_page=str(current_page or ""),
        active_course_item=dict(active_course_item or {}),
        enable_p2a_extensions=True,
    )


def frozen_intent_capabilities(intent_id: str) -> tuple[str, ...]:
    """Return exactly the RQ2-A seed-map entry for one frozen Intent."""

    return tuple(FROZEN_INTENT_CAPABILITY_SEED_MAP.get(str(intent_id), ()))


def capabilities_for_selected_intents(
    selected_intents: Iterable[str],
) -> tuple[str, ...]:
    selected: list[str] = []
    for intent_id in selected_intents:
        selected.extend(frozen_intent_capabilities(str(intent_id)))
    return capability_order(selected)


def build_semantic_capability_evidence(
    *,
    intent_scores: Mapping[str, float],
    selected_intents: Sequence[str],
    policy_id: str,
) -> SemanticCapabilityEvidence:
    """Project selected C0 Intents through the immutable RQ2-A seed map."""

    ordered_intents = tuple(dict.fromkeys(str(value) for value in selected_intents))
    missing_scores = [name for name in ordered_intents if name not in intent_scores]
    if missing_scores:
        raise RQ2BError(
            "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: selected Intent lacks score: "
            + ",".join(missing_scores)
        )
    supporting: dict[str, tuple[str, ...]] = {}
    maximum: dict[str, float | None] = {}
    for capability in CAPABILITIES:
        intent_ids = tuple(
            intent_id
            for intent_id in ordered_intents
            if capability in frozen_intent_capabilities(intent_id)
        )
        supporting[capability] = intent_ids
        maximum[capability] = (
            max(float(intent_scores[intent_id]) for intent_id in intent_ids)
            if intent_ids
            else None
        )
    return SemanticCapabilityEvidence(
        policy_id=str(policy_id),
        selected_intents=ordered_intents,
        selected_capabilities=capabilities_for_selected_intents(ordered_intents),
        maximum_mapped_intent_score=maximum,
        supporting_intents=supporting,
    )


def legacy_working_memory_dependency(
    memory_runtime: MemoryRuntimeResult,
    *,
    selected_route: str,
) -> bool:
    """Invoke the Legacy predicate with its exact production-context shape."""

    resolution = memory_runtime.memory_resolution
    if resolution is None:
        raise RQ2BError(
            "BLOCKED_RQ2_B_CONTEXT_STATUS: Memory resolution is absent"
        )
    legacy_context = {
        "selected_route": str(selected_route or ""),
        "memory_resolution": {
            "resolved": bool(resolution.resolved),
            "referenced_items": list(resolution.referenced_items),
            "memory_context": dict(resolution.memory_context or {}),
            "resolution_type": str(resolution.resolution_type or ""),
            "structured_state": dict(memory_runtime.structured_memory or {}),
        },
    }
    # This is intentionally a direct call rather than a rewritten predicate.
    return bool(_working_memory_dependency(legacy_context))


def build_deterministic_capability_evidence(
    *,
    need_signals: CFullNeedSignals,
    memory_runtime: MemoryRuntimeResult,
    selected_route: str,
) -> DeterministicCapabilityEvidence:
    """Map production Need Signals and actual Memory dependency to Capability evidence."""

    evidence: dict[str, list[str]] = {name: [] for name in CAPABILITIES}
    if need_signals.dashboard_activity_need:
        evidence["dashboard_evidence"].append(
            "need_signal:dashboard_activity_need"
        )
    if need_signals.course_content_need:
        evidence["course_retrieval"].append("need_signal:course_content_need")
    if need_signals.planning_application_need:
        evidence["planning"].append("need_signal:planning_application_need")

    memory_dependency = legacy_working_memory_dependency(
        memory_runtime, selected_route=selected_route
    )
    if memory_dependency:
        evidence["episodic_memory"].append(
            "production_parity:working_memory_dependency"
        )
    if need_signals.plan_memory_need and memory_dependency:
        evidence["episodic_memory"].append("need_signal:plan_memory_need")

    active = capability_order(
        name for name, reasons in evidence.items() if reasons
    )
    return DeterministicCapabilityEvidence(
        capabilities=active,
        capability_evidence={
            name: tuple(reasons) for name, reasons in evidence.items()
        },
        working_memory_dependency=memory_dependency,
        discrepancy_correction_need=bool(
            need_signals.discrepancy_correction_need
        ),
        explicit_source_restriction=bool(
            need_signals.explicit_source_restriction
        ),
        need_signals=need_signals.to_dict(),
    )


def merge_capability_evidence(
    semantic: SemanticCapabilityEvidence,
    deterministic: DeterministicCapabilityEvidence,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Union semantic and deterministic evidence in frozen Capability order."""

    selected = capability_order(
        (*semantic.selected_capabilities, *deterministic.capabilities)
    )
    evidence: dict[str, tuple[str, ...]] = {}
    for capability in CAPABILITIES:
        semantic_reasons = tuple(
            f"semantic_intent:{intent_id}"
            for intent_id in semantic.supporting_intents.get(capability, ())
        )
        deterministic_reasons = tuple(
            deterministic.capability_evidence.get(capability, ())
        )
        evidence[capability] = tuple(
            dict.fromkeys((*semantic_reasons, *deterministic_reasons))
        )
    return selected, evidence
