"""Build the deterministic local-only 23-case blank human adjudication packet."""

from __future__ import annotations

import csv
import io
from pathlib import Path
import random
import subprocess
from typing import Any, Mapping, Sequence

from . import (
    ADJUDICATION_FIELDS,
    ADJUDICATION_PACKET_RELATIVE,
    AGREEMENT_FIELDS,
    ROOT,
    VISIBLE_FIELDS,
    csv_rows,
    durable_write,
    ordered_id_sha256,
    sha256_bytes,
    sha256_file,
)


SHUFFLE_SEED = 20260829
REVIEWER_FIELDS = (*AGREEMENT_FIELDS, "reviewer_rationale")
PACKET_FIELDS = (
    *VISIBLE_FIELDS,
    "disagreement_reasons",
    *(f"reviewer_a_{field}" for field in REVIEWER_FIELDS),
    *(f"reviewer_b_{field}" for field in REVIEWER_FIELDS),
    *ADJUDICATION_FIELDS,
    "query_rewrite_performed",
    "assistant_context_attached",
)


class AdjudicationPacketError(RuntimeError):
    pass


def _rows_by_identity(
    rows_a: Sequence[Mapping[str, str]], rows_b: Sequence[Mapping[str, str]]
) -> tuple[dict[str, Mapping[str, str]], dict[str, Mapping[str, str]]]:
    if {row["reviewer_id"] for row in rows_a} != {"A"}:
        raise AdjudicationPacketError("Reviewer A identity mismatch")
    if {row["reviewer_id"] for row in rows_b} != {"B"}:
        raise AdjudicationPacketError("Reviewer B identity mismatch")
    return (
        {row["review_case_id"]: row for row in rows_a},
        {row["review_case_id"]: row for row in rows_b},
    )


def adjudication_packet_bytes(
    rows_a: Sequence[Mapping[str, str]],
    rows_b: Sequence[Mapping[str, str]],
    disagreement_manifest: Mapping[str, Any],
) -> bytes:
    by_a, by_b = _rows_by_identity(rows_a, rows_b)
    reasons = {
        case["review_case_id"]: case["disagreement_reasons"]
        for case in disagreement_manifest["cases"]
    }
    case_ids = sorted(reasons)
    random.Random(SHUFFLE_SEED).shuffle(case_ids)
    direct_a = [row["review_case_id"] for row in rows_a if row["review_case_id"] in reasons]
    direct_b = [row["review_case_id"] for row in rows_b if row["review_case_id"] in reasons]
    if case_ids in (direct_a, direct_b):
        raise AdjudicationPacketError("adjudication order reuses a reviewer packet order")
    output_rows: list[dict[str, str]] = []
    for case_id in case_ids:
        row_a, row_b = by_a[case_id], by_b[case_id]
        if any(row_a[field] != row_b[field] for field in VISIBLE_FIELDS):
            raise AdjudicationPacketError("visible field mismatch")
        value: dict[str, str] = {
            **{field: row_a[field] for field in VISIBLE_FIELDS},
            "disagreement_reasons": ";".join(reasons[case_id]),
            **{f"reviewer_a_{field}": row_a[field] for field in REVIEWER_FIELDS},
            **{f"reviewer_b_{field}": row_b[field] for field in REVIEWER_FIELDS},
            **{field: "" for field in ADJUDICATION_FIELDS},
            "query_rewrite_performed": "false",
            "assistant_context_attached": "false",
        }
        if tuple(value) != PACKET_FIELDS:
            raise AdjudicationPacketError("adjudication packet field order mismatch")
        output_rows.append(value)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=PACKET_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(output_rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def write_adjudication_packet(
    rows_a: Sequence[Mapping[str, str]],
    rows_b: Sequence[Mapping[str, str]],
    disagreement_manifest: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    value = adjudication_packet_bytes(rows_a, rows_b, disagreement_manifest)
    destination = root / ADJUDICATION_PACKET_RELATIVE
    durable_write(destination, value)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", ADJUDICATION_PACKET_RELATIVE.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ADJUDICATION_PACKET_RELATIVE.as_posix()],
        cwd=root,
        capture_output=True,
        check=False,
    ).returncode == 0
    rows = csv_rows(destination)
    if (
        not ignored
        or tracked
        or len(rows) != 23
        or tuple(rows[0]) != PACKET_FIELDS
        or any(row[field] for row in rows for field in ADJUDICATION_FIELDS)
        or any(
            row["query_rewrite_performed"] != "false"
            or row["assistant_context_attached"] != "false"
            for row in rows
        )
    ):
        raise AdjudicationPacketError("BLOCKED_RQ2_D2A_ADJUDICATION_PACKET")
    order = [row["review_case_id"] for row in rows]
    if value != adjudication_packet_bytes(rows_a, rows_b, disagreement_manifest):
        raise AdjudicationPacketError("adjudication packet is not deterministic")
    return {
        "schema_version": "track-b-adjudication-packet-manifest-v1",
        "stage": "RQ2-D2A",
        "status": "AWAITING_THIRD_INDEPENDENT_HUMAN_ADJUDICATOR",
        "relative_local_path": ADJUDICATION_PACKET_RELATIVE.as_posix(),
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "record_count": 23,
        "column_count": len(PACKET_FIELDS),
        "deterministic_shuffle_seed": SHUFFLE_SEED,
        "ordered_case_id_sha256": ordered_id_sha256(order),
        "direct_reviewer_order_used": False,
        "reviewer_a_decisions_assigned_by_reviewer_id": True,
        "reviewer_b_decisions_assigned_by_reviewer_id": True,
        "adjudication_human_field_count_per_case": len(ADJUDICATION_FIELDS),
        "blank_adjudication_cell_count": len(ADJUDICATION_FIELDS) * 23,
        "all_adjudication_fields_blank": True,
        "future_final_enum_contract": {
            "adjudicated_case_validity": [
                "INCLUDE_VALID_CASE",
                "EXCLUDE_INVALID_CASE",
            ],
            "adjudicated_query_naturalness_1_to_5": [1, 2, 3, 4, 5],
            "adjudicated_context_link_valid": ["YES", "NO"],
            "adjudicated_context_sufficient": ["YES", "NO"],
            "adjudicated_capability_unambiguous": ["YES", "NO"],
            "adjudicated_context_resolution_required": ["YES", "NO"],
            "six_capabilities": ["YES", "NO"],
            "uncertain_permitted": False,
            "forbidden_capability_delimiter": ";",
            "included_case_requires_nonempty_capability_set": True,
            "clarification_exclusive": True,
            "safe_direct_response_exclusive": True,
            "required_forbidden_overlap_permitted": False,
        },
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
        "double_build_sha256": sha256_bytes(
            adjudication_packet_bytes(rows_a, rows_b, disagreement_manifest)
        ),
        "ignored": True,
        "tracked": False,
        "local_only": True,
        "adjudication_decision_count": 0,
        "capability_gold_frozen": False,
        "hidden_proposal_present": False,
        "legacy_or_model_output_present": False,
        "hidden_legacy_accessed": False,
        "model_execution_count": 0,
    }
