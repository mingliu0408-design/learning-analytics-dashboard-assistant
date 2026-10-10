"""Compact, transparent R2V2-B0 multi-label rule baseline.

Inference uses only the four semantic inputs ``current_query``,
``current_page``, ``dashboard_context``, and
``visible_conversation_history``.  Compatibility-only context-state fields,
Gold, provenance, governance, proposed labels, and design rationales never
enter prediction logic.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2_v2_stage0.contracts import validate_case
from evaluation.capability_routing_rq2_v2_stage0.interfaces import RouterPrediction

from . import B0_MODEL_ID, PACKAGE_ROOT


DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "b0_rules_v1.json"


class B0ConfigError(ValueError):
    """Raised when the small B0 ruleset is missing or malformed."""


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _patterns(section: Mapping[str, Any], name: str) -> tuple[re.Pattern[str], ...]:
    raw = section.get(name)
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise B0ConfigError(f"B0 config field {name!r} must be a non-empty string list")
    try:
        return tuple(re.compile(item, re.IGNORECASE) for item in raw)
    except re.error as exc:
        raise B0ConfigError(f"invalid B0 regex in {name!r}: {exc}") from exc


def _matches(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


class B0RuleRouter:
    """Deterministic, independently triggered RAG/Memory/Planning rules."""

    model_id = B0_MODEL_ID

    def __init__(self, config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise B0ConfigError(f"cannot load B0 config: {self.config_path}") from exc
        if not isinstance(config, dict):
            raise B0ConfigError("B0 config must be a JSON object")
        if config.get("schema_version") != "rq2-v2-b0-rule-config-v1":
            raise B0ConfigError("unsupported B0 config schema")
        if config.get("ruleset_status") != "BASELINE_UNTUNED_NOT_EMPIRICALLY_FINAL":
            raise B0ConfigError("B0 ruleset must remain explicitly untuned")
        self.ruleset_id = str(config.get("ruleset_id") or "").strip()
        self.ruleset_status = str(config["ruleset_status"])
        if not self.ruleset_id:
            raise B0ConfigError("B0 ruleset_id must be non-empty")

        rag = config.get("rag")
        memory = config.get("memory")
        planning = config.get("planning")
        if not all(isinstance(value, dict) for value in (rag, memory, planning)):
            raise B0ConfigError("B0 config requires rag, memory, and planning objects")
        assert isinstance(rag, dict) and isinstance(memory, dict) and isinstance(planning, dict)

        self._rag_subject = _patterns(rag, "course_subject_patterns")
        self._rag_operation = _patterns(rag, "request_operation_patterns")
        self._rag_page_request = _patterns(rag, "page_context_request_patterns")
        self._rag_pages = frozenset(str(item) for item in rag.get("page_context_pages") or ())
        self._rag_supplied_context = _patterns(
            rag, "content_already_supplied_context_patterns"
        )
        if not self._rag_pages:
            raise B0ConfigError("B0 RAG page list must be non-empty")

        self._memory_reference = _patterns(memory, "long_term_reference_patterns")
        self._memory_personal = _patterns(memory, "personal_reference_patterns")
        self._memory_current_resolution = _patterns(
            memory, "current_query_resolution_patterns"
        )
        self._memory_generic_history = _patterns(
            memory, "generic_history_reference_patterns"
        )
        self._memory_concrete_context = _patterns(memory, "concrete_context_patterns")
        self._memory_unresolved_context = _patterns(
            memory, "unresolved_context_patterns"
        )
        topics = memory.get("reference_topics")
        if not isinstance(topics, list) or not topics:
            raise B0ConfigError("B0 memory reference_topics must be non-empty")
        self._memory_topics = tuple(_normalise(item) for item in topics)

        self._planning_request = _patterns(planning, "request_patterns")

    def _history_resolves_reference(
        self,
        query: str,
        history: Sequence[Mapping[str, Any]],
    ) -> bool:
        user_history = " ".join(
            _normalise(turn.get("content"))
            for turn in history
            if str(turn.get("role")) == "user"
        )
        if not user_history:
            return False
        query_topics = tuple(topic for topic in self._memory_topics if topic in query)
        if query_topics and any(topic in user_history for topic in query_topics):
            return True
        return _matches(query, self._memory_generic_history)

    def _dashboard_resolves_reference(self, query: str, dashboard: str) -> bool:
        if (
            not dashboard
            or _matches(dashboard, self._memory_unresolved_context)
            or not _matches(dashboard, self._memory_concrete_context)
        ):
            return False
        query_topics = tuple(topic for topic in self._memory_topics if topic in query)
        return bool(query_topics and any(topic in dashboard for topic in query_topics))

    def predict(self, case: Mapping[str, Any]) -> RouterPrediction:
        validate_case(case)
        # This is the deliberate inference boundary.  Context-state fields may
        # remain in the Stage 0 schema, but are not read by B0 prediction logic.
        model_input = case["model_input"]
        query = _normalise(model_input["current_query"])
        current_page = str(model_input["current_page"])
        dashboard = _normalise(model_input["dashboard_context"])
        history = tuple(model_input["visible_conversation_history"])

        matched: list[str] = []
        suppressed: list[str] = []

        rag_subject = _matches(query, self._rag_subject)
        rag_operation = _matches(query, self._rag_operation)
        rag_page_context = current_page in self._rag_pages and _matches(
            query, self._rag_page_request
        )
        rag_candidate = rag_subject and (rag_operation or rag_page_context)
        rag_supplied = _matches(dashboard, self._rag_supplied_context)
        rag_required = bool(rag_candidate and not rag_supplied)
        if rag_candidate:
            matched.append(
                "B0_RAG_PAGE_CONTEXT_REQUEST"
                if rag_page_context and not rag_operation
                else "B0_RAG_COURSE_REQUEST"
            )
        if rag_candidate and rag_supplied:
            suppressed.append("B0_RAG_CONTENT_ALREADY_PROVIDED")

        long_term_reference = _matches(query, self._memory_reference)
        personal_reference = _matches(query, self._memory_personal)
        current_query_resolves = _matches(query, self._memory_current_resolution)
        visible_history_resolves = self._history_resolves_reference(query, history)
        dashboard_resolves = self._dashboard_resolves_reference(query, dashboard)
        memory_candidate = long_term_reference and personal_reference
        memory_required = bool(
            memory_candidate
            and not current_query_resolves
            and not visible_history_resolves
            and not dashboard_resolves
        )
        if memory_candidate:
            matched.append("B0_MEMORY_LONG_TERM_PERSONAL_REFERENCE")
        if memory_candidate and current_query_resolves:
            suppressed.append("B0_MEMORY_DETAIL_IN_CURRENT_QUERY")
        if memory_candidate and visible_history_resolves:
            suppressed.append("B0_MEMORY_DETAIL_IN_VISIBLE_HISTORY")
        if memory_candidate and dashboard_resolves:
            suppressed.append("B0_MEMORY_DETAIL_IN_DASHBOARD_CONTEXT")

        planning_required = _matches(query, self._planning_request)
        if planning_required:
            matched.append("B0_PLANNING_ACTIONABLE_REQUEST")

        return RouterPrediction(
            case_id=str(case["case_id"]),
            model_id=self.model_id,
            dialogue_action="ANSWER",
            rag_required=rag_required,
            memory_required=memory_required,
            planning_required=planning_required,
            metadata={
                "execution_mode": "LOCAL_DETERMINISTIC_RULE_BASELINE",
                "provider_call_count": 0,
                "network_access": False,
                "training_performed": False,
                "ruleset_id": self.ruleset_id,
                "ruleset_status": self.ruleset_status,
                "matched_rule_ids": sorted(set(matched)),
                "suppressed_rule_ids": sorted(set(suppressed)),
                "model_visible_fields_used": [
                    "current_query",
                    "current_page",
                    "dashboard_context",
                    "visible_conversation_history",
                ],
            },
        )


__all__ = ["B0ConfigError", "B0RuleRouter", "DEFAULT_CONFIG_PATH"]
