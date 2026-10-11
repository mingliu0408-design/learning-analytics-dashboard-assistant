"""Public, source-bound charts adapted from the Supervisor Demo FIXED v3 UI.

Source: supervisor-demo-fixed-v3/pages/1_Individual_Feedback.py (2140 lines).
Only the original plotting/layout code is reused here. Firebase, old provider
calls, feedback templates and shared mutable storage are deliberately absent.
All helpers below return fresh data/figures; rendering imports Streamlit lazily.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from io import BytesIO
import hashlib
import json
import re

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "dashboard" / "input"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEK_LABELS = {0: "W0", 1: "W1", 2: "W2", 3: "W3", 4: "W4", 5: "W5", 6: "ReadingWeek", 7: "W6", 8: "W7", 9: "W8", 10: "W9"}
LECTURE_COLORS = ["#dc2f02", "#F3722C", "#F9844A", "#F9C74F", "#90BE6D", "#43AA8B", "#05a8aa"]
# Paths are a fixed allowlist. No arbitrary file supplied by a visitor is read.
SOURCES = {
    "student_info": ("student_info.csv", ["ID", "AppName"]),
    "features": ("features/features.csv", ["ID", "Total_chars"]),
    "moodle": ("moodle/moodle_logs.csv", ["ID", "Week", "Day_of_week", "Event", "Content_week"]),
    "echo": ("echo/echo_logs.csv", ["ID", "Class", "Content_week", "Video Views", "Video View %"]),
    "gdocs": ("gdocs/activities.csv", ["ID", "Week", "dayOfWeek", "day", "absStrCount"]),
    "cohorts": ("gdocs/ts_cohorts.csv", ["day", "previousCohorts", "currentCohort"]),
    "reply": ("debate/reply_network.csv", ["From", "To", "count", "week"]),
    "view": ("debate/view_network.csv", ["From", "To", "count", "week"]),
}


def _empty(key: str) -> pd.DataFrame:
    frame = pd.DataFrame(columns=SOURCES[key][1])
    frame.attrs["available"] = False
    frame.attrs["source"] = "data/dashboard/input/" + SOURCES[key][0]
    return frame


def _frame(data: Mapping, key: str) -> pd.DataFrame:
    value = data.get(key)
    if not isinstance(value, pd.DataFrame) or not set(SOURCES[key][1]).issubset(value.columns):
        return _empty(key)
    frame = value.copy(deep=True)
    frame.attrs.setdefault("available", True)
    return frame


def load_dashboard_data() -> dict[str, pd.DataFrame]:
    """Read the eight allowlisted public CSVs afresh, without shared cache state.

    Missing/unreadable sources are empty frames marked available=False. This
    is distinct from an available file with zero rows: metrics then say unknown.
    Serialized archival pickle/xlsx, original directories and secrets are unused.
    """
    result = {}
    for key, (relative, columns) in SOURCES.items():
        try:
            path = INPUT / relative
            if path.is_symlink() or not path.resolve().is_relative_to(INPUT.resolve()):
                raise ValueError("Dashboard source path boundary")
            content = path.read_bytes()
            frame = pd.read_csv(BytesIO(content))
            if not set(columns).issubset(frame.columns):
                frame = _empty(key)
            else:
                frame.attrs.update(available=True, source="data/dashboard/input/" + relative,
                                   source_sha256=hashlib.sha256(content).hexdigest())
        except (OSError, ValueError, pd.errors.ParserError):
            frame = _empty(key)
        result[key] = frame.copy(deep=True)
    return result



def chart_source_version(data: Mapping) -> str | None:
    """Identity of the exact eight CSV byte strings parsed for these charts.

    Match dashboard.source_identity's aliases and canonical serialization. A
    missing/unavailable source returns None; the host should stop or retry when
    this version differs from the worker-bound dashboard context. No metadata
    entry is added to the data mapping, so its eight values remain DataFrames.
    """
    from .dashboard import SOURCES as DASHBOARD_SOURCES
    aliases = {"roster": "student_info", "moodle": "moodle", "echo": "echo",
               "gdocs": "gdocs", "reply_network": "reply", "view_network": "view",
               "features": "features", "cohorts": "cohorts"}
    hashes = {}
    for source in DASHBOARD_SOURCES:
        frame = data.get(aliases[source])
        if not isinstance(frame, pd.DataFrame) or not frame.attrs.get("available"):
            return None
        identity = frame.attrs.get("source_sha256")
        if not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
            return None
        hashes[source] = identity
    serialized = json.dumps(hashes, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _numeric(frame: pd.DataFrame, columns) -> pd.DataFrame:
    result = frame.copy(deep=True)
    for column in columns:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _window(week_start, week_end) -> tuple[int, int]:
    low, high = int(week_start), int(week_end)
    if not 0 <= low <= high <= 10:
        raise ValueError("The observation window must be within source Week 0..10.")
    return low, high


def _learner(data: Mapping, learner_id) -> int | None:
    roster = _numeric(_frame(data, "student_info"), ["ID"])
    value = str(learner_id)
    if not value.isascii() or not value.isdigit() or str(int(value)) != value:
        return None
    uid = int(value)
    return uid if roster["ID"].eq(uid).any() else None


def learner_name(student_info: pd.DataFrame, learner_id) -> str:
    """Only public pseudonyms are permitted in labels and network hovers."""
    roster = _numeric(student_info, ["ID"])
    match = roster.loc[roster.ID.eq(int(learner_id)), "AppName"] if "AppName" in roster else pd.Series(dtype=str)
    candidate = str(match.iloc[0]) if len(match) else ""
    return candidate if re.fullmatch(r"learner-[0-9]+", candidate) else f"learner-{int(learner_id)}"


def scope_data(data: Mapping, learner_id, week_start=0, week_end=10) -> dict[str, pd.DataFrame]:
    """Copy and filter event data to one allowlisted learner/window.

    Echo rows are *all saved cumulative totals for this learner*: they have
    content weeks but no observation dates. Features are also saved all-period
    totals. Neither is represented as an event-window measurement.
    """
    low, high = _window(week_start, week_end)
    uid = _learner(data, learner_id)
    scoped = {key: _frame(data, key) for key in SOURCES}
    if uid is None:
        return {key: _empty(key) for key in SOURCES}
    for key in ("features", "moodle", "echo", "gdocs"):
        frame = _numeric(scoped[key], ["ID", "Week", "Content_week", "day", "absStrCount", "Video Views", "Video View %", "Total_chars"])
        frame = frame.loc[frame.ID.eq(uid)].copy()
        if key in ("moodle", "gdocs"):
            frame = frame.loc[frame.Week.between(low, high)].copy()
        scoped[key] = frame
    for key in ("reply", "view"):
        frame = _numeric(scoped[key], ["From", "To", "week", "count"])
        scoped[key] = frame.loc[frame.week.between(low, high) & (frame.From.eq(uid) | frame.To.eq(uid))].copy()
    return scoped


def weekly_activity(frame: pd.DataFrame, week_start=0, week_end=10, *, event=None, character_edits=False) -> pd.DataFrame:
    """Seven-day grid of recorded events/character edits, never mutate input."""
    low, high = _window(week_start, week_end)
    column = "dayOfWeek" if character_edits else "Day_of_week"
    required = ["Week", column, "absStrCount" if character_edits else "Event"]
    if not set(required).issubset(frame.columns) or not frame.attrs.get("available", True):
        result = pd.DataFrame(columns=["Day", "Week", "Counts", "Week label"])
        result.attrs["available"] = False
        return result
    selected = _numeric(frame, ["Week", "absStrCount"])
    selected = selected.loc[selected.Week.between(low, high)]
    if event is not None:
        selected = selected.loc[selected.Event.eq(event)]
    selected = selected.loc[selected[column].isin(DAYS)]
    if character_edits:
        grouped = selected.groupby([column, "Week"])["absStrCount"].sum(min_count=1)
    else:
        grouped = selected.groupby([column, "Week"]).size()
    grid = pd.MultiIndex.from_product([DAYS, range(low, high + 1)], names=[column, "Week"])
    result = grouped.reindex(grid, fill_value=0).rename("Counts").reset_index().rename(columns={column: "Day"})
    result["Week label"] = result.Week.map(WEEK_LABELS)
    result.attrs["available"] = True
    return result


def weekly_figure(series: pd.DataFrame, *, y_title="Recorded engagements") -> go.Figure:
    """Original multiweek weekday curves and colored peak markers."""
    colors = {WEEK_LABELS[week]: px.colors.qualitative.Plotly[week % len(px.colors.qualitative.Plotly)] for week in WEEK_LABELS}
    fig = px.line(series, x="Day", y="Counts", color="Week label", color_discrete_map=colors,
                  category_orders={"Day": DAYS, "Week label": list(WEEK_LABELS.values())})
    if not series.empty:
        for _, group in series.groupby("Week", sort=True):
            known = group.loc[group.Counts.notna()]
            if len(known) and known.Counts.max() > 0:
                peak = known.loc[known.Counts.idxmax()]
                fig.add_annotation(x=peak.Day, y=peak.Counts, text="<b>o</b>", showarrow=False,
                                   font=dict(size=16, color=colors[peak["Week label"]]))
    fig.update_yaxes(showgrid=False, title=y_title)
    fig.update_xaxes(showgrid=False, title="Day of week", categoryorder="array", categoryarray=DAYS)
    fig.update_layout(legend_title="Week", margin=dict(l=30, r=10, t=25, b=30))
    return fig


def resource_heatmap(frame: pd.DataFrame, week_start=0, week_end=10) -> pd.DataFrame:
    """Rows=observed engagement Week, columns=known Content_week.

    Unknown content weeks remain excluded, with their actual count retained in
    attrs. Empty intersections of an available source are recorded zero counts.
    """
    low, high = _window(week_start, week_end)
    if not {"Week", "Content_week", "Event"}.issubset(frame.columns) or not frame.attrs.get("available", True):
        result = pd.DataFrame()
        result.attrs.update(available=False, unknown_content_rows=0)
        return result
    selected = _numeric(frame, ["Week", "Content_week"])
    selected = selected.loc[selected.Week.between(low, high) & selected.Event.eq("Resources_views")].copy()
    known = selected.Content_week.notna() & selected.Content_week.between(0, 10) & selected.Content_week.mod(1).eq(0)
    result = selected.loc[known].groupby(["Week", "Content_week"]).size().unstack("Content_week")
    result = result.reindex(index=range(low, high + 1), columns=range(0, 11)).fillna(0).astype(int)
    result.index.name, result.columns.name = "Week engaged", "Content week"
    result.attrs.update(available=True, unknown_content_rows=int((~known).sum()), recorded_rows=len(selected))
    return result


def heatmap_figure(matrix: pd.DataFrame) -> go.Figure:
    """Original blue heat map, with actual axis values and corrected lag sign."""
    if matrix.empty:
        return go.Figure()
    x, y = list(matrix.columns), list(matrix.index)
    lag = np.asarray(y)[:, None] - np.asarray(x)[None, :]
    fig = go.Figure(go.Heatmap(x=x, y=y, z=matrix.to_numpy().tolist(), customdata=lag.tolist(),
                            colorscale="Blues", colorbar=dict(title="Engagements"),
                            text=matrix.to_numpy().tolist(), texttemplate="%{text}",
                            hovertemplate="Content week: %{x}<br>Engaged week: %{y}<br>Engagements: %{z}<br>Week-index difference: %{customdata}<extra></extra>"))
    lower, upper = max(min(x), min(y)) - .5, min(max(x), max(y)) + .5
    fig.add_shape(type="line", x0=lower, y0=lower, x1=upper, y1=upper,
                  line=dict(width=1, dash="dot", color="rgba(0,0,0,0.4)"))
    fig.update_xaxes(title="Content week", tickmode="linear", tick0=0, dtick=1, showgrid=False)
    fig.update_yaxes(title="Week engaged", tickmode="linear", tick0=0, dtick=1, showgrid=False)
    fig.update_layout(title="The weekly contents vs the engaged weeks", margin=dict(l=40, r=10, t=50, b=40))
    return fig


def lecture_figure(frame: pd.DataFrame, lecture_item_id=None) -> go.Figure:
    """Original horizontal bars: exact saved views, class names, percentages."""
    source = _numeric(frame, ["Content_week", "Video Views", "Video View %"])
    if not {"Class", "Video Views", "Video View %"}.issubset(source.columns) or source.empty:
        return go.Figure()
    source = source.sort_values(["Content_week", "Class"], kind="stable").copy()
    source = source.loc[source["Video Views"].notna()]
    fig = px.bar(source, x="Video Views", y="Class", color="Video View %", orientation="h",
                 title="Saved cumulative number and percentage of video views", color_continuous_scale=LECTURE_COLORS,
                 hover_data={"Content_week": True, "Video View %": ":.2f"})
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, family="Arial", color="black"))
    fig.update_xaxes(showgrid=False, title="Saved cumulative video views")
    fig.update_coloraxes(cmin=0, cmax=100)
    # Focus highlights a class without removing the original full saved graph.
    focused = source.loc[source.Class.astype(str).eq(str(lecture_item_id))]
    if not focused.empty:
        for _, row in focused.iterrows():
            fig.add_annotation(x=row["Video Views"], y=row.Class, text="Selected video", showarrow=True, arrowhead=2)
    return fig


def _sum_count(frame: pd.DataFrame, mask) -> int | None:
    if not frame.attrs.get("available", True):
        return None
    values = pd.to_numeric(frame.loc[mask, "count"], errors="coerce")
    return int(values.sum()) if values.notna().all() else None


def debate_metrics(scoped: Mapping, learner_id) -> dict[str, int | None]:
    """Original five cards; posts corrected to actual Moodle event rows."""
    uid = int(learner_id)
    moodle, reply, view = (_frame(scoped, key) for key in ("moodle", "reply", "view"))
    reply, view = _numeric(reply, ["From", "To", "count"]), _numeric(view, ["From", "To", "count"])
    return {
        "Debate_posts": int(moodle.Event.eq("Debate_posts").sum()) if moodle.attrs.get("available") else None,
        "Debate_replies": _sum_count(reply, reply.From.eq(uid) & reply.To.ne(uid)),
        "Debate_views": _sum_count(view, view.From.eq(uid)),
        "Num_unique_students_have_replied": int(reply.loc[reply.To.eq(uid) & reply.From.ne(uid), "From"].nunique()) if reply.attrs.get("available") else None,
        "Num_unique_students_have_viewed": int(view.loc[view.To.eq(uid), "From"].nunique()) if view.attrs.get("available") else None,
    }


def network_specs(network: pd.DataFrame, student_info: pd.DataFrame, learner_id) -> tuple[list[dict], list[dict]]:
    """Pure Node/Edge specs: scoped counts aggregated before pairing directions."""
    uid = int(learner_id)
    frame = _numeric(network, ["From", "To", "count"])
    if not {"From", "To", "count"}.issubset(frame.columns):
        return [], []
    roster = _numeric(student_info, ["ID"])
    allowed = set(roster.ID.dropna())
    frame = frame.loc[(frame.From.eq(uid) | frame.To.eq(uid)) & frame.From.ne(frame.To)
                      & frame.From.isin(allowed) & frame.To.isin(allowed)]
    frame = frame.dropna(subset=["From", "To", "count"])
    frame = frame.loc[frame["count"].ge(0)]
    grouped = frame.groupby(["From", "To"])["count"].sum()
    people = sorted(set(frame.From.astype(int)) | set(frame.To.astype(int)))
    nodes = []
    for person in people:
        node = dict(id=str(person), label=learner_name(student_info, person), title=learner_name(student_info, person))
        if person == uid:
            node["color"] = "orange"
        nodes.append(node)
    edges = []
    for person in people:
        if person == uid:
            continue
        outgoing, incoming = grouped.get((uid, person), 0), grouped.get((person, uid), 0)
        if outgoing and incoming:
            edges.append(dict(source=str(uid), target=str(person), label=f"*{int(outgoing)}↔️{int(incoming)}", width=2))
            edges.append(dict(source=str(person), target=str(uid), width=2))
        elif outgoing:
            edges.append(dict(source=str(uid), target=str(person), label=str(int(outgoing)), width=2))
        elif incoming:
            edges.append(dict(source=str(person), target=str(uid), label=str(int(incoming)), width=2))
    return nodes, edges


def cohort_series(gdocs: pd.DataFrame, all_gdocs: pd.DataFrame, cohorts: pd.DataFrame, week_start=0, week_end=10) -> pd.DataFrame:
    """Explicit day merge; cohort values never mutate or shift by index.

    Days outside the observation scope are removed using the source's day/Week
    mapping. Learner gaps are 0 only within an available recorded activity file;
    missing sources remain NaN. Cohort missing values are never filled with 0.
    """
    low, high = _window(week_start, week_end)
    required = {"day", "previousCohorts", "currentCohort"}
    if not required.issubset(cohorts.columns) or not cohorts.attrs.get("available", True):
        return pd.DataFrame(columns=["day", "previousCohorts", "currentCohort", "student", "Week"])
    source = _numeric(cohorts, ["day", "previousCohorts", "currentCohort"])
    mapping = _numeric(all_gdocs, ["day", "Week"])[["day", "Week"]].dropna().drop_duplicates()
    # A day with conflicting week provenance is unknown, not guessed from index.
    mapping = mapping.loc[~mapping.day.duplicated(keep=False)]
    source = source.merge(mapping, on="day", how="left", validate="many_to_one")
    source = source.loc[source.Week.between(low, high)].copy()
    activities = _numeric(gdocs, ["day", "absStrCount"])
    if {"day", "absStrCount"}.issubset(activities.columns) and activities.attrs.get("available", True):
        daily = activities.groupby("day")["absStrCount"].sum(min_count=1).rename("student").reset_index()
        source = source.merge(daily, on="day", how="left", validate="many_to_one")
        # No row on a day in this available source has zero recorded edits.
        present_days = set(daily.day)
        source.loc[~source.day.isin(present_days), "student"] = 0.0
    else:
        source["student"] = np.nan
    return source.sort_values("day").reset_index(drop=True)


def cohort_figure(series: pd.DataFrame, name: str) -> go.Figure:
    fig = go.Figure()
    for key, label, color in (("previousCohorts", "Previous Cohorts", "cyan"), ("currentCohort", "Your Cohort", "blue"), ("student", name, "red")):
        if key in series:
            fig.add_trace(go.Scatter(x=series.day.tolist(), y=series[key].where(series[key].notna(), None).tolist(), name=label, line=dict(color=color), connectgaps=False))
    ticks = series.groupby("Week").day.min() if not series.empty else pd.Series(dtype=float)
    fig.update_yaxes(showgrid=False, title="Character edits per day")
    fig.update_xaxes(showgrid=True, title="Week (starting on Monday)", tickmode="array", tickvals=ticks.tolist(), ticktext=[WEEK_LABELS.get(int(week), str(week)) for week in ticks.index])
    fig.update_layout(title="Daily character edits compared between cohorts", margin=dict(l=35, r=10, t=45, b=40))
    return fig


def _event_count(frame: pd.DataFrame, event: str) -> int | None:
    return int(frame.Event.eq(event).sum()) if frame.attrs.get("available", True) else None


def _chars(frame: pd.DataFrame) -> float | None:
    if not frame.attrs.get("available", True):
        return None
    values = pd.to_numeric(frame.absStrCount, errors="coerce")
    return float(values.sum()) if values.notna().all() else None


def _value(value) -> str | int | float:
    if value is None or pd.isna(value):
        return "unknown"
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _explain(st, text, title="What is this graph?"):
    with st.popover(title):
        st.markdown(text)


def render_dashboard(page, data, learner_id, week_start=0, week_end=10) -> dict:
    """Render original dashboard forms; no generation or Memory side effects.

    data: mapping returned by load_dashboard_data; optional _lecture_item_id is
    an exact public Class label to highlight (full cumulative chart is retained).
    This function adds no week widget: the host app supplies the shared window.
    Returns current factual metrics for UI inspection, never a template prompt.
    """
    import streamlit as st

    low, high = _window(week_start, week_end)
    uid = _learner(data, learner_id)
    if uid is None:
        st.warning("Select an anonymous learner present in the public roster.")
        return {"available": False}
    scoped = scope_data(data, uid, low, high)
    name = learner_name(scoped["student_info"], uid)
    period = f"{WEEK_LABELS[low]}–{WEEK_LABELS[high]} (source Week {low}–{high})"
    st.caption(f"Historical public dataset · {name} · observation window: {period}. Event counts describe recorded activity, not learning outcomes.")
    metrics = debate_metrics(scoped, uid)
    metrics.update(Resources_views=_event_count(scoped["moodle"], "Resources_views"), Reflection_chars=_chars(scoped["gdocs"]))

    if page in ("Overview", "Introduction", "Introduction / Overview"):
        _, center, _ = st.columns([.2, 1, .2])
        with center:
            st.subheader(f"Hello {name} !")
            st.markdown("This dashboard brings together historical activity data from Moodle, Panopto and GDocs. It visualises recorded clicks, views, interactions and character edits so you can inspect the traces and reflect on study decisions.")
            st.subheader("How to engage with it")
            st.markdown("**Step 1. Resources** — review when readings and materials were accessed.\n\n**Step 2. Lecture** — inspect saved cumulative lecture viewing totals.\n\n**Step 3. Debate** — explore your recorded replying and viewing network.\n\n**Step 4. Reflection** — compare the timing and volume of character edits.\n\n**Step 5. Next Steps** — save your own reflections and draft goals.\n\nUse the assistant controls below for saved research replay, local components or a live question with your own key. Chart summaries are factual captions; they are not generated research answers.")
            st.subheader("Your recorded activity")
            cards = st.columns(4)
            cards[0].metric("Resource views · observed window", _value(metrics["Resources_views"]))
            echo = scoped["echo"]
            saved_views = pd.to_numeric(echo["Video Views"], errors="coerce")
            lecture_total = saved_views.sum() if echo.attrs.get("available") and saved_views.notna().all() else None
            cards[1].metric("Lecture views · saved cumulative", _value(lecture_total))
            cards[2].metric("Debate posts · observed window", _value(metrics["Debate_posts"]))
            cards[3].metric("Character edits · observed window", _value(metrics["Reflection_chars"]))
            st.subheader("How your data were processed?")
            image = INPUT / "images" / "dataprocess.jpg"
            if image.is_file():
                st.image(str(image), width=800)
            else:
                st.info("The historical processing diagram is unavailable.")
            references = INPUT / "references.txt"
            if references.is_file():
                st.subheader("References")
                st.info(references.read_text(encoding="utf-8"))
    elif page == "Resources":
        heading, total = st.columns([3, .5])
        with heading:
            st.subheader("How regularly are you accessing the course materials and resources on Moodle?")
            st.caption("Readings, guidelines, handbook, extra resources and group activity materials.")
        with total:
            st.metric("Total resource views", _value(metrics["Resources_views"]), help="Recorded Resources_views events in the selected observation window.")
        left, right = st.columns([5, 4], vertical_alignment="center")
        with left:
            series = weekly_activity(scoped["moodle"], low, high, event="Resources_views")
            if series.attrs.get("available"):
                st.plotly_chart(weekly_figure(series), use_container_width=True)
            else:
                st.info("Moodle source unavailable: weekly activity is unknown.")
            _explain(st, "Each color is a source week. Curves show the actual number of recorded resource-view events by weekday. The circle marks a positive weekly peak; it is not a learning score.")
        with right:
            matrix = resource_heatmap(scoped["moodle"], low, high)
            if matrix.attrs.get("available"):
                st.plotly_chart(heatmap_figure(matrix), use_container_width=True)
                unknown = matrix.attrs["unknown_content_rows"]
                st.caption(f"{unknown} recorded resource views have unknown Content_week and are excluded from the heat map; they remain in the total and weekday curves.")
            else:
                st.info("Moodle source unavailable: content timing is unknown.")
            _explain(st, "Horizontal axis: content week. Vertical axis: week engaged. The dotted line marks equal source indices. Hover shows engagement week minus content week; positive values mean a later numeric index and negative values an earlier index. These are historical week indices, including the reading-week label, not a deadline judgment.", "How to read this?")
            st.caption("All readings were available in advance, so access can precede the indexed content week.")
        st.info(f"Recorded data: {_value(metrics['Resources_views'])} resource-view events in {period}. Activity frequency alone does not establish understanding or learning quality.")
    elif page == "Lecture":
        st.subheader("How much are you watching the course lecture videos on Panopto?")
        echo = scoped["echo"]
        st.caption("These are saved cumulative totals for this learner's full lecture list. Content_week identifies the material; the source has no viewing-event timestamp. The observation-week slider cannot filter when viewing occurred.")
        if not echo.attrs.get("available"):
            st.warning("Panopto source unavailable: lecture totals are unknown.")
        elif echo.empty:
            st.warning("There are no saved Panopto rows for this learner.")
        else:
            _, center, _ = st.columns([.1, 2, .9], vertical_alignment="center")
            with center:
                focus = data.get("_lecture_item_id")
                st.plotly_chart(lecture_figure(echo, focus), use_container_width=True)
                if focus:
                    st.caption(f"Focused video: {focus}. The full cumulative chart remains visible.")
                _explain(st, "Bar length is the saved Video Views value. The original red-to-green scale represents saved Video View % from 0 to 100. Hover reports the actual class and content week. A material's content week does not reveal the dates on which it was watched.")
                views = pd.to_numeric(echo["Video Views"], errors="coerce")
                known = views.notna()
                st.info(f"Recorded data: {len(echo)} lecture rows; {int((views[known] > 0).sum())} have a positive saved view count. Unknown counts: {int((~known).sum())}. No observation-window viewing total can be derived from this file.")
    elif page == "Debate":
        heading, help_area = st.columns([3, .8])
        with heading:
            st.subheader("How actively are you participating in the debate movements on Moodle?")
        with help_area:
            _explain(st, "Circles are anonymous learners connected to the selected learner. Arrows show direction; *a↔b combines your outgoing count and their incoming count. Reverse arrows are retained. Hover, highlighting, dragging and node selection remain interactive.")
        cards, graph, _ = st.columns([1, 3, .5])
        with cards:
            for label, key, explanation in (
                ("#posts", "Debate_posts", "Actual Moodle Debate_posts event rows in the selected window."),
                ("#replies", "Debate_replies", "Outgoing reply-network counts excluding self-replies, in the selected window."),
                ("#views", "Debate_views", "Outgoing view-network counts in the selected window; recorded self-views are included."),
                ("#student replies", "Num_unique_students_have_replied", "Distinct other learners who replied to this learner in the selected window."),
                ("#student views", "Num_unique_students_have_viewed", "Distinct source learners who viewed this learner in the selected window; a recorded self-view is included."),
            ):
                st.metric(label, _value(metrics[key]), help=explanation)
        with graph:
            network_type = st.radio("Network type", ["Replying", "Viewing"], horizontal=True, key=f"dashboard_network_{uid}")
            key = "reply" if network_type == "Replying" else "view"
            frame = scoped[key]
            if not frame.attrs.get("available"):
                st.info("This network source is unavailable; its metrics are unknown.")
            else:
                nodes, edges = network_specs(frame, scoped["student_info"], uid)
                if nodes:
                    from streamlit_agraph import Config, Edge, Node, agraph
                    config = Config(height=400, directed=True, nodeHighlightBehavior=True, highlightColor="#F7A7A6", linkHighlight=True,
                                    arrows=True, physics=True, physicsSettings={"enabled": True, "barnesHut": {"gravitationalConstant": -5000, "centralGravity": .3, "springLength": 200, "springConstant": .05}, "maxVelocity": 50, "minVelocity": .1, "solver": "barnesHut"},
                                    stabilization={"enabled": True, "iterations": 1000, "onlyDynamicEdges": False}, physicsAfterStabilization=False)
                    selected = agraph(nodes=[Node(**spec) for spec in nodes], edges=[Edge(**spec) for spec in edges], config=config)
                    if selected and str(selected) in {node["id"] for node in nodes}:
                        st.caption(f"Selected node: {learner_name(scoped['student_info'], selected)}")
                else:
                    st.info("No interactions with other learners are recorded in this window.")
            st.caption(f"Network source week filter: {period}. Counts across these weeks are summed before pairing reverse edges. Self-edges are omitted from the drawing.")
        st.info(f"Recorded data: {_value(metrics['Debate_posts'])} Moodle post events, {_value(metrics['Debate_replies'])} outgoing replies and {_value(metrics['Debate_views'])} outgoing views in {period}. These are different source measurements, not estimates from each other.")
    elif page == "Reflection":
        heading, total = st.columns([3, .8])
        with heading:
            st.subheader("How do you engage with your individual reflection activities on Gdocs?")
        with total:
            st.metric("Character edits · observed window", _value(metrics["Reflection_chars"]), help="Sum of actual absStrCount activity values in the selected Week window, not word count or final document length.")
        features = scoped["features"]
        if features.attrs.get("available") and len(features):
            saved = pd.to_numeric(features.Total_chars, errors="coerce")
            st.caption(f"Historical saved all-period Total_chars: {_value(saved.iloc[0])}. This cumulative feature is shown separately and is not the selected-window total.")
        activities = scoped["gdocs"]
        series = weekly_activity(activities, low, high, character_edits=True)
        if series.attrs.get("available"):
            st.plotly_chart(weekly_figure(series, y_title="Character edits"), use_container_width=True)
        else:
            st.warning("GDocs source unavailable: character edits are unknown.")
        _explain(st, "Each curve shows the sum of absStrCount for each weekday of a source week. These are character edits, not the number of strings, words, or the final text length.")
        comparison = cohort_series(activities, _frame(data, "gdocs"), scoped["cohorts"], low, high)
        if not comparison.empty:
            st.plotly_chart(cohort_figure(comparison, name), use_container_width=True)
        else:
            st.info("No cohort days with known source Week mapping fall within this window.")
        _explain(st, "Red is the selected learner, dark blue is the saved current cohort, and cyan is the saved previous-cohort series. All curves join on the actual day field and share the selected observation weeks. They are descriptive comparisons; character-edit volume does not measure learning quality.")
        st.info(f"Recorded data: {_value(metrics['Reflection_chars'])} character edits in {period}. No inferred writing quality or learning outcome is attached to this count.")
    elif page != "Next Steps":
        st.info("This dashboard view is unavailable.")
    return {"available": True, "learner_id": uid, "week_start": low, "week_end": high, "metrics": metrics}
