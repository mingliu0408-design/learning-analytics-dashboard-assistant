"""ContextEnvelopeV1 construction with explicit scope and precedence."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from . import MAXIMUM_RECENT_TURNS


class ContextEnvelopeError(ValueError):
    pass


CONTEXT_SOURCE_WHITELIST = (
    "current_query",
    "current_page",
    "recent_relevant_conversation",
    "existing_structured_memory",
    "active_goal",
    "active_plan",
    "referenced_action",
    "explicit_constraint",
    "explicit_correction",
    "active_course_item",
)
INACTIVE_STATES = {"cancelled", "completed", "inactive", "replaced", "superseded"}
FORBIDDEN_CONTEXT_KEYS = {
    "student_name",
    "email",
    "firebase_id",
    "other_student_state",
    "dashboard_dataframe",
    "full_chat_history",
    "psychological_state",
    "inferred_stable_preference",
}


def normalise_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _active_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        status = str(value.get("status") or "active").casefold()
        if status in INACTIVE_STATES:
            return None
        return dict(value)
    return value if value not in (None, "", [], {}) else None


def _assert_safe_context(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in FORBIDDEN_CONTEXT_KEYS:
                raise ContextEnvelopeError(
                    "forbidden context field: " + ".".join((*path, str(key)))
                )
            _assert_safe_context(child, (*path, str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_safe_context(child, (*path, str(index)))
    elif hasattr(value, "columns") and hasattr(value, "to_dict"):
        raise ContextEnvelopeError("full tabular dashboard state is forbidden")


def _recent_relevant_turns(
    query: str,
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"[a-z0-9]+", normalise_query(query)))
    referential = bool(
        re.search(r"\b(?:it|that|this|second|third|previous|earlier|one)\b", normalise_query(query))
    )
    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(history):
        row = dict(raw)
        content = str(row.get("content") or "").strip()
        content_tokens = set(re.findall(r"[a-z0-9]+", normalise_query(content)))
        relevant = bool(row.get("relevant")) or bool(tokens & content_tokens) or referential
        if not relevant:
            continue
        rows.append(
            {
                "role": str(row.get("role") or "unknown"),
                "turn_order": int(row.get("turn_order", position)),
                "source": str(row.get("source") or "conversation"),
                "content": content,
                "explicit_goal": row.get("explicit_goal"),
                "explicit_constraint": row.get("explicit_constraint"),
                "correction": row.get("correction"),
                "referenced_items": list(row.get("referenced_items") or []),
            }
        )
    rows.sort(key=lambda item: item["turn_order"])
    return rows[-MAXIMUM_RECENT_TURNS:]


@dataclass(frozen=True)
class ContextEnvelopeV1:
    schema_version: str
    case_id: str
    original_query: str
    normalised_query: str
    resolved_query: str
    current_page: str
    recent_relevant_turns: tuple[Mapping[str, Any], ...]
    active_goal: Any
    active_plan: Any
    referenced_items: tuple[Any, ...]
    latest_correction: Any
    active_course_item: Any
    explicit_constraints: tuple[Any, ...]
    explicit_source_restrictions: tuple[str, ...]
    context_resolution_required: bool
    context_sources: tuple[str, ...]
    context_provenance: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if self.schema_version != "context-envelope-v1":
            raise ContextEnvelopeError("ContextEnvelopeV1 schema mismatch")
        if len(self.recent_relevant_turns) > MAXIMUM_RECENT_TURNS:
            raise ContextEnvelopeError("recent-turn maximum exceeded")
        if not set(self.context_sources) <= set(CONTEXT_SOURCE_WHITELIST):
            raise ContextEnvelopeError("context source outside whitelist")
        _assert_safe_context(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "recent_relevant_turns",
            "referenced_items",
            "explicit_constraints",
            "explicit_source_restrictions",
            "context_sources",
            "context_provenance",
        ):
            value[key] = list(value[key])
        return value


def build_context_envelope(
    *,
    case_id: str,
    original_query: str,
    current_page: str,
    conversation_history: Sequence[Mapping[str, Any]] = (),
    structured_memory: Mapping[str, Any] | None = None,
    explicit_constraints: Sequence[Any] = (),
    explicit_source_restrictions: Sequence[str] = (),
    context_resolution_required: bool = False,
) -> ContextEnvelopeV1:
    memory = dict(structured_memory or {})
    _assert_safe_context(memory)
    recent = _recent_relevant_turns(original_query, conversation_history)
    active_goal = _active_value(memory.get("active_goal"))
    active_plan = _active_value(memory.get("active_plan"))
    active_course_item = _active_value(memory.get("active_course_item"))
    constraints = [value for value in explicit_constraints if value not in (None, "")]
    referenced: list[Any] = []
    latest_correction: Any = None
    resolved_query = str(original_query).strip()

    for turn in recent:
        if turn.get("explicit_goal") not in (None, ""):
            active_goal = _active_value(turn["explicit_goal"])
        if turn.get("explicit_constraint") not in (None, ""):
            constraints.append(turn["explicit_constraint"])
        referenced.extend(turn.get("referenced_items") or [])
        correction = turn.get("correction")
        if correction not in (None, "", {}):
            latest_correction = correction

    if isinstance(latest_correction, Mapping):
        if latest_correction.get("cancel_goal") is True:
            active_goal = None
        if latest_correction.get("replacement_goal") not in (None, ""):
            active_goal = _active_value(latest_correction["replacement_goal"])
        if latest_correction.get("replacement_plan") not in (None, ""):
            active_plan = _active_value(latest_correction["replacement_plan"])
        if latest_correction.get("resolved_query") not in (None, ""):
            resolved_query = str(latest_correction["resolved_query"]).strip()

    sources = ["current_query", "current_page"]
    provenance: list[dict[str, Any]] = [
        {"source": "current_query", "precedence": 1},
        {"source": "current_page", "precedence": 1},
    ]
    if recent:
        sources.append("recent_relevant_conversation")
        provenance.append({"source": "recent_relevant_conversation", "turn_count": len(recent)})
    if memory:
        sources.append("existing_structured_memory")
        provenance.append({"source": "existing_structured_memory", "active_only": True})
    for source, value in (
        ("active_goal", active_goal),
        ("active_plan", active_plan),
        ("referenced_action", referenced),
        ("explicit_constraint", constraints),
        ("explicit_correction", latest_correction),
        ("active_course_item", active_course_item),
    ):
        if value not in (None, "", [], {}, ()):
            sources.append(source)
            provenance.append({"source": source, "active": True})

    return ContextEnvelopeV1(
        schema_version="context-envelope-v1",
        case_id=str(case_id),
        original_query=str(original_query).strip(),
        normalised_query=normalise_query(original_query),
        resolved_query=resolved_query,
        current_page=str(current_page),
        recent_relevant_turns=tuple(recent),
        active_goal=active_goal,
        active_plan=active_plan,
        referenced_items=tuple(referenced),
        latest_correction=latest_correction,
        active_course_item=active_course_item,
        explicit_constraints=tuple(constraints),
        explicit_source_restrictions=tuple(
            dict.fromkeys(str(value) for value in explicit_source_restrictions)
        ),
        context_resolution_required=bool(context_resolution_required),
        context_sources=tuple(dict.fromkeys(sources)),
        context_provenance=tuple(provenance),
    )


def context_envelope_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "context-envelope-schema-v1",
        "stage": "RQ2-A",
        "status": "FROZEN_RESEARCH_ONLY",
        "envelope_schema_version": "context-envelope-v1",
        "fields": [
            "schema_version",
            "case_id",
            "original_query",
            "normalised_query",
            "resolved_query",
            "current_page",
            "recent_relevant_turns",
            "active_goal",
            "active_plan",
            "referenced_items",
            "latest_correction",
            "active_course_item",
            "explicit_constraints",
            "explicit_source_restrictions",
            "context_resolution_required",
            "context_sources",
            "context_provenance",
        ],
        "maximum_recent_turns": MAXIMUM_RECENT_TURNS,
        "context_source_whitelist": list(CONTEXT_SOURCE_WHITELIST),
        "conflict_precedence": [
            "LATEST_EXPLICIT_STUDENT_CORRECTION",
            "LATEST_EXPLICIT_GOAL_OR_CONSTRAINT",
            "ACTIVE_STRUCTURED_STATE",
            "RECENT_RELEVANT_CONVERSATION",
            "OLDER_INACTIVE_STATE",
        ],
        "inactive_state_suppressed": True,
        "full_history_forbidden": True,
        "cross_student_context_forbidden": True,
        "full_dashboard_dataframe_forbidden": True,
        "context_resolution_is_independent_boolean": True,
        "working_context_is_predicted_capability": False,
    }
