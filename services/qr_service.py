import asyncio
from io import BytesIO
from pathlib import Path
import qrcode
import cv2
from utils.logger import logger

def create_qr_bytes(data: str) -> BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def scan_qr_image_sync(image_path: Path) -> dict:
    """Scan QR code and return a dictionary with content and parsed type.
    Types: 'URL', 'CONTACT', 'TEXT'
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return {"content": "", "type": "TEXT"}
            
        detector = cv2.QRCodeDetector()
        val, _, _ = detector.detectAndDecode(img)
        if not val:
            return {"content": "", "type": "TEXT"}
            
        # Analyze content type
        content_lower = val.lower().strip()
        val_type = "TEXT"
        
        if content_lower.startswith(("http://", "https://")):
            val_type = "URL"
        elif content_lower.startswith(("begin:vcard", "mecard:")):
            val_type = "CONTACT"
            
        return {"content": val, "type": val_type}
    except Exception as e:
        logger.error(f"Error scanning QR: {e}")
        return {"content": "", "type": "TEXT"}

async def scan_qr_image(image_path: Path) -> dict:
    return await asyncio.to_thread(scan_qr_image_sync, image_path)

async def generate_qr(data: str) -> BytesIO:
    return await asyncio.to_thread(create_qr_bytes, data)
