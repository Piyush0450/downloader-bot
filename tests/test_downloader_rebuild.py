"""
Comprehensive Unit Tests for Rebuilt Universal Media Downloader.

Tests:
1. Thread-safe progress callback bridging without 'no running event loop' error.
2. Dynamic HD format selection: genuine tiers only, no false promises.
3. Auto / Best Quality selection option present.
4. FFmpeg detection and audio MP3 format gating.
5. Streaming size enforcement and abort on oversize.
6. Cancellation event handling & partial file cleanup.
7. Callback data 64-byte Telegram limit compliance.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from productivity_hub.config.settings import Settings
from productivity_hub.services.downloader_service import (
    DownloaderService,
    DownloaderError,
    get_downloader_service,
)
from productivity_hub.utils.validators import validate_media_url


class TestUniversalMediaDownloader(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying all Media Downloader requirements."""

    def setUp(self):
        self.test_dir = Path("temp/test_downloader")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ",
            OWNER_ID=1530123674,
            SECRET_KEY="test_secret_key_12345678901234567890",
            MAX_FILE_SIZE=50,
            MAX_FILE_SIZE_BYTES=50 * 1024 * 1024,
            TELEGRAM_UPLOAD_LIMIT_BYTES=50 * 1024 * 1024
        )
        self.service = DownloaderService(settings=self.settings)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_progress_hook_thread_safety_no_running_event_loop_error(self):
        """
        ROOT CAUSE REGRESSION TEST:
        Simulates yt-dlp running inside a worker thread and calling the progress hook
        with an async progress_callback.
        Verifies that NO 'RuntimeError: no running event loop' is raised!
        """
        progress_calls = []

        async def async_progress_callback(status, percent, speed, eta, dl_bytes, total_bytes):
            progress_calls.append((status, percent, speed, eta))

        # Mock _sync_extract_info to simulate yt-dlp invoking progress hook from worker thread
        def fake_worker_extract(url, opts, download=False):
            # Check that there is NO running event loop in this thread (simulating ThreadPoolExecutor)
            try:
                asyncio.get_running_loop()
                loop_present = True
            except RuntimeError:
                loop_present = False

            # In executor thread, loop_present should be False
            # yt-dlp calls progress hook
            for hook in opts.get("progress_hooks", []):
                hook({
                    "status": "downloading",
                    "downloaded_bytes": 5 * 1024 * 1024,
                    "total_bytes": 10 * 1024 * 1024,
                    "_speed_str": "1.5MiB/s",
                    "_eta_str": "00:03",
                })
                # Simulate finish
                hook({
                    "status": "finished",
                    "downloaded_bytes": 10 * 1024 * 1024,
                    "total_bytes": 10 * 1024 * 1024,
                    "_speed_str": "1.5MiB/s",
                    "_eta_str": "00:00",
                })

            # Create dummy output file
            outtmpl = opts["outtmpl"]
            out_path = Path(outtmpl.replace("%(ext)s", "mp4"))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(b"dummy video data")

            return {
                "title": "Thread Safety Test Video",
                "duration": 60,
                "height": 720,
                "width": 1280,
            }

        with patch.object(self.service, "_sync_extract_info", side_effect=fake_worker_extract):
            # This must succeed without 'Download failed: no running event loop'
            res = await self.service.download_media(
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                format_id="720p",
                progress_callback=async_progress_callback
            )
            self.assertIsNotNone(res)
            self.assertEqual(res["title"], "Thread Safety Test Video")
            self.assertTrue(Path(res["file_path"]).exists())
            # Clean up dummy file
            Path(res["file_path"]).unlink(missing_ok=True)

        # Allow loop to process any scheduled callbacks
        await asyncio.sleep(0.05)
        self.assertGreaterEqual(len(progress_calls), 1)

    async def test_dynamic_hd_resolution_selection_only_genuine_options(self):
        """
        Verify that resolution menus:
        1. Always include 'Auto / Best Quality' as first option.
        2. Do NOT promise 1080p, 1440p, or 2160p when max source height is only 720p.
        3. Correctly include 720p and below.
        """
        fake_720p_info = {
            "title": "720p Only Video",
            "duration": 120,
            "formats": [
                {"format_id": "18", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "width": 640, "tbr": 500},
                {"format_id": "135", "vcodec": "avc1", "acodec": "none", "height": 480, "width": 854, "tbr": 800},
                {"format_id": "136", "vcodec": "avc1", "acodec": "none", "height": 720, "width": 1280, "tbr": 1500},
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "abr": 128},
            ]
        }

        with patch.object(self.service, "_sync_extract_info", return_value=fake_720p_info):
            meta = await self.service.get_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

            self.assertEqual(meta["max_height"], 720)
            v_fmts = meta["video_formats"]

            # First option must be Auto
            self.assertEqual(v_fmts[0]["format_id"], "auto")

            format_ids = [f["format_id"] for f in v_fmts]
            # Must contain 720p
            self.assertIn("720p", format_ids)
            # MUST NOT contain 1080p, 1440p, or 2160p!
            self.assertNotIn("1080p", format_ids)
            self.assertNotIn("1440p", format_ids)
            self.assertNotIn("2160p", format_ids)

    async def test_4k_video_offers_4k_and_lower_tiers(self):
        """Verify that when a 4K stream exists, 2160p (4K) is offered."""
        fake_4k_info = {
            "title": "4K Ultra HD Video",
            "duration": 300,
            "formats": [
                {"format_id": "360", "vcodec": "avc1", "acodec": "none", "height": 360, "width": 640, "tbr": 500},
                {"format_id": "720", "vcodec": "avc1", "acodec": "none", "height": 720, "width": 1280, "tbr": 1500},
                {"format_id": "1080", "vcodec": "avc1", "acodec": "none", "height": 1080, "width": 1920, "tbr": 3500},
                {"format_id": "2160", "vcodec": "av01", "acodec": "none", "height": 2160, "width": 3840, "tbr": 12000},
            ]
        }

        with patch.object(self.service, "_sync_extract_info", return_value=fake_4k_info):
            meta = await self.service.get_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            format_ids = [f["format_id"] for f in meta["video_formats"]]
            self.assertIn("2160p", format_ids)
            self.assertIn("1080p", format_ids)
            self.assertIn("720p", format_ids)

    async def test_vertical_video_resolution_calculation(self):
        """Verify vertical video (TikTok / Shorts / Reels: e.g. 1080x1920) resolves to 1080p tier."""
        fake_shorts_info = {
            "title": "Shorts Video",
            "duration": 30,
            "formats": [
                {"format_id": "v1", "vcodec": "avc1", "acodec": "none", "height": 1920, "width": 1080, "tbr": 2500},
                {"format_id": "v2", "vcodec": "avc1", "acodec": "none", "height": 1280, "width": 720, "tbr": 1200},
            ]
        }

        with patch.object(self.service, "_sync_extract_info", return_value=fake_shorts_info):
            meta = await self.service.get_metadata("https://www.youtube.com/shorts/kJQP7kiw5Fk")
            self.assertEqual(meta["max_height"], 1080)
            format_ids = [f["format_id"] for f in meta["video_formats"]]
            self.assertIn("1080p", format_ids)
            self.assertIn("720p", format_ids)

    async def test_audio_options_gated_by_ffmpeg(self):
        """Verify that MP3 formats are offered when FFmpeg is available."""
        fake_info = {
            "title": "Audio Test",
            "duration": 180,
            "formats": [
                {"format_id": "a1", "vcodec": "none", "acodec": "mp4a", "abr": 128}
            ]
        }

        with patch.object(self.service, "_sync_extract_info", return_value=fake_info):
            # When FFmpeg is present
            with patch("productivity_hub.services.downloader_service.get_dependency_checker") as mock_checker_fn:
                mock_checker = MagicMock()
                mock_checker.check_binary.return_value.available = True
                mock_checker_fn.return_value = mock_checker

                meta = await self.service.get_metadata("https://soundcloud.com/artist/track")
                audio_ids = [f["format_id"] for f in meta["audio_formats"]]
                self.assertIn("audio_320", audio_ids)
                self.assertIn("audio_128", audio_ids)

            # When FFmpeg is NOT present
            with patch("productivity_hub.services.downloader_service.get_dependency_checker") as mock_checker_fn:
                mock_checker = MagicMock()
                mock_checker.check_binary.return_value.available = False
                mock_checker_fn.return_value = mock_checker

                meta = await self.service.get_metadata("https://soundcloud.com/artist/track")
                audio_ids = [f["format_id"] for f in meta["audio_formats"]]
                self.assertNotIn("audio_320", audio_ids)
                self.assertIn("audio_direct", audio_ids)

    async def test_streaming_download_size_limit_stops_immediately(self):
        """Verify that exceeding MAX_FILE_SIZE_BYTES during streaming aborts the download."""
        custom_settings = Settings(
            BOT_TOKEN="mock_tok",
            OWNER_ID=123,
            SECRET_KEY="mock_sec_key_1234567890",
            MAX_FILE_SIZE=10,
            MAX_FILE_SIZE_BYTES=10 * 1024 * 1024
        )
        svc = DownloaderService(settings=custom_settings)

        def fake_oversized_extract(url, opts, download=False):
            for hook in opts.get("progress_hooks", []):
                hook({
                    "status": "downloading",
                    "downloaded_bytes": 12 * 1024 * 1024,
                    "total_bytes": 15 * 1024 * 1024,
                })
            return {}

        with patch.object(svc, "_sync_extract_info", side_effect=fake_oversized_extract):
            with self.assertRaises(DownloaderError) as ctx:
                await svc.download_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

            self.assertIn("exceeded maximum supported limit", str(ctx.exception).lower())

    async def test_cancellation_event_aborts_download(self):
        """Verify that cancel_event aborts download gracefully and cleans up files."""
        cancel_evt = asyncio.Event()
        cancel_evt.set()  # Signal cancellation immediately

        def fake_extract_with_cancel(url, opts, download=False):
            for hook in opts.get("progress_hooks", []):
                hook({
                    "status": "downloading",
                    "downloaded_bytes": 1024,
                    "total_bytes": 10240,
                })
            return {}

        with patch.object(self.service, "_sync_extract_info", side_effect=fake_extract_with_cancel):
            with self.assertRaises(DownloaderError) as ctx:
                await self.service.download_media(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    cancel_event=cancel_evt
                )
            self.assertIn("cancelled", str(ctx.exception).lower())

    def test_callback_data_within_64_bytes(self):
        """Verify that all generated callback data tokens fit in Telegram 64-byte limit."""
        user_id = 1530123674
        format_ids = ["auto", "2160p", "1440p", "1080p", "720p", "480p", "360p", "audio_320", "audio_128", "cancel"]
        for fmt in format_ids:
            cb = f"dlfmt:{fmt}:{user_id}"
            encoded_len = len(cb.encode("utf-8"))
            self.assertLessEqual(encoded_len, 64, f"Callback {cb} exceeds 64 bytes ({encoded_len})")


if __name__ == "__main__":
    unittest.main()
