"""Chat page — session picker (sidebar) + editable conversation with the coach."""

import streamlit as st
import backend
from style import inject_styles, page_header, PALETTE

inject_styles()

# ---------------------------------------------------------------------------
# Session selection — persisted in SQLite (backend.sessions table), so it
# survives app restarts. st.session_state only tracks *which* persisted
# session is currently active in this browser tab.
# ---------------------------------------------------------------------------

if "thread_id" not in st.session_state:
    st.session_state.thread_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "editing_index" not in st.session_state:
    st.session_state.editing_index = None  # which human-message index is being edited


def _load_chat_into_session(thread_id: str) -> None:
    st.session_state.thread_id = thread_id
    st.session_state.messages = backend.get_chat_history(thread_id)
    st.session_state._loaded_thread_id = thread_id
    st.session_state.editing_index = None
    backend.touch_session(thread_id)


with st.sidebar:
    st.markdown(
        f"""
        <div style="padding: 0.4rem 0 1rem 0;">
            <div style="font-family:'Bebas Neue',sans-serif; font-size:1.6rem;
                        letter-spacing:0.05em; color:{PALETTE['text']};">
                💪 FITNESS COACH
            </div>
            <div style="font-family:'JetBrains Mono',monospace; font-size:0.7rem;
                        color:{PALETTE['text_muted']};">
                your sessions, logged
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("➕  Start new chat", width="stretch", type="primary"):
        new_id = backend.create_session()
        _load_chat_into_session(new_id)
        st.rerun()

    sessions = backend.list_sessions()

    if sessions:
        st.markdown(
            '<div class="page-eyebrow" style="margin-top:0.6rem;">Previous chats</div>',
            unsafe_allow_html=True,
        )
        for s in sessions:
            is_active = s["thread_id"] == st.session_state.thread_id
            card_class = "session-card active" if is_active else "session-card"
            st.markdown(
                f"""
                <div class="{card_class}">
                    <div class="session-name">{s['name']}</div>
                    <div class="session-meta">last active · {s['last_active_at']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not is_active:
                if st.button("Resume", key=f"resume_{s['thread_id']}", width="stretch"):
                    _load_chat_into_session(s["thread_id"])
                    st.rerun()

        if st.session_state.thread_id:
            with st.expander("Manage current session"):
                current_name = next(
                    (s["name"] for s in sessions if s["thread_id"] == st.session_state.thread_id),
                    "",
                )
                new_name = st.text_input("Rename session", value=current_name)
                col1, col2 = st.columns(2)
                if col1.button("Save name", width="stretch"):
                    backend.rename_session(st.session_state.thread_id, new_name)
                    st.rerun()
                if col2.button("🗑️ Delete", width="stretch"):
                    backend.delete_session(st.session_state.thread_id)
                    st.session_state.thread_id = None
                    st.session_state.messages = []
                    st.rerun()
    else:
        st.caption("No sessions yet — start a new chat to begin.")

# ---------------------------------------------------------------------------
# No session selected yet -> landing state
# ---------------------------------------------------------------------------

if not st.session_state.thread_id:
    page_header("Get Started", "Welcome to your Fitness Coach")
    st.write(
        "Start a new chat or resume a previous session from the sidebar — "
        "your stats and meal logs are saved between visits."
    )
    st.stop()

# Guard against thread_id being set without a matching messages load (e.g.
# state set programmatically rather than through _load_chat_into_session).
if st.session_state.get("_loaded_thread_id") != st.session_state.thread_id:
    st.session_state.messages = backend.get_chat_history(st.session_state.thread_id)
    st.session_state._loaded_thread_id = st.session_state.thread_id

# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------

page_header("Live Session", "Chat with your coach")

for i, msg in enumerate(st.session_state.messages):
    human_idx = sum(
        1 for m in st.session_state.messages[:i] if m["role"] == "user"
    )  # 0-based index among user messages, used for editing

    with st.chat_message(msg["role"]):
        if msg["role"] == "user" and st.session_state.editing_index == human_idx:
            edited_text = st.text_area(
                "Edit message", value=msg["content"], key=f"edit_box_{i}", label_visibility="collapsed"
            )
            col1, col2 = st.columns([1, 1])
            if col1.button("Save & regenerate", key=f"save_{i}", type="primary"):
                with st.spinner("Regenerating response..."):
                    try:
                        backend.edit_message_and_regenerate(
                            st.session_state.thread_id, human_idx, edited_text
                        )
                        st.session_state.messages = backend.get_chat_history(
                            st.session_state.thread_id
                        )
                        st.session_state.editing_index = None
                    except Exception as e:
                        st.error(f"Couldn't regenerate: {e}")
                st.rerun()
            if col2.button("Cancel", key=f"cancel_{i}"):
                st.session_state.editing_index = None
                st.rerun()
        else:
            st.markdown(msg["content"])
            if msg["role"] == "user":
                if st.button("✏️ Edit", key=f"edit_btn_{i}"):
                    st.session_state.editing_index = human_idx
                    st.rerun()

user_input = st.chat_input("Tell your coach how you're doing, what you ate, or ask for advice...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                reply = backend.send_message(user_input, st.session_state.thread_id)
            except Exception as e:
                reply = f"Sorry, something went wrong: {e}"
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    backend.touch_session(st.session_state.thread_id)
    st.rerun()
