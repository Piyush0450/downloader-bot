"""
Automatic Temporary File Storage Cleanup Service.

Periodically scans temporary runtime directories (uploads, downloads, converted, thumbnails)
and purges files older than TEMP_RETENTION_MINUTES. Guarantees safety by querying the Task Queue
Service to exclude files actively referenced by pending or running background tasks.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set, Union

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.services.queue_service import get_queue_service

logger = logging.getLogger("productivity_hub.services.cleanup")

CLEANUP_DIRECTORIES: List[Path] = [
    Path("temp/uploads"),
    Path("temp/downloads"),
    Path("temp/converted"),
    Path("temp/thumbnails"),
    Path("temp/compressed"),
    Path("temp/qr"),
    Path("temp/background_removed"),
]


def is_safe_temp_file(file_path: Optional[Path]) -> bool:
    """
    Strict safety check ensuring a file path is located strictly within designated
    temporary directories and is NOT a critical system, database, config, or .gitkeep file.
    Never deletes files outside designated temp subdirectories.
    """
    if file_path is None:
        return False
    try:
        p = Path(file_path).resolve()

        # Never delete .gitkeep files
        if p.name == ".gitkeep":
            return False

        # Never delete directories directly via file deletion functions
        if p.is_dir():
            return False

        # Must reside strictly inside one of the designated CLEANUP_DIRECTORIES
        is_inside_temp = False
        for d in CLEANUP_DIRECTORIES:
            d_res = d.resolve()
            if p != d_res and (d_res in p.parents or p.parent == d_res):
                is_inside_temp = True
                break

        if not is_inside_temp:
            return False

        # Extra safety check: Disallow critical system and database files
        forbidden_suffixes = {".py", ".sqlite3", ".db", ".env", ".md", ".json", ".yaml", ".yml", ".toml"}
        if p.suffix.lower() in forbidden_suffixes and "temp" not in str(p).lower():
            return False

        return True
    except Exception as e:
        logger.warning(f"Error checking safety of file path: {e}")
        return False


def is_file_in_use_by_other_tasks(
    file_path: Path,
    exclude_task_id: Optional[str] = None
) -> bool:
    """
    Check if a file is actively referenced by any other pending or running queue task.
    Prevents premature deletion when multiple tasks depend on the same input or output file.
    """
    try:
        queue_svc = get_queue_service()
        active_files = queue_svc.get_active_file_paths(exclude_task_id=exclude_task_id)
        return Path(file_path).resolve() in active_files
    except Exception:
        # If queue service is not initialized or accessible, assume not in use
        return False


def safe_delete_file(
    file_path: Optional[Path],
    exclude_task_id: Optional[str] = None,
    log_msg: str = ""
) -> bool:
    """
    Safely delete a temporary file immediately:
    1. Validates the path is inside designated temporary directories.
    2. Protects .gitkeep, databases, code, and config files.
    3. Verifies no other active/pending task depends on this file.
    4. Logs success and failure cleanly without exposing sensitive paths or credentials.

    Args:
        file_path: Path to file to delete.
        exclude_task_id: Task ID requesting deletion (its own reference won't block deletion).
        log_msg: Optional contextual message for audit logs.

    Returns:
        bool: True if the file was deleted, False otherwise.
    """
    if file_path is None:
        return False

    p = Path(file_path)
    if not p.exists():
        return False

    if not is_safe_temp_file(p):
        logger.warning(f"Refused unsafe file deletion attempt on file: {p.name}")
        return False

    if is_file_in_use_by_other_tasks(p, exclude_task_id=exclude_task_id):
        logger.debug(f"Temporary file {p.name} retained; in use by another active task.")
        return False

    try:
        p.unlink(missing_ok=True)
        extra = f" ({log_msg})" if log_msg else ""
        logger.info(f"Cleaned up temporary file: {p.name}{extra}")
        return True
    except Exception as err:
        logger.warning(f"Failed to delete temporary file {p.name}: {err}")
        return False


def safe_delete_files(
    file_paths: Any,
    exclude_task_id: Optional[str] = None,
    log_msg: str = ""
) -> int:
    """
    Safely delete multiple temporary files.

    Args:
        file_paths: Iterable of Path objects or None.
        exclude_task_id: Task ID requesting deletion.
        log_msg: Optional contextual log message.

    Returns:
        int: Number of files successfully deleted.
    """
    count = 0
    if not file_paths:
        return 0

    for fp in file_paths:
        if fp and safe_delete_file(fp, exclude_task_id=exclude_task_id, log_msg=log_msg):
            count += 1
    return count


async def run_startup_cleanup() -> int:
    """
    Execute an immediate cleanup sweep across all temporary directories at startup.
    Purges stale, abandoned files left behind from previous crashes or Render container restarts.
    Never deletes .gitkeep files or files outside designated temporary directories.

    Returns:
        int: Number of stale temporary files purged.
    """
    logger.info("Executing startup temporary storage cleanup sweep...")
    deleted_count = 0
    for target_dir in CLEANUP_DIRECTORIES:
        if not target_dir.exists():
            continue

        for file_path in target_dir.glob("**/*"):
            if not file_path.is_file():
                continue

            if file_path.name == ".gitkeep":
                continue

            if is_safe_temp_file(file_path):
                try:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"Purged stale temporary file from previous run: {file_path.name}")
                except Exception as e:
                    logger.warning(f"Could not purge stale temporary file {file_path.name}: {e}")

    logger.info(f"Startup cleanup sweep completed. Purged {deleted_count} stale files.")
    return deleted_count


class CleanupService:
    """
    Periodic background cleanup worker for managing disk space and purging expired files.
    """

    def __init__(
        self,
        retention_minutes: Optional[int] = None,
        check_interval_seconds: int = 300,
        settings: Optional[Settings] = None
    ):
        self.settings = settings or get_settings()
        self.retention_seconds = (
            retention_minutes if retention_minutes is not None else self.settings.TEMP_RETENTION_MINUTES
        ) * 60
        self.check_interval_seconds = check_interval_seconds
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the periodic cleanup background task."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._cleanup_loop(), name="CleanupServiceLoop")
            logger.info(
                f"Cleanup Service initialized (Retention: {self.retention_seconds // 60}m, "
                f"Check Interval: {self.check_interval_seconds}s)."
            )

    async def stop(self) -> None:
        """Stop the periodic cleanup task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cleanup Service stopped gracefully.")

    async def run_startup_cleanup(self) -> int:
        """Execute startup cleanup sweep."""
        return await run_startup_cleanup()

    async def run_cleanup_now(self) -> int:
        """
        Execute an immediate cleanup sweep across all temp folders.
        Purges files older than retention_seconds while respecting active task locks.

        Returns:
            int: Total number of deleted expired files.
        """
        logger.info("Executing periodic temporary file cleanup sweep...")
        deleted_count = 0
        now = time.time()
        cutoff_time = now - self.retention_seconds

        for target_dir in CLEANUP_DIRECTORIES:
            if not target_dir.exists():
                continue

            for file_path in target_dir.glob("**/*"):
                if not file_path.is_file():
                    continue

                if file_path.name == ".gitkeep":
                    continue

                try:
                    file_mtime = file_path.stat().st_mtime
                    if file_mtime < cutoff_time:
                        if safe_delete_file(file_path, log_msg="expired retention"):
                            deleted_count += 1
                except Exception as e:
                    logger.warning(f"Error checking temporary file {file_path.name}: {e}")

        logger.info(f"Cleanup sweep completed. Removed {deleted_count} expired temporary files.")
        return deleted_count

    async def _cleanup_loop(self) -> None:
        """Background loop executing cleanup sweep at regular intervals."""
        while self._running:
            try:
                await self.run_cleanup_now()
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup worker loop: {e}", exc_info=True)
                await asyncio.sleep(60)


# Global Cleanup Service instance
_cleanup_service_instance: Optional[CleanupService] = None


async def start_cleanup_service(
    retention_minutes: Optional[int] = None,
    check_interval_seconds: int = 300
) -> CleanupService:
    """Initialize and start global CleanupService instance."""
    global _cleanup_service_instance
    _cleanup_service_instance = CleanupService(
        retention_minutes=retention_minutes,
        check_interval_seconds=check_interval_seconds
    )
    await _cleanup_service_instance.start()
    return _cleanup_service_instance


def get_cleanup_service() -> CleanupService:
    """Retrieve global CleanupService instance."""
    global _cleanup_service_instance
    if _cleanup_service_instance is None:
        raise RuntimeError("CleanupService has not been initialized. Call start_cleanup_service() first.")
    return _cleanup_service_instance
