"""SQLite persistent memory for FRIDAY — conversations, facts, tasks, tool usage.

Survives restarts. Facts persist across sessions; conversation history is
per-session and can be cleared without touching facts.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    tokens_used INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    source TEXT DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_description TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    result_summary TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    args_json TEXT,
    result_summary TEXT,
    success INTEGER NOT NULL,
    timestamp TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class FridayMemory:
    """Thread-safe SQLite store for everything FRIDAY remembers."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else config.MEMORY_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -------------------------------------------------- conversations ---
    def add_message(self, session_id: str, role: str, content: str, tokens_used: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (session_id, role, content, timestamp, tokens_used) VALUES (?,?,?,?,?)",
                (session_id, role, str(content), _now(), int(tokens_used or 0)),
            )
            self._conn.commit()

    def get_history(self, session_id: str, last_n: int = 50) -> list[dict]:
        """Most recent `last_n` messages, oldest first. [{role, content}]"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, int(last_n)),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_session(self, session_id: str) -> int:
        """Delete a session's conversation. Facts and tasks are kept."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM conversations WHERE session_id=?", (session_id,))
            self._conn.commit()
        return cur.rowcount

    def search_history(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, timestamp FROM conversations WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (like, int(limit)),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"][:300], "timestamp": r["timestamp"]} for r in rows]

    # ---------------------------------------------------------- facts ---
    def save_fact(self, key: str, value: str, source: str = "user") -> str:
        """Upsert a fact. Keys are case-insensitive."""
        key = str(key).strip().lower()
        ts = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO facts (key, value, source, created_at, updated_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       source = excluded.source,
                       updated_at = excluded.updated_at""",
                (key, str(value), source, ts, ts),
            )
            self._conn.commit()
        return key

    def get_fact(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM facts WHERE key=?", (str(key).strip().lower(),)
            ).fetchone()
        return row["value"] if row else None

    def get_all_facts(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---------------------------------------------------------- tasks ---
    def log_task(self, description: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tasks (task_description, created_at) VALUES (?,?)", (description, _now())
            )
            self._conn.commit()
            return cur.lastrowid

    def complete_task(self, task_id: int, result_summary: str, status: str = "done") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status=?, result_summary=?, completed_at=? WHERE id=?",
                (status, result_summary, _now(), task_id),
            )
            self._conn.commit()

    def get_recent_tasks(self, n: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_description, status, result_summary, created_at FROM tasks ORDER BY id DESC LIMIT ?",
                (int(n),),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------ tool usage ---
    def log_tool_call(self, tool_name: str, args: dict, result: str, success: bool) -> None:
        with self._lock:
            try:
                args_json = json.dumps(args, ensure_ascii=False)
            except (TypeError, ValueError):
                args_json = str(args)
            self._conn.execute(
                "INSERT INTO tool_usage (tool_name, args_json, result_summary, success, timestamp) VALUES (?,?,?,?,?)",
                (tool_name, args_json[:500], str(result)[:500], 1 if success else 0, _now()),
            )
            self._conn.commit()

    # --------------------------------------------------- introspection ---
    def get_session_summary(self) -> dict:
        with self._lock:
            def _count(sql: str) -> int:
                return self._conn.execute(sql).fetchone()[0]

            return {
                "messages": _count("SELECT COUNT(*) FROM conversations"),
                "facts": _count("SELECT COUNT(*) FROM facts"),
                "tasks": _count("SELECT COUNT(*) FROM tasks"),
                "tool_calls": _count("SELECT COUNT(*) FROM tool_usage"),
                "tool_success": _count("SELECT COUNT(*) FROM tool_usage WHERE success=1"),
                "db": str(self.db_path),
            }
