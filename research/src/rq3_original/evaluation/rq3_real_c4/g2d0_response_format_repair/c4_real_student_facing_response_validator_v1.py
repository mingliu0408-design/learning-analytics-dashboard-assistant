#!/usr/bin/env python3
"""Mechanical student-facing answer_text validator.

This module deliberately evaluates format only. It does not evaluate factual
correctness, relevance, helpfulness, personalisation, actionability, evidence,
or expected condition performance.
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

INTERNAL_FIELD_KEYS: Final = (
    "action_steps",
    "recommended_action",
    "student_state",
    "main_issue",
    "next_steps",
    "next_step",
    "evidence",
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
    r"\A\s*<([A-Za-z_][\w:.-]*)(?:\s[^>]*)?>.*</\1>\s*\Z", re.DOTALL
)
_SERIALIZED_KEY_RE = re.compile(
    r"(?m)(?:[\"']?)([A-Za-z_][A-Za-z0-9_]*)(?:[\"']?)\s*:"
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


def _has_internal_serialized_keys(value: str) -> bool:
    serialized_keys = {match.group(1) for match in _SERIALIZED_KEY_RE.finditer(value)}
    return bool(serialized_keys.intersection(INTERNAL_FIELD_KEYS))


def classify_answer_text(answer_text: object) -> str:
    """Return exactly one frozen mechanical format status."""

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

    if _has_internal_serialized_keys(candidate):
        return RAW_INTERNAL_STRUCTURE

    if candidate.startswith(("{", "[")):
        return OTHER_NON_STUDENT_FACING_FORMAT

    if was_fenced:
        return OTHER_NON_STUDENT_FACING_FORMAT

    if _XML_DOCUMENT_RE.fullmatch(candidate):
        return OTHER_NON_STUDENT_FACING_FORMAT

    return VALID_STUDENT_FACING_RESPONSE


def validate_answer_text(answer_text: object) -> str:
    """Public alias used by the generation runner and offline package tests."""

    return classify_answer_text(answer_text)


if __name__ == "__main__":
    raise SystemExit("Import this module; it has no standalone execution mode.")
