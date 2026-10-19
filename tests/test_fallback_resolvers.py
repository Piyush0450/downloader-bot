"""
Unit tests for Multi-Engine Media Fallback Resolvers.
Tests fallback extraction switching, shortcode parsing, domain routing,
and seamless engine failover.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from productivity_hub.services.media_resolvers.models import MediaResolution
from productivity_hub.services.media_resolvers.instagram_resolver import InstagramResolver
from productivity_hub.services.media_resolvers.tiktok_resolver import TikTokResolver
from productivity_hub.services.media_resolvers.youtube_resolver import YouTubeResolver
from productivity_hub.services.media_resolvers.fallback_manager import FallbackManager, get_fallback_manager
from productivity_hub.services.downloader_service import DownloaderService, DownloaderError


class TestFallbackResolvers(unittest.IsolatedAsyncioTestCase):
    """Test suite for fallback resolvers and multi-engine failover."""

    def test_instagram_shortcode_extraction(self):
        """Verify Instagram shortcode parser handles various URL formats."""
        urls = [
            ("https://www.instagram.com/reel/DepQydisM9O/", "DepQydisM9O"),
            ("https://instagram.com/p/DepQydisM9O/?utm_source=ig_web", "DepQydisM9O"),
            ("https://www.instagram.com/tv/DepQydisM9O/", "DepQydisM9O"),
            ("https://www.instagram.com/reels/DepQydisM9O/", "DepQydisM9O"),
        ]
        for url, expected in urls:
            self.assertEqual(InstagramResolver.extract_shortcode(url), expected)

    def test_resolver_can_handle(self):
        """Verify domain routing across resolvers."""
        self.assertTrue(InstagramResolver.can_handle("https://www.instagram.com/reel/123", "instagram"))
        self.assertFalse(InstagramResolver.can_handle("https://tiktok.com/@user/123", "tiktok"))

        self.assertTrue(TikTokResolver.can_handle("https://www.tiktok.com/@user/video/123", "tiktok"))
        self.assertTrue(TikTokResolver.can_handle("https://vm.tiktok.com/ZM8abc/", "tiktok"))
        self.assertFalse(TikTokResolver.can_handle("https://instagram.com/reel/123", "instagram"))

        self.assertTrue(YouTubeResolver.can_handle("https://www.youtube.com/watch?v=123", "youtube"))
        self.assertTrue(YouTubeResolver.can_handle("https://youtu.be/123", "youtube"))

    async def test_fallback_manager_cache(self):
        """Verify FallbackManager stores and retrieves cached resolutions."""
        mgr = FallbackManager()
        dummy_res = MediaResolution(
            url="https://www.instagram.com/reel/test/",
            service="instagram",
            title="Test Reel",
            duration=15,
            duration_str="00:15",
            thumbnail="https://example.com/thumb.jpg",
            video_formats=[{"format_id": "auto", "resolution": "Best", "height": 720, "filesize_mb": 5.0, "exceeds_limit": False}],
            audio_formats=[],
            max_height=720,
            ffmpeg_available=True,
            direct_stream_url="https://example.com/stream.mp4",
            resolver_name="instaloader",
        )
        mgr.cache_resolution("https://www.instagram.com/reel/test/", dummy_res)
        cached = mgr.get_cached_resolution("https://www.instagram.com/reel/test/")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.resolver_name, "instaloader")

    @patch("productivity_hub.services.downloader_service.yt_dlp.YoutubeDL")
    async def test_downloader_switches_to_fallback_on_ytdlp_extraction_failure(self, mock_ydl):
        """Verify DownloaderService switches to fallback resolver when yt-dlp fails."""
        # Configure yt-dlp to fail with Instagram rate limit error
        mock_instance = MagicMock()
        mock_instance.extract_info.side_effect = Exception("Requested content is not available, rate-limit reached or login required")
        mock_ydl.return_value.__enter__.return_value = mock_instance

        # Create dummy resolution that fallback resolver will return
        dummy_res = MediaResolution(
            url="https://www.instagram.com/reel/DepQydisM9O/",
            service="instagram",
            title="Fallback Resolved Reel",
            duration=20,
            duration_str="00:20",
            thumbnail="https://example.com/thumb.jpg",
            video_formats=[{"format_id": "auto", "resolution": "🌟 Auto / Best", "height": 720, "filesize_mb": 2.5, "exceeds_limit": False}],
            audio_formats=[],
            max_height=720,
            ffmpeg_available=True,
            direct_stream_url="https://example.com/cdn_video.mp4",
            resolver_name="instaloader",
        )

        with patch.object(FallbackManager, "resolve_fallback", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = dummy_res

            service = DownloaderService()
            meta = await service.get_metadata("https://www.instagram.com/reel/DepQydisM9O/")

            self.assertIsNotNone(meta)
            self.assertEqual(meta["service"], "instagram")
            self.assertEqual(meta["resolver_name"], "instaloader")
            self.assertEqual(meta["title"], "Fallback Resolved Reel")
            self.assertTrue(meta["direct_stream_url"])

    @patch("productivity_hub.services.downloader_service.yt_dlp.YoutubeDL")
    async def test_downloader_switches_to_fallback_on_ytdlp_download_failure(self, mock_ydl):
        """Verify DownloaderService switches to fallback direct stream when yt-dlp download fails."""
        mock_instance = MagicMock()
        mock_instance.extract_info.side_effect = Exception("HTTP 403 Forbidden: Login required")
        mock_ydl.return_value.__enter__.return_value = mock_instance

        dummy_res = MediaResolution(
            url="https://www.tiktok.com/@user/video/123",
            service="tiktok",
            title="TikTok Watermark-Free Video",
            duration=30,
            duration_str="00:30",
            thumbnail="https://example.com/thumb.jpg",
            video_formats=[],
            audio_formats=[],
            max_height=720,
            ffmpeg_available=True,
            direct_stream_url="https://example.com/tikwm_video.mp4",
            resolver_name="tikwm",
        )

        service = DownloaderService()
        with patch.object(FallbackManager, "resolve_fallback", new_callable=AsyncMock) as mock_resolve, \
             patch.object(service, "_download_direct_stream", new_callable=AsyncMock) as mock_direct_dl:

            mock_resolve.return_value = dummy_res
            mock_direct_dl.return_value = {
                "file_path": Path("temp/downloads/dl_test.mp4"),
                "file_size": 2500000,
                "file_size_mb": 2.38,
                "title": "TikTok Watermark-Free Video",
                "duration": 30,
                "format": "auto",
                "resolution_note": None,
            }

            result = await service.download_media("https://www.tiktok.com/@user/video/123", format_id="auto")
            self.assertEqual(result["title"], "TikTok Watermark-Free Video")
            mock_direct_dl.assert_called_once()


if __name__ == "__main__":
    unittest.main()
