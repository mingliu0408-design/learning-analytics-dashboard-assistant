"""Versioned, serialisable intent contracts for deterministic and future routing.

This module defines data only.  It does not classify queries, run semantic
models, choose production routes, or decide the live C_FULL source scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Literal, Sequence


INTENT_SCHEMA_VERSION = "intent-schema-v1"


LEGACY_QUERY_TYPES = (
    "memory_state_query",
    "hybrid_course_and_planning",
    "quantitative_metric_query",
    "metric_clarification",
    "reflection_structure_question",
    "course_content_question",
    "access_or_capability_question",
    "discrepancy_or_correction",
    "technical_data_question",
    "dashboard_interpretation",
    "improvement_recommendation",
    "cross_page_relationship",
    "planning_or_strategy",
    "emotional_or_justification",
)

FUTURE_SCOPE_OUTCOMES = (
    "social_interaction",
    "unsupported_task",
    "out_of_scope",
    "ambiguous",
)

SEMANTIC_INTENT_LABELS = LEGACY_QUERY_TYPES + FUTURE_SCOPE_OUTCOMES

PRODUCTION_SOURCE_SCOPES = (
    "memory_only",
    "dashboard_only",
    "course_only",
    "hybrid",
)

FUTURE_SOURCE_SCOPES = (
    "undetermined",
    "no_supported_source",
)

SOURCE_SCOPE_LABELS = PRODUCTION_SOURCE_SCOPES + FUTURE_SOURCE_SCOPES


class IntentReasonCode(str, Enum):
    """Stable, text-free reasons suitable for logs and evaluation records."""

    EMPTY_QUERY_DEFAULT = "EMPTY_QUERY_DEFAULT"
    MEMORY_STATE_PATTERN = "MEMORY_STATE_PATTERN"
    HYBRID_COURSE_PLANNING_SIGNAL = "HYBRID_COURSE_PLANNING_SIGNAL"
    COURSE_READING_SELECTION_PATTERN = "COURSE_READING_SELECTION_PATTERN"
    QUANTITATIVE_METRIC_PATTERN = "QUANTITATIVE_METRIC_PATTERN"
    ACCESS_CAPABILITY_PATTERN = "ACCESS_CAPABILITY_PATTERN"
    DISCREPANCY_CORRECTION_PATTERN = "DISCREPANCY_CORRECTION_PATTERN"
    REFLECTION_STRUCTURE_PATTERN = "REFLECTION_STRUCTURE_PATTERN"
    COURSE_CONTENT_PATTERN = "COURSE_CONTENT_PATTERN"
    CROSS_PAGE_RELATIONSHIP_PATTERN = "CROSS_PAGE_RELATIONSHIP_PATTERN"
    TECHNICAL_DATA_PATTERN = "TECHNICAL_DATA_PATTERN"
    METRIC_CLARIFICATION_HELPER = "METRIC_CLARIFICATION_HELPER"
    DASHBOARD_INTERPRETATION_HELPER = "DASHBOARD_INTERPRETATION_HELPER"
    PLANNING_STRATEGY_PATTERN = "PLANNING_STRATEGY_PATTERN"
    IMPROVEMENT_RECOMMENDATION_PATTERN = "IMPROVEMENT_RECOMMENDATION_PATTERN"
    EMOTIONAL_JUSTIFICATION_PATTERN = "EMOTIONAL_JUSTIFICATION_PATTERN"
    UNMATCHED_DEFAULT = "UNMATCHED_DEFAULT"
    SEMANTIC_NOT_RUN = "SEMANTIC_NOT_RUN"
    SEMANTIC_UNAVAILABLE = "SEMANTIC_UNAVAILABLE"
    SEMANTIC_ERROR = "SEMANTIC_ERROR"
    SEMANTIC_RETRIEVAL_AVAILABLE = "SEMANTIC_RETRIEVAL_AVAILABLE"
    SEMANTIC_EMPTY_QUERY = "SEMANTIC_EMPTY_QUERY"
    SEMANTIC_INDEX_INVALID = "SEMANTIC_INDEX_INVALID"
    SEMANTIC_PAGE_INVALID = "SEMANTIC_PAGE_INVALID"
    SEMANTIC_BACKEND_INVALID = "SEMANTIC_BACKEND_INVALID"
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    HARD_GUARD = "HARD_GUARD"


INTENT_REASON_CODES = tuple(item.value for item in IntentReasonCode)

LegacyQueryType = Literal[
    "memory_state_query",
    "hybrid_course_and_planning",
    "quantitative_metric_query",
    "metric_clarification",
    "reflection_structure_question",
    "course_content_question",
    "access_or_capability_question",
    "discrepancy_or_correction",
    "technical_data_question",
    "dashboard_interpretation",
    "improvement_recommendation",
    "cross_page_relationship",
    "planning_or_strategy",
    "emotional_or_justification",
]
SemanticIntentLabel = str
SourceScopeLabel = str
MatchKind = Literal[
    "pattern",
    "derived_signal",
    "helper",
    "empty_default",
    "unmatched_default",
]
ClassificationStrength = Literal["explicit", "derived", "default"]
SemanticStatus = Literal["not_run", "available", "unavailable", "error"]
DecisionSource = Literal[
    "deterministic",
    "semantic",
    "agreement",
    "hard_guard",
    "fallback",
    "not_run",
]

MATCH_KINDS = (
    "pattern",
    "derived_signal",
    "helper",
    "empty_default",
    "unmatched_default",
)
CLASSIFICATION_STRENGTHS = ("explicit", "derived", "default")
SEMANTIC_STATUSES = ("not_run", "available", "unavailable", "error")
DECISION_SOURCES = (
    "deterministic",
    "semantic",
    "agreement",
    "hard_guard",
    "fallback",
    "not_run",
)


def _validate_schema_version(value: str) -> None:
    if value != INTENT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {INTENT_SCHEMA_VERSION!r}, got {value!r}"
        )


def _validate_score(name: str, value: float | None, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in [0.0, 1.0]")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} must be a finite number in [0.0, 1.0]")


def _validate_label(label: str, *, semantic: bool) -> None:
    allowed = SEMANTIC_INTENT_LABELS if semantic else LEGACY_QUERY_TYPES
    if label not in allowed:
        kind = "semantic intent" if semantic else "legacy query type"
        raise ValueError(f"Unknown {kind}: {label!r}")


def _validate_scope(scope: str) -> None:
    if scope not in SOURCE_SCOPE_LABELS:
        raise ValueError(f"Unknown source scope: {scope!r}")


def _normalise_reason_codes(
    values: Sequence[str | IntentReasonCode],
) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        code = value.value if isinstance(value, IntentReasonCode) else str(value)
        if code not in INTENT_REASON_CODES:
            raise ValueError(f"Unknown intent reason code: {code!r}")
        if code not in result:
            result.append(code)
    return tuple(result)


def _normalise_string_tuple(values: Sequence[str], name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            raise ValueError(f"{name} cannot contain an empty value")
        if item not in result:
            result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class IntentCandidate:
    """One future semantic-router candidate; no predictor is implemented here."""

    label: SemanticIntentLabel
    score: float
    suggested_source_scope: SourceScopeLabel = "undetermined"
    example_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_label(self.label, semantic=True)
        _validate_score("score", self.score)
        _validate_scope(self.suggested_source_scope)
        object.__setattr__(
            self, "example_ids", _normalise_string_tuple(self.example_ids, "example_ids")
        )
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score": self.score,
            "suggested_source_scope": self.suggested_source_scope,
            "example_ids": list(self.example_ids),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class DeterministicIntentResult:
    """Auditable result from the unchanged legacy deterministic classifier."""

    original_query: str
    normalised_query: str
    legacy_query_type: LegacyQueryType
    rule_id: str
    rule_family: str
    match_kind: MatchKind
    is_explicit_match: bool
    is_default_fallback: bool
    is_empty_query: bool
    classification_strength: ClassificationStrength
    reason_codes: tuple[str, ...]
    classification_mechanism: str = "deterministic_rules"
    schema_version: str = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        _validate_label(self.legacy_query_type, semantic=False)
        if self.match_kind not in MATCH_KINDS:
            raise ValueError(f"Unknown match_kind: {self.match_kind!r}")
        if self.classification_strength not in CLASSIFICATION_STRENGTHS:
            raise ValueError(
                f"Unknown classification_strength: {self.classification_strength!r}"
            )
        if self.classification_mechanism != "deterministic_rules":
            raise ValueError("Deterministic results must use deterministic_rules")
        if self.is_explicit_match and self.is_default_fallback:
            raise ValueError("Explicit match and default fallback are mutually exclusive")
        if self.is_default_fallback:
            if self.match_kind not in {"empty_default", "unmatched_default"}:
                raise ValueError("Default fallbacks require a default match_kind")
            if self.classification_strength != "default":
                raise ValueError("Default fallbacks require default classification strength")
        elif self.match_kind in {"empty_default", "unmatched_default"}:
            raise ValueError("Default match_kind requires is_default_fallback=True")
        if self.is_empty_query != (self.normalised_query == ""):
            raise ValueError("is_empty_query must match the normalised query")
        if self.is_empty_query and self.match_kind != "empty_default":
            raise ValueError("An empty query must use empty_default")
        if not str(self.rule_id).strip() or not str(self.rule_family).strip():
            raise ValueError("rule_id and rule_family must be non-empty")
        codes = _normalise_reason_codes(self.reason_codes)
        if self.rule_id not in codes:
            raise ValueError("reason_codes must include rule_id")
        object.__setattr__(self, "original_query", str(self.original_query))
        object.__setattr__(self, "normalised_query", str(self.normalised_query))
        object.__setattr__(self, "reason_codes", codes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "normalised_query": self.normalised_query,
            "legacy_query_type": self.legacy_query_type,
            "rule_id": self.rule_id,
            "rule_family": self.rule_family,
            "match_kind": self.match_kind,
            "is_explicit_match": self.is_explicit_match,
            "is_default_fallback": self.is_default_fallback,
            "is_empty_query": self.is_empty_query,
            "classification_strength": self.classification_strength,
            "reason_codes": list(self.reason_codes),
            "classification_mechanism": self.classification_mechanism,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class SemanticIntentResult:
    """Future semantic result contract; Stage 2 creates no live predictions."""

    status: SemanticStatus
    winning_label: SemanticIntentLabel | None = None
    winning_score: float | None = None
    second_label: SemanticIntentLabel | None = None
    second_score: float | None = None
    margin: float | None = None
    candidates: tuple[IntentCandidate, ...] = field(default_factory=tuple)
    suggested_source_scope: SourceScopeLabel = "undetermined"
    out_of_scope_score: float = 0.0
    requires_clarification: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    model_version: str = "not-run"
    index_version: str = "not-run"
    schema_version: str = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        if self.status not in SEMANTIC_STATUSES:
            raise ValueError(f"Unknown semantic status: {self.status!r}")
        _validate_scope(self.suggested_source_scope)
        _validate_score("winning_score", self.winning_score, optional=True)
        _validate_score("second_score", self.second_score, optional=True)
        _validate_score("margin", self.margin, optional=True)
        _validate_score("out_of_scope_score", self.out_of_scope_score)
        if (self.winning_label is None) != (self.winning_score is None):
            raise ValueError("winning_label and winning_score must be provided together")
        if (self.second_label is None) != (self.second_score is None):
            raise ValueError("second_label and second_score must be provided together")
        if self.winning_label is not None:
            _validate_label(self.winning_label, semantic=True)
        if self.second_label is not None:
            _validate_label(self.second_label, semantic=True)
        if self.winning_label is not None and self.winning_label == self.second_label:
            raise ValueError("winning_label and second_label must differ")
        ordered = tuple(sorted(tuple(self.candidates), key=lambda item: (-item.score, item.label)))
        if self.status == "not_run" and ordered:
            raise ValueError("not_run semantic results cannot contain candidates")
        if self.status == "available" and self.winning_label is None:
            raise ValueError("available semantic results require a winning candidate")
        if ordered:
            first = ordered[0]
            if self.winning_label != first.label or self.winning_score != first.score:
                raise ValueError("winning result must match the highest sorted candidate")
            if self.second_label is not None:
                if len(ordered) < 2:
                    raise ValueError("A second result requires at least two candidates")
                second = ordered[1]
                if self.second_label != second.label or self.second_score != second.score:
                    raise ValueError("second result must match the second sorted candidate")
        if self.winning_score is not None and self.second_score is not None:
            expected_margin = self.winning_score - self.second_score
            if expected_margin < 0.0:
                raise ValueError("winning_score must be at least second_score")
            if self.margin is None or not math.isclose(
                self.margin, expected_margin, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError("margin must equal winning_score - second_score")
        object.__setattr__(self, "candidates", ordered)
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))
        object.__setattr__(self, "out_of_scope_score", float(self.out_of_scope_score))
        if self.winning_score is not None:
            object.__setattr__(self, "winning_score", float(self.winning_score))
        if self.second_score is not None:
            object.__setattr__(self, "second_score", float(self.second_score))
        if self.margin is not None:
            object.__setattr__(self, "margin", float(self.margin))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "winning_label": self.winning_label,
            "winning_score": self.winning_score,
            "second_label": self.second_label,
            "second_score": self.second_score,
            "margin": self.margin,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "suggested_source_scope": self.suggested_source_scope,
            "out_of_scope_score": self.out_of_scope_score,
            "requires_clarification": self.requires_clarification,
            "reason_codes": list(self.reason_codes),
            "model_version": self.model_version,
            "index_version": self.index_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class HybridIntentDecision:
    """Future fusion decision contract; Stage 2 does not create or consume it."""

    legacy_query_type: LegacyQueryType
    semantic_label: SemanticIntentLabel | None
    final_legacy_query_type: LegacyQueryType
    suggested_source_scope: SourceScopeLabel
    decision_source: DecisionSource
    hard_guard_triggered: bool
    out_of_scope: bool
    requires_clarification: bool
    confidence: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        _validate_label(self.legacy_query_type, semantic=False)
        _validate_label(self.final_legacy_query_type, semantic=False)
        if self.semantic_label is not None:
            _validate_label(self.semantic_label, semantic=True)
        _validate_scope(self.suggested_source_scope)
        if self.decision_source not in DECISION_SOURCES:
            raise ValueError(f"Unknown decision_source: {self.decision_source!r}")
        _validate_score("confidence", self.confidence)
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "reason_codes", _normalise_reason_codes(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_query_type": self.legacy_query_type,
            "semantic_label": self.semantic_label,
            "final_legacy_query_type": self.final_legacy_query_type,
            "suggested_source_scope": self.suggested_source_scope,
            "decision_source": self.decision_source,
            "hard_guard_triggered": self.hard_guard_triggered,
            "out_of_scope": self.out_of_scope,
            "requires_clarification": self.requires_clarification,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }
