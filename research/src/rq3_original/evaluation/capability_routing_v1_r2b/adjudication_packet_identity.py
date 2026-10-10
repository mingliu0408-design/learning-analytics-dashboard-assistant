"""Identity and fixed-field audit for the completed adjudication packet."""

from __future__ import annotations

import csv
import io
from pathlib import Path
import tempfile
from typing import Any

from evaluation.capability_routing_v1_r2a.adjudication_packet_builder import (
    ADJUDICATION_FIELDS,
    BLANK_DECISION_FIELDS,
    PACKET_FIELDS,
    build_adjudication_packet_bytes,
)

from . import (
    ADJUDICATION_ID_SET_SHA256,
    BLANK_ADJUDICATION_SHA256,
    COMPLETED_ADJUDICATION_RELATIVE,
    COMPLETED_ADJUDICATION_SHA256,
    MISSING_CONTEXT_CASE_IDS,
    ROOT,
    RQ2AR2BError,
    id_set_sha256,
    sha256_bytes,
    sha256_file,
)


FALLBACK_COMPLETED_PATH = (
    Path.home() / "Downloads" / "rq2a_r2a_adjudication_packet_v1(1).csv"
)
EXPECTED_MISSING_DISPOSITION = (
    "EXCLUDE_FROM_CAPABILITY_GOLD_BUT_RETAIN_AS_CONTEXT_MISSING_CASE"
)


class AdjudicationPacketIdentityError(RQ2AR2BError):
    pass


def _rows(value: bytes) -> list[dict[str, str]]:
    with io.StringIO(value.decode("utf-8"), newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_completed_packet(root: Path = ROOT) -> tuple[Path, dict[str, Any]]:
    """Resolve only the governed project path, then the one authorised fallback."""

    preferred = root / COMPLETED_ADJUDICATION_RELATIVE
    if (
        preferred.is_file()
        and not preferred.is_symlink()
        and sha256_file(preferred) == COMPLETED_ADJUDICATION_SHA256
    ):
        return preferred, {
            "selected_source": "PROJECT_LOCAL_ONLY",
            "preferred_sha256": COMPLETED_ADJUDICATION_SHA256,
            "fallback_checked": False,
            "byte_identical_dual_source": "NOT_EVALUATED_PREFERRED_MATCHED",
        }
    if (
        FALLBACK_COMPLETED_PATH.is_file()
        and not FALLBACK_COMPLETED_PATH.is_symlink()
        and sha256_file(FALLBACK_COMPLETED_PATH) == COMPLETED_ADJUDICATION_SHA256
    ):
        return FALLBACK_COMPLETED_PATH, {
            "selected_source": "AUTHORISED_DOWNLOADS_FALLBACK",
            "preferred_sha256": (
                sha256_file(preferred) if preferred.is_file() else "MISSING"
            ),
            "fallback_checked": True,
            "fallback_sha256": COMPLETED_ADJUDICATION_SHA256,
            "byte_identical_dual_source": False,
        }
    raise AdjudicationPacketIdentityError(
        "BLOCKED_RQ2_A_R2B_ADJUDICATION_PACKET_IDENTITY"
    )


def rebuild_blank_packet_in_external_temp(root: Path = ROOT) -> bytes:
    """Use the frozen R2A builder and round-trip its bytes outside the project."""

    value = build_adjudication_packet_bytes(root)
    with tempfile.TemporaryDirectory(prefix="rq2a_r2b_blank_rebuild_") as tmp:
        path = Path(tmp) / "rq2a_r2a_adjudication_packet_v1.csv"
        path.write_bytes(value)
        rebuilt = path.read_bytes()
    rows = _rows(rebuilt)
    if (
        sha256_bytes(rebuilt) != BLANK_ADJUDICATION_SHA256
        or len(rebuilt) != 4922
        or len(rows) != 5
        or not rows
        or tuple(rows[0]) != PACKET_FIELDS
        or len(PACKET_FIELDS) != 54
        or id_set_sha256(row["review_case_id"] for row in rows)
        != ADJUDICATION_ID_SET_SHA256
        or any(row[field] for row in rows for field in BLANK_DECISION_FIELDS)
        or any(row["query_rewrite_performed"] != "false" for row in rows)
        or any(row["assistant_context_attached"] != "false" for row in rows)
    ):
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_BLANK_PACKET_REPRODUCTION"
        )
    return rebuilt


def validate_completed_against_blank(
    completed_path: Path, blank_bytes: bytes
) -> dict[str, Any]:
    completed_bytes = completed_path.read_bytes()
    if sha256_bytes(completed_bytes) != COMPLETED_ADJUDICATION_SHA256:
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_PACKET_IDENTITY"
        )
    blank_rows = _rows(blank_bytes)
    completed_rows = _rows(completed_bytes)
    if (
        len(completed_rows) != 5
        or not completed_rows
        or tuple(completed_rows[0]) != PACKET_FIELDS
        or [row["review_case_id"] for row in completed_rows]
        != [row["review_case_id"] for row in blank_rows]
    ):
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
        )

    fixed_fields = tuple(
        field for field in PACKET_FIELDS if field not in ADJUDICATION_FIELDS
    )
    mutations = [
        (position, field)
        for position, (blank, completed) in enumerate(
            zip(blank_rows, completed_rows), start=1
        )
        for field in fixed_fields
        if blank[field] != completed[field]
    ]
    if mutations:
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
        )

    always_required = (
        "adjudicated_case_validity",
        "adjudicated_naturalness_1_to_5",
        "adjudicated_context_link_valid",
        "adjudicated_context_sufficient",
        "adjudicated_capability_unambiguous",
        "adjudicated_context_resolution_required",
        "adjudicated_dashboard_evidence",
        "adjudicated_course_retrieval",
        "adjudicated_episodic_memory",
        "adjudicated_planning",
        "adjudicated_safe_direct_response",
        "adjudicated_clarification",
        "disagreement_resolution",
        "adjudicator_rationale",
        "adjudicator_id",
        "adjudication_date",
    )
    if any(not row[field] for row in completed_rows for field in always_required):
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
        )
    for row in completed_rows:
        disposition = row["missing_context_disposition"]
        if row["review_case_id"] in MISSING_CONTEXT_CASE_IDS:
            if disposition != EXPECTED_MISSING_DISPOSITION:
                raise AdjudicationPacketIdentityError(
                    "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
                )
        elif disposition:
            raise AdjudicationPacketIdentityError(
                "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
            )

    if (
        {row["adjudicator_id"] for row in completed_rows} != {"HUMAN_ADJUDICATOR"}
        or any(row["adjudication_date"] != "2026/8/26" for row in completed_rows)
        or any(row["query_rewrite_performed"] != "FALSE" for row in completed_rows)
        or any(row["assistant_context_attached"] != "FALSE" for row in completed_rows)
        or completed_bytes.count(b"2026/8/26") != 5
        or completed_bytes.count(b"2026-08-26") != 0
        or completed_bytes.count(b"FALSE") != 10
    ):
        raise AdjudicationPacketIdentityError(
            "BLOCKED_RQ2_A_R2B_UNAUTHORISED_ADJUDICATION_MUTATION"
        )
    return {
        "completed_packet_sha256": COMPLETED_ADJUDICATION_SHA256,
        "completed_record_count": 5,
        "completed_column_count": 54,
        "blank_packet_sha256": BLANK_ADJUDICATION_SHA256,
        "blank_packet_size_bytes": len(blank_bytes),
        "blank_review_case_id_set_sha256": ADJUDICATION_ID_SET_SHA256,
        "same_case_ids": True,
        "same_row_order": True,
        "fixed_field_mutation_count": 0,
        "reviewer_field_mutation_count": 0,
        "permitted_semantically_empty_forbidden_cells": sum(
            not row["adjudicated_forbidden_capabilities"]
            for row in completed_rows
        ),
        "permitted_empty_nonmissing_disposition_cells": sum(
            not row["missing_context_disposition"]
            for row in completed_rows
            if row["review_case_id"] not in MISSING_CONTEXT_CASE_IDS
        ),
        "human_adjudication_completed": True,
        "precanonical_date_count": 5,
        "uppercase_immutable_boolean_count": 10,
    }


def verify_adjudication_identity(root: Path = ROOT) -> tuple[Path, dict[str, Any]]:
    completed, resolution = resolve_completed_packet(root)
    blank = rebuild_blank_packet_in_external_temp(root)
    audit = validate_completed_against_blank(completed, blank)
    return completed, {**resolution, **audit}
