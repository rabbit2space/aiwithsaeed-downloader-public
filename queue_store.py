from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


JOB_FIELDS = {
    "status", "progress", "title", "detail", "file_path", "file_size",
    "error", "control", "delivered",
}


class QueueStore:
    """Process-safe persistent queue shared by the desktop UI and Telegram bot."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.recovery_backup: Path | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._initialize()
        except sqlite3.DatabaseError as exc:
            diagnostics = str(exc).lower()
            confirmed_corruption = any(message in diagnostics for message in (
                "database disk image is malformed",
                "file is not a database",
                "file is encrypted or is not a database",
            ))
            if not confirmed_corruption or not self.path.exists():
                raise
            self.recovery_backup = self._preserve_corrupt_database()
            self._initialize()

    def _preserve_corrupt_database(self) -> Path:
        """Move an unreadable database aside so the application can start cleanly."""
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(
            f"{self.path.stem}.corrupt-{timestamp}-{time.time_ns()}{self.path.suffix}"
        )
        self.path.replace(backup)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.path}{suffix}")
            if sidecar.exists():
                sidecar.replace(Path(f"{backup}{suffix}"))
        return backup

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'desktop',
                    chat_id INTEGER,
                    settings TEXT NOT NULL,
                    position REAL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress REAL,
                    title TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL DEFAULT '',
                    file_size INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    control TEXT NOT NULL DEFAULT '',
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "position" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN position REAL")
            connection.execute("UPDATE jobs SET position=id WHERE position IS NULL")
            connection.execute("DROP INDEX IF EXISTS jobs_status_id")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_position "
                "ON jobs(status, position, id)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

    def get_preference(self, key: str, default: str = "") -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM preferences WHERE key=?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_preference(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO preferences(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def recover_interrupted(self) -> None:
        now = time.time()
        with self._connection() as connection:
            connection.execute("DELETE FROM jobs WHERE control='remove'")
            policy = connection.execute(
                "SELECT value FROM preferences WHERE key='collection_scope_policy'"
            ).fetchone()
            if not policy or policy["value"] != "1":
                # Queued children created by older auto-playlist behavior have
                # no reliable provenance. Keep them for review, never run them
                # automatically on the first launch after the safety update.
                connection.execute(
                    "UPDATE jobs SET status='paused', control='', "
                    "detail='Review this saved queue item before resuming', updated_at=? WHERE status='queued'",
                    (now,),
                )
                connection.execute(
                    "INSERT INTO preferences(key,value) VALUES ('collection_scope_policy','1') "
                    "ON CONFLICT(key) DO UPDATE SET value='1'"
                )
            connection.execute(
                "UPDATE jobs SET status='paused', control='', detail='Paused after restart; resume when ready', "
                "updated_at=? WHERE status IN ('downloading', 'processing', 'expanding')",
                (now,),
            )

    def add_jobs(
        self,
        urls: Iterable[str],
        settings: dict[str, Any],
        source: str = "desktop",
        chat_id: int | None = None,
    ) -> list[int]:
        now = time.time()
        encoded = json.dumps(settings, ensure_ascii=False)
        identifiers: list[int] = []
        with self._connection() as connection:
            position = float(connection.execute(
                "SELECT COALESCE(MAX(position), 0) FROM jobs"
            ).fetchone()[0])
            for url in urls:
                position += 1
                cursor = connection.execute(
                    "INSERT INTO jobs(url, source, chat_id, settings, position, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (url, source, chat_id, encoded, position, now, now),
                )
                identifiers.append(int(cursor.lastrowid))
        return identifiers

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY "
                "CASE status WHEN 'downloading' THEN 0 WHEN 'processing' THEN 0 "
                "WHEN 'expanding' THEN 0 WHEN 'queued' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END, "
                "position, id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, job_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim_next(self) -> dict[str, Any] | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY position, id LIMIT 1"
            ).fetchone()
            if not row:
                connection.commit()
                return None
            connection.execute(
                "UPDATE jobs SET status='downloading', progress=0, control='', updated_at=? "
                "WHERE id=?",
                (time.time(), row["id"]),
            )
            connection.commit()
        return self.get(int(row["id"]))

    def replace_with_entries(
        self,
        job_id: int,
        entries: Iterable[tuple[str, str]],
        settings: dict[str, Any],
    ) -> list[int]:
        """Replace one playlist placeholder with ordered per-video queue jobs."""
        items = list(entries)
        if not items:
            return []
        now = time.time()
        encoded = json.dumps(settings, ensure_ascii=False)
        identifiers: list[int] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                "SELECT source, chat_id, position, control FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not parent or parent["control"]:
                connection.commit()
                return []
            position = float(parent["position"])
            shift = len(items) - 1
            if shift:
                connection.execute(
                    "UPDATE jobs SET position=position+? WHERE position>?", (shift, position)
                )
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            for offset, (url, title) in enumerate(items):
                cursor = connection.execute(
                    "INSERT INTO jobs(url, source, chat_id, settings, position, title, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        url, parent["source"], parent["chat_id"], encoded, position + offset,
                        title, now, now,
                    ),
                )
                identifiers.append(int(cursor.lastrowid))
            connection.commit()
        return identifiers

    def update(self, job_id: int, **values: Any) -> None:
        invalid = set(values) - JOB_FIELDS
        if invalid:
            raise ValueError(f"Invalid job fields: {sorted(invalid)}")
        if not values:
            return
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        parameters = [*values.values(), job_id]
        with self._connection() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id=?", parameters)

    def set_settings(self, job_id: int, settings: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE jobs SET settings=?, updated_at=? WHERE id=?",
                (json.dumps(settings, ensure_ascii=False), time.time(), job_id),
            )

    def pause(self, job_id: int) -> bool:
        return bool(self.pause_many([job_id]))

    def pause_many(self, job_ids: Iterable[int]) -> list[int]:
        identifiers = sorted({int(job_id) for job_id in job_ids})
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM jobs WHERE id IN ({placeholders}) "
                "AND status IN ('queued','downloading','processing','expanding')",
                identifiers,
            ).fetchall()
            changed = [int(row["id"]) for row in rows]
            connection.execute(
                "UPDATE jobs SET status=CASE WHEN status='queued' THEN 'paused' ELSE status END, "
                "control=CASE WHEN status IN ('downloading','processing','expanding') THEN 'pause' ELSE control END, "
                f"updated_at=? WHERE id IN ({placeholders}) "
                "AND status IN ('queued','downloading','processing','expanding')",
                [time.time(), *identifiers],
            )
        return changed

    def resume(self, job_id: int) -> bool:
        return bool(self.resume_many([job_id]))

    def resume_many(self, job_ids: Iterable[int]) -> list[int]:
        identifiers = sorted({int(job_id) for job_id in job_ids})
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM jobs WHERE id IN ({placeholders}) "
                "AND status IN ('paused','failed','cancelled')",
                identifiers,
            ).fetchall()
            changed = [int(row["id"]) for row in rows]
            connection.execute(
                "UPDATE jobs SET status='queued', control='', error='', delivered=0, updated_at=? "
                f"WHERE id IN ({placeholders}) AND status IN ('paused','failed','cancelled')",
                [time.time(), *identifiers],
            )
        return changed

    def remove(self, job_id: int) -> str:
        result = self.remove_many([job_id])
        if job_id in result["stopping"]:
            return "stopping"
        if job_id in result["removed"]:
            return "removed"
        return "missing"

    def remove_many(self, job_ids: Iterable[int]) -> dict[str, list[int]]:
        identifiers = sorted({int(job_id) for job_id in job_ids})
        result: dict[str, list[int]] = {"stopping": [], "removed": []}
        if not identifiers:
            return result
        placeholders = ",".join("?" for _ in identifiers)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
                identifiers,
            ).fetchall()
            active = {"downloading", "processing", "expanding"}
            result["stopping"] = [int(row["id"]) for row in rows if row["status"] in active]
            result["removed"] = [int(row["id"]) for row in rows if row["status"] not in active]
            if result["stopping"]:
                stopping_placeholders = ",".join("?" for _ in result["stopping"])
                connection.execute(
                    f"UPDATE jobs SET control='remove', updated_at=? "
                    f"WHERE id IN ({stopping_placeholders})",
                    [time.time(), *result["stopping"]],
                )
            if result["removed"]:
                removed_placeholders = ",".join("?" for _ in result["removed"])
                connection.execute(
                    f"DELETE FROM jobs WHERE id IN ({removed_placeholders})",
                    result["removed"],
                )
        return result

    def delete(self, job_id: int) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def terminal_notifications(self, chat_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE source='telegram' AND chat_id=? AND delivered=0 "
                "AND status IN ('completed','failed','cancelled') ORDER BY id",
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def settings(job: dict[str, Any]) -> dict[str, Any]:
        return json.loads(job["settings"])
