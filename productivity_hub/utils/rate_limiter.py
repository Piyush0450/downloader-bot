"""
Per-User Operations Rate Limiter.

Implements an in-memory sliding window rate limiter to prevent spam, API quota exhaustion,
and denial-of-service attacks. Supports customized cooldown periods based on operation type.
"""

import asyncio
import time
from typing import Dict, Tuple


# Default cooldown periods per operation type (in seconds)
OPERATION_COOLDOWNS: Dict[str, float] = {
    "download": 30.0,            # Heavy network & CPU operation
    "conversion": 15.0,          # Document rendering operation
    "background_removal": 15.0,  # AI model inference operation
    "compressor": 15.0,          # Compression operation
    "qr": 5.0,                   # Fast QR operation
    "admin": 1.0,                # Admin commands
    "default": 3.0,              # Standard default cooldown
}


class RateLimiter:
    """
    Sliding window per-user rate limiter.
    """

    def __init__(self, cooldowns: Dict[str, float] = OPERATION_COOLDOWNS):
        self.cooldowns = cooldowns
        # Map: (user_id, operation_type) -> last_execution_timestamp
        self._last_executed: Dict[Tuple[int, str], float] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: int, operation_type: str = "default") -> Tuple[bool, float]:
        """
        Check if a user is permitted to perform a given operation type.

        Args:
            user_id: Telegram numeric user ID.
            operation_type: Type of operation ('download', 'conversion', 'qr', 'default', etc.).

        Returns:
            Tuple[bool, float]:
                - bool: True if operation is allowed, False if rate-limited.
                - float: Remaining wait time in seconds (0.0 if allowed).
        """
        now = time.time()
        cooldown = self.cooldowns.get(operation_type, self.cooldowns["default"])
        key = (user_id, operation_type)

        async with self._lock:
            last_time = self._last_executed.get(key, 0.0)
            elapsed = now - last_time

            if elapsed < cooldown:
                remaining = cooldown - elapsed
                return False, round(remaining, 1)

            # Update last execution time
            self._last_executed[key] = now
            return True, 0.0

    async def reset_user(self, user_id: int) -> None:
        """Clear rate limit history for a specific user."""
        async with self._lock:
            keys_to_delete = [k for k in self._last_executed if k[0] == user_id]
            for k in keys_to_delete:
                del self._last_executed[k]


# Global RateLimiter singleton instance
_rate_limiter_instance = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Retrieve global RateLimiter instance."""
    return _rate_limiter_instance
