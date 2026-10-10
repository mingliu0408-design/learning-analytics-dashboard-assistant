"""Timezone-aware event, creation, ingestion, and payload-reference ordering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .payload_identity_binding import PayloadIntegrityError
from .payload_linkage_schema import MemoryEpisodeV1_2, MemoryPayloadRefV1_2


_NAIVE_CODES = {
    "event_time": "NAIVE_EVENT_TIME",
    "created_at": "NAIVE_CREATED_AT",
    "ingested_at": "NAIVE_INGESTED_AT",
    "payload_ref_created_at": "NAIVE_PAYLOAD_REF_CREATED_AT",
}


def parse_aware_iso8601_v1(value: str, field: str) -> datetime:
    try:
        if not isinstance(value, str) or not value:
            raise ValueError
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError) as exc:
        raise PayloadIntegrityError("INVALID_ISO_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PayloadIntegrityError(_NAIVE_CODES[field])
    return parsed.astimezone(timezone.utc)


def validate_temporal_integrity_v1(
    episode: MemoryEpisodeV1_2, payload_ref: MemoryPayloadRefV1_2
) -> None:
    event = parse_aware_iso8601_v1(episode.event_time, "event_time")
    created = parse_aware_iso8601_v1(episode.created_at, "created_at")
    ingested = parse_aware_iso8601_v1(episode.ingested_at, "ingested_at")
    reference_created = parse_aware_iso8601_v1(
        payload_ref.created_at, "payload_ref_created_at"
    )
    if event > created:
        raise PayloadIntegrityError("EVENT_AFTER_CREATED")
    if created > ingested:
        raise PayloadIntegrityError("CREATED_AFTER_INGESTED")
    if reference_created != ingested:
        raise PayloadIntegrityError("PAYLOAD_REF_TIME_NOT_INGESTION_TIME")


def temporal_integrity_contract() -> dict[str, Any]:
    return {
        "schema_version": "temporal-integrity-contract-v1",
        "stage": "RQ2-C0-R4",
        "status": "FROZEN",
        "timestamp_format": "ISO-8601_TIMEZONE_AWARE",
        "accepted_zone_forms": ["Z", "+00:00", "+01:00", "-05:00"],
        "naive_datetime_allowed": False,
        "timezone_abbreviation_allowed": False,
        "local_timezone_assumption_allowed": False,
        "comparison_instant": "UTC",
        "ordering": "event_time <= created_at <= ingested_at",
        "payload_reference_created_at": "SAME_INSTANT_AS_EPISODE_INGESTED_AT",
        "failure_codes": [
            "NAIVE_EVENT_TIME",
            "NAIVE_CREATED_AT",
            "NAIVE_INGESTED_AT",
            "NAIVE_PAYLOAD_REF_CREATED_AT",
            "EVENT_AFTER_CREATED",
            "CREATED_AFTER_INGESTED",
            "PAYLOAD_REF_TIME_NOT_INGESTION_TIME",
            "INVALID_ISO_TIMESTAMP",
        ],
        "fail_closed": True,
    }
