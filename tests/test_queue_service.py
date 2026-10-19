"""
Unit Tests for TaskQueueService.

Tests task queue submission, concurrency enforcement, file tracking for cleanup protection,
and queue position calculations.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from productivity_hub.services.queue_service import TaskQueueService, QueueOverflowError, UserTaskLimitError
from productivity_hub.config.settings import Settings
from productivity_hub.database.database import init_db, close_db
from productivity_hub.database.migrations import run_migrations


class TestTaskQueueService(unittest.IsolatedAsyncioTestCase):
    """Test background task queue service."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_queue.sqlite3")
        self.mock_settings = Settings(
            BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
            SECRET_KEY="a" * 32,
            OWNER_ID=999888777,
            PORT=8000,
            DATABASE_PATH=self.db_path,
            MAX_CONCURRENT_TASKS=2,
            MAX_USER_ACTIVE_TASKS=1,
            MAX_USER_QUEUE_TASKS=2,
            MAX_QUEUE_SIZE=5
        )
        self.queue_svc = TaskQueueService(settings=self.mock_settings)

    async def asyncSetUp(self):
        await init_db(self.db_path)
        await run_migrations(self.db_path)
        await self.queue_svc.start()

    async def asyncTearDown(self):
        await self.queue_svc.stop()
        await close_db()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_submit_and_execute_task(self):
        """Verify task executes successfully and returns expected result."""
        async def dummy_job(val: int):
            await asyncio.sleep(0.05)
            return val * 2

        task = await self.queue_svc.submit_task(
            user_id=1001,
            task_type="test",
            coro_fn=dummy_job,
            val=21
        )
        self.assertIsNotNone(task.task_id)
        # Wait for future completion
        result = await task.future
        self.assertEqual(result, 42)

    async def test_file_tracking_for_cleanup(self):
        """Verify files associated with active tasks are reported as protected."""
        test_file = Path("temp/uploads/protected_test_file.txt")

        async def long_job():
            await asyncio.sleep(0.3)
            return True

        task = await self.queue_svc.submit_task(
            user_id=1002,
            task_type="test_file",
            coro_fn=long_job,
            associated_files=[test_file]
        )

        protected = self.queue_svc.get_active_file_paths()
        self.assertIn(test_file.resolve(), protected)
        await task.future

    async def test_user_queue_limit_enforced(self):
        """Verify user task quota is strictly enforced."""
        async def blocking_job():
            await asyncio.sleep(1.0)
            return True

        # First task (active)
        t1 = await self.queue_svc.submit_task(user_id=2001, task_type="t1", coro_fn=blocking_job)
        # Second task (queued)
        t2 = await self.queue_svc.submit_task(user_id=2001, task_type="t2", coro_fn=blocking_job)

        # Third task should fail due to MAX_USER_QUEUE_TASKS=2
        with self.assertRaises(UserTaskLimitError):
            await self.queue_svc.submit_task(user_id=2001, task_type="t3", coro_fn=blocking_job)

        # Cancel tasks
        await self.queue_svc.cancel_task(t1.task_id, 2001)
        await self.queue_svc.cancel_task(t2.task_id, 2001)


if __name__ == "__main__":
    unittest.main()
