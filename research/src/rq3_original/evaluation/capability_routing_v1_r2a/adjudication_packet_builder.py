"""Create the local-only blank human adjudication packet."""

from __future__ import annotations

import csv
import io
from pathlib import Path
import subprocess
from typing import Any, Mapping

from evaluation.capability_routing_v1_r1c import PREDICTED_CAPABILITIES

from . import (
    ADJUDICATION_PACKET_RELATIVE,
    CANONICAL_A_RELATIVE,
    CANONICAL_B_RELATIVE,
    EXPECTED_ADJUDICATION_CASES,
    ROOT,
    id_set_sha256,
    sha256_bytes,
    sha256_file,
)
from .adjudication_set_builder import build_adjudication_case_summary


BASE_FIELDS = (
    "review_case_id",
    "source_role",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "disagreement_reasons",
    "reviewer_a_case_validity",
    "reviewer_b_case_validity",
    "reviewer_a_naturalness",
    "reviewer_b_naturalness",
    "reviewer_a_context_link_valid",
    "reviewer_b_context_link_valid",
    "reviewer_a_context_sufficient",
    "reviewer_b_context_sufficient",
    "reviewer_a_capability_unambiguous",
    "reviewer_b_capability_unambiguous",
    "reviewer_a_context_resolution_required",
    "reviewer_b_context_resolution_required",
    *(f"reviewer_a_{capability}" for capability in PREDICTED_CAPABILITIES),
    *(f"reviewer_b_{capability}" for capability in PREDICTED_CAPABILITIES),
    "reviewer_a_forbidden_capabilities",
    "reviewer_b_forbidden_capabilities",
    "reviewer_a_rationale",
    "reviewer_b_rationale",
)
ADJUDICATION_FIELDS = (
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
    "adjudicated_forbidden_capabilities",
    "missing_context_disposition",
    "disagreement_resolution",
    "adjudicator_rationale",
    "adjudicator_id",
    "adjudication_date",
    "query_rewrite_performed",
    "assistant_context_attached",
)
PACKET_FIELDS = (*BASE_FIELDS, *ADJUDICATION_FIELDS)
BLANK_DECISION_FIELDS = ADJUDICATION_FIELDS[:-2]
FORBIDDEN_COLUMNS = {
    "hidden_proposal",
    "c0_score",
    "legacy_output",
    "intent_prediction",
    "expected_gold",
    "threshold",
}


class AdjudicationPacketError(RuntimeError):
    pass


def _packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row(
    review_case_id: str,
    reason: str,
    source_role: str,
    reviewer_a: Mapping[str, str],
    reviewer_b: Mapping[str, str],
) -> dict[str, str]:
    value = {
        "review_case_id": review_case_id,
        "source_role": source_role,
        "current_query": reviewer_a["current_query"],
        "current_page": reviewer_a["current_page"],
        "necessary_conversation_history": reviewer_a[
            "necessary_conversation_history"
        ],
        "disagreement_reasons": reason,
        "reviewer_a_case_validity": reviewer_a["case_validity"],
        "reviewer_b_case_validity": reviewer_b["case_validity"],
        "reviewer_a_naturalness": reviewer_a["query_naturalness_1_to_5"],
        "reviewer_b_naturalness": reviewer_b["query_naturalness_1_to_5"],
        "reviewer_a_context_link_valid": reviewer_a["context_link_valid"],
        "reviewer_b_context_link_valid": reviewer_b["context_link_valid"],
        "reviewer_a_context_sufficient": reviewer_a["context_sufficient"],
        "reviewer_b_context_sufficient": reviewer_b["context_sufficient"],
        "reviewer_a_capability_unambiguous": reviewer_a[
            "capability_unambiguous"
        ],
        "reviewer_b_capability_unambiguous": reviewer_b[
            "capability_unambiguous"
        ],
        "reviewer_a_context_resolution_required": reviewer_a[
            "context_resolution_required"
        ],
        "reviewer_b_context_resolution_required": reviewer_b[
            "context_resolution_required"
        ],
        **{
            f"reviewer_a_{capability}": reviewer_a[capability]
            for capability in PREDICTED_CAPABILITIES
        },
        **{
            f"reviewer_b_{capability}": reviewer_b[capability]
            for capability in PREDICTED_CAPABILITIES
        },
        "reviewer_a_forbidden_capabilities": reviewer_a[
            "forbidden_capabilities"
        ],
        "reviewer_b_forbidden_capabilities": reviewer_b[
            "forbidden_capabilities"
        ],
        "reviewer_a_rationale": reviewer_a["reviewer_rationale"],
        "reviewer_b_rationale": reviewer_b["reviewer_rationale"],
        **{field: "" for field in BLANK_DECISION_FIELDS},
        "query_rewrite_performed": "false",
        "assistant_context_attached": "false",
    }
    if tuple(value) != PACKET_FIELDS:
        raise AdjudicationPacketError("adjudication packet field order mismatch")
    return value


def build_adjudication_packet_bytes(root: Path = ROOT) -> bytes:
    summary = build_adjudication_case_summary(root)
    source_by_id = {
        row["review_case_id"]: row["source_role"] for row in summary["cases"]
    }
    rows_a = {row["review_case_id"]: row for row in _packet(root / CANONICAL_A_RELATIVE)}
    rows_b = {row["review_case_id"]: row for row in _packet(root / CANONICAL_B_RELATIVE)}
    rows = [
        _row(case_id, reason, source_by_id[case_id], rows_a[case_id], rows_b[case_id])
        for case_id, reason in EXPECTED_ADJUDICATION_CASES
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=PACKET_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def write_adjudication_packet(root: Path = ROOT) -> dict[str, Any]:
    value = build_adjudication_packet_bytes(root)
    path = root / ADJUDICATION_PACKET_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", ADJUDICATION_PACKET_RELATIVE.as_posix()],
        cwd=root,
        check=False,
    ).returncode == 0
    if not ignored:
        raise AdjudicationPacketError("adjudication packet is not ignored")
    observed = _packet(path)
    if len(observed) != 5 or tuple(observed[0]) != PACKET_FIELDS:
        raise AdjudicationPacketError("adjudication packet shape mismatch")
    if any(row[field] for row in observed for field in BLANK_DECISION_FIELDS):
        raise AdjudicationPacketError("adjudication decision field was prefilled")
    if any(
        row["query_rewrite_performed"] != "false"
        or row["assistant_context_attached"] != "false"
        for row in observed
    ):
        raise AdjudicationPacketError("immutable query/context flags mismatch")
    if set(PACKET_FIELDS) & FORBIDDEN_COLUMNS:
        raise AdjudicationPacketError("forbidden model/proposal field is present")
    return {
        "schema_version": "rq2a-r2a-adjudication-packet-manifest-v1",
        "stage": "RQ2-A-R2A",
        "status": "AWAITING_HUMAN_ADJUDICATION",
        "record_count": 5,
        "review_case_id_set_sha256": id_set_sha256(
            [row["review_case_id"] for row in observed]
        ),
        "packet_sha256": sha256_file(path),
        "packet_size_bytes": path.stat().st_size,
        "human_decision_field_count_per_case": len(BLANK_DECISION_FIELDS),
        "human_decision_fields_blank": True,
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
        "hidden_proposal_present": False,
        "model_output_present": False,
        "ignored": True,
        "tracked": False,
        "local_only": True,
        "double_build_sha256": sha256_bytes(build_adjudication_packet_bytes(root)),
    }
