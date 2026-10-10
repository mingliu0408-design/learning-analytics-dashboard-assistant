"""Pure in-memory parser for the frozen Primary-v3 Track-A CSV schema."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter
from typing import Any, Mapping, Sequence

from . import LABEL_UNIVERSE
from .authority_contract import validate_authority_contract


class FinalInputError(ValueError):
    """Invalid final input; messages deliberately omit record text."""


REQUIRED_COLUMNS = (
    "probe_id",
    "query",
    "normalised_query",
    "human_final_label",
    "final_semantic_label",
    "human_final_context_requirement",
    "human_final_page_context",
    "final_heldout_family_id",
    "contrast_set_id",
    "contrast_role",
    "difficulty",
    "primary_heldout_eligible",
    "threshold_selection_eligible",
    "human_decision",
    "review_status",
    "human_privacy_check",
    "human_independence_confirmed",
)

PAGE_DISTRIBUTION = {
    "NONE": 104,
    "Overview": 5,
    "Lecture": 5,
    "Reflection": 5,
    "Debate": 5,
    "Resources": 4,
}
CONTEXT_DISTRIBUTION = {"query_only": 104, "current_page": 24}
DIFFICULTY_DISTRIBUTION = {"easy": 32, "boundary": 64, "adversarial": 32}
CONTRAST_ROLE_DISTRIBUTION = {"anchor": 32, "contrast": 32, "NONE": 64}
SOURCE_NORMALISATION = (
    "NFC_STRIP_CASEFOLD_EM_DASH_TO_ASCII_HYPHEN_PRESERVE_OTHER_PUNCTUATION"
)
CONTAMINATION_NORMALISATION = (
    "NFKC_CASEFOLD_REMOVE_UNICODE_PUNCTUATION_COLLAPSE_WHITESPACE"
)


def deterministic_normalised_query(text: str) -> str:
    """Match the frozen LR query-identity normalisation."""

    folded = re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(text)).strip(),
    ).casefold()
    without_punctuation = "".join(
        "" if unicodedata.category(character).startswith("P") else character
        for character in folded
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def source_track_a_normalised_query(text: str) -> str:
    """Match the governed Track-A source-field normalisation exactly."""

    return unicodedata.normalize("NFC", str(text)).strip().casefold().replace("\u2014", "-")


def build_query_variants(record: Mapping[str, Any]) -> tuple[str, str]:
    plain = str(record["query"]).strip()
    if not plain:
        raise FinalInputError("empty final query")
    page = str(record["current_page"])
    return plain, f"[PAGE={page}] {plain}"


def _strict_bool(value: object, role: str) -> bool:
    normalised = str(value).strip().casefold()
    if normalised == "true":
        return True
    if normalised == "false":
        return False
    raise FinalInputError(f"{role} must be true or false")


def _validate_distribution(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) != 128:
        raise FinalInputError("final record count mismatch")
    ids = [str(row["record_id"]) for row in records]
    raw_queries = [str(row["query"]) for row in records]
    normalised = [str(row["normalised_query"]) for row in records]
    if len(set(ids)) != 128:
        raise FinalInputError("duplicate final record ID")
    if len(set(raw_queries)) != 128:
        raise FinalInputError("duplicate raw final query")
    if len(set(normalised)) != 128:
        raise FinalInputError("duplicate normalised final query")
    label_counts = Counter(str(row["gold_label"]) for row in records)
    if set(label_counts) != set(LABEL_UNIVERSE) or any(value != 8 for value in label_counts.values()):
        raise FinalInputError("final label distribution mismatch")
    context_counts = Counter(str(row["context_requirement"]) for row in records)
    page_counts = Counter(str(row["current_page"]) for row in records)
    difficulty_counts = Counter(str(row["difficulty"]) for row in records)
    contrast_counts = Counter(str(row["contrast_role"]) for row in records)
    if dict(context_counts) != CONTEXT_DISTRIBUTION:
        raise FinalInputError("final context distribution mismatch")
    if dict(page_counts) != PAGE_DISTRIBUTION:
        raise FinalInputError("final page distribution mismatch")
    if dict(difficulty_counts) != DIFFICULTY_DISTRIBUTION:
        raise FinalInputError("final difficulty distribution mismatch")
    if dict(contrast_counts) != CONTRAST_ROLE_DISTRIBUTION:
        raise FinalInputError("final contrast-role distribution mismatch")
    families = {str(row["family_id"]) for row in records}
    if len(families) != 128 or "" in families:
        raise FinalInputError("final family distribution mismatch")
    contrast_sets = {
        str(row["contrast_set_id"])
        for row in records
        if str(row["contrast_role"]) in {"anchor", "contrast"}
    }
    if len(contrast_sets) != 32 or "" in contrast_sets:
        raise FinalInputError("final contrast-set distribution mismatch")
    return {
        "record_count": 128,
        "unique_record_id_count": 128,
        "unique_query_count": 128,
        "unique_normalised_query_count": 128,
        "label_count": 16,
        "per_label_count": 8,
        "context_requirement": dict(context_counts),
        "page_context": dict(page_counts),
        "difficulty": dict(difficulty_counts),
        "contrast_role": dict(contrast_counts),
        "contrast_set_count": len(contrast_sets),
        "heldout_family_count": len(families),
    }


def parse_final_csv_bytes(
    raw_bytes: bytes,
    authority_contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a single in-memory byte buffer; this function has no file I/O."""

    validate_authority_contract(authority_contract)
    if not isinstance(raw_bytes, bytes):
        raise FinalInputError("final input must be bytes")
    if not raw_bytes.startswith(b"\xef\xbb\xbf"):
        raise FinalInputError("final CSV must use UTF-8 with BOM")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FinalInputError("final CSV is not valid UTF-8 with BOM") from exc
    remainder = text.replace("\r\n", "")
    if "\n" in remainder or "\r" in remainder:
        raise FinalInputError("final CSV newline contract mismatch")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = tuple(reader.fieldnames or ())
    if len(fieldnames) != len(set(fieldnames)) or not set(REQUIRED_COLUMNS) <= set(fieldnames):
        raise FinalInputError("final CSV field contract mismatch")
    records: list[dict[str, Any]] = []
    for position, source in enumerate(reader):
        if None in source:
            raise FinalInputError("final CSV contains excess columns")
        record_id = str(source["probe_id"]).strip()
        query = str(source["query"]).strip()
        supplied_normalised = str(source["normalised_query"]).strip()
        gold = str(source["human_final_label"]).strip()
        consistency = str(source["final_semantic_label"]).strip()
        context = str(source["human_final_context_requirement"]).strip()
        raw_page = str(source["human_final_page_context"]).strip()
        family = str(source["final_heldout_family_id"]).strip()
        contrast_set = str(source["contrast_set_id"]).strip()
        raw_contrast_role = str(source["contrast_role"]).strip()
        difficulty = str(source["difficulty"]).strip()
        if not record_id or not query or not family:
            raise FinalInputError("required final field is empty")
        if source_track_a_normalised_query(query) != supplied_normalised:
            raise FinalInputError("precomputed normalised query mismatch")
        if gold not in LABEL_UNIVERSE or consistency != gold:
            raise FinalInputError("final gold label contract mismatch")
        if context not in CONTEXT_DISTRIBUTION:
            raise FinalInputError("final context requirement is invalid")
        if context == "query_only":
            if raw_page != "":
                raise FinalInputError("query-only record has page context")
            page = "NONE"
        else:
            if raw_page not in set(PAGE_DISTRIBUTION) - {"NONE"}:
                raise FinalInputError("current-page record lacks a governed page")
            page = raw_page
        if difficulty not in DIFFICULTY_DISTRIBUTION:
            raise FinalInputError("final difficulty value is invalid")
        if raw_contrast_role == "":
            if contrast_set:
                raise FinalInputError("blank contrast role has a contrast-set ID")
            contrast_role = "NONE"
        elif raw_contrast_role in {"anchor", "contrast"}:
            if not contrast_set:
                raise FinalInputError("contrast record lacks a contrast-set ID")
            contrast_role = raw_contrast_role
        else:
            raise FinalInputError("final contrast role is invalid")
        if _strict_bool(source["primary_heldout_eligible"], "primary eligibility") is not True:
            raise FinalInputError("record is not primary-heldout eligible")
        if _strict_bool(source["threshold_selection_eligible"], "threshold eligibility") is not False:
            raise FinalInputError("record is threshold-selection eligible")
        if str(source["human_decision"]).strip() != "approved":
            raise FinalInputError("record lacks approved human decision")
        if str(source["review_status"]).strip() != "completed_researcher_human_review":
            raise FinalInputError("record lacks completed researcher review")
        if str(source["human_privacy_check"]).strip() != "pass":
            raise FinalInputError("record privacy check is not pass")
        if str(source["human_independence_confirmed"]).strip() != "yes":
            raise FinalInputError("record independence is not confirmed")
        records.append(
            {
                "record_order": position,
                "record_id": record_id,
                "query": query,
                "normalised_query": supplied_normalised,
                "gold_label": gold,
                "context_requirement": context,
                "current_page": page,
                "family_id": family,
                "contrast_set_id": contrast_set,
                "contrast_role": contrast_role,
                "difficulty": difficulty,
            }
        )
    distribution = _validate_distribution(records)
    return records, {
        "schema_version": "rq1c-final-input-validation-v1",
        "status": "PASS",
        "record_schema_version": "primary-v3-track-a-blank-template-v1",
        "encoding": "UTF-8 with BOM",
        "newline": "CRLF",
        "required_field_count": len(REQUIRED_COLUMNS),
        "record_order_policy": "PRESERVE_AUTHORISED_CSV_ORDER",
        "runtime_query_normalisation": "STRIP_ONLY_FOR_EMBEDDING",
        "source_normalisation": SOURCE_NORMALISATION,
        "contamination_normalisation": CONTAMINATION_NORMALISATION,
        "plain_variant": "strip(query)",
        "page_prefixed_variant": "[PAGE={human_final_page_context}] {strip(query)}",
        "distribution": distribution,
        "raw_text_emitted": False,
    }


def build_synthetic_final_csv() -> bytes:
    """Create a fully synthetic 128-row fixture matching the frozen distribution."""

    page_values = (
        ["Overview"] * 5
        + ["Lecture"] * 5
        + ["Reflection"] * 5
        + ["Debate"] * 5
        + ["Resources"] * 4
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=REQUIRED_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for index in range(128):
        punctuation_queries = (
            "Synthetic final fixture, comma case 000",
            "Synthetic final fixture question case 001?",
            "Synthetic final fixture student's case 002",
            "Synthetic final fixture full stop case 003.",
            "Synthetic final fixture ASCII-hyphen case 004",
            "Synthetic final fixture EM\u2014DASH case 005",
        )
        query = (
            punctuation_queries[index]
            if index < len(punctuation_queries)
            else f"synthetic final fixture {index:03d} token {index * 17 + 3}"
        )
        if index < 104:
            context = "query_only"
            page = ""
        else:
            context = "current_page"
            page = page_values[index - 104]
        if index < 32:
            difficulty = "easy"
        elif index < 96:
            difficulty = "boundary"
        else:
            difficulty = "adversarial"
        if index < 32:
            contrast_role = "anchor"
            contrast_set = f"SYN-CS-{index:02d}"
        elif index < 64:
            contrast_role = "contrast"
            contrast_set = f"SYN-CS-{index - 32:02d}"
        else:
            contrast_role = ""
            contrast_set = ""
        label = LABEL_UNIVERSE[index % len(LABEL_UNIVERSE)]
        writer.writerow(
            {
                "probe_id": f"SYN-RQ1C-{index:04d}",
                "query": query,
                "normalised_query": source_track_a_normalised_query(query),
                "human_final_label": label,
                "final_semantic_label": label,
                "human_final_context_requirement": context,
                "human_final_page_context": page,
                "final_heldout_family_id": f"SYN-FAMILY-{index:04d}",
                "contrast_set_id": contrast_set,
                "contrast_role": contrast_role,
                "difficulty": difficulty,
                "primary_heldout_eligible": "true",
                "threshold_selection_eligible": "false",
                "human_decision": "approved",
                "review_status": "completed_researcher_human_review",
                "human_privacy_check": "pass",
                "human_independence_confirmed": "yes",
            }
        )
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
