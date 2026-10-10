"""Five-view opt-in UI. Importable without Streamlit or model dependencies."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os

from . import PAGES
from .aggregate import aggregate, source_rows
from .integration import build_scoped_evidence_service, build_scoped_request
from .scope import Scope, ScopeError, Snapshot, ClarificationRequired, digest


def scoped_evidence_enabled(*, environ=None):
    env = os.environ if environ is None else environ
    return str(env.get("ENABLE_C4_SCOPED_EVIDENCE_V1", "")).casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ScopedUIBinding:
    """Injected after authentication. learner_id is never a display-name fallback."""
    snapshot: Snapshot
    learner_id: str

    def __post_init__(self):
        if self.learner_id not in self.snapshot.roster:
            raise ScopeError("UNKNOWN_LEARNER_ID")


def checked_ui_binding(binding, selected_display, identity_rows):
    """Prevent a stale DI binding surviving a learner change in the legacy shell."""
    if not isinstance(binding, ScopedUIBinding):
        return None
    matches = [r for r in identity_rows if r.get("AppName") == selected_display]
    if len(matches) != 1 or str(matches[0].get("ID")) != binding.learner_id:
        return None
    return binding


def render_scoped_dashboard(st, binding, *, now=None):
    """Same provider, scope and visible facts feed charts and actual C4 preparation."""
    if not isinstance(binding, ScopedUIBinding):
        st.info("A verified learner, course calendar and data source must be connected before this dashboard is available.")
        return None
    snapshot = binding.snapshot
    page = st.radio("View", PAGES, horizontal=True, key="e1_view")
    courses = tuple(c for c in snapshot.roster[binding.learner_id] if c in snapshot.calendars)
    if not courses:
        st.info("A verified course calendar and timezone are needed to choose an activity period.")
        return None
    # An opaque course key is internal; the UI uses non-personal ordinal labels.
    choice = st.selectbox("Course", range(len(courses)), format_func=lambda i: "Course " + str(i + 1), key="e1_course")
    course = courses[choice]
    calendar = snapshot.calendars[course]
    weeks = (None, *calendar.weeks)
    week = st.selectbox("Activity period", weeks,
                        format_func=lambda w: "Select a period" if w is None else "Week " + str(w),
                        key="e1_period::" + digest([snapshot.version, course]))
    if week is None:
        st.info("Select the activity period to use for both the charts and your question.")
        return None
    scope = Scope(binding.learner_id, course, snapshot.version, *calendar.weeks[week],
                  calendar.timezone, calendar.version)
    if page == "Lecture":
        spec = snapshot.specs.get("echo")
        raw = source_rows(snapshot, scope, "echo", temporal=False)
        ids = tuple(dict.fromkeys(str(r[spec.item_column]) for _, r in raw.rows
                    if spec and spec.item_column and r.get(spec.item_column) is not None))
        labels = ("All recordings", *["Recording " + str(i + 1) for i in range(len(ids))])
        item = st.selectbox("Lecture item", range(len(labels)), format_func=lambda i: labels[i],
                            key="e1_item::" + digest(scope.internal()))
        if item:
            from dataclasses import replace
            scope = replace(scope, lecture_item_id=ids[item - 1])
    bundle = aggregate(snapshot, scope)
    context = bundle.visible(page)
    st.caption("Activity period: " + scope.start + " to " + scope.end + " (end excluded), " + scope.timezone)
    for domain, facts in context["activity"].items():
        st.subheader(domain)
        chart = {}
        for metric, fact in facts.items():
            label = metric.replace("_", " ").capitalize()
            st.metric(label, fact["value"] if fact["value"] is not None else "Unavailable")
            st.caption(fact["definition"])
            if fact["value"] is not None and fact["time_basis"] == "activity_window" and "percent" not in metric:
                chart[label] = [fact["value"]]
        if chart:
            st.bar_chart(chart, stack=False)
    if "recording_rows" in context:
        st.dataframe(context["recording_rows"])
        calculations = context["recording_calculations"]
        st.dataframe([{"calculation": name, **value} for name, value in calculations.items() if isinstance(value, dict)])
        st.metric("Recording rows viewed", calculations["recording_rows_viewed"] if calculations["recording_rows_viewed"] is not None else "Unavailable")
        st.caption(calculations["definition"])
    if "activity_patterns" in context:
        st.caption("Observed activity by week and day. Missing groups are not filled with zero.")
        st.dataframe(context["activity_patterns"]["records"])
    st.caption(context["interpretation_limit"])
    history_key = "e1_history::" + digest(scope.internal())
    messages = st.session_state.setdefault(history_key, [])
    query = st.chat_input("Ask about this activity period")
    if not query:
        return {"scope": scope, "visible_context": context}
    try:
        request = build_scoped_request(snapshot=snapshot, scope=scope, query=query, page=page,
                                       messages=messages, now=now or datetime.now(timezone.utc),
                                       session_id=history_key)
        service = build_scoped_evidence_service(enabled=True, snapshot=snapshot)
        prepared = service.prepare_generation_request(request)
    except ClarificationRequired as error:
        st.info(str(error))
        return {"scope": scope, "visible_context": context, "clarification": str(error)}
    if not prepared.success:
        st.info("The request could not be prepared with the selected evidence. Check the source binding and period.")
    else:
        st.info("Your question and scoped activity facts are prepared. Answer generation is disabled for this review.")
        messages.append({"role": "user", "content": query})
    return {"scope": scope, "visible_context": context, "request": request, "prepared": prepared}
