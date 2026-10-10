"""Trusted scope and immutable source contracts, outside P3's four fields.

These objects are supplied by an authenticated local application, never parsed
from model output. A manifest is an assertion by that application; file presence
alone cannot establish learner authorisation, course binding or complete coverage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("An explicit timezone offset is required")
    return result


class ScopeError(ValueError):
    pass


class ClarificationRequired(ScopeError):
    pass


@dataclass(frozen=True)
class Calendar:
    version: str
    timezone: str
    weeks: Mapping[int, tuple[str, str]]

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not self.version or not self.weeks:
            raise ScopeError("A verified calendar version and weeks are required")
        weeks = {int(k): tuple(v) for k, v in self.weeks.items()}
        intervals = sorted((instant(a), instant(b)) for a, b in weeks.values())
        if any(a >= b for a, b in intervals) or any(
            a[1] > b[0] for a, b in zip(intervals, intervals[1:])
        ):
            raise ScopeError("Calendar weeks must have non-overlapping intervals")
        object.__setattr__(self, "weeks", MappingProxyType(weeks))


@dataclass(frozen=True)
class Scope:
    learner_id: str
    course_id: str
    snapshot: str
    start: str
    end: str
    timezone: str
    calendar_version: str | None = None
    lecture_item_id: str | None = None
    time_basis: str = "activity_window"

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in (
            self.learner_id, self.course_id, self.snapshot, self.start, self.end
        )):
            raise ScopeError("Scope identities and interval must be explicit")
        ZoneInfo(self.timezone)
        if instant(self.start) >= instant(self.end) or self.time_basis != "activity_window":
            raise ScopeError("Expected a start-inclusive/end-exclusive activity window")

    def public_window(self):
        return {"start_inclusive": self.start, "end_exclusive": self.end,
                "timezone": self.timezone, "time_basis": self.time_basis}

    def internal(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class Coverage:
    """Explicit complete observation claim; required to interpret absence as zero."""
    learner_ids: tuple[str, ...]
    course_id: str
    start: str
    end: str
    metrics: tuple[str, ...]
    basis: str

    def __post_init__(self):
        object.__setattr__(self, "learner_ids", tuple(self.learner_ids))
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if instant(self.start) >= instant(self.end):
            raise ScopeError("Invalid coverage interval")

    def covers(self, scope, metric):
        return bool(self.basis) and scope.learner_id in self.learner_ids and (
            self.course_id == scope.course_id and metric in self.metrics
            and instant(self.start) <= instant(scope.start)
            and instant(self.end) >= instant(scope.end))


@dataclass(frozen=True)
class SourceSpec:
    columns: tuple[str, ...]
    course_column: str | None = None
    single_course: str | None = None
    course_binding_evidence: str | None = None
    observation: str = "none"  # timestamp, week, interval, content_week, cumulative
    time_column: str | None = None
    week_column: str | None = None
    calendar_version: str | None = None
    timestamp_timezone: str | None = None
    interval: tuple[str, str] | None = None
    learner_column: str = "ID"
    item_column: str | None = None
    event_id_column: str | None = None
    coverage: tuple[Coverage, ...] = ()
    metric_semantics: tuple[str, ...] = ()
    source_sha256: str = ""
    status: str = "AVAILABLE"

    def __post_init__(self):
        for name in ("columns", "coverage", "metric_semantics"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.interval is not None:
            object.__setattr__(self, "interval", tuple(self.interval))
        if self.observation not in {"none", "timestamp", "week", "interval", "content_week", "cumulative"}:
            raise ScopeError("Unknown observation basis")
        if self.observation == "timestamp" and not self.time_column:
            raise ScopeError("Timestamp field required")
        if self.observation == "week" and not self.week_column:
            raise ScopeError("Observation-week field required")


@dataclass(frozen=True)
class Snapshot:
    version: str
    tables: Mapping[str, tuple[Mapping[str, Any], ...] | None]
    specs: Mapping[str, SourceSpec]
    roster: Mapping[str, tuple[str, ...]]
    calendars: Mapping[str, Calendar] = field(default_factory=dict)
    origin: str = "LIVE"

    def __post_init__(self):
        if not self.version or self.origin not in {"LIVE", "SYNTHETIC"}:
            raise ScopeError("Explicit snapshot version and source origin required")
        # JSON round-trip rejects arbitrary objects, NaN, and nested mutable frames.
        frozen = {}
        for name, rows in self.tables.items():
            if rows is None:
                frozen[name] = None
                continue
            copied = json.loads(canonical(list(rows)))
            if any(not isinstance(r, dict) or any(isinstance(v, (dict, list)) for v in r.values()) for r in copied):
                raise ScopeError("Raw rows must be flat scalar records")
            frozen[name] = tuple(MappingProxyType(row) for row in copied)
        object.__setattr__(self, "tables", MappingProxyType(frozen))
        object.__setattr__(self, "specs", MappingProxyType(dict(self.specs)))
        object.__setattr__(self, "roster", MappingProxyType({str(k): tuple(v) for k, v in self.roster.items()}))
        object.__setattr__(self, "calendars", MappingProxyType(dict(self.calendars)))

    def validate(self, scope: Scope):
        if scope.snapshot != self.version:
            raise ScopeError("SOURCE_SNAPSHOT_MISMATCH")
        if scope.learner_id not in self.roster:
            raise ScopeError("UNKNOWN_LEARNER_ID")
        if scope.course_id not in self.roster[scope.learner_id]:
            raise ScopeError("UNAUTHORISED_COURSE")
        calendar = self.calendars.get(scope.course_id)
        if scope.calendar_version is not None and (
            calendar is None or scope.calendar_version != calendar.version
            or scope.timezone != calendar.timezone
        ):
            raise ScopeError("CALENDAR_BINDING_MISMATCH")

    def validate_query(self, scope, query, now=None):
        """Queries cannot silently contradict chart controls or invent a week/item."""
        import re
        self.validate(scope)
        q = query.casefold()
        relative = bool(re.search(r"\bthis week\b|本周|这周|这个星期", q))
        named = re.search(r"\bweek\s*(\d+)\b|第\s*(\d+)\s*周", q)
        calendar = self.calendars.get(scope.course_id)
        if relative or named:
            if calendar is None or scope.calendar_version != calendar.version:
                raise ClarificationRequired("Please select a verified course calendar and timezone.")
            if relative:
                if now is None or now.tzinfo is None:
                    raise ClarificationRequired("Please provide the current time in the course timezone.")
                matches = [v for v in calendar.weeks.values() if instant(v[0]) <= now < instant(v[1])]
            else:
                week = int(named.group(1) or named.group(2))
                matches = [calendar.weeks[week]] if week in calendar.weeks else []
            if len(matches) != 1 or (instant(scope.start), instant(scope.end)) != tuple(map(instant, matches[0])):
                raise ClarificationRequired("Please select the requested week in the dashboard controls.")
        if re.search(r"\b(this|current)\s+(lecture|video)\b|这(?:一)?(?:节课|讲|个视频)|当前(?:讲座|课程视频)", q):
            if not scope.lecture_item_id:
                raise ClarificationRequired("Please select the lecture item you mean.")
