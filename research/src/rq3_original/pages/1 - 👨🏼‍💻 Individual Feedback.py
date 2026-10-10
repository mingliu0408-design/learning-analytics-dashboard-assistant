
from utils.helper import *
from utils.conversation_memory import (
    NEUTRAL_CHAT_OPENER,
    clear_scoped_chat_messages,
    clear_student_session_memory,
    scoped_chat_messages,
    session_memory_scope_key,
)
from utils.c_full_service import generate_c_full_chat_turn
from utils.c4_real_contracts import C4Mode, ExecutionContext, MemoryScope
from utils.c4_real_service import C4RealService
from utils.c4_real_streamlit import (
    RESEARCH_MODE_LABELS,
    build_streamlit_c4_request,
    research_mode_enabled,
    research_scope_key,
    run_streamlit_c4_turn,
    streamlit_reply,
)
from utils.c_full_retrieval_adapter import (
    load_persisted_v2_4_retriever,
    v2_4_streamlit_cache_key,
)
from utils.c_full_runtime_config import (
    get_streamlit_allow_retrieval_v1_fallback,
    get_streamlit_retrieval_backend,
    get_streamlit_retrieval_debug,
)
from evaluation.assistant_modes import load_dashboard_data
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit_antd_components as sac
from streamlit_agraph import agraph, Node, Edge, Config
from streamlit_option_menu import option_menu
from streamlit_extras.metric_cards import style_metric_cards
import csv
import os
import openai
from datetime import datetime, timedelta
import json
import math
import requests
import uuid
from pypdf import PdfReader
import re
import streamlit_shadcn_ui as ui
import streamlit_highcharts as hct
import matplotlib.colors as mcolors


@st.cache_resource
def load_pdf_sections(pdf_path="input/moodle_links.pdf"):
    """Reads the Moodle links PDF and separates Lecture, Debate, Reflection, and Resource sections."""
    reader = PdfReader(pdf_path)
    text = "\n".join(p.extract_text() or "" for p in reader.pages)

    # Normalize spacing
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)

    # Split by known headers
    sections = {}
    parts = re.split(r"(?=Lecture:|Debate:|Reflection:|Resources?:)", text)
    for part in parts:
        if ":" not in part:
            continue
        header = part.split(":", 1)[0].strip().lower()  # e.g., "lecture"
        body = part.split(":", 1)[1].strip()
        sections[header] = body
    return sections


PDF_SECTIONS = load_pdf_sections()


@st.cache_resource
def load_c_full_dashboard_data():
    """Load all dashboard sources once for the deployed LLM C_FULL runtime."""

    return load_dashboard_data()


@st.cache_resource(show_spinner=False)
def load_streamlit_c_full_v2_4_retriever(
    retrieval_version: str,
    index_metadata_sha256: str,
    index_path: str,
):
    """Cache only the validated shared index; never cache student/session data."""

    expected = v2_4_streamlit_cache_key(index_path)
    if (retrieval_version, index_metadata_sha256, index_path) != expected:
        raise ValueError("Retrieval v2.4 Streamlit cache key does not match the persisted index")
    return load_persisted_v2_4_retriever(index_path)


def _streamlit_c_full_retrieval_settings():
    backend = get_streamlit_retrieval_backend(secrets=st.secrets)
    allow_fallback = get_streamlit_allow_retrieval_v1_fallback(secrets=st.secrets)
    debug = get_streamlit_retrieval_debug(secrets=st.secrets)
    retrieval_context = {}
    if backend == "v2_4":
        try:
            cache_key = v2_4_streamlit_cache_key()
            retrieval_context["v2_4_retriever"] = load_streamlit_c_full_v2_4_retriever(
                *cache_key
            )
        except Exception:
            retrieval_context["v2_4_retriever_error"] = (
                "The persisted Retrieval v2.4 index is missing or invalid."
            )
    return backend, allow_fallback, debug, retrieval_context


def get_pdf_snippet(page: str) -> str:
    """Return only the section matching the current dashboard page."""
    page = page.lower()
    mapping = {
        "Lecture": "Lecture",
        "Debate": "Debate",
        "Reflection": "Reflection",
        "Resources": "Resources"
    }
    section_name = mapping.get(page, page)
    snippet = PDF_SECTIONS.get(section_name, "")
    return snippet[:1200]  # trim for token safety


def save_goals(data, filename="goals.json"):
    with open(filename, 'w') as f:
        json.dump(data, f)


# Function to load goals from a JSON file
def load_goals(filename="goals.json"):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}


def change_events():
    selected_events = ','.join(st.session_state.selected_events_forSummary)
    fb.log('change_ind_feedback_overview_event@' + selected_events)


def generate_text_feedback(event, **var):
    rows = feedback_texts[feedback_texts.Event == event]
    temp = pd.DataFrame()
    cutoff = 7
    cutoff2 = 8
    if event == 'Resources_views':
        if (var['active_weeks'] >= cutoff2) & (var['late_weeks'] <= 1):
            temp = rows[rows.Case == 1].iloc[:, 3:].dropna(axis=1)
        elif (var['active_weeks'] >= cutoff2) & (var['late_weeks'] > 1):
            temp = rows[rows.Case == 2].iloc[:, 3:].dropna(axis=1)
        elif (var['active_weeks'] < cutoff2) & (var['late_weeks'] > 1):
            temp = rows[rows.Case == 3].iloc[:, 3:].dropna(axis=1)
        else:
            temp = rows[rows.Case == 4].iloc[:, 3:].dropna(axis=1)
    elif event == "Video_views":
        if (var['unique_views'] == cutoff) & (var['percent_views'] >= 70):
            temp = rows[rows.Case == 1].iloc[:, 3:].dropna(axis=1)
        elif (var['unique_views'] == cutoff) & (var['percent_views'] < 70):
            temp = rows[rows.Case == 2].iloc[:, 3:].dropna(axis=1)
        elif (var['unique_views'] < cutoff) & (var['percent_views'] >= 70):
            temp = rows[rows.Case == 3].iloc[:, 3:].dropna(axis=1)
        else:  # (var['unique_views'] < cutoff) & (var['percent_views'] < 70):
            temp = rows[rows.Case == 4].iloc[:, 3:].dropna(axis=1)
    elif event == "Debate":  # didn't consider num_replies
        if (var['num_posts'] >= cutoff) & (len(var['late_week_list']) <= 1):
            temp = rows[rows.Case == 1].iloc[:, 3:].dropna(axis=1)
        elif (var['num_posts'] >= cutoff) & (len(var['late_week_list']) > 1):
            temp = rows[rows.Case == 2].iloc[:, 3:].dropna(axis=1)
        elif (var['num_posts'] < cutoff):
            temp = rows[rows.Case == 3].iloc[:, 3:].dropna(axis=1)
    elif event == "Reflection":
        if var['active_weeks'] >= 8:
            temp = rows[rows.Case == 1].iloc[:, 3:].dropna(axis=1)
        elif (var['active_weeks'] <= 7) & (var['active_weeks'] > 2):
            temp = rows[rows.Case == 2].iloc[:, 3:].dropna(axis=1)
        elif var['active_weeks'] <= 5:
         	temp = rows[rows.Case == 3].iloc[:, 3:].dropna(axis=1)
    for col in temp:
        if col.find('Var') != -1:
            if temp[col].values == 'active_weeks':
                temp[col] = str(var['active_weeks'])
            elif temp[col].values == 'inactive_week_list':
                temp[col] = ', '.join(map(str, var['inactive_week_list']))
            elif temp[col].values == 'active_week_list':
                temp[col] = ', '.join(map(str, var['active_week_list']))
            elif temp[col].values == 'num_events':
                temp[col] = str(var['num_events'])
            elif temp[col].values == 'late_weeks':
                temp[col] = str(var['late_weeks'])
            elif temp[col].values == 'unique_views':
                temp[col] = str(var['unique_views'])
            elif temp[col].values == 'percent_views':
                temp[col] = str(var['percent_views'])
            elif temp[col].values == 'missed_list':
                temp[col] = ', '.join(map(str, var['missed_list']))
            elif temp[col].values == 'num_posts':
                temp[col] = str(var['num_posts'])
            elif temp[col].values == 'num_replies':
                temp[col] = str(var['num_replies'])
            elif temp[col].values == 'num_views':
                temp[col] = str(var['num_views'])
            elif temp[col].values == 'num_views':
                temp[col] = str(var['num_views'])
            elif temp[col].values == 'num_unique_students_i_viewed':
                temp[col] = str(var['num_unique_students_i_viewed'])
            elif temp[col].values == 'num_unique_students_have_viewed':
                temp[col] = str(var['num_unique_students_have_viewed'])
            elif temp[col].values == 'late_week_list':
                # st.write('var:', var['late_week_list'])
                text = ['W' + str(int(w)) for w in var['late_week_list']]
                temp[col] = ', '.join(map(str, text))  # var['late_week_list']))

    description = temp.agg(''.join, axis=1)
    return description.values[0]


def select_feature(key):
    fb.log("select_ind_feedback_" + st.session_state[key] + "_page")


def selected_network(key):
    val = st.session_state.get(key)
    if val is None:
        return
    fb.log("selected_network_type:" + str(val))


def select_network_week():
    val = st.session_state.get('selected_week')
    if val is None:
        return
    fb.log("select_debate_week:" + str(val))


def show_comment_boxx(location):
    # Show feedback form
    feedback_box = st.empty()
    with feedback_box.form(key="feedback_form"):
        st.markdown("#### 📌 What do you think about your feedback?")
        st.caption("Please answer following questions, 1 = disagree · 5 = agree")
        q1 = st.slider("The feedback is understandable.", 1, 5, 3, step=1)
        q2 = st.slider("The feedback is useful for planning my next steps.", 1, 5, 3, step=1)
        q3 = st.slider("The AI assistant is helpful.", 1, 5, 3, step=1)
        q4 = st.text_input("Any additional comments?", placeholder="Write your thoughts here...")

        submitted = st.form_submit_button("Submit")
        if submitted:
            fb.log("submit_feedback_")
            feedback = {
                "section": location,
                "q1_usefulness": q1,
                "q2_confidence": q2,
                "q3_ai_helpfulness": q3,
                "q4_comments": q4,
                "overall": round((q1 + q2 + q3) / 4, 2),
                "timestamp": int(datetime.now().timestamp() * 1000),
                "id": st.session_state.user["localId"],
            }
            fb.db.child("feedback").push(feedback, st.session_state.user["localId"])
            feedback_box.empty()
            st.toast("Thank you for submitting your feedback!", icon="🎉")


def show_comment_box(location):
    # Show feedback form
    feedback_box = st.empty()
    with feedback_box.form(location):
        feedback = {}
        feedback['section'] = location
        feedback['rate'] = sac.rate(label='We 🧡 your feedback!!', value=0, align='left')
        feedback['comment'] = st.text_input("What do you think about your feedback?")
        feedback['timestamp'] = int(datetime.now().timestamp() * 1000)
        feedback['id'] = st.session_state.user['localId']
        submitted = st.form_submit_button("Submit")
        if submitted:
            fb.log('submit_feedback_' + location)
            fb.db.child("feedback").push(feedback, st.session_state.user['localId'])
            # st.success("Thank you for your feedback!")
            feedback_box.empty()
            st.toast('Thank you for submitting your feedback!', icon='🎉')


def calculate_delay(df, content_week_range):
    if not df.empty:
        sorted_df = df.groupby(['Content_week', 'Week'])['Time'].count().reset_index()
        # st.write(sorted_df)
        count = 0
        late_list = []
        for i in content_week_range:
            # st.write(i)
            if not sorted_df[sorted_df['Content_week'] == i].empty:
                row = sorted_df[sorted_df['Content_week'] == i].iloc[0]  # first visited content week
                if int(row['Week']) > int(row['Content_week']):
                    late_list.append(i)
                    count += 1
                    # st.write('found late')
            else:  # no interaction on that week
                # st.write('found late')
                late_list.append(i)
                count += 1
        active_list = list(set(content_week_range) - set(late_list))
    else:
        return len(content_week_range), content_week_range, []
    return count, late_list, active_list


def filter_data(df, col, val):  # val can be a specific value (string), or a list
    if type(val) == list:
        return df[df[col].isin(val)]
    elif val != 'All':
        return df[df[col] == val]
    else:
        return df


# To generate full indexes of df: ls1xls2
def pad_2vars(df, ls1, ls2, label1, label2):
    index = pd.DataFrame(
        index=pd.MultiIndex.from_product([ls1, ls2], names=[label1, label2])).reset_index()
    return pd.merge(index, df, on=[label1, label2], how='left').fillna(0)


def click_download(txt):
    fb.log("download_" + txt + "_logs")


@st.cache_data
def convert_df(df):
    # IMPORTANT: Cache the conversion to prevent computation on every rerun
    return df.to_csv(index=False).encode('utf-8')


# aggregate data at a weekly level by the selected event
def compute_ped(df, event):
    stu_filtered = filter_data(df, 'Event', event)
    # prep and pad data
    stu_ped_filtered = stu_filtered.groupby(['Week', 'Day_of_week'])['Event'].count().reset_index().rename(
        columns={'Event': 'Counts'})
    stu_ped_filtered = pad_2vars(stu_ped_filtered, c.DAY_LIST, c.FEEDBACK_WEEK_VAL_LIST, 'Day_of_week',
                                 'Week')  # EVE edited c.CONTENT_WEEK_LIST
    return stu_ped_filtered


def compute_delay(df, event):
    stu_filtered = filter_data(df, 'Event', event)
    stu_delay_filtered = stu_filtered.groupby(['Week', 'Content_week'])['Time'].count().reset_index().rename(
        columns={'Time': 'Counts'})
    stu_delay_filtered = pad_2vars(stu_delay_filtered, c.CONTENT_WEEK_LIST, c.CONTENT_WEEK_LIST, 'Week', 'Content_week')
    stu_delay_filtered = pd.pivot(stu_delay_filtered, index='Content_week', columns='Week', values='Counts')
    return stu_delay_filtered


def change_weeks():
    selected_weeks = ','.join([str(week) for week in st.session_state.selected_weeks_forViewing])
    fb.log(f"change_ind_feedback_{st.session_state.selected_unit_indi_page}_week@{selected_weeks}")


def print_weekly_patterns(df):
    df['WeekNum'] = df['Week']
    df['Week'] = df['Week'].map(c.MAPPING_WEEK_TO_TEXT)
    name = df.columns
    # Streamlit selectbox to filter weeks
    all_weeks = df['Week'].unique()
    st.multiselect('**Filter by week**', options=all_weeks, default=all_weeks, on_change=change_weeks,
                   key='selected_weeks_forViewing')  # format_func=lambda x: f"Week{x}"
    filtered_df = df[df['Week'].isin(st.session_state.selected_weeks_forViewing)]
    fig = px.line(filtered_df, x=name[0], y=name[2], color=name[1],
                  color_discrete_sequence=px.colors.qualitative.Plotly, title='')
    max_day_per_week = filtered_df.loc[filtered_df.groupby(name[3])[name[2]].idxmax()]
    for i, row in max_day_per_week.iterrows():
        week = row[name[3]]
        week_color = px.colors.qualitative.Plotly[week % len(px.colors.qualitative.Plotly)]
        fig.add_annotation(
            x=row[name[0]],  # Day of week (or x-axis value)
            y=row[name[2]],  # Counts (or y-axis value)
            text=f"<b style='color:{week_color};'>o</b>",  # Bold and colored text showarrow=True,
            align="center",
            showarrow=False,
            font=dict(size=16)
        )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=False)
    st.plotly_chart(fig, use_container_width=True)
    p = st.popover("What is this graph?", use_container_width=False)
    p.text("""
    . The graph displays engagement frequency across days of the week.
    . Colors indicate different weekly patterns.
    . Consistent patterns across weeks may suggest a more strategic approach.
    . Variations could reflect other weekly circumstances.""")


def print_heat_map(df):
    # handle possible non-numeric or missing data
    counts = np.nan_to_num(df.values, nan=0.0)
    counts = np.clip(counts, 0, None).astype(int)

    # position-based lag matrix
    rows, cols = np.indices(counts.shape)
    lag = rows - cols  # >0 late, 0 on time, <0 early

    total = counts.sum() or 1
    timely = int(counts[lag == 0].sum())
    early = int(counts[lag < 0].sum())
    late = int(counts[lag > 0].sum())

    # weighted median lag
    median_lag = (
        float(np.median(np.repeat(lag.ravel(), counts.ravel())))
        if counts.any()
        else 0.0)
    fig = px.imshow(
        df,
        origin="lower",
        aspect="auto",
        color_continuous_scale="Blues",
        text_auto=True,
        title="The weekly contents vs the engaged weeks", )
    # diagonal reference line
    fig.add_shape(
        type="line",
        x0=-0.5, y0=-0.5,
        x1=df.shape[1] - 0.5, y1=df.shape[0] - 0.5,
        line=dict(width=1, dash="dot", color="rgba(0,0,0,0.4)"), )
    fig.update_traces(
        customdata=lag,
        hovertemplate=(
            "Content week: %{x}<br>"
            "Engaged week: %{y}<br>"
            "Engagements: %{z}<br>"
            "Lag (weeks): %{customdata}"
        ),
    )
    fig.update_xaxes(tickformat="d", tickmode="linear", tick0=0, dtick=1)
    fig.update_yaxes(tickformat="d", tickmode="linear", tick0=0, dtick=1)
    fig.update_layout(
        xaxis_title="Content week",
        yaxis_title="Week engaged",
        coloraxis_colorbar=dict(title="Engagements"),
        margin=dict(l=40, r=10, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    p = st.popover("How to read this?")
    p.markdown(
        "- Heat map shows content week vs. engaged week\n"
        "- Cells on the diagonal: on-time engagement\n"
        "- Below the diagonal: earlier than the content week (preview)\n"
        "- Above the diagonal: later than the content week (review/catch-up)\n"
        "- Darker blue = more engagements"
    )


@st.cache_data(ttl=3600)
def pullStudentLogs(id):
    stu_moodle = moodle_df[moodle_df.ID == int(id)]
    stu_echo = echo360_df[echo360_df.ID == int(id)].sort_values('Content_week').reset_index(drop=True)
    stu_gdocs = gdocs_df.loc[gdocs_df.ID == int(id)]  # can be empty
    # stu_gdocs = stu_gdocs[stu_gdocs.Week <= c.FEEDBACK_WEEK]
    stu_features = student_features[student_features.ID == int(id)]
    return stu_moodle, stu_echo, stu_gdocs, stu_features


def getNetwork(netw, id, selected_week=None):
    # Select the appropriate network (reply or view)

    if netw == 'reply':
        network = reply_network
        fb.log("selected_network_type:" + str(netw))
    else:
        network = view_network
        fb.log("selected_network_type:" + str(netw))
    if selected_week is not None:
        network = network[network['week'] == int(selected_week)]

    # Filter interactions involving the given student
    filtered_network = pd.concat([network[network['From'] == int(id)], network[network['To'] == int(id)]])
    filtered_network = filtered_network[~((filtered_network['From'] == int(id)) & (filtered_network['To'] == int(id)))]
    # Get the unique people involved (both senders and receivers)
    people = np.unique(np.append(filtered_network.From.unique(), filtered_network.To.unique()))

    nodes = []
    for i in people:
        # be defensive in case the lookup is empty
        name_series = student_info.loc[student_info['ID'] == i, 'AppName']
        name = name_series.iloc[0] if not name_series.empty else str(i)

        kwargs = dict(id=str(i), label=name, title=name)  # <-- hover text here
        if i == int(id):
            kwargs["color"] = "orange"
        nodes.append(Node(**kwargs))

    edges = []
    processed_edges = set()

    # Iterate through the interactions
    for i, r in filtered_network.iterrows():
        source = r['From']
        target = r['To']
        count = r['count']

        # Create a sorted tuple to uniquely identify edges between source and target
        edge_key = tuple(sorted((source, target)))

        if edge_key not in processed_edges:
            # Check for reverse interaction (target replied to source)
            reverse_interaction = filtered_network[
                (filtered_network['From'] == target) & (filtered_network['To'] == source)]

            if not reverse_interaction.empty:
                reverse_count = reverse_interaction['count'].values[0]
                # Combine the counts into one label, like "1↔1"
                combined_label = f"*{count}↔️{reverse_count}"

                # Add edge from source to target with label
                edges.append(Edge(source=str(source), target=str(target), label=combined_label, width=2))

                # Add reverse edge from target to source without label
                edges.append(Edge(source=str(target), target=str(source), width=2))

                # Mark this edge pair as processed
                processed_edges.add(edge_key)
            else:
                # If no reverse interaction, just add one edge with the count as the label
                edges.append(Edge(source=str(source), target=str(target), label=str(count), width=2))

    return nodes, edges, filtered_network


def _coerce_numeric(df, cols=('From', 'To', 'count', 'week')):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def get_metrics(user_id, selected_week=None):
    uid = int(pd.to_numeric(user_id, errors='coerce'))
    rn = _coerce_numeric(reply_network.copy())
    vn = _coerce_numeric(view_network.copy())

    # optional week filter
    if selected_week is not None and selected_week != 'All':
        wk = int(selected_week)
        rn = rn[rn['week'] == wk]
        vn = vn[vn['week'] == wk]

    # posts = threads you created yourself (self-loops)
    posts_made = int(rn.loc[(rn['To'] == uid), 'week'].dropna().astype('int64').nunique())

    # replies = you commenting on others’ threads
    replies_sent = rn.loc[(rn['From'] == uid) & (rn['To'] != uid), 'count'].sum()

    # replies received = others commenting on your threads
    # replies_recv = rn.loc[(rn['To'] == uid), 'count'].sum()

    # views received
    views_sent = vn.loc[vn['From'] == uid, 'count'].sum()

    # unique people who replied/viewed you
    uniq_repliers = rn.loc[(rn['To'] == uid) & (rn['From'] != uid), 'From'].nunique()
    uniq_viewers = vn.loc[vn['To'] == uid, 'From'].nunique()

    to_int = lambda x: int(x) if pd.notna(x) else 0
    return {
        'Debate_posts': to_int(posts_made),
        'Debate_replies': to_int(replies_sent),
        'Debate_views': to_int(views_sent),
        'Num_unique_students_have_replied': to_int(uniq_repliers),
        'Num_unique_students_have_viewed': to_int(uniq_viewers),
    }


def change_node(node):
    data = {
        'timestamp': int(datetime.now().timestamp() * 1000),
        'event': 'select_node',
        'value': node,
        'id': st.session_state.user['localId']
    }
    fb.db.child('events').push(data, st.session_state.user['localId'])


###Next Steps Page Parts######
def render_reflect_goals():
    c1, c2, c3 = st.columns([0.2, 2, 0.2])
    with c2:
        # ---- state ----
        if "reflections" not in st.session_state:
            st.session_state.reflections = []
        if "goals" not in st.session_state:
            st.session_state.goals = pd.DataFrame([{
                "Goal": "Write a reflection every Friday night",
                "Due": (datetime.today() + timedelta(days=7)).date(),
                "Status": "In progress",
                "Progress": 50,
                "Notes": "",
            }])
        if "_prev_goals" not in st.session_state:
            st.session_state._prev_goals = st.session_state.goals.copy()

        # Load data from Firebase only once per session OR when user changes
        current_user = st.session_state.user["localId"]
        if "data_loaded_user" not in st.session_state or st.session_state.data_loaded_user != current_user:
            _load_user_data()
            st.session_state.data_loaded_user = current_user
        
        with st.container(border=True):
            st.markdown("#### 💭 Reflect on Feedback")

            # Bootstrap local table
            if "reflections_df" not in st.session_state:
                if st.session_state.get("reflections"):  # migrate old list [{"ts","text"}]
                    _df = pd.DataFrame(st.session_state.reflections)
                    _df["Date"] = pd.to_datetime(_df.get("ts"), errors="coerce").dt.date
                    _df["Reflection"] = _df.get("text", "")
                    st.session_state.reflections_df = _df[["Date", "Reflection"]].copy()
                else:
                    st.session_state.reflections_df = pd.DataFrame(columns=["Date", "Reflection"])

            # If previous submit asked to clear the input, drop the key BEFORE rendering the widget
            if st.session_state.get("_clear_refl", False):
                st.session_state.pop("refl_text", None)
                st.session_state["_clear_refl"] = False

            # Use a form so submit is atomic and we can rerun cleanly
            with st.form("reflection_form", clear_on_submit=True, border=False):
                ref_text = st.text_input(
                    "Based on your analytics feedback, what did you learn or notice?",
                    placeholder="1–2 sentences…",
                    key="refl_text",
                )
                submitted = st.form_submit_button("Add reflection")

                if submitted:
                    t = (ref_text or "").strip()
                    if t:
                        # log + persist (non-fatal if either fails)
                        try:
                            fb.log("submitReflect")
                        except Exception:
                            pass
                        try:
                            fb.db.child("reflect").push(
                                {
                                    "timestamp": int(datetime.now().timestamp() * 1000),
                                    "reflection": t,
                                    "id": st.session_state.user["localId"],
                                },
                                st.session_state.user["localId"],
                            )
                        except Exception:
                            st.warning("Saving reflection to the database failed.")

                        # update local table
                        st.session_state.reflections_df = pd.concat(
                            [
                                st.session_state.reflections_df,
                                pd.DataFrame(
                                    [{"Date": datetime.today().date(), "Reflection": t}]
                                ),
                            ],
                            ignore_index=True,
                        )

                        # flag to clear the widget on the next run and rerun
                        st.session_state["_clear_refl"] = True
                        st.success("Saved")
                        st.rerun()

            # Editable table - FIXED: Added num_rows="dynamic" to allow adding new rows
            edited_ref = st.data_editor(
                st.session_state.reflections_df,
                num_rows="dynamic",  # This allows adding new rows
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Reflection": st.column_config.TextColumn(width="large"),
                },
                key="reflections_editor",
            )

            # Persist edits to session state
            if not edited_ref.equals(st.session_state.reflections_df):
                st.session_state.reflections_df = edited_ref

                # Save reflections edits to Firebase
                try:
                    uid = st.session_state.user["localId"]
                    # Clear existing reflections for this user and save all current ones
                    reflections_data = fb.db.child("reflect").get(uid)
                    if reflections_data and reflections_data.val():
                        for key, value in reflections_data.val().items():
                            if value and isinstance(value, dict) and value.get("id") == uid:
                                fb.db.child("reflect").child(key).remove(uid)

                    # Save all current reflections
                    for _, row in st.session_state.reflections_df.iterrows():
                        # Skip empty reflections
                        if pd.notna(row["Reflection"]) and str(row["Reflection"]).strip():
                            fb.db.child("reflect").push(
                                {
                                    "timestamp": int(datetime.now().timestamp() * 1000),
                                    "reflection": row["Reflection"],
                                    "id": uid,
                                },
                                uid,
                            )
                    st.success("Reflections updated!")
                except Exception:
                    st.error("Failed to save reflection edits to database")

            # Legacy mirror
            st.session_state.reflections = [
                {"ts": str(row["Date"]), "text": row["Reflection"]}
                for _, row in edited_ref.iterrows() if pd.notna(row["Reflection"]) and str(row["Reflection"]).strip()
            ]

        st.markdown(
            """
             <div style="text-align:center; font-size:40px; color:#4F46E5;">
                ↓
            </div>
            """,
            unsafe_allow_html=True
        )

        with st.container(border=True):
            st.markdown("#### 🎯 Plan Goals")

            status_options = ["Not started", "In progress", "Done"]
            status_to_progress = {"Not started": 0, "In progress": 50, "Done": 100}

            def _serialize_goals_df(df: pd.DataFrame) -> dict:
                out = {}
                for i, r in df.iterrows():
                    # Due -> ISO string or None
                    due_val = None
                    if pd.notna(r.get("Due")) and r.get("Due") is not None:
                        try:
                            if isinstance(r.get("Due"), str):
                                due_val = datetime.fromisoformat(r.get("Due")).date().isoformat()
                            else:
                                due_val = pd.to_datetime(r.get("Due"), errors="coerce")
                                due_val = None if pd.isna(due_val) else due_val.date().isoformat()
                        except Exception:
                            due_val = None

                    # Progress -> int or None
                    prog_val = 0
                    if pd.notna(r.get("Progress")) and r.get("Progress") is not None:
                        try:
                            prog_val = int(r.get("Progress"))
                        except (ValueError, TypeError):
                            prog_val = 0

                    # Goal -> string
                    goal_val = ""
                    if pd.notna(r.get("Goal")) and r.get("Goal") is not None:
                        goal_val = str(r.get("Goal"))

                    # Status -> string with validation
                    status_val = "Not started"
                    if pd.notna(r.get("Status")) and r.get("Status") is not None:
                        status_val = str(r.get("Status"))
                        if status_val not in ["Not started", "In progress", "Done"]:
                            status_val = "Not started"

                    # Notes -> string
                    notes_val = ""
                    if pd.notna(r.get("Notes")) and r.get("Notes") is not None:
                        notes_val = str(r.get("Notes"))

                    out[str(i)] = {
                        "Goal": goal_val,
                        "Due": due_val,
                        "Status": status_val,
                        "Progress": prog_val,
                        "Notes": notes_val,
                    }
                return out

            def _save_goals_to_firebase(df: pd.DataFrame):
                """Save goals to both individual goals path and goals_table"""
                uid = st.session_state.user["localId"]

                try:
                    # Save to goals_table (structured format)
                    payload = {
                        "updated": int(datetime.now().timestamp() * 1000),
                        "rows": _serialize_goals_df(df),
                    }
                    fb.db.child("users").child(uid).child("goals_table").set(payload, uid)

                    # Also save to individual goals entries for backward compatibility
                    # First, remove existing goals for this user
                    existing_goals = fb.db.child("goals").get(uid)
                    if existing_goals and existing_goals.val():
                        for key, value in existing_goals.val().items():
                            if value and isinstance(value, dict) and value.get("id") == uid:
                                fb.db.child("goals").child(key).remove(uid)

                    # Save all current goals as individual entries with proper type handling
                    for _, row in df.iterrows():
                        goal_text = str(row.get("Goal", "")).strip()
                        if goal_text:  # Only save non-empty goals
                            # Handle Due date safely
                            due_date = row.get("Due")
                            due_iso = None
                            if pd.notna(due_date) and due_date is not None:
                                try:
                                    if isinstance(due_date, str):
                                        due_iso = datetime.fromisoformat(due_date).date().isoformat()
                                    else:
                                        due_iso = pd.to_datetime(due_date).date().isoformat()
                                except (ValueError, TypeError, AttributeError):
                                    due_iso = None

                            # Handle Progress safely
                            progress_val = row.get("Progress", 0)
                            if pd.isna(progress_val):
                                progress_val = 0
                            try:
                                progress_val = int(progress_val)
                            except (ValueError, TypeError):
                                progress_val = 0

                            # Handle Status safely
                            status_val = str(row.get("Status", "Not started"))
                            if status_val not in ["Not started", "In progress", "Done"]:
                                status_val = "Not started"

                            # Handle Notes safely
                            notes_val = str(row.get("Notes", "")).strip()

                            fb.db.child("goals").push(
                                {
                                    "timestamp": int(datetime.now().timestamp() * 1000),
                                    "goal": goal_text,
                                    "due": due_iso,
                                    "status": status_val,
                                    "progress": progress_val,
                                    "notes": notes_val,
                                    "id": uid,
                                },
                                uid,
                            )

                    # Fix: Remove the second argument from fb.log() call
                    try:
                        fb.log("update_goals_table")
                    except Exception:
                        pass
                    return True
                except Exception as e:
                    st.error(f"Saving goals failed: {str(e)}")
                    return False

            # clear inputs safely before rendering widgets (from previous submit)
            if st.session_state.get("_clear_goal", False):
                for k in ["goal_title_input", "goal_notes_input", "goal_due_input", "goal_status_input"]:
                    st.session_state.pop(k, None)
                st.session_state["_clear_goal"] = False

            # Quick add (use a form for atomic submit)
            with st.form("goal_form", clear_on_submit=True, border=False):
                title = st.text_input(
                    "Set the smallest change that moves the needle.",
                    key="goal_title_input",
                    placeholder="e.g., Write a reflection every Friday night..",
                )
                due = st.date_input(
                    "Due",
                    value=(datetime.today() + timedelta(days=7)).date(),
                    key="goal_due_input",
                )
                status = st.selectbox(
                    "Status",
                    status_options,
                    index=1,
                    key="goal_status_input",
                )
                notes = st.text_input("Notes (optional)", key="goal_notes_input")

                submitted_goal = st.form_submit_button("Add goal")

                if submitted_goal and title.strip():
                    row = {
                        "Goal": title.strip(),
                        "Due": due,
                        "Status": status,
                        "Progress": status_to_progress[status],
                        "Notes": notes.strip(),
                    }

                    # log + persist single goal (non-fatal if fails)
                    try:
                        fb.log("submitGoal")
                    except Exception:
                        pass

                    # local table update
                    st.session_state.goals = pd.concat(
                        [st.session_state.goals, pd.DataFrame([row])],
                        ignore_index=True,
                    )

                    # Save the entire updated table to Firebase
                    if _save_goals_to_firebase(st.session_state.goals):
                        st.success("Goal added and saved!")
                    else:
                        st.warning("Goal added locally but saving to database failed.")

                    # clear inputs on next run and rerun
                    st.session_state["_clear_goal"] = True
                    st.rerun()

            # Editable table - FIXED: Added num_rows="dynamic" to allow adding new rows
            edited = st.data_editor(
                st.session_state.goals,
                num_rows="dynamic",  # This allows adding new rows
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Goal": st.column_config.TextColumn(width="large"),
                    "Due": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Status": st.column_config.SelectboxColumn(options=status_options),
                    "Progress": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                    "Notes": st.column_config.TextColumn(width="medium"),
                },
                key="goals_editor",
            )

            # Smart sync: if Status changed but Progress wasn't manually changed, set Progress = 0/50/100
            prev = st.session_state._prev_goals.reindex(edited.index).copy()
            for col in ["Status", "Progress"]:
                if col not in prev.columns:
                    prev[col] = None

            df = edited.copy()
            goals_changed = False

            for i in df.index:
                if i not in prev.index:
                    continue

                new_status = df.at[i, "Status"]
                new_prog = df.at[i, "Progress"]
                old_status = prev.at[i, "Status"] if pd.notna(prev.at[i, "Status"]) else None
                old_prog = prev.at[i, "Progress"] if pd.notna(prev.at[i, "Progress"]) else None

                # Convert to proper types for comparison
                try:
                    new_prog = int(new_prog) if pd.notna(new_prog) else 0
                except (ValueError, TypeError):
                    new_prog = 0

                try:
                    old_prog = int(old_prog) if pd.notna(old_prog) else 0
                except (ValueError, TypeError):
                    old_prog = 0

                if new_status != old_status:
                    if (old_prog == 0) or (new_prog == old_prog):
                        df.at[i, "Progress"] = status_to_progress.get(new_status, new_prog)
                        goals_changed = True
                        # Fix: Remove the second argument from fb.log() call
                        try:
                            fb.log("auto_progress_sync")
                        except Exception:
                            pass

            # Persist if changed, and mirror for next comparison
            if not df.equals(st.session_state.goals) or goals_changed:
                st.session_state.goals = df
                st.session_state._prev_goals = df.copy()

                # Save to Firebase
                if _save_goals_to_firebase(df):
                    st.success("Goals updated!")
                else:
                    st.error("Saving goals table failed.")

            st.caption("Progress auto-sets from Status (0/50/100). You can still edit Progress directly in the table.")

        st.markdown(
            """
             <div style="text-align:center; font-size:40px; color:#4F46E5;">
                ↓
            </div>
            """,
            unsafe_allow_html=True
        )

        with st.container(border=True):
            st.markdown("#### ⏩ Act on your goals ")
            st.markdown(""" Now, it is time to close the loop. You can start working on your goals. """)
            gdocs_link = next(
                (x for x in student_info.loc[student_info['AppName'].eq(st.session_state.selected_student), 'Gdocs']
                .dropna().astype(str).str.strip() if x),
                'There is no Gdocs link.')

            st.info(f"""Moodle: https://moodle.ucl.ac.uk/course/view.php?id=51298  
                     Gdocs: {gdocs_link}  
                     Panopto: https://ucl.cloud.panopto.eu/Panopto/Pages/Sessions/List.aspx#folderID=%2208d8c593-7c74-482c-b0fd-b3190171e0da%22 """)


def _load_user_data():
    """Load user reflections and goals from Firebase without requiring indexes"""
    uid = st.session_state.user["localId"]

    try:
        # Load reflections - alternative method without query
        reflections_data = fb.db.child("reflect").get(uid)
        if reflections_data and reflections_data.val():
            reflections_list = []
            for key, value in reflections_data.val().items():
                if value and isinstance(value, dict) and value.get("id") == uid:
                    # Handle timestamp conversion safely
                    timestamp = value.get("timestamp", 0)
                    try:
                        if timestamp > 1000000000000:  # milliseconds
                            date_obj = datetime.fromtimestamp(timestamp / 1000).date()
                        else:  # seconds
                            date_obj = datetime.fromtimestamp(timestamp).date()
                    except (ValueError, TypeError, OSError):
                        date_obj = datetime.today().date()

                    reflections_list.append({
                        "Date": date_obj,
                        "Reflection": value.get("reflection", "")
                    })

            if reflections_list:
                # Sort by date descending (newest first)
                reflections_list.sort(key=lambda x: x["Date"], reverse=True)
                st.session_state.reflections_df = pd.DataFrame(reflections_list)
                st.session_state.reflections = [
                    {"ts": str(row["Date"]), "text": row["Reflection"]}
                    for _, row in st.session_state.reflections_df.iterrows()
                ]

        # Load goals - check both individual goals and goals_table
        goals_loaded = False

        # First try to load from goals_table (preferred)
        try:
            goals_table_data = fb.db.child("users").child(uid).child("goals_table").get(uid)
            if goals_table_data and goals_table_data.val():
                goals_val = goals_table_data.val()
                if goals_val and "rows" in goals_val:
                    rows_data = goals_val["rows"]
                    goals_list = []

                    for row_key, row_data in rows_data.items():
                        if row_data and isinstance(row_data, dict):
                            # Parse due date
                            due_date = None
                            if row_data.get("Due"):
                                try:
                                    due_date = datetime.fromisoformat(row_data["Due"]).date()
                                except (ValueError, TypeError):
                                    due_date = None

                            # Handle Progress
                            progress_val = 0
                            if row_data.get("Progress") is not None:
                                try:
                                    progress_val = int(row_data.get("Progress", 0))
                                except (ValueError, TypeError):
                                    progress_val = 0

                            # Handle Status
                            status_val = "Not started"
                            if row_data.get("Status"):
                                status_val = str(row_data.get("Status", "Not started"))
                                if status_val not in ["Not started", "In progress", "Done"]:
                                    status_val = "Not started"

                            goals_list.append({
                                "Goal": row_data.get("Goal", ""),
                                "Due": due_date,
                                "Status": status_val,
                                "Progress": progress_val,
                                "Notes": row_data.get("Notes", "")
                            })

                    if goals_list:
                        st.session_state.goals = pd.DataFrame(goals_list)
                        st.session_state._prev_goals = st.session_state.goals.copy()
                        goals_loaded = True
        except Exception:
            pass  # Ignore if goals_table doesn't exist

        # If goals_table not found, try individual goals
        if not goals_loaded:
            goals_data = fb.db.child("goals").get(uid)
            if goals_data and goals_data.val():
                goals_list = []
                for key, value in goals_data.val().items():
                    if value and isinstance(value, dict) and value.get("id") == uid:
                        # Parse due date
                        due_date = None
                        due_str = value.get("due")
                        if due_str:
                            try:
                                due_date = datetime.fromisoformat(due_str).date()
                            except (ValueError, TypeError):
                                try:
                                    due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
                                except (ValueError, TypeError):
                                    due_date = None

                        # Handle Progress
                        progress_val = 0
                        if value.get("progress") is not None:
                            try:
                                progress_val = int(value.get("progress", 0))
                            except (ValueError, TypeError):
                                progress_val = 0

                        # Handle Status
                        status_val = "Not started"
                        if value.get("status"):
                            status_val = str(value.get("status", "Not started"))
                            if status_val not in ["Not started", "In progress", "Done"]:
                                status_val = "Not started"

                        goals_list.append({
                            "Goal": value.get("goal", ""),
                            "Due": due_date,
                            "Status": status_val,
                            "Progress": progress_val,
                            "Notes": value.get("notes", "")
                        })

                if goals_list:
                    # Sort by due date
                    goals_list.sort(key=lambda x: x["Due"] or datetime.max.date())
                    st.session_state.goals = pd.DataFrame(goals_list)
                    st.session_state._prev_goals = st.session_state.goals.copy()
                    goals_loaded = True

    except Exception as e:
        st.warning(f"Loading saved data failed: {str(e)}")
        # Initialize with empty data if loading fails
        if "reflections_df" not in st.session_state:
            st.session_state.reflections_df = pd.DataFrame(columns=["Date", "Reflection"])
        if "goals" not in st.session_state:
            st.session_state.goals = pd.DataFrame(columns=["Goal", "Due", "Status", "Progress", "Notes"])


def render_sidebar_chat_download(current_page: str, enabled_pages: set[str] | None = None):
    if enabled_pages is not None and current_page not in enabled_pages:
        return

    with st.sidebar:
        st.subheader("Download your chats with GenAI")

        user = st.session_state.get("user") or {}
        uid = user.get("localId")
        student_name = st.session_state.get("name", "Unknown Student")

        try:
            chat_db = fb.db.child("chathistory").get().val()
            if not chat_db:
                st.caption("No chat history found..")
                return

            chats = pd.DataFrame.from_dict(chat_db, orient="index").reset_index(drop=True)
            if chats.empty:
                st.caption("Chat history is empty.")
                return

            # convert timestamp if it exists
            if "timestamp" in chats.columns:
                chats["date"] = chats["timestamp"].apply(lambda x: datetime.fromtimestamp(x / 1000))

            # decide which column holds the page
            page_col = "graph_selection" if "graph_selection" in chats.columns else "graph"

            # filter by current user and current page
            chats = chats[(chats["id"] == uid) & (chats[page_col] == current_page)]

            if chats.empty:
                st.caption(f"No chat data for {current_page}.")
                return

            # add student name column
            chats["name"] = student_name

            # drop id and timestamp if present
            chats = chats.drop(columns=[c for c in ["id", "timestamp"] if c in chats.columns])

            # reorder for readability
            col_order = ["name", page_col, "role", "message", "date"]
            existing = [c for c in col_order if c in chats.columns]
            chats = chats[existing + [c for c in chats.columns if c not in existing]]

            csv = chats.to_csv(index=False).encode("utf-8")
            file_name = f"{current_page.lower().replace(' ', '_')}_chat.csv"

            event = f"{current_page}_chathistory"

            # st.download_button(
            #     label=f"{current_page} page chat history⬇",
            #     data=csv,
            #     file_name=file_name,
            #     mime="text/csv",
            #     key=f"dl_csv_{file_name}",
            #     on_click=click_download, args=(event,)
            # )
        except Exception as e:
            st.error(f"Error loading chat history: {e}")


def pull_feedback():
    # E1 is an explicit five-view, scoped preparation path. Legacy/replay
    # entrypoints retain their configuration when this feature is disabled.
    from utils.c4_dashboard_scoped.streamlit import scoped_evidence_enabled, render_scoped_dashboard, checked_ui_binding
    if scoped_evidence_enabled():
        binding = checked_ui_binding(st.session_state.get("c4_scoped_dashboard_binding"),
                                     st.session_state.get("selected_student"), student_info.to_dict("records"))
        render_scoped_dashboard(st, binding)
        return
    idx = student_info.index[student_info.AppName == st.session_state.selected_student]
    stu_row = student_info.loc[idx]

    # filter data
    stu_moodle, stu_echo, stu_gdocs, stu_features = pullStudentLogs(stu_row['ID'])
    # Filter inputs
    # add echo data to the counts

    event_list = moodle_df.Event.unique().tolist()
    event_list.append('Video_views')

    # prep echo data
    stu_echo_counts = stu_echo.groupby(['Content_week'])['Video Views'].sum().reset_index().rename(
        columns={'Video Views': 'Number of activities', 'Content_week': 'Week'})
    stu_echo_counts['Event'] = 'Video_views'

    if "selected_unit_indi_page" not in st.session_state:
        st.session_state.selected_unit_indi_page = "Introduction"
    pages = ["Introduction", "Resources", "Lecture", "Debate", "Reflection",
             "Next Steps"]  # my progress plan, what's next
    option_menu(None, pages,
                icons=['grid-fill', 'file-earmark-fill', 'collection-play-fill', 'wechat', 'pencil-square',
                       'flag-fill'],  # chat-left-quote-fill
                menu_icon="cast",
                default_index=pages.index(st.session_state.selected_unit_indi_page), orientation="horizontal",
                styles={"nav-link": {"--hover-color": "#d0d1fa"}}, key='selected_unit_indi_page')

    AI_PAGES = {"Resources", "Lecture", "Debate", "Reflection"}
    page = st.session_state.selected_unit_indi_page
    if page in AI_PAGES:
        render_sidebar_chat_download(page, enabled_pages=AI_PAGES)

    if st.session_state.selected_unit_indi_page == "Introduction":
        fb.log("select_ind_feedback_introduction_page")
        a1, a2, a3 = st.columns([0.2, 1, 0.2])
        with a2:
            st.subheader(f'Hello {st.session_state.name} !')
            st.markdown("""
                    This dashboard brings together your activity data from Moodle, Panopto, and GDocs. It visualises clicks, views, and interactions across activities and provides feedback that you can reflect on.  
                    **Why it matters**  
                    When you engage with this feedback, it will help you;
                    - Spot strengths and blind spots quickly,  
                    - Turn activity traces into concrete study decisions,  
                    - Build the habits that actually move your learning process forward,  
                    - Set goals and adjust strategies for growth,  
                    - Strengthen self-regulated learning, motivation, and learning outcomes.  
                    """
                        )
            st.subheader("How to engage with it")
            st.markdown(""" 
                    Use the tabs in order; each one focuses on a different type of activity and provides written feedback.  
                    **Step 1. Resources**  
                    Review how and when you access readings and module materials on Moodle.  
                    **Step 2. Lecture**   
                    Check your viewing/watching patterns of pre-recorded lecture videos.  
                    **Step 3. Debate**   
                    Reflect on your debate contributions.  
                    **Step 4. Reflection**   
                    Look at the frequency and timing of your reflective writing.  
                    **Step 5. Next Steps**  
                    Bring everything together: share your reflections, set learning goals and act on these goals.  
                    **⬇ Download your data**  
                    Download your data from the sidebar to further explore yourself.  
                    **🤖 Need support along the way?**  
                    Use the built-in GenAI assistant (chatgpt-4o-mini) to ask questions, clarify feedback, or explore strategies. Treat it as an engagement partner; it won’t give you answers to everything, but it will help you think through your data and next steps.
                    """)
            st.subheader("How your data were processed?")
            st.image("input/images/dataprocess.jpg", width=800)
            st.subheader('References')
            ref = open("input/references.txt", "r").read()
            st.info(ref)
    # Resources
    elif st.session_state.selected_unit_indi_page == "Resources":
        fb.log("select_ind_feedback_resources_page")
        a1, a2 = st.columns([3, 0.5])
        with a1:
            st.subheader("How regularly are you accessing the course materials and resources on Moodle?")
            st.caption("E.g. readings, guidelines, handbook, extra resources, or group activity materials")
        with a2:
            st.metric(label="**Total resource views**", value=stu_features['Resources_views'],
                      help='Number of learning content views on Moodle')

        with st.sidebar:
            st.subheader("Download your log data to further explore")
            csv = convert_df(stu_moodle[stu_moodle.Event == 'Resources_views'].drop(columns='ID'))  # to be filtered
            # st.download_button(
            #     label="Resources log data⬇", help="To explore the data yourself!",
            #     data=csv,
            #     file_name='moodle_resources_logs.csv',
            #     mime='text/csv',
            #     on_click=click_download, args=('resource',)
            # )
        event = 'Resources_views'

        c1, c2 = st.columns([5, 4], vertical_alignment="center")
        with c1:
            stu_ped_filtered = compute_ped(stu_moodle, event)
            print_weekly_patterns(stu_ped_filtered)
        with c2:
            stu_delay_filtered = compute_delay(stu_moodle, event)
            print_heat_map(stu_delay_filtered)
            st.caption("*all the readings are already available, they might appear as early")

        st.write("\n\n")
        # should query from features
        stu_filtered = filter_data(stu_moodle, 'Event', event)
        stu_filtered['W'] = stu_filtered['Week']  # duplicate in 'W'
        stu_filtered['Week'] = stu_filtered['Week'].map(c.MAPPING_WEEK_TO_CONTENT)
        # st.write(stu_filtered)
        active_weeks = len(stu_filtered['Week'].unique())
        num_events = len(stu_filtered)
        late_weeks, late_list, active_list = calculate_delay(stu_filtered, list(c.CONTENT_WEEK_LIST))
        description = generate_text_feedback(event, active_weeks=active_weeks, num_events=num_events,
                                             late_weeks=late_weeks)
        st.info(f'**"** {description}**"**')
        visual_info = """
        . The line graph displays engagement frequency across days of the week.
        . Colors indicate different weekly patterns.
        - Heat map shows content week vs. engaged week
        - Cells on the diagonal: on-time engagement
        - Below the diagonal: earlier than the content week (preview)
        - Above the diagonal: later than the content week (review/catch-up)
        - Darker blue = more engagements"""
        df = stu_ped_filtered
        df2 = stu_delay_filtered
        # st.session_state.messages = []
        c1, c2, c3 = st.columns([1, 2, 2])
        with c3:
            ai_assistant("Resources", visual_info, df, description, df2)
        with c2:
            show_comment_box("ind_resource")

    # Lecture view
    elif st.session_state.selected_unit_indi_page == "Lecture":  # Video_views: unique_views, missed_list, percent_views
        fb.log("select_ind_feedback_lecture_page")
        a1, a2 = st.columns([3, 0.5])
        with a1:
            st.subheader("How much are you watching the course lecture videos on Panopto?")
            st.caption(
                "Bar chart shows your engagement with pre-recorded lecture videos on Panopto.")  # and Heat map shows your weekly video link clicks on Moodle.")
        with a2:
            if stu_echo.empty:
                st.metric(label="**Total video views**", value='-', help='Number of video views on Panopto')
            else:
                st.metric(label="**Total video views**", value=stu_features['Video_views_sum'],
                          help='Number of video views on Panopto')
        with st.sidebar:
            st.subheader("Download your log data to further explore")
            csv = convert_df(stu_echo.drop(columns='ID'))
            # st.download_button(
            #     label="Lecture log data⬇", help="To explore the data yourself!",
            #     data=csv,
            #     file_name='panopto_logs.csv',
            #     mime='text/csv',
            #     on_click=click_download, args=('lecture',)
            # )
        if len(stu_echo) == 0:
            st.warning('There was no data to be retrieved from your panopto logs.')
        else:
            event = 'Video_views'
            # filter only the first five weeks
            idx_last_contents = stu_echo[stu_echo['Content_week'] == c.FEEDBACK_WEEK].index[-1]  # convert to int
            # st.write(idx_last_contents) #HIDE
            # agg function: don't need: .groupby(['Content_week', 'Class']).agg({'Video Views': 'sum', 'Video View %': 'mean'})
            focused_videos = stu_echo.iloc[0:idx_last_contents + 1].groupby(['Content_week'])[
                ['Video Views', 'Video View %']].mean().reset_index()
            c1, c2, c3 = st.columns([0.1, 2, 0.9], vertical_alignment="center")
            with c2:
                colors = ['#dc2f02', '#F3722C', '#F9844A', '#F9C74F', '#90BE6D', '#43AA8B', '#05a8aa']
                fig = px.bar(stu_echo, x='Video Views', y='Class', color='Video View %',
                             # we have a video per week so we can present name on y axis
                             title='Number and percentage of video views per week',
                             color_continuous_scale=colors)  # px.colors.diverging.Spectral)

                fig.update_yaxes(showgrid=False, tickmode="linear", tick0=0, dtick=1,
                                 tickfont={"size": 12, "family": "Arial", "color": "black", "weight": "bold"})
                fig.update_xaxes(showgrid=False)
                fig.update_coloraxes(cmin=0, cmax=100)
                st.plotly_chart(fig, use_container_width=True)
                p = st.popover("What is this graph?", use_container_width=False)
                visual_info = """ 
                . The bar chart shows the number of video views per week.
                . The colours represent the percentages of video view from 0% (red) to 100% (green).
                . You can hover over the chart to see details.
                """
                p.text(visual_info)
                # with c1:
                stu_delay_filtered = compute_delay(stu_moodle, 'Video_views')
                # print_heat_map(stu_delay_filtered)

                unique_views = (focused_videos['Video Views'] != 0).sum()
                missed_list = ['W' + str(item) for item in focused_videos[
                    (focused_videos['Video Views'] == 0) & (focused_videos['Content_week'] != 3)][
                    'Content_week'].astype(int).to_list()]
                percent_views = round(focused_videos[focused_videos['Video Views'] != 0]['Video View %'].mean(), 2)
                description = generate_text_feedback(event, unique_views=unique_views, missed_list=missed_list,
                                                     percent_views=percent_views)
            st.info(f'**"**{description}**"**')
            visual_info = """ 
                . The bar chart shows the number of video views per week.
                . The colours represent the percentages of video view from 0% (red) to 100% (green).
                . You can hover over the chart to see details.
                """
            c1, c2, c3 = st.columns([1, 2, 2])
            with c3:
                df = stu_echo.drop(columns='ID')
                df2 = stu_delay_filtered
                # st.session_state.messages = []
                ai_assistant("Lecture", visual_info, df, description)
            with c2:
                show_comment_box("ind_lecture")

    # Debate
    elif st.session_state.selected_unit_indi_page == "Debate":  # Debate: num_posts, num_replies, num_views, late_week_list
        fb.log("select_ind_feedback_debate_page")
        a1, a2 = st.columns([3, 0.8])
        with a1:
            st.subheader("How actively are you participating in the debate movements on Moodle?")
        with a2:

            with st.popover("What is this graph?", use_container_width=False):
                visual_info = """
                . The network displays engagement frequency in Moodle debates.
                . Circles represent students you interacted with in replying or viewing.
                . Arrows represent direction of the interaction with students.
                . '*1↔2' in bidirectional interactions, * respresents your interaction number."""
                st.text(visual_info)
            weeks = ['All'] + [w for w in range(1, 9) if w != 3]
            selected_week = st.selectbox('Filter by Week:', weeks, key='selected_week', on_change=select_network_week)
        with st.sidebar:
            st.subheader("Download your log data to further explore")
            csv = convert_df(stu_moodle[stu_moodle.Activity == 'Debate'].drop(columns='ID'))  # to be filtered
            # st.download_button(
            #     label="Debate log data⬇", help="To explore the data yourself!",
            #     data=csv,
            #     file_name='moodle_debate_logs.csv',
            #     mime='text/csv',
            #     on_click=click_download, args=('debate',)
            # )
        c1, c3, c4 = st.columns([1, 3, 0.5])
        with c3:
            netw_type = ['Replying', 'Viewing']
            sac.chip(
                items=[
                    sac.ChipItem(label=netw_type[0], icon="chat-quote-fill"),
                    sac.ChipItem(label=netw_type[1], icon="eye-fill"),
                ], align='left', multiple=False, label="Select a type of network",
                index=netw_type.index(st.session_state.get('selected_network')), key='selected_network',
                on_change=selected_network, args=('selected_network')
            )

            if st.session_state.selected_network == 'Replying':
                nodes, edges, stu_network = getNetwork('reply', stu_row['ID'],
                                                       None if selected_week == 'All' else selected_week)
            else:
                nodes, edges, stu_network = getNetwork('view', stu_row['ID'],
                                                       None if selected_week == 'All' else selected_week)
            # config = Config( height=500, directed=True, hierarchical=True, nodeHighlightBehavior=True, highlightColor="#F7A7A6", linkHighlight=True, arrows=True, physics=True)
            config = Config(height=400, directed=True, nodeHighlightBehavior=True, highlightColor="#F7A7A6",
                            linkHighlight=True, arrows=True, physics=True,
                            # Physics starts enabled to arrange the nodes
                            physicsSettings={
                                "enabled": True,
                                "barnesHut": {
                                    "gravitationalConstant": -5000,  # Control node spacing
                                    "centralGravity": 0.3,  # Control the central pull of nodes
                                    "springLength": 200,  # Increase node spacing
                                    "springConstant": 0.05  # Make the edges softer for smoother movement
                                },
                                "maxVelocity": 50,
                                "minVelocity": 0.1,
                                "solver": "barnesHut"
                            },
                            stabilization={
                                "enabled": True,
                                "iterations": 1000,  # How long to stabilize the network
                                "onlyDynamicEdges": False
                            },
                            physicsAfterStabilization=False  # Turn off physics after the graph is stabilized
                            )
            return_node = agraph(nodes=nodes, edges=edges, config=config)
            if return_node: change_node(return_node)
        with c1:
            m = get_metrics(stu_row['ID'], None if selected_week == 'All' else selected_week)
            st.metric("#posts", m['Debate_posts'], help="Number of debate posts")
            st.metric("#replies", m['Debate_replies'], help="Number of debate replies")
            st.metric("#views", m['Debate_views'], help="Number of debate views")
            st.metric("#student replies", m['Num_unique_students_have_replied'],
                      help="Distinct students who replied to you")
            st.metric("#student views", m['Num_unique_students_have_viewed'], help="Distinct students who viewed you")
            metrics_data = {
                "Metric": ["#posts", "#replies", "#views", "#student replies", "#student views"],
                "Value": [
                    m['Debate_posts'],
                    m['Debate_replies'],
                    m['Debate_views'],
                    m['Num_unique_students_have_replied'],
                    m['Num_unique_students_have_viewed']
                ],
                "Description": [
                    "Number of debate posts",
                    "Number of debate replies",
                    "Number of debate views",
                    "Number of students replied to your posts",
                    "Number of students viewed your posts"
                ]
            }

            # Convert the dictionary to a DataFrame
            metrics_df = pd.DataFrame(metrics_data)
        # with c4:

        event = 'Debate'
        stu_filtered = filter_data(stu_moodle, 'Event', 'Debate_posts')
        stu_filtered['W'] = stu_filtered['Week']  # duplicate in 'W'
        stu_filtered['Week'] = stu_filtered['Week'].map(c.MAPPING_WEEK_TO_CONTENT)
        num_posts = len(stu_filtered['Content_week'].unique())
        late_weeks, late_week_list, active_list = calculate_delay(stu_filtered, range(1,
                                                                                      c.FEEDBACK_WEEK + 1))  # list(c.CONTENT_WEEK_LIST))
        stu_filtered = filter_data(stu_moodle, 'Event', 'Debate_replies')
        num_replies = len(stu_filtered['Content_week'])
        # stu_filtered = filter_data(stu_moodle, 'Event', 'Debate_views')
        # num_views = len(stu_filtered['Content_week'])

        description = generate_text_feedback(event, num_posts=num_posts, num_replies=num_replies,
                                             num_unique_students_i_viewed=stu_features[
                                                 'Num_unique_students_i_viewed'].item(),
                                             num_unique_students_have_viewed=stu_features[
                                                 'Num_unique_students_have_viewed'].item(),
                                             late_week_list=late_week_list)

        st.info(f'**"** {description}**"**')

        c1, c2, c3 = st.columns([1, 2, 2])
        with c3:
            df = []  # simplify this data it is too much!!
            # st.session_state.messages = []
            ai_assistant("Debate", visual_info, df, description, metrics_df)
        with c2:
            show_comment_box("ind_debate")


    # Individual reflection
    elif st.session_state.selected_unit_indi_page == "Reflection":  # Reflection: active_weeks, inactive_week_list, active_week_list
        fb.log("select_ind_feedback_reflection_page")
        a1, a2 = st.columns([3, 0.5])
        with a1:
            st.subheader("How do you engage with your individual reflection activities on Gdocs?")
        with a2:
            st.metric(label="**Total strings in the reflection**", value=stu_features['Total_chars'],
                      help='Number of strings in the reflection document')
        with st.sidebar:
            st.subheader("Download your log data to further explore")
            csv = convert_df(stu_gdocs.drop(columns='ID'))  # to be filtered
            # st.download_button(
            #     label="Reflection log data ⬇", help="To explore the data yourself!",
            #     data=csv,
            #     file_name='gdocs_logs.csv',
            #     mime='text/csv',
            #     on_click=click_download, args=('reflection',)
            # )
        stu_gdocs_ped = pd.DataFrame()
        description = " "
        if not stu_gdocs.empty:  # pd.notna(stu_row['DocID']).any(): can be not sharing or share but have no interaction in the period
            # add individual data
            gdocs_ts['student'] = stu_gdocs.groupby('day')['absStrCount'].sum()
            # plot
            stu_gdocs_ped = stu_gdocs.groupby(['Week', 'dayOfWeek'])['absStrCount'].sum().reset_index()
            if c.CONTAIN_RW:
                stu_gdocs_ped = pad_2vars(stu_gdocs_ped, c.DAY_LIST, range(1, c.FEEDBACK_WEEK + 2), 'dayOfWeek',
                                          'Week')  # +2 for the end and RW
            else:
                stu_gdocs_ped = pad_2vars(stu_gdocs_ped, c.DAY_LIST, range(1, c.FEEDBACK_WEEK + 1), 'dayOfWeek',
                                          'Week')  # +1 for the end
            print_weekly_patterns(stu_gdocs_ped)

        else:
            gdocs_ts['student'] = 0
            st.warning('There was no data to be retrieved from your reflective document')
        gdocs_ts.fillna(0, inplace=True)
        max_week = math.ceil(len(gdocs_ts['student']) / 7)
        x_vals = list(range(1, 1 + max_week * 7, 7))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=gdocs_ts['day'], y=gdocs_ts['previousCohorts'], name="Previous Cohorts",
                                 line=dict(color='cyan')))
        fig.add_trace(
            go.Scatter(x=gdocs_ts['day'], y=gdocs_ts['currentCohort'], name="Your Cohort", line=dict(color='blue')))
        if not stu_gdocs.empty:
            fig.add_trace(go.Scatter(x=gdocs_ts['day'], y=gdocs_ts['student'], name=st.session_state.name,
                                     line=dict(color='red')))
        fig.update_yaxes(showgrid=False, title='Number of edited contents per day (characters)')
        fig.update_xaxes(showgrid=True, title='Week (Starting on Monday)')
        fig.update_layout(
            title=f'Number of edited contents per day (characters) compared between cohorts across {max_week} weeks',
            xaxis=dict(
                dtick=1,
                showticklabels=True,
                tickmode='array',
                tickvals=x_vals,
                ticktext=c.FEEDBACK_WEEK_LABEL_LIST[1:]  # exclude week 0
            ))
        st.plotly_chart(fig, use_container_width=True)

        with st.popover("What is this graph?", use_container_width=False):
            fb.log("Reflection_whatIsThis")
            second_graph = """
                    . The line graph shows a comparison of the number of edited content in Gdocs. 
                    . Red line indicates you, dark blue is the cohort of 2025, and light blue represents the previous cohorts' average."""
            st.text(second_graph)
        c1, c2, c3 = st.columns([0.05, 0.9, 0.05])
        with c2:
            # narration
            # Reflection: active_weeks, inactive_week_list, active_week_list
            description = " "
            active_engagement = stu_gdocs.groupby(['Week'])[
                'absStrCount'].sum().reset_index()  # (stu_gdocs[stu_gdocs['Week'] <= 4].groupby('Week')['absStrCount'].sum().reset_index())#stu_gdocs.groupby(['Week'])['absStrCount'].sum().reset_index()#[stu_gdocs.Week <= 4]
            active_engagement = active_engagement[active_engagement['absStrCount'] > 0]
            active_engagement['W'] = active_engagement['Week'].map(c.MAPPING_WEEK_TO_TEXT)
            active_weeks = len(active_engagement)
            active_week_list = active_engagement.W.to_list()
            inactive_week_list = list(set(c.FEEDBACK_WEEK_LABEL_LIST[1:]) - set(active_week_list))
            if not stu_gdocs.empty:
                description = generate_text_feedback('Reflection', active_weeks=active_weeks,
                                                     inactive_week_list=inactive_week_list,
                                                     active_week_list=active_week_list)
                st.info("""**"** """ + description + """**"** """)

            st.info("""Compared to the previous year’s cohorts, DUTE students showed higher engagement with their reflective writing tasks at the beginning of the module, with increased engagement over time. From our previous studies on students’ reflective writing behaviours, highly self-regulated learners tend to:  
                 1. Show more systematic patterns by reflecting more regularly with spaced practice (not cramming their reflections),  
                 2. React promptly to the feedback provided and  
                 3. Avoid postponing the work until the deadline.  
            It is also worth noting that, a higher number of edited contents does not necessarily lead to better learning outcomes, but the systematic pattern of reflective writing is more likely to do.
            More information could be found in the following publications: https://link.springer.com/chapter/10.1007/978-3-030-86436-1_13 and https://link.springer.com/article/10.1186/s41239-022-00368-0.**"**
            """)
        c1, c2, c3 = st.columns([1, 2, 2])
        with c3:
            first_graph = """
            . The line graph displays engagement frequency across days of the week.
            . Colors indicate different weekly patterns."""
            visual_info = f'first graph: {first_graph}, second graph: {second_graph}'
            if stu_gdocs_ped.empty:
                dfgd = pd.DataFrame()
            else:
                dfgd = stu_gdocs_ped  # add second chart info as well
            ai_assistant("Reflection", visual_info, dfgd, description, gdocs_ts)
        with c2:
            show_comment_box("ind_reflection")

    # Next steps
    elif st.session_state.selected_unit_indi_page == "Next Steps":
        fb.log("select_ind_feedback_next_steps")
        c1, c2 = st.columns([2, 0.5], vertical_alignment="center")
        with c1:
            st.subheader("What should you do next?")
            st.markdown("""
            Now that you’ve explored how you engage with resources, lectures, debates, and reflections, you have enough signal to pick one or two small habits to work on next week. 
            If you'd like, add a brief reflection on what the feedback means to you, set a simple goal for next week, and complete the cycle by working on these goals.
            This process reflects the core of **self-regulated learning (SRL)**, planning, monitoring, and evaluating your learning process, so each step supports you in learning with a bit more focus and a clearer sense of where you’re heading. **All of these are optional.**
           """)
            with st.expander("Reference"):
                st.info(
                    "Zimmerman, B. J. (2002). Becoming a Self-Regulated Learner: An Overview. Theory Into Practice, 41(2), 64–70. https://doi.org/10.1207/s15430421tip4102_2")
        with c2:
            st.image("input/images/srl.png", width=200)
        render_reflect_goals()
        # with c2:  #show_comment_boxx("next steps")


def save_chat_history_to_csv(chat_history, file_name='chat_history.csv'):
    # Check if the file exists, and if not, write the header
    file_exists = os.path.exists(file_name)
    # Open the file in append mode
    with open(file_name, mode='a', newline='') as file:
        writer = csv.writer(file)
        # If file doesn't exist, write the header first
        if not file_exists:
            writer.writerow(["timestamp", "role", "message", "graph_selection"])

        # Write chat history to the CSV file
        for entry in chat_history:
            writer.writerow([entry['timestamp'], entry['role'], entry['message'], entry['graph_selection']])


# Function to add a new entry to the chat history (with graph selection)
def add_to_chat_history(role, content, graph_selection):
    data = {
        'timestamp': int(datetime.now().timestamp() * 1000),
        'role': role,
        'message': content,
        'graph': graph_selection,
        'id': st.session_state.user['localId']
    }
    fb.db.child('chathistory').push(data, st.session_state.user['localId'])

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Current timestamp
    st.session_state['history'].append({
        "timestamp": timestamp,
        "role": role,
        "message": content,
        "graph_selection": graph_selection
    })
    save_chat_history_to_csv([{
        "timestamp": timestamp,
        "role": role,
        "message": content,
        "graph_selection": graph_selection
    }])  # Save after each message


# Function to get few shot examples based on selected graph
def get_few_shot(graph_selection):
    if graph_selection == "Overview":
        info = """
       Student sees a line chart of weekly activity and a summary highlighting strong engagement with materials but low debate participation. 
         Q1: What should I focus on improving based on this feedback? 
        A1: Your engagement with resources is strong, but your debate contributions are low. Turning some of your debate views into posts or replies will deepen your understanding and sharpen your critical thinking. Aim to make at least one thoughtful post each week. What’s one step you could take this week to join a debate and keep your study momentum going? 
        Q2: What does it mean viewing [X] times? Is it bad or good? 
        A2: The number itself isn’t a grade. What matters is that you’re checking in regularly and using those resources to prepare for class. Focus on pacing yourself so each week you feel ready for lectures and debates. Which week’s resources felt most useful, and What was the routine that week so that you can repeat? 
        Q3: Why should I care about this feedback? 
        A3: This feedback is a mirror of your habits. Regular engagement builds confidence, helps you retain material, and makes participation easier over time. Being aware of these trends now helps you shape stronger study habits. Looking at your graph, which habit do you think has helped you most so far? 
        """
        return info
    elif graph_selection == "Resources":
        info = """
       Student sees a line graph of clicks on Moodle resources and readings. 
        Q1: What does an increase in resource clicks mean? 
         A1: It means you’ve been more active in exploring readings and resources provided on Moodle. Keep the momentum! this kind of steady engagement makes you feel more prepared. Would you like to check the Moodle page for missed resources in week X? 
        Q2: Why did my resource clicks drop in Week 3? 
         A2: That dip could reflect a busier schedule or topics you found less engaging. Looking back at Week 3’s materials to see if there’s anything you missed and plan a short review session if you need: here is the Moodle link for Week3 resources: [link]
        Q3: Should I view resources every day? 
         A3: Daily viewing isn’t essential, but regular weekly check-ins are. Try batching resource reviews before class so you’re ready to discuss them. You can plan those reviews based on your most active study days, can you identify your active study day from visual? 
               """
        return info
    elif graph_selection == "Debate":
        info = """
        Student sees a network chart showing debate views, posts, and replies in Moodle debates. 
        Q1: Did I reply to [Lidya] 3 times? or What does arrow and number mean between [Yildiz] and [John]? 
         A1: I don’t have access to participant names for privacy reasons, but the arrows show the direction of replies and numbers show the count between two people. In your network, which connections stand out to you? You can consider replying to peers who you haven’t replied yet to contribute diverse debates. 
        Q2: Why are my debate posts or replies low this week [Week4]? 
        A2: Posting takes more time and confidence than viewing, so lower numbers are normal at first. Think about which debates you felt ready to join and start with those topics can help you build momentum. Would you like to visit Moodle to see what your peers posted, you can start from replying to their posts? 
        Q3: Is more views or replies always better? 
         A3: Not always. What matters is thoughtful participation. Aim for at least two reply per week, ideally responding to someone with a different perspective. Looking at your network graph, which peer could you reply to balance your activity?
            """
        return info
    elif graph_selection == "Lecture":
        info = """
        Student sees engagement trends with pre-recorded videos. 
        Q1: What does an increase in lecture video views mean? 
         A1: It shows you’re becoming more consistent in preparing for class. Keep up the routine! it’ll help you connect the lectures with debates and reflections. Which week’s video you viewed most? 
        Q2: Why did my lecture views drop in Week 2? 
         A2: That could mean you were busy, or the topic didn’t grab you. Revisit Week 2’s video if it connects to upcoming assessments. it’s worth catching up. Would you like to watch the video now? 
        Q3: What does this graph tell me? 
        A3: This chart shows your weekly engagement with recorded lectures. Each bar represents a week, and colours indicate how much of each video you watched—from red (0%) to green (100%). You’ve watched almost all the videos so far, averaging about 96%. That’s excellent consistency! What would you like to focus on next?   """
        return info
    elif graph_selection == "Reflection":
        info = """
        Student sees activity graphs for Google Docs reflections. 
        Q1: How can I increase my reflection writing consistency? 
        A1: You can choose a fixed day and time each week to write. Even 10 minutes of regular reflection will help you remember key ideas and track your growth. Could you identify your weekly routines from the graph? 
        Q2: Can you tell me more about the content in my reflective writing? 
        A2: I'm sorry for any confusion, but as an AI assistant, I don't have the capacity to analyze the quality of your reflection content directly. However, here is the Moodle link to reflective writing guidelines:[Moodle link] Would you like me to give you some tips for improving reflection quality? 
        Q3: How can I write better reflections? 
        A3: I see you’re interested in improving your reflective writings, here are some tips for that; 
        1. Link experiences: Try to make connections between your experiences and the lecture. 
        2. Be consistent and regular: Aim to make reflection a consistent part of your learning, not just something you do at the end of a module. As seen in your graph, you are active on [day], you can plan writing time accordingly. 
        Remember, reflection is a continuous process for enhancing your understanding and learning. So keep practicing and refining your methodology. When do you usually feel most productive?	"""
        return info


ss = st.session_state
ss.setdefault("history", [])
# Visible transcripts and structured C_FULL Memory share one student-session
# scope. Each message retains its originating dashboard page for provenance.
ss.setdefault("chat_messages_by_scope", {})
ss.setdefault("memory_turns_by_student", {})
ss.setdefault("structured_memory_by_student", {})
ss.setdefault("c_full_memory_by_student", {})
ss.setdefault("memory_resolution_by_student", {})
ss.setdefault("retrieval_details_by_student", {})
ss.setdefault("c4_real_service", None)
ss.setdefault("c4_real_state_reset_ids", {})
ss.setdefault("c4_real_trace_by_scope", {})
ss.setdefault("c4_real_memory_disabled_by_scope", {})


def _memory_scope_key():
    """Keep session memory separated when an administrator switches students."""

    user = ss.get("user") or {}
    return session_memory_scope_key(ss.get("selected_student"), user.get("localId"))


def _chat_scope_key(graph):
    """Use one visible transcript across pages for the C_FULL student session."""

    user = ss.get("user") or {}
    return session_memory_scope_key(ss.get("selected_student"), user.get("localId"))


def _current_student_id():
    """Map the visible student name to the complete-dashboard student ID."""

    selected = ss.get("selected_student")
    matches = student_info.loc[student_info["AppName"].eq(selected)]
    if not matches.empty and "ID" in matches.columns:
        return str(matches.iloc[0]["ID"])
    return str(selected or "")


def _c4_real_research_enabled():
    """Keep the existing C_FULL path as the default when the flag is absent."""

    try:
        secrets = st.secrets
    except Exception:
        secrets = None
    return research_mode_enabled(secrets=secrets)


def _c4_real_scope(memory_key, mode, state_reset_id):
    return MemoryScope(
        execution_context=ExecutionContext.INTERACTIVE,
        student_id=_current_student_id(),
        session_id=memory_key,
        scenario_id=f"STREAMLIT::{memory_key}",
        condition_id=mode.value,
        state_reset_id=state_reset_id,
    )


def _render_c4_real_memory_controls(service, scope, scope_key):
    """Render contract-level Memory controls without exposing database internals."""

    with st.expander("C4 research Memory controls", expanded=False):
        disabled_key = f"c4_real_memory_disabled::{scope_key}"
        disabled = st.toggle(
            "Disable Memory",
            value=ss.c4_real_memory_disabled_by_scope.get(scope_key, False),
            key=disabled_key,
        )
        if disabled != ss.c4_real_memory_disabled_by_scope.get(scope_key, False):
            service.disable_learner_memory(scope, disabled=disabled)
            ss.c4_real_memory_disabled_by_scope[scope_key] = disabled

        items = list(service.view_learner_memory(scope))
        st.caption("Learner Memory")
        st.json(
            [
                {
                    "memory_id": item.memory_id,
                    "item_type": item.item_type,
                    "value": item.value,
                }
                for item in items
            ]
        )
        if items:
            item_ids = [item.memory_id for item in items]
            selected_id = st.selectbox(
                "Memory item",
                item_ids,
                key=f"c4_real_memory_item::{scope_key}",
            )
            corrected_value = st.text_input(
                "Corrected value",
                key=f"c4_real_memory_correction::{scope_key}",
            )
            correct_col, delete_col = st.columns(2)
            if correct_col.button("Correct Memory", key=f"c4_real_correct::{scope_key}"):
                service.correct_learner_memory(scope, selected_id, corrected_value)
                st.rerun()
            if delete_col.button("Delete Memory", key=f"c4_real_delete::{scope_key}"):
                service.delete_learner_memory(scope, selected_id)
                st.rerun()
        if st.button("Clear research Memory", key=f"c4_real_clear::{scope_key}"):
            service.clear_research_memory(scope.student_id)
            st.rerun()


@st.fragment
def show_chat_box(graph):
    # ---------- CSS + JS ----------
    st.markdown(
        """
        <style>
          :root { --chat-purple:#4F46E5; }

          /* ===== chat-only (tagged via JS) ===== */
          button._is_chat_trigger{
            position: fixed; right: 24px; bottom: 24px; z-index: 1000;
            width: 44px; height: 44px; border-radius: 50%;
            box-shadow: 0 4px 10px rgba(0,0,0,.2) !important;
            border: none !important; background: var(--chat-purple) !important;
            color: #fff !important; font-size: 20px;
            display: flex; align-items: center; justify-content: center;
          }

          /* wider chat popover */
          div._is_chat_popover{
            box-sizing: border-box !important;
            width: 500px !important;   /* was 450 */
            min-width: 500px !important;
            max-width: 500px !important;
            height: 600px !important;
            max-height: 600px !important;
            border-radius: 10px !important;
            overflow: hidden !important;
          }

          /* keep input in flow */
          div._is_chat_popover div[data-testid="stChatInput"]{
            position: static !important; max-width: 100% !important; margin-top: 8px !important;
          }

          /* tighter message spacing (less “centered” look) */
          div._is_chat_popover div[data-testid="stChatMessage"]{ padding: 1px 0 !important; }
          div._is_chat_popover [data-testid="stMarkdownContainer"]{ text-align: left !important; width: 100%; }
          div._is_chat_popover [data-testid="stMarkdownContainer"] p{ margin: 0 0 .18rem 0 !important; }
          div._is_chat_popover [data-testid="stMarkdownContainer"] ul,
          div._is_chat_popover [data-testid="stMarkdownContainer"] ol{ margin: .15rem 0 .2rem 1rem !important; }
          div._is_chat_popover pre{ margin: .2rem 0 !important; }

          /* mobile fallback for chat */
          @media (max-width: 480px){
            div._is_chat_popover{
              width: 92vw !important; min-width: auto !important; max-width: 92vw !important;
              height: 80vh !important;
            }
          }

          /* ===== other popovers (unaltered layout, compact body) ===== */
          div[data-testid="stPopoverBody"], div[role="dialog"]{
            box-sizing: border-box; max-width: 360px; max-height: 75vh; border-radius: 8px; overflow: auto;
          }
        </style>

        <script>
        // Tag only the chat trigger/dialog so styles apply narrowly
        (function(){
          const TRIGGER_TEXT = "🤖 Chat with GenAI Assistant!";
          const TRIGGER_CLASS = "_is_chat_trigger";
          const DIALOG_CLASS = "_is_chat_popover";

          function tag(){
            const btns = Array.from(document.querySelectorAll(
              'button[data-baseweb="button"], button[data-testid="stPopoverButton"], div[data-testid="stPopover"] > button'
            ));
            for(const b of btns){
              if(b.classList.contains(TRIGGER_CLASS)) continue;
              if((b.textContent || "").trim() === TRIGGER_TEXT){
                b.classList.add(TRIGGER_CLASS);
                b.addEventListener('click', () => setTimeout(tagDialogs, 0), { once:false });
              }
            }
            tagDialogs();
          }

          function tagDialogs(){
            const dialogs = Array.from(document.querySelectorAll('div[role="dialog"], div[data-testid="stPopoverBody"]'));
            for(const d of dialogs){
              if(d.classList.contains(DIALOG_CLASS)) continue;
              if((d.textContent || "").indexOf("GenAI Assistant") !== -1){
                d.classList.add(DIALOG_CLASS);
              }
            }
          }

          tag();
          const mo = new MutationObserver(tag);
          mo.observe(document.body, { childList:true, subtree:true });
        })();
        </script>
        """,
        unsafe_allow_html=True
    )

    # ---------- chat body ----------
    def _chat_body():

        st.markdown("#### 🤖 GenAI Assistant")
        st.caption("The assistant is here for you to ask questions, clarify feedback, or explore strategies.")
        memory_key = _memory_scope_key()
        chat_scope = _chat_scope_key(graph)
        messages = scoped_chat_messages(ss.chat_messages_by_scope, chat_scope)
        c4_research_enabled = _c4_real_research_enabled()
        c4_mode = None
        c4_service = None
        c4_scope = None
        c4_scope_key = ""
        c4_reset_id = ""
        if c4_research_enabled:
            selected_label = st.selectbox(
                "Research condition",
                list(RESEARCH_MODE_LABELS),
                index=0,
                key=f"c4_real_mode::{memory_key}",
            )
            c4_mode = RESEARCH_MODE_LABELS[selected_label]
            c4_scope_key = research_scope_key(memory_key, c4_mode)
            chat_scope = c4_scope_key
            messages = scoped_chat_messages(ss.chat_messages_by_scope, chat_scope)
            c4_reset_id = ss.c4_real_state_reset_ids.setdefault(
                c4_scope_key,
                str(uuid.uuid4()),
            )
            c4_scope = _c4_real_scope(memory_key, c4_mode, c4_reset_id)
            candidate_service = ss.get("c4_real_service")
            if isinstance(candidate_service, C4RealService):
                c4_service = candidate_service
                _render_c4_real_memory_controls(c4_service, c4_scope, c4_scope_key)
                if st.button(
                    "Reset C4 research session",
                    key=f"c4_real_reset::{c4_scope_key}",
                ):
                    ss.c4_real_state_reset_ids[c4_scope_key] = c4_service.reset_session(
                        c4_scope
                    )
                    ss.c4_real_trace_by_scope.pop(c4_scope_key, None)
                    ss.c4_real_memory_disabled_by_scope.pop(c4_scope_key, None)
                    ss.pop(f"c4_real_memory_disabled::{c4_scope_key}", None)
                    clear_scoped_chat_messages(
                        ss.chat_messages_by_scope,
                        chat_scope,
                    )
                    st.rerun()
            else:
                st.info(
                    "C4 research providers are not bound. The selector and controls "
                    "are scaffolded; Track R/Track M integration is a later gate."
                )
            safe_trace = ss.c4_real_trace_by_scope.get(c4_scope_key)
            if safe_trace:
                with st.expander("C4 research trace", expanded=False):
                    st.json(safe_trace)
        if (
            not c4_research_enabled
            and ss.get("group") == "admin"
            and ss.memory_resolution_by_student.get(memory_key)
        ):
            with st.expander("C_FULL routing and memory diagnostics"):
                st.json(ss.memory_resolution_by_student[memory_key])
        if (
            not c4_research_enabled
            and ss.get("group") == "admin"
            and ss.retrieval_details_by_student.get(memory_key)
        ):
            retrieval_panel = ss.retrieval_details_by_student[memory_key]
            with st.expander("Retrieval details"):
                st.json(retrieval_panel.get("safe", {}))
            if retrieval_panel.get("debug_enabled") and retrieval_panel.get("debug"):
                with st.expander("Retrieval developer diagnostics"):
                    st.json(retrieval_panel["debug"])
        if not c4_research_enabled and st.button(
            "Clear this student's session memory and current chat",
            key=f"clear_c_full_memory_{memory_key}_{graph}",
        ):
            clear_student_session_memory(ss.c_full_memory_by_student, memory_key)
            ss.memory_turns_by_student.pop(memory_key, None)
            ss.structured_memory_by_student.pop(memory_key, None)
            ss.memory_resolution_by_student.pop(memory_key, None)
            ss.retrieval_details_by_student.pop(memory_key, None)
            clear_scoped_chat_messages(ss.chat_messages_by_scope, memory_key)
            st.rerun()

        with st.container(height=340, border=True):
            for msg in messages:
                if not msg.get("visible", True): continue
                if msg["role"] not in ["user", "assistant"]: continue
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant" and msg.get("course_sources"):
                        st.caption("Sources used:")
                        for source in msg["course_sources"]:
                            st.markdown(f"- {source}")

        prompt = st.chat_input("Type your message")
        if prompt:
            prior_messages = list(messages)
            messages.append({"role": "user", "content": prompt, "page": graph})
            if not c4_research_enabled:
                add_to_chat_history("user", prompt, graph)

            if c4_research_enabled:
                if c4_service is None:
                    reply = (
                        "C4 research orchestration is not available until the "
                        "mock/integration providers are explicitly bound."
                    )
                else:
                    c4_request = build_streamlit_c4_request(
                        request_id=str(uuid.uuid4()),
                        scenario_id=f"STREAMLIT::{memory_key}",
                        mode=c4_mode,
                        current_query=prompt,
                        current_page=graph,
                        dashboard_context=load_c_full_dashboard_data(),
                        messages=prior_messages,
                        student_id=_current_student_id(),
                        session_id=memory_key,
                        state_reset_id=c4_reset_id,
                    )
                    c4_result = run_streamlit_c4_turn(c4_service, c4_request)
                    reply = streamlit_reply(c4_result)
                    ss.c4_real_trace_by_scope[c4_scope_key] = (
                        c4_result.trace.safe_panel()
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": reply,
                        "page": graph,
                    }
                )
                try:
                    st.rerun(scope="fragment")
                except TypeError:
                    st.rerun()
                return

            memory_turns = ss.memory_turns_by_student.setdefault(memory_key, [])
            try:
                live_backend, allow_v1_fallback, retrieval_debug, retrieval_context = (
                    _streamlit_c_full_retrieval_settings()
                )
            except ValueError as config_error:
                reply = f"C_FULL retrieval configuration error: {config_error}"
                st.error(reply)
                messages.append({"role": "assistant", "content": reply, "page": graph})
                add_to_chat_history("assistant", reply, graph)
                return
            chat_outcome = generate_c_full_chat_turn(
                student_query=prompt,
                student_id=_current_student_id(),
                current_page=graph,
                conversation_history=memory_turns,
                existing_session_memory=ss.c_full_memory_by_student.get(memory_key),
                dashboard_data=load_c_full_dashboard_data(),
                openai_client=openai.Client(api_key=st.secrets["openai_api_key"]),
                model="gpt-4o-mini",
                retrieval_backend=live_backend,
                retrieval_context=retrieval_context,
                allow_retrieval_v1_fallback=allow_v1_fallback,
            )
            reply = chat_outcome.response
            if chat_outcome.succeeded:
                c_full_result = chat_outcome.runtime_result
                assert c_full_result is not None
                ss.memory_resolution_by_student[memory_key] = {
                    "original_query": c_full_result.original_query,
                    "resolved_query": c_full_result.resolved_query,
                    "effective_query": c_full_result.effective_query,
                    "query_type": c_full_result.query_type,
                    "intent_routing": c_full_result.context.get("intent_routing", {}),
                    "selected_route": c_full_result.selected_route,
                    "source_scope": c_full_result.context.get("source_scope", ""),
                    "source_scope_reason": c_full_result.context.get("source_scope_reason", ""),
                    **c_full_result.memory_metadata,
                    "selected_evidence_sources": c_full_result.selected_evidence_sources,
                    "retrieval_used": c_full_result.retrieval_used,
                    "retrieval_requested": c_full_result.context.get("retrieval_requested", False),
                    "retrieved_chunk_titles": c_full_result.retrieved_chunk_titles,
                    "retrieval_query": c_full_result.context.get("retrieval_query", ""),
                    "recommendation_plan_used": bool(c_full_result.recommendation_plan),
                    "current_page": c_full_result.context.get("current_page", graph),
                    "explicit_target_domain": c_full_result.context.get("explicit_target_domain", ""),
                    "resolved_target_domain": c_full_result.context.get("resolved_target_domain", ""),
                    "primary_evidence_domain": c_full_result.context.get("primary_evidence_domain", ""),
                    "supplementary_evidence_domains": c_full_result.context.get("supplementary_evidence_domains", []),
                    "allowed_source_types": c_full_result.context.get("allowed_source_types", []),
                    "excluded_source_types": c_full_result.context.get("excluded_source_types", []),
                    "pre_generation_memory_metadata": c_full_result.context.get("pre_generation_memory_metadata", {}),
                    "post_commit_memory_metadata": c_full_result.context.get("post_commit_memory_metadata", {}),
                    "memory_commit": c_full_result.context.get("memory_commit", {}),
                }
                audit = c_full_result.context.get("retrieval_result", {})
                safe_details = c_full_result.context.get("safe_retrieval_details", {})
                debug_details = {}
                if retrieval_debug:
                    debug_details = {
                        "query_plan": audit.get("query_plan", {}),
                        "candidate_diagnostics": audit.get("candidate_diagnostics", {}),
                        "stage_audit": audit.get("stage_audit", {}),
                    }
                ss.retrieval_details_by_student[memory_key] = {
                    "safe": safe_details,
                    "debug_enabled": retrieval_debug,
                    "debug": debug_details,
                }
                ss.c_full_memory_by_student[memory_key] = chat_outcome.structured_memory
                ss.memory_turns_by_student[memory_key] = chat_outcome.memory_turns
                # Compatibility mirror for existing inspection/debug code; C_FULL
                # generation reads only c_full_memory_by_student.
                ss.structured_memory_by_student[memory_key] = chat_outcome.structured_memory
            source_display = (
                chat_outcome.runtime_result.context.get("source_display", [])
                if chat_outcome.succeeded and chat_outcome.runtime_result is not None
                else []
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": reply,
                    "course_sources": source_display,
                    "page": graph,
                }
            )
            add_to_chat_history("assistant", reply, graph)

            try:
                st.rerun(scope="fragment")
            except TypeError:
                st.rerun()

    # ---------- popover ----------
    with st.popover("🤖 Chat with GenAI Assistant!"):
        _chat_body()


def ai_assistant(graph, visual_info, df, description, df2=None):
    ss = st.session_state
    chat_scope = _chat_scope_key(graph)
    messages = scoped_chat_messages(ss.chat_messages_by_scope, chat_scope)
    need_seed = not messages
    if need_seed:
        pdf_snip = get_pdf_snippet(graph)
        # 1) system + few-shot + word limit
        messages.append({
            "role": "system",
            "content": ("""
                As a genAI assistant embedded in a learning analytics dashboard, your job is to help students understand their data, interpret visuals, and plan next steps to improve their learning.  
                You can interpret uploaded data used to create visuals and provide specific, relevant, and helpful feedback.  
                Your role:  
                    - Provide explanations of student data and its analysis clearly, in simple language.  
                    - Offer personalised advice based on students' data trends.  
                    - Guide students to Moodle with {pdf_snip} when required, not always. 
                    - Ask one small clarification question if the prompt is missing clear instructions; never guess. 
                    - Never describe a percentage as a "completion rate" or "perfect completion" unless the supplied context explicitly defines that calculation. State the metric name and denominator instead. 
                    - Remind and motivate students to engage with module activities.  
                    - Engagement partner which promotes human-like dialogue, understands students’ emotional reactions to feedback, and helps regulate their learning processes. 
                    - End your response with a question to the student about behavioural change, next steps or engagement with the dashboard and Moodle.  
                    You are talking to a student, so always respond in a supportive and informative manner, focusing on enhancing the student's learning experience. Be professional but avoid jargon and formalism.  """),
            "visible": False,
            "page": graph,
        })
        messages.append({"role": "system", "content": get_few_shot(graph), "visible": False, "page": graph})
        messages.append({"role": "system", "content": "Limit the response to 100 words or fewer.", "visible": False, "page": graph})

        if pdf_snip: messages.append(
            {"role": "system", "content": f"\n\nMoodle_links info:\n{pdf_snip}", "visible": False, "page": graph})

        # 2) visual context
        visual_msg = f"Context: {visual_info}\n\nDescription: {description}\n\nData:\n{df}"
        if df2 is not None:
            visual_msg += f"\n\nData (2):\n{df2}"
        messages.append({"role": "system", "content": visual_msg, "visible": False, "page": graph})
        ss.opener = NEUTRAL_CHAT_OPENER
        ss.graph = graph
        messages.append({
            "role": "assistant",
            "content": f"{ss.opener}", "visible": True, "page": graph})

    show_chat_box(graph)


if "login_state" not in st.session_state:
    st.session_state.login_state = False
if "selected_network" not in st.session_state:
    st.session_state.selected_network = 'Replying'
if "selected_student" not in st.session_state:
    st.session_state.selected_student = student_info.loc[0, 'AppName']
if st.session_state.login_state:
    fb.log('see_ind_feedback_page')  # every rerun
    if st.session_state.group == 'admin':
        st.sidebar.selectbox('Student', student_info['AppName'], key='selected_student')  # unhide
    else:  # for students
        st.session_state.selected_student = st.session_state.name
        #row = student_info.loc[st.session_state.selected_student]
        match = student_info.loc[student_info["AppName"] == st.session_state.name]
        row = match.iloc[0]
        srl = int(row["srl"])
        engagement = int(row["engagement"])
        name = st.session_state.name

        
        show_dialog_student = f"show_dialog_student_{name}"
        # --- group-specific messages ---
        def copy_for_group(srl_val, eng_val, nm):
            if srl_val == 1 and eng_val == 1:
                
                title= "Explore what’s shaping your progress 📊"
                line= (f"Hello **{nm}**,\n\n"  
                    "Your consistent engagement with learning analytics feedback shows strong self-regulation skills. Very well done! A possible next step could be looking how your study strategies relate to the outcomes you’re seeing and identify which approaches work best for you.\n\n"  
                    "You can have an interactive discussion with the GenAI assistant on each page. Engaging in this dialogue can help you negotiate meaning, explain your reasoning, and uncover deeper learning patterns.")
                btn= "Further Discuss with GenAI Assistant🤖"
            elif srl_val == 1 and eng_val == 0:
                title= "Review your latest learning analytics feedback 📊 "
                line= (f"Hello **{nm}**,\n\n"  
                    "You have shown high self-regulation in your studies, capable of devising your own learning strategies. However, we noticed that you haven’t engaged much with your analytics feedback.\n\n"  
                    "The feedback was meant to help you monitor your progress based on data and reflect on it to confirm that your perception aligns with your actual behaviours and whether your strategies align with your goals.\n\n"  
                    "You can also have an interactive discussion with the GenAI assistant on each page. Engaging in this dialogue can help you negotiate meaning, explain your reasoning, and uncover deeper learning patterns.")
                btn= "Chat with GenAI Assistant 🤖"
            elif srl_val == 0 and eng_val == 1:
                title= "Turn your learning analytics feedback into actions 📊"
                line= (f"Hello **{nm}**,\n\n"  
                    "You’ve been engaging with learning analytics feedback actively. Well done! A possible next step, if you haven’t already done so, could be turning those insights into actions as highly self-regulated learners tend to. \n\n"  
                    "Your analytics feedback points out the patterns and what’s working best; now you can reflect on them and use to set a clear goal for your next steps for the second half of the term.?\n\n"  
                    "If you’d like, you can interact with the GenAI assistant to further discuss your feedback and organize those insights into a plan that fits your schedule. ")
                btn= "Plan your next steps with GenAI Assistant🤖"
            else: 
                title="Your learning analytics feedback is ready 📊"
                line= (f"Hello **{nm}**, \n\n"  
                    "Your recent activity suggests that you haven’t have much chance to engage with the learning analytics feedback.\n\n" 
                    "Our previous studies on students’ engagement with feedback shows that these insights can support your self-regulation skills by helping you track your progress, plan next steps, and adjust your learning strategies more effectively (Uzun et al., 2025; Suraworachet et al., 2021).\n\n"  
                    "The GenAI assistant can also answer any questions you may have regarding the analytics feedback as well as identify patterns and areas requiring attention and recommend next steps for the second half of the term.")
                btn= "Go through the pages now 🤖"
            return title, line, btn
        title, line, btn = copy_for_group(srl, engagement, name)
        st.session_state.setdefault(show_dialog_student, True)
        
        if st.session_state[show_dialog_student] and hasattr(st, "dialog"):
            @st.dialog(title)
            def student_dialog():
                st.markdown(line)
                if st.button(btn, key="close_popup_btn"):
                    # flip flag and force a rerun so the dialog isn't rendered again
                    fb.log("popupclose")
                    st.session_state[show_dialog_student] = False
                    st.rerun()
        
            #student_dialog()
    c1, c2 = st.columns([3, 0.3])
    with c2:
        st.button("Log out", on_click=log_out, key="logout_btn")
    # with c1:
    st.header("Individual Engagement")
    pull_feedback()
else:
    st.warning('↖️ Please go to the **Home** page at the top left to log in.')
