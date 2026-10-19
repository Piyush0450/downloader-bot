"""
Unit tests for URL and domain validators in productivity_hub.
"""

import unittest
from productivity_hub.utils.validators import isValidUrl, isValidDomain, validate_file_size, is_whitelisted_domain


class TestValidators(unittest.TestCase):
    def test_is_valid_url(self):
        self.assertTrue(isValidUrl("https://youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(isValidUrl("http://instagram.com/p/C123456/"))
        self.assertTrue(isValidUrl("https://tiktok.com/@user/video/123456"))
        self.assertFalse(isValidUrl("not_a_url"))
        self.assertFalse(isValidUrl("ftp://invalid-protocol.com"))
        self.assertFalse(isValidUrl(""))

    def test_is_valid_domain(self):
        self.assertTrue(isValidDomain("https://youtube.com/watch?v=123", ["youtube.com", "youtu.be"]))
        self.assertTrue(isValidDomain("https://youtu.be/123", ["youtube.com", "youtu.be"]))
        self.assertFalse(isValidDomain("https://malicious-site.com/video", ["youtube.com", "youtu.be"]))

    def test_whitelisted_domain(self):
        self.assertTrue(is_whitelisted_domain("https://www.youtube.com/watch?v=123"))
        self.assertTrue(is_whitelisted_domain("https://twitter.com/status/123"))
        self.assertFalse(is_whitelisted_domain("https://unknown-untrusted-site.org/file"))

    def test_validate_file_size(self):
        # Default 50MB limit = 52,428,800 bytes
        self.assertTrue(validate_file_size(1024 * 1024))
        self.assertFalse(validate_file_size(60 * 1024 * 1024))

    def test_validate_media_url_platforms(self):
        from productivity_hub.utils.validators import validate_media_url
        valid, service, _ = validate_media_url("https://www.snapchat.com/add/testuser")
        self.assertTrue(valid)
        self.assertEqual(service, "snapchat")

        valid, service, _ = validate_media_url("https://soundcloud.com/artist/track")
        self.assertTrue(valid)
        self.assertEqual(service, "soundcloud")

        valid, service, _ = validate_media_url("https://www.reddit.com/r/videos/comments/xyz")
        self.assertTrue(valid)
        self.assertEqual(service, "reddit")

        valid, service, _ = validate_media_url("javascript:alert(1)")
        self.assertFalse(valid)
        self.assertEqual(service, "invalid_url")


if __name__ == "__main__":
    unittest.main()
