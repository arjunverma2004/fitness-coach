# Fitness Coach Agent

A LangGraph-powered fitness coach that chats with you, extracts and tracks
your body stats and meals in the background, grounds its advice in your
logged history, and lets you browse that history as charts — backed by a
multi-page, custom-themed Streamlit UI.

## Project structure

```
streamlit_app.py         Entrypoint / router (st.navigation + theme setup)
page_chat.py              Chat UI: session picker, editable conversation
style.py                  Shared design tokens, CSS, signature header component
backend.py                 LangGraph graph, DB access, session registry
pages/
  1_Body_Stats.py           Weight / height / age / body-fat charts
  2_Nutrition.py             Calories / protein / carbs / fat charts
.streamlit/config.toml     Dark theme base (charcoal-green + ember accent)
requirements.txt
.env.example
```

Run `streamlit run streamlit_app.py` — **not** any file inside `pages/`
directly, since navigation, theming, and page config are all wired up in
the entrypoint.

## Architecture

```
                ┌──────────────────┐
                │       START       │
                └─────────┬─────────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
   get_body_state    save_body_state   calories_tracker
           │               │               │
           ▼               ▼               ▼
        coach             END             END
           │
           ▼
          END
```

- **`get_body_state`** — loads the user's 5 most recent body-stat rows for
  this conversation thread, before the coach responds.
- **`save_body_state`** — uses structured LLM output to extract
  weight/height/age/body-fat from the latest message **only if the user
  explicitly stated it**; logs nothing otherwise.
- **`calories_tracker`** — same idea, but extracts meal macros
  (calories/protein/carbs/fat).
- **`coach`** — generates the actual reply, with recent stats and the last
  logged meal injected as context.

`get_body_state → coach` is a strict dependency so the coach always sees
fresh data. `save_body_state` and `calories_tracker` run **in parallel**
since neither depends on the other — this is also why each function opens
its own short-lived SQLite cursor rather than sharing one (see "Notes on
fixes" below).

## Navigation

The app uses Streamlit's explicit `st.navigation()` / `st.Page()` API
(stable since Streamlit 1.36) rather than relying on the implicit
`pages/` auto-discovery convention. `streamlit_app.py` is the router:
it declares the three pages (Chat, Body Stats, Nutrition) and renders
whichever one is active. This guarantees the sidebar nav always appears,
regardless of what an individual page does (e.g. an early `st.stop()`).

## Sessions (chats that survive restarts)

Sessions are **not** stored in `st.session_state` (which Streamlit wipes on
every restart) — they're registered in a `sessions` table in SQLite, keyed
by `thread_id`. The sidebar lists every past session as a card and lets you:

- start a new chat
- resume any previous one (full message history, stats, and meal log reload)
- rename or delete a session

Each session's conversation is independently checkpointed by LangGraph's
`SqliteSaver`, and its body-stat / meal-log rows live in their own SQL
tables, named after the `thread_id`.

## Editing messages

Click **✏️ Edit** under any of your past messages to revise it. Saving:

1. Removes that message and everything after it from the LangGraph
   checkpoint (via `RemoveMessage`, the only reliable way to mutate a
   list-typed state channel that uses the `add_messages` reducer — plain
   slicing/reassignment does not work because that reducer only knows how
   to append or remove-by-id).
2. Re-submits your edited text as a new turn, regenerating the coach's
   reply from there.

## Visualization pages

- **Body Stats** — line charts for weight, height, age, body fat, plus the
  raw log table.
- **Nutrition** — daily calorie/macro totals (bar charts) and per-meal
  detail (line charts), plus the raw log table.

Both read from the currently active session, so switch sessions on the
Chat page first if you want to see a different session's charts.

## Design

Dark, athletic-but-editorial theme: charcoal-green background, a single
ember-orange accent, condensed display type (Bebas Neue) for headers,
Inter for body text, and JetBrains Mono for logged data. The signature
element is a thin animated "effort bar" beneath every page title. Theme
base colors live in `.streamlit/config.toml`; all custom CSS and the
header component live in `style.py` and are shared across every page via
`inject_styles()` / `page_header()`.

## Setup

```bash
python -m venv venv
source venv/bin/activate          # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env              # then add your GOOGLE_API_KEY
```

## Run

```bash
streamlit run streamlit_app.py
```

**CLI (for quick testing without the UI):**
```bash
python backend.py
```

## Notes on fixes from earlier iterations

- **Navigation fixed**: switched from implicit `pages/` auto-discovery to
  explicit `st.navigation()`, verified with Streamlit's `AppTest` framework
  across all three pages.
- **Cursor concurrency bug fixed**: `save_body_state` and `calories_tracker`
  run in parallel as separate LangGraph nodes (often on separate threads).
  Earlier versions shared one `sqlite3.Cursor` per database at module level,
  which raised `sqlite3.ProgrammingError: Recursive use of cursors not
  allowed` under concurrent access. Every DB-touching function now opens
  its own short-lived cursor against the shared connection.
- **Connection-level race condition fixed**: even with separate cursors,
  two threads hitting the *same* `sqlite3.Connection` at the same instant
  (e.g. `get_body_state` reading while `save_body_state` writes, both part
  of one parallel graph step) could intermittently raise
  `SystemError: <Connection object> returned NULL without setting an
  exception` — a known sharp edge of SQLite's default "multi-thread" (not
  "serialized") build. Each connection now has its own `threading.Lock`,
  and every function that touches that connection acquires the lock first.
  Verified under a 60-operation concurrent stress test across 5 sessions
  with zero failures.
- **Calorie table primary key fixed**: the table used `datetime` (second
  resolution) as its primary key, so two meals logged within the same
  second collided. Switched to a UUID `id` column, matching the body-stats
  table's existing pattern. *(Note: this is a schema change — a
  `calorie_data.db` created by an earlier version of this app will not be
  compatible; delete it and let the app recreate it, or migrate manually.)*
- **Over-logging fixed**: extraction prompts now explicitly instruct the
  model to return `null` for every field unless the user *stated* that
  exact fact in the current message (with few-shot examples), instead of
  loosely "extracting if present."
- **Falsy-value bug fixed**: the empty-row guard previously used
  `if value:`, which silently treated a legitimate `0` or `0.0` (e.g. a low
  body-fat reading) as "no data." It now checks `is not None`.
- **SQL table names** (derived from `thread_id`) are validated against a
  strict whitelist before use, closing a SQL-injection path.
- **Session persistence**: thread IDs are no longer lost on every Streamlit
  rerun/restart — they live in a `sessions` table and can be resumed.
- **`delete_session`** uses the checkpointer's own `delete_thread()` API
  rather than guessing at LangGraph's internal SQLite schema.
