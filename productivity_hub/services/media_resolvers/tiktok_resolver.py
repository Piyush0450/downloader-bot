"""
TikTok Media Fallback Resolver.
Extracts watermark-free HD video and audio streams from TikTok URLs via TikWM
when yt-dlp encounters regional restrictions or bot detection.
"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from productivity_hub.services.media_resolvers.models import MediaResolution
from productivity_hub.utils.dependency_checker import get_dependency_checker

logger = logging.getLogger("productivity_hub.services.media_resolvers.tiktok")


class TikTokResolver:
    """Specialized fallback resolver for TikTok watermark-free videos and audio."""

    @staticmethod
    def can_handle(url: str, service: str) -> bool:
        """Check if target URL is a TikTok media link."""
        return service == "tiktok" or "tiktok.com" in url.lower()

    @classmethod
    async def resolve(cls, url: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """
        Extract TikTok watermark-free video metadata and direct CDN streaming URL.
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, cls._sync_extract, url, max_file_size_bytes)
        except Exception as e:
            logger.warning(f"TikTok fallback extraction failed for {url}: {e}")
            return None

    @classmethod
    def _sync_extract(cls, url: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """Synchronously query the TikWM public API."""
        try:
            api_endpoint = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
            req = urllib.request.Request(
                api_endpoint,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                }
            )

            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200:
                    return None
                raw_data = response.read().decode("utf-8")
                res = json.loads(raw_data)

            if res.get("code") != 0 or not res.get("data"):
                logger.warning(f"TikWM returned non-zero response for {url}: {res.get('msg')}")
                return None

            data = res["data"]
            # Prefer hdplay if available, else play (both watermark-free)
            video_url = data.get("hdplay") or data.get("play")
            if not video_url:
                return None

            # Handle relative URL paths returned by TikWM
            if video_url.startswith("/"):
                video_url = f"https://www.tikwm.com{video_url}"

            audio_url = data.get("music")
            if audio_url and audio_url.startswith("/"):
                audio_url = f"https://www.tikwm.com{audio_url}"

            thumbnail = data.get("cover") or data.get("origin_cover")
            title = data.get("title") or "TikTok Video"
            title = " ".join(title.split())
            duration = int(data.get("duration", 0) or 0)
            mins, secs = divmod(duration, 60)
            duration_str = f"{mins:02d}:{secs:02d}" if duration > 0 else "00:30"

            size_bytes = data.get("size", 0) or 0
            size_mb = size_bytes / (1024 * 1024) if size_bytes > 0 else 0.0

            dep_checker = get_dependency_checker()
            ffmpeg_ok = dep_checker.check_binary("ffmpeg").available

            video_formats: List[Dict[str, Any]] = [
                {
                    "format_id": "auto",
                    "resolution": f"🌟 Auto / Best (No Watermark){f' (~{size_mb:.1f} MB)' if size_mb > 0 else ''}",
                    "height": 1080 if data.get("hdplay") else 720,
                    "filesize_mb": round(size_mb, 1),
                    "exceeds_limit": size_bytes > max_file_size_bytes if size_bytes > 0 else False,
                },
                {
                    "format_id": "720p",
                    "resolution": "📹 720p HD",
                    "height": 720,
                    "filesize_mb": round(size_mb, 1),
                    "exceeds_limit": size_bytes > max_file_size_bytes if size_bytes > 0 else False,
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
                "Referer": "https://www.tiktok.com/",
            }

            return MediaResolution(
                url=url,
                service="tiktok",
                title=title,
                duration=duration,
                duration_str=duration_str,
                thumbnail=thumbnail,
                video_formats=video_formats,
                audio_formats=audio_formats,
                max_height=1080 if data.get("hdplay") else 720,
                ffmpeg_available=ffmpeg_ok,
                direct_stream_url=video_url,
                direct_audio_url=audio_url,
                resolver_name="tikwm",
                headers=headers,
            )
        except Exception as e:
            logger.warning(f"TikWM sync extraction exception for {url}: {e}")
            return None
