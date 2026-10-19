"""
Unit Tests for BackgroundRemovalService.

Tests availability reporting, memory safety dimensions, and error handling for missing inputs.
"""

import unittest
from pathlib import Path
from PIL import Image
from productivity_hub.services.background_removal_service import (
    BackgroundRemovalService,
    BackgroundRemovalError,
    MAX_IMAGE_DIMENSION
)


class TestBackgroundRemovalService(unittest.IsolatedAsyncioTestCase):
    """Test image background removal service."""

    def setUp(self):
        self.service = BackgroundRemovalService()
        self.temp_dir = Path("temp/test_bg")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_engine_availability_check(self):
        """Verify engine availability returns a boolean."""
        avail = self.service.is_engine_available()
        self.assertIsInstance(avail, bool)

    async def test_non_existent_file_raises_error(self):
        """Verify missing source image raises BackgroundRemovalError."""
        fake_path = self.temp_dir / "non_existent.jpg"
        with self.assertRaises(BackgroundRemovalError):
            await self.service.remove_background(fake_path, user_id=123)

    def test_dimension_safety_check(self):
        """Verify max dimension limit constant."""
        self.assertGreaterEqual(MAX_IMAGE_DIMENSION, 1024)


if __name__ == "__main__":
    unittest.main()
