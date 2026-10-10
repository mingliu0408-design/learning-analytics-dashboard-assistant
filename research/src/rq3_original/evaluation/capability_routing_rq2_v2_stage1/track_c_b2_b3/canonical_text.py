"""Canonical, model-visible-only text representation shared by B2 and B3."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
import unicodedata
from typing import Any

from .errors import CanonicalInputError


SERIALIZER_VERSION = "rq2-v2-track-c-canonical-text-v2"
PRIMARY_FEATURE_PROFILE = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
PRIMARY_FEATURE_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
NON_FEATURE_METADATA_FIELDS = (
    "rag_context_state",
    "memory_context_state",
)

MODEL_INPUT_FIELDS = frozenset(
    {*PRIMARY_FEATURE_FIELDS, *NON_FEATURE_METADATA_FIELDS}
)
CANONICAL_PAGES = frozenset(
    {"Overview", "Resources", "Lecture", "Debate", "Reflection", "Other"}
)
RAG_CONTEXT_STATES = frozenset(
    {
        "PROVIDED_IN_INPUT",
        "RETRIEVAL_AVAILABLE",
        "RETRIEVAL_UNAVAILABLE",
        "UNKNOWN",
    }
)
MEMORY_CONTEXT_STATES = frozenset(
    {
        "VISIBLE_HISTORY_ONLY",
        "LONG_TERM_MEMORY_AVAILABLE",
        "LONG_TERM_MEMORY_UNAVAILABLE",
        "UNKNOWN",
    }
)


def _normalise_visible_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanonicalInputError(f"{field} must be a string")
    normalised = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace(
        "\r", "\n"
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalised.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = is_blank
    return "\n".join(compact)


def validate_model_input(model_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate Stage 0 input, including non-feature context-state metadata."""

    if not isinstance(model_input, Mapping):
        raise CanonicalInputError("model_input must be a mapping")
    unknown = sorted(str(key) for key in set(model_input) - MODEL_INPUT_FIELDS)
    if unknown:
        raise CanonicalInputError(
            "model_input contains non-canonical fields: " + ", ".join(unknown)
        )
    query = _normalise_visible_text(
        model_input.get("current_query"), field="model_input.current_query"
    )
    if not query:
        raise CanonicalInputError("model_input.current_query must be non-empty")

    validated: dict[str, Any] = {"current_query": query}
    if "current_page" in model_input and model_input["current_page"] is not None:
        page = _normalise_visible_text(
            model_input["current_page"], field="model_input.current_page"
        )
        if page not in CANONICAL_PAGES:
            raise CanonicalInputError(f"unsupported current_page: {page!r}")
        validated["current_page"] = page

    if "dashboard_context" in model_input and model_input["dashboard_context"] is not None:
        dashboard = _normalise_visible_text(
            model_input["dashboard_context"],
            field="model_input.dashboard_context",
        )
        if dashboard:
            validated["dashboard_context"] = dashboard

    history_value = model_input.get("visible_conversation_history")
    if history_value is not None:
        if isinstance(history_value, (str, bytes)) or not isinstance(
            history_value, Sequence
        ):
            raise CanonicalInputError(
                "model_input.visible_conversation_history must be a sequence"
            )
        history: list[dict[str, str]] = []
        for index, turn in enumerate(history_value):
            if not isinstance(turn, Mapping):
                raise CanonicalInputError(f"history turn {index} must be a mapping")
            if set(turn) != {"role", "content"}:
                raise CanonicalInputError(
                    f"history turn {index} must contain only role and content"
                )
            role = str(turn["role"])
            if role not in {"user", "assistant"}:
                raise CanonicalInputError(f"unsupported history role: {role!r}")
            content = _normalise_visible_text(
                turn["content"], field=f"history[{index}].content"
            )
            if not content:
                raise CanonicalInputError(f"history turn {index} content is empty")
            history.append({"role": role, "content": content})
        if history:
            validated["visible_conversation_history"] = history

    if "rag_context_state" in model_input and model_input["rag_context_state"] is not None:
        state = str(model_input["rag_context_state"])
        if state not in RAG_CONTEXT_STATES:
            raise CanonicalInputError(f"unsupported rag_context_state: {state!r}")
        validated["rag_context_state"] = state

    if (
        "memory_context_state" in model_input
        and model_input["memory_context_state"] is not None
    ):
        state = str(model_input["memory_context_state"])
        if state not in MEMORY_CONTEXT_STATES:
            raise CanonicalInputError(f"unsupported memory_context_state: {state!r}")
        validated["memory_context_state"] = state
    return validated


def serialize_canonical_text(case: Mapping[str, Any]) -> str:
    """Serialize the four fields in ``R2V2_PRIMARY_SEMANTIC_INPUT_V1``.

    RAG/Memory context-state values remain validated Stage 0 metadata but are
    deliberately not features. Gold, labels, rationale, governance, and all
    other top-level fields are never inspected. Absent or empty optional
    semantic sections are omitted.
    """

    if not isinstance(case, Mapping):
        raise CanonicalInputError("case must be a mapping")
    model_input = validate_model_input(case.get("model_input"))
    sections = [f"[CURRENT_QUERY]\n{model_input['current_query']}"]
    if "current_page" in model_input:
        sections.append(f"[CURRENT_PAGE]\n{model_input['current_page']}")
    if "dashboard_context" in model_input:
        sections.append(f"[DASHBOARD_CONTEXT]\n{model_input['dashboard_context']}")
    if "visible_conversation_history" in model_input:
        turns = [
            f"[TURN_{index:03d}_{turn['role'].upper()}]\n{turn['content']}"
            for index, turn in enumerate(
                model_input["visible_conversation_history"], start=1
            )
        ]
        sections.append("[VISIBLE_CONVERSATION_HISTORY]\n" + "\n".join(turns))
    return "\n\n".join(sections)


def serialize_canonical_batch(cases: Sequence[Mapping[str, Any]]) -> list[str]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise CanonicalInputError("cases must be a sequence of mappings")
    if not cases:
        raise CanonicalInputError("cases must not be empty")
    return [serialize_canonical_text(case) for case in cases]
