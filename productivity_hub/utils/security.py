"""
Security Utilities & Safe Extraction Module.

Provides path traversal (Zip Slip) protection, decompression bomb limits,
and secret masking helpers.
"""

import os
import shutil
import zipfile
import logging
import re

from pathlib import Path
from typing import List

logger = logging.getLogger("productivity_hub.utils.security")

# Maximum uncompressed bytes (100 MB default)
MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024
# Maximum file count per archive
MAX_FILE_COUNT = 500


class SecurityError(Exception):
    """Raised when a security policy violation is detected."""
    pass


def safe_extract_zip(
    zip_path: Path,
    extract_to: Path,
    max_total_bytes: int = MAX_DECOMPRESSED_SIZE,
    max_files: int = MAX_FILE_COUNT
) -> List[Path]:
    """
    Safely extract a ZIP archive while protecting against Zip Slip path traversal
    and decompression bomb attacks.

    Args:
        zip_path: Input ZIP file Path.
        extract_to: Destination directory Path.
        max_total_bytes: Maximum total uncompressed payload bytes allowed.
        max_files: Maximum number of files permitted in archive.

    Returns:
        List[Path]: List of extracted file paths.
    """
    extract_to = extract_to.resolve()
    extract_to.mkdir(parents=True, exist_ok=True)

    extracted_files: List[Path] = []
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(zip_path, 'r') as zf:
        infolist = zf.infolist()

        if len(infolist) > max_files:
            raise SecurityError(f"Decompression bomb blocked: archive contains too many files ({len(infolist)} > {max_files}).")

        for member in infolist:
            # 1. Decompression Bomb Size Accumulation Check
            total_uncompressed_bytes += member.file_size
            if total_uncompressed_bytes > max_total_bytes:
                raise SecurityError(
                    f"Decompression bomb blocked: total uncompressed size exceeds limit ({total_uncompressed_bytes} > {max_total_bytes} bytes)."
                )

            # 2. Zip Slip Path Traversal Check
            target_path = (extract_to / member.filename).resolve()
            if not str(target_path).startswith(str(extract_to)):
                raise SecurityError(f"Zip Slip attack blocked: path traversal in '{member.filename}'")

            # Extract safe file
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, open(target_path, "wb") as target:
                    shutil.copyfileobj(source, target)
                extracted_files.append(target_path)

    logger.info(f"Safely extracted {len(extracted_files)} files ({total_uncompressed_bytes} bytes) from {zip_path.name}")
    return extracted_files


def mask_secrets(text: str) -> str:
    """
    Redact Telegram Bot Tokens, passwords, and sensitive keys from text strings or logs.
    """
    if not text:
        return ""
    # Redact Telegram bot tokens (e.g. 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ...)
    masked = re.sub(r"\b\d{8,10}:[A-Za-z0-9_-]{30,50}\b", "[REDACTED_BOT_TOKEN]", text)
    # Redact potential password parameters
    masked = re.sub(r"(?i)(password|secret|token|key)\s*=\s*['\"]?[^'\";\s]+['\"]?", r"\1=[REDACTED]", masked)
    return masked

