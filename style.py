"""
Shared visual styling for the Fitness Coach app.

Import and call `inject_styles()` once at the top of every page, then use
`page_header()` for the title treatment (the animated "effort bar" is the
app's signature element).
"""

import streamlit as st

PALETTE = {
    "bg": "#1A2420",
    "surface": "#222E28",
    "surface_raised": "#2A372F",
    "text": "#F5F2EB",
    "text_muted": "#A8998A",
    "accent": "#FF6B35",
    "accent_soft": "#FF6B3522",
    "sage": "#7C9885",
    "border": "#34423A",
}

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

/* ---- App background ---- */
.stApp {{
    background: {PALETTE['bg']};
}}

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {{
    background: {PALETTE['surface']};
    border-right: 1px solid {PALETTE['border']};
}}
section[data-testid="stSidebar"] .stRadio label {{
    font-family: 'Inter', sans-serif;
}}

/* ---- Headings use the display face ---- */
h1, h2, h3 {{
    font-family: 'Bebas Neue', 'Inter', sans-serif;
    letter-spacing: 0.04em;
    color: {PALETTE['text']};
}}
h1 {{ font-size: 2.6rem !important; }}

/* ---- Signature element: animated effort bar ---- */
.effort-bar-wrap {{
    width: 100%;
    height: 4px;
    background: {PALETTE['border']};
    border-radius: 2px;
    overflow: hidden;
    margin: -0.4rem 0 1.6rem 0;
    position: relative;
}}
.effort-bar {{
    position: absolute;
    top: 0; left: 0; bottom: 0;
    width: 40%;
    background: linear-gradient(90deg, transparent, {PALETTE['accent']}, {PALETTE['sage']}, transparent);
    animation: effort-pulse 2.6s ease-in-out infinite;
    border-radius: 2px;
}}
@keyframes effort-pulse {{
    0%   {{ left: -40%; }}
    100% {{ left: 100%; }}
}}
@media (prefers-reduced-motion: reduce) {{
    .effort-bar {{ animation: none; left: 0; width: 100%; opacity: 0.5; }}
}}

/* ---- Eyebrow label above page titles ---- */
.page-eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: {PALETTE['accent']};
    margin-bottom: 0.2rem;
}}

/* ---- Chat bubbles: quiet, left-accent style instead of filled bubbles ---- */
div[data-testid="stChatMessage"] {{
    background: {PALETTE['surface']};
    border-left: 3px solid {PALETTE['border']};
    border-radius: 6px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.6rem;
}}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {{
    border-left-color: {PALETTE['accent']};
}}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) {{
    border-left-color: {PALETTE['sage']};
}}

/* ---- Buttons ---- */
.stButton > button {{
    background: {PALETTE['surface_raised']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    font-weight: 500;
    transition: border-color 0.15s ease, color 0.15s ease;
}}
.stButton > button:hover {{
    border-color: {PALETTE['accent']};
    color: {PALETTE['accent']};
}}
.stButton > button:focus-visible {{
    outline: 2px solid {PALETTE['accent']};
    outline-offset: 2px;
}}

/* Primary-style buttons (Start new chat, Save) get the accent fill */
.stButton > button[kind="primary"] {{
    background: {PALETTE['accent']};
    color: {PALETTE['bg']};
    border: none;
}}
.stButton > button[kind="primary"]:hover {{
    background: #ff7f52;
    color: {PALETTE['bg']};
}}

/* ---- Session cards in sidebar ---- */
.session-card {{
    background: {PALETTE['surface_raised']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    margin-bottom: 0.5rem;
}}
.session-card.active {{
    border-color: {PALETTE['accent']};
    background: {PALETTE['accent_soft']};
}}
.session-name {{
    font-weight: 600;
    font-size: 0.92rem;
    color: {PALETTE['text']};
}}
.session-meta {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: {PALETTE['text_muted']};
}}

/* ---- Metric-style numbers (data feel) ---- */
[data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace;
    color: {PALETTE['accent']};
}}

/* ---- Dataframes ---- */
[data-testid="stDataFrame"] {{
    font-family: 'JetBrains Mono', monospace;
}}

/* ---- Captions / muted text ---- */
.stCaption, [data-testid="stCaptionContainer"] {{
    color: {PALETTE['text_muted']} !important;
}}
</style>
"""


def inject_styles() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(eyebrow: str, title: str) -> None:
    """Render the app's signature title treatment: eyebrow + title + pulsing effort bar."""
    st.markdown(f'<div class="page-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.markdown(f"# {title}")
    st.markdown(
        '<div class="effort-bar-wrap"><div class="effort-bar"></div></div>',
        unsafe_allow_html=True,
    )
