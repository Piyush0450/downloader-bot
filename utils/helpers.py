import time
from pathlib import Path
from config.settings import DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR, AUTO_DELETE_TIME
from utils.logger import logger

def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable format."""
    if not size_bytes:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def cleanup_file(path: Path) -> None:
    """Safely delete a file if it exists."""
    try:
        if path and path.exists():
            path.unlink()
            logger.info(f"Deleted file: {path}")
    except Exception as e:
        logger.error(f"Failed to delete file {path}: {e}")

def cleanup_temp_directories() -> int:
    """Scan and delete files in temp folders older than AUTO_DELETE_TIME (15 minutes)."""
    count = 0
    now = time.time()
    for directory in (DOWNLOADS_DIR, UPLOADS_DIR, CONVERTED_DIR, THUMBNAILS_DIR):
        try:
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    age = now - file_path.stat().st_mtime
                    if age > AUTO_DELETE_TIME:
                        cleanup_file(file_path)
                        count += 1
        except Exception as e:
            logger.error(f"Error cleaning directory {directory}: {e}")
    return count

def generate_temp_path(extension: str = None, dir_path: Path = CONVERTED_DIR) -> Path:
    """Helper to generate a safe temporary file path with optional extension."""
    import uuid
    filename = f"{uuid.uuid4()}"
    if extension:
        filename = f"{filename}.{extension.lstrip('.')}"
    return dir_path / filename
