"""Track-B dependence grouping based only on frozen ``contrast_set_id``."""

from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any, Mapping, Sequence


GROUPING_DOMAIN = b"RQ2_FAMILY_OR_GROUP_IDENTITY_V1\x00"
TRACK_B_GROUPING_SOURCE = "contrast_set_id"
SCENARIO_FAMILY_CLUSTER_ROLE = "NOT_ELIGIBLE_UNIQUE_PER_RECORD"


class TrackBGroupingError(RuntimeError):
    pass


def contrast_set_grouping_hash(contrast_set_id: str) -> str:
    if not isinstance(contrast_set_id, str) or not contrast_set_id:
        raise TrackBGroupingError("TRACK_B_FINAL_EVALUATION_INVALID")
    return hashlib.sha256(GROUPING_DOMAIN + contrast_set_id.encode("utf-8")).hexdigest()


def grouping_hash_from_track_b_record(record: Mapping[str, Any]) -> str:
    """Read exactly ``contrast_set_id``; scenario-family content is irrelevant."""

    return contrast_set_grouping_hash(str(record.get(TRACK_B_GROUPING_SOURCE) or ""))


def validate_track_b_contrast_groups(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(records) != 48:
        raise TrackBGroupingError("TRACK_B_FINAL_EVALUATION_INVALID")
    contrast_ids = [str(row.get("contrast_set_id") or "") for row in records]
    scenario_ids = [str(row.get("scenario_family_id") or "") for row in records]
    contrast_counts = Counter(contrast_ids)
    if (
        not all(contrast_ids)
        or len(contrast_counts) != 24
        or set(contrast_counts.values()) != {2}
        or not all(scenario_ids)
        or len(set(scenario_ids)) != 48
    ):
        raise TrackBGroupingError("TRACK_B_FINAL_EVALUATION_INVALID")
    return {
        "status": "PASS",
        "record_count": 48,
        "track_b_grouping_source": TRACK_B_GROUPING_SOURCE,
        "contrast_set_group_count": 24,
        "records_per_contrast_set": 2,
        "scenario_family_unique_count": 48,
        "scenario_family_id_cluster_role": SCENARIO_FAMILY_CLUSTER_ROLE,
        "bootstrap_cluster_source": TRACK_B_GROUPING_SOURCE,
    }


def grouping_semantics_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-grouping-semantics-contract-v1",
        "status": "FROZEN_BEFORE_RAW_TRACK_B_ACCESS",
        "grouping_hash_domain": "RQ2_FAMILY_OR_GROUP_IDENTITY_V1\\x00",
        "track_b_grouping_source": TRACK_B_GROUPING_SOURCE,
        "expected_track_b_records": 48,
        "expected_contrast_groups": 24,
        "expected_records_per_contrast_group": 2,
        "scenario_family_unique_count": 48,
        "scenario_family_id_cluster_role": SCENARIO_FAMILY_CLUSTER_ROLE,
        "scenario_family_id_may_be_bootstrap_cluster": False,
        "grouping_overlap_is_query_or_context_contamination": False,
        "grouping_overlap_can_invalidate_final_evaluation": False,
        "grouping_validation_failure": "TRACK_B_FINAL_EVALUATION_INVALID",
    }
