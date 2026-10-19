"""
Unit tests for DependencyChecker utility.
"""

import unittest
from productivity_hub.utils.dependency_checker import get_dependency_checker, DependencyStatus


class TestDependencyChecker(unittest.TestCase):
    def setUp(self):
        self.checker = get_dependency_checker()

    def test_singleton_instance(self):
        checker2 = get_dependency_checker()
        self.assertIs(self.checker, checker2)

    def test_check_known_python_module(self):
        status = self.checker.check_python_module("sys")
        self.assertTrue(status.available)
        self.assertIn("found", status.details.lower())

    def test_check_nonexistent_python_module(self):
        status = self.checker.check_python_module("non_existent_fake_package_xyz123")
        self.assertFalse(status.available)
        self.assertIn("not found", status.details.lower())

    def test_check_nonexistent_binary(self):
        status = self.checker.check_binary("non_existent_binary_tool_xyz_99")
        self.assertFalse(status.available)
        self.assertIn("not found", status.details.lower())

    def test_get_full_diagnostics(self):
        diagnostics = self.checker.get_full_diagnostics()
        self.assertIsInstance(diagnostics, dict)
        self.assertIn("ffmpeg", diagnostics)
        self.assertIn("py_Pillow", diagnostics)


if __name__ == "__main__":
    unittest.main()
