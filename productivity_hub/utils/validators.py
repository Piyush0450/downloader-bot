"""
Validation and URL Domain Whitelist Helper.

Provides input validation for Telegram IDs, file size constraints, generic HTTP URLs,
and domain whitelisting for supported media downloader platforms (YouTube, Instagram,
TikTok, Twitter/X, Pinterest, Facebook, Reddit, Vimeo, SoundCloud, Spotify).
"""

import re
from typing import Optional, Tuple, Union
from urllib.parse import urlparse


# Supported media platforms & domain whitelist patterns
MEDIA_PLATFORM_DOMAINS = {
    "youtube": [r"(www\.|m\.|music\.)?youtube\.com", r"youtu\.be"],
    "instagram": [r"(www\.)?instagram\.com"],
    "tiktok": [r"(www\.|vm\.)?tiktok\.com"],
    "twitter": [r"(www\.)?twitter\.com", r"(www\.)?x\.com"],
    "pinterest": [r"(www\.)?pinterest\.com", r"pin\.it"],
    "facebook": [r"(www\.)?facebook\.com", r"fb\.watch"],
    "reddit": [r"(www\.)?reddit\.com", r"redd\.it"],
    "vimeo": [r"(www\.)?vimeo\.com"],
    "soundcloud": [r"(www\.)?soundcloud\.com"],
    "spotify": [r"open\.spotify\.com"],
    "snapchat": [r"(www\.)?snapchat\.com", r"story\.snapchat\.com"],
    "twitch": [r"(www\.)?twitch\.tv", r"clips\.twitch\.tv"],
    "dailymotion": [r"(www\.)?dailymotion\.com", r"dai\.ly"],
    "threads": [r"(www\.)?threads\.net"],
    "linkedin": [r"(www\.)?linkedin\.com"],
    "tumblr": [r"(www\.)?tumblr\.com"],
    "vk": [r"(www\.)?vk\.com"],
}


def extract_first_url(text: str) -> Optional[str]:
    """Extract the first HTTP/HTTPS URL from a string if present."""
    if not text:
        return None
    match = re.search(r"https?://[^\s<>\"]+", text)
    return match.group(0) if match else None


def validate_telegram_id(user_id: Union[int, str]) -> bool:
    """
    Validate whether a given value is a valid numeric Telegram ID.

    Args:
        user_id: Telegram user ID or chat ID.

    Returns:
        bool: True if valid positive integer, False otherwise.
    """
    try:
        val = int(user_id)
        return val > 0
    except (ValueError, TypeError):
        return False


def validate_file_size(size_bytes: int, max_mb: Optional[int] = None, max_bytes: Optional[int] = None) -> bool:
    """
    Verify if a file's size in bytes is within the allowed limit.

    Args:
        size_bytes: File size in bytes.
        max_mb: Optional maximum allowed size in Megabytes.
        max_bytes: Optional maximum allowed size in Bytes.

    Returns:
        bool: True if file size is within limits, False if exceeded or negative.
    """
    if size_bytes < 0:
        return False
    if max_bytes is not None:
        return size_bytes <= max_bytes
    if max_mb is not None:
        return size_bytes <= max_mb * 1024 * 1024

    try:
        from productivity_hub.config.settings import get_settings
        return size_bytes <= get_settings().MAX_FILE_SIZE_BYTES
    except Exception:
        return size_bytes <= 50 * 1024 * 1024


def get_oversized_file_message(limit_bytes: Optional[int] = None, actual_size_bytes: Optional[int] = None) -> str:
    """
    Construct standard user-facing error message when a file exceeds supported size.
    Aligned with user prompt requirement:
    "❌ File too large to send through this bot. The file is larger than the maximum supported size of this deployment. Please choose a smaller file or compress it and try again."
    """
    base_msg = (
        "❌ *File too large to send through this bot.*\n\n"
        "The file is larger than the maximum supported size of this deployment. "
        "Please choose a smaller file or compress it and try again."
    )
    details = []
    if actual_size_bytes is not None:
        details.append(f"• *Detected Size:* `{actual_size_bytes / (1024 * 1024):.1f} MB`")
    if limit_bytes is not None:
        details.append(f"• *Supported Deployment Limit:* `{limit_bytes / (1024 * 1024):.1f} MB`")

    if details:
        return f"{base_msg}\n\n" + "\n".join(details)
    return base_msg


def is_compressible_filename(filename_or_ext: str) -> bool:
    """
    Check if a filename or extension corresponds to a format supported by our compressor
    (Images, Video, Audio, or PDF).
    """
    if not filename_or_ext:
        return False
    ext = filename_or_ext.lower().split(".")[-1].strip().lstrip(".")
    compressible = {
        "jpg", "jpeg", "png", "webp", "bmp", "tiff",
        "pdf",
        "mp3", "wav", "flac", "m4a", "ogg", "aac", "opus",
        "mp4", "mkv", "avi", "mov", "webm",
    }
    return ext in compressible


def get_oversized_suggestion_keyboard(owner_id: int, filename: Optional[str] = None, lang: str = "en"):
    """
    Provide interactive keyboard offering file compression option if the file format is compressible.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from productivity_hub.utils.i18n import get_text

    if filename and is_compressible_filename(filename):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Open File Compressor", callback_data=f"menu:compressor:{owner_id}")],
            [InlineKeyboardButton(get_text("menu_main", lang), callback_data=f"menu:main:{owner_id}")],
        ])
    return None


def validate_url(url: str) -> bool:
    """
    Validate whether a string is a well-formed HTTP/HTTPS URL.

    Args:
        url: URL string to validate.

    Returns:
        bool: True if URL scheme is http/https and netloc is present, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def validate_media_url(url: str) -> Tuple[bool, str, str]:
    """
    Validate if a URL belongs to a supported media downloader platform and is safe.
    Supports extracting URLs from mixed text messages (e.g. YouTube app share text).

    Args:
        url: Raw URL string or text containing a URL.

    Returns:
        Tuple[bool, str, str]:
            - bool: True if valid and whitelisted.
            - str: Detected platform service ('youtube', 'instagram', etc.) or 'unknown'.
            - str: Cleaned normalized URL.
    """
    if not url or not isinstance(url, str):
        return False, "invalid_url", ""

    target_url = url.strip()
    if not validate_url(target_url):
        extracted = extract_first_url(target_url)
        if extracted and validate_url(extracted):
            target_url = extracted
        else:
            return False, "invalid_url", ""

    clean_url = target_url.strip()
    parsed = urlparse(clean_url)
    hostname = parsed.netloc.lower()

    for service_name, domain_patterns in MEDIA_PLATFORM_DOMAINS.items():
        for pattern in domain_patterns:
            if re.search(pattern, hostname):
                return True, service_name, clean_url

    return False, "unsupported_platform", clean_url


# Backward-compatible function aliases
isValidUrl = validate_url
def isValidDomain(url: str, allowed_domains: list = None) -> bool:
    is_valid, service, _ = validate_media_url(url)
    return is_valid

def is_whitelisted_domain(url: str) -> bool:
    is_valid, _, _ = validate_media_url(url)
    return is_valid

