"""Identity-vs-grouping contamination semantics for future Track-B D1."""

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


IDENTITY_OVERLAP_FIELDS = {
    "exact_overlap_count": "exact_query_hash",
    "normalised_overlap_count": "normalised_query_hash",
    "query_history_overlap_count": "query_history_hash",
    "source_record_collision_count": "source_record_identity_hash",
}
GROUPING_OVERLAP_FIELD = (
    "family_group_overlap_count",
    "family_or_group_hash_if_available",
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def target_identity(
    *,
    query: str,
    history: Any,
    source_record_identity_hash: str,
    family_or_group_hash: str | None = None,
) -> dict[str, str]:
    result = {
        "exact_query_hash": _hash_text(query),
        "normalised_query_hash": _hash_text(normalise_query(query)),
        "query_history_hash": query_history_commitment(query, history),
        "source_record_identity_hash": source_record_identity_hash,
    }
    if family_or_group_hash:
        result[GROUPING_OVERLAP_FIELD[1]] = family_or_group_hash
    return result


def _overlap_class(identity_hit: bool, grouping_hit: bool) -> str:
    if identity_hit and grouping_hit:
        return "IDENTITY_AND_GROUPING_OVERLAP"
    if identity_hit:
        return "IDENTITY_OVERLAP"
    if grouping_hit:
        return "GROUPING_ONLY_OVERLAP"
    raise AssertionError("overlap class requires at least one hit")


def audit_hash_identities_v1_2(
    track_rows: Sequence[Mapping[str, str]],
    reference_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    by_partition: dict[str, list[Mapping[str, str]]] = {}
    for row in reference_rows:
        by_partition.setdefault(str(row.get("partition_id") or ""), []).append(row)
    expected_partitions = set(HARD_PARTITIONS) | set(SENSITIVITY_PARTITIONS)
    if set(by_partition) != expected_partitions:
        raise ContaminationPolicyError(
            "BLOCKED_RQ2_D0_R2_CONTAMINATION_SEMANTICS"
        )

    hard_case_indices: set[int] = set()
    sensitivity_case_indices: set[int] = set()
    grouping_case_indices: set[int] = set()
    hard_identity_events = 0
    sensitivity_identity_events = 0
    grouping_events = 0
    overlap_registry: list[dict[str, Any]] = []
    hard_conflict_registry: list[dict[str, Any]] = []
    sensitivity_registry: list[dict[str, Any]] = []
    grouping_diagnostics: list[dict[str, Any]] = []
    partition_results: list[dict[str, Any]] = []

    for partition_id in (*HARD_PARTITIONS, *SENSITIVITY_PARTITIONS):
        references = by_partition[partition_id]
        identity_sets = {
            field: {str(row.get(field) or "") for row in references} - {""}
            for field in IDENTITY_OVERLAP_FIELDS.values()
        }
        group_field = GROUPING_OVERLAP_FIELD[1]
        grouping_set = {str(row.get(group_field) or "") for row in references} - {""}
        counts = {output: 0 for output in IDENTITY_OVERLAP_FIELDS}
        identity_case_count = 0
        grouping_case_count = 0
        grouping_only_count = 0

        for index, track in enumerate(track_rows):
            identity_kinds: list[str] = []
            for output, field in IDENTITY_OVERLAP_FIELDS.items():
                value = str(track.get(field) or "")
                hit = bool(value and value in identity_sets[field])
                counts[output] += int(hit)
                if hit:
                    identity_kinds.append(field)
            grouping_value = str(track.get(group_field) or "")
            grouping_hit = bool(grouping_value and grouping_value in grouping_set)
            identity_hit = bool(identity_kinds)
            identity_case_count += int(identity_hit)
            grouping_case_count += int(grouping_hit)
            grouping_only_count += int(grouping_hit and not identity_hit)
            if not identity_hit and not grouping_hit:
                continue

            event = {
                "opaque_track_row_index": index,
                "partition_id": partition_id,
                "overlap_class": _overlap_class(identity_hit, grouping_hit),
                "identity_overlap_kinds": identity_kinds,
                "grouping_overlap": grouping_hit,
            }
            overlap_registry.append(event)
            if grouping_hit:
                grouping_case_indices.add(index)
                grouping_events += 1
                grouping_diagnostics.append(event)
            if partition_id in HARD_PARTITIONS and identity_hit:
                hard_case_indices.add(index)
                hard_identity_events += 1
                hard_conflict_registry.append(event)
            if partition_id in SENSITIVITY_PARTITIONS and identity_hit:
                sensitivity_case_indices.add(index)
                sensitivity_identity_events += 1
            if partition_id in SENSITIVITY_PARTITIONS:
                sensitivity_registry.append(event)

        partition_results.append(
            {
                "partition_id": partition_id,
                "policy_role": (
                    "HARD_FINAL_INDEPENDENCE"
                    if partition_id in HARD_PARTITIONS
                    else "SENSITIVITY"
                ),
                **counts,
                "any_identity_overlap_case_count": identity_case_count,
                "family_group_overlap_count": grouping_case_count,
                "grouping_only_overlap_case_count": grouping_only_count,
            }
        )

    hard_count = len(hard_case_indices)
    return {
        "schema_version": "track-b-contamination-audit-summary-v1.2",
        "status": "PASS" if hard_count == 0 else "TRACK_B_FINAL_EVALUATION_INVALID",
        "track_b_record_count": len(track_rows),
        "per_partition": partition_results,
        "hard_conflicting_track_case_count": hard_count,
        "hard_identity_overlap_event_count": hard_identity_events,
        "sensitivity_identity_overlap_case_count": len(sensitivity_case_indices),
        "sensitivity_identity_overlap_event_count": sensitivity_identity_events,
        "grouping_overlap_case_count": len(grouping_case_indices),
        "grouping_overlap_event_count": grouping_events,
        "hard_conflict_count": hard_count,
        "sensitivity_overlap_count": len(sensitivity_case_indices),
        "hard_conflict_registry": hard_conflict_registry,
        "sensitivity_registry": sensitivity_registry,
        "grouping_diagnostics": grouping_diagnostics,
        "overlap_registry": overlap_registry,
        "identity_overlap_fields": list(IDENTITY_OVERLAP_FIELDS.values()),
        "grouping_overlap_field": GROUPING_OVERLAP_FIELD[1],
        "grouping_only_overlap_can_invalidate": False,
        "automatic_case_deletion_performed": False,
        "label_conflict_audit_deferred_until_capability_gold": True,
        "query_history_emitted": False,
    }


def require_final_independence_v1_2(audit: Mapping[str, Any]) -> None:
    if audit.get("status") != "PASS" or int(audit.get("hard_conflict_count", -1)) != 0:
        raise ContaminationPolicyError("TRACK_B_FINAL_EVALUATION_INVALID")


def contamination_policy_document_v1_2() -> dict[str, Any]:
    return {
        "schema_version": "track-b-contamination-policy-v1.2",
        "status": "FROZEN_BEFORE_ANY_RAW_TRACK_B_ACCESS",
        "hard_final_independence_partitions": list(HARD_PARTITIONS),
        "sensitivity_partitions": list(SENSITIVITY_PARTITIONS),
        "hard_identity_fields": list(IDENTITY_OVERLAP_FIELDS.values()),
        "hard_identity_field_count": 4,
        "grouping_fields": "REPORT_ONLY",
        "grouping_field": GROUPING_OVERLAP_FIELD[1],
        "grouping_overlap_can_invalidate_final_evaluation": False,
        "track_b_grouping_source": "contrast_set_id",
        "scenario_family_id_cluster_role": "NOT_ELIGIBLE_UNIQUE_PER_RECORD",
        "hard_conflict_count_semantics": (
            "unique Track B cases with one or more hard identity overlaps across "
            "all hard partitions"
        ),
        "hard_identity_overlap_event_count_semantics": (
            "Track B case by hard partition identity-overlap events"
        ),
        "sensitivity_overlap_count_semantics": (
            "unique Track B cases with identity overlap against sensitivity "
            "partitions; grouping overlap is reported separately"
        ),
        "sensitivity_overlap_decision": "RETAIN_AND_REPORT_BY_PARTITION",
        "sensitivity_overlap_may_automatically_delete_case": False,
        "label_conflict_timing": "ONLY_AFTER_TRACK_B_CAPABILITY_GOLD_FROZEN",
        "post_overlap_policy_change_permitted": False,
    }
