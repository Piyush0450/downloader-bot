"""
Unit tests for universal compression_service.py.
"""

import tempfile
import unittest
from pathlib import Path
from PIL import Image

from productivity_hub.services.compression_service import get_compression_service


class TestCompressionService(unittest.TestCase):
    def setUp(self):
        self.service = get_compression_service()

    def test_compress_image(self):
        import asyncio

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_img = tmp_path / "large.jpg"

            # Create uncompressed large test image
            img = Image.new("RGB", (400, 400), color=(100, 150, 200))
            img.save(source_img, "JPEG", quality=100)
            orig_size = source_img.stat().st_size

            # Run high compression
            res = asyncio.run(self.service.compress_file(source_img, level="high"))
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.category, "image")
            self.assertEqual(res.original_size, orig_size)
            self.assertGreater(res.compressed_size, 0)

    def test_compress_generic_zip(self):
        import asyncio

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "data.txt"
            source_file.write_text("Hello world repeated content " * 100, encoding="utf-8")

            res = asyncio.run(self.service.compress_file(source_file))
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.category, "archive")
            self.assertTrue(res.is_reduced)
            self.assertGreater(res.bytes_saved, 0)


if __name__ == "__main__":
    unittest.main()
