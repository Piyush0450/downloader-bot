"""
Unit Tests for Automatic Temporary Storage Cleanup Service.

Tests safety boundaries (never delete outside temp, never delete .gitkeep or database files),
safe file deletion, active task dependency protection, cancellation/failure cleanup,
startup cleanup sweep, and periodic retention expiration.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from productivity_hub.services.cleanup_service import (
    CLEANUP_DIRECTORIES,
    is_safe_temp_file,
    safe_delete_file,
    safe_delete_files,
    run_startup_cleanup,
    CleanupService
)
from productivity_hub.services.queue_service import TaskQueueService, init_queue_service
from productivity_hub.config.settings import Settings
from productivity_hub.database.database import init_db, close_db
from productivity_hub.database.migrations import run_migrations


class TestCleanupService(unittest.IsolatedAsyncioTestCase):
    """Test suite for temporary file cleanup and active task locking."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_cleanup.sqlite3")
        self.mock_settings = Settings(
            BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
            SECRET_KEY="a" * 32,
            OWNER_ID=999888777,
            PORT=8000,
            DATABASE_PATH=self.db_path,
            TEMP_RETENTION_MINUTES=5,
            MAX_CONCURRENT_TASKS=2,
            MAX_USER_ACTIVE_TASKS=2,
            MAX_USER_QUEUE_TASKS=5,
            MAX_QUEUE_SIZE=10
        )
        self.queue_svc = TaskQueueService(settings=self.mock_settings)

        # Ensure temp subdirectories exist for testing
        for d in CLEANUP_DIRECTORIES:
            d.mkdir(parents=True, exist_ok=True)

    async def asyncSetUp(self):
        await init_db(self.db_path)
        await run_migrations(self.db_path)
        await self.queue_svc.start()

    async def asyncTearDown(self):
        await self.queue_svc.stop()
        await close_db()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_safe_temp_file_boundaries(self):
        """Verify strict directory boundaries and refusal of system/database/.gitkeep files."""
        # 1. Valid temp files
        valid_file = Path("temp/uploads/sample_upload_123.jpg")
        self.assertTrue(is_safe_temp_file(valid_file))

        valid_converted = Path("temp/converted/output_doc.pdf")
        self.assertTrue(is_safe_temp_file(valid_converted))

        # 2. Critical .gitkeep files must NEVER be considered safe for deletion
        gitkeep = Path("temp/uploads/.gitkeep")
        self.assertFalse(is_safe_temp_file(gitkeep))

        # 3. Directories themselves must not be deleted as files
        self.assertFalse(is_safe_temp_file(Path("temp/uploads")))

        # 4. Critical project files outside temp
        self.assertFalse(is_safe_temp_file(Path("productivity_hub/bot.py")))
        self.assertFalse(is_safe_temp_file(Path("database/app.sqlite3")))
        self.assertFalse(is_safe_temp_file(Path(".env")))
        self.assertFalse(is_safe_temp_file(Path("requirements.txt")))
        self.assertFalse(is_safe_temp_file(None))

    def test_safe_delete_file_success_and_safety(self):
        """Verify safe deletion unlinks valid temp files and rejects unsafe paths."""
        # Create a temp file
        test_file = Path("temp/uploads/test_delete_me.txt")
        test_file.write_text("temporary data")
        self.assertTrue(test_file.exists())

        # Safely delete
        deleted = safe_delete_file(test_file, log_msg="test deletion")
        self.assertTrue(deleted)
        self.assertFalse(test_file.exists())

        # Attempt to delete non-existent file
        self.assertFalse(safe_delete_file(test_file))

        # Attempt to delete critical non-temp file (safety boundary)
        dummy_code = Path(self.temp_dir) / "critical_code.py"
        dummy_code.write_text("print('critical')")
        self.assertFalse(safe_delete_file(dummy_code))
        self.assertTrue(dummy_code.exists())

    async def test_active_task_dependency_locks_file(self):
        """
        Verify that if a file is needed by an active task, it is NOT deleted
        until that task finishes (Requirement 9).
        """
        shared_file = Path("temp/uploads/shared_active_file.pdf")
        shared_file.write_text("important data in use")

        # Set up global queue service for is_file_in_use_by_other_tasks
        import productivity_hub.services.queue_service as qs_mod
        original_inst = qs_mod._queue_service_instance
        qs_mod._queue_service_instance = self.queue_svc

        try:
            async def worker_job():
                await asyncio.sleep(0.4)
                return True

            # Submit task referencing shared_file
            task = await self.queue_svc.submit_task(
                user_id=888,
                task_type="conversion",
                coro_fn=worker_job,
                associated_files=[shared_file]
            )

            # Attempt deletion without excluding this task -> Must be blocked!
            deleted = safe_delete_file(shared_file, exclude_task_id=None)
            self.assertFalse(deleted)
            self.assertTrue(shared_file.exists())

            # Attempt deletion excluding task_id -> allowed since no other task holds it
            deleted_with_exclude = safe_delete_file(shared_file, exclude_task_id=task.task_id)
            self.assertTrue(deleted_with_exclude)
            self.assertFalse(shared_file.exists())

            await task.future
        finally:
            qs_mod._queue_service_instance = original_inst

    async def test_multi_task_dependency_lock(self):
        """
        Verify that if TWO active tasks depend on the same file, neither can delete it
        until both have completed (Requirement 9).
        """
        multi_file = Path("temp/uploads/multi_dependent_file.jpg")
        multi_file.write_text("multi task data")

        import productivity_hub.services.queue_service as qs_mod
        original_inst = qs_mod._queue_service_instance
        qs_mod._queue_service_instance = self.queue_svc

        try:
            async def slow_job():
                await asyncio.sleep(0.4)
                return True

            task1 = await self.queue_svc.submit_task(
                user_id=101,
                task_type="task1",
                coro_fn=slow_job,
                associated_files=[multi_file]
            )
            task2 = await self.queue_svc.submit_task(
                user_id=102,
                task_type="task2",
                coro_fn=slow_job,
                associated_files=[multi_file]
            )

            # Task 1 tries to delete its file, but Task 2 also needs it!
            deleted_by_t1 = safe_delete_file(multi_file, exclude_task_id=task1.task_id)
            self.assertFalse(deleted_by_t1)
            self.assertTrue(multi_file.exists(), "File should remain alive while Task 2 is active!")

            # Wait for tasks to complete
            await task1.future
            await task2.future

            # Now both tasks are done, file can be deleted
            deleted_final = safe_delete_file(multi_file, log_msg="post completion")
            self.assertTrue(deleted_final)
            self.assertFalse(multi_file.exists())
        finally:
            qs_mod._queue_service_instance = original_inst

    async def test_task_cancellation_immediate_cleanup(self):
        """Verify temporary files are immediately removed upon task cancellation (Requirement 5)."""
        temp_input = Path("temp/uploads/cancel_me_input.mp4")
        temp_input.write_text("video payload")

        import productivity_hub.services.queue_service as qs_mod
        original_inst = qs_mod._queue_service_instance
        qs_mod._queue_service_instance = self.queue_svc

        try:
            async def blocking_job():
                await asyncio.sleep(5.0)
                return True

            task = await self.queue_svc.submit_task(
                user_id=999,
                task_type="download",
                coro_fn=blocking_job,
                associated_files=[temp_input]
            )
            self.assertTrue(temp_input.exists())

            # Cancel task
            cancelled = await self.queue_svc.cancel_task(task.task_id, 999)
            self.assertTrue(cancelled)

            # Input file must be immediately cleaned up!
            self.assertFalse(temp_input.exists(), "Temporary file was not cleaned up upon cancellation!")
        finally:
            qs_mod._queue_service_instance = original_inst

    async def test_startup_cleanup_sweep(self):
        """
        Verify startup cleanup sweep removes stale abandoned files while strictly
        preserving .gitkeep files (Requirements 6, 7, 10).
        """
        stale_file = Path("temp/uploads/stale_from_prior_session.tmp")
        stale_file.write_text("stale data from prior render crash")

        # Create .gitkeep file
        gitkeep = Path("temp/uploads/.gitkeep")
        gitkeep.touch()

        self.assertTrue(stale_file.exists())
        self.assertTrue(gitkeep.exists())

        # Run startup sweep
        purged = await run_startup_cleanup()
        self.assertGreaterEqual(purged, 1)

        # Stale file must be unlinked
        self.assertFalse(stale_file.exists())
        # .gitkeep must be preserved!
        self.assertTrue(gitkeep.exists())

    async def test_periodic_cleanup_sweep(self):
        """Verify CleanupService purges expired files older than retention seconds."""
        service = CleanupService(retention_minutes=0, check_interval_seconds=60, settings=self.mock_settings)

        expired_file = Path("temp/converted/expired_old_file.pdf")
        expired_file.write_text("old file")

        # Artificially set mtime to 1 hour in the past
        old_time = time.time() - 3600
        os.utime(expired_file, (old_time, old_time))

        deleted = await service.run_cleanup_now()
        self.assertGreaterEqual(deleted, 1)
        self.assertFalse(expired_file.exists())


if __name__ == "__main__":
    unittest.main()
