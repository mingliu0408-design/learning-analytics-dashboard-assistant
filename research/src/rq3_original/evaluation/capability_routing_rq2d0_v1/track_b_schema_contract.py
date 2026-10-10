"""Exact, authority-driven Track-B CSV parser and effective-input overlay."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Mapping

from . import (
    SAFE_AUTHORITY_COPY_ROOT,
    SCHEMA_AUTHORITY_MEMBER_SHA256,
    TRACK_B_COLUMN_COUNT,
    TRACK_B_FILE_NAME,
    TRACK_B_ORDER_COMMITMENT,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    sha256_bytes,
    sha256_file,
)


class TrackBSchemaError(ValueError):
    pass


NULL_TOKENS = {"NULL", "None", "NA", "N/A", "NaN"}
ORDER_PREFIX = b"RQ2_TRACK_B_RECORD_ORDER_V1\x00"


def _load_json(name: str, root: Path = SAFE_AUTHORITY_COPY_ROOT) -> dict[str, Any]:
    path = root / name
    expected = SCHEMA_AUTHORITY_MEMBER_SHA256[name]
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
        raise TrackBSchemaError("safe schema authority copy mismatch")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TrackBSchemaError("safe schema authority must be an object")
    return value


def load_schema_authority(
    root: Path = SAFE_AUTHORITY_COPY_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    authority = _load_json("TRACK_B_SCHEMA_AUTHORITY_V1.json", root)
    profile = _load_json("TRACK_B_SCHEMA_FIELD_PROFILE_V1.json", root)
    template_path = root / "TRACK_B_BLANK_SCHEMA_TEMPLATE_V1.csv"
    template = template_path.read_bytes()
    if sha256_bytes(template) != SCHEMA_AUTHORITY_MEMBER_SHA256[template_path.name]:
        raise TrackBSchemaError("blank schema template mismatch")
    validate_schema_authority(authority, profile, template)
    return authority, profile, template


def exact_columns(authority: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(authority["header_contract"]["exact_column_order"])


def ordered_id_commitment(ids: list[str]) -> str:
    return hashlib.sha256(ORDER_PREFIX + "\n".join(ids).encode("utf-8")).hexdigest()


def validate_schema_authority(
    authority: Mapping[str, Any], profile: Mapping[str, Any], template: bytes
) -> None:
    source = authority.get("source_identity") or {}
    header = authority.get("header_contract") or {}
    byte_contract = authority.get("byte_format_contract") or {}
    columns = exact_columns(authority)
    if (
        authority.get("status") != "EFFECTIVE_SAFE_SCHEMA_AUTHORITY"
        or source.get("file_name") != TRACK_B_FILE_NAME
        or source.get("sha256") != TRACK_B_SHA256
        or source.get("size_bytes") != TRACK_B_SIZE_BYTES
        or source.get("record_count") != TRACK_B_RECORD_COUNT
        or source.get("column_count") != TRACK_B_COLUMN_COUNT
        or len(columns) != TRACK_B_COLUMN_COUNT
        or len(set(columns)) != TRACK_B_COLUMN_COUNT
        or "index" in columns
        or header.get("display_only_index_column_is_not_part_of_raw_csv") is not True
        or header.get("raw_header_with_bom_and_crlf_sha256")
        != SCHEMA_AUTHORITY_MEMBER_SHA256["TRACK_B_BLANK_SCHEMA_TEMPLATE_V1.csv"]
        or byte_contract.get("encoding") != "UTF-8"
        or byte_contract.get("bom", {}).get("hex") != "EFBBBF"
        or byte_contract.get("newline") != "CRLF"
        or byte_contract.get("final_newline_present") is not True
        or sha256_bytes(template) != header.get("raw_header_with_bom_and_crlf_sha256")
    ):
        raise TrackBSchemaError("safe schema authority identity mismatch")
    decoded = template.decode("utf-8-sig")
    if not decoded.endswith("\r\n") or tuple(next(csv.reader([decoded[:-2]]))) != columns:
        raise TrackBSchemaError("blank schema template header mismatch")
    fields = profile.get("fields") or []
    if (
        profile.get("column_count") != TRACK_B_COLUMN_COUNT
        or len(fields) != TRACK_B_COLUMN_COUNT
        or tuple(field.get("name") for field in fields) != columns
        or tuple(field.get("position_1_based") for field in fields)
        != tuple(range(1, TRACK_B_COLUMN_COUNT + 1))
    ):
        raise TrackBSchemaError("field profile mismatch")
    grouping = authority.get("grouping_contract") or {}
    if (
        grouping.get("scenario_family_id", {}).get("unique_groups") != 48
        or grouping.get("scenario_family_id", {}).get("suitable_as_repeated_cluster_unit")
        is not False
        or grouping.get("contrast_set_id", {}).get("unique_groups") != 24
        or grouping.get("contrast_set_id", {}).get("records_per_group") != 2
        or grouping.get("session_id", {}).get("present") is not False
    ):
        raise TrackBSchemaError("grouping authority mismatch")


def _parse_history(value: str, *, optional: bool = False) -> list[dict[str, str]] | None:
    if optional and value == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TrackBSchemaError("history field is not governed JSON") from exc
    if not isinstance(parsed, list) or len(parsed) != 2:
        raise TrackBSchemaError("history must contain exactly two turns")
    expected_roles = ("user", "assistant")
    result: list[dict[str, str]] = []
    for position, item in enumerate(parsed):
        if not isinstance(item, dict) or set(item) != {"content", "role"}:
            raise TrackBSchemaError("history item keys mismatch")
        role = str(item["role"])
        content = str(item["content"])
        if role != expected_roles[position] or not content:
            raise TrackBSchemaError("history role/content mismatch")
        result.append({"content": content, "role": role})
    return result


def _validate_profile_values(
    source: Mapping[str, str], profile_fields: list[Mapping[str, Any]]
) -> None:
    for field in profile_fields:
        name = str(field["name"])
        value = source[name]
        if value and not value.strip():
            raise TrackBSchemaError("whitespace-only CSV field")
        if value in NULL_TOKENS:
            raise TrackBSchemaError("textual null token is prohibited")
        if field.get("required_column") is not True:
            raise TrackBSchemaError("all 47 governed columns must be present")
        if "constant_value" in field and value != str(field["constant_value"]):
            raise TrackBSchemaError(f"constant field mismatch: {name}")
        allowed = field.get("allowed_values")
        if allowed is not None and value not in set(str(item) for item in allowed):
            raise TrackBSchemaError(f"enum field mismatch: {name}")
        pattern = field.get("pattern")
        if pattern and not re.fullmatch(str(pattern), value):
            raise TrackBSchemaError(f"pattern field mismatch: {name}")


def parse_track_b_csv_bytes(
    raw: bytes,
    *,
    mode: str,
    authority_root: Path = SAFE_AUTHORITY_COPY_ROOT,
    expected_synthetic_sha256: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a single in-memory read; D0 may call only SYNTHETIC_D0 mode."""

    authority, profile, _ = load_schema_authority(authority_root)
    if mode not in {"SYNTHETIC_D0", "D1_AUTHORISED_RAW"}:
        raise TrackBSchemaError("unknown schema execution mode")
    observed_sha = sha256_bytes(raw)
    if mode == "D1_AUTHORISED_RAW":
        if observed_sha != TRACK_B_SHA256 or len(raw) != TRACK_B_SIZE_BYTES:
            raise TrackBSchemaError("TRACK_B_FINAL_EVALUATION_INVALID")
    elif expected_synthetic_sha256 is None or observed_sha != expected_synthetic_sha256:
        raise TrackBSchemaError("synthetic input commitment mismatch")
    if not raw.startswith(b"\xef\xbb\xbf") or not raw.endswith(b"\r\n"):
        raise TrackBSchemaError("BOM/final CRLF mismatch")
    remainder = raw[3:].replace(b"\r\n", b"")
    if b"\r" in remainder or b"\n" in remainder:
        raise TrackBSchemaError("newline contract mismatch")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TrackBSchemaError("CSV is not UTF-8 with BOM") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = exact_columns(authority)
    if tuple(reader.fieldnames or ()) != columns:
        raise TrackBSchemaError("exact 47-column order mismatch")
    profile_fields = list(profile["fields"])
    effective: list[dict[str, Any]] = []
    raw_ids: list[str] = []
    family_ids: list[str] = []
    contrast_ids: list[str] = []
    revised_query_count = 0
    revised_history_count = 0
    revised_expected_count = 0
    for position, source in enumerate(reader):
        if None in source or set(source) != set(columns):
            raise TrackBSchemaError("CSV row shape mismatch")
        _validate_profile_values(source, profile_fields)
        raw_id = source["scenario_id"]
        expected_id = f"PV3-B-{position + 1:04d}"
        if raw_id != expected_id:
            raise TrackBSchemaError("physical record order mismatch")
        history = _parse_history(source["conversation_history"])
        revised_history = _parse_history(source["human_revised_history"], optional=True)
        if source["history_turn_count"] != "2" or source["history_required"] != "True":
            raise TrackBSchemaError("history structure flags mismatch")
        revised_query = source["human_revised_query"]
        revised_expected = source["human_revised_expected_fields"]
        if revised_expected:
            try:
                expected_overlay = json.loads(revised_expected)
            except json.JSONDecodeError as exc:
                raise TrackBSchemaError("expected-field overlay is not JSON") from exc
            if not isinstance(expected_overlay, dict) or not set(expected_overlay) <= {
                "final_expected_source_scope"
            }:
                raise TrackBSchemaError("expected-field overlay keys mismatch")
            revised_expected_count += 1
        if revised_query:
            revised_query_count += 1
        if revised_history is not None:
            revised_history_count += 1
        raw_ids.append(raw_id)
        family_ids.append(source["scenario_family_id"])
        contrast_ids.append(source["contrast_set_id"])
        effective.append(
            {
                "record_order": position,
                "raw_case_id": raw_id,
                "effective_current_query": revised_query or source["current_query"],
                "normalised_current_query": source["normalised_current_query"],
                "current_page": source["current_page"],
                "effective_conversation_history": revised_history or history,
                "scenario_family_id": source["scenario_family_id"],
                "contrast_set_id": source["contrast_set_id"],
            }
        )
    if len(effective) != TRACK_B_RECORD_COUNT or len(set(raw_ids)) != TRACK_B_RECORD_COUNT:
        raise TrackBSchemaError("record count or ID uniqueness mismatch")
    commitment = ordered_id_commitment(raw_ids)
    if commitment != TRACK_B_ORDER_COMMITMENT:
        raise TrackBSchemaError("TRACK_B_FINAL_EVALUATION_INVALID")
    from collections import Counter

    contrast_counts = Counter(contrast_ids)
    if len(set(family_ids)) != 48 or len(contrast_counts) != 24 or set(contrast_counts.values()) != {2}:
        raise TrackBSchemaError("grouping contract mismatch")
    if revised_query_count != 0 or revised_history_count != 1 or revised_expected_count != 1:
        raise TrackBSchemaError("effective overlay structural count mismatch")
    return effective, {
        "schema_version": "track-b-schema-validation-v1",
        "status": "PASS",
        "mode": mode,
        "observed_sha256": observed_sha,
        "byte_count": len(raw),
        "record_count": len(effective),
        "column_count": len(columns),
        "encoding": "UTF-8",
        "bom_hex": "EFBBBF",
        "newline": "CRLF_ONLY",
        "final_crlf_present": True,
        "index_column_present": False,
        "ordered_id_commitment": commitment,
        "scenario_family_unique_count": len(set(family_ids)),
        "contrast_set_count": len(contrast_counts),
        "session_id_present": False,
        "human_revised_query_override_count": revised_query_count,
        "human_revised_history_override_count": revised_history_count,
        "human_revised_expected_fields_count": revised_expected_count,
        "raw_text_emitted": False,
    }


def schema_contract_document(
    authority_root: Path = SAFE_AUTHORITY_COPY_ROOT,
) -> dict[str, Any]:
    authority, profile, template = load_schema_authority(authority_root)
    return {
        "schema_version": "track-b-schema-authority-freeze-v1",
        "status": "FROZEN_BEFORE_D1_RAW_ACCESS",
        "effective_authority": "TRACK_B_SCHEMA_AUTHORITY_V1.json",
        "blank_template_sha256": sha256_bytes(template),
        "field_profile_sha256": SCHEMA_AUTHORITY_MEMBER_SHA256[
            "TRACK_B_SCHEMA_FIELD_PROFILE_V1.json"
        ],
        "raw_identity": authority["source_identity"],
        "byte_format_contract": authority["byte_format_contract"],
        "header_contract": authority["header_contract"],
        "field_mapping_contract": authority["field_mapping_contract"],
        "json_field_contracts": authority["json_field_contracts"],
        "effective_input_resolution": authority["effective_input_resolution"],
        "record_order_contract": authority["record_order_contract"],
        "grouping_contract": authority["grouping_contract"],
        "field_profile_count": len(profile["fields"]),
        "no_raw_rows_in_tracked_contract": True,
        "codex_d0_raw_access": False,
    }
