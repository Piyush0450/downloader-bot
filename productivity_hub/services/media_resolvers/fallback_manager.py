"""
Fallback Resolver Manager.
Coordinates platform-specific fallback resolvers and caches direct stream resolutions.
"""

import logging
from typing import Dict, Optional

from productivity_hub.services.media_resolvers.models import MediaResolution
from productivity_hub.services.media_resolvers.instagram_resolver import InstagramResolver
from productivity_hub.services.media_resolvers.tiktok_resolver import TikTokResolver
from productivity_hub.services.media_resolvers.youtube_resolver import YouTubeResolver

logger = logging.getLogger("productivity_hub.services.media_resolvers.manager")


class FallbackManager:
    """Manages secondary and fallback media extraction engines."""

    def __init__(self):
        self._cache: Dict[str, MediaResolution] = {}

    def get_cached_resolution(self, url: str) -> Optional[MediaResolution]:
        """Retrieve direct stream resolution from cache if previously resolved."""
        return self._cache.get(url)

    def cache_resolution(self, url: str, res: MediaResolution) -> None:
        """Cache direct stream resolution for seamless download execution."""
        self._cache[url] = res
        if res.clean_url_key:
            self._cache[res.clean_url_key] = res

    async def resolve_fallback(self, url: str, service: str, max_file_size_bytes: int) -> Optional[MediaResolution]:
        """
        Attempt resolution across all registered fallback engines.
        """
        logger.info(f"Attempting fallback resolvers for service '{service}' URL: {url}")

        # Check Instagram
        if InstagramResolver.can_handle(url, service):
            res = await InstagramResolver.resolve(url, max_file_size_bytes)
            if res:
                logger.info(f"Fallback resolution succeeded via InstagramResolver ({res.resolver_name})")
                self.cache_resolution(url, res)
                return res

        # Check TikTok
        if TikTokResolver.can_handle(url, service):
            res = await TikTokResolver.resolve(url, max_file_size_bytes)
            if res:
                logger.info(f"Fallback resolution succeeded via TikTokResolver ({res.resolver_name})")
                self.cache_resolution(url, res)
                return res

        # Check YouTube
        if YouTubeResolver.can_handle(url, service):
            res = await YouTubeResolver.resolve(url, max_file_size_bytes)
            if res:
                logger.info(f"Fallback resolution succeeded via YouTubeResolver ({res.resolver_name})")
                self.cache_resolution(url, res)
                return res

        logger.warning(f"All fallback resolvers exhausted for {url}")
        return None


# Global singleton instance
_fallback_manager_instance: Optional[FallbackManager] = None


def get_fallback_manager() -> FallbackManager:
    """Retrieve global FallbackManager singleton instance."""
    global _fallback_manager_instance
    if _fallback_manager_instance is None:
        _fallback_manager_instance = FallbackManager()
    return _fallback_manager_instance
