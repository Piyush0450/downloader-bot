"""
QR Code Scanning & Payload Interpretation Service.

Decodes uploaded images using pyzbar (or OpenCV fallback), detects multi-payloads,
identifies structured payload types (URL, Wi-Fi, vCard, Calendar, Email, SMS, Payment URIs),
and formats safe preview representations without automatic execution.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs
from PIL import Image

logger = logging.getLogger("productivity_hub.services.qr_scanning")

# Safe import of pyzbar with OpenCV fallback
PYZBAR_AVAILABLE = False
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    PYZBAR_AVAILABLE = True
except Exception as e:
    logger.warning(f"pyzbar libraries not available ({e}). Falling back to OpenCV QR detector.")

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


@dataclass
class DecodedQRPayload:
    """Represents an analyzed and decoded QR payload."""
    raw_text: str
    payload_type: str  # 'url', 'wifi', 'vcard', 'event', 'email', 'phone', 'sms', 'payment', 'text'
    type_display: str
    details: Dict[str, Any]
    is_safe_url: bool = False
    safe_url: Optional[str] = None


class QRScanningError(Exception):
    """Raised when QR scanning or decoding fails."""
    pass


class QRScanningService:
    """
    Asynchronous QR code scanner and payload analyzer.
    """

    async def scan_image(self, image_path: Path, user_id: int = 0) -> List[DecodedQRPayload]:
        """
        Scan image file for QR codes asynchronously and interpret all found payloads.

        Args:
            image_path: Input image file Path.
            user_id: Telegram user ID.

        Returns:
            List[DecodedQRPayload]: Decoded results.
        """
        if not image_path.exists():
            return []

        loop = asyncio.get_running_loop()
        raw_payloads = await loop.run_in_executor(None, self._sync_scan, image_path)

        interpreted_results = []
        for raw in raw_payloads:
            interpreted = self.interpret_payload(raw)
            interpreted_results.append(interpreted)

        logger.info(f"Scanned QR image for user {user_id}: found {len(interpreted_results)} QR payload(s).")
        return interpreted_results

    def interpret_payload(self, text: str) -> DecodedQRPayload:
        """
        Classify raw QR content into standard formats and extract structured attributes.
        """
        raw = text.strip()

        # 1. Wi-Fi Configuration
        if raw.upper().startswith("WIFI:"):
            details = {}
            for match in re.finditer(r"([T|S|P|H]):([^;]*);", raw, re.IGNORECASE):
                key, val = match.group(1).upper(), match.group(2)
                if key == "S":
                    details["SSID (Network Name)"] = val
                elif key == "T":
                    details["Security"] = val or "None (Open)"
                elif key == "P":
                    details["Password"] = val or "(No Password)"
                elif key == "H":
                    details["Hidden"] = "Yes" if val.lower() == "true" else "No"

            return DecodedQRPayload(
                raw_text=raw,
                payload_type="wifi",
                type_display="📶 Wi-Fi Network Credentials",
                details=details
            )

        # 2. vCard 3.0 / Contact Info
        if "BEGIN:VCARD" in raw.upper():
            details = {}
            for line in raw.splitlines():
                if line.startswith("FN:"):
                    details["Full Name"] = line[3:]
                elif "TEL" in line and ":" in line:
                    details["Phone Number"] = line.split(":", 1)[1]
                elif "EMAIL" in line and ":" in line:
                    details["Email"] = line.split(":", 1)[1]
                elif line.startswith("ORG:"):
                    details["Organization"] = line[4:]
                elif line.startswith("TITLE:"):
                    details["Job Title"] = line[6:]
                elif line.startswith("URL:"):
                    details["Website"] = line[4:]

            return DecodedQRPayload(
                raw_text=raw,
                payload_type="vcard",
                type_display="👤 Contact Card (vCard)",
                details=details
            )

        # 3. Calendar Event (VEVENT)
        if "BEGIN:VEVENT" in raw.upper():
            details = {}
            for line in raw.splitlines():
                if line.startswith("SUMMARY:"):
                    details["Event Title"] = line[8:]
                elif line.startswith("LOCATION:"):
                    details["Location"] = line[9:]
                elif line.startswith("DTSTART:"):
                    details["Start Time"] = line[8:]
                elif line.startswith("DTEND:"):
                    details["End Time"] = line[6:]
                elif line.startswith("DESCRIPTION:"):
                    details["Description"] = line[12:]

            return DecodedQRPayload(
                raw_text=raw,
                payload_type="event",
                type_display="📅 Calendar Event",
                details=details
            )

        # 4. HTTP / HTTPS Website URL
        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlparse(raw)
            details = {
                "Domain": parsed.netloc,
                "Protocol": parsed.scheme.upper(),
                "Full Link": raw,
            }
            return DecodedQRPayload(
                raw_text=raw,
                payload_type="url",
                type_display="🌐 Website URL",
                details=details,
                is_safe_url=parsed.scheme in ("http", "https") and bool(parsed.netloc),
                safe_url=raw
            )

        # 5. Email (mailto: or MATMSG:)
        if raw.lower().startswith("mailto:") or raw.upper().startswith("MATMSG:"):
            details = {}
            if raw.upper().startswith("MATMSG:"):
                to_m = re.search(r"TO:([^;]+);", raw)
                sub_m = re.search(r"SUB:([^;]+);", raw)
                body_m = re.search(r"BODY:([^;]+);", raw)
                if to_m:
                    details["Recipient"] = to_m.group(1)
                if sub_m:
                    details["Subject"] = sub_m.group(1)
                if body_m:
                    details["Body"] = body_m.group(1)
            else:
                details["Recipient"] = raw[7:].split("?")[0]

            return DecodedQRPayload(
                raw_text=raw,
                payload_type="email",
                type_display="✉️ Email Message",
                details=details
            )

        # 6. SMS or Phone link
        if raw.lower().startswith("smsto:") or raw.lower().startswith("sms:"):
            parts = raw.split(":", 2)
            phone = parts[1] if len(parts) > 1 else ""
            msg = parts[2] if len(parts) > 2 else ""
            return DecodedQRPayload(
                raw_text=raw,
                payload_type="sms",
                type_display="💬 SMS Message",
                details={"Recipient Number": phone, "Message": msg}
            )
        elif raw.lower().startswith("tel:"):
            return DecodedQRPayload(
                raw_text=raw,
                payload_type="phone",
                type_display="📞 Phone Number",
                details={"Telephone": raw[4:]}
            )

        # 7. Payment URIs (UPI, Crypto)
        if raw.lower().startswith("upi://pay"):
            parsed = urlparse(raw)
            params = parse_qs(parsed.query)
            details = {
                "UPI ID": params.get("pa", [""])[0],
                "Payee Name": params.get("pn", [""])[0],
                "Amount": params.get("am", [""])[0] or "Flexible",
                "Currency": params.get("cu", ["INR"])[0],
            }
            return DecodedQRPayload(
                raw_text=raw,
                payload_type="payment",
                type_display="💳 UPI Payment Link",
                details=details
            )
        elif raw.lower().startswith("bitcoin:") or raw.lower().startswith("ethereum:"):
            return DecodedQRPayload(
                raw_text=raw,
                payload_type="payment",
                type_display="💰 Cryptocurrency Address",
                details={"Address": raw.split("?")[0]}
            )

        # 8. Plain Text Fallback
        return DecodedQRPayload(
            raw_text=raw,
            payload_type="text",
            type_display="📝 Plain Text",
            details={"Characters": len(raw), "Lines": len(raw.splitlines())}
        )

    def _sync_scan(self, image_path: Path) -> List[str]:
        """Synchronous decoding helper trying pyzbar and OpenCV."""
        results: List[str] = []

        # Strategy 1: pyzbar
        if PYZBAR_AVAILABLE:
            try:
                with Image.open(image_path) as img:
                    decoded = pyzbar_decode(img)
                    for item in decoded:
                        s = item.data.decode("utf-8", errors="replace").strip()
                        if s and s not in results:
                            results.append(s)
                if results:
                    return results
            except Exception as e:
                logger.warning(f"pyzbar decode failed: {e}")

        # Strategy 2: OpenCV QRCodeDetector
        if OPENCV_AVAILABLE:
            try:
                cv_img = cv2.imread(str(image_path))
                if cv_img is not None:
                    detector = cv2.QRCodeDetector()
                    # Try primary single detector first
                    data, bbox, _ = detector.detectAndDecode(cv_img)
                    if data and data.strip():
                        results.append(data.strip())

                    # Also try multi detection for multiple QR codes in one image
                    if hasattr(detector, "detectAndDecodeMulti"):
                        try:
                            retval, decoded_info, _, _ = detector.detectAndDecodeMulti(cv_img)
                            if retval and decoded_info:
                                for s in decoded_info:
                                    s_clean = s.strip()
                                    if s_clean and s_clean not in results:
                                        results.append(s_clean)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"OpenCV decode failed: {e}")

        return results


# Global scanning service singleton
_qr_scanner_instance: Optional[QRScanningService] = None


def get_qr_scanning_service() -> QRScanningService:
    """Retrieve global QRScanningService singleton."""
    global _qr_scanner_instance
    if _qr_scanner_instance is None:
        _qr_scanner_instance = QRScanningService()
    return _qr_scanner_instance
