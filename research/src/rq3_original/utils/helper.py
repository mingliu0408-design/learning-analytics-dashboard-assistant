#calculation, session-related functions
from collections.abc import Iterable
from datetime import datetime

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta, MO

import utils.firebase_connection as fb
from utils import const as c


@st.cache_data(ttl=3600)
def import_data(path, sheet=None):
    data = pd.DataFrame()
    if path.endswith("csv"):
        data = pd.read_csv(path)
    elif path.endswith("xlsx"):
        if sheet is None:
            data = pd.read_excel(path)
        else:
            data = pd.read_excel(path, sheet_name=sheet)
    elif path.endswith("pkl"):
        data = pd.read_pickle(path)
    return data




# for feedback
student_info = import_data(c.STUDENT_INFO_PATH)
student_features = import_data(c.FEATURES_PATH)
feedback_texts = import_data(c.FEEDBACK_PATH)
moodle_df = import_data(c.MOODLE_PATH)
echo360_df = import_data(c.ECHO_PATH)
gdocs_df = import_data(c.GDOCS_PATH)
gdocs_ts = import_data(c.GDOCS_TS_PATH)
reply_network = import_data(c.REPLY_NETW_PATH)
view_network = import_data(c.VIEW_NETW_PATH)


def get_all_week_range(): #return all list
    num_week = pd.DataFrame(index=pd.date_range(c.START_DAY, periods=len(c.WEEK_STATUS), freq='W-MON'))
    num_week['num'] = c.WEEK_STATUS
    num_week = num_week.reset_index().rename(columns={'index': 'datetime'})
    return num_week


def get_current_week_range():#return list up to the current week
    num_week = pd.DataFrame(index=pd.date_range(c.START_DAY, periods=len(c.WEEK_STATUS), freq='W-MON'))
    num_week['num'] = c.WEEK_STATUS
    lastMonday = str(datetime.today().date() + relativedelta(weekday=MO(-1))) + "T00:00:00"
    return num_week.loc[c.START_DAY:lastMonday, 'num']

def get_current_week():
    return get_current_week_range().iloc[-1]


def log_out():
    fb.log('logout')
    st.session_state.clear()
    # st.session_state.user = None
    # st.session_state.login_state = False
    # if 'saved_pre_survey' in st.session_state:
    #     del st.session_state['saved_pre_survey']
    # if 'saved_post_survey' in st.session_state:
    #     del st.session_state['saved_post_survey']
    st.cache_data.clear()
    st.success("You've logged out.")


def flatten(lis):
    for item in lis:
        if isinstance(item, Iterable) and not isinstance(item, str):
            for x in flatten(item):
                yield x
        else:
            yield item


@st.cache_data
def getBlankSurvey():
    blank_survey = {}
    for ind, q in post_questions.iterrows():
        item = 'q' + str(q['No'])
        if (c.MULTI_SELECT_Q == item) or (pd.isna(q['Choice'])):
            blank_survey[item] = ""
        else:
            blank_survey[item] = q['Choice'].split(';')[0]
    return blank_survey


@st.cache_data
def isValidWeek():
    if get_current_week_range().iloc[-1] == 0 or get_current_week_range().iloc[-1] > c.LAST_WEEK_MODULE:
        return False
    else:
        return True

c.CURRENT_WEEK = get_current_week()