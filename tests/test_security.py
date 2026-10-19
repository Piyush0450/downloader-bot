"""
Unit tests for Zip Slip protection and secret masking security utilities.
"""

import unittest
import tempfile
import zipfile
from pathlib import Path
from productivity_hub.utils.security import safe_extract_zip, SecurityError, mask_secrets


class TestSecurity(unittest.TestCase):
    def test_mask_secrets(self):
        token_sample = "My token is 9876543210:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567 and key='MySecretKey'"
        masked = mask_secrets(token_sample)
        self.assertIn("[REDACTED_BOT_TOKEN]", masked)
        self.assertIn("key=[REDACTED]", masked)
        self.assertNotIn("MySecretKey", masked)

    def test_safe_extract_zip_normal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            zip_file = temp_path / "valid.zip"

            with zipfile.ZipFile(zip_file, "w") as zf:
                zf.writestr("test_file.txt", "Sample contents")

            target_dir = temp_path / "out"
            extracted = safe_extract_zip(zip_file, target_dir)
            self.assertEqual(len(extracted), 1)
            self.assertTrue(extracted[0].exists())

    def test_zip_slip_prevention(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            bad_zip = temp_path / "zip_slip.zip"

            with zipfile.ZipFile(bad_zip, "w") as zf:
                zf.writestr("../evil_file.txt", "Path traversal payload")

            target_dir = temp_path / "out"
            with self.assertRaises(SecurityError):
                safe_extract_zip(bad_zip, target_dir)


if __name__ == "__main__":
    unittest.main()
