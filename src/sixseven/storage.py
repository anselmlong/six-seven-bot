"""SQLite-backed per-chat, per-member 'six seven' counters."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass


@dataclass
class LeaderRow:
    user_id: int
    display_name: str
    username: str
    count: int


class Storage:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counts (
                chat_id      INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                username     TEXT    NOT NULL DEFAULT '',
                display_name TEXT    NOT NULL DEFAULT '',
                count        INTEGER NOT NULL DEFAULT 0,
                last_hit_at  REAL    NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        self._conn.commit()

    def increment(
        self,
        chat_id: int,
        user_id: int,
        display_name: str,
        username: str,
    ) -> int:
        """Add one to a member's counter and return their new total."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO counts (chat_id, user_id, username, display_name, count, last_hit_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    count = count + 1,
                    username = excluded.username,
                    display_name = excluded.display_name,
                    last_hit_at = excluded.last_hit_at
                """,
                (chat_id, user_id, username, display_name, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT count FROM counts WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def leaderboard(self, chat_id: int, limit: int = 10) -> list[LeaderRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT user_id, display_name, username, count
                FROM counts
                WHERE chat_id = ?
                ORDER BY count DESC, last_hit_at ASC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [LeaderRow(r[0], r[1], r[2], int(r[3])) for r in rows]

    def user_count(self, chat_id: int, user_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM counts WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
