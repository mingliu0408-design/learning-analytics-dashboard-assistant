"""Exact clerical canonicalisation and schema validation for adjudication."""

from __future__ import annotations

import csv
from datetime import date
import io
from pathlib import Path
import subprocess
from typing import Any

from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    validate_forbidden_capabilities,
)

from . import (
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    CAPABILITIES,
    COMPLETED_ADJUDICATION_SHA256,
    CONTEXT_RESOLUTION_CASE_ID,
    MISSING_CONTEXT_CASE_IDS,
    ROOT,
    RQ2AR2BError,
    SYNTHETIC_NATURALNESS_CASE_ID,
    sha256_bytes,
    sha256_file,
)


EXPECTED_MISSING_DISPOSITION = (
    "EXCLUDE_FROM_CAPABILITY_GOLD_BUT_RETAIN_AS_CONTEXT_MISSING_CASE"
)


class AdjudicationCanonicalisationError(RQ2AR2BError):
    pass


def canonicalise_adjudication_bytes(value: bytes) -> bytes:
    rows = list(csv.DictReader(io.StringIO(value.decode("utf-8"), newline="")))
    if (
        sha256_bytes(value) != COMPLETED_ADJUDICATION_SHA256
        or value.count(b"2026/8/26") != 5
        or value.count(b"2026-08-26") != 0
        or value.count(b"FALSE") != 10
        or any(row["query_rewrite_performed"] != "FALSE" for row in rows)
        or any(row["assistant_context_attached"] != "FALSE" for row in rows)
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_CANONICALISATION"
        )
    canonical = value.replace(b"2026/8/26", b"2026-08-26").replace(
        b"FALSE", b"false"
    )
    if (
        canonical.count(b"2026/8/26")
        or canonical.count(b"2026-08-26") != 5
        or canonical.count(b"FALSE")
        or sha256_bytes(canonical) != CANONICAL_ADJUDICATION_SHA256
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_CANONICALISATION"
        )
    return canonical


def write_canonical_adjudication(
    completed_path: Path, root: Path = ROOT
) -> tuple[Path, dict[str, Any]]:
    source = completed_path.read_bytes()
    canonical = canonicalise_adjudication_bytes(source)
    target = root / CANONICAL_ADJUDICATION_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical)
    if target.read_bytes() != canonical or sha256_file(target) != (
        CANONICAL_ADJUDICATION_SHA256
    ):
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_CANONICALISATION"
        )
    ignored = (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", str(CANONICAL_ADJUDICATION_RELATIVE)],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )
    tracked = (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(CANONICAL_ADJUDICATION_RELATIVE)],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )
    if not ignored or tracked:
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_CANONICALISATION"
        )
    return target, {
        "schema_version": "rq2a-r2b-adjudication-canonicalisation-manifest-v1",
        "stage": "RQ2-A-R2B",
        "status": "PASS",
        "source_completed_sha256": COMPLETED_ADJUDICATION_SHA256,
        "canonical_sha256": CANONICAL_ADJUDICATION_SHA256,
        "source_record_count": 5,
        "date_replacement": {"from": "2026/8/26", "to": "2026-08-26", "count": 5},
        "immutable_boolean_replacement": {"from": "FALSE", "to": "false", "count": 10},
        "total_authorised_byte_replacements": 15,
        "other_byte_changes": 0,
        "human_annotation_changed": False,
        "adjudication_decision_changed": False,
        "canonical_packet_local_only": True,
        "canonical_packet_ignored": True,
        "canonical_packet_tracked": False,
    }


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_canonical_adjudication(path: Path) -> dict[str, Any]:
    if sha256_file(path) != CANONICAL_ADJUDICATION_SHA256:
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_CANONICALISATION"
        )
    rows = _rows(path)
    if len(rows) != 5 or len({row["review_case_id"] for row in rows}) != 5:
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_SCHEMA"
        )
    if {row["adjudicator_id"] for row in rows} != {"HUMAN_ADJUDICATOR"}:
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_SCHEMA"
        )
    by_id = {row["review_case_id"]: row for row in rows}
    try:
        for row in rows:
            if date.fromisoformat(row["adjudication_date"]).isoformat() != row[
                "adjudication_date"
            ]:
                raise ValueError("non-canonical date")
            if row["query_rewrite_performed"] != "false" or row[
                "assistant_context_attached"
            ] != "false":
                raise ValueError("immutable flag changed")
            if row["adjudicated_case_validity"] not in {
                "INCLUDE_VALID_CASE",
                "EXCLUDE_INVALID_CASE",
            }:
                raise ValueError("invalid case validity")
            if row["adjudicated_naturalness_1_to_5"] not in {
                "1",
                "2",
                "3",
                "4",
                "5",
            }:
                raise ValueError("invalid naturalness")
            if row["adjudicated_context_link_valid"] not in {
                "YES",
                "NO",
                "NOT_APPLICABLE",
            }:
                raise ValueError("invalid context link")
            if row["adjudicated_context_sufficient"] not in {
                "YES",
                "NO",
                "NOT_APPLICABLE",
            }:
                raise ValueError("invalid context sufficiency")
            if row["adjudicated_capability_unambiguous"] not in {"YES", "NO"}:
                raise ValueError("invalid capability ambiguity")
            binary_fields = (
                "adjudicated_context_resolution_required",
                *(f"adjudicated_{capability}" for capability in CAPABILITIES),
            )
            if any(row[field] not in {"YES", "NO"} for field in binary_fields):
                raise ValueError("invalid binary final")
            if any(
                value == "UNCERTAIN"
                for field, value in row.items()
                if field.startswith("adjudicated_")
            ):
                raise ValueError("uncertain final")
            active = {
                capability
                for capability in CAPABILITIES
                if row[f"adjudicated_{capability}"] == "YES"
            }
            if "clarification" in active and active != {"clarification"}:
                raise ValueError("clarification not exclusive")
            if "safe_direct_response" in active and active != {
                "safe_direct_response"
            }:
                raise ValueError("safe direct response not exclusive")
            forbidden = set(
                validate_forbidden_capabilities(
                    row["adjudicated_forbidden_capabilities"]
                )
            )
            if active & forbidden:
                raise ValueError("required/forbidden overlap")

        if set(MISSING_CONTEXT_CASE_IDS) - set(by_id):
            raise ValueError("missing expected authentic cases")
        for case_id in MISSING_CONTEXT_CASE_IDS:
            row = by_id[case_id]
            expected = {
                "source_role": "authentic",
                "adjudicated_case_validity": "INCLUDE_VALID_CASE",
                "adjudicated_context_link_valid": "NOT_APPLICABLE",
                "adjudicated_context_sufficient": "NO",
                "adjudicated_capability_unambiguous": "YES",
                "adjudicated_context_resolution_required": "YES",
                "adjudicated_clarification": "YES",
                "missing_context_disposition": EXPECTED_MISSING_DISPOSITION,
            }
            if any(row[field] != value for field, value in expected.items()):
                raise ValueError("authentic missing-context decision mismatch")
            if any(
                row[f"adjudicated_{capability}"] != "NO"
                for capability in CAPABILITIES
                if capability != "clarification"
            ):
                raise ValueError("authentic missing-context exact set mismatch")

        naturalness = by_id[SYNTHETIC_NATURALNESS_CASE_ID]
        if naturalness["source_role"] != "synthetic" or naturalness[
            "adjudicated_naturalness_1_to_5"
        ] != "4":
            raise ValueError("synthetic naturalness decision mismatch")
        if any(
            naturalness[f"adjudicated_{capability}"] != "YES"
            for capability in (
                "dashboard_evidence",
                "course_retrieval",
                "episodic_memory",
                "planning",
            )
        ) or any(
            naturalness[f"adjudicated_{capability}"] != "NO"
            for capability in ("safe_direct_response", "clarification")
        ):
            raise ValueError("synthetic naturalness capability mismatch")

        resolution = by_id[CONTEXT_RESOLUTION_CASE_ID]
        if resolution["adjudicated_context_resolution_required"] != "NO" or (
            resolution["adjudicated_dashboard_evidence"] != "YES"
        ) or any(
            resolution[f"adjudicated_{capability}"] != "NO"
            for capability in CAPABILITIES
            if capability != "dashboard_evidence"
        ):
            raise ValueError("context-resolution decision mismatch")
    except (KeyError, ValueError) as exc:
        raise AdjudicationCanonicalisationError(
            "BLOCKED_RQ2_A_R2B_ADJUDICATION_SCHEMA"
        ) from exc
    return {
        "status": "PASS",
        "case_count": 5,
        "unique_adjudicator_id_count": 1,
        "iso_date_count": 5,
        "uncertain_final_value_count": 0,
        "authentic_missing_context_case_count": 3,
        "required_forbidden_overlap_count": 0,
        "clarification_exclusivity": "PASS",
        "safe_direct_response_exclusivity": "PASS",
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
    }
