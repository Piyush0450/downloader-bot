"""
QR Code Generation Service & Payload Builders.

Supports standardized encoding for Basic Text, URLs, Contacts (vCard 3.0 / MECARD),
Wi-Fi configurations, Calendar events (iCalendar VEVENT), SMS/Messaging deep links,
and Payment URIs (UPI, Bitcoin, Ethereum, SEPA).
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_H

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.utils.safe_filename import generate_safe_filepath

logger = logging.getLogger("productivity_hub.services.qr_generation")

OUTPUT_DIR = Path("temp/qr")


class QRGenerationError(Exception):
    """Raised when QR encoding or image generation fails."""
    pass


class QRGenerationService:
    """
    Asynchronous QR code generation engine.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def format_wifi_payload(ssid: str, password: str = "", security: str = "WPA", hidden: bool = False) -> str:
        """Format standard WIFI: payload."""
        sec = security.upper() if security else "nopass"
        h_str = "H:true;" if hidden else ""
        return f"WIFI:T:{sec};S:{ssid};P:{password};{h_str};"

    @staticmethod
    def format_vcard_payload(
        name: str,
        phone: str = "",
        email: str = "",
        organization: str = "",
        title: str = "",
        url: str = ""
    ) -> str:
        """Format vCard 3.0 payload."""
        lines = [
            "BEGIN:VCARD",
            "VERSION:3.0",
            f"FN:{name}",
            f"N:;{name};;;",
        ]
        if organization:
            lines.append(f"ORG:{organization}")
        if title:
            lines.append(f"TITLE:{title}")
        if phone:
            lines.append(f"TEL;TYPE=CELL:{phone}")
        if email:
            lines.append(f"EMAIL;TYPE=INTERNET:{email}")
        if url:
            lines.append(f"URL:{url}")
        lines.append("END:VCARD")
        return "\n".join(lines)

    @staticmethod
    def format_event_payload(
        title: str,
        start_datetime: str,  # Format: YYYYMMDDTHHMMSSZ or YYYYMMDD
        end_datetime: str = "",
        location: str = "",
        description: str = ""
    ) -> str:
        """Format iCalendar VEVENT payload."""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            f"SUMMARY:{title}",
            f"DTSTART:{start_datetime}",
        ]
        if end_datetime:
            lines.append(f"DTEND:{end_datetime}")
        if location:
            lines.append(f"LOCATION:{location}")
        if description:
            lines.append(f"DESCRIPTION:{description}")
        lines.extend(["END:VEVENT", "END:VCALENDAR"])
        return "\n".join(lines)

    @staticmethod
    def format_sms_payload(phone: str, message: str = "") -> str:
        """Format SMS payload."""
        return f"SMSTO:{phone}:{message}"

    async def generate_qr_image(
        self,
        payload: str,
        payload_type: str = "text",
        user_id: int = 0,
        high_error_correction: bool = False
    ) -> Tuple[Path, str]:
        """
        Generate a QR code image from payload string.

        Args:
            payload: Formatted QR payload string.
            payload_type: Category identifier ('text', 'url', 'wifi', 'vcard', etc.).
            user_id: Telegram user ID.
            high_error_correction: Use Error Correction Level H for dense payloads.

        Returns:
            Tuple[Path, str]: (Saved image Path, payload_type).
        """
        if not payload or not payload.strip():
            raise QRGenerationError("QR payload cannot be empty.")

        target_path, _ = generate_safe_filepath(OUTPUT_DIR, f"qr_{payload_type}.png", prefix="qr")

        loop = asyncio.get_running_loop()
        try:
            res_path = await loop.run_in_executor(
                None, self._sync_make_qr, payload.strip(), target_path, high_error_correction
            )
            logger.info(f"Generated QR image for user {user_id} (type={payload_type})")
            return res_path, payload_type
        except Exception as e:
            logger.error(f"Failed to generate QR for user {user_id}: {e}", exc_info=True)
            raise QRGenerationError(f"Failed to generate QR code: {str(e)}")

    @staticmethod
    def _sync_make_qr(payload: str, target_path: Path, high_ec: bool) -> Path:
        """Synchronous QR drawing with Pillow."""
        ec_level = ERROR_CORRECT_H if high_ec else ERROR_CORRECT_M
        qr = qrcode.QRCode(
            version=None,
            error_correction=ec_level,
            box_size=12,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(target_path)
        return target_path


# Global service singleton
_qr_gen_instance: Optional[QRGenerationService] = None


def get_qr_generation_service() -> QRGenerationService:
    """Retrieve global QRGenerationService singleton."""
    global _qr_gen_instance
    if _qr_gen_instance is None:
        _qr_gen_instance = QRGenerationService()
    return _qr_gen_instance
