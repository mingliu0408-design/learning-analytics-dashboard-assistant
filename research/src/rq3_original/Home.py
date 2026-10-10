import streamlit as st
# page config needed to be called first.
st.set_page_config(
    page_title='DUTE AI APP ANONYMISED',
    page_icon="👩‍💻",
    layout="wide",
    initial_sidebar_state="expanded"
)
from utils.helper import*
import plotly.graph_objects as go
import requests
import json
import numpy as np


# remove main menu and the footer
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
    """
st.markdown(hide_menu_style, unsafe_allow_html=True)


def convert_df(df):
    # IMPORTANT: Cache the conversion to prevent computation on every rerun
    return df.to_csv(index=False).encode('utf-8')


def pull_goals():
    # fetch post-survey data
    response = fb.getSurvey('post-survey')
    if not(response is None):
        my_data_post = pd.DataFrame()
        my_data_post['Week'] = response.week
        my_data_post['Follow-up plans'] = response[c.POST_PLANS]

    # show data even when their is no submission -> need to check in a reading week case
    if 'my_data_post' not in locals():
        if get_current_week_range().iloc[-1] == 0:
            my_data_post = pd.DataFrame({'Week': [get_current_week_range().iloc[-2]], 'Follow-up plans': ['No data']})
        elif get_current_week_range().iloc[-1] > c.LAST_WEEK_MODULE:
            my_data_post = pd.DataFrame({'Week': [c.LAST_WEEK_MODULE], 'Follow-up plans': ['No data']})
        else:
            my_data_post = pd.DataFrame({'Week': [get_current_week_range().iloc[-1]], 'Follow-up plans': ['No data']})
    #print a table listed goals
    my_data_post['Week'] = my_data_post['Week'].astype(int)
    all_data = my_data_post.fillna("-")
    fig = go.Figure(data=[go.Table(
        columnwidth=[1, 4],
        header=dict(values=all_data.columns,
                    line_color='white',
                    fill_color=c.BG_COLOR,
                    line_width=1,
                    height=35,
                    align='left',
                    font=dict(color='white', size=16)),
        cells=dict(values=[all_data['Week'], all_data['Follow-up plans']],
                   line_color='white',
                   align='left',
                   fill_color='#F0F2F6',
                   height=50,
                   line_width=1,
                   font=dict(color='black', size=14)))])
    fig.update_layout(margin=dict(l=2, r=2, b=2, t=2))
    st.plotly_chart(fig, use_container_width=True)


if "login_state" not in st.session_state:
    st.session_state.login_state = False
if not st.session_state.login_state:
    login_section = st.container().empty()
    with login_section.container(): #display login panel
        st.title(c.PAGE_TITLE)
        st.markdown('## Log in')
        email = st.text_input('Email address')  # no side bar is needed
        password = st.text_input('Password', type='password')
        # reset = st.checkbox('Forget my password', key='reset_password')
        # if reset:
        #     try:
        #         auth.send_password_reset_email(email)
        #         st.info("Email has been sent to: " + email +
        #                 ". Please check your email/junk mail and follow the instruction to reset the password.")
        #         if "ucl.ac.uk" in email:
        #             st.warning("If you couldn't find an email to reset your password, please contact: wannapon.suraworachet.20@ucl.ac.uk to reset the password manually.")
        #     except requests.exceptions.HTTPError as e:
        #         error_json = e.args[1]
        #         error = json.loads(error_json)['error']['message']
        #         if error == "INVALID_EMAIL":
        #             st.error("Email isn't correct. Please input the correct email.")
        login = st.button('Login')


    if login:
        try:
            user = fb.auth.sign_in_with_email_and_password(email, password)
            st.session_state.user = user
            st.session_state.name, st.session_state.group = fb.getAccount()
            # st.session_state.members = len(student_info[student_info.Group == st.session_state.group])
            # st.session_state.id = st.session_state.user['localId']
            fb.log('login')
            login = False
            st.session_state.login_state = True
            login_section.empty()
        except requests.exceptions.HTTPError as e:
            error_json = e.args[1]
            error = json.loads(error_json)['error']['message']
            if error == "EMAIL_NOT_FOUND":
                st.error("Email wasn't found. Please contact the DUTE team (wannapon.suraworachet.20@ucl.ac.uk).")
            elif error == "INVALID_LOGIN_CREDENTIALS":#INVALID_PASSWORD
                st.error("Invalid password. Please enter your UCL email along with the password provided in the email from the DUTE team (wannapon.suraworachet.20@ucl.ac.uk).")

# show info if login successfully
if st.session_state.login_state:
    fb.log('see_homepage')
    c1, c2 = st.columns([3, 0.3])
    with c2:
        st.button("Log out", on_click=log_out, key="logout_btn")
    if st.session_state.group == 'admin':
        st.header('Hello, admin!')

        with st.expander('User info'):
            users_db = fb.db.child('users').get().val()
            users = pd.DataFrame.from_dict(users_db, orient='index')
            st.write(users)
            csv = convert_df(users)
            st.download_button(
                label="⬇ Download user data",
                data=csv,
                file_name='users.csv',
                mime='text/csv')


        with st.expander('Chat history'):
            chat_db = fb.db.child('chathistory').get().val()
            if chat_db:
                chats = pd.DataFrame.from_dict(chat_db, orient='index').reset_index(drop=True)
                chats = chats.merge(users[["id", "name"]], on="id", how="left")
                chats["date"] = chats['timestamp'].apply(lambda x: datetime.fromtimestamp(x / 1000))
                st.write(chats)
                csv = convert_df(chats)
                st.download_button(
                    label="⬇ Download chat data",
                    data=csv,
                    file_name='chats.csv',
                    mime='text/csv')
            else:
                st.write("No chat history")



    else:  # For students
        with c1:
            st.title('My plans')
        if get_current_week_range().iloc[-1] == 0:  # if the latest week is the reading week
            st.subheader("Welcome: " + st.session_state.name + " to the reading week")
        else:
            st.subheader("Welcome: " + st.session_state.name + " to Week " + str(get_current_week_range().iloc[-1]))
        pull_goals()




