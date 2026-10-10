"""Restricted field projector and source-blinded grouping construction."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from typing import Any, Iterable

from . import canonical_jsonl_bytes, utf8_key


DOMAIN = b"RQ2_TRACK_B_SOURCE_BLINDED_CONTRAST_GROUP_V1\x00"


class GroupingStructureError(RuntimeError):
    pass


def _skip_ws(text: str, position: int) -> int:
    while position < len(text) and text[position] in " \t\r\n":
        position += 1
    return position


def _skip_json_value(text: str, position: int) -> int:
    """Skip one valid JSON value without materialising the value."""

    position = _skip_ws(text, position)
    if position >= len(text):
        raise GroupingStructureError("truncated JSON value")
    opener = text[position]
    if opener == '"':
        position += 1
        escaped = False
        while position < len(text):
            char = text[position]
            position += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                return position
        raise GroupingStructureError("unterminated JSON string")
    if opener in "[{":
        stack = [opener]
        position += 1
        in_string = False
        escaped = False
        pairs = {"]": "[", "}": "{"}
        while position < len(text):
            char = text[position]
            position += 1
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                if not stack or stack.pop() != pairs[char]:
                    raise GroupingStructureError("malformed nested JSON")
                if not stack:
                    return position
        raise GroupingStructureError("unterminated nested JSON")
    while position < len(text) and text[position] not in ",}":
        position += 1
    return position


def project_json_object_fields_v1(text: str, allowed_fields: tuple[str, ...]) -> tuple[dict[str, str], int]:
    decoder = json.JSONDecoder()
    position = _skip_ws(text, 0)
    if position >= len(text) or text[position] != "{":
        raise GroupingStructureError("JSONL row must be an object")
    position += 1
    projected: dict[str, str] = {}
    seen_keys: set[str] = set()
    skipped = 0
    while True:
        position = _skip_ws(text, position)
        if position < len(text) and text[position] == "}":
            position += 1
            break
        key, end = decoder.raw_decode(text, position)
        if not isinstance(key, str) or key in seen_keys:
            raise GroupingStructureError("invalid or duplicate JSON key")
        seen_keys.add(key)
        position = _skip_ws(text, end)
        if position >= len(text) or text[position] != ":":
            raise GroupingStructureError("missing JSON colon")
        position = _skip_ws(text, position + 1)
        if key in allowed_fields:
            value, position = decoder.raw_decode(text, position)
            if not isinstance(value, str) or not value:
                raise GroupingStructureError("allowed grouping identity must be a non-empty string")
            projected[key] = value
        else:
            position = _skip_json_value(text, position)
            skipped += 1
        position = _skip_ws(text, position)
        if position < len(text) and text[position] == ",":
            position += 1
            continue
        if position < len(text) and text[position] == "}":
            position += 1
            break
        raise GroupingStructureError("malformed top-level JSON object")
    if _skip_ws(text, position) != len(text) or set(projected) != set(allowed_fields):
        raise GroupingStructureError("grouping projector schema mismatch")
    return projected, skipped


def project_jsonl_fields_v1(data: bytes, allowed_fields: tuple[str, ...]) -> tuple[list[dict[str, str]], dict[str, int]]:
    if data.startswith(b"\xef\xbb\xbf") or b"\r" in data or not data.endswith(b"\n"):
        raise GroupingStructureError("grouping input encoding contract mismatch")
    rows: list[dict[str, str]] = []
    skipped = 0
    for raw_line in data.splitlines():
        if not raw_line:
            raise GroupingStructureError("blank JSONL row")
        projected, row_skipped = project_json_object_fields_v1(raw_line.decode("utf-8"), allowed_fields)
        rows.append(projected)
        skipped += row_skipped
    return rows, {
        "row_count": len(rows),
        "allowed_field_value_access_count": len(rows) * len(allowed_fields),
        "forbidden_field_value_access_count": 0,
        "skipped_unprojected_field_count": skipped,
    }


def opaque_group_id_v1(review_case_ids: Iterable[str]) -> str:
    ordered = sorted((str(value) for value in review_case_ids), key=utf8_key)
    if len(ordered) != 2 or len(set(ordered)) != 2:
        raise GroupingStructureError("opaque group requires exactly two unique case IDs")
    payload = DOMAIN + ordered[0].encode("utf-8") + b"\x00" + ordered[1].encode("utf-8")
    return "TBCG-" + hashlib.sha256(payload).hexdigest()[:16].upper()


def build_source_blinded_grouping_v1(
    mapping_rows: list[dict[str, str]], case_bank_rows: list[dict[str, str]]
) -> tuple[bytes, dict[str, Any]]:
    if len(mapping_rows) != 48 or len(case_bank_rows) != 48:
        raise GroupingStructureError("grouping inputs must each contain 48 rows")
    mapping_keys = [row["raw_scenario_id"] for row in mapping_rows]
    raw_case_ids = [row["raw_case_id"] for row in case_bank_rows]
    review_ids = [row["review_case_id"] for row in mapping_rows]
    if len(set(mapping_keys)) != 48 or len(set(raw_case_ids)) != 48 or len(set(review_ids)) != 48:
        raise GroupingStructureError("duplicate mapping or case identity")
    cases_by_raw = {row["raw_case_id"]: row["contrast_set_id"] for row in case_bank_rows}
    if set(mapping_keys) != set(cases_by_raw):
        raise GroupingStructureError("mapping/case-bank join mismatch")
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in mapping_rows:
        grouped[cases_by_raw[row["raw_scenario_id"]]].append(row["review_case_id"])
    distribution = Counter(len(values) for values in grouped.values())
    if len(grouped) != 24 or distribution != Counter({2: 24}):
        raise GroupingStructureError("contrast groups must be 24 x 2")
    group_ids = {raw_group: opaque_group_id_v1(ids) for raw_group, ids in grouped.items()}
    if len(set(group_ids.values())) != 24:
        raise GroupingStructureError("opaque group ID collision")
    ledger_rows = sorted(
        (
            {"review_case_id": row["review_case_id"], "contrast_group_id": group_ids[cases_by_raw[row["raw_scenario_id"]]]}
            for row in mapping_rows
        ),
        key=lambda row: utf8_key(row["review_case_id"]),
    )
    ledger = canonical_jsonl_bytes(ledger_rows)
    second = canonical_jsonl_bytes(ledger_rows)
    if ledger != second:
        raise GroupingStructureError("grouping double build mismatch")
    return ledger, {
        "mapping_row_count": 48,
        "case_bank_row_count": 48,
        "joined_row_count": 48,
        "unmatched_count": 0,
        "duplicate_count": 0,
        "unique_review_case_id_count": 48,
        "unique_contrast_group_id_count": 24,
        "records_per_contrast_group_distribution": {"2": 24},
        "opaque_group_collision_count": 0,
        "raw_contrast_id_used_in_hash": False,
        "ledger_row_order": "REVIEW_CASE_ID_UTF8_ASCENDING",
        "double_build_byte_identical": True,
    }
