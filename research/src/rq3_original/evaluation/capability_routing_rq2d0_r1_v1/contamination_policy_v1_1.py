"""Pre-registered hard/sensitivity contamination policy for future D1."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d0_v1.contamination_contract import (
    normalise_query,
    query_history_commitment,
)

from . import HARD_PARTITIONS, SENSITIVITY_PARTITIONS


class ContaminationPolicyError(RuntimeError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def target_identity(
    *,
    query: str,
    history: Any,
    source_record_identity_hash: str,
    family_or_group_hash: str | None = None,
) -> dict[str, str]:
    row = {
        "exact_query_hash": _hash(query),
        "normalised_query_hash": _hash(normalise_query(query)),
        "query_history_hash": query_history_commitment(query, history),
        "source_record_identity_hash": source_record_identity_hash,
    }
    if family_or_group_hash:
        row["family_or_group_hash_if_available"] = family_or_group_hash
    return row


OVERLAP_FIELDS = {
    "exact_overlap_count": "exact_query_hash",
    "normalised_overlap_count": "normalised_query_hash",
    "query_history_overlap_count": "query_history_hash",
    "source_record_collision_count": "source_record_identity_hash",
    "family_group_overlap_count": "family_or_group_hash_if_available",
}


def audit_hash_identities(
    track_rows: Sequence[Mapping[str, str]],
    reference_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    by_partition: dict[str, list[Mapping[str, str]]] = {}
    for row in reference_rows:
        by_partition.setdefault(str(row["partition_id"]), []).append(row)
    if set(by_partition) != set(HARD_PARTITIONS) | set(SENSITIVITY_PARTITIONS):
        raise ContaminationPolicyError(
            "BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE"
        )
    partition_results: list[dict[str, Any]] = []
    hard_conflicts = 0
    sensitivity_overlaps = 0
    sensitivity_registry: list[dict[str, Any]] = []
    for partition_id in (*HARD_PARTITIONS, *SENSITIVITY_PARTITIONS):
        references = by_partition[partition_id]
        reference_sets = {
            output: {str(row.get(field) or "") for row in references} - {""}
            for output, field in OVERLAP_FIELDS.items()
        }
        counts = {output: 0 for output in OVERLAP_FIELDS}
        any_overlap_count = 0
        for index, track in enumerate(track_rows):
            matched = False
            matched_kinds: list[str] = []
            for output, field in OVERLAP_FIELDS.items():
                value = str(track.get(field) or "")
                hit = bool(value and value in reference_sets[output])
                counts[output] += int(hit)
                if hit:
                    matched = True
                    matched_kinds.append(output)
            if matched:
                any_overlap_count += 1
                if partition_id in SENSITIVITY_PARTITIONS:
                    sensitivity_registry.append(
                        {
                            "opaque_track_row_index": index,
                            "partition_id": partition_id,
                            "overlap_kinds": matched_kinds,
                        }
                    )
        role = "HARD_FINAL_INDEPENDENCE" if partition_id in HARD_PARTITIONS else "SENSITIVITY"
        if role == "HARD_FINAL_INDEPENDENCE":
            hard_conflicts += any_overlap_count
        else:
            sensitivity_overlaps += any_overlap_count
        partition_results.append(
            {
                "partition_id": partition_id,
                "policy_role": role,
                **counts,
                "any_identity_overlap_case_count": any_overlap_count,
            }
        )
    return {
        "schema_version": "track-b-contamination-audit-summary-v1",
        "status": "PASS" if hard_conflicts == 0 else "TRACK_B_FINAL_EVALUATION_INVALID",
        "track_b_record_count": len(track_rows),
        "per_partition": partition_results,
        "hard_conflict_count": hard_conflicts,
        "sensitivity_overlap_count": sensitivity_overlaps,
        "sensitivity_registry": sensitivity_registry,
        "automatic_case_deletion_performed": False,
        "label_conflict_audit_deferred_until_capability_gold": True,
        "query_history_emitted": False,
    }


def require_final_independence(audit: Mapping[str, Any]) -> None:
    if int(audit.get("hard_conflict_count", -1)) != 0 or audit.get("status") != "PASS":
        raise ContaminationPolicyError("TRACK_B_FINAL_EVALUATION_INVALID")


def contamination_policy_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-contamination-policy-v1.1",
        "status": "FROZEN_BEFORE_ANY_RAW_TRACK_B_ACCESS",
        "hard_final_independence_partitions": list(HARD_PARTITIONS),
        "sensitivity_partitions": list(SENSITIVITY_PARTITIONS),
        "identity_overlap_types": [
            "exact_query",
            "normalised_query",
            "query_plus_history",
            "source_record_identity",
        ],
        "family_or_group_overlap": "REPORT_WHERE_AVAILABLE",
        "hard_overlap_decision": "TRACK_B_FINAL_EVALUATION_INVALID",
        "sensitivity_overlap_decision": "RETAIN_AND_REPORT_BY_PARTITION",
        "sensitivity_overlap_may_automatically_delete_case": False,
        "label_conflict_timing": "ONLY_AFTER_TRACK_B_CAPABILITY_GOLD_FROZEN",
        "post_overlap_policy_change_permitted": False,
    }
