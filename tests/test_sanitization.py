"""
Unit tests for safe filename sanitization and path traversal prevention.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from productivity_hub.utils.safe_filename import sanitize_filename, generate_safe_filepath


class TestSanitization(unittest.TestCase):
    def test_sanitize_filename(self):
        # Path traversal characters must be stripped
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("image<script>.png"), "image_script_.png")
        self.assertEqual(sanitize_filename("normal_file.pdf"), "normal_file.pdf")
        self.assertEqual(sanitize_filename(""), "unnamed_file")

    def test_generate_safe_filepath(self):
        with TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)
            target_path, display_name = generate_safe_filepath(
                directory=dir_path,
                original_filename="../../../malicious_exec.sh",
                prefix="test"
            )

            # Resolved path must strictly reside inside target dir
            self.assertTrue(str(target_path.resolve()).startswith(str(dir_path.resolve())))
            self.assertTrue(target_path.name.startswith("test_"))
            self.assertIn("malicious_exec.sh", display_name)


if __name__ == "__main__":
    unittest.main()
