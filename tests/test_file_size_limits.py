"""
Tests for File-Size Validation and Telegram Upload Limits.

Covers:
1. Configurable limits via environment variables (MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE, etc.).
2. Validation helper functions (validate_file_size, get_oversized_file_message, is_compressible_filename).
3. Files below, at, and above limits.
4. Streaming download byte monitoring and immediate abortion when limit exceeded.
5. Pre-download size rejection from Telegram metadata before downloading.
6. Post-download size rejection when initial size was unknown.
7. Pre-upload size checks preventing oversized Telegram upload attempts.
8. Graceful TelegramError catching without leaking internal paths, tokens, or traces.
9. Cleanup of temporary files and partial downloads on failure/size error.
"""

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import telegram.error

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.database.database import init_db, get_db, close_db
from productivity_hub.services.downloader_service import DownloaderService, DownloaderError
from productivity_hub.utils.validators import (
    validate_file_size,
    get_oversized_file_message,
    is_compressible_filename,
    get_oversized_suggestion_keyboard
)
from productivity_hub.handlers.converter import document_upload_handler
from productivity_hub.handlers.downloader import handle_download_format_callback


class TestFileSizeValidationAndLimits(unittest.IsolatedAsyncioTestCase):
    """Test suite covering file size constraints and Telegram upload/download limits."""

    async def asyncSetUp(self):
        # Initialize in-memory database for testing handlers
        self.db = await init_db(":memory:")
        self.download_temp_dir = Path("temp/downloads")
        self.download_temp_dir.mkdir(parents=True, exist_ok=True)

    async def asyncTearDown(self):
        await close_db()
        # Clean up any test files inside temp/downloads
        for f in self.download_temp_dir.glob("test_*"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    def test_settings_configurable_via_env(self):
        """Test Requirement 1 & 9: Configurable limits without rewriting code."""
        # Test default limits
        default_settings = Settings(
            BOT_TOKEN="test_token",
            OWNER_ID=123,
            SECRET_KEY="test_secret_key_minimum_length"
        )
        self.assertEqual(default_settings.MAX_FILE_SIZE_BYTES, 50 * 1024 * 1024)
        self.assertEqual(default_settings.TELEGRAM_UPLOAD_LIMIT_BYTES, 50 * 1024 * 1024)
        self.assertEqual(default_settings.TELEGRAM_DOWNLOAD_LIMIT_BYTES, 20 * 1024 * 1024)
        self.assertAlmostEqual(default_settings.max_file_size_mb, 50.0)

        # Test custom MAX_FILE_SIZE_BYTES via env
        with patch.dict(os.environ, {
            "BOT_TOKEN": "test_token",
            "OWNER_ID": "123",
            "SECRET_KEY": "test_secret_key_minimum_length",
            "MAX_FILE_SIZE_BYTES": str(30 * 1024 * 1024)
        }):
            custom_settings = Settings.load_from_env()
            self.assertEqual(custom_settings.MAX_FILE_SIZE_BYTES, 30 * 1024 * 1024)
            self.assertAlmostEqual(custom_settings.max_file_size_mb, 30.0)

        # Test custom MAX_FILE_SIZE in MB synchronizing to MAX_FILE_SIZE_BYTES
        with patch.dict(os.environ, {
            "BOT_TOKEN": "test_token",
            "OWNER_ID": "123",
            "SECRET_KEY": "test_secret_key_minimum_length",
            "MAX_FILE_SIZE": "15"
        }):
            mb_settings = Settings.load_from_env()
            self.assertEqual(mb_settings.MAX_FILE_SIZE, 15)
            self.assertEqual(mb_settings.MAX_FILE_SIZE_BYTES, 15 * 1024 * 1024)

    def test_validate_file_size_boundaries(self):
        """Test Requirement 10: Files below, at, and above the limit."""
        limit_bytes = 50 * 1024 * 1024  # 50 MB

        # Below limit
        self.assertTrue(validate_file_size(10 * 1024 * 1024, max_bytes=limit_bytes))
        self.assertTrue(validate_file_size(49 * 1024 * 1024, max_bytes=limit_bytes))
        self.assertTrue(validate_file_size(0, max_bytes=limit_bytes))

        # Exactly at limit
        self.assertTrue(validate_file_size(limit_bytes, max_bytes=limit_bytes))

        # Above limit
        self.assertFalse(validate_file_size(limit_bytes + 1, max_bytes=limit_bytes))
        self.assertFalse(validate_file_size(100 * 1024 * 1024, max_bytes=limit_bytes))

        # Negative size is invalid
        self.assertFalse(validate_file_size(-1, max_bytes=limit_bytes))

        # MB-based validation
        self.assertTrue(validate_file_size(20 * 1024 * 1024, max_mb=20))
        self.assertFalse(validate_file_size(20 * 1024 * 1024 + 1, max_mb=20))

    def test_oversized_file_message_formatting(self):
        """Test Requirement 5: Clear, friendly user message for oversized files."""
        msg = get_oversized_file_message(limit_bytes=50 * 1024 * 1024, actual_size_bytes=60 * 1024 * 1024)
        self.assertIn("File too large to send through this bot", msg)
        self.assertIn("The file is larger than the maximum supported size of this deployment", msg)
        self.assertIn("Please choose a smaller file or compress it and try again", msg)
        self.assertIn("60.0 MB", msg)
        self.assertIn("50.0 MB", msg)

    def test_compressible_detection_and_suggestion_keyboard(self):
        """Test Requirement 6: Offer compression options when practical."""
        # Compressible formats
        self.assertTrue(is_compressible_filename("photo.jpg"))
        self.assertTrue(is_compressible_filename("image.png"))
        self.assertTrue(is_compressible_filename("video.mp4"))
        self.assertTrue(is_compressible_filename("song.mp3"))
        self.assertTrue(is_compressible_filename("document.pdf"))
        self.assertTrue(is_compressible_filename(".WEBP"))

        # Non-compressible or unsupported compression formats
        self.assertFalse(is_compressible_filename("app.exe"))
        self.assertFalse(is_compressible_filename("archive.zip"))
        self.assertFalse(is_compressible_filename("data.bin"))
        self.assertFalse(is_compressible_filename(""))

        # Verify suggestion keyboard generation
        kb_compressible = get_oversized_suggestion_keyboard(owner_id=12345, filename="video.mp4", lang="en")
        self.assertIsNotNone(kb_compressible)
        # Check buttons in keyboard
        has_compressor_btn = any(
            any("Compressor" in btn.text for btn in row)
            for row in kb_compressible.inline_keyboard
        )
        self.assertTrue(has_compressor_btn)

        # Non-compressible returns None
        kb_non_compressible = get_oversized_suggestion_keyboard(owner_id=12345, filename="app.exe", lang="en")
        self.assertIsNone(kb_non_compressible)

    async def test_streaming_download_size_limit_abort(self):
        """Test Requirement 3: Streaming download monitoring stops immediately when exceeding max."""
        custom_settings = Settings(
            BOT_TOKEN="mock_tok",
            OWNER_ID=123,
            SECRET_KEY="mock_sec_key_1234567890",
            MAX_FILE_SIZE_BYTES=10 * 1024 * 1024
        )
        svc = DownloaderService(settings=custom_settings)

        with patch.object(svc, "_sync_extract_info") as mock_extract:
            # Simulate hook triggering size violation during download
            def fake_extract(url, opts, download=False):
                hooks = opts.get("progress_hooks", [])
                for hook in hooks:
                    # Feed status with 12MB downloaded (exceeds 10MB limit)
                    hook({
                        "status": "downloading",
                        "downloaded_bytes": 12 * 1024 * 1024,
                        "total_bytes": 15 * 1024 * 1024,
                    })
                return {}

            mock_extract.side_effect = fake_extract

            with self.assertRaises(DownloaderError) as cm:
                await svc.download_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

            self.assertIn("exceeded maximum supported limit", str(cm.exception).lower())

    async def test_pre_download_metadata_size_rejection(self):
        """Test Requirement 2: Reject oversized files before downloading (Telegram 20MB limit)."""
        mock_update = MagicMock()
        mock_context = MagicMock()
        mock_message = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 998877
        mock_user.username = "testuser"
        mock_user.language_code = "en"

        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_context.user_data = {}

        # Simulate Telegram document with known file_size = 25MB (exceeds Telegram Bot getFile 20MB limit)
        mock_doc = MagicMock()
        mock_doc.file_id = "doc_file_id_oversized"
        mock_doc.file_name = "huge_manual.pdf"
        mock_doc.file_size = 25 * 1024 * 1024
        mock_message.document = mock_doc
        mock_message.photo = None

        mock_message.reply_text = AsyncMock()

        # Mock validate_user_access to bypass rate limiter in middleware
        with patch("productivity_hub.handlers.middleware.validate_user_access") as mock_val:
            mock_db_user = MagicMock()
            mock_db_user.language = "en"
            mock_val.return_value = mock_db_user

            await document_upload_handler(mock_update, mock_context)

        # Verify get_file was NEVER called (wasting zero bandwidth/CPU)
        mock_context.bot.get_file.assert_not_called()

        # Verify user was sent the oversized friendly message
        mock_message.reply_text.assert_called_once()
        args, kwargs = mock_message.reply_text.call_args
        reply_text = args[0]
        self.assertIn("File too large to send through this bot", reply_text)
        self.assertIn("The file is larger than the maximum supported size", reply_text)

        # Verify compression option was provided for PDF
        self.assertIsNotNone(kwargs.get("reply_markup"))

    async def test_post_download_size_rejection_for_unknown_size(self):
        """Test Requirement 10: Size unknown until download begins, rejected and cleaned up upon exceeding limit."""
        mock_update = MagicMock()
        mock_context = MagicMock()
        mock_message = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 998877
        mock_user.username = "testuser"
        mock_user.language_code = "en"

        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_context.user_data = {}

        # Document with unknown initial size (file_size is None)
        mock_doc = MagicMock()
        mock_doc.file_id = "doc_unknown_size"
        mock_doc.file_name = "mystery.pdf"
        mock_doc.file_size = None
        mock_message.document = mock_doc
        mock_message.photo = None

        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        mock_message.reply_text = AsyncMock(return_value=status_msg)

        # Simulate downloaded file exceeding MAX_FILE_SIZE_BYTES (e.g. 55MB)
        file_handle = MagicMock()
        downloaded_path = []

        async def fake_download(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            downloaded_path.append(Path(custom_path))
            with open(custom_path, "wb") as f:
                f.seek(55 * 1024 * 1024 - 1)
                f.write(b"\0")

        file_handle.download_to_drive = fake_download
        mock_context.bot.get_file = AsyncMock(return_value=file_handle)

        with patch("productivity_hub.handlers.middleware.validate_user_access") as mock_val:
            mock_db_user = MagicMock()
            mock_db_user.language = "en"
            mock_val.return_value = mock_db_user

            await document_upload_handler(mock_update, mock_context)

        # Verify friendly message was sent via status_msg.edit_text
        status_msg.edit_text.assert_called_once()
        args, kwargs = status_msg.edit_text.call_args
        self.assertIn("File too large to send through this bot", args[0])

        # Verify oversized downloaded file was deleted immediately
        self.assertTrue(len(downloaded_path) > 0)
        self.assertFalse(downloaded_path[0].exists())

    async def test_pre_upload_size_rejection_prevents_telegram_call(self):
        """Test Requirement 4 & 5: Check actual size against 50MB before sending to Telegram."""
        mock_query = MagicMock()
        mock_update = MagicMock()
        mock_update.callback_query = mock_query
        mock_context = MagicMock()
        mock_context.user_data = {}

        mock_query.from_user.id = 12345
        mock_query.data = "dlfmt:720p:12345"
        mock_query.answer = AsyncMock()

        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        mock_query.message.reply_text = AsyncMock(return_value=status_msg)
        mock_query.message.chat_id = 12345

        # Create oversized output file inside designated temp/downloads (52MB, exceeds 50MB upload limit)
        oversized_output = self.download_temp_dir / "test_huge_output.mp4"
        with open(oversized_output, "wb") as f:
            f.seek(52 * 1024 * 1024 - 1)
            f.write(b"\0")

        from productivity_hub.handlers.downloader import ACTIVE_DOWNLOAD_URLS
        ACTIVE_DOWNLOAD_URLS[12345] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with patch("productivity_hub.handlers.downloader.get_downloader_service") as mock_get_dl, \
             patch("productivity_hub.handlers.downloader.get_queue_service") as mock_get_q:

            dl_svc = MagicMock()
            dl_svc.download_media = AsyncMock(return_value={
                "file_path": oversized_output,
                "file_size": 52 * 1024 * 1024,
                "title": "Huge Video",
            })
            mock_get_dl.return_value = dl_svc

            q_svc = MagicMock()
            deferred_coro = []

            async def fake_submit(user_id, task_type, coro_fn, **kwargs):
                deferred_coro.append(coro_fn)
                task_mock = MagicMock()
                task_mock.task_id = "test_task_id"
                return task_mock

            q_svc.submit_task = fake_submit
            q_svc.get_queue_position.return_value = None
            mock_get_q.return_value = q_svc

            await handle_download_format_callback(mock_update, mock_context)

            # Now execute the deferred queue task
            self.assertEqual(len(deferred_coro), 1)
            await deferred_coro[0]()

            # Assert send_video was NEVER called because pre-upload check intercepted it
            mock_context.bot.send_video.assert_not_called()
            mock_context.bot.send_audio.assert_not_called()

            # Assert friendly oversized message was sent to user
            calls = [c[0][0] for c in status_msg.edit_text.call_args_list if c[0]]
            has_oversized_msg = any("File too large to send through this bot" in str(msg) for msg in calls)
            self.assertTrue(has_oversized_msg)

            # Assert oversized file was automatically cleaned up in finally block
            self.assertFalse(oversized_output.exists())

    async def test_graceful_telegram_upload_error_handling(self):
        """Test Requirement 7: Catch Telegram file-size errors and upload failures gracefully without leaking internals."""
        mock_query = MagicMock()
        mock_update = MagicMock()
        mock_update.callback_query = mock_query
        mock_context = MagicMock()
        mock_context.user_data = {}

        mock_query.from_user.id = 12345
        mock_query.data = "dlfmt:720p:12345"
        mock_query.answer = AsyncMock()

        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        mock_query.message.reply_text = AsyncMock(return_value=status_msg)
        mock_query.message.chat_id = 12345

        # Create valid output file inside temp/downloads (45MB, within 50MB limit)
        output_file = self.download_temp_dir / "test_sample.mp4"
        with open(output_file, "wb") as f:
            f.seek(45 * 1024 * 1024 - 1)
            f.write(b"\0")

        from productivity_hub.handlers.downloader import ACTIVE_DOWNLOAD_URLS
        ACTIVE_DOWNLOAD_URLS[12345] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        # Simulate Telegram rejecting with BadRequest("Request Entity Too Large")
        mock_context.bot.send_video = AsyncMock(side_effect=telegram.error.BadRequest("Request Entity Too Large"))

        with patch("productivity_hub.handlers.downloader.get_downloader_service") as mock_get_dl, \
             patch("productivity_hub.handlers.downloader.get_queue_service") as mock_get_q:

            dl_svc = MagicMock()
            dl_svc.download_media = AsyncMock(return_value={
                "file_path": output_file,
                "file_size": 45 * 1024 * 1024,
                "title": "Sample Video",
            })
            mock_get_dl.return_value = dl_svc

            q_svc = MagicMock()
            deferred_coro = []

            async def fake_submit(user_id, task_type, coro_fn, **kwargs):
                deferred_coro.append(coro_fn)
                task_mock = MagicMock()
                task_mock.task_id = "test_task_id"
                return task_mock

            q_svc.submit_task = fake_submit
            q_svc.get_queue_position.return_value = None
            mock_get_q.return_value = q_svc

            await handle_download_format_callback(mock_update, mock_context)

            # Run deferred queue task
            self.assertEqual(len(deferred_coro), 1)
            await deferred_coro[0]()

            # Assert error message shown to user does not expose internal path, token, or stack trace
            calls = [c[0][0] for c in status_msg.edit_text.call_args_list if c[0]]
            error_msg = calls[-1]
            self.assertIn("File too large to send through this bot", error_msg)
            self.assertNotIn("Traceback", error_msg)
            self.assertNotIn("temp/downloads", error_msg)
            self.assertNotIn("token", error_msg.lower())

            # Verify file was cleaned up despite upload failure
            self.assertFalse(output_file.exists())


if __name__ == "__main__":
    unittest.main()
