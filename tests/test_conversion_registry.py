"""
Unit tests for functional document and image conversion registry.
"""

import unittest
from productivity_hub.utils.conversion_registry import get_conversion_registry


class TestConversionRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = get_conversion_registry()

    def test_available_conversions(self):
        # PNG image targets
        png_conversions = self.registry.get_available_conversions("png")
        png_targets = [rule.target_format for rule in png_conversions]
        self.assertIn("jpg", png_targets)
        self.assertIn("pdf", png_targets)

    def test_unsupported_format(self):
        invalid_conversions = self.registry.get_available_conversions("unknown_ext_xyz")
        self.assertEqual(len(invalid_conversions), 0)

    def test_get_rule(self):
        rule = self.registry.get_rule("png", "jpg")
        self.assertIsNotNone(rule)
        if rule:
            self.assertEqual(rule.source_format, "png")
            self.assertEqual(rule.target_format, "jpg")

    def test_image_conversion_execution(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from productivity_hub.services.conversion_service import get_conversion_service

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_img = tmp_path / "test.png"
            img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
            img.save(source_img, "PNG")

            service = get_conversion_service()
            target_out = tmp_path / "test_out.jpg"
            res = service._sync_execute_conversion(source_img, target_out, "png", "jpg")
            self.assertTrue(res.exists())
            self.assertGreater(res.stat().st_size, 0)

            # Validate that output is a valid JPEG
            with Image.open(res) as converted_img:
                self.assertEqual(converted_img.format, "JPEG")

    def test_csv_to_xlsx_conversion_execution(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        from productivity_hub.services.conversion_service import get_conversion_service

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_csv = tmp_path / "data.csv"
            source_csv.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")

            service = get_conversion_service()
            target_out = tmp_path / "data.xlsx"
            res = service._sync_execute_conversion(source_csv, target_out, "csv", "xlsx")
            self.assertTrue(res.exists())
            self.assertGreater(res.stat().st_size, 0)

            # Validate reading XLSX
            import io
            with open(res, "rb") as f:
                content = f.read()
            wb = openpyxl.load_workbook(io.BytesIO(content))
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))
            wb.close()
            self.assertEqual(rows[0], ("name", "age"))
            self.assertEqual(rows[1], ("Alice", "30"))


if __name__ == "__main__":
    unittest.main()
