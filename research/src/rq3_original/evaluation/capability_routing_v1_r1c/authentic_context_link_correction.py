"""Remove all unsupported assistant-context links from the authentic bank."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import (
    HERE,
    LOCAL_AUTHENTIC_BANK_RELATIVE,
    PREVIOUS_CONTEXT_CASE_IDS,
    R1B_AUTHENTIC_BANK_RELATIVE,
    R1B_AUTHENTIC_BANK_SHA256,
    ROOT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_file,
)


class ContextLinkCorrectionError(RuntimeError):
    pass


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_r1b_authentic_cases(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / R1B_AUTHENTIC_BANK_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise ContextLinkCorrectionError("R1B authentic local bank unavailable")
    if sha256_file(path) != R1B_AUTHENTIC_BANK_SHA256:
        raise ContextLinkCorrectionError("R1B authentic local bank mismatch")
    rows = _read_jsonl(path)
    if len(rows) != 25:
        raise ContextLinkCorrectionError("R1B authentic case count mismatch")
    linked = {
        str(row["case_id"])
        for row in rows
        if row.get("candidate_conversation_history")
    }
    if linked != set(PREVIOUS_CONTEXT_CASE_IDS):
        raise ContextLinkCorrectionError("R1B context-link candidate set mismatch")
    return rows


def build_corrected_authentic_cases(root: Path = ROOT) -> list[dict[str, Any]]:
    previous = load_r1b_authentic_cases(root)
    corrected: list[dict[str, Any]] = []
    for source in previous:
        row = dict(source)
        query = str(row["current_query"])
        if hashlib.sha256(query.encode("utf-8")).hexdigest() != row["raw_query_sha256"]:
            raise ContextLinkCorrectionError("authentic query hash mismatch")
        row["candidate_conversation_history"] = []
        row["assistant_context_attached"] = False
        row["assistant_outputs_used_as_context"] = False
        row["context_link_status"] = "NOT_AVAILABLE"
        row["adjacent_pair_linkage_confirmed"] = False
        row["automatic_session_inference_authorised"] = False
        row["authentic_student_origin"] = True
        row["student_origin_confirmation"] = "USER_EXPLICIT_ATTESTATION"
        corrected.append(row)
    if [row["current_query"] for row in corrected] != [
        row["current_query"] for row in previous
    ]:
        raise ContextLinkCorrectionError("authentic query text changed")
    if any(row["candidate_conversation_history"] for row in corrected):
        raise ContextLinkCorrectionError("authentic assistant context remains")
    return corrected


def write_context_link_correction(
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    corrected = build_corrected_authentic_cases(root)
    path = root / LOCAL_AUTHENTIC_BANK_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(corrected))
    summary = {
        "authentic_case_count": 25,
        "previous_candidate_link_count": 5,
        "links_removed": 5,
        "remaining_link_count": 0,
        "assistant_context_in_packets": 0,
        "query_text_modified": 0,
    }
    (HERE / "authentic_context_link_correction_v1.json").write_bytes(
        canonical_json_bytes(summary)
    )
    return corrected, summary
