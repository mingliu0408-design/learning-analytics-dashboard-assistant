"""Timezone-aware validity intervals and retrieval-query time semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
)

from . import INTERVAL_CONTRACT_ID


class RetrievalTimeIntegrityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_CODES = {
    "valid_from": ("INVALID_VALID_FROM", "NAIVE_VALID_FROM"),
    "valid_until": ("INVALID_VALID_UNTIL", "NAIVE_VALID_UNTIL"),
    "query_time": ("INVALID_QUERY_TIME", "NAIVE_QUERY_TIME"),
}


def parse_timezone_aware_iso8601_v1_1(value: str, field_name: str) -> datetime:
    if field_name not in _CODES:
        raise ValueError("UNKNOWN_TIME_FIELD")
    invalid_code, naive_code = _CODES[field_name]
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalTimeIntegrityError(invalid_code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RetrievalTimeIntegrityError(naive_code)
    return parsed.astimezone(timezone.utc)


def validate_episode_validity_interval_v1_1(
    episode: MemoryEpisodeV1_2,
) -> tuple[datetime, datetime | None]:
    starts = parse_timezone_aware_iso8601_v1_1(episode.valid_from, "valid_from")
    ends = (
        parse_timezone_aware_iso8601_v1_1(episode.valid_until, "valid_until")
        if episode.valid_until is not None
        else None
    )
    if ends is not None and starts >= ends:
        raise RetrievalTimeIntegrityError("VALID_INTERVAL_NOT_STRICTLY_INCREASING")
    return starts, ends


def temporal_validity_aware_v1_1(
    valid_from: str, valid_until: str | None, query_time: str
) -> bool:
    starts = parse_timezone_aware_iso8601_v1_1(valid_from, "valid_from")
    ends = (
        parse_timezone_aware_iso8601_v1_1(valid_until, "valid_until")
        if valid_until is not None
        else None
    )
    if ends is not None and starts >= ends:
        raise RetrievalTimeIntegrityError("VALID_INTERVAL_NOT_STRICTLY_INCREASING")
    query = parse_timezone_aware_iso8601_v1_1(query_time, "query_time")
    return starts <= query and (ends is None or query < ends)


def retrieval_time_integrity_contract() -> dict[str, Any]:
    return {
        "schema_version": "retrieval-time-integrity-contract-v1.1",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "contract_id": INTERVAL_CONTRACT_ID,
        "parser": "parse_timezone_aware_iso8601_v1_1",
        "timezone_required": True,
        "accepted_zone_forms": ["Z", "+00:00", "+01:00", "-05:00"],
        "comparison_instant": "UTC",
        "valid_interval": "valid_from < valid_until WHEN valid_until IS NOT NULL",
        "retrieval_semantics": (
            "valid_from_utc <= query_time_utc AND "
            "(valid_until IS NULL OR query_time_utc < valid_until_utc)"
        ),
        "start_inclusive": True,
        "end_exclusive": True,
        "episode_timezone_descriptive_only": True,
        "episode_timezone_authoritative_for_missing_offset": False,
        "implicit_local_timezone_allowed": False,
        "r2_naive_timestamp_interface_authorised_for_rq2c1": False,
        "failure_codes": [
            "INVALID_VALID_FROM",
            "NAIVE_VALID_FROM",
            "INVALID_VALID_UNTIL",
            "NAIVE_VALID_UNTIL",
            "INVALID_QUERY_TIME",
            "NAIVE_QUERY_TIME",
            "VALID_INTERVAL_NOT_STRICTLY_INCREASING",
        ],
    }
