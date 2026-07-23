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


_DEDUP_TTL = 7 * 24 * 3600  # 7 days in seconds


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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_config (
                chat_id      INTEGER NOT NULL PRIMARY KEY,
                notify_mode  TEXT    NOT NULL DEFAULT 'instant'
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                chat_id      INTEGER NOT NULL,
                message_id   INTEGER NOT NULL,
                processed_at REAL    NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_processed_messages_cleanup "
            "ON processed_messages (processed_at)"
        )
        self._conn.commit()
        self._cleanup_processed_messages()

    def get_notify_mode(self, chat_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT notify_mode FROM chat_config WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return row[0] if row else "instant"

    def set_notify_mode(self, chat_id: int, mode: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO chat_config (chat_id, notify_mode) VALUES (?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET notify_mode = excluded.notify_mode""",
                (chat_id, mode),
            )
            self._conn.commit()

    def get_daily_chats(self) -> list[int]:
        """Return chat_ids that have notify_mode='daily'."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id FROM chat_config WHERE notify_mode = 'daily'"
            ).fetchall()
        return [r[0] for r in rows]

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

    def is_first_time(self, chat_id: int, message_id: int) -> bool:
        """Atomically check-and-mark a message as processed.

        Returns True the FIRST time a (chat_id, message_id) pair is seen.
        Returns False for any subsequent call with the same pair — even after
        a process restart — preventing double-counting from all causes
        (Telegram re-delivery, concurrent processing, crash recovery, etc.).
        """
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO processed_messages (chat_id, message_id, processed_at) "
                "VALUES (?, ?, ?)",
                (chat_id, message_id, time.time()),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def _cleanup_processed_messages(self) -> None:
        """Remove entries older than the TTL to keep the table bounded."""
        cutoff = time.time() - _DEDUP_TTL
        with self._lock:
            self._conn.execute(
                "DELETE FROM processed_messages WHERE processed_at < ?", (cutoff,)
            )
            self._conn.commit()

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
