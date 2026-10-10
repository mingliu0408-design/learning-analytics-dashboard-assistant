#database-related functions
import streamlit as st
import pyrebase
from utils import const as c
from datetime import datetime
import pandas as pd

#Use the defined key_path or the Streamlit secret key.
if c.KEY_PATH != "":
    firebaseConfig = {}
    with open(c.KEY_PATH, 'r') as file:
        for line in file:
            key, value = line.strip().split('=')
            firebaseConfig[key] = value
else:
    firebaseConfig = {
        'apiKey': st.secrets['apiKey'],
        'authDomain': st.secrets['authDomain'],
        'projectId': st.secrets['projectId'],
        'databaseURL': st.secrets['databaseURL'],
        'storageBucket': st.secrets['storageBucket'],
        'messagingSenderId': st.secrets['messagingSenderId'],
        'appId': st.secrets['appId'],
        # 'measurementId': st.secrets['measurementId']
    }

# Firebase Authenticaiton
firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()
db = firebase.database()
storage = firebase.storage()


def log(action):
    data = {
        'timestamp': int(datetime.now().timestamp() * 1000),
        'activity': action,
        'id': st.session_state.user['localId']
    }
    db.child('activities').push(data, st.session_state.user['localId'])


def rate(rating, comment):
    data = {
        'timestamp': int(datetime.now().timestamp() * 1000),
        'id': st.session_state.user['localId'],
        'rating': rating,
        'comment': comment
    }
    result = db.child('feedback').push(data, st.session_state.user['localId'])

# @st.cache_data
def getAccount():
    name = db.child('users').child(st.session_state.user['localId']).child("name").get().val()
    group = db.child('users').child(st.session_state.user['localId']).child("group").get().val()
    return name, group


def getSurvey(survey):
    survey_db = db.child(survey).get().val()
    if survey_db is not None:
        surveys = pd.DataFrame.from_dict(survey_db, orient='index')#conv json to df
        surveys = surveys[surveys.id == st.session_state.user['localId']]
        if not surveys.empty:
            # surveys['date'] = surveys['timestamp'].apply(
            #     lambda x: datetime.fromtimestamp(x / 1000))  # this is british time, not utc
            # surveys['week'] = surveys.index.str.split('_').str[1]
            response = pd.json_normalize(surveys.response)
            response['week'] = surveys.index.str.split('_').str[1]
            return response
        else:
            return None


def getDf(branch, id=None):
    db_json = db.child(branch).get().val()
    if db_json is not None:
        df = pd.DataFrame.from_dict(db_json, orient='index')#conv json to df
        if id is None:#return all df
            return None
        else:#query df for id
            df = df[df.id == st.session_state.user['localId']]
            if not df.empty:
                return df
            else:
                return None

