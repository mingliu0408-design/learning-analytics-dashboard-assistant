"""Short-term, rule-based conversation memory helpers.

This module resolves context-dependent follow-up questions from recent
conversation turns only. It does not persist memory, build user profiles, use
embeddings, or call external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Mapping, Sequence


MAX_SESSION_MEMORY_MESSAGES = 12
NEUTRAL_CHAT_OPENER = "Hi there! What would you like help understanding?"


@dataclass(frozen=True)
class MemoryResolution:
    """Result of resolving a context-dependent follow-up query."""

    is_follow_up: bool
    resolved: bool
    original_query: str
    resolved_query: str
    referenced_items: list[dict[str, str]] = field(default_factory=list)
    memory_context: dict[str, Any] = field(default_factory=dict)
    structured_state: dict[str, Any] = field(default_factory=dict)
    resolution_type: str = ""
    reason: str = ""


@dataclass(frozen=True)
class MemoryRuntimeResult:
    """Canonical Mode CM memory preparation result shared by all runtimes."""

    original_query: str
    resolved_query: str
    memory_triggered: bool
    memory_resolved: bool
    memory_resolution_type: str
    numbered_reference_resolved: bool
    referenced_items: list[dict[str, str]] = field(default_factory=list)
    structured_memory: dict[str, Any] = field(default_factory=dict)
    formatted_memory_context: str = ""
    memory_updates: dict[str, Any] = field(default_factory=dict)
    memory_resolution: MemoryResolution | None = None

    def metadata(self) -> dict[str, Any]:
        """Expose transparent memory metadata for evaluation and debugging."""

        state = self.structured_memory
        resolution_context = (self.memory_resolution.memory_context if self.memory_resolution else {}) or {}
        active_plan = state.get("active_plan") or {}
        active_course_item = state.get("active_course_item") or {}
        completion_state_injected = bool(
            resolution_context.get("completion_reference_resolved")
            or (
                self.memory_resolution_type == "memory_state_query"
                and resolution_context.get("memory_state_query_subtype") == "completed_actions"
                and resolution_context.get("memory_state_value")
            )
            or self.memory_resolution_type == "structured_session_state"
        )
        return {
            "memory_triggered": self.memory_triggered,
            "memory_resolved": self.memory_resolved,
            "memory_used": self.memory_resolved,
            "memory_resolution_type": self.memory_resolution_type,
            "numbered_reference_resolved": self.numbered_reference_resolved,
            "numbered_reference_kind": resolution_context.get("numbered_reference_kind", ""),
            "active_plan_updated": bool(self.memory_updates.get("active_plan_updated")),
            "referenced_items": self.referenced_items,
            "active_goal_used": bool(self.memory_resolved and state.get("active_goal")),
            "constraints_used": bool(self.memory_resolved and state.get("constraints")),
            "completed_actions_used": bool(
                self.memory_resolved and completion_state_injected
            ),
            "corrections_applied": bool(
                self.memory_resolved and state.get("corrections")
            ),
            "memory_fields_updated": list(self.memory_updates.get("updated_fields", [])),
            "resolved_query": self.resolved_query if self.memory_resolved else "",
            "active_plan": active_plan,
            "completed_steps": list(active_plan.get("completed_steps") or []),
            "pending_steps": list(active_plan.get("pending_steps") or []),
            "next_pending_step": active_plan.get("next_pending_step"),
            "active_plan_complete": bool(active_plan.get("active_plan_complete")),
            "completion_reference_resolved": bool(
                resolution_context.get("completion_reference_resolved")
            ),
            "active_course_item": active_course_item,
            "course_reference_triggered": bool(resolution_context.get("course_reference_triggered")),
            "course_reference_resolved": bool(resolution_context.get("course_reference_resolved")),
            "resolved_course_entity": resolution_context.get("resolved_course_entity") or {},
            "memory_state_query_subtype": resolution_context.get("memory_state_query_subtype", ""),
            "plan_memory_intent": resolution_context.get("plan_memory_intent", ""),
            "plan_revision_requested": bool(
                resolution_context.get("plan_revision_requested")
            ),
            "memory_context_available": _memory_context_available(state),
            "memory_context_injected": bool(self.memory_resolved and _memory_context_available(state)),
            "memory_reference_triggered": self.memory_triggered,
            "memory_reference_resolved": self.memory_resolved,
            "active_goal_available": bool(state.get("active_goal")),
            "active_goal_injected": bool(self.memory_resolved and state.get("active_goal")),
            "constraints_available": bool(state.get("constraints")),
            "constraints_injected": bool(self.memory_resolved and state.get("constraints")),
            "completed_actions_available": bool(state.get("completed_actions") or active_plan.get("completed_steps")),
            "completed_actions_injected": bool(
                self.memory_resolved and completion_state_injected
            ),
        }


ORDINAL_TO_NUMBER = {
    "one": 1,
    "first": 1,
    "1st": 1,
    "two": 2,
    "second": 2,
    "2nd": 2,
    "three": 3,
    "third": 3,
    "3rd": 3,
    "four": 4,
    "fourth": 4,
    "4th": 4,
    "five": 5,
    "fifth": 5,
    "5th": 5,
}

PLAN_ITEM_NOUN_PATTERN = r"(?:step|action|item|task|point|recommendation)"
PLAN_NUMBER_PATTERN = (
    r"(?:\d{1,2}|one|two|three|four|five|first|second|third|fourth|fifth|"
    r"1st|2nd|3rd|4th|5th)"
)

EXPLICIT_REFERENCE_RE = re.compile(
    r"\b(?:item|point|number|step)\s*(\d{1,2})\b"
    r"|(?:\b(?:do|doing|suggest|try|explain|expand|about|on|for)\b[^\n]{0,40}?\b(\d{1,2})(?:\s*(?:and|&|,)\s*(\d{1,2}))*\b)"
    r"|^\s*(\d{1,2})(?:\s*(?:and|&|,)\s*(\d{1,2}))*\s*$",
    flags=re.IGNORECASE,
)

FOLLOW_UP_PATTERNS = (
    rf"\b{PLAN_ITEM_NOUN_PATTERN}(?:\s+number)?\s*{PLAN_NUMBER_PATTERN}\b",
    rf"\b{PLAN_NUMBER_PATTERN}\s+{PLAN_ITEM_NOUN_PATTERN}\b",
    r"\b\d{1,2}\s*(?:and|&|,)\s*\d{1,2}\b",
    r"^\s*(?:do\s*)?\d{1,2}\s*(?:and|&|,)\s*\d{1,2}\s*$",
    r"\b(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+(?:one|point|item|step)\b",
    r"\b(?:those steps|these steps|the previous suggestion|previous suggestion|previous point|above suggestion|last suggestion)\b",
    r"\b(?:this|that)\s+(?:one|point|step|item|recommendation)\b",
    r"\bexpand on\b",
    r"\bwhat about\b",
    r"\bhow should i do\b",
    r"\b(?:continue|carry on|pick up)\b.*\b(?:plan|goal|step|where we left off)\b",
    r"\b(?:the|our|my)\s+(?:plan|goal)\s+(?:we|you|i)\b",
    r"\b(?:same goal|what should i do next|what do i do next|what next|next after that)\b",
    r"\b(?:i(?:'ve| have)?\s+)?(?:finished|completed|done|watched|reviewed|read|submitted|replied|wrote)\b.*\b(?:next|now)\b",
    r"\b(?:as i said|as we discussed|based on what we planned|use the plan we made)\b",
    r"\b(?:where can i find it|what we covered|that week|the previous material|the material)\b",
    r"\bactually\b.{0,80}\b(?:meant|week\s*\d+|w\d+)\b",
)
P2A_FOLLOW_UP_PATTERNS = (
    r"\b(?:remind me what (?:the )?next action involves|what comes next)\b",
    r"\b(?:correction|i meant|i was referring to|rather than)\b.{0,100}\b(?:week\s*\d+|w\d+)\b",
)

GOAL_RE = re.compile(
    r"\b(?:my goal is|i(?:'d| would)? like to|i want to|i need to|i(?:'m| am) trying to|i still want to)\b",
    flags=re.IGNORECASE,
)
CONSTRAINT_RE = re.compile(
    r"\b(?:i (?:only )?have\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an)\s*(?:minutes?|mins?|hours?|days?|hour)|"
    r"if i (?:only )?have\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an)\s*(?:minutes?|mins?|hours?|days?|hour)|"
    r"i can only spend\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an)\s*(?:minutes?|mins?|hours?|days?|hour)|"
    r"i only have\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an)\s*(?:minutes?|mins?|hours?|days?|hour)|"
    r"only\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an)\s*(?:minutes?|mins?|hours?|days?|hour)|i can(?:not|'t)|i am unable|i'm unable|"
    r"i(?:'m| am) busy|before (?:the )?deadline|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    flags=re.IGNORECASE,
)
COMPLETION_RE = re.compile(
    r"\b(?:i(?:'ve| have)?\s+)?(?:finished|completed|done|watched|reviewed|read|submitted|replied|wrote|caught up)\b",
    flags=re.IGNORECASE,
)
CORRECTION_RE = re.compile(
    r"\b(?:actually|i meant|not\s+[^,.!?;]{1,60}\s+but|rather than)\b",
    flags=re.IGNORECASE,
)
COMMITTED_ACTION_RE = re.compile(
    r"\b(?:i(?:'ll| will)|i(?:'m| am) going to|i plan to|i chose|i choose)\b",
    flags=re.IGNORECASE,
)
STRUCTURED_CONTINUITY_RE = re.compile(
    r"\b(?:what should i do next|what do i do next|what next|next after that|same goal|"
    r"continue (?:the|our|my)|carry on|pick up where we left off|our plan|plan we made|"
    r"as we discussed|as i said|remind me what (?:the )?next action involves|"
    r"i(?:'ve| have)? (?:finished|completed|done|watched|reviewed|read|submitted|replied|wrote))\b",
    flags=re.IGNORECASE,
)
BASELINE_STRUCTURED_CONTINUITY_RE = re.compile(
    r"\b(?:what should i do next|what do i do next|what next|next after that|same goal|"
    r"continue (?:the|our|my)|carry on|pick up where we left off|our plan|plan we made|"
    r"as we discussed|as i said|"
    r"i(?:'ve| have)? (?:finished|completed|done|watched|reviewed|read|submitted|replied|wrote))\b",
    flags=re.IGNORECASE,
)

MEMORY_STATE_PATTERNS = {
    "active_plan": (
        r"\bwhat was the plan i just agreed to\b|\bwhat is my active plan\b|"
        r"\bremind me of my plan\b|\bwhat plan did we make\b|"
        r"\bshow me the current plan\b|"
        r"\b(?:(?:can|could) you\s+)?show (?:me\s+)?(?:that|the|my) plan(?: again)?\b|"
        r"\b(?:(?:can|could) you\s+)?repeat (?:that|the|my) plan\b|"
        r"\bremind me what i need to do\b|"
        r"\b(?:go over|go through|walk me through) (?:that|the|my) plan again\b|"
        r"\bwhat were the actions again\b|\bwhat am i supposed to do again\b|"
        r"\bwhat (?:routine|schedule|strategy) did you (?:just )?(?:set|suggest|give) (?:for )?me\b"
    ),
    "current_goal": (
        r"\b(?:what is|what's|remind me of)\s+my\s+(?:current\s+)?goal\b|\bcurrent goal\b|"
        r"\bwhat goal am i (?:currently )?working (?:toward|towards)\b"
    ),
    "current_constraints": r"\b(?:what|which).*(?:constraint|time limit|time constraint)\b|\bexact time constraint\b",
    "selected_actions": r"\b(?:what|which).*(?:actions?|steps?).*(?:selected|planned|choose|chose)\b",
    "completed_actions": r"\b(?:what|which).*(?:actions?|steps?).*(?:completed|finished|done)\b|\bcompleted so far\b",
    "next_plan_step": r"\b(?:what is|what's)\s+(?:my\s+)?next\s+(?:plan\s+)?step\b",
    "previous_correction": r"\b(?:what|which).*(?:previous|latest|last)\s+correction\b",
    "current_course_item": (
        r"\b(?:what|which)\s+(?:lecture(?:\s+week)?|reading|course\s+item|assessment)\b"
        r"[^?]{0,100}\b(?:did\s+i\s+(?:say|mention|choose|select|plan)|"
        r"was\s+i\s+referring\s+to|i\s+(?:said|mentioned|chose|selected|planned|referred\s+to))\b"
        r"|\b(?:what|which).*\b(?:current|selected|previous)\s+(?:reading|lecture|course\s+item|assessment)\b|"
        r"\bwhich lecture week is my .{0,80}goal about\b"
    ),
}
BASELINE_MEMORY_STATE_PATTERNS = {
    **MEMORY_STATE_PATTERNS,
    "active_plan": (
        r"\bwhat was the plan i just agreed to\b|\bwhat is my active plan\b|"
        r"\bremind me of my plan\b|\bwhat plan did we make\b|"
        r"\bshow me the current plan\b|"
        r"\b(?:(?:can|could) you\s+)?show (?:me\s+)?(?:that|the|my) plan(?: again)?\b|"
        r"\b(?:(?:can|could) you\s+)?repeat (?:that|the|my) plan\b|"
        r"\bremind me what i need to do\b|"
        r"\b(?:go over|go through|walk me through) (?:that|the|my) plan again\b|"
        r"\bwhat were the actions again\b|\bwhat am i supposed to do again\b"
    ),
    "current_goal": r"\b(?:what is|what's|remind me of)\s+my\s+(?:current\s+)?goal\b|\bcurrent goal\b",
    "current_course_item": (
        r"\b(?:what|which)\s+(?:lecture(?:\s+week)?|reading|course\s+item|assessment)\b"
        r"[^?]{0,100}\b(?:did\s+i\s+(?:say|mention|choose|select|plan)|"
        r"was\s+i\s+referring\s+to|i\s+(?:said|mentioned|chose|selected|planned|referred\s+to))\b"
        r"|\b(?:what|which).*\b(?:current|selected|previous)\s+(?:reading|lecture|course\s+item|assessment)\b"
    ),
}

AMBIGUOUS_STATE_REFERENCE_RE = re.compile(
    r"^\s*(?:what did we (?:decide(?: on)?|agree (?:to|on)|choose|settle on)|"
    r"what was our decision|(?:(?:can|could) you\s+)?remind me what we "
    r"(?:agreed (?:on|to)|decided)|"
    r"what were we talking about|repeat it)\s*[?.!]*\s*$",
    flags=re.IGNORECASE,
)

COURSE_REFERENCE_RE = re.compile(
    r"\b(?:that|this|the|the previous|previous|selected|current)\s+"
    r"(?:reading|lecture|assessment|reflection prompt|debate task|course item|material|topic)\b"
    r"|\b(?:what (?:was|is) it about|(?:can you\s+)?(?:explain|summari[sz]e) it|"
    r"what did it cover|where (?:is|can i (?:find|access)) it|can you show it to me|"
    r"open it|give me the link|what were its main topics|what did that cover|"
    r"what was that about|tell me more about that|can you explain that material|"
    r"where can i find it|what we covered|that week|the previous material|"
    r"what was the previous material about)\b",
    flags=re.IGNORECASE,
)
BASELINE_COURSE_REFERENCE_RE = re.compile(
    r"\b(?:that|this|the|the previous|previous|selected|current)\s+"
    r"(?:reading|lecture|assessment|reflection prompt|debate task|course item|material)\b"
    r"|\b(?:what (?:was|is) it about|(?:can you\s+)?(?:explain|summari[sz]e) it|"
    r"what did it cover|where (?:is|can i (?:find|access)) it|can you show it to me|"
    r"open it|give me the link|what were its main topics|what did that cover|"
    r"what was that about|tell me more about that|can you explain that material|"
    r"where can i find it|what we covered|that week|the previous material|"
    r"what was the previous material about)\b",
    flags=re.IGNORECASE,
)


ASSISTANT_MEMORY_ANNOTATION_FIELDS = (
    "query_type",
    "selected_route",
    "memory_turn_kind",
    "plan_update_policy",
    "numbered_reference_kind",
    "origin_query_type",
    "origin_route",
    "structured_plan",
    "selected_course_item",
    "structured_payload",
)


def normalise_conversation_history(
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
) -> list[dict[str, str]]:
    """Normalise recent turns to ``{"role": ..., "content": ...}`` records.

    Supported inputs include Streamlit/OpenAI-like dicts, ``(role, content)``
    tuples/lists, and plain strings. Plain strings are treated as assistant
    content because they are usually used in tests as previous assistant text.
    """

    if not conversation_history:
        return []

    normalised: list[dict[str, str]] = []
    for turn in conversation_history:
        role = ""
        content = ""
        if isinstance(turn, Mapping):
            role = str(
                turn.get("role")
                or turn.get("sender")
                or turn.get("type")
                or turn.get("author")
                or ""
            )
            content = str(
                turn.get("content")
                or turn.get("message")
                or turn.get("text")
                or turn.get("value")
                or ""
            )
            page = str(turn.get("page") or turn.get("graph") or turn.get("graph_selection") or "")
        elif isinstance(turn, (tuple, list)) and len(turn) >= 2:
            role = str(turn[0])
            content = str(turn[1])
            page = ""
        elif isinstance(turn, str):
            role = "assistant"
            content = turn
            page = ""
        else:
            page = ""

        role = _normalise_role(role)
        content = content.strip()
        if content:
            record = {"role": role, "content": content}
            if page.strip():
                record["page"] = page.strip()
            if isinstance(turn, Mapping):
                for field in ASSISTANT_MEMORY_ANNOTATION_FIELDS:
                    if field in turn:
                        record[field] = turn[field]
            normalised.append(record)
    return normalised


def extract_numbered_items(text: str) -> list[dict[str, str]]:
    """Extract numbered list items from assistant text.

    Handles examples such as ``1. Revisit W4 lecture``, ``2) Reply to one
    debate post``, and ``3: Write a reflection paragraph``. Continuation lines
    are attached to the preceding item until the next numbered item appears.
    """

    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    continuation_open = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continuation_open = False
            continue
        match = re.match(r"^\s*(\d{1,2})\s*[\.\):\-]\s+(.+?)\s*$", line)
        ordinal_match = re.match(
            r"^\s*(?:the\s+)?(first|second|third|fourth|fifth)\s+"
            r"(?:step|point|item)\s+(?:is|was|:)\s*(.+?)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            current = {"number": match.group(1), "text": strip_structural_markdown(match.group(2))}
            items.append(current)
            continuation_open = True
        elif ordinal_match:
            number = ORDINAL_TO_NUMBER[ordinal_match.group(1).lower()]
            current = {"number": str(number), "text": strip_structural_markdown(ordinal_match.group(2))}
            items.append(current)
            continuation_open = True
        elif current and continuation_open and (raw_line[:1].isspace() or re.match(r"^[-*+]\s+", raw_line)):
            current["text"] = _compact(f"{current['text']} {strip_structural_markdown(line)}")
        else:
            continuation_open = False
    return items


def strip_structural_markdown(text: str) -> str:
    """Remove simple structural Markdown while preserving the action wording."""

    value = _compact(text)
    value = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", value)
    value = re.sub(r"^(?:\*\*|__|\*|_|`)+", "", value)
    value = re.sub(r"(?:\*\*|__|\*|_|`)+$", "", value)
    return _compact(value)


def is_context_dependent_follow_up(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> bool:
    """Return whether a query appears to depend on previous conversation."""

    q = str(query or "").strip().lower()
    if not q:
        return False
    return bool(
        AMBIGUOUS_STATE_REFERENCE_RE.match(q)
        or detect_plan_memory_intent(q, enable_p2a_extensions=enable_p2a_extensions)
        or
        memory_state_query_subtype(q, enable_p2a_extensions=enable_p2a_extensions)
        or (COURSE_REFERENCE_RE if enable_p2a_extensions else BASELINE_COURSE_REFERENCE_RE).search(q)
        or any(
            re.search(pattern, q, flags=re.IGNORECASE)
            for pattern in (
                FOLLOW_UP_PATTERNS + (P2A_FOLLOW_UP_PATTERNS if enable_p2a_extensions else ())
            )
        )
    )


def detect_plan_memory_intent(
    query: str,
    *,
    active_plan_exists: bool = False,
    enable_p2a_extensions: bool = True,
) -> str:
    """Return one auditable plan-Memory intent without an LLM classifier."""

    q = _compact(query).casefold()
    if not q:
        return ""
    revision_verb = r"(?:update|revise|adapt|adjust|shorten|simplify|change|reduce|fit|make)"
    remaining_reference = r"(?:remaining|pending|rest|next|unfinished|incomplete|everything else)"
    quicker_language = r"(?:quicker|faster|shorter|more manageable|new time limit|less time|workload)"
    explicit_revision = bool(
        re.search(
            rf"\b{revision_verb}\b.{{0,100}}\b(?:plan|{remaining_reference}|steps?|actions?|items?|tasks?|recommendations?|{quicker_language})\b"
            rf"|\b(?:{remaining_reference})\b.{{0,100}}\b(?:{revision_verb}|{quicker_language})\b"
            r"|\b(?:keep|preserve|do not change)\b.{0,80}\bcompleted\b.{0,100}\b(?:shorten|simplify|adapt|adjust|quicker|faster|rest|everything else)\b",
            q,
        )
    )
    changed_time = bool(
        re.search(
            r"\b(?:only have|can only spend|less time|new time limit|cannot spend|can't spend)\b.{0,50}"
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|twenty-five|thirty|forty|forty-five|half an|minutes?|hours?)\b",
            q,
        )
    )
    contextual_time_change = bool(
        changed_time
        and (
            active_plan_exists
            or re.search(r"\b(?:now|anymore|less time|new time limit)\b", q)
        )
    )
    if explicit_revision or contextual_time_change:
        return "plan_revision"
    if _is_explicit_completion_statement(q) and re.search(
        rf"\b(?:plan|{PLAN_ITEM_NOUN_PATTERN}|first|second|third|fourth|fifth|"
        r"1st|2nd|3rd|4th|5th)\b",
        q,
    ):
        return "plan_completion"
    if memory_state_query_subtype(q, enable_p2a_extensions=enable_p2a_extensions) == "active_plan":
        return "plan_recall"
    if _has_explicit_numbered_reference(q):
        return "plan_item_reference"
    progression_pattern = (
        r"\b(?:what should i do next|what do i do next|what next|next action|next step|"
        r"continue (?:the|my|our) plan"
        + (r"|remind me what (?:the )?next action involves|what comes next" if enable_p2a_extensions else "")
        + r")\b"
    )
    if re.search(progression_pattern, q):
        return "plan_progression"
    if re.search(r"\b(?:actually|i meant|instead|rather than)\b", q) and re.search(
        r"\b(?:plan|step|action|task|constraint|minutes?|hours?|deadline)\b", q
    ):
        return "plan_correction"
    return ""


def memory_state_query_subtype(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> str:
    """Return the direct explicit-Memory query subtype, if any."""

    q = _compact(query).lower()
    if re.search(r"\bgoal\b", q) and re.search(r"\bconstraint\b", q):
        return "current_goal_and_constraints"
    if re.search(r"\bwhat (?:is|was|'s) my previous goal\b", q):
        return "previous_goal"
    patterns = MEMORY_STATE_PATTERNS if enable_p2a_extensions else BASELINE_MEMORY_STATE_PATTERNS
    for subtype, pattern in patterns.items():
        if re.search(pattern, q, flags=re.IGNORECASE):
            return subtype
    return ""


def _resolve_ambiguous_state_reference(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, Any]],
) -> MemoryResolution | None:
    """Resolve only state-dependent decision/pronoun references.

    These phrases intentionally bypass the lexical plan-recall allowlist. With
    both candidate referents present, deterministic clarification is safer than
    choosing one without an explicit recent-referent annotation.
    """

    if not AMBIGUOUS_STATE_REFERENCE_RE.match(_compact(query)):
        return None
    active_plan = _enrich_active_plan(state.get("active_plan"))
    active_course_item = dict(state.get("active_course_item") or {})
    if active_plan and not active_course_item:
        return _resolve_memory_state_query(
            query,
            "active_plan",
            state,
            recent_messages,
            plan_memory_intent="plan_recall",
        )
    if active_course_item and not active_plan:
        return _resolve_memory_state_query(
            query,
            "current_course_item",
            state,
            recent_messages,
            plan_memory_intent="",
        )

    if active_plan and active_course_item:
        subtype = "ambiguous_plan_or_course"
        prompt = "Do you mean the action plan or the course material we were discussing?"
        value: dict[str, Any] = {
            "active_plan_available": True,
            "active_course_item_available": True,
        }
        reason = "Both a plan and course item are active, so the referent is ambiguous."
    else:
        subtype = "ambiguous_recent_state"
        prompt = "What previous decision or course material do you mean?"
        value = {}
        reason = "No active plan or course item is stored for the ambiguous referent."
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=(
            "Ask this clarification exactly and do not infer or fabricate state: "
            f"{prompt}"
        ),
        memory_context={
            "recent_message_count": len(recent_messages),
            "memory_state_query_subtype": subtype,
            "memory_state_value": value,
            "plan_memory_intent": "",
            "state_reference_ambiguous": True,
            "clarification_prompt": prompt,
        },
        structured_state=state,
        resolution_type="memory_state_query",
        reason=reason,
    )


def resolve_follow_up_query(
    query: str,
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    max_messages: int = MAX_SESSION_MEMORY_MESSAGES,
    existing_session_memory: Mapping[str, Any] | None = None,
    current_page: str = "",
    transactional_course_corrections: bool = False,
    enable_p2a_extensions: bool = True,
) -> MemoryResolution:
    """Resolve a follow-up using at most ``max_messages`` recent messages.

    The resolver handles numbered references and explicit structured plan state.
    If no usable context exists, the original query is returned with
    ``resolved=False``.
    """

    original_query = str(query or "").strip()
    history = normalise_conversation_history(conversation_history)
    recent = history[-max_messages:] if max_messages > 0 else history
    recent_state = build_structured_session_memory(
        recent,
        current_query=original_query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    structured_state = merge_structured_session_memory(
        existing_session_memory,
        recent_state,
        current_page=current_page,
    )
    existing_course_item = dict(
        (existing_session_memory or {}).get("active_course_item") or {}
    )
    if (
        transactional_course_corrections
        and existing_course_item
        and _looks_like_course_correction(original_query)
    ):
        # A correction is only a proposed reference until corrected retrieval
        # succeeds.  Do not let current-query entity extraction overwrite the
        # last transactionally committed course item before that retrieval.
        structured_state["active_course_item"] = existing_course_item
        structured_state["course_entity_candidates"] = [existing_course_item]
        structured_state["active_course_item_source_role"] = str(
            (existing_session_memory or {}).get("active_course_item_source_role")
            or "authoritative"
        )
    is_follow_up = is_context_dependent_follow_up(
        original_query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    if not is_follow_up:
        return MemoryResolution(
            is_follow_up=False,
            resolved=False,
            original_query=original_query,
            resolved_query=original_query,
            structured_state=structured_state,
            reason="Query does not appear to depend on previous conversational context.",
        )

    plan_memory_intent = detect_plan_memory_intent(
        original_query,
        active_plan_exists=bool(structured_state.get("active_plan")),
        enable_p2a_extensions=enable_p2a_extensions,
    )
    ambiguous_state = _resolve_ambiguous_state_reference(
        original_query,
        structured_state,
        recent,
    )
    if ambiguous_state is not None:
        return ambiguous_state
    memory_state_subtype = memory_state_query_subtype(
        original_query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    if memory_state_subtype:
        return _resolve_memory_state_query(
            original_query,
            memory_state_subtype,
            structured_state,
            recent,
            plan_memory_intent=plan_memory_intent,
        )

    plan_revision = _resolve_active_plan_revision(
        original_query,
        structured_state,
        recent,
        plan_memory_intent,
    )
    if plan_revision is not None:
        return plan_revision

    course_correction = _resolve_course_week_correction(
        original_query, structured_state, recent
    )
    if course_correction is not None:
        return course_correction

    if plan_memory_intent in {
        "plan_progression",
        "plan_revision",
        "plan_correction",
        "plan_completion",
    } and not structured_state.get("active_plan") and not (
        plan_memory_intent == "plan_progression"
        and (
            structured_state.get("active_goal")
            or structured_state.get("selected_actions")
            or structured_state.get("completed_actions")
        )
    ):
        return _resolve_no_active_plan(
            original_query,
            structured_state,
            recent,
            plan_memory_intent,
        )

    completion_resolution = _resolve_active_plan_completion(original_query, structured_state, recent)
    if completion_resolution is not None:
        return completion_resolution

    course_resolution = _resolve_course_reference(original_query, structured_state, recent)
    if course_resolution is not None:
        return course_resolution

    plan_reference = _resolve_active_plan_numbered_reference(original_query, structured_state, recent)
    if plan_reference is not None:
        return plan_reference

    assistant_turn, items = _most_recent_numbered_assistant_turn(recent)
    numbered_kind = (
        str(assistant_turn.get("numbered_reference_kind") or "")
        or (_numbered_reference_kind(assistant_turn.get("content", ""), items) if items else "")
    )
    if not items:
        items = list(structured_state.get("generic_numbered_referents") or [])
        if items:
            assistant_turn = {"content": "\n".join(f"{item.get('number')}. {item.get('text')}" for item in items)}
            numbered_kind = str(structured_state.get("numbered_reference_kind") or "other")
    if not items:
        structured = _resolve_structured_continuity(
            original_query,
            structured_state,
            recent,
            enable_p2a_extensions=enable_p2a_extensions,
        )
        if structured is not None and not _has_explicit_numbered_reference(original_query):
            return structured
        return MemoryResolution(
            is_follow_up=True,
            resolved=False,
            original_query=original_query,
            resolved_query=original_query,
            memory_context={"recent_message_count": len(recent)},
            structured_state=structured_state,
            reason="No recent assistant turn with numbered items was available.",
        )

    referenced_numbers = _referenced_item_numbers(original_query, items)
    if not referenced_numbers:
        vague_mode = _vague_reference_mode(original_query)
        if vague_mode == "all":
            referenced_numbers = [int(item["number"]) for item in items]
        elif vague_mode == "single" and len(items) == 1 and items[0]["number"].isdigit():
            referenced_numbers = [int(items[0]["number"])]
        else:
            structured = _resolve_structured_continuity(
                original_query,
                structured_state,
                recent,
                enable_p2a_extensions=enable_p2a_extensions,
            )
            if structured is not None:
                return structured
            return MemoryResolution(
                is_follow_up=True,
                resolved=False,
                original_query=original_query,
                resolved_query=original_query,
                memory_context={
                    "recent_message_count": len(recent),
                    "available_numbered_items": items,
                },
                structured_state=structured_state,
                reason="The query looked like a follow-up but no item reference could be mapped unambiguously.",
            )

    item_lookup = {int(item["number"]): item for item in items if item["number"].isdigit()}
    referenced_items = []
    for number in referenced_numbers:
        if number not in item_lookup:
            continue
        referenced = dict(item_lookup[number])
        referenced["number"] = str(number)
        referenced["text"] = item_lookup[number]["text"]
        referenced_items.append(referenced)
    if not referenced_items:
        return MemoryResolution(
            is_follow_up=True,
            resolved=False,
            original_query=original_query,
            resolved_query=original_query,
            memory_context={
                "recent_message_count": len(recent),
                "available_numbered_items": items,
                "requested_item_numbers": [str(number) for number in referenced_numbers],
            },
            structured_state=structured_state,
            reason="The referenced item numbers were not present in the recent assistant list.",
        )

    item_text = "; ".join(f"item {item['number']}: {item['text']}" for item in referenced_items)
    if numbered_kind == "action_plan":
        resolved_query = (
            "The student is following up on previous action-plan steps: "
            f"{item_text}. Original follow-up query: \"{original_query}\". "
            "Provide concrete guidance for the referenced pending steps without replacing the active plan."
        )
    else:
        resolved_query = (
            "The student is following up on previous numbered items: "
            f"{item_text}. Original follow-up query: \"{original_query}\". "
            "Explain only the referenced items and do not treat them as selected or completed actions."
        )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=original_query,
        resolved_query=resolved_query,
        referenced_items=referenced_items,
        memory_context={
            "recent_message_count": len(recent),
            "assistant_turn_content": assistant_turn.get("content", ""),
            "available_numbered_items": items,
            "requested_item_numbers": [item["number"] for item in referenced_items],
            "numbered_reference_kind": numbered_kind or "other",
        },
        structured_state=structured_state,
        resolution_type="numbered_reference",
        reason="Resolved follow-up query from the most recent assistant numbered list.",
    )


def build_structured_session_memory(
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    current_query: str = "",
    *,
    enable_p2a_extensions: bool = True,
) -> dict[str, Any]:
    """Extract explicit, session-scoped learning state from recent turns.

    The extractor deliberately stores only statements present in the transcript.
    It does not infer ability, motivation, preferences, or learning quality.
    """

    turns = normalise_conversation_history(conversation_history)
    if current_query.strip():
        turns = [*turns, {"role": "user", "content": current_query.strip()}]

    goals: list[str] = []
    constraints: list[str] = []
    completions: list[str] = []
    corrections: list[str] = []
    actions: list[dict[str, Any]] = []
    pages: list[str] = []
    generic_numbered_referents: list[dict[str, str]] = []
    numbered_reference_kind = ""
    active_plan: dict[str, Any] = {}
    active_course_item: dict[str, Any] = {}
    course_entity_candidates: list[dict[str, Any]] = []
    active_course_item_source_role = ""

    for index, turn in enumerate(turns):
        role = turn.get("role", "")
        content = _compact(turn.get("content", ""))
        page = _compact(turn.get("page", ""))
        if page:
            pages.append(page)
        if not content:
            continue

        course_entities = _dedupe_course_entities(_extract_course_entities(content, source_turn_id=index))
        if len(course_entities) == 1:
            active_course_item = course_entities[0]
            course_entity_candidates = course_entities
            active_course_item_source_role = role
        elif len(course_entities) > 1:
            active_course_item = {}
            course_entity_candidates = course_entities
            active_course_item_source_role = role

        if role == "user":
            if GOAL_RE.search(content):
                goals.append(_bounded(content))
            if CONSTRAINT_RE.search(content):
                constraints.append(_bounded(content))
            if _is_explicit_completion_statement(content) and not memory_state_query_subtype(
                content,
                enable_p2a_extensions=enable_p2a_extensions,
            ):
                completions.append(_bounded(content))
            if CORRECTION_RE.search(content):
                corrections.append(_bounded(content))
            if COMMITTED_ACTION_RE.search(content):
                actions.append(
                    {
                        "text": _bounded(content),
                        "number": "",
                        "status": "committed",
                        "source_turn": index,
                    }
                )
        elif role == "assistant":
            plan_policy = str(turn.get("plan_update_policy") or "")
            annotated_plan = turn.get("structured_plan") if isinstance(turn.get("structured_plan"), Mapping) else {}
            annotated_item = turn.get("selected_course_item") if isinstance(turn.get("selected_course_item"), Mapping) else {}
            if annotated_item:
                active_course_item = dict(annotated_item)
                course_entity_candidates = [dict(annotated_item)]
                active_course_item_source_role = "authoritative"
            if plan_policy == "create" and annotated_plan:
                active_plan = _enrich_active_plan(annotated_plan)
                numbered_reference_kind = "action_plan"
                generic_numbered_referents = _normalise_recommendations(
                    turn.get("structured_payload", {}).get("numbered_referents", [])
                )[-8:]
                actions.extend(_actions_from_active_plan(active_plan))
                continue
            numbered = extract_numbered_items(turn.get("content", ""))
            if numbered:
                fallback_kind = str(turn.get("numbered_reference_kind") or _numbered_reference_kind(content, numbered))
                payload_items = (turn.get("structured_payload") or {}).get("numbered_referents", [])
                numbered_reference_kind = fallback_kind
                if plan_policy == "preserve" and fallback_kind == "action_plan":
                    # Explanatory numbering is ephemeral and must not shadow the stable plan.
                    continue
                generic_numbered_referents = _normalise_recommendations(payload_items or numbered)[-8:]
                if numbered_reference_kind == "action_plan" and plan_policy not in {"preserve", "none"}:
                    active_plan = _build_active_plan(numbered, index, goals[-1] if goals else "", constraints)
                    actions.extend(
                        {
                            "text": _bounded(item["text"]),
                            "number": item["number"],
                            "status": "proposed",
                            "source_turn": index,
                        }
                        for item in numbered
                    )
            else:
                action = _extract_unnumbered_action(content)
                if action:
                    actions.append(
                        {"text": action, "number": "", "status": "proposed", "source_turn": index}
                    )

    goals = _dedupe_text(goals)[-3:]
    constraints = _dedupe_text(constraints)[-4:]
    completions = _dedupe_text(completions)[-4:]
    corrections = _dedupe_text(corrections)[-3:]
    actions = _dedupe_actions(actions)[-8:]
    for action in actions:
        if any(_texts_refer_to_same_action(action["text"], completion) for completion in completions):
            action["status"] = "completed"
    if active_plan:
        active_plan = _apply_completions_to_plan(active_plan, completions)
        actions = _actions_with_plan(active_plan, actions)

    recent_numbered_recommendations = (
        generic_numbered_referents if numbered_reference_kind == "action_plan" else []
    )

    return {
        "active_goal": goals[-1] if goals else "",
        "goals": goals,
        "constraints": constraints,
        "selected_actions": actions,
        "completed_actions": completions,
        "corrections": corrections,
        "relevant_pages": _dedupe_text(pages),
        "generic_numbered_referents": generic_numbered_referents,
        "numbered_reference_kind": numbered_reference_kind,
        "recent_numbered_recommendations": recent_numbered_recommendations,
        "active_plan": active_plan,
        "active_course_item": active_course_item,
        "course_entity_candidates": course_entity_candidates,
        "active_course_item_source_role": active_course_item_source_role,
        "scope": "recent_session_only",
    }


def merge_structured_session_memory(
    existing_session_memory: Mapping[str, Any] | None,
    recent_memory: Mapping[str, Any] | None,
    current_page: str = "",
) -> dict[str, Any]:
    """Merge bounded explicit state, preferring newly stated information.

    The function does not infer new learner traits. It only preserves explicit
    fields already stored in the session and combines them with explicit fields
    extracted from recent messages.
    """

    existing = dict(existing_session_memory or {})
    recent = dict(recent_memory or {})

    goals = _dedupe_text([*existing.get("goals", []), *recent.get("goals", [])])[-3:]
    active_goal = str(recent.get("active_goal") or existing.get("active_goal") or "")
    if active_goal and active_goal not in goals:
        goals = _dedupe_text([*goals, active_goal])[-3:]
    constraints = _dedupe_text([*existing.get("constraints", []), *recent.get("constraints", [])])[-4:]
    completions = _dedupe_text(
        [*existing.get("completed_actions", []), *recent.get("completed_actions", [])]
    )[-4:]
    corrections = _dedupe_text([*existing.get("corrections", []), *recent.get("corrections", [])])[-3:]
    active_plan = _merge_active_plan(
        existing.get("active_plan"),
        recent.get("active_plan"),
        completions,
        replacement_policy=str(recent.get("active_plan_replacement_policy") or "preserve"),
    )
    active_plan = _apply_week_corrections_to_plan(active_plan, corrections)
    actions = _merge_actions(
        [*existing.get("selected_actions", []), *recent.get("selected_actions", [])],
        completions,
    )[-8:]
    if active_plan:
        actions = _actions_with_plan(active_plan, actions)
    actions = _apply_explicit_corrections(actions, corrections)
    pages = _dedupe_text(
        [*existing.get("relevant_pages", []), *recent.get("relevant_pages", []), current_page]
    )[-6:]
    recent_numbered = list(recent.get("recent_numbered_recommendations") or [])
    if not recent_numbered:
        recent_numbered = list(existing.get("recent_numbered_recommendations") or [])
    generic_numbered = list(recent.get("generic_numbered_referents") or [])
    numbered_kind = str(recent.get("numbered_reference_kind") or "")
    if not generic_numbered:
        generic_numbered = list(existing.get("generic_numbered_referents") or [])
        numbered_kind = str(existing.get("numbered_reference_kind") or "")
    course_entity_candidates = list(
        recent.get("course_entity_candidates") or existing.get("course_entity_candidates") or []
    )
    recent_item = dict(recent.get("active_course_item") or {})
    existing_item = dict(existing.get("active_course_item") or {})
    recent_role = str(recent.get("active_course_item_source_role") or "")
    if recent_role in {"user", "authoritative"} and recent_item:
        active_course_item = recent_item
    elif existing_item:
        active_course_item = existing_item
    elif len(recent.get("course_entity_candidates") or []) <= 1:
        active_course_item = recent_item
    else:
        active_course_item = {}

    active_goal = _apply_week_corrections_to_text(active_goal, corrections)
    goals = _dedupe_text(
        [_apply_week_corrections_to_text(goal, corrections) for goal in goals]
    )[-3:]
    if active_goal and active_goal not in goals:
        goals = _dedupe_text([*goals, active_goal])[-3:]
    active_course_item = _apply_week_corrections_to_course_item(active_course_item, corrections)
    course_entity_candidates = [
        _apply_week_corrections_to_course_item(candidate, corrections)
        for candidate in course_entity_candidates
    ]
    generic_numbered = _apply_week_corrections_to_numbered_items(generic_numbered, corrections)
    recent_numbered = _apply_week_corrections_to_numbered_items(recent_numbered, corrections)

    return {
        "active_goal": active_goal,
        "goals": goals,
        "constraints": constraints,
        "selected_actions": actions,
        "completed_actions": completions,
        "corrections": corrections,
        "relevant_pages": pages,
        "generic_numbered_referents": _normalise_recommendations(generic_numbered)[-8:],
        "numbered_reference_kind": numbered_kind,
        "recent_numbered_recommendations": _normalise_recommendations(recent_numbered)[-8:],
        "active_plan": active_plan,
        "active_course_item": active_course_item,
        "course_entity_candidates": course_entity_candidates,
        "active_course_item_source_role": recent_role or str(existing.get("active_course_item_source_role") or ""),
        "scope": "recent_session_only",
    }


def prepare_mode_cm_context(
    *,
    student_query: str,
    conversation_history: Sequence[Mapping[str, Any] | tuple | str] | None,
    existing_session_memory: Mapping[str, Any] | None = None,
    current_page: str = "",
    max_messages: int = MAX_SESSION_MEMORY_MESSAGES,
    transactional_course_corrections: bool = False,
    enable_p2a_extensions: bool = True,
) -> MemoryRuntimeResult:
    """Prepare the single shared expanded-memory stage for CM and C_FULL.

    CM, C_FULL, and the Streamlit assistant must call this function rather than
    implementing their own follow-up resolver or structured-state updater.
    """

    before = merge_structured_session_memory(existing_session_memory, {}, current_page="")
    resolution = resolve_follow_up_query(
        student_query,
        conversation_history,
        max_messages=max_messages,
        existing_session_memory=existing_session_memory,
        current_page=current_page,
        transactional_course_corrections=transactional_course_corrections,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    state = resolution.structured_state
    updates = _memory_updates(before, state)
    return MemoryRuntimeResult(
        original_query=str(student_query or "").strip(),
        resolved_query=resolution.resolved_query,
        memory_triggered=resolution.is_follow_up,
        memory_resolved=resolution.resolved,
        memory_resolution_type=resolution.resolution_type,
        numbered_reference_resolved=resolution.resolution_type == "numbered_reference",
        referenced_items=list(resolution.referenced_items),
        structured_memory=state,
        formatted_memory_context=format_memory_context_for_prompt(resolution),
        memory_updates=updates,
        memory_resolution=resolution,
    )


def clear_student_session_memory(
    memory_by_student: dict[str, Any],
    student_key: str,
) -> None:
    """Clear only one student's in-session expanded memory state."""

    memory_by_student.pop(str(student_key), None)


def scoped_chat_messages(
    messages_by_scope: dict[str, list[dict[str, Any]]],
    scope_key: str,
) -> list[dict[str, Any]]:
    """Return the durable visible/model transcript for one student-page scope."""

    return messages_by_scope.setdefault(str(scope_key), [])


def clear_scoped_chat_messages(
    messages_by_scope: dict[str, list[dict[str, Any]]],
    student_session_key: str,
) -> None:
    """Clear every page transcript belonging to one student session only."""

    prefix = f"{student_session_key}::"
    for key in list(messages_by_scope):
        if key == student_session_key or key.startswith(prefix):
            messages_by_scope.pop(key, None)


def format_memory_context_for_prompt(resolution: MemoryResolution) -> str:
    """Format memory resolution as hidden prompt context."""

    if not resolution.is_follow_up:
        return "No short-term memory resolution was needed."
    if not resolution.resolved:
        return (
            "The student appears to ask a follow-up question, but no usable recent memory context "
            f"was available. Original query: {resolution.original_query}"
        )
    items = "\n".join(f"- item {item['number']}: {item['text']}" for item in resolution.referenced_items)
    numbered_kind = str((resolution.memory_context or {}).get("numbered_reference_kind", ""))
    state_text = (
        ""
        if resolution.resolution_type == "numbered_reference" and numbered_kind != "action_plan"
        else _format_structured_state(resolution.structured_state)
    )
    return (
        "Short-term memory resolved the student's follow-up query.\n"
        f"Resolution type: {resolution.resolution_type or 'short_term_follow_up'}\n"
        f"Original query: {resolution.original_query}\n"
        f"Resolved query: {resolution.resolved_query}\n"
        + (f"Referenced previous items:\n{items}\n" if items else "")
        + (f"Explicit structured session state:\n{state_text}\n" if state_text else "")
        + "Use only explicit remembered statements. Newer corrections override older details. "
        "Do not infer ability, motivation, comprehension, or preferences."
    )


def format_structured_session_memory(state: Mapping[str, Any] | None) -> str:
    """Return a compact prompt-safe representation of explicit session state."""

    return _format_structured_state(state)


def session_memory_scope_key(selected_student: Any = None, user_id: Any = None) -> str:
    """Return a stable per-student key for session-only memory."""

    student = _compact(selected_student)
    if student:
        return student
    user = _compact(user_id)
    return user or "current_session"


def chat_message_scope_key(page: Any, selected_student: Any = None, user_id: Any = None) -> str:
    """Scope visible/model chat messages by both student and dashboard page."""

    return f"{session_memory_scope_key(selected_student, user_id)}::{_compact(page) or 'unknown_page'}"


def prepare_messages_with_memory(
    messages: Sequence[Mapping[str, Any]],
    resolution: MemoryResolution | None,
) -> list[dict[str, str]]:
    """Prepare a model request without mutating the visible chat transcript.

    A resolved query is rewritten exactly as in offline CM and accompanied by
    the same auditable memory context. Triggered-but-unresolved and ordinary
    queries are sent unchanged, so unusable memory cannot leak into an answer.
    """

    prepared = [
        {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
        for message in messages
        if message.get("role") in {"system", "user", "assistant"} and "content" in message
    ]
    if not resolution or not resolution.resolved:
        return prepared

    last_user_index = next(
        (index for index in range(len(prepared) - 1, -1, -1) if prepared[index]["role"] == "user"),
        None,
    )
    if last_user_index is None:
        return prepared

    prepared[last_user_index] = {"role": "user", "content": resolution.resolved_query}
    prepared.insert(
        last_user_index,
        {
            "role": "system",
            "content": (
                format_memory_context_for_prompt(resolution)
                + "\nMemory is only conversational context. Dashboard evidence must support claims about "
                "student activity, and retrieved course material must support course or task guidance."
            ),
        },
    )
    return prepared


def _numbered_reference_kind(text: str, items: Sequence[Mapping[str, Any]]) -> str:
    """Classify a numbered list without assuming that numbering means a plan."""

    combined = _compact(text).lower()
    item_texts = [strip_structural_markdown(item.get("text", "")) for item in items]
    analytical_terms = re.compile(
        r"\b(?:average|mean|denominator|numerator|calculation|definition|defined|"
        r"across (?:all|real|viewed)|percentage among|total equals|interpretation)\b",
        flags=re.IGNORECASE,
    )
    action_start = re.compile(
        r"^(?:choose|write|add|review|revisit|watch|read|reply|create|schedule|use|"
        r"pick|select|complete|submit|draft|note|reflect|compare|check|focus|start|try)\b",
        flags=re.IGNORECASE,
    )
    actionable = sum(bool(action_start.search(item)) for item in item_texts)
    plan_marked = bool(
        re.search(r"\b(?:action plan|steps? to|try this next|recommended actions?|your plan)\b", combined)
    )
    if not plan_marked and any(analytical_terms.search(item) for item in item_texts):
        return "analytical_list"
    if plan_marked or (item_texts and actionable >= max(1, (len(item_texts) + 1) // 2)):
        return "action_plan"
    if item_texts and all(re.search(r"\b(?:reading|lecture|assessment|prompt|task|w\d+)\b", item, re.I) for item in item_texts):
        return "course_item_list"
    return "other"


def _build_active_plan(
    items: Sequence[Mapping[str, Any]],
    source_turn_id: int,
    goal: str,
    constraints: Sequence[str],
) -> dict[str, Any]:
    steps = [
        {
            "index": int(item.get("number")),
            "action_text": _bounded(item.get("text", "")),
            "status": "pending",
        }
        for item in items
        if str(item.get("number", "")).isdigit() and _compact(item.get("text", ""))
    ]
    if not steps:
        return {}
    signature = "-".join(str(step["index"]) + ":" + step["action_text"].casefold() for step in steps)
    plan_id = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    plan = {
        "plan_id": f"plan-{plan_id}",
        "goal": goal,
        "constraints": list(constraints)[-4:],
        "steps": steps,
        "source_turn_id": source_turn_id,
    }
    return _enrich_active_plan(plan)


def _enrich_active_plan(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {}
    out = dict(plan)
    steps = [dict(step) for step in out.get("steps", []) if isinstance(step, Mapping)]
    steps.sort(key=lambda step: int(step.get("index", 0)))
    out["steps"] = steps
    out["completed_steps"] = [step for step in steps if step.get("status") == "completed"]
    out["pending_steps"] = [step for step in steps if step.get("status") != "completed"]
    out["next_pending_step"] = out["pending_steps"][0] if out["pending_steps"] else None
    out["active_plan_complete"] = bool(steps) and not out["pending_steps"]
    return out


def _apply_completions_to_plan(
    plan: Mapping[str, Any] | None,
    completions: Sequence[str],
) -> dict[str, Any]:
    out = _enrich_active_plan(plan)
    if not out:
        return {}
    steps = [dict(step) for step in out.get("steps", [])]
    for completion in completions:
        referenced = _completion_step_numbers(completion)
        for step in steps:
            explicitly_referenced = int(step.get("index", 0)) in referenced
            inferred_same_action = bool(
                not referenced
                and _texts_refer_to_same_action(
                    str(step.get("action_text", "")), completion
                )
            )
            if explicitly_referenced or inferred_same_action:
                step["status"] = "completed"
                step["completed_by"] = _bounded(completion)
    out["steps"] = steps
    return _enrich_active_plan(out)


def _completion_step_numbers(text: str) -> list[int]:
    q = _compact(text).lower()
    if not COMPLETION_RE.search(q):
        return []
    numbers: list[int] = []
    for ordinal, number in ORDINAL_TO_NUMBER.items():
        if re.search(rf"\b{re.escape(ordinal)}\s+{PLAN_ITEM_NOUN_PATTERN}\b", q):
            numbers.append(number)
    for match in re.finditer(
        rf"\b{PLAN_ITEM_NOUN_PATTERN}(?:\s+number)?\s*(\d{{1,2}})\b", q
    ):
        numbers.append(int(match.group(1)))
    return _dedupe_ints(numbers)


def _is_explicit_completion_statement(text: str) -> bool:
    """Separate learner progress reports from questions about watched metrics."""

    compact = _compact(text)
    if not COMPLETION_RE.search(compact):
        return False
    if re.search(r"\b(?:average|percentage|percent|metric|calculation|report separately)\b", compact, re.I):
        return False
    if re.search(
        r"\b(?:update|revise|adapt|shorten|simplify|keep|preserve)\b.{0,100}\bcompleted\b",
        compact,
        re.I,
    ):
        return False
    return bool(
        re.search(r"\b(?:i(?:'ve| have)?\s+)?(?:finished|completed|done|submitted|replied|wrote|caught up)\b", compact, re.I)
        or re.match(r"^(?:watched|reviewed|read)\b", compact, re.I)
        or re.search(r"\bi(?:'ve| have)\s+(?:watched|reviewed|read)\b", compact, re.I)
    )


def _merge_active_plan(
    existing_plan: Mapping[str, Any] | None,
    recent_plan: Mapping[str, Any] | None,
    completions: Sequence[str],
    replacement_policy: str = "preserve",
) -> dict[str, Any]:
    existing = _enrich_active_plan(existing_plan)
    recent = _enrich_active_plan(recent_plan)
    if not recent:
        return _apply_completions_to_plan(existing, completions)
    if existing and replacement_policy != "replace":
        return _apply_completions_to_plan(existing, completions)
    if existing:
        existing_signature = [
            _compact(step.get("action_text", "")).casefold()
            for step in existing.get("steps", [])
        ]
        recent_signature = [
            _compact(step.get("action_text", "")).casefold()
            for step in recent.get("steps", [])
        ]
        if existing_signature == recent_signature:
            recent["plan_id"] = existing.get("plan_id", recent.get("plan_id"))
        old_by_text = {
            _compact(step.get("action_text", "")).casefold(): step
            for step in existing.get("steps", [])
        }
        for step in recent.get("steps", []):
            old = old_by_text.get(_compact(step.get("action_text", "")).casefold())
            if old and old.get("status") == "completed":
                step["status"] = "completed"
                if old.get("completed_by"):
                    step["completed_by"] = old["completed_by"]
    return _apply_completions_to_plan(recent, completions)


def _actions_from_active_plan(plan: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {
            "text": step.get("action_text", ""),
            "number": str(step.get("index", "")),
            "status": step.get("status", "pending"),
            "source_turn": plan.get("source_turn_id", "") if plan else "",
        }
        for step in (plan or {}).get("steps", [])
    ]


def _actions_with_plan(
    plan: Mapping[str, Any] | None,
    existing_actions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    plan_actions = _actions_from_active_plan(plan)
    plan_text = {_compact(action.get("text", "")).casefold() for action in plan_actions}
    committed = [
        dict(action)
        for action in existing_actions
        if action.get("status") == "committed"
        and _compact(action.get("text", "")).casefold() not in plan_text
    ]
    return [*plan_actions, *committed][-8:]


def _resolve_no_active_plan(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    plan_memory_intent: str,
) -> MemoryResolution:
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=(
            "The student referred to an active plan, but no active plan is stored in this "
            "session. State that directly. Do not fabricate actions or run a new planner."
        ),
        memory_context={
            "recent_message_count": len(recent_messages),
            "memory_state_query_subtype": "active_plan",
            "memory_state_value": {},
            "plan_memory_intent": plan_memory_intent,
            "no_active_plan": True,
        },
        structured_state=state,
        resolution_type="no_active_plan",
        reason="The query requires plan Memory, but no active plan is stored.",
    )


def _latest_time_constraint(query: str) -> str:
    value = str(query or "")
    if re.search(r"\b(?:cannot|can't)\s+spend\b", value, re.IGNORECASE):
        return ""
    if re.search(r"\bhalf an hour\b", value, re.IGNORECASE):
        return "30 minutes"
    match = re.search(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|"
        r"twenty|twenty-five|thirty|forty|forty-five)\s*"
        r"(minutes?|mins?|hours?|days?)\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    number_words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "fifteen": 15, "twenty": 20, "twenty-five": 25,
        "thirty": 30, "forty": 40, "forty-five": 45,
    }
    number_token = match.group(1).lower()
    number = int(number_token) if number_token.isdigit() else number_words[number_token]
    unit = match.group(2).lower()
    if unit.startswith("min"):
        unit = "minutes"
    return f"{number} {unit}"


def _adapt_pending_action(action_text: str, constraint: str) -> str:
    base = re.sub(
        r"^(?:Within\s+\d+\s+(?:minutes?|hours?|days?),\s*|"
        r"Under the revised time limit,\s*|Use a shorter version:\s*)",
        "",
        _compact(action_text),
        flags=re.IGNORECASE,
    )
    if not base:
        return action_text
    lowered = base[0].lower() + base[1:]
    if re.search(r"\b\d+\s+(?:minutes?|hours?|days?)\b", constraint, re.I):
        return f"Within {constraint}, {lowered}"
    if constraint:
        return f"Under the revised time limit, {lowered}"
    return f"Use a shorter version: {lowered}"


def _resolve_active_plan_revision(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    plan_memory_intent: str,
) -> MemoryResolution | None:
    if plan_memory_intent not in {"plan_revision", "plan_correction"}:
        return None
    plan = _enrich_active_plan(state.get("active_plan"))
    if not plan:
        return None
    constraint = _latest_time_constraint(query)
    if not constraint and not re.search(
        r"\b(?:shorten|simplify|adapt|adjust|update|revise|reduce|fit|quicker|faster|"
        r"shorter|manageable|less time|cannot spend|can't spend)\b",
        query,
        re.IGNORECASE,
    ):
        return None

    previous_constraints = list(
        plan.get("current_constraints") or plan.get("constraints") or []
    )
    current_constraints = list(previous_constraints)
    if constraint:
        current_constraints = [
            item
            for item in current_constraints
            if not re.search(r"\b\d+\s*(?:minutes?|mins?|hours?|days?)\b", str(item), re.I)
        ]
        current_constraints.append(constraint)
    elif re.search(r"\b(?:less time|cannot spend|can't spend|new time limit)\b", query, re.I):
        current_constraints = ["less time than the previous constraint"]

    revised_steps: list[dict[str, Any]] = []
    referenced_items: list[dict[str, Any]] = []
    for raw_step in plan.get("steps", []):
        step = dict(raw_step)
        if step.get("status") != "completed":
            step["action_text"] = _adapt_pending_action(
                str(step.get("action_text") or ""),
                constraint or (
                    "less time than the previous constraint"
                    if current_constraints == ["less time than the previous constraint"]
                    else ""
                ),
            )
            referenced_items.append(
                {
                    "number": str(step.get("index", "")),
                    "text": str(step.get("action_text", "")),
                    "origin_query_type": str(plan.get("source_query_type") or ""),
                    "origin_route": str(plan.get("source_route") or ""),
                    "origin_evidence_domain": str(plan.get("source_domain") or ""),
                }
            )
        revised_steps.append(step)

    revised = dict(plan)
    revised.update(
        {
            "steps": revised_steps,
            "revision_number": int(plan.get("revision_number") or 0) + 1,
            "revised_at_turn": "current_successful_turn",
            "previous_constraints": previous_constraints,
            "current_constraints": current_constraints,
            "constraints": current_constraints,
            "revision_reason": _bounded(query),
        }
    )
    revised = _enrich_active_plan(revised)
    revised_state = dict(state)
    revised_state["active_plan"] = revised
    revised_state["constraints"] = current_constraints
    revised_state["selected_actions"] = _actions_from_active_plan(revised)
    next_step = revised.get("next_pending_step")
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=(
            "Revise only the pending actions in the existing active plan. Preserve completed "
            f"steps exactly. Current constraints: {current_constraints}. Revised pending steps: "
            + " | ".join(
                f"{item['number']}. {item['text']}" for item in referenced_items
            )
        ),
        referenced_items=referenced_items,
        memory_context={
            "recent_message_count": len(recent_messages),
            "numbered_reference_kind": "action_plan",
            "plan_memory_intent": "plan_revision",
            "plan_revision_requested": True,
            "previous_constraints": previous_constraints,
            "current_constraints": current_constraints,
            "next_pending_step": next_step,
        },
        structured_state=revised_state,
        resolution_type="active_plan_revision",
        reason="Revised pending active-plan actions under the explicit new constraint.",
    )


def _resolve_course_week_correction(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, Any]],
) -> MemoryResolution | None:
    active_item = dict(state.get("active_course_item") or {})
    if not active_item:
        return None
    value = str(query or "")
    correction_marker = bool(
        re.search(
            r"\b(?:actually|no|sorry|i meant|rather|make that|change that to|"
            r"i was referring to|instead)\b|\buse\b.{0,40}\binstead\b|"
            r"^\s*not\s+(?:week\s*|w)\d+",
            value,
            flags=re.IGNORECASE,
        )
    )
    week_matches = list(
        re.finditer(r"\b(?:week\s*|w)(\d{1,2})\b", value, flags=re.IGNORECASE)
    )
    if not correction_marker or not week_matches:
        return None
    if re.search(r"^\s*not\b", value, re.IGNORECASE) and len(week_matches) > 1:
        target = week_matches[-1]
    else:
        target = week_matches[0]
    corrected_number = int(target.group(1))
    if not 1 <= corrected_number <= 12:
        return MemoryResolution(
            is_follow_up=True,
            resolved=False,
            original_query=query,
            resolved_query=query,
            memory_context={
                "recent_message_count": len(recent_messages),
                "course_reference_triggered": True,
                "course_reference_resolved": False,
                "unsupported_week": True,
                "detected_week_expression": target.group(0),
                "parsed_week_number": corrected_number,
                "supported_week": False,
            },
            structured_state=state,
            resolution_type="unsupported_course_week",
            reason="The corrected course week is outside the supported W1-W12 range.",
        )
    corrected_week = f"W{corrected_number}"
    previous_week = str(active_item.get("week") or "").upper()
    explicit_material = re.search(
        r"\b(lecture|reading|assessment|reflection|debate material|course material)\b",
        value,
        flags=re.IGNORECASE,
    )
    previous_material = str(
        active_item.get("material_type") or active_item.get("entity_type") or "material"
    )
    material_type = (
        explicit_material.group(1).lower().replace(" ", "_")
        if explicit_material
        else previous_material
    )
    if corrected_week == previous_week and material_type == previous_material:
        return None
    corrected = dict(active_item)
    corrected.update(
        {
            "week": corrected_week,
            "entity_type": material_type,
            "material_type": material_type,
            "title": "",
        }
    )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=(
            f"The student corrected the active course reference from {previous_week} to "
            f"{corrected_week} {material_type}. Retrieve only the corrected week before "
            "committing a replacement active course item."
        ),
        memory_context={
            "recent_message_count": len(recent_messages),
            "course_reference_triggered": True,
            "course_reference_resolved": True,
            "course_reference_correction": True,
            "previous_course_entity": active_item,
            "resolved_course_entity": corrected,
        },
        structured_state=state,
        resolution_type="course_entity_correction",
        reason="Resolved an explicit week correction against the active course item.",
    )


def _looks_like_course_correction(query: str) -> bool:
    value = str(query or "")
    return bool(
        re.search(r"\b(?:week\s*|w)\d{1,2}\b", value, re.IGNORECASE)
        and re.search(
            r"\b(?:actually|no|sorry|i meant|rather|make that|change that to|"
            r"i was referring to|instead)\b|\buse\b.{0,40}\binstead\b|"
            r"^\s*not\s+(?:week\s*|w)\d+",
            value,
            re.IGNORECASE,
        )
    )


def _resolve_active_plan_completion(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> MemoryResolution | None:
    referenced = _completion_step_numbers(query)
    plan = _enrich_active_plan(state.get("active_plan"))
    if not referenced or not plan:
        return None
    completed = [step for step in plan.get("steps", []) if int(step.get("index", 0)) in referenced]
    if not completed:
        return None
    next_step = plan.get("next_pending_step")
    if next_step:
        resolved_query = (
            f"The student completed active-plan step {completed[0]['index']}: {completed[0]['action_text']}. "
            f"Continue the same plan with the next pending step {next_step['index']}: {next_step['action_text']}. "
            "Do not recommend the completed step as unfinished."
        )
    else:
        resolved_query = "The student has completed all steps in the active action plan. Acknowledge completion and do not repeat a completed step."
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=resolved_query,
        referenced_items=[{"number": str(step["index"]), "text": str(step["action_text"])} for step in completed],
        memory_context={
            "recent_message_count": len(recent_messages),
            "numbered_reference_kind": "action_plan",
            "completion_reference_resolved": True,
            "completed_steps": completed,
            "pending_steps": plan.get("pending_steps", []),
            "next_pending_step": next_step,
            "active_plan_complete": plan.get("active_plan_complete", False),
        },
        structured_state=state,
        resolution_type="active_plan_progress",
        reason="Resolved explicit completion against the stable active action plan.",
    )


def _resolve_active_plan_numbered_reference(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, Any]],
) -> MemoryResolution | None:
    """Resolve ordinal/number references against the stable active plan first."""

    plan = _enrich_active_plan(state.get("active_plan"))
    if not plan or not _has_explicit_numbered_reference(query):
        return None
    stable_kind = str(state.get("numbered_reference_kind") or "")
    action_related = stable_kind == "action_plan" or bool(
        re.search(rf"\b(?:plan|{PLAN_ITEM_NOUN_PATTERN})\b", query, flags=re.IGNORECASE)
    )
    if not action_related:
        return None
    stable_by_number = {
        str(item.get("number")): dict(item)
        for item in state.get("generic_numbered_referents") or []
        if item.get("number")
    }
    items: list[dict[str, Any]] = []
    for step in plan.get("steps", []):
        number = str(step.get("index", ""))
        item = dict(stable_by_number.get(number) or {})
        item.update({"number": number, "text": str(step.get("action_text", ""))})
        items.append(item)
    referenced_numbers = _referenced_item_numbers(query, items)
    lookup = {int(item["number"]): item for item in items if str(item.get("number", "")).isdigit()}
    referenced_items = [dict(lookup[number]) for number in referenced_numbers if number in lookup]
    if not referenced_items:
        return None
    item_text = "; ".join(f"item {item['number']}: {item['text']}" for item in referenced_items)
    resolved_query = (
        "The student is following up on original active-plan steps: "
        f"{item_text}. Original follow-up query: \"{query}\". "
        "Explain only these original indexed steps without replacing or renumbering the active plan."
    )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=resolved_query,
        referenced_items=referenced_items,
        memory_context={
            "recent_message_count": len(recent_messages),
            "numbered_reference_kind": "action_plan",
            "active_plan_reference": True,
            "available_numbered_items": items,
            "requested_item_numbers": [item["number"] for item in referenced_items],
            "active_plan_source_domain": plan.get("source_domain", ""),
            "active_plan_source_page": plan.get("source_page", ""),
            "active_plan_source_route": plan.get("source_route", ""),
        },
        structured_state=state,
        resolution_type="numbered_reference",
        reason="Resolved the numbered reference against stable active_plan.steps before recent assistant numbering.",
    )


def _resolve_memory_state_query(
    query: str,
    subtype: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, str]],
    *,
    plan_memory_intent: str = "",
) -> MemoryResolution:
    values = {
        "active_plan": _enrich_active_plan(state.get("active_plan")),
        "current_goal": state.get("active_goal") or "",
        "previous_goal": (
            (state.get("goals") or [])[-2]
            if len(state.get("goals") or []) > 1
            else ((state.get("goals") or [""])[-1])
        ),
        "current_goal_and_constraints": {
            "goal": state.get("active_goal") or "",
            "constraints": list(state.get("constraints") or []),
        },
        "current_constraints": list(state.get("constraints") or []),
        "selected_actions": list(state.get("selected_actions") or []),
        "completed_actions": list((state.get("active_plan") or {}).get("completed_steps") or state.get("completed_actions") or []),
        "next_plan_step": (state.get("active_plan") or {}).get("next_pending_step"),
        "previous_correction": list(state.get("corrections") or []),
        "current_course_item": state.get("active_course_item") or {},
    }
    value = values.get(subtype)
    if subtype == "current_goal_and_constraints" and not (
        value.get("goal") or value.get("constraints")
    ):
        value = {}
    prompt_value = value
    if subtype == "current_course_item" and isinstance(value, Mapping):
        prompt_value = {
            key: value.get(key)
            for key in ("week", "entity_type", "material_type", "title")
            if value.get(key)
        }
    resolved_query = (
        f"Answer the direct session-Memory state question for subtype {subtype}. "
        f"Explicit stored value: {prompt_value if prompt_value else 'none explicitly stored'}. "
        "Use session Memory only. Do not use Dashboard activity as a substitute and do not invent missing state."
    )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=resolved_query,
        memory_context={
            "recent_message_count": len(recent_messages),
            "memory_state_query_subtype": subtype,
            "memory_state_value": value,
            "plan_memory_intent": plan_memory_intent,
        },
        structured_state=state,
        resolution_type="memory_state_query",
        reason="Resolved a direct query about explicit session Memory state.",
    )


def _extract_course_entities(text: str, source_turn_id: int) -> list[dict[str, Any]]:
    compact = _compact(text)
    entities: list[dict[str, Any]] = []
    entity_pattern = re.compile(
        r"\b(?:(W\d{1,2})\s+)?(reading|lecture|assessment|reflection prompt|debate task)\b"
        r"(?:\s+(?:called|titled|on|about)?\s*[\"'“‘]?([^.;\n\"”’]{3,100})[\"'”’]?)?",
        flags=re.IGNORECASE,
    )
    for match in entity_pattern.finditer(compact):
        entity_type = match.group(2).lower().replace(" ", "_")
        title = _compact(match.group(3) or "")
        title = re.sub(r"\b(?:and|then|to)\s+(?:write|reply|use|take|add|reflect)\b.*$", "", title, flags=re.I)
        title = _sanitise_course_entity_title(title)
        entity = {
            "entity_type": entity_type,
            "week": (match.group(1) or "").upper(),
            "title": _bounded(title, 140),
            "citation": "",
            "source_turn_id": source_turn_id,
        }
        prefix = compact[max(0, match.start() - 20):match.end() + 20]
        explicitly_titled = bool(re.search(r"[\"'“‘]|\b(?:called|titled|named)\b", prefix, re.I))
        if not explicitly_titled:
            entity["title"] = ""
        if entity["week"] or (entity["title"] and explicitly_titled):
            entities.append(entity)
    return entities[-3:]


def _dedupe_course_entities(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated mentions of the same course entity before ambiguity checks."""

    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in entities:
        entity = dict(raw)
        key = (
            _compact(entity.get("entity_type", "")).casefold(),
            _compact(entity.get("week", "")).upper(),
            _compact(entity.get("title", "")).casefold(),
            _compact(entity.get("citation", "")).casefold(),
        )
        if any(key):
            deduped[key] = entity
    return list(deduped.values())


def _sanitise_course_entity_title(title: str) -> str:
    """Reject generic trailing prose that is not a course-item title."""

    compact = _compact(title)
    if not compact:
        return ""
    if re.match(
        r"^(?:in this session|for this week|before writing|to catch up|in (?:the )?dashboard)\b",
        compact,
        flags=re.IGNORECASE,
    ):
        return ""
    return compact


def _resolve_course_reference(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> MemoryResolution | None:
    explicit_course_reference = bool(COURSE_REFERENCE_RE.search(query))
    vague_single = bool(re.search(r"\bthat one\b", query, flags=re.I))
    if not explicit_course_reference and not (vague_single and not state.get("generic_numbered_referents")):
        return None
    entity = dict(state.get("active_course_item") or {})
    if not entity:
        candidates = list(state.get("course_entity_candidates") or [])
        if len(candidates) > 1:
            return MemoryResolution(
                is_follow_up=True,
                resolved=False,
                original_query=query,
                resolved_query=query,
                memory_context={
                    "recent_message_count": len(recent_messages),
                    "course_reference_triggered": True,
                    "course_reference_resolved": False,
                    "course_entity_candidates": candidates,
                },
                structured_state=state,
                resolution_type="course_entity_ambiguous",
                reason="Multiple recent course entities were equally plausible; clarification is required.",
            )
        return None
    label = " ".join(str(entity.get(key, "")) for key in ("week", "entity_type", "title") if entity.get(key))
    resolved_query = (
        f"The student is referring to the previously selected course item: {label}. "
        f"Original follow-up: \"{query}\". Use this resolved course entity for retrieval and answer only supported content."
    )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=resolved_query,
        memory_context={
            "recent_message_count": len(recent_messages),
            "course_reference_triggered": True,
            "course_reference_resolved": True,
            "resolved_course_entity": entity,
        },
        structured_state=state,
        resolution_type="course_entity_reference",
        reason="Resolved the follow-up to one unambiguous recent course entity.",
    )


def _memory_context_available(state: Mapping[str, Any] | None) -> bool:
    state = state or {}
    return any(
        bool(state.get(field))
        for field in (
            "active_goal",
            "constraints",
            "selected_actions",
            "completed_actions",
            "corrections",
            "active_plan",
            "active_course_item",
            "course_entity_candidates",
            "generic_numbered_referents",
        )
    )


def _resolve_structured_continuity(
    query: str,
    state: dict[str, Any],
    recent_messages: list[dict[str, str]],
    *,
    enable_p2a_extensions: bool = True,
) -> MemoryResolution | None:
    """Resolve plan/goal continuity when explicit session state is available."""

    continuity_re = STRUCTURED_CONTINUITY_RE if enable_p2a_extensions else BASELINE_STRUCTURED_CONTINUITY_RE
    if not continuity_re.search(query):
        return None
    has_prior_state = bool(
        state.get("active_goal")
        or state.get("constraints")
        or state.get("selected_actions")
        or state.get("completed_actions")
        or state.get("corrections")
        or (enable_p2a_extensions and state.get("active_plan"))
    )
    if not has_prior_state or not recent_messages:
        return None

    state_text = _format_structured_state(state)
    active_plan = _enrich_active_plan(state.get("active_plan"))
    next_step = active_plan.get("next_pending_step") if active_plan else None
    referenced_items = []
    memory_context: dict[str, Any] = {"recent_message_count": len(recent_messages)}
    if next_step:
        referenced_items = [
            {
                "number": str(next_step.get("index", "")),
                "text": str(next_step.get("action_text", "")),
                "origin_query_type": str(active_plan.get("source_query_type") or ""),
                "origin_route": str(active_plan.get("source_route") or ""),
                "origin_evidence_domain": str(active_plan.get("source_domain") or ""),
            }
        ]
        memory_context.update(
            {
                "numbered_reference_kind": "action_plan",
                "plan_memory_intent": "plan_progression",
                "next_pending_step": next_step,
            }
        )
    resolved_query = (
        "The student is continuing a previous learning goal or plan. "
        f"Current query: \"{query}\". Explicit remembered session state: {state_text}. "
        "Answer the current query without repeating actions already marked completed. "
        "Respect explicit constraints and use the newest correction when details conflict."
    )
    return MemoryResolution(
        is_follow_up=True,
        resolved=True,
        original_query=query,
        resolved_query=resolved_query,
        referenced_items=referenced_items,
        memory_context=memory_context,
        structured_state=state,
        resolution_type="structured_session_state",
        reason="Resolved follow-up from explicit goal, plan, constraint, progress, or correction state.",
    )


def _format_structured_state(state: Mapping[str, Any] | None) -> str:
    if not state:
        return ""
    parts: list[str] = []
    if state.get("active_goal"):
        parts.append(f"active goal={state['active_goal']}")
    constraints = list(state.get("constraints") or [])
    if constraints:
        parts.append("constraints=" + " | ".join(map(str, constraints)))
    actions = list(state.get("selected_actions") or [])
    if actions:
        rendered = []
        for action in actions:
            if isinstance(action, Mapping):
                rendered.append(f"{action.get('text', '')} [{action.get('status', 'proposed')}]")
            else:
                rendered.append(str(action))
        parts.append("previous actions=" + " | ".join(rendered))
    completions = list(state.get("completed_actions") or [])
    if completions:
        parts.append("reported progress=" + " | ".join(map(str, completions)))
    corrections = list(state.get("corrections") or [])
    if corrections:
        parts.append("newest corrections=" + " | ".join(map(str, corrections)))
    pages = list(state.get("relevant_pages") or [])
    if pages:
        parts.append("pages=" + ", ".join(map(str, pages)))
    recommendations = _normalise_recommendations(state.get("recent_numbered_recommendations") or [])
    if recommendations:
        parts.append(
            "recent numbered recommendations="
            + " | ".join(f"{item['number']}. {item['text']}" for item in recommendations)
        )
    active_plan = state.get("active_plan") or {}
    if active_plan:
        rendered_steps = [
            f"{step.get('index')}. {step.get('action_text')} [{step.get('status', 'pending')}]"
            for step in active_plan.get("steps", [])
        ]
        if rendered_steps:
            parts.append("active action plan=" + " | ".join(rendered_steps))
    course_item = state.get("active_course_item") or {}
    if course_item:
        parts.append(
            "active course item="
            + " ".join(
                str(value)
                for value in (
                    course_item.get("week"),
                    course_item.get("entity_type"),
                    course_item.get("title"),
                )
                if value
            )
        )
    return "; ".join(part for part in parts if part.strip())


def _has_explicit_numbered_reference(query: str) -> bool:
    q = str(query or "")
    return bool(
        re.search(
            rf"\b{PLAN_ITEM_NOUN_PATTERN}(?:\s+number)?\s*{PLAN_NUMBER_PATTERN}\b",
            q,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b\d{1,2}\s*(?:and|&|,)\s*\d{1,2}\b", q)
        or re.search(
            rf"\b(?:{PLAN_NUMBER_PATTERN}|last)\s+(?:one|{PLAN_ITEM_NOUN_PATTERN})\b",
            q,
            flags=re.IGNORECASE,
        )
    )


def _extract_unnumbered_action(text: str) -> str:
    """Keep one explicit assistant recommendation without inventing a plan."""

    sentences = re.split(r"(?<=[.!?])\s+", _compact(text))
    action_re = re.compile(
        r"\b(?:start (?:by|with)|next step|you (?:can|could|should)|i (?:recommend|suggest)|"
        r"try|focus on|revisit|review|watch|write|reply|choose)\b",
        flags=re.IGNORECASE,
    )
    for sentence in sentences:
        if action_re.search(sentence):
            return _bounded(sentence)
    return ""


def _normalise_recommendations(items: Sequence[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        number = _compact(item.get("number", ""))
        text = _compact(item.get("text", ""))
        if number and text:
            record = dict(item)
            record["number"] = number
            record["text"] = strip_structural_markdown(text)
            out.append(record)
    return out


def _merge_actions(actions: Sequence[Mapping[str, Any] | Any], completions: Sequence[str]) -> list[dict[str, Any]]:
    """Dedupe actions while preserving the strongest explicit progress status."""

    priority = {"proposed": 1, "committed": 2, "completed": 3, "superseded": 4}
    by_text: dict[str, dict[str, Any]] = {}
    for raw_action in actions:
        if not isinstance(raw_action, Mapping):
            continue
        action = dict(raw_action)
        text = _compact(action.get("text", ""))
        if not text:
            continue
        action["text"] = text
        action["number"] = str(action.get("number", ""))
        action["status"] = str(action.get("status", "proposed"))
        if any(_texts_refer_to_same_action(text, completion) for completion in completions):
            action["status"] = "completed"
        key = text.casefold()
        previous = by_text.get(key)
        if previous is None or priority.get(action["status"], 0) >= priority.get(previous.get("status", ""), 0):
            by_text[key] = action
    return list(by_text.values())


def _apply_explicit_corrections(actions: list[dict[str, Any]], corrections: Sequence[str]) -> list[dict[str, Any]]:
    """Apply unambiguous W-number corrections without inferring learner intent."""

    corrected = [dict(action) for action in actions]
    for correction in corrections:
        pair = _unambiguous_week_correction(correction)
        if not pair:
            continue
        replacement, superseded = pair
        for action in corrected:
            if re.search(rf"\b{re.escape(superseded)}\b", action.get("text", ""), flags=re.IGNORECASE):
                action["text"] = re.sub(
                    rf"\b{re.escape(superseded)}\b",
                    replacement.upper(),
                    action["text"],
                    flags=re.IGNORECASE,
                )
                action["corrected_by"] = _bounded(correction)
    return corrected


def _unambiguous_week_correction(correction: str) -> tuple[str, str] | None:
    matches = re.findall(
        r"\b(?:i meant\s+)?(w\d+)\s+(?:rather than|instead of)\s+(w\d+)\b",
        str(correction),
        flags=re.IGNORECASE,
    )
    if len(matches) != 1:
        return None
    replacement, superseded = matches[0]
    if replacement.casefold() == superseded.casefold():
        return None
    return replacement.upper(), superseded.upper()


def _apply_week_corrections_to_text(text: str, corrections: Sequence[str]) -> str:
    corrected = str(text or "")
    for correction in corrections:
        pair = _unambiguous_week_correction(correction)
        if not pair:
            continue
        replacement, superseded = pair
        corrected = re.sub(
            rf"\b{re.escape(superseded)}\b",
            replacement,
            corrected,
            flags=re.IGNORECASE,
        )
    return corrected


def _apply_week_corrections_to_course_item(
    course_item: Mapping[str, Any] | None,
    corrections: Sequence[str],
) -> dict[str, Any]:
    corrected = dict(course_item or {})
    if not corrected:
        return {}
    for correction in corrections:
        pair = _unambiguous_week_correction(correction)
        if not pair:
            continue
        replacement, superseded = pair
        if str(corrected.get("week", "")).casefold() == superseded.casefold():
            corrected["week"] = replacement
            # A title associated only with the superseded week is not evidence
            # for the corrected week. Keep the entity type and clear the title.
            corrected["title"] = ""
            corrected["corrected_by"] = _bounded(correction)
        elif corrected.get("title"):
            corrected["title"] = _apply_week_corrections_to_text(
                str(corrected["title"]), [correction]
            )
    return corrected


def _apply_week_corrections_to_plan(
    plan: Mapping[str, Any] | None,
    corrections: Sequence[str],
) -> dict[str, Any]:
    corrected = _enrich_active_plan(plan)
    if not corrected:
        return {}
    corrected["goal"] = _apply_week_corrections_to_text(
        str(corrected.get("goal", "")), corrections
    )
    steps = []
    for step in corrected.get("steps", []):
        updated = dict(step)
        original = str(updated.get("action_text", ""))
        updated["action_text"] = _apply_week_corrections_to_text(original, corrections)
        if updated["action_text"] != original:
            updated["corrected_by"] = next(
                (
                    _bounded(correction)
                    for correction in reversed(list(corrections))
                    if _unambiguous_week_correction(correction)
                ),
                "",
            )
        steps.append(updated)
    corrected["steps"] = steps
    return _enrich_active_plan(corrected)


def _apply_week_corrections_to_numbered_items(
    items: Sequence[Mapping[str, Any]],
    corrections: Sequence[str],
) -> list[dict[str, Any]]:
    corrected: list[dict[str, Any]] = []
    for item in items:
        if not item.get("number") or not item.get("text"):
            continue
        record = dict(item)
        record["number"] = str(item.get("number", ""))
        record["text"] = _apply_week_corrections_to_text(str(item.get("text", "")), corrections)
        corrected.append(record)
    return corrected


def _memory_updates(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    tracked = [
        "active_goal",
        "goals",
        "constraints",
        "selected_actions",
        "completed_actions",
        "corrections",
        "relevant_pages",
        "recent_numbered_recommendations",
        "generic_numbered_referents",
        "numbered_reference_kind",
        "active_plan",
        "active_course_item",
        "course_entity_candidates",
    ]
    updated = [field for field in tracked if before.get(field) != after.get(field)]
    return {
        "updated_fields": updated,
        "state_changed": bool(updated),
        "active_plan_updated": "active_plan" in updated,
    }


def _texts_refer_to_same_action(action: str, completion: str) -> bool:
    stop = {
        "the", "and", "that", "this", "with", "from", "have", "finished", "completed",
        "done", "watched", "reviewed", "read", "submitted", "replied", "wrote", "your",
        "you", "one", "step", "action", "then", "next",
    }
    action_tokens = {token for token in re.findall(r"[a-z0-9]+", action.lower()) if token not in stop and len(token) >= 2}
    completion_tokens = {
        token for token in re.findall(r"[a-z0-9]+", completion.lower()) if token not in stop and len(token) >= 2
    }
    if not action_tokens or not completion_tokens:
        return False
    overlap = action_tokens & completion_tokens
    if any(re.fullmatch(r"w\d+", token) for token in overlap):
        return True
    return len(overlap) >= 2 or len(overlap) / min(len(action_tokens), len(completion_tokens)) >= 0.5


def _dedupe_text(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        compact = _compact(value)
        key = compact.casefold()
        if not compact or key in seen:
            continue
        seen.add(key)
        out.append(compact)
    return out


def _dedupe_actions(actions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for action in actions:
        text = _compact(action.get("text", ""))
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(dict(action))
    return out


def _bounded(text: str, limit: int = 240) -> str:
    compact = _compact(text)
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _normalise_role(role: str) -> str:
    role_l = str(role or "").strip().lower()
    if role_l in {"assistant", "ai", "bot", "system_assistant"}:
        return "assistant"
    if role_l in {"user", "student", "human"}:
        return "user"
    if role_l == "system":
        return "system"
    return role_l or "unknown"


def _most_recent_numbered_assistant_turn(turns: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    for turn in reversed(turns):
        if turn.get("role") != "assistant":
            continue
        payload = turn.get("structured_payload")
        if isinstance(payload, Mapping):
            annotated = _normalise_recommendations(payload.get("numbered_referents") or [])
            if annotated:
                return turn, annotated
        items = extract_numbered_items(turn.get("content", ""))
        if items:
            return turn, items
    return {}, []


def _referenced_item_numbers(query: str, items: list[dict[str, str]]) -> list[int]:
    q = str(query or "").lower()
    numbers: list[int] = []

    for match in re.finditer(
        rf"\b{PLAN_ITEM_NOUN_PATTERN}(?:\s+number)?\s*(\d{{1,2}})\b", q
    ):
        numbers.append(int(match.group(1)))

    for match in re.finditer(r"\b(\d{1,2})\s*(?:and|&|,)\s*(\d{1,2})\b", q):
        numbers.extend([int(match.group(1)), int(match.group(2))])

    if not numbers:
        for match in re.finditer(
            r"\b(?:do|doing|suggest|try|explain|expand|about|on|for)\b[^\n]{0,40}?\b(\d{1,2})\b",
            q,
        ):
            numbers.append(int(match.group(1)))

    for ordinal, number in ORDINAL_TO_NUMBER.items():
        if re.search(
            rf"\b{re.escape(ordinal)}\s+(?:one|{PLAN_ITEM_NOUN_PATTERN})\b", q
        ) or re.search(
            rf"\b{PLAN_ITEM_NOUN_PATTERN}(?:\s+number)?\s+{re.escape(ordinal)}\b", q
        ):
            numbers.append(number)

    if re.search(rf"\blast\s+(?:one|{PLAN_ITEM_NOUN_PATTERN})\b", q):
        item_numbers = [int(item["number"]) for item in items if item["number"].isdigit()]
        if item_numbers:
            numbers.append(max(item_numbers))

    return _dedupe_ints(numbers)


def _vague_reference_mode(query: str) -> str:
    """Return how a vague phrase should map to numbered items.

    Standalone ``this`` and ``that`` are intentionally excluded to avoid false
    positives such as "What does this metric mean?". Plural/list phrases map to
    all items. Singular phrases such as "this point" map only when there is one
    available item, which is checked by the caller.
    """

    q = str(query or "").lower()
    if re.search(
        r"\b(those steps|these steps|the previous suggestion|previous suggestion|previous point|above suggestion|last suggestion)\b",
        q,
    ):
        return "all"
    if re.search(r"\b(this|that)\s+(one|point|step|item|recommendation)\b", q):
        return "single"
    return ""


def _dedupe_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
