"""
Fitness Coach Agent — Streamlit entrypoint.

Run with:  streamlit run streamlit_app.py

Uses st.navigation() (stable Streamlit API) to explicitly wire up the
sidebar navigation, rather than relying on implicit pages/ auto-discovery —
this guarantees Chat / Body Stats / Nutrition always appear, regardless of
sidebar content ordering or st.stop() calls on any individual page.
"""

import streamlit as st

st.set_page_config(page_title="Fitness Coach", page_icon="💪", layout="wide")

chat_page = st.Page("page_chat.py", title="Chat", icon="💬", default=True)
body_page = st.Page("pages/1_Body_Stats.py", title="Body Stats", icon="📏")
nutrition_page = st.Page("pages/2_Nutrition.py", title="Nutrition", icon="🍽️")

nav = st.navigation([chat_page, body_page, nutrition_page])
nav.run()
