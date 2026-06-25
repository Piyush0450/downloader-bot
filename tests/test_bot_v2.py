import unittest
import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

# Set env before importing settings
import os
os.environ["DATABASE_URL"] = "sqlite:///database/test_bot_v2.db"
os.environ["BOT_TOKEN"] = "123456:ABCDEFabcdef123456"
os.environ["OWNER_ID"] = "12345"
os.environ["SECRET_KEY"] = "secure_secret_key_999"

from config.settings import MAX_FILE_SIZE_BYTES
from utils.helpers import format_size
from utils.validators import is_valid_url, validate_file_size
from utils.conversion_registry import get_conversion_targets, CONVERSION_MATRIX
from services.text_service import to_sentence_case, remove_duplicate_lines, clean_text, pretty_print_json, get_text_stats
from services.database_service import (
    init_db, UserService, DownloadService, ConversionService, AdminService, StatisticsService
)

def setUpModule():
    import os
    from pathlib import Path
    os.environ["DATABASE_URL"] = "sqlite:///database/test_bot_v2.db"
    test_db = Path("database/test_bot_v2.db")
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass
    init_db()

def tearDownModule():
    from pathlib import Path
    test_db = Path("database/test_bot_v2.db")
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass

class TestQueueService(unittest.IsolatedAsyncioTestCase):
    async def test_queue_scheduler_concurrency(self):
        """Test that only 2 tasks run concurrently and extra tasks are enqueued."""
        from services.queue_service import enqueue_task, get_queue_stats, _active_tasks, _pending_queue
        
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

class TestDatabaseArchitecture(unittest.TestCase):
    def test_database_operations(self):
        user_id = 987654321
        # Create user
        user = UserService.get_or_create_user(user_id, "jane_doe", "Jane")
        self.assertEqual(user['first_name'], "Jane")
        self.assertEqual(user['downloads_count'], 0)
        
        # Ban check
        self.assertFalse(UserService.is_banned(user_id))
        self.assertTrue(UserService.ban_user(user_id))
        self.assertTrue(UserService.is_banned(user_id))
        self.assertTrue(UserService.unban_user(user_id))
        self.assertFalse(UserService.is_banned(user_id))
        
        # Log download
        DownloadService.log_download(user_id, "https://youtu.be/123", "YouTube", "Video Title", "VIDEO", "720p", 2048)
        # Log conversion
        ConversionService.log_conversion(user_id, "doc.docx", "docx", "pdf", 1024)
        # Log QR
        ConversionService.log_qr(user_id, "GENERATE")
        
        # Verify stats increments
        stats = StatisticsService.get_user_stats(user_id)
        self.assertEqual(stats["downloads"], 1)
        self.assertEqual(stats["conversions"], 1)
        self.assertEqual(stats["files_processed"], 3)
        
        # Suspicious activity logging
        self.assertEqual(AdminService.get_suspicious(user_id), 0)
        AdminService.track_suspicious(user_id)
        AdminService.track_suspicious(user_id)
        self.assertEqual(AdminService.get_suspicious(user_id), 2)
        
        # Global stats checks
        glob = StatisticsService.get_global_stats()
        self.assertGreaterEqual(glob["total_users"], 1)
        self.assertEqual(glob["total_downloads"], 1)
        self.assertEqual(glob["total_conversions"], 1)
        
        # History check
        hist = StatisticsService.get_user_history(user_id, limit=5)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["type"], "conversion")
        self.assertEqual(hist[1]["type"], "download")

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

if __name__ == "__main__":
    unittest.main()
