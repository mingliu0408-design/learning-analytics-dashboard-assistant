"""Pure helpers for the feature-flagged Streamlit C4 research scaffold.

This module intentionally does not import Streamlit.  The page remains the UI
owner while this adapter keeps request construction testable and ensures that
UI and headless replay both call :class:`C4RealService`.
"""

from __future__ import annotations

import os
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from utils.c4_real_contracts import C4Mode, C4RealRequest, C4RealResult, ExecutionContext
from utils.c4_real_service import C4RealService


RESEARCH_MODE_LABELS: Mapping[str, C4Mode] = MappingProxyType(
    {
        "Original": C4Mode.C0_ORIGINAL,
        "Evidence": C4Mode.C1_EVIDENCE,
        "Evidence + RAG": C4Mode.C2_EVIDENCE_RAG,
        "Evidence + Memory": C4Mode.C3_EVIDENCE_MEMORY,
        "Evidence + Planning": C4Mode.C4_EVIDENCE_PLANNING,
        "Full C4": C4Mode.C5_FULL_C4,
    }
)
RESEARCH_PLACEHOLDER_REPLY = (
    "C4 research orchestration completed. Real response generation is disabled in Track S."
)


def research_mode_enabled(
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> bool:
    """Return false unless the feature flag is explicitly truthy."""

    environment = os.environ if environ is None else environ
    raw: Any = environment.get("ENABLE_C4_REAL_RESEARCH_MODE")
    if raw is None and secrets is not None:
        try:
            raw = secrets.get("ENABLE_C4_REAL_RESEARCH_MODE")
        except Exception:
            raw = None
    return str(raw or "").strip().casefold() in {"1", "true", "yes", "on"}


def visible_history(messages: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], ...]:
    """Project a transcript onto the frozen visible role/content representation."""

    return tuple(
        {
            "role": str(message.get("role", "")),
            "content": str(message.get("content", "")),
        }
        for message in messages
        if message.get("visible", True)
        and message.get("role") in {"user", "assistant"}
    )


def research_scope_key(session_id: str, mode: C4Mode | str) -> str:
    """Keep the visible transcript separated by research condition."""

    if not str(session_id or "").strip():
        raise ValueError("session_id must be non-empty")
    return f"{session_id}::{C4Mode(mode).value}"


def build_streamlit_c4_request(
    *,
    request_id: str,
    scenario_id: str,
    mode: C4Mode | str,
    current_query: str,
    current_page: str,
    dashboard_context: Any,
    messages: Sequence[Mapping[str, Any]],
    student_id: str,
    session_id: str,
    state_reset_id: str,
) -> C4RealRequest:
    return C4RealRequest(
        request_id=request_id,
        scenario_id=scenario_id,
        mode=C4Mode(mode),
        current_query=current_query,
        current_page=current_page,
        dashboard_context=dashboard_context,
        visible_conversation_history=visible_history(messages),
        student_id=student_id,
        session_id=session_id,
        state_reset_id=state_reset_id,
        execution_context=ExecutionContext.INTERACTIVE,
    )


def run_streamlit_c4_turn(
    service: C4RealService, request: C4RealRequest
) -> C4RealResult:
    """The sole research-mode UI execution hook."""

    if not isinstance(service, C4RealService):
        raise TypeError("The Streamlit C4 hook requires a C4RealService instance")
    return service.execute(request)


def streamlit_reply(result: C4RealResult) -> str:
    """Never invent an answer when the Track-S mock generator is suppressed."""

    if not result.success:
        return "C4 research orchestration failed; inspect the safe trace."
    if result.output is None or not result.output.text.strip():
        return RESEARCH_PLACEHOLDER_REPLY
    return result.output.text
