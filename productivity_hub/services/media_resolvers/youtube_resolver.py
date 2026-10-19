"""
YouTube Media Fallback Resolver.
Extracts YouTube streams via PyTubeFix when yt-dlp encounters bot detection
or sign-in restrictions on cloud hosting.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from productivity_hub.services.media_resolvers.models import MediaResolution
from productivity_hub.utils.dependency_checker import get_dependency_checker

logger = logging.getLogger("productivity_hub.services.media_resolvers.youtube")


class YouTubeResolver:
    """Specialized fallback resolver for YouTube videos and audio via PyTubeFix."""

    @staticmethod
    def can_handle(url: str, service: str) -> bool:
        """Check if target URL is a YouTube media link."""
        return service == "youtube" or "youtube.com" in url.lower() or "youtu.be" in url.lower()

    @classmethod
    async def resolve(cls, url: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """
        Extract YouTube video metadata and direct CDN streaming URL via PyTubeFix.
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, cls._sync_extract, url, max_file_size_bytes)
        except Exception as e:
            logger.warning(f"YouTube PyTubeFix fallback extraction failed for {url}: {e}")
            return None

    @classmethod
    def _sync_extract(cls, url: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """Synchronously extract YouTube metadata."""
        try:
            from pytubefix import YouTube

            yt = YouTube(url, client="ANDROID")
            title = yt.title or "YouTube Video"
            duration = int(yt.length or 0)
            thumbnail = yt.thumbnail_url

            mins, secs = divmod(duration, 60)
            duration_str = f"{mins:02d}:{secs:02d}" if duration > 0 else "00:00"

            dep_checker = get_dependency_checker()
            ffmpeg_ok = dep_checker.check_binary("ffmpeg").available

            # Check streams
            # 1. Look for progressive MP4 stream (audio + video combined)
            progressive = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
            # 2. Or highest resolution video stream
            video_stream = progressive or yt.streams.filter(type="video", file_extension="mp4").order_by("resolution").desc().first()
            # 3. Audio stream
            audio_stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()

            if not video_stream and not audio_stream:
                return None

            direct_stream_url = video_stream.url if video_stream else None
            direct_audio_url = audio_stream.url if audio_stream else None

            res_str = video_stream.resolution if video_stream and video_stream.resolution else "720p"
            h_int = int(res_str.replace("p", "")) if res_str.replace("p", "").isdigit() else 720

            video_formats: List[Dict[str, Any]] = [
                {
                    "format_id": "auto",
                    "resolution": f"🌟 Auto / Best ({res_str})",
                    "height": h_int,
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                }
            ]

            if h_int >= 720:
                video_formats.append({
                    "format_id": "720p",
                    "resolution": "📹 720p HD",
                    "height": 720,
                    "filesize_mb": 0.0,
                    "exceeds_limit": False,
                })

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

            return MediaResolution(
                url=url,
                service="youtube",
                title=title,
                duration=duration,
                duration_str=duration_str,
                thumbnail=thumbnail,
                video_formats=video_formats,
                audio_formats=audio_formats,
                max_height=h_int,
                ffmpeg_available=ffmpeg_ok,
                direct_stream_url=direct_stream_url,
                direct_audio_url=direct_audio_url,
                resolver_name="pytubefix",
            )
        except Exception as e:
            logger.warning(f"PyTubeFix extraction failed: {e}")
            return None
