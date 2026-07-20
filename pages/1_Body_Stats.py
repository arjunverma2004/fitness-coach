"""Body Stats page — charts weight, height, age, and body fat over time."""

import pandas as pd
import streamlit as st
import backend
from style import inject_styles, page_header, PALETTE

inject_styles()

if "thread_id" not in st.session_state or not st.session_state.thread_id:
    page_header("Body Stats", "No active session")
    st.info("Start or resume a chat session first from the Chat page.")
    st.stop()

thread_id = st.session_state.thread_id
rows = backend.get_body_history(thread_id)

page_header("Tracked Metrics", "Body Stats")

if not rows:
    st.info(
        "No body stats logged yet for this session. Try telling your coach "
        "something like *\"I'm 25 years old, 70kg, 175cm\"* in the chat."
    )
    st.stop()

df = pd.DataFrame(rows)
df["datetime"] = pd.to_datetime(df["datetime"])
df = df.sort_values("datetime")

st.caption(f"{len(df)} logged entries for this session")

CHART_COLORS = [PALETTE["accent"], PALETTE["sage"]]

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Weight (kg)**")
    if df["weight"].notna().any():
        st.line_chart(df.set_index("datetime")["weight"].dropna(), color=PALETTE["accent"])
    else:
        st.caption("No weight data logged yet.")

with col2:
    st.markdown("**Height (cm)**")
    if df["height"].notna().any():
        st.line_chart(df.set_index("datetime")["height"].dropna(), color=PALETTE["sage"])
    else:
        st.caption("No height data logged yet.")

col3, col4 = st.columns(2)

with col3:
    st.markdown("**Body fat (%)**")
    if df["body_fat"].notna().any():
        st.line_chart(df.set_index("datetime")["body_fat"].dropna(), color=PALETTE["accent"])
    else:
        st.caption("No body fat data logged yet.")

with col4:
    st.markdown("**Age**")
    if df["age"].notna().any():
        st.line_chart(df.set_index("datetime")["age"].dropna(), color=PALETTE["sage"])
    else:
        st.caption("No age data logged yet.")

st.divider()
st.markdown('<div class="page-eyebrow">Raw log</div>', unsafe_allow_html=True)
st.dataframe(df.sort_values("datetime", ascending=False), width="stretch", hide_index=True)
