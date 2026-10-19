"""
Database Migration Runner.

Provides a safe, non-destructive, incremental migration engine. Checks for existing
tables and columns before executing DDL operations. NEVER drops tables or data.
"""

import logging
from typing import List, Set
import aiosqlite

logger = logging.getLogger("productivity_hub.database.migrations")

CURRENT_SCHEMA_VERSION = 2


async def _get_existing_tables(db: aiosqlite.Connection) -> Set[str]:
    """Retrieve set of all table names in SQLite database."""
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table';") as cursor:
        rows = await cursor.fetchall()
        return {row[0] for row in rows}


async def _get_existing_columns(db: aiosqlite.Connection, table_name: str) -> Set[str]:
    """Retrieve set of column names for a given table using PRAGMA table_info."""
    try:
        async with db.execute(f"PRAGMA table_info('{table_name}');") as cursor:
            rows = await cursor.fetchall()
            return {row[1] for row in rows}
    except Exception as e:
        logger.warning(f"Could not inspect table_info for {table_name}: {e}")
        return set()


async def run_migrations(db_path: str = "database/app.sqlite3") -> int:
    """
    Check database schema version and apply pending incremental migrations safely.

    Args:
        db_path: Target SQLite database file path.

    Returns:
        int: Current applied schema version.
    """
    logger.info("Executing database migration check...")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Ensure schema_migrations table exists
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        await db.commit()

        # Get current version
        async with db.execute("SELECT MAX(version) as current_ver FROM schema_migrations") as cursor:
            row = await cursor.fetchone()
            current_version = row["current_ver"] if row and row["current_ver"] is not None else 0

        logger.info(f"Current database schema version: {current_version}")

        # ----------------------------------------------------------------
        # MIGRATION v1: Baseline Schema Setup
        # ----------------------------------------------------------------
        if current_version < 1:
            logger.info("Applying Migration v1 (Baseline Schema)...")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    role TEXT NOT NULL DEFAULT 'user',
                    language TEXT NOT NULL DEFAULT 'en',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT,
                    result_data TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                );
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

            await db.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (1);")
            await db.commit()
            current_version = 1
            logger.info("Migration v1 applied successfully.")

        # ----------------------------------------------------------------
        # MIGRATION v2: Full Domain Tables Expansion
        # ----------------------------------------------------------------
        if current_version < 2:
            logger.info("Applying Migration v2 (Downloads, Conversions, QR, Security & Audit Logs)...")
            existing_tables = await _get_existing_tables(db)

            # 1. Downloads Table
            if "downloads" not in existing_tables:
                await db.execute("""
                    CREATE TABLE downloads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        url TEXT NOT NULL,
                        service TEXT,
                        title TEXT,
                        file_path TEXT,
                        file_size INTEGER,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id);")

            # 2. Conversions Table
            if "conversions" not in existing_tables:
                await db.execute("""
                    CREATE TABLE conversions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        source_format TEXT NOT NULL,
                        target_format TEXT NOT NULL,
                        source_file TEXT,
                        result_file TEXT,
                        file_size INTEGER,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_conversions_user ON conversions(user_id);")

            # 3. QR History Table
            if "qr_history" not in existing_tables:
                await db.execute("""
                    CREATE TABLE qr_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        action_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_qr_history_user ON qr_history(user_id);")

            # 4. Admins Table
            if "admins" not in existing_tables:
                await db.execute("""
                    CREATE TABLE admins (
                        user_id INTEGER PRIMARY KEY,
                        added_by INTEGER NOT NULL,
                        role TEXT NOT NULL DEFAULT 'admin',
                        added_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)

            # 5. Banned Users Table
            if "banned_users" not in existing_tables:
                await db.execute("""
                    CREATE TABLE banned_users (
                        user_id INTEGER PRIMARY KEY,
                        reason TEXT NOT NULL,
                        banned_by INTEGER NOT NULL,
                        banned_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)

            # 6. Suspicious Users Table
            if "suspicious_users" not in existing_tables:
                await db.execute("""
                    CREATE TABLE suspicious_users (
                        user_id INTEGER PRIMARY KEY,
                        event_count INTEGER NOT NULL DEFAULT 1,
                        last_reason TEXT,
                        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                    );
                """)

            # 7. Audit Logs Table
            if "logs" not in existing_tables:
                await db.execute("""
                    CREATE TABLE logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        level TEXT NOT NULL,
                        logger_name TEXT NOT NULL,
                        message TEXT NOT NULL,
                        user_id INTEGER,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    );
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_logs_user ON logs(user_id);")

            # Column verification & non-destructive ALTERs for pre-existing tables
            users_cols = await _get_existing_columns(db, "users")
            if "role" not in users_cols:
                await db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';")
            if "language" not in users_cols:
                await db.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en';")

            await db.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (2);")
            await db.commit()
            current_version = 2
            logger.info("Migration v2 applied successfully.")

        logger.info(f"Database migrations complete. Schema up to date at version {current_version}.")
        return current_version
