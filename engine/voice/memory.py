"""Lightweight local session & persistent memory for P.E.K.K.A (Jarvis-style, 100% offline)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator


@dataclass(frozen=True)
class TurnRecord:
    role: str
    content: str
    tool: str | None
    timestamp: float


class SessionMemory:
    """Stores recent conversation turns and key/value context in local SQLite."""

    def __init__(self, db_path: Path | None = None, max_turns: int = 20) -> None:
        default_path = Path(__file__).resolve().parent.parent / ".cache" / "memory.db"
        self.db_path = db_path or default_path
        self.max_turns = max_turns
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS turns ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "role TEXT NOT NULL, content TEXT NOT NULL, tool TEXT, ts REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS facts ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL NOT NULL)"
            )
            conn.commit()

    def add_turn(self, role: str, content: str, tool: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO turns (role, content, tool, ts) VALUES (?, ?, ?, ?)",
                (role, content, tool, time.time()),
            )
            conn.commit()

    def recent_turns(self, limit: int | None = None) -> list[TurnRecord]:
        n = limit or self.max_turns
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, tool, ts FROM turns ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [TurnRecord(r[0], r[1], r[2], r[3]) for r in reversed(rows)]

    def set_fact(self, key: str, value: Any) -> None:
        raw = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO facts (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                (key, raw, time.time()),
            )
            conn.commit()

    def get_fact(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return row[0]

    def all_facts(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        out: dict[str, Any] = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except ValueError:
                out[k] = v
        return out

    def context_summary(self, limit: int = 6) -> str:
        turns = self.recent_turns(limit)
        facts = self.all_facts()
        lines: list[str] = []
        if facts:
            lines.append("Known context: " + json.dumps(facts, ensure_ascii=False))
        for t in turns:
            prefix = f"{t.role} ({t.tool})" if t.tool else t.role
            lines.append(f"- {prefix}: {t.content[:200]}")
        return "\n".join(lines)
