"""Model-independent Stage-5A Hybrid Intent shadow decision policy.

This module consumes already-typed deterministic and semantic results. It does
not classify, retrieve, embed, access application state, or change production.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from utils.intent_schema import (
    FUTURE_SCOPE_OUTCOMES,
    LEGACY_QUERY_TYPES,
    SOURCE_SCOPE_LABELS,
    DeterministicIntentResult,
    SemanticIntentResult,
)


HYBRID_POLICY_VERSION = "hybrid-intent-shadow-policy-v1"
POLICY_MODE = "shadow_only"

HYBRID_OUTCOMES = (
    "HARD_GUARD_RETAINED",
    "DETERMINISTIC_SEMANTIC_AGREEMENT",
    "EXPLICIT_RULE_CONFLICT_RETAINED",
    "DERIVED_RULE_CONFLICT_RETAINED",
    "DEFAULT_FALLBACK_SEMANTIC_CANDIDATE",
    "DEFAULT_FALLBACK_FUTURE_OUTCOME_CANDIDATE",
    "DEFAULT_FALLBACK_OOS_CANDIDATE",
    "DEFAULT_FALLBACK_CLARIFICATION_CANDIDATE",
    "SEMANTIC_BELOW_DEVELOPMENT_GATE",
    "SEMANTIC_UNAVAILABLE",
    "SEMANTIC_ERROR",
    "SOURCE_SCOPE_SUGGESTION_CONFLICT",
    "SHADOW_ONLY_NO_ACTION",
)

HARD_GUARD_FLAGS = (
    "memory_transaction_authoritative",
    "explicit_source_restriction",
    "week_validation_fail_closed",
    "course_correction_authoritative",
    "capability_or_privacy_guard",
    "runtime_invariant_guard",
)


def _normalise_strings(values: Sequence[str], name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            raise ValueError(f"{name} cannot contain an empty value")
        if item not in result:
            result.append(item)
    return tuple(result)


def _finite_threshold(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1]")
    return numeric


@dataclass(frozen=True)
class DeterministicAuthorityContext:
    memory_transaction_authoritative: bool = False
    explicit_source_restriction: bool = False
    week_validation_fail_closed: bool = False
    course_correction_authoritative: bool = False
    capability_or_privacy_guard: bool = False
    source_scope_locked: bool = False
    runtime_invariant_guard: bool = False
    authority_reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in HARD_GUARD_FLAGS + ("source_scope_locked",):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be Boolean")
        object.__setattr__(
            self,
            "authority_reason_codes",
            _normalise_strings(self.authority_reason_codes, "authority_reason_codes"),
        )

    @property
    def hard_guard_triggered(self) -> bool:
        return any(getattr(self, name) for name in HARD_GUARD_FLAGS)

    @property
    def generated_reason_codes(self) -> tuple[str, ...]:
        generated = [name.upper() for name in HARD_GUARD_FLAGS if getattr(self, name)]
        if self.source_scope_locked:
            generated.append("SOURCE_SCOPE_LOCKED")
        return _normalise_strings((*generated, *self.authority_reason_codes), "hard_guard_reason_codes")


@dataclass(frozen=True)
class HybridRouterPolicy:
    policy_version: str
    policy_mode: str
    semantic_score_threshold: float
    semantic_margin_threshold: float
    oos_score_threshold: float
    oos_margin_threshold: float
    semantic_candidate_generation_enabled: bool
    semantic_override_action_enabled: bool
    source_scope_override_action_enabled: bool
    oos_action_enabled: bool
    clarification_action_enabled: bool
    shadow_diagnostics_enabled: bool
    production_activation_ready: bool
    production_activation_blockers: tuple[str, ...]
    selection_manifest_sha256: str
    threshold_status: str

    def __post_init__(self) -> None:
        if self.policy_version != HYBRID_POLICY_VERSION or self.policy_mode != POLICY_MODE:
            raise ValueError("Hybrid policy version or mode is invalid")
        for name in (
            "semantic_score_threshold", "semantic_margin_threshold",
            "oos_score_threshold", "oos_margin_threshold",
        ):
            object.__setattr__(self, name, _finite_threshold(getattr(self, name), name))
        if self.semantic_candidate_generation_enabled is not True or self.shadow_diagnostics_enabled is not True:
            raise ValueError("Stage 5A requires shadow candidate diagnostics")
        for name in (
            "semantic_override_action_enabled", "source_scope_override_action_enabled",
            "oos_action_enabled", "clarification_action_enabled", "production_activation_ready",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"Stage 5A requires {name}=false")
        blockers = _normalise_strings(self.production_activation_blockers, "production_activation_blockers")
        if "PRODUCTION_INTEGRATION_NOT_AUTHORISED" not in blockers:
            raise ValueError("Policy lacks the independent production-authorisation blocker")
        if len(self.selection_manifest_sha256) != 64:
            raise ValueError("Selection manifest SHA-256 is invalid")
        if self.threshold_status != "development_shadow_thresholds":
            raise ValueError("Hybrid policy thresholds must remain development shadow thresholds")
        object.__setattr__(self, "production_activation_blockers", blockers)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["production_activation_blockers"] = list(self.production_activation_blockers)
        return value

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "HybridRouterPolicy":
        return cls(
            policy_version=str(manifest["hybrid_policy_version"]),
            policy_mode=str(manifest["policy_mode"]),
            semantic_score_threshold=manifest["development_semantic_score_threshold"],
            semantic_margin_threshold=manifest["development_semantic_margin_threshold"],
            oos_score_threshold=manifest["development_oos_score_threshold"],
            oos_margin_threshold=manifest["development_oos_margin_threshold"],
            semantic_candidate_generation_enabled=manifest["semantic_candidate_generation_enabled"],
            semantic_override_action_enabled=manifest["semantic_override_action_enabled"],
            source_scope_override_action_enabled=manifest["source_scope_override_action_enabled"],
            oos_action_enabled=manifest["oos_action_enabled"],
            clarification_action_enabled=manifest["clarification_action_enabled"],
            shadow_diagnostics_enabled=manifest["shadow_diagnostics_enabled"],
            production_activation_ready=manifest["production_activation_ready"],
            production_activation_blockers=tuple(manifest["production_activation_blockers"]),
            selection_manifest_sha256=str(manifest["selection_manifest_sha256"]),
            threshold_status=str(manifest["threshold_status"]),
        )


@dataclass(frozen=True)
class HybridIntentShadowDecision:
    policy_version: str
    policy_mode: str
    deterministic_legacy_query_type: str
    deterministic_rule_id: str
    deterministic_match_kind: str
    deterministic_classification_strength: str
    deterministic_is_default_fallback: bool
    semantic_status: str
    semantic_winning_label: str | None
    semantic_winning_score: float | None
    semantic_second_label: str | None
    semantic_second_score: float | None
    semantic_margin: float | None
    semantic_suggested_source_scope: str
    semantic_legacy_candidate: str | None
    hard_guard_triggered: bool
    hard_guard_reason_codes: tuple[str, ...]
    source_scope_locked: bool
    semantic_source_scope_conflict: bool
    semantic_deterministic_agreement: bool
    development_semantic_gate_passed: bool
    development_oos_gate_passed: bool
    development_clarification_candidate: bool
    future_outcome_candidate: str | None
    would_semantic_override_in_future: bool
    would_oos_action_in_future: bool
    would_request_clarification_in_future: bool
    semantic_override_executed: bool
    oos_action_executed: bool
    clarification_action_executed: bool
    primary_outcome: str
    reason_codes: tuple[str, ...]
    final_legacy_query_type: str
    deterministic_source_scope_if_supplied: str | None
    final_source_scope_if_supplied: str | None
    final_source_scope: str | None
    production_activation_ready: bool
    production_activation_blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.policy_version != HYBRID_POLICY_VERSION or self.policy_mode != POLICY_MODE:
            raise ValueError("Shadow decision policy identity is invalid")
        if self.deterministic_legacy_query_type not in LEGACY_QUERY_TYPES:
            raise ValueError("Shadow decision deterministic query type is invalid")
        if self.final_legacy_query_type != self.deterministic_legacy_query_type:
            raise ValueError("Stage 5A final query type must retain deterministic parity")
        if self.final_source_scope_if_supplied != self.deterministic_source_scope_if_supplied:
            raise ValueError("Stage 5A final source scope must retain deterministic parity")
        if self.final_source_scope != self.final_source_scope_if_supplied:
            raise ValueError("Final source-scope aliases differ")
        if self.primary_outcome not in HYBRID_OUTCOMES:
            raise ValueError("Unknown hybrid primary outcome")
        if any((self.semantic_override_executed, self.oos_action_executed, self.clarification_action_executed)):
            raise ValueError("Stage 5A cannot execute production actions")
        if self.production_activation_ready:
            raise ValueError("Stage 5A cannot mark production activation ready")
        object.__setattr__(self, "hard_guard_reason_codes", _normalise_strings(self.hard_guard_reason_codes, "hard_guard_reason_codes"))
        object.__setattr__(self, "reason_codes", _normalise_strings(self.reason_codes, "reason_codes"))
        object.__setattr__(self, "production_activation_blockers", _normalise_strings(self.production_activation_blockers, "production_activation_blockers"))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("hard_guard_reason_codes", "reason_codes", "production_activation_blockers"):
            value[name] = list(value[name])
        return value


def load_hybrid_router_policy(
    *,
    policy_manifest_path: str | Path,
    policy_sha256_path: str | Path,
) -> HybridRouterPolicy:
    manifest_path = Path(policy_manifest_path)
    sha_path = Path(policy_sha256_path)
    if not manifest_path.is_file() or not sha_path.is_file():
        raise FileNotFoundError("Hybrid policy manifest and SHA-256 sidecar are required")
    parts = sha_path.read_text(encoding="utf-8").strip().split("  ")
    if len(parts) != 2 or parts[1] != manifest_path.name or len(parts[0]) != 64:
        raise ValueError("Hybrid policy SHA-256 sidecar is malformed")
    actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if actual != parts[0]:
        raise ValueError("Hybrid policy manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("production_integration") is not False:
        raise ValueError("Hybrid policy manifest unexpectedly enables production integration")
    return HybridRouterPolicy.from_manifest(manifest)


def _append_unique(values: list[str], *items: str) -> None:
    for item in items:
        if item and item not in values:
            values.append(item)


def decide_hybrid_intent_shadow(
    *,
    deterministic_result: DeterministicIntentResult,
    semantic_result: SemanticIntentResult,
    policy: HybridRouterPolicy,
    authority_context: DeterministicAuthorityContext | None = None,
    deterministic_source_scope: str | None = None,
) -> HybridIntentShadowDecision:
    authority = authority_context or DeterministicAuthorityContext()
    if deterministic_source_scope is not None and deterministic_source_scope not in SOURCE_SCOPE_LABELS:
        raise ValueError("deterministic_source_scope is invalid")
    available = semantic_result.status == "available"
    label = semantic_result.winning_label if available else None
    score = semantic_result.winning_score if available else None
    margin = semantic_result.margin if available else None
    semantic_gate = bool(
        available
        and label != "out_of_scope"
        and score is not None
        and margin is not None
        and score >= policy.semantic_score_threshold
        and margin >= policy.semantic_margin_threshold
    )
    oos_gate = bool(
        available
        and label == "out_of_scope"
        and margin is not None
        and semantic_result.out_of_scope_score >= policy.oos_score_threshold
        and margin >= policy.oos_margin_threshold
    )
    clarification = bool(available and ((not semantic_gate and not oos_gate) or label == "ambiguous"))
    agreement = bool(available and label == deterministic_result.legacy_query_type)
    future = label if label in FUTURE_SCOPE_OUTCOMES else None
    legacy_candidate = label if label in LEGACY_QUERY_TYPES else None
    scope_conflict = bool(
        available
        and deterministic_source_scope is not None
        and semantic_result.suggested_source_scope != deterministic_source_scope
    )
    reasons: list[str] = []
    hard_reasons = authority.generated_reason_codes
    if authority.hard_guard_triggered:
        primary = "HARD_GUARD_RETAINED"
        _append_unique(reasons, primary, *hard_reasons)
    elif semantic_result.status in {"not_run", "unavailable"}:
        primary = "SEMANTIC_UNAVAILABLE"
        _append_unique(reasons, primary, "SEMANTIC_NOT_RUN" if semantic_result.status == "not_run" else "SEMANTIC_UNAVAILABLE")
    elif semantic_result.status == "error":
        primary = "SEMANTIC_ERROR"
        _append_unique(reasons, primary)
    elif agreement:
        primary = "DETERMINISTIC_SEMANTIC_AGREEMENT"
        _append_unique(reasons, primary, "AGREEMENT_ABOVE_DEVELOPMENT_GATE" if semantic_gate else "AGREEMENT_BELOW_DEVELOPMENT_GATE")
    elif deterministic_result.classification_strength == "explicit":
        primary = "EXPLICIT_RULE_CONFLICT_RETAINED"
        _append_unique(reasons, primary)
    elif deterministic_result.classification_strength == "derived":
        primary = "DERIVED_RULE_CONFLICT_RETAINED"
        _append_unique(reasons, primary)
    elif deterministic_result.is_default_fallback:
        if label == "out_of_scope" and oos_gate:
            primary = "DEFAULT_FALLBACK_OOS_CANDIDATE"
        elif label in {"social_interaction", "unsupported_task"} and semantic_gate:
            primary = "DEFAULT_FALLBACK_FUTURE_OUTCOME_CANDIDATE"
        elif label == "ambiguous" or not semantic_gate:
            primary = "DEFAULT_FALLBACK_CLARIFICATION_CANDIDATE"
        elif legacy_candidate is not None:
            primary = "DEFAULT_FALLBACK_SEMANTIC_CANDIDATE"
        else:
            primary = "DEFAULT_FALLBACK_FUTURE_OUTCOME_CANDIDATE"
        _append_unique(reasons, primary)
    else:
        primary = "SEMANTIC_BELOW_DEVELOPMENT_GATE"
        _append_unique(reasons, primary)

    if available:
        _append_unique(reasons, "DEVELOPMENT_SEMANTIC_GATE_PASSED" if semantic_gate else "SEMANTIC_BELOW_DEVELOPMENT_GATE")
        if label == "out_of_scope":
            _append_unique(reasons, "DEVELOPMENT_OOS_GATE_PASSED" if oos_gate else "DEVELOPMENT_OOS_GATE_FAILED")
        if future is not None:
            _append_unique(reasons, "FUTURE_OUTCOME_CANDIDATE")
        if clarification:
            _append_unique(reasons, "DEVELOPMENT_CLARIFICATION_CANDIDATE")
    if scope_conflict:
        _append_unique(reasons, "SOURCE_SCOPE_SUGGESTION_CONFLICT")
    elif available and deterministic_source_scope is not None:
        _append_unique(reasons, "SOURCE_SCOPE_SUGGESTION_AGREEMENT")
    if authority.source_scope_locked:
        _append_unique(reasons, "SOURCE_SCOPE_LOCKED")
    _append_unique(reasons, "SHADOW_ONLY_NO_ACTION")

    would_semantic = bool(
        deterministic_result.is_default_fallback
        and legacy_candidate is not None
        and semantic_gate
    )
    would_oos = bool(deterministic_result.is_default_fallback and label == "out_of_scope" and oos_gate)
    return HybridIntentShadowDecision(
        policy_version=policy.policy_version,
        policy_mode=policy.policy_mode,
        deterministic_legacy_query_type=deterministic_result.legacy_query_type,
        deterministic_rule_id=deterministic_result.rule_id,
        deterministic_match_kind=deterministic_result.match_kind,
        deterministic_classification_strength=deterministic_result.classification_strength,
        deterministic_is_default_fallback=deterministic_result.is_default_fallback,
        semantic_status=semantic_result.status,
        semantic_winning_label=label,
        semantic_winning_score=score,
        semantic_second_label=semantic_result.second_label if available else None,
        semantic_second_score=semantic_result.second_score if available else None,
        semantic_margin=margin,
        semantic_suggested_source_scope=semantic_result.suggested_source_scope,
        semantic_legacy_candidate=legacy_candidate,
        hard_guard_triggered=authority.hard_guard_triggered,
        hard_guard_reason_codes=hard_reasons,
        source_scope_locked=authority.source_scope_locked,
        semantic_source_scope_conflict=scope_conflict,
        semantic_deterministic_agreement=agreement,
        development_semantic_gate_passed=semantic_gate,
        development_oos_gate_passed=oos_gate,
        development_clarification_candidate=clarification,
        future_outcome_candidate=future,
        would_semantic_override_in_future=would_semantic,
        would_oos_action_in_future=would_oos,
        would_request_clarification_in_future=clarification,
        semantic_override_executed=False,
        oos_action_executed=False,
        clarification_action_executed=False,
        primary_outcome=primary,
        reason_codes=tuple(reasons),
        final_legacy_query_type=deterministic_result.legacy_query_type,
        deterministic_source_scope_if_supplied=deterministic_source_scope,
        final_source_scope_if_supplied=deterministic_source_scope,
        final_source_scope=deterministic_source_scope,
        production_activation_ready=policy.production_activation_ready,
        production_activation_blockers=policy.production_activation_blockers,
    )
