"""Supervisor dashboard UI with the complete recovered LAD research core."""
import streamlit as st

st.set_page_config(page_title='DUTE AI Assistant · LAD', page_icon='👩‍💻', layout='wide', initial_sidebar_state='expanded')
from public_runtime.supervisor_ui import run
run()
