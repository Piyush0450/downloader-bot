"""
Unit tests for QR Generation and QR Scanning services.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from productivity_hub.services.qr_generation_service import get_qr_generation_service
from productivity_hub.services.qr_scanning_service import get_qr_scanning_service


class TestQRServices(unittest.TestCase):
    def setUp(self):
        self.gen_service = get_qr_generation_service()
        self.scan_service = get_qr_scanning_service()

    def test_generate_and_scan_url_qr(self):
        test_url = "https://example.com/test-path?param=1"
        img_path, p_type = asyncio.run(
            self.gen_service.generate_qr_image(test_url, payload_type="url")
        )
        self.assertTrue(img_path.exists())
        self.assertEqual(p_type, "url")

        # Scan the generated QR image
        results = asyncio.run(self.scan_service.scan_image(img_path))
        img_path.unlink(missing_ok=True)

        self.assertGreaterEqual(len(results), 1)
        qr_result = results[0]
        self.assertEqual(qr_result.raw_text, test_url)
        self.assertEqual(qr_result.payload_type, "url")
        self.assertTrue(qr_result.is_safe_url)
        self.assertEqual(qr_result.safe_url, test_url)

    def test_interpret_wifi_payload(self):
        wifi_payload = "WIFI:T:WPA;S:HomeNetwork;P:SuperSecret123;;"
        result = self.scan_service.interpret_payload(wifi_payload)
        self.assertEqual(result.payload_type, "wifi")
        self.assertEqual(result.details.get("SSID (Network Name)"), "HomeNetwork")
        self.assertEqual(result.details.get("Password"), "SuperSecret123")

    def test_interpret_vcard_payload(self):
        vcard_payload = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            "FN:Jane Doe\n"
            "TEL;TYPE=CELL:+123456789\n"
            "EMAIL;TYPE=INTERNET:jane@example.com\n"
            "END:VCARD"
        )
        result = self.scan_service.interpret_payload(vcard_payload)
        self.assertEqual(result.payload_type, "vcard")
        self.assertEqual(result.details.get("Full Name"), "Jane Doe")
        self.assertEqual(result.details.get("Phone Number"), "+123456789")


if __name__ == "__main__":
    unittest.main()
