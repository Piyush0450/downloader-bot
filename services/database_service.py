import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from config.settings import DATABASE_DIR, OWNER_ID, DATABASE_URL
from utils.logger import logger

import os

def get_db_path() -> str:
    from config.settings import DATABASE_URL, DATABASE_DIR
    url = os.getenv("DATABASE_URL", DATABASE_URL)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return str(DATABASE_DIR / "bot.db")


@contextmanager
def get_db():
    """Context manager for SQLite database connection."""
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes tables and seeds the Owner in admins table using raw SQL."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    language TEXT DEFAULT 'en',
                    join_date TEXT,
                    last_seen TEXT,
                    downloads_count INTEGER DEFAULT 0,
                    conversions_count INTEGER DEFAULT 0,
                    files_processed INTEGER DEFAULT 0,
                    total_storage_saved INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0
                )
            """)
            
            # Create downloads table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT,
                    platform TEXT,
                    title TEXT,
                    download_type TEXT,
                    quality TEXT,
                    size INTEGER,
                    timestamp TEXT
                )
            """)
            
            # Create conversions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    original_file TEXT,
                    source_format TEXT,
                    target_format TEXT,
                    file_size INTEGER,
                    timestamp TEXT
                )
            """)
            
            # Create qr_history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS qr_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT,
                    timestamp TEXT
                )
            """)
            
            # Create logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    message TEXT,
                    timestamp TEXT
                )
            """)
            
            # Create admins table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    role TEXT
                )
            """)
            
            # Create suspicious_users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS suspicious_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    attempt_count INTEGER DEFAULT 0,
                    last_attempt TEXT
                )
            """)
            
            # Create system_state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # Create indexes for production performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloads_user_id ON downloads (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversions_user_id ON conversions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_suspicious_users_user_id ON suspicious_users (user_id)")
            
            conn.commit()
            logger.info("SQLite database tables and indexes created successfully.")
            
        log_event("SYSTEM", "SQLite Database initialized.")
        
        # Seed Owner ID if configured
        if OWNER_ID:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT role FROM admins WHERE user_id = ?", (OWNER_ID,))
                row = cursor.fetchone()
                if not row:
                    cursor.execute("INSERT INTO admins (user_id, role) VALUES (?, ?)", (OWNER_ID, "OWNER"))
                    conn.commit()
                    logger.info(f"Owner {OWNER_ID} seeded as OWNER role.")
                    log_event("ADMIN", f"Owner {OWNER_ID} seeded.")
                    
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        raise e

def log_event(event_type: str, message: str):
    """Write an audit entry in the logs table."""
    try:
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO logs (event_type, message, timestamp) VALUES (?, ?, ?)",
                (event_type, message, now_str)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to write DB log: {e}")

# --- USER SERVICE ---
class UserService:
    @staticmethod
    def get_or_create_user(user_id: int, username: str = None, first_name: str = None) -> dict:
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if not row:
                cursor.execute(
                    "INSERT INTO users (user_id, username, first_name, join_date, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, first_name, now_str, now_str)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                logger.info(f"Registered user {user_id} in DB.")
                log_event("SYSTEM", f"New user registered: {user_id}")
            else:
                cursor.execute(
                    "UPDATE users SET username = ?, first_name = ?, last_seen = ? WHERE user_id = ?",
                    (username, first_name, now_str, user_id)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                
            return dict(row)

    @staticmethod
    def update_last_seen(user_id: int):
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now_str, user_id))
            conn.commit()

    @staticmethod
    def ban_user(user_id: int) -> bool:
        if user_id == OWNER_ID:
            return False
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                return False
            cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if not cursor.fetchone():
                return False
            cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            log_event("ADMIN", f"Banned user {user_id}")
            return True

    @staticmethod
    def unban_user(user_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if not cursor.fetchone():
                return False
            cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            log_event("ADMIN", f"Unbanned user {user_id}")
            return True

    @staticmethod
    def is_banned(user_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            # is_banned field is integer (0 or 1) in SQLite
            return bool(row["is_banned"]) if row else False

    @staticmethod
    def add_storage_saved(user_id: int, bytes_saved: int):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET total_storage_saved = total_storage_saved + ? WHERE user_id = ?",
                (bytes_saved, user_id)
            )
            conn.commit()

# --- DOWNLOAD SERVICE ---
class DownloadService:
    @staticmethod
    def log_download(user_id: int, url: str, platform: str, title: str, download_type: str, quality: str, size: int):
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO downloads (user_id, url, platform, title, download_type, quality, size, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, url, platform, title, download_type, quality, size, now_str)
            )
            cursor.execute(
                "UPDATE users SET downloads_count = downloads_count + 1, files_processed = files_processed + 1 "
                "WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        log_event("DOWNLOADS", f"User {user_id} downloaded {platform} ({download_type})")

# --- CONVERSION SERVICE ---
class ConversionService:
    @staticmethod
    def log_conversion(user_id: int, original_file: str, source_format: str, target_format: str, file_size: int):
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversions (user_id, original_file, source_format, target_format, file_size, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, original_file, source_format, target_format, file_size, now_str)
            )
            cursor.execute(
                "UPDATE users SET conversions_count = conversions_count + 1, files_processed = files_processed + 1 "
                "WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        log_event("CONVERSIONS", f"User {user_id} converted {original_file} ({source_format}->{target_format})")

    @staticmethod
    def log_qr(user_id: int, action_type: str):
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO qr_history (user_id, action_type, timestamp) VALUES (?, ?, ?)",
                (user_id, action_type, now_str)
            )
            cursor.execute(
                "UPDATE users SET files_processed = files_processed + 1 WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        log_event("SYSTEM", f"User {user_id} QR utility: {action_type}")

# --- ADMIN SERVICE ---
class AdminService:
    @staticmethod
    def is_admin(user_id: int) -> str:
        """Return role (OWNER/ADMIN) if user is admin, else None."""
        if user_id == OWNER_ID:
            return "OWNER"
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row["role"] if row else None

    @staticmethod
    def add_admin(user_id: int, role: str = "ADMIN") -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                return False
            cursor.execute("INSERT INTO admins (user_id, role) VALUES (?, ?)", (user_id, role))
            conn.commit()
            log_event("ADMIN", f"User {user_id} added as {role}")
            return True

    @staticmethod
    def track_suspicious(user_id: int):
        now_str = datetime.utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT attempt_count FROM suspicious_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if not row:
                cursor.execute(
                    "INSERT INTO suspicious_users (user_id, attempt_count, last_attempt) VALUES (?, 1, ?)",
                    (user_id, now_str)
                )
                attempts = 1
            else:
                attempts = row["attempt_count"] + 1
                cursor.execute(
                    "UPDATE suspicious_users SET attempt_count = ?, last_attempt = ? WHERE user_id = ?",
                    (attempts, now_str, user_id)
                )
            conn.commit()
        log_event("UNAUTHORIZED", f"Suspicious attempt by {user_id} (Count: {attempts})")

    @staticmethod
    def get_suspicious(user_id: int) -> int:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT attempt_count FROM suspicious_users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row["attempt_count"] if row else 0

# --- STATISTICS SERVICE ---
class StatisticsService:
    @staticmethod
    def get_user_stats(user_id: int) -> dict:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return {}
            
            # Format datetime
            join_dt = datetime.fromisoformat(row["join_date"])
            seen_dt = datetime.fromisoformat(row["last_seen"])
            
            return {
                "downloads": row["downloads_count"],
                "conversions": row["conversions_count"],
                "files_processed": row["files_processed"],
                "storage_saved_bytes": row["total_storage_saved"],
                "join_date": join_dt,
                "last_seen": seen_dt
            }

    @staticmethod
    def get_global_stats() -> dict:
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(1) FROM users")
            total_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(1) FROM users WHERE is_banned = 1")
            banned_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(1) FROM downloads")
            total_downloads = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(1) FROM conversions")
            total_conversions = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(total_storage_saved) FROM users")
            total_storage = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM suspicious_users")
            suspicious = cursor.fetchone()[0]
            
            # Today's metrics
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE datetime(last_seen) >= datetime('now', '-1 day')")
            active_today = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM downloads WHERE datetime(timestamp) >= datetime('now', '-1 day')")
            downloads_today = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM conversions WHERE datetime(timestamp) >= datetime('now', '-1 day')")
            conversions_today = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM qr_history WHERE action_type = 'GENERATE'")
            qr_generated = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM logs WHERE event_type = 'CONVERSIONS' AND (message LIKE '%compressed%' OR message LIKE '%compress%')")
            files_compressed = cursor.fetchone()[0] or 0
            
            return {
                "total_users": total_users,
                "banned_users": banned_users,
                "total_downloads": total_downloads,
                "total_conversions": total_conversions,
                "total_storage_saved_bytes": total_storage,
                "suspicious_count": suspicious,
                "active_today": active_today,
                "downloads_today": downloads_today,
                "conversions_today": conversions_today,
                "qr_generated": qr_generated,
                "files_compressed": files_compressed
            }

    @staticmethod
    def get_recent_downloads(limit: int = 10) -> list:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM downloads ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_recent_conversions(limit: int = 10) -> list:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversions ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_all_users() -> list:
        """Returns list of user dictionaries sorted by last_seen."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY last_seen DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_user_history(user_id: int, limit: int = 5) -> list:
        """Fetch history of conversions and downloads."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT platform, title, download_type, quality, size, timestamp FROM downloads "
                "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit)
            )
            dls = cursor.fetchall()
            
            cursor.execute(
                "SELECT original_file, source_format, target_format, file_size, timestamp FROM conversions "
                "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit)
            )
            convs = cursor.fetchall()
            
        combined = []
        for d in dls:
            combined.append({
                "type": "download",
                "action": f"Download {d['platform']} media",
                "details": f"{d['title'][:30]} ({d['quality']})",
                "size": d["size"],
                "timestamp": datetime.fromisoformat(d["timestamp"])
            })
            
        for c in convs:
            combined.append({
                "type": "conversion",
                "action": f"Conversion ({c['source_format'].upper()} -> {c['target_format'].upper()})",
                "details": c["original_file"][:30],
                "size": c["file_size"],
                "timestamp": datetime.fromisoformat(c["timestamp"])
            })
            
        combined.sort(key=lambda x: x["timestamp"], reverse=True)
        return combined[:limit]

    @staticmethod
    def get_detailed_analytics() -> dict:
        """Fetch extensive user, platform, conversion, and compression analytics."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE datetime(last_seen) >= datetime('now', '-1 day')")
            dau = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE datetime(last_seen) >= datetime('now', '-7 days')")
            wau = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE datetime(last_seen) >= datetime('now', '-30 days')")
            mau = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM users WHERE datetime(join_date) >= datetime('now', '-1 day')")
            new_users_today = cursor.fetchone()[0] or 0
            
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) FROM users 
                WHERE datetime(last_seen) >= datetime('now', '-1 day') 
                  AND datetime(join_date) < datetime('now', '-1 day')
            """)
            returning_users_today = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM downloads")
            dls_total = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM conversions")
            convs_total = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM qr_history")
            qr_total = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM logs WHERE message LIKE '%text action%'")
            text_total = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(1) FROM logs WHERE event_type = 'CONVERSIONS' AND (message LIKE '%compressed%' OR message LIKE '%compress%')")
            compress_total = cursor.fetchone()[0] or 0
            
            cursor.execute("""
                SELECT source_format, COUNT(1) as cnt 
                FROM conversions 
                GROUP BY source_format 
                ORDER BY cnt DESC LIMIT 5
            """)
            common_types = [{"format": r["source_format"], "count": r["cnt"]} for r in cursor.fetchall()]
            
            cursor.execute("""
                SELECT (source_format || ' -> ' || target_format) as route, COUNT(1) as cnt 
                FROM conversions 
                GROUP BY route 
                ORDER BY cnt DESC LIMIT 5
            """)
            popular_conversions = [{"route": r["route"], "count": r["cnt"]} for r in cursor.fetchall()]
            
            cursor.execute("""
                SELECT platform, COUNT(1) as cnt 
                FROM downloads 
                GROUP BY platform 
                ORDER BY cnt DESC LIMIT 5
            """)
            top_platforms = [{"platform": r["platform"], "count": r["cnt"]} for r in cursor.fetchall()]

            cursor.execute("SELECT COUNT(1) FROM logs WHERE event_type = 'CONVERSIONS' AND (message LIKE '%compressed%' OR message LIKE '%compress%')")
            files_compressed = cursor.fetchone()[0] or 0

            return {
                "dau": dau,
                "wau": wau,
                "mau": mau,
                "new_users_today": new_users_today,
                "returning_users_today": returning_users_today,
                "popular_tools": {
                    "Downloads": dls_total,
                    "Conversions": convs_total,
                    "QR Tools": qr_total,
                    "Text Tools": text_total,
                    "Compressor": compress_total
                },
                "common_file_types": common_types,
                "popular_conversions": popular_conversions,
                "top_platforms": top_platforms,
                "files_compressed": files_compressed
            }

# --- SYSTEM STATE SERVICE ---
class SystemStateService:
    @staticmethod
    def get_value(key: str, default: str = None) -> str:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    @staticmethod
    def set_value(key: str, value: str):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    @classmethod
    def get_restart_count(cls) -> int:
        return int(cls.get_value("restart_count", "0"))

    @classmethod
    def increment_restart_count(cls):
        count = cls.get_restart_count() + 1
        cls.set_value("restart_count", count)

    @classmethod
    def get_crash_count(cls) -> int:
        return int(cls.get_value("crash_count", "0"))

    @classmethod
    def increment_crash_count(cls):
        count = cls.get_crash_count() + 1
        cls.set_value("crash_count", count)
