"""Transparent corrected variants of the four legacy activity aggregators.

Counts describe records, not learning outcomes. Overview reuses these facts and
never adds a fifth raw source. Moodle clicks, Echo views and network interactions
remain separate measurements even if they describe overlapping actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from zoneinfo import ZoneInfo

from . import DOMAINS
from .scope import Scope, Snapshot, canonical, digest, instant, ClarificationRequired


@dataclass(frozen=True)
class Slice:
    rows: tuple
    status: str


@dataclass(frozen=True)
class Fact:
    domain: str
    metric: str
    value: object
    status: str
    definition: str
    time_basis: str
    table: str
    spans: tuple[int, ...]
    scope: Scope

    def public(self):
        return {"value": self.value, "status": self.status,
                "definition": self.definition, "time_basis": self.time_basis}

    def trace(self):
        # Private identities stay here. Review exporters must redact them.
        return {"fact_id": digest([self.scope.internal(), self.domain, self.metric,
                                   self.value, self.table, self.spans]),
                "domain": self.domain, "metric": self.metric,
                **self.public(), "table": self.table,
                "source_row_spans": list(self.spans), "scope": self.scope.internal()}


def source_rows(snapshot: Snapshot, scope: Scope, table: str, *, temporal=True) -> Slice:
    snapshot.validate(scope)
    spec = snapshot.specs.get(table)
    rows = snapshot.tables.get(table)
    if spec is None or rows is None:
        return Slice((), spec.status if spec and spec.status != "AVAILABLE" else "SOURCE_UNAVAILABLE")
    if spec.status != "AVAILABLE":
        return Slice((), spec.status)
    if not spec.course_column and not (spec.single_course == scope.course_id and spec.course_binding_evidence):
        return Slice((), "UNVERIFIED_COURSE_SCOPE")
    network = table in {"reply_network", "view_network"}
    required = {"From", "To"} if network else {spec.learner_column}
    if spec.course_column:
        required.add(spec.course_column)
    if not required.issubset(spec.columns):
        return Slice((), "INVALID_SOURCE_SCHEMA")
    selected = []
    for i, row in enumerate(rows, 2):
        if network:
            belongs = any(str(row.get(k)) == scope.learner_id for k in ("From", "To"))
        else:
            belongs = str(row.get(spec.learner_column)) == scope.learner_id
        if belongs and (not spec.course_column or str(row.get(spec.course_column)) == scope.course_id):
            selected.append((i, row))
    # Identity/course filtering precedes parsing timestamps, optional text and edges.
    if temporal:
        a, b = instant(scope.start), instant(scope.end)
        calendar = snapshot.calendars.get(scope.course_id)
        if spec.observation in {"none", "cumulative", "content_week"}:
            return Slice((), "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")
        if spec.observation == "week" and (
            not calendar or scope.calendar_version != calendar.version or spec.calendar_version != calendar.version
            or spec.week_column == "Content_week"
        ):
            return Slice((), "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")
        kept = []
        try:
            if spec.observation == "interval":
                # Preaggregated intervals cannot be cropped or proportionally allocated.
                if spec.interval is None or tuple(map(instant, spec.interval)) != (a, b):
                    return Slice((), "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")
                kept = selected
            elif spec.observation in {"timestamp", "week"}:
                for i, row in selected:
                    if spec.observation == "timestamp":
                        t = datetime.fromisoformat(str(row[spec.time_column]).replace("Z", "+00:00"))
                        if t.tzinfo is None:
                            if not spec.timestamp_timezone:
                                return Slice((), "UNVERIFIED_TIMESTAMP_TIMEZONE")
                            # Reject ambiguous/nonexistent local times, including DST folds.
                            zone = ZoneInfo(spec.timestamp_timezone)
                            if t.replace(tzinfo=zone, fold=0).utcoffset() != t.replace(tzinfo=zone, fold=1).utcoffset():
                                return Slice((), "AMBIGUOUS_LOCAL_TIMESTAMP")
                            t = t.replace(tzinfo=zone)
                        if a <= t < b:
                            kept.append((i, row))
                    else:
                        raw_week = float(row[spec.week_column])
                        if not raw_week.is_integer():
                            raise ValueError("Invalid observation week")
                        x, y = map(instant, calendar.weeks[int(raw_week)])
                        if x < b and y > a:
                            if x < a or y > b:
                                return Slice((), "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW")
                            kept.append((i, row))
            else:
                return Slice((), "INVALID_TIME_SEMANTICS")
        except (ValueError, TypeError, KeyError, OverflowError):
            return Slice((), "INVALID_OBSERVATION_TIME")
        selected = kept
    if table == "echo" and scope.lecture_item_id:
        if not spec.item_column or spec.item_column not in spec.columns:
            raise ClarificationRequired("This source has no verified lecture item identity.")
        matches = [(i, r) for i, r in selected if str(r.get(spec.item_column)) == scope.lecture_item_id]
        if not matches:
            raise ClarificationRequired("The selected lecture item is absent from this scope.")
        if len({(r.get("Class"), r.get("Content_week")) for _, r in matches}) > 1:
            raise ClarificationRequired("The lecture item identifier refers to more than one recording.")
        selected = matches
    if spec.event_id_column:
        unique = {}
        for i, row in selected:
            identity = row.get(spec.event_id_column)
            if identity in (None, ""):
                return Slice((), "MISSING_EVENT_ID")
            if identity in unique and canonical(dict(unique[identity][1])) != canonical(dict(row)):
                return Slice((), "CONFLICTING_EVENT_ID")
            unique.setdefault(identity, (i, row))
        selected = list(unique.values())
    return Slice(tuple(selected), "AVAILABLE")


class Aggregator:
    def __init__(self, snapshot: Snapshot, scope: Scope):
        snapshot.validate(scope)
        self.snapshot, self.scope = snapshot, scope
        # Request-local only; never indexed by P3's four fields.
        self.slices = {name: source_rows(snapshot, scope, name) for name in
                       ("moodle", "echo", "gdocs", "reply_network", "view_network", "goals", "reflections", "features")}
        self.facts = []

    def complete(self, table, metric):
        spec = self.snapshot.specs.get(table)
        return bool(spec and any(c.covers(self.scope, metric) for c in spec.coverage))

    def add(self, domain, metric, table, definition, *, rows=None, value=None,
            status=None, time_basis="activity_window"):
        source = self.slices[table]
        rows = source.rows if rows is None else rows
        if status is None:
            status = source.status
            if status == "AVAILABLE":
                if value is None:
                    status = "MISSING_METRIC_VALUES"
                elif value == 0 and not rows and not self.complete(table, metric):
                    value, status = None, "NO_OBSERVATIONS_COVERAGE_UNKNOWN"
                elif self.complete(table, metric):
                    status = "OBSERVED_ZERO" if value == 0 else "OBSERVED"
                elif value == 0:
                    # A reported numeric zero row is an observation, unlike an empty table.
                    status = "OBSERVED_ZERO_PARTIAL_COVERAGE"
                else:
                    status = "OBSERVED_PARTIAL_COVERAGE"
            else:
                value = None
        elif not status.startswith(("OBSERVED", "CUMULATIVE")):
            value = None
        fact = Fact(domain, metric, value, status, definition, time_basis, table,
                    tuple(i for i, _ in rows), self.scope)
        self.facts.append(fact)
        return fact

    def events(self, domain, metric, event):
        source = self.slices["moodle"]
        spec = self.snapshot.specs.get("moodle")
        rows = tuple((i, r) for i, r in source.rows if r.get("Event") == event)
        invalid = source.status == "AVAILABLE" and (not spec or "Event" not in spec.columns or
                  any(r.get("Event") in (None, "") for _, r in source.rows))
        if metric == "video_clicks" and self.scope.lecture_item_id:
            if spec and spec.item_column and all(spec.item_column in r for _, r in rows):
                rows = tuple((i, r) for i, r in rows if str(r[spec.item_column]) == self.scope.lecture_item_id)
            else:
                return self.add(domain, metric, "moodle", "Moodle video clicks for the selected recording.",
                                rows=(), status="UNAVAILABLE_FOR_REQUESTED_LECTURE_ITEM")
        f = self.add(domain, metric, "moodle", "Count of Moodle " + event + " event records.",
                     rows=rows, value=len(rows), status="INVALID_EVENT_SCHEMA" if invalid else None)
        return self.feature_fallback(f, event)

    def feature_fallback(self, fact, column):
        """Only equivalent, exactly interval-bound features can replace unavailable metrics."""
        if fact.value is not None:
            return fact
        source = self.slices["features"]
        spec = self.snapshot.specs.get("features")
        if (not spec or source.status != "AVAILABLE" or len(source.rows) != 1
                or spec.observation != "interval" or fact.metric not in spec.metric_semantics
                or self.scope.lecture_item_id):
            return fact
        value = number(source.rows[0][1].get(column))
        if value is None:
            return fact
        self.facts.remove(fact)
        return self.add(fact.domain, fact.metric, "features", fact.definition,
                        value=value, status="OBSERVED_MATCHING_INTERVAL_FEATURE")

    def numeric(self, domain, metric, table, column, definition, *, mean=False):
        source = self.slices[table]
        spec = self.snapshot.specs.get(table)
        if source.status == "AVAILABLE" and (spec is None or column not in spec.columns):
            return self.add(domain, metric, table, definition, status="INVALID_METRIC_SCHEMA")
        values = [number(r.get(column)) for _, r in source.rows]
        if column == "Video View %":
            values = [v if v is None or v <= 100 else None for v in values]
        if any(v is None for v in values):
            value = None
        elif mean:
            value = round(sum(values) / len(values), 2) if values else None
        else:
            value = sum(values)
        return self.add(domain, metric, table, definition, value=value)

    def resources(self):
        self.events("Resources", "resource_views", "Resources_views")

    def lecture(self):
        self.events("Lecture", "video_clicks", "Video_views")
        f = self.numeric("Lecture", "video_views", "echo", "Video Views",
                         "Sum of Echo Video Views; separate from Moodle link clicks.")
        self.feature_fallback(f, "Video_views_sum")
        f = self.numeric("Lecture", "mean_view_percent", "echo", "Video View %",
                         "Arithmetic mean Video View % across scoped tracked recording rows; not mastery.", mean=True)
        self.feature_fallback(f, "Video_view%_avg")
        echo = self.slices["echo"]
        if echo.status == "UNAVAILABLE_FOR_REQUESTED_ACTIVITY_WINDOW":
            cumulative = source_rows(self.snapshot, self.scope, "echo", temporal=False)
            spec = self.snapshot.specs.get("echo")
            if cumulative.status == "AVAILABLE" and spec and spec.observation in {"content_week", "cumulative"}:
                vals = [number(r.get("Video Views")) for _, r in cumulative.rows]
                identity_column = spec.item_column or "Class"
                identities = [r.get(identity_column) for _, r in cumulative.rows]
                if any(v is None for v in identities) or len(set(identities)) != len(identities):
                    self.add("Lecture", "cumulative_video_views", "echo",
                             "Cumulative recording snapshots cannot be added when recording identity is ambiguous.",
                             rows=(), status="AMBIGUOUS_CUMULATIVE_RECORDING", time_basis="cumulative_snapshot")
                    return
                self.add("Lecture", "cumulative_video_views", "echo",
                         "Cumulative views in the source snapshot; Content_week is material week, not watching time.",
                         rows=cumulative.rows, value=sum(vals) if vals and all(v is not None for v in vals) else None,
                         status="CUMULATIVE_NOT_ACTIVITY_WINDOW" if vals and all(v is not None for v in vals) else "MISSING_METRIC_VALUES",
                         time_basis="cumulative_snapshot")

    def debate(self):
        for metric, event in (("debate_posts", "Debate_posts"), ("debate_replies", "Debate_replies"), ("debate_views", "Debate_views")):
            self.events("Debate", metric, event)
        for table, prefix in (("reply_network", "network_replies"), ("view_network", "network_views")):
            source = self.slices[table]
            spec = self.snapshot.specs.get(table)
            invalid_schema = source.status == "AVAILABLE" and (spec is None or "count" not in spec.columns or
                              any(r.get("From") is None or r.get("To") is None for _, r in source.rows))
            for direction, field in (("sent", "From"), ("received", "To")):
                rows = tuple((i, r) for i, r in source.rows
                             if str(r.get(field)) == self.scope.learner_id
                             and str(r.get("From")) != str(r.get("To")))
                vals = [number(r.get("count")) for _, r in rows]
                value = sum(vals) if all(v is not None for v in vals) else None
                self.add("Debate", prefix + "_" + direction, table,
                         "Sum of scoped directed non-self network counts; not added to Moodle events.", rows=rows, value=value,
                         status="INVALID_METRIC_SCHEMA" if invalid_schema else None)
                other = "To" if field == "From" else "From"
                people = {str(r[other]) for _, r in rows if r.get(other) is not None and number(r.get("count")) not in (None, 0)}
                self.add("Debate", prefix + "_unique_" + direction, table,
                         "Number of distinct counterparties on positive non-self edges; identities withheld.",
                         rows=rows, value=len(people) if all(v is not None for v in vals) else None,
                         status="INVALID_METRIC_SCHEMA" if invalid_schema else None)

    def reflection(self):
        f = self.numeric("Reflection", "edited_characters", "gdocs", "absStrCount",
                         "Sum of absolute edited-character counts; no inference about reflection content or quality.")
        self.feature_fallback(f, "Total_chars")
        for table in ("goals", "reflections"):
            self.add("Reflection", table + "_record_count", table,
                     "Number of optional scoped records; text is not supplied to the model.",
                     value=len(self.slices[table].rows))

    def build(self):
        self.resources()
        self.lecture()
        self.debate()
        self.reflection()
        return Bundle(self.scope, tuple(self.facts), self.slices, self.snapshot)


def number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return (int(n) if n.is_integer() else n) if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def percentage(value):
    n = number(value)
    return n if n is not None and n <= 100 else None


@dataclass(frozen=True)
class Bundle:
    scope: Scope
    facts: tuple[Fact, ...]
    slices: dict
    snapshot: Snapshot

    def context(self, pages):
        selected = [f for f in self.facts if f.domain in pages]
        coverage = {}
        for domain in pages:
            fs = [f for f in selected if f.domain == domain and f.time_basis == "activity_window"]
            valid = [f for f in fs if f.value is not None]
            complete = all(f.status in {"OBSERVED", "OBSERVED_ZERO", "OBSERVED_MATCHING_INTERVAL_FEATURE"} for f in fs)
            coverage[domain] = "AVAILABLE" if fs and len(valid) == len(fs) and complete else "PARTIAL" if valid else "UNAVAILABLE"
        return {"window": self.scope.public_window(), "coverage": coverage,
                "activity": {domain: {f.metric: f.public() for f in selected if f.domain == domain} for domain in pages},
                "interpretation_limit": "Activity measures do not establish understanding, reflection quality or learning improvement."}

    def visible(self, page):
        context = self.context(DOMAINS if page == "Overview" else (page,))
        # Preserve chart-level distributions for the current detail view, not
        # only its total. No padded unobserved cells are turned into zeroes.
        if page != "Overview":
            table = "gdocs" if page == "Reflection" else "moodle"
            source = self.slices[table]
            events = {"Resources": ("Resources_views",), "Lecture": ("Video_views",),
                      "Debate": ("Debate_posts", "Debate_replies", "Debate_views")}
            groups = {}
            calendar = self.snapshot.calendars.get(self.scope.course_id)
            spec = self.snapshot.specs.get(table)
            for _, row in source.rows:
                event = "edited_characters" if table == "gdocs" else row.get("Event")
                if table == "moodle" and event not in events[page]:
                    continue
                if page == "Lecture" and self.scope.lecture_item_id:
                    if not spec.item_column or str(row.get(spec.item_column)) != self.scope.lecture_item_id:
                        continue
                week = None
                if spec.observation == "week":
                    week = number(row.get(spec.week_column))
                elif spec.observation == "timestamp" and calendar:
                    t = datetime.fromisoformat(str(row[spec.time_column]).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=ZoneInfo(spec.timestamp_timezone))
                    week = next((w for w, (a, b) in calendar.weeks.items() if instant(a) <= t < instant(b)), None)
                weekday = row.get("dayOfWeek" if table == "gdocs" else "Day_of_week")
                if weekday not in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}:
                    weekday = None
                material = number(row.get("Content_week"))
                key = (event, week, material, weekday)
                value = number(row.get("absStrCount")) if table == "gdocs" else 1
                previous = groups.get(key, 0)
                groups[key] = previous + value if previous is not None and value is not None else None
            context["activity_patterns"] = {"source_status": source.status,
                "definition": "Scoped observed week/day/material-week groups; absent groups are not imputed as zero.",
                "records": [{"metric": k[0], "observation_week": k[1], "material_week": k[2], "weekday": k[3], "value": v}
                            for k, v in groups.items()]}
        # Retain all visible lecture row values and explicit calculations in both modes.
        if page == "Lecture":
            rows = self.slices["echo"].rows
            context["recording_rows"] = [
                {"recording": "Recording " + str(n), "video_views": number(r.get("Video Views")),
                 "view_percent": percentage(r.get("Video View %")), "material_week": number(r.get("Content_week"))}
                for n, (_, r) in enumerate(rows, 1)]
            values = [percentage(r.get("Video View %")) for _, r in rows]
            context["view_percent_calculation"] = {
                "numerator": sum(values) if values and all(v is not None for v in values) else None,
                "denominator": len(values),
                "rule": "Mean over all scoped tracked rows with valid percentages; unavailable if any value is missing."}
            real = [r for _, r in rows if "no lecture video" not in str(r.get("Class", "")).casefold()]
            viewed = [r for r in real if (number(r.get("Video Views")) or 0) > 0]
            def calculation(records):
                vals = [percentage(r.get("Video View %")) for r in records]
                valid = bool(vals) and all(v is not None for v in vals)
                return {"numerator": sum(vals) if valid else None, "denominator": len(vals),
                        "value": round(sum(vals) / len(vals), 2) if valid else None}
            context["recording_calculations"] = {
                "mean_among_viewed_real_recordings": calculation(viewed),
                "mean_across_real_recordings": calculation(real),
                "recording_rows_viewed": len(viewed) if rows else None,
                "definition": "Real recording rows exclude No Lecture Video placeholders; repeated actual event rows are not unique videos."}
        return context


def aggregate(snapshot, scope):
    return Aggregator(snapshot, scope).build()
