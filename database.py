"""Small SQLite data layer for usage statistics and rate limiting."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    total_downloads INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('success', 'failed'))
                );

                CREATE INDEX IF NOT EXISTS idx_downloads_user_time
                ON downloads (telegram_user_id, timestamp);
                """
            )

    def ensure_user(self, telegram_user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users (telegram_user_id, first_seen) VALUES (?, ?)",
                (telegram_user_id, now),
            )

    def successful_downloads_last_hour(self, telegram_user_id: int) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM downloads
                WHERE telegram_user_id = ?
                  AND status = 'success'
                  AND timestamp >= datetime('now', '-1 hour')
                """,
                (telegram_user_id,),
            ).fetchone()
        return int(row["count"])

    def record_download(self, telegram_user_id: int, status: str) -> None:
        if status not in {"success", "failed"}:
            raise ValueError("Invalid download status")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users (telegram_user_id, first_seen) VALUES (?, ?)",
                (telegram_user_id, datetime.now(timezone.utc).isoformat()),
            )
            connection.execute(
                "INSERT INTO downloads (telegram_user_id, timestamp, status) VALUES (?, ?, ?)",
                (telegram_user_id, now, status),
            )
            if status == "success":
                connection.execute(
                    "UPDATE users SET total_downloads = total_downloads + 1 WHERE telegram_user_id = ?",
                    (telegram_user_id,),
                )

    def get_stats(self, telegram_user_id: int) -> tuple[int, int, int]:
        with self._lock, self._connect() as connection:
            total_success = connection.execute(
                "SELECT COUNT(*) AS count FROM downloads WHERE status = 'success'"
            ).fetchone()["count"]
            total_failed = connection.execute(
                "SELECT COUNT(*) AS count FROM downloads WHERE status = 'failed'"
            ).fetchone()["count"]
            user_success = connection.execute(
                """
                SELECT COUNT(*) AS count FROM downloads
                WHERE telegram_user_id = ? AND status = 'success'
                """,
                (telegram_user_id,),
            ).fetchone()["count"]
        return int(total_success), int(user_success), int(total_failed)

