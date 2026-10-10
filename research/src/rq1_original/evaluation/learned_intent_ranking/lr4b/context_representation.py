"""Pure deterministic context representations frozen by RQ1-A."""

from __future__ import annotations

import hashlib
import unicodedata

from .contract_schema import MODEL_INPUT_FIELDS, QUERY_ONLY_V1, STRUCTURED_CONTEXT_V1


STRUCTURED_CONTEXT_TEMPLATE = (
    "[QUESTION_ANCHOR]\n{question_anchor}\n"
    "[PREVIOUS_TURNS]\n{previous_turns}\n"
    "[CURRENT_STUDENT_UTTERANCE]\n{current_student_utterance}"
)


def decode_utf8_with_optional_bom(value: bytes) -> str:
    """Decode UTF-8 input while accepting and removing one leading BOM."""

    if not isinstance(value, bytes):
        raise TypeError("source bytes are required")
    return value.decode("utf-8-sig")


def normalise_source_field(value: str) -> str:
    """Apply only NFC, newline canonicalisation, and edge trimming."""

    if not isinstance(value, str):
        raise TypeError("source field must be text")
    newline_normalised = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", newline_normalised).strip()


def _require_non_empty(field_name: str, value: str) -> str:
    normalised = normalise_source_field(value)
    if not normalised:
        raise ValueError(f"required context field is missing: {field_name}")
    return normalised


def build_query_only_representation(query: str) -> str:
    """Return the canonical current-query-only model input."""

    return _require_non_empty("query", query)


def build_structured_context_representation(
    *,
    question_anchor_for_review: str,
    previous_turns_for_review: str,
    utterance_for_review: str,
) -> str:
    """Build the fixed three-field structured representation, fail closed."""

    question_anchor = _require_non_empty(
        "question_anchor_for_review", question_anchor_for_review
    )
    previous_turns = _require_non_empty(
        "previous_turns_for_review", previous_turns_for_review
    )
    current_student_utterance = _require_non_empty(
        "utterance_for_review", utterance_for_review
    )
    return STRUCTURED_CONTEXT_TEMPLATE.format(
        question_anchor=question_anchor,
        previous_turns=previous_turns,
        current_student_utterance=current_student_utterance,
    )


def representation_sha256(representation: str) -> str:
    if not isinstance(representation, str) or not representation:
        raise ValueError("non-empty representation text is required")
    return hashlib.sha256(representation.encode("utf-8")).hexdigest()


def model_input_fields_for_mode(context_mode: str) -> tuple[str, ...]:
    try:
        return MODEL_INPUT_FIELDS[context_mode]
    except KeyError as exc:
        raise ValueError("unknown context mode") from exc


def truncation_contract() -> dict[str, object]:
    """Return the preregistered principle; no truncation is performed here."""

    return {
        "actual_truncation_performed": False,
        "current_student_utterance": "PRESERVE_IN_FULL",
        "question_anchor_priority": "ABOVE_OLDER_PREVIOUS_TURNS",
        "previous_turns_truncation_edge": "OLDEST_EDGE_ONLY",
        "retain_most_recent_previous_turns": True,
        "silent_tokenizer_default_truncation": False,
        "implementation_gate": "RQ1_B_TOKEN_LENGTH_PREFLIGHT_AND_INDEPENDENT_TEST",
    }
