"""
Smart File Type and Magic Byte Signature Detector.

Inspects raw file headers (magic bytes) and mimetypes to accurately identify true file types,
preventing file extension spoofing attacks (e.g., executable disguised as .pdf or .png).
"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FileTypeInfo:
    """
    Metadata representation of detected file properties.

    Attributes:
        extension: Primary file extension (e.g., 'pdf', 'png').
        mime_type: Standardized MIME type (e.g., 'application/pdf').
        category: High-level classification ('document', 'image', 'audio', 'video', 'archive', 'text', 'unknown').
        is_validated: True if header magic bytes matched known signature.
    """
    extension: str
    mime_type: str
    category: str
    is_validated: bool = False


# Known magic byte header signatures
MAGIC_SIGNATURES = [
    # PDF
    (b"%PDF-", "pdf", "application/pdf", "document"),
    # PNG
    (b"\x89PNG\r\n\x1a\n", "png", "image/png", "image"),
    # JPEG
    (b"\xff\xd8\xff", "jpg", "image/jpeg", "image"),
    # GIF
    (b"GIF87a", "gif", "image/gif", "image"),
    (b"GIF89a", "gif", "image/gif", "image"),
    # WEBP
    (b"RIFF", "webp", "image/webp", "image"),  # Substring check for WEBP at byte 8
    # ZIP / DOCX / XLSX / PPTX
    (b"PK\x03\x04", "zip", "application/zip", "archive"),
    # MP3 (ID3)
    (b"ID3", "mp3", "audio/mpeg", "audio"),
    # WAV
    (b"RIFF", "wav", "audio/wav", "audio"),
]


def detect_file_type(file_path: Path) -> FileTypeInfo:
    """
    Detect the real file type of a file by inspecting magic bytes and mimetypes.

    Args:
        file_path: Absolute or relative Path to target file.

    Returns:
        FileTypeInfo: Verified file extension, mime type, and category.
    """
    if not file_path.exists() or not file_path.is_file():
        return FileTypeInfo(extension="unknown", mime_type="application/octet-stream", category="unknown", is_validated=False)

    ext_fallback = file_path.suffix.lstrip(".").lower()
    mime_fallback, _ = mimetypes.guess_type(str(file_path))
    mime_fallback = mime_fallback or "application/octet-stream"

    # Read header bytes (first 32 bytes)
    header = b""
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)
    except Exception:
        pass

    if header:
        # Check Magic Signatures
        for sig, ext, mime, cat in MAGIC_SIGNATURES:
            if header.startswith(sig):
                # Special handling for RIFF containers (WEBP vs WAV)
                if sig == b"RIFF":
                    if len(header) >= 12 and header[8:12] == b"WEBP":
                        return FileTypeInfo(extension="webp", mime_type="image/webp", category="image", is_validated=True)
                    elif len(header) >= 12 and header[8:12] == b"WAVE":
                        return FileTypeInfo(extension="wav", mime_type="audio/wav", category="audio", is_validated=True)
                    continue

                # Special handling for Office Open XML (DOCX / XLSX / PPTX disguised as ZIP)
                if ext == "zip":
                    if ext_fallback in ("docx", "xlsx", "pptx"):
                        return FileTypeInfo(extension=ext_fallback, mime_type=mime_fallback, category="document", is_validated=True)
                    return FileTypeInfo(extension="zip", mime_type="application/zip", category="archive", is_validated=True)

                return FileTypeInfo(extension=ext, mime_type=mime, category=cat, is_validated=True)

        # Check MP4 ftyp box
        if len(header) >= 8 and header[4:8] == b"ftyp":
            return FileTypeInfo(extension="mp4", mime_type="video/mp4", category="video", is_validated=True)

    # Fallback to extension & mimetype guessing
    category = "unknown"
    if mime_fallback.startswith("image/"):
        category = "image"
    elif mime_fallback.startswith("audio/"):
        category = "audio"
    elif mime_fallback.startswith("video/"):
        category = "video"
    elif mime_fallback.startswith("text/") or ext_fallback in ("txt", "csv", "json", "md"):
        category = "text"
    elif mime_fallback.startswith("application/pdf") or ext_fallback in ("pdf", "docx", "doc", "xlsx", "pptx"):
        category = "document"

    return FileTypeInfo(
        extension=ext_fallback or "bin",
        mime_type=mime_fallback,
        category=category,
        is_validated=False
    )
