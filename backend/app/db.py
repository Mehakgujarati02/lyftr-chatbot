"""SQLite storage for session history."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

_db_path: str | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,          -- 'user' or 'assistant'
    content     TEXT NOT NULL,
    metadata    TEXT,                   -- JSON string, assistant messages only
    created_at  TEXT NOT NULL           -- server time, ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);
"""


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    if _db_path is None:
        raise RuntimeError("database not initialised")
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ping() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_history(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        if r["metadata"]:
            item["metadata"] = json.loads(r["metadata"])
        out.append(item)
    return out


def get_system_prompt(session_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row["system_prompt"] if row else None


def save_exchange(session_id: str, user_msg: str, reply: str, metadata: dict, system_prompt: str | None) -> None:
    """Persist a successful user/assistant turn atomically (failed requests are never stored)."""
    now = _now()
    with connect() as conn:
        if system_prompt is not None:
            conn.execute(
                "INSERT INTO sessions(session_id, system_prompt, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt",
                (session_id, system_prompt, now),
            )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
            (session_id, user_msg, now),
        )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, reply, json.dumps(metadata), _now()),
        )
