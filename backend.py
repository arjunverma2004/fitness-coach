"""
Fitness Coach Agent — LangGraph backend.

Graph topology:

    START ──► get_body_state ──► coach ──► END
      │
      ├──► save_body_state ──► END
      │
      └──► calories_tracker ──► END

`get_body_state` is sequenced strictly before `coach` so the coach always
sees fresh stats. `save_body_state` and `calories_tracker` run in parallel
since neither depends on the other's output.
"""

import os
import re
import sqlite3
import uuid
import datetime
import getpass
import threading
from typing import TypedDict, Annotated, Optional

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_DIR = os.environ.get("FITNESS_DB_DIR", "/tmp")
DB_PATH = os.path.join(DB_DIR, "body_data.db")
CHECKPOINT_PATH = os.path.join(DB_DIR, "checkpointer.db")
CALORIE_DB_PATH = os.path.join(DB_DIR, "calorie_data.db")
SESSIONS_DB_PATH = os.path.join(DB_DIR, "sessions.db")

MODEL_NAME = os.environ.get("FITNESS_LLM_MODEL", "gemini-3.1-flash-lite")

# Thread IDs become SQLite table names via string formatting (sqlite3 can't
# parameterize identifiers). Whitelist the format so nothing else can be
# smuggled into a CREATE/INSERT/SELECT statement.
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_thread_id(thread_id: str) -> str:
    """Validate a thread_id before it's used as a SQL identifier."""
    if not _THREAD_ID_RE.match(thread_id):
        raise ValueError(
            f"Invalid thread_id {thread_id!r}: must be 1-64 chars of "
            f"letters, numbers, underscore, or hyphen."
        )
    return thread_id


def get_api_key() -> str:
    """Resolve the Gemini API key from env, prompting only in interactive use."""
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    if os.isatty(0):
        key = getpass.getpass("Enter your Gemini API key: ")
        os.environ["GOOGLE_API_KEY"] = key
        return key
    raise RuntimeError(
        "GOOGLE_API_KEY is not set. Add it to your .env file or environment."
    )


# ---------------------------------------------------------------------------
# State schemas
# ---------------------------------------------------------------------------

class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    prev_stats: list
    last_meal: dict


class BodyState(TypedDict):
    weight: Optional[float]
    height: Optional[float]
    age: Optional[int]
    body_fat: Optional[float]


class CalorieState(TypedDict):
    calories: Optional[int]
    protein: Optional[int]
    carbs: Optional[int]
    fat: Optional[int]


# ---------------------------------------------------------------------------
# Resources (LLM, DB connections) — created once at import time
# ---------------------------------------------------------------------------

def build_llm() -> ChatGoogleGenerativeAI:
    get_api_key()
    return ChatGoogleGenerativeAI(model=MODEL_NAME)


def build_connections():
    checkpoint_conn = sqlite3.connect(CHECKPOINT_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn=checkpoint_conn)

    body_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    calorie_conn = sqlite3.connect(CALORIE_DB_PATH, check_same_thread=False)

    sessions_conn = sqlite3.connect(SESSIONS_DB_PATH, check_same_thread=False)
    sessions_cursor = sessions_conn.cursor()
    sessions_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            thread_id STRING PRIMARY KEY,
            name STRING,
            created_at STRING,
            last_active_at STRING
        )
        """
    )
    sessions_conn.commit()

    return checkpointer, body_conn, calorie_conn, sessions_conn


llm = build_llm()
checkpointer, body_conn, calorie_conn, sessions_conn = build_connections()
# NOTE: we intentionally do NOT keep module-level shared cursors here.
# get_body_state / save_body_state / calories_tracker run concurrently as
# parallel LangGraph nodes (see graph topology above), each potentially on
# its own thread. A single shared sqlite3.Cursor object is not safe to use
# from multiple threads at once ("Recursive use of cursors not allowed").
#
# It IS safe to share the underlying Connections across threads (opened with
# check_same_thread=False) as long as access is serialized — SQLite's
# default build is "multi-thread" safe, not "serialized" safe, so two
# threads hitting the same connection at the exact same instant (e.g.
# get_body_state reading body_conn while save_body_state writes it) can
# still raise spurious errors like "Connection object returned NULL without
# setting an exception". A lock per connection avoids that without needing
# a different storage layer.
body_lock = threading.Lock()
calorie_lock = threading.Lock()
sessions_lock = threading.Lock()

COACH_SYSTEM_PROMPT = (
    "You are a helpful, encouraging fitness coach. Give practical, safe "
    "guidance on nutrition and training based on the user's stated goals "
    "and stats. You are not a doctor — for medical concerns, recommend "
    "the user consult one."
)

BODY_PARSE_PROMPT = (
    "You are a precise data extractor, not a conversational assistant. "
    "Look ONLY at the human message below.\n"
    "Extract weight, height, age, and body_fat ONLY if the user explicitly "
    "stated that exact value as a fact about themselves in THIS message.\n"
    "Rules:\n"
    "- If a field is not explicitly stated, you MUST set it to null. "
    "Do not estimate, infer, default to 0, or carry over a value from "
    "earlier conversation.\n"
    "- A message like 'how many calories should I eat?' or 'give me a "
    "workout plan' contains NO body stats — return all fields null.\n"
    "- Only a message like 'I'm 70kg and 175cm' or 'I weigh 154 lbs' "
    "should populate fields.\n"
    "Example 1 -> message: 'What should I eat today?' -> "
    "{weight: null, height: null, age: null, body_fat: null}\n"
    "Example 2 -> message: 'I'm 25 years old, 70kg' -> "
    "{weight: 70, height: null, age: 25, body_fat: null}"
)

CALORIE_PARSE_PROMPT = (
    "You are a precise data extractor, not a conversational assistant. "
    "Look ONLY at the human message below.\n"
    "Extract calories, protein, carbs, and fat ONLY if the user explicitly "
    "described a specific food or meal they ate or are about to eat in "
    "THIS message.\n"
    "Rules:\n"
    "- If no specific food is mentioned, you MUST set every field to null. "
    "Do not estimate a 'typical' meal.\n"
    "- A message like 'how's my progress?' or 'what should I eat for "
    "dinner?' (asking, not stating) contains NO food log — return all "
    "fields null.\n"
    "- Only a message like 'I had 2 eggs and toast' or 'just ate a "
    "chicken salad' should populate fields, with your best nutritional "
    "estimate for that food.\n"
    "Example 1 -> message: 'What should I eat for dinner?' -> "
    "{calories: null, protein: null, carbs: null, fat: null}\n"
    "Example 2 -> message: 'I had 2 eggs and toast for breakfast' -> "
    "{calories: 220, protein: 14, carbs: 18, fat: 11}"
)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def get_body_state(state: ChatState, config: RunnableConfig) -> dict:
    """Load the user's 5 most recent body-stat rows for this thread."""
    thread_id = _safe_thread_id(str(config["configurable"]["thread_id"]))

    with body_lock:
        cur = body_conn.cursor()
        try:
            cur.execute(
                f'SELECT * FROM "{thread_id}" ORDER BY datetime DESC LIMIT 5'
            )
            return {"prev_stats": cur.fetchall()}
        except sqlite3.OperationalError:
            # Table doesn't exist yet for this thread — that's fine, no history.
            return {"prev_stats": []}


def save_body_state(state: ChatState, config: RunnableConfig) -> dict:
    """Extract body stats from the latest message and persist them, if present."""
    structured_model = llm.with_structured_output(BodyState)
    user_input = state["messages"][-1]

    try:
        response = structured_model.invoke(
            [SystemMessage(content=BODY_PARSE_PROMPT), user_input]
        )
    except Exception as e:
        print(f"[save_body_state] extraction failed: {e}")
        return {}

    if not response or not any(
        response.get(k) is not None for k in ("weight", "height", "age", "body_fat")
    ):
        # Nothing useful was extracted — don't write an empty row.
        return {}

    thread_id = _safe_thread_id(str(config["configurable"]["thread_id"]))
    record_id = str(uuid.uuid4())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with body_lock:
        cur = body_conn.cursor()
        cur.execute(
            f'''
            CREATE TABLE IF NOT EXISTS "{thread_id}" (
                id STRING PRIMARY KEY,
                datetime STRING,
                weight FLOAT,
                height FLOAT,
                age INTEGER,
                body_fat FLOAT
            )
            '''
        )
        cur.execute(
            f'''
            INSERT INTO "{thread_id}" (id, datetime, weight, height, age, body_fat)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                record_id,
                now,
                response.get("weight"),
                response.get("height"),
                response.get("age"),
                response.get("body_fat"),
            ),
        )
        body_conn.commit()
    return {}


def calories_tracker(state: ChatState, config: RunnableConfig) -> dict:
    """Extract meal macros from the latest message and persist them, if present."""
    structured_model = llm.with_structured_output(CalorieState)
    user_input = state["messages"][-1]

    try:
        response = structured_model.invoke(
            [SystemMessage(content=CALORIE_PARSE_PROMPT), user_input]
        )
    except Exception as e:
        print(f"[calories_tracker] extraction failed: {e}")
        return {}

    if not response or not any(
        response.get(k) is not None for k in ("calories", "protein", "carbs", "fat")
    ):
        return {}

    thread_id = _safe_thread_id(str(config["configurable"]["thread_id"]))
    record_id = str(uuid.uuid4())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with calorie_lock:
        cur = calorie_conn.cursor()
        cur.execute(
            f'''
            CREATE TABLE IF NOT EXISTS "{thread_id}" (
                id STRING PRIMARY KEY,
                datetime STRING,
                calories INTEGER,
                protein INTEGER,
                carbs INTEGER,
                fat INTEGER
            )
            '''
        )
        cur.execute(
            f'''
            INSERT INTO "{thread_id}" (id, datetime, calories, protein, carbs, fat)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                record_id,
                now,
                response.get("calories"),
                response.get("protein"),
                response.get("carbs"),
                response.get("fat"),
            ),
        )
        calorie_conn.commit()

    last_meal = {
        "calories": response.get("calories"),
        "protein": response.get("protein"),
        "carbs": response.get("carbs"),
        "fat": response.get("fat"),
    }
    return {"last_meal": last_meal}


def coach(state: ChatState) -> dict:
    """Generate the coach's reply, grounded in recent stats and the latest meal."""
    prev_stats = state.get("prev_stats", [])
    last_meal = state.get("last_meal", {})

    context = f"\nUser's recent stats from database: {prev_stats}" if prev_stats else ""
    dynamic_sys_msg = SystemMessage(content=COACH_SYSTEM_PROMPT + context)

    history = list(state["messages"][-10:])
    if last_meal:
        history = history + [HumanMessage(content=f"User's last logged meal: {last_meal}")]

    messages_for_llm = [dynamic_sys_msg] + history
    response = llm.invoke(messages_for_llm)
    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("coach", coach)
    graph.add_node("save_body_state", save_body_state)
    graph.add_node("get_body_state", get_body_state)
    graph.add_node("calories_tracker", calories_tracker)

    graph.add_edge(START, "get_body_state")
    graph.add_edge(START, "save_body_state")
    graph.add_edge(START, "calories_tracker")
    graph.add_edge("get_body_state", "coach")

    graph.add_edge("save_body_state", END)
    graph.add_edge("calories_tracker", END)
    graph.add_edge("coach", END)

    return graph.compile(checkpointer=checkpointer)


chatbot = build_graph()


# ---------------------------------------------------------------------------
# Public helper for the frontend
# ---------------------------------------------------------------------------

def extract_text(ai_message) -> str:
    """
    Safely pull plain text out of an AIMessage, regardless of whether the
    provider returned a plain string or a list of content blocks.
    """
    content = ai_message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
        return "".join(parts) if parts else str(content)
    return str(content)


def send_message(user_text: str, thread_id: str) -> str:
    """One round-trip: send a user message, get the coach's reply as plain text."""
    config = {"configurable": {"thread_id": _safe_thread_id(thread_id)}}
    state_update = {"messages": [HumanMessage(content=user_text)]}
    result = chatbot.invoke(state_update, config=config)
    return extract_text(result["messages"][-1])


def get_body_history(thread_id: str) -> list:
    """Fetch raw body-stat rows for display in the frontend (read-only helper)."""
    thread_id = _safe_thread_id(thread_id)
    with body_lock:
        cur = body_conn.cursor()
        try:
            cur.execute(
                f'SELECT * FROM "{thread_id}" ORDER BY datetime ASC'
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


def get_calorie_history(thread_id: str) -> list:
    """Fetch raw meal-log rows for display in the frontend (read-only helper)."""
    thread_id = _safe_thread_id(thread_id)
    with calorie_lock:
        cur = calorie_conn.cursor()
        try:
            cur.execute(
                f'SELECT * FROM "{thread_id}" ORDER BY datetime ASC'
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


# ---------------------------------------------------------------------------
# Session registry — lets the frontend list / create / resume sessions,
# surviving app restarts (unlike st.session_state, which is wiped on reload).
# ---------------------------------------------------------------------------

def create_session(name: str = "") -> str:
    """Create a new session (thread_id) and register it. Returns the thread_id."""
    thread_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    display_name = name.strip() or f"Session {now}"
    with sessions_lock:
        cur = sessions_conn.cursor()
        cur.execute(
            "INSERT INTO sessions (thread_id, name, created_at, last_active_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, display_name, now, now),
        )
        sessions_conn.commit()
    return thread_id


def list_sessions() -> list:
    """Return all known sessions, most recently active first."""
    with sessions_lock:
        cur = sessions_conn.cursor()
        cur.execute(
            "SELECT thread_id, name, created_at, last_active_at FROM sessions "
            "ORDER BY last_active_at DESC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def touch_session(thread_id: str) -> None:
    """Update a session's last_active_at timestamp."""
    thread_id = _safe_thread_id(thread_id)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sessions_lock:
        cur = sessions_conn.cursor()
        cur.execute(
            "UPDATE sessions SET last_active_at = ? WHERE thread_id = ?",
            (now, thread_id),
        )
        sessions_conn.commit()


def rename_session(thread_id: str, new_name: str) -> None:
    thread_id = _safe_thread_id(thread_id)
    with sessions_lock:
        cur = sessions_conn.cursor()
        cur.execute(
            "UPDATE sessions SET name = ? WHERE thread_id = ?",
            (new_name.strip(), thread_id),
        )
        sessions_conn.commit()


def delete_session(thread_id: str) -> None:
    """Remove a session from the registry and drop its associated data."""
    thread_id = _safe_thread_id(thread_id)
    with sessions_lock:
        sessions_cur = sessions_conn.cursor()
        sessions_cur.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
        sessions_conn.commit()
    with body_lock:
        try:
            body_conn.cursor().execute(f'DROP TABLE IF EXISTS "{thread_id}"')
            body_conn.commit()
        except sqlite3.OperationalError:
            pass
    with calorie_lock:
        try:
            calorie_conn.cursor().execute(f'DROP TABLE IF EXISTS "{thread_id}"')
            calorie_conn.commit()
        except sqlite3.OperationalError:
            pass
    # Drop LangGraph checkpoints for this thread via the checkpointer's own
    # API, rather than reaching into its internal table schema directly.
    try:
        checkpointer.delete_thread(thread_id)
    except Exception as e:
        print(f"[delete_session] failed to delete checkpoint thread: {e}")


def get_chat_history(thread_id: str) -> list:
    """
    Return the full message history for a thread as a list of
    {"role": "user"|"assistant", "content": str} dicts, for rendering
    in the UI when resuming a session.
    """
    thread_id = _safe_thread_id(thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = chatbot.get_state(config)
    except Exception:
        return []
    if not state or not state.values:
        return []
    messages = state.values.get("messages", [])
    history = []
    for m in messages:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        history.append({"role": role, "content": extract_text(m)})
    return history


def edit_message_and_regenerate(thread_id: str, message_index: int, new_text: str) -> str:
    """
    Edit a past user message and regenerate the conversation from that point
    forward, discarding everything after it (including the coach's old
    reply). Returns the new assistant reply.

    message_index is the index into the *human* messages only (0 = first
    user message), matching what the UI shows as editable bubbles.
    """
    thread_id = _safe_thread_id(thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    state = chatbot.get_state(config)
    if not state or not state.values:
        # Nothing to edit yet — just send it as a new message.
        return send_message(new_text, thread_id)

    messages = state.values.get("messages", [])
    human_indices = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if message_index >= len(human_indices):
        return send_message(new_text, thread_id)

    cutoff = human_indices[message_index]
    # Everything from the edited message onward gets removed via the
    # add_messages reducer's RemoveMessage support (plain list slicing does
    # NOT work here, since add_messages only knows how to append or remove
    # by id, never to replace the whole list).
    to_remove = messages[cutoff:]
    ids_to_remove = [m.id for m in to_remove if getattr(m, "id", None)]

    if ids_to_remove:
        chatbot.update_state(
            config, {"messages": [RemoveMessage(id=mid) for mid in ids_to_remove]}
        )
        # Verify removal actually took effect (RemoveMessage has known
        # flakiness in some langgraph versions) before trusting it.
        post_state = chatbot.get_state(config)
        remaining = post_state.values.get("messages", []) if post_state else []
        if len(remaining) > cutoff:
            raise RuntimeError(
                "Failed to remove old messages from checkpoint state; "
                "the conversation thread may need to be reset to recover."
            )

    return send_message(new_text, thread_id)


# ---------------------------------------------------------------------------
# CLI entry point (kept for quick terminal testing, mirrors the old notebook loop)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Fitness Coach Agent (CLI mode). Type 'exit' or 'quit' to stop.")
    cli_thread_id = "cli-session"
    while True:
        user_input = input("User: ")
        if user_input.strip().lower() in ("exit", "quit"):
            print("Exiting the chatbot. Goodbye!")
            break
        try:
            reply = send_message(user_input, cli_thread_id)
            print("Chatbot:", reply)
        except Exception as e:
            print(f"[error] {e}")
