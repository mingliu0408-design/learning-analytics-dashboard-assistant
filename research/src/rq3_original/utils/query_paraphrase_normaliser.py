"""Small allowlisted natural-query normalisation for C_FULL orchestration.

The rules in this module are deliberately lexical and auditable.  They do not
use embeddings, fuzzy matching, or a model classifier, and they never mutate
the caller's preserved original query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

from utils.dashboard_domain_resolver import (
    detect_explicit_dashboard_domains,
    is_explicit_whole_dashboard_query,
)


@dataclass(frozen=True)
class QueryNormalisation:
    original_query: str
    normalised_query: str
    applied_rules: list[dict[str, str]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


WEEK_CARDINALS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
WEEK_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
}
TIME_CARDINALS = {
    **WEEK_CARDINALS,
    "fifteen": 15,
    "twenty": 20,
    "twenty-five": 25,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
}
NUMBER_ONES = {
    "zero": 0,
    **WEEK_CARDINALS,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
NUMBER_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
ORDINAL_ONES = {
    **WEEK_ORDINALS,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
}
ORDINAL_TENS = {
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}
NUMBERLIKE_MISSPELLINGS = frozenset({"fourty", "threeteen", "threeteenth"})


PLAN_RECALL_RE = re.compile(
    r"^\s*(?:(?:can|could) you\s+)?(?:show (?:me\s+)?(?:that|the|my) plan(?: again)?|"
    r"repeat (?:that|the|my) plan|"
    r"(?:can you\s+)?repeat (?:that|the|my) plan|"
    r"remind me what i need to do|"
    r"(?:go over|go through|walk me through) (?:that|the|my) plan again|"
    r"what were the actions again|what am i supposed to do again)\s*[?.!]*\s*$",
    flags=re.IGNORECASE,
)

OVERVIEW_GLOBAL_PRIORITY_RE = re.compile(
    r"\b(?:where is my biggest engagement gap|what is my weakest area|"
    r"which area is falling behind most|where should i focus my effort)\b",
    flags=re.IGNORECASE,
)


def _record(
    rules: list[dict[str, str]],
    *,
    rule: str,
    before: str,
    after: str,
) -> None:
    if before != after:
        rules.append({"rule": rule, "from": before, "to": after})


def _sub_rule(
    value: str,
    pattern: str,
    replacement: str,
    rules: list[dict[str, str]],
    rule: str,
) -> str:
    match = re.search(pattern, value, flags=re.IGNORECASE)
    if not match:
        return value
    revised = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    _record(rules, rule=rule, before=match.group(0), after=replacement)
    return revised


def _week_diagnostic(
    expression: str,
    number: int | None,
    *,
    applied: bool,
    supported: bool | None = None,
    reason: str = "",
) -> dict[str, Any]:
    supported_week = (
        bool(number is not None and 1 <= number <= 12)
        if supported is None
        else bool(supported)
    )
    diagnostic: dict[str, Any] = {
        "detected_week_expression": expression,
        "parsed_week_number": number,
        "supported_week": supported_week,
        "normalisation_applied": applied,
    }
    if reason:
        diagnostic["reason"] = reason
    return diagnostic


def detect_number_shaped_week_guard_candidates(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> list[str]:
    """Return conservative explicit-week spans for C_FULL defense in depth.

    This deliberately uses a separate, shape-based detector rather than the
    normalizer's grammar. It is not a parser and never makes syntax supported.
    """

    value = str(query or "")
    digit_body = (
        r"[+\-]?\d+(?:(?:\s*(?:\.\.|[+;,.'’_\-–—/])\s*\d+)|"
        r"(?:\s+(?:to|through|and|or)\s+(?:W\s*)?\d+)|"
        r"(?:\s*&\s*(?:W\s*)?\d+))*(?:st|nd|rd|th)?"
    )
    roman_alias = r"(?-i:[IVX]+)" if enable_p2a_extensions else r"[IVX]+"
    number_alias = (
        r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
        r"twelve|thirteen|fourteen|fifteen|twenty|thirty|forty|fourty|"
        rf"fifty|sixty|seventy|eighty|ninety|threeteen|{roman_alias})"
    )
    patterns = (
        rf"\b(?:weeks?|wk)\s*(?:(?:number|no\.?)\s*)?"
        rf"(?:[:.#/\-–—]|\(|\[)?\s*(?:{digit_body}|{number_alias})\s*[\)\]]?",
        rf"\bW(?![A-Za-z])\s*(?:[:.#/_\-–—]|\(|\[)?\s*(?:{digit_body}|{number_alias})\s*[\)\]]?",
        rf"\b{digit_body}\s+weeks?\b",
    )
    found: list[tuple[int, int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            expression = match.group(0).rstrip()
            found.append((match.start(), match.start() + len(expression), expression))
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(found, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(candidate[0] < item[1] and item[0] < candidate[1] for item in selected):
            continue
        selected.append(candidate)
    selected.sort()
    return [expression for _start, _end, expression in selected]


def unresolved_explicit_week_guard_candidate(
    query: str,
    diagnostics: list[dict[str, Any]],
    applied_rules: list[dict[str, str]],
    *,
    enable_p2a_extensions: bool = True,
) -> str:
    """Return a candidate that must force clarification, or an empty string."""

    if any(item.get("supported_week") is False for item in diagnostics):
        return ""
    supported = [item for item in diagnostics if item.get("supported_week") is True]
    correction = any(item.get("rule") == "course_correction_marker" for item in applied_rules)
    correction = correction or bool(enable_p2a_extensions and
        re.search(
            r"\b(?:correction|actually|i meant|i was referring to|rather than|instead of)\b",
            str(query or ""),
            flags=re.IGNORECASE,
        )
    )
    candidates = detect_number_shaped_week_guard_candidates(
        query,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    if not candidates:
        return ""
    if not supported:
        return candidates[0]
    if len(supported) > 1:
        return "" if correction else candidates[0]
    if len(candidates) > 1 and not correction:
        return candidates[0]

    expression = str(supported[0].get("detected_week_expression") or "")
    match = re.search(re.escape(expression), str(query or ""), flags=re.IGNORECASE)
    if not match:
        return candidates[0]
    continuation = re.match(
        r"(?:\s*[,.'’_]\s*\d+|\s*[-–—/]\s*(?:W\s*)?\d+|"
        r"\s+(?:to|through|and|or)\s+(?:W\s*)?\d+|"
        r"\s*&\s*(?:W\s*)?\d+|(?:st|nd|rd|th)\b|"
        r"[eE][+-]?\d+|[a-z]+)",
        str(query or "")[match.end() :],
        flags=re.IGNORECASE,
    )
    return candidates[0] if continuation else ""


def _normalise_weeks(
    value: str,
    rules: list[dict[str, str]],
    diagnostics: list[dict[str, Any]],
    *,
    enable_p2a_extensions: bool = True,
) -> str:
    number_words = {
        *NUMBER_ONES,
        *NUMBER_TENS,
        *ORDINAL_ONES,
        *ORDINAL_TENS,
        "hundred",
        "hundredth",
        "thousand",
        "thousandth",
    }
    word = "|".join(sorted(map(re.escape, number_words), key=len, reverse=True))
    word_sequence = rf"(?:{word})(?:(?:\s+(?:and\s+)?|-(?=[a-z]))(?:{word}))*"
    candidates: list[dict[str, Any]] = []

    def collect(
        pattern: str,
        kind: str,
        *,
        predicate: Any = None,
    ) -> None:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            token = match.group(1)
            if predicate is not None and not predicate(token, match):
                continue
            candidates.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "expression": match.group(0),
                    "token": token,
                    "kind": kind,
                }
            )

    def looks_number_like_token(token: str) -> bool:
        """Conservatively recognise a single malformed number-shaped token."""

        lowered = token.casefold()
        compact = lowered.replace("-", "")
        established = {
            *NUMBER_ONES,
            *NUMBER_TENS,
            *ORDINAL_ONES,
            *ORDINAL_TENS,
            "hundred",
            "hundredth",
            "thousand",
            "thousandth",
        }
        if lowered in established or lowered in NUMBERLIKE_MISSPELLINGS:
            return True
        if lowered.endswith("ish") and lowered[:-3].rstrip("-") in established:
            return True
        if compact in NUMBERLIKE_MISSPELLINGS:
            return True
        for scale in ("hundred", "hundredth", "thousand", "thousandth"):
            if compact.endswith(scale) and compact[: -len(scale)] in established:
                return True
        return False

    def ordinal_word_candidate(token: str, _match: Any) -> bool:
        last = token.casefold().replace("-", " ").split()[-1]
        if last in {*ORDINAL_ONES, *ORDINAL_TENS, "hundredth", "thousandth"}:
            return True
        # Preserve the established fail-closed handling for bare compound
        # candidates, but do not reinterpret explicit duration constraints.
        escaped = re.escape(token)
        duration = re.search(
            rf"\b(?:have|has|had|within|shorten(?:\s+the\s+plan)?\s+to|"
            rf"reduce(?:\s+the\s+plan)?\s+to)\s+{escaped}\s+week\b|"
            rf"\b{escaped}\s+week\s+(?:to|of)\b",
            value,
            flags=re.IGNORECASE,
        )
        compound_duration_noun = bool(enable_p2a_extensions and
            "-" in _match.group(0)
            and re.match(
                r"\s+(?:routine|plan|schedule|window|period|timescale|deadline)\b",
                value[_match.end() :],
                flags=re.IGNORECASE,
            )
        )
        return not duration and not compound_duration_noun

    def malformed_before_week_candidate(token: str, _match: Any) -> bool:
        if not looks_number_like_token(token):
            return False
        lowered = token.casefold()
        ordinal_shaped = lowered.endswith(("st", "nd", "rd", "th"))
        course_context = bool(
            re.search(
                r"\b(?:course|lecture|topics?|reading|materials?|module|content)\b",
                value,
                flags=re.IGNORECASE,
            )
        )
        return ordinal_shaped or course_context

    # Stage A collects broad, complete explicit-week candidates without
    # normalising them. Longer punctuation/alias candidates suppress any
    # overlapping strict prefix during the span-selection pass below.
    collect(r"\bweek\s+([0-9]+)\b", "numeric")
    collect(r"\bW([0-9]+)\b", "canonical_numeric")
    collect(rf"\bweek\s+({word_sequence})(?:['’]s)?\b", "cardinal")
    collect(
        rf"\b(?:the\s+)?({word_sequence})(?:\s+|-)week\b",
        "ordinal",
        predicate=ordinal_word_candidate,
    )

    numeric_variant = (
        r"(?:[0-9]+(?:\s*[,\'’_]\s*[0-9]+)+|"
        r"[0-9]+(?:\s+[0-9]+)+|[0-9]+\.[0-9]+|"
        r"[0-9]+[eE][+-]?[0-9]+)"
    )
    multiweek_joiner = r"(?:\+|;|\.\.|-|–|—|/|\bto\b|\bthrough\b|\band\b|\bor\b|&)"
    collect(
        rf"\bweeks?\s+([0-9]+\s*{multiweek_joiner}\s*(?:W\s*)?[0-9]+)\b",
        "multiweek",
    )
    collect(
        rf"\b(W[0-9]+\s*{multiweek_joiner}\s*W?[0-9]+)\b",
        "multiweek",
    )
    collect(
        rf"\b([0-9]+\s*{multiweek_joiner}\s*[0-9]+)\s+weeks\b",
        "multiweek",
    )
    collect(rf"\bweek\s+({numeric_variant})\b", "unsupported_numeric")
    collect(r"\bweek\s+([+-][0-9]+)\b", "unsupported_numeric")
    collect(r"\bweek\s*#\s*([0-9]+)\b", "unsupported_numeric")
    collect(
        r"\bweek\s+(?:number|no\.?)(?:\s*:\s*|\s+|\s*#\s*)([+-]?[0-9]+)\b",
        "unsupported_numeric",
    )
    collect(
        r"\b(?:week|weeks|wk)\s*(?:[:./\-–—#]|\(\s*|\[\s*)([0-9]+)(?:\s*[\)\]])?",
        "unsupported_numeric",
    )
    collect(
        r"\bW\s*(?:[:./_\-–—#]\s*|\(\s*|\[\s*)([0-9]+)(?:\s*[\)\]])?",
        "unsupported_numeric",
    )
    collect(r"\bweek([0-9]+)\b", "unsupported_numeric")
    collect(r"\bW(?:\s+|[-#]\s*)([0-9]+)\b", "unsupported_numeric")
    collect(r"\bwk(?:\s+|[-#]\s*)([0-9]+)\b", "unsupported_numeric")
    collect(
        r"\b([0-9]+(?:\s*[,\'’_]\s*[0-9]+)+)(?:st|nd|rd|th)\s+week\b",
        "numeric_ordinal_formatted",
    )
    collect(r"\b([0-9]+)(?:st|nd|rd|th)\s+week\b", "numeric_ordinal")
    collect(r"\bW([0-9]+)(?:st|nd|rd|th)\b", "numeric_ordinal")
    collect(
        r"\bweek\s+(\d+)\b",
        "unicode_numeric",
        predicate=lambda token, _match: not token.isascii(),
    )
    collect(
        rf"\b(?:wk|W)\s+({word_sequence})\b",
        "alias_word",
    )
    collect(
        rf"\bweek\s+(?:number|no\.?)\s*:?\s*({word_sequence})\b",
        "alias_word",
    )
    collect(r"\b(?:week|W)\s+([IVX]+)\b", "roman_alias")
    collect(r"\bweek\s+([0-9]+[a-z]+)\b", "malformed")
    collect(
        r"\bweek\s+([a-z]+(?:-[a-z]+)?)\b",
        "malformed",
        predicate=lambda token, _match: looks_number_like_token(token),
    )
    collect(
        r"\b([a-z]+(?:-[a-z]+)?)\s+week\b",
        "malformed",
        predicate=malformed_before_week_candidate,
    )

    # A strict candidate is never accepted when number-like continuation
    # follows it. Expanding here makes the diagnostic span cover the complete
    # source expression even if a future broad pattern misses that spelling.
    continuation_re = re.compile(
        r"(?:\s*[,.'’_]\s*\d+|\s*[-–—/]\s*(?:W\s*)?\d+|"
        r"\s*(?:\+|;|\.\.)\s*(?:W\s*)?\d+|"
        r"\s+(?:to|through|and|or)\s+(?:W\s*)?\d+|"
        r"\s*&\s*(?:W\s*)?\d+|(?:st|nd|rd|th)\b|"
        r"[eE][+-]?\d+|[a-z]+)",
        flags=re.IGNORECASE,
    )
    for candidate in candidates:
        if candidate["kind"] not in {"numeric", "canonical_numeric", "cardinal", "ordinal"}:
            continue
        continuation = continuation_re.match(value[int(candidate["end"]) :])
        if not continuation:
            continue
        candidate["end"] = int(candidate["end"]) + continuation.end()
        candidate["expression"] = value[int(candidate["start"]) : int(candidate["end"])]
        candidate["token"] = candidate["expression"]
        candidate["kind"] = "boundary_unsupported"

    # Prefer the longest candidate at one position, then discard overlaps. This
    # makes one source expression produce exactly one diagnostic.
    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item["start"], -(item["end"] - item["start"])),
    ):
        if any(
            candidate["start"] < item["end"] and item["start"] < candidate["end"]
            for item in selected
        ):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: item["start"])

    def parse_cardinal(token: str) -> tuple[int | None, str]:
        lowered = token.casefold()
        if "hundred" in lowered or "thousand" in lowered or " and " in lowered:
            return None, "unparsed_or_out_of_range_week"
        if " " in lowered:
            return None, "unsupported_number_format"
        parts = lowered.split("-")
        if len(parts) == 2 and parts[0] in NUMBER_TENS and parts[1] in NUMBER_ONES:
            return NUMBER_TENS[parts[0]] + NUMBER_ONES[parts[1]], ""
        if len(parts) == 1 and parts[0] in NUMBER_ONES:
            return NUMBER_ONES[parts[0]], ""
        if len(parts) == 1 and parts[0] in NUMBER_TENS:
            return NUMBER_TENS[parts[0]], ""
        return None, "unparsed_or_out_of_range_week"

    def parse_ordinal(token: str) -> tuple[int | None, str]:
        lowered = token.casefold()
        if "hundred" in lowered or "thousand" in lowered or " and " in lowered:
            return None, "unparsed_or_out_of_range_week"
        if " " in lowered:
            return None, "unsupported_number_format"
        parts = lowered.split("-")
        if len(parts) == 2 and parts[0] in NUMBER_TENS and parts[1] in ORDINAL_ONES:
            return NUMBER_TENS[parts[0]] + ORDINAL_ONES[parts[1]], ""
        if len(parts) == 1 and parts[0] in ORDINAL_ONES:
            return ORDINAL_ONES[parts[0]], ""
        if len(parts) == 1 and parts[0] in ORDINAL_TENS:
            return ORDINAL_TENS[parts[0]], ""
        return None, "unparsed_or_out_of_range_week"

    def parse_unsupported_numeric(token: str) -> int | None:
        lowered = token.casefold()
        if re.fullmatch(r"[+-]?[0-9]+", lowered):
            return int(lowered)
        if re.fullmatch(r"[0-9]+(?:\s*[,\'’_]\s*[0-9]+)+", lowered):
            return int(re.sub(r"[^0-9]", "", lowered))
        if re.fullmatch(r"[0-9]+(?:\s+[0-9]+)+", lowered):
            return int(re.sub(r"\s+", "", lowered))
        decimal = re.fullmatch(r"([0-9]+)\.([0-9]+)", lowered)
        if decimal and not set(decimal.group(2)) - {"0"}:
            return int(decimal.group(1))
        return None

    def parse_unicode_decimal(token: str) -> int | None:
        try:
            ascii_digits = "".join(str(unicodedata.decimal(char)) for char in token)
        except (TypeError, ValueError):
            return None
        return int(ascii_digits) if ascii_digits else None

    def is_multiweek_expression(expression: str) -> bool:
        lowered = expression.casefold()
        if re.search(r"\bweeks\b|\b(?:to|through|and|or)\b|&|\+|;|\.\.", lowered):
            return True
        pair = re.search(r"(\d+)\s*(?:\+|;|\.\.|[-–—/])\s*(?:w\s*)?(\d+)", lowered)
        if pair:
            first = parse_unicode_decimal(pair.group(1))
            second = parse_unicode_decimal(pair.group(2))
            return bool(
                first is not None
                and second is not None
                and 1 <= first <= 12
                and 1 <= second <= 12
            )
        return False

    def parse_boundary_number(expression: str) -> int | None:
        if re.search(r"[a-df-z]", expression.casefold().replace("week", "").replace("w", "")):
            return None
        decimal = re.search(r"(\d+)\.(\d+)\s*$", expression)
        if decimal:
            if not {unicodedata.decimal(char) for char in decimal.group(2)} - {0}:
                return parse_unicode_decimal(decimal.group(1))
            return None
        digit_groups = re.findall(r"\d+", expression)
        if not digit_groups:
            return None
        try:
            digits = "".join(
                "".join(str(unicodedata.decimal(char)) for char in group)
                for group in digit_groups
            )
        except (TypeError, ValueError):
            return None
        return int(digits) if digits else None

    # Stage B accepts only the established strict grammar. Every other Stage A
    # candidate remains byte-preserved and produces a fail-closed diagnostic.
    pieces: list[str] = []
    cursor = 0
    for candidate in selected:
        token = str(candidate["token"])
        kind = str(candidate["kind"])
        if kind in {"numeric", "canonical_numeric"}:
            number, reason = int(token), ""
        elif kind == "cardinal":
            number, reason = parse_cardinal(token)
        elif kind == "ordinal":
            number, reason = parse_ordinal(token)
        elif kind == "numeric_ordinal":
            number = int(token)
            reason = (
                "unsupported_ordinal_format"
                if 1 <= number <= 12
                else "out_of_range_week"
            )
        elif kind == "numeric_ordinal_formatted":
            number = int(re.sub(r"[^0-9]", "", token))
            reason = (
                "unsupported_ordinal_format"
                if 1 <= number <= 12
                else "out_of_range_week"
            )
        elif kind == "unicode_numeric":
            number = parse_unicode_decimal(token)
            reason = (
                "out_of_range_week"
                if number is not None and not 1 <= number <= 12
                else "unsupported_week_format"
            )
        elif kind == "alias_word":
            number, _unused = parse_cardinal(token)
            reason = (
                "out_of_range_week"
                if number is not None and not 1 <= number <= 12
                else "unsupported_week_format"
            )
        elif kind == "roman_alias":
            number = {
                "I": 1,
                "II": 2,
                "III": 3,
                "IV": 4,
                "V": 5,
                "VI": 6,
                "VII": 7,
                "VIII": 8,
                "IX": 9,
                "X": 10,
                "XI": 11,
                "XII": 12,
                "XIII": 13,
            }.get(token.upper())
            reason = (
                "out_of_range_week"
                if number is not None and not 1 <= number <= 12
                else "unsupported_week_format"
            )
        elif kind == "multiweek" or (
            kind == "boundary_unsupported" and is_multiweek_expression(token)
        ):
            number, reason = None, "unsupported_multiweek_format"
        elif kind == "boundary_unsupported":
            number = parse_boundary_number(token)
            numeric_ordinal = bool(re.search(r"\d+(?:st|nd|rd|th)\b", token, re.IGNORECASE))
            if numeric_ordinal and number is not None and 1 <= number <= 12:
                reason = "unsupported_ordinal_format"
            elif number is not None and not 1 <= number <= 12:
                reason = "out_of_range_week"
            else:
                reason = "unsupported_week_format"
        elif kind == "unsupported_numeric":
            number = parse_unsupported_numeric(token)
            reason = (
                "out_of_range_week"
                if number is not None and not 1 <= number <= 12
                else "unsupported_week_format"
            )
        else:
            number, reason = None, "unsupported_week_format"
        supported = bool(
            kind in {"numeric", "canonical_numeric", "cardinal", "ordinal"}
            and number is not None
            and 1 <= number <= 12
        )
        expression = str(candidate["expression"])
        replacement = f"W{number}" if supported else expression
        applied = supported and replacement != expression
        if not supported and not reason:
            reason = "out_of_range_week"
        diagnostics.append(
            _week_diagnostic(
                expression,
                number,
                applied=applied,
                supported=supported,
                reason=reason,
            )
        )
        pieces.extend((value[cursor : candidate["start"]], replacement))
        cursor = int(candidate["end"])
        if applied:
            _record(
                rules,
                rule="numeric_week" if kind == "numeric" else "written_week",
                before=expression,
                after=replacement,
            )
    pieces.append(value[cursor:])
    return "".join(pieces)


def _normalise_times(value: str, rules: list[dict[str, str]]) -> str:
    match = re.search(r"\bhalf an hour\b", value, flags=re.IGNORECASE)
    if match:
        before = match.group(0)
        value = value[: match.start()] + "30 minutes" + value[match.end() :]
        _record(rules, rule="written_time", before=before, after="30 minutes")
    time_words = "|".join(sorted(map(re.escape, TIME_CARDINALS), key=len, reverse=True))
    while True:
        match = re.search(
            rf"\b({time_words})\s+(minutes?|mins?|hours?)\b",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            break
        number = TIME_CARDINALS[match.group(1).casefold()]
        unit = match.group(2).casefold()
        unit = "minutes" if unit.startswith("min") else unit
        replacement = f"{number} {unit}"
        before = match.group(0)
        value = value[: match.start()] + replacement + value[match.end() :]
        _record(rules, rule="written_time", before=before, after=replacement)
    return value


def _normalise_correction(value: str, rules: list[dict[str, str]]) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    week = r"(?:W|Week\s*)\d{1,2}"
    candidates = (
        (rf"^(?:no|sorry),?\s+i meant\s+({week}.*)$", r"Actually, I meant \1"),
        (rf"^i meant\s+({week}.*?)\s*,?\s+not\s+({week})[.!]?$", r"Actually, I meant \1, not \2."),
        (rf"^not\s+({week}).*?\s+({week})[.!]?$", r"Actually, I meant \2, not \1."),
        (rf"^(?:rather,?\s*|actually\s+)({week}.*)$", r"Actually, I meant \1"),
        (rf"^(?:make that|change that to|i was referring to|use)\s+(?:the\s+)?({week}.*?)(?:\s+instead)?[.!]?$", r"Actually, I meant \1."),
        (rf"^sorry,?\s+(?:the\s+)?({week}\s+(?:lecture|reading|material))[.!]?$", r"Actually, I meant \1."),
    )
    for pattern, replacement in candidates:
        if re.search(pattern, compact, flags=re.IGNORECASE):
            revised = re.sub(pattern, replacement, compact, flags=re.IGNORECASE)
            _record(rules, rule="course_correction_marker", before=compact, after=revised)
            return revised
    return value


def _normalise_relationships(
    value: str,
    rules: list[dict[str, str]],
    diagnostics: list[dict[str, Any]],
) -> str:
    negative_match = re.search(
        r"\b(?:unrelated\s+to|not\s+(?:related|linked|connected)\s+(?:to|with)|"
        r"not\s+(?:associated|correlated)\s+with|"
        r"(?:do(?:es)?\s+not|do(?:es)?n['’]t)\s+relate\s+to|"
        r"(?:do(?:es)?\s+not|do(?:es)?n['’]t|not)\s+line\s+up(?:\s+with)?|"
        r"no\s+relationship\s+between|different\s+from|differ\s+from|in\s+contrast\s+to)\b",
        value,
        flags=re.IGNORECASE,
    )
    if negative_match:
        diagnostics.append(
            {
                "relationship_expression": negative_match.group(0),
                "relationship_type": "negative_or_contrastive",
                "meaning_preserved": True,
            }
        )
        return value
    replacements = (
        (r"\b(?:related|linked|connected|associated|correlated)\s+(?:to|with)\b", "relate to"),
        (r"\bcompare\s+(?:with|against)\b", "compare"),
        (r"\b(?:line up|go together)\s+with\b", "relate to"),
        (r"\bconnection\s+between\b", "relationship between"),
    )
    for pattern, replacement in replacements:
        if negative_match and re.search(pattern, negative_match.group(0), flags=re.IGNORECASE):
            continue
        value = _sub_rule(
            value,
            pattern,
            replacement,
            rules,
            "cross_page_relationship_morphology",
        )
    return value


def _normalise_plan_revision_language(
    value: str, rules: list[dict[str, str]]
) -> str:
    if not re.search(
        r"\b(?:shorten|simplify|adapt|adjust|reduce|fit|quicker|faster|shorter|"
        r"manageable|less time|new time limit|cannot spend|can't spend)\b",
        value,
        flags=re.IGNORECASE,
    ):
        return value
    value = _sub_rule(
        value,
        r"\b(?:the\s+)?rest\b",
        "remaining actions",
        rules,
        "plan_revision_reference",
    )
    value = _sub_rule(
        value,
        r"\b(?:quicker|faster|more manageable)\b",
        "shorter",
        rules,
        "plan_revision_synonym",
    )
    value = _sub_rule(
        value,
        r"\bremaining workload\b",
        "remaining actions",
        rules,
        "plan_revision_reference",
    )
    return value


def normalise_query_paraphrases(
    query: str,
    *,
    enable_p2a_extensions: bool = True,
) -> QueryNormalisation:
    """Apply deterministic paraphrase rules and retain a complete audit trail."""

    original = str(query or "")
    value = original
    rules: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []

    value = _sub_rule(value, r"\bwhere['’]s\b", "Where is", rules, "location_contraction")
    value = _normalise_weeks(
        value,
        rules,
        diagnostics,
        enable_p2a_extensions=enable_p2a_extensions,
    )
    value = _normalise_times(value, rules)
    value = _normalise_plan_revision_language(value, rules)

    if PLAN_RECALL_RE.match(value):
        before = value
        value = "Remind me of my plan."
        _record(rules, rule="plan_recall_paraphrase", before=before, after=value)

    value = _normalise_correction(value, rules)

    explicitly_named_domains = detect_explicit_dashboard_domains(value)
    if (
        len(explicitly_named_domains) < 2
        and is_explicit_whole_dashboard_query(value)
    ):
        before = value
        value = "Which area should I prioritise first: lectures, resources, debate, or reflection?"
        _record(rules, rule="dashboard_priority_paraphrase", before=before, after=value)

    value = _normalise_relationships(value, rules, diagnostics)
    return QueryNormalisation(original, value, rules, diagnostics)


def normalise_overview_priority_paraphrase(
    normalisation: QueryNormalisation,
    *,
    current_page: str,
) -> QueryNormalisation:
    """Apply the one page-aware priority rule after lexical normalisation.

    This deliberately lives outside ``normalise_query_paraphrases`` so a
    page-local phrase cannot become global before C_FULL knows the current page.
    """

    page = str(current_page or "").strip().casefold()
    value = normalisation.normalised_query
    if (
        page != "overview"
        or detect_explicit_dashboard_domains(value)
        or not OVERVIEW_GLOBAL_PRIORITY_RE.search(value)
    ):
        return normalisation
    before = value
    after = "Which area should I prioritise first: lectures, resources, debate, or reflection?"
    rules = list(normalisation.applied_rules)
    _record(rules, rule="overview_global_priority_paraphrase", before=before, after=after)
    return QueryNormalisation(
        normalisation.original_query,
        after,
        rules,
        list(normalisation.diagnostics),
    )
