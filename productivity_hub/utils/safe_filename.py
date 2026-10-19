"""
Safe Filename & Path Traversal Protection Utility.

Sanitizes user-supplied filenames to protect against path traversal attacks (../, ..\\),
control characters, and shell injection metacharacters. Generates collision-free, safe
storage filepaths with unique UUID identifiers.
"""

import os
import re
import uuid
from pathlib import Path
from typing import Tuple


# Regex matching dangerous characters: path separators, control chars, shell metacharacters
UNSAFE_CHARS_REGEX = re.compile(r"[^\w\.-]")


def sanitize_filename(filename: str, max_length: int = 128) -> str:
    """
    Sanitize raw filename string to prevent path traversal and shell injection.

    Args:
        filename: Raw input filename.
        max_length: Maximum allowed output filename length.

    Returns:
        str: Cleaned, safe filename.
    """
    if not filename or not isinstance(filename, str):
        return "unnamed_file"

    # 1. Normalize slashes & strip directory path components
    clean = filename.replace("\\", "/").split("/")[-1]

    # 2. Remove null bytes, control chars, path traversal sequences
    clean = clean.replace("\x00", "").replace("../", "").replace("..\\", "")

    # 3. Replace invalid/unsafe characters with underscores
    clean = UNSAFE_CHARS_REGEX.sub("_", clean)

    # 4. Collapse multiple underscores or dots
    clean = re.sub(r"_{2,}", "_", clean)
    clean = re.sub(r"\.{2,}", ".", clean)

    # 5. Strip leading/trailing dots and spaces
    clean = clean.strip(". ")

    # 6. Extract extension and enforce max_length
    if not clean:
        return "unnamed_file"

    parts = clean.rsplit(".", 1)
    if len(parts) == 2:
        base, ext = parts[0], parts[1].lower()
        if len(ext) > 10:
            ext = ext[:10]
        base = base[: max_length - len(ext) - 1]
        clean = f"{base}.{ext}" if base else f"file.{ext}"
    else:
        clean = clean[:max_length]

    return clean or "unnamed_file"


def generate_safe_filepath(directory: Path, original_filename: str, prefix: str = "") -> Tuple[Path, str]:
    """
    Generate a collision-free safe internal filepath inside a target directory using UUIDv4.

    Args:
        directory: Target storage directory Path.
        original_filename: Raw original filename from user.
        prefix: Optional prefix for filename ('upload', 'conv', etc.).

    Returns:
        Tuple[Path, str]:
            - Path: Absolute safe destination Filepath.
            - str: Sanitized original display filename.
    """
    directory.mkdir(parents=True, exist_ok=True)
    sanitized_display_name = sanitize_filename(original_filename)

    # Extract extension
    parts = sanitized_display_name.rsplit(".", 1)
    ext = f".{parts[1]}" if len(parts) == 2 else ""

    # Generate unique storage filename
    unique_id = uuid.uuid4().hex[:12]
    p_str = f"{prefix}_" if prefix else ""
    safe_disk_filename = f"{p_str}{unique_id}{ext}"
    
    target_filepath = directory / safe_disk_filename
    return target_filepath, sanitized_display_name
