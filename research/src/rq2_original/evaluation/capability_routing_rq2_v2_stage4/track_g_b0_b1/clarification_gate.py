"""Deterministic shared clarification gate for RQ2-V2 Stage 4G.

Only the four frozen primary semantic fields enter prediction. Identifiers,
folds, grouping metadata, Gold, and writer metadata are deliberately absent
from this module's inference interface.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence


ALLOWED_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "before",
        "better",
        "can",
        "course",
        "does",
        "from",
        "have",
        "here",
        "into",
        "make",
        "mentioned",
        "next",
        "only",
        "should",
        "that",
        "these",
        "this",
        "those",
        "what",
        "when",
        "which",
        "with",
        "would",
        "your",
    }
)


class ClarificationConfigError(ValueError):
    """Raised when the frozen candidate contract is malformed."""


@dataclass(frozen=True)
class ClarificationPrediction:
    dialogue_action: str
    matched_clause: str
    unresolved_reference: bool
    plausible_visible_targets: int
    explicit_selection: bool
    explicitly_unselected: bool
    history_resolved: bool
    activity_unidentified: bool
    deadline_unidentified: bool


def _patterns(raw: Any, name: str) -> tuple[re.Pattern[str], ...]:
    if not isinstance(raw, list) or not raw or not all(isinstance(x, str) for x in raw):
        raise ClarificationConfigError(f"{name} must be a non-empty string list")
    try:
        return tuple(re.compile(value, re.IGNORECASE) for value in raw)
    except re.error as exc:
        raise ClarificationConfigError(f"invalid regex in {name}: {exc}") from exc


def _matches(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _history(value: Any) -> tuple[dict[str, str], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ClarificationConfigError("visible history is not valid JSON") from exc
    if not isinstance(value, list):
        raise ClarificationConfigError("visible history must be a list")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ClarificationConfigError("visible history entries must be objects")
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            raise ClarificationConfigError("visible history entries are malformed")
        rows.append({"role": role, "content": content})
    return tuple(rows)


def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _TOKEN.findall(text)
        if len(token) >= 4 and token.casefold() not in _STOPWORDS
    )


def _history_resolves(query: str, history: Sequence[Mapping[str, str]]) -> bool:
    query_tokens = _content_tokens(query)
    if not query_tokens:
        return False
    user_text = " ".join(
        str(turn.get("content") or "")
        for turn in history
        if str(turn.get("role") or "") == "user"
    )
    return bool(query_tokens.intersection(_content_tokens(user_text)))


def _plausible_target_count(dashboard: str) -> int:
    """Estimate a visible-target lower bound using generic display markers."""

    counts = [0]
    counts.append(len(set(re.findall(r"\bweek\s+(\d+)\b", dashboard, re.IGNORECASE))))
    counts.append(len(set(re.findall(r"\blecture\s+(\d+)\b", dashboard, re.IGNORECASE))))
    counts.append(
        len(
            set(
                re.findall(
                    r"\b\d+(?:\.\d+)?\s*(?:%|percentage(?:\s+points?)?)",
                    dashboard,
                    re.IGNORECASE,
                )
            )
        )
    )
    number_words = {"two": 2, "three": 3, "four": 4, "five": 5}
    for word, value in number_words.items():
        if re.search(rf"\b{word}\b", dashboard, re.IGNORECASE):
            counts.append(value)
    if re.search(r"\b(?:both|multiple|simultaneously)\b", dashboard, re.IGNORECASE):
        counts.append(2)
    return max(counts)


class ClarificationGate:
    """Apply one of the immutable candidate configurations."""

    def __init__(self, candidate_payload: Mapping[str, Any]) -> None:
        if candidate_payload.get("schema_version") != "rq2-v2-stage4g-clarification-candidates-v1":
            raise ClarificationConfigError("unsupported clarification candidate schema")
        if candidate_payload.get("candidate_status") != "FROZEN_PREDECLARED_BEFORE_DEV_SCORING":
            raise ClarificationConfigError("clarification candidates are not predeclared")
        if candidate_payload.get("performance_metrics_calculated_at_declaration") is not False:
            raise ClarificationConfigError("candidate declaration already contains performance")
        lexical = candidate_payload.get("shared_lexical_contract")
        if not isinstance(lexical, dict):
            raise ClarificationConfigError("shared lexical contract is missing")
        self._reference = _patterns(
            lexical.get("unresolved_reference_patterns"), "unresolved_reference_patterns"
        )
        self._temporal = _patterns(
            lexical.get("temporal_reference_patterns"), "temporal_reference_patterns"
        )
        self._selected = _patterns(
            lexical.get("explicit_selection_patterns"), "explicit_selection_patterns"
        )
        self._unselected = _patterns(
            lexical.get("explicitly_unselected_patterns"), "explicitly_unselected_patterns"
        )
        self._activity = _patterns(
            lexical.get("activity_identity_patterns"), "activity_identity_patterns"
        )
        self._deadline = _patterns(
            lexical.get("deadline_identity_patterns"), "deadline_identity_patterns"
        )
        raw_candidates = candidate_payload.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ClarificationConfigError("candidate list is missing")
        self.candidates: dict[str, dict[str, Any]] = {}
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                raise ClarificationConfigError("candidate entries must be objects")
            config_id = str(raw.get("config_id") or "")
            if not config_id or config_id in self.candidates:
                raise ClarificationConfigError("candidate IDs must be non-empty and unique")
            self.candidates[config_id] = dict(raw)

    def predict(self, semantic_input: Mapping[str, Any], config_id: str) -> ClarificationPrediction:
        if set(semantic_input) != set(ALLOWED_FIELDS):
            raise ClarificationConfigError(
                "clarification inference requires exactly the four allowed semantic fields"
            )
        try:
            config = self.candidates[config_id]
        except KeyError as exc:
            raise ClarificationConfigError(f"unknown clarification config: {config_id}") from exc
        query = _normalise(semantic_input["current_query"])
        page = str(semantic_input["current_page"])
        dashboard = _normalise(semantic_input["dashboard_context"])
        history = _history(semantic_input["visible_conversation_history"])
        if not query or page not in {"Overview", "Resources", "Lecture", "Debate", "Reflection", "Other"}:
            raise ClarificationConfigError("semantic input has an invalid query or page")

        unresolved_reference = _matches(query, self._reference)
        temporal_reference = _matches(query, self._temporal)
        explicitly_unselected = _matches(dashboard, self._unselected)
        explicit_selection = _matches(dashboard, self._selected) and not explicitly_unselected
        plausible_targets = _plausible_target_count(dashboard)
        history_resolved = _history_resolves(query, history)
        combined = " ".join(
            [query, dashboard]
            + [_normalise(turn["content"]) for turn in history if turn["role"] == "user"]
        )
        activity_unidentified = not _matches(combined, self._activity)
        deadline_unidentified = not _matches(combined, self._deadline)

        reference = config.get("reference_clause") or {}
        temporal = config.get("temporal_clause") or {}
        reference_match = bool(
            reference.get("enabled")
            and unresolved_reference
            and plausible_targets >= int(reference.get("min_plausible_visible_targets", 0))
            and (not reference.get("require_explicitly_unselected") or explicitly_unselected)
            and (not reference.get("require_no_explicit_selection") or not explicit_selection)
            and (not reference.get("require_history_unresolved") or not history_resolved)
        )
        temporal_match = bool(
            temporal.get("enabled")
            and temporal_reference
            and (not temporal.get("require_activity_unidentified") or activity_unidentified)
            and (not temporal.get("require_deadline_unidentified") or deadline_unidentified)
        )
        if reference_match:
            action, clause = "CLARIFY", "UNRESOLVED_REFERENCE_MULTI_TARGET"
        elif temporal_match:
            action, clause = "CLARIFY", "UNRESOLVED_ACTIVITY_AND_DEADLINE"
        else:
            action, clause = "ANSWER", "NO_CLARIFICATION_TRIGGER"
        return ClarificationPrediction(
            dialogue_action=action,
            matched_clause=clause,
            unresolved_reference=unresolved_reference,
            plausible_visible_targets=plausible_targets,
            explicit_selection=explicit_selection,
            explicitly_unselected=explicitly_unselected,
            history_resolved=history_resolved,
            activity_unidentified=activity_unidentified,
            deadline_unidentified=deadline_unidentified,
        )


__all__ = [
    "ALLOWED_FIELDS",
    "ClarificationConfigError",
    "ClarificationGate",
    "ClarificationPrediction",
]
