"""
Admin Service module for productivity_hub.

Handles admin authentication, system diagnostics, dashboard statistics, user ban/unban management,
broadcast messaging with safe API throttling, maintenance mode toggling, and disk usage checks.
"""

import os
import sys
import time
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from telegram import Bot
from telegram.error import Forbidden, BadRequest, TelegramError

from productivity_hub.config.settings import get_settings, Settings
from productivity_hub.database.database import get_db, DatabaseManager
from productivity_hub.database.models import User, LogEntry, BannedUser
from productivity_hub.services.queue_service import get_queue_service
from productivity_hub.services.cleanup_service import get_cleanup_service

logger = logging.getLogger("productivity_hub.services.admin")

# Process start time for uptime calculation
BOT_START_TIME = time.time()


class AdminService:
    """
    Business logic engine for administrator management and system diagnostics.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    async def is_admin(self, user_id: int) -> bool:
        """
        Check if a given user_id has admin or owner privileges.
        """
        try:
            if int(user_id) == int(self.settings.OWNER_ID):
                return True
        except (ValueError, TypeError):
            pass

        try:
            db = get_db()
            user = await db.get_user(user_id)
            if user and (user.is_admin or user.role in ("admin", "owner")):
                return True
        except Exception as e:
            logger.error(f"Error checking admin status for user {user_id}: {e}")

        return False

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Collect system diagnostic metrics (CPU, RAM, Queue, Active Tasks, Storage, Uptime, FFmpeg/yt-dlp status).
        """
        # Uptime
        elapsed_seconds = int(time.time() - BOT_START_TIME)
        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Queue & Task status
        queue_size = 0
        active_tasks = 0
        try:
            queue_svc = get_queue_service()
            queue_size = queue_svc.queue_size
            active_tasks = queue_svc.active_task_count
        except Exception:
            pass

        # Memory & Disk
        cpu_str = "N/A"
        ram_str = "N/A"
        try:
            import psutil
            cpu_str = f"{psutil.cpu_percent(interval=None)}%"
            ram_info = psutil.virtual_memory()
            ram_str = f"{ram_info.percent}% ({ram_info.used // (1024*1024)}MB / {ram_info.total // (1024*1024)}MB)"
        except ImportError:
            cpu_str = f"{os.cpu_count() or 1} Cores"

        # Storage
        total, used, free = shutil.disk_usage(".")
        used_gb = used / (1024 ** 3)
        total_gb = total / (1024 ** 3)
        pct_used = (used / total) * 100 if total > 0 else 0
        storage_str = f"{used_gb:.1f}GB / {total_gb:.1f}GB ({pct_used:.1f}%)"

        # Comprehensive external dependencies check
        from productivity_hub.utils.dependency_checker import get_dependency_checker
        checker = get_dependency_checker()

        return {
            "uptime": uptime_str,
            "cpu": cpu_str,
            "ram": ram_str,
            "queue_size": queue_size,
            "active_tasks": active_tasks,
            "storage": storage_str,
            "ffmpeg": "Available" if checker.has_ffmpeg() else "Not Found",
            "ffprobe": "Available" if checker.has_ffprobe() else "Not Found",
            "libreoffice": "Available" if checker.has_libreoffice() else "Not Found",
            "rembg": "Available" if checker.has_rembg() else "Not Found",
            "ytdlp": "Available" if checker.check_python_module("yt_dlp").available else "Not Found",
            "python_version": sys.version.split()[0],
        }

    async def get_dependencies_status(self) -> Dict[str, Any]:
        """Fetch system and python package dependencies diagnostic report."""
        from productivity_hub.utils.dependency_checker import get_dependency_checker
        diagnostics = get_dependency_checker().get_full_diagnostics()
        binaries = ("ffmpeg", "ffprobe", "soffice", "libreoffice", "gs", "pdftoppm", "7z", "unrar")
        return {
            "python_packages": {k: v.available for k, v in diagnostics.items() if k not in binaries},
            "system_binaries": {k: v.available for k, v in diagnostics.items() if k in binaries},
            "full_diagnostics": diagnostics,
        }

    async def get_users_summary(self) -> Dict[str, int]:
        """Fetch total users, banned users, and admin count."""
        db = get_db()
        async with db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM users") as c:
                total_users = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as c:
                banned_users = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 OR role = 'admin'") as c:
                admin_count = (await c.fetchone())[0]

        return {
            "total_users": total_users,
            "banned_users": banned_users,
            "admin_count": admin_count,
        }

    async def get_all_statistics(self) -> Dict[str, Any]:
        """Fetch global task, download, conversion, and QR stats."""
        db = get_db()
        async with db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM tasks") as c:
                total_tasks = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'") as c:
                completed_tasks = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'failed'") as c:
                failed_tasks = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM downloads") as c:
                total_downloads = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM conversions") as c:
                total_conversions = (await c.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM qr_history") as c:
                total_qr = (await c.fetchone())[0]

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "total_downloads": total_downloads,
            "total_conversions": total_conversions,
            "total_qr": total_qr,
        }

    async def ban_user(self, target_user_id: int, reason: str, admin_id: int) -> Tuple[bool, str]:
        """Ban user from bot access."""
        if target_user_id == self.settings.OWNER_ID:
            return False, "Cannot ban the bot owner."

        db = get_db()
        await db.set_user_ban_status(target_user_id, is_banned=True, reason=reason, banned_by=admin_id)
        await db.add_audit_log("WARNING", "admin", f"User {target_user_id} banned by admin {admin_id}. Reason: {reason}", user_id=target_user_id)
        logger.info(f"User {target_user_id} banned by admin {admin_id}")
        return True, f"User {target_user_id} has been banned."

    async def unban_user(self, target_user_id: int, admin_id: int) -> Tuple[bool, str]:
        """Unban user."""
        db = get_db()
        await db.set_user_ban_status(target_user_id, is_banned=False)
        await db.add_audit_log("INFO", "admin", f"User {target_user_id} unbanned by admin {admin_id}", user_id=target_user_id)
        logger.info(f"User {target_user_id} unbanned by admin {admin_id}")
        return True, f"User {target_user_id} has been unbanned."

    async def toggle_maintenance_mode(self) -> bool:
        """Toggle global maintenance mode status in DB settings and settings singleton."""
        db = get_db()
        current = await db.get_setting("maintenance_mode", "false")
        new_state = "false" if current.lower() == "true" else "true"
        await db.set_setting("maintenance_mode", new_state)

        # Update in-memory settings flag
        self.settings.MAINTENANCE_MODE = (new_state == "true")
        logger.info(f"Maintenance mode toggled to: {self.settings.MAINTENANCE_MODE}")
        return self.settings.MAINTENANCE_MODE

    async def is_maintenance_mode(self) -> bool:
        """Check if maintenance mode is active."""
        db = get_db()
        setting_val = await db.get_setting("maintenance_mode", "false")
        return setting_val.lower() == "true" or self.settings.MAINTENANCE_MODE

    async def get_storage_details(self) -> Dict[str, Any]:
        """Get disk usage metrics and temp directory size."""
        total, used, free = shutil.disk_usage(".")

        temp_dir = Path("temp")
        temp_size_bytes = 0
        if temp_dir.exists():
            for f in temp_dir.glob("**/*"):
                if f.is_file():
                    temp_size_bytes += f.stat().st_size

        return {
            "total_gb": total / (1024 ** 3),
            "used_gb": used / (1024 ** 3),
            "free_gb": free / (1024 ** 3),
            "pct_used": (used / total) * 100 if total > 0 else 0,
            "temp_mb": temp_size_bytes / (1024 * 1024),
        }

    async def trigger_manual_cleanup(self) -> Dict[str, Any]:
        """Run disk cleanup cycle manually."""
        try:
            cleanup_svc = get_cleanup_service()
            stats = await cleanup_svc.run_cleanup_cycle()
            return stats
        except Exception as e:
            logger.warning(f"Manual cleanup call failed or service not running: {e}")
            return {"deleted_files": 0, "freed_bytes": 0}


    async def get_recent_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Fetch latest audit and security logs from database."""
        db = get_db()
        async with db.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": r["id"],
                        "level": r["level"],
                        "logger_name": r["logger_name"],
                        "message": r["message"],
                        "user_id": r["user_id"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]

    async def broadcast_message(
        self,
        bot: Bot,
        message_text: str,
        admin_id: int
    ) -> Dict[str, int]:
        """
        Broadcast message to all registered users with safe rate throttling (~30 msgs/sec).
        Returns counts for total, sent, failed, and blocked users.
        """
        db = get_db()
        async with db.get_connection() as conn:
            async with conn.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                user_ids = [r[0] for r in rows]

        sent = 0
        failed = 0
        blocked = 0

        logger.info(f"Admin {admin_id} started broadcast to {len(user_ids)} users.")

        for uid in user_ids:
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=f"📢 <b>Announcement</b>\n\n{message_text}",
                    parse_mode="HTML"
                )
                sent += 1
            except Forbidden:
                blocked += 1
            except (BadRequest, TelegramError) as e:
                logger.warning(f"Broadcast failed for user {uid}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"Unexpected broadcast error for user {uid}: {e}")
                failed += 1

            # Throttle to avoid Telegram API rate limits (~30 msgs/sec -> 35ms sleep)
            await asyncio.sleep(0.035)

        await db.add_audit_log(
            "INFO",
            "admin",
            f"Broadcast completed: Total={len(user_ids)}, Sent={sent}, Blocked={blocked}, Failed={failed}",
            user_id=admin_id
        )

        return {
            "total": len(user_ids),
            "sent": sent,
            "blocked": blocked,
            "failed": failed,
        }


# Global AdminService singleton instance
_admin_service_instance: Optional[AdminService] = None


def get_admin_service() -> AdminService:
    """Retrieve global AdminService instance."""
    global _admin_service_instance
    if _admin_service_instance is None:
        _admin_service_instance = AdminService()
    return _admin_service_instance
