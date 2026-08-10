"""SQLite data layer with non-destructive migrations, plans, and analytics."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

PLATFORMS = ("instagram", "facebook", "snapchat", "youtube")


class Database:
    def __init__(self, path: Path) -> None:
        self.path, self._lock = path, Lock()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY, first_seen TEXT NOT NULL,
                    total_downloads INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('success','failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_downloads_user_time ON downloads (telegram_user_id, timestamp);
            """)
            self._add_column(connection, "users", "pro_until", "TEXT")
            self._add_column(connection, "downloads", "platform", "TEXT NOT NULL DEFAULT 'instagram'")
            self._add_column(connection, "downloads", "requested_quality", "INTEGER")
            self._add_column(connection, "downloads", "plan", "TEXT NOT NULL DEFAULT 'free'")

    @staticmethod
    def _add_column(connection, table, name, definition):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def ensure_user(self, user_id: int) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("INSERT OR IGNORE INTO users (telegram_user_id, first_seen) VALUES (?, ?)", (user_id, datetime.now(timezone.utc).isoformat()))

    def is_pro(self, user_id: int) -> bool:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT pro_until FROM users WHERE telegram_user_id=?", (user_id,)).fetchone()
        if not row or not row["pro_until"]:
            return False
        try:
            return datetime.fromisoformat(row["pro_until"]) > datetime.now(timezone.utc)
        except ValueError:
            return False

    def pro_expiry(self, user_id: int):
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT pro_until FROM users WHERE telegram_user_id=?", (user_id,)).fetchone()
        return row["pro_until"] if row else None

    def set_pro(self, user_id: int, days: int) -> None:
        self.ensure_user(user_id)
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT pro_until FROM users WHERE telegram_user_id=?", (user_id,)).fetchone()
            now = datetime.now(timezone.utc)
            try:
                current = datetime.fromisoformat(row["pro_until"]) if row["pro_until"] else now
            except ValueError:
                current = now
            expiry = max(current, now) + timedelta(days=days)
            connection.execute("UPDATE users SET pro_until=? WHERE telegram_user_id=?", (expiry.isoformat(), user_id))

    def remove_pro(self, user_id: int) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("UPDATE users SET pro_until=NULL WHERE telegram_user_id=?", (user_id,))

    def successful_downloads_today(self, user_id: int) -> int:
        with self._lock, self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE telegram_user_id=? AND status='success' AND date(timestamp)=date('now')", (user_id,)).fetchone()["count"])

    def successful_downloads_last_hour(self, user_id: int) -> int:
        with self._lock, self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE telegram_user_id=? AND status='success' AND timestamp>=datetime('now','-1 hour')", (user_id,)).fetchone()["count"])

    def record_download(self, user_id: int, status: str, platform="instagram", requested_quality=None, plan="free") -> None:
        if status not in {"success", "failed"} or platform not in PLATFORMS:
            raise ValueError("Invalid download record")
        self.ensure_user(user_id)
        with self._lock, self._connection() as connection:
            connection.execute("INSERT INTO downloads (telegram_user_id,timestamp,status,platform,requested_quality,plan) VALUES (?,?,?,?,?,?)", (user_id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), status, platform, requested_quality, plan))
            if status == "success":
                connection.execute("UPDATE users SET total_downloads=total_downloads+1 WHERE telegram_user_id=?", (user_id,))

    def user_stats(self, user_id: int):
        with self._lock, self._connection() as connection:
            total = int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE telegram_user_id=? AND status='success'", (user_id,)).fetchone()["count"])
            rows = connection.execute("SELECT platform,COUNT(*) count FROM downloads WHERE telegram_user_id=? AND status='success' GROUP BY platform", (user_id,)).fetchall()
        return total, {row["platform"]: int(row["count"]) for row in rows}

    def admin_stats(self):
        with self._lock, self._connection() as connection:
            total = int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE status='success'").fetchone()["count"])
            today = int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE status='success' AND date(timestamp)=date('now')").fetchone()["count"])
            active_pro = int(connection.execute("SELECT COUNT(*) count FROM users WHERE pro_until>datetime('now')").fetchone()["count"])
            users = int(connection.execute("SELECT COUNT(*) count FROM users").fetchone()["count"])
            rows = connection.execute("SELECT platform,COUNT(*) count FROM downloads WHERE status='success' GROUP BY platform").fetchall()
        return total, today, active_pro, users-active_pro, {r["platform"]: int(r["count"]) for r in rows}

    def get_stats(self, user_id: int):
        total, _, _, _, _ = self.admin_stats()
        user_total, _ = self.user_stats(user_id)
        with self._lock, self._connection() as connection:
            failed = int(connection.execute("SELECT COUNT(*) count FROM downloads WHERE status='failed'").fetchone()["count"])
        return total, user_total, failed
