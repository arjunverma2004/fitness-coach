"""Nutrition page — charts calories, protein, carbs, and fat over time."""

import pandas as pd
import streamlit as st
import backend
from style import inject_styles, page_header, PALETTE

inject_styles()

if "thread_id" not in st.session_state or not st.session_state.thread_id:
    page_header("Nutrition", "No active session")
    st.info("Start or resume a chat session first from the Chat page.")
    st.stop()

thread_id = st.session_state.thread_id
rows = backend.get_calorie_history(thread_id)

page_header("Fuel Log", "Nutrition")

if not rows:
    st.info(
        "No meals logged yet for this session. Try telling your coach "
        "something like *\"I had 2 eggs and toast for breakfast\"* in the chat."
    )
    st.stop()

df = pd.DataFrame(rows)
df["datetime"] = pd.to_datetime(df["datetime"])
df = df.sort_values("datetime")

st.caption(f"{len(df)} logged meals for this session")

# --- Daily totals (most useful view for a fitness coach context) ---
df["date"] = df["datetime"].dt.date
daily = df.groupby("date")[["calories", "protein", "carbs", "fat"]].sum(min_count=1)

st.markdown('<div class="page-eyebrow">Daily totals</div>', unsafe_allow_html=True)
col1, col2 = st.columns(2)

with col1:
    st.markdown("**Calories per day**")
    if daily["calories"].notna().any():
        st.bar_chart(daily["calories"].dropna(), color=PALETTE["accent"])
    else:
        st.caption("No calorie data logged yet.")

with col2:
    macro_cols = [c for c in ["protein", "carbs", "fat"] if daily[c].notna().any()]
    if macro_cols:
        st.markdown("**Macros per day (g)**")
        st.bar_chart(
            daily[macro_cols].dropna(how="all"),
            color=[PALETTE["accent"], PALETTE["sage"], PALETTE["text_muted"]][: len(macro_cols)],
        )
    else:
        st.caption("No macro data logged yet.")

st.divider()

st.markdown('<div class="page-eyebrow">Per-meal detail</div>', unsafe_allow_html=True)
col3, col4 = st.columns(2)

with col3:
    st.markdown("**Calories per meal**")
    if df["calories"].notna().any():
        st.line_chart(df.set_index("datetime")["calories"].dropna(), color=PALETTE["accent"])
    else:
        st.caption("No calorie data logged yet.")

with col4:
    macro_cols = [c for c in ["protein", "carbs", "fat"] if df[c].notna().any()]
    if macro_cols:
        st.markdown("**Protein / Carbs / Fat per meal (g)**")
        st.line_chart(
            df.set_index("datetime")[macro_cols].dropna(how="all"),
            color=[PALETTE["accent"], PALETTE["sage"], PALETTE["text_muted"]][: len(macro_cols)],
        )
    else:
        st.caption("No macro data logged yet.")

st.divider()
st.markdown('<div class="page-eyebrow">Raw log</div>', unsafe_allow_html=True)
st.dataframe(
    df.drop(columns=["date"]).sort_values("datetime", ascending=False),
    width="stretch",
    hide_index=True,
)
