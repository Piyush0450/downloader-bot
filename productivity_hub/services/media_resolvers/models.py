"""
Models for multi-engine media extraction and resolution.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MediaResolution:
    """Unified container for media metadata extracted from any engine."""
    url: str
    service: str
    title: str
    duration: int
    duration_str: str
    thumbnail: Optional[str]
    video_formats: List[Dict[str, Any]]
    audio_formats: List[Dict[str, Any]]
    max_height: int
    ffmpeg_available: bool
    direct_stream_url: Optional[str] = None
    direct_audio_url: Optional[str] = None
    clean_url_key: Optional[str] = None
    resolver_name: str = "primary"
    headers: Dict[str, str] = field(default_factory=dict)

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Convert to the standard dictionary consumed by bot handlers."""
        return {
            "url": self.url,
            "service": self.service,
            "title": self.title,
            "duration": self.duration,
            "duration_str": self.duration_str,
            "thumbnail": self.thumbnail,
            "video_formats": self.video_formats,
            "audio_formats": self.audio_formats,
            "max_height": self.max_height,
            "ffmpeg_available": self.ffmpeg_available,
            "resolver_name": self.resolver_name,
            "direct_stream_url": self.direct_stream_url,
            "direct_audio_url": self.direct_audio_url,
        }
