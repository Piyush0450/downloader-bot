import asyncio
import unittest
from productivity_hub.utils.validators import validate_media_url
from productivity_hub.services.downloader_service import get_downloader_service


class TestShortsDownloadFix(unittest.TestCase):
    def test_shorts_url_extraction_and_validation(self):
        test_cases = [
            ("https://www.youtube.com/shorts/kJQP7kiw5Fk", True, "youtube"),
            ("https://youtube.com/shorts/kJQP7kiw5Fk", True, "youtube"),
            ("https://m.youtube.com/shorts/kJQP7kiw5Fk", True, "youtube"),
            ("https://youtube.com/shorts/kJQP7kiw5Fk?si=abcdef123", True, "youtube"),
            ("https://youtube.com/shorts/kJQP7kiw5Fk?feature=share", True, "youtube"),
            ("Watch this short: https://youtube.com/shorts/kJQP7kiw5Fk", True, "youtube"),
            ("Check https://m.youtube.com/shorts/kJQP7kiw5Fk?si=xyz", True, "youtube"),
        ]
        for text, expected_valid, expected_service in test_cases:
            valid, service, clean_url = validate_media_url(text)
            self.assertEqual(valid, expected_valid, f"Failed validity for {text}")
            self.assertEqual(service, expected_service, f"Failed service for {text}")
            self.assertIn("kJQP7kiw5Fk", clean_url, f"Video ID missing in {clean_url}")

    def test_metadata_callback_data_within_telegram_64_byte_limit(self):
        async def run_check():
            svc = get_downloader_service()
            meta = await svc.get_metadata("https://www.youtube.com/shorts/kJQP7kiw5Fk")
            user_id = 1530123674

            self.assertGreater(len(meta["video_formats"]), 0)
            for fmt in meta["video_formats"]:
                cb = f"dlfmt:{fmt['format_id']}:{user_id}"
                self.assertLessEqual(
                    len(cb.encode("utf-8")),
                    64,
                    f"Video callback_data {cb} exceeds 64 bytes ({len(cb.encode('utf-8'))} bytes)"
                )

            self.assertGreater(len(meta["audio_formats"]), 0)
            for afmt in meta["audio_formats"]:
                cb = f"dlfmt:{afmt['format_id']}:{user_id}"
                self.assertLessEqual(
                    len(cb.encode("utf-8")),
                    64,
                    f"Audio callback_data {cb} exceeds 64 bytes ({len(cb.encode('utf-8'))} bytes)"
                )

        asyncio.run(run_check())


if __name__ == "__main__":
    unittest.main()
