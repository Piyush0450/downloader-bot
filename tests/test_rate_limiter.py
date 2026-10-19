"""
Unit tests for per-user rate limiter.
"""

import unittest
import asyncio
from productivity_hub.utils.rate_limiter import RateLimiter


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limiter_allow_and_block(self):
        # Cooldown of 2 seconds for test_op
        limiter = RateLimiter(cooldowns={"test_op": 2.0, "default": 2.0})
        user_id = 12345

        # 1st request -> allowed
        allowed, wait_time = await limiter.check_rate_limit(user_id, "test_op")
        self.assertTrue(allowed)
        self.assertEqual(wait_time, 0)

        # Immediate 2nd request -> blocked
        allowed, wait_time = await limiter.check_rate_limit(user_id, "test_op")
        self.assertFalse(allowed)
        self.assertGreater(wait_time, 0)

        # Reset user -> allowed again
        await limiter.reset_user(user_id)
        allowed, wait_time = await limiter.check_rate_limit(user_id, "test_op")
        self.assertTrue(allowed)
        self.assertEqual(wait_time, 0)


if __name__ == "__main__":
    unittest.main()
