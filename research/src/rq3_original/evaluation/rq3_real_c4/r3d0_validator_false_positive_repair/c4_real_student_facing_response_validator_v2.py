#!/usr/bin/env python3
"""Blind mechanical format validator for C4 REAL student-facing answer_text.

V2 narrows V1's serialized-key false positive.  It evaluates format only and
does not inspect condition, mode, route, expected outcome, factual quality, or
response quality.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Final


VALID_STUDENT_FACING_RESPONSE: Final = "VALID_STUDENT_FACING_RESPONSE"
TRIVIAL_NONANSWER: Final = "TRIVIAL_NONANSWER"
SERIALIZED_JSON_OBJECT_OR_ARRAY: Final = "SERIALIZED_JSON_OBJECT_OR_ARRAY"
RAW_INTERNAL_STRUCTURE: Final = "RAW_INTERNAL_STRUCTURE"
OTHER_NON_STUDENT_FACING_FORMAT: Final = "OTHER_NON_STUDENT_FACING_FORMAT"

VALIDATOR_STATUSES: Final = (
    VALID_STUDENT_FACING_RESPONSE,
    TRIVIAL_NONANSWER,
    SERIALIZED_JSON_OBJECT_OR_ARRAY,
    RAW_INTERNAL_STRUCTURE,
    OTHER_NON_STUDENT_FACING_FORMAT,
)

# These snake_case names are strongly diagnostic when they occur in a
# structurally key-like position.  The generic English word "evidence" is
# intentionally absent: its presence before a colon is not proof of a raw
# internal structure.
STRONG_INTERNAL_FIELD_KEYS: Final = (
    "action_steps",
    "recommended_action",
    "student_state",
    "main_issue",
    "next_steps",
    "next_step",
    "availability_notes",
    "supporting_evidence",
    "reflection_summary",
    "activity_summary",
    "data_summary",
    "gaps_identified",
    "planning_support",
)

_FENCED_BLOCK_RE = re.compile(
    r"\A```(?:json|javascript|js|python|yaml|yml|xml)?\s*\n(?P<body>.*)\n```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_XML_DOCUMENT_RE = re.compile(
    r"\A\s*(?:<\?xml[^>]*\?>\s*)?<([A-Za-z_][\w:.-]*)(?:\s[^>]*)?(?:/>|>.*</\1>)\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_STRONG_INTERNAL_FIELD_LINE_RE = re.compile(
    r"(?mi)^[ \t]*(?:[-*+][ \t]+)?[\"']?(?:"
    + "|".join(re.escape(key) for key in STRONG_INTERNAL_FIELD_KEYS)
    + r")[\"']?[ \t]*:"
)


def _unwrap_single_code_fence(value: str) -> tuple[str, bool]:
    match = _FENCED_BLOCK_RE.fullmatch(value.strip())
    if match is None:
        return value.strip(), False
    return match.group("body").strip(), True


def _parsed_container(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    return isinstance(parsed, (dict, list))


def _python_container(value: str) -> bool:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return False
    return isinstance(parsed, (dict, list))


def _has_strong_internal_field_lines(value: str) -> bool:
    return _STRONG_INTERNAL_FIELD_LINE_RE.search(value) is not None


def classify_answer_text(answer_text: object) -> str:
    """Return exactly one deterministic, blind mechanical format status."""

    if not isinstance(answer_text, str):
        return OTHER_NON_STUDENT_FACING_FORMAT

    stripped = answer_text.strip()
    if not stripped:
        return TRIVIAL_NONANSWER

    candidate, was_fenced = _unwrap_single_code_fence(stripped)

    if _parsed_container(candidate):
        return SERIALIZED_JSON_OBJECT_OR_ARRAY

    if _python_container(candidate):
        return RAW_INTERNAL_STRUCTURE

    if not any(character.isalpha() for character in stripped):
        return TRIVIAL_NONANSWER

    if _has_strong_internal_field_lines(candidate):
        return RAW_INTERNAL_STRUCTURE

    if candidate.startswith(("{", "[")):
        return OTHER_NON_STUDENT_FACING_FORMAT

    if was_fenced:
        return OTHER_NON_STUDENT_FACING_FORMAT

    if _XML_DOCUMENT_RE.fullmatch(candidate):
        return OTHER_NON_STUDENT_FACING_FORMAT

    return VALID_STUDENT_FACING_RESPONSE


def validate_answer_text(answer_text: object) -> str:
    """Public alias used by the continuation runner and offline tests."""

    return classify_answer_text(answer_text)


if __name__ == "__main__":
    raise SystemExit("Import this module; it has no standalone execution mode.")
