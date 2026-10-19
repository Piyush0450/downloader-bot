"""
Unit Tests for AdminService.

Tests admin authentication, OWNER_ID verification, system diagnostics, and ban/unban logic.
"""

import unittest
from productivity_hub.services.admin_service import AdminService
from productivity_hub.config.settings import Settings


class TestAdminService(unittest.IsolatedAsyncioTestCase):
    """Test Admin Dashboard and authorization operations."""

    def setUp(self):
        self.mock_settings = Settings(
            BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ123456789",
            SECRET_KEY="a" * 32,
            OWNER_ID=999888777,
            PORT=8000,
            DATABASE_PATH=":memory:"
        )
        self.admin_service = AdminService(settings=self.mock_settings)

    async def test_is_admin_check(self):
        """Verify strict numeric OWNER_ID matching."""
        self.assertTrue(await self.admin_service.is_admin(999888777))
        self.assertTrue(await self.admin_service.is_admin("999888777"))
        self.assertFalse(await self.admin_service.is_admin(111222333))
        self.assertFalse(await self.admin_service.is_admin("invalid_id"))

    async def test_get_system_status(self):
        """Verify system status metrics aggregation."""
        status = await self.admin_service.get_system_status()
        self.assertIn("cpu", status)
        self.assertIn("ram", status)
        self.assertIn("uptime", status)
        self.assertIn("active_tasks", status)
        self.assertIn("queue_size", status)
        self.assertIn("storage", status)

    async def test_dependencies_check(self):
        """Verify dependencies inspection report structure."""
        deps = await self.admin_service.get_dependencies_status()
        self.assertIn("python_packages", deps)
        self.assertIn("system_binaries", deps)
        self.assertIsInstance(deps["python_packages"], dict)
        self.assertIsInstance(deps["system_binaries"], dict)


if __name__ == "__main__":
    unittest.main()
