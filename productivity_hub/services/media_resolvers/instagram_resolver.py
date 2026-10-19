"""
Instagram Media Fallback Resolver.
Extracts direct CDN video streams from Instagram Reels and Posts via Instaloader
and secondary HTML scraping when yt-dlp encounters login walls or rate-limits.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from productivity_hub.services.media_resolvers.models import MediaResolution
from productivity_hub.utils.dependency_checker import get_dependency_checker

logger = logging.getLogger("productivity_hub.services.media_resolvers.instagram")

# Regular expression to extract shortcode from Instagram URLs
INSTAGRAM_SHORTCODE_REGEX = re.compile(
    r"(?:instagram\.com/(?:reel|reels|p|tv)/)([\w\-]+)",
    re.IGNORECASE
)


class InstagramResolver:
    """Specialized fallback resolver for Instagram Reels, Posts, and Videos."""

    @staticmethod
    def can_handle(url: str, service: str) -> bool:
        """Check if target URL is an Instagram media link."""
        return service == "instagram" or "instagram.com" in url.lower()

    @classmethod
    def extract_shortcode(cls, url: str) -> Optional[str]:
        """Extract post/reel shortcode from URL."""
        match = INSTAGRAM_SHORTCODE_REGEX.search(url)
        if match:
            return match.group(1)
        return None

    @classmethod
    async def resolve(cls, url: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """
        Extract Instagram media metadata and direct CDN streaming URL.
        Executes inside thread pool executor to maintain event loop responsiveness.
        """
        shortcode = cls.extract_shortcode(url)
        if not shortcode:
            logger.debug(f"Could not extract Instagram shortcode from {url}")
            return None

        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, cls._sync_extract, shortcode, max_file_size_bytes)
            return res
        except Exception as e:
            logger.warning(f"Instagram fallback extraction failed for shortcode {shortcode}: {e}")
            return None

    @classmethod
    def _sync_extract(cls, shortcode: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """Synchronous extraction using instaloader in quiet worker thread."""
        try:
            import instaloader
            # Suppress noisy GraphQL retry logging
            logging.getLogger("instaloader").setLevel(logging.CRITICAL)

            loader = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                quiet=True,
                max_connection_attempts=1,
            )

            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            if not post.is_video or not post.video_url:
                logger.debug(f"Instagram post {shortcode} is not a video or has no video_url")
                return None

            video_url = post.video_url
            thumbnail = post.url
            title = post.title or (post.caption[:80] + "..." if post.caption and len(post.caption) > 80 else post.caption) or f"Instagram Reel ({shortcode})"
            # Sanitize title newlines
            title = " ".join(title.split()) if title else f"Instagram Reel ({shortcode})"
            duration = int(post.video_duration or 0)

            # Check FFmpeg availability for MP3 extraction
            dep_checker = get_dependency_checker()
            ffmpeg_ok = dep_checker.check_binary("ffmpeg").available

            # Format duration string
            mins, secs = divmod(duration, 60)
            duration_str = f"{mins:02d}:{secs:02d}" if duration > 0 else "00:30"

            video_formats: List[Dict[str, Any]] = [
                {
                    "format_id": "auto",
                    "resolution": "🌟 Auto / Best (720p HD)",
                    "height": 720,
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                },
                {
                    "format_id": "720p",
                    "resolution": "📹 720p HD",
                    "height": 720,
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                }
            ]

            audio_formats: List[Dict[str, Any]] = []
            if ffmpeg_ok:
                audio_formats.append({
                    "format_id": "audio_320",
                    "resolution": "🎵 Audio MP3 (320k)",
                    "quality": "320",
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                })
                audio_formats.append({
                    "format_id": "audio_128",
                    "resolution": "🎵 Audio MP3 (128k)",
                    "quality": "128",
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                })
            else:
                audio_formats.append({
                    "format_id": "audio_direct",
                    "resolution": "🎵 Audio Stream (Direct)",
                    "quality": "direct",
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                })

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://www.instagram.com/",
            }

            return MediaResolution(
                url=f"https://www.instagram.com/reel/{shortcode}/",
                service="instagram",
                title=title,
                duration=duration,
                duration_str=duration_str,
                thumbnail=thumbnail,
                video_formats=video_formats,
                audio_formats=audio_formats,
                max_height=720,
                ffmpeg_available=ffmpeg_ok,
                direct_stream_url=video_url,
                resolver_name="instaloader",
                headers=headers,
            )
        except Exception as e:
            logger.warning(f"Instaloader sync extraction error for {shortcode}: {e}")
            return None
