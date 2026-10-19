"""
Async Database Infrastructure & Centralized Data Access layer.

Provides an asynchronous database layer powered by aiosqlite. Centralizes all raw SQL DDL
and DML operations in dedicated data access methods to ensure clean separation of concerns
and easy future porting to PostgreSQL or MySQL.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncGenerator
from contextlib import asynccontextmanager
import aiosqlite

from productivity_hub.database.models import (
    User, Task, TaskStatus, Download, Conversion, QRHistory, Admin, BannedUser, SuspiciousUser, LogEntry
)

logger = logging.getLogger("productivity_hub.database")


class DatabaseManager:
    """
    Asynchronous SQLite Database Manager providing connection pooling context
    and centralized CRUD Data Access Object (DAO) methods.
    """

    def __init__(self, db_path: str = "database/app.sqlite3"):
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        """
        Ensure database directory exists, connect, set SQLite PRAGMAs (WAL, Foreign Keys),
        and establish baseline table structure.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initializing SQLite database at: {self.db_path.resolve()}")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.commit()
            logger.info("Database connection PRAGMAs configured (WAL mode active).")

        from productivity_hub.database.migrations import run_migrations
        await run_migrations(str(self.db_path))


    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Async context manager for DB sessions."""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            await conn.close()

    # ====================================================================
    # USER DATA ACCESS METHODS
    # ====================================================================

    async def upsert_user(self, user: User) -> None:
        """Insert or update user details."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, is_banned, is_admin, role, language, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = datetime('now');
            """, (
                user.user_id, user.username, user.first_name, user.last_name,
                int(user.is_banned), int(user.is_admin), user.role, user.language
            ))
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[User]:
        """Fetch user by Telegram ID."""
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                keys = row.keys()
                return User(
                    user_id=row["user_id"],
                    username=row["username"] if "username" in keys else None,
                    first_name=row["first_name"] if "first_name" in keys else None,
                    last_name=row["last_name"] if "last_name" in keys else None,
                    is_banned=bool(row["is_banned"]) if "is_banned" in keys else False,
                    is_admin=bool(row["is_admin"]) if "is_admin" in keys else False,
                    role=row["role"] if "role" in keys else "user",
                    language=row["language"] if "language" in keys else "en",
                    created_at=row["created_at"] if "created_at" in keys else "",
                    updated_at=row["updated_at"] if "updated_at" in keys else ""
                )

    async def set_user_language(self, user_id: int, language_code: str) -> None:
        """Update user language preference."""
        async with self.get_connection() as db:
            await db.execute(
                "UPDATE users SET language = ?, updated_at = datetime('now') WHERE user_id = ?",
                (language_code, user_id)
            )
            await db.commit()

    async def set_user_ban_status(self, user_id: int, is_banned: bool, reason: str = "", banned_by: int = 0) -> None:
        """Ban or unban a user."""
        async with self.get_connection() as db:
            await db.execute("UPDATE users SET is_banned = ?, updated_at = datetime('now') WHERE user_id = ?", (int(is_banned), user_id))
            if is_banned:
                await db.execute("""
                    INSERT INTO banned_users (user_id, reason, banned_by)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason, banned_by = excluded.banned_by, banned_at = datetime('now');
                """, (user_id, reason, banned_by))
            else:
                await db.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            await db.commit()

    # ====================================================================
    # TASK DATA ACCESS METHODS
    # ====================================================================

    async def create_task(self, task: Task) -> None:
        """Create a new task record."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO tasks (task_id, user_id, task_type, status, payload, result_data, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id, task.user_id, task.task_type,
                task.status.value if isinstance(task.status, TaskStatus) else task.status,
                task.payload, task.result_data, task.error_message
            ))
            await db.commit()

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result_data: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """Update task status and results."""
        status_val = status.value if isinstance(status, TaskStatus) else status
        async with self.get_connection() as db:
            await db.execute("""
                UPDATE tasks
                SET status = ?, result_data = COALESCE(?, result_data), error_message = COALESCE(?, error_message), updated_at = datetime('now')
                WHERE task_id = ?
            """, (status_val, result_data, error_message, task_id))
            await db.commit()

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Fetch task by ID."""
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return Task(
                    task_id=row["task_id"],
                    user_id=row["user_id"],
                    task_type=row["task_type"],
                    status=TaskStatus(row["status"]),
                    payload=row["payload"],
                    result_data=row["result_data"],
                    error_message=row["error_message"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )

    async def get_user_history(self, user_id: int, limit: int = 10) -> List[Task]:
        """Fetch latest tasks for user history menu."""
        async with self.get_connection() as db:
            async with db.execute(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    Task(
                        task_id=row["task_id"],
                        user_id=row["user_id"],
                        task_type=row["task_type"],
                        status=TaskStatus(row["status"]),
                        payload=row["payload"],
                        result_data=row["result_data"],
                        error_message=row["error_message"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
                    for row in rows
                ]

    # ====================================================================
    # DOMAIN SPECIFIC RECORD LOGS
    # ====================================================================

    async def record_download(self, download: Download) -> None:
        """Log media download entry."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO downloads (task_id, user_id, url, service, title, file_path, file_size, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (download.task_id, download.user_id, download.url, download.service, download.title, download.file_path, download.file_size, download.status))
            await db.commit()

    async def record_conversion(self, conversion: Conversion) -> None:
        """Log conversion entry."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO conversions (task_id, user_id, source_format, target_format, source_file, result_file, file_size, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (conversion.task_id, conversion.user_id, conversion.source_format, conversion.target_format, conversion.source_file, conversion.result_file, conversion.file_size, conversion.status))
            await db.commit()

    async def record_qr_action(self, qr: QRHistory) -> None:
        """Log QR code generation or scan."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO qr_history (user_id, action_type, content)
                VALUES (?, ?, ?)
            """, (qr.user_id, qr.action_type, qr.content))
            await db.commit()

    async def add_audit_log(self, level: str, logger_name: str, message: str, user_id: Optional[int] = None) -> None:
        """Insert structured audit log into database."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO logs (level, logger_name, message, user_id)
                VALUES (?, ?, ?, ?)
            """, (level, logger_name, message, user_id))
            await db.commit()

    # ====================================================================
    # SYSTEM SETTINGS ACCESS
    # ====================================================================

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch setting value by key."""
        async with self.get_connection() as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        """Insert or update setting."""
        async with self.get_connection() as db:
            await db.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now');
            """, (key, value))
            await db.commit()


# Global database manager instance
_db_manager_instance: Optional[DatabaseManager] = None


async def init_db(db_path: str = "database/app.sqlite3") -> DatabaseManager:
    """Initialize global DatabaseManager instance."""
    global _db_manager_instance
    _db_manager_instance = DatabaseManager(db_path)
    await _db_manager_instance.initialize()
    return _db_manager_instance


def get_db() -> DatabaseManager:
    """Retrieve global DatabaseManager singleton."""
    global _db_manager_instance
    if _db_manager_instance is None:
        raise RuntimeError("DatabaseManager is not initialized. Call init_db() first.")
    return _db_manager_instance


async def close_db() -> None:
    """Close global database resources."""
    global _db_manager_instance
    if _db_manager_instance:
        logger.info("Database connection closed cleanly.")
        _db_manager_instance = None
