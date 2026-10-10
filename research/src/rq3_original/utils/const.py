
from datetime import datetime

PAGE_TITLE = 'DUTE AI APP ANONYMISED'
PAGE_ICON = "👩‍💻"
KEY_PATH = ""
START_DAY = datetime(2025, 9, 29)  # Monday of the week of week 1
WEEK_STATUS = [1, 2, 3, 4, 5, 0, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]  # week number, use zero to define the reading week(skipped week)
LAST_WEEK_MODULE = 9
NUM_GROUP = 10

#for individual feedback
FEEDBACK_WEEK = 8#for echo content
CONTENT_WEEK_LIST = range(0, FEEDBACK_WEEK+1)#for heatmap
FEEDBACK_WEEK_LABEL_LIST = ['W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'ReadingWeek','W6','W7','W8']#, 'W5', 'ReadingWeek', 'W6', 'W7'] #display texts where mid-semester as RW-reading week
FEEDBACK_WEEK_VAL_LIST = [0, 1, 2, 3, 4, 5,6,7,8,9]#, 3, 4, 5, 6, 7, 8] #actual week
MAPPING_WEEK_TO_TEXT = {0: 'W0', 1: 'W1', 2: 'W2', 3: 'W3', 4: 'W4', 5: 'W5', 6: 'ReadingWeek', 7: 'W6', 8: 'W7', 9: 'W8', 10: 'W9'}
MAPPING_WEEK_TO_CONTENT = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 5, 7: 6, 8: 7, 9:8, 10:9}
CONTAIN_RW = True#whether the feedback period has a reading week


# Identify survey question that is multi select because this will have possible values to be recognised as a blank response but it isn't correct.
# So it was defined manually here of which question is multiselect. However, this can be checked directly from the survey questions.
MULTI_SELECT_Q = 'q10'#to check
POST_PLANS = 'q12'#to check
BG_COLOR = '#636EFA'
GROUP_MEASURE_SURVEY_ITEMS = [0,1,2,9,10] #index in post-survey for showing group reported measures
GROUP_CH_SURVEY_ITEMS = ['q4', 'q5', 'q6', 'q7']#index in post-survey for showing group reported challenges
CH_SURVEY_LIST = ['Behavioural', 'Cognitive', 'Emotional', 'Technical']


# #for group feedback
# FROM_WEEK = 2
# TO_WEEK = 7#depriciate

DAY_LIST = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


STUDENT_INFO_PATH = 'input/student_info.xlsx'


FEATURES_PATH = 'input/features/features.csv'
MOODLE_PATH = 'input/moodle/moodle_logs.csv'
ECHO_PATH = 'input/echo/echo_logs.csv'
GDOCS_PATH = 'input/gdocs/activities.pkl'
GDOCS_TS_PATH = 'input/gdocs/ts_cohorts.csv'
FEEDBACK_PATH = 'input/feedback/feedback_texts.xlsx'

REPLY_NETW_PATH = 'input/debate/reply_network.csv'
VIEW_NETW_PATH = 'input/debate/view_network.csv'
VIDEO_NAME_PATH = 'input/Group Interactions/Video Name matching.xlsx'

MAPPING_LIKERT = {'not at all': 1, 'slightly': 2, 'moderately': 3, 'very': 4, 'extremely': 5}
MAPPING_TO_LIKERT = {1: 'not at all', 2: 'slight', 3: 'moderate', 4: 'very high', 5: 'extreme'}
MAPPING_POST_QUESTIONS = {'q4': "Behavioural",
                          'q5': "Cognitive",
                          'q6': "Emotional",
                          'q7': "Technical"}


d3_scheme_category10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

plotly_default_colors = [
    "#636EFA",  # Blue
    "#EF553B",  # Red
    "#00CC96",  # Green
    "#AB63FA",  # Purple
    "#FFA15A",  # Orange
    "#19D3F3",  # Cyan
    "#FF6692",  # Pink
    "#B6E880",  # Light Green
    "#FF97FF",  # Light Pink
    "#FECB52"   # Yellow
]
