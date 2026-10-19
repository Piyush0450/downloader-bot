"""
Multi-Engine Media Resolver Architecture.
Provides independent, modular fallback resolvers for social media platforms
(Instagram, TikTok, YouTube, Twitter/X) when primary yt-dlp scraping is restricted.
"""

from .models import MediaResolution
from .fallback_manager import get_fallback_manager, FallbackManager

__all__ = ["MediaResolution", "get_fallback_manager", "FallbackManager"]
