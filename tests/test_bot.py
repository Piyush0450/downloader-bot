import unittest
import asyncio
import time
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

# Override Environment variables for testing
os.environ["DATABASE_URL"] = "sqlite:///database/test_bot.db"
os.environ["BOT_TOKEN"] = "123456:ABCDEFabcdef123456"
os.environ["OWNER_ID"] = "12345"
os.environ["SECRET_KEY"] = "secure_secret_key_999"

from config.settings import DATABASE_DIR, MAX_FILE_SIZE_BYTES
from utils.helpers import format_size
from utils.validators import is_valid_url, validate_file_size
from utils.conversion_registry import get_conversion_targets
from services.text_service import to_sentence_case, remove_duplicate_lines, clean_text, pretty_print_json, get_text_stats
from services.database_service import (
    init_db, get_db, UserService, DownloadService, ConversionService, AdminService, StatisticsService
)
from services.queue_service import (
    enqueue_task, cancel_user_task, get_queue_stats, _active_tasks, _pending_queue, _user_cooldowns
)

def setUpModule():
    os.environ["DATABASE_URL"] = "sqlite:///database/test_bot.db"
    test_db = DATABASE_DIR / "test_bot.db"
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass
    init_db()

def tearDownModule():
    test_db = DATABASE_DIR / "test_bot.db"
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


class TestValidators(unittest.TestCase):
    def test_validators(self):
        self.assertTrue(is_valid_url("https://youtube.com/watch?v=123"))
        self.assertTrue(is_valid_url("https://tiktok.com/@user/video/123"))
        self.assertFalse(is_valid_url("https://malicious.org"))
        
        self.assertTrue(validate_file_size(1024 * 1024))
        self.assertFalse(validate_file_size(MAX_FILE_SIZE_BYTES + 100))


class TestConversionRegistry(unittest.TestCase):
    def test_matrix_targets(self):
        docx_targets = get_conversion_targets("docx")
        self.assertEqual(docx_targets, ["pdf", "txt", "rtf", "odt", "html", "epub"])
        
        png_targets = get_conversion_targets("png")
        self.assertEqual(png_targets, ["jpg", "webp", "bmp", "tiff", "ico", "pdf"])
        
        self.assertEqual(get_conversion_targets("invalid"), [])


class TestTextService(unittest.TestCase):
    def test_sentence_case(self):
        raw = "hello world! this is a test. multiple sentences? yes."
        expected = "Hello world! This is a test. Multiple sentences? Yes."
        self.assertEqual(to_sentence_case(raw), expected)

    def test_clean_text(self):
        self.assertEqual(clean_text("  <div>Hello</div>   world  "), "Hello world")

    def test_json_pretty(self):
        raw = '{"a":1,"b":2}'
        self.assertIn("{\n    \"a\": 1", pretty_print_json(raw))


class TestSqlite3Services(unittest.TestCase):
    def test_user_service(self):
        user_id = 777888
        # Create
        user = UserService.get_or_create_user(user_id, "bob_builder", "Bob")
        self.assertEqual(user["first_name"], "Bob")
        self.assertEqual(user["is_banned"], 0)
        
        # Seen
        UserService.update_last_seen(user_id)
        
        # Ban
        self.assertFalse(UserService.is_banned(user_id))
        self.assertTrue(UserService.ban_user(user_id))
        self.assertTrue(UserService.is_banned(user_id))
        self.assertTrue(UserService.unban_user(user_id))
        self.assertFalse(UserService.is_banned(user_id))

    def test_log_actions(self):
        user_id = 777888
        # Ensure user exists for this test
        UserService.get_or_create_user(user_id, "bob_builder", "Bob")
        
        DownloadService.log_download(user_id, "https://x.com/post/1", "Twitter", "Post Title", "VIDEO", "720p", 4096)
        ConversionService.log_conversion(user_id, "notes.txt", "txt", "pdf", 2048)
        ConversionService.log_qr(user_id, "SCAN")
        UserService.add_storage_saved(user_id, 1024)
        
        stats = StatisticsService.get_user_stats(user_id)
        self.assertEqual(stats["downloads"], 1)
        self.assertEqual(stats["conversions"], 1)
        self.assertEqual(stats["files_processed"], 3)
        self.assertEqual(stats["storage_saved_bytes"], 1024)
        
        history = StatisticsService.get_user_history(user_id, limit=5)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["type"], "conversion")
        self.assertEqual(history[1]["type"], "download")

        # Global stats checks
        glob = StatisticsService.get_global_stats()
        self.assertGreaterEqual(glob["total_users"], 1)
        self.assertEqual(glob["total_downloads"], 1)
        self.assertEqual(glob["total_conversions"], 1)

    def test_admin_service(self):
        user_id = 999111
        self.assertFalse(AdminService.is_admin(user_id))
        self.assertTrue(AdminService.add_admin(user_id, "ADMIN"))
        self.assertEqual(AdminService.is_admin(user_id), "ADMIN")
        
        self.assertEqual(AdminService.get_suspicious(user_id), 0)
        AdminService.track_suspicious(user_id)
        self.assertEqual(AdminService.get_suspicious(user_id), 1)


class TestQueueAndCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_queue_scheduler_concurrency(self):
        """Test that only 2 tasks run concurrently and extra tasks are enqueued."""
        # Reset queue states
        _active_tasks.clear()
        _pending_queue.clear()
        
        task_runs = []
        async def dummy_task(duration, name):
            task_runs.append(f"{name}_start")
            await asyncio.sleep(duration)
            task_runs.append(f"{name}_end")
            return name
            
        mock_bot = object()
        
        # Enqueue 3 tasks with different user IDs to bypass per-user spam limits
        t1, pos1, w1 = await enqueue_task(111, mock_bot, 999, "Task 1", dummy_task, 0.1, "T1")
        t2, pos2, w2 = await enqueue_task(222, mock_bot, 999, "Task 2", dummy_task, 0.1, "T2")
        t3, pos3, w3 = await enqueue_task(333, mock_bot, 999, "Task 3", dummy_task, 0.1, "T3")
        
        # T1 and T2 must start immediately (position = 0)
        self.assertEqual(pos1, 0)
        self.assertEqual(pos2, 0)
        # T3 must be queued (position = 1)
        self.assertEqual(pos3, 1)
        self.assertGreaterEqual(w3, 1)
        
        # Check running sizes
        stats = get_queue_stats()
        self.assertEqual(stats["active"], 2)
        self.assertEqual(stats["pending"], 1)
        
        # Let T1 and T2 run
        await asyncio.sleep(0.05)
        # Check that T1 and T2 have started, but not T3
        self.assertIn("T1_start", task_runs)
        self.assertIn("T2_start", task_runs)
        self.assertNotIn("T3_start", task_runs)
        
        # Await first task futures
        await t1.future
        await t2.future
        
        # Let loop switch context to trigger next task queue processing
        await asyncio.sleep(0.05)
        
        # Now T3 must have started and finished
        await t3.future
        self.assertIn("T3_start", task_runs)
        self.assertIn("T3_end", task_runs)

    async def test_limits_and_cooldowns(self):
        # Reset queue states
        _active_tasks.clear()
        _pending_queue.clear()
        _user_cooldowns.clear()
        
        mock_bot = object()
        user_id = 222
        
        async def dummy():
            await asyncio.sleep(0.5)
            
        # 1. Enqueue task succeeds
        task1, pos1, w1 = await enqueue_task(user_id, mock_bot, 999, "Task 1", dummy)
        self.assertEqual(pos1, 0)
        
        # 2. Cooldown check: subsequent task within 10s should raise ValueError
        with self.assertRaises(ValueError) as context:
            await enqueue_task(user_id, mock_bot, 999, "Task 2", dummy)
        self.assertIn("Please wait", str(context.exception))
        
        # 3. Simulate cooldown expired (reset) and test active task limit (max 1 active task)
        _user_cooldowns.clear()
        with self.assertRaises(ValueError) as context:
            await enqueue_task(user_id, mock_bot, 999, "Task 2", dummy)
        self.assertIn("Please wait", str(context.exception))
        
        # Cancel task1 to free user active slot
        task1.future.set_result(None)
        await asyncio.sleep(0.01)

    async def test_cancellation(self):
        _active_tasks.clear()
        _pending_queue.clear()
        _user_cooldowns.clear()
        
        mock_bot = object()
        user_id = 333
        
        task_executed = False
        async def cancel_test_task():
            nonlocal task_executed
            try:
                await asyncio.sleep(1.0)
                task_executed = True
            except asyncio.CancelledError:
                task_executed = False
                raise
                
        # Enqueue active
        task, pos, w = await enqueue_task(user_id, mock_bot, 999, "Cancellable", cancel_test_task)
        self.assertEqual(pos, 0)
        
        # Let it start processing
        await asyncio.sleep(0.05)
        self.assertEqual(task.status, "PROCESSING")
        
        # Cancel
        cancelled = cancel_user_task(user_id)
        self.assertTrue(cancelled)
        
        # Await future expecting CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await task.future
            
        self.assertEqual(task.status, "CANCELLED")
        self.assertFalse(task_executed)
        
        # Verify queue cleaned up
        stats = get_queue_stats()
        self.assertEqual(stats["active"], 0)


class TestPart4Operations(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Ensure dummy environment variables are set before bot imports
        os.environ["BOT_TOKEN"] = "123456:ABCDEFabcdef123456"
        os.environ["OWNER_ID"] = "12345"
        os.environ["SECRET_KEY"] = "secure_secret_key_999"

    def test_system_state_service(self):
        from services.database_service import SystemStateService
        
        # Reset table value
        SystemStateService.set_value("restart_count", "0")
        SystemStateService.set_value("crash_count", "0")
        
        self.assertEqual(SystemStateService.get_restart_count(), 0)
        self.assertEqual(SystemStateService.get_crash_count(), 0)
        
        SystemStateService.increment_restart_count()
        self.assertEqual(SystemStateService.get_restart_count(), 1)
        
        SystemStateService.increment_crash_count()
        self.assertEqual(SystemStateService.get_crash_count(), 1)
        
        SystemStateService.increment_restart_count()
        SystemStateService.increment_crash_count()
        self.assertEqual(SystemStateService.get_restart_count(), 2)
        self.assertEqual(SystemStateService.get_crash_count(), 2)

    def test_backup_service(self):
        import services.backup_service as bs
        from pathlib import Path
        import zipfile
        
        # Point BACKUPS_DIR to a temporary folder
        test_backups_dir = Path("database/test_backups")
        test_backups_dir.mkdir(exist_ok=True)
        original_backups_dir = bs.BACKUPS_DIR
        bs.BACKUPS_DIR = test_backups_dir
        
        try:
            success = bs.run_backup()
            self.assertTrue(success)
            
            backups = list(test_backups_dir.glob("backup_*.zip"))
            self.assertEqual(len(backups), 1)
            
            with zipfile.ZipFile(backups[0], 'r') as zf:
                namelist = zf.namelist()
                # Should contain database
                self.assertTrue(any(name.startswith("database/") for name in namelist))
        finally:
            # Cleanup
            for f in test_backups_dir.glob("*"):
                f.unlink()
            if test_backups_dir.exists():
                test_backups_dir.rmdir()
            bs.BACKUPS_DIR = original_backups_dir

    async def test_security_service_record_suspicious_event(self):
        from services.security_service import record_suspicious_event
        from services.database_service import AdminService, UserService, get_db
        import unittest.mock as mock
        
        user_id = 999222
        mock_user = mock.MagicMock()
        mock_user.id = user_id
        mock_user.first_name = "Hackerman"
        
        mock_update = mock.MagicMock()
        mock_update.effective_user = mock_user
        mock_update.message = mock.AsyncMock()
        
        mock_context = mock.MagicMock()
        
        # Reset any pre-existing suspicious records/ban state for this user
        with get_db() as conn:
            conn.execute("DELETE FROM suspicious_users WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            
        UserService.get_or_create_user(user_id, "hackerman", "Hackerman")
            
        # Attempt 1: Count becomes 1 (no warning/ban yet)
        await record_suspicious_event(mock_update, mock_context, "Unauthorized action")
        self.assertEqual(AdminService.get_suspicious(user_id), 1)
        self.assertFalse(UserService.is_banned(user_id))
        mock_update.message.reply_text.assert_not_called()
        
        # Attempt 2: Count becomes 2
        await record_suspicious_event(mock_update, mock_context, "Unauthorized action")
        self.assertEqual(AdminService.get_suspicious(user_id), 2)
        mock_update.message.reply_text.assert_not_called()
        
        # Attempt 3: Count becomes 3 (SUSPICIOUS_WARN_THRESHOLD) -> Should send warning message
        await record_suspicious_event(mock_update, mock_context, "Unauthorized action")
        self.assertEqual(AdminService.get_suspicious(user_id), 3)
        self.assertFalse(UserService.is_banned(user_id))
        mock_update.message.reply_text.assert_called_once()
        self.assertIn("Security Warning", mock_update.message.reply_text.call_args[0][0])
        
        # Attempt 4: Count becomes 4
        mock_update.message.reply_text.reset_mock()
        await record_suspicious_event(mock_update, mock_context, "Unauthorized action")
        self.assertEqual(AdminService.get_suspicious(user_id), 4)
        self.assertFalse(UserService.is_banned(user_id))
        mock_update.message.reply_text.assert_called_once()
        
        # Attempt 5: Count becomes 5 (SUSPICIOUS_BAN_THRESHOLD) -> Should ban user and send ban message
        mock_update.message.reply_text.reset_mock()
        await record_suspicious_event(mock_update, mock_context, "Unauthorized action")
        self.assertEqual(AdminService.get_suspicious(user_id), 5)
        self.assertTrue(UserService.is_banned(user_id))
        mock_update.message.reply_text.assert_called_once()
        self.assertIn("Access Revoked", mock_update.message.reply_text.call_args[0][0])

    async def test_admin_protection_from_ban(self):
        from services.database_service import UserService, AdminService, get_db
        from services.security_service import record_unauthorized_attempt, record_suspicious_event
        import unittest.mock as mock

        owner_id = 12345
        admin_id = 999333

        # Setup database
        with get_db() as conn:
            conn.execute("DELETE FROM admins WHERE user_id = ?", (admin_id,))
            conn.execute("DELETE FROM users WHERE user_id in (?, ?)", (owner_id, admin_id))
            conn.commit()

        UserService.get_or_create_user(owner_id, "owner", "Owner")
        UserService.get_or_create_user(admin_id, "admin", "Admin")
        AdminService.add_admin(admin_id, "ADMIN")

        # 1. Database-level ban checks
        self.assertFalse(UserService.ban_user(owner_id))
        self.assertFalse(UserService.is_banned(owner_id))

        self.assertFalse(UserService.ban_user(admin_id))
        self.assertFalse(UserService.is_banned(admin_id))

        # 2. Security-level unauthorized attempt checks
        self.assertFalse(record_unauthorized_attempt(owner_id))
        self.assertFalse(record_unauthorized_attempt(admin_id))

        # 3. Security-level suspicious event checks
        mock_user = mock.MagicMock()
        mock_user.id = admin_id
        mock_user.first_name = "Admin"
        
        mock_update = mock.MagicMock()
        mock_update.effective_user = mock_user
        mock_update.message = mock.AsyncMock()
        mock_context = mock.MagicMock()

        await record_suspicious_event(mock_update, mock_context, "Attempting high load operation")
        self.assertFalse(UserService.is_banned(admin_id))
        self.assertEqual(AdminService.get_suspicious(admin_id), 0)

    def test_validate_startup_success(self):
        from services.startup_service import validate_startup
        import unittest.mock as mock
        
        with mock.patch("services.startup_service.BOT_TOKEN", "123456:mock_token"), \
             mock.patch("services.startup_service.OWNER_ID", 12345), \
             mock.patch("services.startup_service.SECRET_KEY", "highly_secure_non_default_secret_key_123"), \
             mock.patch("services.startup_service.BOT_MODE", "polling"):
            try:
                validate_startup()
            except SystemExit:
                self.fail("validate_startup raised SystemExit unexpectedly on valid config")
                
    def test_validate_startup_failures(self):
        from services.startup_service import validate_startup
        import unittest.mock as mock
        
        # 1. Missing BOT_TOKEN
        with mock.patch("services.startup_service.BOT_TOKEN", None), \
             mock.patch("services.startup_service.OWNER_ID", 12345), \
             mock.patch("services.startup_service.SECRET_KEY", "secure_secret_key"):
            with self.assertRaises(SystemExit) as cm:
                validate_startup()
            self.assertEqual(cm.exception.code, 1)
            
        # 2. Missing OWNER_ID
        with mock.patch("services.startup_service.BOT_TOKEN", "123:token"), \
             mock.patch("services.startup_service.OWNER_ID", 0), \
             mock.patch("services.startup_service.SECRET_KEY", "secure_secret_key"):
            with self.assertRaises(SystemExit) as cm:
                validate_startup()
            self.assertEqual(cm.exception.code, 1)

        # 3. Default/insecure SECRET_KEY
        with mock.patch("services.startup_service.BOT_TOKEN", "123:token"), \
             mock.patch("services.startup_service.OWNER_ID", 12345), \
             mock.patch("services.startup_service.SECRET_KEY", "productivity_hub_default_secret"):
            with self.assertRaises(SystemExit) as cm:
                validate_startup()
            self.assertEqual(cm.exception.code, 1)

if __name__ == "__main__":
    unittest.main()
